#!/usr/bin/env python3
"""
Example test script demonstrating the execute_junos_command_batch tool usage.

This shows how an LLM would call the batch command tool and the expected response format.
"""

import json

# Example 1: Batch command request
example_request = {
    "tool": "execute_junos_command_batch",
    "arguments": {
        "router_names": ["router1", "router2", "router3"],
        "command": "show version | match Junos",
        "timeout": 60
    }
}

print("=" * 80)
print("EXAMPLE REQUEST TO execute_junos_command_batch:")
print("=" * 80)
print(json.dumps(example_request, indent=2))
print()

# Example 2: Expected response format
example_response = {
    "summary": {
        "command": "show version | match Junos",
        "total_routers": 3,
        "successful": 2,
        "failed": 1,
        "total_duration": 2.456
    },
    "results": [
        {
            "router_name": "router1",
            "status": "success",
            "output": "Junos: 21.4R3.15",
            "execution_duration": 1.234,
            "start_time": "2025-01-15T10:30:00.000Z",
            "end_time": "2025-01-15T10:30:01.234Z"
        },
        {
            "router_name": "router2",
            "status": "success",
            "output": "Junos: 22.2R1.13",
            "execution_duration": 1.189,
            "start_time": "2025-01-15T10:30:00.005Z",
            "end_time": "2025-01-15T10:30:01.194Z"
        },
        {
            "router_name": "router3",
            "status": "failed",
            "output": "Connection error to router3: ConnectionRefusedError: [Errno 61] Connection refused",
            "execution_duration": 0.456,
            "start_time": "2025-01-15T10:30:00.010Z",
            "end_time": "2025-01-15T10:30:00.466Z"
        }
    ]
}

print("=" * 80)
print("EXAMPLE RESPONSE FROM execute_junos_command_batch:")
print("=" * 80)
print(json.dumps(example_response, indent=2))
print()

print("=" * 80)
print("KEY FEATURES:")
print("=" * 80)
print("✓ Parallel execution - all routers contacted simultaneously")
print("✓ Clear router identification - each result labeled with router_name")
print("✓ Status tracking - success/failed status for each router")
print("✓ Timing data - individual execution times plus total batch duration")
print("✓ Summary statistics - quick overview of batch results")
print()

print("=" * 80)
print("USE CASES:")
print("=" * 80)
print("1. Collect interface statistics from all routers in a region")
print("2. Check BGP neighbor status across multiple devices")
print("3. Gather configuration snippets from multiple routers")
print("4. Verify NTP sync status across the network")
print("5. Check system alarms on all devices")
print()

print("=" * 80)
print("COMPARISON: Single vs Batch Execution")
print("=" * 80)
print("Single command (serial execution):")
print("  - 3 routers × 1.2 seconds each = ~3.6 seconds total")
print()
print("Batch command (parallel execution):")
print("  - 3 routers running simultaneously = ~1.2 seconds total")
print("  - Performance improvement: 3x faster!")
print()
