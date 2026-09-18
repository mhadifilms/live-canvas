#!/usr/bin/env python3
"""Resolve a client session and run the adjacent canvas runtime."""
import os
from pathlib import Path
import re
import sys

bundle = Path(__file__).resolve().parents[2]
runtime = bundle / "session-canvas" / "canvas.py"
args = sys.argv[1:]
def take_option(name):
    values = []
    index = 0
    while index < len(args):
        if args[index] == name:
            if index + 1 == len(args):
                raise SystemExit(name + " requires a value")
            values.append(args[index + 1])
            del args[index:index + 2]
        elif args[index].startswith(name + "="):
            values.append(args.pop(index).split("=", 1)[1])
        else:
            index += 1
    if len(values) > 1:
        raise SystemExit(name + " must occur once")
    return values[0] if values else None

client = take_option("--client") or os.environ.get("LIVE_CANVAS_CLIENT")
session = take_option("--session-id") or os.environ.get("LIVE_CANVAS_SESSION_ID")
command_index = 0
while command_index < len(args):
    if args[command_index] == "--home":
        command_index += 2
    elif args[command_index].startswith("--home="):
        command_index += 1
    else:
        break
command = args[command_index] if command_index < len(args) else None
if (client or session) and command not in {"shutdown", "_serve"}:
    if client not in {"claude", "cursor"} or not session or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", session):
        raise SystemExit("Use --client claude|cursor and the exact --session-id from SessionStart")
    if any(arg == "--thread" or arg.startswith("--thread=") for arg in args):
        raise SystemExit("Do not combine a client session with --thread")
    if any(arg == "--transcript" or arg.startswith("--transcript=") for arg in args):
        raise SystemExit("Claude/Cursor messages arrive through hooks, not the Codex transcript parser")
    args.extend(["--thread", client + ":" + session])
thread = os.environ.get("CODEX_THREAD_ID", "")
if "--thread" in args:
    index = args.index("--thread")
    if index + 1 < len(args):
        thread = args[index + 1]
for arg in args:
    if arg.startswith("--thread="):
        thread = arg.split("=", 1)[1]
if not client and command == "start" and not any(arg == "--transcript" or arg.startswith("--transcript=") for arg in args) and re.fullmatch(r"[A-Za-z0-9_-]+", thread):
    sessions = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "sessions"
    matches = list(sessions.rglob("*-" + thread + ".jsonl")) if sessions.exists() else []
    if matches:
        latest = max(matches, key=lambda path: path.stat().st_mtime)
        args.extend(["--transcript", str(latest.resolve())])
os.execv(sys.executable, [sys.executable, str(runtime), *args])
