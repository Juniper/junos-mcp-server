import os
import unittest
from unittest.mock import patch

from jmcp import get_stateless_with_fallback


class StatelessEnvParsingTests(unittest.TestCase):
    def test_default_false_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(get_stateless_with_fallback())

    def test_default_override_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(get_stateless_with_fallback(default=True))

    def test_truthy_values_enable_stateless(self):
        truthy_values = ["1", "true", "TRUE", "yes", "Y", "on", " On "]

        for value in truthy_values:
            with self.subTest(value=value):
                with patch.dict(os.environ, {"JMCP_STATELESS": value}, clear=True):
                    self.assertTrue(get_stateless_with_fallback())

    def test_falsy_values_disable_stateless(self):
        falsy_values = ["0", "false", "FALSE", "no", "N", "off", " Off "]

        for value in falsy_values:
            with self.subTest(value=value):
                with patch.dict(os.environ, {"JMCP_STATELESS": value}, clear=True):
                    self.assertFalse(get_stateless_with_fallback(default=True))

    def test_invalid_value_uses_default_and_logs_warning(self):
        with patch.dict(os.environ, {"JMCP_STATELESS": "sometimes"}, clear=True):
            with self.assertLogs("jmcp-server", level="WARNING") as captured:
                self.assertFalse(get_stateless_with_fallback())

        self.assertTrue(
            any("Invalid JMCP_STATELESS" in message for message in captured.output)
        )


if __name__ == "__main__":
    unittest.main()
