// DOM-helper regressions only; real layout/keyboard checks still need a browser.
import { readFileSync } from 'node:fs';
import { runInContext, createContext } from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, webcrypto } from 'node:crypto';

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
  constructor(tag = '#text', text = '') { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.style = {}; this.listeners = new Map(); this.textContent = text; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = value; this.children = []; }
  get lastChild() { return this.children.at(-1); }
  get childElementCount() { return this.children.length; }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  focus() { this.focused = true; }
  append(...children) { for (const child of children) { if (child.parentElement) child.parentElement.children.splice(child.parentElement.children.indexOf(child), 1); child.parentElement = this; this.children.push(child); } }
  after(child) { const parent = this.parentElement; child.parentElement = parent; parent.children.splice(parent.children.indexOf(this) + 1, 0, child); }
  cloneNode(deep) { const copy = new Element(this.tagName, this._text); copy.className = this.className; if (deep) this.children.forEach(child => copy.append(child.cloneNode(true))); return copy; }
  querySelector(tag) { return this.children.find(child => child.tagName === tag) || this.children.map(child => child.querySelector(tag)).find(Boolean); }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  setAttribute(name, value) { this.attributes[name] = value; }
}
function viewer(storage = new Map(), unavailable = false, options = {}) {
  const elements = new Map(), events = new Map();
  const document = {
    documentElement: Object.assign(new Element('html'), { dataset: options.route ? { canvasRoute: options.route } : {} }),
    getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
    createElement: tag => new Element(tag),
    createTextNode: text => new Element('#text', text),
    addEventListener() {},
  };
  const localStorage = {
    get length() { if (unavailable) throw Error('Unavailable'); return storage.size; },
    key(index) { return [...storage.keys()][index] ?? null; },
    getItem(key) { if (unavailable) throw Error('Unavailable'); return storage.get(key) ?? null; },
    setItem(key, value) { if (unavailable) throw Error('Unavailable'); storage.set(key, value); },
    removeItem(key) { if (unavailable) throw Error('Unavailable'); storage.delete(key); },
  };
  const context = createContext({ document, localStorage, URL, URLSearchParams, location: { hash: options.hash || '' }, history: options.history || { replaceState() {} }, TextEncoder, crypto: webcrypto, navigator: {},
    setTimeout: () => 0, clearTimeout() {}, setInterval() {}, fetch: options.fetch || (() => new Promise(() => {})),
    window: { addEventListener(name, listener) { events.set(name, listener); } } });
  runInContext(script, context);
  return { evaluate: code => runInContext(code, context), elements, storage,
    storageEvent(key) { events.get('storage')?.({ key, storageArea: localStorage }); } };
}
const data = { thread: 'fixture-session', context_started_at: '2026-01-01T00:00:00Z', content: { context: { id: 'study' } } };
const key = JSON.stringify(['section', 'block', { prompt: 'Question', answer: 'First answer' }]);
function selectContext(view, value = data) { view.evaluate(`useLocalState(${JSON.stringify(value)})`); }

test('Markdown uses text nodes, formats safe links, and refuses executable URLs', () => {
  const view = viewer();
  const el = view.evaluate(`richText(node('p'), '**Bold** [Docs](https://example.org/path) [Bad](javascript:alert) <img src=x onerror=alert(1)>')`);
  assert.equal(el.children.filter(child => child.tagName === 'strong').length, 1);
  const links = el.children.filter(child => child.tagName === 'a');
  assert.equal(links.length, 1);
  assert.equal(links[0].href, 'https://example.org/path');
  assert.equal(links[0].rel, 'noopener noreferrer');
  assert.equal(links[0].referrerPolicy, 'no-referrer');
  assert.ok(el.children.some(child => child.tagName === '#text' && child.textContent.includes('<img')));
  assert.equal(view.evaluate(`plainText('**Idea** [file](/local/example.py) [Bad](javascript:alert)')`), 'Idea file Bad');
  for (const url of ['javascript:alert(1)', 'data:text/html,test', 'file:///tmp/test', '//example.org', 'java\nscript:alert']) {
    assert.equal(view.evaluate(`safeURL(${JSON.stringify(url)})`), null);
  }
});

