# Shared board design

The editing surface is Excalidraw. Human and agent work lives in the same scene, not in separate document and sketch interfaces. The local Python service is the persistence authority; Excalidraw owns selection, drawing, text entry, undo and camera movement.

Agent section IDs project deterministically to stable object IDs. A human change marks that object protected, including moves and deletions. Later automatic projection and Jev arrangement skip protected objects. An agent may intentionally edit a shared object through the board API after reading its current version and understanding the user's instruction.

Browser saves contain changed elements and their base versions. Independent object changes merge. Same-object conflicts return 409; the browser retains the draft and offers a download. Saves in flight never replace edits made after their submission. The camera is not reset on remote updates or during typing/dragging.

Jev receives typed decision questions in one bounded request. It does not generate HTML or JavaScript. Its layout choices map to deterministic, constrained operations over unmodified agent objects. Colors and font families come from a short set. Human revision and debounced selection/viewport changes invalidate decisions; Jev's own layout changes do not create a feedback loop. Rich context is a separate opt-in.

All clients share one local data root, but each exact client/session identity has its own scene, URL, authentication cookie and conversation reference. Presence is separate from scene revisions and model input. Open dispatch, saved state and confirmed visibility remain distinct.

Codex startup uses a backed-up managed instruction rather than editing hook trust. There is no supported before-first-turn Desktop panel lifecycle API. Other apps use their documented command hooks or OpenCode plugin hooks. Host loading needs real-host verification.

The app serves bundled code, CSS and fonts locally. Browser requests are task-authenticated and same-origin. API keys never enter the scene. Binary images are held locally; non-image files are private attachments. Static HTML snapshots are simplified exports; editable scene files retain the original board.
