#!/usr/bin/env python3
"""Reversible user-level live-canvas hooks and skill installation (macOS/Linux)."""
import argparse
import copy
import datetime as dt
import json
import os
from pathlib import Path
import secrets
import shlex
import sys

import canvas
from client_hooks import EVENTS

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "live-canvas"


def entries(client):
    result = {}
    for event in EVENTS[client]:
        command = shlex.join([sys.executable, str(HERE / "client_hooks.py"), "--client", client, "--event", event])
        hook = {"type": "command", "command": command, "timeout": 2}
        if client in {"claude", "codex"}:
            result[event] = {"hooks": [hook]}
        else:
            hook["failClosed"] = False
            result[event] = hook
    return result


def load(path, default):
    if path.is_symlink():
        raise ValueError("Refusing to replace a symlink: " + str(path))
    if not path.exists():
        return default
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object: " + str(path))
    return value


def commands(value):
    if isinstance(value, dict):
        if isinstance(value.get("command"), str):
            yield value["command"]
        for child in value.values():
            yield from commands(child)
    elif isinstance(value, list):
        for child in value:
            yield from commands(child)


def plan(user_home, client, uninstall=False):
    if client == "opencode":
        return __import__("opencode_install").plan(user_home, uninstall)
    base = user_home / {"claude": ".claude", "cursor": ".cursor", "codex": ".codex"}[client]
    if client == "codex" and user_home == Path.home().resolve() and os.environ.get("CODEX_HOME"):
        base = Path(os.environ["CODEX_HOME"]).expanduser().resolve()
    config_path = base / ("settings.json" if client == "claude" else "hooks.json")
    manifest_path = base / ".live-canvas-install.json"
    skill_path = base / "skills/live-canvas"
    original = load(config_path, {})
    manifest = load(manifest_path, None)
    desired = entries(client)
    owned = manifest.get("entries", {}) if manifest else {}
    if manifest and (manifest.get("schema") not in {1, 2} or manifest.get("client") != client or
                     manifest.get("source") != str(SKILL) or not isinstance(owned, dict) or
                     any(desired.get(event) != entry for event, entry in owned.items())):
        raise ValueError("Installation belongs to a different bundle/interpreter; uninstall using its original installer first: " + str(manifest_path))
    if skill_path.parent.is_symlink():
        raise ValueError("Refusing to modify a symlinked skills directory: " + str(skill_path.parent))
    same_skill = skill_path.is_symlink() and skill_path.resolve() == SKILL.resolve()
    if (skill_path.exists() or skill_path.is_symlink()) and not same_skill:
        raise ValueError("Skill collision; existing path was preserved: " + str(skill_path))
    hooks = original.get("hooks", {})
    if not isinstance(hooks, dict) or any(not isinstance(value, list) for value in hooks.values()):
        raise ValueError("Expected hook event lists in " + str(config_path))
    if client == "cursor" and original.get("version", 1) != 1:
        raise ValueError("Unsupported Cursor hooks version; configuration was preserved")
    for event, definitions in hooks.items():
        for definition in definitions:
            ours = any("client_hooks.py" in command for command in commands(definition))
            if ours and (not manifest or owned.get(event) != definition):
                raise ValueError("Unowned or edited live-canvas hook; configuration was preserved: " + event)
        if event in desired and definitions.count(desired[event]) > 1:
            raise ValueError("Duplicate live-canvas hook; resolve manually: " + event)
    updated = copy.deepcopy(original)
    installed = bool(manifest and same_skill and all(hooks.get(event, []).count(entry) == 1 for event, entry in desired.items()))
    if uninstall:
        if manifest:
            for event, entry in owned.items():
                definitions = updated.get("hooks", {}).get(event, [])
                if entry in definitions:
                    definitions.remove(entry)
                if not definitions and event not in manifest["original_events"]:
                    updated.get("hooks", {}).pop(event, None)
            if not updated.get("hooks") and not manifest["had_hooks"]:
                updated.pop("hooks", None)
            if client == "cursor" and not manifest["had_version"]:
                # Keep schema version when other hook definitions were added later.
                if not updated.get("hooks"):
                    updated.pop("version", None)
    else:
        updated.setdefault("hooks", {})
        for event, entry in desired.items():
            definitions = updated["hooks"].setdefault(event, [])
            if entry not in definitions:
                definitions.append(entry)
        if client == "cursor":
            updated["version"] = 1
    if not manifest and not uninstall:
        manifest = {"schema": 2, "client": client, "source": str(SKILL), "entries": desired,
                    "config_existed": config_path.exists(), "had_hooks": "hooks" in original,
                    "had_version": "version" in original, "original_events": list(hooks),
                    "created_skill": not same_skill}
    elif manifest and not uninstall:
        # Upgrade known older manifests without taking ownership of other hooks.
        manifest = {**manifest, "schema": 2, "entries": desired}
    return {"client": client, "base": base, "config_path": config_path, "manifest_path": manifest_path,
            "skill_path": skill_path, "original": original, "updated": updated, "manifest": manifest,
            "same_skill": same_skill, "installed": installed, "uninstall": uninstall}


