"""Offline regressions: python3 -m unittest discover -s session-canvas -v."""
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

import canvas
import client_hooks
import install_clients


class ClientHooksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "state"

    def tearDown(self):
        self.temp.cleanup()

    def state(self, client):
        return canvas.read_json(canvas.task_dir(self.root, client + ":same-id") / "state.json")

    def enable(self, client):
        canvas.mutate(self.root, client + ":same-id", lambda state: state.update(enabled=True))

    def test_session_start_injects_identity_without_creating_state(self):
        claude = client_hooks.handle(self.root, "claude", "SessionStart", {"session_id": "same-id"})
        cursor = client_hooks.handle(self.root, "cursor", "sessionStart", {"conversation_id": "same-id", "session_id": "wrong-id", "source": "resume"})
        self.assertIn("--client claude --session-id same-id", claude["hookSpecificOutput"]["additionalContext"])
        self.assertIn("--client cursor --session-id same-id", cursor["additional_context"])
        self.assertEqual(cursor["env"]["LIVE_CANVAS_SESSION_ID"], "same-id")
        self.assertFalse(self.root.exists())

    def test_cursor_session_start_accepts_documented_session_id_fallback(self):
        result = client_hooks.handle(self.root, "cursor", "sessionStart", {"session_id": "same-id", "source": "resume"})
        self.assertEqual(result["env"]["LIVE_CANVAS_SESSION_ID"], "same-id")
        self.assertIn("--session-id same-id", result["additional_context"])
        self.assertFalse(self.root.exists())

    def test_realistic_final_messages_are_isolated_and_exclude_private_fields(self):
        self.enable("claude")
        self.enable("cursor")
        claude = {"session_id": "same-id", "hook_event_name": "Stop", "stop_hook_active": False,
                  "last_assistant_message": "Claude result", "transcript_path": "/private/transcript.jsonl",
                  "tool_response": "PRIVATE TOOL RESULT", "thinking": "PRIVATE THOUGHT"}
        cursor = {"conversation_id": "same-id", "generation_id": "turn-one", "hook_event_name": "afterAgentResponse",
                  "text": "Cursor result", "workspace_roots": ["/project"], "thought": "PRIVATE THOUGHT"}
        self.assertEqual(client_hooks.handle(self.root, "claude", "Stop", claude), {})
        self.assertEqual(client_hooks.handle(self.root, "cursor", "afterAgentResponse", cursor), {})
        self.assertEqual(self.state("claude")["automatic"]["latest_final"]["text"], "Claude result")
        self.assertEqual(self.state("cursor")["automatic"]["latest_final"]["text"], "Cursor result")
        self.assertNotIn("PRIVATE", json.dumps(self.state("claude")) + json.dumps(self.state("cursor")))
        client_hooks.handle(self.root, "claude", "Stop", claude)
        client_hooks.handle(self.root, "cursor", "afterAgentResponse", cursor)
        self.assertEqual(len(self.state("claude")["feed"]), 1)
        self.assertEqual(len(self.state("cursor")["feed"]), 1)
        cursor["generation_id"] = "turn-two"
        client_hooks.handle(self.root, "cursor", "afterAgentResponse", cursor)
        self.assertEqual(len(self.state("cursor")["feed"]), 2)

    def test_only_enabled_sessions_receive_signals_or_messages(self):
        client_hooks.handle(self.root, "claude", "Stop", {"session_id": "same-id", "last_assistant_message": "Ignored"})
        self.assertFalse(self.root.exists())
        self.enable("cursor")
        canvas.update_content(self.root, "cursor:same-id", {"current": "Authored work"})
        for event in ("beforeSubmitPrompt", "postToolUse", "stop"):
            client_hooks.handle(self.root, "cursor", event, {"conversation_id": "same-id", "text": "PRIVATE", "tool_output": "PRIVATE"})
        state = self.state("cursor")
        self.assertEqual(state["activity"]["phase"], "idle")
        self.assertEqual(state["content"]["current"], "Authored work")
        self.assertNotIn("PRIVATE", json.dumps(state))
        self.assertEqual(state["feed"], [])
        canvas.mutate(self.root, "cursor:same-id", lambda item: item.update(enabled=False))
        before = self.state("cursor")
        client_hooks.handle(self.root, "cursor", "afterAgentResponse", {"conversation_id": "same-id", "text": "Ignored"})
        self.assertEqual(self.state("cursor"), before)

    def test_thought_unknown_and_mismatched_events_are_ignored(self):
        self.enable("cursor")
        before = self.state("cursor")
        for event, reported in (("afterAgentThought", "afterAgentThought"), ("afterAgentResponse", "stop")):
            client_hooks.handle(self.root, "cursor", event, {"conversation_id": "same-id", "hook_event_name": reported, "text": "PRIVATE"})
        self.assertEqual(self.state("cursor"), before)

    def test_hook_process_is_fail_open_on_malformed_and_oversized_input(self):
        script = Path(client_hooks.__file__)
        for raw in (b"not json", b"[]", b'{"session_id":"../../bad"}', b" " * (canvas.MAX_INPUT + 1)):
            result = subprocess.run([sys.executable, str(script), "--home", str(self.root), "--client", "claude", "--event", "Stop"],
                                    input=raw, capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(result.stderr, b"")
        self.assertFalse(self.root.exists())

    def test_wrapper_explicit_client_overrides_inherited_codex_identity(self):
        wrapper = Path(client_hooks.__file__).resolve().parents[1] / "live-canvas/scripts/live_canvas.py"
        for client in ("claude", "cursor"):
            with patch.dict(os.environ, {"CODEX_THREAD_ID": "inherited-codex-id"}, clear=True), \
                 patch.object(sys, "argv", [str(wrapper), "--client", client, "--session-id", "same-id", "start"]), \
                 patch("os.execv") as execute:
                runpy.run_path(str(wrapper), run_name="__main__")
            forwarded = execute.call_args.args[1]
            self.assertEqual(forwarded[-2:], ["--thread", client + ":same-id"])
            self.assertNotIn("--transcript", forwarded)
            self.assertNotIn("inherited-codex-id", forwarded)

    def test_wrapper_session_environment_does_not_add_thread_to_shutdown(self):
        wrapper = Path(client_hooks.__file__).resolve().parents[1] / "live-canvas/scripts/live_canvas.py"
        with patch.dict(os.environ, {"LIVE_CANVAS_CLIENT": "cursor", "LIVE_CANVAS_SESSION_ID": "same-id"}, clear=True), \
             patch.object(sys, "argv", [str(wrapper), "shutdown", "--help"]), \
             patch("os.execv") as execute:
            runpy.run_path(str(wrapper), run_name="__main__")
        self.assertEqual(execute.call_args.args[1][-2:], ["shutdown", "--help"])
        self.assertNotIn("--thread", execute.call_args.args[1])


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_install(self, action, client="both"):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return install_clients.main([action, "--user-home", str(self.root), "--client", client])

    def write_config(self, client, value):
        base = self.root / (".claude" if client == "claude" else ".cursor")
        path = base / ("settings.json" if client == "claude" else "hooks.json")
        canvas.atomic_json(path, value)
        return path

    def test_dry_run_and_check_are_read_only(self):
        self.assertEqual(self.run_install("dry-run"), 0)
        self.assertEqual(self.run_install("check"), 1)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_install_is_idempotent_and_uninstall_preserves_unrelated_edits(self):
        existing = {"model": "unchanged", "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "existing-start"}]}]}}
        path = self.write_config("claude", existing)
        before = path.read_bytes()
        self.assertEqual(self.run_install("install"), 0)
        self.assertEqual(self.run_install("check"), 0)
        installed_bytes = path.read_bytes()
        self.assertEqual(self.run_install("install"), 0)
        self.assertEqual(path.read_bytes(), installed_bytes)
        backups = list((path.parent / ".live-canvas-backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        edited = json.loads(installed_bytes)
        edited["other_setting"] = True
        edited["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "new-stop"}]})
        canvas.atomic_json(path, edited)
        self.assertEqual(self.run_install("uninstall"), 0)
        remaining = json.loads(path.read_text())
        self.assertEqual(remaining["model"], "unchanged")
        self.assertTrue(remaining["other_setting"])
        self.assertEqual(remaining["hooks"]["SessionStart"], existing["hooks"]["SessionStart"])
        self.assertEqual(remaining["hooks"]["Stop"], [{"hooks": [{"type": "command", "command": "new-stop"}]}])
        self.assertFalse((self.root / ".claude/skills/live-canvas").exists())
        self.assertFalse((self.root / ".cursor/hooks.json").exists())
        self.assertEqual(self.run_install("uninstall"), 0)

    def test_existing_canvas_skill_and_cursor_settings_survive(self):
        old = self.root / ".claude/skills/canvas/SKILL.md"
        old.parent.mkdir(parents=True)
        old.write_text("Existing canvas skill")
        original = {"version": 1, "hooks": {"sessionStart": [{"command": "original"}]}, "other": True}
        path = self.write_config("cursor", original)
        self.assertEqual(self.run_install("install"), 0)
        self.assertTrue((self.root / ".cursor/skills/live-canvas").is_symlink())
        self.assertEqual(self.run_install("uninstall"), 0)
        self.assertEqual(json.loads(path.read_text()), original)
        self.assertEqual(old.read_text(), "Existing canvas skill")

    def test_collision_on_second_client_prevents_all_mutations(self):
        collision = self.root / ".cursor/skills/live-canvas"
        collision.mkdir(parents=True)
        (collision / "SKILL.md").write_text("User skill")
        self.assertEqual(self.run_install("install"), 1)
        self.assertFalse((self.root / ".claude").exists())
        self.assertEqual((collision / "SKILL.md").read_text(), "User skill")

    def test_edited_owned_hook_and_symlinked_config_are_refused(self):
        self.assertEqual(self.run_install("install", "claude"), 0)
        path = self.root / ".claude/settings.json"
        config = json.loads(path.read_text())
        config["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 8
        canvas.atomic_json(path, config)
        before = path.read_bytes()
        self.assertEqual(self.run_install("uninstall", "claude"), 1)
        self.assertEqual(path.read_bytes(), before)
        target = self.root / "external.json"
        target.write_text("{}")
        path.unlink()
        path.symlink_to(target)
        self.assertEqual(self.run_install("install", "claude"), 1)
        self.assertEqual(target.read_text(), "{}")


if __name__ == "__main__":
    unittest.main()
