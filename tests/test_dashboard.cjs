const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

function setup(hidden = false) {
  const timers = new Map();
  const events = new Map();
  const elements = new Map();
  const requests = [];
  let nextTimer = 0;
  const element = id => {
    if (!elements.has(id)) elements.set(id, { textContent: '', querySelector() { return null; } });
    return elements.get(id);
  };
  const on = (name, fn) => {
    const previous = events.get(name);
    events.set(name, event => { previous?.(event); fn(event); });
  };
  const document = {
    hidden,
    addEventListener: on,
    querySelector(selector) {
      if (selector === '#scan-app') return null;
      if (selector.startsWith('meta')) return { content: 'csrf' };
      return element(selector);
    },
    querySelectorAll() { return []; },
  };
  const context = {
    document, AbortController, Intl, Date, Set,
    window: {
      addEventListener: on,
      setTimeout(fn) { timers.set(++nextTimer, fn); return nextTimer; },
      clearTimeout(id) { timers.delete(id); },
    },
    fetch(url, { signal }) {
      // Deliberately delay abort settlement, like a browser restoring a page
      // while an old network operation is still unwinding.
      return new Promise((resolve, reject) => requests.push({ url, signal, resolve, reject }));
    },
  };
  vm.runInNewContext(readFileSync(join(__dirname, '../equipment_manager/static/app.js'), 'utf8'), context);
  return {
    timers, requests, element,
    hide() { document.hidden = true; events.get('visibilitychange')(); },
    show() { document.hidden = false; events.get('visibilitychange')(); },
    fire(name, event = {}) { events.get(name)(event); },
    tick() {
      const [id, fn] = timers.entries().next().value;
      timers.delete(id);
      fn();
    },
    answer(request = requests.at(-1)) {
      request.resolve({ ok: true, json: async () => ({ ok: true, inventory: [],
        device: { online: true, last_seen: null }, server_time: null }) });
    },
    abort(request = requests.at(-1)) {
      const error = new Error('aborted');
      error.name = 'AbortError';
      request.reject(error);
    },
  };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test('hidden dashboard sends no requests and repeated resume starts only once', async () => {
  const ui = setup(true);
  assert.equal(ui.requests.length, 0);
  ui.show();
  ui.show();
  ui.fire('pageshow', { persisted: true });
  assert.equal(ui.requests.length, 1);
  ui.answer();
  await settle();
  assert.equal(ui.timers.size, 1);
  ui.show();
  assert.equal(ui.requests.length, 1);
  ui.hide();
  assert.equal(ui.timers.size, 0);
});

test('hidden tab aborts in-flight fetch and ignores its late successful response', async () => {
  const ui = setup();
  ui.hide();
  assert.equal(ui.requests[0].signal.aborted, true);
  ui.answer();
  await settle();
  assert.equal(ui.element('#device-state').textContent, '');
  assert.equal(ui.timers.size, 0);
  ui.show();
  assert.equal(ui.requests.length, 2);
});

test('100 page restore cycles never overlap requests or accumulate timers', async () => {
  const ui = setup();
  for (let i = 0; i < 100; i++) {
    assert.equal(ui.requests.length, i + 1);
    ui.fire('pagehide');
    assert.equal(ui.requests.at(-1).signal.aborted, true);
    ui.fire('pageshow', { persisted: true });
    ui.show();
    assert.equal(ui.requests.length, i + 1);
    ui.abort();
    await settle();
    assert.equal(ui.timers.size, 1);
    ui.tick();
    assert.equal(ui.timers.size, 1); // Only the request deadline remains.
  }
  ui.hide();
  ui.abort();
  await settle();
  assert.equal(ui.timers.size, 0);
});

test('request timeout is cleaned before scheduling the next poll', async () => {
  const ui = setup();
  ui.tick();
  assert.equal(ui.requests[0].signal.aborted, true);
  ui.abort();
  await settle();
  assert.equal(ui.timers.size, 1);
  assert.equal(ui.element('#device-state').textContent, '서버 연결 실패');
});
