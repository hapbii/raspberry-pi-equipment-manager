const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

test('poweroff policy grants only the selected user starting the fixed timer', () => {
  let rule;
  vm.runInNewContext(readFileSync(join(__dirname, '../deploy/50-equipment-manager-poweroff.rules'), 'utf8')
    .replace('__USER__', 'pi30304'), { polkit: { addRule: fn => { rule = fn; }, Result: { YES: 'yes' } } });
  const check = (user, id, unit, verb) => rule({ id, lookup: key => ({ unit, verb })[key] }, { user });
  const action = 'org.freedesktop.systemd1.manage-units';
  const timer = 'equipment-manager-poweroff.timer';
  assert.equal(check('pi30304', action, timer, 'start'), 'yes');
  for (const user of ['other', 'teacher', 'developer', 'root']) {
    assert.equal(check(user, action, timer, 'start'), undefined);
  }
  for (const unit of ['ssh.service', 'equipment-manager-poweroff.service', 'poweroff.target', undefined]) {
    assert.equal(check('pi30304', action, unit, 'start'), undefined);
  }
  for (const verb of ['stop', 'restart', 'enable', 'set-property', undefined]) {
    assert.equal(check('pi30304', action, timer, verb), undefined);
  }
  assert.equal(check('pi30304', 'org.freedesktop.systemd1.manage-unit-files', timer, 'start'), undefined);
});
