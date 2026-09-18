#!/usr/bin/env python3
"""Private, local, dependency-free live canvases for individual Codex threads."""
import argparse
import contextlib
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
MAX_INPUT = 256 * 1024
FIELDS = {"title", "outcome", "current", "decisions", "open", "next", "visual_html", "visual_title", "context", "sections"}
LIST_FIELDS = {"decisions", "open", "next"}
SECTION_DELTA_FIELDS = {"upsert_sections", "remove_sections"}
SUMMARY_MAX = 4000


class HealthUnavailable(RuntimeError):
    def __init__(self, info):
        super().__init__("Loopback health check is blocked by the environment; allow local networking before starting or stopping the server")
        self.info = info


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def display_text(text):
    return re.sub(r"<oai-mem-citation>[\s\S]*?(?:</oai-mem-citation>|$)", "", text).strip()


def home():
    return Path(os.environ.get("SESSION_CANVAS_HOME", str(HERE / ".state"))).expanduser().resolve()


def key(thread):
    return hashlib.sha256(thread.encode()).hexdigest()[:32]


def task_dir(root, thread):
    return root / "tasks" / key(thread)


def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextlib.contextmanager
def locked(path, timeout=5):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT, 0o600), "a+") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Canvas is busy")
                time.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def empty_content():
    return {"title": "Session canvas", "outcome": "", "current": "",
            "decisions": [], "open": [], "next": [], "visual_html": "", "visual_title": "Visual note",
            "context": None, "sections": []}


def initial(thread):
    return {"schema": 2, "thread": thread, "revision": 0, "enabled": False,
            "created_at": now(), "updated_at": None, "curated_at": None,
            "content": empty_content(), "context_started_at": None, "content_updated_at": {},
            "activity": {"phase": "unknown", "label": "Waiting for activity", "at": None},
            "automatic": {"latest_commentary": None, "latest_final": None}, "feed": [], "history": []}


def mutate(root, thread, action, enabled_only=False):
    directory = task_dir(root, thread)
    if enabled_only and not (directory / "state.json").exists():
        return None
    with locked(directory / ".lock", timeout=0.15 if enabled_only else 5):
        state = read_json(directory / "state.json") or initial(thread)
        # Migrate in memory before every write; old snapshots stay readable unchanged.
        state["content"] = {**empty_content(), **state["content"]}
        state.setdefault("context_started_at", None)
        state.setdefault("content_updated_at", {})
        for field in FIELDS:
            state["content_updated_at"].setdefault(field, state.get("curated_at"))
        state["schema"] = 2
        if enabled_only and not state["enabled"]:
            return None
        if action(state) is False:
            return state
        state["revision"] += 1
        state["updated_at"] = now()
        atomic_json(directory / "state.json", state)
        return state


def validate_sections(sections):
    def require(condition, message):
        if not condition:
            raise ValueError("sections: " + message)

    def strings(value):
        return isinstance(value, list) and all(isinstance(item, str) for item in value)

    def identity(value):
        return isinstance(value, str) and bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", value))

    require(isinstance(sections, list) and len(sections) <= 30, "expected up to 30 sections")
    section_ids = set()
    for section in sections:
        require(isinstance(section, dict) and not set(section) - {"id", "title", "blocks"}, "unknown section field")
        require(identity(section.get("id")) and section["id"] not in section_ids, "section IDs must be unique stable identifiers")
        section_ids.add(section["id"])
        require(isinstance(section.get("title"), str), "section title must be a string")
        blocks = section.get("blocks")
        require(isinstance(blocks, list) and len(blocks) <= 30, "expected up to 30 blocks per section")
        block_ids = set()
        for block in blocks:
            require(isinstance(block, dict), "block must be an object")
            require(identity(block.get("id")) and block["id"] not in block_ids, "block IDs must be unique within a section")
            block_ids.add(block["id"])
            kind = block.get("type")
            allowed = {"text": {"text"}, "list": {"items", "ordered"}, "checklist": {"items"},
                       "table": {"columns", "rows"}, "reveal": {"items"}, "timeline": {"items"}}
            require(isinstance(kind, str) and kind in allowed, "unsupported block type")
            require(not set(block) - ({"id", "type"} | allowed[kind]), "unknown block field")
            if kind == "text":
                require(isinstance(block.get("text"), str), "text block needs text")
            elif kind == "list":
                require(strings(block.get("items")), "list needs string items")
                require(isinstance(block.get("ordered", False), bool), "ordered must be boolean")
            elif kind == "table":
                columns, rows = block.get("columns"), block.get("rows")
                require(strings(columns), "table columns must be strings")
                require(isinstance(rows, list) and all(strings(row) and len(row) == len(columns) for row in rows), "table rows must match columns")
            else:
                items = block.get("items")
                require(isinstance(items, list), "block needs items")
                ids = set()
                for item in items:
                    require(isinstance(item, dict), "structured item must be an object")
                    if kind == "checklist":
                        require(not set(item) - {"text", "checked"} and isinstance(item.get("text"), str)
                                and isinstance(item.get("checked", False), bool), "checklist needs text and optional boolean checked")
                    elif kind == "reveal":
                        require(not set(item) - {"id", "prompt", "answer"} and identity(item.get("id")) and item["id"] not in ids
                                and isinstance(item.get("prompt"), str) and isinstance(item.get("answer"), str), "reveal needs unique id, prompt, answer")
                        ids.add(item["id"])
                    else:
                        require(not set(item) - {"label", "detail", "at"} and isinstance(item.get("label"), str)
                                and isinstance(item.get("detail", ""), str) and isinstance(item.get("at", ""), str), "timeline needs label and optional detail/at strings")


