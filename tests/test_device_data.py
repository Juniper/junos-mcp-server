#!/usr/bin/env python3
"""Shared JSON-backed device fixtures for unit tests."""

import json
from copy import deepcopy
from pathlib import Path

_DEVICES_FILE = Path(__file__).resolve().parent / "test_devices.json"


def _load_devices() -> dict:
    with _DEVICES_FILE.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


_DEVICES = _load_devices()


def get_device(name: str) -> dict:
    """Return a defensive copy of a device fixture by name."""
    if name not in _DEVICES:
        raise KeyError(f"Unknown test device fixture: {name}")
    return deepcopy(_DEVICES[name])
