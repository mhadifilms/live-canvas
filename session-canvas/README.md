# Runtime reference

Live Canvas is one editable Excalidraw scene per conversation. See the [main guide](../README.md) for installation, host support, privacy and configuration.

## Semantic authoring

Use stable nodes and explicit relationships when the work benefits from a diagram. The same graph contract supports argument maps, concept maps, dependencies, decisions and connected questions. The scene records source identities separately from positions; rewording or reordering a node does not recreate it.

```json
{
  "title": "An argument to develop",
  "sections": [{
    "id": "argument",
    "title": "Working argument",
    "blocks": [{
      "id": "map",
      "type": "graph",
      "nodes": [
        {"id": "claim", "role": "claim", "label": "Libraries are public infrastructure", "detail": "A working thesis, not a verified conclusion."},
        {"id": "evidence", "role": "question", "label": "What evidence supports this?", "detail": "Collect and verify local access data."},
        {"id": "objection", "role": "question", "label": "What is the strongest alternative?"}
      ],
      "edges": [
        {"id": "evidence-question", "from": "claim", "to": "evidence", "relation": "connects"},
        {"id": "objection-question", "from": "claim", "to": "objection", "relation": "connects"}
      ]
    }]
  }]
}
```

Each node requires `id` and `label`; optional fields are `detail`, `role` and `source` (an HTTP(S) URL). Roles: `concept`, `question`, `claim`, `evidence`, `task`, `decision`, `reference`, `event`, `note`. Each edge requires `id`, `from` and `to`; optional `relation` defaults to `connects`. Relations: `connects`, `supports`, `challenges`, `depends_on`, `contains`, `precedes`, `answers`. Direction always reads **from node → relation → to node**. `connects` is undirected; other relationships show an arrow. Unsupported roles, duplicate IDs and missing endpoints fail validation before any state is written. Graphs accept up to 120 nodes and 240 edges, subject to the shared scene limit.

Use only relationships supported by the authored work. Jev chooses bounded presentation options; it cannot add facts or edges. Source links belong on the node's shape. The canonical graph is saved under `board.model`; native scene elements carry `nodeId`, `role`, `sectionId` and `blockId`. IDs are scoped to the section and block, so keep those IDs stable too.

### Compatible blocks

Existing content is lifted into semantic nodes locally, without another model call:

| Type | Fields | Current board representation |
| --- | --- | --- |
| `text` | `text` string | Editable text in a node. |
| `list` | string `items`; optional `ordered`, `selectable` booleans | One node per item; only an explicitly ordered list adds sequence edges. |
| `checklist` | `items` with `text`, optional `checked` | Task nodes with authored check marks. |
| `table` | string `columns`; matching string-array `rows` | Labeled evidence nodes per row. |
| `reveal` | `items` with unique `id`, `prompt`, `answer` | Question nodes with visible answers. |
| `timeline` | `items` with `label`, optional `at`, `detail` | Event nodes connected in source order. |

The old document viewer's shortlist, recall buttons and checklist controls are not active Excalidraw widgets. Editing the board persists through the shared scene API. Legacy `visual_html` is retained in history but is not rendered.

Legacy string-list IDs are reconciled by unchanged text first and edited position second. Explicit graph IDs are preferred when an item must retain identity across simultaneous reordering and rewriting.

## Updating the same work

```sh
python3 canvas.py update --thread EXACT_HOST_SESSION_ID --file update.json
```

Omitted fields stay unchanged. `sections` replaces the section list. Prefer a section delta for an existing context:

```json
{"upsert_sections": [{"id": "argument", "title": "Working argument", "blocks": []}], "remove_sections": ["obsolete"]}
```

Do not combine deltas with `sections`. Each upsert replaces one section in place. Section/block IDs use 1–80 letters, numbers, underscores, dots or hyphens and begin with a letter or number. Up to 30 sections and 30 blocks per section are accepted. Unknown fields are rejected.

`context` accepts an `id`, `label` and optional `description`. Changing `context.id` clears old authored material atomically, while preserving human work and revision history. `replace: true` resets authored content within the current context. The latest visible assistant reply supplies fallback content when no authored sections exist.

## Human ownership and layout

Text corrections protect the edited words, styling changes protect the changed style, and moving/resizing protects that node's placement. Neighboring nodes continue receiving updates and rearranging. Deletions stay deleted. The service compares edits against the browser's measured baseline so automatic wrapping is not mistaken for a human move. Human-edited sections from older releases remain conservatively protected during migration.

The browser measures text and computes live geometry using the usable viewport, including toolbars and padding. Graphs can form layers and branches; independent nodes pack compactly. Native arrows have reciprocal shape bindings, so dragging a node keeps its connections attached. Cycles remain supported without infinite layout passes. The server supplies estimated geometry for the offline snapshot; the measured browser baseline is persisted with scene saves.

Fit never deliberately shrinks text below 16 CSS pixels. If the scene cannot fit at readable size, previous/next views provide access. Manual pan and zoom remain available. Incoming updates preserve the current readable view where its anchor survives. Turning adaptation off freezes automatic rearrangement; it does not stop authored content updates.

This foundation does not yet provide semantic zoom, collapsible node details, anchored comment threads, or automatic interpretation of drawings.

## Direct shared scene API

`board --thread EXACT_ID --file changes.json` accepts `{ "elements": [...], "base_versions": {...}, "files": {...} }`. Elements use the Excalidraw scene format; IDs and versions come from `state.json` under `board`. Submit only changed objects. Omission preserves an object; delete with `isDeleted: true`. A stale version fails without overwriting another writer. HTTP uses authenticated `POST /<task>/events` with `kind: "board"`.

The editor also submits a `rendered` baseline for generated geometry and wrapping. That baseline cannot change words or ownership. Scene writes are atomic. Limits: 2,000 objects, 8 MiB scene JSON, 6 MiB embedded image data, 2 MiB per other attachment and 20 MiB attachment storage per task. Oversized authored scenes fail without silently dropping source material. The normal agent digest remains 4,000 characters.

## Lifecycle, storage and Jev

`start` enables a task; `stop` pauses it without deleting data; `shutdown` stops the shared service. Use actual host/session identities, never guessed working-directory identities. URLs remain stable after title changes. `status --summary` returns bounded authored previews and recent human board feedback.

Each task stores `state.json`, an editable `board.excalidraw`, a simplified offline `canvas.html`, and `chat.json` with its source conversation reference. Human input reaches the agent at normal checkpoints; canvas interactions do not secretly start an agent turn or execute tools.

Jev receives bounded authored excerpts and relationship types. Enhanced context adds bounded visible chat, board text/geometry and user feedback with consent. Native roles are authored data; neither role labels nor model choices establish factual correctness. Pixel layout stays local. Requests remain debounced, cached and capped by the configured daily request and byte allowances. API keys remain in the local service, never in the page. See [configuration and privacy](../README.md#optional-jev--typesafe).
