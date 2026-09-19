# Runtime reference

The current viewer is an editable Excalidraw board. See the [main guide](../README.md) for installation, storage, privacy and controls. Earlier section-based content remains accepted and projects to editable text objects. Legacy HTML visuals and document-specific recall/checklist widgets are retained in state but are no longer active viewer controls.

## Shared scene API

`board --thread <exact-id> --file changes.json` accepts `{ "elements": [...], "base_versions": {...}, "files": {...} }`. Elements use the Excalidraw scene format; IDs and versions come from `state.json` under `board`. Submit only changed objects. An absent object is preserved; delete with `isDeleted: true`. A version conflict preserves saved state and returns failure. HTTP uses the same merge through authenticated `POST /<task>/events` with `kind: "board"`.

Limits: 2,000 objects, 8 MiB scene JSON, 6 MiB embedded image data, 2 MiB per non-image attachment and 20 MiB attachment storage per task. These bounds prevent unbounded local requests. The main-agent digest remains 4,000 characters. The static HTML snapshot is a simplified SVG rendering; download the `.excalidraw` file for full fidelity.

## Write a curated update

```sh
python3 canvas.py update --thread YOUR_THREAD_ID <<'JSON'
{
  "title": "A clearer session",
  "outcome": "The latest verified result.",
  "current": "What we are working on now.",
  "decisions": ["Keep task data separate."],
  "open": ["A question to resolve."],
  "next": ["The next concrete step."],
  "visual_title": "How it works",
  "visual_html": "<svg viewBox='0 0 300 100' xmlns='http://www.w3.org/2000/svg'><rect x='1' y='1' width='298' height='98' rx='12' fill='#e3ece6'/><text x='150' y='55' text-anchor='middle' fill='#222725'>Task → State → Canvas</text></svg>"
}
JSON
```

Omitted fields stay unchanged. `--file /path/update.json` is also supported. Only the documented fields are accepted. Arrays must contain strings; remaining fields must be strings. Updates persist even if the viewer is stopped. The previous content of the last 20 curated revisions is retained. Automatic events never overwrite these fields.

For an existing context, update only the sections that changed:

```json
{"upsert_sections": [{"id": "checks", "title": "Checks", "blocks": []}], "remove_sections": ["old"]}
```

An upsert replaces a matching section in place and appends a new section. Removals happen first; the resulting full section list is validated atomically. Do not combine section deltas with a whole `sections` replacement. Use a whole replacement for a new context or a real structural rewrite.

When no authored sections exist, the latest final reply becomes editable board text. The assistant feed remains bounded and internal memory-citation blocks are removed. Legacy `visual_html` remains stored but is not rendered in the board; use Excalidraw objects for diagrams and visual notes.

## Adaptive content for any task

The canvas has an open-ended authored context and six general-purpose block types. No scenario classifier, fixed mode list, or extra model call runs in the server. The active `live-canvas` skill instructs the assistant to choose useful structures at the start of a changed objective and update the actual work product at meaningful milestones. Transcript messages update automatically; semantic adaptation depends on the assistant following that instruction. Recall practice supports self-marked Again / Got it choices. These are browser-only practice marks, not grading or assistant-verified learning scores.

An update can contain:

```json
{
  "context": {"id": "my-current-objective", "label": "Planning a workshop", "description": "Optional context, uncertainty, or scope."},
  "title": "A useful working title",
  "sections": [
    {"id": "outline", "title": "An outline to discuss", "blocks": [
      {"id": "purpose", "type": "text", "text": "The purpose of this workshop."},
      {"id": "agenda", "type": "list", "ordered": true, "items": ["Welcome", "Practice together", "Share discoveries"]}
    ]}
  ]
}
```

Contexts accept any nonempty ID and label, with an optional description. Changing `context.id` atomically clears all previously authored content, including old sections, outcome/current text, visual, and legacy lists. Supply the new title/content in the same update. The old content is retained in revision history, and earlier assistant feed entries remain in the archive. Old automatic summaries are cleared; transcript backlogs older than the context boundary cannot restore them. `"context": null` switches back to an unclassified context and also resets content.

Within the same context, omitted fields stay intact; `sections` replaces the entire ordered section list when provided. `"replace": true` resets authored content even within the same context, preserving only the context unless replaced explicitly. Copy chosen relevant material into that same update for deliberate carry-over. A new context or replacement resets browser interactions through the context boundary. Unrelated feed updates preserve the work surface. Checklist marks, shortlists, recall position, and revealed answers survive reload in the same browser origin. Changed item text, answers, or authored checklist values invalidate the corresponding local choices.

