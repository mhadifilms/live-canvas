# Live Canvas

One shared board beside your AI conversation. Draw, write, move things around, drop files, and work on the same objects as your agent. The board stays with the conversation and saves locally.

Live Canvas embeds [Excalidraw](https://excalidraw.com), with direct text editing, shapes, arrows, freehand drawing, selection, resizing, undo, and pan/zoom. There is no separate sketch dialog. Agent-authored sections become editable board objects. Human edits and deletions are protected from automatic updates.

![Desktop panel placement, shown with the earlier document viewer](docs/images/live-canvas-codex.png)

## Install

```sh
git clone https://github.com/mhadifilms/live-canvas.git
cd live-canvas
python3 session-canvas/setup.py
```

Choose your apps, automatic opening, and optional Jev assistance. No account or API key is needed for a local board. The editor assets are bundled; running it needs Python 3.10+ on macOS or Linux, with no Node installation or CDN connection. Keep the checkout in place after setup.

| App | Startup | Conversation capture |
| --- | --- | --- |
| Codex Desktop | Managed startup instruction opens the app browser on the first user turn | Registered local transcript |
| Claude Code | Foreground session hook opens the OS browser | Visible replies and user prompts through hooks |
| Cursor | Native browser when the agent has that tool; OS browser fallback | Documented command hooks |
| OpenCode | Global plugin opens the OS browser | Visible messages at session idle |

Codex setup backs up its global instructions and removes only unchanged Live Canvas-owned legacy hooks. It does not alter hook trust records or require a CLI trust command. Opening still depends on the agent following the startup instruction: Codex does not expose a supported way for this package to open its panel before the first turn starts. Ordinary Claude web chat and Windows are not supported.

Host integrations use one board per exact conversation identity and check for an existing view before opening. `stop` and `auto-open off` remain respected. Host-specific hooks/plugins may require restarting the app and reviewing its normal integration permissions. OpenCode 1.18.31 has been verified with a real local host: session creation opens a visible OS-browser board, visible replies sync at idle, subsequent turns reuse it, and child sessions are skipped. Its auto-discovery requires a `.js` plugin; rerunning setup migrates an unchanged Live Canvas-owned legacy `.mjs` installation safely.

## Readable spatial layouts

Fit measures the usable editor area, including desktop/mobile toolbars and padding. Automatic fitting keeps text at least 16 CSS pixels on screen. Larger boards have previous/next readable views; manual zoom and pan remain available. New text uses Excalidraw's hand-drawn Virgil font. Generated text wraps using measured font widths, and compact native cards use their actual text heights.

Jev chooses focus, importance, grouping, and whether source material describes a connected sequence or independent ideas. It receives the available viewport and readability constraints. Pixel measurements and resize fitting run locally; they do not require model calls. Semantic decisions remain debounced, cached and subject to the existing configurable daily budget. Human-edited sections and manually authored objects stay fixed, so automatic packing may leave space around that protected work.

## Work together

Use the editor tools directly on the board. Double-click text to edit; draw to annotate or highlight; drag objects to organize them. Drop images onto the board and other files to attach them. Text objects can hold comments beside the work they refer to. Links navigate in the current browser panel. **Fit** gives an overview; a narrow pane initially focuses a readable group rather than shrinking the entire board into illegible text.

Changes save automatically. Concurrent changes to different objects merge. If two writers change the same object, the board keeps your unsaved work and offers an editable download before you reload. Human edits are never silently replaced by an agent projection or Jev layout change. Canvas input is available to the agent at its next normal checkpoint; it does not secretly send a new chat message or trigger tools.

The agent reuses this board for drafts, study material, evidence, brainstorming, code plans, and edit notes. It should not create completion-summary Markdown files or another canvas unless asked. The latest visible response is mirrored when no authored board content exists. A real spatial board can grow beyond the viewport; pan/zoom remain available rather than hiding your work to promise zero scrolling.

## Local storage

All apps use the same data root:

- macOS: `~/Library/Application Support/Live Canvas`
- Linux: `$XDG_DATA_HOME/live-canvas` (default `~/.local/share/live-canvas`)

Each conversation has a unique readable URL and a `tasks/<key>/` folder containing `state.json`, an offline `canvas.html` snapshot, an editable `board.excalidraw`, `chat.json`, visible conversation text, and attachments. `chat.json` records the app/session and original transcript path when available. Snapshots are simplified static SVG; the editable file preserves the full scene.

For an older installation using `session-canvas/.state`, stop its server, back up the folder, and move it into the shared root before restarting. Do not merge two populated roots blindly. `--home` or `SESSION_CANVAS_HOME` can deliberately override storage.

The initial private URL exchanges its credential for an HttpOnly, SameSite cookie and clears the fragment immediately. Clean URLs alone grant no access. Writes require the same origin and task authentication. State and saved keys have owner-only permissions; other processes running as the same OS user are outside this security boundary.

## Optional Jev / TypeSafe

Jev judges priorities, grouping, spacing, restrained emphasis colors, and suitable text style. It arranges only untouched agent objects; anything you edit stays put. Decisions run in the local background service after meaningful changes settle, with caching and shared daily caps. Pointer motion, refreshes, and connection heartbeats do not trigger decisions. There are no extra main-agent turns.

Setup explains what leaves your device. Basic mode sends bounded authored excerpts. Enhanced context additionally sends bounded visible chat text, board text and geometry, selections, viewport size, and text-file excerpts. Images, binary attachments, tool results, and reasoning are never sent to Jev. A drawing is represented by its type/bounds, not visually interpreted.

Get an optional key from the [TypeSafe dashboard](https://console.typesafe.ai/settings/keys), then use the hidden setup prompt. Keys stay in the local service, never the board or repository. Saved keys are plaintext protected by file permissions, not an OS keychain. Environment keys take precedence.

```sh
python3 session-canvas/setup.py configure
python3 session-canvas/canvas.py adaptive status
python3 session-canvas/canvas.py adaptive off
```

Defaults are 10,000 requests and 60 MB of encoded input per UTC day, shared across conversations. Both are configurable; whichever limit is reached first stops inference. Requests are bounded to 12 KB. These are usage caps, not a dollar guarantee. The board continues to work when Jev is disabled or unavailable. Its toolbar toggle pauses Jev for that board; it cannot bypass global consent.

## Development and removal

```sh
python3 -m unittest discover -s session-canvas -v
node --test session-canvas/test_viewer.mjs
npm ci --prefix board
npm run build --prefix board
python3 session-canvas/install_clients.py uninstall
```

The build refreshes bundled assets in `session-canvas/board-assets`. Tests cover persistence, conflict handling, protected human edits, authenticated routes, cost limits, and installer preservation. Real browser and host checks remain necessary.

See the [agent skill](live-canvas/SKILL.md), [runtime schema](session-canvas/README.md), and [design notes](session-canvas/DESIGN.md). Inspired by [herdr-canvas](https://github.com/sebi75/herdr-canvas); Herdr is not required. Live Canvas is [MIT licensed](LICENSE); bundled editor dependencies retain their own notices.
