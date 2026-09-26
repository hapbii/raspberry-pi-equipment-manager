const {test} = require('node:test');
const assert = require('node:assert/strict');
const {startPreview} = require('../scripts/capture_preview_assets/preview.js');
const settle = () => new Promise(resolve => setImmediate(resolve));

function setup() {
  const timers = new Map(), events = new Map(), elements = new Map(), requests = [];
  const blobs = new Set();
  let nextTimer = 0, nextBlob = 0;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      dataset: {token: 'secret', limit: '200'}, disabled: true,
      addEventListener(name, fn) { this[name] = fn; }, removeAttribute() {},
    });
    return elements.get(id);
  }
  const doc = {hidden: false, getElementById: element, addEventListener: (name, fn) => events.set(name, fn)};
  const env = {
    AbortController,
    addEventListener: (name, fn) => events.set(name, fn),
    setTimeout(fn) { timers.set(++nextTimer, fn); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
    URL: {createObjectURL() {const url = `blob:${++nextBlob}`; blobs.add(url); return url;},
      revokeObjectURL(url) {blobs.delete(url);}},
    fetch(url, options) { return new Promise((resolve, reject) => requests.push({url, options, resolve, reject})); },
  };
  startPreview(doc, env);
  return {timers, events, elements, requests, blobs, doc, element,
    tick() {const [id, fn] = timers.entries().next().value; timers.delete(id); fn();},
    answer(saved = 0, request = requests.at(-1)) {request.resolve({ok: true, headers: {get: () => String(saved)},
      blob: async () => 'jpeg', json: async () => ({saved, file: 'photo.jpg'})});},
  };
}

test('500 preview refreshes retain just one blob and one timer; no capture', async () => {
  const ui = setup();
  for (let i = 0; i < 500; i++) {
    ui.tick(); ui.answer(); await settle();
    assert.equal(ui.timers.size, 1);
    assert.equal(ui.blobs.size, 1);
    assert.equal(ui.requests.at(-1).url, '/frame.jpg');
  }
  ui.events.get('pagehide')();
  assert.equal(ui.blobs.size, 0);
  assert.equal(ui.timers.size, 0);
});

test('save waits for frame request and repeated clicks do not duplicate save', async () => {
  const ui = setup();
  ui.tick(); ui.answer(); await settle();
  ui.tick();
  ui.element('capture').click(); ui.element('capture').click();
  assert.equal(ui.requests.length, 2);
  ui.answer(); await settle(); ui.tick();
  assert.equal(ui.requests.at(-1).url, '/capture');
  assert.equal(ui.requests.at(-1).options.method, 'POST');
  ui.element('capture').click(); ui.answer(1); await settle();
  assert.equal(ui.element('saved').textContent, '1');
  ui.tick(); assert.equal(ui.requests.at(-1).url, '/frame.jpg');
});

test('hidden page pauses refresh and resumes without duplicate requests', async () => {
  const ui = setup();
  ui.tick();
  ui.doc.hidden = true; ui.events.get('visibilitychange')();
  ui.answer(); await settle(); assert.equal(ui.timers.size, 0);
  ui.doc.hidden = false;
  ui.events.get('visibilitychange')(); ui.events.get('visibilitychange')();
  assert.equal(ui.timers.size, 1);
  ui.tick(); assert.equal(ui.requests.length, 2);
});

test('failed save is never automatically repeated; maximum disables capture', async () => {
  const ui = setup();
  ui.tick(); ui.answer(); await settle();
  ui.element('capture').click(); ui.tick();
  ui.requests.at(-1).reject(new Error('lost connection')); await settle();
  assert.match(ui.element('status').textContent, /자동 재촬영하지/);
  ui.tick(); assert.equal(ui.requests.at(-1).url, '/frame.jpg');
  ui.answer(200); await settle(); assert.equal(ui.element('capture').disabled, true);
});

test('page close aborts request and late image does not retain a blob', async () => {
  const ui = setup(); ui.tick(); ui.events.get('pagehide')();
  assert.equal(ui.requests[0].options.signal.aborted, true);
  ui.answer(); await settle();
  assert.equal(ui.blobs.size, 0); assert.equal(ui.timers.size, 0);
  ui.events.get('pageshow')({persisted: true});
  assert.equal(ui.timers.size, 1);
});

