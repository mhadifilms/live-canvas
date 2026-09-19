// Compare authored properties, not editor bookkeeping or server-owned metadata.
const transient = new Set([
  "customData",
  "version",
  "versionNonce",
  "updated",
  "index",
  "seed",
]);
export function signature(element) {
  return JSON.stringify(
    Object.fromEntries(
      Object.keys(element)
        .sort()
        .filter((k) => !transient.has(k))
        .map((k) => [k, element[k]]),
    ),
  );
}
export function changes(elements, baseline) {
  const previous = new Map(baseline.map((e) => [e.id, signature(e)]));
  return elements.filter((e) => signature(e) !== previous.get(e.id));
}
// A save may finish while the person keeps drawing. Preserve every newer local edit.
export function mergeAcknowledgement(local, submitted, remote) {
  const sent = new Map(submitted.map((e) => [e.id, signature(e)]));
  const pending = new Map(
    local.filter((e) => signature(e) !== sent.get(e.id)).map((e) => [e.id, e]),
  );
  return [
    ...remote.map((e) => pending.get(e.id) || e),
    ...local.filter(
      (e) =>
        !remote.some((r) => r.id === e.id) &&
        (!sent.has(e.id) || pending.has(e.id)),
    ),
  ];
}
export function safeLink(link, origin) {
  try {
    const u = new URL(link, origin);
    return ["http:", "https:", "mailto:"].includes(u.protocol) ? u.href : null;
  } catch {
    return null;
  }
}
