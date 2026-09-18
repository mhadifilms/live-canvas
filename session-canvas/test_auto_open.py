"""Automatic-opening fixtures never launch a browser, server, or model."""
import concurrent.futures
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import auto_open
import canvas
import client_hooks
import install_clients


class AutoOpenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "state"
        self.thread = "codex-session"

    def tearDown(self):
        self.temp.cleanup()

    def state(self):
        return canvas.read_json(canvas.task_dir(self.root, self.thread) / "state.json")

    def test_foreground_start_only_and_defensive_background_opt_outs(self):
        for client in ("codex", "claude", "cursor"):
            self.assertTrue(auto_open.foreground_start(client, {"source": "startup", "agent_type": "custom-main"}))
            for source in ("resume", "clear", "compact", "fork"):
                self.assertFalse(auto_open.foreground_start(client, {"source": source}))
            for field in ("is_background_agent", "is_subagent", "noninteractive", "non_interactive"):
                self.assertFalse(auto_open.foreground_start(client, {"source": "startup", field: True}))
            self.assertFalse(auto_open.foreground_start(client, {"source": "startup", "interactive": False}))
            self.assertFalse(auto_open.foreground_start(client, {"source": "startup", "parent_session_id": "parent"}))
        self.assertTrue(auto_open.foreground_start("cursor", {}))
        self.assertFalse(auto_open.foreground_start("codex", {}))
        self.assertFalse(auto_open.foreground_start("claude", {}))

    def test_concurrent_startup_and_claims_allow_only_one_open(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _: auto_open.prepare(self.root, self.thread), range(8)))
            attempts = list(executor.map(lambda _: auto_open.claim(self.root, self.thread), range(8)))
        winners = [item for item in attempts if item["should_open"]]
        self.assertEqual(len(winners), 1)
        self.assertTrue(auto_open.settle(self.root, self.thread, winners[0]["claim"], opened=True)["acknowledged"])
        self.assertFalse(auto_open.prepare(self.root, self.thread))
        self.assertFalse(auto_open.claim(self.root, self.thread)["should_open"])
        self.assertTrue(auto_open.prepare(self.root, "different-session"))
        self.assertTrue(auto_open.claim(self.root, "different-session")["should_open"])

    def test_stopped_and_opted_out_sessions_do_not_reopen(self):
        auto_open.prepare(self.root, self.thread)
        token = auto_open.claim(self.root, self.thread)["claim"]
        canvas.mutate(self.root, self.thread, lambda state: state.update(enabled=False))
        self.assertFalse(auto_open.prepare(self.root, self.thread))
        self.assertFalse(auto_open.claim(self.root, self.thread)["should_open"])
        with patch("subprocess.run") as process:
            self.assertFalse(auto_open.settle(self.root, self.thread, token, opened=True,
                                             opener=lambda: process())["acknowledged"])
        process.assert_not_called()
        auto_open.preference(self.root, False)
        self.assertFalse(auto_open.prepare(self.root, "new-session"))
        self.assertFalse(canvas.task_dir(self.root, "new-session").exists())
        auto_open.preference(self.root, True)
        self.assertFalse(auto_open.prepare(self.root, self.thread))

    def test_failure_release_and_expired_claim_allow_retry(self):
        auto_open.prepare(self.root, self.thread)
        token = auto_open.claim(self.root, self.thread)["claim"]
        self.assertFalse(auto_open.settle(self.root, self.thread, "wrong-token", opened=True)["acknowledged"])
        self.assertTrue(auto_open.settle(self.root, self.thread, token)["acknowledged"])
        token = auto_open.claim(self.root, self.thread)["claim"]
        canvas.mutate(self.root, self.thread, lambda state: state["auto_open"]["claim"].update(expires=0))
        self.assertFalse(auto_open.settle(self.root, self.thread, token, opened=True)["acknowledged"])
        self.assertTrue(auto_open.claim(self.root, self.thread)["should_open"])

    def test_codex_native_context_keeps_raw_identity_and_no_os_worker(self):
        payload = {"session_id": self.thread, "source": "startup", "transcript_path": "/unused/transcript"}
        with patch("auto_open.launch") as launch:
            response = client_hooks.handle(self.root, "codex", "SessionStart", payload)
        launch.assert_not_called()
        context = response["hookSpecificOutput"]["additionalContext"]
        self.assertIn("--client codex --session-id codex-session", context)
        self.assertIn("mcp__codex_app__open_in_codex", context)
        self.assertIn("placement right", context)
        self.assertIn("auto-open claim", context)
        self.assertIn("auto-open opened --claim", context)
        self.assertEqual(self.state()["thread"], self.thread)
        self.assertFalse(canvas.task_dir(self.root, "codex:" + self.thread).exists())
        token = auto_open.claim(self.root, self.thread)["claim"]
        auto_open.settle(self.root, self.thread, token, opened=True)
        repeated = client_hooks.handle(self.root, "codex", "SessionStart", payload)
        self.assertNotIn("first user turn", repeated["hookSpecificOutput"]["additionalContext"])

    def test_cursor_native_start_and_claude_detached_worker_use_no_followups(self):
        with patch("subprocess.Popen") as process:
            claude = client_hooks.handle(self.root, "claude", "SessionStart", {"session_id": "c", "source": "startup"})
        self.assertEqual(process.call_count, 1)
        argv = process.call_args.args[0]
        self.assertEqual(Path(argv[1]).name, "auto_open.py")
        self.assertEqual(argv[-1], "claude:c")
        self.assertTrue(process.call_args.kwargs["start_new_session"])
        self.assertNotIn("followup_message", json.dumps(claude))
        with patch("auto_open.launch") as launch:
            cursor = client_hooks.handle(self.root, "cursor", "sessionStart", {"conversation_id": "c", "is_background_agent": False})
        launch.assert_not_called()
        self.assertIn("built-in browser", cursor["additional_context"])
        self.assertIn("OS browser", cursor["additional_context"])

    def test_worker_retries_failed_browser_and_deduplicates_success(self):
        auto_open.prepare(self.root, self.thread)
        server = subprocess.CompletedProcess([], 0, stdout=b'{"url":"http://127.0.0.1:4321/view/capability"}')
        failed = subprocess.CalledProcessError(1, ["open"])
        with patch("auto_open.browser_command", return_value=["open", "local-url"]), \
             patch("subprocess.run", side_effect=[server, failed]) as process:
            auto_open.worker(self.root, self.thread)
        self.assertEqual(process.call_count, 2)
        self.assertNotIn("opened_at", self.state().get("auto_open", {}))
        self.assertNotIn("claim", self.state().get("auto_open", {}))
        with patch("auto_open.browser_command", return_value=["open", "local-url"]), \
             patch("subprocess.run", side_effect=[server, subprocess.CompletedProcess([], 0)]) as process:
            auto_open.worker(self.root, self.thread)
            auto_open.worker(self.root, self.thread)
        self.assertEqual(process.call_count, 2)
        self.assertIn("--ensure-server", process.call_args_list[0].args[0])
        self.assertIn("opened_at", self.state()["auto_open"])

    def test_stop_during_worker_server_start_does_not_dispatch_browser(self):
        auto_open.prepare(self.root, self.thread)
        def starting(*args, **kwargs):
            canvas.mutate(self.root, self.thread, lambda state: state.update(enabled=False))
            return subprocess.CompletedProcess([], 0, stdout=b'{"url":"http://127.0.0.1:4321/view/capability"}')
        with patch("auto_open.browser_command", return_value=["open", "local-url"]), \
             patch("subprocess.run", side_effect=starting) as process:
            auto_open.worker(self.root, self.thread)
        self.assertEqual(process.call_count, 1)
        self.assertFalse(self.state()["enabled"])

    def test_guarded_native_start_refuses_stop_without_starting_server(self):
        auto_open.prepare(self.root, self.thread)
        token = auto_open.claim(self.root, self.thread)["claim"]
        canvas.mutate(self.root, self.thread, lambda state: state.update(enabled=False))
        with patch.object(sys, "argv", ["canvas.py", "--home", str(self.root), "start", "--thread", self.thread, "--auto-claim", token]), \
             patch("canvas.ensure_server") as server, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(canvas.main(), 1)
        server.assert_not_called()
        self.assertFalse(self.state()["enabled"])

    def test_wrapper_codex_identity_and_global_toggle(self):
        wrapper = Path(client_hooks.__file__).resolve().parents[1] / "live-canvas/scripts/live_canvas.py"
        for args, expected in ((["--client", "codex", "--session-id", self.thread, "auto-open", "claim"], self.thread),
                               (["auto-open", "off"], None)):
            with patch.dict(os.environ, {"LIVE_CANVAS_CLIENT": "cursor", "LIVE_CANVAS_SESSION_ID": "other-session"}, clear=True), \
                 patch.object(sys, "argv", [str(wrapper), *args]), patch("os.execv") as execute:
                runpy.run_path(str(wrapper), run_name="__main__")
            forwarded = execute.call_args.args[1]
            if expected:
                self.assertEqual(forwarded[-2:], ["--thread", expected])
            else:
                self.assertNotIn("--thread", forwarded)