test('leaving with a queued click never takes a photo automatically on restore', async () => {
  const ui = setup();
  ui.tick(); ui.answer(); await settle();
  ui.element('capture').click();
  ui.events.get('pagehide')();
  ui.events.get('pageshow')({persisted: true});
  ui.tick();
  assert.equal(ui.requests.at(-1).url, '/frame.jpg');
});

test('restoring before an old frame finishes does not display stale data', async () => {
  const ui = setup(); ui.tick();
  ui.events.get('pagehide')();
  ui.events.get('pageshow')({persisted: true});
  ui.answer(); await settle();
  assert.equal(ui.blobs.size, 0);
  assert.equal(ui.element('capture').disabled, true);
  assert.equal(ui.timers.size, 1);
  ui.tick(); ui.answer(); await settle();
  assert.equal(ui.blobs.size, 1);
  assert.equal(ui.element('capture').disabled, false);
});

test('hiding releases the displayed image and ignores an in-flight preview', async () => {
  const ui = setup(); ui.tick(); ui.answer(); await settle(); ui.tick();
  ui.doc.hidden = true; ui.events.get('visibilitychange')();
  assert.equal(ui.blobs.size, 0);
  assert.equal(ui.requests.at(-1).options.signal.aborted, true);
  ui.answer(); await settle();
  assert.equal(ui.blobs.size, 0);
  assert.equal(ui.timers.size, 0);
});

test('page close clears request deadline immediately without waiting for fetch', () => {
  const ui = setup(); ui.tick();
  ui.events.get('pagehide')();
  assert.equal(ui.timers.size, 0);
  assert.equal(ui.element('capture').disabled, true);
});

test('100 rapid page restore cycles never overlap requests or accumulate resources', async () => {
  const ui = setup(); ui.tick();
  for (let i = 0; i < 100; i++) {
    ui.events.get('pagehide')();
    ui.events.get('pageshow')({persisted: true});
    ui.events.get('pageshow')({persisted: true});
    assert.equal(ui.timers.size, 0); // Old request still owns the single slot.
    assert.equal(ui.blobs.size, 0);
    assert.equal(ui.requests.length, i + 1);
    ui.requests.at(-1).reject(new Error('aborted'));
    await settle();
    assert.equal(ui.timers.size, 1);
    ui.tick();
  }
  ui.answer(); await settle();
  assert.equal(ui.blobs.size, 1);
  assert.equal(ui.timers.size, 1);
  ui.events.get('pagehide')();
});

test('hiding while saving does not abort or retry the save', async () => {
  const ui = setup(); ui.tick(); ui.answer(); await settle();
  ui.element('capture').click(); ui.tick();
  const save = ui.requests.at(-1);
  ui.doc.hidden = true; ui.events.get('visibilitychange')();
  assert.equal(save.options.signal.aborted, false);
  ui.doc.hidden = false; ui.events.get('visibilitychange')();
  assert.equal(ui.element('capture').disabled, true);
  ui.answer(1); await settle(); ui.tick();
  assert.equal(ui.requests.at(-1).url, '/frame.jpg');
  ui.answer(1); await settle();
  assert.equal(ui.element('saved').textContent, '1');
  assert.equal(ui.requests.filter(r => r.url === '/capture').length, 1);
});

test('a decoded image arriving after page close never creates a blob URL', async () => {
  const ui = setup(); ui.tick();
  let finishBody;
  ui.requests.at(-1).resolve({ok: true, headers: {get: () => '0'},
    blob: () => new Promise(resolve => {finishBody = resolve;})});
  await settle();
  ui.events.get('pagehide')();
  ui.events.get('pageshow')({persisted: true});
  finishBody('late-image'); await settle();
  assert.equal(ui.blobs.size, 0);
  assert.equal(ui.element('capture').disabled, true);
});

test('request timeout does not retry a save and cleans the old deadline', async () => {
  const ui = setup(); ui.tick(); ui.answer(); await settle();
  ui.element('capture').click(); ui.tick();
  const save = ui.requests.at(-1);
  ui.tick(); // Request deadline.
  assert.equal(save.options.signal.aborted, true);
  save.reject(new Error('timeout')); await settle();
  assert.equal(ui.timers.size, 1);
  ui.tick(); assert.equal(ui.requests.at(-1).url, '/frame.jpg');
});
