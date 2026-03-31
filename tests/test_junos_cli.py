#!/usr/bin/env python3
"""Unit tests for CLI helper functions used in Junos command testing."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

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


class JunosCliHelperTests(unittest.TestCase):
    def setUp(self):
        self._original_devices = jmcp.devices.copy()

    def tearDown(self):
        jmcp.devices = self._original_devices

    def test_load_devices_success(self):
        devices = {"router1": get_device("router1")}
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "devices.json"
            file_path.write_text(json.dumps(devices), encoding="utf-8")

            self.assertTrue(load_devices(str(file_path)))
            self.assertEqual(jmcp.devices, devices)

    def test_load_devices_missing_file(self):
        self.assertFalse(load_devices("/tmp/does-not-exist-devices.json"))

    def test_load_devices_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "devices.json"
            file_path.write_text("{ invalid-json", encoding="utf-8")

            self.assertFalse(load_devices(str(file_path)))


if __name__ == "__main__":
    unittest.main()
