#!/usr/bin/env python3
"""Unit tests for commit check, dry run and commit confirmed.

Covers load_and_commit_config (commit check before every commit, dry_run,
confirm_timeout_mins), render_and_apply_j2_template (confirm_timeout_mins),
the confirm_commit tool, and the pending-commit guard that keeps a commit
check from silently confirming a pending `commit confirmed`.

The <get-commit-information> fixtures mirror replies captured from a vSRX
running Junos 24.4R2.21 (user names and comments changed).
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import jmcp
from jnpr.junos.exception import CommitError, RpcError, RpcTimeoutError
from lxml import etree
from tests.test_device_data import get_device

CONFIG = "set system host-name foo"
DIFF = "+ set system host-name foo"

# A commit confirmed inside its window, with a commit comment (in <log>).
PENDING_WITH_COMMENT = """
<commit-information>
  <commit-history>
    <sequence-number>0</sequence-number>
    <user>netops</user>
    <client>netconf</client>
    <date-time seconds="1791237823">2026-10-05 22:03:43 UTC</date-time>
    <comment>commit confirmed, rollback in 5mins</comment>
    <log>change under test</log>
    <commit-confirmed>rollback pending</commit-confirmed>
  </commit-history>
  <commit-history>
    <sequence-number>1</sequence-number>
    <user>netops</user>
    <client>netconf</client>
    <date-time seconds="1791229512">2026-10-05 19:45:12 UTC</date-time>
    <log>earlier change</log>
  </commit-history>
</commit-information>
"""

# The same without a commit comment: no <log>, marker still present.
PENDING_NO_COMMENT = """
<commit-information>
  <commit-history>
    <sequence-number>0</sequence-number>
    <user>netops</user>
    <client>netconf</client>
    <date-time seconds="1791238573">2026-10-05 22:16:13 UTC</date-time>
    <comment>commit confirmed, rollback in 5mins</comment>
    <commit-confirmed>rollback pending</commit-confirmed>
  </commit-history>
</commit-information>
"""

# A commit confirmed that was confirmed (here by a commit check): the
# <comment> text stays, the <commit-confirmed> marker is gone.
CONFIRMED = """
<commit-information>
  <commit-history>
    <sequence-number>0</sequence-number>
    <user>netops</user>
    <client>netconf</client>
    <date-time seconds="1791229206">2026-10-05 19:40:06 UTC</date-time>
    <comment>commit confirmed, rollback in 3mins</comment>
    <log>change under test</log>
  </commit-history>
</commit-information>
"""

# After the automatic rollback: a new entry 0 by root via other.
ROLLED_BACK = """
<commit-information>
  <commit-history>
    <sequence-number>0</sequence-number>
    <user>root</user>
    <client>other</client>
    <date-time seconds="1791238157">2026-10-05 22:09:17 UTC</date-time>
  </commit-history>
  <commit-history>
    <sequence-number>1</sequence-number>
    <user>netops</user>
    <client>netconf</client>
    <date-time seconds="1791237823">2026-10-05 22:03:43 UTC</date-time>
    <comment>commit confirmed, rollback in 5mins</comment>
    <log>change under test</log>
  </commit-history>
