#!/usr/bin/env python3
"""Unit tests for execute_junos_command_batch example payloads."""

import unittest

EXAMPLE_REQUEST = {
    "tool": "execute_junos_command_batch",
    "arguments": {
        "router_names": ["router1", "router2", "router3"],
        "command": "show version | match Junos",
        "timeout": 60,
    },
}


EXAMPLE_RESPONSE = {
    "summary": {
        "command": "show version | match Junos",
        "total_routers": 3,
        "successful": 2,
        "failed": 1,
        "total_duration": 2.456,
    },
    "results": [
        {
            "router_name": "router1",
            "status": "success",
            "output": "Junos: 21.4R3.15",
            "execution_duration": 1.234,
            "start_time": "2025-01-15T10:30:00.000Z",
            "end_time": "2025-01-15T10:30:01.234Z",
        },
        {
            "router_name": "router2",
            "status": "success",
            "output": "Junos: 22.2R1.13",
            "execution_duration": 1.189,
            "start_time": "2025-01-15T10:30:00.005Z",
            "end_time": "2025-01-15T10:30:01.194Z",
        },
        {
            "router_name": "router3",
            "status": "failed",
            "output": "Connection error to router3: ConnectionRefusedError: [Errno 61] Connection refused",
            "execution_duration": 0.456,
            "start_time": "2025-01-15T10:30:00.010Z",
            "end_time": "2025-01-15T10:30:00.466Z",
        },
    ],
}


class BatchCommandExampleTests(unittest.TestCase):
    def test_example_request_schema(self):
        self.assertEqual(EXAMPLE_REQUEST["tool"], "execute_junos_command_batch")
        arguments = EXAMPLE_REQUEST["arguments"]
        self.assertIn("router_names", arguments)
        self.assertIn("command", arguments)
        self.assertIn("timeout", arguments)
        self.assertIsInstance(arguments["router_names"], list)
        self.assertGreater(len(arguments["router_names"]), 0)

    def test_example_response_summary_consistency(self):
        summary = EXAMPLE_RESPONSE["summary"]
        results = EXAMPLE_RESPONSE["results"]

        successful = sum(1 for r in results if r["status"] == "success")
        failed = sum(1 for r in results if r["status"] == "failed")

        self.assertEqual(summary["total_routers"], len(results))
        self.assertEqual(summary["successful"], successful)
        self.assertEqual(summary["failed"], failed)

    def test_each_result_has_required_keys(self):
        required_keys = {
            "router_name",
            "status",
            "output",
            "execution_duration",
            "start_time",
            "end_time",
        }
        for result in EXAMPLE_RESPONSE["results"]:
            self.assertTrue(required_keys.issubset(result.keys()))


if __name__ == "__main__":
    unittest.main()
