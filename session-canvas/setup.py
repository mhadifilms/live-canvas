#!/usr/bin/env python3
"""Guided first-run setup and later private configuration for Live Canvas."""
import argparse
import contextlib
import getpass
import json
from pathlib import Path
import sys
import warnings

import canvas
import configuration
import install_clients

DEFAULT_ROOT = canvas.HERE / ".state"
CLIENTS = ("codex", "claude", "cursor")


def add_options(parser):
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--typesafe", choices=("on", "off"))
    parser.add_argument("--auto-open", choices=("on", "off"))
    parser.add_argument("--daily-calls", type=int)
    parser.add_argument("--daily-bytes", type=int)
    secret = parser.add_mutually_exclusive_group()
    secret.add_argument("--api-key-stdin", action="store_true", help="Read one key from stdin; never put a key in command arguments")
    secret.add_argument("--remove-key", action="store_true", help="Remove the saved key and disable saved TypeSafe preference")


def choose(prompt, choices, default=None):
    while True:
        answer = input(prompt + (" [" + default + "]" if default is not None else "") + ": ").strip().lower()
        answer = answer or default
        if answer in choices:
            return answer
        print("Choose " + ", ".join(choices) + ".")


def number(prompt, default, maximum):
    while True:
        answer = input(prompt + " [" + str(default) + "]: ").strip()
        try:
            value = int(answer) if answer else default
            if 0 <= value <= maximum:
                return value
        except ValueError:
            pass
        print("Enter a whole number between 0 and " + str(maximum) + ".")


def wizard(root, installing):
    current = configuration.effective(root)
    saved = configuration.load(root)
    clients = saved.get("clients", [])
    print("Live Canvas setup — changes are saved only after review. Ctrl-C cancels.")
    print("Hooks run local Live Canvas commands when your coding assistant starts or updates a session.")
    print("Supported: Codex, Claude Code, Cursor. Ordinary Claude web/desktop chat is not a hook host.")
    if installing:
        while True:
            answer = input("Clients (comma-separated: codex, claude, cursor)" +
                           (" [" + ",".join(clients) + "]" if clients else "") + ": ").strip()
            selected = list(dict.fromkeys(part.strip().lower() for part in answer.split(","))) if answer else clients
            if selected and all(client in CLIENTS for client in selected):
                clients = selected
                break
            print("Select at least one supported client; there is no default install-all.")
    changes = {"auto_open": choose("Automatically open a canvas for new sessions?", ("yes", "no"),
                                  "yes" if current["auto_open"] else "no") == "yes"}
    print("Optional TypeSafe: sends bounded excerpts of authored canvas sections to api.typesafe.ai to choose section focus.")
    print("No transcript is submitted. Provider charges may apply; local caps count decisions and UTF-8 request bytes per UTC day.")
    print("Create an account and API key at https://console.typesafe.ai/settings/keys — a key is optional; the canvas works without it.")
    changes["typesafe"] = choose("Allow TypeSafe to receive these excerpts?", ("yes", "no"),
                                "yes" if current["enabled"] else "no") == "yes"
    if current["key_source"] == "environment":
        print("TYPESAFE_API_KEY currently overrides any saved key. It will not be copied into the saved configuration.")
    action = choose("Saved API key: keep, change, or remove?", ("keep", "change", "remove"),
                    "change" if changes["typesafe"] and not current["key"] else "keep")
    print("Saved keys are plaintext in " + str(configuration.location(root)) + " (directory 0700; file 0600).")
    if action == "change":
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            changes["api_key"] = getpass.getpass("TypeSafe API key (hidden): ")
        if not changes["api_key"]:
            raise ValueError("Empty API key; nothing saved")
    if action == "remove":
        changes["typesafe"] = False
    changes["daily_calls"] = number("Maximum decisions per UTC day (0 pauses requests)", current["daily_calls"], configuration.MAX_CALLS)
    default_bytes = current["daily_bytes"] if changes["daily_calls"] == current["daily_calls"] else changes["daily_calls"] * configuration.REQUEST_BYTES
    changes["daily_bytes"] = number("Maximum input bytes per UTC day", default_bytes, configuration.MAX_BYTES)
    print("Saved keys are plaintext in " + str(configuration.location(root)) + " (directory 0700; file 0600).")
    print("Existing daily usage is preserved. Environment overrides remain effective until removed from the server environment.")
    print(json.dumps({"clients": clients if installing else saved.get("clients", []), "auto_open": changes["auto_open"], "typesafe": changes["typesafe"], "daily_calls": changes["daily_calls"], "daily_bytes": changes["daily_bytes"], "saved_key_action": action}, indent=2))
    if choose("Save" + (" and install hooks for " + ", ".join(clients) if installing else "") + "?", ("yes", "no"), "no") != "yes":
        raise ValueError("Cancelled; nothing saved or installed")
    return changes, action == "remove", clients


