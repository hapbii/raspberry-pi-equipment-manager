const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

function setup(hidden = false, equipmentIds = []) {
  const timers = new Map();
  const events = new Map();
  const elements = new Map();
  const requests = [];
  let nextTimer = 0;
  let reloads = 0;
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      textContent: '', style: {}, classList: {toggle() {}},
      querySelector(selector) {
        if (id === '#inventory-grid') {
          const match = selector.match(/data-equipment-id="(\d+)"/);
          if (!match || !equipmentIds.some(value => String(value) === match[1])) return null;
        }
        return element(`${id} ${selector}`);
      },
    });
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
    querySelectorAll(selector) {
      if (selector === '#inventory-grid [data-equipment-id]') {
        return equipmentIds.map(id => ({dataset: {equipmentId: String(id)}}));
      }
      return [];
    },
  };
  const context = {
    document, AbortController, Intl, Date, Set,
    window: {
      location: {reload() { reloads++; }},
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
    timers, requests, element, get reloads() { return reloads; },
    hide() { document.hidden = true; events.get('visibilitychange')(); },
    show() { document.hidden = false; events.get('visibilitychange')(); },
    fire(name, event = {}) { events.get(name)(event); },
    tick() {
      const [id, fn] = timers.entries().next().value;
      timers.delete(id);
      fn();
    },
    answer(request = requests.at(-1), inventory = []) {
      request.resolve({ ok: true, json: async () => ({ ok: true, inventory,
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

test('equipment additions and removals refresh server-rendered cards and counts', async () => {
  for (const [initial, updated] of [[[], [1]], [[1], []], [[1], [2]]]) {
    const ui = setup(false, initial);
    ui.answer(undefined, updated.map(id => ({id})));
    await settle();
    assert.equal(ui.reloads, 1);
    assert.equal(ui.timers.size, 0);
    assert.equal(ui.requests.length, 1);
  }
});

test('unchanged equipment does not reload the dashboard', async () => {
  const ui = setup(false, [1]);
  ui.answer(undefined, [{id: 1, available_qty: 2, total_qty: 3, loaned_qty: 1, loan_period_days: 7}]);
  await settle();
  assert.equal(ui.reloads, 0);
  assert.equal(ui.timers.size, 1);
  assert.equal(ui.element('#dashboard-updated').textContent, '기록 없음');
  assert.equal(ui.element('#inventory-grid [data-equipment-id="1"] .available-number').textContent, 2);
});

test('late inventory changes after hiding the page never trigger reload', async () => {
  const ui = setup();
  ui.hide();
  ui.answer(undefined, [{id: 1}]);
  await settle();
  assert.equal(ui.reloads, 0);
  assert.equal(ui.timers.size, 0);
});

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
  assert.equal(ui.element('#dashboard-updated').textContent, '');
  assert.equal(ui.timers.size, 0);
  ui.show();
  assert.equal(ui.requests.length, 2);
});

test('pagehide clears the request deadline before an aborted fetch settles', async () => {
  const ui = setup();
  assert.equal(ui.timers.size, 1);
  ui.fire('pagehide');
  assert.equal(ui.requests[0].signal.aborted, true);
  assert.equal(ui.timers.size, 0);
  ui.abort();
  await settle();
  assert.equal(ui.timers.size, 0);
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
  assert.equal(ui.element('#dashboard-updated').textContent, '현황을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
});
