#!/usr/bin/env python3
"""End-to-end smoke test: MCP client -> freecad-mcp server -> HEADLESS FreeCAD.

Run with the headless bridge already listening on 9875:

    freecadcmd headless_server.py &
    python examples/headless_smoke.py
"""
import asyncio, os, sys, json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HOME = os.path.expanduser("~")


async def call(session, name, args):
    r = await session.call_tool(name, arguments=args)
    text, img = [], 0
    for c in r.content:
        t = getattr(c, "type", None)
        if t == "text":
            text.append(c.text)
        elif t == "image":
            img += 1
    return "\n".join(text), img


async def main():
    server = os.environ.get("FREECAD_MCP_BIN", os.path.join(HOME, "freecad-mcp-env/bin/freecad-mcp"))
    params = StdioServerParameters(command=server, args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            print(f"1. MCP connected, {len(tools)} tools")

            txt, _ = await call(session, "get_rpc_status", {})
            print(f"2. rpc_status: {txt[:160]}")

            txt, _ = await call(session, "create_document", {"name": "HeadlessTest"})
            print(f"3. create_document: {txt[:120]}")

            code = (
                "import FreeCAD, Part\n"
                "doc = FreeCAD.getDocument('HeadlessTest')\n"
                "box = doc.addObject('Part::Box', 'Box')\n"
                "box.Length, box.Width, box.Height = 2000, 1500, 500\n"
                "cyl = doc.addObject('Part::Cylinder', 'Stack')\n"
                "cyl.Radius, cyl.Height = 400, 3000\n"
                "cyl.Placement.Base = FreeCAD.Vector(1000, 750, 0)\n"
                "doc.recompute()\n"
                "print('OBJECTS', [o.Name for o in doc.Objects])\n"
            )
            txt, _ = await call(session, "execute_code", {"code": code})
            print(f"4. execute_code: {txt[:220]}")

            txt, _ = await call(session, "get_objects", {"doc_name": "HeadlessTest", "include_screenshot": False})
            objs = json.loads(txt)
            print(f"5. get_objects -> {[o.get('Name') for o in objs]}")

            txt, _ = await call(session, "list_documents", {})
            print(f"6. list_documents: {txt[:120]}")

            txt, nimg = await call(session, "get_view", {"view_name": "Isometric"})
            print(f"7. get_view (headless, expected graceful): images={nimg} text={txt[:90]!r}")

            print("\nHEADLESS PIPELINE OK")


asyncio.run(main())
