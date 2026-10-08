/* Graphical string editors. YAML serialization continues to read the textarea. */
(function (root) {
  'use strict';

  // Deliberately lexical: recognize common Mako forms without evaluating Python.
  // Brace nesting and quoted strings keep dictionaries and literal '}' intact.
  function makoRanges(text) {
    var ranges = [];
    var directives = new Set(
      'if elif else endif for endfor while endwhile try except finally endtry with endwith def enddef return include'.split(
        ' ',
      ),
    );
    var opener = /\$\{|<\/?%(?=([a-z]+))|<%|^[ \t]*%[ \t]*([a-z]+)\b/gm;
    var match;
    while ((match = opener.exec(text))) {
      if (match[2] && !directives.has(match[2])) continue;
      var start = match.index;
      var end;
      if (match[0] === '${') {
        var depth = 1;
        var quote = '';
        end = opener.lastIndex;
        while (end < text.length && depth) {
          var ch = text[end++];
          if (quote) {
            if (ch === '\\') end = Math.min(end + 1, text.length);
            else if (ch === quote) quote = '';
          } else if (ch === '"' || ch === "'") quote = ch;
          else if (ch === '{') depth++;
          else if (ch === '}') depth--;
        }
      } else if (match[1]) {
        // Tags like <%def name="x()">, </%def> and <%include file="a"/> end
        // at the first unquoted '>'.
        end = tagEnd(text, opener.lastIndex);
        if (match[0] === '<%' && match[1] === 'text') {
          // <%text> content is literal, so only its closing tag is Mako.
          ranges.push({ from: start, to: end });
          start = text.indexOf('</%text', end);
          if (start < 0) {
            opener.lastIndex = text.length;
            continue;
          }
          end = tagEnd(text, start + 2);
        }
      } else if (match[0] === '<%') {
        end = text.indexOf('%>', opener.lastIndex);
        end = end < 0 ? text.length : end + 2;
      } else {
        end = text.indexOf('\n', opener.lastIndex);
        if (end < 0) end = text.length;
      }
      ranges.push({ from: start, to: end });
      opener.lastIndex = end;
    }
    return ranges;
  }

  function tagEnd(text, from) {
    var quote = '';
    for (var i = from; i < text.length; i++) {
      var ch = text[i];
      if (quote) {
        if (ch === quote) quote = '';
      } else if (ch === '"' || ch === "'") quote = ch;
      else if (ch === '>') return i + 1;
    }
    return text.length;
  }

  var editors = new Map();
  var inputsByHost = new WeakMap();
  var hosts = new WeakMap();
  var highlight;

  // Returns whether the input is now shown as a graphical editor, so callers
  // can fall back to plain-textarea behavior when the CM6 bundle is missing.
  function enhance(input) {
    if (!input || input.tagName !== 'TEXTAREA') return false;
    if (editors.has(input)) return true;
    if (input.disabled || input.readOnly) return false;
    if (typeof root.daNewEditor !== 'function') return false;
    // The bundle's completion source reads this list unconditionally.
    if (!Array.isArray(root.daAutoComp)) root.daAutoComp = [];
    var doc = input.ownerDocument;
    var host = doc.createElement('div');
    host.className = 'editor-markdown';
    input.after(host);
    hosts.set(input, host);
    inputsByHost.set(host, input);
    var previousFocus = doc.activeElement;
    var bundle = root.daNewEditor(host, input.value, 'md', 'default', true);
    var view = bundle.ev;
    var originalFocus = input.focus;
    var disposed = false;
    var syncing = false;
    var frame;
    var painted = [];
    var tokenDoc;
    var tokens = [];
    var error = doc.createElement('div');
    error.className = 'text-danger small';
    error.setAttribute('role', 'alert');
    error.hidden = true;
    host.appendChild(error);
    var label = input.labels && input.labels[0];
    // Name the editor exactly as the textarea is named; an unnamed textarea
    // stays unnamed so accessibility checks still report it.
    if (input.getAttribute('aria-label'))
      view.contentDOM.setAttribute(
        'aria-label',
        input.getAttribute('aria-label'),
      );
    else if (input.getAttribute('aria-labelledby'))
      view.contentDOM.setAttribute(
        'aria-labelledby',
        input.getAttribute('aria-labelledby'),
      );
    else if (label) {
      if (!label.id) label.id = (input.id || 'weaver-markdown') + '-label';
      view.contentDOM.setAttribute('aria-labelledby', label.id);
    }
    view.contentDOM.setAttribute('aria-multiline', 'true');
    view.contentDOM.setAttribute('tabindex', '0');
    view.contentDOM.setAttribute('aria-required', String(input.required));
    if (input.getAttribute('aria-describedby'))
      view.contentDOM.setAttribute(
        'aria-describedby',
        input.getAttribute('aria-describedby'),
      );

    // CSS Highlights color DOM ranges without mutating CodeMirror's DOM or
    // importing a second, incompatible copy of CodeMirror's state classes.
    function paint() {
      if (disposed || !root.CSS || !root.CSS.highlights || !root.Highlight)
        return;
      if (!highlight) {
        highlight = new root.Highlight();
        root.CSS.highlights.set('weaver-mako', highlight);
      }
      painted.forEach(function (range) {
        highlight.delete(range);
      });
      painted = [];
      if (tokenDoc !== view.state.doc) {
        tokenDoc = view.state.doc;
        tokens = makoRanges(tokenDoc.toString());
      }
      tokens.forEach(function (token) {
        view.visibleRanges.forEach(function (visible) {
          var from = Math.max(token.from, visible.from);
          var to = Math.min(token.to, visible.to);
          if (from >= to) return;
          var start = view.domAtPos(from, 1);
          var end = view.domAtPos(to, -1);
          var range = doc.createRange();
          range.setStart(start.node, start.offset);
          range.setEnd(end.node, end.offset);
          highlight.add(range);
          painted.push(range);
        });
      });
    }

    function update(change) {
      var selection = view.state.selection.main;
      if (change.docChanged && !syncing) {
        input.value = view.state.doc.toString();
      }
      input.setSelectionRange(selection.from, selection.to);
      if (change.docChanged && !syncing) {
        syncing = true;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        syncing = false;
      }
      // Cursor movement leaves the text and its DOM in place; repaint only
      // when the text, the visible part, or a painted text node changed.
      if (
        change.docChanged ||
        change.viewportChanged ||
        painted.some(function (range) {
          return range.collapsed || !range.startContainer.isConnected;
        })
      ) {
        root.cancelAnimationFrame(frame);
        frame = root.requestAnimationFrame(paint);
      }
    }
    // The bundle's public compartment accepts extensions from its own View.
    view.dispatch({
      effects: bundle.compartment.reconfigure(
        view.constructor.updateListener.of(update),
      ),
    });

    function updateValidity() {
      if (disposed) return;
      if (input.validity.valid) {
        error.hidden = true;
        view.contentDOM.removeAttribute('aria-invalid');
      }
      view.contentDOM.setAttribute('aria-required', String(input.required));
    }
    function readInput() {
      // The delegated question handler clears custom validity after this listener.
      root.queueMicrotask(updateValidity);
      if (syncing) return;
      var before = view.state.doc.toString();
      var after = input.value;
      if (before === after) return;
      // A minimal change preserves undo history and the surrounding selection.
      var from = 0;
      while (
        from < before.length &&
        from < after.length &&
        before[from] === after[from]
      )
        from++;
      var oldEnd = before.length;
      var newEnd = after.length;
      while (
        oldEnd > from &&
        newEnd > from &&
        before[oldEnd - 1] === after[newEnd - 1]
      ) {
        oldEnd--;
        newEnd--;
      }
      syncing = true;
      view.dispatch({
        changes: { from: from, to: oldEnd, insert: after.slice(from, newEnd) },
        selection: { anchor: input.selectionStart, head: input.selectionEnd },
        scrollIntoView: true,
      });
      syncing = false;
    }
    function focus() {
      view.focus();
    }
    function invalid(event) {
      event.preventDefault();
      error.textContent = input.validationMessage;
      error.hidden = false;
      view.contentDOM.setAttribute('aria-invalid', 'true');
      view.focus();
    }
    function contextMenu(event) {
      if (!input.matches('[data-label-field="true"]')) return;
      event.preventDefault();
      input.dispatchEvent(
        new MouseEvent('contextmenu', { bubbles: true, cancelable: true }),
      );
    }
    // Toggling `required` (e.g. "Leave this question label blank") fires no
    // input event, so watch the attribute to clear a stale error.
    var requiredObserver = new root.MutationObserver(updateValidity);
    requiredObserver.observe(input, {
      attributes: true,
      attributeFilter: ['required'],
    });
    input.addEventListener('input', readInput);
    input.addEventListener('invalid', invalid);
    host.addEventListener('contextmenu', contextMenu);
    // Form fields must allow Tab / Shift+Tab to reach the next control.
    host.addEventListener(
      'keydown',
      function (event) {
        if (event.key === 'Tab') event.stopPropagation();
      },
      true,
    );
    if (label) label.addEventListener('click', focus);
    input.focus = focus;
    input.hidden = true;
    input.classList.add('editor-markdown-original');
    editors.set(input, function () {
      disposed = true;
      root.cancelAnimationFrame(frame);
      painted.forEach(function (range) {
        highlight.delete(range);
      });
      requiredObserver.disconnect();
      input.removeEventListener('input', readInput);
      input.removeEventListener('invalid', invalid);
      if (label) label.removeEventListener('click', focus);
      input.focus = originalFocus;
      input.hidden = false;
      input.classList.remove('editor-markdown-original');
      view.destroy();
      host.remove();
      editors.delete(input);
      hosts.delete(input);
      inputsByHost.delete(host);
    });
    // daNewEditor focuses every new instance; mounting must not move focus.
    if (previousFocus && previousFocus !== doc.body) previousFocus.focus();
    else view.contentDOM.blur();
    frame = root.requestAnimationFrame(paint);
    return true;
  }

  // Editors whose textarea already left the page are destroyed too, whatever
  // removed it, so their views are never kept alive.
  function dispose(container) {
    editors.forEach(function (destroy, input) {
      if (!container || !input.isConnected || container.contains(input))
        destroy();
    });
  }

  var api = {
    control: function (input) {
      return hosts.get(input) || input;
    },
    // The textarea an event inside a graphical editor belongs to.
    source: function (element) {
      var host =
        element && element.closest && element.closest('.editor-markdown');
      return (host && inputsByHost.get(host)) || element;
    },
    enhance: enhance,
    dispose: dispose,
    makoRanges: makoRanges,
  };
  root.WeaverMarkdown = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window === 'object' ? window : globalThis);