class AutoInstallTests(unittest.TestCase):
    def test_codex_install_preserves_guards_feature_config_and_preexisting_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / ".codex"
            guard = {"hooks": [{"type": "command", "command": "existing-guard", "timeout": 10}]}
            canvas.atomic_json(base / "hooks.json", {"hooks": {"PostToolUse": [guard]}})
            config = base / "config.toml"
            config.write_text('[features]\nhooks = true\nother = true\n')
            skill = base / "skills/live-canvas"
            skill.parent.mkdir()
            skill.symlink_to(install_clients.SKILL, target_is_directory=True)
            before = config.read_bytes()
            def action(name):
                with contextlib.redirect_stdout(io.StringIO()):
                    return install_clients.main([name, "--user-home", str(root), "--client", "codex"])
            self.assertEqual(action("install"), 0)
            self.assertEqual(action("check"), 0)
            self.assertEqual(json.loads((base / "hooks.json").read_text())["hooks"]["PostToolUse"], [guard])
            self.assertEqual(action("uninstall"), 0)
            self.assertTrue(skill.is_symlink())
            self.assertEqual(config.read_bytes(), before)
            self.assertEqual(json.loads((base / "hooks.json").read_text()), {"hooks": {"PostToolUse": [guard]}})

    def test_schema_one_manifest_upgrades_without_replacing_other_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def action():
                with contextlib.redirect_stdout(io.StringIO()):
                    return install_clients.main(["install", "--user-home", str(root), "--client", "claude"])
            self.assertEqual(action(), 0)
            path = root / ".claude/.live-canvas-install.json"
            manifest = json.loads(path.read_text())
            manifest["schema"] = 1
            manifest["entries"].pop("Stop")
            canvas.atomic_json(path, manifest)
            config_path = root / ".claude/settings.json"
            config = json.loads(config_path.read_text())
            config["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": "other-stop"}]}]
            canvas.atomic_json(config_path, config)
            self.assertEqual(action(), 0)
            updated = json.loads(path.read_text())
            self.assertEqual(updated["schema"], 2)
            self.assertEqual(updated["created_skill"], manifest["created_skill"])
            self.assertEqual(json.loads(config_path.read_text())["hooks"]["Stop"][0], config["hooks"]["Stop"][0])
            self.assertTrue(list((root / ".claude/.live-canvas-backups").glob('.live-canvas-install.json.*')))


if __name__ == "__main__":
    unittest.main()
