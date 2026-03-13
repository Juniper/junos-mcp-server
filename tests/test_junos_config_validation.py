#!/usr/bin/env python3
"""Unit tests for device configuration validation."""

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.test_device_data import get_device
from utils.config import validate_all_devices


class ConfigValidationTests(unittest.TestCase):
    def test_valid_config(self):
        valid_config = {"router1": get_device("router1")}
        validate_all_devices(valid_config)

    def test_missing_ip(self):
        device = get_device("router1")
        device.pop("ip", None)
        config = {"router1": device}
        with self.assertRaises(ValueError):
            validate_all_devices(config)

    def test_missing_auth(self):
        device = get_device("router1")
        device.pop("auth", None)
        config = {"router1": device}
        with self.assertRaises(ValueError):
            validate_all_devices(config)

    def test_invalid_auth_type(self):
        device = get_device("router1")
        device["auth"] = {"type": "invalid_type", "password": "secret123"}
        config = {"router1": device}
        with self.assertRaises(ValueError):
            validate_all_devices(config)

    def test_ssh_key_missing_path(self):
        device = get_device("router1")
        device["auth"] = {"type": "ssh_key"}
        config = {"router1": device}
        with self.assertRaises(ValueError):
            validate_all_devices(config)

    def test_invalid_port_type(self):
        device = get_device("router1")
        device["port"] = "22"
        config = {"router1": device}
        with self.assertRaises(ValueError):
            validate_all_devices(config)

    def test_backward_compatibility_password_format(self):
        device = get_device("router1")
        config = {
            "router1": {
                "ip": device["ip"],
                "port": device["port"],
                "username": device["username"],
                "password": "secret123",
            }
        }
        validate_all_devices(config)

    def test_multiple_devices_reports_all_invalid(self):
        router1 = get_device("router1")
        router2 = get_device("router2")
        router3 = get_device("router3")

        router2.pop("ip", None)
        router3["port"] = "invalid"
        router3.pop("auth", None)
        router3["password"] = "secret"

        config = {
            "router1": router1,
            "router2": router2,
            "router3": router3,
        }

        with self.assertRaises(ValueError) as ctx:
            validate_all_devices(config)

        error_str = str(ctx.exception)
        self.assertIn("router2", error_str)
        self.assertIn("router3", error_str)


if __name__ == "__main__":
    unittest.main()
