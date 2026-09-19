"""Portable local HTML snapshots and transcript references, without credentials."""
import json
import os
from pathlib import Path
import sys


def default_home():
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/Live Canvas'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'live-canvas'


def metadata(state):
    thread = state['thread']
    client, session = thread.split(':', 1) if ':' in thread else ('codex', thread)
    return {'client': client, 'session_id': session,
            'chat_url': 'codex://threads/' + session if client == 'codex' else None,
            'transcript_path': state.get('transcript', {}).get('path'),
            'event_log': 'conversation.jsonl'}


def snapshot(root, state):
    import canvas
    directory = canvas.task_dir(root, state['thread'])
    # Reuse the real document renderer, but omit network polling and private history.
    saved = {key: state.get(key) for key in ('thread', 'context_started_at', 'revision', 'curated_at', 'content', 'presentation')}
    saved.update(enabled=True, feed=[], history=[], automatic={}, activity={}, transcript={})
    payload = json.dumps(saved, ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = (canvas.HERE / 'index.html').read_text()
    prefix = template.split('// The fragment is never sent', 1)[0]
    document = prefix + 'render(' + payload + "); $('connection-text').textContent = 'Saved locally';</script></body></html>"
    canvas.atomic_bytes(directory / 'canvas.html', document.encode())
    canvas.atomic_json(directory / 'chat.json', metadata(state))


def record_message(root, thread, item):
    import canvas
    if item.get('kind') not in {'user', 'final', 'commentary'}:
        return
    path = canvas.task_dir(root, thread) / 'conversation.jsonl'
    with canvas.locked(path.with_suffix('.lock')):
        if path.exists() and path.stat().st_size > 20 * 1024 * 1024:
            return  # Source host transcript remains authoritative; bound the mirror.
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'a') as f:
            f.write(json.dumps({k: item.get(k) for k in ('id', 'kind', 'text', 'at')}, ensure_ascii=False) + '\n')
