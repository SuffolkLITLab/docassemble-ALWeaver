/* Source authoring tools using docassemble's own CodeMirror instance. */
(function (root) {
  'use strict';

  function completionEdit(before, label, from, to) {
    var start = before.length;
    while (start > 0 && /[\w.[\]]/.test(before[start - 1])) start--;
    var prefix = before.slice(start);
    var insert = label;
    if (prefix.endsWith('.') && /^[A-Za-z_]/.test(prefix)) {
      var segments = prefix.split('.').length - 1;
      var candidate = label.split('.').slice(0, segments).join('.') + '.';
      if (
        prefix.replace(/\[\w+\]/g, '[]') === candidate.replace(/\[\w+\]/g, '[]')
      )
        insert = prefix + label.slice(candidate.length);
      else if (!label.includes('.'))
        return { from: from, to: to, insert: label };
      else insert = prefix + label.split('.').pop();
      from -= prefix.length;
    }
    if (prefix.endsWith('[') && label.startsWith(prefix)) from -= prefix.length;
    return { from: from, to: to, insert: insert };
  }

  function completions(groups, names, functions) {
    var entries = new Map();
    Object.keys(groups).forEach(function (group) {
      (groups[group] || []).forEach(function (name) {
        var types = {
          functions: 'function',
          methods: 'method',
          classes: 'class',
          templates: 'template',
          tables: 'table',
          events: 'event',
          yaml_files: 'file',
          template_files: 'file',
          static_files: 'file',
          static_images: 'file',
        };
        entries.set(name, {
          label: name,
          detail: group.replace(/_/g, ' '),
          symbolKind: types[group] || 'variable',
        });
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
        symbolKind: 'function',
        origin: entry.origin,
        builtin:
          entry.origin === 'Python' || entry.origin === 'docassemble.base.util',
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
          var edit = completionEdit(
            view.state.doc.sliceString(0, from),
            completion.label,
            from,
            to,
          );
          view.dispatch({
            changes: edit,
            selection: { anchor: edit.from + edit.insert.length },
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
        if (item.rendered_jinja) return [];
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
        var to = starts[line - 1] + lines[line - 1].length;
        var end = item.source_range && item.source_range.end;
        if (
          end &&
          Number.isInteger(end.line) &&
          end.line >= line &&
          end.line <= lines.length
        ) {
          to =
            starts[end.line - 1] +
            Array.from(lines[end.line - 1])
              .slice(0, Math.max(0, Number(end.column || 1) - 1))
              .join('').length;
        }
        return [
          {
            from: from,
            to: Math.max(from, to),
            line: line,
            index: index,
            level: String(item.level || item.severity || 'error').toLowerCase(),
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
    var activeDiagnostic = -1;
    var lastDocument = view.state.doc;
    var originalExtensions = bundle.compartment.get(view.state);
    var toolbar = doc.createElement('div');
    toolbar.className = 'editor-source-tools';
    toolbar.setAttribute('role', 'group');
    toolbar.setAttribute('aria-label', 'Source tools');
    function button(label, callback) {
      var control = doc.createElement('button');
      control.type = 'button';
      control.className = 'btn btn-sm btn-link editor-source-tool';
      control.textContent =
        { 'Previous problem': '↑', 'Next problem': '↓' }[label] || label;
      control.setAttribute('aria-label', label);
      control.title = label;
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
    var status = doc.createElement('span');
    status.setAttribute('role', 'status');
    toolbar.appendChild(status);
    container.prepend(toolbar);
    container.classList.add('editor-source-with-tools');

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
      activeDiagnostic = ranges.indexOf(range);
      view.dispatch({
        selection: { anchor: range.from },
        effects: view.constructor.scrollIntoView(range.from, { y: 'center' }),
      });
      view.focus();
      selectedMessage = 'Line ' + range.line + ': ' + range.message;
      status.textContent = selectedMessage;
      view.requestMeasure();
      schedule();
    }
    function navigate(direction) {
      if (!current() || !ranges.length) return;
      var position = view.state.selection.main.from;
      var range;
      if (activeDiagnostic >= 0 && ranges[activeDiagnostic].from === position) {
        range =
          ranges[
            (activeDiagnostic + direction + ranges.length) % ranges.length
          ];
      } else {
        range =
          direction > 0
            ? ranges.find(function (item) {
                return item.from >= position;
              }) || ranges[0]
            : ranges
                .slice()
                .reverse()
                .find(function (item) {
                  return item.from <= position;
                }) || ranges[ranges.length - 1];
      }
      reveal(range);
    }
    function paint() {
      if (disposed) return;
      var focusedLine = markers.contains(doc.activeElement)
        ? doc.activeElement.getAttribute('data-line')
        : null;
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
      var bottomPanel = view.dom.querySelector('.cm-panels-bottom');
      var bottom = bottomPanel
        ? Math.min(viewport.bottom, bottomPanel.getBoundingClientRect().top)
        : viewport.bottom;
      var lineMarkers = new Map();
      ranges.forEach(function (item) {
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
        var visible = view.visibleRanges.some(function (range) {
          return item.from >= range.from && item.from <= range.to;
        });
        if (!visible) return;
        var coords = view.coordsAtPos(item.from);
        if (!coords || coords.top < viewport.top || coords.top >= bottom)
          return;
        var marker = lineMarkers.get(item.line);
        if (marker) {
          marker.title += '\n' + item.message;
          marker.setAttribute('aria-label', marker.title);
          var ranks = { info: 0, warning: 1, error: 2 };
          if (ranks[item.level] > ranks[marker.dataset.level]) {
            marker.dataset.level = item.level;
            marker.dataset.findingIndex = item.index;
            marker.className = 'editor-source-diagnostic-marker ' + item.level;
            marker.textContent = { info: 'i', warning: '▲', error: '!' }[
              item.level
            ];
          }
        } else {
          marker = doc.createElement('button');
          marker.type = 'button';
          var level = ['error', 'warning', 'info'].includes(item.level)
            ? item.level
            : 'info';
          marker.dataset.level = level;
          marker.dataset.line = item.line;
          marker.dataset.findingIndex = item.index;
          marker.className = 'editor-source-diagnostic-marker ' + level;
          marker.style.top = coords.top - bounds.top + 'px';
          marker.textContent = { warning: '▲', error: '!', info: 'i' }[level];
          marker.title = 'Line ' + item.line + ': ' + item.message;
          marker.setAttribute('aria-label', marker.title);
          marker.addEventListener('click', function () {
            var selected =
              ranges.find(function (entry) {
                return entry.index === Number(marker.dataset.findingIndex);
              }) || item;
            reveal(selected);
            actions.findings(selected.index);
          });
          lineMarkers.set(item.line, marker);
          markers.appendChild(marker);
        }
      });
      if (focusedLine) {
        var replacement = markers.querySelector(
          '[data-line="' + focusedLine + '"]',
        );
        (replacement || next).focus({ preventScroll: true });
      }
    }
    function schedule() {
      if (lastDocument !== view.state.doc) {
        lastDocument = view.state.doc;
        selectedMessage = '';
        activeDiagnostic = -1;
      }
      root.cancelAnimationFrame(frame);
      frame = root.requestAnimationFrame(paint);
    }
    view.dispatch({
      effects: bundle.compartment.reconfigure([
        originalExtensions,
        view.constructor.updateListener.of(function (update) {
          if (
            update.docChanged ||
            update.viewportChanged ||
            update.geometryChanged
          )
            schedule();
        }),
      ]),
    });
    view.scrollDOM.addEventListener('scroll', schedule);
    root.addEventListener('resize', schedule);
    schedule();
    return {
      revealFinding: function (index) {
        if (!current()) {
          status.textContent =
            'Source changed; validate again before navigating to a finding.';
          return true;
        }
        var range = ranges.find(function (item) {
          return item.index === index;
        });
        if (range) {
          reveal(range);
          return true;
        } else
          status.textContent =
            'This finding has no location in the current source.';
        return false;
      },
      setDiagnostics: function (value) {
        snapshot = value;
        activeDiagnostic = -1;
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
        view.dispatch({
          effects: bundle.compartment.reconfigure(originalExtensions),
        });
        container.classList.remove('editor-source-with-tools');
        view.scrollDOM.removeEventListener('scroll', schedule);
        root.removeEventListener('resize', schedule);
        Object.keys(highlights).forEach(function (level) {
          if (
            root.CSS.highlights.get('weaver-source-' + level) ===
            highlights[level]
          )
            root.CSS.highlights.delete('weaver-source-' + level);
        });
        toolbar.remove();
        markers.remove();
      },
    };
  }
  var api = {
    completionEdit: completionEdit,
    completions: completions,
    diagnosticRanges: diagnosticRanges,
    attach: attach,
  };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ALWeaverSourceTools = api;
})(typeof window === 'undefined' ? globalThis : window);
