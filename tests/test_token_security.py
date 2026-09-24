import json
import os
import secrets
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jmcp
import jmcp_token_manager


class TokenFileSecurityTests(unittest.TestCase):
    def test_save_tokens_creates_owner_only_file_under_common_umask(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / ".tokens"
            previous_umask = os.umask(0o022)
            try:
                with patch.object(jmcp_token_manager, "TOKENS_FILE", str(token_file)):
                    jmcp_token_manager.save_tokens({"test": {"token": "dummy"}})
            finally:
                os.umask(previous_umask)

            self.assertEqual(stat.S_IMODE(token_file.stat().st_mode), 0o600)

    def test_default_token_file_is_independent_of_working_directory(self):
        expected_path = Path(jmcp_token_manager.__file__).resolve().with_name(".tokens")

        self.assertEqual(jmcp_token_manager.TOKENS_FILE, expected_path)

    def test_validation_uses_explicit_path_and_constant_time_comparison(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / ".tokens"
            token_file.write_text(
                json.dumps({"test": {"token": "jmcp_expected"}}), encoding="utf-8"
            )
            other_directory = Path(tmpdir) / "other"
            other_directory.mkdir()
            original_cwd = Path.cwd()
            try:
                os.chdir(other_directory)
                with patch(
                    "jmcp.secrets.compare_digest", wraps=secrets.compare_digest
                ) as compare_digest:
                    valid = jmcp.validate_token_from_file(
                        "jmcp_expected", token_file=token_file
                    )
            finally:
                os.chdir(original_cwd)

            self.assertTrue(valid)
            compare_digest.assert_called_once_with(b"jmcp_expected", b"jmcp_expected")

    def test_validation_rejects_non_ascii_token_without_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / ".tokens"
            token_file.write_text(
                json.dumps({"test": {"token": "jmcp_expected"}}), encoding="utf-8"
            )

            self.assertFalse(
                jmcp.validate_token_from_file("jmcp_é", token_file=token_file)
            )

    def test_token_manager_uses_constant_time_comparison(self):
        with (
            patch.object(
                jmcp_token_manager,
                "load_tokens",
                return_value={"test": {"token": "jmcp_expected"}},
            ),
            patch(
                "jmcp_token_manager.secrets.compare_digest",
                wraps=secrets.compare_digest,
            ) as compare_digest,
        ):
            valid = jmcp_token_manager.validate_token("jmcp_expected")

        self.assertTrue(valid)
        compare_digest.assert_called_once_with(b"jmcp_expected", b"jmcp_expected")

    def test_save_tokens_repairs_existing_permissive_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / ".tokens"
            token_file.write_text("{}", encoding="utf-8")
            token_file.chmod(0o644)

            with patch.object(jmcp_token_manager, "TOKENS_FILE", str(token_file)):
                jmcp_token_manager.save_tokens({"test": {"token": "dummy"}})

            self.assertEqual(stat.S_IMODE(token_file.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