def backup(path, base):
    if not path.exists():
        return None
    directory = base / ".live-canvas-backups"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = directory / (path.name + "." + stamp + "." + secrets.token_hex(3))
    with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        handle.write(path.read_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    return str(destination)


def apply(item):
    if item["client"] == "opencode":
        return __import__("opencode_install").apply(item)
    base, path, manifest = item["base"], item["config_path"], item["manifest"]
    if item["uninstall"] and not manifest:
        return {"client": item["client"], "changed": False, "status": "not installed"}
    config_changed = item["updated"] != item["original"]
    backup_path = backup(path, base) if config_changed else None
    if not item["uninstall"]:
        # Persist ownership before mutation, allowing recovery from interrupted installs.
        saved_manifest = load(item["manifest_path"], None)
        updated_manifest = {**manifest, "backup": manifest.get("backup", backup_path)}
        if saved_manifest != updated_manifest:
            backup(item["manifest_path"], base)
            canvas.atomic_json(item["manifest_path"], updated_manifest)
        item["skill_path"].parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not item["same_skill"]:
            item["skill_path"].symlink_to(SKILL, target_is_directory=True)
    if config_changed:
        if item["uninstall"] and not item["updated"] and not manifest["config_existed"]:
            path.unlink(missing_ok=True)
        else:
            canvas.atomic_json(path, item["updated"])
    if item["uninstall"]:
        if manifest["created_skill"] and item["same_skill"]:
            item["skill_path"].unlink()
        item["manifest_path"].unlink(missing_ok=True)
    return {"client": item["client"], "changed": config_changed or not item["installed"] or item["uninstall"],
            "status": "uninstalled" if item["uninstall"] else "installed", "backup": backup_path}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("dry-run", "check", "install", "uninstall"))
    parser.add_argument("--client", choices=("codex", "claude", "cursor", "opencode", "both", "all"), default="all")
    parser.add_argument("--user-home", type=Path, default=Path.home(), help="Override the user home (also useful for fixtures)")
    args = parser.parse_args(argv)
    try:
        clients = ["codex", "claude", "cursor", "opencode"] if args.client == "all" else (
            ["claude", "cursor"] if args.client == "both" else [args.client])
        user_home = args.user_home.expanduser().resolve()
        def client_plan(client):
            if client == 'codex':
                import codex_startup
                return codex_startup.uninstall_plan(user_home) if args.action == 'uninstall' else codex_startup.plan(user_home)
            return plan(user_home, client, args.action == 'uninstall')
        plans = [client_plan(client) for client in clients]
        if args.action in {'dry-run','check'}:
            print(json.dumps({'action':args.action,'clients':[{'client':p['client'],'installed':p['installed'],'config':str(p['config_path']),'readiness':'requires_host_verification','next_step':'Start a new foreground task and verify its first-turn browser opening.','would_change_config':p['original']!=p['updated']} for p in plans]},indent=2))
            return int(args.action == 'check' and not all(p['installed'] for p in plans))
        results=[]
        for item in plans:
            item['base'].mkdir(mode=0o700,parents=True,exist_ok=True)
            with canvas.locked(item['base']/'.live-canvas-install.lock'):
                if client_plan(item['client']) != item:raise ValueError('Configuration changed during preflight; retry after reviewing it')
                if item.get('startup_instruction'):
                    import codex_startup
                    results.append(codex_startup.uninstall(item) if args.action == 'uninstall' else codex_startup.apply(item))
                else:results.append(apply(item))
        print(json.dumps({"action": args.action, "clients": results}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, TimeoutError) as exc:
        print("live-canvas install: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
