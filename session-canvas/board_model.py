"""Semantic board content. Identity and authored relationships survive layout changes."""
import hashlib
import re

ROLES = {'concept', 'question', 'claim', 'evidence', 'task', 'decision', 'reference', 'event', 'note'}
RELATIONS = {'connects', 'supports', 'challenges', 'depends_on', 'contains', 'precedes', 'answers'}


def validate_graph(block):
    def require(ok, message):
        if not ok:
            raise ValueError('graph: ' + message)
    identity = lambda v: isinstance(v, str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', v))
    nodes, edges = block.get('nodes'), block.get('edges', [])
    require(isinstance(nodes, list) and len(nodes) <= 120, 'expected up to 120 nodes')
    require(isinstance(edges, list) and len(edges) <= 240, 'expected up to 240 edges')
    ids = set()
    for node in nodes:
        require(isinstance(node, dict) and not set(node) - {'id', 'label', 'detail', 'role', 'source'}, 'unknown node field')
        require(identity(node.get('id')) and node['id'] not in ids, 'unique node IDs required')
        ids.add(node['id'])
        require(isinstance(node.get('label'), str) and 0 < len(node['label']) <= 500, 'label must be 1–500 characters')
        require(isinstance(node.get('detail', ''), str) and len(node.get('detail', '')) <= 20000, 'detail must be at most 20000 characters')
        require(isinstance(node.get('role', 'concept'), str) and node.get('role', 'concept') in ROLES, 'unsupported node role')
        source = node.get('source')
        require(source is None or (isinstance(source, str) and len(source) <= 2048 and re.match(r'^https?://[^\s]+$', source)), 'source must be an HTTP(S) URL')
    ids_edges = set()
    for edge in edges:
        require(isinstance(edge, dict) and not set(edge) - {'id', 'from', 'to', 'relation'}, 'unknown edge field')
        require(identity(edge.get('id')) and edge['id'] not in ids_edges, 'unique edge IDs required')
        ids_edges.add(edge['id'])
        require(isinstance(edge.get('from'), str) and isinstance(edge.get('to'), str)
                and edge['from'] in ids and edge['to'] in ids and edge['from'] != edge['to'], 'edges must join two existing distinct nodes')
        require(isinstance(edge.get('relation', 'connects'), str) and edge.get('relation', 'connects') in RELATIONS, 'unsupported relationship')


def key(*parts):
    return hashlib.sha256('\0'.join(map(str, parts)).encode()).hexdigest()[:22]


def compile_model(sections, previous=None, namespace=''):
    """Lift legacy blocks without asking a model to invent missing structure.

    Explicit graph IDs are the durable authoring contract. For older string lists,
    match unchanged items first, then edited slots; new entries get monotonic IDs.
    """
    import board
    previous = previous or {}
    if previous.get('namespace', '') != namespace:
        previous = {}
    nodes, edges = [], []
    serial = previous.get('serial', 0)
    for section in sections:
        for bi, block in enumerate(section.get('blocks', [])):
            bid = block.get('id', str(bi))
            scope = key(namespace, section['id'], bid)
            kind = block['type']
            entries = []
            if kind == 'graph':
                entries = [{**n, 'sourceId': n['id']} for n in block['nodes']]
            elif kind == 'text':
                if block.get('text', '').strip():
                    entries = [{'sourceId': 'text', 'label': section['title'], 'detail': board.plain(block['text']), 'role': 'note'}]
            elif kind == 'table':
                entries = [{'label': row[0] if row else section['title'], 'detail': '\n'.join(f'{c}: {v}' for c, v in zip(block['columns'], row)), 'role': 'evidence'} for row in block['rows']]
            else:
                for item in block.get('items', []):
                    if kind == 'timeline':
                        entries.append({'label': ' · '.join(board.plain(item.get(k)) for k in ('at', 'label') if item.get(k)), 'detail': board.plain(item.get('detail')), 'role': 'event'})
                    elif kind == 'reveal':
                        entries.append({'sourceId': item['id'], 'label': board.plain(item['prompt']), 'detail': board.plain(item['answer']), 'role': 'question'})
                    elif kind == 'checklist':
                        entries.append({'label': ('☑ ' if item.get('checked') else '☐ ') + board.plain(item['text']), 'detail': '', 'role': 'task'})
                    else:
                        entries.append({'label': board.plain(item), 'detail': '', 'role': 'concept'})
            prior = [n for n in previous.get('nodes', []) if n.get('scope') == scope]
            matches, used = {}, set()
            # Reserve exact matches before handling insertions or edits.
            for i, entry in enumerate(entries):
                if 'sourceId' in entry:
                    continue
                match = next((n for n in prior if n['id'] not in used and (n['label'], n['detail']) == (entry['label'], entry.get('detail', ''))), None)
                if match:
                    matches[i] = match['id']; used.add(match['id'])
            block_nodes = []
            for i, entry in enumerate(entries):
                if 'sourceId' in entry:
                    nid = key(scope, entry['sourceId'])
                elif i in matches:
                    nid = matches[i]
                else:
                    match = next((n for n in prior if n['id'] not in used and n.get('slot') == i), None)
                    if match:
                        nid = match['id']; used.add(nid)
                    else:
                        serial += 1; nid = key(scope, 'item', serial)
                node = {**entry, 'id': nid, 'scope': scope, 'slot': i, 'sectionId': section['id'],
                        'blockId': bid, 'kind': kind, 'sectionTitle': section['title'], 'detail': entry.get('detail', ''), 'role': entry.get('role', 'concept')}
                block_nodes.append(node); nodes.append(node)
            if kind == 'graph':
                lookup = {n['sourceId']: n['id'] for n in block_nodes}
                edges.extend({'id': key(scope, 'edge', e['id']), 'from': lookup[e['from']], 'to': lookup[e['to']],
                              'relation': e.get('relation', 'connects'), 'sectionId': section['id']} for e in block.get('edges', []))
            elif kind == 'timeline' or (kind == 'list' and block.get('ordered')):
                edges.extend({'id': key(a['id'], b['id']), 'from': a['id'], 'to': b['id'], 'relation': 'precedes', 'sectionId': section['id']}
                             for a, b in zip(block_nodes, block_nodes[1:]))
    if len(nodes) * 3 + len(edges) * 2 > board.MAX_ELEMENTS:
        raise ValueError('Board content exceeds 2000 native objects; use fewer nodes or separate details')
    return {'version': 1, 'namespace': namespace, 'serial': serial, 'nodes': nodes, 'edges': edges}
