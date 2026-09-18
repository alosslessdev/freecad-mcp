#!/usr/bin/env python3
"""Headless RPC bridge for FreeCAD — drive FreeCAD with no GUI and no display.

Serves the *same* XML-RPC interface as the ``FreeCADMCP`` GUI addon, so any
``freecad-mcp`` MCP client (Claude Desktop, Cursor, VS Code, Hermes, a custom
agent) works unchanged against a headless FreeCAD process.

Usage
-----
    freecadcmd headless_server.py --port 9875

Why this exists
---------------
The GUI addon imports ``FreeCADGui`` / ``PySide`` at module scope and dispatches
every command onto FreeCAD's Qt GUI thread.  Inside ``freecadcmd`` that import
fails::

    AttributeError: module 'FreeCADGui' has no attribute 'addCommand'

so the addon cannot run without a display (headless servers, containers, CI).
But everything that does not need a *viewport* — documents, objects, properties,
and arbitrary ``execute_code`` — only needs the plain ``FreeCAD`` API, which is
fully available headless.  This module wires the identical RPC surface straight
to that API.

What is available
-----------------
* ``ping`` ``get_rpc_status`` ``list_documents``
* ``create_document`` ``reload_document``
* ``create_object`` ``edit_object`` ``delete_object``
* ``get_objects`` ``get_object``
* ``execute_code`` ``execute_code_async`` ``get_async_status``
* ``get_parts_list``

What is *not* (needs a viewport, returns a clear headless response)
------------------------------------------------------------------
* ``get_active_screenshot`` -> ``None``
* ``run_fem_analysis``      -> ``{"success": False, "error": ...}``
  (FEM solving needs the GUI thread + solver dialogs; use ``execute_code`` with
  the ``Fem`` workbench directly, or run the GUI bridge when you need it.)
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import traceback
import uuid
import xmlrpc.server

import FreeCAD

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9875

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# These modules are GUI-free on purpose — they only touch the plain FreeCAD API.
from rpc_server.serialize import serialize_object                     # noqa: E402
from rpc_server.property_mapper import Object                         # noqa: E402
from rpc_server.object_factory import create_object_gui, edit_object_gui  # noqa: E402


def _make_namespace() -> dict:
    """Persistent exec namespace, mirroring the GUI addon's ``App``/``Gui`` aliases."""
    ns: dict = {"__name__": "__main__", "FreeCAD": FreeCAD, "App": FreeCAD}
    for mod in ("Part", "Mesh", "MeshPart", "Draft", "Sketcher", "Spreadsheet"):
        try:
            ns[mod] = __import__(mod)
        except Exception:
            pass
    return ns


_EXEC_NAMESPACE = _make_namespace()


