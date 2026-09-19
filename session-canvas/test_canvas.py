"""Run with: python3 -m unittest discover -s session-canvas -v"""
import concurrent.futures
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

import canvas


class CanvasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.thread = "thread-one"
        canvas.mutate(self.root, self.thread, lambda s: s.update(enabled=True))

    def tearDown(self):
        self.temp.cleanup()

    def state(self, thread=None):
        return canvas.read_json(canvas.task_dir(self.root, thread or self.thread) / "state.json")

    def test_curated_content_survives_activity_and_other_threads(self):
        canvas.update_content(self.root, self.thread, {"outcome": "Verified result", "decisions": ["Keep files private"]})
        canvas.hook(self.root, self.thread, {"tool_input": "SECRET"}, "PostToolUse")
        canvas.ingest(self.root, self.thread, {"kind": "final", "text": "New response", "event_id": "a"})
        canvas.update_content(self.root, "other-thread", {"outcome": "Separate"})
        state = self.state()
        self.assertEqual(state["content"]["outcome"], "Verified result")
        self.assertEqual(state["content"]["decisions"], ["Keep files private"])
        self.assertNotIn("SECRET", json.dumps(state))
        self.assertEqual(self.state("other-thread")["content"]["outcome"], "Separate")
        self.assertEqual(len(state["history"]), 1)

    def test_disabled_hooks_are_noop_and_duplicates_are_ignored(self):
        canvas.hook(self.root, "missing", {}, "PostToolUse")
        self.assertFalse(canvas.task_dir(self.root, "missing").exists())
        event = {"kind": "commentary", "text": "Reading", "event_id": "same"}
        canvas.ingest(self.root, self.thread, event)
        revision = self.state()["revision"]
        canvas.ingest(self.root, self.thread, event)
        self.assertEqual(self.state()["revision"], revision)
        canvas.mutate(self.root, self.thread, lambda s: s.update(enabled=False))
        revision = self.state()["revision"]
        canvas.hook(self.root, self.thread, {}, "PostToolUse")
        canvas.ingest(self.root, self.thread, {"kind": "final", "text": "Ignored"})
        self.assertEqual(self.state()["revision"], revision)

    def test_concurrent_updates_preserve_all_independent_fields(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(canvas.update_content, self.root, self.thread, {field: [field]})
                       for field in ("decisions", "open", "next")]
            futures += [pool.submit(canvas.ingest, self.root, self.thread,
                        {"kind": "commentary", "text": str(n), "event_id": str(n)}) for n in range(8)]
            for future in futures:
                future.result()
        state = self.state()
        for field in ("decisions", "open", "next"):
            self.assertEqual(state["content"][field], [field])
        self.assertEqual(len(state["feed"]), 8)
        self.assertEqual(len(state["history"]), 3)
        self.assertEqual((canvas.task_dir(self.root, self.thread) / "state.json").stat().st_mode & 0o777, 0o600)

    def transcript(self, events):
        path = self.root / "session.jsonl"
        meta = {"type": "session_meta", "payload": {"id": self.thread}}
        path.write_text("\n".join(json.dumps(e) for e in [meta] + events) + "\n")
        canvas.validate_transcript(path, self.thread)
        canvas.mutate(self.root, self.thread, lambda s: s.update(transcript={"path": str(path), "offset": 0}))
        return path

    def message(self, phase, text, role="assistant", id="a"):
        return {"type": "response_item", "timestamp": "2026-09-18T00:00:00Z", "payload": {
            "type": "message", "role": role, "phase": phase, "id": id,
            "content": [{"type": "output_text", "text": text}]}}

    def test_transcript_restart_dedupe_filters_and_partial_lines(self):
        path = self.transcript([
            self.message("commentary", "Working"), self.message(None, "Private instructions", role="user", id="u"),
            {"type": "response_item", "payload": {"type": "agent_message", "text": "Internal delegation"}},
            {"type": "response_item", "payload": {"type": "function_call", "arguments": "private tool input"}},
            self.message("final_answer", "Done<oai-mem-citation>metadata</oai-mem-citation>", id="b")])
        canvas.follow_once(self.root, self.thread)
        state = self.state()
        self.assertEqual(state["automatic"]["latest_final"]["text"], "Done")
        self.assertEqual(len(state["feed"]), 2)
        self.assertNotIn("Private instructions", json.dumps(state))
        self.assertNotIn("Internal delegation", json.dumps(state))
        self.assertNotIn("private tool input", json.dumps(state))
        canvas.follow_once(self.root, self.thread)
        self.assertEqual(self.state()["revision"], state["revision"])
        message = json.dumps(self.message("commentary", "Another turn", id="c"))
        with path.open("a") as handle:
            handle.write(message[:50])
        canvas.follow_once(self.root, self.thread)
        self.assertEqual(len(self.state()["feed"]), 2)
        with path.open("a") as handle:
            handle.write(message[50:] + "\n")
        canvas.follow_once(self.root, self.thread)
        self.assertEqual(self.state()["automatic"]["latest_commentary"]["text"], "Another turn")
        self.assertEqual(len(self.state()["feed"]), 3)

    def test_mismatched_transcript_rejected(self):
        path = self.transcript([])
        with self.assertRaises(ValueError):
            canvas.validate_transcript(path, "another-thread")

    def test_legacy_state_migrates_without_losing_content(self):
        legacy = self.state()
        legacy["schema"] = 1
        legacy["content"].pop("sections", None)
        legacy["content"].pop("context", None)
        legacy.pop("content_updated_at", None)
        legacy.pop("context_started_at", None)
        legacy["content"]["decisions"] = ["Keep this decision"]
        canvas.atomic_json(canvas.task_dir(self.root, self.thread) / "state.json", legacy)
        canvas.update_content(self.root, self.thread, {"title": "Continued task"})
        state = self.state()
        self.assertEqual(state["schema"], 2)
        self.assertEqual(state["content"]["decisions"], ["Keep this decision"])
        self.assertEqual(state["content"]["sections"], [])
        self.assertIsNone(state["content"]["context"])

    def test_context_switch_clears_stale_content_and_archives_it(self):
        canvas.update_content(self.root, self.thread, {"title": "Feature", "outcome": "Old result",
            "current": "Old work", "visual_html": "<p>Old diagram</p>", "decisions": ["Old decision"],
            "context": {"id": "feature", "label": "Feature"},
            "sections": [{"id": "checks", "title": "Checks", "blocks": [{"id": "status", "type": "text", "text": "Old checks"}]}]})
        canvas.ingest(self.root, self.thread, {"kind": "final", "text": "Old final"})
        canvas.update_content(self.root, self.thread, {"context": {"id": "any-new-objective", "label": "Open-ended topic"},
            "title": "Study", "sections": [], "next": ["Explicit carry-over"]})
        state = self.state()
        for field in ("outcome", "current", "visual_html"):
            self.assertEqual(state["content"][field], "")
        self.assertEqual(state["content"]["decisions"], [])
        self.assertEqual(state["content"]["sections"], [])
        self.assertEqual(state["content"]["next"], ["Explicit carry-over"])
        self.assertIsNone(state["automatic"]["latest_final"])
        self.assertEqual(state["activity"]["phase"], "unknown")
        self.assertEqual(state["history"][0]["reason"], "context switch")
        self.assertEqual(state["history"][0]["content"]["visual_html"], "<p>Old diagram</p>")
        self.assertEqual(state["feed"][0]["text"], "Old final")

    def test_same_context_patch_preserves_sections_and_replace_clears_them(self):
        context = {"id": "workshop", "label": "Workshop"}
        sections = [{"id": "plan", "title": "Plan", "blocks": [{"id": "note", "type": "text", "text": "Useful context"}]}]
        canvas.update_content(self.root, self.thread, {"context": context, "sections": sections, "outcome": "Known result"})
        stamp = self.state()["content_updated_at"]["outcome"]
        canvas.update_content(self.root, self.thread, {"context": {**context, "label": "Workshop planning"}, "current": "Continuing"})
        self.assertEqual(self.state()["content"]["sections"], sections)
        self.assertEqual(self.state()["content_updated_at"]["outcome"], stamp)
        canvas.update_content(self.root, self.thread, {"replace": True, "title": "Fresh version"})
        state = self.state()
        self.assertEqual(state["content"]["context"]["id"], context["id"])
        self.assertEqual(state["content"]["sections"], [])
        self.assertEqual(state["content"]["outcome"], "")
        self.assertEqual(state["history"][0]["reason"], "replacement")

    def test_section_deltas_replace_append_and_remove(self):
        context = {"id": "delta", "label": "Delta"}
        original = [
            {"id": "one", "title": "One", "blocks": [{"id": "a", "type": "text", "text": "old"}]},
            {"id": "two", "title": "Two", "blocks": []},
        ]
        canvas.update_content(self.root, self.thread, {"context": context, "sections": original})
        canvas.update_content(self.root, self.thread, {"upsert_sections": [
            {"id": "one", "title": "One revised", "blocks": []},
            {"id": "three", "title": "Three", "blocks": []},
        ], "remove_sections": ["two"]})
        self.assertEqual([section["id"] for section in self.state()["content"]["sections"]], ["one", "three"])
        self.assertEqual(self.state()["content"]["sections"][0]["title"], "One revised")

    def test_section_delta_rejects_ambiguous_or_invalid_updates_atomically(self):
        section = {"id": "one", "title": "One", "blocks": []}
        canvas.update_content(self.root, self.thread, {"sections": [section]})
        before = self.state()
        invalid = [
            {"sections": [], "upsert_sections": [section]},
            {"upsert_sections": [{"id": "bad", "title": "Bad", "blocks": [{"id": "x", "type": "unknown"}]}]},
            {"remove_sections": ["bad", "bad"]},
            {"remove_sections": ["bad id"]},
        ]
        for patch in invalid:
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):
                    canvas.update_content(self.root, self.thread, patch)
                self.assertEqual(self.state(), before)

    def test_status_summary_is_bounded_and_excludes_large_automatic_fields(self):
        sections = [{"id": "s" + str(i), "title": "Section " + str(i), "blocks": [
            {"id": "b", "type": "text", "text": "x" * 1000}]} for i in range(30)]
        canvas.update_content(self.root, self.thread, {"context": {"id": "summary", "label": "Summary"},
            "current": "Current work", "outcome": "Outcome", "sections": sections,
            "visual_html": "<svg>secret visual</svg>"})
        canvas.ingest(self.root, self.thread, {"kind": "final", "text": "private feed"})
        summary = canvas.status_summary(self.state())
        encoded = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        self.assertLessEqual(len(encoded), canvas.SUMMARY_MAX)
        self.assertTrue(summary["truncated"])
        self.assertNotIn("private feed", encoded)
        self.assertNotIn("visual_html", encoded)
        self.assertEqual(summary["context"]["id"], "summary")

    def test_status_summary_flags_preview_clipping(self):
        canvas.update_content(self.root, self.thread, {"current": "current detail " * 30,
            "sections": [{"id": "s", "title": "Section", "blocks": [
                {"id": "b", "type": "text", "text": "preview detail " * 30}]}]})
        summary = canvas.status_summary(self.state())
        self.assertLessEqual(len(json.dumps(summary, ensure_ascii=False, separators=(",", ":"))), canvas.SUMMARY_MAX)
        self.assertTrue(summary["truncated"])

    def test_status_summary_cli_stdout_is_bounded(self):
        canvas.mutate(self.root, self.thread, lambda s: s.update(
            feed=[{"id": str(i), "kind": "final", "text": "feed-secret" * 500, "at": "now"} for i in range(40)],
            history=[{"content": {"secret": "history-secret" * 500}} for _ in range(20)],
            content={**s["content"], "visual_html": "visual-secret" * 500}))
        result = subprocess.run([sys.executable, str(Path(canvas.__file__)), "--home", str(self.root),
                                 "status", "--thread", self.thread, "--summary"],
                                check=True, capture_output=True, text=True)
        self.assertLessEqual(len(result.stdout.strip()), canvas.SUMMARY_MAX)
        self.assertNotIn("feed-secret", result.stdout)
        self.assertNotIn("history-secret", result.stdout)
        self.assertNotIn("visual-secret", result.stdout)

    def test_summary_long_context_and_identity_terminate_with_bounded_cli_output(self):
        thread = "t" * 6000
        canvas.update_content(self.root, thread, {"context": {"id": "i" * 5000, "label": "l" * 5000}, "current": "x"})
        result = subprocess.run([sys.executable, str(Path(canvas.__file__)), "--home", str(self.root),
                                 "status", "--thread", thread, "--summary"],
                                check=True, capture_output=True, text=True, timeout=3)
        self.assertLessEqual(len(result.stdout.strip()), canvas.SUMMARY_MAX)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["summary"]["truncated"])
        self.assertTrue(payload["metadata_truncated"])
        self.assertIsNone(payload["thread"])
        self.assertEqual(payload["state_file"], str(canvas.task_dir(self.root.resolve(), thread) / "state.json"))

    def test_summary_tiny_budgets_and_long_metadata_are_finite(self):
        snapshot = canvas.initial("t" * 6000)
        snapshot["content"].update(context={"id": "i" * 5000, "label": "l" * 5000}, current="x", outcome="y")
        for budget in (32, 64, 128, 512, canvas.SUMMARY_MAX):
            summary = canvas.status_summary(snapshot, budget)
            self.assertLessEqual(len(json.dumps(summary, ensure_ascii=False, separators=(",", ":"))), budget)
            self.assertTrue(summary["truncated"])
        result = canvas.status_summary_result(snapshot, snapshot["thread"], "/" + "path" * 4000)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))), canvas.SUMMARY_MAX)
        self.assertTrue(result["metadata_truncated"])
        with self.assertRaises(ValueError):
            canvas.status_summary(snapshot, 31)

    def test_old_transcript_backlog_does_not_restore_previous_context(self):
        self.transcript([self.message("final_answer", "Old final", id="old")])
        canvas.update_content(self.root, self.thread, {"context": {"id": "new", "label": "New topic"}})
        # A future boundary makes this independent of the machine's calendar.
        canvas.mutate(self.root, self.thread, lambda s: s.update(context_started_at="2099-01-01T00:00:00+00:00"))
        canvas.follow_once(self.root, self.thread)
        self.assertIsNone(self.state()["automatic"]["latest_final"])
        self.assertGreater(self.state()["transcript"]["offset"], 0)

    def test_all_examples_validate_and_switch_independently(self):
        examples = sorted((Path(canvas.__file__).parent / "examples").glob("*.json"))
        self.assertEqual(len(examples), 6)
        for fixture in examples:
            with self.subTest(fixture=fixture.name):
                patch = json.loads(fixture.read_text())
                canvas.update_content(self.root, self.thread, patch)
                state = self.state()
                self.assertEqual(state["content"]["sections"], patch["sections"])
                self.assertEqual(state["content"]["context"], patch["context"])
                self.assertEqual(state["content"]["outcome"], "")

    def test_invalid_adaptive_updates_are_atomic(self):
        valid = {"id": "note", "type": "text", "text": "A note"}
        invalid_blocks = [
            {"id": "bad", "type": "list", "items": ["Idea"], "selectable": "yes"},
            {"id": "bad", "type": "script", "text": "alert(1)"},
            {"id": "bad", "type": "table", "columns": ["One"], "rows": [["Two", "cells"]]},
            {"id": "bad", "type": "checklist", "items": [{"text": "Check", "checked": "yes"}]},
            {"id": "bad", "type": "reveal", "items": [{"id": "card", "prompt": "Question"}]},
            {"id": "bad", "type": "timeline", "items": [{"label": "Shot", "at": 123}]},
        ]
        before = self.state()
        patches = [{"sections": [{"id": "s", "title": "Section", "blocks": [block]}]} for block in invalid_blocks]
        patches += [{"sections": [{"id": "s", "title": "Section", "blocks": [valid, valid]}]},
                    {"context": {"id": "", "label": "Empty ID"}}, {"replace": "yes"}]
        for patch in patches:
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):
                    canvas.update_content(self.root, self.thread, patch)
                self.assertEqual(self.state(), before)

    def test_selectable_list_is_explicit_and_preserves_authored_items(self):
        block = {"id": "ideas", "type": "list", "selectable": True,
                 "items": ["First direction", "Second direction"]}
        canvas.update_content(self.root, self.thread, {"sections": [{"id": "directions", "title": "Shortlist ideas", "blocks": [block]}]})
        self.assertEqual(self.state()["content"]["sections"][0]["blocks"][0], block)
        before = self.state()
        with self.assertRaises(ValueError):
            canvas.update_content(self.root, self.thread, {"sections": [{"id": "directions", "title": "Ideas", "blocks": [
                {"id": "text", "type": "text", "text": "Not a list", "selectable": True}]}]})
        self.assertEqual(self.state(), before)

    def test_viewer_only_known_paths_and_readonly_requests(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), canvas.make_handler(self.root, "secret", "instance"))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = "/v/secret/" + canvas.key(self.thread) + "/"
        def request(path, method="GET", headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            body = response.read()
            result = response.status, dict(response.getheaders()), body
            connection.close()
            return result
        try:
            status, headers, body = request(base + "state")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["thread"], self.thread)
            self.assertEqual(request(base + "state", headers={"If-None-Match": headers["ETag"]})[0], 304)
            self.assertEqual(request(base)[0], 200)
            for route in ("/", "/canvas.py", "/v/wrong/health", "/v/secret/../server.json", base + "../../server.json", base + "state?file=secret"):
                self.assertEqual(request(route)[0], 404)
            self.assertEqual(request(base + "state", "POST")[0], 405)
            self.assertEqual(request(base + "state", headers={"Host": "attacker.example"})[0], 403)
            self.assertEqual(request(base + "state", headers={"Origin": "https://attacker.example"})[0], 403)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_branded_routes_are_stable_collision_safe_and_task_scoped(self):
        canvas.update_content(self.root, self.thread, {"title": "Quiz review"})
        other = "another-thread"
        canvas.mutate(self.root, other, lambda s: s.update(enabled=True))
        canvas.update_content(self.root, other, {"title": "Quiz review"})
        route = canvas.task_route(self.root, canvas.key(self.thread))
        other_route = canvas.task_route(self.root, canvas.key(other))
        self.assertEqual(route, "/quiz-review")
        self.assertTrue(other_route.startswith("/quiz-review-"))
        self.assertNotEqual(route, other_route)
        # Even deliberately occupied discriminator names cannot replace a route.
        third = "third-thread"
        canvas.mutate(self.root, third, lambda s: s.update(enabled=True))
        canvas.update_content(self.root, third, {"title": "Quiz review"})
        routes = canvas.read_json(self.root / "routes.json")
        for suffix in (canvas.key(third)[:8], canvas.key(third)):
            routes["quiz-review-" + suffix] = "reserved-task"
        canvas.atomic_json(self.root / "routes.json", routes)
        third_route = canvas.task_route(self.root, canvas.key(third))
        self.assertTrue(third_route.endswith("-2"))
        self.assertEqual(canvas.read_json(self.root / "routes.json")["quiz-review-" + canvas.key(third)], "reserved-task")
        canvas.update_content(self.root, self.thread, {"title": "A different title"})
        self.assertEqual(canvas.task_route(self.root, canvas.key(self.thread)), route)
        info = {"port": 60839, "token": "secret"}
        self.assertEqual(canvas.viewer_url(info, self.thread, self.root, hostname="canvas.localhost"),
                         "http://canvas.localhost:60839/quiz-review#auth=" + canvas.task_capability("secret", canvas.key(self.thread)))
        self.assertNotEqual(canvas.task_capability("secret", canvas.key(self.thread)), canvas.task_capability("secret", canvas.key(other)))
        with self.assertRaises(ValueError):
            canvas.viewer_url(info, self.thread, self.root, hostname="evil.localhost")

    def test_clean_routes_authenticate_only_their_task_and_keep_legacy_links(self):
        route = canvas.task_route(self.root, canvas.key(self.thread))
        other = "other-session"
        canvas.mutate(self.root, other, lambda s: s.update(enabled=True))
        other_route = canvas.task_route(self.root, canvas.key(other))
        server = ThreadingHTTPServer(("127.0.0.1", 0), canvas.make_handler(self.root, "secret", "instance"))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        host = "canvas.localhost:" + str(server.server_port)
        credential = canvas.task_capability("secret", canvas.key(self.thread))
        def request(path, method="GET", headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request(method, path, headers={"Host": host, **(headers or {})})
            response = connection.getresponse()
            result = response.status, dict(response.getheaders()), response.read()
            connection.close()
            return result
        auth = {"Origin": "http://" + host, "Authorization": "Bearer " + credential}
        try:
            shell = request(route)
            self.assertEqual(shell[0], 200)
            self.assertNotIn(self.thread.encode(), shell[2])
            self.assertEqual(request(route + "/state")[0], 403)
            self.assertEqual(request(route + "/archive")[0], 403)
            self.assertEqual(request(route + "/chat.json")[0], 403)
            self.assertEqual(request(route + "/_auth", "POST", {"Authorization": auth["Authorization"]})[0], 403)
            self.assertEqual(request(route + "/_auth", "POST", {**auth, "Origin": "http://evil.localhost"})[0], 403)
            self.assertEqual(request(route + "/_auth", "POST", {**auth, "Sec-Fetch-Site": "cross-site"})[0], 403)
            self.assertEqual(request(other_route + "/_auth", "POST", auth)[0], 403)
            response = request(route + "/_auth", "POST", auth)
            self.assertEqual(response[0], 204)
            cookie_header = response[1]["Set-Cookie"]
            self.assertIn("HttpOnly", cookie_header)
            self.assertIn("SameSite=Strict", cookie_header)
            self.assertIn("Path=" + route + ";", cookie_header)
            self.assertNotIn("Domain=", cookie_header)
            cookie = cookie_header.split(";", 1)[0]
            authenticated = {"Cookie": cookie}
            self.assertEqual(request(route + "/archive", headers=authenticated)[0], 200)
            self.assertEqual(request(route + "/chat.json", headers=authenticated)[0], 200)
            self.assertEqual(request(other_route + "/archive", headers=authenticated)[0], 403)
            self.assertEqual(request(route + "/board.excalidraw", headers=authenticated)[0], 404)
            state = request(route + "/state", headers=authenticated)
            self.assertEqual(state[0], 200)
            self.assertEqual(json.loads(state[2])["thread"], self.thread)
            self.assertEqual(request(route + "/state", headers={**authenticated, "If-None-Match": state[1]["ETag"]})[0], 304)
            self.assertEqual(request(other_route + "/state", headers=authenticated)[0], 403)
            self.assertEqual(request(route + "/state", headers={"Cookie": cookie + "; " + cookie})[0], 403)
            self.assertEqual(request(route + "/state", headers={"Host": "evil.localhost:" + str(server.server_port), **authenticated})[0], 403)
            self.assertEqual(request(route + "/state", headers={"Origin": "http://localhost:" + str(server.server_port), **authenticated})[0], 403)
            for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
                self.assertEqual(request(route + "/state", method, authenticated)[0], 405)
            self.assertEqual(request(route + "/_auth", "PUT", auth)[0], 405)
            self.assertEqual(request(route + "/state?file=server.json", headers=authenticated)[0], 404)
            for alias in canvas.VIEWER_HOSTS:
                self.assertEqual(request(route, headers={"Host": alias + ":" + str(server.server_port)})[0], 200)
            legacy = request("/v/secret/" + canvas.key(self.thread) + "/")
            self.assertEqual(legacy[0], 200)
            self.assertEqual(legacy[1]["Set-Cookie"], cookie_header)
            self.assertIn(('data-canvas-route="' + route + '"').encode(), legacy[2])
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
