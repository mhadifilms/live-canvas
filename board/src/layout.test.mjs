import test from "node:test";
import assert from "node:assert/strict";
import {
  safeViewport,
  bounds,
  camera,
  readableViews,
  wrapText,
  prepareScene,
} from "./layout.mjs";
const text = (id, x, y, w, h) => ({
  id,
  type: "text",
  x,
  y,
  width: w,
  height: h,
  fontSize: 20,
  text: "Work",
  groupIds: [id],
});
test("readable fit clears toolbar, footer and side padding", () => {
  const elements = [text("a", 10, 20, 400, 240)];
  const rect = { x: 24, y: 96, width: 480, height: 440 };
  const view = readableViews(elements, rect)[0],
    c = camera(view, rect),
    b = bounds(elements),
    z = c.zoom.value;
  assert.ok((b.x + c.scrollX) * z >= rect.x);
  assert.ok((b.y + c.scrollY) * z >= rect.y);
  assert.ok((b.x + b.width + c.scrollX) * z <= rect.x + rect.width + 0.01);
  assert.ok((b.y + b.height + c.scrollY) * z <= rect.y + rect.height + 0.01);
  assert.ok(z * 20 >= 16);
});
test("dense board gets readable views rather than tiny all-content zoom", () => {
  const es = Array.from({ length: 12 }, (_, i) =>
    text("n" + i, (i % 3) * 350, Math.floor(i / 3) * 280, 320, 250),
  );
  const views = readableViews(es, { x: 16, y: 90, width: 330, height: 430 });
  assert.ok(views.length > 1);
  assert.ok(views.every((v) => v.zoom * 20 >= 16));
});
test("long human text has reachable camera tiles without modifying the text", () => {
  const e = text("a", 0, 0, 500, 2500),
    before = JSON.stringify(e);
  const views = readableViews([e], { x: 20, y: 90, width: 500, height: 400 });
  assert.ok(views.length > 1);
  assert.equal(JSON.stringify(e), before);
  assert.ok(views.at(-1).y + views.at(-1).height >= 2500);
});
test("pixel wrapping includes wide glyphs and unbroken words without losing source", () => {
  const source = "WWW WWW long_unbroken_path_1234567890";
  const width = (s) => [...s].reduce((n, c) => n + (c === "W" ? 20 : 8), 0);
  const wrapped = wrapText(source, 72, width);
  assert.ok(wrapped.split("\n").every((s) => width(s) <= 72));
  assert.equal(wrapped.replace(/\s/g, ""), source.replace(/\s/g, ""));
});
test("font repair does not mutate the server baseline or claim human work", () => {
  const e = {
    ...text("a", 20, 30, 80, 120),
    text: "WWW WWW",
    originalText: "WWW WWW",
    lineHeight: 1.3,
    customData: { projection: 2 },
  };
  const human = {
    ...text("b", 90, 40, 100, 100),
    customData: { humanTouched: true },
  };
  const scene = { elements: [e, human] },
    copy = JSON.stringify(scene);
  const result = prepareScene(scene, (s) => s.length * 20);
  assert.equal(JSON.stringify(scene), copy);
  assert.equal(result.elements[0].text, "WWW\nWWW");
  assert.deepEqual(result.elements[1], human);
});

test("mobile bottom toolbar is not mistaken for a top obstruction", () => {
  const toolbar = (top, bottom) => ({
    getBoundingClientRect: () => ({
      top,
      bottom,
      left: 14,
      right: 466,
      width: 452,
      height: bottom - top,
    }),
    matches: (s) => s.includes(".App-toolbar"),
  });
  const editor = {
    getBoundingClientRect: () => ({
      top: 48,
      bottom: 720,
      left: 0,
      right: 480,
      width: 480,
      height: 672,
    }),
    querySelectorAll: () => [toolbar(64, 108), toolbar(658, 706)],
  };
  const rect = safeViewport(editor);
  assert.equal(rect.y, 84);
  assert.ok(rect.height > 450);
  assert.ok(rect.y + rect.height <= 610);
});
test("old element insertion order cannot interleave workflow and supporting groups", () => {
  const unit = (id, order, x) => [
    {
      id: id + "box",
      type: "rectangle",
      x,
      y: 20,
      width: 250,
      height: 120,
      groupIds: [id],
      customData: {
        projection: 3,
        sectionId: id,
        renderOrder: order,
        sequence: true,
      },
    },
    {
      ...text(id + "head", x + 16, 34, 218, 30),
      text: "Title",
      originalText: "Title",
      lineHeight: 1.3,
      groupIds: [id],
      customData: {
        projection: 3,
        sectionId: id,
        renderOrder: order,
        heading: true,
      },
    },
    {
      ...text(id + "body", x + 16, 70, 218, 40),
      text: "Words",
      originalText: "Words",
      lineHeight: 1.3,
      groupIds: [id],
      customData: { projection: 3, sectionId: id, renderOrder: order },
    },
  ];
  const scene = {
    elements: [
      ...unit("support", 1000, 24),
      ...unit("first", 0, 24),
      ...unit("second", 1, 298),
      ...unit("third", 2, 24),
    ],
  };
  scene.elements.find((e) => e.id === "secondbody").originalText =
    "Long step details ".repeat(12);
  const result = prepareScene(scene, (s) => s.length * 10);
  const second = result.elements.find((e) => e.id === "secondbox"),
    third = result.elements.find((e) => e.id === "thirdbox");
  assert.ok(third.y >= second.y + second.height + 24);
  assert.ok(
    result.elements.find((e) => e.id === "supportbox").y >
      result.elements.find((e) => e.id === "firstbox").y,
  );
});