test('Local choices survive feed changes and reload but invalidate changed content/context', () => {
  const first = viewer(); selectContext(first);
  first.evaluate(`localSet(${JSON.stringify(key)}, true)`);
  selectContext(first, { ...data, revision: 123, feed: [{ text: 'Unrelated update' }] });
  assert.equal(first.evaluate(`localGet(${JSON.stringify(key)}, false)`), true);
  const reloaded = viewer(first.storage); selectContext(reloaded);
  assert.equal(reloaded.evaluate(`localGet(${JSON.stringify(key)}, false)`), true);
  assert.equal(reloaded.evaluate(`localGet(${JSON.stringify(key.replace('First answer', 'Changed answer'))}, false)`), false);
  selectContext(reloaded, { ...data, context_started_at: '2026-01-02T00:00:00Z' });
  assert.equal(reloaded.evaluate(`localGet(${JSON.stringify(key)}, false)`), false);
});

test('Unavailable storage does not prevent session-local interaction', () => {
  const view = viewer(new Map(), true); selectContext(view);
  view.evaluate(`localSet(${JSON.stringify(key)}, 'remembered')`);
  assert.equal(view.evaluate(`localGet(${JSON.stringify(key)}, 'new')`), 'remembered');
  assert.match(view.elements.get('storage-note').textContent, /last for this page only/);
});

test('Browser interaction cache is bounded per task', () => {
  const view = viewer(); selectContext(view);
  view.evaluate(`for (let i = 0; i < 450; i++) localSet('item-' + i + 'x'.repeat(800), true)`);
  assert.ok(view.evaluate('Object.keys(localValues).length') <= 400);
  assert.ok(view.evaluate('JSON.stringify(localValues).length') <= 200000);
  assert.ok(view.storage.size <= 400);
  assert.ok([...view.storage].reduce((sum, [key, value]) => sum + key.length + value.length, 0) <= 200000);
});

test('Large collections disclose after five rows without duplicating or losing row nodes', () => {
  const view = viewer(); selectContext(view);
  for (const tag of ['ul', 'ol', 'div']) {
    const result = view.evaluate(`(() => { const host = node('div'), list = node('${tag}'); host.append(list); for (let i = 0; i < 9; i++) list.append(node('li', String(i))); const original = list.children.slice(); localSet('more-${tag}', true); foldCollection(list, 'more-${tag}'); return { first: list.children, more: host.children[1], original }; })()`);
    assert.equal(result.first.length, 5);
    assert.equal(result.more.open, true);
    assert.equal(result.more.children[1].children.length, 4);
    assert.equal(result.more.children[1].children[0], result.original[5]);
  }
  const table = view.evaluate(`(() => { const host = node('div'), table = node('table'), head = node('thead'), body = node('tbody'); head.append(node('tr', 'Heading')); table.append(head, body); host.append(table); for (let i = 0; i < 8; i++) body.append(node('tr', String(i))); foldCollection(body, 'table-more'); return host; })()`);
  assert.equal(table.children[0].querySelector('tbody').children.length, 5);
  assert.equal(table.children[1].children[1].querySelector('tbody').children.length, 3);
  assert.equal(table.children[1].children[1].querySelector('thead').textContent, 'Heading');
});

test('Content fingerprints match SHA-256 for long and Unicode input', () => {
  const view = viewer();
  for (const value of ['', 'abc', 'A🌱é\ud800', 'x'.repeat(110000)]) {
    assert.equal(view.evaluate(`fingerprint(${JSON.stringify(value)})`), createHash('sha256').update(value).digest('hex'));
  }
});

