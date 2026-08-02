/* Weaver-owned adapter around Docassemble's bundled CodeMirror 6 editor. */
(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverSourceEditor = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  function codeMirrorMode(language) {
    var mode = String(language || '').toLowerCase();
    if (mode === 'python') return 'py';
    if (mode === 'mako') return 'html';
    if (mode === 'plaintext') return 'text';
    return mode || 'yaml';
  }

  function positionOffset(documentValue, position) {
    if (typeof position === 'number') {
      return Math.max(0, Math.min(documentValue.length, position));
    }
    if (position && typeof position.offset === 'number') {
      return Math.max(0, Math.min(documentValue.length, position.offset));
    }
    if (position && typeof position.line === 'number') {
      var lineNumber = Math.max(1, Math.min(documentValue.lines, position.line));
      var line = documentValue.line(lineNumber);
      return Math.max(line.from, Math.min(line.to, line.from + (Number(position.column) || 0)));
    }
    return 0;
  }

  function createTextareaEditor(container, value, options) {
    var subscribers = [];
    var textarea = root.document.createElement('textarea');
    textarea.className = 'editor-yaml-textarea';
    textarea.value = String(value === undefined || value === null ? '' : value);
    textarea.setAttribute('aria-label', options.ariaLabel || 'Source editor');
    textarea.addEventListener('input', function () {
      subscribers.slice().forEach(function (callback) { callback(textarea.value); });
    });
    container.innerHTML = '';
    container.appendChild(textarea);
    return {
      getValue: function () { return textarea.value; },
      setValue: function (nextValue) {
        textarea.value = String(nextValue === undefined || nextValue === null ? '' : nextValue);
      },
      onChange: function (callback) {
        subscribers.push(callback);
        return { dispose: function () {
          subscribers = subscribers.filter(function (candidate) { return candidate !== callback; });
        } };
      },
      setDiagnostics: function (diagnostics) {
        if (diagnostics && diagnostics.length) container.setAttribute('aria-invalid', 'true');
        else container.removeAttribute('aria-invalid');
      },
      revealPosition: function (position) {
        var offset = positionOffset({
          length: textarea.value.length,
          lines: textarea.value.split('\n').length,
          line: function (number) {
            var lines = textarea.value.split('\n');
            var before = lines.slice(0, number - 1).join('\n');
            var from = number === 1 ? 0 : before.length + 1;
            return { from: from, to: from + lines[number - 1].length };
          },
        }, position);
        textarea.setSelectionRange(offset, offset);
        textarea.focus();
      },
      setReadOnly: function (readOnly) { textarea.readOnly = Boolean(readOnly); },
      focus: function () { textarea.focus(); },
      dispose: function () { subscribers = []; textarea.remove(); },
    };
  }

  function createSourceEditor(container, value, language, options) {
    options = options || {};
    if (!container) throw new Error('A source editor container is required.');
    if (typeof root.daNewEditor !== 'function') {
      return createTextareaEditor(container, value, options);
    }

    if (!Array.isArray(root.daAutoComp)) root.daAutoComp = [];
    container.innerHTML = '';
    var bundle = root.daNewEditor(
      container,
      String(value === undefined || value === null ? '' : value),
      codeMirrorMode(language),
      'default',
      true
    );
    if (!bundle || !bundle.ev) throw new Error('Docassemble did not create a CodeMirror editor.');

    var view = bundle.ev;
    var subscribers = [];
    var originalDispatch = view.dispatch.bind(view);
    view.dispatch = function () {
      var before = view.state.doc.toString();
      originalDispatch.apply(view, arguments);
      var after = view.state.doc.toString();
      if (after !== before) {
        subscribers.slice().forEach(function (callback) { callback(after); });
      }
    };
    if (view.contentDOM && typeof view.contentDOM.setAttribute === 'function') {
      view.contentDOM.setAttribute('aria-label', options.ariaLabel || 'Source editor');
      view.contentDOM.setAttribute('aria-multiline', 'true');
    }

    return {
      getValue: function () { return view.state.doc.toString(); },
      setValue: function (nextValue) {
        view.dispatch({
          changes: {
            from: 0,
            to: view.state.doc.length,
            insert: String(nextValue === undefined || nextValue === null ? '' : nextValue),
          },
        });
      },
      onChange: function (callback) {
        subscribers.push(callback);
        return { dispose: function () {
          subscribers = subscribers.filter(function (candidate) { return candidate !== callback; });
        } };
      },
      setDiagnostics: function (diagnostics) {
        if (diagnostics && diagnostics.length) container.setAttribute('aria-invalid', 'true');
        else container.removeAttribute('aria-invalid');
      },
      revealPosition: function (position) {
        var offset = positionOffset(view.state.doc, position);
        view.dispatch({
          selection: { anchor: offset },
          scrollIntoView: true,
        });
      },
      setReadOnly: function (readOnly) {
        if (readOnly) bundle.disable();
        else bundle.enable();
      },
      focus: function () { view.focus(); },
      dispose: function () {
        subscribers = [];
        view.destroy();
      },
    };
  }

  return {
    createSourceEditor: createSourceEditor,
  };
});
