// Screen geometry stays deterministic and local. Jev chooses meaning, never pixels.
export const MIN_TEXT_PX = 16;
export function bounds(elements) {
  if (!elements.length) return { x: 0, y: 0, width: 1, height: 1 };
  const boxes = elements.map((e) => {
    if (e.points?.length) {
      const xs = e.points.map((p) => p[0]),
        ys = e.points.map((p) => p[1]);
      return {
        x: e.x + Math.min(...xs),
        y: e.y + Math.min(...ys),
        width: Math.max(...xs) - Math.min(...xs),
        height: Math.max(...ys) - Math.min(...ys),
      };
    }
    const w = Math.abs(e.width),
      h = Math.abs(e.height),
      a = e.angle || 0;
    const rw = Math.abs(w * Math.cos(a)) + Math.abs(h * Math.sin(a));
    const rh = Math.abs(w * Math.sin(a)) + Math.abs(h * Math.cos(a));
    return {
      x: e.x + e.width / 2 - rw / 2,
      y: e.y + e.height / 2 - rh / 2,
      width: rw,
      height: rh,
    };
  });
  const x = Math.min(...boxes.map((b) => b.x)),
    y = Math.min(...boxes.map((b) => b.y));
  return {
    x,
    y,
    width: Math.max(1, ...boxes.map((b) => b.x + b.width - x)),
    height: Math.max(1, ...boxes.map((b) => b.y + b.height - y)),
  };
}
export function safeViewport(editor) {
  const r = editor.getBoundingClientRect();
  let left = 20,
    top = 84,
    right = 20,
    bottom = 64;
  for (const el of editor.querySelectorAll(
    ".App-toolbar, .HintViewer, .layer-ui__wrapper__footer, .App-menu_bottom, .sidebar, .App-menu__left, .mobile-misc-tools-container",
  )) {
    const b = el.getBoundingClientRect();
    if (!b.width || !b.height) continue;
    if (el.matches(".App-toolbar, .HintViewer")) {
      if (b.top < r.top + r.height / 2)
        top = Math.max(top, b.bottom - r.top + 16);
      else bottom = Math.max(bottom, r.bottom - b.top + 16);
    } else if (el.matches(".sidebar, .mobile-misc-tools-container"))
      right = Math.max(right, r.right - b.left + 16);
    else if (el.matches(".App-menu__left, .mobile-misc-tools-container"))
      left = Math.max(left, b.right - r.left + 16);
    else bottom = Math.max(bottom, r.bottom - b.top + 16);
  }
  return {
    x: left,
    y: top,
    width: Math.max(1, r.width - left - right),
    height: Math.max(1, r.height - top - bottom),
  };
}
export function wrapText(text, width, measure) {
  const lines = [];
  for (const paragraph of text.split("\n")) {
    let line = "";
    for (const word of paragraph.split(/\s+/).filter(Boolean)) {
      if (line && measure(line + " " + word) > width) {
        lines.push(line);
        line = "";
      }
      let part = "";
      for (const char of word) {
        if (part && measure(part + char) > width) {
          if (line) {
            lines.push(line);
            line = "";
          }
          lines.push(part);
          part = "";
        }
        part += char;
      }
      line += (line ? " " : "") + part;
    }
    lines.push(line);
  }
  return lines.join("\n");
}
export function prepareScene(scene, measure, options = {}) {
  if (scene.model) return semanticScene(scene, measure, options);
  if (scene.adaptive === false) return structuredClone(scene);
  const elements = (scene.elements || []).map((e) => {
    if (
      e.isDeleted ||
      e.type !== "text" ||
      !e.customData?.projection ||
      e.customData?.humanTouched
    )
      return { ...e };
    const text = wrapText(
      e.originalText || e.text,
      Math.max(80, e.width - 4),
      (s) => measure(s, e),
    );
    return {
      ...e,
      text,
      height: text.split("\n").length * e.fontSize * e.lineHeight,
    };
  });
  // Recompute cards from measured text; preserve protected sections and authored diagrams.
  const protectedSections = new Set(
    elements
      .filter((e) => e.customData?.humanTouched)
      .map((e) => e.customData?.sectionId),
  );
  const groups = new Map();
  for (const e of elements)
    if (
      !e.isDeleted &&
      e.customData?.projection &&
      !protectedSections.has(e.customData.sectionId)
    ) {
      const key = e.groupIds[0];
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(e);
    }
  const orderedGroups = [...groups.values()].sort(
    (a, b) =>
      (a[0].customData?.renderOrder || 0) - (b[0].customData?.renderOrder || 0),
  );
  const cards = orderedGroups
    .map((g) => g.find((e) => e.type === "rectangle"))
    .filter(Boolean);
  const columns = [...new Set(cards.map((e) => e.x))].sort((a, b) => a - b);
  const bottoms = new Map(columns.map((x) => [x, 24]));
  const fixed = elements.filter(
    (e) =>
      !e.isDeleted &&
      (!e.customData?.projection ||
        protectedSections.has(e.customData.sectionId)),
  );
  let sequenceRowY = 24;
  for (const objects of orderedGroups) {
    const card = objects.find((e) => e.type === "rectangle"),
      head = objects.find((e) => e.type === "text" && e.customData.heading),
      body = objects.find((e) => e.type === "text" && !e.customData.heading);
    if (!card || !head || !body) continue;
    const oldX = card.x;
    const x = card.customData.wide
      ? columns[0]
      : card.customData.sequence
        ? oldX
        : columns.reduce((a, b) => (bottoms.get(a) <= bottoms.get(b) ? a : b));
    let y = card.customData.wide
      ? Math.max(...bottoms.values())
      : bottoms.get(x) || 24;
    if (card.customData.sequence) {
      if (x === columns[0]) sequenceRowY = Math.max(...bottoms.values());
      y = sequenceRowY;
    }
    const height = head.height + body.height + 40;
    for (let tries = 0; tries <= fixed.length; tries++) {
      const hits = fixed.filter(
        (e) =>
          x < e.x + Math.abs(e.width) + 16 &&
          x + card.width > e.x - 16 &&
          y < e.y + Math.abs(e.height) + 16 &&
          y + height > e.y - 16,
      );
      if (!hits.length) break;
      y = Math.max(...hits.map((e) => e.y + Math.abs(e.height))) + 24;
    }
    card.x = x;
    card.y = y;
    card.height = height;
    head.x = x + 16;
    head.y = y + 14;
    body.x = x + 16;
    body.y = head.y + head.height + 10;
    if (card.customData.wide)
      for (const c of columns) bottoms.set(c, y + height + 24);
    else bottoms.set(x, y + height + 24);
  }
  const byId = new Map(elements.map((e) => [e.id, e]));
  for (const e of elements)
    if (
      e.type === "arrow" &&
      e.customData?.startCard &&
      !e.customData?.humanTouched
    ) {
      const a = byId.get(e.customData.startCard),
        b = byId.get(e.customData.endCard);
      if (a && b && !protectedSections.has(e.customData.sectionId)) {
        const across = b.x > a.x;
        e.x = across ? a.x + a.width : a.x + a.width / 2;
        e.y = across ? a.y + a.height / 2 : a.y + a.height;
        e.width = (across ? b.x : b.x + b.width / 2) - e.x;
        e.height = (across ? b.y + b.height / 2 : b.y) - e.y;
        e.points = across
          ? [
              [0, 0],
              [e.width, e.height],
            ]
          : [
              [0, 0],
              [0, e.height / 2],
              [e.width, e.height / 2],
              [e.width, e.height],
            ];
      }
    }
  return { ...scene, elements };
}
export function readableViews(elements, rect) {
  const visible = elements.filter((e) => !e.isDeleted);
  if (!visible.length) return [];
  const textFloor = Math.max(
    0.5,
    ...visible
      .filter((e) => e.type === "text")
      .map((e) => MIN_TEXT_PX / Math.max(1, e.fontSize)),
  );
  const floor = () => textFloor;
  const content = visible.filter((e) => !e.customData?.edgeId);
  const full = bounds(visible),
    inner = bounds(content);
  const gutter = Math.max(0, full.x + full.width - inner.x - inner.width);
  const viewBounds = (group) => {
    const b = bounds(group);
    if (!group.some((e) => e.customData?.edgeId)) b.width += gutter;
    return b;
  };
  const fits = (group) => {
    const b = viewBounds(group);
    return (
      Math.min(rect.width / b.width, rect.height / b.height) >= floor(group)
    );
  };
  if (fits(visible))
    return [
      {
        ...bounds(visible),
        ids: visible.map((e) => e.id),
        zoom: Math.min(
          1.15,
          rect.width / bounds(visible).width,
          rect.height / bounds(visible).height,
        ),
      },
    ];
  const groups = new Map();
  for (const e of visible.filter((e) => !e.customData?.edgeId)) {
    const id = e.groupIds?.[0] || e.id;
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(e);
  }
  const pages = [];
  let batch = [];
  function add(group) {
    const b = viewBounds(group),
      z = Math.max(
        floor(group),
        Math.min(1, rect.width / b.width, rect.height / b.height),
      );
    const w = rect.width / z,
      h = rect.height / z;
    // Oversized human diagrams remain intact; readable camera tiles expose every part.
    for (let y = b.y; y < b.y + b.height; y += h * 0.9)
      for (let x = b.x; x < b.x + b.width; x += w * 0.9) {
        pages.push({
          x,
          y,
          ids: group.map((e) => e.id),
          width: Math.min(w, b.x + b.width - x),
          height: Math.min(h, b.y + b.height - y),
          zoom: z,
        });
        if (x + w >= b.x + b.width) break;
      }
  }
  for (const group of groups.values()) {
    if (batch.length && !fits([...batch, ...group])) {
      add(batch);
      batch = [];
    }
    batch.push(...group);
  }
  if (batch.length) add(batch);
  return pages;
}
export function camera(view, rect) {
  const zoom = view.zoom;
  return {
    zoom: { value: zoom },
    scrollX: (rect.x + (rect.width - view.width * zoom) / 2) / zoom - view.x,
    scrollY: (rect.y + (rect.height - view.height * zoom) / 2) / zoom - view.y,
  };
}

