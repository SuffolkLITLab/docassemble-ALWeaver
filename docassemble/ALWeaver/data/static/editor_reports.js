/* Shared report controls. Analysis stays in interview_scan.py. */
(function (root) {
  'use strict';
  var bridge, report, requestNumber = 0, timer, lastKey;
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
  function render() {
    var box = el('variable-report-results');
    box.replaceChildren();
    if (!report) return;
    var filter = el('variable-report-filter').value.toLowerCase();
    var blocks = {};
    report.blocks.forEach(function (b) { blocks[b.scan_id] = b; });
    var notice = document.createElement('p');
    notice.className = 'small text-muted mt-2';
    notice.textContent = report.limitation + ' ' + report.warnings.join(' ');
    box.appendChild(notice);
    report.variables.forEach(function (v) {
      if (v.name.toLowerCase().indexOf(filter) === -1) return;
      var detail = document.createElement('details');
      var summary = document.createElement('summary');
      summary.textContent = v.name + (v.possibly_unused ? ' · possibly unused' : '');
      detail.appendChild(summary);
      v.definitions.forEach(function (id) { detail.appendChild(location(blocks[id], 'Defined')); });
      v.references.forEach(function (id) { detail.appendChild(location(blocks[id], 'Used')); });
      box.appendChild(detail);
    });
    report.blocks.filter(function (b) {
      return b.possibly_unreachable && (b.title + b.sourceFile).toLowerCase().indexOf(filter) !== -1;
    }).forEach(function (b) { box.appendChild(location(b, 'Possibly unreachable: ' + b.title)); });
  }
  function refresh() {
    var sequence = ++requestNumber;
    var state = bridge.getState();
    lastKey = key();
    el('variable-report-results').textContent = 'Reading interview…';
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
  function openVariables(options) {
    bridge = options;
    el('variable-report-rail').classList.remove('d-none');
    el('variable-report-close').onclick = function () {
      el('variable-report-rail').classList.add('d-none');
      clearInterval(timer);
      requestNumber++;
    };
    el('variable-report-refresh').onclick = refresh;
    el('variable-report-filter').oninput = render;
    clearInterval(timer);
    timer = setInterval(function () { if (lastKey !== key()) refresh(); }, 1500);
    refresh();
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
            var reportOptions = options.previewOptions();
            for (var filename of selected) {
              message.textContent = 'Rendering ' + filename + ' (' + (reports.length + 1) + ' of ' + selected.length + ')…';
              var scan = checked(await options.apiPost('/api/reports/scan', {project: project, filename: filename}));
              var steps = root.ALWeaverInterviewReport.expandNamedOrders(scan.order_steps, scan.named_order_steps);
              var opts = Object.assign({}, reportOptions, {title: filename + ' — Interview flow report',
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
  root.ALWeaverReports = {openVariables: openVariables, openRepository: openRepository};
})(globalThis);
