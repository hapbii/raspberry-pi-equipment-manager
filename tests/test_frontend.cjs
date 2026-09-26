const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

function setup(mode = 'yolo', canScan = true, ignoreAbort = false) {
  const elements = new Map();
  const timers = new Map();
  const pageEvents = new Map();
  const requests = [];
  let timerId = 0;
  let now = Date.now();
  class TestDate extends Date { static now() { return now; } }
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        value: '', disabled: false, open: false,
        dataset: { canScan: String(canScan), mode }, events: new Map(),
        classList: {
          add: (...names) => names.forEach((name) => classes.add(name)),
          remove: (...names) => names.forEach((name) => classes.delete(name)),
          toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
        },
        addEventListener(name, fn) { this.events.set(name, fn); },
        setAttribute() {}, removeAttribute() {}, toggleAttribute() {}, focus() {},
        showModal() { this.open = true; },
        close() { this.open = false; this.events.get('close')?.(); },
      });
    }
    return elements.get(id);
  }
  element('action').value = 'loan';
  const context = {
    AbortController, Intl, Date: TestDate, Number, Set,
    document: {
      querySelector(selector) {
        if (selector === '#inventory-grid') return null;
        if (selector.startsWith('meta')) return { content: 'csrf' };
        if (selector.includes(':checked')) return element('action');
        return element(selector);
      },
      querySelectorAll: (selector) => selector.includes('action') ? [element('action')] : [],
    },
    window: {
      addEventListener(name, fn) {
        const previous = pageEvents.get(name);
        pageEvents.set(name, (event = {}) => { previous?.(event); fn(event); });
      },
      setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
      clearTimeout(id) { timers.delete(id); },
    },
    fetch(url, options) {
      return new Promise((resolve, reject) => {
        const request = { url, body: JSON.parse(options.body), resolve };
        requests.push(request);
        options.signal.addEventListener('abort', () => {
          if (ignoreAbort) return;
          const error = new Error('aborted');
          error.name = 'AbortError';
          reject(error);
        }, { once: true });
      });
    },
  };
  vm.runInNewContext(readFileSync(join(__dirname, '../equipment_manager/static/app.js'), 'utf8'), context);
  const fire = (id, name) => element(id).events.get(name)({ preventDefault() {} });
  const answer = (request, data, ok = true) => {
    if (data.scan) {
      data.server_time ??= new Date(now).toISOString();
      data.scan.expires_at ??= new Date(now + 90000).toISOString();
    }
    request.resolve({ ok, json: async () => data });
  };
  return { element, timers, requests, fire, answer, pageEvents, advance(ms) { now += ms; } };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

async function readyScan(ui) {
  ui.element('#student-id').value = '30304';
  ui.element('#loan-reason').value = '실습';
  const promise = ui.fire('#detect-button', 'click');
  ui.answer(ui.requests.at(-1), { ok: true, server_time: '2020-01-01T00:00:00Z',
    scan: { token: 'expiring-scan', expires_at: '2020-01-01T00:01:30Z',
      equipment_name: 'meter', confidence: 0.9, due_date: null }, votes: 3, frame_count: 3, duration_ms: 100 });
  await promise;
}

test('missing model disables detection even in yolo mode', async () => {
  const ui = setup('yolo', false);
  assert.equal(ui.element('#detect-button').disabled, true);
  await ui.fire('#detect-button', 'click');
  assert.equal(ui.requests.length, 0);
});

test('countdown handles clock skew and blocks expired confirmation', async () => {
  const ui = setup();
  await readyScan(ui);
  assert.match(ui.element('#scan-expiry').textContent, /90초/);
  assert.equal(ui.timers.size, 1);
  ui.advance(91000);
  [...ui.timers.values()][0]();
  assert.equal(ui.element('#confirm-button').disabled, true);
  assert.match(ui.element('#scan-expiry').textContent, /만료/);
  ui.fire('#confirm-button', 'click');
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.timers.size, 0);
});

