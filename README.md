# Live Canvas

A small, local workspace beside your AI conversation. Keep the actual work visible: an outline, evidence, decisions, study questions, edit beats, or a diagram. The assistant updates authored sections at meaningful milestones; lightweight local adapters bring in activity and visible responses automatically.

Python standard library only. Default local mode needs no API key, packages, hosted service, or background model calls. Optional TypeSafe integration can select a focus section from existing authored work. The viewer has light and dark themes, six flexible content blocks, and useful browser-local interactions. It never writes back to the assistant or runtime.

![Live Canvas running beside a conversation in the Codex desktop app](docs/images/live-canvas-codex.png)

## Supported clients

| Client | Automatic observations | Viewer |
| --- | --- | --- |
| Codex | Managed startup instruction plus registered local transcript | Right-hand Codex browser panel on the first user turn |
| Claude Code | Command hooks: generic activity and the final visible response on `Stop` | OS browser automatically at foreground session startup |
| Cursor | Command hooks: generic activity and `afterAgentResponse` text | Built-in browser on the first user turn when exposed; otherwise OS browser |
| OpenCode | Local plugin: visible user and assistant messages | OS browser automatically for each foreground session |

This package targets local macOS and Linux environments with Python 3.10+. Windows is not supported by the runtime's file-locking implementation. Ordinary Claude chat has no native integration. Remote environments need their own installation and access to the loopback viewer.

## Quick start

```sh
git clone https://github.com/mhadifilms/live-canvas.git
cd live-canvas
```

Run the guided setup in a terminal:

```sh
python3 session-canvas/setup.py
```

