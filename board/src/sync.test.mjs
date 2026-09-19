import test from "node:test";
import assert from "node:assert/strict";
import { changes, mergeAcknowledgement, safeLink } from "./sync.mjs";
const a = { id: "a", type: "text", text: "Original", x: 0 };
test("editor bookkeeping is not a human edit", () =>
  assert.deepEqual(
    changes(
      [{ ...a, version: 90, index: "b2", customData: { humanTouched: true } }],
      [a],
    ),
    [],
  ));
test("text, movement and deletion are edits", () => {
  for (const patch of [{ text: "New" }, { x: 4 }, { isDeleted: true }])
    assert.equal(changes([{ ...a, ...patch }], [a]).length, 1);
});
test("edits made during a save are preserved beside remote objects", () => {
  const submitted = [a],
    newer = { ...a, text: "Still typing" },
    remote = [
      { ...a, customData: { lastActor: "human" } },
      { id: "b", text: "Agent" },
    ];
  assert.deepEqual(mergeAcknowledgement([newer], submitted, remote), [
    newer,
    remote[1],
  ]);
});
test("new local objects survive an in-flight acknowledgement", () => {
  const b = { id: "b", text: "New" };
  assert.deepEqual(mergeAcknowledgement([a, b], [a], [a]), [a, b]);
});
test("unsafe URL schemes cannot navigate the board", () => {
  assert.equal(safeLink("javascript:alert(1)", "https://example.com"), null);
  assert.equal(safeLink("/a", "https://example.com"), "https://example.com/a");
  assert.equal(
    safeLink("https://example.org", "https://example.com"),
    "https://example.org/",
  );
});
import { startPolling } from "./polling.mjs";
test("stopping during an in-flight poll prevents rescheduling", async () => {
  let release,
    scheduled = 0;
  const stop = startPolling(
    () =>
      new Promise((r) => {
        release = r;
      }),
    {
      schedule: () => {
        scheduled++;
      },
      cancel: () => {},
    },
  );
  stop();
  release();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(scheduled, 0);
});
import { debounce } from "./polling.mjs";
test("debounced viewport work cancels the latest timer on unmount", () => {
  let id = 0;
  const cancelled = [];
  const run = debounce(
    () => {},
    900,
    () => ++id,
    (x) => cancelled.push(x),
  );
  run();
  run();
  run.cancel();
  assert.deepEqual(cancelled, [undefined, 1, 2]);
});
test("retired server objects are not reintroduced by an unchanged save acknowledgement", () => {
  assert.deepEqual(mergeAcknowledgement([a], [a], []), []);
  assert.deepEqual(
    mergeAcknowledgement([{ ...a, text: "Still editing" }], [a], []),
    [{ ...a, text: "Still editing" }],
  );
});