function descendants(element) { return [element, ...element.children.flatMap(descendants)]; }
test('LC003: a valid 110k answer retains a newly marked remembered state', () => {
  const view = viewer(); selectContext(view);
  const block = { id: 'cards', type: 'reveal', items: [{ id: 'card', prompt: 'Question', answer: 'x'.repeat(110000) }] };
  const card = view.evaluate(`renderStudy(${JSON.stringify(block)}, 'section')`);
  descendants(card).find(el => el.tagName === 'button' && el.textContent === 'Reveal answer').onclick();
  descendants(card).find(el => el.tagName === 'button' && el.textContent === 'Got it').onclick();
  assert.match(card.textContent, /1 of 1 remembered/);
  const reloaded = viewer(view.storage); selectContext(reloaded);
  const again = reloaded.evaluate(`renderStudy(${JSON.stringify(block)}, 'section')`);
  assert.match(again.textContent, /1 of 1 remembered/);
  assert.ok([...view.storage.values()].every(value => !value.includes('x'.repeat(100))));
  block.items[0].answer = 'Changed answer';
  assert.match(reloaded.evaluate(`renderStudy(${JSON.stringify(block)}, 'section')`).textContent, /0 of 1 remembered/);
});

test('Existing v1 marks migrate without overriding newer v2 choices', () => {
  const storage = new Map(), old = viewer(storage);
  const oldKey = old.evaluate(`'live-canvas-interactions-v1:' + hash(${JSON.stringify(data.thread)})`);
  const digest = old.evaluate(`hash(${JSON.stringify(key)})`);
  const saved = { boundary: JSON.stringify([data.thread, data.content.context.id, data.context_started_at]),
    values: { [digest]: { signature: key, value: true } } };
  storage.set(oldKey, JSON.stringify(saved));
  const first = viewer(storage); selectContext(first);
  assert.equal(first.evaluate(`localGet(${JSON.stringify(key)}, false)`), true);
  assert.equal(storage.has(oldKey), false);
  first.evaluate(`localSet(${JSON.stringify(key)}, false)`);
  storage.set(oldKey, JSON.stringify(saved)); // A partially migrated or old viewer re-saved v1.
  const second = viewer(storage); selectContext(second);
  assert.equal(second.evaluate(`localGet(${JSON.stringify(key)}, true)`), false);
  const changed = viewer(storage); selectContext(changed, { ...data, context_started_at: '2026-02-01' });
  assert.equal(changed.evaluate(`localGet(${JSON.stringify(key)}, false)`), false);
});

test('LC004: interleaved tab writes merge by record, synchronize, and respect reset epochs', () => {
  const storage = new Map(), first = viewer(storage), second = viewer(storage);
  selectContext(first); selectContext(second);
  first.evaluate(`localSet('choice-a', true)`);
  second.evaluate(`localSet('choice-b', true)`);
  for (const view of [first, second, viewer(storage)]) {
    selectContext(view);
    assert.equal(view.evaluate(`localGet('choice-a', false)`), true);
    assert.equal(view.evaluate(`localGet('choice-b', false)`), true);
  }
  second.evaluate('globalThis.refreshes = 0; refreshLocalView = () => { globalThis.refreshes++; }');
  second.storageEvent([...storage.keys()][0]);
  assert.equal(second.evaluate('globalThis.refreshes'), 1);
  const oldRecords = [...storage.entries()];
  first.evaluate('resetLocalState()');
  const epochKey = first.evaluate("localPrefix + 'epoch'");
  second.storageEvent(epochKey);
  assert.equal(second.evaluate(`localGet('choice-a', false)`), false);
  assert.equal(second.evaluate(`localGet('choice-b', false)`), false);
  // An in-flight old-epoch write and its delayed event cannot resurrect a reset.
  const [oldKey, oldValue] = oldRecords[0]; storage.set(oldKey, oldValue); second.storageEvent(oldKey);
  assert.equal(second.evaluate(`localGet('choice-a', false)`), false);
  second.evaluate(`localSet('choice-b', true)`);
  assert.equal(first.evaluate(`localGet('choice-b', false)`), true);
  const before = storage.get([...storage.keys()].find(name => name.endsWith(second.evaluate("fingerprint('choice-b')"))));
  second.evaluate(`localSet('choice-b', true)`);
  assert.equal(storage.get([...storage.keys()].find(name => name.endsWith(second.evaluate("fingerprint('choice-b')")))), before);
});

