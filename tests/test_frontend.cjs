const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

function setup(pinRequired = true, mode = 'yolo') {
  const elements = new Map();
  const timers = new Map();
  const pageEvents = new Map();
  const requests = [];
  let timerId = 0;
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        value: '', disabled: false, open: false,
        dataset: { pinRequired: String(pinRequired), mode }, events: new Map(),
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
    AbortController, Intl, Date, Number, Set,
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
      addEventListener(name, fn) { pageEvents.set(name, fn); },
      setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
      clearTimeout(id) { timers.delete(id); },
    },
    fetch(url, options) {
      return new Promise((resolve, reject) => {
        const request = { url, body: JSON.parse(options.body), resolve };
        requests.push(request);
        options.signal.addEventListener('abort', () => {
          const error = new Error('aborted');
          error.name = 'AbortError';
          reject(error);
        }, { once: true });
      });
    },
  };
  vm.runInNewContext(readFileSync(join(__dirname, '../equipment_manager/static/app.js'), 'utf8'), context);
  const fire = (id, name) => element(id).events.get(name)({ preventDefault() {} });
  const answer = (request, data, ok = true) => request.resolve({ ok, json: async () => data });
  return { element, timers, requests, fire, answer, pageEvents };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

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
  assert.equal(ui.element('#station-pin-dialog').open, true);
});

test('mock page does not offer manual equipment selection or start recognition', async () => {
  const ui = setup(true, 'mock');
  ui.element('#student-id').value = '30304';
  ui.element('#loan-reason').value = '실습';
  assert.equal(ui.element('#detect-button').disabled, true);
  await ui.fire('#detect-button', 'click');
  assert.equal(ui.requests.length, 0);
});

test('developer final confirmation skips the PIN dialog and submits only once', async () => {
  const ui = setup(false);
  ui.element('#student-id').value = '30304';
  ui.element('#loan-reason').value = '수업 실습';
  const detecting = ui.fire('#detect-button', 'click');
  ui.answer(ui.requests[0], { ok: true, scan: { token: 'scan-developer', confidence: 0.99,
    equipment_name: 'meter', due_date: '2026-09-10', loan_period_days: 7 },
    votes: 5, frame_count: 5, duration_ms: 10 });
  await detecting;
  ui.fire('#confirm-button', 'click');
  ui.fire('#confirm-button', 'click');
  assert.equal(ui.element('#station-pin-dialog').open, false);
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
});

test('PIN retries send one transaction at a time and release request timers', async () => {
  const ui = setup();
  ui.element('#student-id').value = '30304';
  ui.element('#loan-reason').value = '수업 실습';
  const detecting = ui.fire('#detect-button', 'click');
  ui.answer(ui.requests[0], { ok: true, scan: { token: 'scan-1', confidence: 0.99,
    equipment_name: 'meter', due_date: '2026-09-10', loan_period_days: 7 },
    votes: 5, frame_count: 5, duration_ms: 10 });
  await detecting;
  ui.fire('#confirm-button', 'click');
  assert.equal(ui.element('#station-pin-dialog').open, true);
  ui.element('#transaction-station-pin').value = 'wrong';
  ui.fire('#station-pin-form', 'submit');
  ui.fire('#station-pin-form', 'submit');
  assert.equal(ui.requests.length, 2);
  assert.equal(ui.element('#transaction-station-pin').value, '');
  ui.answer(ui.requests[1], { ok: false, code: 'station_pin_invalid', error: 'wrong PIN' }, false);
  await settle();
  assert.equal(ui.element('#station-pin-dialog').open, true);
  assert.equal(ui.element('#station-pin-confirm').disabled, false);
  ui.element('#transaction-station-pin').value = '2468';
  ui.fire('#station-pin-form', 'submit');
  ui.answer(ui.requests[2], { ok: true, transaction: { action: 'loan',
    equipment_name: 'meter', quantity: 1, available_qty: 2 } });
  await settle();
  assert.equal(ui.element('#station-pin-dialog').open, false);
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
