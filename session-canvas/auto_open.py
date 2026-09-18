"""Local, opt-out automatic opening with per-session claims; no model calls."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import canvas

CLAIM_SECONDS = 300


def enabled(root):
    return canvas.read_json(root / "preferences.json", {}).get("auto_open", True) is not False


def preference(root, value=None):
    if value is not None:
        with canvas.locked(root / ".preferences.lock"):
            settings = canvas.read_json(root / "preferences.json", {})
            settings["auto_open"] = value
            canvas.atomic_json(root / "preferences.json", settings)
    return {"auto_open": enabled(root)}


def foreground_start(client, payload):
    # Cursor documents is_background_agent. Other explicit flags are defensive
    # opt-outs when a host supplies them; absence cannot prove interactivity.
    if any(payload.get(field) is True for field in
           ("is_background_agent", "is_subagent", "noninteractive", "non_interactive")):
        return False
    if payload.get("interactive") is False or payload.get("is_interactive") is False:
        return False
    if payload.get("parent_session_id") or payload.get("parent_agent_id"):
        return False
    source = payload.get("source", "startup" if client == "cursor" else None)
    return source == "startup"


def prepare(root, thread):
    """Enable a fresh session, without overriding an existing explicit stop."""
    if not enabled(root):
        return False
    directory = canvas.task_dir(root, thread)
    ready = False
    with canvas.locked(directory / ".lock", timeout=0.15):
        state = canvas.read_json(directory / "state.json")
        if state is not None and not state.get("enabled"):
            return False
        if state is None:
            state = canvas.initial(thread)
            state["enabled"] = True
            state["revision"] = 1
            state["updated_at"] = canvas.now()
            canvas.atomic_json(directory / "state.json", state)
        opening = state.get("auto_open", {})
        ready = not opening.get("opened_at")
    return ready


def claim(root, thread):
    result = {"should_open": False}
    if not enabled(root):
        return result
    def apply(state):
        opening = state.setdefault("auto_open", {})
        if opening.get("opened_at") or opening.get("claim", {}).get("expires", 0) > time.time():
            return False
        token = secrets.token_hex(16)
        opening["claim"] = {"token": token, "expires": time.time() + CLAIM_SECONDS}
        result.update(should_open=True, claim=token)
    canvas.mutate(root, thread, apply, enabled_only=True)
    return result


def settle(root, thread, token, opened=False, opener=None):
    """Acknowledge only the live claim; optionally perform an OS dispatch under lock."""
    accepted = False
    def apply(state):
        nonlocal accepted
        opening = state.get("auto_open", {})
        lease = opening.get("claim", {})
        if not token or lease.get("token") != token or lease.get("expires", 0) <= time.time():
            return False
        if opened and not enabled(root):
            opening.pop("claim", None)
            return
        if opener:
            opener()
        opening.pop("claim", None)
        if opened:
            opening["opened_at"] = canvas.now()
        accepted = True
    canvas.mutate(root, thread, apply, enabled_only=True)
    return {"acknowledged": accepted}


def native_instruction(root, thread, prefix, client):
    if not prepare(root, thread):
        return ""
    browser = ("mcp__codex_app__open_in_codex with target {type:browser,url:<url>} and placement right"
               if client == "codex" else "the built-in browser tool if exposed; otherwise the OS browser")
    # Commands claim before UI work, so repeated SessionStart context cannot open
    # duplicate panes. Tool failure releases the claim; a crashed turn expires it.
    return ("Auto-open is enabled. On this session's first user turn, before answering, run " + prefix +
            " auto-open claim. Only if should_open is true: run the same prefix with start --auto-claim <returned-claim>, open its URL using " + browser +
            ", then run the same prefix with auto-open opened --claim <returned-claim>. "
            "If start/open fails, run auto-open release --claim <returned-claim> and continue normally. "
            "Do not ask for permission, open again after acknowledgement, or create an extra model turn. ")


def launch(root, thread):
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--home", str(root), "--thread", thread],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)


def browser_command(url):
    if sys.platform == "darwin":
        return ["open", url]
    if sys.platform.startswith("linux") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return ["xdg-open", url]
    raise RuntimeError("No supported local graphical browser environment")


def worker(root, thread):
    token = None
    try:
        # Multiple hook deliveries may launch workers; only one receives a claim.
        result = claim(root, thread)
        if not result["should_open"]:
            return
        token = result["claim"]
        # A subprocess bounds server startup too. The hook itself never waits here.
        started = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--home", str(root),
                                  "--ensure-server", "--thread", thread], capture_output=True, timeout=10, check=True)
        url = json.loads(started.stdout)["url"]
        if not isinstance(url, str) or not url.startswith("http://127.0.0.1:"):
            raise ValueError("Expected the local canvas URL")
        command = browser_command(url)
        settle(root, thread, token, opened=True, opener=lambda: subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=3, check=True))
    except Exception:
        if token:
            try:
                settle(root, thread, token)
            except Exception:
                pass  # An interrupted attempt remains retryable after its claim expires.


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--thread", required=True)
    parser.add_argument("--ensure-server", action="store_true")
    options = parser.parse_args()
    if options.ensure_server:
        # Starting the shared server must never re-enable a stopped session.
        print(json.dumps({"url": canvas.viewer_url(canvas.ensure_server(options.home), options.thread)}))
    else:
        worker(options.home, options.thread)
