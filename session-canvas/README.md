# Session canvas

A live, local side panel for Codex, Claude Code, and Cursor sessions. Python 3.9+ standard library only; no packages, build step, remote services, or Herdr dependency. The browser reads state once per second using conditional requests; Codex transcript updates are followed every 0.8 seconds. Hidden browser tabs poll every five seconds.

## Install and automatically open new chats

From this directory:

```sh
python3 install_clients.py dry-run
python3 install_clients.py install
python3 install_clients.py check
```

The default installs Codex, Claude Code, and Cursor. Select one with `--client codex|claude|cursor`; `--client both` retains the earlier Claude Code + Cursor selection. Skill links are named `live-canvas`; existing `canvas` skills are never modified. The installer merges `~/.codex/hooks.json`, `~/.claude/settings.json`, and version-1 `~/.cursor/hooks.json`, preserving unrelated hooks and settings. Codex uses `CODEX_HOME` when set for the real user home. Its hooks feature must be enabled separately: `codex features enable hooks`. The installer never edits `config.toml`.

Start a new foreground chat after installation; restart the host if it caches hooks. Automatic opening is on by default:

- **Codex:** SessionStart supplies the exact session prefix and a short instruction to open the right-hand browser panel on the first user turn. The hook cannot directly open the native panel on a blank-chat click.
- **Cursor:** the first user turn opens the built-in browser when exposed by the host, otherwise the OS browser.
- **Claude Code:** a detached local worker starts the shared server and dispatches the OS browser at startup, without a model call. macOS uses `open`; Linux requires a graphical session and `xdg-open`.

Only `source: startup` triggers Codex/Claude automatic opening. Cursor sessionStart accepts absent source as startup. Resume, clear, compact, and fork never trigger opening. Cursor's documented `is_background_agent`, plus explicit background/subagent/noninteractive indicators supplied by other hosts, suppress opening. Absence of those indicators is not proof that a host is interactive. A main custom `agent_type` is not treated as a subagent.

Session identities are exact: Codex retains its raw task ID; Claude uses `claude:<session_id>`; Cursor uses `cursor:<conversation_id>` (sessionStart can fall back to `session_id`). No IDs are inferred from a working directory. SessionStart injects the command prefix, and Cursor also supplies environment values when the host supports them.

Disable or re-enable automatic opening for the shared state directory:

```sh
python3 canvas.py auto-open off
python3 canvas.py auto-open on
python3 canvas.py auto-open status
```

The off switch affects automatic opening; explicit manual `start` still works. `stop --thread <exact-key>` disables a session, and startup hooks do not re-enable it. Claims serialize automatic opening attempts across repeated hooks and concurrent turns. Native opening follows `auto-open claim`, `start --auto-claim <claim>`, browser tool success, then `auto-open opened --claim <claim>`. Failed attempts use `auto-open release --claim <claim>`; interrupted claims expire after five minutes. A crash between UI opening and acknowledgement can result in a repeated opening on retry. OS dispatch success is not proof that a browser rendered the page.

The hooks do not retry themselves or create follow-up model turns. A failed opening can be retried on a later startup or manually; errors release the claim when possible. The Claude worker bounds shared-server startup to ten seconds and OS dispatch to three seconds, outside the two-second hook process. Automatic observations still make zero model calls. Useful authored sections require concise updates at milestones and before the assistant's final reply.

Claude hooks record generic activity and `Stop.last_assistant_message`; Cursor records generic activity and `afterAgentResponse.text`. Responses arrive at message boundaries rather than token streaming. These adapters never read prompts, tool inputs/results, thoughts, or transcripts. Codex registers its transcript through the launcher as before. Stopped sessions ignore observations. Malformed input and state contention fail open.

### Reversible configuration

Keep this checkout in place because hook commands and skill links reference it. Changed files are backed up privately in each client's `.live-canvas-backups/`, with ownership recorded in `.live-canvas-install.json`. Known schema-1 manifests upgrade in place, preserving previous backup and skill-link ownership. Unowned or edited hooks, incompatible manifests, conflicting skills, symlinked configs, and unsupported versions are refused. To move the bundle or change interpreters, uninstall using the original installer first.

```sh
python3 install_clients.py uninstall
```

Uninstall removes only unchanged owned hook entries and links it created, preserving later unrelated edits, earlier skill links, backups, and canvas data. It does not replace current settings with an old backup. `dry-run` and `check` are read-only; check validates installation files, not host hook loading or the Codex feature flag. `--user-home /temporary/directory` targets fixture configurations. All clients are preflighted before writes, but multiple files are not one filesystem transaction; interrupted installs can be inspected with check and retried or uninstalled.

Keep `SESSION_CANVAS_HOME` consistent between hook processes and manual commands. SessionStart's injected prefix includes the actual state directory. Ordinary Claude chat has no native panel integration, and remote environments need access to their own local filesystem and loopback viewer.

References: [Codex hooks](https://developers.openai.com/es-419/docs/hooks), [Claude Code hooks](https://code.claude.com/docs/en/hooks), [Claude Code skills](https://code.claude.com/docs/en/skills), [Cursor hooks](https://cursor.com/docs/hooks), [Cursor skills](https://cursor.com/docs/skills).

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

For agent inspection, begin with `python3 canvas.py status --thread YOUR_THREAD_ID --summary`. The result is a deterministic digest capped at 4,000 serialized characters and includes the `state_file` path, context, revision, current/outcome previews, and section IDs, titles, block counts/types, and short previews. It never includes feed, history, or `visual_html`; `summary.truncated` tells you when material was omitted. Read the state file only for a targeted follow-up. Context and thread previews may be clipped with `summary.truncated: true`; do not use clipped previews as command identities. Top-level task identity and `state_file` are preserved exactly when they fit; oversized metadata is `null` with `metadata_truncated: true`, rather than a misleading partial identity or path. Use your known session command when metadata is omitted.

The compact viewer retains the latest authored content while automatic events arrive. Source and activity details remain available in state and status output. Quiet periods do not imply completion, and observations never invent progress.

All HTTP methods that could mutate data are rejected. Only capability-protected known viewer, state, and health paths are served; arbitrary files are never served. Host and Origin checks block foreign website access and DNS rebinding. The capability URL is private: anyone with local access and that URL can read the canvas. It is not an authentication boundary against other processes running as the same OS user. Curated and automatic writes use the same file lock and atomic replacement.

## Verification

From the project root:

```sh
python3 -m unittest discover -s session-canvas -v
node --test session-canvas/test_viewer.mjs
```

Tests cover per-task isolation, concurrent writes, automatic/curated separation, disabled hooks, deduplication, transcript identity/privacy, partial-line recovery, private state permissions, endpoint restrictions, origin checks, read-only HTTP, legacy migration, context switching, explicit replacement, schema validation, and all six fixtures. Node helper tests cover safe links/text, local persistence and invalidation, denied storage, and bounded caches without extra dependencies. Browser verification must separately confirm keyboard and screen-reader names, native checkbox behavior, recall/shortlist persistence through polling and reload, changed-answer reset, clipboard success/failure, narrow light/dark layouts, bounded activity/history, authored freshness, and sandboxed visuals.
