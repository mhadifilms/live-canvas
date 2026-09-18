// DOM-helper regressions only; real layout/keyboard checks still need a browser.
import { readFileSync } from 'node:fs';
import { runInContext, createContext } from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
  constructor(tag = '#text', text = '') { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.style = {}; this.textContent = text; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = value; this.children = []; }
  append(...children) { for (const child of children) { if (child.parentElement) child.parentElement.children.splice(child.parentElement.children.indexOf(child), 1); child.parentElement = this; this.children.push(child); } }
  after(child) { const parent = this.parentElement; child.parentElement = parent; parent.children.splice(parent.children.indexOf(this) + 1, 0, child); }
  cloneNode(deep) { const copy = new Element(this.tagName, this._text); copy.className = this.className; if (deep) this.children.forEach(child => copy.append(child.cloneNode(true))); return copy; }
  querySelector(tag) { return this.children.find(child => child.tagName === tag) || this.children.map(child => child.querySelector(tag)).find(Boolean); }
  addEventListener() {}
  setAttribute(name, value) { this.attributes[name] = value; }
}
function viewer(storage = new Map(), unavailable = false) {
  const elements = new Map();
  const document = {
    documentElement: new Element('html'),
    getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
    createElement: tag => new Element(tag),
    createTextNode: text => new Element('#text', text),
    addEventListener() {},
  };
  const localStorage = {
    getItem(key) { if (unavailable) throw Error('Unavailable'); return storage.get(key) ?? null; },
    setItem(key, value) { if (unavailable) throw Error('Unavailable'); storage.set(key, value); },
  };
  const context = createContext({ document, localStorage, URL, navigator: {},
    setTimeout: () => 0, clearTimeout() {}, setInterval() {}, fetch: () => new Promise(() => {}), window: {} });
  runInContext(script, context);
  return { evaluate: code => runInContext(code, context), elements, storage };
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
  assert.equal(view.storage.size, 1);
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
