#!/usr/bin/env python3
"""Unit tests for the tool registry and the advertised tool list.

Guards two invariants:
- TOOL_HANDLERS and list_tools() advertise exactly the same tool names
  (a handler without a schema is unreachable, and a schema without a
  handler returns "Unknown tool").
- The dynamic device-management tools (add_device, reload_devices) stay
  removed; devices are managed only via the JSON mapping file at startup.
"""

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import mcp.types as types

import jmcp

EXPECTED_TOOLS = {
    "execute_junos_command",
    "execute_junos_command_batch",
    "execute_junos_pfe_command",
    "get_junos_config",
    "junos_config_diff",
    "render_and_apply_j2_template",
    "gather_device_facts",
    "get_router_list",
    "load_and_commit_config",
    "confirm_commit",
}

REMOVED_TOOLS = {"add_device", "reload_devices"}


async def list_advertised_tools() -> list[types.Tool]:
    """Invoke the registered tools/list handler on a fresh server."""
    app = jmcp.create_mcp_server()
    handler = app.request_handlers[types.ListToolsRequest]
    result = await handler(types.ListToolsRequest(method="tools/list"))
    return result.root.tools


class ToolRegistryTests(unittest.IsolatedAsyncioTestCase):
    def test_tool_handlers_match_expected(self):
        self.assertEqual(set(jmcp.TOOL_HANDLERS), EXPECTED_TOOLS)

    async def test_list_tools_matches_registry(self):
        advertised = {tool.name for tool in await list_advertised_tools()}
        self.assertEqual(advertised, set(jmcp.TOOL_HANDLERS))

    async def test_device_management_tools_removed(self):
        advertised = {tool.name for tool in await list_advertised_tools()}
        self.assertFalse(REMOVED_TOOLS & advertised)
        self.assertFalse(REMOVED_TOOLS & set(jmcp.TOOL_HANDLERS))
        for name in REMOVED_TOOLS:
            self.assertFalse(hasattr(jmcp, f"handle_{name}"))

    async def test_unknown_tool_call_returns_error_text(self):
        app = jmcp.create_mcp_server()
        handler = app.request_handlers[types.CallToolRequest]
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="add_device", arguments={}),
        )
        result = await handler(request)
        content = result.root.content
        self.assertEqual(len(content), 1)
        self.assertIn("Unknown tool: add_device", content[0].text)


if __name__ == "__main__":
    unittest.main()
