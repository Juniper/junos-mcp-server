#!/usr/bin/env python3
"""
Unit tests for handle_get_router_list() function
Tests JSON output structure and sensitive data filtering
"""
import json
import sys
import asyncio
from unittest.mock import MagicMock

# Import the function and module to test
import jmcp


def create_mock_context():
    """Create a mock Context object for testing"""
    mock_context = MagicMock()
    return mock_context


async def test_empty_devices():
    """Test with no devices configured"""
    print("\n=== Testing Empty Devices List ===")

    # Save original devices
    original_devices = jmcp.devices.copy()

    try:
        jmcp.devices = {}

        context = create_mock_context()
        result = await jmcp.handle_get_router_list({}, context)

        # Verify result structure
        if len(result) != 1:
            print("❌ Expected 1 ContentBlock")
            return False

        # Parse the JSON output
        output_text = result[0].text
        router_info = json.loads(output_text)

        if router_info != {}:
            print(f"❌ Expected empty dict, got: {router_info}")
            return False

        print("✅ Empty devices list handled correctly")
        return True

    finally:
        # Restore original devices
        jmcp.devices = original_devices


async def test_single_device_password_auth():
    """Test single device with password authentication"""
    print("\n=== Testing Single Device with Password Auth ===")

    original_devices = jmcp.devices.copy()

    try:
        jmcp.devices = {
            "router-1": {
                "ip": "192.168.1.1",
                "port": 22,
                "username": "admin",
                "auth": {
                    "type": "password",
                    "password": "secret123"
                }
            }
        }

        context = create_mock_context()
        result = await jmcp.handle_get_router_list({}, context)

        output_text = result[0].text
        router_info = json.loads(output_text)

        # Verify router exists
        if "router-1" not in router_info:
            print("❌ Router not found in output")
            return False

        device = router_info["router-1"]

        # Verify included fields
        if device.get("ip") != "192.168.1.1":
            print(f"❌ Expected ip=192.168.1.1, got: {device.get('ip')}")
            return False

        if device.get("port") != 22:
            print(f"❌ Expected port=22, got: {device.get('port')}")
            return False

        if device.get("username") != "admin":
            print(f"❌ Expected username=admin, got: {device.get('username')}")
            return False

        # Verify auth type is included
        if device.get("auth", {}).get("type") != "password":
            print(f"❌ Expected auth.type=password, got: {device.get('auth', {}).get('type')}")
            return False

        # Verify password is EXCLUDED
        if "password" in device.get("auth", {}):
            print("❌ Password should be excluded from output")
            return False

        print("✅ Password auth device handled correctly")
        return True

    finally:
        jmcp.devices = original_devices


async def test_single_device_ssh_key_auth():
    """Test single device with SSH key authentication"""
    print("\n=== Testing Single Device with SSH Key Auth ===")

    original_devices = jmcp.devices.copy()

    try:
        jmcp.devices = {
            "router-2": {
                "ip": "192.168.1.2",
                "port": 22,
                "username": "admin",
                "auth": {
                    "type": "ssh_key",
                    "private_key_path": "/path/to/key.pem"
                }
            }
        }

        context = create_mock_context()
        result = await jmcp.handle_get_router_list({}, context)

        output_text = result[0].text
        router_info = json.loads(output_text)

        device = router_info["router-2"]

        # Verify auth type is included
        if device.get("auth", {}).get("type") != "ssh_key":
            print(f"❌ Expected auth.type=ssh_key, got: {device.get('auth', {}).get('type')}")
            return False

        # Verify private_key_path is EXCLUDED
        if "private_key_path" in device.get("auth", {}):
            print("❌ private_key_path should be excluded from output")
            return False

        print("✅ SSH key auth device handled correctly")
        return True

    finally:
        jmcp.devices = original_devices


async def test_device_with_ssh_config():
    """Test device with ssh_config field is excluded"""
    print("\n=== Testing Device with ssh_config Field ===")

    original_devices = jmcp.devices.copy()

    try:
        jmcp.devices = {
            "router-3": {
                "ip": "192.168.1.3",
                "port": 22,
                "username": "admin",
                "ssh_config": "/home/user/.ssh/config_jumphost",
                "auth": {
                    "type": "password",
                    "password": "secret123"
                }
            }
        }

        context = create_mock_context()
        result = await jmcp.handle_get_router_list({}, context)

        output_text = result[0].text
        router_info = json.loads(output_text)

        device = router_info["router-3"]

        # Verify ssh_config is EXCLUDED
        if "ssh_config" in device:
            print("❌ ssh_config should be excluded from output")
            return False

        # Verify other fields are included
        if device.get("ip") != "192.168.1.3":
            print("❌ IP should be included")
            return False

        print("✅ ssh_config field correctly excluded")
        return True

    finally:
        jmcp.devices = original_devices


