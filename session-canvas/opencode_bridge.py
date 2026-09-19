#!/usr/bin/env python3
"""OpenCode event adapter; never consumes thoughts, tool output, or other sessions."""
import json
import re
import sys
import canvas
import auto_open


def handle(data, root=None):
    root = root or canvas.home()
    sid = data.get('session_id', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', sid) or data.get('parent_id'):
        return
    thread = 'opencode:' + sid
    if data.get('event') == 'start':
        if auto_open.prepare(root, thread): auto_open.launch(root, thread)
    elif data.get('event') == 'message':
        kind = data.get('role')
        if kind not in {'user', 'assistant'}: return
        canvas.ingest(root, thread, {'kind': 'user' if kind == 'user' else 'final', 'text': str(data.get('text', ''))[:20000],
            'event_id': str(data.get('message_id', ''))[:180], 'source': 'OpenCode visible message'})


if __name__ == '__main__':
    try: handle(json.loads(sys.stdin.buffer.read(256 * 1024)))
    except Exception: pass  # Never break a host turn.
