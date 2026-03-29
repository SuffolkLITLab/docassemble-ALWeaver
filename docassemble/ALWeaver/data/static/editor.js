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
  var authState = BOOT.auth || {};
  var LOGIN_URL = authState.loginUrl || BOOT.login_url || '/user/sign-in';

  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------
  var state = {
    projects: BOOT.projects || [],
    project: null,
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
    canvasMode: 'project-selector',
    questionEditMode: 'preview',
    advancedOpen: false,
    jumpTarget: 'block',
    fullYamlTab: 'full',
    searchQuery: '',
    projectSearchQuery: '',
    filterQuestionsOnly: true,
    dirty: false,
    markdownPreviewMode: false,
    insertAfterBlockId: null,
  };

  var RECENT_PROJECTS_STORAGE_KEY = 'alweaver_recent_projects';
  var MAX_RECENT_PROJECTS = 8;

  // -------------------------------------------------------------------------
  // Monaco management
  // -------------------------------------------------------------------------
  var _monacoReady = false;
  var _monacoEditors = {};
  var _textareaEditors = {};

  function initMonaco(callback) {
    if (_monacoReady) { callback(); return; }
    if (typeof require === 'undefined' || !require.config) {
      // Monaco loader is not available in this deployment.
      callback();
      return;
    }
    require.config({ paths: { vs: '/static/app/monaco-editor/min/vs' } });
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
    Object.keys(_textareaEditors).forEach(function (key) {
      delete _textareaEditors[key];
    });
  }

  function createMonacoEditor(containerId, value, language, opts) {
    var container = document.getElementById(containerId);
    if (!container) return null;
    opts = opts || {};
    if (!_monacoReady || typeof monaco === 'undefined') {
      container.innerHTML = '';
      var textarea = document.createElement('textarea');
      textarea.className = 'editor-yaml-textarea';
      textarea.value = value || '';
      if (opts.onChange) textarea.addEventListener('input', opts.onChange);
      container.appendChild(textarea);
      _textareaEditors[containerId] = textarea;
      return textarea;
    }
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
    if (ed) return ed.getValue();
    var ta = _textareaEditors[containerId];
    return ta ? ta.value : '';
  }

  function getOrCreateBootstrapModal(elementId) {
    var modalEl = document.getElementById(elementId);
    if (!modalEl || typeof bootstrap === 'undefined' || !bootstrap.Modal) return null;
    return bootstrap.Modal.getOrCreateInstance(modalEl);
  }

  function closeBootstrapModal(elementId) {
    var modalEl = document.getElementById(elementId);
    if (!modalEl || typeof bootstrap === 'undefined' || !bootstrap.Modal) return;
    var instance = bootstrap.Modal.getInstance(modalEl);
    if (instance) instance.hide();
  }

  function makeNewBlockYaml(kind) {
    var stamp = Date.now();
    if (kind === 'question') {
      return (
        'id: question_' + stamp + '\n' +
        'question: New question\n' +
        'subquestion: |\n' +
        '  \n' +
        'fields:\n' +
        '  - New field: new_field_' + stamp + '\n'
      );
    }
    if (kind === 'code') {
      return (
        'id: code_' + stamp + '\n' +
        'code: |\n' +
        '  # Write Python here\n' +
        '  pass\n'
      );
    }
    if (kind === 'objects') {
      return (
        'id: objects_' + stamp + '\n' +
        'objects:\n' +
        '  - user: Individual\n'
      );
    }
    return (
      'id: block_' + stamp + '\n' +
      'comment: New block\n'
    );
  }

  // -------------------------------------------------------------------------
  // Auto-resize textarea helpers
  // -------------------------------------------------------------------------
  function _autoResize(el) {
    el.style.height = 'auto';
    var minH = el._minHeight || 0;
    el.style.height = Math.max(el.scrollHeight, minH) + 'px';
  }

  function _initAutoResize(el, minHeight) {
    if (!el || el.tagName.toLowerCase() !== 'textarea') return;
    el._minHeight = minHeight || 0;
    el.style.overflow = 'hidden';
    el.style.resize = 'none';
    _autoResize(el);
    el.addEventListener('input', function () { _autoResize(el); });
  }

  // -------------------------------------------------------------------------
  // Lightweight Markdown renderer (supports Mako syntax display)
  // -------------------------------------------------------------------------
  function renderMarkdown(text) {
    if (!text) return '<span class="text-muted fst-italic">(empty)</span>';
    var lines = String(text).split('\n');
    var html = '';
    var inList = false;
    var listTag = '';

    function escH(s) {
      return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function closeList() {
      if (inList) { html += '</' + listTag + '>'; inList = false; listTag = ''; }
    }

    function processInline(s) {
      // Mako ${...} expressions — highlight, don't evaluate
      s = s.replace(/\$\{([^}]*)\}/g, function (_, expr) {
        return '<code class="md-mako-expr">${' + expr + '}</code>';
      });
      // Bold+italic ***t***
      s = s.replace(/\*\*\*([\s\S]+?)\*\*\*/g, '<strong><em>$1</em></strong>');
      // Bold **t**
      s = s.replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>');
      // Italic *t*
      s = s.replace(/\*([\s\S]+?)\*/g, '<em>$1</em>');
      // Inline code `t`
      s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
      // Links [label](url)
      s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      return s;
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];

      // Mako % control lines
      if (/^\s*%/.test(line)) {
        closeList();
        html += '<div class="md-mako-line"><code>' + escH(line) + '</code></div>';
        continue;
      }

      // ATX header
      var hm = line.match(/^(#{1,6})\s+(.*)$/);
      if (hm) {
        closeList();
        var hl = Math.min(hm[1].length + 3, 6); // h4-h6 visually
        html += '<h' + hl + ' class="md-h">' + processInline(escH(hm[2])) + '</h' + hl + '>';
        continue;
      }

      // Unordered list  - / * / +
      var ulm = line.match(/^[-*+]\s+(.+)$/);
      if (ulm) {
        if (!inList || listTag !== 'ul') { closeList(); html += '<ul>'; inList = true; listTag = 'ul'; }
        html += '<li>' + processInline(escH(ulm[1])) + '</li>';
        continue;
      }

      // Ordered list
      var olm = line.match(/^\d+\.\s+(.+)$/);
      if (olm) {
        if (!inList || listTag !== 'ol') { closeList(); html += '<ol>'; inList = true; listTag = 'ol'; }
        html += '<li>' + processInline(escH(olm[1])) + '</li>';
        continue;
      }

      // Empty line
      if (line.trim() === '') {
        closeList();
        html += '<div class="md-br"></div>';
        continue;
      }

      // Normal paragraph line
      closeList();
      html += '<p class="md-p">' + processInline(escH(line)) + '</p>';
    }

    closeList();
    return html;
  }

  function refreshFromFileResponse(data) {
    state.blocks = data.blocks || [];
    state.metadataIndices = data.metadata_blocks || [];
    state.includeIndices = data.include_blocks || [];
    state.defaultSpIndices = data.default_screen_parts_blocks || [];
    state.orderIndices = data.order_blocks || [];
    state.rawYaml = data.raw_yaml || state.rawYaml;
    state.selectedBlockId = data.inserted_block_id || state.selectedBlockId || (state.blocks[0] ? state.blocks[0].id : null);
    state.canvasMode = 'question';
    state.questionEditMode = 'preview';
    state.advancedOpen = false;
    state.markdownPreviewMode = false;
    state.dirty = false;
    renderOutline();
    renderCanvas();
  }

  function setActiveTopTab(targetTab) {
    $$('.editor-top-tab').forEach(function (tab) {
      var isActive = tab === targetTab;
      tab.classList.toggle('active', isActive);
      tab.classList.toggle('btn-light', isActive);
      tab.classList.toggle('btn-outline-light', !isActive);
    });
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

  function appendYamlValue(yaml, key, value) {
    if (value === undefined || value === null) return yaml;
    var text = String(value).trim();
    if (!text) return yaml;
    return yaml + key + ': ' + escapeYamlStr(text) + '\n';
  }

  function appendYamlListValue(yaml, key, value) {
    if (value === undefined || value === null) return yaml;
    var text = String(value).trim();
    if (!text) return yaml;
    var parts = text.split(',').map(function (p) { return p.trim(); }).filter(Boolean);
    if (parts.length <= 1) {
      return appendYamlValue(yaml, key, text);
    }
    yaml += key + ':\n';
    parts.forEach(function (item) {
      yaml += '  - ' + escapeYamlStr(item) + '\n';
    });
    return yaml;
  }

  function serializeQuestionToYaml(block) {
    var yaml = '';

    var idInput = document.getElementById('adv-id');
    var blockId = (idInput && idInput.value) ? idInput.value : (block && block.id ? block.id : 'question_block');
    yaml = appendYamlValue(yaml, 'id', blockId);

    // Special modifiers immediately after id.
    var condToggle = document.getElementById('adv-enable-if');
    var condInput = document.getElementById('adv-if');
    if (condToggle && condToggle.checked && condInput && condInput.value.trim()) {
      yaml = appendYamlValue(yaml, 'if', condInput.value.trim());
    }

    var mandatoryBtn = document.getElementById('adv-mandatory-toggle');
    if (mandatoryBtn && mandatoryBtn.getAttribute('data-enabled') === 'true') {
      yaml += 'mandatory: True\n';
    }

    var setsInput = document.getElementById('adv-sets');
    if (setsInput && setsInput.value.trim()) {
      var setsKey = setsInput.getAttribute('data-sets-key') || 'sets';
      yaml = appendYamlListValue(yaml, setsKey, setsInput.value);
    }

    var needInput = document.getElementById('adv-need');
    if (needInput && needInput.value.trim()) {
      yaml = appendYamlListValue(yaml, 'need', needInput.value);
    }

    var eventInput = document.getElementById('adv-event');
    if (eventInput && eventInput.value.trim()) {
      yaml = appendYamlValue(yaml, 'event', eventInput.value);
    }

    var genericObjectInput = document.getElementById('adv-generic-object');
    if (genericObjectInput && genericObjectInput.value.trim()) {
      yaml = appendYamlValue(yaml, 'generic object', genericObjectInput.value);
    }

    var qTitle = document.getElementById('q-title');
    if (qTitle && qTitle.value) yaml = appendYamlValue(yaml, 'question', qTitle.value);

    var qSub = document.getElementById('q-subquestion');
    if (qSub && qSub.value) yaml = appendYamlValue(yaml, 'subquestion', qSub.value);

    var rows = document.querySelectorAll('.editor-field-row');
    if (rows.length > 0) {
      yaml += 'fields:\n';
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var label = row.querySelector('[data-field-prop="label"]').value || 'Label';
        var type = row.querySelector('[data-field-prop="type"]').value;
        var variable = row.querySelector('[data-field-prop="variable"]').value;
        var choicesEl = document.getElementById('field-choices-' + i);

        var isMultiLineLabel = label.indexOf('\n') !== -1;
        if (isMultiLineLabel) {
          yaml += '  - label: ' + escapeYamlStr(label) + '\n';
          if (variable) yaml += '    field: ' + escapeYamlStr(variable) + '\n';
        } else {
          yaml += '  - ' + escapeYamlStr(label) + ':';
          if (variable) {
            yaml += ' ' + escapeYamlStr(variable) + '\n';
          } else {
            yaml += '\n';
          }
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

    // Continue button keys are kept near the end in common docassemble style.
    var contField = document.getElementById('adv-continue-field');
    if (contField && contField.value.trim()) {
      yaml = appendYamlValue(yaml, 'continue button field', contField.value);
    }
    var contLabel = document.getElementById('adv-continue-label');
    if (contLabel && contLabel.value.trim()) {
      yaml = appendYamlValue(yaml, 'continue button label', contLabel.value);
    }

    return yaml;
  }

  function serializeCodeToYaml(block) {
    var yaml = '';
    var idInput = document.getElementById('adv-id');
    var blockId = (idInput && idInput.value) ? idInput.value : (block && block.id ? block.id : 'code_block');
    yaml = appendYamlValue(yaml, 'id', blockId);

    var condToggle = document.getElementById('adv-enable-if');
    var condInput = document.getElementById('adv-if');
    if (condToggle && condToggle.checked && condInput && condInput.value.trim()) {
      yaml = appendYamlValue(yaml, 'if', condInput.value.trim());
    }

    var mandatoryBtn = document.getElementById('adv-mandatory-toggle');
    if (mandatoryBtn && mandatoryBtn.getAttribute('data-enabled') === 'true') {
      yaml += 'mandatory: True\n';
    }

    var setsInput = document.getElementById('adv-sets');
    if (setsInput && setsInput.value.trim()) {
      var setsKey = setsInput.getAttribute('data-sets-key') || 'sets';
      yaml = appendYamlListValue(yaml, setsKey, setsInput.value);
    }

    var needInput = document.getElementById('adv-need');
    if (needInput && needInput.value.trim()) {
      yaml = appendYamlListValue(yaml, 'need', needInput.value);
    }

    var eventInput = document.getElementById('adv-event');
    if (eventInput && eventInput.value.trim()) {
      yaml = appendYamlValue(yaml, 'event', eventInput.value);
    }

    var genericObjectInput = document.getElementById('adv-generic-object');
    if (genericObjectInput && genericObjectInput.value.trim()) {
      yaml = appendYamlValue(yaml, 'generic object', genericObjectInput.value);
    }

    var contField = document.getElementById('adv-continue-field');
    if (contField && contField.value.trim()) {
      yaml = appendYamlValue(yaml, 'continue button field', contField.value);
    }

    var contLabel = document.getElementById('adv-continue-label');
    if (contLabel && contLabel.value.trim()) {
      yaml = appendYamlValue(yaml, 'continue button label', contLabel.value);
    }

    var codeText = getMonacoValue('code-monaco');
    if (!codeText && block && block.data && block.data.code) {
      codeText = String(block.data.code);
    }
    yaml += 'code: |\n';
    String(codeText || '').split('\n').forEach(function (line) {
      yaml += '  ' + line + '\n';
    });

    return yaml;
  }

  function serializeObjectsToYaml(block) {
    var yaml = '';
    var idInput = document.getElementById('adv-id');
    var blockId = (idInput && idInput.value) ? idInput.value : (block && block.id ? block.id : 'objects_block');
    yaml = appendYamlValue(yaml, 'id', blockId);

    var condToggle = document.getElementById('adv-enable-if');
    var condInput = document.getElementById('adv-if');
    if (condToggle && condToggle.checked && condInput && condInput.value.trim()) {
      yaml = appendYamlValue(yaml, 'if', condInput.value.trim());
    }

    var mandatoryBtn = document.getElementById('adv-mandatory-toggle');
    if (mandatoryBtn && mandatoryBtn.getAttribute('data-enabled') === 'true') {
      yaml += 'mandatory: True\n';
    }

    var setsInput = document.getElementById('adv-sets');
    if (setsInput && setsInput.value.trim()) {
      var setsKey = setsInput.getAttribute('data-sets-key') || 'sets';
      yaml = appendYamlListValue(yaml, setsKey, setsInput.value);
    }

    var needInput = document.getElementById('adv-need');
    if (needInput && needInput.value.trim()) {
      yaml = appendYamlListValue(yaml, 'need', needInput.value);
    }

    var eventInput = document.getElementById('adv-event');
    if (eventInput && eventInput.value.trim()) {
      yaml = appendYamlValue(yaml, 'event', eventInput.value);
    }

    var genericObjectInput = document.getElementById('adv-generic-object');
    if (genericObjectInput && genericObjectInput.value.trim()) {
      yaml = appendYamlValue(yaml, 'generic object', genericObjectInput.value);
    }

    var contField = document.getElementById('adv-continue-field');
    if (contField && contField.value.trim()) {
      yaml = appendYamlValue(yaml, 'continue button field', contField.value);
    }

    var contLabel = document.getElementById('adv-continue-label');
    if (contLabel && contLabel.value.trim()) {
      yaml = appendYamlValue(yaml, 'continue button label', contLabel.value);
    }

    yaml += 'objects:\n';
    var rows = document.querySelectorAll('.editor-obj-row');
    if (rows.length > 0) {
      rows.forEach(function (row) {
        var nameEl = row.querySelector('[data-obj-prop="name"]');
        var classEl = row.querySelector('[data-obj-prop="class"]');
        var name = nameEl ? String(nameEl.value || '').trim() : '';
        var cls = classEl ? String(classEl.value || '').trim() : '';
        if (!name) return;
        yaml += '  - ' + escapeYamlStr(name) + ': ' + escapeYamlStr(cls || 'DAObject') + '\n';
      });
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

    var contField = document.getElementById('adv-continue-field');
    if (contField) {
      if (contField.value) blk.data['continue button field'] = contField.value;
      else delete blk.data['continue button field'];
    }

    var contLabel = document.getElementById('adv-continue-label');
    if (contLabel) {
      if (contLabel.value) blk.data['continue button label'] = contLabel.value;
      else delete blk.data['continue button label'];
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

    var setsInput = document.getElementById('adv-sets');
    if (setsInput) {
      var setsKey = setsInput.getAttribute('data-sets-key') || 'sets';
      var setsValue = setsInput.value.trim();
      delete blk.data.sets;
      delete blk.data['only sets'];
      if (setsValue) {
        var setParts = setsValue.split(',').map(function (p) { return p.trim(); }).filter(Boolean);
        blk.data[setsKey] = setParts.length > 1 ? setParts : setParts[0] || setsValue;
      }
    }

    var needInput = document.getElementById('adv-need');
    if (needInput) {
      var needValue = needInput.value.trim();
      if (needValue) {
        var needParts = needValue.split(',').map(function (p) { return p.trim(); }).filter(Boolean);
        blk.data.need = needParts.length > 1 ? needParts : needParts[0] || needValue;
      } else {
        delete blk.data.need;
      }
    }

    var eventInput = document.getElementById('adv-event');
    if (eventInput) {
      if (eventInput.value.trim()) blk.data.event = eventInput.value.trim();
      else delete blk.data.event;
    }

    var genericObjectInput = document.getElementById('adv-generic-object');
    if (genericObjectInput) {
      if (genericObjectInput.value.trim()) blk.data['generic object'] = genericObjectInput.value.trim();
      else delete blk.data['generic object'];
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
  function getCookieValue(name) {
    var prefix = name + '=';
    var cookies = (document.cookie || '').split(';');
    for (var i = 0; i < cookies.length; i++) {
      var c = cookies[i].trim();
      if (c.indexOf(prefix) === 0) {
        return decodeURIComponent(c.slice(prefix.length));
      }
    }
    return null;
  }

  function readRecentProjects() {
    try {
      var raw = window.localStorage.getItem(RECENT_PROJECTS_STORAGE_KEY);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(function (p) { return typeof p === 'string' && p.trim(); });
    } catch (_err) {
      return [];
    }
  }

  function writeRecentProjects(projects) {
    try {
      window.localStorage.setItem(RECENT_PROJECTS_STORAGE_KEY, JSON.stringify(projects.slice(0, MAX_RECENT_PROJECTS)));
    } catch (_err) {
      // Ignore storage failures (private mode, quota, etc.)
    }
  }

  function rememberRecentProject(projectName) {
    if (!projectName) return;
    var next = readRecentProjects().filter(function (name) { return name !== projectName; });
    next.unshift(projectName);
    writeRecentProjects(next);
  }

  function getRecentProjectsInWorkspace() {
    var known = {};
    var workspaceProjects = state.projects || [];
    workspaceProjects.forEach(function (p) { known[p] = true; });

    var candidateCookieKeys = ['playgroundproject', 'playground_project', 'current_project', 'project'];
    var merged = [];
    candidateCookieKeys.forEach(function (key) {
      var value = getCookieValue(key);
      if (value && known[value] && merged.indexOf(value) === -1) {
        merged.push(value);
      }
    });
    readRecentProjects().forEach(function (p) {
      if (known[p] && merged.indexOf(p) === -1) merged.push(p);
    });
    return merged.slice(0, MAX_RECENT_PROJECTS);
  }

  function populateProjects() {
    projectSelect.innerHTML = '';
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select project...';
    placeholder.disabled = false;
    placeholder.selected = !state.project;
    projectSelect.appendChild(placeholder);

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
    if (!state.project) {
      state.files = [];
      state.filename = null;
      state.blocks = [];
      populateFiles();
      renderOutline();
      renderCanvas();
      return Promise.resolve();
    }
    return apiGet('/api/files?project=' + encodeURIComponent(state.project))
      .then(function (res) {
        if (!res.success) return;
        rememberRecentProject(state.project);
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

  function openProject(projectName) {
    if (!projectName) return;
    state.project = projectName;
    state.selectedBlockId = null;
    state.canvasMode = 'question';
    populateProjects();
    return loadFiles();
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
    html += '<div class="editor-outline-insert"><button type="button" class="editor-outline-insert-btn btn btn-outline-secondary btn-sm" data-insert-after-id=""><i class="fa-solid fa-plus" aria-hidden="true"></i><span class="visually-hidden">Insert block at top</span></button></div>';
    blocks.forEach(function (block) {
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
      html += '<div class="editor-outline-insert"><button type="button" class="editor-outline-insert-btn btn btn-outline-secondary btn-sm" data-insert-after-id="' + esc(block.id) + '"><i class="fa-solid fa-plus" aria-hidden="true"></i><span class="visually-hidden">Insert block after ' + esc(block.title) + '</span></button></div>';
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

  function getBlockYamlForSave(block) {
    if (!block) return '';
    if (state.questionEditMode === 'preview' && block.type === 'question') {
      return serializeQuestionToYaml(block);
    }
    if (state.questionEditMode === 'preview' && block.type === 'code') {
      return serializeCodeToYaml(block);
    }
    if (state.questionEditMode === 'preview' && block.type === 'objects') {
      return serializeObjectsToYaml(block);
    }
    var yamlVal = getMonacoValue('block-yaml-monaco');
    if (!yamlVal && block.yaml) yamlVal = block.yaml;
    return yamlVal;
  }

  function saveCurrentBlockIfDirty() {
    if (!state.dirty || !state.filename) return Promise.resolve(true);
    var block = getSelectedBlock();
    if (!block) return Promise.resolve(true);
    var yamlVal = getBlockYamlForSave(block);
    if (!yamlVal) return Promise.resolve(false);
    return apiPost('/api/block', {
      project: state.project,
      filename: state.filename,
      block_id: block.id,
      block_yaml: yamlVal,
    }).then(function (res) {
      if (!res.success || !res.data) return false;
      var keepBlockId = res.data.saved_block_id || block.id;
      refreshFromFileResponse(res.data);
      state.selectedBlockId = keepBlockId;
      renderOutline();
      renderCanvas();
      return true;
    });
  }

  function renderCanvas() {
    disposeMonacoEditors();
    if (state.currentView !== 'interview') {
      renderSecondaryView();
      return;
    }
    if (state.canvasMode === 'project-selector') {
      renderProjectSelector();
    } else if (state.canvasMode === 'new-project') {
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
    if (!state.project) {
      state.canvasMode = 'project-selector';
      renderProjectSelector();
      return;
    }
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

  function renderLoginRequired() {
    var html = '';
    html += '<div class="editor-login-shell">';
    html += '<div class="editor-login-card">';
    html += '<div class="editor-login-icon"><i class="fa-solid fa-right-to-bracket" aria-hidden="true"></i></div>';
    html += '<h2>Sign in to use the Interview Editor</h2>';
    html += '<p>Use your docassemble account to open projects, edit YAML, and preview interviews.</p>';
    html += '<a class="btn btn-primary btn-lg" href="' + esc(LOGIN_URL) + '">Go to docassemble sign in</a>';
    html += '</div></div>';
    canvasContent.innerHTML = html;
  }

  function renderProjectSelector() {
    var query = state.projectSearchQuery.toLowerCase().trim();
    var recent = getRecentProjectsInWorkspace();
    var filteredProjects = state.projects.filter(function (name) {
      if (!query) return true;
      return name.toLowerCase().indexOf(query) !== -1;
    });

    var html = '';
    html += '<div class="editor-project-selector-shell">';
    html += '<div class="editor-project-selector-header">';
    html += '<div>';
    html += '<h2>Choose a project</h2>';
    html += '<p>Jump back into a recent project, search all projects, or start a new one.</p>';
    html += '</div>';
    html += '<button type="button" class="btn btn-primary" id="open-new-project-card">Create new project</button>';
    html += '</div>';
    html += '<div class="editor-card"><div class="editor-card-body">';
    html += '<label class="editor-tiny" for="project-search-input">Search projects</label>';
    html += '<input class="form-control mt-1" id="project-search-input" placeholder="Type a project name" value="' + esc(state.projectSearchQuery) + '">';
    html += '</div></div>';

    if (recent.length > 0) {
      html += '<div class="editor-project-section">';
      html += '<div class="editor-project-section-title">Recent projects</div>';
      html += '<div class="editor-project-cards">';
      recent.forEach(function (name) {
        html += '<button type="button" class="editor-project-card editor-project-card-recent" data-project-card="' + esc(name) + '">';
        html += '<span class="editor-project-card-badge">Recent</span>';
        html += '<span class="editor-project-card-title">' + esc(name) + '</span>';
        html += '<span class="editor-project-card-meta">Open project</span>';
        html += '</button>';
      });
      html += '</div></div>';
    }

    html += '<div class="editor-project-section">';
    html += '<div class="editor-project-section-title">All projects</div>';
    if (filteredProjects.length === 0) {
      html += '<div class="editor-card"><div class="editor-card-body text-muted">No projects matched your search.</div></div>';
    } else {
      html += '<div class="editor-project-cards">';
      filteredProjects.forEach(function (name) {
        html += '<button type="button" class="editor-project-card" data-project-card="' + esc(name) + '">';
        html += '<span class="editor-project-card-title">' + esc(name) + '</span>';
        html += '<span class="editor-project-card-meta">Open project</span>';
        html += '</button>';
      });
      html += '</div>';
    }
    html += '</div>';
    html += '</div>';
    canvasContent.innerHTML = html;
  }

  // --- Question block: rich field editor ---
  function renderQuestionBlock(block) {
    var data = block.data || {};
    var fields = data.fields || [];
    var isPreview = state.questionEditMode === 'preview';
    var isMdPreview = isPreview && state.markdownPreviewMode;
    var html = '';

    // Header bar
    html += '<div class="editor-center-bar">';
    html += '<div></div>';
    html += '<div class="d-flex gap-2 align-items-center">';
    if (isPreview) {
      html += '<div class="btn-group btn-group-sm" role="group" aria-label="Edit or preview mode">';
      html += '<button type="button" class="btn btn-sm ' + (!isMdPreview ? 'btn-primary' : 'btn-outline-secondary') + '" id="md-preview-off">Edit</button>';
      html += '<button type="button" class="btn btn-sm ' + (isMdPreview ? 'btn-primary' : 'btn-outline-secondary') + '" id="md-preview-on"><i class="fa-regular fa-eye me-1" aria-hidden="true"></i>Preview</button>';
      html += '</div>';
    }
    html += '<button class="btn btn-sm btn-outline-secondary" id="toggle-edit-mode">' + (isPreview ? 'Edit YAML' : 'Visual editor') + '</button>';
    if (!isMdPreview) {
      html += '<button class="btn btn-sm btn-primary" id="save-block-btn"' + (!state.dirty ? ' disabled' : '') + '>Save</button>';
    }
    html += '</div></div>';

    html += '<div class="editor-shell">';

    if (isPreview) {
      html += '<div class="editor-card editor-question-main-card"><div class="editor-card-body editor-card-body-compact">';

      // Question
      html += '<div class="editor-form-group">';
      html += '<label class="editor-tiny" for="q-title">Question</label>';
      if (isMdPreview) {
        html += '<div class="md-preview-wrapper">' + renderMarkdown(data.question || '') + '</div>';
      } else {
        html += '<textarea class="form-control editor-form-control" id="q-title" rows="1">' + esc(data.question || '') + '</textarea>';
      }
      html += '</div>';

      // Subquestion — always shown
      html += '<div class="editor-form-group">';
      html += '<label class="editor-tiny" for="q-subquestion">Subquestion</label>';
      if (isMdPreview) {
        html += '<div class="md-preview-wrapper">' + renderMarkdown(String(data.subquestion || '')) + '</div>';
      } else {
        html += '<textarea class="form-control editor-form-control" id="q-subquestion" rows="5">' + esc(String(data.subquestion || '')) + '</textarea>';
      }
      html += '</div>';

      html += '</div></div>';

      if (fields.length > 0) {
        html += '<div class="editor-card editor-question-main-card"><div class="editor-card-body editor-card-body-compact">';
        html += '<div class="editor-section-legend">Fields</div>';
        if (!isMdPreview) {
          html += '<div class="editor-field-grid-header">';
          html += '<div>Label</div><div>Type</div><div>Variable</div><div></div>';
          html += '</div>';
        }
        fields.forEach(function (f, fi) {
          var label = '', varName = '', dtype = 'text', choices = '';
          if (typeof f === 'object' && f !== null) {
            // Detect label:/field: expanded style
            if (Object.prototype.hasOwnProperty.call(f, 'label') &&
                (Object.prototype.hasOwnProperty.call(f, 'field') ||
                 Object.prototype.hasOwnProperty.call(f, 'datatype') ||
                 Object.prototype.hasOwnProperty.call(f, 'choices'))) {
              label = String(f.label || '');
              varName = String(f.field || '');
              dtype = f.datatype || f.input_type || 'text';
              if (f.choices && Array.isArray(f.choices)) {
                choices = f.choices.map(function (c) {
                  if (typeof c === 'object') { var ck = Object.keys(c); return ck[0] + ': ' + c[ck[0]]; }
                  return String(c);
                }).join('\n');
              }
            } else {
              // Shorthand: {"Label": "variable"} or {"Label": {datatype:...}}
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
            }
          } else if (typeof f === 'string') {
            label = f;
          }

          var hasChoices = CHOICE_TYPES.indexOf(dtype) !== -1;

          if (isMdPreview) {
            html += '<div class="editor-field-row-preview">';
            html += '<div class="md-preview-wrapper md-preview-label">' + renderMarkdown(label) + '</div>';
            html += '<div class="editor-tiny text-muted" style="align-self:start;padding-top:6px">' + esc(dtype) + '</div>';
            html += '<div class="font-monospace editor-tiny" style="align-self:start;padding-top:6px">' + esc(varName) + '</div>';
            html += '</div>';
          } else {
            html += '<div class="editor-field-row" data-field-idx="' + fi + '">';
            html += '<textarea class="form-control editor-form-control" data-field-prop="label" rows="1" placeholder="Field label">' + esc(label) + '</textarea>';
            html += '<select class="form-select editor-form-control" data-field-prop="type">';
            FIELD_TYPES.forEach(function (t) {
              html += '<option value="' + t + '"' + (t === dtype ? ' selected' : '') + '>' + t + '</option>';
            });
            html += '</select>';
            html += '<input class="form-control editor-form-control font-monospace" data-field-prop="variable" value="' + esc(varName) + '" placeholder="variable_name">';
            html += '<div class="editor-field-actions"><button type="button" class="btn btn-outline-danger btn-sm" data-remove-field="' + fi + '" title="Remove field"><i class="fa-solid fa-trash" aria-hidden="true"></i><span class="visually-hidden">Remove field</span></button></div>';
            html += '</div>';
            if (hasChoices || choices) {
              html += '<div class="editor-field-choices-row" data-field-idx="' + fi + '">';
              html += '<label class="editor-tiny" for="field-choices-' + fi + '">Choices (one per line)</label>';
              html += '<textarea class="form-control editor-form-control editor-field-choices" id="field-choices-' + fi + '" rows="2">' + esc(choices) + '</textarea>';
              html += '</div>';
            }
          }
        });
        if (!isMdPreview) {
          html += '<div class="mt-2"><button class="btn btn-sm btn-outline-primary" id="add-field-btn">+ Add field</button></div>';
        }
        html += '</div></div>';
      } else if (!isMdPreview) {
        html += '<div class="editor-card editor-question-main-card"><div class="editor-card-body editor-card-body-compact">';
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

      // Advanced (only in edit mode)
      if (!isMdPreview) {
        html += renderAdvancedPanel(block);
      }

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
    } else if (!isMdPreview) {
      // Auto-resize editable textareas
      var qTitle = document.getElementById('q-title');
      if (qTitle) _initAutoResize(qTitle, 36);
      var qSub = document.getElementById('q-subquestion');
      if (qSub) _initAutoResize(qSub, 120);
      document.querySelectorAll('[data-field-prop="label"]').forEach(function (ta) {
        _initAutoResize(ta, 36);
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
          html += '<div><button type="button" class="btn btn-sm btn-outline-danger" data-remove-obj="' + oi + '" title="Remove object"><i class="fa-solid fa-trash" aria-hidden="true"></i><span class="visually-hidden">Remove object</span></button></div>';
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

      html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-continue-field">Continue button field</label>';
      html += '<input class="form-control editor-form-control font-monospace" id="adv-continue-field" value="' + esc(String(data['continue button field'] || '')) + '"></div>';

      html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-continue-label">Continue button label</label>';
      html += '<input class="form-control editor-form-control" id="adv-continue-label" value="' + esc(String(data['continue button label'] || '')) + '"></div>';

      // Additional keys
      var setsVal = data.sets || data['only sets'] || '';
      if (Array.isArray(setsVal)) setsVal = setsVal.join(', ');
      html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-sets">' + (data['only sets'] ? 'Only sets' : 'Sets') + '</label>';
      html += '<input class="form-control editor-form-control font-monospace" id="adv-sets" data-sets-key="' + (data['only sets'] ? 'only sets' : 'sets') + '" value="' + esc(String(setsVal)) + '"></div>';

      var needVal = data.need || '';
      if (Array.isArray(needVal)) needVal = needVal.join(', ');
      html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-need">Need</label>';
      html += '<input class="form-control editor-form-control font-monospace" id="adv-need" value="' + esc(String(needVal)) + '"></div>';

      html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-event">Event</label>';
      html += '<input class="form-control editor-form-control font-monospace" id="adv-event" value="' + esc(String(data.event || '')) + '"></div>';

      html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-generic-object">Generic object</label>';
      html += '<input class="form-control editor-form-control font-monospace" id="adv-generic-object" value="' + esc(String(data['generic object'] || '')) + '"></div>';

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
    html += '<button type="button" class="btn btn-sm btn-outline-primary" data-add-step="screen"><i class="fa-solid fa-plus me-1" aria-hidden="true"></i>Screen</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-step="gather"><i class="fa-solid fa-plus me-1" aria-hidden="true"></i>Gather</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-step="section"><i class="fa-solid fa-plus me-1" aria-hidden="true"></i>Section</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-step="progress"><i class="fa-solid fa-plus me-1" aria-hidden="true"></i>Progress</button>';
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
      html += '<button type="button" class="btn btn-sm btn-outline-secondary py-0 px-1" data-step-action="edit" data-step-idx="' + i + '" title="Edit"><i class="fa-solid fa-pen-to-square" aria-hidden="true"></i><span class="visually-hidden">Edit step</span></button>';
      html += '<button type="button" class="btn btn-sm btn-outline-danger py-0 px-1" data-step-action="remove" data-step-idx="' + i + '" title="Remove"><i class="fa-solid fa-trash" aria-hidden="true"></i><span class="visually-hidden">Remove step</span></button>';
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
    var topTab = target.closest('.editor-top-tab');
    var jumpItem = target.closest('.editor-jump-item');
    var outlineInsertBtn = target.closest('.editor-outline-insert-btn');
    var insertChoiceBtn = target.closest('[data-insert]');
    var stepActionBtn = target.closest('[data-step-action]');
    var addStepBtn = target.closest('[data-add-step]');
    var removeFieldBtn = target.closest('[data-remove-field]');
    var removeObjBtn = target.closest('[data-remove-obj]');
    var removeUploadBtn = target.closest('[data-remove-upload]');
    var projectCardBtn = target.closest('[data-project-card]');

    // View tabs
    if (topTab) {
      state.currentView = topTab.getAttribute('data-view');
      setActiveTopTab(topTab);
      if (state.currentView === 'interview') {
        state.canvasMode = state.project ? 'question' : 'project-selector';
      }
      renderCanvas();
      return;
    }

    // Project selector cards
    if (projectCardBtn) {
      openProject(projectCardBtn.getAttribute('data-project-card'));
      return;
    }
    if (target.id === 'open-new-project-card') {
      state.canvasMode = 'new-project';
      renderCanvas();
      return;
    }

    // Jump targets
    if (jumpItem) {
      var jump = jumpItem.getAttribute('data-jump');
      $$('.editor-jump-item').forEach(function (j) { j.classList.remove('active'); });
      jumpItem.classList.add('active');
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
      var interviewTab = document.querySelector('.editor-top-tab[data-view="interview"]');
      if (interviewTab) setActiveTopTab(interviewTab);
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
      state.markdownPreviewMode = false;
      renderOutline();
      renderCanvas();
      return;
    }

    // Outline insert
    if (outlineInsertBtn) {
      state.insertAfterBlockId = outlineInsertBtn.getAttribute('data-insert-after-id') || '';
      var insertModal = getOrCreateBootstrapModal('insert-modal');
      if (insertModal) insertModal.show();
      return;
    }

    // Insert block modal actions
    if (insertChoiceBtn) {
      if (!state.filename) return;
      var kind = insertChoiceBtn.getAttribute('data-insert');
      var newYaml = makeNewBlockYaml(kind);
      apiPost('/api/insert-block', {
        project: state.project,
        filename: state.filename,
        insert_after_id: state.insertAfterBlockId,
        block_yaml: newYaml,
      }).then(function (res) {
        if (res.success && res.data) {
          closeBootstrapModal('insert-modal');
          refreshFromFileResponse(res.data);
        }
      });
      return;
    }

    // Top action buttons
    if (target.id === 'btn-project-selector') {
      state.canvasMode = 'project-selector';
      state.currentView = 'interview';
      var interviewTab0 = document.querySelector('.editor-top-tab[data-view="interview"]');
      if (interviewTab0) setActiveTopTab(interviewTab0);
      renderCanvas();
      return;
    }
    if (target.id === 'btn-new-project') {
      state.canvasMode = 'new-project';
      state.currentView = 'interview';
      var interviewTab1 = document.querySelector('.editor-top-tab[data-view="interview"]');
      if (interviewTab1) setActiveTopTab(interviewTab1);
      renderCanvas();
      return;
    }
    if (target.id === 'btn-full-yaml') {
      state.canvasMode = state.canvasMode === 'full-yaml' ? 'question' : 'full-yaml';
      state.currentView = 'interview';
      var interviewTab2 = document.querySelector('.editor-top-tab[data-view="interview"]');
      if (interviewTab2) setActiveTopTab(interviewTab2);
      renderCanvas();
      return;
    }
    if (target.id === 'btn-order-builder') {
      state.canvasMode = 'order-builder';
      state.currentView = 'interview';
      var interviewTab3 = document.querySelector('.editor-top-tab[data-view="interview"]');
      if (interviewTab3) setActiveTopTab(interviewTab3);
      renderCanvas();
      return;
    }
    if (target.id === 'btn-preview-interview') {
      if (!state.filename) return;
      saveCurrentBlockIfDirty().then(function () {
        apiGet('/api/preview-url?project=' + encodeURIComponent(state.project) + '&filename=' + encodeURIComponent(state.filename))
          .then(function (res) { if (res.success && res.data && res.data.url) window.open(res.data.url, '_blank'); });
      });
      return;
    }

    // Markdown preview toggle
    if (target.id === 'md-preview-on') {
      var selectedForPreview = getSelectedBlock();
      if (selectedForPreview && selectedForPreview.type === 'question' && state.questionEditMode === 'preview') {
        syncFieldsToData(selectedForPreview);
      }
      state.markdownPreviewMode = true;
      renderCanvas();
      return;
    }
    if (target.id === 'md-preview-off') {
      var selectedForEdit = getSelectedBlock();
      if (selectedForEdit && selectedForEdit.type === 'question' && state.questionEditMode === 'preview') {
        syncFieldsToData(selectedForEdit);
      }
      state.markdownPreviewMode = false;
      renderCanvas();
      return;
    }

    // Toggle edit mode (shared by question / code / objects)
    if (target.id === 'toggle-edit-mode') {
      state.questionEditMode = state.questionEditMode === 'preview' ? 'yaml' : 'preview';
      state.markdownPreviewMode = false;
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
      var yamlVal = getBlockYamlForSave(block);

      apiPost('/api/block', {
        project: state.project,
        filename: state.filename,
        block_id: block.id,
        block_yaml: yamlVal,
      }).then(function (res) {
        if (res.success && res.data) {
          var keepBlockId = res.data.saved_block_id || block.id;
          refreshFromFileResponse(res.data);
          state.selectedBlockId = keepBlockId;
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
    if (stepActionBtn) {
      var action = stepActionBtn.getAttribute('data-step-action');
      var idx = parseInt(stepActionBtn.getAttribute('data-step-idx'), 10);
      if (action === 'up' && idx > 0) { var t1 = state.orderSteps[idx]; state.orderSteps[idx] = state.orderSteps[idx - 1]; state.orderSteps[idx - 1] = t1; renderCanvas(); }
      else if (action === 'down' && idx < state.orderSteps.length - 1) { var t2 = state.orderSteps[idx]; state.orderSteps[idx] = state.orderSteps[idx + 1]; state.orderSteps[idx + 1] = t2; renderCanvas(); }
      else if (action === 'remove') { state.orderSteps.splice(idx, 1); renderCanvas(); }
      else if (action === 'preview') { showOrderPreview(state.orderSteps[idx]); }
      else if (action === 'edit') { showOrderEdit(state.orderSteps[idx], idx); }
      return;
    }

    // Add step
    if (addStepBtn) {
      var kind = addStepBtn.getAttribute('data-add-step');
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
    if (removeFieldBtn) {
      var fi = parseInt(removeFieldBtn.getAttribute('data-remove-field'), 10);
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
    if (removeObjBtn) {
      var oi = parseInt(removeObjBtn.getAttribute('data-remove-obj'), 10);
      var blk4 = getSelectedBlock();
      if (blk4 && blk4.data && blk4.data.objects) {
        blk4.data.objects.splice(oi, 1);
        state.dirty = true;
        renderCanvas();
      }
      return;
    }

    // New project
    if (target.id === 'cancel-new-project') { state.canvasMode = 'project-selector'; _uploadedFiles = []; renderCanvas(); return; }

    // Remove upload chip
    if (removeUploadBtn) {
      var removeBtn = removeUploadBtn;
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
    if (target.id === 'project-search-input') {
      state.projectSearchQuery = target.value || '';
      if (state.canvasMode === 'project-selector') renderProjectSelector();
      return;
    }
    if (target.matches('[data-field-prop]') || target.matches('.editor-field-choices') ||
        target.matches('.editor-obj-input') || target.id === 'q-title' || target.id === 'q-subquestion' ||
        target.id === 'adv-id' || target.id === 'adv-if' || target.id === 'adv-continue-field' ||
        target.id === 'adv-continue-label' || target.id === 'adv-sets' || target.id === 'adv-need' ||
        target.id === 'adv-event' || target.id === 'adv-generic-object') {
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
    var previewModal = getOrCreateBootstrapModal('order-preview-modal');
    if (previewModal) previewModal.show();
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
    var editModal = getOrCreateBootstrapModal('order-edit-modal');
    if (editModal) editModal.show();
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
    closeBootstrapModal('order-edit-modal');
    renderCanvas();
  });

  // -------------------------------------------------------------------------
  // Select change handlers
  // -------------------------------------------------------------------------
  projectSelect.addEventListener('change', function () {
    var nextProject = projectSelect.value;
    state.project = nextProject || null;
    state.selectedBlockId = null;
    if (!state.project) {
      state.canvasMode = 'project-selector';
      renderCanvas();
      return;
    }
    state.canvasMode = 'question';
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
    var isAuthenticated = Boolean(authState.authenticated || BOOT.authenticated);
    if (!isAuthenticated) {
      renderLoginRequired();
      return;
    }
    initMonaco(function () {
      populateProjects();
      state.canvasMode = 'project-selector';
      renderCanvas();
    });
  }

  init();
})();
