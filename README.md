[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/neka-nat-freecad-mcp-badge.png)](https://mseep.ai/app/neka-nat-freecad-mcp)

# FreeCAD MCP

Control FreeCAD from Claude Desktop and other MCP clients. Create and edit models,
run Python scripts, inspect documents, and run FEM analyses.

## Demo

Design a flange:

![Designing a flange in FreeCAD](./assets/freecad_mcp4.gif)

See [more demos and examples](docs/examples.md) for a toy car, modelling from a
2D drawing, and agent integrations.

## Quick start

You need FreeCAD and [uv / uvx](https://docs.astral.sh/uv/guides/tools/).
FreeCAD MCP has two components: an addon running inside FreeCAD and an MCP server
launched by your client.

### 1. Install and start the FreeCAD addon

```bash
git clone https://github.com/neka-nat/freecad-mcp.git
cd freecad-mcp
```

Copy `addon/FreeCADMCP` into your [FreeCAD addon directory](docs/installation.md#addon-directory),
then restart FreeCAD. Select the **MCP Addon** workbench and click
**Start RPC Server** in the **FreeCAD MCP** toolbar.

See the [installation guide](docs/installation.md) for platform-specific commands
and screenshots.

### 2. Connect Claude Desktop

Add the following entry to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "freecad": {
      "command": "uvx",
      "args": ["freecad-mcp"]
    }
  }
}
```

Restart Claude Desktop to load the configuration, keep FreeCAD open with its RPC
server running, and ask Claude to create a model. Connections use `localhost` by
default.

## Headless mode (no GUI, no display)

FreeCAD can run the whole bridge headless — for servers, containers and CI —
where there is no X/Wayland session to host the addon's workbench:

```bash
freecadcmd /path/to/addon/FreeCADMCP/headless_server.py
# -> FreeCAD headless MCP bridge listening on localhost:9875
```

Point any MCP client at `freecad-mcp` exactly as usual; it cannot tell whether
the far end is a GUI or a headless process. Modelling, `execute_code`, object
CRUD and volume/deterministic geometry work unchanged. Screenshots and
`run_fem_analysis` need a viewport and report that they are unavailable instead
of erroring.

See [headless mode](docs/headless.md) for configuration, Docker usage and
limitations.

## Documentation

| Guide | Contents |
| --- | --- |
| [Installation](docs/installation.md) | Addon directories, setup screenshots, running from source |
| [Configuration](docs/configuration.md) | Auto-start, text feedback, remote connections |
| [Tools](docs/tools.md) | Available tools, screenshots, FEM analysis |
| [Code execution](docs/execution.md) | GUI execution, background jobs, headless scripts, timeout troubleshooting |
| [Headless mode](docs/headless.md) | Run the bridge with no GUI/display: flags, Docker, limitations |
| [Demos and examples](docs/examples.md) | Design demos, FEM example, ADK and LangChain integrations |

## Contributors

<a href="https://github.com/neka-nat/freecad-mcp/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=neka-nat/freecad-mcp" />
</a>

Made with [contrib.rocks](https://contrib.rocks).
