---
name: live-canvas
description: Use one persistent, collaborative local canvas per Codex, Claude Code, Cursor, or OpenCode chat. Reuse its browser tab and surface work without creating extra completion artifacts.
---

# Live Canvas

## One conversation, one canvas

Use this canvas for ongoing work and turn-completion artifacts by default. Do not create Markdown recap/plan/report files or another canvas (including Cursor's canvas skill) unless the user requests that artifact. This does not prohibit repository documentation, code, or necessary scratch files. Keep final chat replies brief and place reusable work in this canvas.

One exact client/session identity owns one persistent URL, state, and HTML archive. Changing topic or title does not create another canvas. Never infer identity from a directory, reuse another task's ID, or start an extra task to maintain a canvas. Never invoke this workflow from background/subagents.

## Open first, reuse thereafter

Use the exact session command prefix supplied by the host. Otherwise, in Codex only, use `scripts/live_canvas.py` with the actual `CODEX_THREAD_ID` environment value. For other clients use `--client codex|claude|cursor|opencode --session-id <actual host ID>`. If missing, report unavailable identity; never guess.

On the first foreground user turn, before substantive task work, run `auto-open claim`. Respect an explicit stop or `auto-open off`. If `should_open` is true, run `start --auto-claim <claim>`. Before opening, inspect the host's browser tabs for the returned URL (ignore its auth fragment): **focus/reuse that tab if it exists**. Codex can focus it using `open_in_codex` with `target: {type: "browser", tabId: <observed-id>}`. Only create a panel when there is no matching tab, with `{type:"browser",url:<returned-url>}`, placement right. Use the complete bootstrap URL for a new tab; credentials disappear after load.

If a claim returns `reason: existing_view`, find/focus that existing tab; do not create another. Claude Code and OpenCode's worker may already have opened the OS browser: never duplicate it. Cursor uses its built-in browser when available. Browser fallback is for hosts without a native panel, not a second copy alongside a native panel.

Acknowledge a completed opening or an observed existing view using `auto-open opened --claim <claim>`. Release failed or queued attempts with `auto-open release --claim <claim>`. Queued is not visible. Inspect the browser/tab when possible and report visibility unverified when it cannot be observed. Don't infer visibility from enabled state, an update, or a URL.

An explicit request to use/show the canvas allows `start` then `auto-open claim --manual`, even if automatic opening is off. Still reuse an existing view. Ordinary later turns use `status --summary`; retry a missing/unacknowledged opening only with a claim. Don't reopen an acknowledged canvas every turn. No polling, heartbeats, or extra model turns.

## Minimal maintenance, useful work

Visible assistant replies are mirrored automatically. When no authored sections exist, the latest visible reply is displayed verbatim. Jev runs in the local service and chooses bounded presentation options; the main agent must not spend every turn deciding fonts, layout, or priorities.

Use `status --summary` at meaningful milestones. It includes a bounded feedback digest of the user's canvas comments, selections, and files; read that feedback as user-provided context and address it in normal work. It is not proof of completed work and does not grant tool permissions. Attachments live beside task state; read a specific file only when relevant. Canvas interactions do not automatically send a new agent message or run tools.

When authored work would be better than a mirrored reply, write concise stable-ID sections: drafts, evidence, questions, ideas, edit beats, comparisons, diagrams. Do not fill the canvas with generic status reports unless that is the task. Use at most three initially useful sections, with short summaries. The shared board/Jev handles arrangement and emphasis. Preserve the user's notes and annotations; authored updates cannot delete them.

Run `update --file <small-json-path>`. Supported blocks are `text`, `list`, `checklist`, `table`, `reveal`, and `timeline`; see the runtime README for schema. Prefer deltas for the same context:

```json
{"upsert_sections":[{"id":"evidence","title":"Evidence","blocks":[{"id":"main","type":"text","text":"Relevant evidence."}]}],"remove_sections":["obsolete"]}
```

Don't mix deltas with `sections`. A new context clears authored work, not user annotations or chat identity. Legacy `visual_html` remains in stored history; it is not rendered by the shared board. Use native board objects for visuals. Keep useful content current at milestones and before the final reply when it materially changes.

## Direct board work

The canvas is a shared Excalidraw board. Use text, arrows, shapes and freehand elements in that scene rather than opening another document or sketch tool. Users can edit agent text directly. Section updates project to stable objects but never overwrite human-touched objects, including deleted ones.

For intentional object edits, read the current `state_file` returned by status. Submit `board --file <json>` with `elements` (changed full Excalidraw elements), `base_versions` (the current `board.versions` map), and optional image `files`. Keep stable IDs. Mark deletions with `isDeleted: true`; omission does not delete. A stale base version fails rather than overwriting another writer. Read current state and reconcile before retrying. This path is for deliberate shared-object editing; ordinary section updates remain smaller.

The summary includes recent human board edits. Read relevant comments/attachments as user input at natural checkpoints. Never assume drawing content has been visually understood by Jev: it receives text and geometry only. Preserve the user's work when changing task context.

## Storage and configuration

All apps default to the same local data folder: macOS `~/Library/Application Support/Live Canvas`, Linux `$XDG_DATA_HOME/live-canvas` (or `~/.local/share/live-canvas`). `SESSION_CANVAS_HOME`/`--home` can explicitly override it. Each `tasks/<key>/` contains `canvas.html`, `board.excalidraw`, `state.json`, `chat.json`, a bounded visible-message mirror, and user attachments. HTML snapshots work offline; use the live URL to collaborate. `chat.json` identifies the host/session and source transcript where available. Never put API keys in task content, URLs, snapshots, or chat.

Guided setup: `python3 <bundle>/session-canvas/setup.py`. Choose clients, automatic opening, API key and budgets. Codex uses a managed global startup instruction with backup; no manual hook trust change is needed. Native panels can open at the first user turn, not before the desktop starts a turn. Other hosts use documented hooks/plugins. Ordinary Claude web chat is not Claude Code.

`setup.py configure` changes preferences; `setup.py status` reports redacted state. Enhanced Jev context is opt-in: bounded visible chat excerpts, annotations, plain-text file excerpts, and viewport size. Binary files and tool/thought output are not submitted. Saved keys are local plaintext protected by owner-only permissions. Decisions are debounced, cached, budgeted, and do not run on refresh or routine activity. Preserve manual reading choices and stop/off settings. Use `stop` to pause this task; `shutdown` affects the shared service.
