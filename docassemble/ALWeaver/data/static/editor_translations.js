/* Translation controls; ALDashboard owns extraction, drafting and validation. */
(function (root) {
  'use strict';
  function languageCodes(value) {
    var codes = Array.from(new Set(String(value || '').trim().split(/\s+/).filter(Boolean)));
    if (!codes.length || codes.some(function (code) { return !/^[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$/.test(code); })) throw new Error('Enter language codes such as es and fr, one per line.');
    return codes;
  }
  function open(bridge) {
    var dialog = document.createElement('dialog');
    dialog.className = 'p-4 rounded border';
    dialog.setAttribute('aria-label', 'Interview translations');
    dialog.innerHTML = '<h2 class="h4">Interview translations</h2>' +
      '<p id="translation-scope" role="status">Finding the interview root…</p>' +
      '<p>This includes the root interview and its included YAML files. Shared wording appears once per language. Separate interviews that are not included need their own translation workbooks.</p>' +
      '<p>Create workbooks for one or more languages, review their wording, then import them to connect them to this interview.</p>' +
      '<label for="translation-languages">Language codes, one per line</label><textarea id="translation-languages" class="form-control mb-2" rows="3" aria-describedby="translation-language-help">es</textarea>' +
      '<p id="translation-language-help" class="small">For example: es (Spanish), fr (French), ar (Arabic). Multiple languages download together as a ZIP file.</p>' +
      '<label class="d-block mb-2"><input type="checkbox" id="translation-ai"> Draft translations with AI</label>' +
      '<p class="small">AI drafting sends interview wording to the configured AI provider and may incur a charge. Review the machine translation before publishing.</p>' +
      '<button type="button" class="btn btn-primary" id="translation-generate">Download workbooks</button>' +
      '<hr><label for="translation-language">Flow report language code</label><input id="translation-language" class="form-control mb-2" value="es" aria-describedby="translation-report-help">' +
      '<p id="translation-report-help" class="small">Choose one language for this report. Import its reviewed workbook first.</p>' +
      '<button type="button" class="btn btn-outline-primary" id="translation-preview">Preview translated flow report</button>' +
      '<hr><label for="translation-upload">Reviewed translation workbooks (.xlsx)</label><input id="translation-upload" type="file" accept=".xlsx" multiple class="form-control mb-2">' +
      '<button type="button" class="btn btn-outline-primary" id="translation-import">Import and connect workbooks</button>' +
      '<p role="status" aria-live="polite" id="translation-status"></p>' +
      '<button type="button" class="btn btn-secondary" id="translation-close">Close</button>';
    document.body.appendChild(dialog);
    var trigger = document.activeElement;
    dialog.addEventListener('close', function () { dialog.remove(); if (trigger) trigger.focus(); });
    dialog.querySelector('#translation-close').onclick = function () { dialog.close(); };
    var status = dialog.querySelector('#translation-status');
    function checked(response) { if (!response.success) throw new Error(response.error.message); return response.data; }
    async function updateScope() {
      var state = bridge.getState();
      var scope = checked(await bridge.apiPost('/api/translations/scope', {project: state.project, filename: state.filename}));
      dialog.querySelector('#translation-scope').textContent = 'Interview: ' + scope.filename + ' (and its includes). Imported workbooks connect to ' + scope.filename + '.';
      return scope;
    }
    async function run(action) {
      var buttons = dialog.querySelectorAll('button');
      buttons.forEach(function (button) { button.disabled = true; });
      status.textContent = 'Working…';
      try {
        if (!await bridge.prepareSaved('work with translations')) { status.textContent = 'Cancelled.'; return; }
        await action(await updateScope());
      } catch (error) { status.textContent = error.message || String(error); }
      finally { buttons.forEach(function (button) { button.disabled = false; }); }
    }
    dialog.querySelector('#translation-generate').onclick = function () { return run(async function (body) {
      body.tr_langs = languageCodes(dialog.querySelector('#translation-languages').value);
      body.use_gpt = dialog.querySelector('#translation-ai').checked;
      var data = checked(await bridge.apiPost('/api/translations/generate', body));
      var item = data.translations[0];
      var bytes = Uint8Array.from(atob(data.archive_base64 || item.xlsx_base64), function (c) { return c.charCodeAt(0); });
      var url = URL.createObjectURL(new Blob([bytes], {type: data.archive_base64 ? 'application/zip' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));
      var link = document.createElement('a'); link.href = url; link.download = data.archive_filename || body.filename.replace(/\.ya?ml$/, '') + '_' + item.language + '.xlsx'; link.click();
      setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
      status.textContent = data.translations.length + ' workbook(s) downloaded. ' + data.translations.map(function (translation) { return translation.language + ': ' + translation.untranslated_segments + ' segments to translate or review'; }).join('; ') + '. Import the reviewed workbooks to connect them.';
    }); };
    dialog.querySelector('#translation-import').onclick = function () { return run(async function (body) {
      var files = Array.from(dialog.querySelector('#translation-upload').files);
      if (!files.length || files.some(function (file) { return !/\.xlsx$/i.test(file.name) || file.size > 20 * 1024 * 1024; })) throw new Error('Choose XLSX workbooks smaller than 20 MB each.');
      var completed = 0, blank = 0;
      try {
        for (var file of files) {
          status.textContent = 'Importing ' + (completed + 1) + ' of ' + files.length + ': ' + file.name;
          body.content = await new Promise(function (resolve, reject) { var reader = new FileReader(); reader.onload = function () { resolve(String(reader.result).split(',')[1]); }; reader.onerror = reject; reader.readAsDataURL(file); });
          var data = checked(await bridge.apiPost('/api/translations/import', body));
          body.expected_revision = data.revision;
          completed++;
          blank += data.validation.summary.empty_row_count;
        }
        status.textContent = completed + ' workbook(s) connected. ' + blank + ' blank translations will use the original wording.';
      } catch (error) {
        throw new Error(completed + ' of ' + files.length + ' workbooks connected. ' + (files[completed] ? files[completed].name + ': ' : '') + (error.message || String(error)) + ' Select only the remaining files to retry.');
      } finally {
        if (completed) await bridge.reload(body.project, body.filename);
      }
    }); };
    dialog.querySelector('#translation-preview').onclick = function () {
      var language = dialog.querySelector('#translation-language').value.trim();
      if (!/^[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$/.test(language)) { status.textContent = 'Enter a language code such as es.'; return; }
      dialog.close();
      dialog.remove();
      bridge.previewFlow(language);
    };
    dialog.showModal();
    updateScope().catch(function (error) { status.textContent = error.message || String(error); });
  }
  root.ALWeaverTranslations = {open: open, languageCodes: languageCodes};
})(typeof window !== 'undefined' ? window : globalThis);
