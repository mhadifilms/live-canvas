---
name: live-canvas
description: Open and maintain a live visual canvas for substantial work in Codex, Claude Code, or Cursor; keep authored sections current with concise milestone updates.
---

# Live canvas

Use `scripts/live_canvas.py` beside this skill. It delegates to the adjacent dependency-free runtime. Automatic transcript following (Codex) and message/activity hooks (Claude Code/Cursor) make zero model calls and require no heartbeat or follow-up turns. Activate for requested or substantial work; leave trivial chats alone.

## Start and inspect

For Codex, run:

```sh
python3 <skill-dir>/scripts/live_canvas.py start --title "<short task title>"
```

For Claude Code or Cursor, use the **exact session command prefix from SessionStart context**, followed by `start --title "<short task title>"`. It contains `--client claude|cursor --session-id <actual-id>`; keep this prefix for every subsequent command. Cursor may also provide `LIVE_CANVAS_CLIENT` and `LIVE_CANVAS_SESSION_ID`. Never use a Codex ID for another client, infer IDs from directories, or invent a fallback ID. If session context is missing, load the installed hooks in a new chat; setup instructions are in the runtime README.

Open the returned URL once: Codex uses `mcp__codex_app__open_in_codex` with `{type:"browser",url:<url>}` and placement `"right"`; Cursor uses its built-in browser when exposed by the host. Otherwise open the URL in the user's browser (macOS `open`, Linux `xdg-open`). Claude Code uses this browser fallback; ordinary Claude chat has no supported native panel integration. Reuse the viewer afterward. `status` returns metadata, URL, and `state_file`; `stop` disables this session. Do not use `shutdown` unless the shared service should stop.

To author an update, write a small JSON artifact and run the same session command with `update --file <json-path>`.

At the start of a meaningful turn, run `status --summary` and inspect its bounded digest first. It is capped at 4,000 serialized characters and includes context, revision, current/outcome previews, and section IDs/titles/block counts/types with short previews. It excludes feed, history, and visual HTML. If `summary.truncated` is true, read the returned `state_file` only for the specific detail needed. A blocked loopback health probe is not evidence that the server stopped; do not launch a second server.

## Author the actual work

Infer context from the user's objective and evidence; do not ask them to choose a mode. At most three small sections should be visible by default, with at most five short items per section and two-line summaries. Show the actual artifact: an outline, argument, evidence, edit beats, candidate ideas, or verified checks. Record meaningful changes only. Do not repeat arbitrary turn logs or generated prose.

Use `context.id`, a descriptive label, a short title, and flexible `sections` with stable IDs. Supported blocks are `text`, `list`, `checklist`, `table`, `reveal`, and `timeline`; the full schema and examples are in `../session-canvas/README.md`. Primitive text is escaped. `visual_html` is optional isolated HTML/SVG for a diagram, never a tool surface.

For the same context, prefer a delta:

```json
{"upsert_sections": [{"id": "evidence", "title": "Evidence", "blocks": []}], "remove_sections": ["old"]}
```

Upserts replace matching IDs in place and append new IDs; removals happen first. The complete result is validated atomically. Do not mix deltas with `sections`, which replaces the whole ordered list. Use a whole rewrite only for a new context or genuine structural rewrite. A changed context atomically clears stale authored content while preserving history.

Refresh authored content at meaningful milestones and before the final reply. Quiet periods retain useful content. Transcript messages and activity signals are automatic observations; they do not infer plans, grades, semantic adaptation, or completion. Never invent progress, scores, citations, timecodes, or test results.

## Recovery and limits

State defaults to the resolved bundle's `session-canvas/.state`, overridable with `SESSION_CANVAS_HOME` (use the same location in hooks and commands). State is local and private, with loopback-only capability URLs. The viewer is read-only. Claude Code records the final visible response on Stop; Cursor records afterAgentResponse; both record generic activity without tool output or thoughts. These observations do not semantically rewrite sections: author concise changed sections at milestones and before the final reply. If hooks are unavailable, explicit updates still work with a known session ID. Do not edit global hooks or the user's existing canvas skill.