// Explicit graph layers are computed locally; cycles remain editable without looping.
export function graphRanks(nodes, edges) {
  const ids = new Set(nodes.map((n) => n.id)),
    ranks = new Map(),
    indegree = new Map(nodes.map((n) => [n.id, 0])),
    out = new Map(nodes.map((n) => [n.id, []]));
  for (const e of edges)
    if (ids.has(e.from) && ids.has(e.to)) {
      out.get(e.from).push(e.to);
      indegree.set(e.to, indegree.get(e.to) + 1);
    }
  const queue = nodes.filter((n) => indegree.get(n.id) === 0).map((n) => n.id);
  for (const id of queue) ranks.set(id, 0);
  for (let i = 0; i < queue.length; i++)
    for (const to of out.get(queue[i])) {
      ranks.set(to, Math.max(ranks.get(to) || 0, ranks.get(queue[i]) + 1));
      indegree.set(to, indegree.get(to) - 1);
      if (indegree.get(to) === 0) queue.push(to);
    }
  const tail = queue.length ? Math.max(...ranks.values()) + 1 : 0;
  for (const n of nodes) if (indegree.get(n.id) > 0) ranks.set(n.id, tail);
  return ranks;
}

function semanticScene(scene, measure, options) {
  const elements = structuredClone(scene.elements || []),
    byId = new Map(elements.map((e) => [e.id, e]));
  const previous = new Map(
    (options.previous?.elements || []).map((e) => [e.id, e]),
  );
  const enabled = scene.adaptive !== false;
  const width = Math.max(
    120,
    Math.min(1800, options.rect?.width || scene.layout?.width || 960),
  );
  const gap = scene.layout?.gap || 24;
  const columns = Math.max(
    1,
    Math.min(
      scene.layout?.style?.layout === "compare" ? 2 : 4,
      Math.floor((width + gap) / 304),
    ),
  );
  const reserve = columns === 1 && scene.model.edges.length > 1 ? 80 : 0;
  const cardWidth = Math.min(
    420,
    (width - reserve - (columns - 1) * gap) / columns,
  );
  const groups = new Map();
  for (const e of elements)
    if (!e.isDeleted && e.customData?.nodeId) {
      const nid = e.customData.nodeId;
      if (!groups.has(nid)) groups.set(nid, []);
      groups.get(nid).push(e);
    }
  const pinned = new Set(
    [...groups]
      .filter(([, es]) =>
        es.some(
          (e) =>
            e.customData.pinned ||
            (e.customData.humanTouched &&
              (!e.customData.humanFields ||
                e.customData.humanFields.some((k) =>
                  ["x", "y", "width", "height", "angle"].includes(k),
                ))),
        ),
      )
      .map(([id]) => id),
  );
  if (!enabled) {
    for (const e of elements) {
      const prior = previous.get(e.id);
      if (prior)
        for (const k of ["x", "y", "width", "height", "angle"]) e[k] = prior[k];
    }
    return { ...scene, elements };
  }
  // A fixed position still needs font measurement after a server update/reload.
  // Otherwise fallback line breaks can exceed a saved two-line text height.
  for (const id of pinned) {
    const es = groups.get(id);
    for (const e of es.filter((e) => e.type === "text")) {
      const source = e.originalText ?? e.text ?? "";
      e.text = wrapText(source, Math.max(40, e.width), (s) => measure(s, e));
      e.height = source
        ? e.text.split("\n").length * e.fontSize * e.lineHeight
        : 0;
    }
    const card = es.find((e) => e.customData.part === "card");
    if (card && !card.customData.humanFields?.includes("height")) {
      card.height = Math.max(
        card.height,
        ...es
          .filter((e) => e.type === "text")
          .map((e) => e.y + e.height - card.y + 16),
      );
    }
  }
  const fixed = elements.filter(
    (e) =>
      !e.isDeleted &&
      (!e.customData?.projection ||
        pinned.has(e.customData?.nodeId) ||
        (e.customData?.humanTouched && !e.customData?.nodeId)),
  );
  const bottoms = Array(columns).fill(24);
  const ordered = [...groups.values()].sort(
    (a, b) =>
      (a[0].customData.renderOrder || 0) - (b[0].customData.renderOrder || 0),
  );
  const ranks = graphRanks(scene.model.nodes, scene.model.edges);
  const nodes = new Map(scene.model.nodes.map((n) => [n.id, n]));
  // Stable source order between blocks; explicit graph depth within each block.
  ordered.sort((a, b) => {
    const na = nodes.get(a[0].customData.nodeId),
      nb = nodes.get(b[0].customData.nodeId);
    if (
      na?.scope === nb?.scope &&
      na?.kind === "graph" &&
      a[0].customData.representation === "map"
    )
      return ranks.get(na.id) - ranks.get(nb.id);
    return (
      (a[0].customData.renderOrder || 0) - (b[0].customData.renderOrder || 0)
    );
  });
  let layerKey = "",
    layerY = 24,
    layerIndex = 0;
  for (const es of ordered) {
    const card = es.find((e) => e.customData.part === "card"),
      head = es.find((e) => e.customData.part === "heading"),
      body = es.find((e) => e.customData.part === "body");
    if (!card || !head || !body) continue;
    const node = nodes.get(card.customData.nodeId);
    if (pinned.has(card.customData.nodeId)) continue;
    const connected =
      node?.kind === "graph" && card.customData.representation === "map";
    const key = connected ? node.scope + ":" + ranks.get(node.id) : "";
    let col = bottoms.indexOf(Math.min(...bottoms)),
      y = bottoms[col];
    if (connected) {
      if (key !== layerKey) {
        layerKey = key;
        layerY = Math.max(...bottoms);
        layerIndex = 0;
      }
      col = layerIndex++ % columns;
      if (col === 0) layerY = Math.max(...bottoms);
      y = layerY;
    }
    const x = 24 + col * (cardWidth + gap);
    for (const e of [head, body]) {
      const source = e.originalText ?? e.text ?? "";
      e.width = Math.max(40, cardWidth - 32);
      e.text = wrapText(source, e.width, (s) => measure(s, e));
      e.height = source
        ? e.text.split("\n").length * e.fontSize * e.lineHeight
        : 0;
    }
    const h = head.height + body.height + 40;
    for (let tries = 0; tries <= fixed.length; tries++) {
      const hits = fixed.filter(
        (e) =>
          x < e.x + Math.abs(e.width) + 16 &&
          x + cardWidth > e.x - 16 &&
          y < e.y + Math.abs(e.height) + 16 &&
          y + h > e.y - 16,
      );
      if (!hits.length) break;
      y = Math.max(...hits.map((e) => e.y + Math.abs(e.height))) + gap;
    }
    card.x = x;
    card.y = y;
    card.width = cardWidth;
    card.height = h;
    head.x = x + 16;
    head.y = y + 14;
    body.x = x + 16;
    body.y = head.y + head.height + 10;
    bottoms[col] = y + h + (connected ? Math.max(gap, 64) : gap);
  }
  for (const e of elements)
    if (
      e.type === "arrow" &&
      e.customData?.edgeId &&
      !e.customData.humanTouched
    ) {
      const a = byId.get(e.customData.startCard),
        b = byId.get(e.customData.endCard);
      if (!a || !b || a.isDeleted || b.isDeleted) continue;
      const blocked = elements.some(
        (c) =>
          c.type === "rectangle" &&
          !c.isDeleted &&
          c.id !== a.id &&
          c.id !== b.id &&
          c.y > a.y + a.height &&
          c.y < b.y &&
          c.x <= a.x + a.width / 2 &&
          c.x + c.width >= a.x + a.width / 2,
      );
      const horizontal =
        !blocked && (b.x >= a.x + a.width || a.x >= b.x + b.width);
      const forward = horizontal ? b.x > a.x : b.y > a.y;
      const ax = horizontal ? a.x + (forward ? a.width : 0) : a.x + a.width / 2;
      const ay = horizontal
        ? a.y + a.height / 2
        : a.y + (forward ? a.height : 0);
      const bx = horizontal ? b.x + (forward ? 0 : b.width) : b.x + b.width / 2;
      const by = horizontal
        ? b.y + b.height / 2
        : b.y + (forward ? 0 : b.height);
      const dx = bx - ax,
        dy = by - ay;
      e.x = ax;
      e.y = ay;
      e.width = Math.abs(dx);
      e.height = Math.abs(dy);
      e.points = horizontal
        ? [
            [0, 0],
            [dx / 2, 0],
            [dx / 2, dy],
            [dx, dy],
          ]
        : [
            [0, 0],
            [0, dy / 2],
            [dx, dy / 2],
            [dx, dy],
          ];
      if (blocked) {
        const lane =
          Math.max(
            a.x + a.width,
            b.x + b.width,
            ...elements
              .filter(
                (c) =>
                  c.type === "rectangle" &&
                  !c.isDeleted &&
                  c.y >= a.y &&
                  c.y <= b.y,
              )
              .map((c) => c.x + c.width),
          ) + 24;
        e.points = [
          [0, 0],
          [0, 24],
          [lane - ax, 24],
          [lane - ax, dy - 32],
          [dx, dy - 32],
          [dx, dy],
        ];
        e.width =
          Math.max(...e.points.map((p) => p[0])) -
          Math.min(...e.points.map((p) => p[0]));
      }
      // Excalidraw bindings keep connections attached during direct manipulation.
      e.startBinding = { elementId: a.id, focus: 0, gap: 1 };
      e.endBinding = { elementId: b.id, focus: 0, gap: 1 };
      const label = byId.get(e.id + "-label");
      if (label && !label.customData?.humanTouched) {
        label.width = measure(label.originalText, label);
        label.height = label.fontSize * label.lineHeight;
        const mid = Math.floor((e.points.length - 1) / 2),
          p = e.points[mid],
          q = e.points[mid + 1] || p;
        label.text = label.originalText;
        label.x = ax + (p[0] + q[0]) / 2 - label.width / 2;
        label.y = ay + (p[1] + q[1]) / 2 - label.height / 2;
      }
    }
  return { ...scene, elements };
}
