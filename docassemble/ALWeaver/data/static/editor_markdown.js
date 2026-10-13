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
    var tags = new Set(
      'def block call page include namespace inherit text doc'.split(' '),
    );
    var opener = /\$\{|<\/?%|^[ \t]*(%|##)/gm;
    var tagName = /([a-z]+)\b/y;
    var directiveName = /[ \t]*([a-z]+)\b/y;
    var match;
    while ((match = opener.exec(text))) {
      if (match[1] === '##') {
        var commentEnd = text.indexOf('\n', opener.lastIndex);
        opener.lastIndex = commentEnd < 0 ? text.length : commentEnd;
        continue;
      }
      var word = match[1] === '%' ? directiveName : tagName;
      word.lastIndex = opener.lastIndex;
      var nameMatch = word.exec(text);
      var name = nameMatch && nameMatch[1];
      if (match[1] === '%' && !directives.has(name)) continue;
      var start = match.index;
      var end;
      if (match[0] === '${') {
        var substitution = substitutionRange(text, start);
        ranges.push(substitution);
        opener.lastIndex = substitution.to;
        continue;
      } else if (tags.has(name)) {
        // Tags like <%def name="x()">, </%def> and <%include file="a"/> end
        // at the first unquoted '>'.
        end = tagEnd(text, opener.lastIndex);
        if (match[0] === '<%' && ['text', 'doc'].includes(name)) {
          // Never discover substitutions inside literal or comment regions.
          if (name === 'text') ranges.push({ from: start, to: end });
          var closing = new RegExp('</%' + name + '\\s*>', 'g');
          closing.lastIndex = end;
          var closeMatch = closing.exec(text);
          if (!closeMatch) {
            opener.lastIndex = text.length;
            continue;
          }
          start = closeMatch.index;
          end = closing.lastIndex;
          if (name === 'doc') {
            opener.lastIndex = end;
            continue;
          }
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

  function substitutionRange(text, start) {
    var stack = ['}'];
    var quote = '';
    var filtered = false;
    var pairs = { '(': ')', '[': ']', '{': '}' };
    var i = start + 1;
    while (++i < text.length) {
      var ch = text[i];
      if (quote) {
        if (ch === '\\') i++;
        else if (text.startsWith(quote, i)) {
          i += quote.length - 1;
          quote = '';
        }
        continue;
      }
      if (text.startsWith('${', i)) break;
      if (ch === '"' || ch === "'") {
        quote = text.startsWith(ch.repeat(3), i) ? ch.repeat(3) : ch;
        i += quote.length - 1;
      } else if (ch === '#') {
        var newline = text.indexOf('\n', i);
        if (newline < 0) break;
        i = newline;
      } else if (pairs[ch]) stack.push(pairs[ch]);
      else if (')]}'.includes(ch)) {
        if (stack.pop() !== ch) break;
        if (!stack.length) {
          var inner = text.slice(start + 2, i);
          var from = start + 2 + inner.length - inner.trimStart().length;
          return {
            from: start,
            to: i + 1,
            expressionFrom: from,
            expressionTo: Math.max(
              from,
              i - (inner.length - inner.trimEnd().length),
            ),
            editable: !filtered,
          };
        }
      } else if (ch === '|' && stack.length === 1) filtered = true;
    }
    // With no unambiguous closing delimiter, select only the opener. Never
    // guess that neighboring prose (or the next token) belongs to this token.
    return { from: start, to: start + 2 };
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
  var expressionEditor;
  var activePopover;
  var rangeCache = new WeakMap();
  var hintSerial = 0;

  function rangesFor(document) {
    if (!rangeCache.has(document))
      rangeCache.set(document, makoRanges(document.toString()));
    return rangeCache.get(document);
  }

  function dismissPopover() {
    if (activePopover) activePopover();
  }

  function contextualActions(input, host, view, isDisposed) {
    var doc = input.ownerDocument;
    var popover;
    var current;
    var revision = 0;
    var timer;
    var frame;
    var pointerDown = false;
    var actionPointerDown = false;
    var suppressed = false;
    var modal = false;
    var cachedDoc;
    var ranges = [];
    function editable() {
      return (
        !isDisposed() && input.isConnected && !input.disabled && !input.readOnly
      );
    }
    function hide() {
      root.clearTimeout(timer);
      var previous = popover;
      popover = null;
      current = null;
      if (activePopover === hide) activePopover = null;
      if (previous) previous.remove();
    }
    function tokenAt(pos) {
      if (cachedDoc !== view.state.doc) {
        cachedDoc = view.state.doc;
        ranges = rangesFor(cachedDoc);
      }
      return ranges.find(function (token) {
        return token.from <= pos && pos < token.to;
      });
    }
    function position() {
      if (!popover || !current) return;
      var anchor = view.coordsAtPos(current.anchor);
      var bounds = host.getBoundingClientRect();
      if (!anchor || anchor.bottom < bounds.top || anchor.top > bounds.bottom) {
        hide();
        return;
      }
      var viewport = root.visualViewport;
      var left = viewport ? viewport.offsetLeft : 0;
      var top = viewport ? viewport.offsetTop : 0;
      var width = viewport ? viewport.width : root.innerWidth;
      var height = viewport ? viewport.height : root.innerHeight;
      if (
        anchor.bottom < top ||
        anchor.top > top + height ||
        anchor.right < left ||
        anchor.left > left + width
      ) {
        hide();
        return;
      }
      popover.style.maxWidth = Math.max(100, width - 16) + 'px';
      var rect = popover.getBoundingClientRect();
      popover.style.left =
        Math.max(
          left + 8,
          Math.min(anchor.left, left + width - rect.width - 8),
        ) + 'px';
      popover.style.top =
        Math.max(
          top + 8,
          Math.min(anchor.bottom + 4, top + height - rect.height - 8),
        ) + 'px';
    }
    function select(from, to) {
      if (!editable()) return;
      suppressed = true;
      view.dispatch({
        selection: { anchor: from, head: to },
        scrollIntoView: true,
        userEvent: 'select.expression',
      });
      view.focus();
    }
    function activate() {
      var target = current;
      var original = input.value;
      var originalDoc = view.state.doc;
      var originalRevision = revision;
      var originalSelection = view.state.selection.main;
      hide();
      if (!target || !editable()) return;
      if (original !== originalDoc.toString()) {
        // A programmatic value update without an input event has not reached
        // CodeMirror yet. Synchronize it, then let the author reopen the token.
        input.dispatchEvent(new Event('input', { bubbles: true }));
        view.focus();
        return;
      }
      if (!target.token.editable) {
        select(target.token.from, target.token.to);
        return;
      }
      var token = target.token;
      var from = token.expressionFrom;
      var to = token.expressionTo;
      var returnRevision = originalRevision;
      var returnValue = original;
      function checkTarget() {
        if (
          !editable() ||
          revision !== originalRevision ||
          view.state.doc !== originalDoc ||
          input.value !== original
        ) {
          throw new Error(
            'This text changed while you were editing. Your expression has not been applied. Copy your draft, then reopen the expression.',
          );
        }
      }
      modal = true;
      expressionEditor.open(
        original.slice(from, to),
        'value',
        function (next) {
          checkTarget();
          var replacement =
            original.slice(token.from, from) +
            next +
            original.slice(token.expressionTo, token.to);
          var boundary = substitutionRange(replacement, 0);
          if (!boundary.editable || boundary.to !== replacement.length) {
            throw new Error(
              'This draft would introduce a Mako filter or leave a delimiter unclosed. Wrap Python | operations in parentheses, or cancel and edit the text directly.',
            );
          }
          // An explicit non-typing user event makes this one separate undo step.
          view.dispatch({
            changes: { from: from, to: to, insert: next },
            userEvent: 'input.expression',
          });
          to = from + next.length;
          returnRevision++;
          returnValue =
            original.slice(0, from) + next + original.slice(token.expressionTo);
          input.dispatchEvent(new Event('change', { bubbles: true }));
        },
        'Edit expression',
        null,
        {
          fieldLabel:
            view.contentDOM.getAttribute('aria-label') ||
            (input.labels && input.labels[0] && input.labels[0].textContent) ||
            'Text',
          guidance: 'Apply updates this field. Use Save to keep the change.',
          validateTarget: checkTarget,
          validateUnchanged: true,
          onClose: function () {
            modal = false;
            // A changed/replaced source must not receive an obsolete selection.
            if (editable()) {
              if (revision === returnRevision && input.value === returnValue)
                select(
                  returnRevision === originalRevision
                    ? originalSelection.from
                    : from,
                  returnRevision === originalRevision
                    ? originalSelection.to
                    : to,
                );
              else view.focus();
            }
          },
        },
      );
    }
    function show(token, anchor) {
      if (
        !token ||
        !expressionEditor ||
        expressionEditor.isOpen() ||
        modal ||
        !editable()
      ) {
        hide();
        return;
      }
      root.clearTimeout(timer);
      if (current && current.token === token) return;
      dismissPopover();
      current = { token: token, anchor: anchor };
      popover = doc.createElement('div');
      popover.className = 'mako-expression-popover';
      popover.setAttribute('role', 'group');
      popover.setAttribute('aria-label', 'Mako expression');
      var preview = doc.createElement('code');
      preview.textContent = view.state.doc.sliceString(
        token.editable ? token.expressionFrom : token.from,
        token.editable ? token.expressionTo : token.to,
      );
      var action = doc.createElement('button');
      action.type = 'button';
      action.className = 'btn btn-sm btn-outline-secondary';
      action.textContent = token.editable ? 'Edit expression' : 'Edit in text';
      action.addEventListener('click', activate);
      popover.append(preview, action);
      popover.addEventListener('pointerenter', function () {
        root.clearTimeout(timer);
      });
      popover.addEventListener('pointerleave', leave);
      // Following the editor in DOM order makes the action reachable with Tab.
      host.appendChild(popover);
      activePopover = hide;
      position();
    }
    function leave() {
      root.clearTimeout(timer);
      timer = root.setTimeout(function () {
        if (popover && !popover.contains(doc.activeElement)) hide();
      }, 400);
    }
    function pointer(event) {
      if (
        event.type === 'pointermove' &&
        (event.pointerType !== 'mouse' || event.buttons)
      )
        return;
      if (!view.contentDOM.contains(event.target)) return;
      if (event.type === 'click' && !view.state.selection.main.empty) return;
      var pos = view.posAtCoords({ x: event.clientX, y: event.clientY });
      var token = pos === null ? null : tokenAt(pos);
      // posAtCoords also returns the line end when hovering trailing whitespace.
      var rect = pos === null ? null : view.coordsAtPos(pos);
      if (token && rect && Math.abs(event.clientX - rect.left) < 20) {
        root.cancelAnimationFrame(frame);
        show(token, pos);
      } else leave();
    }
    function caret() {
      root.cancelAnimationFrame(frame);
      frame = root.requestAnimationFrame(function () {
        if (
          isDisposed() ||
          pointerDown ||
          suppressed ||
          modal ||
          !view.hasFocus
        )
          return;
        var selection = view.state.selection.main;
        show(selection.empty ? tokenAt(selection.head) : null, selection.head);
      });
    }
    function down(event) {
      actionPointerDown = Boolean(popover && popover.contains(event.target));
      if (actionPointerDown) return;
      hide();
      pointerDown = host.contains(event.target);
      suppressed = true;
    }
    function up() {
      pointerDown = false;
      // Safari can blur the editor without focusing the tapped button. Keep
      // that button mounted through the ensuing click dispatch.
      root.setTimeout(function () {
        actionPointerDown = false;
      }, 0);
    }
    function key(event) {
      if (event.key === 'Escape' && popover) {
        var focused = popover.contains(doc.activeElement);
        hide();
        suppressed = true;
        event.preventDefault();
        event.stopPropagation();
        if (focused) view.focus();
      } else if (
        view.contentDOM.contains(event.target) &&
        event.key !== 'Tab'
      ) {
        suppressed = false;
      }
    }
    function focusOut(event) {
      if (!actionPointerDown && !host.contains(event.relatedTarget)) hide();
    }
    var listeners = [
      [host, 'pointermove', pointer],
      [host, 'click', pointer],
      [host, 'pointerleave', leave],
      [host, 'keydown', key],
      [host, 'focusin', caret],
      [host, 'focusout', focusOut],
      [doc, 'pointerdown', down],
      [doc, 'pointerup', up],
      [doc, 'pointercancel', up],
      [doc, 'scroll', position, true],
      [root, 'resize', position],
    ];
    if (root.visualViewport)
      listeners.push(
        [root.visualViewport, 'resize', position],
        [root.visualViewport, 'scroll', position],
      );
    listeners.forEach(function (entry) {
      entry[0].addEventListener(entry[1], entry[2], entry[3]);
    });
    return {
      update: function (change) {
        if (change.docChanged) {
          revision++;
          root.cancelAnimationFrame(frame);
          hide();
        }
        if (change.selectionSet && !change.docChanged) caret();
      },
      dispose: function () {
        hide();
        root.cancelAnimationFrame(frame);
        listeners.forEach(function (entry) {
          entry[0].removeEventListener(entry[1], entry[2], entry[3]);
        });
      },
    };
  }

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
    var actions;
    var syncing = false;
    var frame;
    var painted = [];
    var paintedBounds = new WeakMap();
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
    var hint = doc.createElement('span');
    hint.id = 'mako-expression-hint-' + ++hintSerial;
    hint.className = 'mako-expression-hint';
    hint.textContent =
      'Move the caret into a Mako expression, then press Tab for editing actions.';
    host.appendChild(hint);
    view.contentDOM.setAttribute(
      'aria-describedby',
      [input.getAttribute('aria-describedby'), hint.id]
        .filter(Boolean)
        .join(' '),
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
        tokens = rangesFor(tokenDoc);
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
          paintedBounds.set(range, { from: from, to: to });
        });
      });
    }

    function update(change) {
      if (actions) actions.update(change);
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
          if (
            range.collapsed ||
            !view.contentDOM.contains(range.startContainer) ||
            !view.contentDOM.contains(range.endContainer)
          )
            return true;
          // Markdown can replace inline nodes when the cursor moves. Live
          // DOM ranges can then expand into prose without collapsing or
          // detaching, so also check their original document boundaries.
          var bounds = paintedBounds.get(range);
          return (
            view.posAtDOM(range.startContainer, range.startOffset) !==
              bounds.from ||
            view.posAtDOM(range.endContainer, range.endOffset) !== bounds.to
          );
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
    actions = contextualActions(input, host, view, function () {
      return disposed;
    });
    editors.set(input, function () {
      disposed = true;
      actions.dispose();
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
    setExpressionEditor: function (editor) {
      expressionEditor = editor;
    },
    dismissPopover: dismissPopover,
  };
  root.WeaverMarkdown = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window === 'object' ? window : globalThis);
