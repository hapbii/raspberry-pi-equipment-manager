const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

function setup({ delayed = false } = {}) {
  const field = initial => {
    let value = String(initial);
    return { get value() { return value; }, set value(next) { value = String(next); } };
  };
  const events = new Map();
  const selected = { checked: false };
  const row = {
    dataset: { equipmentId: '5', original: JSON.stringify({ id: 5, total_qty: 9,
      available_qty: 8, loaned_qty: 1, loan_period_days: 7, updated_at: 'old' }) },
    elements: { total_qty: field(9), available_qty: field(8), loan_period_days: field(7) },
    classList: { toggle() {}, contains() { return false; } },
    addEventListener(name, fn) { events.set(name, fn); },
    querySelector(selector) { return selector === '.equipment-select' ? selected : { removeAttribute() {} }; },
    reportValidity() { return true; },
  };
  const nodes = new Map();
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, { addEventListener() {}, content: 'csrf' });
    return nodes.get(selector);
  };
  const editor = {
    dataset: { endpoint: '/api/admin/equipment/batch' },
    querySelector: node,
    querySelectorAll: selector => selector === '.inventory-edit' ? [row] : [],
  };
  let payload, answer;
  const timers = new Map();
  const pageEvents = new Map();
  const context = {
    document: { querySelector: selector => selector === '#equipment-editor' ? editor : node(selector) },
    window: {
      addEventListener(name, fn) { pageEvents.set(name, fn); },
      setTimeout(fn) { timers.set(1, fn); return 1; },
      clearTimeout(id) { timers.delete(id); },
    },
    AbortController,
    async fetch(url, options) {
      payload = JSON.parse(options.body);
      if (delayed) await new Promise(resolve => { answer = resolve; });
      return { ok: true, json: async () => ({ ok: true, items: [{ ...payload.items[0], loaned_qty: 1, updated_at: 'new' }] }) };
    },
  };
  vm.runInNewContext(readFileSync(join(__dirname, '../equipment_manager/static/equipment_editor.js'), 'utf8'), context);
  return { row, events, timers, pageEvents, node, get payload() { return payload; }, answer: () => answer() };
}

test('total edits preserve real loans, including after an asynchronous batch save', async () => {
  const ui = setup();
  const { row, events } = ui;
  row.elements.total_qty.value = 10;
  events.get('input')({ target: row.elements.total_qty });
  assert.equal(row.elements.available_qty.value, '9');
  events.get('submit')({ preventDefault() {}, submitter: { dataset: { rowAction: 'update' } } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.payload.items[0].total_qty, 10);
  assert.equal(ui.payload.items[0].available_qty, 9);
  row.elements.total_qty.value = 11;
  events.get('input')({ target: row.elements.total_qty });
  assert.equal(row.elements.available_qty.value, '10');
});

test('leaving a batch edit releases timeout and does not adopt a late response', async () => {
  const ui = setup({ delayed: true });
  const original = ui.row.dataset.original;
  ui.row.elements.total_qty.value = 10;
  ui.events.get('submit')({ preventDefault() {}, submitter: { dataset: { rowAction: 'update' } } });
  assert.equal(ui.timers.size, 1);
  ui.pageEvents.get('pagehide')();
  assert.equal(ui.timers.size, 0);
  ui.answer();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.row.dataset.original, original);
  assert.equal(ui.row.elements.total_qty.value, '10');
  assert.match(ui.node('#equipment-edit-message').textContent, /반영 여부/);
  assert.equal(ui.timers.size, 0);
});