def update_content(root, thread, patch):
    if not isinstance(patch, dict) or set(patch) - (FIELDS | SECTION_DELTA_FIELDS | {"replace"}):
        raise ValueError("Update accepts only: " + ", ".join(sorted(FIELDS | SECTION_DELTA_FIELDS | {"replace"})))
    patch = dict(patch)
    replace = patch.pop("replace", False)
    if not isinstance(replace, bool):
        raise ValueError("replace must be boolean")
    whole_sections = "sections" in patch
    delta_sections = bool(SECTION_DELTA_FIELDS & set(patch))
    if whole_sections and delta_sections:
        raise ValueError("sections cannot be combined with section deltas")
    upserts = patch.pop("upsert_sections", None)
    removals = patch.pop("remove_sections", None)
    if upserts is not None:
        validate_sections(upserts)
    if removals is not None:
        if not isinstance(removals, list) or len(removals) > 30 or not all(
                isinstance(item, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", item)
                for item in removals):
            raise ValueError("remove_sections must be an array of section IDs")
        if len(set(removals)) != len(removals):
            raise ValueError("remove_sections IDs must be unique")
    for name, value in patch.items():
        if name == "context":
            if value is not None and (not isinstance(value, dict) or set(value) - {"id", "label", "description"}
                    or not isinstance(value.get("id"), str) or not value["id"].strip()
                    or not isinstance(value.get("label"), str) or not value["label"].strip()
                    or not isinstance(value.get("description", ""), str)):
                raise ValueError("context needs a nonempty id and label, with optional description")
        elif name == "sections":
            validate_sections(value)
        elif name in LIST_FIELDS:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(name + " must be an array of strings")
        elif not isinstance(value, str):
            raise ValueError(name + " must be a string")
    def apply(state):
        old = state["content"]
        switched = "context" in patch and (patch["context"] or {}).get("id") != (old.get("context") or {}).get("id")
        reset = replace or switched
        target = {**empty_content(), "context": old.get("context")} if reset else dict(old)
        target.update(patch)
        if upserts is not None or removals is not None:
            removed = set(removals or [])
            current_sections = [section for section in target.get("sections", []) if section["id"] not in removed]
            positions = {section["id"]: index for index, section in enumerate(current_sections)}
            for section in upserts or []:
                if section["id"] in positions:
                    current_sections[positions[section["id"]]] = section
                else:
                    positions[section["id"]] = len(current_sections)
                    current_sections.append(section)
            validate_sections(current_sections)
            target["sections"] = current_sections
        changed = sorted(name for name, value in target.items() if old.get(name) != value)
        if not changed and not reset:
            return False
        stamp = now()
        state["history"].insert(0, {"at": stamp, "revision": state["revision"] + 1,
            "fields": changed, "reason": "context switch" if switched else "replacement" if replace else "update", "content": old})
        state["history"] = state["history"][:20]
        state["content"] = target
        state["curated_at"] = stamp
        for name in changed:
            state["content_updated_at"][name] = stamp
        if reset:
            state["context_started_at"] = stamp
            state["automatic"] = {"latest_commentary": None, "latest_final": None}
            state["activity"] = {"phase": "unknown", "label": "Context changed", "at": stamp}
    return mutate(root, thread, apply)


def ingest(root, thread, event):
    kind = event.get("kind", "activity")
    if kind not in {"commentary", "final", "activity"}:
        raise ValueError("Feed kind must be commentary, final, or activity")
    text = event.get("text", "")
    if not isinstance(text, str):
        raise ValueError("Feed text must be a string")
    event_id = str(event.get("event_id") or secrets.token_hex(10))[:200]
    def apply(state):
        if any(item["id"] == event_id for item in state["feed"]):
            return False
        item = {"id": event_id, "kind": kind, "text": display_text(text)[:20000],
                "source": str(event.get("source", "event input"))[:160], "at": now()}
        state["feed"].insert(0, item)
        state["feed"] = state["feed"][:40]
        if kind in {"commentary", "final"}:
            state["automatic"]["latest_" + kind] = item
        state["activity"] = {"phase": "idle" if kind == "final" else "observed",
                             "label": "Assistant response received" if kind == "final" else "Activity received", "at": item["at"]}
    return mutate(root, thread, apply, enabled_only=True)


def hook(root, thread, event, event_name=None):
    name = event_name or event.get("hook_event_name") or event.get("event_name") or ""
    labels = {"SessionStart": ("connected", "Session started"),
              "UserPromptSubmit": ("observed", "User prompt received"),
              "PostToolUse": ("observed", "Tool activity received"),
              "Stop": ("idle", "Turn ended")}
    if name not in labels:
        return None
    phase, label = labels[name]
    def apply(state):
        # Deliberately excludes tool arguments, results, prompts, and inferred progress.
        state["activity"] = {"phase": phase, "label": label, "at": now(), "source": name}
    return mutate(root, thread, apply, enabled_only=True)


def validate_transcript(path, thread):
    path = Path(path).expanduser().resolve()
    with path.open("rb") as handle:
        first = handle.readline(256 * 1024)
    meta = json.loads(first)
    payload = meta.get("payload", {})
    if meta.get("type") != "session_meta" or (payload.get("id") or payload.get("session_id")) != thread:
        raise ValueError("Transcript session identity does not match the canvas thread")
    return path


def transcript_item(event, offset):
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        return None
    stamp = event.get("timestamp") or now()
    if event.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "assistant":
        phase = payload.get("phase") or payload.get("channel")
        if phase not in {"commentary", "final_answer", "final"}:
            return None
        text = "\n".join(item.get("text", "") for item in payload.get("content", [])
                         if isinstance(item, dict) and item.get("type") == "output_text")
        if not text.strip():
            return None
        return {"id": str(payload.get("id") or "transcript:" + str(offset)),
                "kind": "commentary" if phase == "commentary" else "final", "text": display_text(text)[:20000],
                "at": stamp, "source": "Task transcript"}
    if event.get("type") == "event_msg" and payload.get("type") in {"task_started", "task_complete"}:
        started = payload["type"] == "task_started"
        return {"kind": "signal", "phase": "observed" if started else "idle",
                "label": "Turn started" if started else "Turn ended", "at": stamp}
    if event.get("type") == "response_item" and payload.get("type") in {"function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output"}:
        return {"kind": "signal", "phase": "observed", "label": "Tool activity received", "at": stamp}
    return None


def follow_once(root, thread):
    snapshot = read_json(task_dir(root, thread) / "state.json", {})
    registration = snapshot.get("transcript")
    if not snapshot.get("enabled") or not registration:
        return
    path = Path(registration["path"])
    try:
        stat = path.stat()
        cursor = registration.get("offset", 0)
        identity = [stat.st_dev, stat.st_ino]
        if registration.get("identity") != identity or cursor > stat.st_size:
            validate_transcript(path, thread)
            cursor = 0
        if cursor == stat.st_size:
            return
        events, end, dropping = [], cursor, registration.get("dropping", False)
        with path.open("rb") as handle:
            handle.seek(cursor)
            for _ in range(120):
                begin = handle.tell()
                line = handle.readline(1024 * 1024)
                if not line:
                    break
                if not line.endswith(b"\n"):
                    if len(line) == 1024 * 1024:
                        dropping = True
                        end = handle.tell()
                        continue
                    break  # A writer is still appending this line.
                end = handle.tell()
                if dropping:
                    dropping = False
                    continue
                try:
                    item = transcript_item(json.loads(line), begin)
                    if item:
                        events.append(item)
                except (ValueError, TypeError, AttributeError):
                    pass
        if end == cursor:
            return
        def apply(state):
            current = state.get("transcript", {})
            if current.get("path") != str(path) or current.get("offset", 0) != registration.get("offset", 0):
                return False
            state["transcript"].update({"offset": end, "identity": identity, "dropping": dropping, "error": None})
            for item in events:
                boundary = state.get("context_started_at")
                if boundary:
                    try:
                        stamp = dt.datetime.fromisoformat(str(item["at"]).replace("Z", "+00:00"))
                        if stamp.tzinfo is None:
                            stamp = stamp.replace(tzinfo=dt.timezone.utc)
                        if stamp < dt.datetime.fromisoformat(boundary):
                            continue  # A backlog from the old context cannot revive its status.
                    except (TypeError, ValueError):
                        continue
                if item["kind"] == "signal":
                    state["activity"] = {"phase": item["phase"], "label": item["label"], "at": item["at"], "source": "Task transcript"}
                    continue
                if any(existing["id"] == item["id"] for existing in state["feed"]):
                    continue
                state["feed"].insert(0, item)
                state["feed"] = state["feed"][:40]
                state["automatic"]["latest_" + item["kind"]] = item
                state["activity"] = {"phase": "idle" if item["kind"] == "final" else "observed",
                    "label": "Assistant response received" if item["kind"] == "final" else "Assistant update received", "at": item["at"], "source": "Task transcript"}
        mutate(root, thread, apply, enabled_only=True)
    except (OSError, ValueError) as exc:
        def mark_error(state):
            message = type(exc).__name__ + ": unable to read registered transcript"
            if state.get("transcript", {}).get("error") == message:
                return False
            state["transcript"]["error"] = message
        mutate(root, thread, mark_error, enabled_only=True)


def follow_loop(root, stopped):
    while not stopped.is_set():
        for path in (root / "tasks").glob("*/state.json"):
            try:
                state = read_json(path, {})
                if state.get("enabled") and state.get("transcript"):
                    follow_once(root, state["thread"])
            except Exception:
                pass  # One unreadable task must not interrupt other canvases.
        stopped.wait(0.8)


def request_json(url):
    # Ignore system HTTP proxies for this loopback-only service.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=0.7) as response:
        return json.load(response)


def running(root):
    info = read_json(root / "server.json")
    if not info:
        return None
    try:
        health = request_json("http://127.0.0.1:%s/v/%s/health" % (int(info["port"]), info["token"]))
        if health.get("instance") == info["instance"]:
            return info
    except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
        cause = getattr(exc, "reason", exc)
        if getattr(cause, "errno", None) in {errno.EPERM, errno.EACCES}:
            raise HealthUnavailable(info) from exc
    return None


def ensure_server(root):
    with locked(root / ".server-start.lock"):
        info = running(root)
        if info:
            return info
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(os.open(root / "server.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as log:
            process = subprocess.Popen([sys.executable, str(HERE / "canvas.py"), "--home", str(root), "_serve"],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True, close_fds=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            info = running(root)
            if info:
                return info
            if process.poll() is not None:
                break
            time.sleep(0.05)
    raise RuntimeError("Server did not start; see " + str(root / "server.log"))


def viewer_url(info, thread):
    return "http://127.0.0.1:%s/v/%s/%s/" % (info["port"], info["token"], key(thread))


def make_handler(root, token, instance):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Capability URLs and task identifiers never go to access logs.

        def send_body(self, status, body=b"", mime="text/plain; charset=utf-8", etag=None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            if etag:
                self.send_header("ETag", etag)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            expected_host = "127.0.0.1:" + str(self.server.server_port)
            if self.headers.get("Host") != expected_host:
                return self.send_body(403)
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + expected_host:
                return self.send_body(403)
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self.send_body(403)
            prefix = "/v/" + token + "/"
            if not self.path.startswith(prefix):
                return self.send_body(404)
            route = self.path[len(prefix):]
            if route == "health":
                return self.send_body(200, json.dumps({"instance": instance}).encode(), "application/json")
            parts = route.split("/")
            if len(parts) != 2 or len(parts[0]) != 32 or any(c not in "0123456789abcdef" for c in parts[0]) or parts[1] not in {"", "state"}:
                return self.send_body(404)
            state = read_json(root / "tasks" / parts[0] / "state.json")
            if not state:
                return self.send_body(404)
            if parts[1] == "":
                return self.send_body(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            etag = '"%s"' % state["revision"]
            if self.headers.get("If-None-Match") == etag:
                return self.send_body(304, etag=etag)
            return self.send_body(200, json.dumps(state, ensure_ascii=False).encode(), "application/json; charset=utf-8", etag)

        do_HEAD = do_GET

        def do_POST(self):
            self.send_body(405, b"Read-only viewer")

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST
        do_OPTIONS = do_POST
    return Handler


def serve(root):
    previous = read_json(root / "viewer.json", {})
    token, instance = previous.get("token") or secrets.token_urlsafe(32), secrets.token_hex(16)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", previous.get("port", 0)), make_handler(root, token, instance))
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root, token, instance))
    atomic_json(root / "viewer.json", {"token": token, "port": server.server_port})
    server.daemon_threads = True
    info = {"pid": os.getpid(), "port": server.server_port, "token": token, "instance": instance, "started_at": now()}
    atomic_json(root / "server.json", info)
    stopped = threading.Event()
    threading.Thread(target=follow_loop, args=(root, stopped), daemon=True).start()
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.3)
    finally:
        stopped.set()
        server.server_close()
        if read_json(root / "server.json", {}).get("instance") == instance:
            (root / "server.json").unlink(missing_ok=True)


def read_input(file=None):
    if file:
        with open(file, "r") as handle:
            raw = handle.read(MAX_INPUT + 1)
    else:
        raw = sys.stdin.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError("Input exceeds 256 KiB")
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise ValueError("Input must be a JSON object")
    return data


def _preview(value, limit=180):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _clipped(value, limit):
    return len(re.sub(r"\s+", " ", str(value or "")).strip()) > limit


def status_summary(state, limit=SUMMARY_MAX):
    """Return a deterministic, bounded digest for agents before targeted reads."""
    content = state.get("content") or {}
    context = content.get("context")
    digest = {
        "thread": state.get("thread"),
        "revision": state.get("revision"),
        "context": ({"id": context.get("id"), "label": context.get("label")} if isinstance(context, dict) else None),
        "title": _preview(content.get("title"), 120),
        "current": _preview(content.get("current")),
        "outcome": _preview(content.get("outcome")),
        "sections": [],
        "truncated": False,
    }
    digest["truncated"] = any(_clipped(content.get(field), limit)
                              for field, limit in (("title", 120), ("current", 180), ("outcome", 180)))
    for section in content.get("sections") or []:
        blocks = section.get("blocks") or []
        item = {"id": section.get("id"), "title": _preview(section.get("title"), 120),
                "block_types": [block.get("type") for block in blocks], "block_count": len(blocks), "previews": []}
        digest["truncated"] |= _clipped(section.get("title"), 120) or len(blocks) > 5
        for block in blocks[:5]:
            kind = block.get("type")
            if kind == "text":
                preview = block.get("text")
            elif kind in {"list", "checklist"}:
                values = block.get("items") or []
                preview = "; ".join((v if isinstance(v, str) else v.get("text", "")) for v in values[:3])
            elif kind == "table":
                preview = " | ".join(str(v) for v in (block.get("columns") or [])[:4])
            elif kind == "reveal":
                preview = "; ".join(v.get("prompt", "") for v in (block.get("items") or [])[:3])
            else:
                preview = "; ".join(v.get("label", "") for v in (block.get("items") or [])[:3])
            digest["truncated"] |= _clipped(preview, 140)
            if kind == "table" and len(block.get("columns") or []) > 4:
                digest["truncated"] = True
            if kind in {"list", "checklist", "reveal", "timeline"} and len(block.get("items") or []) > 3:
                digest["truncated"] = True
            item["previews"].append(_preview(preview, 140))
        digest["sections"].append(item)
    encoded = lambda: json.dumps(digest, ensure_ascii=False, separators=(",", ":"))
    while len(encoded()) > limit:
        if digest["sections"] and digest["sections"][-1]["previews"]:
            digest["sections"][-1]["previews"].pop()
        elif digest["sections"]:
            digest["sections"].pop()
        elif digest["current"] or digest["outcome"]:
            digest["current"] = _preview(digest["current"], max(20, len(digest["current"]) // 2))
            digest["outcome"] = _preview(digest["outcome"], max(20, len(digest["outcome"]) // 2))
        else:
            break
        digest["truncated"] = True
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", help="Private persistent state directory")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "status", "update", "stop", "hook", "feed"):
        child = sub.add_parser(name)
        child.add_argument("--thread", help="Defaults to CODEX_THREAD_ID; never guessed from working directory")
        if name in {"update", "hook", "feed"}:
            child.add_argument("--file", help="JSON input file; otherwise read stdin")
        if name == "start":
            child.add_argument("--title")
            child.add_argument("--transcript", help="Exact session JSONL path; session identity must match")
        if name == "status":
            child.add_argument("--summary", action="store_true", help="Return a bounded content digest")
        if name == "hook":
            child.add_argument("--event")
    sub.add_parser("shutdown", help="Stop the shared server; preserve all task data")
    sub.add_parser("_serve", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(args.home).expanduser().resolve() if args.home else home()
    try:
        if args.command == "_serve":
            serve(root)
            return 0
        if args.command == "shutdown":
            info = running(root)
            if info:
                os.kill(info["pid"], signal.SIGTERM)
            print(json.dumps({"shutdown_requested": bool(info)}))
            return 0
        data = read_input(args.file) if args.command in {"hook", "feed", "update"} else {}
        thread = args.thread or os.environ.get("CODEX_THREAD_ID")
        if not thread and args.command in {"hook", "feed"}:
            thread = data.get("thread_id") or data.get("session_id")
        if not isinstance(thread, str) or not thread.strip():
            if args.command == "hook":
                return 0
            raise ValueError("Task identity required: use --thread or CODEX_THREAD_ID")
        if args.command == "hook":
            hook(root, thread, data, args.event)
            return 0
        if args.command == "feed":
            state = ingest(root, thread, data)
            print(json.dumps({"ingested": state is not None}))
            return 0
        if args.command == "update":
            state = update_content(root, thread, data)
        elif args.command in {"start", "stop"}:
            transcript = validate_transcript(args.transcript, thread) if args.command == "start" and args.transcript else None
            def enable(state):
                state["enabled"] = args.command == "start"
                if transcript and state.get("transcript", {}).get("path") != str(transcript):
                    state["transcript"] = {"path": str(transcript), "offset": 0, "error": None}
            state = mutate(root, thread, enable)
            if args.command == "start" and args.title:
                state = update_content(root, thread, {"title": args.title})
        else:
            state = read_json(task_dir(root, thread) / "state.json")
        if args.command == "status" and args.summary:
            result = {"thread": thread, "enabled": bool(state and state["enabled"]),
                      "revision": state["revision"] if state else None,
                      "summary": status_summary(state or {"thread": thread}),
                      "state_file": str(task_dir(root, thread) / "state.json")}
            encoded = lambda: json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            # Keep the complete printed response bounded, including metadata overhead.
            while len(encoded()) > SUMMARY_MAX and result["summary"].get("sections"):
                result["summary"] = status_summary(state or {"thread": thread},
                    max(128, len(json.dumps(result["summary"], ensure_ascii=False)) - 256))
            if len(encoded()) > SUMMARY_MAX:
                result["summary"]["current"] = _preview(result["summary"].get("current"), 80)
                result["summary"]["outcome"] = _preview(result["summary"].get("outcome"), 80)
                result["summary"]["truncated"] = True
            print(encoded())
            return 0
        health_unavailable = False
        try:
            info = ensure_server(root) if args.command == "start" else running(root)
        except HealthUnavailable as exc:
            if args.command == "start":
                raise
            info, health_unavailable = exc.info, True
        print(json.dumps({"thread": thread, "enabled": bool(state and state["enabled"]),
                          "revision": state["revision"] if state else None,
                          "server_running": None if health_unavailable else bool(info),
                          "server_status": "health unavailable: local networking blocked" if health_unavailable else "running" if info else "stopped",
                          "url": viewer_url(info, thread) if info and state else None,
                          "state_file": str(task_dir(root, thread) / "state.json")}, indent=2))
        return 0
    except Exception as exc:
        if args.command == "hook":
            return 0  # Hooks must never break the assistant's operation.
        print("canvas: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
