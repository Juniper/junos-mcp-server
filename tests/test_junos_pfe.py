#!/usr/bin/env python3
"""Unit tests for PFE helper functions used in Junos PFE command testing."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import jmcp
from tests.test_device_data import get_device


def load_devices(devices_file: str) -> bool:
    """Load devices configuration from JSON file."""
    try:
        with open(devices_file, "r", encoding="utf-8") as file_handle:
            jmcp.devices = json.load(file_handle)
            return True
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False


class JunosPfeHelperTests(unittest.TestCase):
    def setUp(self):
        self._original_devices = jmcp.devices.copy()

    def tearDown(self):
        jmcp.devices = self._original_devices

    @patch("jmcp.Device")
    def test_run_junos_pfe_command_success(self, mock_device_class):
        # Setup mock device and rpc response
        mock_device = MagicMock()
        mock_rpc = MagicMock()
        mock_rpc.request_pfe_execute.return_value.text = "PFE command output"
        mock_device.__enter__.return_value = mock_device
        mock_device.rpc = mock_rpc
        mock_device_class.return_value = mock_device

        devices = {"router1": get_device("router1")}
        jmcp.devices = devices

        result = jmcp._run_junos_pfe_command(
            "router1", "fpc0", "show pfe statistics", timeout=10
        )
        self.assertIsInstance(result, dict)
        self.assertIn("fpc0", result)
        self.assertEqual(result["fpc0"], "PFE command output")

    @patch("jmcp.Device")
    def test_run_junos_pfe_command_connect_error(self, mock_device_class):
        # Create a mock device with a hostname attribute
        mock_dev = MagicMock()
        mock_dev.hostname = "router1"
        mock_device_class.side_effect = jmcp.ConnectError(mock_dev)
        devices = {"router1": get_device("router1")}
        jmcp.devices = devices
        result = jmcp._run_junos_pfe_command(
            "router1", "fpc0", "show version", timeout=10
        )
        self.assertIsInstance(result, str)
        self.assertIn("Connection error", result)

    @patch("jmcp.Device")
    def test_run_junos_pfe_command_value_error(self, mock_device_class):
        with patch(
            "jmcp.prepare_connection_params", side_effect=ValueError("Invalid params")
        ):
            devices = {"router1": get_device("router1")}
            jmcp.devices = devices
            result = jmcp._run_junos_pfe_command(
                "router1", "fpc0", "show version", timeout=10
            )
            self.assertIsInstance(result, str)
            self.assertIn("Error:", result)

    @patch("jmcp.Device")
    def test_run_junos_pfe_command_generic_exception(self, mock_device_class):
        mock_device = MagicMock()
        mock_device.__enter__.side_effect = Exception("Generic failure")
        mock_device_class.return_value = mock_device
        devices = {"router1": get_device("router1")}
        jmcp.devices = devices
        result = jmcp._run_junos_pfe_command(
            "router1", "fpc0", "show version", timeout=10
        )
        self.assertIsInstance(result, str)
        self.assertIn("An error occurred", result)


if __name__ == "__main__":
    unittest.main()
