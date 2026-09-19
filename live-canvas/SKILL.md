---
name: live-canvas
description: Automatically open and maintain a live visual canvas for new Codex, Claude Code, Cursor, or OpenCode sessions; keep authored sections current with concise milestone updates.
---

# Live canvas

Use `scripts/live_canvas.py` beside this skill. It delegates to the adjacent dependency-free runtime. Automatic transcript following (Codex) and message/activity hooks (Claude Code/Cursor) make zero model calls and require no heartbeat or follow-up turns.

Use one persistent canvas per chat. Before opening, look for an existing tab for the clean returned URL and focus it; create a tab only when none exists. Avoid completion-summary Markdown files and alternate canvas tools unless explicitly requested.

## Opening is part of using the canvas

An explicit request to **use, show, open, or reopen the canvas requires showing its view**, even when its state is already enabled or contains current work. Run `start`, retain its URL, then run `auto-open claim --manual` with the same exact session prefix. Only when `should_open` is true, open that URL through the host browser and settle the returned claim as described below. Manual claims permit this explicit request when automatic opening is off or a previous opening was acknowledged; `start` explicitly re-enables a stopped session. Do not use `--manual` for unsolicited recovery. If another live claim owns the opening, do not dispatch a duplicate.

Starting or updating the runtime does not open a host panel. `opening.status` in start/update/status output is `not_started`, `stopped`, `unacknowledged`, `pending`, or `dispatched`. A dispatch acknowledgement is only historical dispatch evidence; `opening.visibility` remains `unverified` because the runtime cannot observe the host UI. Never describe an active canvas, a returned URL, or a successful update alone as visible.

## Automatic opening

For Codex, follow the managed AGENTS startup instruction on the first user turn. For hook-based clients, follow the SessionStart instruction on the next user turn after startup or resume without asking again: use its exact session command prefix, run `auto-open claim`, and only if `should_open` is true run `start --auto-claim <claim>`, open the returned URL in the host browser, inspect its result as described below, then acknowledge completed dispatch with `auto-open opened --claim <claim>`. If starting/opening fails, release with `auto-open release --claim <claim>` and continue the user's task. Never open when the claim is declined. Claude Code opens through a local worker; do not duplicate that opening. Hooks cannot directly open Codex/Cursor native panels before a user turn.

Respect an explicit `stop` or `auto-open off`. The global toggle is `python3 <skill-dir>/scripts/live_canvas.py auto-open off` (or `on`). A manual user request to reopen uses the explicit opening workflow above. Automatic opening does not require substantial work, but authored updates should remain small and useful.

## Start and inspect

For Codex, run:

```sh
python3 <skill-dir>/scripts/live_canvas.py start --title "<short task title>"
```

For any client with installed hooks, use the **exact session command prefix from SessionStart context**, followed by `start --title "<short task title>"` for a manual opening. It contains `--client codex|claude|cursor|opencode --session-id <actual-id>`; keep this prefix for subsequent commands. Cursor may also provide `LIVE_CANVAS_CLIENT` and `LIVE_CANVAS_SESSION_ID`. Never use another client's ID, infer IDs from directories, or invent a fallback ID. If session context is missing, load the installed hooks in a new chat; setup instructions are in the runtime README.

For every permitted opening claim, open the returned URL: Codex uses `mcp__codex_app__open_in_codex` with `{type:"browser",url:<url>}` and placement `"right"`; Cursor uses its built-in browser when exposed by the host. Otherwise open the URL in the user's browser (macOS `open`, Linux `xdg-open`). Claude Code uses this browser fallback; ordinary Claude chat has no supported native panel integration. Open the full returned bootstrap URL; its credential disappears after load. If a browser cannot resolve `canvas.localhost`, rerun the command with `LIVE_CANVAS_HOST=localhost`. Inspect the opening tool result. A `queued` result for a hidden task is **not** a completed opening: release the claim, explain that the tab awaits that task being shown, and do not claim visibility. On failure, release the claim and report the concrete blocker. On completed dispatch, acknowledge with `auto-open opened --claim <claim>` so subsequent ordinary turns do not reopen it. Then verify the exact target URL/tab through host browser state or a screenshot when those tools are available; if not, report that dispatch succeeded but visibility is unverified. When the user explicitly asks to open in another task, pass that exact `threadId` to the host tool; do not silently open in the calling task. Do not invent a host bridge or claim host trust based on configuration files.

Reuse an acknowledged viewer on ordinary turns. `status` returns metadata, URL, and `state_file`; `stop` disables this session. Do not use `shutdown` unless the shared service should stop.

To author an update, write a small JSON artifact and run the same session command with `update --file <json-path>`.

