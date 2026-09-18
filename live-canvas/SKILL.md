---
name: live-canvas
description: Automatically open and maintain a live visual canvas for new Codex, Claude Code, or Cursor sessions; keep authored sections current with concise milestone updates.
---

# Live canvas

Use `scripts/live_canvas.py` beside this skill. It delegates to the adjacent dependency-free runtime. Automatic transcript following (Codex) and message/activity hooks (Claude Code/Cursor) make zero model calls and require no heartbeat or follow-up turns.

## Automatic opening

Follow the SessionStart instruction on the first user turn without asking again: use its exact session command prefix, run `auto-open claim`, and only if `should_open` is true run `start --auto-claim <claim>`, open the returned URL in the host browser, then acknowledge with `auto-open opened --claim <claim>`. If starting/opening fails, release with `auto-open release --claim <claim>` and continue the user's task. Never open when the claim is declined. Claude Code opens through a local worker; do not duplicate that opening. Hooks cannot directly open Codex/Cursor native panels before a user turn.

Respect an explicit `stop` or `auto-open off`. The global toggle is `python3 <skill-dir>/scripts/live_canvas.py auto-open off` (or `on`). A manual user request to reopen still permits the explicit start workflow below. Automatic opening does not require substantial work, but authored updates should remain small and useful.

## Start and inspect

For Codex, run:

```sh
python3 <skill-dir>/scripts/live_canvas.py start --title "<short task title>"
```

For any client with installed hooks, use the **exact session command prefix from SessionStart context**, followed by `start --title "<short task title>"` for a manual opening. It contains `--client codex|claude|cursor --session-id <actual-id>`; keep this prefix for subsequent commands. Cursor may also provide `LIVE_CANVAS_CLIENT` and `LIVE_CANVAS_SESSION_ID`. Never use another client's ID, infer IDs from directories, or invent a fallback ID. If session context is missing, load the installed hooks in a new chat; setup instructions are in the runtime README.

Open the returned URL once: Codex uses `mcp__codex_app__open_in_codex` with `{type:"browser",url:<url>}` and placement `"right"`; Cursor uses its built-in browser when exposed by the host. Otherwise open the URL in the user's browser (macOS `open`, Linux `xdg-open`). Claude Code uses this browser fallback; ordinary Claude chat has no supported native panel integration. Open the full returned bootstrap URL; its credential disappears after load. If a browser cannot resolve `canvas.localhost`, rerun the command with `LIVE_CANVAS_HOST=localhost`. Reuse the viewer afterward. `status` returns metadata, URL, and `state_file`; `stop` disables this session. Do not use `shutdown` unless the shared service should stop.

To author an update, write a small JSON artifact and run the same session command with `update --file <json-path>`.

At the start of a meaningful turn, run `status --summary` and inspect its bounded digest first. It is capped at 4,000 serialized characters and includes context, revision, current/outcome previews, and section IDs/titles/block counts/types with short previews. It excludes feed, history, and visual HTML. If `summary.truncated` is true, read the returned `state_file` only for the specific detail needed. Oversized metadata can be null with `metadata_truncated`; keep using the exact known session command, never a clipped summary identity or invented path. A blocked loopback health probe is not evidence that the server stopped; do not launch a second server.

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

State defaults to the resolved bundle's `session-canvas/.state`, overridable with `SESSION_CANVAS_HOME` (use the same location in hooks and commands). State is local and private, with loopback-only capability URLs. The viewer is read-only. Claude Code records the final visible response on Stop; Cursor records afterAgentResponse; both record generic activity without tool output or thoughts. These observations do not semantically rewrite sections: author concise changed sections at milestones and before the final reply. If hooks are unavailable, explicit updates still work with a known session ID. Do not edit global hooks or the user's existing canvas skill.
