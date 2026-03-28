/* =============================================================================
   Docassemble Interview Editor — Client-side controller
   Communicates with /al/editor/api/* endpoints.
   Uses Monaco editor for YAML/Python code editing.
   ============================================================================= */

(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // Bootstrap data injected by the server
  // -------------------------------------------------------------------------
  var BOOT = window.__EDITOR_BOOTSTRAP__ || {};
  var API = BOOT.apiBasePath || '/al/editor';

  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------
  var state = {
    projects: BOOT.projects || [],
    project: (BOOT.projects && BOOT.projects[0]) || 'default',
    files: [],
    filename: null,
    blocks: [],
    metadataIndices: [],
    includeIndices: [],
    defaultSpIndices: [],
    orderIndices: [],
    orderSteps: [],
    rawYaml: '',
    selectedBlockId: null,
    currentView: 'interview',
    canvasMode: 'question',
    questionEditMode: 'preview',
    advancedOpen: false,
    jumpTarget: 'block',
    fullYamlTab: 'full',
    searchQuery: '',
    filterQuestionsOnly: true,
    dirty: false,
  };

  // -------------------------------------------------------------------------
  // Monaco management
  // -------------------------------------------------------------------------
  var _monacoReady = false;
  var _monacoEditors = {};

  function initMonaco(callback) {
    if (_monacoReady) { callback(); return; }
    if (typeof require === 'undefined' || !require.config) {
      // Monaco loader not available — fall back to textareas
      callback();
      return;
    }
    require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.47.0/min/vs' } });
    require(['vs/editor/editor.main'], function () {
      _monacoReady = true;
      callback();
    });
  }

  function disposeMonacoEditors() {
    Object.keys(_monacoEditors).forEach(function (key) {
      if (_monacoEditors[key]) {
        _monacoEditors[key].dispose();
        delete _monacoEditors[key];
      }
    });
  }

  function createMonacoEditor(containerId, value, language, opts) {
    if (!_monacoReady) return null;
    var container = document.getElementById(containerId);
    if (!container) return null;
    opts = opts || {};
    var editor = monaco.editor.create(container, {
      value: value || '',
      language: language || 'yaml',
      theme: 'vs',
      fontSize: 13,
      fontFamily: "ui-monospace, 'Cascadia Code', 'Fira Code', monospace",
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      lineNumbers: opts.lineNumbers !== false ? 'on' : 'off',
      wordWrap: 'on',
      automaticLayout: true,
      tabSize: 2,
      renderWhitespace: 'none',
      overviewRulerLanes: 0,
      hideCursorInOverviewRuler: true,
      scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8, alwaysConsumeMouseWheel: false },
    });
    _monacoEditors[containerId] = editor;
    if (opts.onChange) {
      editor.onDidChangeModelContent(opts.onChange);
    }
    return editor;
  }

  function getMonacoValue(containerId) {
    var ed = _monacoEditors[containerId];
    return ed ? ed.getValue() : '';
  }

  // -------------------------------------------------------------------------
  // DOM refs
  // -------------------------------------------------------------------------
  var $ = function (sel) { return document.querySelector(sel); };
  var $$ = function (sel) { return document.querySelectorAll(sel); };

  var projectSelect = $('#project-select');
  var fileSelect = $('#file-select');
  var searchInput = $('#search-input');
  var filterQuestionsCheckbox = $('#filter-questions-checkbox');
  var outlineList = $('#outline-list');
  var canvasContent = $('#canvas-content');

  // Known docassemble field datatypes
  var FIELD_TYPES = [
    'text', 'area', 'yesno', 'yesnowide', 'yesnoradio', 'yesnomaybe',
    'noyes', 'noyeswide', 'noyesradio', 'noyesmaybe',
    'number', 'integer', 'currency', 'date', 'time', 'datetime',
    'email', 'password', 'url',
    'file', 'files', 'camera',
    'radio', 'checkboxes', 'combobox', 'multiselect', 'dropdown',
    'range', 'object', 'object_radio', 'object_checkboxes',
    'ml', 'microphone',
  ];

  // -------------------------------------------------------------------------
  // Fetch helper
  // -------------------------------------------------------------------------
  function apiFetch(path, opts) {
    opts = opts || {};
    var url = API + path;
    return fetch(url, opts).then(function (res) { return res.json(); });
  }

  function apiGet(path) {
    return apiFetch(path, { credentials: 'same-origin' });
  }

  function apiPost(path, body) {
    return apiFetch(path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  // -------------------------------------------------------------------------
  // Escaping
  // -------------------------------------------------------------------------
  function esc(text) {
    var el = document.createElement('span');
    el.textContent = text || '';
    return el.innerHTML;
  }

  // Datatypes that accept a choices list
  var CHOICE_TYPES = ['radio', 'checkboxes', 'combobox', 'multiselect', 'dropdown'];

  function escapeYamlStr(str) {
    if (!str) return str;
    if (str.indexOf('\n') !== -1) {
      return '|\n  ' + str.replace(/\n/g, '\n  ');
    }
    if (/[:\#\{\}\[\],&*!>|'"%@`]/.test(str) || str.trim() !== str || str === '') {
      return '"' + str.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
    }
    return str;
  }

  function serializeQuestionToYaml() {
    var yaml = '';

    var idInput = document.getElementById('adv-id');
    if (idInput && idInput.value) yaml += 'id: ' + escapeYamlStr(idInput.value) + '\n';

    var qTitle = document.getElementById('q-title');
    if (qTitle && qTitle.value) yaml += 'question: ' + escapeYamlStr(qTitle.value) + '\n';

    var qSub = document.getElementById('q-subquestion');
    if (qSub && qSub.value) yaml += 'subquestion: ' + escapeYamlStr(qSub.value) + '\n';

    var contField = document.getElementById('q-continue-field');
    if (contField && contField.value) yaml += 'continue button field: ' + escapeYamlStr(contField.value) + '\n';

    var condToggle = document.getElementById('adv-enable-if');
    var condInput = document.getElementById('adv-if');
    if (condToggle && condToggle.checked && condInput && condInput.value.trim()) {
      yaml += 'if: ' + escapeYamlStr(condInput.value.trim()) + '\n';
    }

    var mandatoryBtn = document.getElementById('adv-mandatory-toggle');
    if (mandatoryBtn && mandatoryBtn.getAttribute('data-enabled') === 'true') {
      yaml += 'mandatory: True\n';
    }

    var rows = document.querySelectorAll('.editor-field-row');
    if (rows.length > 0) {
      yaml += 'fields:\n';
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var label = row.querySelector('[data-field-prop="label"]').value || 'Label';
        var type = row.querySelector('[data-field-prop="type"]').value;
        var variable = row.querySelector('[data-field-prop="variable"]').value;
        var choicesEl = document.getElementById('field-choices-' + i);

        yaml += '  - ' + escapeYamlStr(label) + ':';
        if (variable) {
          yaml += ' ' + escapeYamlStr(variable) + '\n';
        } else {
          yaml += '\n';
        }
        if (type && type !== 'text') yaml += '    datatype: ' + type + '\n';
        if (choicesEl && choicesEl.value.trim() && CHOICE_TYPES.indexOf(type) !== -1) {
          yaml += '    choices:\n';
          choicesEl.value.split('\n').forEach(function (c) {
            if (c.trim()) yaml += '      - ' + escapeYamlStr(c.trim()) + '\n';
          });
        }
      }
    }
    return yaml;
  }

  function syncQuestionMetaToData(blk) {
    if (!blk || blk.type !== 'question') return;
    if (!blk.data) blk.data = {};

    var idInput = document.getElementById('adv-id');
    if (idInput) {
      var nextId = idInput.value.trim();
      if (nextId) {
        blk.id = nextId;
        state.selectedBlockId = nextId;
      }
    }

    var qTitle = document.getElementById('q-title');
    if (qTitle) {
      blk.data.question = qTitle.value;
      blk.title = qTitle.value || 'Untitled question';
    }

    var qSub = document.getElementById('q-subquestion');
    if (qSub) {
      if (qSub.value) blk.data.subquestion = qSub.value;
      else delete blk.data.subquestion;
    }

    var contField = document.getElementById('q-continue-field');
    if (contField) {
      if (contField.value) blk.data['continue button field'] = contField.value;
      else delete blk.data['continue button field'];
    }

    var condToggle = document.getElementById('adv-enable-if');
    var condInput = document.getElementById('adv-if');
    if (condToggle && condToggle.checked && condInput && condInput.value.trim()) {
      blk.data['if'] = condInput.value.trim();
      blk.data._editor_if_enabled = true;
    } else if (condToggle && condToggle.checked) {
      blk.data._editor_if_enabled = true;
      delete blk.data['if'];
    } else {
      delete blk.data._editor_if_enabled;
      delete blk.data['if'];
    }

    var mandatoryBtn = document.getElementById('adv-mandatory-toggle');
    if (mandatoryBtn) {
      if (mandatoryBtn.getAttribute('data-enabled') === 'true') blk.data.mandatory = true;
      else delete blk.data.mandatory;
    }
  }

  function syncFieldsToData(blk) {
    if (!blk || blk.type !== 'question') return;
    var rows = document.querySelectorAll('.editor-field-row');
    syncQuestionMetaToData(blk);
    if (rows.length === 0) {
      blk.data.fields = [];
      return;
    }
    blk.data.fields = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var label = row.querySelector('[data-field-prop="label"]').value || 'Label';
      var type = row.querySelector('[data-field-prop="type"]').value;
      var variable = row.querySelector('[data-field-prop="variable"]').value;
      var rowIdx = row.getAttribute('data-field-idx');
      var choicesEl = document.getElementById('field-choices-' + rowIdx);

      if (!variable && type === 'text') {
        blk.data.fields.push(label);
        continue;
      }
      var inner = {};
      if (variable) inner.variable = variable;
      if (type && type !== 'text') inner.datatype = type;
      if (choicesEl && choicesEl.value.trim() && CHOICE_TYPES.indexOf(type) !== -1) {
        inner.choices = choicesEl.value.split('\n').map(function (c) { return c.trim(); }).filter(Boolean);
      }
      var fieldObj = {};
      if (Object.keys(inner).length === 1 && inner.variable) {
        fieldObj[label] = inner.variable;
      } else {
        if (!inner.variable) inner.variable = label;
        fieldObj[label] = inner;
      }
      blk.data.fields.push(fieldObj);
    }
  }

  // -------------------------------------------------------------------------
  // Project / file selectors
  // -------------------------------------------------------------------------
  function populateProjects() {
    projectSelect.innerHTML = '';
    state.projects.forEach(function (p) {
      var opt = document.createElement('option');
      opt.value = p;
      opt.textContent = p;
      if (p === state.project) opt.selected = true;
      projectSelect.appendChild(opt);
    });
  }

  function populateFiles() {
    fileSelect.innerHTML = '';
    if (state.files.length === 0) {
      var opt = document.createElement('option');
      opt.textContent = '(no files)';
      opt.disabled = true;
      fileSelect.appendChild(opt);
      return;
    }
    state.files.forEach(function (f) {
      var opt = document.createElement('option');
      opt.value = f.filename;
      opt.textContent = f.label || f.filename;
      if (state.filename === f.filename) opt.selected = true;
      fileSelect.appendChild(opt);
    });
  }

  function loadFiles() {
    return apiGet('/api/files?project=' + encodeURIComponent(state.project))
      .then(function (res) {
        if (!res.success) return;
        state.files = res.data.files || [];
        state.filename = state.files.length ? state.files[0].filename : null;
        populateFiles();
        if (state.files.length === 0) {
          state.blocks = [];
          renderOutline();
          renderCanvas();
          return;
        }
        return loadFile();
      });
  }

  function loadFile() {
    if (!state.filename) return Promise.resolve();
    return apiGet(
      '/api/file?project=' + encodeURIComponent(state.project) +
      '&filename=' + encodeURIComponent(state.filename)
    ).then(function (res) {
      if (!res.success) return;
      var d = res.data;
      state.blocks = d.blocks || [];
      state.metadataIndices = d.metadata_blocks || [];
      state.includeIndices = d.include_blocks || [];
      state.defaultSpIndices = d.default_screen_parts_blocks || [];
      state.orderIndices = d.order_blocks || [];
      state.orderSteps = d.order_steps || [];
      state.rawYaml = d.raw_yaml || '';
      state.dirty = false;
      state.selectedBlockId = (state.blocks.length) ? state.blocks[0].id : null;
      renderOutline();
      renderCanvas();
    });
  }

  // -------------------------------------------------------------------------
  // Outline
  // -------------------------------------------------------------------------
  function filteredBlocks() {
    var q = state.searchQuery.toLowerCase().trim();
    var filtered = state.blocks;
    if (state.filterQuestionsOnly) {
      filtered = filtered.filter(function (b) { return b.type === 'question'; });
    }
    if (!q) return filtered;
    return filtered.filter(function (b) {
      return [b.title, b.id, b.variable || '', b.yaml, (b.tags || []).join(' '), b.type]
        .join(' ').toLowerCase().indexOf(q) !== -1;
    });
  }

  function typeClass(type) {
    if (type === 'question') return 'editor-outline-type-q';
    if (type === 'code') return 'editor-outline-type-py';
    if (type === 'objects') return 'editor-outline-type-obj';
    if (type === 'metadata') return 'editor-outline-type-meta';
    if (type === 'includes') return 'editor-outline-type-inc';
    return 'editor-outline-type-oth';
  }

  function typeLabel(type) {
    if (type === 'question') return 'Q';
    if (type === 'code') return 'Py';
    if (type === 'objects') return 'Obj';
    if (type === 'metadata') return 'Meta';
    if (type === 'includes') return 'Inc';
    if (type === 'default_screen_parts') return 'Def';
    return type.charAt(0).toUpperCase() + type.slice(1, 3);
  }

  function renderOutline() {
    var blocks = filteredBlocks();
    var html = '';
    html += '<div class="editor-outline-insert"><button class="editor-outline-insert-btn" data-insert-pos="start">+</button></div>';
    blocks.forEach(function (block, i) {
      var active = state.selectedBlockId === block.id;
      var tl = typeLabel(block.type);
      var tc = typeClass(block.type);
      html += '<div class="editor-outline-item' + (active ? ' active' : '') + '" data-block-id="' + esc(block.id) + '">';
      html += '<div class="editor-outline-item-row">';
      if (active) html += '<div class="editor-outline-active-bar"></div>';
      html += '<div style="min-width:0"><div class="editor-outline-title">' + esc(block.title) + '</div>';
      if (block.variable) {
        html += '<div class="editor-outline-meta"><span>' + esc(block.variable) + '</span></div>';
      }
      html += '</div>';
      html += '<div class="editor-outline-type ' + tc + '">' + esc(tl) + '</div>';
      html += '</div></div>';
      html += '<div class="editor-outline-insert"><button class="editor-outline-insert-btn" data-insert-pos="after-' + i + '">+</button></div>';
    });
    outlineList.innerHTML = html;
  }

  // -------------------------------------------------------------------------
  // Canvas dispatcher
  // -------------------------------------------------------------------------
  function getSelectedBlock() {
    if (!state.selectedBlockId) return state.blocks[0] || null;
    for (var i = 0; i < state.blocks.length; i++) {
      if (state.blocks[i].id === state.selectedBlockId) return state.blocks[i];
    }
    return state.blocks[0] || null;
  }

  function renderCanvas() {
    disposeMonacoEditors();
    if (state.currentView !== 'interview') {
      renderSecondaryView();
      return;
    }
    if (state.canvasMode === 'new-project') {
      renderNewProject();
    } else if (state.canvasMode === 'full-yaml') {
      renderFullYaml();
    } else if (state.canvasMode === 'order-builder') {
      renderOrderBuilder();
    } else {
      renderBlockCanvas();
    }
  }

  // -------------------------------------------------------------------------
  // Block canvas — type-specific renderers
  // -------------------------------------------------------------------------
  function renderBlockCanvas() {
    var block = getSelectedBlock();
    if (!block) {
      canvasContent.innerHTML = '<div class="text-center py-5 text-muted"><p>No blocks in this file. Click + in the outline to add one.</p></div>';
      return;
    }

    if (block.type === 'question') {
      renderQuestionBlock(block);
    } else if (block.type === 'code') {
      renderCodeBlock(block);
    } else if (block.type === 'objects') {
      renderObjectsBlock(block);
    } else {
      renderGenericBlock(block);
    }
  }

  // --- Question block: rich field editor ---
  function renderQuestionBlock(block) {
    var data = block.data || {};
    var fields = data.fields || [];
    var isPreview = state.questionEditMode === 'preview';
    var html = '';

    // Header bar
    html += '<div class="editor-center-bar">';
    html += '<div class="editor-tiny">Question editor</div>';
    html += '<div class="d-flex gap-2">';
    html += '<button class="btn btn-sm btn-outline-secondary" id="toggle-edit-mode">' + (isPreview ? 'Edit YAML' : 'Visual editor') + '</button>';
    html += '<button class="btn btn-sm btn-primary" id="save-block-btn"' + (!state.dirty ? ' disabled' : '') + '>Save</button>';
    html += '</div></div>';

    html += '<div class="editor-shell">';

    if (isPreview) {
      html += '<div class="editor-card"><div class="editor-card-body editor-card-body-compact">';
      html += '<div class="editor-section-legend">Question</div>';
      html += '<div class="editor-form-group">';
      html += '<label class="editor-tiny" for="q-title">Question title</label>';
      html += '<input class="form-control editor-form-control" id="q-title" value="' + esc(data.question || '') + '">';
      html += '</div>';
      if (data.subquestion !== undefined) {
        html += '<div class="editor-form-group">';
        html += '<label class="editor-tiny" for="q-subquestion">Subquestion</label>';
        html += '<textarea class="form-control editor-form-control" id="q-subquestion" rows="4">' + esc(String(data.subquestion || '')) + '</textarea>';
        html += '</div>';
      }
      if (data['continue button field']) {
        html += '<div class="editor-form-group">';
        html += '<label class="editor-tiny" for="q-continue-field">Continue button field</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="q-continue-field" value="' + esc(data['continue button field']) + '">';
        html += '</div>';
      }
      html += '</div></div>';

      if (fields.length > 0) {
        html += '<div class="editor-card"><div class="editor-card-body editor-card-body-compact">';
        html += '<div class="editor-section-legend">Fields</div>';
        html += '<div class="editor-field-grid-header">';
        html += '<div>Label</div><div>Type</div><div>Variable</div><div></div>';
        html += '</div>';
        fields.forEach(function (f, fi) {
          var label = '', varName = '', dtype = 'text', choices = '';
          if (typeof f === 'object' && f !== null) {
            var keys = Object.keys(f);
            if (keys.length > 0) {
              label = keys[0];
              var val = f[keys[0]];
              if (typeof val === 'string') {
                varName = val;
              } else if (typeof val === 'object' && val !== null) {
                varName = val.variable || val.name || keys[0];
                dtype = val.datatype || val.input_type || 'text';
                if (val.choices && Array.isArray(val.choices)) {
                  choices = val.choices.map(function (c) {
                    if (typeof c === 'object') { var ck = Object.keys(c); return ck[0] + ': ' + c[ck[0]]; }
                    return String(c);
                  }).join('\n');
                }
              }
            }
          } else if (typeof f === 'string') {
            label = f;
          }
          var hasChoices = CHOICE_TYPES.indexOf(dtype) !== -1;
          html += '<div class="editor-field-row" data-field-idx="' + fi + '">';
          html += '<input class="form-control editor-form-control" data-field-prop="label" value="' + esc(label) + '" placeholder="Field label">';
          html += '<select class="form-select editor-form-control" data-field-prop="type">';
          FIELD_TYPES.forEach(function (t) {
            html += '<option value="' + t + '"' + (t === dtype ? ' selected' : '') + '>' + t + '</option>';
          });
          html += '</select>';
          html += '<input class="form-control editor-form-control font-monospace" data-field-prop="variable" value="' + esc(varName) + '" placeholder="variable_name">';
          html += '<div class="editor-field-actions"><button class="btn btn-outline-danger btn-sm" data-remove-field="' + fi + '" title="Remove field"><i class="fas fa-trash-alt" aria-hidden="true"></i><span class="visually-hidden">Remove field</span></button></div>';
          html += '</div>';
          if (hasChoices || choices) {
            html += '<div class="editor-field-choices-row" data-field-idx="' + fi + '">';
            html += '<label class="editor-tiny" for="field-choices-' + fi + '">Choices (one per line)</label>';
            html += '<textarea class="form-control editor-form-control editor-field-choices" id="field-choices-' + fi + '" rows="2">' + esc(choices) + '</textarea>';
            html += '</div>';
          }
        });
        html += '<div class="mt-2"><button class="btn btn-sm btn-outline-primary" id="add-field-btn">+ Add field</button></div>';
        html += '</div></div>';
      } else {
        html += '<div class="editor-card"><div class="editor-card-body editor-card-body-compact">';
        html += '<div class="editor-section-legend">Fields</div>';
        html += '<p class="text-muted small mb-2">No fields defined yet.</p>';
        html += '<button class="btn btn-sm btn-outline-primary" id="add-field-btn">+ Add field</button>';
        html += '</div></div>';
      }

      // Attachment info
      if (data.attachment || data.attachments) {
        html += '<div class="editor-card"><div class="editor-card-header">Attachment</div><div class="editor-card-body">';
        html += '<div class="editor-info-box">This block has an attachment. Edit in YAML mode for full control.</div>';
        html += '</div></div>';
      }

      // Advanced
      html += renderAdvancedPanel(block);

    } else {
      // YAML edit mode — Monaco
      html += '<div class="editor-card"><div class="editor-card-body">';
      html += '<div class="editor-monaco-container" id="block-yaml-monaco" style="height:500px"></div>';
      html += '</div></div>';
    }

    html += '</div>';
    canvasContent.innerHTML = html;

    if (!isPreview) {
      initMonaco(function () {
        createMonacoEditor('block-yaml-monaco', block.yaml, 'yaml', {
          onChange: function () { state.dirty = true; var b = document.getElementById('save-block-btn'); if (b) b.disabled = false; }
        });
      });
    }
  }

  // --- Code block: Monaco + advanced panel ---
  function renderCodeBlock(block) {
    var data = block.data || {};
    var codeText = data.code || '';
    var html = '';

    html += '<div class="editor-center-bar">';
    html += '<div>';
    html += '<span class="editor-pill editor-pill-muted">Code</span>';
    if (block.tags && block.tags.indexOf('mandatory') !== -1) html += ' <span class="editor-pill">mandatory</span>';
    html += '<div style="font-weight:600;font-size:16px;margin-top:6px">' + esc(block.title) + '</div>';
    html += '</div>';
    html += '<div class="d-flex gap-2">';
    html += '<button class="btn btn-sm btn-outline-secondary" id="toggle-edit-mode">Edit full YAML</button>';
    html += '<button class="btn btn-sm btn-primary" id="save-block-btn"' + (!state.dirty ? ' disabled' : '') + '>Save</button>';
    html += '</div></div>';

    html += '<div class="editor-shell">';

    if (state.questionEditMode === 'preview') {
      // Python editor via Monaco
      html += '<div class="editor-card"><div class="editor-card-header">Python code</div><div class="editor-card-body">';
      html += '<div class="editor-monaco-container" id="code-monaco" style="height:400px"></div>';
      html += '</div></div>';

      // Advanced: id, if, sets, only sets, need, etc.
      html += renderAdvancedPanel(block);
    } else {
      // Full YAML mode
      html += '<div class="editor-card"><div class="editor-card-body">';
      html += '<div class="editor-monaco-container" id="block-yaml-monaco" style="height:500px"></div>';
      html += '</div></div>';
    }

    html += '</div>';
    canvasContent.innerHTML = html;

    initMonaco(function () {
      if (state.questionEditMode === 'preview') {
        createMonacoEditor('code-monaco', codeText, 'python', {
          onChange: function () { state.dirty = true; var b = document.getElementById('save-block-btn'); if (b) b.disabled = false; }
        });
      } else {
        createMonacoEditor('block-yaml-monaco', block.yaml, 'yaml', {
          onChange: function () { state.dirty = true; var b = document.getElementById('save-block-btn'); if (b) b.disabled = false; }
        });
      }
    });
  }

  // --- Objects block: structured editor ---
  function renderObjectsBlock(block) {
    var data = block.data || {};
    var objects = data.objects || [];
    var html = '';

    html += '<div class="editor-center-bar">';
    html += '<div>';
    html += '<span class="editor-pill" style="background:#d1fae5;color:#065f46">Objects</span>';
    html += '<div style="font-weight:600;font-size:16px;margin-top:6px">' + esc(block.title) + '</div>';
    html += '</div>';
    html += '<div class="d-flex gap-2">';
    html += '<button class="btn btn-sm btn-outline-secondary" id="toggle-edit-mode">' + (state.questionEditMode === 'preview' ? 'Edit YAML' : 'Structured view') + '</button>';
    html += '<button class="btn btn-sm btn-primary" id="save-block-btn"' + (!state.dirty ? ' disabled' : '') + '>Save</button>';
    html += '</div></div>';

    html += '<div class="editor-shell">';

    if (state.questionEditMode === 'preview') {
      html += '<div class="editor-card"><div class="editor-card-header">Object declarations</div><div class="editor-card-body">';

      if (Array.isArray(objects) && objects.length > 0) {
        html += '<div style="display:grid;grid-template-columns:1fr 1fr auto;gap:8px;font-size:11px;letter-spacing:0.02em;color:var(--editor-muted);font-weight:600;padding:0 0 4px">';
        html += '<div>Variable name</div><div>Class (with .using())</div><div></div>';
        html += '</div>';

        objects.forEach(function (obj, oi) {
          var name = '', cls = '';
          if (typeof obj === 'object' && obj !== null) {
            var k = Object.keys(obj);
            if (k.length > 0) {
              name = k[0];
              cls = String(obj[k[0]] || '');
            }
          } else if (typeof obj === 'string') {
            // "- varname: ClassName" parsed as string shouldn't happen, but handle
            name = obj;
          }
          html += '<div class="editor-obj-row" data-obj-idx="' + oi + '">';
          html += '<input class="editor-obj-input" data-obj-prop="name" value="' + esc(name) + '" placeholder="variable_name">';
          html += '<input class="editor-obj-input" data-obj-prop="class" value="' + esc(cls) + '" placeholder="ClassName.using(...)">';
          html += '<div><button class="btn btn-sm btn-outline-danger" data-remove-obj="' + oi + '">&times;</button></div>';
          html += '</div>';
        });
      } else {
        html += '<p class="text-muted small mb-0">No objects declared.</p>';
      }

      html += '<div class="mt-2"><button class="btn btn-sm btn-outline-primary" id="add-obj-btn">+ Add object</button></div>';
      html += '</div></div>';

      html += renderAdvancedPanel(block);
    } else {
      html += '<div class="editor-card"><div class="editor-card-body">';
      html += '<div class="editor-monaco-container" id="block-yaml-monaco" style="height:400px"></div>';
      html += '</div></div>';
    }

    html += '</div>';
    canvasContent.innerHTML = html;

    if (state.questionEditMode !== 'preview') {
      initMonaco(function () {
        createMonacoEditor('block-yaml-monaco', block.yaml, 'yaml', {
          onChange: function () { state.dirty = true; var b = document.getElementById('save-block-btn'); if (b) b.disabled = false; }
        });
      });
    }
  }

  // --- Generic block (metadata, includes, event, attachment, etc.) ---
  function renderGenericBlock(block) {
    var html = '';

    html += '<div class="editor-center-bar">';
    html += '<div>';
    html += '<span class="editor-pill editor-pill-muted">' + esc(block.type) + '</span>';
    html += '<div style="font-weight:600;font-size:16px;margin-top:6px">' + esc(block.title) + '</div>';
    html += '</div>';
    html += '<div class="d-flex gap-2">';
    html += '<button class="btn btn-sm btn-primary" id="save-block-btn"' + (!state.dirty ? ' disabled' : '') + '>Save</button>';
    html += '</div></div>';

    html += '<div class="editor-shell">';
    html += '<div class="editor-card"><div class="editor-card-body">';
    html += '<div class="editor-monaco-container" id="block-yaml-monaco" style="height:500px"></div>';
    html += '</div></div>';
    html += '</div>';

    canvasContent.innerHTML = html;

    initMonaco(function () {
      createMonacoEditor('block-yaml-monaco', block.yaml, 'yaml', {
        onChange: function () { state.dirty = true; var b = document.getElementById('save-block-btn'); if (b) b.disabled = false; }
      });
    });
  }

  // --- Advanced panel (shared across block types) ---
  function renderAdvancedPanel(block) {
    var data = block.data || {};
    var ifEnabled = Boolean(data['if'] || data._editor_if_enabled);
    var mandatoryEnabled = Boolean(data.mandatory);
    var html = '';
    html += '<div class="editor-card" style="margin-top:12px">';
    html += '<button class="editor-advanced-toggle" id="toggle-advanced">Advanced options ' + (state.advancedOpen ? '&#8722;' : '+') + '</button>';
    if (state.advancedOpen) {
      html += '<div class="editor-advanced-body editor-advanced-grid">';

      // Block ID (editable)
      html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-id">Block ID</label>';
      html += '<input class="form-control editor-form-control font-monospace" id="adv-id" value="' + esc(block.id) + '"></div>';

      // Variable
      if (block.variable) {
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-variable">Variable</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-variable" value="' + esc(block.variable) + '" readonly></div>';
      }

      var ifVal = data['if'] || '';
      html += '<div class="editor-form-group editor-form-group-compact">';
      html += '<div class="form-check form-switch editor-inline-toggle">';
      html += '<input class="form-check-input" type="checkbox" id="adv-enable-if"' + (ifEnabled ? ' checked' : '') + '>';
      html += '<label class="form-check-label" for="adv-enable-if">Add condition</label>';
      html += '</div>';
      if (ifEnabled) {
        html += '<input class="form-control editor-form-control font-monospace mt-2" id="adv-if" value="' + esc(String(ifVal)) + '">';
      }
      html += '</div>';

      html += '<div class="editor-form-group editor-form-group-compact"><label class="editor-tiny" for="adv-mandatory-toggle">Mandatory</label>';
      html += '<button type="button" class="btn btn-sm ' + (mandatoryEnabled ? 'btn-primary' : 'btn-outline-secondary') + '" id="adv-mandatory-toggle" data-enabled="' + (mandatoryEnabled ? 'true' : 'false') + '">' + (mandatoryEnabled ? 'On' : 'Off') + '</button></div>';

      // sets / only sets
      if (data.sets || data['only sets']) {
        var setsVal = data.sets || data['only sets'] || '';
        if (Array.isArray(setsVal)) setsVal = setsVal.join(', ');
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-sets">' + (data['only sets'] ? 'Only sets' : 'Sets') + '</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-sets" value="' + esc(String(setsVal)) + '"></div>';
      }

      // need
      if (data.need) {
        var needVal = data.need;
        if (Array.isArray(needVal)) needVal = needVal.join(', ');
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-need">Need</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-need" value="' + esc(String(needVal)) + '"></div>';
      }

      // event
      if (data.event) {
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-event">Event</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-event" value="' + esc(String(data.event)) + '"></div>';
      }

      // generic object
      if (data['generic object']) {
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-generic-object">Generic object</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-generic-object" value="' + esc(String(data['generic object'])) + '"></div>';
      }

      html += '</div>';
    }
    html += '</div>';
    return html;
  }

  // -------------------------------------------------------------------------
  // Full YAML editor (Monaco)
  // -------------------------------------------------------------------------
  function renderFullYaml() {
    var html = '<div class="editor-full-yaml-shell">';
    html += '<div class="editor-full-yaml-header">';
    html += '<div><h2 style="font-weight:700;font-size:18px;margin:0">Full YAML</h2></div>';
    html += '<div class="d-flex gap-2">';
    html += '<button class="btn btn-sm btn-outline-secondary" id="back-to-question">Back to blocks</button>';
    html += '</div></div>';

    html += '<div class="editor-tab-bar">';
    html += '<button class="btn ' + (state.fullYamlTab === 'full' ? 'btn-primary' : 'btn-outline-secondary') + '" data-yaml-tab="full">Full YAML</button>';
    html += '<button class="btn ' + (state.fullYamlTab === 'order' ? 'btn-primary' : 'btn-outline-secondary') + '" data-yaml-tab="order">Interview order</button>';
    html += '<button class="btn ' + (state.fullYamlTab === 'metadata' ? 'btn-primary' : 'btn-outline-secondary') + '" data-yaml-tab="metadata">Metadata</button>';
    html += '</div>';

    html += '<div class="editor-card"><div class="editor-card-body">';
    var editorId = 'full-yaml-monaco';
    html += '<div class="editor-monaco-container" id="' + editorId + '" style="height:600px"></div>';
    html += '</div></div>';

    html += '<div class="d-flex justify-content-end"><button class="btn btn-primary" id="save-full-yaml">Save</button></div>';
    html += '</div>';
    canvasContent.innerHTML = html;

    var content = '';
    if (state.fullYamlTab === 'full') {
      content = state.rawYaml;
    } else if (state.fullYamlTab === 'order') {
      if (state.orderIndices.length && state.blocks[state.orderIndices[0]]) {
        content = state.blocks[state.orderIndices[0]].yaml;
      }
    } else {
      var parts = [];
      state.metadataIndices.forEach(function (idx) { if (state.blocks[idx]) parts.push(state.blocks[idx].yaml); });
      state.includeIndices.forEach(function (idx) { if (state.blocks[idx]) parts.push(state.blocks[idx].yaml); });
      state.defaultSpIndices.forEach(function (idx) { if (state.blocks[idx]) parts.push(state.blocks[idx].yaml); });
      content = parts.join('\n---\n') || '# No metadata blocks found';
    }

    initMonaco(function () {
      createMonacoEditor(editorId, content, 'yaml');
    });
  }

  // -------------------------------------------------------------------------
  // Order builder
  // -------------------------------------------------------------------------
  function renderOrderBuilder() {
    var html = '<div class="editor-order-shell">';
    html += '<div class="editor-center-bar">';
    html += '<div><h2 style="font-weight:700;font-size:18px;margin:0">Interview Order</h2></div>';
    html += '<div class="d-flex gap-2">';
    html += '<button class="btn btn-sm btn-outline-secondary" id="generate-draft-order">Auto-generate</button>';
    html += '<button class="btn btn-sm btn-outline-secondary" id="order-to-raw">View YAML</button>';
    html += '</div></div>';

    html += '<div class="editor-order-grid">';

    // Steps list
    html += '<div class="editor-card"><div class="editor-card-header d-flex justify-content-between align-items-center">';
    html += '<span>Steps</span>';
    html += '<div class="editor-order-actions">';
    html += '<button class="btn btn-sm btn-outline-primary" data-add-step="screen">+ Screen</button>';
    html += '<button class="btn btn-sm btn-outline-secondary" data-add-step="gather">+ Gather</button>';
    html += '<button class="btn btn-sm btn-outline-secondary" data-add-step="section">+ Section</button>';
    html += '<button class="btn btn-sm btn-outline-secondary" data-add-step="progress">+ Progress</button>';
    html += '</div></div>';

    html += '<div class="editor-card-body"><div class="editor-order-timeline" id="order-sortable-list">';
    state.orderSteps.forEach(function (step, i) {
      var kindLabel = step.label || step.kind;
      var detail = step.invoke || step.value || step.code || '';
      // Strip "ask " prefix — redundant
      if (detail.substring(0, 4) === 'ask ') detail = detail.substring(4);
      // Don't repeat summary in detail
      if (detail === step.summary) detail = '';

      html += '<div class="editor-order-step" data-step-index="' + i + '">';
      html += '<div class="editor-order-step-top">';
      html += '<span class="drag-handle" title="Drag to reorder">&#9776;</span>';
      html += '<div style="flex:1;min-width:0;display:flex;align-items:center;gap:6px">';
      if (kindLabel.toLowerCase() !== 'screen') {
        html += '<span class="badge bg-secondary" style="font-size:10px">' + esc(kindLabel) + '</span>';
      }
      html += '<span style="font-weight:500;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(step.summary) + '</span>';
      if (detail) {
        html += '<code class="text-muted" style="font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(detail) + '</code>';
      }
      html += '</div>';
      html += '<div class="d-flex gap-1">';
      html += '<button class="btn btn-sm btn-outline-secondary py-0 px-1" data-step-action="edit" data-step-idx="' + i + '" title="Edit">&#9998;</button>';
      html += '<button class="btn btn-sm btn-outline-danger py-0 px-1" data-step-action="remove" data-step-idx="' + i + '" title="Remove">&times;</button>';
      html += '</div>';
      html += '</div></div>';
    });
    if (state.orderSteps.length === 0) {
      html += '<p class="text-muted small mb-0">No order steps. Click "Auto-generate" to create a draft.</p>';
    }
    html += '</div></div></div>';

    // Right: generated code
    html += '<div>';
    html += '<div class="editor-card"><div class="editor-card-header">Generated code</div><div class="editor-card-body">';
    var orderYaml = '';
    if (state.orderIndices.length && state.blocks[state.orderIndices[0]]) {
      orderYaml = state.blocks[state.orderIndices[0]].yaml;
    }
    html += '<div class="editor-monaco-container" id="order-fallback-monaco" style="height:300px"></div>';
    html += '</div></div>';
    html += '<div class="mt-2 d-flex justify-content-end"><button class="btn btn-primary" id="save-order-steps">Save order</button></div>';
    html += '</div>';

    html += '</div></div>';
    canvasContent.innerHTML = html;

    // Initialize drag-to-reorder via SortableJS
    var sortableEl = document.getElementById('order-sortable-list');
    if (sortableEl && typeof Sortable !== 'undefined') {
      Sortable.create(sortableEl, {
        handle: '.drag-handle',
        animation: 150,
        onEnd: function (evt) {
          var moved = state.orderSteps.splice(evt.oldIndex, 1)[0];
          state.orderSteps.splice(evt.newIndex, 0, moved);
          renderOrderBuilder();
        }
      });
    }

    initMonaco(function () {
      createMonacoEditor('order-fallback-monaco', orderYaml, 'yaml', { lineNumbers: false });
    });
  }

  // -------------------------------------------------------------------------
  // New project (with file upload / "I'm feeling lucky")
  // -------------------------------------------------------------------------
  var _uploadedFiles = [];

  function renderNewProject() {
    _uploadedFiles = [];
    var html = '<div class="editor-new-project-shell">';

    // Header
    html += '<div class="editor-card"><div class="editor-card-body">';
    html += '<div class="d-flex justify-content-between align-items-start flex-wrap gap-3">';
    html += '<div>';
    html += '<h2 style="font-weight:700;font-size:18px;margin:0 0 6px">Create a new project</h2>';
    html += '<p class="text-muted small mb-0" style="max-width:600px">Upload a PDF or DOCX template and Weaver will generate a scaffolded interview draft, or start with a blank project.</p>';
    html += '</div>';
    html += '<div class="d-flex gap-2">';
    html += '<button class="btn btn-sm btn-outline-secondary" id="cancel-new-project">Cancel</button>';
    html += '<button class="btn btn-sm btn-primary" id="create-project-btn">Create project</button>';
    html += '</div></div>';
    html += '</div></div>';

    // File upload zone
    html += '<div class="editor-card"><div class="editor-card-header">Template files (optional)</div><div class="editor-card-body">';
    html += '<div class="editor-dropzone" id="upload-dropzone">';
    html += '<div class="editor-dropzone-icon">&#128196;</div>';
    html += '<div style="font-weight:600">Drag &amp; drop PDF or DOCX files here</div>';
    html += '<div class="text-muted small mt-1">or click to browse</div>';
    html += '<input type="file" id="upload-file-input" multiple accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" style="display:none">';
    html += '</div>';
    html += '<div id="upload-file-list" class="mt-2"></div>';
    html += '</div></div>';

    // Project form
    html += '<div class="editor-card"><div class="editor-card-header">Project settings</div><div class="editor-card-body">';
    html += '<div class="d-grid gap-3">';
    html += '<div><label class="editor-tiny" for="new-project-name">Project name</label><input class="form-control form-control-sm mt-1" id="new-project-name" value="NewProject"></div>';
    html += '<div><label class="editor-tiny" for="new-project-notes">Notes for Weaver (optional)</label>';
    html += '<textarea class="form-control form-control-sm mt-1" id="new-project-notes" rows="3" placeholder="E.g. desired title, jurisdiction, special instructions"></textarea></div>';
    html += '</div></div></div>';

    // Progress
    html += '<div class="editor-card d-none" id="upload-progress-card"><div class="editor-card-body">';
    html += '<div class="editor-tiny">Generating&hellip;</div>';
    html += '<div class="progress mt-2"><div class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" style="width:100%"></div></div>';
    html += '<div class="text-muted small mt-2" id="upload-progress-msg">Analyzing templates. This may take a moment.</div>';
    html += '</div></div>';

    html += '</div>';
    canvasContent.innerHTML = html;
    _initDropzone();
  }

  // -------------------------------------------------------------------------
  // Dropzone helpers
  // -------------------------------------------------------------------------
  function _initDropzone() {
    var dropzone = document.getElementById('upload-dropzone');
    var fileInput = document.getElementById('upload-file-input');
    if (!dropzone || !fileInput) return;
    dropzone.addEventListener('click', function () { fileInput.click(); });
    fileInput.addEventListener('change', function () { _addFiles(fileInput.files); fileInput.value = ''; });
    dropzone.addEventListener('dragover', function (e) { e.preventDefault(); dropzone.classList.add('editor-dropzone-active'); });
    dropzone.addEventListener('dragleave', function () { dropzone.classList.remove('editor-dropzone-active'); });
    dropzone.addEventListener('drop', function (e) { e.preventDefault(); dropzone.classList.remove('editor-dropzone-active'); _addFiles(e.dataTransfer.files); });
  }

  function _addFiles(fileList) {
    if (!fileList) return;
    var validExts = ['.pdf', '.docx'];
    for (var i = 0; i < fileList.length; i++) {
      var f = fileList[i];
      var ext = (f.name || '').toLowerCase().replace(/^.*(\.[^.]+)$/, '$1');
      if (validExts.indexOf(ext) === -1) continue;
      var isDupe = _uploadedFiles.some(function (existing) { return existing.name === f.name && existing.size === f.size; });
      if (!isDupe) _uploadedFiles.push(f);
    }
    _renderFileList();
  }

  function _renderFileList() {
    var container = document.getElementById('upload-file-list');
    if (!container) return;
    if (_uploadedFiles.length === 0) { container.innerHTML = ''; return; }
    var html = '<div class="d-flex flex-wrap gap-2">';
    _uploadedFiles.forEach(function (f, idx) {
      var sizeKb = (f.size / 1024).toFixed(1);
      html += '<div class="editor-upload-chip"><span>' + esc(f.name) + ' <span class="text-muted">(' + sizeKb + ' KB)</span></span>';
      html += '<button class="editor-upload-chip-remove" data-remove-upload="' + idx + '">&times;</button></div>';
    });
    html += '</div>';
    container.innerHTML = html;
  }

  function _showUploadError(message) {
    var progressCard = document.getElementById('upload-progress-card');
    if (progressCard) {
      progressCard.classList.remove('d-none');
      progressCard.innerHTML = '<div class="editor-card-body"><div class="text-danger small fw-bold">Error</div><div class="mt-1">' + esc(message) + '</div></div>';
    }
    var btn = document.getElementById('create-project-btn');
    if (btn) btn.disabled = false;
  }

  // -------------------------------------------------------------------------
  // Secondary view placeholder
  // -------------------------------------------------------------------------
  function renderSecondaryView() {
    var label = state.currentView.charAt(0).toUpperCase() + state.currentView.slice(1);
    canvasContent.innerHTML =
      '<div class="editor-secondary-center"><div class="editor-secondary-card">' +
      '<h2 style="font-weight:700">' + esc(label) + '</h2>' +
      '<p class="text-muted mt-2">Switch to the Interview tab to edit question blocks.</p>' +
      '</div></div>';
  }

  // -------------------------------------------------------------------------
  // Event delegation
  // -------------------------------------------------------------------------
  document.addEventListener('click', function (e) {
    var target = e.target;

    // View tabs
    if (target.matches('.editor-top-tab')) {
      state.currentView = target.getAttribute('data-view');
      $$('.editor-top-tab').forEach(function (t) { t.classList.remove('active'); });
      target.classList.add('active');
      if (state.currentView === 'interview') state.canvasMode = 'question';
      renderCanvas();
      return;
    }

    // Jump targets
    if (target.matches('.editor-jump-item')) {
      var jump = target.getAttribute('data-jump');
      $$('.editor-jump-item').forEach(function (j) { j.classList.remove('active'); });
      target.classList.add('active');
      state.jumpTarget = jump;
      if (jump === 'order') {
        state.canvasMode = 'order-builder';
      } else if (jump === 'metadata' || jump === 'includes' || jump === 'defaults') {
        state.canvasMode = 'full-yaml';
        state.fullYamlTab = 'metadata';
      } else {
        state.canvasMode = 'question';
      }
      state.currentView = 'interview';
      renderCanvas();
      return;
    }

    // Outline block selection
    var outlineItem = target.closest('.editor-outline-item');
    if (outlineItem) {
      state.selectedBlockId = outlineItem.getAttribute('data-block-id');
      state.canvasMode = 'question';
      state.questionEditMode = 'preview';
      state.advancedOpen = false;
      renderOutline();
      renderCanvas();
      return;
    }

    // Outline insert
    if (target.matches('.editor-outline-insert-btn')) {
      bootstrap.Modal.getOrCreateInstance(document.getElementById('insert-modal')).show();
      return;
    }

    // Top action buttons
    if (target.id === 'btn-new-project') { state.canvasMode = 'new-project'; state.currentView = 'interview'; renderCanvas(); return; }
    if (target.id === 'btn-full-yaml') { state.canvasMode = state.canvasMode === 'full-yaml' ? 'question' : 'full-yaml'; state.currentView = 'interview'; renderCanvas(); return; }
    if (target.id === 'btn-order-builder') { state.canvasMode = 'order-builder'; state.currentView = 'interview'; renderCanvas(); return; }
    if (target.id === 'btn-preview-interview') {
      if (!state.filename) return;
      apiGet('/api/preview-url?project=' + encodeURIComponent(state.project) + '&filename=' + encodeURIComponent(state.filename))
        .then(function (res) { if (res.success && res.data && res.data.url) window.open(res.data.url, '_blank'); });
      return;
    }

    // Toggle edit mode (shared by question / code / objects)
    if (target.id === 'toggle-edit-mode') {
      state.questionEditMode = state.questionEditMode === 'preview' ? 'yaml' : 'preview';
      renderCanvas();
      return;
    }
    if (target.id === 'toggle-advanced') {
      state.advancedOpen = !state.advancedOpen;
      renderCanvas();
      return;
    }
    if (target.id === 'adv-mandatory-toggle') {
      var enabled = target.getAttribute('data-enabled') === 'true';
      target.setAttribute('data-enabled', enabled ? 'false' : 'true');
      target.classList.toggle('btn-primary', !enabled);
      target.classList.toggle('btn-outline-secondary', enabled);
      target.textContent = enabled ? 'Off' : 'On';
      state.dirty = true;
      return;
    }

    // Save block

    if (target.id === 'save-block-btn') {
      var block = getSelectedBlock();
      if (!block) return;
      var yamlVal = '';
      if (state.questionEditMode === 'preview' && block.type === 'question') {
        yamlVal = serializeQuestionToYaml();
      } else {
        yamlVal = getMonacoValue('block-yaml-monaco');
        if (!yamlVal && _monacoEditors['code-monaco']) {
          yamlVal = block.yaml;
        }
        if (!yamlVal) yamlVal = block.yaml;
      }

      apiPost('/api/block', {
        project: state.project,
        filename: state.filename,
        block_id: block.id,
        block_yaml: yamlVal,
      }).then(function (res) {
        if (res.success) {
          state.blocks = res.data.blocks;
          state.dirty = false;
          renderOutline();
          renderCanvas();
        }
      });
      return;
    }

    // Full YAML tabs
    if (target.matches('[data-yaml-tab]')) { state.fullYamlTab = target.getAttribute('data-yaml-tab'); renderCanvas(); return; }
    if (target.id === 'back-to-question') { state.canvasMode = 'question'; renderCanvas(); return; }
    if (target.id === 'save-full-yaml') {
      var yamlContent = getMonacoValue('full-yaml-monaco');
      if (!yamlContent) return;
      apiPost('/api/file', { project: state.project, filename: state.filename, content: yamlContent })
        .then(function (res) { if (res.success) { state.dirty = false; loadFile(); } });
      return;
    }

    // Order builder
    if (target.id === 'generate-draft-order') {
      apiPost('/api/draft-order', { project: state.project, filename: state.filename })
        .then(function (res) { if (res.success) { state.orderSteps = res.data.steps; renderCanvas(); } });
      return;
    }
    if (target.id === 'order-to-raw') { state.canvasMode = 'full-yaml'; state.fullYamlTab = 'order'; renderCanvas(); return; }
    if (target.id === 'save-order-steps') {
      apiPost('/api/order', { project: state.project, filename: state.filename, steps: state.orderSteps })
        .then(function (res) { if (res.success) loadFile(); });
      return;
    }

    // Step actions
    if (target.matches('[data-step-action]')) {
      var action = target.getAttribute('data-step-action');
      var idx = parseInt(target.getAttribute('data-step-idx'), 10);
      if (action === 'up' && idx > 0) { var t1 = state.orderSteps[idx]; state.orderSteps[idx] = state.orderSteps[idx - 1]; state.orderSteps[idx - 1] = t1; renderCanvas(); }
      else if (action === 'down' && idx < state.orderSteps.length - 1) { var t2 = state.orderSteps[idx]; state.orderSteps[idx] = state.orderSteps[idx + 1]; state.orderSteps[idx + 1] = t2; renderCanvas(); }
      else if (action === 'remove') { state.orderSteps.splice(idx, 1); renderCanvas(); }
      else if (action === 'preview') { showOrderPreview(state.orderSteps[idx]); }
      else if (action === 'edit') { showOrderEdit(state.orderSteps[idx], idx); }
      return;
    }

    // Add step
    if (target.matches('[data-add-step]')) {
      var kind = target.getAttribute('data-add-step');
      var newStep = { id: 'step-new-' + Date.now(), kind: kind, label: kind, summary: 'New ' + kind + ' step' };
      if (kind === 'screen' || kind === 'gather') newStep.invoke = '';
      else if (kind === 'section') newStep.value = 'New section';
      else if (kind === 'progress') newStep.value = '50';
      state.orderSteps.push(newStep);
      renderCanvas();
      return;
    }

    // Add field
    if (target.id === 'add-field-btn') {
      var blk = getSelectedBlock();
      if (blk && blk.data) {
        syncFieldsToData(blk);
        if (!blk.data.fields) blk.data.fields = [];
        blk.data.fields.push({ 'New field': 'new_variable' });
        state.dirty = true;
        renderCanvas();
      }
      return;
    }

    // Remove field
    if (target.matches('[data-remove-field]')) {
      var fi = parseInt(target.getAttribute('data-remove-field'), 10);
      var blk2 = getSelectedBlock();
      if (blk2 && blk2.data && blk2.data.fields) {
        syncFieldsToData(blk2);
        blk2.data.fields.splice(fi, 1);
        state.dirty = true;
        renderCanvas();
      }
      return;
    }

    // Add object
    if (target.id === 'add-obj-btn') {
      var blk3 = getSelectedBlock();
      if (blk3 && blk3.data) {
        if (!blk3.data.objects) blk3.data.objects = [];
        blk3.data.objects.push({ 'new_object': 'DAObject' });
        state.dirty = true;
        renderCanvas();
      }
      return;
    }

    // Remove object
    if (target.matches('[data-remove-obj]')) {
      var oi = parseInt(target.getAttribute('data-remove-obj'), 10);
      var blk4 = getSelectedBlock();
      if (blk4 && blk4.data && blk4.data.objects) {
        blk4.data.objects.splice(oi, 1);
        state.dirty = true;
        renderCanvas();
      }
      return;
    }

    // New project
    if (target.id === 'cancel-new-project') { state.canvasMode = 'question'; _uploadedFiles = []; renderCanvas(); return; }

    // Remove upload chip
    if (target.matches('[data-remove-upload]') || target.closest('[data-remove-upload]')) {
      var removeBtn = target.matches('[data-remove-upload]') ? target : target.closest('[data-remove-upload]');
      var removeIdx = parseInt(removeBtn.getAttribute('data-remove-upload'), 10);
      _uploadedFiles.splice(removeIdx, 1);
      _renderFileList();
      return;
    }

    // Create project
    if (target.id === 'create-project-btn') {
      var nameInput = document.getElementById('new-project-name');
      var notesInput = document.getElementById('new-project-notes');
      var projectName = nameInput ? nameInput.value : 'NewProject';
      var notes = notesInput ? notesInput.value : '';
      var progressCard = document.getElementById('upload-progress-card');
      if (progressCard) progressCard.classList.remove('d-none');
      target.disabled = true;

      if (_uploadedFiles.length > 0) {
        var formData = new FormData();
        formData.append('project_name', projectName);
        formData.append('generation_notes', notes);
        _uploadedFiles.forEach(function (f) { formData.append('files', f, f.name); });
        fetch(API + '/api/new-project', { method: 'POST', credentials: 'same-origin', body: formData })
          .then(function (res) { return res.json(); })
          .then(function (res) {
            if (progressCard) progressCard.classList.add('d-none');
            if (res.success) {
              state.project = res.data.project;
              state.filename = res.data.filename;
              state.canvasMode = 'question';
              _uploadedFiles = [];
              apiGet('/api/projects').then(function (r) { if (r.success) state.projects = r.data.projects; populateProjects(); loadFiles(); });
            } else { _showUploadError(res.error ? res.error.message : 'Unknown error'); }
          })
          .catch(function (err) { if (progressCard) progressCard.classList.add('d-none'); _showUploadError(err.message || 'Network error'); });
      } else {
        apiPost('/api/new-project', { project_name: projectName, generation_notes: notes })
          .then(function (res) {
            if (progressCard) progressCard.classList.add('d-none');
            if (res.success) {
              state.project = res.data.project;
              state.filename = res.data.filename;
              state.canvasMode = 'question';
              apiGet('/api/projects').then(function (r) { if (r.success) state.projects = r.data.projects; populateProjects(); loadFiles(); });
            } else { _showUploadError(res.error ? res.error.message : 'Unknown error'); }
          });
      }
      return;
    }
  });

  // Track dirty state from inline inputs
  document.addEventListener('input', function (e) {
    var target = e.target;
    if (target.matches('[data-field-prop]') || target.matches('.editor-field-choices') ||
        target.matches('.editor-obj-input') || target.id === 'q-title' || target.id === 'q-subquestion' ||
        target.id === 'q-continue-field' || target.id === 'adv-id' || target.id === 'adv-if') {
      state.dirty = true;
      var saveBtn = document.getElementById('save-block-btn');
      if (saveBtn) saveBtn.disabled = false;
    }
  });

  document.addEventListener('change', function (e) {
    var target = e.target;
    if (target.matches('[data-field-prop="type"]')) {
      var blk = getSelectedBlock();
      if (blk) {
        syncFieldsToData(blk);
        state.dirty = true;
        renderCanvas();
      }
      return;
    }
    if (target.id === 'adv-enable-if') {
      var blk2 = getSelectedBlock();
      if (blk2) {
        syncFieldsToData(blk2);
        state.dirty = true;
        renderCanvas();
      }
      return;
    }
  });

  // -------------------------------------------------------------------------
  // Order step modals
  // -------------------------------------------------------------------------
  function showOrderPreview(step) {
    if (!step) return;
    document.getElementById('order-preview-label').textContent = step.label || step.kind;
    document.getElementById('order-preview-summary').textContent = step.summary;
    var body = '<div class="editor-info-box">' + esc(step.invoke || step.value || step.code || step.summary) + '</div>';
    if (step.invoke) {
      for (var i = 0; i < state.blocks.length; i++) {
        if (state.blocks[i].variable === step.invoke) {
          body += '<div class="editor-info-box mt-2"><strong>' + esc(state.blocks[i].title) + '</strong>';
          if (state.blocks[i].data && state.blocks[i].data.subquestion) {
            body += '<div class="text-muted small mt-1">' + esc(String(state.blocks[i].data.subquestion)) + '</div>';
          }
          body += '</div>';
          break;
        }
      }
    }
    document.getElementById('order-preview-body').innerHTML = body;
    bootstrap.Modal.getOrCreateInstance(document.getElementById('order-preview-modal')).show();
  }

  var _editStepIndex = -1;
  function showOrderEdit(step, idx) {
    if (!step) return;
    _editStepIndex = idx;
    document.getElementById('order-edit-title').textContent = step.label || step.kind;
    var body = '';
    if (step.kind === 'screen' || step.kind === 'gather' || step.kind === 'function') {
      body += '<div class="mb-3"><label class="editor-tiny">Variable / expression</label>';
      body += '<input class="form-control form-control-sm mt-1 font-monospace" id="order-edit-invoke" value="' + esc(step.invoke || '') + '"></div>';
    }
    if (step.kind === 'section') {
      body += '<div class="mb-3"><label class="editor-tiny">Section name</label>';
      body += '<input class="form-control form-control-sm mt-1" id="order-edit-value" value="' + esc(step.value || '') + '"></div>';
    }
    if (step.kind === 'progress') {
      body += '<div class="mb-3"><label class="editor-tiny">Progress value</label>';
      body += '<input class="form-control form-control-sm mt-1" id="order-edit-value" value="' + esc(step.value || '') + '"></div>';
    }
    if (step.kind === 'raw') {
      body += '<div class="mb-3"><label class="editor-tiny">Python code</label>';
      body += '<textarea class="form-control form-control-sm mt-1 font-monospace" id="order-edit-code" rows="4">' + esc(step.code || '') + '</textarea></div>';
    }
    document.getElementById('order-edit-body').innerHTML = body;
    bootstrap.Modal.getOrCreateInstance(document.getElementById('order-edit-modal')).show();
  }

  document.getElementById('order-edit-save').addEventListener('click', function () {
    if (_editStepIndex < 0 || _editStepIndex >= state.orderSteps.length) return;
    var step = state.orderSteps[_editStepIndex];
    var invokeEl = document.getElementById('order-edit-invoke');
    var valueEl = document.getElementById('order-edit-value');
    var codeEl = document.getElementById('order-edit-code');
    if (invokeEl) { step.invoke = invokeEl.value; step.summary = 'Ask ' + invokeEl.value; }
    if (valueEl) { step.value = valueEl.value; if (step.kind === 'section') step.summary = 'Section: ' + valueEl.value; if (step.kind === 'progress') step.summary = 'Progress: ' + valueEl.value + '%'; }
    if (codeEl) { step.code = codeEl.value; step.summary = codeEl.value.split('\n')[0].slice(0, 60); }
    bootstrap.Modal.getInstance(document.getElementById('order-edit-modal')).hide();
    renderCanvas();
  });

  // -------------------------------------------------------------------------
  // Select change handlers
  // -------------------------------------------------------------------------
  projectSelect.addEventListener('change', function () {
    state.project = projectSelect.value;
    state.selectedBlockId = null;
    loadFiles();
  });

  fileSelect.addEventListener('change', function () {
    state.filename = fileSelect.value;
    state.selectedBlockId = null;
    loadFile();
  });

  if (filterQuestionsCheckbox) {
    filterQuestionsCheckbox.addEventListener('change', function () {
      state.filterQuestionsOnly = filterQuestionsCheckbox.checked;
      renderOutline();
    });
  }

  searchInput.addEventListener('input', function () {
    state.searchQuery = searchInput.value;
    renderOutline();
  });

  // -------------------------------------------------------------------------
  // Init
  // -------------------------------------------------------------------------
  function init() {
    if (!BOOT.authenticated) {
      canvasContent.innerHTML = '<div class="text-center py-5"><h3>Login required</h3><p class="text-muted">Please log in to docassemble to use the interview editor.</p></div>';
      return;
    }
    initMonaco(function () {
      populateProjects();
      loadFiles();
    });
  }

  init();
})();
