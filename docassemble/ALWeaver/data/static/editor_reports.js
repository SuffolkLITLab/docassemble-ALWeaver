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
    report = null;
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
      var previewOptions = Object.assign({}, options.previewOptions(prepared.blocks.filter(function (block) { return block.sourceFile === payload.filename; })), {
        interview: root.ALWeaverScreenPreview.buildInterviewContext(prepared.blocks)});
      for (var i = 0; i < prepared.screens.length; i++) {
        if (!dialog.isConnected) return;
        var screen = prepared.screens[i];
        status.textContent = 'Capturing screen ' + (i + 1) + ' of ' + prepared.screens.length + '…';
        previews[screen.id] = await captureScreen(screen.data, previewOptions);
      }
      if (!dialog.isConnected) return;
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
      if (file.size > 30 * 1024 * 1024) { status.textContent = 'Choose a workbook smaller than 30 MB.'; return; }
      review.disabled = true;
      input.disabled = true;
      resultBox.replaceChildren();
      try {
        status.textContent = 'Checking workbook changes…';
        var encoded = await new Promise(function (resolve, reject) {
          var reader = new FileReader();
          reader.onerror = function () { reject(new Error('Could not read the workbook.')); };
          reader.onload = function () { resolve(reader.result.split(',')[1]); };
          reader.readAsDataURL(file);
        });
        var request = Object.assign({}, payload, {content: encoded});
        var proposal = checked(await options.apiPost('/api/reports/wording/import', request));
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
            checked(await options.apiPost('/api/reports/wording/import', Object.assign({}, request,
              {apply: true, review_digest: proposal.review_digest})));
            status.textContent = proposal.changes.length + ' wording changes saved.';
            await options.reload(payload.project, payload.filename);
          } catch (error) { status.textContent = error.message; review.hidden = false; }
        };
        resultBox.append(table, apply);
      } catch (error) { status.textContent = error.message; }
      finally { review.disabled = false; input.disabled = false; }
    };
  }
  root.ALWeaverReports = {openVariables: openVariables, openRepository: openRepository,
    exportWording: exportWording, importWording: importWording, captureScreen: captureScreen};
})(globalThis);
