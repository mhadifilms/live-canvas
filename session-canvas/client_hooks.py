#!/usr/bin/env python3
"""Fail-open, zero-model-call local client hook adapters."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys

import canvas
import auto_open

EVENTS = {
    "codex": {"SessionStart": "SessionStart"},
    "claude": {"SessionStart": "SessionStart", "UserPromptSubmit": "UserPromptSubmit",
               "PostToolUse": "PostToolUse", "Stop": "Stop"},
    "cursor": {"sessionStart": "SessionStart", "beforeSubmitPrompt": "UserPromptSubmit",
               "postToolUse": "PostToolUse", "afterAgentResponse": "response", "stop": "Stop"},
}


def identity(client, payload, event=None):
    field = "conversation_id" if client == "cursor" else "session_id"
    session = payload.get(field)
    if client == "cursor" and event == "sessionStart" and not session:
        session = payload.get("session_id")
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", session):
        raise ValueError("Missing or invalid client session identity")
    return session, session if client == "codex" else client + ":" + session


def handle(root, client, event, payload):
    if not isinstance(payload, dict) or event not in EVENTS.get(client, {}):
        return {}
    # A configured command owns its event; reject contradictory payloads.
    reported = payload.get("hook_event_name")
    if reported and reported != event:
        return {}
    session, thread = identity(client, payload, event)
    signal = EVENTS[client][event]
    if signal == "SessionStart":
        launcher = Path(__file__).resolve().parents[1] / "live-canvas/scripts/live_canvas.py"
        prefix = shlex.join([sys.executable, str(launcher), "--home", str(root),
                             "--client", client, "--session-id", session])
        opening = ""
        if auto_open.foreground_start(client, payload):
            if client == "claude":
                if auto_open.prepare(root, thread):
                    auto_open.launch(root, thread)
                    opening = "A local worker is automatically opening this session's canvas in the OS browser. "
            else:
                opening = auto_open.native_instruction(root, thread, prefix, client)
        context = ("Live canvas is available via /live-canvas. Exact session command prefix: " + prefix +
                   ". " + opening + "Respect explicit stop and auto-open off; do not automatically reopen otherwise. "
                   "For an active canvas, use status --summary, then update meaningful changed sections at milestones and before the final reply. "
                   "Hooks record activity and final responses automatically; no polling or follow-up turns are needed.")
        canvas.hook(root, thread, {}, signal)
        if client in {"claude", "codex"}:
            return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
        return {"additional_context": context,
                "env": {"LIVE_CANVAS_CLIENT": client, "LIVE_CANVAS_SESSION_ID": session}}
    # No files, server, or registration are created for inactive sessions.
    state = canvas.read_json(canvas.task_dir(root, thread) / "state.json", {})
    if not state.get("enabled"):
        return {}
    text = payload.get("last_assistant_message") if client == "claude" and event == "Stop" else (
        payload.get("text") if client == "cursor" and event == "afterAgentResponse" else None)
    if isinstance(text, str) and text.strip():
        # Only documented, visible assistant text is admitted. Never inspect transcript,
        # prompt, tool inputs/results, afterAgentThought, or arbitrary nested messages.
        turn = payload.get("generation_id", "") if client == "cursor" else ""
        digest = hashlib.sha256((str(turn) + "\0" + text).encode()).hexdigest()
        canvas.ingest(root, thread, {"kind": "final", "text": text,
                     "event_id": client + ":" + digest, "source": client + " " + event})
    if signal != "response":
        canvas.hook(root, thread, {}, signal)
    return {}


def main(argv=None):
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--client", required=True, choices=EVENTS)
        parser.add_argument("--event", required=True)
        parser.add_argument("--home")
        args = parser.parse_args(argv)
        raw = sys.stdin.buffer.read(canvas.MAX_INPUT + 1)
        if len(raw) > canvas.MAX_INPUT:
            return 0
        payload = json.loads(raw)
        result = handle(Path(args.home).expanduser().resolve() if args.home else canvas.home(),
                        args.client, args.event, payload)
        if result:
            print(json.dumps(result))
    except (Exception, SystemExit):
        # Never prevent or continue the host's turn, and never leak payloads in errors.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