test('retry and page exit clear countdown and restored pages recheck expiry', async () => {
  const ui = setup();
  await readyScan(ui);
  ui.fire('#retry-button', 'click');
  assert.equal(ui.timers.size, 0);
  await readyScan(ui);
  ui.pageEvents.get('pagehide')();
  assert.equal(ui.timers.size, 0);
  ui.advance(91000);
  ui.pageEvents.get('pageshow')({ persisted: true });
  assert.equal(ui.element('#confirm-button').disabled, true);
  assert.equal(ui.timers.size, 0);
});

test('expiry while saving does not discard a successful server response', async () => {
  const ui = setup();
  await readyScan(ui);
  ui.element('#student-id').readOnly = true;
  ui.fire('#confirm-button', 'click');
  ui.advance(91000);
  [...ui.timers.values()][0]();
  ui.answer(ui.requests[1], { ok: true, transaction: { action: 'loan', equipment_name: 'meter', quantity: 1, available_qty: 2 } });
  await settle();
  assert.match(ui.element('#scan-message').textContent, /완료/);
  assert.equal(ui.element('#student-id').value, '30304');
  assert.equal(ui.timers.size, 0);
});

test('expired login clears recognition result and countdown', async () => {
  const ui = setup();
  await readyScan(ui);
  ui.fire('#confirm-button', 'click');
  ui.answer(ui.requests[1], { ok: false, code: 'login_required', error: '로그인 후 이용해 주세요.' }, false);
  await settle();
  assert.equal(ui.element('#confirm-button').disabled, true);
  assert.equal(ui.timers.size, 0);
});

test('loan reason is required before detection but return needs only a student', async () => {
  const ui = setup();
  ui.element('#student-id').value = '30304';
  await ui.fire('#detect-button', 'click');
  assert.equal(ui.requests.length, 0);
  assert.equal(ui.element('#scan-message').textContent, '대여 사유를 입력해 주세요.');
  ui.element('action').value = 'return';
  ui.fire('action', 'change');
  assert.equal(ui.element('#loan-reason').required, false);
  assert.equal(ui.element('#loan-reason').disabled, true);
  const detecting = ui.fire('#detect-button', 'click');
  assert.equal(ui.requests[0].body.action, 'return');
  assert.equal(ui.element('#student-id').disabled, true);
  ui.fire('#detect-button', 'click');
  assert.equal(ui.requests.length, 1);
  ui.answer(ui.requests[0], { ok: true, scan: { token: 'return-1', confidence: 0.9,
    equipment_name: '멀티미터', due_date: null, loan_period_days: 7 },
    votes: 3, frame_count: 3, duration_ms: 10 });
  await detecting;
  assert.equal(ui.element('#confirm-button').textContent, '이 기자재 반납하기');
  ui.fire('#confirm-button', 'click');
  assert.equal(ui.requests[1].url, '/api/transactions');
  assert.ok(!('station_pin' in ui.requests[1].body));
});

test('mock page does not offer manual equipment selection or start recognition', async () => {
  const ui = setup('mock');
  ui.element('#student-id').value = '30304';
  ui.element('#loan-reason').value = '실습';
  assert.equal(ui.element('#detect-button').disabled, true);
  await ui.fire('#detect-button', 'click');
  assert.equal(ui.requests.length, 0);
});

test('final confirmation submits only once without a PIN', async () => {
  const ui = setup();
  ui.element('#student-id').value = '30304';
  ui.element('#loan-reason').value = '수업 실습';
  const detecting = ui.fire('#detect-button', 'click');
  ui.answer(ui.requests[0], { ok: true, scan: { token: 'scan-developer', confidence: 0.99,
    equipment_name: 'meter', due_date: '2026-09-10', loan_period_days: 7 },
    votes: 5, frame_count: 5, duration_ms: 10 });
  await detecting;
  ui.fire('#confirm-button', 'click');
  ui.fire('#confirm-button', 'click');
  assert.equal(ui.requests.length, 2);
  assert.equal(ui.requests[1].url, '/api/transactions');
  assert.ok(!ui.requests[1].body.station_pin);
  assert.equal(ui.requests[1].body.quantity, 1);
  assert.equal(ui.requests[1].body.reason, '수업 실습');
  assert.ok(!('mock_equipment_id' in ui.requests[0].body));
  assert.equal(ui.element('#result-name').textContent, 'meter 기자재입니다.');
  ui.answer(ui.requests[1], { ok: true, transaction: { action: 'loan',
    equipment_name: 'meter', quantity: 1, available_qty: 2 } });
  await settle();
  assert.equal(ui.timers.size, 0);
  assert.equal(ui.element('#loan-reason').value, '');
  assert.equal(ui.element('#result-name').textContent, '');
  assert.equal(ui.element('#result-loan-period').textContent, '');
});

