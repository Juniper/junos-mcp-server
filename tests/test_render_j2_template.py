#!/usr/bin/env python3
"""Unit tests for render_and_apply_j2_template.

Covers the rendering/validation surface and the apply-path behaviors that
test_render_j2_pool.py does not: strict undefined-variable handling, YAML
mapping validation, config-format auto-detection (including XML), timeout
propagation (argument and JUNOS_TIMEOUT fallback), fail-fast router
validation, blocklist enforcement on the rendered output, parallel
multi-router application with per-router failure isolation, and eviction of
sessions whose dry-run rollback failed.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import jmcp
from tests.test_device_data import get_device

TEMPLATE = "set system host-name {{ name }}"
VARS = "name: foo"


def _make_context():
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.debug = AsyncMock()
    ctx.warning = AsyncMock()
    ctx.error = AsyncMock()
    return ctx


def _run(args):
    return asyncio.run(jmcp.handle_render_and_apply_j2_template(args, _make_context()))


def _apply_args(**overrides):
    args = {
        "template_content": TEMPLATE,
        "vars_content": VARS,
        "router_name": "router1",
        "apply_config": True,
    }
    args.update(overrides)
    return args


def _make_config_cm(cu):
    """Wrap a Config mock in a context manager the handler can enter."""
    cfg_cm = MagicMock()
    cfg_cm.__enter__.return_value = cu
    cfg_cm.__exit__.return_value = False
    return cfg_cm


def _make_cu(diff="+ set system host-name foo"):
    cu = MagicMock()
    cu.diff.return_value = diff
    cu.commit_check.return_value = True
    return cu


class DetectConfigFormatTests(unittest.TestCase):
    def test_set_format(self):
        cfg = "set system host-name foo\ndelete interfaces ge-0/0/0\n"
        self.assertEqual(jmcp._detect_config_format(cfg), "set")

    def test_set_format_with_comments_and_blanks(self):
        cfg = "# hostname config\n\nset system host-name foo\n"
        self.assertEqual(jmcp._detect_config_format(cfg), "set")

    def test_text_format(self):
        cfg = "system {\n    host-name foo;\n}\n"
        self.assertEqual(jmcp._detect_config_format(cfg), "text")

    def test_xml_format(self):
        cfg = (
            "<configuration><system><host-name>foo</host-name></system></configuration>"
        )
        self.assertEqual(jmcp._detect_config_format(cfg), "xml")

    def test_xml_format_with_leading_whitespace(self):
        cfg = "\n  <configuration/>\n"
        self.assertEqual(jmcp._detect_config_format(cfg), "xml")


class RenderValidationTests(unittest.TestCase):
    """Input validation and render-only paths — no device is ever touched."""

    @patch("jmcp.Device")
    def test_render_only_does_not_connect(self, mock_device_cls):
        result = _run({"template_content": TEMPLATE, "vars_content": VARS})
        self.assertIn("✅ Template rendered successfully!", result[0].text)
        self.assertIn("set system host-name foo", result[0].text)
        mock_device_cls.assert_not_called()

    def test_missing_template_content(self):
        result = _run({"vars_content": VARS})
        self.assertIn("template_content is required", result[0].text)

    def test_missing_vars_content(self):
        result = _run({"template_content": TEMPLATE})
        self.assertIn("vars_content is required", result[0].text)

    def test_invalid_yaml(self):
        result = _run({"template_content": TEMPLATE, "vars_content": "name: [unclosed"})
        self.assertIn("❌ Error parsing YAML content", result[0].text)

    def test_non_mapping_vars(self):
        result = _run({"template_content": TEMPLATE, "vars_content": "- a\n- b\n"})
        self.assertIn("must be a YAML mapping", result[0].text)
        self.assertIn("got list", result[0].text)

    def test_undefined_variable_fails_render(self):
        # A typo'd/missing variable must fail loudly, not render as an empty
        # string that could load broken config onto a device.
        result = _run({"template_content": TEMPLATE, "vars_content": "wrong_key: foo"})
        self.assertIn("❌ Error rendering template", result[0].text)
        self.assertIn("'name' is undefined", result[0].text)

    def test_empty_rendered_config(self):
        result = _run(
            {"template_content": "{# only a comment #}", "vars_content": VARS}
        )
        self.assertIn("rendered configuration is empty", result[0].text)

    def test_invalid_config_format_override(self):
        result = _run(_apply_args(config_format="json"))
        self.assertIn("invalid config_format 'json'", result[0].text)

    def test_apply_without_routers(self):
        result = _run(
            {
                "template_content": TEMPLATE,
                "vars_content": VARS,
                "apply_config": True,
            }
        )
        self.assertIn("router_name or router_names must be provided", result[0].text)


class RenderApplyTests(unittest.TestCase):
    """Apply-path behaviors against mocked pooled devices."""

    def setUp(self):
        self._orig_devices = jmcp.devices.copy()
        jmcp.devices = {
            "router1": get_device("router1"),
            "router3": get_device("router3"),
        }
        jmcp.connection_pool.close_all(shutdown=False)

    def tearDown(self):
        jmcp.devices = self._orig_devices
        jmcp.connection_pool.close_all(shutdown=False)

    @patch("jmcp.Device")
    def test_unknown_router_fails_fast(self, mock_device_cls):
        # One bad name aborts the whole call before any device is touched —
        # a partial fleet application is worse than none.
        result = _run(_apply_args(router_names=["router1", "ghost"]))
        self.assertIn("ghost", result[0].text)
        self.assertIn("No configuration was applied", result[0].text)
        mock_device_cls.assert_not_called()

    @patch("jmcp.Device")
    def test_blocklist_rejects_rendered_config(self, mock_device_cls):
        result = _run(
            _apply_args(
                template_content=(
                    "set system root-authentication plain-text-password {{ name }}"
                )
            )
        )
        self.assertIn("Blocked configuration rejected", result[0].text)
        mock_device_cls.assert_not_called()

    @patch("jmcp.Config")
    @patch("jmcp.Device")
    def test_timeout_argument_reaches_connection_and_commit(
        self, mock_device_cls, mock_config_cls
    ):
        mock_device = MagicMock()
        mock_device.connected = True
        mock_device_cls.return_value = mock_device
        cu = _make_cu()
        mock_config_cls.return_value = _make_config_cm(cu)

        result = _run(_apply_args(timeout=42))

        self.assertIn("✅ router1", result[0].text)
        # get_connection stamps the borrowed session with the call's timeout.
        self.assertEqual(mock_device.timeout, 42)
        cu.commit.assert_called_once_with(
            comment="Configuration applied via Jinja2 template", timeout=42
        )

    @patch("jmcp.Config")
    @patch("jmcp.Device")
    def test_junos_timeout_env_fallback(self, mock_device_cls, mock_config_cls):
        mock_device = MagicMock()
        mock_device.connected = True
        mock_device_cls.return_value = mock_device
        cu = _make_cu()
        mock_config_cls.return_value = _make_config_cm(cu)

        with patch.dict(os.environ, {"JUNOS_TIMEOUT": "77"}):
            result = _run(_apply_args())

        self.assertIn("✅ router1", result[0].text)
        self.assertEqual(mock_device.timeout, 77)
        cu.commit.assert_called_once_with(
            comment="Configuration applied via Jinja2 template", timeout=77
        )

    @patch("jmcp.Config")
    @patch("jmcp.Device")
    def test_xml_config_autodetected_and_loaded_as_xml(
        self, mock_device_cls, mock_config_cls
    ):
        mock_device = MagicMock()
        mock_device.connected = True
        mock_device_cls.return_value = mock_device
        cu = _make_cu()
        mock_config_cls.return_value = _make_config_cm(cu)

        result = _run(
            _apply_args(
                template_content=(
                    "<configuration><system><host-name>{{ name }}"
                    "</host-name></system></configuration>"
                )
            )
        )

        self.assertIn("✅ router1", result[0].text)
        load_kwargs = cu.load.call_args.kwargs
        self.assertEqual(load_kwargs.get("format"), "xml")

    @patch("jmcp.Config")
    @patch("jmcp.Device")
    def test_load_ignores_statement_not_found_warning(
        self, mock_device_cls, mock_config_cls
    ):
        # Deleting an already-absent statement makes Junos emit a
        # "statement not found" warning, which PyEZ escalates into
        # ConfigLoadError unless suppressed — a re-run of a delete template
        # must report "no changes", not an error.
        mock_device = MagicMock()
        mock_device.connected = True
        mock_device_cls.return_value = mock_device
        cu = _make_cu(diff=None)
        mock_config_cls.return_value = _make_config_cm(cu)

        result = _run(_apply_args(template_content="delete system location {{ name }}"))

        self.assertIn("No configuration changes detected", result[0].text)
        self.assertEqual(
            cu.load.call_args.kwargs.get("ignore_warning"),
            ["statement not found"],
        )

    @patch("jmcp.Config")
    @patch("jmcp.Device")
    def test_router_name_and_router_names_merge_and_dedupe(
        self, mock_device_cls, mock_config_cls
    ):
        devices_by_host = {}

        def _device_factory(**kwargs):
            dev = MagicMock()
            dev.connected = True
            devices_by_host[kwargs["host"]] = dev
            return dev

        mock_device_cls.side_effect = _device_factory

        cus = []

        def _config_factory(dev, **kwargs):
            cu = _make_cu()
            cus.append(cu)
            return _make_config_cm(cu)

        mock_config_cls.side_effect = _config_factory

        result = _run(
            _apply_args(router_name="router1", router_names=["router1", "router3"])
        )

        self.assertIn("✅ router1", result[0].text)
        self.assertIn("✅ router3", result[0].text)
        # router1 appears in both arguments but is configured exactly once.
        self.assertEqual(mock_device_cls.call_count, 2)
        self.assertEqual(len(cus), 2)
        for cu in cus:
            cu.commit.assert_called_once()

    @patch("jmcp.Config")
    @patch("jmcp.Device")
    def test_parallel_apply_isolates_per_router_failures(
        self, mock_device_cls, mock_config_cls
    ):
        # router1's commit blows up mid-flight; router3 must still commit, and
        # only router1's session gets evicted from the pool.
        devices_by_host = {}

        def _device_factory(**kwargs):
            dev = MagicMock()
            dev.connected = True

            def _close(_dev=dev):
                _dev.connected = False

            dev.close.side_effect = _close
            devices_by_host[kwargs["host"]] = dev
            return dev

        mock_device_cls.side_effect = _device_factory

        cus_by_dev = {}

        def _config_factory(dev, **kwargs):
            cu = _make_cu()
            if dev is devices_by_host.get("1.1.1.1"):
                cu.commit.side_effect = RuntimeError("commit exploded")
            cus_by_dev[id(dev)] = cu
            return _make_config_cm(cu)

        mock_config_cls.side_effect = _config_factory

        result = _run(_apply_args(router_names=["router1", "router3"]))

        text = result[0].text
        self.assertIn(
            "❌ router1: Failed to apply configuration: commit exploded", text
        )
        self.assertIn("✅ router3: Configuration committed successfully", text)
        # router1's transport was dropped and its pool slot cleared...
        self.assertIsNone(jmcp.connection_pool._connections["router1"]["device"])
        # ...while router3's healthy session stays cached for reuse.
        self.assertIs(
            jmcp.connection_pool._connections["router3"]["device"],
            devices_by_host["1.1.1.3"],
        )

    @patch("jmcp.Config")
    @patch("jmcp.Device")
    def test_dry_run_rollback_failure_evicts_session(
        self, mock_device_cls, mock_config_cls
    ):
        # If the dry-run rollback fails, the pooled session still holds the
        # uncommitted candidate config — it must be evicted, not reused.
        mock_device = MagicMock()
        mock_device.connected = True

        def _close():
            mock_device.connected = False

        mock_device.close.side_effect = _close
        mock_device_cls.return_value = mock_device

        cu = _make_cu()
        cu.rollback.side_effect = RuntimeError("rollback failed")
        mock_config_cls.return_value = _make_config_cm(cu)

        result = _run(_apply_args(dry_run=True))

        self.assertIn(
            "❌ router1: Failed to apply configuration: rollback failed",
            result[0].text,
        )
        mock_device.close.assert_called()
        self.assertIsNone(jmcp.connection_pool._connections["router1"]["device"])

    @patch("jmcp.Config")
    @patch("jmcp.Device")
    def test_no_diff_reports_no_changes_and_skips_commit(
        self, mock_device_cls, mock_config_cls
    ):
        mock_device = MagicMock()
        mock_device.connected = True
        mock_device_cls.return_value = mock_device
        cu = _make_cu(diff=None)
        mock_config_cls.return_value = _make_config_cm(cu)

        result = _run(_apply_args())

        self.assertIn("No configuration changes detected", result[0].text)
        cu.commit.assert_not_called()

    @patch("jmcp.Config")
    @patch("jmcp.Device")
    def test_failed_commit_check_rolls_back_without_commit(
        self, mock_device_cls, mock_config_cls
    ):
        mock_device = MagicMock()
        mock_device.connected = True
        mock_device_cls.return_value = mock_device
        cu = _make_cu()
        cu.commit_check.return_value = False
        mock_config_cls.return_value = _make_config_cm(cu)

        result = _run(_apply_args())

        self.assertIn(
            "❌ router1: Commit check failed - configuration has errors",
            result[0].text,
        )
        cu.rollback.assert_called_once()
        cu.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