</commit-information>
"""

NOT_PENDING = ROLLED_BACK


def _xml(text):
    return etree.XML(text.strip())


def _make_context():
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.debug = AsyncMock()
    ctx.warning = AsyncMock()
    ctx.error = AsyncMock()
    return ctx


def _load_args(**overrides):
    args = {"router_name": "router1", "config_text": CONFIG, "config_format": "set"}
    args.update(overrides)
    return args


class _DeviceTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_devices = jmcp.devices.copy()
        jmcp.devices = {"router1": get_device("router1")}
        jmcp.connection_pool.close_all(shutdown=False)

        device_patch = patch("jmcp.Device")
        config_patch = patch("jmcp.Config")
        mock_device_cls = device_patch.start()
        self.mock_config_cls = config_patch.start()
        self.addCleanup(device_patch.stop)
        self.addCleanup(config_patch.stop)

        self.device = MagicMock()
        self.device.connected = True
        self.set_commit_information(NOT_PENDING)
        mock_device_cls.return_value = self.device

        # Config(...) is used directly (load_and_commit_config, confirm_commit)
        # and as a context manager (render_and_apply_j2_template); both yield cu.
        self.cu = MagicMock()
        self.cu.diff.return_value = DIFF
        self.cu.commit_check.return_value = True
        self.cu.__enter__.return_value = self.cu
        self.cu.__exit__.return_value = False
        self.mock_config_cls.return_value = self.cu

    def tearDown(self):
        jmcp.devices = self._orig_devices
        jmcp.connection_pool.close_all(shutdown=False)

    def set_commit_information(self, xml_text):
        self.device.rpc.get_commit_information.return_value = _xml(xml_text)

    def timeout_error(self):
        return RpcTimeoutError(self.device, "commit", 30)


class ParseConfirmTimeoutTests(unittest.TestCase):
    def test_none_means_plain_commit(self):
        self.assertIsNone(jmcp._parse_confirm_timeout(None))

    def test_valid_range(self):
        self.assertEqual(jmcp._parse_confirm_timeout(1), 1)
        self.assertEqual(jmcp._parse_confirm_timeout(65535), 65535)

    def test_rejects_out_of_range_and_wrong_types(self):
        for bad in (0, -5, 65536, True, "10", 2.5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                jmcp._parse_confirm_timeout(bad)


class CommitConfirmedPendingTests(unittest.TestCase):
    def _pending(self, xml_text):
        dev = MagicMock()
        dev.rpc.get_commit_information.return_value = _xml(xml_text)
        return jmcp._commit_confirmed_pending(dev)

    def test_pending_with_comment(self):
        self.assertTrue(self._pending(PENDING_WITH_COMMENT))

    def test_pending_without_comment(self):
        self.assertTrue(self._pending(PENDING_NO_COMMENT))

    def test_confirmed_commit_keeps_comment_but_is_not_pending(self):
        self.assertFalse(self._pending(CONFIRMED))

    def test_rolled_back_is_not_pending(self):
        self.assertFalse(self._pending(ROLLED_BACK))

    def test_empty_history_is_not_pending(self):
        self.assertFalse(self._pending("<commit-information/>"))


class LoadAndCommitTests(_DeviceTestCase):
    def _call(self, **overrides):
        return asyncio.run(
            jmcp.handle_load_and_commit_config(_load_args(**overrides), _make_context())
        )

    def _run(self, **overrides):
        return self._call(**overrides)[0].text

    def test_commit_check_runs_before_plain_commit(self):
        text = self._run()
        self.assertIn("successfully loaded and committed", text)
        self.cu.commit_check.assert_called_once()
        self.cu.commit.assert_called_once()
        self.assertIsNone(self.cu.commit.call_args.kwargs.get("confirm"))
        self.assertNotIn("pending confirmation", text)

    def test_failed_commit_check_does_not_commit(self):
        rsp = etree.XML(
            "<rpc-reply><rpc-error><error-severity>error</error-severity>"
            "<error-message>missing mandatory statement</error-message>"
            "</rpc-error></rpc-reply>"
        )
        self.cu.commit_check.side_effect = CommitError(rsp=rsp)
        text = self._run()
        self.assertTrue(text.startswith("Failed commit check on router1"))
        self.assertIn("missing mandatory statement", text)
        self.cu.commit.assert_not_called()
        self.cu.rollback.assert_called_once()
        self.cu.unlock.assert_called_once()

    def test_commit_check_error_dict_does_not_commit(self):
        # PyEZ can return a truthy error dict instead of raising.
        self.cu.commit_check.return_value = {"message": "rpc error"}
        text = self._run()
        self.assertTrue(text.startswith("Failed commit check on router1"))
        self.assertIn("rpc error", text)
        self.cu.commit.assert_not_called()
        self.cu.rollback.assert_called_once()

    def test_commit_check_false_does_not_commit(self):
        self.cu.commit_check.return_value = False
        text = self._run()
        self.assertTrue(text.startswith("Failed commit check on router1"))
        self.cu.commit.assert_not_called()

    def test_commit_check_rpc_error_rolls_back(self):
        self.cu.commit_check.side_effect = RpcError()
        text = self._run()
        self.assertTrue(text.startswith("Failed to load/commit configuration"))
        self.cu.commit.assert_not_called()
        self.cu.rollback.assert_called_once()
        self.cu.unlock.assert_called_once()
        self.device.close.assert_not_called()

    def test_commit_check_timeout_rolls_back_and_evicts_session(self):
        self.cu.commit_check.side_effect = self.timeout_error()
        text = self._run()
        self.assertTrue(text.startswith("Failed to load/commit configuration"))
        self.cu.commit.assert_not_called()
        self.cu.rollback.assert_called_once()
        self.cu.unlock.assert_called_once()
        self.device.close.assert_called()

    def test_dry_run_checks_and_rolls_back(self):
        text = self._run(dry_run=True)
        self.assertIn("Dry run: commit check passed on router1", text)
        self.assertIn(DIFF, text)
        self.cu.commit_check.assert_called_once()
        self.cu.commit.assert_not_called()
        self.cu.rollback.assert_called_once()
        self.cu.unlock.assert_called_once()

    def test_confirm_timeout_uses_commit_confirmed(self):
        text = self._run(confirm_timeout_mins=5)
        self.assertEqual(self.cu.commit.call_args.kwargs["confirm"], 5)
        self.assertIn("Commit is pending confirmation", text)
        self.assertIn("roll back in 5 minute(s)", text)
        self.assertIn("confirm_commit", text)

    def test_confirmed_commit_timeout_warns_it_may_have_landed(self):
        self.cu.commit.side_effect = self.timeout_error()
        text = self._run(confirm_timeout_mins=5)
        self.assertTrue(text.startswith("Failed to load/commit configuration"))
        self.assertIn("may still have landed on router1", text)
        self.assertIn("show system commit", text)
        self.device.close.assert_called()

    def test_plain_commit_timeout_has_no_confirm_warning(self):
        self.cu.commit.side_effect = self.timeout_error()
        text = self._run()
        self.assertTrue(text.startswith("Failed to load/commit configuration"))
        self.assertNotIn("may still have landed", text)
        self.device.close.assert_called()

    def test_invalid_confirm_timeout_never_touches_device(self):
        text = self._run(confirm_timeout_mins=0)
        self.assertTrue(text.startswith("Error: confirm_timeout_mins"))
        self.mock_config_cls.assert_not_called()

    def test_error_results_are_flagged(self):
        self.cu.commit_check.return_value = False
        self.assertTrue(jmcp._is_error_content(self._call()))

    def test_refused_while_commit_confirmed_pending(self):
        self.set_commit_information(PENDING_WITH_COMMENT)
        for overrides in ({"dry_run": True}, {}, {"confirm_timeout_mins": 5}):
            with self.subTest(**overrides):
                self.cu.reset_mock()
                result = self._call(**overrides)
                text = result[0].text
                self.assertTrue(
                    text.startswith("Error: a commit confirmed is pending on router1")
                )
                self.assertIn("confirm_commit", text)
                self.assertTrue(jmcp._is_error_content(result))
                # Refused before loading: no candidate change, no check, no commit.
                self.cu.load.assert_not_called()
                self.cu.commit_check.assert_not_called()
                self.cu.commit.assert_not_called()
                self.cu.unlock.assert_called_once()

    def test_refused_while_pending_without_comment(self):
        self.set_commit_information(PENDING_NO_COMMENT)
        text = self._run(dry_run=True)
        self.assertTrue(text.startswith("Error: a commit confirmed is pending"))
        self.cu.commit_check.assert_not_called()

    def test_allowed_after_commit_confirmed_was_confirmed(self):
        self.set_commit_information(CONFIRMED)
        text = self._run(dry_run=True)
        self.assertIn("Dry run: commit check passed on router1", text)


class RenderJ2ConfirmTests(_DeviceTestCase):
    def _run(self, **overrides):
        args = {
            "template_content": "set system host-name {{ name }}",
            "vars_content": "name: foo",
            "router_name": "router1",
            "apply_config": True,
        }
        args.update(overrides)
        return asyncio.run(
            jmcp.handle_render_and_apply_j2_template(args, _make_context())
        )[0].text

    def test_confirm_timeout_passed_to_commit(self):
        text = self._run(confirm_timeout_mins=10)
        self.assertEqual(self.cu.commit.call_args.kwargs["confirm"], 10)
        self.assertIn("roll back in 10 minute(s)", text)

    def test_plain_commit_without_confirm(self):
        self._run()
        self.assertIsNone(self.cu.commit.call_args.kwargs.get("confirm"))

    def test_invalid_confirm_timeout_rejected(self):
        text = self._run(confirm_timeout_mins=70000)
        self.assertTrue(text.startswith("❌ Error: confirm_timeout_mins"))
        self.mock_config_cls.assert_not_called()

    def test_refused_while_commit_confirmed_pending(self):
        self.set_commit_information(PENDING_WITH_COMMENT)
        for overrides in ({"dry_run": True}, {}):
            with self.subTest(**overrides):
                self.cu.reset_mock()
                text = self._run(**overrides)
                self.assertIn("❌ router1: a commit confirmed is pending", text)
                self.cu.load.assert_not_called()
                self.cu.commit_check.assert_not_called()
                self.cu.commit.assert_not_called()

    def test_confirmed_commit_timeout_warns_it_may_have_landed(self):
        self.cu.commit.side_effect = self.timeout_error()
        text = self._run(confirm_timeout_mins=10)
        self.assertIn("Failed to apply configuration", text)
        self.assertIn("may still have landed on router1", text)


class ConfirmCommitTests(_DeviceTestCase):
    def setUp(self):
        super().setUp()
        self.set_commit_information(PENDING_WITH_COMMENT)
        self.cu.diff.return_value = None

    def _call(self, router_name="router1"):
        return asyncio.run(
            jmcp.handle_confirm_commit({"router_name": router_name}, _make_context())
        )

    def _run(self, router_name="router1"):
        return self._call(router_name)[0].text

    def test_confirms_pending_commit_with_clean_candidate(self):
        text = self._run()
        self.assertEqual(
            text, "Pending commit on router1 confirmed; automatic rollback cancelled."
        )
        self.cu.commit.assert_called_once()
        self.assertNotIn("confirm", self.cu.commit.call_args.kwargs)
        self.cu.unlock.assert_called_once()

    def test_refuses_when_nothing_is_pending(self):
        for state in (ROLLED_BACK, CONFIRMED):
            with self.subTest(state=state[:40]):
                self.cu.reset_mock()
                self.set_commit_information(state)
                result = self._call()
                self.assertTrue(
                    result[0].text.startswith(
                        "Error: No pending commit confirmed on router1"
                    )
                )
                self.assertTrue(jmcp._is_error_content(result))
                self.cu.commit.assert_not_called()
                self.cu.unlock.assert_called_once()

    def test_refuses_when_candidate_is_dirty(self):
        self.cu.diff.return_value = DIFF
        text = self._run()
        self.assertTrue(text.startswith("Failed to confirm commit on router1"))
        self.assertIn(DIFF, text)
        self.cu.commit.assert_not_called()
        self.cu.unlock.assert_called_once()

    def test_lock_failure(self):
        self.cu.lock.side_effect = RuntimeError("configuration database locked")
        text = self._run()
        self.assertTrue(text.startswith("Failed to lock configuration"))
        self.cu.commit.assert_not_called()

    def test_commit_error_unlocks_and_keeps_session(self):
        self.cu.commit.side_effect = RuntimeError("boom")
        text = self._run()
        self.assertEqual(text, "Failed to confirm commit on router1: boom")
        self.cu.unlock.assert_called_once()
        self.device.close.assert_not_called()

    def test_commit_error_with_failed_unlock_evicts_session(self):
        self.cu.commit.side_effect = RuntimeError("boom")
        self.cu.unlock.side_effect = RuntimeError("unlock failed")
        text = self._run()
        self.assertTrue(text.startswith("Failed to confirm commit on router1"))
        self.device.close.assert_called()

    def test_commit_timeout_evicts_session_and_warns(self):
        self.cu.commit.side_effect = self.timeout_error()
        text = self._run()
        self.assertTrue(text.startswith("Failed to confirm commit on router1"))
        self.assertIn("may or may not have reached the device", text)
        self.assertIn("show system commit", text)
        self.cu.unlock.assert_called_once()
        self.device.close.assert_called()

    def test_unknown_router(self):
        text = self._run("nope")
        self.assertIn("not found", text)
        self.mock_config_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