Choose **Codex, Cursor, Claude Code, OpenCode, or a combination**. Setup asks whether to open canvases automatically, whether to use optional TypeSafe focus, and your daily limits. Local-only mode needs no account or key. For TypeSafe, sign in or create an account, then get an API key from the [TypeSafe dashboard](https://console.typesafe.ai/settings/keys), then paste the key into the hidden terminal prompt. Setup explains the remote data sharing before enabling it.

The key is stored in a private local configuration file with owner-only permissions. It is plaintext on disk, not encrypted or stored in an OS keychain. It never appears in the browser, task content, or status output. An existing `TYPESAFE_API_KEY` environment variable takes precedence; setup reports that source without revealing the key. Keep the checkout in place because hooks reference it.

**Finish the selected host's setup:**

| Client | Required next step |
| --- | --- |
| Codex | Setup installs a managed startup instruction. Start a desktop task and send a message. No CLI hook-trust step is needed. |
| Cursor | Restart Cursor if necessary. Check the **Hooks** tab / Hooks output channel, then send a message in a new Agent conversation. |
| Claude Code | Restart Claude Code if necessary, review the installed hooks with `/hooks`, then begin a new foreground session. The canvas opens in your OS browser. |
| OpenCode | Restart OpenCode so it discovers `~/.config/opencode/plugins/live-canvas.js`, then start a foreground session. |

Codex and Cursor receive an instruction to open their panel on the first user turn; clicking a blank new-chat button alone cannot open a native panel. Setup does not bypass host trust or claim a hook executed merely because its files are installed. Ordinary Claude chat and cloud agents are not supported by this local installation.

Change configuration later or inspect it without making API calls:

```sh
python3 session-canvas/setup.py configure
python3 session-canvas/setup.py status
python3 session-canvas/setup.py configure --daily-calls 2500
python3 session-canvas/setup.py configure --typesafe off --remove-key
```

The daily input allowance scales with the selected request cap unless explicitly set. Changes preserve today's recorded usage. The running service picks up saved settings; changing its inherited environment still requires a restart.

For scripted installation, make every first-run choice explicit:

```sh
python3 session-canvas/setup.py --non-interactive --client codex --client cursor --auto-open on --typesafe off
```

To supply a TypeSafe key in automation, use `--api-key-stdin` with a secret manager or private pipe. Never place a key in command arguments. See the [configuration guide](session-canvas/README.md#guided-setup-and-configuration) for details.

The existing low-level installer remains available for preview, installation, checks, and removal. Pass a client explicitly; its default is all four:

```sh
python3 session-canvas/install_clients.py dry-run --client codex
python3 session-canvas/install_clients.py install --client codex
python3 session-canvas/install_clients.py check --client codex
```

It merges user hooks, backs up changed settings, preserves unrelated hooks and existing skills, and refuses conflicts. Cloning alone changes no client configuration.

Resume, clear, compact, and fork events do not trigger automatic opening. Background/subagent/noninteractive sessions are skipped when the payload identifies them; hosts do not always expose those indicators. Per-session claims suppress repeated openings, and explicit `stop` remains stopped. Opening failures are retryable; after an interrupted attempt, a claim expires after five minutes. A crash between opening a UI and acknowledgement can cause a later retry to open it again.

Codex setup preserves unrelated instructions and removes only unchanged Live Canvas legacy hooks. It never changes host trust. Startup instructions request the first-turn opening; verify the actual panel in the host, since installed files alone do not prove visibility.

Keep this checkout in place because the installed hooks and skill reference it. To move an installation, uninstall from the original checkout first. You can still ask **“open live canvas”** or invoke `/live-canvas` for manual use.

Turn automatic opening off or on for all clients using this state directory:

```sh
python3 session-canvas/canvas.py auto-open off
python3 session-canvas/canvas.py auto-open on
```

For skill-only Codex use without automatic opening, create a link from the repository root. This refuses to replace an existing path:

```sh
skill_path="${CODEX_HOME:-$HOME/.codex}/skills/live-canvas"
if [ -e "$skill_path" ] || [ -L "$skill_path" ]; then
  printf 'Already exists; inspect before changing: %s\n' "$skill_path"
else
  mkdir -p "$(dirname "$skill_path")"
  ln -s "$PWD/live-canvas" "$skill_path"
fi
```

Open a new Codex task and ask to use the `live-canvas` skill. Automatic transcript discovery requires a local session and `CODEX_THREAD_ID`; the skill documents explicit updates when a transcript is unavailable.

Try a fictional example without installing any hooks:

```sh
python3 session-canvas/canvas.py start --thread example-preview
python3 session-canvas/canvas.py update --thread example-preview --file session-canvas/examples/study.json
```

Open the returned URL. Use `stop --thread example-preview` to disable that example or `shutdown` to stop the shared server.

## How it stays useful

Authored sections support text, lists, checklists, tables, recall cards, and timelines, plus optional isolated HTML/SVG visuals. Check off personal review items, practice with Again / Got it, or shortlist candidate ideas and copy your choices. These interactions persist in your browser, synchronize between views of the same task, reset when their content changes, and never imply assistant-verified results. Existing browser choices migrate automatically; a shared reset clears them across views. A compact header separates connection status from authored freshness; bounded activity and readable version history stay collapsed until needed. Stable section IDs let the assistant update only what changed. A new context clears stale authored content and retains revision history.

Automatic observations never infer a plan, completion, scores, or semantic adaptation. Claude Code and Cursor deliver response text at message boundaries, not token by token. The assistant must still update useful sections at milestones and before its final reply. A bounded `status --summary` digest keeps that work inexpensive.

State stays in one shared local directory across clients: `~/Library/Application Support/Live Canvas` on macOS, or `$XDG_DATA_HOME/live-canvas` (normally `~/.local/share/live-canvas`) on Linux. Each task has an offline `canvas.html`, a `chat.json` reference to its source conversation, and a bounded visible-message log. These files contain private task content; share them deliberately. The viewer opens at a readable address such as `http://canvas.localhost:60839/quiz-review`. Its initial private link contains a task credential in the fragment; the page immediately removes it and exchanges it for an HttpOnly cookie. Keep the initial link private; the clean address alone does not authorize another browser. Canvas content remains read-only over HTTP. This is not a security boundary against other processes running as the same OS user. Adapters capture visible user/assistant messages where the host supplies them, but exclude tool arguments/results and reasoning. Codex transcript registration can import earlier visible messages from that same session. Review canvas content before sharing it.

See the [runtime guide and schema](session-canvas/README.md), [skill instructions](live-canvas/SKILL.md), and [design notes](session-canvas/DESIGN.md).

## Uninstall and development

Remove the installed client integrations with:

```sh
python3 session-canvas/install_clients.py uninstall
```

It removes unchanged owned hooks and skill links while preserving unrelated edits, backups, and canvas state. Remove a Codex skill link only after confirming it points to this checkout.

Run the offline tests from the repository root:

```sh
python3 -m unittest discover -s session-canvas -v
node --test session-canvas/test_viewer.mjs
```

CI runs the Python suite on 3.10 and 3.12, plus dependency-free Node tests for viewer helpers. Node is needed only for those development tests, not to run the canvas. Host hook loading and browser behavior also need verification in the installed client; unit tests do not establish that a host has loaded the integration.

Inspired by [sebi75/herdr-canvas](https://github.com/sebi75/herdr-canvas). Live Canvas does not require Herdr. Licensed under [MIT](LICENSE).

Readable routes stay fixed after their first opening, even when the title changes. Duplicate names receive a short task suffix. Chromium-based host panels support `canvas.localhost`; the external-browser startup helper defaults to `localhost`. If your browser cannot resolve the branded name, set `LIVE_CANVAS_HOST=localhost` (or `127.0.0.1`) when running the command that returns the URL. No hosts-file edits are needed. Cookies and browser-only choices belong to each origin: old capability links still open and clean themselves on their original origin, preserving choices there; switching hostname or port does not migrate those choices. After upgrading a running installation, run `shutdown` and then `start` to load the new server code.

## Optional TypeSafe focus

TypeSafe can choose which existing section to put first and collapse the others. It never generates content or changes authored history. This feature sends bounded authored task context and section excerpts to TypeSafe, so it is off until explicitly enabled:

```sh
# Configure the key and consent through the terminal wizard.
python3 session-canvas/setup.py configure
python3 session-canvas/canvas.py adaptive status
# Disable remote selection and return to the authored layout:
python3 session-canvas/canvas.py adaptive off
```

The preference survives restarts. Guided setup can save a private local key; an environment key takes precedence and requires a server restart when changed. Keys never enter canvas content or browser responses. Defaults are 10,000 calls and 60,000,000 encoded input bytes per UTC day, shared across tasks. No calls happen on browser refresh, tool activity, or token streaming. With separate `--context on` consent, bounded recent visible messages can inform focus; settled message changes can trigger a decision. Missing keys, failures, uncertain results, and exhausted budgets retain the authored layout. `adaptive retry` requests a bounded retry after a transient failure; it cannot reset the budget. In Settings, **Follow suggested focus** controls this browser's layout only, while `adaptive off` controls remote inference. See [configuration and limitations](session-canvas/README.md#optional-typesafe-presentation).

## Experimental branch

The Excalidraw board and human/agent collaboration experiments are preserved on [`excalidraw-board`](https://github.com/mhadifilms/live-canvas/tree/excalidraw-board). They are not included in the main branch or supported release downloads.
