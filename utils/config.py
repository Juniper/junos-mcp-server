"""
Device configuration validation and connection parameter utilities
"""

import logging
from typing import Dict, Any

log = logging.getLogger("jmcp-server.config")


def validate_device_config(device_name: str, device_config: Dict[str, Any]) -> None:
    """Validate device configuration has all required fields"""
    # ---- Required top-level fields ----
    required_fields = ["ip", "username"]
    missing_fields = [f for f in required_fields if f not in device_config]
    if missing_fields:
        raise ValueError(
            f"Device '{device_name}' missing required fields: {', '.join(missing_fields)}"
        )
    # Default port normalization
    if "port" not in device_config:
        device_config["port"] = 22
    if not isinstance(device_config["port"], int):
        raise ValueError(
            f"Device '{device_name}' has invalid port type "
            f"({type(device_config['port']).__name__}); expected int"
        )
    # ---- Device type ----
    device_type = device_config.get("type", "junos").lower()
    if device_type not in {"junos", "linux"}:
        raise ValueError(
            f"Device '{device_name}' has unsupported type '{device_type}'"
        )
    # ---- Auth validation ----
    if "auth" not in device_config:
        raise ValueError(
            f"Device '{device_name}' missing auth configuration"
        )
    auth = device_config["auth"]
    if "type" not in auth:
        raise ValueError(
            f"Device '{device_name}' auth section missing 'type'"
        )
    auth_type = auth["type"]
    if auth_type == "password":
        if "password" not in auth:
            raise ValueError(
                f"Device '{device_name}' auth type is 'password' "
                f"but 'password' field is missing"
            )
        # Enforce Junos restriction
        if device_type == "junos":
            log.warning(
                "Device '%s' is Junos using password authentication; "
                "this is discouraged and may fail depending on Junos/NETCONF settings",
                device_name,
            )

    elif auth_type == "ssh_key":
        if "private_key_path" not in auth:
            raise ValueError(
                f"Device '{device_name}' auth type is 'ssh_key' "
                f"but 'private_key_path' is missing"
            )
    else:
        raise ValueError(
            f"Device '{device_name}' has unsupported auth type '{auth_type}'"
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
