# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Model Context Protocol (MCP) server for Juniper Junos network devices. It enables LLMs to interact with Juniper network equipment through a standardized interface using the FastMCP framework and Juniper's PyEZ library.

## Key Commands

### Running the Server

```bash
# Install dependencies
pip install -r requirements.txt

# Run with stdio transport (for Claude Desktop)
python3.11 jmcp.py -f devices.json -t stdio

# Run with streamable-http transport (for VSCode)
python3.11 jmcp.py -f devices.json -t streamable-http -H 127.0.0.1 -p 30030

# Docker build
docker build -t junos-mcp-server:latest .

# Docker run (stdio)
docker run --rm -it -v /path/to/devices.json:/app/config/devices.json junos-mcp-server:latest

# Docker run (streamable-http)
docker run --rm -it -v /path/to/devices.json:/app/config/devices.json -p 30030:30030 junos-mcp-server:latest python jmcp.py -f /app/config/devices.json -t streamable-http -H 0.0.0.0
```

### Testing and Development

- Run the unit tests with `make test` (or `python -m unittest discover -s tests -v`)
- Code style is enforced with Black (configured in `pyproject.toml`); check with `black --check .` and auto-format with `black .`. CI runs Black and the unit tests (`.github/workflows/ci.yml`).
- Live testing against devices requires a valid Junos device configuration in JSON format

## Architecture

The server implements 10 MCP tools in `jmcp.py`:

1. **execute_junos_command** - Execute arbitrary CLI commands on routers
2. **execute_junos_command_batch** - Execute the same command on multiple routers in parallel
3. **execute_junos_pfe_command** - Execute a PFE (packet forwarding engine) command on an FPC
4. **get_junos_config** - Retrieve device configuration (uses `show configuration | display inheritance no-comments`)
5. **junos_config_diff** - Compare configuration versions (rollback comparison)
6. **render_and_apply_j2_template** - Render a Jinja2 template and load/commit it
7. **gather_device_facts** - Collect device information using PyEZ facts
8. **get_router_list** - List available routers from the configuration
9. **load_and_commit_config** - Apply configuration changes (supports set/text/xml formats); always runs a commit check first, with optional `dry_run` and `confirm_timeout_mins` (commit confirmed)
10. **confirm_commit** - Confirm a pending commit confirmed so the device does not roll back

Device inventory is defined solely by the JSON mapping file loaded and validated at startup. The former `add_device` and `reload_devices` runtime device-management tools were removed for security reasons (see `.commit-logs.txt`): they let any MCP client register attacker-controlled hosts, probe arbitrary IP:port pairs, and swap the device map from arbitrary server file paths.

### Key Implementation Details

- Device-accessing handlers borrow from the thread-safe `ConnectionPool` (`connection_pool.get_connection`) and dispatch PyEZ's blocking calls off the async event loop with `anyio.to_thread.run_sync` (e.g. `execute_junos_command`/`_batch`, `get_junos_config`, `gather_device_facts`, `load_and_commit_config`, `render_and_apply_j2_template`).
- Idle pooled connections are closed after `JMCP_POOL_IDLE_TIMEOUT` seconds (default 300)
- Connection parameters are prepared by `prepare_connection_params` which handles both password and SSH key authentication
- Default timeout is 360 seconds for long-running operations
- The server uses FastMCP for the MCP protocol implementation
- Device configurations are loaded from a JSON file at startup

### Device Configuration Format

The device configuration file must follow this structure:

```json
{
    "router-name": {
        "ip": "ip-address",
        "port": 22,
        "username": "user",
        "auth": {
            "type": "password|ssh_key",
            "password": "pwd",  // if type is password
            "private_key_path": "/path/to/key.pem"  // if type is ssh_key
        }
    }
}
```

## Security Considerations

- **CRITICAL**: Configuration changes are automatically committed to devices when using `load_and_commit_config` (after a commit check). Use `confirm_timeout_mins` for an automatic rollback safety net, then `confirm_commit`
- SSH key authentication is strongly recommended over passwords
- The server exposes network infrastructure to LLM access - ensure corporate policies allow this
- Always review LLM-generated configurations before allowing execution

## Common Development Tasks

When modifying the server:

1. **Adding new tools**: Register the handler in the `TOOL_HANDLERS` dict and declare its schema in `list_tools()`. A single `@app.call_tool()` dispatcher routes calls by name — there are no per-tool `@mcp.tool()` decorators, so a handler that isn't in `TOOL_HANDLERS` is never invoked.
2. **Error handling**: Use try/except blocks around device operations to catch ConnectError and general exceptions
3. **Authentication**: Any changes must support both password and SSH key authentication types
4. **Logging**: Use the global `log` logger for debugging (`logging.getLogger('jmcp-server')`)

## Integration Points

- **Claude Desktop**: Use stdio transport with absolute paths in configuration
- **VSCode with GitHub Copilot**: Use streamable-http transport pointing to server URL
- **Docker**: Mount device configuration and any SSH key files as volumes