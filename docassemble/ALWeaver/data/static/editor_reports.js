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
  root.ALWeaverReports = {openVariables: openVariables};
})(globalThis);