At the start of a meaningful turn, run `status --summary` and inspect its bounded digest and opening status first. If automatic opening is on and `opening.status` is `not_started` or `unacknowledged`, run the automatic claim/start/open/acknowledge flow once on this ordinary user turn; the claim creates missing state while preserving explicit stops and global opt-out. This also recovers sessions created before hooks were installed. Do not automatically reopen `dispatched` views, compete with `pending` claims, or revive `stopped` views. Never poll or create follow-up turns to retry. A legacy manually opened view with no acknowledgement may be recovered once; record the new acknowledgement to prevent repeated openings. An explicit use/show request always takes the manual workflow above instead. It is capped at 4,000 serialized characters and includes context, revision, current/outcome previews, and section IDs/titles/block counts/types with short previews. It excludes feed, history, and visual HTML. If `summary.truncated` is true, read the returned `state_file` only for the specific detail needed. Oversized metadata can be null with `metadata_truncated`; keep using the exact known session command, never a clipped summary identity or invented path. A blocked loopback health probe is not evidence that the server stopped; do not launch a second server.

## Author the actual work

Infer context from the user's objective and evidence; do not ask them to choose a mode. At most three small sections should be visible by default, with at most five short items per section and two-line summaries. Lead with the actual work: draft paragraphs, an argument, cited evidence, edit beats, candidate ideas, recall questions, or a concrete design. Do not make installation details, delivery recaps, agent activity, or generic status reports the main artifact unless that is the user’s task. Record meaningful changes only. Do not repeat arbitrary turn logs or generated prose.

Use `context.id`, a descriptive label, a short title, and flexible `sections` with stable IDs. Supported blocks are `text`, `list`, `checklist`, `table`, `reveal`, and `timeline`; the full schema and examples are in `../session-canvas/README.md`. Use `list.selectable: true` for candidate ideas the user can shortlist. Checklists are local review aids; recall cards offer Again / Got it practice. These browser-only actions are not sent back to you and are not proof of completion or learning. Never assume a local choice without user input. Keep long prose and wide comparisons focused; the viewer adapts tables at narrow widths. Primitive text supports safe bold/emphasis/code/links. `visual_html` is optional isolated HTML/SVG for a diagram, never a tool surface.

For the same context, prefer a delta:

```json
{"upsert_sections": [{"id": "evidence", "title": "Evidence", "blocks": []}], "remove_sections": ["old"]}
```

Upserts replace matching IDs in place and append new IDs; removals happen first. The complete result is validated atomically. Do not mix deltas with `sections`, which replaces the whole ordered list. Use a whole rewrite only for a new context or genuine structural rewrite. A changed context atomically clears stale authored content while preserving history.

Refresh authored content at meaningful milestones and before the final reply. Quiet periods retain useful content. Transcript messages and activity signals are automatic observations; they do not infer plans, grades, semantic adaptation, or completion. Never invent progress, scores, citations, timecodes, or test results.

## Recovery and limits

State defaults to `~/Library/Application Support/Live Canvas` on macOS or `$XDG_DATA_HOME/live-canvas` (normally `~/.local/share/live-canvas`) on Linux, overridable with `SESSION_CANVAS_HOME` (use the same location in hooks and commands). State is local and private, with loopback-only capability URLs. The viewer is read-only. Claude Code records the final visible response on Stop; Cursor records afterAgentResponse; both record generic activity without tool output or thoughts. These observations do not semantically rewrite sections: author concise changed sections at milestones and before the final reply. If hooks are unavailable, explicit updates still work with a known session ID. Do not edit global hooks or the user's existing canvas skill.

Optional TypeSafe presentation is user-controlled: `adaptive on|off|status|retry` are global commands. It selects among existing authored sections, with separately opted-in bounded visible chat context; keep authoring useful sections normally and never add model calls from a poll or heartbeat. Set a key through guided setup or `TYPESAFE_API_KEY` in the server’s launch environment. `adaptive status` reports configuration/budget without inference; browser “Follow suggested focus” changes layout only. Never enable remote inference without user authorization. Codex uses a managed startup instruction, not a CLI hook-trust step. File installation alone is not proof of panel visibility.


## First-run setup and later changes

For missing installation, client selection, API keys, or adjustable limits, guide the user to `python3 <bundle>/session-canvas/setup.py` in a terminal. `setup.py configure` revisits preferences without installing clients; `setup.py status` reports redacted effective configuration. The same configure command is available through the skill launcher. Do not ask users to paste keys into chat: hidden terminal entry or private stdin is supported. Saved credentials use a private plaintext file and never belong in authored canvas content. Codex setup installs managed startup instructions without editing hook trust. OpenCode uses a discoverable `.js` plugin and opens the OS browser. Verify the actual first-turn view after setup.