class HeadlessRPC:
    """XML-RPC surface equivalent to the GUI addon, minus the GUI thread."""

    # ---- health -----------------------------------------------------------
    def ping(self) -> bool:
        return True

    def get_rpc_status(self) -> dict:
        return {
            "success": True,
            "rpc_server": "running",
            "mode": "headless",
            "gui_dispatch": "disabled (no GUI in freecadcmd)",
            "async_jobs_running": [],
        }

    # ---- documents --------------------------------------------------------
    def list_documents(self) -> list:
        return list(FreeCAD.listDocuments().keys())

    def create_document(self, name: str = "New_Document") -> dict:
        try:
            doc = FreeCAD.newDocument(name)
            doc.recompute()
            # Report the ACTUAL name: FreeCAD sanitises ("My Doc" -> "My_Doc")
            # and de-duplicates ("Doc" -> "Doc001").
            return {"success": True, "document_name": doc.Name}
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    def reload_document(self, doc_name: str) -> dict:
        """Close and re-open a document from disk (pick up external edits)."""
        try:
            doc = FreeCAD.getDocument(doc_name)
        except Exception:
            return {"success": False, "error": f"document not found: {doc_name}"}
        path = doc.FileName
        if not path or not os.path.exists(path):
            return {"success": False, "error": f"document has no file on disk: {doc_name}"}
        try:
            FreeCAD.closeDocument(doc.Name)
            new_doc = FreeCAD.openDocument(path)
            return {"success": True, "document_name": new_doc.Name}
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    # ---- objects ----------------------------------------------------------
    def get_objects(self, doc_name: str) -> list:
        try:
            doc = FreeCAD.getDocument(doc_name)
        except Exception:
            return []
        if doc is None:
            return []
        return [serialize_object(o) for o in doc.Objects]

    def get_object(self, doc_name: str, obj_name: str):
        try:
            doc = FreeCAD.getDocument(doc_name)
        except Exception:
            return None
        if doc is None:
            return None
        obj = doc.getObject(obj_name)
        return serialize_object(obj) if obj else None

    def create_object(self, doc_name: str, obj_data: dict) -> dict:
        try:
            obj = Object(
                name=obj_data.get("Name", "New_Object"),
                type=obj_data["Type"],
                analysis=obj_data.get("Analysis"),
                properties=obj_data.get("Properties", {}),
            )
        except KeyError as e:
            return {"success": False, "error": f"missing required key: {e}"}
        res = create_object_gui(doc_name, obj)
        if isinstance(res, dict):
            return res
        return {"success": False, "error": str(res)}

    def edit_object(self, doc_name: str, obj_name: str, properties: dict) -> dict:
        obj = Object(name=obj_name, properties=properties.get("Properties", {}))
        res = edit_object_gui(doc_name, obj)
        if res is True:
            return {"success": True, "object_name": obj.name}
        if isinstance(res, dict):
            return res
        return {"success": False, "error": str(res)}

    def delete_object(self, doc_name: str, obj_name: str) -> dict:
        try:
            doc = FreeCAD.getDocument(doc_name)
            if doc.getObject(obj_name) is None:
                return {"success": False, "error": f"object not found: {obj_name}"}
            doc.removeObject(obj_name)
            doc.recompute()
            return {"success": True, "object_name": obj_name}
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    # ---- code execution ---------------------------------------------------
    def execute_code(self, code: str) -> dict:
        """Run Python on the main thread (no GUI thread to hand off to)."""
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(code, _EXEC_NAMESPACE)
        except Exception as e:
            tb = traceback.format_exc(limit=4)
            return {"success": False, "error": f"{type(e).__name__}: {e}\n{tb}"}
        return {
            "success": True,
            "message": "Python code executed successfully.\nOutput: " + buf.getvalue(),
        }

    def execute_code_async(self, code: str) -> dict:
        """Headless runs are already off the GUI thread — execute inline.

        Returns the same ``job_id`` shape so clients written against the GUI
        addon keep working; the work has already finished when this returns.
        """
        job_id = uuid.uuid4().hex
        res = self.execute_code(code)
        if res.get("success"):
            return {"success": True, "job_id": job_id, "note": "completed inline (headless)"}
        return {"success": False, "job_id": job_id, "error": res.get("error", "failed")}

    def get_async_status(self, job_id: str = "") -> dict:
        return {
            "success": True,
            "jobs": [],
            "note": "headless mode executes inline; no background jobs are queued",
        }

    # ---- viewport-only (not available headless) ---------------------------
    def get_active_screenshot(self, view_name: str = "Isometric", width=None,
                              height=None, focus_object=None):
        FreeCAD.Console.PrintWarning(
            "MCP RPC (headless): no viewport, get_active_screenshot returns None\n"
        )
        return None

    def get_parts_list(self):
        try:
            from rpc_server.parts_library import get_parts_list
            return get_parts_list()
        except Exception:
            return []

    def run_fem_analysis(self, doc_name: str, analysis_name: str, timeout: int = 600) -> dict:
        return {
            "success": False,
            "error": "run_fem_analysis needs the GUI solver dispatch; "
                     "not available in headless mode. Drive the Fem workbench "
                     "directly via execute_code, or use the GUI bridge.",
        }


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          allow_remote: bool = False) -> None:
    """Start the XML-RPC server and block. Called by ``main``."""
    if allow_remote and host == DEFAULT_HOST:
        host = "0.0.0.0"
    server = xmlrpc.server.SimpleXMLRPCServer(
        (host, port), allow_none=True, logRequests=False
    )
    server.register_instance(HeadlessRPC())
    server.register_introspection_functions()
    print(f"FreeCAD headless MCP bridge listening on {host}:{port}", flush=True)
    print("  mode: freecadcmd (no GUI, no Qt, no display)", flush=True)
    print(f"  FreeCAD {FreeCAD.Version()[0]}.{FreeCAD.Version()[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    finally:
        server.server_close()


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Headless XML-RPC bridge for FreeCAD (run with freecadcmd)."
    )
    parser.add_argument("--host", default=os.environ.get("FC_MCP_HOST", DEFAULT_HOST),
                        help=f"bind address (default {DEFAULT_HOST}, env FC_MCP_HOST)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("FC_MCP_PORT", DEFAULT_PORT)),
                        help=f"port, must match the MCP client (default {DEFAULT_PORT}, env FC_MCP_PORT)")
    parser.add_argument("--open", action="append", default=[], metavar="FILE",
                        help="open a .FCStd at startup (repeatable; env FC_MCP_OPEN, ':'-separated)")
    parser.add_argument("--allow-remote", action="store_true",
                        help="bind 0.0.0.0 instead of localhost (no auth — use with care)")
    # parse_known_args: when run under `freecadcmd script.py` the host's argv
    # still contains the script path and its own flags, which argparse would
    # otherwise reject as unrecognized.
    args, _unknown = parser.parse_known_args(argv)

    for path in args.open:
        try:
            doc = FreeCAD.openDocument(path)
            print(f"opened {path} as '{doc.Name}'", flush=True)
        except Exception as e:
            print(f"could not open {path}: {e}", flush=True)

    serve(args.host, args.port, args.allow_remote)
    return 0


def _is_entrypoint() -> bool:
    """True when this file is the script FreeCAD/python was asked to run.

    ``freecadcmd script.py`` executes the file as a *module* named after the
    file (``__name__ == "headless_server"``), never ``"__main__"`` — so the
    usual guard alone would never start the server.
    """
    if __name__ == "__main__":
        return True
    return __name__ == os.path.splitext(os.path.basename(__file__))[0]


if _is_entrypoint():
    sys.exit(main())
