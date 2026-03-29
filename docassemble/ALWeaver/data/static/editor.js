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
    orderStepMap: {},
    activeOrderBlockId: null,
    orderCollapsed: {},
    selectedOrderStepIds: {},
    symbolCatalog: {
      loadedFor: null,
      all: [],
      topLevel: [],
      groups: {},
    },
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
  var _symbolInsertContext = null;
  var DOCASSEMBLE_MARKUP_DOCS_URL = 'https://docassemble.org/docs/markup.html';
  var MAKO_DOCS_URL = 'https://docs.makotemplates.org/en/latest/syntax.html';

  // -------------------------------------------------------------------------
  // Monaco management
  // -------------------------------------------------------------------------
  var _monacoReady = false;
  var _monacoLoading = false;
  var _monacoFailed = false;
  var _monacoLoaderBase = null;
  var _monacoEditors = {};
  var _textareaEditors = {};

  function _loadScriptOnce(src, callback) {
    var existing = document.querySelector('script[data-editor-loader-src="' + src + '"]');
    if (existing) {
      if (existing.getAttribute('data-loaded') === 'true') {
        callback(true);
        return;
      }
      existing.addEventListener('load', function () { callback(true); }, { once: true });
      existing.addEventListener('error', function () { callback(false); }, { once: true });
      return;
    }
    var script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.setAttribute('data-editor-loader-src', src);
    script.addEventListener('load', function () {
      script.setAttribute('data-loaded', 'true');
      callback(true);
    }, { once: true });
    script.addEventListener('error', function () {
      callback(false);
    }, { once: true });
    document.head.appendChild(script);
  }

  function _getMonacoLoaderCandidates() {
    return [
      '/static/app/monaco-editor/min/vs/loader.js',
      '/packagestatic/docassemble.webapp/monaco-editor/min/vs/loader.js',
      'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs/loader.js'
    ];
  }

  function _ensureMonacoLoader(callback) {
    if (typeof require !== 'undefined' && require && require.config) {
      callback(true);
      return;
    }
    var candidates = _getMonacoLoaderCandidates().slice();
    function tryNext() {
      var src = candidates.shift();
      if (!src) {
        callback(false);
        return;
      }
      _loadScriptOnce(src, function (loaded) {
        if (loaded && typeof require !== 'undefined' && require && require.config) {
          _monacoLoaderBase = src.replace(/\/loader\.js(?:\?.*)?$/, '');
          callback(true);
          return;
        }
        tryNext();
      });
    }
    tryNext();
  }

  function initMonaco(callback) {
    if (_monacoReady) { callback(); return; }
    if (_monacoFailed) {
      callback();
      return;
    }
    if (_monacoLoading) {
      window.setTimeout(function () { initMonaco(callback); }, 50);
      return;
    }
    _monacoLoading = true;
    _ensureMonacoLoader(function (loaderReady) {
      if (!loaderReady || typeof require === 'undefined' || !require.config) {
        _monacoLoading = false;
        _monacoFailed = true;
        callback();
        return;
      }
      var vsBase = _monacoLoaderBase || '/static/app/monaco-editor/min/vs';
      require.config({ paths: { vs: vsBase } });
      require(['vs/editor/editor.main'], function () {
        _monacoLoading = false;
        _monacoReady = true;
        callback();
      }, function () {
        _monacoLoading = false;
        _monacoFailed = true;
        callback();
      });
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
    state.orderStepMap = data.order_step_map || state.orderStepMap || {};
    state.rawYaml = data.raw_yaml || state.rawYaml;
    var nextOrderBlockId = state.activeOrderBlockId;
    if (!nextOrderBlockId || !getBlockById(nextOrderBlockId)) {
      nextOrderBlockId = getDefaultOrderBlockId();
    }
    setActiveOrderBlock(nextOrderBlockId, nextOrderBlockId ? state.orderStepMap[nextOrderBlockId] : (data.order_steps || []));
    state.selectedBlockId = data.inserted_block_id || state.selectedBlockId;
    if (!state.selectedBlockId || !getBlockById(state.selectedBlockId) || !isBlockVisibleInOutline(getBlockById(state.selectedBlockId))) {
      state.selectedBlockId = getDefaultVisibleBlockId();
    }
    state.canvasMode = 'question';
    state.questionEditMode = 'preview';
    state.advancedOpen = false;
    state.markdownPreviewMode = false;
    state.dirty = false;
    loadAvailableSymbols();
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

  function cloneData(value) {
    if (value === undefined || value === null) return value;
    return JSON.parse(JSON.stringify(value));
  }

  function uniqueList(items) {
    var seen = {};
    var out = [];
    (items || []).forEach(function (item) {
      var name = String(item || '').trim();
      if (!name || seen[name]) return;
      seen[name] = true;
      out.push(name);
    });
    return out;
  }

  function fuzzyMatch(query, text) {
    var q = String(query || '').toLowerCase().trim();
    var t = String(text || '').toLowerCase();
    if (!q) return true;
    if (t.indexOf(q) !== -1) return true;
    var qi = 0;
    for (var i = 0; i < t.length && qi < q.length; i++) {
      if (t.charAt(i) === q.charAt(qi)) qi += 1;
    }
    return qi === q.length;
  }

  function normalizeSymbolRole(role) {
    role = String(role || 'all').trim() || 'all';
    if (role === 'top-level' || role === 'object-class' || role === 'section' || role === 'static-image') {
      return role;
    }
    return 'all';
  }

  function _looksLikeImageFile(name) {
    return /\.(png|jpe?g|gif|webp|svg|bmp|tiff?)$/i.test(String(name || '').trim());
  }

  function _flattenSymbolGroups(groups) {
    var flattened = [];
    Object.keys(groups || {}).forEach(function (key) {
      var vals = groups[key];
      if (!Array.isArray(vals)) return;
      vals.forEach(function (name) {
        flattened.push({ name: String(name), group: key });
      });
    });
    return flattened;
  }

  function getSymbolCandidates(role) {
    role = normalizeSymbolRole(role);
    var groups = state.symbolCatalog.groups || {};
    var topLevel = state.symbolCatalog.topLevel || [];
    var all = state.symbolCatalog.all || [];

    if (role === 'top-level') {
      return topLevel.map(function (name) { return { name: name, group: 'top_level_names' }; });
    }
    if (role === 'object-class') {
      var classGroupKeys = Object.keys(groups).filter(function (key) {
        return key.toLowerCase().indexOf('class') !== -1 || key.toLowerCase().indexOf('object') !== -1;
      });
      var classLike = [];
      classGroupKeys.forEach(function (key) {
        (groups[key] || []).forEach(function (name) { classLike.push({ name: name, group: key }); });
      });
      if (classLike.length === 0) {
        all.forEach(function (name) {
          if (/^[A-Z]/.test(name)) classLike.push({ name: name, group: 'all_names' });
        });
      }
      return classLike;
    }
    if (role === 'section') {
      var sections = [];
      state.orderSteps.forEach(function collect(step) {
        if (!step) return;
        if (step.kind === 'section' && step.value) sections.push({ name: String(step.value), group: 'section' });
        if (Array.isArray(step.children)) step.children.forEach(collect);
      });
      return sections.concat(topLevel.map(function (name) { return { name: name, group: 'top_level_names' }; }));
    }
    if (role === 'static-image') {
      var staticLike = [];
      Object.keys(groups).forEach(function (key) {
        var keyLower = key.toLowerCase();
        if (keyLower.indexOf('static') === -1 && keyLower.indexOf('image') === -1) return;
        (groups[key] || []).forEach(function (name) {
          if (_looksLikeImageFile(name)) staticLike.push({ name: name, group: key });
        });
      });
      if (!staticLike.length) {
        all.forEach(function (name) {
          if (_looksLikeImageFile(name)) staticLike.push({ name: name, group: 'all_names' });
        });
      }
      return staticLike;
    }
    return _flattenSymbolGroups(groups).concat(all.map(function (name) { return { name: name, group: 'all_names' }; }));
  }

  function getSymbolMatchResult(query, role, limit) {
    limit = limit || 40;
    var matches = [];
    var seen = {};
    var total = 0;
    getSymbolCandidates(role).forEach(function (entry) {
      var name = String(entry.name || '').trim();
      if (!name || seen[name]) return;
      if (!fuzzyMatch(query, name)) return;
      seen[name] = true;
      total += 1;
      if (matches.length < limit) {
        matches.push({ name: name, group: entry.group || 'all_names' });
      }
    });
    matches.sort(function (a, b) {
      var qa = String(query || '').toLowerCase();
      var ai = a.name.toLowerCase().indexOf(qa);
      var bi = b.name.toLowerCase().indexOf(qa);
      if (ai !== bi) return ai - bi;
      return a.name.localeCompare(b.name);
    });
    return { matches: matches, total: total };
  }

  function getSymbolMatches(query, role, limit) {
    return getSymbolMatchResult(query, role, limit).matches;
  }

  function loadAvailableSymbols() {
    if (!state.project || !state.filename) return Promise.resolve();
    var key = state.project + '::' + state.filename;
    if (state.symbolCatalog.loadedFor === key && state.symbolCatalog.all.length) {
      return Promise.resolve();
    }
    return apiGet('/api/variables?project=' + encodeURIComponent(state.project) + '&filename=' + encodeURIComponent(state.filename))
      .then(function (res) {
        if (!res.success || !res.data) return;
        var data = res.data;
        state.symbolCatalog = {
          loadedFor: key,
          all: uniqueList(data.all_names || []),
          topLevel: uniqueList(data.top_level_names || []),
          groups: data.symbol_groups || {},
        };
      })
      .catch(function () {
        state.symbolCatalog = {
          loadedFor: key,
          all: [],
          topLevel: [],
          groups: {},
        };
      });
  }

  function insertTextAtCursor(el, insertText, opts) {
    if (!el) return;
    opts = opts || {};
    var value = String(el.value || '');
    var start = el.selectionStart || 0;
    var end = el.selectionEnd || start;
    var before = value.slice(0, start);
    var selected = value.slice(start, end);
    var after = value.slice(end);
    var replacement = insertText;
    if (opts.wrapSelectionPrefix || opts.wrapSelectionSuffix) {
      replacement = String(opts.wrapSelectionPrefix || '') + (selected || opts.defaultSelection || '') + String(opts.wrapSelectionSuffix || '');
    }
    el.value = before + replacement + after;
    var cursor = (before + replacement).length;
    el.selectionStart = cursor;
    el.selectionEnd = cursor;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.focus();
  }

  function _getTokenCharPattern() {
    return /[A-Za-z0-9_\.\[\]]/;
  }

  function getSymbolTokenRange(value, cursorPos) {
    var text = String(value || '');
    var cursor = Math.max(0, Math.min(Number(cursorPos || 0), text.length));
    var isTokenChar = _getTokenCharPattern();

    var start = cursor;
    while (start > 0 && isTokenChar.test(text.charAt(start - 1))) start -= 1;
    var end = cursor;
    while (end < text.length && isTokenChar.test(text.charAt(end))) end += 1;

    var token = text.slice(start, end);

    // If cursor is inside ${ ... }, use the inner token region.
    var leftBrace = text.lastIndexOf('${', cursor);
    var rightBrace = text.indexOf('}', cursor);
    if (leftBrace !== -1 && rightBrace !== -1 && leftBrace < cursor && rightBrace >= cursor) {
      var innerStart = leftBrace + 2;
      while (innerStart < rightBrace && /\s/.test(text.charAt(innerStart))) innerStart += 1;
      var innerEnd = rightBrace;
      while (innerEnd > innerStart && /\s/.test(text.charAt(innerEnd - 1))) innerEnd -= 1;
      var relCursor = Math.max(innerStart, Math.min(cursor, innerEnd));
      start = relCursor;
      while (start > innerStart && isTokenChar.test(text.charAt(start - 1))) start -= 1;
      end = relCursor;
      while (end < innerEnd && isTokenChar.test(text.charAt(end))) end += 1;
      token = text.slice(start, end);
    }

    var query = String(token || '').replace(/^\$?\{?\s*/, '').replace(/\s*\}?$/, '').trim();
    return { start: start, end: end, query: query };
  }

  function replaceInputRange(inputEl, start, end, replacement) {
    if (!inputEl) return;
    var value = String(inputEl.value || '');
    var safeStart = Math.max(0, Math.min(start, value.length));
    var safeEnd = Math.max(safeStart, Math.min(end, value.length));
    var next = value.slice(0, safeStart) + replacement + value.slice(safeEnd);
    inputEl.value = next;
    var cursor = safeStart + String(replacement).length;
    inputEl.selectionStart = cursor;
    inputEl.selectionEnd = cursor;
    inputEl.dispatchEvent(new Event('input', { bubbles: true }));
    inputEl.focus();
  }

  function renderMarkdownToolbar(targetId, compact) {
    var cls = compact ? ' editor-md-toolbar-compact' : '';
    var html = '<div class="editor-md-toolbar' + cls + '" data-md-toolbar-for="' + esc(targetId) + '">';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="bold" data-target-id="' + esc(targetId) + '" title="Bold"><i class="fa-solid fa-bold" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="italic" data-target-id="' + esc(targetId) + '" title="Italic"><i class="fa-solid fa-italic" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="heading" data-target-id="' + esc(targetId) + '" title="Heading"><i class="fa-solid fa-heading" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="link" data-target-id="' + esc(targetId) + '" title="Link"><i class="fa-solid fa-link" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="image" data-target-id="' + esc(targetId) + '" title="Image"><i class="fa-regular fa-image" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="table" data-target-id="' + esc(targetId) + '" title="Table"><i class="fa-solid fa-table" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="file" data-target-id="' + esc(targetId) + '" title="FILE markup"><i class="fa-solid fa-file-lines" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="qr" data-target-id="' + esc(targetId) + '" title="QR code"><i class="fa-solid fa-qrcode" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="youtube" data-target-id="' + esc(targetId) + '" title="YouTube"><i class="fa-brands fa-youtube" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="field" data-target-id="' + esc(targetId) + '" title="Embed field"><i class="fa-solid fa-i-cursor" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="target" data-target-id="' + esc(targetId) + '" title="Embed target"><i class="fa-solid fa-bullseye" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="twocol" data-target-id="' + esc(targetId) + '" title="Two-column layout"><i class="fa-solid fa-table-columns" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="mako" data-target-id="' + esc(targetId) + '" title="Insert Mako variable"><i class="fa-solid fa-code" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="symbol-raw" data-target-id="' + esc(targetId) + '" title="Insert variable name only"><i class="fa-solid fa-at" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="mako-if" data-target-id="' + esc(targetId) + '" title="Insert Mako conditional"><i class="fa-solid fa-code-branch" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="mako-for" data-target-id="' + esc(targetId) + '" title="Insert Mako loop"><i class="fa-solid fa-repeat" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="mako-python" data-target-id="' + esc(targetId) + '" title="Insert Mako Python block"><i class="fa-solid fa-terminal" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="docs-markup" data-target-id="' + esc(targetId) + '" title="Docassemble markup docs"><i class="fa-solid fa-book" aria-hidden="true"></i></button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-md-insert="docs-mako" data-target-id="' + esc(targetId) + '" title="Mako syntax docs"><i class="fa-solid fa-book-open" aria-hidden="true"></i></button>';
    html += '</div>';
    return html;
  }

  function _buildDocassembleImageToken(fileRef, width, altText) {
    var parts = [String(fileRef || '').trim()];
    var widthVal = String(width || '').trim();
    var altVal = String(altText || '').trim();
    if (widthVal || altVal) {
      parts.push(widthVal || 'None');
    }
    if (altVal) {
      parts.push(altVal);
    }
    return '[FILE ' + parts.join(', ') + ']';
  }

  function openMarkupInsertModal(context) {
    _symbolInsertContext = context || null;
    var header = document.getElementById('symbol-insert-title');
    var searchWrap = document.getElementById('symbol-insert-search-wrap');
    var listWrap = document.getElementById('symbol-insert-list-wrap');
    var formWrap = document.getElementById('symbol-insert-form-wrap');
    var formBody = document.getElementById('symbol-insert-form-body');
    var applyBtn = document.getElementById('symbol-insert-apply');
    if (!formWrap || !formBody || !applyBtn) return;

    if (header) header.textContent = 'Insert Markup';
    if (searchWrap) searchWrap.classList.add('d-none');
    if (listWrap) listWrap.classList.add('d-none');
    formWrap.classList.remove('d-none');
    applyBtn.classList.remove('d-none');
    applyBtn.setAttribute('data-insert-form-action', String(context.action || ''));

    var action = String(context.action || '');
    var html = '';
    if (action === 'link') {
      html += '<label class="editor-tiny" for="insert-link-text">Visible text</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-link-text" value="link text">';
      html += '<label class="editor-tiny mt-2" for="insert-link-url">URL</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-link-url" value="https://">';
    } else if (action === 'image') {
      html += '<label class="editor-tiny" for="insert-image-kind">Image source</label>';
      html += '<select class="form-select form-select-sm mt-1" id="insert-image-kind">';
      html += '<option value="static">From project static folder</option>';
      html += '<option value="url">External URL</option>';
      html += '</select>';
      html += '<label class="editor-tiny mt-2" for="insert-image-ref">File name or URL</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-image-ref" data-symbol-role="static-image" placeholder="example.png or https://...">';
      html += '<div class="editor-tiny mt-1">Type to filter available static images, or paste a full URL.</div>';
      html += '<label class="editor-tiny mt-2" for="insert-image-width">Width (optional)</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-image-width" placeholder="100% or 250px">';
      html += '<label class="editor-tiny mt-2" for="insert-image-alt">Alt text (optional)</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-image-alt" placeholder="Describe the image">';
    } else if (action === 'table') {
      html += '<label class="editor-tiny" for="insert-table-cols">Columns</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-table-cols" type="number" min="2" max="8" value="2">';
      html += '<label class="editor-tiny mt-2" for="insert-table-rows">Data rows</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-table-rows" type="number" min="1" max="20" value="3">';
    } else if (action === 'file') {
      html += '<label class="editor-tiny" for="insert-file-ref">File reference</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-file-ref" placeholder="filename.ext or package:file.ext">';
      html += '<label class="editor-tiny mt-2" for="insert-file-width">Width (optional)</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-file-width" placeholder="100% or 250px">';
      html += '<label class="editor-tiny mt-2" for="insert-file-alt">Alt text (optional)</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-file-alt" placeholder="Accessible description">';
    } else if (action === 'qr') {
      html += '<label class="editor-tiny" for="insert-qr-text">QR text or URL</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-qr-text" value="https://">';
      html += '<label class="editor-tiny mt-2" for="insert-qr-width">Width (optional)</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-qr-width" placeholder="200px">';
      html += '<label class="editor-tiny mt-2" for="insert-qr-alt">Alt text (optional)</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-qr-alt" placeholder="QR code description">';
    } else if (action === 'youtube') {
      html += '<label class="editor-tiny" for="insert-youtube-id">YouTube video ID</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-youtube-id" placeholder="RpgYyuLt7Dx">';
    } else if (action === 'field') {
      html += '<label class="editor-tiny" for="insert-field-name">Field variable</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-field-name" data-symbol-role="all" placeholder="user.name.first">';
    } else if (action === 'target') {
      html += '<label class="editor-tiny" for="insert-target-name">Target name</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-target-name" data-symbol-role="all" placeholder="interim_status">';
    } else if (action === 'twocol') {
      html += '<label class="editor-tiny" for="insert-twocol-left">Left column text</label>';
      html += '<textarea class="form-control form-control-sm mt-1" id="insert-twocol-left" rows="2"></textarea>';
      html += '<label class="editor-tiny mt-2" for="insert-twocol-right">Right column text</label>';
      html += '<textarea class="form-control form-control-sm mt-1" id="insert-twocol-right" rows="2"></textarea>';
    }
    formBody.innerHTML = html;

    var modal = getOrCreateBootstrapModal('symbol-insert-modal');
    if (modal) modal.show();
  }

  function buildInsertionFromForm(action) {
    action = String(action || '');
    if (action === 'link') {
      var linkText = (document.getElementById('insert-link-text') || {}).value || 'link text';
      var linkUrl = (document.getElementById('insert-link-url') || {}).value || 'https://';
      return '[' + String(linkText).trim() + '](' + String(linkUrl).trim() + ')';
    }
    if (action === 'image') {
      var kind = (document.getElementById('insert-image-kind') || {}).value || 'static';
      var imageRefRaw = ((document.getElementById('insert-image-ref') || {}).value || '').trim();
      var imageWidth = ((document.getElementById('insert-image-width') || {}).value || '').trim();
      var imageAlt = ((document.getElementById('insert-image-alt') || {}).value || '').trim();
      if (!imageRefRaw) return '';
      if (kind === 'url' || /^https?:\/\//i.test(imageRefRaw)) {
        var altText = imageAlt || 'Image';
        return '![' + altText + '](' + imageRefRaw + ')';
      }
      return _buildDocassembleImageToken(imageRefRaw, imageWidth, imageAlt);
    }
    if (action === 'table') {
      var colCount = parseInt(((document.getElementById('insert-table-cols') || {}).value || '2'), 10);
      var rowCount = parseInt(((document.getElementById('insert-table-rows') || {}).value || '3'), 10);
      if (!Number.isFinite(colCount) || colCount < 2) colCount = 2;
      if (!Number.isFinite(rowCount) || rowCount < 1) rowCount = 3;
      var headerCells = [];
      var sepCells = [];
      var lines = [];
      for (var ci = 0; ci < colCount; ci++) {
        headerCells.push('Column ' + (ci + 1));
        sepCells.push('---');
      }
      lines.push(headerCells.join(' | '));
      lines.push(sepCells.join('|'));
      for (var ri = 0; ri < rowCount; ri++) {
        var row = [];
        for (var cj = 0; cj < colCount; cj++) row.push('Value');
        lines.push(row.join(' | '));
      }
      return lines.join('\n');
    }
    if (action === 'file') {
      var fileRef = ((document.getElementById('insert-file-ref') || {}).value || '').trim();
      var fileWidth = ((document.getElementById('insert-file-width') || {}).value || '').trim();
      var fileAlt = ((document.getElementById('insert-file-alt') || {}).value || '').trim();
      if (!fileRef) return '';
      return _buildDocassembleImageToken(fileRef, fileWidth, fileAlt);
    }
    if (action === 'qr') {
      var qrText = ((document.getElementById('insert-qr-text') || {}).value || '').trim();
      var qrWidth = ((document.getElementById('insert-qr-width') || {}).value || '').trim();
      var qrAlt = ((document.getElementById('insert-qr-alt') || {}).value || '').trim();
      if (!qrText) return '';
      var qrParts = [qrText];
      if (qrWidth || qrAlt) qrParts.push(qrWidth || 'None');
      if (qrAlt) qrParts.push(qrAlt);
      return '[QR ' + qrParts.join(', ') + ']';
    }
    if (action === 'youtube') {
      var ytId = ((document.getElementById('insert-youtube-id') || {}).value || '').trim();
      if (!ytId) return '';
      return '[YOUTUBE ' + ytId + ']';
    }
    if (action === 'field') {
      var fieldName = ((document.getElementById('insert-field-name') || {}).value || '').trim();
      return fieldName ? '[FIELD ' + fieldName + ']' : '';
    }
    if (action === 'target') {
      var targetName = ((document.getElementById('insert-target-name') || {}).value || '').trim();
      return targetName ? '[TARGET ' + targetName + ']' : '';
    }
    if (action === 'twocol') {
      var left = ((document.getElementById('insert-twocol-left') || {}).value || '').trim();
      var right = ((document.getElementById('insert-twocol-right') || {}).value || '').trim();
      return '[BEGIN_TWOCOL]\n' + left + '\n[BREAK]\n' + right + '\n[END_TWOCOL]';
    }
    return '';
  }

  function openSymbolInsertModal(context) {
    _symbolInsertContext = context || null;
    var header = document.getElementById('symbol-insert-title');
    var searchWrap = document.getElementById('symbol-insert-search-wrap');
    var listWrap = document.getElementById('symbol-insert-list-wrap');
    var formWrap = document.getElementById('symbol-insert-form-wrap');
    var applyBtn = document.getElementById('symbol-insert-apply');
    var search = document.getElementById('symbol-insert-search');
    var list = document.getElementById('symbol-insert-list');
    var summary = document.getElementById('symbol-insert-summary');
    if (!search || !list) return;
    if (header) header.textContent = 'Name or Formatting';
    if (searchWrap) searchWrap.classList.remove('d-none');
    if (listWrap) listWrap.classList.remove('d-none');
    if (formWrap) formWrap.classList.add('d-none');
    if (applyBtn) applyBtn.classList.add('d-none');
    search.value = '';
    list.innerHTML = '';

    var result = getSymbolMatchResult('', context && context.role, 80);
    var matches = result.matches;
    matches.forEach(function (entry) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'editor-symbol-item';
      item.setAttribute('data-symbol-name', entry.name);
      item.innerHTML = '<span class="editor-symbol-item-name">' + esc(entry.name) + '</span>' +
        '<span class="editor-symbol-item-group">' + esc(entry.group || '') + '</span>';
      list.appendChild(item);
    });
    if (summary) {
      if (result.total > matches.length) {
        summary.textContent = 'Showing ' + matches.length + ' of ' + result.total + ' names. Keep typing to filter more.';
      } else if (matches.length) {
        summary.textContent = 'Showing ' + matches.length + ' available names.';
      } else {
        summary.textContent = 'No matching names found.';
      }
    }

    var modal = getOrCreateBootstrapModal('symbol-insert-modal');
    if (modal) modal.show();
    window.setTimeout(function () { search.focus(); }, 50);
  }

  function refreshSymbolInsertModalList(query) {
    if (!_symbolInsertContext) return;
    var list = document.getElementById('symbol-insert-list');
    var summary = document.getElementById('symbol-insert-summary');
    if (!list) return;
    var result = getSymbolMatchResult(query || '', _symbolInsertContext.role, 80);
    var matches = result.matches;
    list.innerHTML = '';
    matches.forEach(function (entry) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'editor-symbol-item';
      item.setAttribute('data-symbol-name', entry.name);
      item.innerHTML = '<span class="editor-symbol-item-name">' + esc(entry.name) + '</span>' +
        '<span class="editor-symbol-item-group">' + esc(entry.group || '') + '</span>';
      list.appendChild(item);
    });
    if (summary) {
      if (result.total > matches.length) {
        summary.textContent = 'Showing ' + matches.length + ' of ' + result.total + ' names. Keep typing to filter more.';
      } else if (matches.length) {
        summary.textContent = 'Showing ' + matches.length + ' available names.';
      } else {
        summary.textContent = 'No matching names found.';
      }
    }
  }

  function applyMarkdownInsert(targetEl, action) {
    if (!targetEl) return;
    if (action === 'bold') {
      insertTextAtCursor(targetEl, '', { wrapSelectionPrefix: '**', wrapSelectionSuffix: '**', defaultSelection: 'bold text' });
    } else if (action === 'italic') {
      insertTextAtCursor(targetEl, '', { wrapSelectionPrefix: '*', wrapSelectionSuffix: '*', defaultSelection: 'italic text' });
    } else if (action === 'heading') {
      insertTextAtCursor(targetEl, '## ');
    } else if (action === 'link') {
      openMarkupInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'all', insertMode: 'markup-form', action: 'link' });
    } else if (action === 'image') {
      openMarkupInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'static-image', insertMode: 'markup-form', action: 'image' });
    } else if (action === 'table') {
      openMarkupInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'all', insertMode: 'markup-form', action: 'table' });
    } else if (action === 'file') {
      openMarkupInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'all', insertMode: 'markup-form', action: 'file' });
    } else if (action === 'qr') {
      openMarkupInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'all', insertMode: 'markup-form', action: 'qr' });
    } else if (action === 'youtube') {
      openMarkupInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'all', insertMode: 'markup-form', action: 'youtube' });
    } else if (action === 'field') {
      openMarkupInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'all', insertMode: 'markup-form', action: 'field' });
    } else if (action === 'target') {
      openMarkupInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'all', insertMode: 'markup-form', action: 'target' });
    } else if (action === 'twocol') {
      openMarkupInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'all', insertMode: 'markup-form', action: 'twocol' });
    } else if (action === 'mako') {
      var cursorPos = Number(targetEl.selectionStart || 0);
      var text = String(targetEl.value || '');
      var leftBrace = text.lastIndexOf('${', cursorPos);
      var rightBrace = text.indexOf('}', cursorPos);
      var insideMako = leftBrace !== -1 && rightBrace !== -1 && leftBrace < cursorPos && rightBrace >= cursorPos;
      openSymbolInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'all', insertMode: insideMako ? 'raw' : 'mako' });
    } else if (action === 'symbol-raw') {
      openSymbolInsertModal({ targetId: targetEl.id || null, targetEl: targetEl, role: 'all', insertMode: 'raw' });
    } else if (action === 'mako-if') {
      insertTextAtCursor(targetEl, '% if condition_here:\nText when true\n% endif');
    } else if (action === 'mako-for') {
      insertTextAtCursor(targetEl, '% for item in items:\n- ${ item }\n% endfor');
    } else if (action === 'mako-python') {
      insertTextAtCursor(targetEl, '<%\n  # python statements\n%>\n${ value }');
    } else if (action === 'docs-markup') {
      window.open(DOCASSEMBLE_MARKUP_DOCS_URL, '_blank');
    } else if (action === 'docs-mako') {
      window.open(MAKO_DOCS_URL, '_blank');
    }
  }

  function applySelectedSymbolToContext(symbolName) {
    if (!_symbolInsertContext || !symbolName) return;
    var ctx = _symbolInsertContext;
    var target = ctx.targetEl;
    if (!target && ctx.targetId) target = document.getElementById(ctx.targetId);
    if (!target) return;

    var mode = ctx.insertMode || 'raw';
    if (mode === 'mako') {
      insertTextAtCursor(target, '${' + symbolName + '}');
    } else if (mode === 'raw') {
      insertTextAtCursor(target, symbolName);
    } else if (mode === 'label-menu') {
      insertTextAtCursor(target, '${' + symbolName + '}');
    } else {
      insertTextAtCursor(target, symbolName);
    }
  }

  function getOrCreateTypeaheadMenu() {
    var menu = document.getElementById('editor-symbol-typeahead');
    if (menu) return menu;
    menu = document.createElement('div');
    menu.id = 'editor-symbol-typeahead';
    menu.className = 'editor-symbol-typeahead d-none';
    menu.innerHTML = '<div class="editor-symbol-typeahead-list" id="editor-symbol-typeahead-list"></div>';
    document.body.appendChild(menu);
    return menu;
  }

  function hideTypeaheadMenu() {
    var menu = document.getElementById('editor-symbol-typeahead');
    if (!menu) return;
    menu.classList.add('d-none');
    menu.removeAttribute('data-target-id');
  }

  function showTypeaheadForInput(inputEl) {
    if (!inputEl) return;
    var role = inputEl.getAttribute('data-symbol-role');
    if (!role) return;
    var token = getSymbolTokenRange(inputEl.value || '', inputEl.selectionStart || 0);
    var result = getSymbolMatchResult(token.query || '', role, 16);
    var matches = result.matches;
    if (matches.length === 0) {
      hideTypeaheadMenu();
      return;
    }
    var menu = getOrCreateTypeaheadMenu();
    var list = document.getElementById('editor-symbol-typeahead-list');
    if (!list) return;
    var targetId = inputEl.id || ('symbol-input-' + Date.now());
    if (!inputEl.id) inputEl.id = targetId;

    var html = '';
    matches.forEach(function (entry) {
      html += '<button type="button" class="editor-symbol-typeahead-item" data-typeahead-name="' + esc(entry.name) + '" data-target-id="' + esc(targetId) + '" data-typeahead-start="' + token.start + '" data-typeahead-end="' + token.end + '">';
      html += '<span>' + esc(entry.name) + '</span>';
      html += '<span class="editor-symbol-typeahead-group">' + esc(entry.group || '') + '</span>';
      html += '</button>';
    });
    if (result.total > matches.length) {
      html += '<div class="editor-symbol-typeahead-more">Showing ' + matches.length + ' of ' + result.total + ' names. Type to narrow.</div>';
    }
    list.innerHTML = html;

    var rect = inputEl.getBoundingClientRect();
    menu.style.left = (window.scrollX + rect.left) + 'px';
    menu.style.top = (window.scrollY + rect.bottom + 4) + 'px';
    menu.style.width = Math.max(rect.width, 260) + 'px';
    menu.classList.remove('d-none');
    menu.setAttribute('data-target-id', targetId);
  }

  function getBlockById(blockId) {
    if (!blockId) return null;
    for (var i = 0; i < state.blocks.length; i++) {
      if (state.blocks[i].id === blockId) return state.blocks[i];
    }
    return null;
  }

  function getOrderBlocks() {
    return state.orderIndices.map(function (idx) { return state.blocks[idx]; }).filter(Boolean);
  }

  function getOrderTargets() {
    var blocks = getOrderBlocks().slice();
    var seen = {};
    blocks.forEach(function (block) { seen[block.id] = true; });
    var activeBlock = getBlockById(state.activeOrderBlockId);
    if (activeBlock && activeBlock.type === 'code' && !seen[activeBlock.id]) {
      blocks.push(activeBlock);
    }
    return blocks;
  }

  function getDefaultOrderBlockId() {
    if (state.activeOrderBlockId && getBlockById(state.activeOrderBlockId)) return state.activeOrderBlockId;
    var orderBlocks = getOrderBlocks();
    if (orderBlocks.length > 0) return orderBlocks[0].id;
    var selected = getSelectedBlock();
    if (selected && selected.type === 'code') return selected.id;
    return null;
  }

  function setActiveOrderBlock(blockId, steps) {
    state.activeOrderBlockId = blockId || null;
    state.orderSteps = cloneData(steps || (blockId ? state.orderStepMap[blockId] : []) || []) || [];
    state.selectedOrderStepIds = {};
  }

  function syncActiveOrderStepMap() {
    if (!state.activeOrderBlockId) return;
    state.orderStepMap[state.activeOrderBlockId] = cloneData(state.orderSteps) || [];
  }

  function loadOrderStepsForBlock(blockId) {
    var block = getBlockById(blockId);
    if (!block || block.type !== 'code') return Promise.resolve([]);
    if (Object.prototype.hasOwnProperty.call(state.orderStepMap, blockId)) {
      setActiveOrderBlock(blockId, state.orderStepMap[blockId]);
      return Promise.resolve(state.orderSteps);
    }
    var code = (block.data && block.data.code) ? String(block.data.code) : '';
    return apiGet('/api/parse-order?code=' + encodeURIComponent(code)).then(function (res) {
      var steps = (res.success && res.data && Array.isArray(res.data.steps)) ? res.data.steps : [];
      state.orderStepMap[blockId] = steps;
      setActiveOrderBlock(blockId, steps);
      return steps;
    });
  }

  function cleanOrderText(text) {
    return String(text || '').replace(/^Ask\s+/i, '').trim();
  }

  function getOrderStepBadge(step) {
    if (!step) return '';
    if (step.kind === 'gather') return 'g';
    if (step.kind === 'condition') return 'if';
    if (step.kind === 'section') return 'sec';
    if (step.kind === 'progress') return '%';
    if (step.kind === 'function') return 'f';
    if (step.kind === 'raw') return 'p';
    return '';
  }

  function getOrderStepPresentation(step) {
    var heading = getOrderStepHeading(step);
    var detail = getOrderStepDetail(step);
    var tooltip = '';
    if (step && step.kind === 'screen') {
      var screenBlock = findBlockByInvoke(step);
      var title = screenBlock ? cleanOrderText(screenBlock.title || '') : '';
      var variable = cleanOrderText(step.invoke || step.summary || '');
      if (title) {
        heading = title;
        detail = '';
        tooltip = variable && variable !== title ? variable : '';
      } else if (variable) {
        heading = variable;
        tooltip = title && title !== variable ? title : '';
      }
    }
    return {
      heading: heading,
      detail: detail,
      tooltip: tooltip
    };
  }

  function getOrderBranchSteps(step, branch) {
    if (!step) return [];
    if (branch === 'else') {
      if (!Array.isArray(step.else_children)) step.else_children = [];
      return step.else_children;
    }
    if (!Array.isArray(step.children)) step.children = [];
    return step.children;
  }

  function findBlockByInvoke(step) {
    if (!step) return null;
    if (step.blockId) {
      var byId = getBlockById(step.blockId);
      if (byId) return byId;
    }
    if (!step.invoke) return null;
    for (var i = 0; i < state.blocks.length; i++) {
      if (state.blocks[i].variable === step.invoke) return state.blocks[i];
    }
    return null;
  }

  function getOrderStepHeading(step) {
    if (!step) return '';
    if (step.kind === 'screen') {
      var screenBlock = findBlockByInvoke(step);
      return screenBlock ? screenBlock.title : cleanOrderText(step.summary || step.invoke || 'Screen');
    }
    if (step.kind === 'gather') return cleanOrderText(step.summary || step.invoke || 'Gather');
    if (step.kind === 'condition') return cleanOrderText(step.condition || step.summary || 'condition');
    if (step.kind === 'section') return cleanOrderText(step.summary || step.value || 'Section');
    if (step.kind === 'progress') return cleanOrderText(step.summary || (step.value ? 'Progress ' + step.value + '%' : 'Progress'));
    return cleanOrderText(step.summary || step.invoke || step.code || step.label || step.kind);
  }

  function getOrderStepDetail(step) {
    if (!step) return '';
    if (step.kind === 'screen' || step.kind === 'gather') return '';
    if (step.kind === 'condition') {
      var childCount = Array.isArray(step.children) ? step.children.length : 0;
      var elseCount = Array.isArray(step.else_children) ? step.else_children.length : 0;
      var parts = [childCount + ' then'];
      if (step.has_else) parts.push(elseCount + ' else');
      return parts.join(' · ');
    }
    if (step.kind === 'section') return step.value || '';
    if (step.kind === 'progress') return step.value ? step.value + '%' : '';
    if (step.kind === 'function') return step.invoke || '';
    if (step.kind === 'raw') return cleanOrderText((step.code || '').split('\n')[0]);
    return '';
  }

  function createOrderStep(kind) {
    var uniqueId = 'step-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
    if (kind === 'screen') return { id: uniqueId, kind: kind, label: 'Screen', summary: 'Select a screen', invoke: '' };
    if (kind === 'gather') return { id: uniqueId, kind: kind, label: 'List gather', summary: 'Gather a list', invoke: '' };
    if (kind === 'section') return { id: uniqueId, kind: kind, label: 'Start section', summary: 'Section: New section', value: 'New section' };
    if (kind === 'progress') return { id: uniqueId, kind: kind, label: 'Progress', summary: 'Progress: 50%', value: '50' };
    if (kind === 'condition') return { id: uniqueId, kind: kind, label: 'Condition', summary: 'condition_here', condition: 'condition_here', children: [], has_else: false, else_children: [] };
    if (kind === 'function') return { id: uniqueId, kind: kind, label: 'Function', summary: 'function_call()', invoke: 'function_call()' };
    return { id: uniqueId, kind: 'raw', label: 'Raw Python', summary: 'pass', code: 'pass' };
  }

  function findStepRecord(stepList, stepId, parentStep) {
    for (var i = 0; i < stepList.length; i++) {
      var step = stepList[i];
      if (step.id === stepId) {
        return { step: step, index: i, list: stepList, parent: parentStep || null };
      }
      if (Array.isArray(step.children) && step.children.length) {
        var nested = findStepRecord(step.children, stepId, step);
        if (nested) return nested;
      }
      if (Array.isArray(step.else_children) && step.else_children.length) {
        var nestedElse = findStepRecord(step.else_children, stepId, step);
        if (nestedElse) return nestedElse;
      }
    }
    return null;
  }

  function renderOrderCodePreview(stepList, indent) {
    indent = indent || 2;
    var lines = [];
    stepList.forEach(function (step, index) {
      var prefix = new Array(indent + 1).join(' ');
      if (step.kind === 'section') lines.push(prefix + "set_parts(subtitle='" + String(step.value || '') + "')");
      else if (step.kind === 'progress') lines.push(prefix + 'set_progress(' + String(step.value || '0') + ')');
      else if (step.kind === 'gather' || step.kind === 'screen' || step.kind === 'function') lines.push(prefix + String(step.invoke || ''));
      else if (step.kind === 'condition') {
        lines.push(prefix + 'if ' + String(step.condition || step.summary || 'True') + ':');
        if (Array.isArray(step.children) && step.children.length) {
          lines.push(renderOrderCodePreview(step.children, indent + 2));
        } else {
          lines.push(new Array(indent + 3).join(' ') + 'pass');
        }
        if (step.has_else) {
          lines.push(prefix + 'else:');
          if (Array.isArray(step.else_children) && step.else_children.length) {
            lines.push(renderOrderCodePreview(step.else_children, indent + 2));
          } else {
            lines.push(new Array(indent + 3).join(' ') + 'pass');
          }
        }
      } else {
        String(step.code || '').split('\n').forEach(function (line) {
          lines.push(prefix + line);
        });
      }
    });
    return lines.join('\n');
  }

  function wrapSelectedOrderSteps() {
    var selectedIds = Object.keys(state.selectedOrderStepIds).filter(function (stepId) { return state.selectedOrderStepIds[stepId]; });
    if (selectedIds.length === 0) return false;

    function attemptWrap(stepList) {
      var indices = [];
      for (var i = 0; i < stepList.length; i++) {
        if (selectedIds.indexOf(stepList[i].id) !== -1) indices.push(i);
      }
      if (indices.length === selectedIds.length && indices.length > 0) {
        for (var j = 1; j < indices.length; j++) {
          if (indices[j] !== indices[j - 1] + 1) return false;
        }
        var firstIndex = indices[0];
        var wrappedChildren = stepList.slice(firstIndex, indices[indices.length - 1] + 1);
        var conditionStep = createOrderStep('condition');
        conditionStep.children = cloneData(wrappedChildren);
        stepList.splice(firstIndex, wrappedChildren.length, conditionStep);
        state.selectedOrderStepIds = {};
        state.orderCollapsed[conditionStep.id] = false;
        return true;
      }
      for (var k = 0; k < stepList.length; k++) {
        if (Array.isArray(stepList[k].children) && stepList[k].children.length && attemptWrap(stepList[k].children)) {
          return true;
        }
        if (Array.isArray(stepList[k].else_children) && stepList[k].else_children.length && attemptWrap(stepList[k].else_children)) {
          return true;
        }
      }
      return false;
    }

    var didWrap = attemptWrap(state.orderSteps);
    if (didWrap) syncActiveOrderStepMap();
    return didWrap;
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
      state.orderStepMap = d.order_step_map || {};
      state.rawYaml = d.raw_yaml || '';
      state.dirty = false;
      state.selectedBlockId = getDefaultVisibleBlockId();
      setActiveOrderBlock(getDefaultOrderBlockId(), d.order_steps || []);
      loadAvailableSymbols();
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

  function isBlockVisibleInOutline(block) {
    if (!block) return false;
    var visible = filteredBlocks();
    for (var i = 0; i < visible.length; i++) {
      if (visible[i].id === block.id) return true;
    }
    return false;
  }

  function getDefaultVisibleBlockId() {
    var visible = filteredBlocks();
    if (visible.length > 0) return visible[0].id;
    return state.blocks.length ? state.blocks[0].id : null;
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
    html += '<div class="editor-outline-insert"><button type="button" class="editor-outline-insert-btn" data-insert-after-id=""><span class="editor-outline-insert-line" aria-hidden="true"></span><span class="editor-outline-insert-icon"><i class="fa-solid fa-plus" aria-hidden="true"></i></span><span class="visually-hidden">Insert block at top</span></button></div>';
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
      html += '<div class="editor-outline-insert"><button type="button" class="editor-outline-insert-btn" data-insert-after-id="' + esc(block.id) + '"><span class="editor-outline-insert-line" aria-hidden="true"></span><span class="editor-outline-insert-icon"><i class="fa-solid fa-plus" aria-hidden="true"></i></span><span class="visually-hidden">Insert block after ' + esc(block.title) + '</span></button></div>';
    });
    outlineList.innerHTML = html;
  }

  // -------------------------------------------------------------------------
  // Canvas dispatcher
  // -------------------------------------------------------------------------
  function getSelectedBlock() {
    if (!state.selectedBlockId) {
      var defaultId = getDefaultVisibleBlockId();
      return defaultId ? getBlockById(defaultId) : null;
    }
    for (var i = 0; i < state.blocks.length; i++) {
      if (state.blocks[i].id === state.selectedBlockId) {
        if (state.filterQuestionsOnly && state.blocks[i].type !== 'question') {
          var visibleId = getDefaultVisibleBlockId();
          return visibleId ? getBlockById(visibleId) : null;
        }
        return state.blocks[i];
      }
    }
    var fallbackId = getDefaultVisibleBlockId();
    return fallbackId ? getBlockById(fallbackId) : null;
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
        html += renderMarkdownToolbar('q-title', false);
        html += '<textarea class="form-control editor-form-control" id="q-title" rows="1">' + esc(data.question || '') + '</textarea>';
      }
      html += '</div>';

      // Subquestion — always shown
      html += '<div class="editor-form-group">';
      html += '<label class="editor-tiny" for="q-subquestion">Subquestion</label>';
      if (isMdPreview) {
        html += '<div class="md-preview-wrapper">' + renderMarkdown(String(data.subquestion || '')) + '</div>';
      } else {
        html += renderMarkdownToolbar('q-subquestion', false);
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
            html += '<textarea class="form-control editor-form-control" data-field-prop="label" data-label-field="true" rows="1" placeholder="Field label" title="Right-click for insert tools">' + esc(label) + '</textarea>';
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
    html += '<button class="btn btn-sm btn-outline-secondary" id="code-to-order-builder">Interview order mode</button>';
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
          html += '<input class="editor-obj-input" data-obj-prop="name" data-symbol-role="top-level" value="' + esc(name) + '" placeholder="variable_name">';
          html += '<input class="editor-obj-input" data-obj-prop="class" data-symbol-role="object-class" value="' + esc(cls) + '" placeholder="ClassName.using(...)">';
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
    var activeOrderBlock = getBlockById(state.activeOrderBlockId);
    if (state.fullYamlTab === 'order') {
      var orderTargets = getOrderTargets();
      if (orderTargets.length > 0) {
        html += '<div class="editor-order-block-switcher mb-3">';
        orderTargets.forEach(function (block) {
          var isActive = activeOrderBlock && activeOrderBlock.id === block.id;
          html += '<button type="button" class="btn btn-sm ' + (isActive ? 'btn-primary' : 'btn-outline-secondary') + '" data-order-block-id="' + esc(block.id) + '">';
          html += esc(block.title || block.id);
          if (block.tags && block.tags.indexOf('mandatory') !== -1) html += ' <span class="editor-inline-meta">Order</span>';
          html += '</button>';
        });
        html += '</div>';
      }
    }
    html += '<div class="editor-monaco-container" id="' + editorId + '" style="height:600px"></div>';
    html += '</div></div>';

    html += '<div class="d-flex justify-content-end"><button class="btn btn-primary" id="save-full-yaml">Save</button></div>';
    html += '</div>';
    canvasContent.innerHTML = html;

    var content = '';
    if (state.fullYamlTab === 'full') {
      content = state.rawYaml;
    } else if (state.fullYamlTab === 'order') {
      if (activeOrderBlock) {
        content = activeOrderBlock.yaml;
      } else {
        content = '# No interview-order block selected';
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
  function renderOrderInsertRow(parentStepId, branch, index, depth) {
    var html = '<div class="editor-order-insert" style="--order-depth:' + depth + '">';
    html += '<div class="editor-order-insert-controls">';
    html += '<button type="button" class="btn btn-sm btn-outline-primary" data-add-step="screen" data-parent-step-id="' + esc(parentStepId || '') + '" data-step-branch="' + esc(branch || 'then') + '" data-insert-index="' + index + '">+ Screen</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-step="gather" data-parent-step-id="' + esc(parentStepId || '') + '" data-step-branch="' + esc(branch || 'then') + '" data-insert-index="' + index + '">G</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-step="condition" data-parent-step-id="' + esc(parentStepId || '') + '" data-step-branch="' + esc(branch || 'then') + '" data-insert-index="' + index + '">If</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-step="section" data-parent-step-id="' + esc(parentStepId || '') + '" data-step-branch="' + esc(branch || 'then') + '" data-insert-index="' + index + '">Sec</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-step="progress" data-parent-step-id="' + esc(parentStepId || '') + '" data-step-branch="' + esc(branch || 'then') + '" data-insert-index="' + index + '">%</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-step="function" data-parent-step-id="' + esc(parentStepId || '') + '" data-step-branch="' + esc(branch || 'then') + '" data-insert-index="' + index + '">f</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-step="raw" data-parent-step-id="' + esc(parentStepId || '') + '" data-step-branch="' + esc(branch || 'then') + '" data-insert-index="' + index + '">p</button>';
    html += '</div></div>';
    return html;
  }

  function renderOrderBranch(step, depth, branch, label) {
    var branchSteps = getOrderBranchSteps(step, branch);
    var html = '<div class="editor-order-branch">';
    html += '<div class="editor-order-branch-label">' + esc(label) + '</div>';
    html += renderOrderStepTree(branchSteps, depth, step.id, branch);
    if (branchSteps.length === 0) {
      html += '<div class="editor-order-empty">No ' + esc(label.toLowerCase()) + ' steps yet.</div>';
    }
    html += '</div>';
    return html;
  }

  function renderOrderStepTree(stepList, depth, parentStepId, branch) {
    var html = '';
    depth = depth || 0;
    parentStepId = parentStepId || '';
    branch = branch || 'then';
    html += renderOrderInsertRow(parentStepId, branch, 0, depth);
    stepList.forEach(function (step) {
      var presentation = getOrderStepPresentation(step);
      var isCollapsed = Boolean(state.orderCollapsed[step.id]);
      var hasChildren = Array.isArray(step.children) && step.children.length > 0;
      var hasElse = Boolean(step.has_else);
      var kindBadge = getOrderStepBadge(step);
      html += '<div class="editor-order-step-shell" style="--order-depth:' + depth + '">';
      html += '<div class="editor-order-step' + (step.kind === 'condition' ? ' editor-order-step-condition' : '') + '" data-step-id="' + esc(step.id) + '">';
      html += '<div class="editor-order-step-top">';
      html += '<div class="editor-order-step-main">';
      if (depth === 0) html += '<span class="drag-handle" title="Drag to reorder">&#9776;</span>';
      else html += '<span class="editor-order-indent" aria-hidden="true"></span>';
      html += '<input type="checkbox" class="form-check-input editor-order-select" data-step-select="' + esc(step.id) + '"' + (state.selectedOrderStepIds[step.id] ? ' checked' : '') + '>';
      if (step.kind === 'condition') {
        html += '<button type="button" class="editor-order-collapse" data-step-action="toggle-collapse" data-step-id="' + esc(step.id) + '" title="' + (isCollapsed ? 'Expand' : 'Collapse') + '">';
        html += '<i class="fa-solid ' + (isCollapsed ? 'fa-chevron-right' : 'fa-chevron-down') + '" aria-hidden="true"></i>';
        html += '</button>';
      } else {
        html += '<span class="editor-order-collapse-spacer" aria-hidden="true"></span>';
      }
      if (kindBadge) {
        html += '<span class="editor-order-badge" title="' + esc(step.label || step.kind) + '">' + esc(kindBadge) + '</span>';
      }
      html += '<span class="editor-order-title"' + (presentation.tooltip ? ' title="' + esc(presentation.tooltip) + '"' : '') + '>' + esc(presentation.heading) + '</span>';
      if (presentation.detail) {
        html += '<span class="editor-order-detail">' + esc(presentation.detail) + '</span>';
      }
      html += '</div>';
      html += '<div class="editor-order-step-actions">';
      if (step.kind === 'condition') {
        if (!hasElse) {
          html += '<button type="button" class="btn btn-sm btn-outline-secondary py-0 px-2" data-step-action="add-else" data-step-id="' + esc(step.id) + '" title="Add else branch">Else</button>';
        }
      }
      html += '<button type="button" class="btn btn-sm btn-outline-secondary py-0 px-1" data-step-action="edit" data-step-id="' + esc(step.id) + '" title="Edit"><i class="fa-solid fa-pen-to-square" aria-hidden="true"></i><span class="visually-hidden">Edit step</span></button>';
      html += '<button type="button" class="btn btn-sm btn-outline-danger py-0 px-1" data-step-action="remove" data-step-id="' + esc(step.id) + '" title="Remove"><i class="fa-solid fa-trash" aria-hidden="true"></i><span class="visually-hidden">Remove step</span></button>';
      html += '</div>';
      html += '</div>';
      if (step.kind === 'condition') {
        html += '<div class="editor-order-children' + (isCollapsed ? ' d-none' : '') + '">';
        html += renderOrderBranch(step, depth + 1, 'then', 'Then');
        if (hasElse) html += renderOrderBranch(step, depth + 1, 'else', 'Else');
        html += '</div>';
      }
      html += '</div></div>';
      html += renderOrderInsertRow(parentStepId, branch, index + 1, depth);
    });
    return html;
  }

  function renderOrderBuilder() {
    syncActiveOrderStepMap();
    var activeOrderBlock = getBlockById(state.activeOrderBlockId);
    var orderTargets = getOrderTargets();
    var html = '<div class="editor-order-shell">';
    html += '<div class="editor-center-bar">';
    html += '<div><h2 style="font-weight:700;font-size:18px;margin:0">Interview Order</h2></div>';
    html += '<div class="d-flex gap-2">';
    html += '<button class="btn btn-sm btn-outline-secondary" id="generate-draft-order">Auto-generate</button>';
    html += '<button class="btn btn-sm btn-outline-secondary" id="wrap-selected-order-steps">Wrap selected in if</button>';
    html += '<button class="btn btn-sm btn-outline-secondary" id="order-to-raw">Edit YAML</button>';
    if (activeOrderBlock) {
      html += '<button class="btn btn-sm btn-outline-secondary" id="order-back-to-code">Back to code block</button>';
    }
    html += '</div></div>';

    if (orderTargets.length > 0) {
      html += '<div class="editor-order-block-switcher mb-3">';
      orderTargets.forEach(function (block) {
        var isActive = activeOrderBlock && activeOrderBlock.id === block.id;
        html += '<button type="button" class="btn btn-sm ' + (isActive ? 'btn-primary' : 'btn-outline-secondary') + '" data-order-block-id="' + esc(block.id) + '">';
        html += esc(block.title || block.id);
        if (block.tags && block.tags.indexOf('mandatory') !== -1) html += ' <span class="editor-inline-meta">Order</span>';
        html += '</button>';
      });
      html += '</div>';
    }

    html += '<div class="editor-order-grid">';

    // Steps list
    html += '<div class="editor-card"><div class="editor-card-header d-flex justify-content-between align-items-center">';
    html += '<span>Steps</span>';
    html += '<div class="editor-order-actions">';
    html += '<span class="editor-order-actions-hint">Insert anywhere with the inline add rows.</span>';
    html += '</div></div>';

    html += '<div class="editor-card-body"><div class="editor-order-timeline" id="order-sortable-list">';
    html += renderOrderStepTree(state.orderSteps, 0, '', 'then');
    if (state.orderSteps.length === 0) {
      html += '<p class="text-muted small mb-0">No order steps yet. Use the add row below or click "Auto-generate" to create a draft.</p>';
    }
    html += '</div></div></div>';

    html += '<div class="mt-2 d-flex justify-content-end"><button class="btn btn-primary" id="save-order-steps">Save order</button></div>';

    html += '</div></div>';
    canvasContent.innerHTML = html;

    // Initialize drag-to-reorder via SortableJS
    var sortableEl = document.getElementById('order-sortable-list');
    if (sortableEl && typeof Sortable !== 'undefined') {
      Sortable.create(sortableEl, {
        handle: '.drag-handle',
        draggable: '.editor-order-step-shell',
        animation: 150,
        onEnd: function (evt) {
          var moved = state.orderSteps.splice(evt.oldIndex, 1)[0];
          state.orderSteps.splice(evt.newIndex, 0, moved);
          renderOrderBuilder();
        }
      });
    }

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
    var mdInsertBtn = target.closest('[data-md-insert]');
    var symbolItemBtn = target.closest('[data-symbol-name]');
    var typeaheadItemBtn = target.closest('[data-typeahead-name]');
    var labelQuickBtn = target.closest('[data-label-insert]');
    var stepActionBtn = target.closest('[data-step-action]');
    var addStepBtn = target.closest('[data-add-step]');
    var orderBlockBtn = target.closest('[data-order-block-id]');
    var stepSelectInput = target.closest('[data-step-select]');
    var removeFieldBtn = target.closest('[data-remove-field]');
    var removeObjBtn = target.closest('[data-remove-obj]');
    var removeUploadBtn = target.closest('[data-remove-upload]');
    var projectCardBtn = target.closest('[data-project-card]');

    if (!target.closest('#editor-symbol-typeahead') && !target.closest('[data-symbol-role]')) {
      hideTypeaheadMenu();
    }

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

    if (mdInsertBtn) {
      var mdAction = mdInsertBtn.getAttribute('data-md-insert');
      var targetId = mdInsertBtn.getAttribute('data-target-id');
      var targetEl = targetId ? document.getElementById(targetId) : null;
      applyMarkdownInsert(targetEl, mdAction);
      return;
    }

    if (labelQuickBtn) {
      if (!_symbolInsertContext || !_symbolInsertContext.targetEl) return;
      var labelAction = labelQuickBtn.getAttribute('data-label-insert');
      var labelTarget = _symbolInsertContext.targetEl;
      if (labelAction === 'bold') {
        insertTextAtCursor(labelTarget, '', { wrapSelectionPrefix: '**', wrapSelectionSuffix: '**', defaultSelection: 'text' });
      } else if (labelAction === 'italic') {
        insertTextAtCursor(labelTarget, '', { wrapSelectionPrefix: '*', wrapSelectionSuffix: '*', defaultSelection: 'text' });
      } else if (labelAction === 'link') {
        closeBootstrapModal('symbol-insert-modal');
        openMarkupInsertModal({ targetEl: labelTarget, role: 'all', insertMode: 'markup-form', action: 'link' });
        return;
      } else if (labelAction === 'mako') {
        closeBootstrapModal('symbol-insert-modal');
        openSymbolInsertModal({ targetEl: labelTarget, role: 'all', insertMode: 'label-menu' });
        return;
      }
      closeBootstrapModal('symbol-insert-modal');
      return;
    }

    if (target.id === 'symbol-insert-apply') {
      var actionName = target.getAttribute('data-insert-form-action') || '';
      if (!_symbolInsertContext) return;
      var formTarget = _symbolInsertContext.targetEl;
      if (!formTarget && _symbolInsertContext.targetId) formTarget = document.getElementById(_symbolInsertContext.targetId);
      if (!formTarget) return;
      var insertion = buildInsertionFromForm(actionName);
      if (insertion) {
        insertTextAtCursor(formTarget, insertion);
      }
      closeBootstrapModal('symbol-insert-modal');
      return;
    }

    if (symbolItemBtn) {
      var chosenSymbol = symbolItemBtn.getAttribute('data-symbol-name');
      applySelectedSymbolToContext(chosenSymbol);
      closeBootstrapModal('symbol-insert-modal');
      return;
    }

    if (typeaheadItemBtn) {
      var pick = typeaheadItemBtn.getAttribute('data-typeahead-name');
      var pickTargetId = typeaheadItemBtn.getAttribute('data-target-id');
      var pickStart = parseInt(typeaheadItemBtn.getAttribute('data-typeahead-start') || '-1', 10);
      var pickEnd = parseInt(typeaheadItemBtn.getAttribute('data-typeahead-end') || '-1', 10);
      var pickTarget = pickTargetId ? document.getElementById(pickTargetId) : null;
      if (pickTarget) {
        if (Number.isFinite(pickStart) && Number.isFinite(pickEnd) && pickStart >= 0 && pickEnd >= pickStart) {
          replaceInputRange(pickTarget, pickStart, pickEnd, pick);
        } else {
          insertTextAtCursor(pickTarget, pick);
        }
      }
      hideTypeaheadMenu();
      return;
    }

    if (stepSelectInput) {
      var selectedStepId = stepSelectInput.getAttribute('data-step-select');
      state.selectedOrderStepIds[selectedStepId] = Boolean(stepSelectInput.checked);
      return;
    }

    if (orderBlockBtn) {
      var nextOrderBlockId = orderBlockBtn.getAttribute('data-order-block-id');
      if (!nextOrderBlockId || nextOrderBlockId === state.activeOrderBlockId) return;
      syncActiveOrderStepMap();
      loadOrderStepsForBlock(nextOrderBlockId).then(function () {
        renderCanvas();
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
      syncActiveOrderStepMap();
      if (!state.activeOrderBlockId) state.activeOrderBlockId = getDefaultOrderBlockId();
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
    if (target.id === 'code-to-order-builder') {
      var selectedCodeBlock = getSelectedBlock();
      if (!selectedCodeBlock || selectedCodeBlock.type !== 'code') return;
      syncActiveOrderStepMap();
      loadOrderStepsForBlock(selectedCodeBlock.id).then(function () {
        state.canvasMode = 'order-builder';
        renderCanvas();
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
      if (state.questionEditMode === 'preview') {
        // Switching from preview to yaml: sync current edits to block.yaml
        var block = getSelectedBlock();
        if (block) {
          if (block.type === 'question') {
            syncFieldsToData(block);
            block.yaml = serializeQuestionToYaml(block);
          } else if (block.type === 'code') {
            block.yaml = serializeCodeToYaml(block);
          } else if (block.type === 'objects') {
            block.yaml = serializeObjectsToYaml(block);
          }
        }
      }
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
      if (state.fullYamlTab === 'order' && state.activeOrderBlockId) {
        apiPost('/api/block', {
          project: state.project,
          filename: state.filename,
          block_id: state.activeOrderBlockId,
          block_yaml: yamlContent,
        }).then(function (res) { if (res.success && res.data) refreshFromFileResponse(res.data); });
      } else {
        apiPost('/api/file', { project: state.project, filename: state.filename, content: yamlContent })
          .then(function (res) { if (res.success) { state.dirty = false; loadFile(); } });
      }
      return;
    }

    // Order builder
    if (target.id === 'generate-draft-order') {
      apiPost('/api/draft-order', { project: state.project, filename: state.filename })
        .then(function (res) { if (res.success) { state.orderSteps = res.data.steps; syncActiveOrderStepMap(); renderCanvas(); } });
      return;
    }
    if (target.id === 'wrap-selected-order-steps') {
      if (wrapSelectedOrderSteps()) renderCanvas();
      return;
    }
    if (target.id === 'order-to-raw') { state.canvasMode = 'full-yaml'; state.fullYamlTab = 'order'; renderCanvas(); return; }
    if (target.id === 'order-back-to-code') {
      if (state.activeOrderBlockId) state.selectedBlockId = state.activeOrderBlockId;
      state.canvasMode = 'question';
      state.questionEditMode = 'preview';
      renderOutline();
      renderCanvas();
      return;
    }
    if (target.id === 'save-order-steps') {
      syncActiveOrderStepMap();
      apiPost('/api/order', { project: state.project, filename: state.filename, order_block_id: state.activeOrderBlockId, steps: state.orderSteps })
        .then(function (res) { if (res.success) loadFile(); });
      return;
    }

    // Step actions
    if (stepActionBtn) {
      var action = stepActionBtn.getAttribute('data-step-action');
      var targetStepId = stepActionBtn.getAttribute('data-step-id');
      var stepRecord = findStepRecord(state.orderSteps, targetStepId, null);
      if (!stepRecord) return;
      if (action === 'remove') {
        stepRecord.list.splice(stepRecord.index, 1);
        delete state.selectedOrderStepIds[targetStepId];
        syncActiveOrderStepMap();
        renderCanvas();
      } else if (action === 'preview') {
        showOrderPreview(stepRecord.step);
      } else if (action === 'edit') {
        showOrderEdit(stepRecord.step, targetStepId);
      } else if (action === 'toggle-collapse') {
        state.orderCollapsed[targetStepId] = !state.orderCollapsed[targetStepId];
        renderCanvas();
      } else if (action === 'add-else') {
        stepRecord.step.has_else = true;
        if (!Array.isArray(stepRecord.step.else_children)) stepRecord.step.else_children = [];
        state.orderCollapsed[targetStepId] = false;
        syncActiveOrderStepMap();
        renderCanvas();
      }
      return;
    }

    // Add step
    if (addStepBtn) {
      var kind = addStepBtn.getAttribute('data-add-step');
      var parentStepId = addStepBtn.getAttribute('data-parent-step-id');
      var branch = addStepBtn.getAttribute('data-step-branch') || 'then';
      var insertIndex = parseInt(addStepBtn.getAttribute('data-insert-index') || '-1', 10);
      var newStep = createOrderStep(kind);
      if (parentStepId) {
        var parentRecord = findStepRecord(state.orderSteps, parentStepId, null);
        if (parentRecord) {
          var targetList = getOrderBranchSteps(parentRecord.step, branch);
          if (branch === 'else') parentRecord.step.has_else = true;
          if (!Number.isFinite(insertIndex) || insertIndex < 0 || insertIndex > targetList.length) insertIndex = targetList.length;
          targetList.splice(insertIndex, 0, newStep);
          state.orderCollapsed[parentStepId] = false;
        }
      } else {
        if (!Number.isFinite(insertIndex) || insertIndex < 0 || insertIndex > state.orderSteps.length) insertIndex = state.orderSteps.length;
        state.orderSteps.splice(insertIndex, 0, newStep);
      }
      syncActiveOrderStepMap();
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
    if (target.id === 'symbol-insert-search') {
      refreshSymbolInsertModalList(target.value || '');
      return;
    }
    if (target.matches('[data-symbol-role]')) {
      showTypeaheadForInput(target);
    }
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
    if (target.matches('[data-symbol-role]')) {
      hideTypeaheadMenu();
    }
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

  document.addEventListener('focusin', function (e) {
    var target = e.target;
    if (target.matches('[data-symbol-role]')) {
      showTypeaheadForInput(target);
    }
  });

  document.addEventListener('contextmenu', function (e) {
    var labelField = e.target.closest('[data-label-field="true"]');
    if (!labelField) return;
    e.preventDefault();
    openSymbolInsertModal({ targetEl: labelField, role: 'all', insertMode: 'label-menu' });
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') hideTypeaheadMenu();
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

  var _editStepId = null;
  function showOrderEdit(step, stepId) {
    if (!step) return;
    _editStepId = stepId;
    document.getElementById('order-edit-title').textContent = step.label || step.kind;
    var body = '';
    if (step.kind === 'screen' || step.kind === 'gather' || step.kind === 'function') {
      body += '<div class="mb-3"><label class="editor-tiny">Variable / expression</label>';
      body += '<input class="form-control form-control-sm mt-1 font-monospace" data-symbol-role="all" id="order-edit-invoke" value="' + esc(step.invoke || '') + '"></div>';
    }
    if (step.kind === 'condition') {
      body += '<div class="mb-3"><label class="editor-tiny">Condition</label>';
      body += '<input class="form-control form-control-sm mt-1 font-monospace" data-symbol-role="all" id="order-edit-condition" value="' + esc(step.condition || step.summary || '') + '"></div>';
    }
    if (step.kind === 'section') {
      body += '<div class="mb-3"><label class="editor-tiny">Section name</label>';
      body += '<input class="form-control form-control-sm mt-1" data-symbol-role="section" id="order-edit-value" value="' + esc(step.value || '') + '"></div>';
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
    if (!_editStepId) return;
    var record = findStepRecord(state.orderSteps, _editStepId, null);
    if (!record) return;
    var step = record.step;
    var invokeEl = document.getElementById('order-edit-invoke');
    var valueEl = document.getElementById('order-edit-value');
    var codeEl = document.getElementById('order-edit-code');
    var conditionEl = document.getElementById('order-edit-condition');
    if (invokeEl) { step.invoke = invokeEl.value; step.summary = invokeEl.value; }
    if (conditionEl) { step.condition = conditionEl.value; step.summary = conditionEl.value; }
    if (valueEl) { step.value = valueEl.value; if (step.kind === 'section') step.summary = 'Section: ' + valueEl.value; if (step.kind === 'progress') step.summary = 'Progress: ' + valueEl.value + '%'; }
    if (codeEl) { step.code = codeEl.value; step.summary = codeEl.value.split('\n')[0].slice(0, 60); }
    syncActiveOrderStepMap();
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
      var selected = getBlockById(state.selectedBlockId);
      if (!selected || !isBlockVisibleInOutline(selected)) {
        state.selectedBlockId = getDefaultVisibleBlockId();
      }
      renderOutline();
      renderCanvas();
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

  window.addEventListener('resize', hideTypeaheadMenu);
  document.addEventListener('scroll', hideTypeaheadMenu, true);

  init();
})();