test('failed transactions can retry once and release timers on success', async () => {
  const ui = setup();
  ui.element('#student-id').value = '30304';
  ui.element('#loan-reason').value = '수업 실습';
  const detecting = ui.fire('#detect-button', 'click');
  ui.answer(ui.requests[0], { ok: true, scan: { token: 'scan-1', confidence: 0.99,
    equipment_name: 'meter', due_date: '2026-09-10', loan_period_days: 7 },
    votes: 5, frame_count: 5, duration_ms: 10 });
  await detecting;
  ui.fire('#confirm-button', 'click');
  ui.fire('#confirm-button', 'click');
  assert.equal(ui.requests.length, 2);
  ui.answer(ui.requests[1], { ok: false, error: 'temporary failure' }, false);
  await settle();
  assert.equal(ui.element('#confirm-button').disabled, false);
  ui.fire('#confirm-button', 'click');
  ui.answer(ui.requests[2], { ok: true, transaction: { action: 'loan',
    equipment_name: 'meter', quantity: 1, available_qty: 2 } });
  await settle();
  assert.equal(ui.timers.size, 0);
});

test('page exit and request timeout release pending scan timers and controls', async () => {
  for (const stop of ['pagehide', 'timeout']) {
    const ui = setup();
    ui.element('#student-id').value = '30304';
    ui.element('#loan-reason').value = '수업 실습';
    const detecting = ui.fire('#detect-button', 'click');
    if (stop === 'pagehide') ui.pageEvents.get('pagehide')();
    else [...ui.timers.values()][0]();
    await detecting;
    assert.equal(ui.timers.size, 0);
    assert.equal(ui.element('#detect-button').disabled, false);
  }
});

test('page exit immediately clears deadline and rejects a late scan after restore', async () => {
  const ui = setup('yolo', true, true);
  ui.element('#student-id').value = '30304';
  ui.element('#loan-reason').value = '실습';
  const detecting = ui.fire('#detect-button', 'click');
  ui.pageEvents.get('pagehide')();
  assert.equal(ui.timers.size, 0);
  ui.pageEvents.get('pageshow')({ persisted: true });
  ui.answer(ui.requests[0], { ok: true, scan: { token: 'stale', confidence: 0.9,
    equipment_name: 'old camera result', due_date: null }, votes: 1, frame_count: 1, duration_ms: 1 });
  await detecting;
  assert.equal(ui.element('#confirm-button').disabled, true);
  assert.equal(ui.element('#result-name').textContent, '');
  assert.equal(ui.timers.size, 0);
  await readyScan(ui);
  assert.equal(ui.element('#confirm-button').disabled, false);
});

test('repeated scan interruption releases deadline and re-enables detection', async () => {
  const ui = setup();
  ui.element('#student-id').value = '30304';
  ui.element('#loan-reason').value = '실습';
  for (let index = 0; index < 100; index++) {
    const detecting = ui.fire('#detect-button', 'click');
    assert.equal(ui.timers.size, 1);
    ui.pageEvents.get('pagehide')();
    assert.equal(ui.timers.size, 0);
    ui.pageEvents.get('pageshow')({ persisted: true });
    await detecting;
    assert.equal(ui.element('#detect-button').disabled, false);
    assert.equal(ui.element('#confirm-button').disabled, true);
  }
});