async def test_device_with_custom_fields():
    """Test device with custom user-defined fields are included"""
    print("\n=== Testing Device with Custom Fields ===")

    original_devices = jmcp.devices.copy()

    try:
        jmcp.devices = {
            "router-4": {
                "ip": "192.168.1.4",
                "port": 22,
                "username": "admin",
                "role": "pe",
                "group": "ISP",
                "location": "datacenter-1",
                "tags": ["production", "core"],
                "auth": {
                    "type": "password",
                    "password": "secret123"
                }
            }
        }

        context = create_mock_context()
        result = await jmcp.handle_get_router_list({}, context)

        output_text = result[0].text
        router_info = json.loads(output_text)

        device = router_info["router-4"]

        # Verify custom fields are INCLUDED
        if device.get("role") != "pe":
            print(f"❌ Custom field 'role' should be included, got: {device.get('role')}")
            return False

        if device.get("group") != "ISP":
            print(f"❌ Custom field 'group' should be included, got: {device.get('group')}")
            return False

        if device.get("location") != "datacenter-1":
            print(f"❌ Custom field 'location' should be included, got: {device.get('location')}")
            return False

        if device.get("tags") != ["production", "core"]:
            print(f"❌ Custom field 'tags' should be included, got: {device.get('tags')}")
            return False

        # Verify password is still excluded
        if "password" in device.get("auth", {}):
            print("❌ Password should still be excluded")
            return False

        print("✅ Custom fields correctly included")
        return True

    finally:
        jmcp.devices = original_devices


async def test_multiple_devices():
    """Test multiple devices with mixed configurations"""
    print("\n=== Testing Multiple Devices ===")

    original_devices = jmcp.devices.copy()

    try:
        jmcp.devices = {
            "router-1": {
                "ip": "192.168.1.1",
                "port": 22,
                "username": "admin",
                "auth": {
                    "type": "password",
                    "password": "secret123"
                }
            },
            "router-2": {
                "ip": "192.168.1.2",
                "port": 830,
                "username": "operator",
                "role": "pe",
                "auth": {
                    "type": "ssh_key",
                    "private_key_path": "/path/to/key.pem"
                }
            },
            "router-3": {
                "ip": "192.168.1.3",
                "port": 22,
                "username": "admin",
                "ssh_config": "~/.ssh/config",
                "group": "core",
                "auth": {
                    "type": "password",
                    "password": "another_secret"
                }
            }
        }

        context = create_mock_context()
        result = await jmcp.handle_get_router_list({}, context)

        output_text = result[0].text
        router_info = json.loads(output_text)

        # Verify all routers are present
        expected_routers = {"router-1", "router-2", "router-3"}
        actual_routers = set(router_info.keys())

        if expected_routers != actual_routers:
            print(f"❌ Expected routers {expected_routers}, got {actual_routers}")
            return False

        # Verify router-1
        if "password" in router_info["router-1"].get("auth", {}):
            print("❌ router-1: password should be excluded")
            return False

        # Verify router-2
        if "private_key_path" in router_info["router-2"].get("auth", {}):
            print("❌ router-2: private_key_path should be excluded")
            return False

        if router_info["router-2"].get("role") != "pe":
            print("❌ router-2: custom field 'role' should be included")
            return False

        # Verify router-3
        if "ssh_config" in router_info["router-3"]:
            print("❌ router-3: ssh_config should be excluded")
            return False

        if router_info["router-3"].get("group") != "core":
            print("❌ router-3: custom field 'group' should be included")
            return False

        print("✅ Multiple devices handled correctly")
        return True

    finally:
        jmcp.devices = original_devices


async def test_json_format_validation():
    """Test that output is valid, pretty-printed JSON"""
    print("\n=== Testing JSON Format ===")

    original_devices = jmcp.devices.copy()

    try:
        jmcp.devices = {
            "test-router": {
                "ip": "10.0.0.1",
                "port": 22,
                "username": "test",
                "auth": {
                    "type": "password",
                    "password": "test123"
                }
            }
        }

        context = create_mock_context()
        result = await jmcp.handle_get_router_list({}, context)

        output_text = result[0].text

        # Verify it's valid JSON
        try:
            router_info = json.loads(output_text)
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON output: {e}")
            return False

        # Verify it's pretty-printed (contains newlines and indentation)
        if "\n" not in output_text or "  " not in output_text:
            print("❌ Output should be pretty-printed JSON")
            return False

        print("✅ JSON format validation passed")
        return True

    finally:
        jmcp.devices = original_devices


async def test_original_devices_not_modified():
    """Test that original devices dictionary is not modified"""
    print("\n=== Testing Original Devices Immutability ===")

    original_devices = jmcp.devices.copy()

    try:
        jmcp.devices = {
            "router-1": {
                "ip": "192.168.1.1",
                "port": 22,
                "username": "admin",
                "auth": {
                    "type": "password",
                    "password": "secret123"
                }
            }
        }

        # Save a reference to verify immutability
        devices_before = json.dumps(jmcp.devices, sort_keys=True)

        context = create_mock_context()
        result = await jmcp.handle_get_router_list({}, context)

        # Check devices dict wasn't modified
        devices_after = json.dumps(jmcp.devices, sort_keys=True)

        if devices_before != devices_after:
            print("❌ Original devices dictionary was modified")
            return False

        # Verify password still exists in original
        if "password" not in jmcp.devices["router-1"]["auth"]:
            print("❌ Password was removed from original devices dict")
            return False

        print("✅ Original devices dictionary remains unmodified")
        return True

    finally:
        jmcp.devices = original_devices


def run_async_test(test_func):
    """Helper to run async test functions"""
    return asyncio.run(test_func())


def main():
    """Run all tests"""
    print("=" * 60)
    print("handle_get_router_list() Unit Tests")
    print("=" * 60)

    tests = [
        test_empty_devices,
        test_single_device_password_auth,
        test_single_device_ssh_key_auth,
        test_device_with_ssh_config,
        test_device_with_custom_fields,
        test_multiple_devices,
        test_json_format_validation,
        test_original_devices_not_modified
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if run_async_test(test):
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} raised exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
