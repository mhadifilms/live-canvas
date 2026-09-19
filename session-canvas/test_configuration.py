"""Clean-user onboarding, secret boundaries and live configuration regressions."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import auto_open
import canvas
import configuration
import install_clients
import setup
import typesafe_presentation as adaptive


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "runtime"
        self.user_home = Path(self.temp.name) / "user"
        self.env = patch.dict("os.environ", {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def cli(self, *args, stdin=""):
        output = io.StringIO()
        with patch.object(setup, "DEFAULT_ROOT", self.root), patch("sys.stdin", io.StringIO(stdin)), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output), \
             patch.object(adaptive.urllib.request, "build_opener", side_effect=AssertionError("No network during configuration")):
            code = setup.main([*args, "--home", str(self.root), "--user-home", str(self.user_home)])
        return code, output.getvalue()

    def install(self, *extra):
        return self.cli("setup", "--client", "cursor", "--typesafe", "off", "--auto-open", "on", *extra)

    def test_clean_home_only_selected_clients_and_repeat_preserves_unrelated_hooks(self):
        cursor = self.user_home / ".cursor" / "hooks.json"
        unrelated = {"version": 1, "hooks": {"stop": [{"command": "unrelated-command"}]}}
        canvas.atomic_json(cursor, unrelated)
        code, output = self.install()
        self.assertEqual(code, 0, output)
        self.assertFalse((self.user_home / ".claude").exists())
        self.assertFalse((self.user_home / ".codex").exists())
        self.assertTrue(install_clients.plan(self.user_home, "cursor")["installed"])
        installed = cursor.read_bytes()
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(cursor.read_bytes(), installed)
        self.assertIn(unrelated["hooks"]["stop"][0], json.loads(installed)["hooks"]["stop"])
        self.assertIn("requires_host_verification", output)
        self.assertEqual(configuration.status(self.root)["clients"], ["cursor"])

    def test_collision_preflight_never_saves_secret_or_installs_other_target(self):
        collision = self.user_home / ".cursor" / "skills" / "live-canvas"
        collision.mkdir(parents=True)
        code, output = self.cli("setup", "--client", "claude", "--client", "cursor", "--typesafe", "on", "--auto-open", "on", "--api-key-stdin", stdin="secret-fixture\n")
        self.assertEqual(code, 1)
        self.assertNotIn("secret-fixture", output)
        self.assertFalse(configuration.location(self.root).exists())
        self.assertFalse((self.user_home / ".claude").exists())
        self.assertTrue(collision.is_dir())

    def test_key_save_permissions_redaction_remove_and_budget_preserved(self):
        ledger = {"day": adaptive.utc_day(), "calls": 7, "input_bytes": 8000, "cache": {}}
        canvas.atomic_json(self.root / "typesafe-budget.json", ledger)
        code, output = self.cli("configure", "--typesafe", "on", "--api-key-stdin", "--daily-calls", "100", stdin="secret-fixture\n")
        self.assertEqual(code, 0, output)
        self.assertNotIn("secret-fixture", output)
        path = configuration.location(self.root)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(adaptive.config(root=self.root)["key"], "secret-fixture")
        self.assertEqual(adaptive.config(root=self.root)["daily_bytes"], 600000)
        self.assertEqual(self.cli("status")[0], 0)
        self.assertNotIn("secret-fixture", self.cli("status")[1])
        self.assertEqual(self.cli("configure", "--remove-key")[0], 0)
        self.assertNotIn("api_key", configuration.load(self.root))
        self.assertFalse(adaptive.config(root=self.root)["enabled"])
        self.assertEqual(canvas.read_json(self.root / "typesafe-budget.json"), ledger)

    def test_environment_precedence_never_copies_key(self):
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "environment-secret", "LIVE_CANVAS_TYPESAFE_DAILY_CALLS": "3"}):
            code, output = self.cli("configure", "--typesafe", "on", "--daily-calls", "20")
            self.assertEqual(code, 0, output)
            self.assertNotIn("environment-secret", output)
            self.assertNotIn("api_key", configuration.load(self.root))
            self.assertEqual(configuration.effective(self.root)["key_source"], "environment")
            configuration.update(self.root, {"api_key": "saved-secret"})
            self.assertEqual(adaptive.config(root=self.root)["key"], "environment-secret")
            self.assertEqual(adaptive.config(root=self.root)["daily_calls"], 3)
        self.assertEqual(adaptive.config(root=self.root)["key"], "saved-secret")
        self.assertEqual(adaptive.config(root=self.root)["daily_calls"], 20)

    def test_invalid_limits_and_missing_key_leave_prior_config_unchanged(self):
        configuration.update(self.root, {"auto_open": False})
        original = configuration.location(self.root).read_bytes()
        for args in (("--daily-calls", "10001"), ("--daily-bytes", "-1"), ("--typesafe", "on"), ("--api-key-stdin",)):
            code, _ = self.cli("configure", *args)
            self.assertEqual(code, 1)
            self.assertEqual(configuration.location(self.root).read_bytes(), original)
        self.assertEqual(self.cli("setup", "--non-interactive")[0], 1)
        self.assertEqual(self.cli("configure")[0], 1)  # No hanging prompt without a terminal.

    def test_hot_reload_toggles_and_rotation_invalidate_inflight_decisions(self):
        configuration.update(self.root, {"api_key": "first-key", "typesafe": True, "auto_open": False})
        before = adaptive.config(root=self.root)
        self.assertFalse(auto_open.enabled(self.root))
        auto_open.preference(self.root, True)
        self.assertTrue(auto_open.enabled(self.root))
        configuration.update(self.root, {"api_key": "second-key"})
        self.assertEqual(adaptive.config(root=self.root)["key"], "second-key")
        self.assertFalse(adaptive.still_current(self.root, before))
        before = adaptive.config(root=self.root)
        adaptive.preference(self.root, "off")
        adaptive.preference(self.root, "on")
        self.assertFalse(adaptive.still_current(self.root, before))
        configuration.update(self.root, {"daily_calls": 0})
        self.assertEqual(adaptive.config(root=self.root)["daily_calls"], 0)

    def test_symlink_or_loose_configuration_is_refused_without_leaking_key(self):
        configuration.update(self.root, {"api_key": "secret-fixture"})
        path = configuration.location(self.root)
        path.chmod(0o644)
        code, output = self.cli("status")
        self.assertEqual(code, 1)
        self.assertNotIn("secret-fixture", output)
        self.assertFalse(auto_open.enabled(self.root))
        path.chmod(0o600)
        path.unlink()
        target = Path(self.temp.name) / "elsewhere"
        target.write_text('{}')
        path.symlink_to(target)
        self.assertEqual(self.cli("configure", "--auto-open", "on")[0], 1)
        self.assertEqual(target.read_text(), '{}')

    def test_guided_abort_preserves_everything_and_hidden_key_warning_aborts(self):
        # Reject an echoed getpass fallback even on a terminal-like fixture.
        def warning(*args):
            import warnings
            warnings.warn("Cannot control echo", setup.getpass.GetPassWarning)
        with patch("builtins.input", side_effect=["cursor", "yes", "yes", "yes", "change"]), \
             patch.object(setup.getpass, "getpass", side_effect=warning):
            with self.assertRaises(setup.getpass.GetPassWarning):
                setup.wizard(self.root, True)
        self.assertFalse(configuration.location(self.root).exists())
        with patch("builtins.input", side_effect=["cursor", "no", "no", "no", "keep", "", "", "no"]):
            with self.assertRaisesRegex(ValueError, "Cancelled"):
                setup.wizard(self.root, True)
        self.assertFalse(configuration.location(self.root).exists())
        self.assertFalse(self.user_home.exists())

    def test_worker_recovers_after_bad_configuration_without_network(self):
        configuration.update(self.root, {"api_key": "key", "typesafe": True})
        path = configuration.location(self.root)
        valid = path.read_text()
        path.write_text("malformed")
        class Stop:
            ticks = 0
            def is_set(self): return self.ticks >= 2
            def wait(self, _):
                path.write_text(valid)
                self.ticks += 1
        with patch.object(adaptive, "process", side_effect=AssertionError("No authored task")):
            adaptive.run(self.root, Stop())
        status = canvas.read_json(self.root / "typesafe-runtime.json")
        self.assertTrue(status["enabled"])
        self.assertFalse(status["configuration_error"])


if __name__ == "__main__":
    unittest.main()
