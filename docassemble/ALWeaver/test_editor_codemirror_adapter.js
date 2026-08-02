'use strict';

const assert = require('assert');

function makeDocument(value) {
  return {
    length: value.length,
    lines: value.split('\n').length,
    toString: () => value,
    line(number) {
      const lines = value.split('\n');
      const before = lines.slice(0, number - 1).join('\n');
      const from = number === 1 ? 0 : before.length + 1;
      return { from, to: from + lines[number - 1].length };
    },
  };
}

function run() {
  const calls = { disable: 0, enable: 0, focus: 0, destroy: 0 };
  let created;
  global.window = global;
  global.daNewEditor = (parent, contents, mode, keymapping, lineWrapping) => {
    let value = contents;
    const view = {
      state: { doc: makeDocument(value) },
      contentDOM: { setAttribute() {} },
      dispatch(spec) {
        if (spec.changes) {
          value = String(spec.changes.insert);
          this.state = { doc: makeDocument(value) };
        }
        this.lastDispatch = spec;
      },
      focus() { calls.focus += 1; },
      destroy() { calls.destroy += 1; },
    };
    created = { parent, contents, mode, keymapping, lineWrapping, view };
    return {
      ev: view,
      disable() { calls.disable += 1; },
      enable() { calls.enable += 1; },
    };
  };

  const adapterApi = require('./data/static/editor_source_adapter.js');
  const attributes = {};
  const container = {
    innerHTML: 'old',
    setAttribute(name, value) { attributes[name] = value; },
    removeAttribute(name) { delete attributes[name]; },
  };
  const editor = adapterApi.createSourceEditor(container, 'first', 'python', {
    ariaLabel: 'Python source',
  });
  assert.strictEqual(created.mode, 'py');
  assert.strictEqual(created.keymapping, 'default');
  assert.strictEqual(created.lineWrapping, true);
  assert.strictEqual(editor.getValue(), 'first');

  let observed = null;
  const disposable = editor.onChange((value) => { observed = value; });
  editor.setValue('second');
  assert.strictEqual(editor.getValue(), 'second');
  assert.strictEqual(observed, 'second');
  disposable.dispose();

  editor.revealPosition({ line: 1, column: 2 });
  assert.strictEqual(created.view.lastDispatch.selection.anchor, 2);
  assert.strictEqual(created.view.lastDispatch.scrollIntoView, true);
  editor.setReadOnly(true);
  editor.setReadOnly(false);
  assert.deepStrictEqual([calls.disable, calls.enable], [1, 1]);
  editor.setDiagnostics([{ severity: 'error', message: 'Invalid YAML' }]);
  assert.strictEqual(attributes['aria-invalid'], 'true');
  editor.setDiagnostics([]);
  assert.strictEqual(attributes['aria-invalid'], undefined);
  editor.focus();
  editor.dispose();
  assert.deepStrictEqual([calls.focus, calls.destroy], [1, 1]);

  delete global.daNewEditor;
  let inputListener = null;
  const fallbackTextarea = {
    value: '',
    className: '',
    readOnly: false,
    setAttribute() {},
    addEventListener(name, callback) {
      if (name === 'input') inputListener = callback;
    },
    setSelectionRange(from, to) { this.selection = [from, to]; },
    focus() { this.focused = true; },
    remove() { this.removed = true; },
  };
  global.document = {
    createElement(tagName) {
      assert.strictEqual(tagName, 'textarea');
      return fallbackTextarea;
    },
  };
  const fallbackContainer = {
    innerHTML: 'old',
    appendChild(child) { this.child = child; },
    setAttribute(name, value) { this[name] = value; },
    removeAttribute(name) { delete this[name]; },
  };
  const fallback = adapterApi.createSourceEditor(
    fallbackContainer,
    'fallback',
    'yaml',
    { ariaLabel: 'YAML source' }
  );
  assert.strictEqual(fallbackContainer.child, fallbackTextarea);
  assert.strictEqual(fallback.getValue(), 'fallback');
  let fallbackObserved = null;
  fallback.onChange((value) => { fallbackObserved = value; });
  fallbackTextarea.value = 'edited';
  inputListener();
  assert.strictEqual(fallbackObserved, 'edited');
  fallback.setReadOnly(true);
  assert.strictEqual(fallbackTextarea.readOnly, true);
  fallback.dispose();
  assert.strictEqual(fallbackTextarea.removed, true);
}

run();
