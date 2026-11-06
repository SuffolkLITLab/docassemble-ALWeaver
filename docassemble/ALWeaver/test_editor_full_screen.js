'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const start = source.indexOf('  function attachFullScreenToggle(');
const buttons = [];
const toolbar = { appendChild: (button) => buttons.push(button) };
const classes = new Set();
let keydown;
let measures = 0;
let focuses = 0;
let updates = 0;
const wrapper = {
  querySelector: (selector) => {
    assert.equal(selector, '.editor-source-tools');
    return toolbar;
  },
  appendChild: (button) => buttons.push(button),
  classList: {
    toggle: (name) => {
      if (classes.has(name)) classes.delete(name);
      else classes.add(name);
      return classes.has(name);
    },
  },
  addEventListener: (event, callback, capture) => {
    assert.equal(event, 'keydown');
    assert.equal(capture, true);
    keydown = callback;
  },
};
const context = vm.createContext({
  document: {
    createElement: (tag) => {
      assert.equal(tag, 'button');
      return {
        addEventListener: function (event, callback) {
          assert.equal(event, 'click');
          this.click = callback;
        },
      };
    },
  },
});
vm.runInContext(
  source.slice(start, source.indexOf('\n  }\n', start) + 5),
  context,
);
context.attachFullScreenToggle(
  wrapper,
  {
    requestMeasure: () => measures++,
    focus: () => focuses++,
  },
  () => updates++,
);
const [enter, exit] = buttons;
assert.equal(enter.type, 'button');
assert.equal(enter.textContent, 'Full screen');
assert.equal(exit.textContent, 'Exit full screen (F11)');
enter.click();
assert.ok(classes.has('editor-source-full-screen'));
exit.click();
assert.ok(!classes.has('editor-source-full-screen'));
let prevented = 0;
let stopped = 0;
const event = {
  key: 'F11',
  preventDefault: () => prevented++,
  stopPropagation: () => stopped++,
};
keydown(event);
assert.ok(classes.has('editor-source-full-screen'));
exit.click();
keydown({ ...event, ctrlKey: true });
keydown({ ...event, key: 'Enter' });
assert.ok(!classes.has('editor-source-full-screen'));
assert.equal(prevented, 1);
assert.equal(stopped, 1);
assert.equal(measures, 4);
assert.equal(updates, 4);
assert.equal(focuses, 4);

const css = fs.readFileSync(`${__dirname}/data/static/editor.css`, 'utf8');
assert.match(
  css,
  /\.editor-source-full-screen \.editor-source-enter-full-screen\s*\{ display: none; \}/,
);
console.log('Full-screen pointer controls and F11 passed');