def readiness(user_home, clients):
    results = []
    for client in clients:
        item = install_clients.plan(user_home, client)
        next_step = {
            "codex": "Run codex features enable hooks. In Codex /hooks, review and trust the exact Live Canvas SessionStart command. Restart/open a new chat and send its first message; opening cannot occur in a blank chat before that turn.",
            "claude": "Restart Claude Code, review the installed hooks in /hooks, then start a new session and send a message. Automatic opening uses your OS browser.",
            "cursor": "Restart Cursor and review Hooks in Cursor Settings. Start a new Agent session and send a message; the built-in browser is used when its tools are available, otherwise the OS browser."}[client]
        results.append({"client": client, "installed": item["installed"],
                        "config": str(item["config_path"]), "skill": str(item["skill_path"]),
                        "readiness": "requires_host_verification", "next_step": next_step})
    return results


def execute(args, root):
    action = getattr(args, "action", "configure")
    user_home = getattr(args, "user_home", Path.home()).expanduser().resolve()
    if action == "status":
        result = configuration.status(root)
        result["hosts"] = readiness(user_home, result["clients"])
        print(json.dumps(result, indent=2))
        return 0
    installing = action == "setup"
    if installing and root.resolve() != DEFAULT_ROOT.resolve():
        raise ValueError("Setup hooks use the bundle's default .state directory. Use configure/status --home for custom runtimes; do not install hooks with a different state root.")
    clients = list(dict.fromkeys(getattr(args, "client", None) or []))
    has_flags = any((args.non_interactive, clients, args.typesafe is not None, args.auto_open is not None,
                     args.daily_calls is not None, args.daily_bytes is not None, args.api_key_stdin, args.remove_key))
    before = configuration.load(root)
    if not has_flags:
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise ValueError("Guided setup needs a terminal. Supply explicit flags and --non-interactive instead.")
        changes, remove_key, clients = wizard(root, installing)
    else:
        if installing and (not clients or args.typesafe is None or args.auto_open is None):
            raise ValueError("Noninteractive setup requires --client (repeatable), --typesafe on|off and --auto-open on|off")
        if not installing and clients:
            raise ValueError("--client is for setup; configure does not install hooks")
        changes = {}
        for field in ("typesafe", "auto_open"):
            if getattr(args, field) is not None:
                changes[field] = getattr(args, field) == "on"
        for field in ("daily_calls", "daily_bytes"):
            if getattr(args, field) is not None:
                changes[field] = getattr(args, field)
        if args.daily_calls is not None and args.daily_bytes is None:
            changes["daily_bytes"] = args.daily_calls * configuration.REQUEST_BYTES
        remove_key = args.remove_key
        if args.api_key_stdin:
            if sys.stdin.isatty():
                raise ValueError("Use the guided hidden prompt for terminal key entry, or pipe a key through stdin")
            key = sys.stdin.buffer.read(4098) if hasattr(sys.stdin, "buffer") else sys.stdin.read(4098).encode()
            changes["api_key"] = key.decode("ascii").rstrip("\r\n")
            if not changes["api_key"]:
                raise ValueError("Empty API key; nothing saved")
    if installing:
        changes["clients"] = list(dict.fromkeys(before.get("clients", []) + clients))
    # Validate both local configuration and every host before any mutation.
    configuration.prepare(root, changes, remove_key)
    plans = [install_clients.plan(user_home, client) for client in sorted(clients)] if installing else []
    with contextlib.ExitStack() as stack:
        stack.enter_context(canvas.locked(root / ".configuration.lock"))
        if configuration.load(root) != before:
            raise ValueError("Configuration changed during setup; rerun to review it")
        for item in plans:
            stack.enter_context(canvas.locked(item["base"] / ".live-canvas-install.lock"))
        if any(install_clients.plan(user_home, item["client"]) != item for item in plans):
            raise ValueError("Host configuration changed during setup; rerun to review it")
        for item in plans:
            install_clients.apply(item)
        configuration.save(root, configuration.prepare(root, changes, remove_key))
    result = configuration.status(root)
    result["hosts"] = readiness(user_home, result["clients"])
    result["next_step"] = "Host loading and hook trust still require the checks listed above." if installing else "The running canvas reloads configuration automatically; daily usage was preserved."
    print(json.dumps(result, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="setup", choices=("setup", "configure", "status"))
    parser.add_argument("--home", type=Path, default=None, help="State root (configure/status only for custom roots)")
    parser.add_argument("--user-home", type=Path, default=Path.home())
    parser.add_argument("--client", action="append", choices=CLIENTS)
    add_options(parser)
    args = parser.parse_args(argv)
    root = args.home.expanduser().resolve() if args.home else canvas.home()
    try:
        return execute(args, root)
    except (KeyboardInterrupt, EOFError, getpass.GetPassWarning):
        print("Live Canvas setup cancelled.", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, UnicodeError):
        print("Invalid configuration JSON or API key encoding; no secret was printed.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print("Live Canvas setup: " + str(exc), file=sys.stderr)
        return 1
    except (OSError, TypeError, KeyError, TimeoutError):
        # Do not expose exception payloads: malformed files/stdin may include keys.
        print("Live Canvas setup could not finish. Check the selected clients, permissions, configuration and limits. Some hook files may already be installed; rerun setup to recover. No secret was printed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
