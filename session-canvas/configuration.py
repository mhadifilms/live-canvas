"""Private local preferences. API keys are plaintext, never part of task state."""
import json
import os
from pathlib import Path
import stat

import canvas

MAX_CALLS = 10000
MAX_BYTES = 60000000
REQUEST_BYTES = 6000
FIELDS = {"schema", "revision", "api_key", "daily_calls", "daily_bytes", "typesafe", "auto_open", "clients"}


def location(root):
    return Path(root) / "configuration" / "settings.json"


def validate(value):
    # Errors deliberately never interpolate input: it may contain a credential.
    if not isinstance(value, dict) or set(value) - FIELDS or value.get("schema", 1) != 1:
        raise ValueError("Unsupported Live Canvas configuration; existing file preserved")
    for name, maximum in (("daily_calls", MAX_CALLS), ("daily_bytes", MAX_BYTES)):
        if name in value and (type(value[name]) is not int or not 0 <= value[name] <= maximum):
            raise ValueError(name + " must be an integer between 0 and " + str(maximum))
    for name in ("typesafe", "auto_open"):
        if name in value and type(value[name]) is not bool:
            raise ValueError(name + " must be a boolean")
    if "revision" in value and (type(value["revision"]) is not int or value["revision"] < 0):
        raise ValueError("Invalid configuration revision")
    if "api_key" in value and (not isinstance(value["api_key"], str) or
                               len(value["api_key"]) > 4096 or
                               any(ord(char) < 33 or ord(char) > 126 for char in value["api_key"])):
        raise ValueError("API key must contain only printable non-space ASCII characters (maximum 4096)")
    if "clients" in value and (not isinstance(value["clients"], list) or
                               any(client not in ("codex", "claude", "cursor") for client in value["clients"])):
        raise ValueError("Unknown client selection")
    return value


def private_path(path, directory=False):
    if path.is_symlink():
        raise ValueError("Refusing symlinked Live Canvas configuration")
    if path.exists():
        info = path.stat()
        if (not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) or
                info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)):
            raise ValueError("Live Canvas configuration must be owned by this user with directory 0700 / file 0600 permissions")


def load(root):
    path = location(root)
    private_path(path.parent, directory=True)
    private_path(path)
    try:
        if path.stat().st_size > 32768:
            raise ValueError("Live Canvas configuration is too large")
        return validate(json.loads(path.read_text()))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError("Invalid Live Canvas configuration; existing file preserved") from None


def effective(root, environ=None, saved=None):
    env = os.environ if environ is None else environ
    saved = load(root) if saved is None else validate(saved)
    legacy = canvas.read_json(Path(root) / "preferences.json", {})
    def limit(name, default, maximum):
        try:
            return min(maximum, max(0, int(env.get(name, default))))
        except (ValueError, TypeError):
            return default
    calls = limit("LIVE_CANVAS_TYPESAFE_DAILY_CALLS", saved.get("daily_calls", MAX_CALLS), MAX_CALLS)
    return {"enabled": env["LIVE_CANVAS_TYPESAFE"] == "1" if "LIVE_CANVAS_TYPESAFE" in env else saved.get("typesafe", legacy.get("typesafe", False)) is True,
            "auto_open": saved.get("auto_open", legacy.get("auto_open", True)) is not False,
            "key": env.get("TYPESAFE_API_KEY", saved.get("api_key", "")),
            "key_source": "environment" if "TYPESAFE_API_KEY" in env else "saved" if saved.get("api_key") else "none",
            "daily_calls": calls,
            "daily_bytes": limit("LIVE_CANVAS_TYPESAFE_DAILY_BYTES", saved.get("daily_bytes", calls * REQUEST_BYTES), MAX_BYTES),
            "retry": legacy.get("typesafe_retry", 0), "revision": saved.get("revision", 0)}


def prepare(root, changes, remove_key=False):
    current = load(root)
    updated = {**current, **changes, "schema": 1, "revision": current.get("revision", 0) + 1}
    if remove_key:
        updated.pop("api_key", None)
        # Removing a saved credential also opts out, even if an environment key exists.
        updated["typesafe"] = False
    validate(updated)
    settings = effective(root, saved=updated)
    if updated.get("typesafe") is True and not settings["key"]:
        raise ValueError("TypeSafe needs an API key before it can be enabled")
    return updated


def save(root, updated):
    validate(updated)
    path = location(root)
    private_path(path.parent, directory=True)
    private_path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    canvas.atomic_json(path, updated)


def update(root, changes, remove_key=False):
    with canvas.locked(Path(root) / ".configuration.lock"):
        save(root, prepare(root, changes, remove_key))


def status(root):
    saved = load(root)
    settings = effective(root, saved=saved)
    return {"configured": bool(saved), "configuration_file": str(location(root)),
            "credential_storage": "plaintext; user-owned directory 0700 and file 0600",
            "saved_key_present": bool(saved.get("api_key")),
            "key_present": bool(settings["key"]), "key_source": settings["key_source"],
            "typesafe": settings["enabled"], "auto_open": settings["auto_open"],
            "daily_calls": settings["daily_calls"], "daily_bytes": settings["daily_bytes"],
            "clients": saved.get("clients", []),
            "environment_overrides": [name for name in ("TYPESAFE_API_KEY", "LIVE_CANVAS_TYPESAFE", "LIVE_CANVAS_TYPESAFE_DAILY_CALLS", "LIVE_CANVAS_TYPESAFE_DAILY_BYTES") if name in os.environ]}
