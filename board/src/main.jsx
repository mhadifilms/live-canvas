import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Excalidraw,
  MainMenu,
  convertToExcalidrawElements,
  CaptureUpdateAction,
} from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import { changes, mergeAcknowledgement, safeLink } from "./sync.mjs";
import "./style.css";
import { startPolling, debounce } from "./polling.mjs";
window.EXCALIDRAW_ASSET_PATH = "/board-assets/";
const route =
  document.documentElement.dataset.canvasRoute ||
  location.pathname.replace(/\/$/, "");
const auth = new URLSearchParams(location.hash.slice(1)).get("auth");
history.replaceState(null, "", route);
const viewId = crypto.randomUUID();
const empty = { elements: [], files: {}, versions: {}, revision: 0 };
const apiRequest = async (path, body, signal) => {
  const r = await fetch(
    route + path,
    body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal,
        }
      : { signal },
  );
  if (!r.ok) {
    const e = new Error(
      r.status === 403
        ? "Open this board from your conversation to reconnect."
        : r.status === 409
          ? "An object changed elsewhere. Your unsaved edits are still here."
          : await r.text(),
    );
    e.status = r.status;
    throw e;
  }
  return r.status === 204 ? {} : r.json();
};
function App() {
  const [api, setApi] = useState(null),
    [title, setTitle] = useState("Live Canvas"),
    [status, setStatus] = useState("Local board"),
    [error, setError] = useState(""),
    [count, setCount] = useState(0),
    [jev, setJev] = useState(""),
    [connected, setConnected] = useState(false),
    [adaptive, setAdaptive] = useState(false);
  const state = useRef({
      board: empty,
      ready: false,
      busy: false,
      dirty: false,
      pointer: false,
      hydrating: false,
      conflict: false,
      timer: null,
      selection: "",
      follow: true,
    }),
    [follow, setFollow] = useState(true);
  const theme = matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
  const showError = useCallback((e) => {
    setError(e.message || "Could not save. Your work remains on this board.");
    setStatus("Unsaved");
    if (e.status === 409) state.current.conflict = true;
  }, []);
  const hydrate = useCallback(
    (scene) => {
      if (!api) return;
      const s = state.current;
      s.hydrating = true;
      api.addFiles(Object.values(scene.files || {}));
      api.updateScene({
        elements: scene.elements || [],
        captureUpdate: CaptureUpdateAction.NEVER,
      });
      s.hydrating = false;
      setCount((scene.elements || []).filter((e) => !e.isDeleted).length);
    },
    [api],
  );
  const save = useCallback(
    async function save() {
      const s = state.current;
      if (!api || !s.ready || !s.alive || s.busy || s.conflict) return;
      if (s.pointer || api.getAppState().editingTextElement) {
        s.timer = setTimeout(save, 600);
        return;
      }
      const submitted = api.getSceneElementsIncludingDeleted(),
        delta = changes(submitted, s.board.elements);
      if (!delta.length) {
        s.dirty = false;
        setStatus("Saved locally");
        return;
      }
      s.busy = true;
      setStatus("Saving…");
      try {
        const result = await apiRequest("/events", {
          kind: "board",
          elements: delta,
          files: api.getFiles(),
          base_versions: s.board.versions,
        });
        const local = api.getSceneElementsIncludingDeleted();
        const merged = mergeAcknowledgement(
          local,
          submitted,
          result.board.elements,
        );
        s.board = result.board;
        s.dirty = changes(merged, s.board.elements).length > 0;
        if (!s.pointer && !api.getAppState().editingTextElement)
          hydrate({ ...result.board, elements: merged });
        else s.needsHydrate = true;
        setError("");
        setStatus(s.dirty ? "Saving…" : "Saved locally");
      } catch (e) {
        showError(e);
      } finally {
        s.busy = false;
        if (s.dirty && s.alive && !s.conflict) s.timer = setTimeout(save, 1200);
      }
    },
    [api, hydrate, showError],
  );
  function changed(elements, appState) {
    const s = state.current;
    setCount(elements.filter((e) => !e.isDeleted).length);
    if (s.hydrating || !s.ready) return;
    if (changes(elements, s.board.elements).length) {
      s.dirty = true;
      setStatus("Unsaved");
      clearTimeout(s.timer);
      s.timer = setTimeout(save, 650);
    }
    const selected = Object.keys(appState.selectedElementIds).sort().join(",");
    if (selected !== s.selection) {
      s.selection = selected;
      clearTimeout(s.selectionTimer);
      s.selectionTimer = setTimeout(
        () =>
          apiRequest("/events", {
            id: crypto.randomUUID(),
            kind: "selection",
            text: selected.slice(0, 2000),
          }).catch(() => {}),
        1400,
      );
    }
  }
  useEffect(() => {
    if (!api) return;
    let cancelled = false,
      stopPolling = () => {};
    const s = state.current;
    s.alive = true;
    const heartbeat = () =>
      apiRequest("/events", { kind: "presence", id: viewId }).catch(() => {});
    async function poll(signal) {
      try {
        const data = await apiRequest("/state", null, signal);
        if (cancelled) return;
        const scene = data.board || empty;
        setAdaptive(Boolean(data.adaptive?.enabled));
        setFollow(data.adaptive?.follow !== false);
        setTitle(data.content?.title || "Live Canvas");
        document.title = data.content?.title || "Live Canvas";
        setJev(
          data.presentation?.status === "focused"
            ? "Jev arranged the agent content"
            : "",
        );
        if (!s.ready) {
          // Preserve strokes made immediately on the empty board while authentication finishes.
          const local = api.getSceneElementsIncludingDeleted(),
            remoteIds = new Set(scene.elements.map((e) => e.id));
          s.board = scene;
          hydrate({
            ...scene,
            elements: [
              ...scene.elements,
              ...local.filter((e) => !remoteIds.has(e.id)),
            ],
          });
          s.ready = true;
          s.dirty = local.length > 0;
          if (scene.elements.length && !local.length) {
            const visible = scene.elements.filter((e) => !e.isDeleted);
            const first =
              visible.find(
                (e) => e.customData?.sectionId === data.presentation?.focus_id,
              ) || visible[0];
            const firstGroups = new Set(first?.groupIds || []);
            const target =
              innerWidth < 700
                ? visible.filter(
                    (e) =>
                      e.groupIds?.some((g) => firstGroups.has(g)) ||
                      e.id === first.id,
                  )
                : visible;
            api.scrollToContent(target, {
              fitToContent: true,
              minZoom: 0.65,
              maxZoom: 1,
              animate: false,
            });
          }
          if (s.dirty) void save();
        } else if (
          (scene.revision !== s.board.revision || s.needsHydrate) &&
          !s.dirty &&
          !s.busy &&
          !s.pointer &&
          !api.getAppState().editingTextElement
        ) {
          s.board = scene;
          s.needsHydrate = false;
          hydrate(scene);
        }
        setConnected(true);
        if (!s.dirty) setStatus("Saved locally");
      } catch (e) {
        if (!cancelled) {
          setConnected(false);
          if (!s.dirty) setStatus("Reconnecting");
          if (e.status === 403) setError(e.message);
        }
      }
    }
    const presence = setInterval(heartbeat, 15000);
    const viewport = debounce(
      () =>
        apiRequest("/events", {
          kind: "viewport",
          id: crypto.randomUUID(),
          width: Math.max(120, innerWidth),
          height: Math.max(120, innerHeight),
        }).catch(() => {}),
      900,
    );
    (async () => {
      try {
        if (auth) {
          const r = await fetch(route + "/_auth", {
            method: "POST",
            headers: { Authorization: "Bearer " + auth },
          });
          if (!r.ok)
            throw new Error(
              "Open this board from your conversation to reconnect.",
            );
        }
        if (!cancelled) {
          stopPolling = startPolling(poll);
          heartbeat();
          viewport();
        }
      } catch (e) {
        if (!cancelled) showError(e);
      }
    })();
    viewport();
    addEventListener("resize", viewport);
    const leave = (e) => {
      if (s.dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    addEventListener("beforeunload", leave);
    return () => {
      cancelled = true;
      s.alive = false;
      stopPolling();
      viewport.cancel();
      clearInterval(presence);
      clearTimeout(s.timer);
      clearTimeout(s.selectionTimer);
      removeEventListener("resize", viewport);
      removeEventListener("beforeunload", leave);
    };
  }, [api, hydrate, save, showError]);
  function exportDraft() {
    const blob = new Blob(
      [
        JSON.stringify({
          type: "excalidraw",
          version: 2,
          source: "Live Canvas",
          elements: api.getSceneElementsIncludingDeleted(),
          appState: {
            viewBackgroundColor: api.getAppState().viewBackgroundColor,
          },
          files: api.getFiles(),
        }),
      ],
      { type: "application/json" },
    );
    const a = document.createElement("a");
    const url = URL.createObjectURL(blob);
    a.href = url;
    a.download = "live-canvas.excalidraw";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function drop(e) {
    const files = [...e.dataTransfer.files].filter(
      (f) => !f.type.startsWith("image/") && !f.name.endsWith(".excalidraw"),
    );
    if (!files.length) return;
    e.preventDefault();
    e.stopPropagation();
    for (const file of files) {
      try {
        if (file.size > 2 * 1024 * 1024)
          throw new Error("Attachments can be up to 2 MB.");
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = "";
        for (const byte of bytes) binary += String.fromCharCode(byte);
        const id = crypto.randomUUID();
        const res = await apiRequest("/events", {
          kind: "file",
          id,
          name: file.name,
          data: btoa(binary),
        });
        const entry = res.collaboration.events.find((x) => x.id === id);
        const a = api.getAppState(),
          zoom = a.zoom.value;
        const added = convertToExcalidrawElements([
          {
            type: "text",
            x: e.clientX / zoom - a.scrollX,
            y: e.clientY / zoom - a.scrollY,
            text: "↗ " + file.name,
            fontSize: 18,
            fontFamily: 2,
            link: location.origin + route + "/attachment/" + entry.file_id,
          },
        ]);
        api.updateScene({
          elements: [...api.getSceneElementsIncludingDeleted(), ...added],
          captureUpdate: CaptureUpdateAction.IMMEDIATELY,
        });
      } catch (err) {
        showError(err);
      }
    }
  }
  async function toggleFollow() {
    const next = !follow;
    try {
      await apiRequest("/events", {
        kind: "preference",
        id: crypto.randomUUID(),
        text: next ? "adaptive:on" : "adaptive:off",
      });
      setFollow(next);
    } catch (e) {
      showError(e);
    }
  }
  return (
    <main onDropCapture={drop}>
      <header className="board-header">
        <div className="identity">
          <strong>{title}</strong>
          <span className={connected ? "connected" : ""}>{status}</span>
        </div>
        <div className="board-actions">
          <button
            onClick={() =>
              api?.scrollToContent(
                api.getSceneElements().filter((e) => !e.isDeleted),
                { fitToContent: true, animate: true },
              )
            }
            title="Fit all objects in view"
          >
            Fit
          </button>
          <button
            aria-pressed={adaptive && follow}
            disabled={!adaptive}
            onClick={toggleFollow}
            title={
              adaptive
                ? "Let Jev arrange untouched agent content"
                : "Enable optional Jev in Live Canvas setup"
            }
          >
            Jev {adaptive && follow ? "on" : "off"}
          </button>
          <button
            onClick={exportDraft}
            disabled={!api}
            title="Download an editable copy"
          >
            ↓
          </button>
        </div>
      </header>
      <div className="editor">
        <Excalidraw
          excalidrawAPI={setApi}
          initialData={{
            elements: [],
            appState: {
              theme,
              viewBackgroundColor: "#fbfaf8",
              currentItemFontFamily: 2,
              currentItemRoughness: 0,
              currentItemStrokeColor: "#343a40",
            },
          }}
          theme={theme}
          onChange={changed}
          onPointerDown={() => {
            state.current.pointer = true;
          }}
          onPointerUp={() => {
            state.current.pointer = false;
          }}
          onLinkOpen={(element, event) => {
            const url = safeLink(element.link, location.origin);
            if (url) {
              event.preventDefault();
              location.assign(url);
            }
          }}
          UIOptions={{
            canvasActions: {
              loadScene: false,
              saveToActiveFile: false,
              export: false,
              toggleTheme: false,
            },
          }}
        >
          <MainMenu>
            <MainMenu.Item onSelect={exportDraft}>
              Download editable board
            </MainMenu.Item>
            <MainMenu.Item onSelect={() => location.assign(route + "/archive")}>
              Open saved snapshot
            </MainMenu.Item>
            <MainMenu.DefaultItems.Help />
          </MainMenu>
        </Excalidraw>
      </div>
      {count === 0 && !error && (
        <div className="welcome">
          <h1>A place to think together.</h1>
          <p>
            Draw, type, or drop something here.
            <br />
            You and your agent share this board.
          </p>
          <span>V select · P draw · T text · space drag to pan</span>
        </div>
      )}
      {error && (
        <div className="notice" role="alert">
          <span>{error}</span>
          <button onClick={exportDraft}>Download my edits</button>
          {state.current.conflict && (
            <button onClick={() => location.reload()}>
              Reload saved board
            </button>
          )}
        </div>
      )}
      {jev && !error && <div className="jev-status">{jev}</div>}
    </main>
  );
}
createRoot(document.getElementById("root")).render(<App />);
