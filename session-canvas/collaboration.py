"""Authenticated local feedback. User data is separate from assistant-authored content."""
import base64
import binascii
import hashlib
import math
from pathlib import Path
import re
import canvas

MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL_FILES = 20 * 1024 * 1024
MAX_EVENTS = 120
KINDS = {'comment', 'highlight', 'selection', 'drawing', 'file', 'preference', 'viewport', 'interaction', 'remove'}


def text(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Invalid or oversized text')
    return value


def validate(data):
    if not isinstance(data, dict) or set(data) - {'id', 'kind', 'text', 'quote', 'section', 'points', 'name', 'data', 'width', 'height', 'target'}:
        raise ValueError('Unknown feedback fields')
    kind = data.get('kind')
    if kind not in KINDS or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(data.get('id', ''))):
        raise ValueError('Invalid feedback identity')
    item = {'id': data['id'], 'kind': kind, 'at': canvas.now()}
    for field, limit in [('text', 4000), ('quote', 2000), ('section', 80)]:
        if field in data:
            item[field] = text(data[field], limit)
    if kind == 'viewport':
        for field in ('width', 'height'):
            v = data.get(field)
            if type(v) is not int or not 120 <= v <= 10000:
                raise ValueError('Invalid viewport')
            item[field] = round(v / 80) * 80  # Ignore insignificant resize jitter.
    if kind == 'drawing':
        points = data.get('points')
        if not isinstance(points, list) or not 2 <= len(points) <= 1000:
            raise ValueError('Drawing must contain 2–1000 points')
        for p in points:
            if not isinstance(p, list) or len(p) != 2 or any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in p):
                raise ValueError('Drawing coordinates must be normalized')
        item['points'] = points
    if kind == 'file':
        name = text(data.get('name'), 180)
        if not name.strip() or '/' in name or '\\' in name or any(ord(c) < 32 for c in name):
            raise ValueError('Invalid file name')
        try:
            raw = base64.b64decode(text(data.get('data'), MAX_FILE * 2), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError('Invalid attachment') from None
        if len(raw) > MAX_FILE:
            raise ValueError('Attachments are limited to 2 MiB each')
        item.update(name=name, size=len(raw), file_id=hashlib.sha256(raw).hexdigest())
        # Only plain-text excerpts enter adaptation; never executable HTML or binary data.
        if Path(name).suffix.lower() in {'.txt', '.md', '.csv', '.srt'}:
            item['excerpt'] = raw[:4000].decode('utf-8', errors='replace')
        item['_raw'] = raw
    if kind == 'remove':
        item['target'] = text(data.get('target'), 80)
    return item


def submit(root, thread, data):
    if isinstance(data, dict) and data.get('kind') == 'presence':
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(data.get('id', ''))): raise ValueError('Invalid view identity')
        import time
        directory = canvas.task_dir(root, thread)
        with canvas.locked(directory / '.presence.lock'):
            views = canvas.read_json(directory / 'views.json', {})
            views = {k:v for k,v in views.items() if time.time()-v < 45}
            if len(views) > 8: views = dict(list(views.items())[-8:])
            views[data['id']] = time.time()
            canvas.atomic_json(directory / 'views.json', views)
        return {'saved':True}
    item = validate(data)
    def apply(state):
        collab = state.setdefault('collaboration', {'events': [], 'revision': 0})
        events = collab.setdefault('events', [])
        if item['id'] in collab.get('seen', []):
            return False
        if item['kind'] == 'viewport':
            viewport = {k: item[k] for k in ('width', 'height')}
            if collab.get('viewport') == viewport:
                return False
            collab['viewport'] = viewport
        elif item['kind'] == 'remove':
            # Removal is scoped to user-created annotations, never authored work.
            target = next((x for x in events if x['id'] == item['target']), None)
            if target and target.get('file_id'):
                remaining = [x for x in events if x['id'] != item['target']]
                if not any(x.get('file_id') == target['file_id'] for x in remaining):
                    (canvas.task_dir(root, thread) / 'attachments' / target['file_id']).unlink(missing_ok=True)
            events[:] = [x for x in events if x['id'] != item['target']]
        else:
            if item['kind'] in {'interaction', 'selection'}:
                old = [e for e in events if e['kind'] == item['kind']]
                for e in old[:-15]: events.remove(e)
            if len(events) >= MAX_EVENTS:
                raise ValueError('Remove an older annotation before adding another (120 maximum)')
            raw = item.pop('_raw', None)
            if raw is not None:
                directory = canvas.task_dir(root, thread) / 'attachments'
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                size = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
                dest = directory / item['file_id']
                if not dest.exists() and size + len(raw) > MAX_TOTAL_FILES:
                    raise ValueError('This canvas has reached its 20 MiB attachment limit')
                canvas.atomic_bytes(dest, raw)
            if len(events) >= MAX_EVENTS:
                raise ValueError('Remove an older annotation before adding another (120 maximum)')
            events.append(item)
        collab['seen'] = (collab.get('seen', []) + [item['id']])[-240:]
        collab['revision'] = collab.get('revision', 0) + 1
        state.pop('presentation', None)
    result = canvas.mutate(root, thread, apply)
    return {'saved': True, 'revision': result['revision'], 'collaboration': result.get('collaboration', {})}


def summary(state):
    events = state.get('collaboration', {}).get('events', [])
    return [{k: e[k] for k in ('id', 'kind', 'text', 'quote', 'section', 'name', 'file_id') if k in e}
            for e in events[-5:]]