import { graphRanks } from "./layout.mjs";
const semantic = () => {
  const nodes = ["root", "left", "right"].map((id, i) => ({
    id,
    scope: "graph",
    kind: "graph",
    sectionId: "work",
  }));
  const edges = [
    { id: "one", from: "root", to: "left" },
    { id: "two", from: "root", to: "right" },
  ];
  const elements = nodes.flatMap((n, i) => [
    {
      id: n.id + "-card",
      type: "rectangle",
      x: i * 300,
      y: 24,
      width: 280,
      height: 150,
      groupIds: [n.id],
      customData: {
        nodeId: n.id,
        part: "card",
        projection: 6,
        renderOrder: i,
        representation: "map",
      },
    },
    ...["heading", "body"].map((part) => ({
      id: n.id + "-" + part,
      type: "text",
      x: i * 300 + 16,
      y: 40,
      width: 248,
      height: 30,
      groupIds: [n.id],
      text: part === "heading" ? n.id : "Measured content in a clear font.",
      originalText:
        part === "heading" ? n.id : "Measured content in a clear font.",
      fontSize: part === "heading" ? 24 : 20,
      fontFamily: 2,
      lineHeight: 1.3,
      customData: {
        nodeId: n.id,
        part,
        projection: 6,
        renderOrder: i,
        representation: "map",
      },
    })),
  ]);
  return {
    elements,
    adaptive: true,
    model: { nodes, edges },
    layout: { width: 800, gap: 24 },
  };
};
const measure = (s) => s.length * 10;
test("semantic branches occupy layers with no overlapping cards at either width", () => {
  for (const width of [340, 800]) {
    const scene = prepareScene(semantic(), measure, { rect: { width } }),
      cards = scene.elements.filter((e) => e.type === "rectangle");
    for (const a of cards)
      for (const b of cards)
        if (a.id !== b.id)
          assert.ok(
            a.x + a.width <= b.x ||
              b.x + b.width <= a.x ||
              a.y + a.height <= b.y ||
              b.y + b.height <= a.y,
          );
    assert.ok(cards.every((e) => e.width <= width));
    assert.ok(cards.slice(1).every((e) => e.y >= cards[0].y + cards[0].height));
    for (const e of scene.elements.filter((e) => e.type === "text"))
      assert.ok(e.text.split("\n").every((l) => measure(l) <= e.width));
  }
});
test("editing words does not pin a node or freeze the other branches", () => {
  const scene = semantic();
  const edited = scene.elements.find((e) => e.id === "left-body");
  edited.originalText = "Human correction ".repeat(8);
  edited.customData.humanTouched = true;
  edited.customData.humanFields = ["text", "originalText"];
  const out = prepareScene(scene, measure, { rect: { width: 340 } }),
    body = out.elements.find((e) => e.id === edited.id),
    box = out.elements.find((e) => e.id === "left-card");
  assert.equal(
    body.text.replace(/\s/g, ""),
    edited.originalText.replace(/\s/g, ""),
  );
  assert.ok(body.y + body.height < box.y + box.height);
  assert.ok(out.elements.find((e) => e.id === "right-card").y > box.y);
});
test("a moved node stays put while automatic cards avoid it", () => {
  const scene = semantic();
  for (const e of scene.elements.filter((e) => e.customData.nodeId === "left"))
    e.customData.pinned = true;
  const before = scene.elements.filter((e) => e.customData.nodeId === "left");
  const out = prepareScene(scene, measure, { rect: { width: 340 } });
  for (const e of before) {
    const result = out.elements.find((v) => v.id === e.id);
    assert.equal(result.x, e.x);
    assert.equal(result.y, e.y);
    if (e.type === "text")
      assert.equal(
        result.height,
        result.text.split("\n").length * result.fontSize * result.lineHeight,
      );
  }
});
test("adaptation off does not wrap, pack or reroute on resize", () => {
  const scene = semantic();
  scene.adaptive = false;
  assert.deepEqual(
    prepareScene(scene, measure, { rect: { width: 240 } }),
    scene,
  );
});
test("cyclic and disconnected relationships have finite local ranks", () => {
  const nodes = ["a", "b", "c"].map((id) => ({ id }));
  const ranks = graphRanks(nodes, [
    { from: "a", to: "b" },
    { from: "b", to: "a" },
  ]);
  assert.equal(ranks.size, 3);
  assert.ok([...ranks.values()].every(Number.isFinite));
});
test("backward arrows are included in fit bounds", () => {
  assert.deepEqual(
    bounds([
      {
        type: "arrow",
        x: 300,
        y: 200,
        width: 200,
        height: 100,
        points: [
          [0, 0],
          [-200, -100],
        ],
      },
    ]),
    { x: 100, y: 100, width: 200, height: 100 },
  );
});
