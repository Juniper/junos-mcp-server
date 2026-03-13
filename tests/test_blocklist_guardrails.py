import tempfile
import unittest
import mcp.types as types
from pathlib import Path

from jmcp import check_command_blocklist, check_config_blocklist, _is_error_content


class BlocklistGuardrailsTests(unittest.TestCase):
    def test_blocks_literal_prefix_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            block_file = Path(tmpdir) / "block.cfg"
            block_file.write_text("set system root-authentication\n", encoding="utf-8")

            blocked, message = check_config_blocklist(
                "set system root-authentication encrypted-password foo",
                block_file=str(block_file),
            )

            self.assertTrue(blocked)
            self.assertIn("matches blocked pattern", message)

    def test_blocks_regex_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            block_file = Path(tmpdir) / "block.cfg"
            block_file.write_text(
                "set system login user (.*) authentication\n", encoding="utf-8"
            )

            blocked, message = check_config_blocklist(
                "set system login user automation authentication encrypted-password bar",
                block_file=str(block_file),
            )

            self.assertTrue(blocked)
            self.assertIn("set system login user (.*) authentication", message)

    def test_blocks_regex_pattern_with_extra_spaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            block_file = Path(tmpdir) / "block.cfg"
            block_file.write_text(
                "set system login user (.*) authentication\n", encoding="utf-8"
            )

            blocked, message = check_config_blocklist(
                "set   system   login user guardx authentication encrypted-password xyz",
                block_file=str(block_file),
            )

            self.assertTrue(blocked)
            self.assertIn("set system login user (.*) authentication", message)

    def test_blocks_non_space_token_regex_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            block_file = Path(tmpdir) / "block.cfg"
            block_file.write_text(
                "set system login user ([^ ]+) authentication\n", encoding="utf-8"
            )

            blocked, message = check_config_blocklist(
                "set system login user guardx authentication encrypted-password",
                block_file=str(block_file),
            )

            self.assertTrue(blocked)
            self.assertIn("set system login user ([^ ]+) authentication", message)

    def test_uses_repo_block_cfg_when_cwd_differs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = Path.cwd()
            try:
                # Ensure no local block.cfg exists in temporary cwd
                import os

                os.chdir(tmpdir)
                blocked, message = check_config_blocklist(
                    "set system login user guardx authentication encrypted-password",
                    block_file="block.cfg",
                )
            finally:
                os.chdir(original_cwd)

            self.assertTrue(blocked)
            self.assertIn("set system login user ([^ ]+) authentication", message)

    def test_missing_block_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_file = Path(tmpdir) / "does-not-exist.cfg"

            blocked, message = check_config_blocklist(
                "set interfaces ge-0/0/0 description test",
                block_file=str(missing_file),
            )

            self.assertTrue(blocked)
            self.assertIn("not found", message)

    def test_allows_non_blocked_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            block_file = Path(tmpdir) / "block.cfg"
            block_file.write_text("set system root-authentication\n", encoding="utf-8")

            blocked, message = check_config_blocklist(
                "set interfaces ge-0/0/0 description test",
                block_file=str(block_file),
            )

            self.assertFalse(blocked)
            self.assertIsNone(message)


class CommandBlocklistGuardrailsTests(unittest.TestCase):
    def test_blocks_literal_prefix_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            block_file = Path(tmpdir) / "block.cmd"
            block_file.write_text("request system reboot\n", encoding="utf-8")

            blocked, message = check_command_blocklist(
                "request system reboot in 1",
                block_file=str(block_file),
            )

            self.assertTrue(blocked)
            self.assertIn("matches blocked pattern", message)

    def test_blocks_regex_prefix_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            block_file = Path(tmpdir) / "block.cmd"
            block_file.write_text("request system reboot(.*)\n", encoding="utf-8")

            blocked, message = check_command_blocklist(
                "request system reboot at 22:00",
                block_file=str(block_file),
            )

            self.assertTrue(blocked)
            self.assertIn("request system reboot(.*)", message)

    def test_allows_non_blocked_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            block_file = Path(tmpdir) / "block.cmd"
            block_file.write_text("request system reboot\n", encoding="utf-8")

            blocked, message = check_command_blocklist(
                "show interfaces terse",
                block_file=str(block_file),
            )

            self.assertFalse(blocked)
            self.assertIsNone(message)

    def test_missing_block_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_file = Path(tmpdir) / "does-not-exist.cmd"

            blocked, message = check_command_blocklist(
                "show version",
                block_file=str(missing_file),
            )

            self.assertTrue(blocked)
            self.assertIn("not found", message)


class ToolErrorClassificationTests(unittest.TestCase):
    def test_blocked_message_is_error(self):
        blocks = [
            types.TextContent(
                type="text",
                text="Blocked configuration rejected: line 'x' matches blocked pattern 'y'",
            )
        ]
        self.assertTrue(_is_error_content(blocks))

    def test_blocked_command_message_is_error(self):
        blocks = [
            types.TextContent(
                type="text",
                text="Blocked command rejected: command 'request system reboot now' matches blocked pattern 'request system reboot'",
            )
        ]
        self.assertTrue(_is_error_content(blocks))


if __name__ == "__main__":
    unittest.main()
