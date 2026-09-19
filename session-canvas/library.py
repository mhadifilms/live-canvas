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


def display_state(state):
    # Deterministic extraction keeps the main agent out of layout maintenance.
    # Authored content wins. Otherwise promote the last visible response verbatim.
    content = state.get('content', {})
    latest = state.get('automatic', {}).get('latest_final') or {}
    if not content.get('sections') and latest.get('text'):
        state = dict(state)
        content = dict(content)
        paragraphs = [p.strip() for p in latest['text'].split('\n\n') if p.strip()]
        content['sections'] = [{'id': 'conversation-response', 'title': 'From the conversation',
            'blocks': [{'id': 'response', 'type': 'text', 'text': '\n\n'.join(paragraphs)[:20000]}]}]
        state['content'] = content
    return state


def snapshot(root, state):
    import canvas
    import html
    import board
    directory = canvas.task_dir(root, state['thread'])
    title = html.escape(state.get('content', {}).get('title') or 'Live Canvas')
    scene = state.get('board', {'elements': [], 'files': {}})
    payload = json.dumps({'type': 'excalidraw', 'version': 2, 'source': 'Live Canvas',
                         'elements': scene['elements'], 'files': scene.get('files', {}),
                         'appState': {'viewBackgroundColor': '#fbfaf8'}}, ensure_ascii=False)
    canvas.atomic_bytes(directory / 'board.excalidraw', payload.encode())
    document = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>' + title + '</title><style>body{margin:24px;font:14px system-ui;background:#fbfaf8;color:#343a40}h1{font-size:18px}svg{width:100%;height:auto;max-height:85vh}a{color:inherit}</style><h1>' + title + '</h1>' + board.svg(state) + '<p>Saved locally · <a href="board.excalidraw">Editable board</a> · <a href="chat.json">Conversation reference</a></p></html>'
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
