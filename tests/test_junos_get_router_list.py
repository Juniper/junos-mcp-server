#!/usr/bin/env python3
"""Unit tests for handle_get_router_list() and data redaction."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import jmcp
from tests.test_device_data import get_device


class GetRouterListTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._original_devices = jmcp.devices.copy()
        self.context = MagicMock()

    def tearDown(self):
        jmcp.devices = self._original_devices

    async def test_empty_devices(self):
        jmcp.devices = {}
        result = await jmcp.handle_get_router_list({}, self.context)
        self.assertEqual(len(result), 1)
        self.assertEqual(json.loads(result[0].text), {})

    async def test_password_and_ssh_key_redaction(self):
        jmcp.devices = {
            "router1": get_device("router1"),
            "router2": get_device("router2"),
        }

        result = await jmcp.handle_get_router_list({}, self.context)
        output = json.loads(result[0].text)

        self.assertEqual(output["router1"]["auth"]["type"], "password")
        self.assertNotIn("password", output["router1"]["auth"])

        self.assertEqual(output["router2"]["auth"]["type"], "ssh_key")
        self.assertNotIn("private_key_path", output["router2"]["auth"])

    async def test_ssh_config_removed_and_custom_fields_kept(self):
        router = get_device("router3")
        router["ssh_config"] = "/home/user/.ssh/config_jumphost"
        router["role"] = "pe"
        router["group"] = "ISP"
        jmcp.devices = {"router3": router}

        result = await jmcp.handle_get_router_list({}, self.context)
        output = json.loads(result[0].text)
        router = output["router3"]

        self.assertNotIn("ssh_config", router)
        self.assertEqual(router["role"], "pe")
        self.assertEqual(router["group"], "ISP")
        self.assertNotIn("password", router["auth"])

    async def test_json_pretty_and_source_immutability(self):
        jmcp.devices = {"router1": get_device("router1")}
        before = json.dumps(jmcp.devices, sort_keys=True)

        result = await jmcp.handle_get_router_list({}, self.context)
        output_text = result[0].text

        json.loads(output_text)
        self.assertIn("\n", output_text)
        self.assertIn("  ", output_text)

        after = json.dumps(jmcp.devices, sort_keys=True)
        self.assertEqual(before, after)
        self.assertIn("password", jmcp.devices["router1"]["auth"])


if __name__ == "__main__":
    unittest.main()
