# Headless mode

Run FreeCAD — and the whole freecad-mcp bridge — with **no GUI, no Qt and no
display**. Designed for servers, containers, and CI, where there is no X/Wayland
session to put a window on.

```bash
freecadcmd /path/to/addon/FreeCADMCP/headless_server.py
# -> FreeCAD headless MCP bridge listening on localhost:9875
```

Then point any MCP client at `freecad-mcp` exactly as usual — it does not know
or care whether the far end is a GUI or a headless process.

## Why the GUI addon cannot do this

The `FreeCADMCP` addon is a *workbench*: it imports `FreeCADGui` / `PySide` at
module scope, registers toolbar commands with `FreeCADGui.addCommand`, and
dispatches every RPC command onto FreeCAD's **Qt GUI thread**. Inside
`freecadcmd` that fails immediately:

```
AttributeError: module 'FreeCADGui' has no attribute 'addCommand'
```

Nothing about *modelling* needs a viewport, though. Documents, objects,
properties and arbitrary Python only need the plain `FreeCAD` API, which is
fully available headless. `headless_server.py` exposes the **same XML-RPC
interface** and wires it straight to that API — no Qt, no thread hop.

## What works

| RPC method | Headless |
| --- | --- |
| `ping`, `get_rpc_status` | ✅ reports `"mode": "headless"` |
| `list_documents`, `create_document`, `reload_document` | ✅ |
| `create_object`, `edit_object`, `delete_object` | ✅ (non-FEM types) |
| `get_objects`, `get_object` | ✅ |
| `execute_code`, `execute_code_async`, `get_async_status` | ✅ runs inline |
| `get_parts_list` | ✅ |
| `get_active_screenshot` | ⛔ returns `None` (no viewport) |
| `run_fem_analysis` | ⛔ GUI solver dispatch only |

MCP tools that would return a screenshot just report that the view type does not
support one, so clients degrade gracefully instead of erroring.

## Configuration

| Flag | Env | Default | Meaning |
| --- | --- | --- | --- |
| `--host` | `FC_MCP_HOST` | `localhost` | bind address |
| `--port` | `FC_MCP_PORT` | `9875` | must match the MCP client |
| `--open FILE` | `FC_MCP_OPEN` | – | open a `.FCStd` at startup (repeatable) |
| `--allow-remote` | – | off | bind `0.0.0.0` instead of localhost |

> `freecadcmd` executes a script file as a *module* (not `__main__`) and leaves
> its own arguments in `sys.argv`. `headless_server.py` handles both, so
> `freecadcmd headless_server.py` works with no wrapper.

> ⚠️ The bridge has **no authentication** — it is XML-RPC. Keep the default
> `localhost` bind unless you genuinely need remote access, and if you do, put it
> behind something that authenticates.

## Example: Docker

```dockerfile
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        freecad-python3 python3-pip && rm -rf /var/lib/apt/lists/*
COPY addon/FreeCADMCP /opt/FreeCADMCP
EXPOSE 9875
CMD ["freecadcmd", "/opt/FreeCADMCP/headless_server.py", "--allow-remote"]
```

## Verifying

With the bridge running:

```bash
python examples/headless_smoke.py
```

It creates a document, builds a `Part::Box` and a `Part::Cylinder` through
`execute_code`, reads them back with `get_objects`, and confirms a screenshot
request degrades gracefully.

## Limitations

* **One request at a time.** The server is single-threaded on purpose: FreeCAD's
  document/scenegraph APIs are not thread-safe, so commands are serialised. A
  long `execute_code` blocks `ping` until it finishes — same as the GUI's 90 s
  budget, but there is no queue-vs-execute split.
* **No viewport** — no screenshots, no `ViewObject` (colour/visibility) changes.
  Anything that needs `FreeCADGui` will not work; use `execute_code` with the
  plain `FreeCAD` API instead.
* **No FEM solving** via `run_fem_analysis` (GUI solver dispatch). The `Fem`
  workbench itself is importable, so bespoke solving can be scripted through
  `execute_code`.