test('Old queued disclosure toggles cannot repopulate a reset epoch', () => {
  const view = viewer(); selectContext(view);
  const details = view.evaluate(`disclosure('More', 'old-disclosure')`);
  details.open = true;
  view.evaluate('resetLocalState()');
  details.listeners.get('toggle')();
  assert.equal(view.evaluate(`localGet('old-disclosure', false)`), false);
});

test('LC002: failed JSON or render keeps old ETag and retries the same revision', async () => {
  const calls = []; let stage = 'pending';
  const fetch = async (_url, options) => {
    calls.push(options.headers['If-None-Match']);
    if (stage === 'pending') return new Promise(() => {});
    return { status: 200, ok: true, headers: { get: () => '"next"' }, json: async () => {
      if (stage === 'bad-json') throw Error('Interrupted body');
      return { name: 'next' };
    } };
  };
  const view = viewer(new Map(), false, { fetch });
  view.evaluate(`state = {name:'previous'}; etag = '"previous"'; refreshTimes = () => {}; render = next => { state = next; };`);
  stage = 'bad-json'; await view.evaluate('poll()');
  assert.equal(view.evaluate('etag'), '"previous"');
  assert.equal(view.evaluate('state.name'), 'previous');
  assert.equal(view.elements.get('connection').dataset.live, 'false');
  stage = 'valid'; view.evaluate(`render = next => { if (next.name === 'next') throw Error('Render failed'); state = next; };`);
  await view.evaluate('poll()');
  assert.equal(view.evaluate('etag'), '"previous"');
  assert.equal(view.evaluate('state.name'), 'previous');
  view.evaluate('render = next => { state = next; };');
  await view.evaluate('poll()');
  assert.equal(view.evaluate('etag'), '"next"');
  assert.equal(view.evaluate('state.name'), 'next');
  assert.deepEqual(calls.slice(1), ['"previous"', '"previous"', '"previous"']);
});


test('bootstrap removes visible credentials before authentication and polls the clean route', async () => {
  const calls = [], replaced = [];
  const app = viewer(new Map(), false, { route: '/quiz-review', hash: '#auth=task-secret',
    history: { replaceState(...args) { replaced.push(args); } },
    fetch: async (url, options) => {
      calls.push({ url, options, cleaned: replaced.length === 1 });
      if (url.endsWith('/_auth')) return { ok: true };
      return { status: 304 };
    },
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(replaced[0][2], '/quiz-review');
  assert.equal(calls[0].cleaned, true);
  assert.equal(calls[0].url, '/quiz-review/_auth');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer task-secret');
  assert.equal(calls[1].url, '/quiz-review/state');
  assert.equal(app.evaluate('bootstrapCredential'), null);
  assert.equal(app.storage.size, 0);
  await app.evaluate('poll()');
  assert.equal(calls.filter(call => call.url.endsWith('/_auth')).length, 1);
});

test('clean reload uses its task cookie without exposing a new credential', async () => {
  const calls = [];
  viewer(new Map(), false, { route: '/quiz-review', fetch: async url => { calls.push(url); return { status: 304 }; } });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['/quiz-review/state']);
});

test('failed bootstrap keeps no credential in the URL and does not request task data', async () => {
  const calls = [], replaced = [];
  const app = viewer(new Map(), false, { route: '/quiz-review', hash: '#auth=incorrect',
    history: { replaceState(...args) { replaced.push(args); } },
    fetch: async url => { calls.push(url); return { ok: false, status: 403 }; },
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(replaced[0][2], '/quiz-review');
  assert.deepEqual(calls, ['/quiz-review/_auth']);
  assert.equal(app.elements.get('connection').dataset.live, 'false');
});
