/* Shared report controls. Analysis stays in interview_scan.py. */
(function (root) {
  'use strict';
  var bridge, report, requestNumber = 0, timer, lastKey, sourceHost, sourceFilters, sourcePreferences, sourceCollapsed = false, listObserver, listGeneration = 0, listPageKey = '', listShown = 150;
  function el(id) { return document.getElementById(id); }
  function key() {
    var state = bridge.getState();
    return [state.project, state.filename, state.revision].join('|');
  }
  function location(block, label) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-link btn-sm text-start';
    button.textContent = label + ' — ' + block.sourceFile + ':' + block.line_start;
    button.disabled = block.sourceFile.indexOf(':') !== -1;
    button.addEventListener('click', function () { bridge.openBlock(block); });
    return button;
  }
  var dock = 'full';
  function setDock(value) {
    dock = value;
    var panel = el('variable-report-rail');
    panel.dataset.dock = value;
    document.body.classList.remove('variable-browser-pinned');
    var layout = el('editor-workspace') || panel.parentElement;
    layout.classList.toggle('variable-browser-pinned', value === 'side');
    document.querySelectorAll('[data-variable-dock]').forEach(function (button) {
      button.setAttribute('aria-pressed', String(button.dataset.variableDock === value));
    });
    try { if (value !== 'source') localStorage.setItem('alweaver-variable-dock', value); } catch (_) { /* Storage is optional. */ }
  }
  function stopListObserver() {
    listGeneration++;
    if (listObserver) listObserver.disconnect();
    listObserver = null;
  }
  function render() {
    stopListObserver();
    var generation = listGeneration;
    var box = el('variable-report-results');
    var focused = box.contains(document.activeElement) ? document.activeElement : null;
    var focusedLabel = focused && focused.getAttribute('aria-label');
    var focusedMore = focused && focused.classList.contains('variable-browser-more');
    box.replaceChildren();
    if (!report && !sourceHost) return;
    var data = report || { blocks: [], variables: [], symbols: [], warnings: [] };
    var filter = el('variable-report-filter').value.toLowerCase();
    var kind = el('variable-report-kind').value;
    var status = el('variable-report-status').value;
    var pageKey = JSON.stringify([bridge.getState().project, bridge.getState().filename, filter, kind, status, el('variable-report-scope').value]);
    if (pageKey !== listPageKey) { listPageKey = pageKey; listShown = 150; }
    var blocks = {};
    data.blocks.forEach(function (b) { blocks[b.scan_id] = b; });
    var declarations = new Map();
    (data.symbols || []).forEach(function (symbol) {
      var previous = declarations.get(symbol.name);
      declarations.set(symbol.name, Object.assign({}, symbol, {definitions: Array.from(new Set((previous ? previous.definitions : []).concat(symbol.definitions || [])))}));
    });
    var variables = new Map(data.variables.map(function (entry) { return [entry.name, entry]; }));
    var symbols = Array.from(declarations.values()).map(function (symbol) { return Object.assign({}, variables.get(symbol.name), symbol); });
    var entries = kind === 'variable' ? data.variables : kind === 'screen' ? data.blocks.filter(function (b) { return b.data && b.data.question; }).map(function (b) { return {name: b.report_title || b.title, definitions: [b.scan_id], references: b.possibly_unreachable ? [] : ['flow'], possibly_unused: b.possibly_unreachable}; }) : symbols.filter(function (s) { return s.kind === kind; });
    if (kind === 'all' || kind === 'variable') {
      var declaredKinds = new Set(declarations.keys());
      entries = data.variables.filter(function (entry) { return !declaredKinds.has(entry.name); });
      entries = entries.concat(kind === 'all' ? symbols : symbols.filter(function (symbol) { return symbol.kind === 'variable'; }));
    }
    entries = entries.slice();
    if (sourceHost && bridge.sourceSymbols) {
      var known = new Set(Array.from(declarations.keys()).concat(Array.from(variables.keys()), entries.map(function (entry) { return entry.name; })));
      bridge.sourceSymbols().forEach(function (symbol) {
        var symbolKind = symbol.symbolKind || (symbol.type === 'function' ? 'function' : 'variable');
        if (!known.has(symbol.label) && (kind === 'all' || kind === symbolKind)) {
          known.add(symbol.label);
          entries.push({ name: symbol.label, kind: symbolKind, definitions: [], references: [], catalog: true, builtin: symbol.builtin, origin: symbol.origin });
        }
      });
    }
    var matches = entries.map(function (entry) {
      var definitions = (entry.definitions || []).map(function (id) { return blocks[id]; }).filter(Boolean);
      // A method is called on an instance, never through its class name.
      var method = entry.kind === 'method' ? '.' + entry.name.split('.').pop() : null;
      var references = entry.references || data.blocks.filter(function (b) {
        return (b.references || []).some(function (name) { return method ? name.endsWith(method) : name === entry.name; });
      }).map(function (b) { return b.scan_id; });
      var errors = definitions.flatMap(function (b) { return bridge.findings ? bridge.findings(b) : []; });
      if (entry.undefined) {
        errors.unshift({message: 'Nothing in this interview or its includes defines ' + entry.name + ', and Docassemble does not provide it. The interview stops with "could not be looked up" when it reaches a use.'});
      }
      // An undefined name has no definition, so it belongs where it is used.
      var located = entry.undefined ? references.map(function (id) { return blocks[id]; }).filter(Boolean) : definitions;
      return {entry: entry, definitions: definitions, located: located, references: references, errors: errors, unused: !entry.catalog && (typeof entry.possibly_unused === 'boolean' ? entry.possibly_unused : !references.length), unreachable: definitions.some(function (b) { return b.possibly_unreachable; })};
    }).filter(function (item) {
      return (item.entry.name + ' ' + item.located.map(function (b) { return b.sourceFile; }).join(' ')).toLowerCase().includes(filter) &&
        (el('variable-report-scope').value === 'all' || item.located.some(function (b) { return !b.sourceFile.includes(':'); })) &&
        (status === 'all' || status === 'used' && !item.unused && !item.entry.catalog || status === 'unused' && item.unused || status === 'unreachable' && item.unreachable || status === 'error' && item.errors.length);
    });
    var kinds = ['variable', 'template', 'table', 'function', 'method', 'class', 'event', 'file'];
    var headings = {variable: 'Variables', template: 'Templates', table: 'Tables', function: 'Functions', method: 'Methods', class: 'Classes', event: 'Events', file: 'Files'};
    function group(item) { return item.entry.kind || 'variable'; }
    // Keep each type together; errors lead within their group.
    matches.sort(function (a, b) { return (kind === 'all' ? kinds.indexOf(group(a)) - kinds.indexOf(group(b)) : 0) || (b.errors.length ? 1 : 0) - (a.errors.length ? 1 : 0) || a.entry.name.localeCompare(b.entry.name); });
    var count = document.createElement('p');
    count.className = 'small text-muted';
    box.appendChild(count);
    var more = document.createElement('button');
    more.type = 'button';
    more.className = 'btn btn-sm btn-outline-secondary w-100 mt-2 variable-browser-more';
    box.appendChild(more);
    var rendered = 0, previousGroup;
    function renderRow(item) {
      var row = document.createElement('div');
      row.className = 'variable-browser-row';
      var info = document.createElement('div');
      var name = document.createElement(sourceHost && kind !== 'screen' ? 'button' : 'strong');
      name.textContent = item.entry.name;
      if (sourceHost && kind !== 'screen') {
        name.type = 'button'; name.className = 'variable-browser-insert';
        name.title = 'Insert ' + item.entry.name;
        name.setAttribute('aria-label', 'Insert ' + item.entry.name);
        name.onclick = function () { bridge.insertSymbol(item.entry.name); };
      }
      var state = item.errors.length ? 'error' : (item.entry.builtin || item.entry.origin === 'Python' || item.entry.origin === 'docassemble.base.util') ? 'builtin' : item.unused ? 'unused' : item.unreachable ? 'unreachable' : item.entry.catalog || item.entry.origin ? 'provided' : 'used';
      var labels = {error: 'Error', builtin: 'Built-in', unreachable: 'Possibly unreachable', unused: 'Possibly unused', provided: 'Provided'};
      row.dataset.symbolStatus = state;
      var detail = document.createElement('div');
      detail.className = 'small text-muted';
      detail.textContent = (item.entry.origin ? item.entry.origin + ' · imported at ' : item.entry.undefined ? 'Used at ' : '') + item.located.map(function (b) { return b.sourceFile + ':' + b.line_start; }).join(', ');
      var usage = document.createElement('div');
      usage.className = 'small';
      if (item.errors.length) usage.className += ' text-danger';
      usage.textContent = item.entry.catalog ? (item.entry.builtin ? 'Built-in symbol' : 'Provided by the symbol catalog') : item.entry.undefined ? 'Error · Not defined' : (item.errors.length ? 'Error · ' : '') + (item.unused ? 'Possibly unused' : 'Used') + (item.unreachable ? ' · Possibly unreachable' : '');
      info.append(name);
      if (!sourceHost) info.append(detail, usage);
      if (sourceHost && labels[state]) {
        var badge = document.createElement('span');
        badge.className = 'variable-browser-status';
        badge.textContent = labels[state] + (state === 'unused' && item.unreachable ? ' · unreachable' : '');
        if (item.errors.length) badge.title = item.errors[0].message;
        info.appendChild(badge);
      }
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-sm btn-link variable-browser-details';
      button.textContent = sourceHost ? '…' : 'Details';
      button.setAttribute('aria-label', 'Details for ' + item.entry.name);
      button.onclick = function () {
        var dialog = reportDialog(item.entry.name);
        if (item.entry.signature) { var signature = document.createElement('pre'); signature.textContent = item.entry.signature; dialog.appendChild(signature); }
        if (item.entry.origin) { var origin = document.createElement('p'); origin.textContent = 'Provided by ' + item.entry.origin + '.' + (item.definitions.length ? ' The source links below show where this module is included.' : ''); dialog.appendChild(origin); }
        if (item.entry.documentation) { var docs = document.createElement('p'); docs.textContent = item.entry.documentation; dialog.appendChild(docs); }
        item.errors.forEach(function (error) { var message = document.createElement('p'); message.className = 'text-danger'; message.textContent = error.message || String(error); dialog.appendChild(message); });
        if (sourceHost && kind !== 'screen' && !item.entry.catalog && !item.entry.origin && bridge.renameSymbol && (!item.entry.kind || item.entry.kind === 'variable')) {
          var rename = document.createElement('button'); rename.type = 'button'; rename.className = 'btn btn-sm btn-outline-secondary mb-2'; rename.textContent = 'Rename variable…';
          rename.onclick = function () { dialog.close(); bridge.renameSymbol(item.entry.name); };
          dialog.appendChild(rename);
        }
        item.definitions.forEach(function (b) { dialog.appendChild(location(b, 'Declared')); });
        item.references.forEach(function (id) { if (blocks[id]) dialog.appendChild(location(blocks[id], 'Used')); });
        dialog.querySelectorAll('button:not(.btn-close)').forEach(function (link) { link.addEventListener('click', function () { dialog.close(); if (dock === 'full') setDock('side'); }); });
      };
      row.append(info, button);
      return row;
    }
    function appendRows(amount, focusNew) {
      if (generation !== listGeneration) return;
      var end = Math.min(rendered + amount, matches.length);
      var firstNew;
      matches.slice(rendered, end).forEach(function (item) {
        if (kind === 'all' && group(item) !== previousGroup) {
          previousGroup = group(item);
          var heading = document.createElement('h3');
          heading.className = 'variable-browser-group';
          heading.textContent = headings[previousGroup] || previousGroup;
          box.insertBefore(heading, more);
        }
        var row = renderRow(item);
        if (!firstNew) firstNew = row;
        box.insertBefore(row, more);
      });
      rendered = end;
      listShown = Math.max(listShown, rendered);
      count.textContent = (rendered < matches.length ? 'Showing ' + rendered + ' of ' + matches.length + ' results' : matches.length + (matches.length === 1 ? ' result' : ' results')) + (data.warnings.length ? ' · ' + data.warnings.join(' ') : '');
      more.hidden = rendered === matches.length;
      more.textContent = 'Show more (' + (matches.length - rendered) + ' remaining)';
      if (more.hidden && listObserver) { listObserver.disconnect(); listObserver = null; }
      if (focusNew && firstNew) {
        var next = firstNew.querySelector('button');
        if (next) next.focus({ preventScroll: true });
        firstNew.scrollIntoView({ block: 'nearest' });
      }
    }
    more.onclick = function () { appendRows(150, true); };
    appendRows(listShown, false);
    if (focusedLabel) {
      var replacement = Array.from(box.querySelectorAll('button[aria-label]')).find(function (button) { return button.getAttribute('aria-label') === focusedLabel; });
      if (replacement) replacement.focus({ preventScroll: true });
    } else if (focusedMore && !more.hidden) more.focus({ preventScroll: true });
    if (!more.hidden && root.IntersectionObserver) {
      listObserver = new root.IntersectionObserver(function (entries) {
        if (entries.some(function (entry) { return entry.isIntersecting; })) appendRows(150, false);
      }, { root: el('variable-report-rail'), rootMargin: '150px 0px' });
      listObserver.observe(more);
    }
  }
  function refresh() {
    var sequence = ++requestNumber;
    var state = bridge.getState();
    lastKey = key();
    report = null;
    if (sourceHost) render();
    else el('variable-report-results').textContent = 'Reading interview…';
    bridge.apiPost('/api/reports/scan', {project: state.project, filename: state.filename})
      .then(function (response) {
        if (sequence !== requestNumber || lastKey !== key()) return;
        if (!response.success) throw new Error(response.error.message);
        report = response.data;
        render();
      }).catch(function (error) {
        if (sequence === requestNumber) el('variable-report-results').textContent = error.message;
      });
  }
  function setSourceCollapsed(collapsed) {
    if (!sourceHost) return;
    sourceCollapsed = collapsed;
    sourceHost.classList.toggle('source-variables-collapsed', collapsed);
    el('variable-report-content').hidden = collapsed;
    var button = el('variable-source-collapse');
    button.setAttribute('aria-expanded', String(!collapsed));
    button.setAttribute('aria-label', collapsed ? 'Expand variables' : 'Collapse variables');
    button.title = collapsed ? 'Expand variables' : 'Collapse variables';
    try { localStorage.setItem('alweaver-source-variables-collapsed', String(collapsed)); } catch (_) { /* keep the session preference */ }
  }
  function openVariables(options) {
    if (sourceHost && !options.sourceHost) { setSourceCollapsed(false); el('variable-report-filter').focus(); return; }
    bridge = options;
    sourceHost = options.sourceHost || null;
    var panel = el('variable-report-rail');
    (sourceHost || document.body).appendChild(panel);
    panel.classList.toggle('source-variable-browser', Boolean(sourceHost));
    el('variable-source-collapse').hidden = !sourceHost;
    if (sourceHost) {
      sourceHost.classList.add('editor-source-with-variables');
      try { sourceCollapsed = localStorage.getItem('alweaver-source-variables-collapsed') === 'true'; } catch (_) { /* retain session preference */ }
      setSourceCollapsed(sourceCollapsed);
      el('variable-source-collapse').onclick = function () { setSourceCollapsed(!sourceCollapsed); };
      var outlineStatus = el('source-outline-status');
      sourceHost.querySelector('#full-source-editor').insertBefore(outlineStatus, sourceHost.querySelector('.cm-editor'));
      outlineStatus.textContent = '';
      if (!sourceFilters) {
        sourceFilters = {};
        ['filter', 'kind', 'scope', 'status'].forEach(function (name) { sourceFilters[name] = el('variable-report-' + name).value; });
      }
      if (sourcePreferences) {
        Object.keys(sourcePreferences).forEach(function (name) { el('variable-report-' + name).value = sourcePreferences[name]; });
      } else {
        el('variable-report-kind').value = 'all';
        el('variable-report-scope').value = 'all';
      }
    }
    panel.querySelector('h2').textContent = sourceHost ? 'Variables & references' : 'Interview variables';
    el('variable-report-insert-help').hidden = !sourceHost;
    el('variable-report-rail').classList.remove('d-none');
    el('variable-report-close').onclick = function () {
      stopListObserver();
      el('variable-report-rail').classList.add('d-none');
      (el('editor-workspace') || document.body).classList.remove('variable-browser-pinned');
      clearInterval(timer);
      requestNumber++;
    };
    el('variable-report-refresh').onclick = refresh;
    ['filter', 'kind', 'scope', 'status'].forEach(function (name) { el('variable-report-' + name).oninput = render; });
    try { dock = localStorage.getItem('alweaver-variable-dock') || 'side'; } catch (_) { dock = 'side'; }
    if (!['bottom', 'tall', 'side', 'full'].includes(dock)) dock = 'side';
    setDock(sourceHost ? 'source' : dock);
    document.querySelectorAll('[data-variable-dock]').forEach(function (button) { button.onclick = function () { setDock(button.dataset.variableDock); }; });
    clearInterval(timer);
    var diagnosticKey = '';
    timer = setInterval(function () {
      if (lastKey !== key()) refresh();
      var next = JSON.stringify(bridge.getState().validationErrors || []);
      if (next !== diagnosticKey) { diagnosticKey = next; render(); }
    }, 1500);
    refresh();
  }
  function closeSource() {
    if (!sourceHost) return;
    stopListObserver();
    var panel = el('variable-report-rail');
    sourceHost.classList.remove('editor-source-with-variables', 'source-variables-collapsed');
    el('variable-source-collapse').hidden = true;
    el('variable-report-content').hidden = false;
    el('left-rail').insertBefore(el('source-outline-status'), el('outline-list'));
    sourcePreferences = {};
    ['filter', 'kind', 'scope', 'status'].forEach(function (name) { sourcePreferences[name] = el('variable-report-' + name).value; });
    if (sourceFilters) Object.keys(sourceFilters).forEach(function (name) { el('variable-report-' + name).value = sourceFilters[name]; });
    sourceFilters = null;
    sourceHost = null;
    document.body.appendChild(panel);
    panel.classList.add('d-none');
    panel.classList.remove('source-variable-browser');
    clearInterval(timer);
    requestNumber++;
  }
  function checked(response) {
    if (!response.success) throw new Error(response.error && response.error.message || 'Report request failed.');
    return response.data;
  }
  function download(content, filename, type) {
    var raw = atob(content);
    var bytes = Uint8Array.from(raw, function (c) { return c.charCodeAt(0); });
    var url = URL.createObjectURL(new Blob([bytes], {type: type}));
    var link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
  }
  function reportDialog(title) {
    var dialog = document.createElement('dialog');
    dialog.setAttribute('aria-label', title);
    dialog.style.cssText = 'width: min(850px, 95vw);max-height:90vh;overflow:auto;border:1px solid #ccc;border-radius:8px;padding:1.5rem';
    var heading = document.createElement('h2');
    heading.className = 'h4';
    heading.textContent = title;
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'btn-close float-end';
    close.setAttribute('aria-label', 'Close report dialog');
    close.onclick = function () { dialog.close(); };
    dialog.append(close, heading);
    dialog.addEventListener('close', function () { dialog.remove(); });
    document.body.appendChild(dialog);
    dialog.showModal();
    return dialog;
  }
  function openRepository(options) {
    var project = options.getState().project;
    var dialog = reportDialog('Repository flow reports');
    var status = document.createElement('p');
    status.setAttribute('role', 'status');
    status.textContent = 'Reading interview files…';
    dialog.appendChild(status);
    options.apiPost('/api/reports/entrypoints', {project: project}).then(checked).then(function (data) {
      status.textContent = 'Choose the entrypoints to report. Each report follows its own includes. Suggested entrypoints are selected; included files can also be selected.';
      var choices = [];
      data.files.forEach(function (file) {
        var label = document.createElement('label');
        label.className = 'd-block';
        var input = document.createElement('input');
        input.type = 'checkbox';
        input.className = 'form-check-input me-2';
        input.checked = file.suggested;
        input.value = file.filename;
        choices.push(input);
        label.append(input, document.createTextNode(file.filename));
        dialog.appendChild(label);
      });
      var generate = document.createElement('button');
      generate.type = 'button';
      generate.className = 'btn btn-primary mt-3';
      generate.textContent = 'Download selected reports (ZIP)';
      dialog.appendChild(generate);
      generate.onclick = function () {
        var selected = choices.filter(function (input) { return input.checked; }).map(function (input) { return input.value; });
        if (!selected.length) { status.textContent = 'Choose at least one interview.'; return; }
        generate.disabled = true;
        // Close the native dialog before the editor's unsaved-changes modal.
        dialog.close();
        options.prepareSaved('generate repository reports').then(async function (ready) {
          if (!ready) return;
          var progress = reportDialog('Generating repository reports');
          var message = document.createElement('p');
          message.setAttribute('role', 'status');
          progress.appendChild(message);
          try {
            var reports = [];
            for (var filename of selected) {
              message.textContent = 'Rendering ' + filename + ' (' + (reports.length + 1) + ' of ' + selected.length + ')…';
              var scan = checked(await options.apiPost('/api/reports/scan', {project: project, filename: filename}));
              var steps = root.ALWeaverInterviewReport.expandNamedOrders(scan.order_steps, scan.named_order_steps);
              var reportOptions = options.previewOptions(scan.blocks.filter(function (block) { return block.sourceFile === filename; }));
              var opts = Object.assign({}, reportOptions, {continueLabel: reportOptions.continueButtonLabel, title: filename + ' — Interview flow report',
                subtitle: filename + (scan.warnings.length ? ' · ' + scan.warnings.join(' ') : ''),
                interview: root.ALWeaverScreenPreview.buildInterviewContext(scan.blocks)});
              reports.push({filename: filename, html: root.ALWeaverInterviewReport.buildReport(steps, scan.blocks, opts)});
            }
            var archive = checked(await options.apiPost('/api/reports/archive', {reports: reports}));
            download(archive.content, 'interview-flow-reports.zip', 'application/zip');
            message.textContent = reports.length + ' reports downloaded. Extract the ZIP and open index.html.';
          } catch (error) { message.textContent = error.message; }
        });
      };
    }).catch(function (error) { status.textContent = error.message; });
  }
  async function captureScreen(data, options) {
    if (typeof root.html2canvas !== 'function') throw new Error('The preview capture module did not load. Refresh the editor.');
    var frame = document.createElement('iframe');
    frame.setAttribute('sandbox', 'allow-same-origin');
    frame.setAttribute('aria-hidden', 'true');
    frame.style.cssText = 'position:fixed;left:-12000px;top:0;width:1100px;height:900px;border:0';
    // Screen text is sanitized by the shared preview renderer. The capture
    // frame cannot execute scripts, including any supplied by an interview.
    var html = root.ALWeaverScreenPreview.buildDocument(data, Object.assign({}, options, {widgetStyle: 'native'}));
    html = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
    try {
      await new Promise(function (resolve, reject) {
        var timeout = setTimeout(function () { reject(new Error('A screen preview timed out.')); }, 30000);
        frame.onload = function () { clearTimeout(timeout); resolve(); };
        frame.srcdoc = html;
        document.body.appendChild(frame);
      });
      var doc = frame.contentDocument;
      var links = Array.from(doc.querySelectorAll('link[rel="stylesheet"]'));
      if (links.slice(0, 2).some(function (link) { return !link.sheet; })) {
        throw new Error('The screen preview could not load its main stylesheets. Try again after restoring access to the server.');
      }
      await doc.fonts.ready;
      var height = Math.max(1, doc.body.scrollHeight);
      if (height > 12000) throw new Error('A screen is too tall for a workbook PNG preview. Shorten it or split it into screens.');
      var canvas = await root.html2canvas(doc.body, {backgroundColor: '#ffffff', scale: 1,
        width: 1100, height: height, windowWidth: 1100, windowHeight: height,
        useCORS: true, logging: false});
      return canvas.toDataURL('image/png');
    } finally { frame.remove(); }
  }
  function previewBytes(previews) {
    return Object.keys(previews).reduce(function (total, id) { return total + previews[id].length; }, 0);
  }
  async function scalePng(dataUrl, factor) {
    var image = new Image();
    image.src = dataUrl;
    await image.decode();
    var canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.width * factor));
    canvas.height = Math.max(1, Math.round(image.height * factor));
    var context = canvas.getContext('2d');
    context.imageSmoothingQuality = 'high';
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/png');
  }
  // Shrink every preview by the same factor until all of them fit the budget.
  async function fitPreviews(previews, budget, active) {
    var size = previewBytes(previews);
    if (size <= budget) return previews;
    var factor = Math.sqrt(budget / size) * 0.95;
    while (factor >= 0.3) {
      var scaled = {};
      for (var id of Object.keys(previews)) {
        if (!active()) return null;
        scaled[id] = await scalePng(previews[id], factor);
      }
      size = previewBytes(scaled);
      if (size <= budget) return scaled;
      factor *= Math.sqrt(budget / size) * 0.95;
    }
    throw new Error('These screen previews are too large for one workbook on this server. Open a smaller interview, or ask an administrator to raise "maximum content length".');
  }
  async function exportWording(options) {
    if (!await options.prepareSaved('export the wording workbook')) return;
    var state = options.getState();
    var payload = {project: state.project, filename: state.filename};
    var dialog = reportDialog('Export wording workbook');
    var status = document.createElement('p');
    status.setAttribute('role', 'status');
    status.textContent = 'Reading the interview…';
    dialog.appendChild(status);
    try {
      var prepared = checked(await options.apiPost('/api/reports/wording/prepare', payload));
      if (prepared.warnings.length) {
        var warning = document.createElement('p');
        warning.className = 'alert alert-warning';
        warning.textContent = prepared.warnings.join(' ');
        dialog.appendChild(warning);
      }
      var previews = {};
      var previewOptions = Object.assign({}, options.previewOptions(prepared.blocks.filter(function (block) { return block.sourceFile === (prepared.filename || payload.filename); })), {
        interview: root.ALWeaverScreenPreview.buildInterviewContext(prepared.blocks)});
      for (var i = 0; i < prepared.screens.length; i++) {
        if (!dialog.isConnected) return;
        var screen = prepared.screens[i];
        status.textContent = 'Capturing screen ' + (i + 1) + ' of ' + prepared.screens.length + '…';
        previews[screen.id] = await captureScreen(screen.data, previewOptions);
      }
      if (!dialog.isConnected) return;
      // The previews travel in one request, and the workbook holding them is
      // uploaded again on import, so both must fit the server's size limit.
      var budget = Math.floor((prepared.max_request_bytes || 16 * 1024 * 1024) * 0.85);
      previews = await fitPreviews(previews, budget, function () { return dialog.isConnected; });
      if (!previews) return;
      status.textContent = 'Building the workbook…';
      var exported = checked(await options.apiPost('/api/reports/wording/export', Object.assign({}, payload,
        {revisions: prepared.revisions, previews: previews})));
      download(exported.content, payload.filename.replace(/\.ya?ml$/i, '') + '-wording.xlsx',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
      status.textContent = 'Workbook downloaded. Give it to your reviewer, then use Import wording workbook to review and apply their edits.';
    } catch (error) { status.textContent = error.message; }
  }
  async function importWording(options) {
    if (!await options.prepareSaved('import a wording workbook')) return;
    var state = options.getState();
    var payload = {project: state.project, filename: state.filename};
    var dialog = reportDialog('Import wording workbook');
    var label = document.createElement('label');
    label.textContent = 'Edited XLSX workbook';
    var input = document.createElement('input');
    input.type = 'file';
    input.accept = '.xlsx';
    input.className = 'form-control';
    label.appendChild(input);
    var status = document.createElement('p');
    status.setAttribute('role', 'status');
    status.textContent = 'Choose the workbook exported for this interview. All changes are checked before any files are saved.';
    var review = document.createElement('button');
    review.className = 'btn btn-primary';
    review.type = 'button';
    review.textContent = 'Review changes';
    var resultBox = document.createElement('div');
    dialog.append(label, status, review, resultBox);
    input.onchange = function () { resultBox.replaceChildren(); review.hidden = false; };
    review.onclick = async function () {
      var file = input.files[0];
      if (!file) { status.textContent = 'Choose an XLSX workbook.'; return; }

      review.disabled = true;
      input.disabled = true;
      resultBox.replaceChildren();
      try {
        status.textContent = 'Checking workbook changes…';
        var upload = function (fields) {
          var form = new FormData();
          Object.keys(fields).forEach(function (key) { form.append(key, fields[key]); });
          form.append('workbook', file);
          return options.apiPost('/api/reports/wording/import', form, {json: false});
        };
        var proposal = checked(await upload(payload));
        status.textContent = proposal.changes.length + ' wording changes ready for review. No files have been changed.';
        if (!proposal.changes.length) return;
        review.hidden = true;
        var table = document.createElement('table');
        table.className = 'table table-bordered mt-3';
        var head = table.createTHead().insertRow();
        ['Screen / text part', 'Before', 'After'].forEach(function (text) {
          var th = document.createElement('th'); th.scope = 'col'; th.textContent = text; head.appendChild(th);
        });
        var tbody = table.createTBody();
        proposal.changes.forEach(function (change) {
          var row = tbody.insertRow();
          [change.filename + ' · ' + change.screen + ' · ' + change.part, change.original, change.edited].forEach(function (text) {
            var cell = row.insertCell(); cell.style.whiteSpace = 'pre-wrap'; cell.textContent = text;
          });
        });
        var apply = document.createElement('button');
        apply.type = 'button'; apply.className = 'btn btn-primary'; apply.textContent = 'Apply reviewed changes';
        apply.onclick = async function () {
          apply.disabled = true;
          try {
            checked(await upload(Object.assign({}, payload,
              {apply: 'true', review_digest: proposal.review_digest})));
            status.textContent = proposal.changes.length + ' wording changes saved.';
            await options.reload(payload.project, payload.filename);
          } catch (error) { status.textContent = error.message; review.hidden = false; }
        };
        resultBox.append(table, apply);
      } catch (error) { status.textContent = error.message; }
      finally { review.disabled = false; input.disabled = false; }
    };
  }
  root.ALWeaverReports = {closeSource: closeSource, refreshSourceSymbols: function () { if (sourceHost) render(); }, openVariables: openVariables, openRepository: openRepository,
    exportWording: exportWording, importWording: importWording, captureScreen: captureScreen,
    fitPreviews: fitPreviews};
})(globalThis);