Sections require unique `id`, string `title`, and `blocks`. Each block requires `id` (unique within its section) and `type`. Section/block/reveal IDs use 1–80 letters, numbers, underscores, dots, or hyphens and begin with a letter or number. At most 30 sections and 30 blocks per section are accepted. Unknown fields/types are rejected before mutation. Empty sections/blocks do not render filler.

| Type | Additional fields | Behavior |
| --- | --- | --- |
| `text` | `text`: string | Plain text, retaining line breaks. |
| `list` | `items`: strings; optional `ordered` and `selectable`: booleans | Bullets or an ordered outline. `selectable: true` enables a browser-only shortlist and Copy shortlist. |
| `checklist` | `items`: objects with `text` and optional boolean `checked` | Authored initial values with native, browser-local checkbox overrides. Local marks do not change task state or establish verified completion. |
| `table` | `columns`: strings; `rows`: arrays of strings with matching width | Horizontally scrollable comparison or evidence table. |
| `reveal` | `items`: objects with unique `id`, `prompt`, `answer` strings | One-card recall practice: Reveal answer, Again, Got it, navigation, and a retry queue. Marks stay in this browser. |
| `timeline` | `items`: objects with `label`, optional `detail` and `at` strings | Ordered beats, steps, or events; `at` is optional authored text, never synthesized. |

Primitive text is rendered through DOM text nodes. Text supports a small safe Markdown subset: bold, emphasis, inline code, and absolute HTTP(S)/mailto links. Raw HTML stays text; executable, local-file, and relative URLs become readable labels without links. Links use a new tab with no opener or referrer. HTML/SVG belongs only in the existing isolated `visual_html` surface. Sections may mix block types freely. The same primitives support study questions, idea groups, essay arguments/drafts, feature/check lists, edit beats, research notes, planning, and other scenarios. The UI does not guess interaction modes from task labels. Mark a list `selectable: true` only when choosing a shortlist is useful. Tables with more than two columns become labeled rows on narrow screens. Collections initially show five items/rows and the workspace shows three sections; remaining content is available through persisted Show more controls. Long authored summaries and text have explicit full-text disclosures rather than losing the rest of the content.

Six fictional examples are bundled in `examples/study.json`, `brainstorm.json`, `essay.json`, `feature.json`, `video.json`, and `custom.json`. They contain no claimed test passes, grades, media timecodes, or verified source data. Preview them only on a dedicated example thread; applying one to a real task intentionally switches its context:

```sh
python3 canvas.py start --thread example-preview
python3 canvas.py update --thread example-preview --file examples/study.json
```

Browser interactions never send writes to the runtime or the assistant. Settings explains this boundary and can reset local interactions; each interactive block also labels its local scope. Interaction storage uses compact SHA-256 content fingerprints and separate records, bounded per task to 400 records and 200,000 key/value characters, with older records pruned. Long authored answers are not duplicated into storage keys. A context change selects a different interaction namespace; a new context boundary never reuses earlier choices. Matching version-1 browser choices migrate automatically without overwriting newer records. Same-task tabs synchronize local changes through browser storage events. Different-item writes remain independent; simultaneous edits to the same item use the last write. Reset changes a shared per-task epoch so delayed writes from an older epoch cannot restore cleared choices. If browser storage is unavailable, interaction remains usable for the current page. Clearing site data or changing the server origin also loses saved choices.

The viewer accepts a new polling ETag only after parsing and rendering succeed, so failed response bodies are retried instead of stranding a stale view. The header reports the real connection separately from authored freshness (`curated_at`), so incoming chat messages do not make old work look freshly edited. Activity and version history start collapsed, with four short message previews and five readable prior versions in bounded scroll areas. Automatic responses never replace the main authored work. Copy work exports authored content; Copy shortlist exports the current local selection as plain visible text. A clipboard error reports failure rather than a false success.

Existing flat updates remain valid. Schema-1 states gain default context/sections on the next mutation while preserving previous content. History retains the original snapshots.

## Lifecycle

`start` enables a task; `stop` pauses it without deleting data; `shutdown` stops the shared service. Use exact session IDs, never a working-directory-derived identity. Explicit readable URLs stay stable after title changes. The launcher automatically registers the local Codex transcript when it can resolve the exact session.

`status --summary` returns a bounded digest including human board edits. The full `state_file` is available for deliberate object edits. Visible replies and prompts are captured locally at message boundaries; no tool results or private reasoning enter the board. Host adapters do not create follow-up agent turns.

## Security and model configuration

Refer to the [main guide](../README.md#optional-jev--typesafe) for Jev consent, key storage, limits and enhanced context. The service enforces task credentials and same-origin writes. Scene saves are atomic and version checked. Static snapshots and transcript references remain private local files. No API key is sent to the browser.
