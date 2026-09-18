"""TypeSafe fixtures use injected responses; no network requests or real keys."""
import copy
import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import canvas
import typesafe_presentation as adaptive


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.thread = "private-session-id"
        self.settings = {"enabled": True, "key": "fixture-secret-key", "daily_calls": 12, "daily_bytes": 48000, "retry": 0}
        canvas.mutate(self.root, self.thread, lambda state: state.update(enabled=True))
        canvas.update_content(self.root, self.thread, {"title": "Review quiz", "current": "Practice the weaker topic", "sections": [
            {"id": "first", "title": "Overview", "blocks": [{"id": "private-block-id", "type": "text", "text": "Known material"}]},
            {"id": "second", "title": "Practice", "blocks": [{"id": "practice", "type": "reveal", "items": [{"id": "question-one", "prompt": "Example question", "answer": "Example answer"}]}]}]})

    def tearDown(self):
        self.temp.cleanup()

    def state(self):
        return canvas.read_json(canvas.task_dir(self.root, self.thread) / "state.json")

    def answer(self, body=None, key=None):
        return {"answers": {"presentation": {"type": "choice", "choice": "section_1", "confidence": 0.9,
                "probabilities": {"unchanged": 0.05, "section_0": 0.05, "section_1": 0.9}}}}

    def test_macos_system_ca_fallback_preserves_explicit_trust_configuration(self):
        with patch.object(adaptive.ssl, "create_default_context") as create, \
             patch.object(adaptive.ssl, "get_default_verify_paths", return_value=SimpleNamespace(cafile=None, capath=None)), \
             patch.object(adaptive.sys, "platform", "darwin"), patch.object(adaptive.Path, "is_file", return_value=True), \
             patch.dict("os.environ", {}, clear=True):
            context = adaptive.tls_context()
            self.assertIs(context, create.return_value)
            context.load_verify_locations.assert_called_once_with(cafile="/etc/ssl/cert.pem")
            context.reset_mock()
            with patch.dict("os.environ", {"SSL_CERT_FILE": "/explicit/trust.pem"}):
                adaptive.tls_context()
            context.load_verify_locations.assert_not_called()
            with patch.object(adaptive.ssl, "get_default_verify_paths", return_value=SimpleNamespace(cafile="/configured/trust.pem", capath=None)):
                adaptive.tls_context()
            context.load_verify_locations.assert_not_called()

    def test_request_is_bounded_and_excludes_observations_and_identifiers(self):
        state = self.state()
        state.update(feed=[{"text": "PRIVATE_FEED"}], history=[{"text": "PRIVATE_HISTORY"}])
        state["content"]["visual_html"] = "PRIVATE_HTML"
        state["content"]["sections"][0]["blocks"][0]["text"] = "😀" * 100000
        body, mapping = adaptive.build_request(state)
        self.assertLessEqual(len(body), adaptive.MAX_INPUT_BYTES)
        for value in ("PRIVATE_FEED", "PRIVATE_HISTORY", "PRIVATE_HTML", self.thread, "private-block-id", "fixture-secret-key"):
            self.assertNotIn(value, body.decode())
        self.assertEqual(mapping, {"section_0": "first", "section_1": "second"})
        self.assertEqual(json.loads(body)["model"], "jev-latest")

    def test_result_is_derived_and_cache_ignores_activity(self):
        before = self.state()
        adaptive.process(self.root, before, self.settings, request=self.answer)
        after = self.state()
        self.assertEqual(after["presentation"]["focus_id"], "second")
        for field in ("content", "history", "curated_at", "content_updated_at"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after["revision"], before["revision"] + 1)
        canvas.ingest(self.root, self.thread, {"kind": "activity", "text": "Working"})
        self.assertEqual(adaptive.source_hash(self.state()), adaptive.source_hash(before))
        with patch.object(adaptive, "evaluate", side_effect=AssertionError("No network")):
            adaptive.process(self.root, self.state(), self.settings, request=lambda *_: self.fail("Cache miss"))
        ledger = canvas.read_json(self.root / "typesafe-budget.json")
        self.assertEqual(ledger["calls"], 1)
        self.assertNotIn(self.settings["key"], json.dumps(ledger))

    def test_stale_and_disabled_inflight_responses_do_not_apply(self):
        before = self.state()
        def changed(*args):
            canvas.update_content(self.root, self.thread, {"current": "A different task"})
            return self.answer()
        adaptive.process(self.root, before, self.settings, request=changed)
        self.assertNotIn("presentation", self.state())
        adaptive.process(self.root, self.state(), self.settings, request=self.answer, is_enabled=lambda: False)
        self.assertNotIn("presentation", self.state())

    def test_authored_change_clears_focus_immediately_but_visual_only_preserves_it(self):
        adaptive.process(self.root, self.state(), self.settings, request=self.answer)
        canvas.update_content(self.root, self.thread, {"visual_title": "Another label"})
        self.assertEqual(self.state()["presentation"]["status"], "focused")
        canvas.update_content(self.root, self.thread, {"current": "New emphasis"})
        self.assertNotIn("presentation", self.state())

    def test_invalid_and_uncertain_outputs_cannot_choose_arbitrary_ids(self):
        _, mapping = adaptive.build_request(self.state())
        response = self.answer()
        response["answers"]["presentation"]["choice"] = "untrusted-id"
        self.assertEqual(adaptive.decision(response, mapping)["status"], "invalid-response")
        response = self.answer()
        response["answers"]["presentation"]["confidence"] = 0.4
        self.assertEqual(adaptive.decision(response, mapping)["status"], "uncertain")
        for malformed in ([], {}, {"answers": []}, {"answers": {"presentation": None}}):
            self.assertEqual(adaptive.decision(malformed, mapping)["status"], "invalid-response")

    def test_daily_reservations_are_atomic_persistent_and_include_failures(self):
        settings = {**self.settings, "daily_calls": 2, "daily_bytes": 200}
        def reserve(index):
            return adaptive.reserve(self.root, str(index), 100, settings, "2026-09-18")[1]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(sum(pool.map(reserve, range(6))), 2)
        ledger = canvas.read_json(self.root / "typesafe-budget.json")
        self.assertEqual((ledger["calls"], ledger["input_bytes"]), (2, 200))
        self.assertFalse(adaptive.reserve(self.root, "new", 1, settings, "2026-09-18")[1])
        self.assertTrue(adaptive.reserve(self.root, "new", 100, settings, "2026-09-19")[1])

    def test_missing_key_offline_and_explicit_retry_fail_open_without_secret_logs(self):
        adaptive.process(self.root, self.state(), {**self.settings, "key": ""}, request=lambda *_: self.fail("No key"))
        self.assertEqual(self.state()["presentation"]["status"], "missing-key")
        def offline(*args):
            raise OSError("fixture-secret-key must never be saved")
        adaptive.process(self.root, self.state(), self.settings, request=offline)
        self.assertEqual(self.state()["presentation"]["status"], "unavailable")
        adaptive.process(self.root, self.state(), self.settings, request=lambda *_: self.fail("Failure must be cached"))
        with patch.dict("os.environ", {}, clear=True):
            adaptive.preference(self.root, "retry")
        adaptive.process(self.root, self.state(), self.settings, request=self.answer)
        self.assertEqual(self.state()["presentation"]["status"], "focused")
        self.assertEqual(canvas.read_json(self.root / "typesafe-budget.json")["calls"], 2)
        for path in self.root.rglob("*.json"):
            self.assertNotIn(self.settings["key"], path.read_text())

    def test_pending_lease_recovers_without_resetting_reserved_budget(self):
        fingerprint = adaptive.source_hash(self.state())
        with patch.object(adaptive.time, "time", return_value=100):
            self.assertTrue(adaptive.reserve(self.root, fingerprint, 100, self.settings, "2026-09-18")[1])
        with patch.object(adaptive.time, "time", return_value=110):
            self.assertFalse(adaptive.reserve(self.root, fingerprint, 100, self.settings, "2026-09-18")[1])
        with patch.object(adaptive.time, "time", return_value=131):
            self.assertTrue(adaptive.reserve(self.root, fingerprint, 100, self.settings, "2026-09-18")[1])
        self.assertEqual(canvas.read_json(self.root / "typesafe-budget.json")["calls"], 2)

    def test_off_clears_focus_and_rechecks_permission_at_commit(self):
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fixture-secret-key"}, clear=True):
            adaptive.preference(self.root, "on")
            adaptive.process(self.root, self.state(), self.settings, request=self.answer)
            adaptive.preference(self.root, "off")
            self.assertNotIn("presentation", self.state())
            canvas.update_content(self.root, self.thread, {"current": "New intent"})
            adaptive.preference(self.root, "on")
            def turn_off(*args):
                adaptive.preference(self.root, "off")
                return self.answer()
            adaptive.process(self.root, self.state(), self.settings, request=turn_off,
                             is_enabled=lambda: adaptive.config(root=self.root)["enabled"])
            self.assertNotIn("presentation", self.state())

    def test_off_between_process_and_locked_commit_cannot_restore_focus(self):
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fixture-secret-key"}, clear=True):
            adaptive.preference(self.root, "on")
            adaptive.process(self.root, self.state(), self.settings, request=self.answer)
            self.assertEqual(self.state()["presentation"]["status"], "focused")
            original_mutate = canvas.mutate
            interrupted = False
            def turn_off_before_lock(*args, **kwargs):
                nonlocal interrupted
                if not interrupted:
                    interrupted = True
                    adaptive.preference(self.root, "off")
                return original_mutate(*args, **kwargs)
            with patch.object(canvas, "mutate", side_effect=turn_off_before_lock):
                adaptive.process(self.root, self.state(), self.settings, request=self.answer,
                                 is_enabled=lambda: adaptive.config(root=self.root)["enabled"])
            self.assertTrue(interrupted)
            self.assertNotIn("presentation", self.state())

    def test_preference_is_opt_in_preserves_other_settings_and_status_never_infers(self):
        canvas.atomic_json(self.root / "preferences.json", {"auto_open": False})
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fixture-secret-key"}, clear=True), patch.object(adaptive, "evaluate", side_effect=AssertionError("No network")):
            self.assertFalse(adaptive.preference(self.root)["enabled"])
            self.assertTrue(adaptive.preference(self.root, "on")["enabled"])
            self.assertFalse(canvas.read_json(self.root / "preferences.json")["auto_open"])
            self.assertFalse(adaptive.preference(self.root, "off")["enabled"])
        with patch.dict("os.environ", {"LIVE_CANVAS_TYPESAFE": "0", "TYPESAFE_API_KEY": "fixture-secret-key"}, clear=True):
            result = adaptive.preference(self.root, "on")
            self.assertFalse(result["enabled"])
            self.assertTrue(result["environment_override"])
            self.assertTrue(result["key_present_in_this_process"])
            self.assertNotIn("fixture-secret-key", json.dumps(result))

    def test_daemon_debounces_and_does_not_run_for_activity_or_refresh(self):
        calls = []
        actions = [lambda: canvas.ingest(self.root, self.thread, {"kind": "activity", "text": "Working"}),
                   lambda: canvas.update_content(self.root, self.thread, {"current": "New focus"}), lambda: None, lambda: None, lambda: None]
        class Stop:
            index = 0
            def is_set(self): return self.index >= len(actions)
            def wait(self, _):
                actions[self.index]()
                self.index += 1
        stopped = Stop()
        def processed(*args, **kwargs):
            calls.append(args[1])
            return True
        # canvas.locked shares the time module; its clock reads must not consume
        # the fixture's debounce timeline.
        with patch.object(adaptive, "config", return_value=self.settings), patch.object(adaptive.time, "monotonic", side_effect=lambda: stopped.index * 4), patch.object(adaptive, "process", side_effect=processed):
            adaptive.run(self.root, stopped)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(adaptive.source_hash(calls[0]), adaptive.source_hash(calls[1]))


if __name__ == "__main__":
    unittest.main()
