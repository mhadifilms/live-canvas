# Session canvas

A live, local side panel for Codex, Claude Code, and Cursor sessions. Python 3.9+ standard library only; no packages, build step, remote services, or Herdr dependency. The browser reads state once per second using conditional requests; Codex transcript updates are followed every 0.8 seconds. Hidden browser tabs poll every five seconds.

## Install for Claude Code and Cursor

From this directory, preview the exact configuration paths and then install:

```sh
python3 install_clients.py dry-run
python3 install_clients.py install
python3 install_clients.py check
```

Default scope is both clients; add `--client claude` or `--client cursor` for one. The installer adds `live-canvas` at `~/.claude/skills/live-canvas` and `~/.cursor/skills/live-canvas`, linking to this bundle. Keep the bundle in place. It merges command hooks into `~/.claude/settings.json` and `~/.cursor/hooks.json` (version 1). It never changes an existing `canvas` skill. Other settings and hooks are preserved; collisions, modified owned hooks, symlinked config files, and unsupported schema versions are refused before changes. `dry-run` and `check` are read-only; `check` exits 1 when missing or incomplete.

Changed configuration bytes are backed up privately under each client's `.live-canvas-backups/`; ownership is tracked in `.live-canvas-install.json`. Repeated installation is idempotent. To remove this integration while preserving later unrelated edits:

```sh
python3 install_clients.py uninstall
```

Uninstall removes only unchanged owned entries and the skill link it created. It keeps backups and canvas state; it does not restore a whole old settings file over newer edits. If an owned hook was edited, review that change and restore the exact owned entry (or remove it) before retrying. `--user-home /temporary/directory` exercises the same installer against fixture configs. Multi-client installation preflights both targets but is not a filesystem-wide transaction: an I/O failure during mutation may leave one installed; rerun `check` and use `uninstall` or retry to recover.

Start a **new client chat after installation**, or restart the host if its hooks/skill cache requires it. Ask “open live canvas” or invoke `/live-canvas` where supported. SessionStart supplies the exact command prefix and session identity; no manual ID lookup is needed. The skill opens the same viewer in Cursor's built-in browser when the host exposes one, otherwise in a normal browser. Claude Code uses a normal browser; there is no native panel integration for ordinary Claude chat. Claude environments without access to this local filesystem and loopback server cannot use the local installation.

For explicit commands, use the prefix from the actual SessionStart context:

```sh
python3 ../live-canvas/scripts/live_canvas.py --client claude --session-id ACTUAL_SESSION_ID start --title "Current work"
python3 ../live-canvas/scripts/live_canvas.py --client cursor --session-id ACTUAL_CONVERSATION_ID status --summary
```

Retain `--client` and `--session-id` for every `update`, `status`, or `stop`. Cursor SessionStart also injects `LIVE_CANVAS_CLIENT`/`LIVE_CANVAS_SESSION_ID` when the host honors environment output. Explicit identities work even if `CODEX_THREAD_ID` is inherited. State keys are `claude:<session_id>` and `cursor:<conversation_id>`; existing Codex task keys remain compatible. Cursor's SessionStart-only `session_id` is accepted as a fallback when common `conversation_id` is absent. Never guess an ID from a working directory or use another client's ID.

Only explicitly started canvases receive data. SessionStart adds brief context and optionally signals an already-active canvas; it never starts a server or opens a browser. Claude hooks record generic SessionStart/UserPromptSubmit/PostToolUse/Stop signals and `Stop.last_assistant_message`. Cursor hooks record generic sessionStart/beforeSubmitPrompt/postToolUse/stop signals and `afterAgentResponse.text`. Visible response delivery occurs at these message boundaries, not token streaming. Prompt content, tool arguments/results, thought events, and transcripts are not read by these adapters. Duplicate completed messages are deduplicated (Claude identical response text is retained once; Cursor distinguishes generation IDs). Malformed/oversized input and busy state fail open; hooks never block, request follow-up turns, or call a model. A missed event is not replayed automatically.

Authored sections still require concise model-written updates at meaningful milestones and before the final reply. Automatic events do not infer an outline, plan, progress percentage, or semantic adaptation. This avoids a background model loop and repeated history loads. A hook update does not start a stopped shared server; explicitly run `start` to resume it. Keep `SESSION_CANVAS_HOME` consistent between the host's hook environment and manual commands if overriding the default state directory.

