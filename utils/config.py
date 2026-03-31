"""
Device configuration validation and connection parameter utilities
"""

import logging
from typing import Dict, Any

log = logging.getLogger("jmcp-server.config")


def validate_device_config(device_name: str, device_config: Dict[str, Any]) -> None:
    """Validate device configuration has all required fields

    Args:
        device_name: Name of the device
        device_config: Device configuration dictionary

    Raises:
        ValueError: If required fields are missing or invalid
    """
    # Check required top-level fields
    required_fields = ["ip", "port", "username"]
    missing_fields = [field for field in required_fields if field not in device_config]

    if missing_fields:
        raise ValueError(
            f"Device '{device_name}' missing required fields: {', '.join(missing_fields)}. "
            f"Expected format: {{'ip': 'x.x.x.x', 'port': 22, 'username': 'user', 'auth': {{...}}}}"
        )

    # Validate authentication configuration
    if "auth" in device_config:
        auth_config = device_config["auth"]
        if "type" not in auth_config:
            raise ValueError(
                f"Device '{device_name}' has 'auth' section but missing 'type' field. "
                f"Expected 'type' to be either 'password' or 'ssh_key'"
            )

        if auth_config["type"] == "password":
            if "password" not in auth_config:
                raise ValueError(
                    f"Device '{device_name}' auth type is 'password' "
                    "but 'password' field is missing"
                )
        elif auth_config["type"] == "ssh_key":
            if "private_key_path" not in auth_config:
                raise ValueError(
                    f"Device '{device_name}' auth type is 'ssh_key' "
                    "but 'private_key_path' field is missing"
                )
        else:
            raise ValueError(
                f"Device '{device_name}' has unsupported auth type '{auth_config['type']}'. "
                f"Supported types are: 'password', 'ssh_key'"
            )
    elif "password" not in device_config:
        # No auth section and no password field (backward compatibility check)
        raise ValueError(
            f"Device '{device_name}' missing authentication configuration. "
            f"Either provide 'auth' section or 'password' field (deprecated)"
        )

    # Validate data types
    if not isinstance(device_config.get("port"), int):
        raise ValueError(
            f"Device '{device_name}' has invalid 'port' value. "
            f"Expected integer, got {type(device_config.get('port')).__name__}"
        )

    log.debug("Device '%s' configuration validated successfully", device_name)


def validate_all_devices(devices: Dict[str, Dict[str, Any]]) -> None:
    """Validate all device configurations

    Args:
        devices: Dictionary of device configurations

    Raises:
        ValueError: If any device configuration is invalid
    """
    if not devices:
        log.warning("No devices configured")
        return

    errors = []
    for device_name, device_config in devices.items():
        try:
            validate_device_config(device_name, device_config)
        except ValueError as e:
            errors.append(str(e))

    if errors:
        error_msg = "Device configuration validation failed:\n" + "\n".join(
            f"  - {e}" for e in errors
        )
        raise ValueError(error_msg)

    log.info("All %s device(s) validated successfully", len(devices))


def prepare_connection_params(
    device_info: Dict[str, Any], router_name: str
) -> Dict[str, Any]:
    """Prepare connection parameters based on authentication type

    Args:
        device_info: Device configuration dictionary
        router_name: Name of the router (used for error messages)

    Returns:
        Connection parameters for Junos Device

    Raises:
        ValueError: If authentication configuration is invalid
    """
    # Validate configuration first
    validate_device_config(router_name, device_info)

    # Base connection parameters
    connect_params = {
        "host": device_info["ip"],
        "port": device_info["port"],
        "user": device_info["username"],
        "gather_facts": False,
        "timeout": 360,  # Default timeout of 360 seconds
    }

    # Add SSH config file if specified
    if "ssh_config" in device_info:
        connect_params["ssh_config"] = device_info["ssh_config"]

    # Handle different authentication methods
    if "auth" in device_info:
        auth_config = device_info["auth"]
        if auth_config["type"] == "password":
            connect_params["password"] = auth_config["password"]
        elif auth_config["type"] == "ssh_key":
            connect_params["ssh_private_key_file"] = auth_config["private_key_path"]
        else:
            raise ValueError(
                f"Unsupported auth type '{auth_config['type']}' for {router_name}"
            )
    elif "password" in device_info:
        # Backward compatibility with old format
        connect_params["password"] = device_info["password"]
    else:
        raise ValueError(f"No valid authentication method found for {router_name}")

    return connect_params
