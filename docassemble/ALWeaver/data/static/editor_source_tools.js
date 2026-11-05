/* Source authoring tools using docassemble's own CodeMirror instance. */
(function (root) {
  'use strict';

  function completions(groups, names, functions) {
    var entries = new Map();
    Object.keys(groups).forEach(function (group) {
      (groups[group] || []).forEach(function (name) {
        entries.set(name, { label: name, detail: group.replace(/_/g, ' ') });
      });
    });
    names.forEach(function (name) {
      if (!entries.has(name))
        entries.set(name, { label: name, detail: 'symbol' });
    });
    functions.forEach(function (entry) {
      entries.set(entry.name, {
        label: entry.name,
        type: 'function',
        detail: entry.signature || 'function',
        info: entry.doc || entry.description || '',
      });
    });
    return Array.from(entries.values())
      .filter(function (entry) {
        return typeof entry.label === 'string' && entry.label.length > 0;
      })
      .map(function (entry) {
        // The upstream completion source matches only the final word. Replace
        // the whole dotted prefix when it belongs to the chosen symbol.
        entry.apply = function (view, completion, from, to) {
          var before = view.state.doc.sliceString(0, from);
          var start = before.length;
          while (start > 0 && /[\w.]/.test(before[start - 1])) start--;
          var prefix = before.slice(start);
          if (prefix.endsWith('.') && completion.label.startsWith(prefix))
            from -= prefix.length;
          view.dispatch({
            changes: { from: from, to: to, insert: completion.label },
            selection: { anchor: from + completion.label.length },
            userEvent: 'input.complete',
          });
        };
        return entry;
      });
  }

  function diagnosticRanges(source, diagnostics, filename) {
    var lines = source.split('\n');
    var starts = [],
      offset = 0;
    lines.forEach(function (line) {
      starts.push(offset);
      offset += line.length + 1;
    });
    return diagnostics
      .flatMap(function (item, index) {
        if (item.filename && item.filename !== filename) return [];
        var start = item.source_range && item.source_range.start;
        var line = Number(start ? start.line : item.line_number);
        if (!Number.isInteger(line) || line < 1 || line > lines.length)
          return [];
        // Python source positions count Unicode code points; CM counts UTF-16.
        var column = Math.max(0, Number((start && start.column) || 1) - 1);
        var from =
          starts[line - 1] +
          Array.from(lines[line - 1])
            .slice(0, column)
            .join('').length;
        return [
          {
            from: from,
            to: starts[line - 1] + lines[line - 1].length,
            line: line,
            index: index,
            level: item.level || item.severity || 'error',
            message: String(item.message || 'Source diagnostic'),
          },
        ];
      })
      .sort(function (a, b) {
        return a.from - b.from;
      });
  }

  function attach(bundle, container, actions) {
    var view = bundle.ev,
      doc = container.ownerDocument;
    var snapshot = null,
      ranges = [],
      disposed = false,
      frame = 0,
      selectedMessage = '';
    var lastDocument = view.state.doc;
    var toolbar = doc.createElement('div');
    toolbar.className = 'editor-source-tools';
    toolbar.setAttribute('role', 'toolbar');
    toolbar.setAttribute('aria-label', 'Source tools');
    function button(label, callback) {
      var control = doc.createElement('button');
      control.type = 'button';
      control.className = 'btn btn-sm btn-outline-secondary';
      control.textContent = label;
      control.addEventListener('click', callback);
      toolbar.appendChild(control);
      return control;
    }
    button('Validate', actions.validate);
    var previous = button('Previous problem', function () {
      navigate(-1);
    });
    var next = button('Next problem', function () {
      navigate(1);
    });
    button('Findings', actions.findings);
    var symbols = button('Symbols', function () {
      picker.hidden = !picker.hidden;
      if (!picker.hidden) {
        search.value = '';
        showSymbols();
        search.focus();
      }
    });
    symbols.title = 'Browse symbols; Ctrl-Space completes a symbol in source';
    var status = doc.createElement('span');
    status.setAttribute('role', 'status');
    toolbar.appendChild(status);
    container.prepend(toolbar);
    container.classList.add('editor-source-with-tools');

    var picker = doc.createElement('div');
    picker.className = 'editor-source-symbols';
    picker.hidden = true;
    var label = doc.createElement('label');
    label.textContent = 'Find a symbol';
    var search = doc.createElement('input');
    search.type = 'search';
    search.className = 'form-control form-control-sm';
    label.appendChild(search);
    picker.appendChild(label);
    var help = doc.createElement('p');
    help.className = 'small text-muted';
    help.textContent =
      'Symbols from the saved interview and its includes. Click to insert at the source selection. Ctrl-Space also completes symbols.';
    picker.appendChild(help);
    var list = doc.createElement('div');
    picker.appendChild(list);
    container.appendChild(picker);
    function showSymbols() {
      list.replaceChildren();
      var query = search.value.toLowerCase();
      var matches = actions.symbols().filter(function (entry) {
        return entry.label.toLowerCase().includes(query);
      });
      matches.slice(0, 80).forEach(function (entry) {
        var item = doc.createElement('button');
        item.type = 'button';
        item.className = 'editor-source-symbol';
        item.textContent = entry.label + ' · ' + entry.detail;
        item.addEventListener('click', function () {
          var selection = view.state.selection.main;
          view.dispatch({
            changes: {
              from: selection.from,
              to: selection.to,
              insert: entry.label,
            },
            selection: { anchor: selection.from + entry.label.length },
            userEvent: 'input.complete',
          });
          picker.hidden = true;
          view.focus();
        });
        list.appendChild(item);
      });
      var count = doc.createElement('p');
      count.textContent =
        matches.length > 80
          ? 'Showing 80 of ' + matches.length + '; narrow your search.'
          : matches.length + ' symbols';
      list.appendChild(count);
    }
    search.addEventListener('input', showSymbols);
    picker.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        picker.hidden = true;
        view.focus();
      }
    });

    var markers = doc.createElement('div');
    markers.className = 'editor-source-diagnostic-markers';
    container.appendChild(markers);
    var highlights = {};
    if (root.CSS && root.CSS.highlights && root.Highlight) {
      ['error', 'warning', 'info'].forEach(function (level) {
        highlights[level] = new root.Highlight();
        root.CSS.highlights.set('weaver-source-' + level, highlights[level]);
      });
    }
    function current() {
      return snapshot && snapshot.source === view.state.doc.toString();
    }
    function reveal(range) {
      view.dispatch({
        selection: { anchor: range.from, head: range.to },
        effects: view.constructor.scrollIntoView(range.from, { y: 'center' }),
      });
      view.focus();
      selectedMessage = 'Line ' + range.line + ': ' + range.message;
      status.textContent = selectedMessage;
    }
    function navigate(direction) {
      if (!current() || !ranges.length) return;
      var position = view.state.selection.main.from;
      var range =
        direction > 0
          ? ranges.find(function (item) {
              return item.from > position;
            }) || ranges[0]
          : ranges
              .slice()
              .reverse()
              .find(function (item) {
                return item.from < position;
              }) || ranges[ranges.length - 1];
      reveal(range);
    }
    function paint() {
      if (disposed) return;
      markers.replaceChildren();
      Object.values(highlights).forEach(function (highlight) {
        highlight.clear();
      });
      var valid = current();
      previous.disabled = next.disabled = !valid || !ranges.length;
      if (!valid) {
        status.textContent = snapshot
          ? 'Source changed; validate again.'
          : 'Validate to locate problems.';
        return;
      }
      status.textContent =
        selectedMessage ||
        snapshot.diagnostics.length +
          ' findings; ' +
          ranges.length +
          ' located in source.';
      var bounds = container.getBoundingClientRect();
      var viewport = view.scrollDOM.getBoundingClientRect();
      var lineMarkers = new Map();
      ranges.forEach(function (item) {
        var visible = view.visibleRanges.some(function (range) {
          return item.from >= range.from && item.from <= range.to;
        });
        if (!visible) return;
        var coords = view.coordsAtPos(item.from);
        if (
          !coords ||
          coords.top < viewport.top ||
          coords.top >= viewport.bottom
        )
          return;
        var marker = lineMarkers.get(item.line);
        if (marker) {
          marker.title += '\n' + item.message;
          marker.setAttribute('aria-label', marker.title);
          if (item.level === 'error')
            marker.className = 'editor-source-diagnostic-marker error';
        } else {
          marker = doc.createElement('button');
          marker.type = 'button';
          var level = ['error', 'warning', 'info'].includes(item.level)
            ? item.level
            : 'info';
          marker.className = 'editor-source-diagnostic-marker ' + level;
          marker.style.top = coords.top - bounds.top + 'px';
          marker.textContent = { warning: '▲', error: '!', info: 'i' }[level];
          marker.title = 'Line ' + item.line + ': ' + item.message;
          marker.setAttribute('aria-label', marker.title);
          marker.addEventListener('click', function () {
            reveal(item);
            actions.findings(item.index);
          });
          lineMarkers.set(item.line, marker);
          markers.appendChild(marker);
        }
        var highlight = highlights[item.level] || highlights.info;
        if (highlight && item.from < item.to) {
          view.visibleRanges.forEach(function (range) {
            var from = Math.max(item.from, range.from),
              to = Math.min(item.to, range.to);
            if (from >= to) return;
            var a = view.domAtPos(from, 1),
              b = view.domAtPos(to, -1);
            var domRange = doc.createRange();
            domRange.setStart(a.node, a.offset);
            domRange.setEnd(b.node, b.offset);
            highlight.add(domRange);
          });
        }
      });
    }
    function schedule() {
      if (lastDocument !== view.state.doc) {
        lastDocument = view.state.doc;
        selectedMessage = '';
      }
      root.cancelAnimationFrame(frame);
      frame = root.requestAnimationFrame(paint);
    }
    view.dispatch({
      effects: bundle.compartment.reconfigure(
        view.constructor.updateListener.of(function (update) {
          if (
            update.docChanged ||
            update.viewportChanged ||
            update.geometryChanged
          )
            schedule();
        }),
      ),
    });
    view.scrollDOM.addEventListener('scroll', schedule);
    root.addEventListener('resize', schedule);
    schedule();
    return {
      refreshSymbols: function () {
        if (!picker.hidden) showSymbols();
      },
      revealFinding: function (index) {
        if (!current()) {
          status.textContent =
            'Source changed; validate again before navigating to a finding.';
          return;
        }
        var range = ranges.find(function (item) {
          return item.index === index;
        });
        if (range) reveal(range);
        else
          status.textContent =
            'This finding has no location in the current source.';
      },
      setDiagnostics: function (value) {
        snapshot = value;
        selectedMessage = '';
        ranges = value
          ? diagnosticRanges(value.source, value.diagnostics, value.filename)
          : [];
        status.textContent = value
          ? value.diagnostics.length +
            ' findings; ' +
            ranges.length +
            ' located in source.'
          : '';
        schedule();
      },
      dispose: function () {
        disposed = true;
        root.cancelAnimationFrame(frame);
        view.scrollDOM.removeEventListener('scroll', schedule);
        root.removeEventListener('resize', schedule);
        Object.keys(highlights).forEach(function (level) {
          root.CSS.highlights.delete('weaver-source-' + level);
        });
        toolbar.remove();
        picker.remove();
        markers.remove();
      },
    };
  }
  var api = {
    completions: completions,
    diagnosticRanges: diagnosticRanges,
    attach: attach,
  };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ALWeaverSourceTools = api;
})(typeof window === 'undefined' ? globalThis : window);