Payload/config references: [Claude Code hooks](https://code.claude.com/docs/en/hooks), [Claude Code skills](https://code.claude.com/docs/en/skills), [Cursor hooks](https://cursor.com/docs/hooks), [Cursor skills](https://cursor.com/docs/skills). Hook availability and browser tools depend on the installed host version and local policy; fixture tests do not prove that a host has loaded its hooks.

## Open a canvas

From this directory:

```sh
python3 canvas.py start --thread YOUR_THREAD_ID --title "Your task" --transcript /absolute/path/to/task.jsonl
```

Open the returned `url` in the Codex browser panel. `CODEX_THREAD_ID` supplies the thread when `--thread` is omitted. Missing task identity is an error; there is no shared anonymous canvas. An explicit transcript path is optional. Without it, the panel receives CLI updates and enabled hook/feed events. The sibling `live-canvas` skill provides automatic transcript discovery and panel-opening instructions.

Persistent private state defaults to `.state` beside the runtime. Set `SESSION_CANVAS_HOME` or pass `--home /absolute/path` **before** the subcommand to use another location. Files are created with mode `0600`, directories with `0700`. Use the same home on every invocation. The server binds only `127.0.0.1` and may require local-network permission from the Codex sandbox.

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

The latest assistant final response or commentary takes display precedence when it is newer than the curated update. Long content is expandable. The assistant feed retains the last 40 entries. Known internal memory-citation blocks are removed; other text is displayed literally and cannot execute HTML.

`visual_html` is intentionally a separate authoring surface: HTML and SVG render in an empty-sandbox iframe. Scripts, network requests, forms, embedded external content, and parent access are blocked. Inline CSS and data images are permitted. This supports diagrams and static visual notes, not interactive JavaScript applications. The outer viewer also has a restrictive content security policy.

## Adaptive content for any task

The canvas has an open-ended authored context and six general-purpose block types. No scenario classifier, fixed mode list, or extra model call runs in the server. The active `live-canvas` skill instructs the assistant to choose useful structures at the start of a changed objective and update the actual work product at meaningful milestones. Transcript messages update automatically; semantic adaptation depends on the assistant following that instruction. Local disclosure interactions do not grade answers or persist learning scores.

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

Within the same context, omitted fields stay intact; `sections` replaces the entire ordered section list when provided. `"replace": true` resets authored content even within the same context, preserving only the context unless replaced explicitly. Copy chosen relevant material into that same update for deliberate carry-over. A new context or replacement closes earlier reveal cards. Ordinary transcript revisions leave authored blocks and open disclosures intact; updated questions start closed. Disclosure state lasts for the current browser page, not across a reload.

Sections require unique `id`, string `title`, and `blocks`. Each block requires `id` (unique within its section) and `type`. Section/block/reveal IDs use 1–80 letters, numbers, underscores, dots, or hyphens and begin with a letter or number. At most 30 sections and 30 blocks per section are accepted. Unknown fields/types are rejected before mutation. Empty sections/blocks do not render filler.

| Type | Additional fields | Behavior |
| --- | --- | --- |
| `text` | `text`: string | Plain text, retaining line breaks. |
| `list` | `items`: strings; optional `ordered`: boolean | Bullets or an ordered outline. |
| `checklist` | `items`: objects with `text` and optional boolean `checked` | Read-only authored status; no completion is inferred. |
| `table` | `columns`: strings; `rows`: arrays of strings with matching width | Horizontally scrollable comparison or evidence table. |
| `reveal` | `items`: objects with unique `id`, `prompt`, `answer` strings | Click or keyboard-activate a question to reveal its answer. |
| `timeline` | `items`: objects with `label`, optional `detail` and `at` strings | Ordered beats, steps, or events; `at` is optional authored text, never synthesized. |

All primitive text is escaped through DOM text nodes. HTML/SVG belongs only in the existing isolated `visual_html` surface. Sections may mix block types freely. The same primitives support study questions, idea groups, essay arguments/drafts, feature/check lists, edit beats, research notes, planning, and other scenarios. The UI does not impose scenario-specific labels or quotas.

Six fictional examples are bundled in `examples/study.json`, `brainstorm.json`, `essay.json`, `feature.json`, `video.json`, and `custom.json`. They contain no claimed test passes, grades, media timecodes, or verified source data. Preview them only on a dedicated example thread; applying one to a real task intentionally switches its context:

```sh
python3 canvas.py start --thread example-preview
python3 canvas.py update --thread example-preview --file examples/study.json
```

Existing flat updates remain valid. Schema-1 states gain default context/sections on the next mutation while preserving previous content. History retains the original snapshots.

## Automatic sources

Registered transcripts must begin with `session_meta` matching the exact task ID. The follower reads only that path, persists its byte offset, handles partial append lines, deduplicates message IDs, and resumes after restart. It reads assistant `response_item` messages whose phase is `commentary`, `final_answer`, or `final`, and only their `output_text`. It excludes user/developer/system text, reasoning, inter-agent messages, tool arguments, and tool results. Turn and tool signals convey observed activity, not inferred progress. A turn completion leaves the follower running for the next turn. Existing transcript history is processed on registration; large transcripts can take several polling cycles to catch up.

An external integration may send explicit assistant text:

```sh
python3 canvas.py feed --thread YOUR_THREAD_ID <<'JSON'
{"kind":"commentary","text":"The visible assistant update.","source":"My integration","event_id":"unique-message-id"}
JSON
```

Feed kinds are `commentary`, `final`, and `activity`. Feed writes are ignored for tasks that have not been enabled with `start`, or have been disabled with `stop`.

Hooks can call:

```sh
python3 canvas.py hook --event PostToolUse
```

The hook reads JSON on stdin. It resolves task identity from `--thread`, then `CODEX_THREAD_ID`, then input `thread_id` or `session_id`. `--event` overrides `hook_event_name` / `event_name`. Recognized events are `SessionStart`, `UserPromptSubmit`, `PostToolUse`, and `Stop`; recognition does not mean a given Codex host supports that event. Configure only events supported by your host. Missing identity, disabled tasks, unrecognized events, contention, and input errors fail open with exit zero. Hook ingestion excludes input/output bodies and does not start servers or create state for unknown tasks. No global hooks are installed by this runtime.

## Lifecycle and freshness

```sh
python3 canvas.py status --thread YOUR_THREAD_ID
python3 canvas.py stop --thread YOUR_THREAD_ID
python3 canvas.py start --thread YOUR_THREAD_ID
python3 canvas.py shutdown
```

`stop` disables automatic ingestion for one task while retaining its view and data. `start` resumes it. `shutdown` stops the shared server for all tasks without deleting state. A restart tries to reuse its private URL token and port; if that port is occupied, open the new returned URL. `status` and `update` report an unverified health state with the recorded URL if the environment blocks loopback probing; they do not claim that a blocked probe means the server is stopped. `start` refuses to launch a duplicate when this health check is blocked.

For agent inspection, begin with `python3 canvas.py status --thread YOUR_THREAD_ID --summary`. The result is a deterministic digest capped at 4,000 serialized characters and includes the `state_file` path, context, revision, current/outcome previews, and section IDs, titles, block counts/types, and short previews. It never includes feed, history, or `visual_html`; `summary.truncated` tells you when material was omitted. Read the state file only for a targeted follow-up.

The compact viewer retains the latest authored content while automatic events arrive. Source and activity details remain available in state and status output. Quiet periods do not imply completion, and observations never invent progress.

All HTTP methods that could mutate data are rejected. Only capability-protected known viewer, state, and health paths are served; arbitrary files are never served. Host and Origin checks block foreign website access and DNS rebinding. The capability URL is private: anyone with local access and that URL can read the canvas. It is not an authentication boundary against other processes running as the same OS user. Curated and automatic writes use the same file lock and atomic replacement.

## Verification

From the project root:

```sh
python3 -m unittest discover -s session-canvas -v
```

Tests cover per-task isolation, concurrent writes, automatic/curated separation, disabled hooks, deduplication, transcript identity/privacy, partial-line recovery, private state permissions, endpoint restrictions, origin checks, read-only HTTP, legacy migration, context switching, explicit replacement, schema validation, and all six fixtures. Browser verification should also confirm live updates without reload, narrow light/dark layout, retained state after server restart, sandboxed visuals, stable reveals across activity refreshes, and closed reveals after context/question changes.
