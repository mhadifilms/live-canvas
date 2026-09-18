# Design notes

Live Canvas keeps a compact work product visible beside a conversation. Its content model stays general: the assistant chooses sections appropriate to the objective, and updates them at meaningful milestones. The runtime does not classify tasks or call a model.

## Content and interaction

Each canvas holds a context, authored sections, recent visible assistant messages, generic activity signals, and bounded revision history. Sections can mix text, lists, checklists, tables, reveal cards, and timelines. Optional HTML/SVG is isolated in a sandboxed frame. Primitive text is escaped through DOM text nodes.

Stable section IDs support small replacement deltas. Changing the context clears stale authored content in the same atomic update. Reveal cards remain open across unrelated automatic refreshes and close when their questions or context change. The compact interface prioritizes the work over status metadata and adapts to narrow viewports and light/dark themes.

## Runtime

The Python standard-library server binds to loopback and serves only known capability-protected viewer, state, and health routes. HTTP clients cannot mutate state. The browser uses conditional requests; local commands and adapters use file locking and atomic replacement. Private files are created with mode `0600` and state directories with mode `0700`.

One server can host multiple session canvases. Claude Code and Cursor identities include their provider prefix; Codex retains its original task IDs for compatibility. Start enables one canvas, stop disables its automatic ingestion, and shutdown stops the shared server while preserving state. Health checks distinguish unavailable loopback access from a stopped process.

Codex follows only a registered transcript whose metadata matches the selected task. It persists the byte offset and reads visible assistant text and generic lifecycle/tool signals. Claude Code and Cursor use documented command-hook events. These hooks admit visible response text and fixed activity labels, exclude private tool/reasoning bodies, fail open, and never open a browser or start a model follow-up loop.

## Cost and limitations

Automatic observations make no model calls. `status --summary` returns a digest capped at 4,000 serialized characters so authored updates can use bounded context. Semantic organization remains the assistant's responsibility; activity is not proof of progress or completion.

Hook responses arrive at message boundaries. Missed hook events are not replayed; transcript history can take several polling cycles to catch up. A quiet canvas retains its last useful content. Capability URLs protect local routes, but they are not an authentication boundary against the same OS user. This package targets local macOS/Linux clients and uses Unix file locking.

## Verification

Run `python3 -m unittest discover -s session-canvas -v` from the repository root. The suite covers session separation, atomic writes, event privacy, transcript recovery, content validation, HTTP restrictions, wrapper routing, and reversible installation.

Manual client verification should confirm skill discovery, SessionStart identity, completed-response hook delivery, browser opening, automatic refresh without reload, narrow and light/dark layouts, context changes, and server restart. CI fixtures exercise the contracts without claiming that a particular client has loaded its hooks.
