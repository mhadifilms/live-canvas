"""Project semantic nodes to Excalidraw. The browser owns measured live layout."""
import copy
import hashlib
import json
import secrets

from board_model import compile_model, key

VERSION = 6
GEOMETRY = {'x', 'y', 'width', 'height', 'angle'}
CONTENT = {'text', 'originalText'}


def project(state, presentation=None):
    import board
    sections = state.get('content', {}).get('sections') or []
    latest = (state.get('automatic', {}).get('latest_final') or {}).get('text')
    if not sections and latest:
        sections = [{'id': 'conversation-response', 'title': 'From the conversation', 'blocks': [{'id': 'reply', 'type': 'text', 'text': latest}]}]
    scene = state.setdefault('board', {'elements': [], 'files': {}, 'versions': {}, 'revision': 0})
    source = hashlib.sha256(json.dumps(sections, sort_keys=True).encode()).hexdigest()
    enabled = board.adaptive_enabled(state)
    p = (presentation if presentation is not None else state.get('presentation', {})) if enabled else {}
    viewport = state.get('collaboration', {}).get('viewport', {})
    width = max(240, min(1800, viewport.get('width', 960)))
    height = max(120, min(1400, viewport.get('height', 640)))
    namespace = state.get('context_started_at') or ''
    fingerprint = hashlib.sha256(json.dumps([VERSION, source, namespace, p, width, height, scene.get('human_revision', 0), enabled], sort_keys=True).encode()).hexdigest()
    if scene.get('layout_hash') == fingerprint:
        return
    old = {e['id']: e for e in scene['elements']}
    model = compile_model(sections, scene.get('model'), namespace)
    legacy = {e.get('customData', {}).get('sectionId') for e in old.values()
              if e.get('customData', {}).get('humanTouched') and e.get('customData', {}).get('sectionId') and not e.get('customData', {}).get('nodeId') and not e.get('customData', {}).get('edgeId')}
    touched = {e['customData']['nodeId'] for e in old.values() if e.get('customData', {}).get('humanTouched') and e['customData'].get('nodeId')}
    pinned = {e.get('customData', {}).get('nodeId') for e in old.values()
              if e.get('customData', {}).get('humanTouched') and e['customData'].get('nodeId') and
              (not e['customData'].get('humanFields') or GEOMETRY.intersection(e['customData']['humanFields']))}
    occupied = [(e['x'], e['y'], abs(e['width']), abs(e['height'])) for e in old.values() if not e.get('isDeleted') and
                ('generatedText' not in e.get('customData', {}) or e.get('customData', {}).get('nodeId') in pinned or e.get('customData', {}).get('sectionId') in legacy)]
    style = p.get('style', {})
    gap = 32 if style.get('density') == 'comfortable' else 24
    columns = max(1, min(4, int((width + gap) / 304)))
    if style.get('layout') == 'compare' and width >= 620:
        columns = 2
    card_width = min(420, (width - gap * (columns - 1)) / columns)
    heights = [24.0] * columns
    priorities = p.get('priorities', {})
    sections_order = sorted(sections, key=lambda s: (s['id'] != p.get('focus_id'), {'high': 0, 'normal': 1, 'low': 2}.get(priorities.get(s['id']), 1)))
    ranks = {s['id']: i for i, s in enumerate(sections_order)}
    nodes = sorted(model['nodes'], key=lambda n: ranks[n['sectionId']])
    color = {'blue': '#426a82', 'sage': '#527565'}.get(style.get('emphasis'), '#343a40')
    wanted = {}

    def emit(e, node, part, order):
        prior = old.get(e['id'])
        e['groupIds'] = ['node-' + node['id']]
        e['customData'] = {'origin': 'agent', 'sectionId': node['sectionId'], 'blockId': node['blockId'],
                           'nodeId': node['id'], 'role': node['role'], 'part': part, 'generatedText': e.get('originalText', part),
                           'heading': part == 'heading', 'projection': VERSION, 'renderOrder': order,
                           'pinned': node['id'] in pinned, 'representation': p.get('representations', {}).get(node['sectionId'], 'map' if node['kind'] == 'graph' else 'cards')}
        if prior:
            meta = prior.get('customData', {})
            if meta.get('humanTouched'):
                fields = meta.get('humanFields')
                if fields is None:
                    wanted[e['id']] = copy.deepcopy(prior)
                    return
                for field in fields:
                    if field in prior:
                        e[field] = copy.deepcopy(prior[field])
                e['customData'].update(humanTouched=True, humanFields=fields, lastActor=meta.get('lastActor'))
            same_view = scene.get('layout', {}).get('width') == width and scene.get('layout', {}).get('height') == height
            if node['id'] in pinned or not enabled or (scene.get('source_hash') == source and same_view):
                for field in GEOMETRY:
                    e[field] = prior[field]
        wanted[e['id']] = e

    for order, node in enumerate(nodes):
        if node['sectionId'] in legacy:
            continue
        col = min(range(columns), key=lambda c: heights[c]); x = 24 + col * (card_width + gap); y = heights[col]
        head = board.text_element('agent-' + key(node['id'], 'heading'), node['label'], x + 16, y + 14, True, card_width - 32)
        body = board.text_element('agent-' + key(node['id'], 'body'), node['detail'], x + 16, y + head['height'] + 24, False, card_width - 32)
        if not node['detail']:
            body['height'] = 0
        boxheight = head['height'] + body['height'] + 40
        for _ in range(len(occupied) + 1):
            hits = [r for r in occupied if x < r[0] + r[2] + 16 and x + card_width > r[0] - 16 and y < r[1] + r[3] + 16 and y + boxheight > r[1] - 16]
            if not hits:
                break
            y = max(r[1] + r[3] for r in hits) + gap
        head.update(y=y + 14, strokeColor=color); body['y'] = y + head['height'] + 24
        frame = board.base_element('agent-' + key(node['id'], 'card'), 'rectangle', x, y, card_width, boxheight)
        frame.update(roughness=1, roundness={'type': 3}, strokeColor='#adb5bd', backgroundColor='transparent', link=node.get('source'))
        for element, part in ((frame, 'card'), (head, 'heading'), (body, 'body')):
            emit(element, node, part, order)
        heights[col] = y + boxheight + gap
    # Keep the whole small node when a person removed/edited one member, not its section.
    for eid, e in old.items():
        meta = e.get('customData', {})
        if eid not in wanted and (meta.get('nodeId') in touched or meta.get('sectionId') in legacy):
            wanted[eid] = copy.deepcopy(e)
    for edge in model['edges']:
        a = wanted.get('agent-' + key(edge['from'], 'card')); b = wanted.get('agent-' + key(edge['to'], 'card'))
        if not a or not b or a.get('isDeleted') or b.get('isDeleted'):
            continue
        eid = 'agent-' + edge['id']
        start = (a['x'] + a['width'] / 2, a['y'] + a['height'])
        end = (b['x'] + b['width'] / 2, b['y'])
        e = board.base_element(eid, 'arrow', *start, abs(end[0] - start[0]), abs(end[1] - start[1]))
        e.update(points=[[0, 0], [end[0] - start[0], end[1] - start[1]]], startBinding={'elementId': a['id'], 'focus': 0, 'gap': 1},
                 endBinding={'elementId': b['id'], 'focus': 0, 'gap': 1}, startArrowhead=None,
                 endArrowhead=None if edge['relation'] == 'connects' else 'arrow', roughness=1)
        e['customData'] = {'origin': 'agent', 'sectionId': edge['sectionId'], 'edgeId': edge['id'], 'relation': edge['relation'],
                           'generatedText': edge['relation'], 'projection': VERSION, 'startCard': a['id'], 'endCard': b['id']}
        prior = old.get(eid)
        if prior and prior.get('customData', {}).get('humanTouched'):
            e = copy.deepcopy(prior)
        elif prior and (not enabled or scene.get('source_hash') == source):
            for field in (*GEOMETRY, 'points'):
                if field in prior:e[field] = copy.deepcopy(prior[field])
        wanted[eid] = e
        # Explicit labels preserve relation meaning instead of suggesting generic causality.
        if edge['relation'] != 'precedes':
            label = board.text_element(eid + '-label', edge['relation'].replace('_', ' '), (start[0] + end[0]) / 2, (start[1] + end[1]) / 2, False, 150)
            label.update(fontSize=16, height=21, text=edge['relation'].replace('_', ' '), containerId=eid, autoResize=True)
            label['customData'] = {**{k:v for k,v in e['customData'].items() if k not in {'humanTouched','humanFields','lastActor'}}, 'edgeLabel': True}
            old_label = old.get(label['id'])
            if old_label and (not enabled or scene.get('source_hash') == source):
                for field in GEOMETRY:label[field] = old_label[field]
            wanted[label['id']] = copy.deepcopy(old_label) if old_label and old_label.get('customData', {}).get('humanTouched') else label
            e['boundElements'] = [{'id': label['id'], 'type': 'text'}]
    # Rebuild reciprocal bindings, retaining arrows the human added to these shapes.
    all_elements = {**old, **wanted}
    for e in wanted.values():
        if e['type'] != 'rectangle':
            continue
        links = [link for link in (e.get('boundElements') or []) if link.get('type') != 'arrow']
        for arrow in all_elements.values():
            if arrow.get('type') == 'arrow' and not arrow.get('isDeleted') and (arrow['id'] in wanted or 'generatedText' not in arrow.get('customData', {})):
                if any((arrow.get(side) or {}).get('elementId') == e['id'] for side in ('startBinding', 'endBinding')):
                    links.append({'id': arrow['id'], 'type': 'arrow'})
        e['boundElements'] = links or None
    changed = False
    comparison = lambda item: {k: v for k, v in item.items() if k not in {'version', 'versionNonce', 'updated', 'index'}}
    for eid, e in wanted.items():
        prior = old.get(eid)
        if prior and comparison(prior) == comparison(e):
            continue
        if prior:
            e.update(version=prior.get('version', 1) + 1, versionNonce=secrets.randbelow(2**30))
        old[eid] = e; scene['versions'][eid] = scene['versions'].get(eid, 0) + 1; changed = True
    for eid, e in list(old.items()):
        meta = e.get('customData', {})
        if meta.get('origin') == 'agent' and 'generatedText' in meta and eid not in wanted and not meta.get('humanTouched') and not e.get('isDeleted'):
            old[eid] = {**e, 'isDeleted': True, 'version': e.get('version', 1) + 1}; scene['versions'][eid] = scene['versions'].get(eid, 0) + 1; changed = True
    # Generated tombstones need not accumulate forever. Human deletions remain protected.
    elements = [e for e in old.values() if not e.get('isDeleted') or e.get('customData', {}).get('humanTouched') or e['id'] in wanted]
    board.validate(elements, scene.get('files', {}))
    scene.update(source_hash=source, layout_hash=fingerprint, layout_version=VERSION, model=model, adaptive=enabled,
                 layout={'width': width, 'height': height, 'gap': gap, 'style': style})
    # Layout policy changes (including off) must reach clients even when no
    # individual element changed. Element versions only advance for real edits.
    scene['elements'] = elements
    scene['revision'] += 1
    if changed:scene['last_actor'] = 'jev' if p else 'agent'
