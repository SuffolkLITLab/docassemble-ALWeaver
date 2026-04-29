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
    orderBuilderLoading: false,
    orderDirty: false,
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
    questionBlockTab: 'screen',
    advancedOpen: false,
    advancedShowMore: false,
    reviewMetaOpen: false,
    openReviewItemIndex: null,
    jumpTarget: 'questions',
    fullYamlTab: 'full',
    searchQuery: '',
    projectSearchQuery: '',
    sectionFiles: {
      templates: [],
      modules: [],
      static: [],
      data: [],
    },
    sectionSelectedFile: {
      templates: null,
      modules: null,
      static: null,
      data: null,
    },
    sectionDirty: false,
    dirty: false,
    markdownPreviewMode: false,
    insertAfterBlockId: null,
    fullYamlStash: {},
    validationErrors: [],
    validationOpen: false,
    validationMode: 'validation',
  };

  var RECENT_PROJECTS_STORAGE_KEY = 'alweaver_recent_projects';
  var MAX_RECENT_PROJECTS = 8;
  var _symbolInsertContext = null;
  var _pendingOrderInsert = null;
  var _lastInsertedOrderStepId = null;
  var _lastInsertedOrderStepTimer = null;
  var _orderBuilderLoadSeq = 0;
  var _questionEventFieldOpen = {};
  var DOCASSEMBLE_MARKUP_DOCS_URL = 'https://docassemble.org/docs/markup.html';
  var MAKO_DOCS_URL = 'https://docs.makotemplates.org/en/latest/syntax.html';
  var UPLOAD_JOB_POLL_INTERVAL_MS = 1500;
  var UPLOAD_JOB_MAX_ATTEMPTS = 480;

  function isInterviewView() {
    return state.currentView === 'interview';
  }

  function getSectionFromView(view) {
    if (view === 'templates') return 'templates';
    if (view === 'modules') return 'modules';
    if (view === 'static') return 'static';
    if (view === 'data') return 'data';
    return null;
  }

  function updateTopbarProject() {
    var projectEl = document.getElementById('topbar-project-name');
    if (!projectEl) return;
    projectEl.textContent = state.project || 'No project selected';
  }

  function getCurrentSectionFilename(view) {
    if (view === 'interview') return state.filename;
    var selected = state.sectionSelectedFile[view];
    if (selected) return selected;
    var meta = getSelectedSectionFileMeta(view);
    return meta ? meta.filename : null;
  }

  function buildStandardPlaygroundUrl() {
    if (!state.project) return null;
    var section = isInterviewView() ? 'playground' : getSectionFromView(state.currentView);
    var filename = getCurrentSectionFilename(state.currentView);
    var url = '/playground?project=' + encodeURIComponent(state.project);
    if (section) url += '&section=' + encodeURIComponent(section);
    if (filename) url += '&file=' + encodeURIComponent(filename);
    return url;
  }

  function updateLeftSearchPlaceholder() {
    if (!searchInput) return;
    searchInput.placeholder = isInterviewView() ? 'Type to filter...' : 'Search files...';
  }

  function updateLeftRailMode() {
    var fileSection = document.getElementById('editor-file-section');
    var jumpTargets = document.getElementById('jump-targets');
    if (fileSection) fileSection.classList.toggle('editor-section-hidden', !isInterviewView());
    if (jumpTargets) jumpTargets.classList.toggle('d-none', !isInterviewView());
    updateOutlineHeader();
  }

  function updateOutlineHeader() {
    var outlineHeader = document.querySelector('.editor-outline-header .editor-tiny');
    var orderButton = document.getElementById('btn-order-builder');
    if (outlineHeader) {
      outlineHeader.textContent = isInterviewView() ? 'Outline' : 'File list';
    }
    if (orderButton) {
      orderButton.classList.toggle('d-none', !isInterviewView());
    }
  }

  function updateTopbarSaveState() {
    var btn = document.getElementById('btn-save-file');
    if (!btn) return;
    var isDirty = state.dirty || state.sectionDirty;
    btn.disabled = !isDirty;
    var badge = btn.querySelector('.js-save-badge');
    if (badge) {
      badge.classList.toggle('d-none', !isDirty);
    }
  }

  function isOutlineDragEnabled() {
    return isInterviewView() && !state.searchQuery.trim();
  }

  function isCommentedBlock(block) {
    return Boolean(block && (block.type === 'commented' || (block.tags || []).indexOf('commented') !== -1));
  }

  function getBlockDisplayType(block) {
    if (!block) return '';
    if (block.type === 'commented' && block.data && block.data._commented_type) {
      return String(block.data._commented_type || 'commented');
    }
    return String(block.type || '');
  }

  function isPlaceholderSectionFile(filename) {
    return String(filename || '').toLowerCase() === '.placeholder';
  }

  function sectionTypeTag(fileMeta) {
    var filename = String((fileMeta && fileMeta.filename) || '');
    if (isPlaceholderSectionFile(filename)) return '';
    var size = Number((fileMeta && fileMeta.size) || 0);
    if (Number.isFinite(size) && size === 0) return 'empty file';
    var tag = String((fileMeta && (fileMeta.preview_kind || fileMeta.mimetype || 'file')) || 'file').toUpperCase();
    return tag.slice(0, 4);
  }

  function supportsDashboardEditor(fileMeta) {
    return Boolean(fileMeta && (fileMeta.preview_kind === 'pdf' || fileMeta.preview_kind === 'docx'));
  }

  function blockUnsavedSectionNavigation() {
    if (!state.sectionDirty || isInterviewView()) return false;
    window.alert('You have unsaved changes in this file. Save your changes before leaving this file.');
    return true;
  }

  // -------------------------------------------------------------------------
  // Monaco management
  // -------------------------------------------------------------------------
  var _monacoReady = false;
  var _monacoLoading = false;
  var _monacoFailed = false;
  var _monacoLoaderBase = null;
  var _monacoEditors = {};
  var _outlineSortable = null;
  var _textareaEditors = {};
  var _makoLanguageRegistered = false;

  function registerMakoLanguage() {
    if (_makoLanguageRegistered || typeof monaco === 'undefined' || !monaco.languages) return;
    if (typeof monaco.languages.getLanguages === 'function') {
      var languages = monaco.languages.getLanguages();
      for (var i = 0; i < languages.length; i++) {
        if (languages[i] && languages[i].id === 'mako') {
          _makoLanguageRegistered = true;
          return;
        }
      }
    }

    monaco.languages.register({ id: 'mako' });
    monaco.languages.setMonarchTokensProvider('mako', {
      defaultToken: '',
      tokenPostfix: '.mako',
      keywords: [
        'and', 'as', 'assert', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
        'False', 'finally', 'for', 'from', 'if', 'import', 'in', 'is', 'lambda', 'None', 'not', 'or',
        'pass', 'raise', 'return', 'True', 'try', 'while', 'with', 'yield', 'block', 'namespace',
        'endblock', 'endfor', 'endif', 'endtry', 'endwhile', 'endwith'
      ],
      tokenizer: {
        root: [
          [/^\s*##.*$/, 'comment.mako'],
          [/^\s*%\s*(if|elif|else|for|while|try|except|finally|with|def|block|namespace|endfor|endif|endwhile|endtry|endwith|endblock)\b.*$/, ['delimiter.mako', 'keyword.mako']],
          [/^\s*%.*$/, 'meta.mako'],
          [/<%doc>/, { token: 'comment.mako', next: '@docBlock' }],
          [/<%/, { token: 'delimiter.mako', next: '@pythonBlock' }],
          [/\$\{/, { token: 'delimiter.mako', next: '@expression' }],
          [/\$\(/, { token: 'delimiter.mako', next: '@parenExpression' }],
          [/<\/?[A-Za-z][\w:-]*/, 'tag.mako'],
          [/&[a-zA-Z_][\w-]*;/, 'string.escape'],
          [/[{}()[\]]/, '@brackets'],
          [/[;,.]/, 'delimiter'],
          [/\b\d+\.\d+([eE][-+]?\d+)?\b/, 'number.float'],
          [/\b\d+\b/, 'number'],
          [/"([^"\\]|\\.)*"/, 'string'],
          [/'([^'\\]|\\.)*'/, 'string'],
          [/\b[A-Za-z_][\w]*\b/, {
            cases: {
              '@keywords': 'keyword.mako',
              '@default': 'identifier'
            }
          }],
          [/\s+/, 'white'],
        ],
        expression: [
          [/\}/, { token: 'delimiter.mako', next: '@pop' }],
          { include: '@rootExpression' },
        ],
        parenExpression: [
          [/\)/, { token: 'delimiter.mako', next: '@pop' }],
          { include: '@rootExpression' },
        ],
        rootExpression: [
          [/\s+/, 'white'],
          [/\b(and|as|assert|break|class|continue|def|del|elif|else|except|False|finally|for|from|if|import|in|is|lambda|None|not|or|pass|raise|return|True|try|while|with|yield)\b/, 'keyword.mako'],
          [/\$\{/, { token: 'delimiter.mako', next: '@expression' }],
          [/\$\(/, { token: 'delimiter.mako', next: '@parenExpression' }],
          [/[{}()[\]]/, '@brackets'],
          [/\b\d+\.\d+([eE][-+]?\d+)?\b/, 'number.float'],
          [/\b\d+\b/, 'number'],
          [/"([^"\\]|\\.)*"/, 'string'],
          [/'([^'\\]|\\.)*'/, 'string'],
          [/\b[A-Za-z_][\w]*\b/, 'identifier'],
          [/./, 'operator'],
        ],
        pythonBlock: [
          [/%>/, { token: 'delimiter.mako', next: '@pop' }],
          [/\b(and|as|assert|break|class|continue|def|del|elif|else|except|False|finally|for|from|if|import|in|is|lambda|None|not|or|pass|raise|return|True|try|while|with|yield)\b/, 'keyword.mako'],
          [/"([^"\\]|\\.)*"/, 'string'],
          [/'([^'\\]|\\.)*'/, 'string'],
          [/\b\d+\.\d+([eE][-+]?\d+)?\b/, 'number.float'],
          [/\b\d+\b/, 'number'],
          [/\b[A-Za-z_][\w]*\b/, 'identifier'],
          [/./, 'operator'],
        ],
        docBlock: [
          [/<\/doc>/, { token: 'comment.mako', next: '@pop' }],
          [/.*$/, 'comment.mako'],
        ],
      },
    });
    _makoLanguageRegistered = true;
  }

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
      var vsBase = _monacoLoaderBase || 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs';
      require.config({ paths: { vs: vsBase } });
      require(['vs/editor/editor.main'], function () {
        registerMakoLanguage();
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
    if (kind === 'attachment') {
      return (
        'id: attachment_' + stamp + '\n' +
        'question: Download your document\n' +
        'subquestion: |\n' +
        '  Your document is ready.\n' +
        'attachments:\n' +
        '  - name: Draft document\n' +
        '    filename: draft_document\n' +
        '    docx template file: draft_template.docx\n'
      );
    }
    if (kind === 'review') {
      return (
        'id: review_screen_' + stamp + '\n' +
        'event: review_form\n' +
        'question: Review your answers\n' +
        'review:\n' +
        '  - Edit: new_field_' + stamp + '\n' +
        '    button: |\n' +
        '      New answer: ${ showifdef("new_field_' + stamp + '") }\n'
      );
    }
    return (
      'id: block_' + stamp + '\n' +
      'code: |\n' +
      '  # New block\n' +
      '  pass\n'
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
    state.fullYamlStash = {};
    loadAvailableSymbols(true);
    renderOutline();
    renderCanvas();
    runCurrentValidationCheck();
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
    'range', 'object', 'object_radio', 'object_checkboxes', 'object_multiselect',
    'ml', 'mlarea', 'microphone', 'camcorder',
    'hidden', 'raw', 'note', 'html', 'raw html', 'code',
    'user', 'environment',
  ];

  var FIELD_TYPE_GROUPS = [
    { label: 'Text inputs', items: ['text', 'area', 'raw', 'email', 'password', 'url', 'ml', 'mlarea'] },
    { label: 'Numbers', items: ['number', 'integer', 'currency', 'range'] },
    { label: 'Choices', items: ['radio', 'checkboxes', 'dropdown', 'combobox', 'multiselect'] },
    { label: 'Booleans', items: ['yesno', 'yesnowide', 'yesnoradio', 'yesnomaybe', 'noyes', 'noyeswide', 'noyesradio', 'noyesmaybe'] },
    { label: 'Date and time', items: ['date', 'time', 'datetime'] },
    { label: 'Files and media', items: ['file', 'files', 'camera', 'microphone', 'camcorder', 'environment'] },
    { label: 'Objects', items: ['object', 'object_radio', 'object_checkboxes', 'object_multiselect', 'user'] },
    { label: 'Standalone content', items: ['note', 'html', 'raw html'] },
    { label: 'Special', items: ['hidden', 'code'] },
  ];

  var FIELD_STANDALONE_TYPES = ['note', 'html', 'raw html', 'code'];

  var FIELD_TYPE_LABELS = {
    raw: 'Raw',
    note: 'Note row',
    html: 'HTML row',
    'raw html': 'Raw HTML row',
    code: 'Fields code',
    hidden: 'Hidden input',
    mlarea: 'ML area',
    object_radio: 'Object radio',
    object_checkboxes: 'Object checkboxes',
    object_multiselect: 'Object multiselect',
    yesnowide: 'Yes/no wide',
    yesnoradio: 'Yes/no radio',
    yesnomaybe: 'Yes/no maybe',
    noyeswide: 'No/yes wide',
    noyesradio: 'No/yes radio',
    noyesmaybe: 'No/yes maybe',
  };

  function _normalizeFieldType(type) {
    return String(type || 'text').trim().toLowerCase() || 'text';
  }

  function _isStandaloneFieldType(type) {
    return FIELD_STANDALONE_TYPES.indexOf(_normalizeFieldType(type)) !== -1;
  }

  function _fieldTypeSupportsStandaloneContent(type) {
    return _isStandaloneFieldType(type);
  }

  // All known field modifier keys
  var FIELD_MODIFIER_KEYS = [
    'datatype', 'input type', 'required', 'disabled', 'under text', 'hint',
    'help', 'default', 'choices', 'code', 'exclude', 'none of the above',
    'all of the above', 'shuffle', 'show if', 'hide if', 'enable if',
    'disable if', 'js show if', 'js hide if', 'js enable if', 'js disable if',
    'disable others', 'note', 'html', 'raw html', 'no label', 'css class',
    'label above field', 'floating label', 'grid', 'item grid', 'label', 'field',
    'field metadata', 'min', 'max', 'minlength', 'maxlength', 'step', 'rows',
    'validate', 'validation code', 'validation messages', 'accept',
    'maximum image size', 'image upload type', 'persistent', 'private',
    'allow users', 'allow privileges', 'file css class', 'inline width',
    'address autocomplete', 'uncheck others', 'check others', 'object labeler',
  ];

  // Question-level modifier keys (from modifiers.html)
  var QUESTION_MODIFIER_KEYS = [
    'id', 'if', 'mandatory', 'sets', 'only sets', 'need', 'event',
    'generic object', 'continue button field', 'continue button label',
    'continue button color', 'audio', 'video', 'help', 'decoration',
    'script', 'css', 'progress', 'section', 'prevent going back',
    'back button', 'back button label', 'corner back button label',
    'terms', 'auto terms', 'language', 'role', 'reload',
    'ga id', 'segment id', 'segment', 'breadcrumb', 'supersedes',
    'allowed to set', 'hide continue button', 'disable continue button',
    'scan for variables', 'depends on', 'undefine', 'reconsider',
    'action buttons', 'comment', 'tabular', 'resume button label',
    'validation code',
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

  function fetchResponsePayload(url, opts) {
    opts = opts || {};
    return fetch(url, opts).then(function (res) {
      var contentType = res.headers.get('content-type') || '';
      return res.text().then(function (text) {
        var body = null;
        if (contentType.indexOf('json') !== -1) {
          try {
            body = text ? JSON.parse(text) : null;
          } catch (err) {
            body = null;
          }
        }
        return {
          ok: res.ok,
          status: res.status,
          contentType: contentType,
          text: text,
          body: body,
        };
      });
    });
  }

  function _fetchErrorMessage(response) {
    if (!response) return 'Unknown error';
    var body = response.body || {};
    if (body.error && body.error.message) return String(body.error.message);
    if (body.message) return String(body.message);
    var text = String(response.text || '').trim();
    if (!text) return 'Request failed with status ' + response.status;
    if (response.contentType && response.contentType.indexOf('json') === -1) {
      return 'Server returned HTTP ' + response.status + ' (' + response.contentType + ').';
    }
    if (text.length > 240) return text.slice(0, 240) + '...';
    return text;
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

  function generateBlockId(questionText, blocks, currentId) {
    var base = String(questionText || '').toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 40) || 'question';
    var existing = {};
    (blocks || []).forEach(function (b) {
      if (b.id && b.id !== currentId) existing[b.id] = true;
    });
    var id = base;
    var count = 2;
    while (existing[id]) {
      id = base + '_' + count;
      count += 1;
    }
    return id;
  }

  function isBlockIdUnique(id, blocks, currentId) {
    if (!id) return false;
    return !(blocks || []).some(function (b) {
      return b.id === id && b.id !== currentId;
    });
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
    if (role === 'variable' || role === 'top-level' || role === 'object-class' || role === 'section' || role === 'static-image' || role === 'static-file' || role === 'function-call' || role === 'template-file') {
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

  function _groupEntries(groups, keyNames) {
    var out = [];
    var normalized = (keyNames || []).map(function (name) { return String(name || '').toLowerCase(); });
    Object.keys(groups || {}).forEach(function (key) {
      if (normalized.indexOf(String(key || '').toLowerCase()) === -1) return;
      var vals = groups[key];
      if (!Array.isArray(vals)) return;
      vals.forEach(function (name) {
        var clean = String(name || '').trim();
        if (clean) out.push({ name: clean, group: key });
      });
    });
    return out;
  }

  function getSymbolCandidates(role) {
    role = normalizeSymbolRole(role);
    var groups = state.symbolCatalog.groups || {};
    var topLevel = state.symbolCatalog.topLevel || [];
    var all = state.symbolCatalog.all || [];

    if (role === 'variable') {
      return all.map(function (name) { return { name: name, group: 'variables' }; });
    }
    if (role === 'top-level') {
      return topLevel.map(function (name) { return { name: name, group: 'top_level_names' }; });
    }
    if (role === 'object-class') {
      var classLike = _groupEntries(groups, ['classes']);
      if (classLike.length === 0) {
        var classGroupKeys = Object.keys(groups).filter(function (key) {
          return key.toLowerCase().indexOf('class') !== -1 || key.toLowerCase().indexOf('object') !== -1;
        });
        classGroupKeys.forEach(function (key) {
          (groups[key] || []).forEach(function (name) { classLike.push({ name: name, group: key }); });
        });
      }
      if (classLike.length === 0) {
        all.forEach(function (name) {
          if (/^[A-Z]/.test(name)) classLike.push({ name: name, group: 'all_names' });
        });
      }
      return classLike;
    }
    if (role === 'function-call') {
      var functionLike = _groupEntries(groups, ['functions']);
      if (functionLike.length === 0) {
        Object.keys(groups).forEach(function (key) {
          if (key.toLowerCase().indexOf('function') === -1) return;
          (groups[key] || []).forEach(function (name) {
            functionLike.push({ name: String(name), group: key });
          });
        });
      }
      return functionLike;
    }
    if (role === 'template-file') {
      var templateLike = _groupEntries(groups, ['template_files', 'templates']);
      if (templateLike.length === 0) {
        Object.keys(groups).forEach(function (key) {
          if (key.toLowerCase().indexOf('template') === -1) return;
          (groups[key] || []).forEach(function (name) {
            templateLike.push({ name: String(name), group: key });
          });
        });
      }
      return templateLike;
    }
    if (role === 'static-file') {
      var staticFiles = _groupEntries(groups, ['static_files', 'static_images']);
      if (!staticFiles.length) {
        all.forEach(function (name) {
          if (name.indexOf('.') !== -1) staticFiles.push({ name: name, group: 'all_names' });
        });
      }
      return staticFiles;
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
      var staticLike = _groupEntries(groups, ['static_images']);
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

  function renderSymbolDatalist(id, role, limit) {
    var matches = getSymbolMatches('', role || 'variable', limit || 120);
    if (!matches.length) return '';
    var seen = {};
    var html = '<datalist id="' + esc(id) + '">';
    matches.forEach(function (entry) {
      var name = String(entry.name || '').trim();
      if (!name || seen[name]) return;
      seen[name] = true;
      html += '<option value="' + esc(name) + '">';
    });
    html += '</datalist>';
    return html;
  }

  function resetSymbolCatalog() {
    state.symbolCatalog = {
      loadedFor: null,
      all: [],
      topLevel: [],
      groups: {},
    };
  }

  function refreshActiveSymbolPickers() {
    if (_symbolInsertContext) {
      var search = document.getElementById('symbol-insert-search');
      refreshSymbolInsertModalList(search ? search.value || '' : '');
    }
    var activeEl = document.activeElement;
    if (activeEl && activeEl.matches && activeEl.matches('[data-symbol-role]')) {
      showTypeaheadForInput(activeEl);
    }
  }

  function loadAvailableSymbols(forceRefresh) {
    if (!state.project || !state.filename) {
      resetSymbolCatalog();
      return Promise.resolve();
    }
    var key = state.project + '::' + state.filename;
    if (!forceRefresh && state.symbolCatalog.loadedFor === key && state.symbolCatalog.all.length) {
      return Promise.resolve();
    }
    return apiGet('/api/variables?project=' + encodeURIComponent(state.project) + '&filename=' + encodeURIComponent(state.filename))
      .then(function (res) {
        if (!res.success || !res.data) return;
        if (key !== state.project + '::' + state.filename) return;
        var data = res.data;
        state.symbolCatalog = {
          loadedFor: key,
          all: uniqueList(data.all_names || []),
          topLevel: uniqueList(data.top_level_names || []),
          groups: data.symbol_groups || {},
        };
        refreshActiveSymbolPickers();
      })
      .catch(function () {
        resetSymbolCatalog();
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
    // Primary actions — always visible, light ghost style
    html += '<button type="button" class="editor-md-btn" data-md-insert="bold" data-target-id="' + esc(targetId) + '" title="Bold"><i class="fa-solid fa-bold" aria-hidden="true"></i></button>';
    html += '<button type="button" class="editor-md-btn" data-md-insert="italic" data-target-id="' + esc(targetId) + '" title="Italic"><i class="fa-solid fa-italic" aria-hidden="true"></i></button>';
    html += '<button type="button" class="editor-md-btn" data-md-insert="link" data-target-id="' + esc(targetId) + '" title="Link"><i class="fa-solid fa-link" aria-hidden="true"></i></button>';
    html += '<button type="button" class="editor-md-btn" data-md-insert="mako" data-target-id="' + esc(targetId) + '" title="Insert Mako variable"><i class="fa-solid fa-code" aria-hidden="true"></i></button>';
    // Heading dropdown
    html += '<div class="dropdown d-inline-block">';
    html += '<button type="button" class="editor-md-btn dropdown-toggle editor-md-dropdown-toggle" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-display="dynamic" aria-expanded="false" title="Heading"><i class="fa-solid fa-heading" aria-hidden="true"></i></button>';
    html += '<ul class="dropdown-menu editor-md-overflow-menu">';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="heading1" data-target-id="' + esc(targetId) + '">Heading 1</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="heading2" data-target-id="' + esc(targetId) + '">Heading 2</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="heading3" data-target-id="' + esc(targetId) + '">Heading 3</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="heading4" data-target-id="' + esc(targetId) + '">Heading 4</button></li>';
    html += '</ul></div>';
    // List dropdown
    html += '<div class="dropdown d-inline-block">';
    html += '<button type="button" class="editor-md-btn dropdown-toggle editor-md-dropdown-toggle" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-display="dynamic" aria-expanded="false" title="List"><i class="fa-solid fa-list" aria-hidden="true"></i></button>';
    html += '<ul class="dropdown-menu editor-md-overflow-menu">';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="list-bullet" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-list-ul me-2" aria-hidden="true"></i>Bulleted list</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="list-numbered" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-list-ol me-2" aria-hidden="true"></i>Numbered list</button></li>';
    html += '</ul></div>';
    // Kebab overflow menu — mako items first, then media/layout
    html += '<div class="dropdown d-inline-block">';
    html += '<button type="button" class="editor-md-btn dropdown-toggle editor-md-kebab" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-display="dynamic" aria-expanded="false" title="More formatting"><i class="fa-solid fa-ellipsis-vertical" aria-hidden="true"></i></button>';
    html += '<ul class="dropdown-menu editor-md-overflow-menu">';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="symbol-raw" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-at me-2" aria-hidden="true"></i>Insert variable name</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="mako-if" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-code-branch me-2" aria-hidden="true"></i>Mako conditional</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="mako-for" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-repeat me-2" aria-hidden="true"></i>Mako loop</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="mako-python" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-terminal me-2" aria-hidden="true"></i>Mako Python block</button></li>';
    html += '<li><hr class="dropdown-divider"></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="image" data-target-id="' + esc(targetId) + '"><i class="fa-regular fa-image me-2" aria-hidden="true"></i>Image</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="table" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-table me-2" aria-hidden="true"></i>Table</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="file" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-file-lines me-2" aria-hidden="true"></i>FILE markup</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="qr" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-qrcode me-2" aria-hidden="true"></i>QR code</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="youtube" data-target-id="' + esc(targetId) + '"><i class="fa-brands fa-youtube me-2" aria-hidden="true"></i>YouTube</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="field" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-i-cursor me-2" aria-hidden="true"></i>Embed field</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="target" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-bullseye me-2" aria-hidden="true"></i>Embed target</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="twocol" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-table-columns me-2" aria-hidden="true"></i>Two-column layout</button></li>';
    html += '<li><hr class="dropdown-divider"></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="docs-markup" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-book me-2" aria-hidden="true"></i>Markup docs</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-md-insert="docs-mako" data-target-id="' + esc(targetId) + '"><i class="fa-solid fa-book-open me-2" aria-hidden="true"></i>Mako docs</button></li>';
    html += '</ul></div>';
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
      html += '<input class="form-control form-control-sm mt-1" id="insert-field-name" data-symbol-role="variable" placeholder="user.name.first">';
    } else if (action === 'target') {
      html += '<label class="editor-tiny" for="insert-target-name">Target name</label>';
      html += '<input class="form-control form-control-sm mt-1" id="insert-target-name" data-symbol-role="variable" placeholder="interim_status">';
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
    } else if (action === 'heading' || action === 'heading2') {
      insertTextAtCursor(targetEl, '## ');
    } else if (action === 'heading1') {
      insertTextAtCursor(targetEl, '# ');
    } else if (action === 'heading3') {
      insertTextAtCursor(targetEl, '### ');
    } else if (action === 'heading4') {
      insertTextAtCursor(targetEl, '#### ');
    } else if (action === 'list-bullet') {
      insertTextAtCursor(targetEl, '* Item 1\n* Item 2\n* Item 3');
    } else if (action === 'list-numbered') {
      insertTextAtCursor(targetEl, '1. Item 1\n2. Item 2\n3. Item 3');
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

  function isOrderBlockId(blockId) {
    if (!blockId) return false;
    for (var i = 0; i < state.orderIndices.length; i++) {
      var idx = state.orderIndices[i];
      var block = state.blocks[idx];
      if (block && block.id === blockId) return true;
    }
    return false;
  }

  function getDefaultOrderBlockId() {
    if (state.activeOrderBlockId && getBlockById(state.activeOrderBlockId) && isOrderBlockId(state.activeOrderBlockId)) {
      return state.activeOrderBlockId;
    }
    var orderBlocks = getOrderBlocks();
    if (orderBlocks.length > 0) return orderBlocks[0].id;
    if (state.activeOrderBlockId && getBlockById(state.activeOrderBlockId)) return state.activeOrderBlockId;
    var selected = getSelectedBlock();
    if (selected && selected.type === 'code') return selected.id;
    return null;
  }

  function setActiveOrderBlock(blockId, steps) {
    state.activeOrderBlockId = blockId || null;
    state.orderSteps = cloneData(steps || (blockId ? state.orderStepMap[blockId] : []) || []) || [];
    state.selectedOrderStepIds = {};
    state.orderBuilderLoading = false;
  }

  function syncActiveOrderStepMap() {
    if (!state.activeOrderBlockId) return;
    state.orderStepMap[state.activeOrderBlockId] = cloneData(state.orderSteps) || [];
  }

  function syncInlineOrderEdit() {
    if (!_inlineEditStepId) return false;
    var stepRecord = findStepRecord(state.orderSteps, _inlineEditStepId, null);
    if (!stepRecord) return false;
    var inlineInvoke = document.getElementById('order-inline-edit-invoke');
    var inlineCondition = document.getElementById('order-inline-edit-condition');
    var inlineValue = document.getElementById('order-inline-edit-value');
    if (inlineInvoke) {
      stepRecord.step.invoke = inlineInvoke.value;
      stepRecord.step.summary = inlineInvoke.value;
    }
    if (inlineCondition) {
      stepRecord.step.condition = inlineCondition.value;
      stepRecord.step.summary = inlineCondition.value;
    }
    if (inlineValue) {
      stepRecord.step.value = inlineValue.value;
      if (stepRecord.step.kind === 'section') stepRecord.step.summary = 'Section: ' + inlineValue.value;
      if (stepRecord.step.kind === 'progress') stepRecord.step.summary = 'Progress: ' + inlineValue.value + '%';
    }
    return Boolean(inlineInvoke || inlineCondition || inlineValue);
  }

  function markInterviewDirty() {
    state.dirty = true;
    updateTopbarSaveState();
  }

  function markOrderDirty() {
    state.orderDirty = true;
    markInterviewDirty();
  }

  function stashCurrentEditorState() {
    _stashFullYamlContent();
    if (!isInterviewView()) return;
    if (state.canvasMode === 'order-builder') {
      if (syncInlineOrderEdit()) markOrderDirty();
      syncActiveOrderStepMap();
      return;
    }
    var block = getSelectedBlock();
    if (!block || state.questionEditMode !== 'preview') return;
    if (block.type === 'question') {
      syncFieldsToData(block);
    }
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

  function enterOrderBuilder(requestedBlockId, source) {
    syncActiveOrderStepMap();
    var nextOrderBlockId = requestedBlockId || getDefaultOrderBlockId();
    if (nextOrderBlockId) {
      state.activeOrderBlockId = nextOrderBlockId;
    }
    state.currentView = 'interview';
    state.canvasMode = 'order-builder';
    state.orderBuilderLoading = Boolean(nextOrderBlockId);
    state.orderSteps = nextOrderBlockId && state.orderStepMap[nextOrderBlockId]
      ? cloneData(state.orderStepMap[nextOrderBlockId]) || []
      : [];
    state.selectedOrderStepIds = {};

    var loadSeq = ++_orderBuilderLoadSeq;

    var interviewTab = document.querySelector('.editor-top-tab[data-view="interview"]');
    if (interviewTab) setActiveTopTab(interviewTab);
    renderOutline();
    renderCanvas();
    scrollOrderBuilderIntoView();

    if (!nextOrderBlockId) {
      console.warn('[Order] No interview-order block found for order builder.');
      return Promise.resolve([]);
    }

    return loadOrderStepsForBlock(nextOrderBlockId).then(function (steps) {
      if (loadSeq !== _orderBuilderLoadSeq) return steps;
      state.orderBuilderLoading = false;
      renderOutline();
      renderCanvas();
      scrollOrderBuilderIntoView();
      return steps;
    }).catch(function (err) {
      if (loadSeq !== _orderBuilderLoadSeq) return [];
      state.orderBuilderLoading = false;
      console.warn('[Order] Failed to load interview order steps: ' + String((err && err.message) || err || 'Unknown error'));
      renderOutline();
      renderCanvas();
      scrollOrderBuilderIntoView();
      return [];
    });
  }

  function scrollOrderBuilderIntoView() {
    var mainCanvas = document.getElementById('main-canvas');
    if (mainCanvas && typeof mainCanvas.scrollTo === 'function') {
      mainCanvas.scrollTo({ top: 0, left: 0, behavior: 'auto' });
      return;
    }
    if (mainCanvas) {
      mainCanvas.scrollTop = 0;
      mainCanvas.scrollLeft = 0;
    }
    if (typeof window !== 'undefined' && typeof window.scrollTo === 'function') {
      window.scrollTo(0, 0);
    }
  }

  function cleanOrderText(text) {
    return String(text || '').replace(/^Ask\s+/i, '').trim();
  }

  function getOrderStepBadge(step) {
    if (!step) return '';
    if (step.kind === 'gather') return 'gather';
    if (step.kind === 'condition') return 'if';
    if (step.kind === 'section') return 'sec';
    if (step.kind === 'progress') return '%';
    if (step.kind === 'function') return 'f';
    if (step.kind === 'raw') return 'py';
    if (step.kind === 'screen') return 'screen';
    return '';
  }

  function getOrderBadgeCssClass(step) {
    if (!step) return '';
    if (step.kind === 'screen') return 'editor-order-badge-screen';
    if (step.kind === 'gather') return 'editor-order-badge-gather';
    if (step.kind === 'condition') return 'editor-order-badge-if';
    if (step.kind === 'section') return 'editor-order-badge-sec';
    if (step.kind === 'progress') return 'editor-order-badge-progress';
    if (step.kind === 'function') return 'editor-order-badge-func';
    if (step.kind === 'raw') return 'editor-order-badge-raw';
    return 'editor-order-badge-var';
  }

  function getOrderStepPresentation(step) {
    var heading = getOrderStepHeading(step);
    var detail = getOrderStepDetail(step);
    var tooltip = '';
    if (step && (step.kind === 'screen' || step.kind === 'gather')) {
      var screenBlock = findBlockByInvoke(step);
      var title = screenBlock ? cleanOrderText(screenBlock.title || '') : '';
      var variable = cleanOrderText(step.invoke || step.summary || '');
      // Variable is always primary; question title is secondary preview
      if (variable) {
        heading = variable;
        detail = (title && title !== variable) ? title : '';
      } else if (title) {
        heading = title;
        detail = '';
      }
      tooltip = '';
    } else if (step && step.kind === 'raw') {
      // Show first code line as heading with no duplicate detail
      var firstLine = cleanOrderText((step.code || '').split('\n')[0]);
      heading = firstLine || step.label || 'Python';
      detail = '';
    } else if (step && step.kind === 'section') {
      heading = step.value ? 'Set section: ' + step.value : (step.summary || 'Section');
      detail = step.value ? 'nav.set_section(\'' + step.value + '\')' : '';
    } else if (step && step.kind === 'progress') {
      heading = step.value ? 'Set progress to ' + step.value + '%' : (step.summary || 'Progress');
      detail = step.value ? 'set_progress(' + step.value + ')' : '';
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

  function _normalizeObjectClassName(classText) {
    var raw = String(classText || '').trim();
    if (!raw) return '';
    return raw.split('.', 1)[0].split('(', 1)[0].trim();
  }

  function _isDaListLikeClass(className) {
    var normalized = _normalizeObjectClassName(className);
    if (!normalized) return false;
    if (normalized === 'DAList' || normalized === 'ALPeopleList') return true;
    return /^(DA|AL).+List$/.test(normalized);
  }

  function getGatherListCandidates() {
    var out = [];
    var seen = {};

    state.blocks.forEach(function (block) {
      if (!block || block.type !== 'objects' || !block.data || !Array.isArray(block.data.objects)) return;
      block.data.objects.forEach(function (entry) {
        if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return;
        Object.keys(entry).forEach(function (varName) {
          var classText = entry[varName];
          if (!_isDaListLikeClass(classText)) return;
          var cleanVar = String(varName || '').trim();
          if (!cleanVar || seen[cleanVar]) return;
          seen[cleanVar] = true;
          out.push({
            variable: cleanVar,
            className: _normalizeObjectClassName(classText),
          });
        });
      });
    });

    var listLikeGroupKeys = Object.keys(state.symbolCatalog.groups || {}).filter(function (key) {
      return key.toLowerCase().indexOf('list') !== -1;
    });
    listLikeGroupKeys.forEach(function (key) {
      (state.symbolCatalog.groups[key] || []).forEach(function (name) {
        var cleanName = String(name || '').trim();
        if (!cleanName || cleanName.indexOf('.') !== -1 || cleanName.indexOf('[') !== -1 || seen[cleanName]) return;
        seen[cleanName] = true;
        out.push({
          variable: cleanName,
          className: 'list',
        });
      });
    });

    return out.sort(function (a, b) { return a.variable.localeCompare(b.variable); });
  }

  function renderOrderAddBody(kind) {
    var bodyEl = document.getElementById('order-add-body');
    if (!bodyEl) return;
    var saveBtn = document.getElementById('order-add-save');

    var html = '';
    if (kind === 'screen') {
      html += '<div class="mb-2"><label class="editor-tiny">Screen variable / expression</label>';
      html += '<input class="form-control form-control-sm mt-1 font-monospace" id="order-add-invoke" data-symbol-role="variable" value="" placeholder="users[0].name.first"></div>';
    } else if (kind === 'gather') {
      var gatherChoices = getGatherListCandidates();
      html += '<div class="mb-2"><label class="editor-tiny">List to gather</label>';
      if (gatherChoices.length) {
        html += '<select class="form-select form-select-sm mt-1 font-monospace" id="order-add-gather-list">';
        gatherChoices.forEach(function (entry) {
          html += '<option value="' + esc(entry.variable) + '">' + esc(entry.variable + ' (' + entry.className + ')') + '</option>';
        });
        html += '</select>';
        html += '<div class="editor-tiny mt-2">Only DA/AL list-style objects are shown.</div>';
      } else {
        html += '<div class="editor-info-box mt-1">No DAList-style objects found in this file yet. Add an objects block first.</div>';
      }
      html += '</div>';
      if (saveBtn) saveBtn.disabled = gatherChoices.length === 0;
    } else if (kind === 'condition') {
      html += '<div class="mb-2"><label class="editor-tiny">Condition expression</label>';
      html += renderSymbolDatalist('order-add-condition-list', 'variable', 120);
      html += '<input class="form-control form-control-sm mt-1 font-monospace" id="order-add-condition" data-symbol-role="variable" list="order-add-condition-list" value="condition_here"></div>';
    } else if (kind === 'section') {
      html += '<div class="mb-2"><label class="editor-tiny">Section to activate</label>';
      html += '<input class="form-control form-control-sm mt-1" id="order-add-value" data-symbol-role="section" value="New section"></div>';
    } else if (kind === 'progress') {
      html += '<div class="mb-2"><label class="editor-tiny">Progress percent</label>';
      html += '<input type="number" min="0" max="100" step="1" class="form-control form-control-sm mt-1" id="order-add-value" value="50"></div>';
    } else if (kind === 'function') {
      html += '<div class="mb-2"><label class="editor-tiny">Function call</label>';
      html += '<input class="form-control form-control-sm mt-1 font-monospace" id="order-add-invoke" data-symbol-role="function-call" value="function_call()"></div>';
    } else {
      html += '<div class="mb-2"><label class="editor-tiny">Raw Python</label>';
      html += '<textarea class="form-control form-control-sm mt-1 font-monospace" id="order-add-code" rows="4">pass</textarea></div>';
    }

    bodyEl.innerHTML = html;
    if (kind !== 'gather' && saveBtn) saveBtn.disabled = false;
  }

  function openOrderAddModal(parentStepId, branch, insertIndex) {
    _pendingOrderInsert = {
      parentStepId: parentStepId || '',
      branch: branch || 'then',
      insertIndex: Number.isFinite(insertIndex) ? insertIndex : -1,
    };
    var kindSelect = document.getElementById('order-add-kind');
    if (kindSelect) {
      kindSelect.value = 'screen';
      renderOrderAddBody(kindSelect.value);
    }
    var addModal = getOrCreateBootstrapModal('order-add-modal');
    if (addModal) addModal.show();
  }

  function insertOrderStepAtLocation(step, parentStepId, branch, insertIndex) {
    if (!step) return;
    if (parentStepId) {
      var parentRecord = findStepRecord(state.orderSteps, parentStepId, null);
      if (parentRecord) {
        var targetList = getOrderBranchSteps(parentRecord.step, branch);
        if (branch === 'else') parentRecord.step.has_else = true;
        if (!Number.isFinite(insertIndex) || insertIndex < 0 || insertIndex > targetList.length) insertIndex = targetList.length;
        targetList.splice(insertIndex, 0, step);
        state.orderCollapsed[parentStepId] = false;
      }
    } else {
      if (!Number.isFinite(insertIndex) || insertIndex < 0 || insertIndex > state.orderSteps.length) insertIndex = state.orderSteps.length;
      state.orderSteps.splice(insertIndex, 0, step);
    }
  }

  function clearInsertedStepHighlightSoon(stepId) {
    if (_lastInsertedOrderStepTimer) {
      window.clearTimeout(_lastInsertedOrderStepTimer);
      _lastInsertedOrderStepTimer = null;
    }
    _lastInsertedOrderStepTimer = window.setTimeout(function () {
      var stepEl = document.querySelector('.editor-order-step[data-step-id="' + stepId + '"]');
      if (stepEl) stepEl.classList.remove('editor-order-step-new');
      if (_lastInsertedOrderStepId === stepId) _lastInsertedOrderStepId = null;
    }, 950);
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
      if (step.kind === 'section') lines.push(prefix + "nav.set_section('" + String(step.value || '') + "')");
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
  var CHOICE_TYPES = ['radio', 'checkboxes', 'combobox', 'multiselect', 'dropdown',
                      'object', 'object_radio', 'object_checkboxes', 'object_multiselect'];

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

  function appendYamlBlockValue(yaml, key, value) {
    if (value === undefined || value === null) return yaml;
    var text = String(value);
    if (!text.trim()) return yaml;
    yaml += key + ': |\n';
    text.split('\n').forEach(function (line) {
      yaml += '      ' + line + '\n';
    });
    return yaml;
  }

  function _yamlScalar(value) {
    if (value === true) return 'True';
    if (value === false) return 'False';
    if (value === null || value === undefined) return '';
    return escapeYamlStr(String(value));
  }

  function _yamlValueLines(value, indent) {
    var pad = ' '.repeat(indent || 0);
    var lines = [];
    if (Array.isArray(value)) {
      if (value.length === 0) return ['[]'];
      value.forEach(function (item) {
        if (item && typeof item === 'object' && !Array.isArray(item)) {
          var keys = Object.keys(item);
          if (keys.length === 0) {
            lines.push(pad + '- {}');
          } else {
            var first = keys[0];
            var firstVal = item[first];
            if (firstVal && typeof firstVal === 'object') {
              lines.push(pad + '- ' + first + ':');
              lines = lines.concat(_yamlValueLines(firstVal, indent + 4));
            } else {
              lines.push(pad + '- ' + first + ': ' + _yamlScalar(firstVal));
            }
            keys.slice(1).forEach(function (key) {
              lines = lines.concat(_yamlKeyValueLines(key, item[key], indent + 2));
            });
          }
        } else {
          lines.push(pad + '- ' + _yamlScalar(item));
        }
      });
      return lines;
    }
    if (value && typeof value === 'object') {
      Object.keys(value).forEach(function (key) {
        lines = lines.concat(_yamlKeyValueLines(key, value[key], indent));
      });
      return lines.length ? lines : ['{}'];
    }
    return [_yamlScalar(value)];
  }

  function _yamlKeyValueLines(key, value, indent) {
    var pad = ' '.repeat(indent || 0);
    if (Array.isArray(value) || (value && typeof value === 'object')) {
      return [pad + key + ':'].concat(_yamlValueLines(value, (indent || 0) + 2));
    }
    if (typeof value === 'string' && value.indexOf('\n') !== -1) {
      var out = [pad + key + ': |'];
      value.replace(/\n$/, '').split('\n').forEach(function (line) {
        out.push(pad + '  ' + line);
      });
      return out;
    }
    return [pad + key + ': ' + _yamlScalar(value)];
  }

  function serializeReviewItemData(item) {
    if (typeof item === 'string') {
      var raw = item.trim();
      if (raw.indexOf('- ') === 0) return raw + '\n';
      return '- ' + _yamlScalar(item) + '\n';
    }
    if (!item || typeof item !== 'object') return '- note: ""\n';
    var keys = Object.keys(item);
    if (!keys.length) return '- note: ""\n';
    var first = keys[0];
    var lines = [];
    var firstValue = item[first];
    if (Array.isArray(firstValue) || (firstValue && typeof firstValue === 'object')) {
      lines.push('- ' + first + ':');
      lines = lines.concat(_yamlValueLines(firstValue, 2));
    } else if (typeof firstValue === 'string' && firstValue.indexOf('\n') !== -1) {
      lines.push('- ' + first + ': |');
      firstValue.replace(/\n$/, '').split('\n').forEach(function (line) {
        lines.push('  ' + line);
      });
    } else {
      lines.push('- ' + first + ': ' + _yamlScalar(firstValue));
    }
    keys.slice(1).forEach(function (key) {
      lines = lines.concat(_yamlKeyValueLines(key, item[key], 2));
    });
    return lines.join('\n') + '\n';
  }

  function serializeReviewItemSnippetForBlock(snippet) {
    var text = String(snippet || '').trim();
    if (!text) return '';
    if (text.indexOf('- ') === 0) return text + '\n';
    return '- ' + text + '\n';
  }

  function stashReviewItemSnippets(block) {
    if (!block || !block.data) return;
    var controls = document.querySelectorAll('.editor-review-item[data-review-item-idx]');
    if (!controls.length) return;
    block.data.review = Array.prototype.map.call(controls, function (el) {
      return _serializeReviewItemFromControls(el.getAttribute('data-review-item-idx')).trim();
    });
  }

  function _reviewItemActionKey(item) {
    if (!item || typeof item !== 'object') return '';
    var reserved = {
      button: true,
      help: true,
      'show if': true,
      'hide if': true,
      'css class': true,
      fields: true,
      note: true,
      html: true,
    };
    var keys = Object.keys(item);
    for (var i = 0; i < keys.length; i++) {
      if (!reserved[keys[i]]) return keys[i];
    }
    return '';
  }

  function _reviewFieldsValueToText(value) {
    if (Array.isArray(value)) {
      return value.map(function (item) {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object') return Object.keys(item)[0] || '';
        return String(item || '');
      }).filter(Boolean).join('\n');
    }
    if (value === undefined || value === null) return '';
    if (typeof value === 'object') return JSON.stringify(value, null, 2);
    return String(value);
  }

  function _reviewFieldsTextToValue(text) {
    var parts = String(text || '').split(/[\n,]/).map(function (part) {
      return part.trim();
    }).filter(Boolean);
    if (parts.length > 1) return parts;
    return parts[0] || '';
  }

  function _serializeReviewItemFromControls(idx) {
    var kindEl = document.querySelector('[data-review-kind="' + idx + '"]');
    if (!kindEl) return '';
    var kind = kindEl.value || 'edit';
    if (kind === 'raw') {
      var rawEl = document.getElementById('review-item-yaml-' + idx);
      return serializeReviewItemSnippetForBlock(rawEl ? rawEl.value : '');
    }
    var item = {};
    if (kind === 'note' || kind === 'html') {
      var contentEl = document.getElementById('review-item-content-' + idx);
      item[kind] = contentEl ? contentEl.value : '';
    } else {
      var labelEl = document.getElementById('review-item-label-' + idx);
      var fieldsEl = document.getElementById('review-item-fields-' + idx);
      var buttonEl = document.getElementById('review-item-button-' + idx);
      var actionKey = labelEl && labelEl.value.trim() ? labelEl.value.trim() : 'Edit';
      item[actionKey] = _reviewFieldsTextToValue(fieldsEl ? fieldsEl.value : '');
      if (buttonEl && buttonEl.value.trim()) item.button = buttonEl.value;
    }
    var showIfEl = document.getElementById('review-item-show-if-' + idx);
    if (showIfEl && showIfEl.value.trim()) item['show if'] = showIfEl.value.trim();
    var helpEl = document.getElementById('review-item-help-' + idx);
    if (helpEl && helpEl.value.trim()) item.help = helpEl.value;
    return serializeReviewItemData(item);
  }

  function _appendQuestionAdvancedYaml(yaml, block) {
    var data = (block && block.data) || {};

    function _rawValue(domId, dataKeys) {
      var el = document.getElementById(domId);
      if (el && typeof el.value !== 'undefined') return el.value;
      var keys = Array.isArray(dataKeys) ? dataKeys : [dataKeys];
      for (var i = 0; i < keys.length; i++) {
        var key = keys[i];
        if (Object.prototype.hasOwnProperty.call(data, key)) {
          return data[key];
        }
      }
      return undefined;
    }

    function _textValue(domId, dataKeys) {
      var raw = _rawValue(domId, dataKeys);
      if (raw === undefined || raw === null) return '';
      if (Array.isArray(raw)) return raw.join(', ');
      return String(raw);
    }

    function _boolValue(domId, dataKeys) {
      var el = document.getElementById(domId);
      if (el) return Boolean(el.checked);
      var raw = _rawValue(domId, dataKeys);
      return Boolean(raw);
    }

    var condEnabled = _boolValue('adv-enable-if', ['_editor_if_enabled', 'if']);
    var condValue = _textValue('adv-if', 'if');
    if (condEnabled && condValue.trim()) {
      yaml = appendYamlValue(yaml, 'if', condValue.trim());
    }

    var mandatoryEnabled = _boolValue('adv-mandatory-switch', 'mandatory');
    var mandatoryBtn = document.getElementById('adv-mandatory-toggle');
    if (mandatoryBtn && mandatoryBtn.getAttribute('data-enabled') === 'true') {
      mandatoryEnabled = true;
    }
    if (mandatoryEnabled) {
      yaml += 'mandatory: True\n';
    }

    var setsKey = document.getElementById('adv-sets')
      ? (document.getElementById('adv-sets').getAttribute('data-sets-key') || 'sets')
      : (Object.prototype.hasOwnProperty.call(data, 'only sets') ? 'only sets' : 'sets');
    var setsValue = _textValue('adv-sets', setsKey);
    if (setsValue.trim()) {
      yaml = appendYamlListValue(yaml, setsKey, setsValue);
    }

    var needValue = _textValue('adv-need', 'need');
    if (needValue.trim()) {
      yaml = appendYamlListValue(yaml, 'need', needValue);
    }

    var eventValue = _textValue('adv-event', 'event');
    if (eventValue.trim()) {
      yaml = appendYamlValue(yaml, 'event', eventValue.trim());
    }

    var genericObjectValue = _textValue('adv-generic-object', 'generic object');
    if (genericObjectValue.trim()) {
      yaml = appendYamlValue(yaml, 'generic object', genericObjectValue.trim());
    }

    var continueFieldValue = _textValue('adv-continue-field', 'continue button field');
    if (continueFieldValue.trim()) {
      yaml = appendYamlValue(yaml, 'continue button field', continueFieldValue.trim());
    }

    var continueLabelValue = _textValue('adv-continue-label', 'continue button label');
    if (continueLabelValue.trim()) {
      yaml = appendYamlValue(yaml, 'continue button label', continueLabelValue.trim());
    }

    var continueColorValue = _textValue('adv-continue-color', 'continue button color');
    if (continueColorValue.trim()) {
      yaml = appendYamlValue(yaml, 'continue button color', continueColorValue.trim());
    }

    var hideContinueValue = _textValue('adv-hide-continue', 'hide continue button');
    if (hideContinueValue.trim() && hideContinueValue.toLowerCase() === 'true') {
      yaml = appendYamlValue(yaml, 'hide continue button', 'True');
    }

    var disableContinueValue = _textValue('adv-disable-continue', 'disable continue button');
    if (disableContinueValue.trim() && disableContinueValue.toLowerCase() === 'true') {
      yaml = appendYamlValue(yaml, 'disable continue button', 'True');
    }

    var preventBackValue = _textValue('adv-prevent-back', 'prevent going back');
    if (preventBackValue.trim()) {
      yaml = appendYamlValue(yaml, 'prevent going back', preventBackValue.trim());
    }

    var backButtonValue = _textValue('adv-back-button', 'back button');
    if (backButtonValue.trim()) {
      yaml = appendYamlValue(yaml, 'back button', backButtonValue.trim());
    }

    var backButtonLabelValue = _textValue('adv-back-button-label', 'back button label');
    if (backButtonLabelValue.trim()) {
      yaml = appendYamlValue(yaml, 'back button label', backButtonLabelValue.trim());
    }

    var progressValue = _textValue('adv-progress', 'progress');
    if (progressValue.trim()) {
      yaml = appendYamlValue(yaml, 'progress', progressValue.trim());
    }

    var sectionValue = _textValue('adv-section', 'section');
    if (sectionValue.trim()) {
      yaml = appendYamlValue(yaml, 'section', sectionValue.trim());
    }

    var helpValue = _textValue('adv-help', 'help');
    if (helpValue.trim()) {
      yaml = appendYamlValue(yaml, 'help', helpValue);
    }

    var audioValue = _textValue('adv-audio', 'audio');
    if (audioValue.trim()) {
      yaml = appendYamlValue(yaml, 'audio', audioValue.trim());
    }

    var videoValue = _textValue('adv-video', 'video');
    if (videoValue.trim()) {
      yaml = appendYamlValue(yaml, 'video', videoValue.trim());
    }

    var decorationValue = _textValue('adv-decoration', 'decoration');
    if (decorationValue.trim()) {
      yaml = appendYamlValue(yaml, 'decoration', decorationValue.trim());
    }

    var scriptValue = _textValue('adv-script', 'script');
    if (scriptValue.trim()) {
      yaml = appendYamlValue(yaml, 'script', scriptValue);
    }

    var cssValue = _textValue('adv-css', 'css');
    if (cssValue.trim()) {
      yaml = appendYamlValue(yaml, 'css', cssValue);
    }

    var languageValue = _textValue('adv-language', 'language');
    if (languageValue.trim()) {
      yaml = appendYamlValue(yaml, 'language', languageValue.trim());
    }

    var reloadValue = _textValue('adv-reload', 'reload');
    if (reloadValue.trim()) {
      yaml = appendYamlValue(yaml, 'reload', reloadValue.trim());
    }

    var roleValue = _textValue('adv-role', 'role');
    if (roleValue.trim()) {
      yaml = appendYamlValue(yaml, 'role', roleValue.trim());
    }

    var gaIdValue = _textValue('adv-ga-id', 'ga id');
    if (gaIdValue.trim()) {
      yaml = appendYamlValue(yaml, 'ga id', gaIdValue.trim());
    }

    var segmentIdValue = _textValue('adv-segment-id', 'segment id');
    if (segmentIdValue.trim()) {
      yaml = appendYamlValue(yaml, 'segment id', segmentIdValue.trim());
    }

    var scanVarsValue = _textValue('adv-scan-vars', 'scan for variables');
    if (scanVarsValue.trim()) {
      yaml = appendYamlValue(yaml, 'scan for variables', scanVarsValue.trim());
    }

    var resumeLabelValue = _textValue('adv-resume-button-label', 'resume button label');
    if (resumeLabelValue.trim()) {
      yaml = appendYamlValue(yaml, 'resume button label', resumeLabelValue.trim());
    }

    var allowedToSetValue = _textValue('adv-allowed-to-set', 'allowed to set');
    if (allowedToSetValue.trim()) {
      yaml = appendYamlListValue(yaml, 'allowed to set', allowedToSetValue);
    }

    var dependsOnValue = _textValue('adv-depends-on', 'depends on');
    if (dependsOnValue.trim()) {
      yaml = appendYamlListValue(yaml, 'depends on', dependsOnValue);
    }

    var undefineValue = _textValue('adv-undefine', 'undefine');
    if (undefineValue.trim()) {
      yaml = appendYamlListValue(yaml, 'undefine', undefineValue);
    }

    var reconsiderValue = _textValue('adv-reconsider', 'reconsider');
    if (reconsiderValue.trim()) {
      yaml = appendYamlListValue(yaml, 'reconsider', reconsiderValue);
    }

    var validationCodeValue = _textValue('adv-validation-code', 'validation code');
    if (validationCodeValue.trim()) {
      yaml = appendYamlValue(yaml, 'validation code', validationCodeValue);
    }

    var commentValue = _textValue('adv-comment', 'comment');
    if (commentValue.trim()) {
      yaml = appendYamlValue(yaml, 'comment', commentValue);
    }

    return yaml;
  }

  function serializeQuestionToYaml(block) {
    var yaml = '';
    var data = (block && block.data) || {};

    var idInput = document.getElementById('adv-id');
    var blockId = (idInput && idInput.value) ? idInput.value : (block && block.id ? block.id : 'question_block');
    yaml = appendYamlValue(yaml, 'id', blockId);

    var qTitle = document.getElementById('q-title');
    var questionText = qTitle && qTitle.value ? qTitle.value : (block && block.data && block.data.question ? String(block.data.question) : '');
    if (questionText) yaml = appendYamlValue(yaml, 'question', questionText);

    var qSub = document.getElementById('q-subquestion');
    var subquestionText = qSub && qSub.value ? qSub.value : (block && block.data && block.data.subquestion ? String(block.data.subquestion) : '');
    if (subquestionText) yaml = appendYamlValue(yaml, 'subquestion', subquestionText);

    var rows = document.querySelectorAll('.editor-field-row');
    if (rows.length > 0) {
      yaml += 'fields:\n';
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var rowIdx = row.getAttribute('data-field-idx') !== null ? row.getAttribute('data-field-idx') : String(i);
        var type = row.querySelector('[data-field-prop="type"]').value;
        var isStandaloneType = _fieldTypeSupportsStandaloneContent(type);
        var labelEl = row.querySelector('[data-field-prop="label"]');
        var label = labelEl ? String(labelEl.value || '') : '';
        if (!isStandaloneType && !label) label = 'Label';
        var variable = row.querySelector('[data-field-prop="variable"]').value;
        var choicesEl = document.getElementById('field-choices-' + rowIdx);
        var codeEl = document.getElementById('field-code-' + rowIdx);
        var showIfEl = document.getElementById('field-showif-' + rowIdx);
        var showIfKeyEl = document.querySelector('.editor-field-showif-key[data-field-idx="' + rowIdx + '"]');
        var requiredSwitch = document.querySelector('.editor-field-required-switch[data-field-idx="' + rowIdx + '"]');
        var fieldModsPanel = document.querySelector('.editor-field-mods-panel[data-field-idx="' + rowIdx + '"]');
        var fmodInputs = fieldModsPanel ? fieldModsPanel.querySelectorAll('[data-fmod]') : [];
        var sfmods = {};
        fmodInputs.forEach(function (el) { var k = el.getAttribute('data-fmod'); var v = el.value.trim(); if (v) sfmods[k] = v; });
        var hasCodeExpr = codeEl && codeEl.value.trim();
        var hasChoices = choicesEl && choicesEl.value.trim() && CHOICE_TYPES.indexOf(type) !== -1;
        var showIfVal = showIfEl ? showIfEl.value.trim() : '';
        var showIfKey = showIfKeyEl ? showIfKeyEl.value : 'show if';
        var isRequired = requiredSwitch ? requiredSwitch.checked : true;
        var hasMods = hasCodeExpr || showIfVal || !isRequired || Object.keys(sfmods).length > 0;
        var isMultiLineLabel = label.indexOf('\n') !== -1;
        if (isStandaloneType) {
          yaml = appendYamlBlockValue(yaml, '  - ' + type, label);
          if (hasChoices) {
            yaml += '    choices:\n';
            choicesEl.value.split('\n').forEach(function (c) { if (c.trim()) yaml += '      - ' + escapeYamlStr(c.trim()) + '\n'; });
          }
          if (hasCodeExpr) {
            var codeStr = codeEl.value.trim();
            yaml += '    code: |\n';
            codeStr.split('\n').forEach(function (line) { yaml += '      ' + line + '\n'; });
          }
          if (!isRequired) yaml += '    required: False\n';
          if (showIfVal) yaml += '    ' + showIfKey + ': ' + escapeYamlStr(showIfVal) + '\n';
          Object.keys(sfmods).forEach(function (k) { yaml += '    ' + k + ': ' + escapeYamlStr(sfmods[k]) + '\n'; });
          continue;
        }
        if (isMultiLineLabel || hasMods) {
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
        if (hasChoices) {
          yaml += '    choices:\n';
          choicesEl.value.split('\n').forEach(function (c) { if (c.trim()) yaml += '      - ' + escapeYamlStr(c.trim()) + '\n'; });
        }
        if (hasCodeExpr) {
          var codeStr = codeEl.value.trim();
          if (codeStr.indexOf('\n') !== -1) {
            yaml += '    code: |\n';
            codeStr.split('\n').forEach(function (line) { yaml += '      ' + line + '\n'; });
          } else {
            yaml += '    code: ' + codeStr + '\n';
          }
        }
        if (!isRequired) yaml += '    required: False\n';
        if (showIfVal) yaml += '    ' + showIfKey + ': ' + escapeYamlStr(showIfVal) + '\n';
        Object.keys(sfmods).forEach(function (k) { yaml += '    ' + k + ': ' + escapeYamlStr(sfmods[k]) + '\n'; });
      }
    } else if ((state.markdownPreviewMode || state.questionBlockTab !== 'screen') && block && block.data && Array.isArray(block.data.fields) && block.data.fields.length > 0) {
      yaml += 'fields:\n';
      block.data.fields.forEach(function (field) {
        yaml += _serializeQuestionFieldFromData(field);
      });
    }

    return _appendQuestionAdvancedYaml(yaml, block);
  }

  function serializeReviewToYaml(block) {
    var data = (block && block.data) || {};
    var yaml = '';
    var blockIdEl = document.getElementById('review-block-id');
    var blockId = blockIdEl ? blockIdEl.value.trim() : String(data.id || (block && block.id) || 'review_screen');
    yaml = appendYamlValue(yaml, 'id', blockId || 'review_screen');

    var eventEl = document.getElementById('review-event');
    var eventText = eventEl ? eventEl.value.trim() : String(data.event || '').trim();
    if (eventText) yaml = appendYamlValue(yaml, 'event', eventText);

    var questionEl = document.getElementById('review-question');
    var questionText = questionEl ? questionEl.value : String(data.question || 'Review your answers');
    yaml = appendYamlValue(yaml, 'question', questionText || 'Review your answers');

    var subEl = document.getElementById('review-subquestion');
    var subText = subEl ? subEl.value : String(data.subquestion || '');
    if (subText.trim()) yaml = appendYamlValue(yaml, 'subquestion', subText);

    var continueEl = document.getElementById('review-continue-field');
    var continueText = continueEl ? continueEl.value.trim() : String(data['continue button field'] || data.field || '').trim();
    var continueKey = continueEl ? (continueEl.getAttribute('data-continue-key') || 'continue button field') : (data.field && !data['continue button field'] ? 'field' : 'continue button field');
    if (continueText) yaml = appendYamlValue(yaml, continueKey, continueText);

    var needEl = document.getElementById('review-need');
    var needText = needEl ? needEl.value.trim() : (Array.isArray(data.need) ? data.need.join(', ') : String(data.need || '').trim());
    if (needText) yaml = appendYamlListValue(yaml, 'need', needText);

    var tabularEl = document.getElementById('review-tabular');
    var tabularText = tabularEl ? tabularEl.value.trim() : String(data.tabular || '').trim();
    if (tabularText) yaml = appendYamlValue(yaml, 'tabular', tabularText);

    var skipUndefinedEl = document.getElementById('review-skip-undefined');
    var skipUndefinedText = skipUndefinedEl ? skipUndefinedEl.value.trim() : (data['skip undefined'] === false ? 'False' : '');
    if (skipUndefinedText) yaml = appendYamlValue(yaml, 'skip undefined', skipUndefinedText);

    var managedReviewKeys = {
      id: true,
      event: true,
      question: true,
      subquestion: true,
      field: true,
      'continue button field': true,
      need: true,
      tabular: true,
      'skip undefined': true,
      review: true,
    };
    Object.keys(data).forEach(function (key) {
      if (managedReviewKeys[key] || key.charAt(0) === '_') return;
      _yamlKeyValueLines(key, data[key], 0).forEach(function (line) {
        yaml += line + '\n';
      });
    });

    yaml += 'review:\n';
    var itemControls = document.querySelectorAll('.editor-review-item[data-review-item-idx]');
    if (itemControls.length) {
      itemControls.forEach(function (el) {
        var idx = el.getAttribute('data-review-item-idx');
        _serializeReviewItemFromControls(idx).split('\n').forEach(function (line) {
          if (line.trim()) yaml += '  ' + line + '\n';
        });
      });
    } else if (Array.isArray(data.review)) {
      data.review.forEach(function (item) {
        serializeReviewItemData(item).split('\n').forEach(function (line) {
          if (line.trim()) yaml += '  ' + line + '\n';
        });
      });
    } else {
      yaml += '  - note: Add review items here.\n';
    }
    return yaml;
  }

  function _serializeQuestionFieldFromData(field) {
    var yaml = '';
    if (field === null || field === undefined) return yaml;
    if (typeof field === 'string' || typeof field === 'number' || typeof field === 'boolean') {
      return '  - ' + escapeYamlStr(String(field)) + '\n';
    }
    if (typeof field !== 'object') return yaml;

    var reserved = {
      label: true,
      question: true,
      field: true,
      variable: true,
      datatype: true,
      type: true,
      choices: true,
      code: true,
      required: true,
    };
    var keys = Object.keys(field);
    var standaloneType = null;
    if (!field.label && !field.question && !field.field && !field.variable) {
      for (var i = 0; i < keys.length; i++) {
        if (!Object.prototype.hasOwnProperty.call(field, keys[i])) continue;
        if (reserved[keys[i]]) continue;
        if (_fieldTypeSupportsStandaloneContent(keys[i])) {
          standaloneType = keys[i];
          break;
        }
      }
    }

    if (standaloneType) {
      yaml += '  - ' + standaloneType + ': ' + escapeYamlStr(String(field[standaloneType] || '')) + '\n';
      if (Array.isArray(field.choices) && field.choices.length) {
        yaml += '    choices:\n';
        field.choices.forEach(function (choice) {
          var choiceText = String(choice || '').trim();
          if (choiceText) yaml += '      - ' + escapeYamlStr(choiceText) + '\n';
        });
      }
      if (field.code) {
        var standaloneCode = String(field.code);
        if (standaloneCode.indexOf('\n') !== -1) {
          yaml += '    code: |\n';
          standaloneCode.split('\n').forEach(function (line) { yaml += '      ' + line + '\n'; });
        } else {
          yaml += '    code: ' + standaloneCode + '\n';
        }
      }
      if (field.required === false || field.required === 'False') yaml += '    required: False\n';
      keys.forEach(function (key) {
        if (reserved[key] || key === standaloneType) return;
        var value = field[key];
        if (value === undefined || value === null || String(value).trim() === '') return;
        yaml += '    ' + key + ': ' + escapeYamlStr(String(value)) + '\n';
      });
      return yaml;
    }

    var label = String(field.label || field.question || 'Field').trim() || 'Field';
    var variable = String(field.field || field.variable || '').trim();
    var datatype = String(field.datatype || field.type || 'text').trim() || 'text';
    var hasChoices = Array.isArray(field.choices) && field.choices.length > 0;
    var hasCode = Boolean(field.code && String(field.code).trim());
    var isRequired = !(field.required === false || field.required === 'False');
    var extraMods = [];
    keys.forEach(function (key) {
      if (reserved[key] || key === 'label' || key === 'question' || key === 'field' || key === 'variable' || key === 'datatype' || key === 'type') return;
      var value = field[key];
      if (value === undefined || value === null || String(value).trim() === '') return;
      extraMods.push(key);
    });

    if (label.indexOf('\n') !== -1 || datatype !== 'text' || hasChoices || hasCode || !isRequired || extraMods.length > 0) {
      yaml += '  - label: ' + escapeYamlStr(label) + '\n';
      if (variable) yaml += '    field: ' + escapeYamlStr(variable) + '\n';
    } else {
      yaml += '  - ' + escapeYamlStr(label) + ':';
      if (variable) yaml += ' ' + escapeYamlStr(variable) + '\n';
      else yaml += '\n';
    }

    if (datatype && datatype !== 'text') yaml += '    datatype: ' + datatype + '\n';
    if (hasChoices) {
      yaml += '    choices:\n';
      field.choices.forEach(function (choice) {
        var choiceText = String(choice || '').trim();
        if (choiceText) yaml += '      - ' + escapeYamlStr(choiceText) + '\n';
      });
    }
    if (hasCode) {
      var codeText = String(field.code);
      if (codeText.indexOf('\n') !== -1) {
        yaml += '    code: |\n';
        codeText.split('\n').forEach(function (line) { yaml += '      ' + line + '\n'; });
      } else {
        yaml += '    code: ' + codeText + '\n';
      }
    }
    if (!isRequired) yaml += '    required: False\n';

    extraMods.forEach(function (key) {
      var value = field[key];
      if (value === undefined || value === null || String(value).trim() === '') return;
      yaml += '    ' + key + ': ' + escapeYamlStr(String(value)) + '\n';
    });

    return yaml;
  }

  function serializeCodeToYaml(block) {
    var yaml = '';
    var data = (block && block.data) || {};
    var idInput = document.getElementById('adv-id');
    var blockId = (idInput && idInput.value) ? idInput.value : (block && block.id ? block.id : 'code_block');
    yaml = appendYamlValue(yaml, 'id', blockId);

    var codeText = getMonacoValue('code-monaco');
    if (!codeText && block && block.data && block.data.code) {
      codeText = String(block.data.code);
    }
    yaml += 'code: |\n';
    String(codeText || '').split('\n').forEach(function (line) {
      yaml += '  ' + line + '\n';
    });

    return _appendQuestionAdvancedYaml(yaml, block);
  }

  function serializeObjectsToYaml(block) {
    var yaml = '';
    var data = (block && block.data) || {};
    var idInput = document.getElementById('adv-id');
    var blockId = (idInput && idInput.value) ? idInput.value : (block && block.id ? block.id : 'objects_block');
    yaml = appendYamlValue(yaml, 'id', blockId);

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

    return _appendQuestionAdvancedYaml(yaml, block);
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

    var mandatorySwitch = document.getElementById('adv-mandatory-switch');
    var mandatoryBtn = document.getElementById('adv-mandatory-toggle');
    if (mandatorySwitch || mandatoryBtn) {
      if ((mandatorySwitch && mandatorySwitch.checked) || (mandatoryBtn && mandatoryBtn.getAttribute('data-enabled') === 'true')) blk.data.mandatory = true;
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

    // Extended advanced fields (show more)
    function _syncSimple(id, key) {
      var el = document.getElementById(id);
      if (!el) return;
      var v = String(el.value || '').trim();
      if (v) blk.data[key] = v; else delete blk.data[key];
    }
    function _syncList(id, key) {
      var el = document.getElementById(id);
      if (!el) return;
      var v = String(el.value || '').trim();
      if (v) {
        var parts = v.split(',').map(function (p) { return p.trim(); }).filter(Boolean);
        blk.data[key] = parts.length > 1 ? parts : (parts[0] || v);
      } else delete blk.data[key];
    }
    _syncSimple('adv-continue-color', 'continue button color');
    _syncSimple('adv-back-button', 'back button');
    _syncSimple('adv-back-button-label', 'back button label');
    _syncSimple('adv-hide-continue', 'hide continue button');
    _syncSimple('adv-disable-continue', 'disable continue button');
    _syncSimple('adv-prevent-back', 'prevent going back');
    _syncSimple('adv-progress', 'progress');
    _syncSimple('adv-section', 'section');
    _syncSimple('adv-help', 'help');
    _syncSimple('adv-audio', 'audio');
    _syncSimple('adv-video', 'video');
    _syncSimple('adv-decoration', 'decoration');
    _syncSimple('adv-script', 'script');
    _syncSimple('adv-css', 'css');
    _syncSimple('adv-language', 'language');
    _syncSimple('adv-reload', 'reload');
    _syncSimple('adv-role', 'role');
    _syncSimple('adv-ga-id', 'ga id');
    _syncSimple('adv-segment-id', 'segment id');
    _syncSimple('adv-comment', 'comment');
    _syncSimple('adv-validation-code', 'validation code');
    _syncSimple('adv-resume-button-label', 'resume button label');
    _syncSimple('adv-scan-vars', 'scan for variables');
    _syncList('adv-allowed-to-set', 'allowed to set');
    _syncList('adv-depends-on', 'depends on');
    _syncList('adv-undefine', 'undefine');
    _syncList('adv-reconsider', 'reconsider');
  }

  function syncFieldsToData(blk) {
    if (!blk || blk.type !== 'question') return;
    var rows = document.querySelectorAll('.editor-field-row');
    syncQuestionMetaToData(blk);
    if (rows.length === 0) {
      if (state.questionBlockTab === 'screen' && !state.markdownPreviewMode) blk.data.fields = [];
      return;
    }
    blk.data.fields = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var rowIdx = row.getAttribute('data-field-idx') !== null ? row.getAttribute('data-field-idx') : String(i);
      var type = row.querySelector('[data-field-prop="type"]').value;
      var isStandaloneType = _fieldTypeSupportsStandaloneContent(type);
      var labelEl = row.querySelector('[data-field-prop="label"]');
      var label = labelEl ? String(labelEl.value || '') : '';
      if (!isStandaloneType && !label) label = 'Label';
      var variable = row.querySelector('[data-field-prop="variable"]').value;
      var choicesEl = document.getElementById('field-choices-' + rowIdx);
      var codeEl = document.getElementById('field-code-' + rowIdx);
      var showIfEl = document.getElementById('field-showif-' + rowIdx);
      var showIfKeyEl = document.querySelector('.editor-field-showif-key[data-field-idx="' + rowIdx + '"]');
      var requiredSwitch = document.querySelector('.editor-field-required-switch[data-field-idx="' + rowIdx + '"]');
      var fieldModsPanel = document.querySelector('.editor-field-mods-panel[data-field-idx="' + rowIdx + '"]');
      var fmodInputs = fieldModsPanel ? fieldModsPanel.querySelectorAll('[data-fmod]') : [];
      var syncFmods = {};
      fmodInputs.forEach(function (el) { var k = el.getAttribute('data-fmod'); var v = el.value.trim(); if (v) syncFmods[k] = v; });
      var hasCodeExpr = codeEl && codeEl.value.trim();
      var hasChoices = choicesEl && choicesEl.value.trim() && CHOICE_TYPES.indexOf(type) !== -1;
      var showIfVal = showIfEl ? showIfEl.value.trim() : '';
      var showIfKey = showIfKeyEl ? showIfKeyEl.value : 'show if';
      var isRequired = requiredSwitch ? requiredSwitch.checked : true;
      var hasMods = hasCodeExpr || showIfVal || !isRequired || Object.keys(syncFmods).length > 0;
      if (isStandaloneType) {
        var standaloneObj = {};
        standaloneObj[type] = label;
        Object.keys(syncFmods).forEach(function (k) { standaloneObj[k] = syncFmods[k]; });
        blk.data.fields.push(standaloneObj);
        continue;
      }
      if (!variable && type === 'text' && !hasMods) {
        blk.data.fields.push(label);
        continue;
      }
      // Use expanded label:/field: format for round-trip fidelity with modifiers
      var fieldObj = { label: label };
      if (variable) fieldObj.field = variable;
      if (type && type !== 'text') fieldObj.datatype = type;
      if (hasChoices) {
        fieldObj.choices = choicesEl.value.split('\n').map(function (c) { return c.trim(); }).filter(Boolean);
      }
      if (hasCodeExpr) fieldObj.code = codeEl.value.trim();
      if (!isRequired) fieldObj.required = false;
      if (showIfVal) fieldObj[showIfKey] = showIfVal;
      Object.keys(syncFmods).forEach(function (k) { fieldObj[k] = syncFmods[k]; });
      blk.data.fields.push(fieldObj);
    }
  }

  function _setButtonLoading(buttonId, loading, loadingText) {
    var btn = document.getElementById(buttonId);
    if (!btn) return;
    if (loading) {
      btn.setAttribute('data-prev-label', btn.textContent || '');
      btn.textContent = loadingText;
      btn.disabled = true;
      return;
    }
    var prev = btn.getAttribute('data-prev-label');
    if (prev !== null) {
      btn.textContent = prev;
      btn.removeAttribute('data-prev-label');
    }
    btn.disabled = false;
  }

  function _fieldsToExpandedRows(fields) {
    var out = [];
    (fields || []).forEach(function (field) {
      if (!field || typeof field !== 'object') return;
      var label = String(field.label || field.question || 'Field').trim() || 'Field';
      var variable = String(field.field || field.variable || '').trim();
      var datatype = String(field.datatype || field.type || 'text').trim() || 'text';
      var row = {
        label: label,
        field: variable,
        datatype: datatype,
      };
      if (Array.isArray(field.choices) && field.choices.length) {
        row.choices = field.choices.map(function (choice) { return String(choice); });
      }
      out.push(row);
    });
    return out;
  }

  function applyAIGeneratedScreenToBlock(block, screen) {
    if (!block || block.type !== 'question' || !screen || typeof screen !== 'object') return;
    if (!block.data || typeof block.data !== 'object') block.data = {};
    if (screen.question) {
      block.data.question = String(screen.question);
      block.title = String(screen.question);
    }
    if (screen.subquestion) block.data.subquestion = String(screen.subquestion);
    else delete block.data.subquestion;
    var fields = _fieldsToExpandedRows(screen.fields || []);
    block.data.fields = fields;
    if (screen.continue_button_field) block.data['continue button field'] = String(screen.continue_button_field);
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

  function getSectionFiles(view) {
    return state.sectionFiles[view] || [];
  }

  function getSelectedSectionFileMeta(view) {
    var selectedName = state.sectionSelectedFile[view];
    var files = getSectionFiles(view);
    for (var i = 0; i < files.length; i++) {
      if (files[i].filename === selectedName) return files[i];
    }
    return files.length ? files[0] : null;
  }

  function loadSectionFiles(view) {
    var section = getSectionFromView(view);
    if (!section || !state.project) {
      if (section) {
        state.sectionFiles[view] = [];
        state.sectionSelectedFile[view] = null;
      }
      renderOutline();
      renderCanvas();
      return Promise.resolve();
    }
    return apiGet('/api/section-files?project=' + encodeURIComponent(state.project) + '&section=' + encodeURIComponent(section))
      .then(function (res) {
        if (!res.success || !res.data) return;
        var files = Array.isArray(res.data.files) ? res.data.files : [];
        state.sectionFiles[view] = files;
        var selected = state.sectionSelectedFile[view];
        var stillExists = false;
        for (var i = 0; i < files.length; i++) {
          if (files[i].filename === selected) {
            stillExists = true;
            break;
          }
        }
        if (!stillExists) {
          state.sectionSelectedFile[view] = files.length ? files[0].filename : null;
        }
        if (!isInterviewView()) {
          renderOutline();
          renderCanvas();
        }
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
        var currentStillExists = state.filename && state.files.some(function (f) { return f.filename === state.filename; });
        if (!currentStillExists) {
          state.filename = state.files.length ? state.files[0].filename : null;
        }
        populateFiles();
        if (state.files.length === 0) {
          state.blocks = [];
          renderOutline();
          renderCanvas();
          loadSectionFiles('templates');
          loadSectionFiles('modules');
          loadSectionFiles('static');
          loadSectionFiles('data');
          return;
        }
        return loadFile().then(function () {
          loadSectionFiles('templates');
          loadSectionFiles('modules');
          loadSectionFiles('static');
          loadSectionFiles('data');
        });
      });
  }

  function loadFile() {
    if (!state.filename) return Promise.resolve();
    return apiGet(
      '/api/file?project=' + encodeURIComponent(state.project) +
      '&filename=' + encodeURIComponent(state.filename)
    ).then(function (res) {
      if (!res.success) {
        state.blocks = [];
        state.rawYaml = '';
        state.dirty = false;
        renderOutline();
        renderCanvas();
        return;
      }
      var d = res.data;
      state.blocks = d.blocks || [];
      state.metadataIndices = d.metadata_blocks || [];
      state.includeIndices = d.include_blocks || [];
      state.defaultSpIndices = d.default_screen_parts_blocks || [];
      state.orderIndices = d.order_blocks || [];
      state.orderStepMap = d.order_step_map || {};
      state.rawYaml = d.raw_yaml || '';
      state.dirty = false;
      state.fullYamlStash = {};
      state.selectedBlockId = getDefaultVisibleBlockId();
      setActiveOrderBlock(getDefaultOrderBlockId(), d.order_steps || []);
      loadAvailableSymbols(true);
      renderOutline();
      renderCanvas();
      runValidation();
    }).catch(function () {
      state.blocks = [];
      state.rawYaml = '';
      state.dirty = false;
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

  function getOutlineBlockIds() {
    return state.blocks.map(function (block) { return block.id; }).filter(Boolean);
  }

  function getVisibleOutlineBlockIds() {
    return filteredBlocks().map(function (block) { return block.id; }).filter(Boolean);
  }

  function getBlockIndexById(blockId) {
    for (var i = 0; i < state.blocks.length; i++) {
      if (state.blocks[i].id === blockId) return i;
    }
    return -1;
  }

  function reorderOutlineBlocks(blockIds, selectedBlockId) {
    if (!state.project || !state.filename || !Array.isArray(blockIds)) return Promise.resolve();
    return apiPost('/api/block/reorder', {
      project: state.project,
      filename: state.filename,
      block_ids: blockIds,
    }).then(function (res) {
      if (!res.success || !res.data) {
        window.alert((res.error && res.error.message) || 'Unable to move block.');
        return;
      }
      refreshFromFileResponse(res.data);
      if (selectedBlockId) {
        state.selectedBlockId = selectedBlockId;
        renderOutline();
        renderCanvas();
      }
    });
  }

  function moveOutlineBlock(blockId, delta) {
    var blockIds = getVisibleOutlineBlockIds();
    var currentIndex = blockIds.indexOf(blockId);
    if (currentIndex < 0) return;
    var targetIndex = currentIndex + delta;
    if (targetIndex < 0 || targetIndex >= blockIds.length) return;
    blockIds.splice(currentIndex, 1);
    blockIds.splice(targetIndex, 0, blockId);
    reorderVisibleOutlineBlocks(blockIds, blockId);
  }

  function moveOutlineBlockToEdge(blockId, edge) {
    var blockIds = getVisibleOutlineBlockIds();
    var currentIndex = blockIds.indexOf(blockId);
    if (currentIndex < 0) return;
    blockIds.splice(currentIndex, 1);
    if (edge === 'top') {
      blockIds.unshift(blockId);
    } else {
      blockIds.push(blockId);
    }
    reorderVisibleOutlineBlocks(blockIds, blockId);
  }

  function buildFullOutlineOrderFromVisibleIds(visibleIds) {
    var visibleSet = {};
    var nextVisibleIndex = 0;
    var orderedVisibleIds = Array.isArray(visibleIds) ? visibleIds.slice() : [];
    orderedVisibleIds.forEach(function (id) {
      if (id) visibleSet[id] = true;
    });
    return state.blocks.map(function (block) {
      if (block && block.id && visibleSet[block.id] && nextVisibleIndex < orderedVisibleIds.length) {
        return orderedVisibleIds[nextVisibleIndex++];
      }
      return block.id;
    });
  }

  function reorderVisibleOutlineBlocks(visibleIds, selectedBlockId) {
    return reorderOutlineBlocks(buildFullOutlineOrderFromVisibleIds(visibleIds), selectedBlockId);
  }

  function persistOutlineDragOrder() {
    if (!outlineList) return;
    var ids = [];
    outlineList.querySelectorAll('.editor-outline-item[data-block-id]').forEach(function (item) {
      ids.push(item.getAttribute('data-block-id'));
    });
    reorderVisibleOutlineBlocks(ids, state.selectedBlockId);
  }

  function initOutlineSortable() {
    if (_outlineSortable && _outlineSortable.destroy) {
      _outlineSortable.destroy();
      _outlineSortable = null;
    }
    if (!outlineList || !isOutlineDragEnabled() || typeof Sortable === 'undefined') return;
    _outlineSortable = Sortable.create(outlineList, {
      animation: 150,
      handle: '.editor-outline-drag-handle',
      draggable: '.editor-outline-item',
      filter: '.editor-outline-item-actions, .editor-outline-menu-btn',
      preventOnFilter: false,
      onEnd: function () {
        persistOutlineDragOrder();
      }
    });
  }

  function getBlockMenuHtml(block, index, totalCount) {
    var blockId = esc(block.id);
    var moveUpDisabled = index <= 0;
    var moveDownDisabled = index >= totalCount - 1;
    var enableLabel = block.type === 'commented' ? 'Re-enable block' : 'Disable (comment out)';
    var enableAction = block.type === 'commented' ? 'enable' : 'comment';
    var html = '';
    html += '<div class="dropdown editor-outline-item-actions">';
    html += '<button type="button" class="editor-outline-menu-btn" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-display="dynamic" aria-expanded="false" aria-label="Block actions" title="Block actions"><i class="fa-solid fa-ellipsis-vertical" aria-hidden="true"></i></button>';
    html += '<ul class="dropdown-menu dropdown-menu-end editor-outline-item-action-menu">';
    html += '<li><button type="button" class="dropdown-item" data-block-action="move-top" data-block-id="' + blockId + '"' + (moveUpDisabled ? ' disabled' : '') + '><i class="fa-solid fa-angles-up me-2" aria-hidden="true"></i>Move to top</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-block-action="move-up" data-block-id="' + blockId + '"' + (moveUpDisabled ? ' disabled' : '') + '><i class="fa-solid fa-arrow-up me-2" aria-hidden="true"></i>Move up</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-block-action="move-down" data-block-id="' + blockId + '"' + (moveDownDisabled ? ' disabled' : '') + '><i class="fa-solid fa-arrow-down me-2" aria-hidden="true"></i>Move down</button></li>';
    html += '<li><button type="button" class="dropdown-item" data-block-action="move-bottom" data-block-id="' + blockId + '"' + (moveDownDisabled ? ' disabled' : '') + '><i class="fa-solid fa-angles-down me-2" aria-hidden="true"></i>Move to bottom</button></li>';
    html += '<li><hr class="dropdown-divider"></li>';
    html += '<li><button type="button" class="dropdown-item" data-block-action="' + enableAction + '" data-block-id="' + blockId + '"><i class="fa-solid ' + (block.type === 'commented' ? 'fa-toggle-on' : 'fa-toggle-off') + ' me-2" aria-hidden="true"></i>' + enableLabel + '</button></li>';
    html += '<li><button type="button" class="dropdown-item text-danger" data-block-action="delete" data-block-id="' + blockId + '"><i class="fa-solid fa-trash-can me-2" aria-hidden="true"></i>Delete block</button></li>';
    html += '</ul></div>';
    return html;
  }

  function getProjectCardMenuHtml(projectName) {
    var projectId = esc(projectName);
    var html = '';
    html += '<div class="dropdown editor-project-card-actions">';
    html += '<button type="button" class="editor-project-card-menu-btn" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-display="dynamic" aria-expanded="false" aria-label="Project actions" title="Project actions"><i class="fa-solid fa-ellipsis-vertical" aria-hidden="true"></i></button>';
    html += '<ul class="dropdown-menu dropdown-menu-end editor-project-card-action-menu">';
    html += '<li><button type="button" class="dropdown-item" data-project-action="rename" data-project-name="' + projectId + '"><i class="fa-solid fa-pen me-2" aria-hidden="true"></i>Rename project</button></li>';
    html += '<li><button type="button" class="dropdown-item text-danger" data-project-action="delete" data-project-name="' + projectId + '"><i class="fa-solid fa-trash-can me-2" aria-hidden="true"></i>Delete project</button></li>';
    html += '</ul></div>';
    return html;
  }

  function reloadProjectsAfterMutation(projectName, replacementName) {
    return apiGet('/api/projects').then(function (res) {
      if (res.success && res.data) {
        state.projects = res.data.projects || [];
        populateProjects();
      }
      if (replacementName) {
        state.project = replacementName;
      } else if (projectName && state.project === projectName) {
        state.project = null;
        state.filename = null;
        state.blocks = [];
      }
      if (replacementName) {
        loadFiles();
      } else {
        renderCanvas();
      }
    });
  }

  // -------------------------------------------------------------------------
  // Outline
  // -------------------------------------------------------------------------
  function filteredBlocks() {
    var q = state.searchQuery.toLowerCase().trim();
    var orderById = {};
    state.orderIndices.forEach(function (idx) {
      var block = state.blocks[idx];
      if (block && block.id) orderById[block.id] = true;
    });
    var filtered = state.blocks.filter(function (b) {
      var blockType = getBlockDisplayType(b);
      if (state.jumpTarget === 'all') return true;
      if (state.jumpTarget === 'questions') return blockType === 'question' || blockType === 'review';
      if (state.jumpTarget === 'reviews') return blockType === 'review';
      if (state.jumpTarget === 'order') return Boolean(orderById[b.id]);
      if (state.jumpTarget === 'code') return blockType === 'code';
      if (state.jumpTarget === 'objects') return blockType === 'objects';
      if (state.jumpTarget === 'attachments') {
        return Boolean((b.tags || []).indexOf('attachment') !== -1 || (b.data && (b.data.attachment || b.data.attachments)));
      }
      if (state.jumpTarget === 'meta') {
        return blockType === 'metadata' || blockType === 'includes' || blockType === 'default_screen_parts' || blockType === 'features' || blockType === 'other';
      }
      if (state.jumpTarget === 'templates') {
        return blockType === 'template';
      }
      if (state.jumpTarget === 'tables') {
        return blockType === 'table';
      }
      if (state.jumpTarget === 'events') {
        return Boolean((b.tags || []).indexOf('event') !== -1 || (b.data && b.data.event));
      }
      if (state.jumpTarget === 'modules') {
        return blockType === 'modules' || blockType === 'imports';
      }
      if (state.jumpTarget === 'sections') {
        return blockType === 'sections';
      }
      if (state.jumpTarget === 'commented') {
        return blockType === 'commented' || b.type === 'commented';
      }
      return true;
    });
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
    return null;
  }

  function typeClass(type) {
    if (type === 'question') return 'editor-outline-type-q';
    if (type === 'review') return 'editor-outline-type-review';
    if (type === 'code') return 'editor-outline-type-py';
    if (type === 'objects') return 'editor-outline-type-obj';
    if (type === 'metadata') return 'editor-outline-type-meta';
    if (type === 'includes') return 'editor-outline-type-inc';
    if (type === 'commented') return 'editor-outline-type-disabled';
    return 'editor-outline-type-oth';
  }

  function typeLabel(type) {
    if (type === 'commented') return 'Off';
    if (type === 'question') return 'Q';
    if (type === 'review') return 'Rev';
    if (type === 'code') return 'Py';
    if (type === 'objects') return 'Obj';
    if (type === 'metadata') return 'Meta';
    if (type === 'includes') return 'Inc';
    if (type === 'default_screen_parts') return 'Def';
    return type.charAt(0).toUpperCase() + type.slice(1, 3);
  }

  function _lintFindingLevel(finding) {
    return String((finding && finding.level) || (finding && finding.severity) || 'error').toLowerCase();
  }

  function _findingsMatchBlock(finding, block) {
    if (!finding || !block) return false;
    var findingBlockId = String((finding && (finding.block_id || finding.screen_id)) || '').trim();
    if (findingBlockId && findingBlockId === String(block.id || '').trim()) return true;
    if (finding && finding.screen_link) {
      var linkId = String(finding.screen_link || '').replace(/^#screen-/, '').trim();
      if (linkId && linkId === String(block.id || '').trim()) return true;
    }
    var lineNumber = Number((finding && finding.line_number) || 0);
    if (lineNumber > 0) {
      var startLine = Number(block.line_start || 0);
      var endLine = Number(block.line_end || 0);
      if (startLine > 0 && endLine >= startLine && lineNumber >= startLine && lineNumber <= endLine) {
        return true;
      }
    }
    var ruleId = String((finding && finding.rule_id) || '').trim();
    if ((ruleId === 'missing-metadata-fields' || ruleId === 'missing-custom-theme') && block.type === 'metadata') {
      return true;
    }
    var problematicText = String((finding && finding.problematic_text) || '').trim();
    if (problematicText) {
      var yamlText = String(block.yaml || '');
      var title = String(block.title || '');
      if (yamlText.indexOf(problematicText) !== -1 || title.indexOf(problematicText) !== -1) {
        return true;
      }
    }
    return false;
  }

  function getBlockLintFindings(blockId) {
    var block = getBlockById(blockId);
    if (!block) return [];
    return (state.validationErrors || []).filter(function (finding) {
      return _findingsMatchBlock(finding, block);
    });
  }

  function getBlockLintSummary(findings) {
    var summary = { error: 0, warning: 0, info: 0 };
    (findings || []).forEach(function (finding) {
      var level = _lintFindingLevel(finding);
      if (level !== 'error' && level !== 'warning' && level !== 'info') level = 'error';
      summary[level] += 1;
    });
    return summary;
  }

  function getBlockLintHighestLevel(findings) {
    var summary = getBlockLintSummary(findings);
    if (summary.error > 0) return 'error';
    if (summary.warning > 0) return 'warning';
    if (summary.info > 0) return 'info';
    return '';
  }

  function getBlockLintLeadMessage(findings) {
    if (!findings || !findings.length) return '';
    return String((findings[0] && findings[0].message) || '').trim();
  }

  function getBlockLintFeedbackClass(findings) {
    var level = getBlockLintHighestLevel(findings);
    if (!level) return '';
    return 'editor-outline-item-lint-' + level;
  }

  function renderOutline() {
    updateOutlineHeader();
    if (!isInterviewView()) {
      renderSectionOutline();
      return;
    }
    var blocks = filteredBlocks();
    var html = '';
    html += '<div class="editor-outline-insert"><button type="button" class="editor-outline-insert-btn" data-insert-after-id=""><span class="editor-outline-insert-line" aria-hidden="true"></span><span class="editor-outline-insert-icon"><i class="fa-solid fa-plus" aria-hidden="true"></i></span><span class="visually-hidden">Insert block at top</span></button></div>';
    blocks.forEach(function (block) {
      var active = state.selectedBlockId === block.id;
      var displayType = getBlockDisplayType(block);
      var tl = typeLabel(displayType);
      var tc = typeClass(displayType);
      var lintFindings = getBlockLintFindings(block.id);
      var lintClass = lintFindings.length ? (' ' + getBlockLintFeedbackClass(lintFindings)) : '';
      html += '<div class="editor-outline-item' + (active ? ' active' : '') + (block.type === 'commented' ? ' editor-outline-item-commented' : '') + lintClass + '" data-block-id="' + esc(block.id) + '">';
      html += '<div class="editor-outline-item-row">';
      if (active) html += '<div class="editor-outline-active-bar"></div>';
      if (isOutlineDragEnabled()) {
        html += '<button type="button" class="editor-outline-drag-handle btn btn-sm btn-link" title="Drag to reorder" aria-label="Drag to reorder"><i class="fa-solid fa-grip-vertical" aria-hidden="true"></i></button>';
      } else {
        html += '<span class="editor-outline-drag-spacer" aria-hidden="true"></span>';
      }
      html += '<div class="editor-outline-item-main"><div class="editor-outline-title">' + esc(block.title) + '</div>';
      if (block.variable) {
        html += '<div class="editor-outline-meta"><span>' + esc(block.variable) + '</span></div>';
      }
      if (lintFindings.length) {
        var lintLevel = getBlockLintHighestLevel(lintFindings) || 'info';
        var lintIcon = 'fa-circle-info';
        if (lintLevel === 'warning') lintIcon = 'fa-triangle-exclamation';
        if (lintLevel === 'error') lintIcon = 'fa-circle-xmark';
        html += '<div class="editor-outline-lint ' + esc(lintLevel) + '">';
        html += '<i class="fa-solid ' + lintIcon + ' editor-outline-lint-icon" aria-hidden="true"></i>';
        html += '<span class="editor-outline-lint-text">' + esc(getBlockLintLeadMessage(lintFindings) || 'Lint finding') + '</span>';
        if (lintFindings.length > 1) {
          html += '<span class="editor-outline-lint-count">+' + esc(String(lintFindings.length - 1)) + '</span>';
        }
        html += '</div>';
      }
      html += '</div>';
      html += '<div class="editor-outline-type ' + tc + '">' + esc(tl) + '</div>';
      html += getBlockMenuHtml(block, blocks.indexOf(block), blocks.length);
      html += '</div></div>';
      html += '<div class="editor-outline-insert"><button type="button" class="editor-outline-insert-btn" data-insert-after-id="' + esc(block.id) + '"><span class="editor-outline-insert-line" aria-hidden="true"></span><span class="editor-outline-insert-icon"><i class="fa-solid fa-plus" aria-hidden="true"></i></span><span class="visually-hidden">Insert block after ' + esc(block.title) + '</span></button></div>';
    });
    outlineList.innerHTML = html;
    initOutlineSortable();
  }

  function renderSectionOutline() {
    var view = state.currentView;
    var files = getSectionFiles(view);
    var q = state.searchQuery.toLowerCase().trim();
    var selected = state.sectionSelectedFile[view];
    var filtered = files.filter(function (f) {
      if (!q) return true;
      return String(f.filename || '').toLowerCase().indexOf(q) !== -1;
    });
    var html = '';
    if (!filtered.length) {
      html = '<div class="text-muted small p-2">No files found.</div>';
      outlineList.innerHTML = html;
      initOutlineSortable();
      return;
    }
    filtered.forEach(function (file) {
      var active = selected === file.filename;
      var tag = sectionTypeTag(file);
      var rawUrl = API + '/api/section-file/raw?project=' + encodeURIComponent(state.project) + '&section=' + encodeURIComponent(getSectionFromView(view)) + '&filename=' + encodeURIComponent(file.filename);
      html += '<div class="editor-outline-item' + (active ? ' active' : '') + '" data-section-filename="' + esc(file.filename) + '">';
      html += '<div class="editor-outline-item-row">';
      if (active) html += '<div class="editor-outline-active-bar"></div>';
      html += '<div style="min-width:0;flex:1"><div class="editor-outline-title">' + esc(file.filename) + '</div></div>';
      if (tag) {
        html += '<div class="editor-outline-type editor-outline-type-oth">' + esc(tag) + '</div>';
      }
      html += '<div class="dropdown editor-section-file-kebab" data-stop-propagation>';
      html += '<button type="button" class="editor-file-actions-kebab" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-display="dynamic" aria-expanded="false" title="File actions" aria-label="File actions"><i class="fa-solid fa-ellipsis-vertical" aria-hidden="true"></i></button>';
      html += '<ul class="dropdown-menu dropdown-menu-end">';
      html += '<li><button type="button" class="dropdown-item js-section-file-rename" data-filename="' + esc(file.filename) + '"><i class="fa-solid fa-pen me-2" aria-hidden="true"></i>Rename</button></li>';
      html += '<li><a class="dropdown-item" href="' + esc(rawUrl) + '" download="' + esc(file.filename) + '"><i class="fa-solid fa-download me-2" aria-hidden="true"></i>Download</a></li>';
      if (supportsDashboardEditor(file)) {
        html += '<li><button type="button" class="dropdown-item js-section-file-dashboard" data-filename="' + esc(file.filename) + '"><i class="fa-solid fa-pen-to-square me-2" aria-hidden="true"></i>Open in Dashboard editor</button></li>';
      }
      html += '<li><hr class="dropdown-divider"></li>';
      html += '<li><button type="button" class="dropdown-item text-danger js-section-file-delete" data-filename="' + esc(file.filename) + '"><i class="fa-solid fa-trash-can me-2" aria-hidden="true"></i>Delete</button></li>';
      html += '</ul></div>';
      html += '</div></div>';
    });
    // Bottom action buttons
    html += '<div class="editor-section-file-actions">';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" id="btn-new-section-file-inline"><i class="fa-solid fa-plus me-1" aria-hidden="true"></i>New</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" id="btn-upload-section-file-inline"><i class="fa-solid fa-upload me-1" aria-hidden="true"></i>Upload</button>';
    html += '</div>';
    outlineList.innerHTML = html;
    initOutlineSortable();
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
        if (!isBlockVisibleInOutline(state.blocks[i])) {
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
    if (state.questionEditMode === 'preview' && block.type === 'review') {
      return serializeReviewToYaml(block);
    }
    var yamlVal = getMonacoValue('block-yaml-monaco');
    if (!yamlVal && block.yaml) yamlVal = block.yaml;
    return yamlVal;
  }

  function saveCurrentBlockIfDirty() {
    if (!state.dirty || !state.filename) return Promise.resolve(true);
    if (state.orderDirty) {
      syncActiveOrderStepMap();
      return apiPost('/api/order', {
        project: state.project,
        filename: state.filename,
        order_block_id: state.activeOrderBlockId,
        steps: state.orderSteps,
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to save interview order.');
          return false;
        }
        state.orderDirty = false;
        state.dirty = false;
        updateTopbarSaveState();
        return true;
      });
    }
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
      if (!res.success || !res.data) {
        window.alert((res.error && res.error.message) || 'Unable to save block.');
        return false;
      }
      var keepBlockId = res.data.saved_block_id || block.id;
      refreshFromFileResponse(res.data);
      state.selectedBlockId = keepBlockId;
      renderOutline();
      renderCanvas();
      return true;
    });
  }

  // -------------------------------------------------------------------------
  // Validation / Error drawer
  // -------------------------------------------------------------------------
  var _validationInFlight = false;

  function getValidationDrawerTitle() {
    return state.validationMode === 'style' ? 'Style check' : 'Errors & Warnings';
  }

  function runCurrentValidationCheck() {
    if (state.validationMode === 'style') {
      runStyleCheck();
      return;
    }
    runValidation();
  }

  function runValidation() {
    if (!state.project || !state.filename || _validationInFlight) return;
    state.validationMode = 'validation';
    _validationInFlight = true;
    apiGet('/api/weaver/validate?project=' + encodeURIComponent(state.project) + '&filename=' + encodeURIComponent(state.filename))
      .then(function (res) {
        _validationInFlight = false;
        if (res.success && res.data) {
          state.validationErrors = res.data.errors || [];
        } else {
          state.validationErrors = [];
        }
        renderValidationDrawer();
        renderOutline();
      })
      .catch(function () {
        _validationInFlight = false;
        state.validationErrors = [{ level: 'error', message: 'Could not run validation right now.' }];
        renderValidationDrawer();
        renderOutline();
      });
  }

  function runStyleCheck() {
    if (!state.project || !state.filename || _validationInFlight) return;
    state.validationMode = 'style';
    _validationInFlight = true;
    apiGet('/api/weaver/style-check?project=' + encodeURIComponent(state.project) + '&filename=' + encodeURIComponent(state.filename) + '&include_llm=1')
      .then(function (res) {
        _validationInFlight = false;
        if (res.success && res.data) {
          state.validationErrors = res.data.errors || [];
        } else {
          state.validationErrors = [];
        }
        renderValidationDrawer();
        renderOutline();
      })
      .catch(function () {
        _validationInFlight = false;
        state.validationErrors = [{ level: 'error', message: 'Could not run style check right now.' }];
        renderValidationDrawer();
        renderOutline();
      });
  }

  function _validationLevelRank(level) {
    if (level === 'error') return 3;
    if (level === 'warning') return 2;
    return 1;
  }

  function _validationSummary(errors) {
    var counts = { error: 0, warning: 0, info: 0 };
    (errors || []).forEach(function (err) {
      var level = String((err && err.level) || 'error').toLowerCase();
      if (level !== 'error' && level !== 'warning' && level !== 'info') level = 'error';
      counts[level] += 1;
    });
    return counts;
  }

  function renderValidationDrawer() {
    var drawer = document.getElementById('validation-drawer');
    if (!drawer) return;
    var title = document.getElementById('validation-drawer-title');
    if (title) title.textContent = getValidationDrawerTitle();
    var count = state.validationErrors.length;
    var summary = _validationSummary(state.validationErrors);
    var hasProblems = (summary.error + summary.warning) > 0;
    var levelClass = summary.error > 0 ? 'validation-error' : (summary.warning > 0 ? 'validation-warning' : 'validation-info');

    Array.prototype.forEach.call(document.querySelectorAll('[data-validation-badge]'), function (badge) {
      badge.textContent = count > 0 ? String(count) : '';
      badge.classList.toggle('d-none', count === 0);
      badge.classList.toggle('validation-error', summary.error > 0);
      badge.classList.toggle('validation-warning', summary.error === 0 && summary.warning > 0);
      badge.classList.toggle('validation-info', summary.error === 0 && summary.warning === 0 && summary.info > 0);
    });

    Array.prototype.forEach.call(document.querySelectorAll('.js-check-errors-btn'), function (btn) {
      btn.classList.toggle('editor-validation-has-issues', hasProblems);
      btn.classList.toggle('editor-validation-has-info', !hasProblems && summary.info > 0);
    });

    // Show/hide the alert icon — only visible when there are actual errors
    Array.prototype.forEach.call(document.querySelectorAll('.js-check-errors-icon'), function (icon) {
      icon.classList.toggle('d-none', count === 0);
    });

    drawer.classList.toggle('editor-validation-has-issues', hasProblems);
    drawer.classList.remove('validation-error', 'validation-warning', 'validation-info');
    if (count > 0) drawer.classList.add(levelClass);

    var body = document.getElementById('validation-drawer-body');
    if (!body) return;
    if (!state.validationOpen) {
      drawer.classList.remove('open');
      body.innerHTML = '';
      return;
    }
    drawer.classList.add('open');
    if (count === 0) {
      body.innerHTML = '<div class="text-muted small p-2">No errors or warnings found.</div>';
      return;
    }
    var sortedErrors = (state.validationErrors || []).slice().sort(function (a, b) {
      var levelA = String((a && a.level) || 'error').toLowerCase();
      var levelB = String((b && b.level) || 'error').toLowerCase();
      var rankDiff = _validationLevelRank(levelB) - _validationLevelRank(levelA);
      if (rankDiff !== 0) return rankDiff;
      return Number((a && a.line_number) || 0) - Number((b && b.line_number) || 0);
    });
    var html = '<div class="editor-validation-summary small text-muted mb-2">'
      + summary.error + ' errors, '
      + summary.warning + ' warnings, '
      + summary.info + ' infos'
      + '</div>';
    html += '<ul class="editor-validation-list">';
    sortedErrors.forEach(function (err) {
      var level = String((err && err.level) || 'error').toLowerCase();
      var icon = 'fa-circle-info';
      if (level === 'warning') icon = 'fa-triangle-exclamation';
      if (level === 'error') icon = 'fa-circle-xmark';
      var lineText = err.line_number ? ('Line ' + Number(err.line_number)) : '';
      if (lineText && err.file_name) lineText += ' - ';
      if (err.file_name) lineText += String(err.file_name).split('/').pop();
      html += '<li class="editor-validation-item' + (err.block_id ? ' editor-validation-item-linked' : '') + '"' + (err.block_id ? ' data-block-id="' + esc(String(err.block_id)) + '"' : '') + '>';
      html += '<i class="fa-solid ' + icon + ' editor-validation-item-icon ' + esc(level) + '" aria-hidden="true"></i>';
      html += '<div class="editor-validation-item-msg">';
      html += '<div>' + esc(err.message || 'Unknown issue') + '</div>';
      if (lineText) html += '<div class="editor-validation-item-meta">' + esc(lineText) + '</div>';
      if (err.variable) html += '<span class="editor-validation-item-var">' + esc(err.variable) + '</span>';
      html += '</div>';
      html += '</li>';
    });
    html += '</ul>';
    body.innerHTML = html;
  }

  function renderCanvas() {
    disposeMonacoEditors();
    updateLeftRailMode();
    updateLeftSearchPlaceholder();
    updateTopbarProject();
    updateTopbarSaveState();
    if (state.currentView !== 'interview') {
      renderSecondaryView();
      renderValidationDrawer();
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
    renderValidationDrawer();
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
    } else if (block.type === 'review') {
      renderReviewBlock(block);
    } else if (block.type === 'commented') {
      renderCommentedBlock(block);
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
        html += '<div class="editor-project-card-shell editor-project-card-shell-recent">';
        html += '<button type="button" class="editor-project-card editor-project-card-recent" data-project-card="' + esc(name) + '">';
        html += '<span class="editor-project-card-badge">Recent</span>';
        html += '<span class="editor-project-card-title">' + esc(name) + '</span>';
        html += '<span class="editor-project-card-meta">Open project</span>';
        html += '</button>';
        html += getProjectCardMenuHtml(name);
        html += '</div>';
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
        html += '<div class="editor-project-card-shell">';
        html += '<button type="button" class="editor-project-card" data-project-card="' + esc(name) + '">';
        html += '<span class="editor-project-card-title">' + esc(name) + '</span>';
        html += '<span class="editor-project-card-meta">Open project</span>';
        html += '</button>';
        html += getProjectCardMenuHtml(name);
        html += '</div>';
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

    // Header bar — matches Code / Objects pattern
    html += '<div class="editor-center-bar">';
    html += '<div>';
    html += '<span class="editor-pill">Question</span>';
    if (data.mandatory) html += ' <span class="editor-pill">mandatory</span>';
    if (data.event) html += ' <span class="editor-pill">event: ' + esc(String(data.event)) + '</span>';
    html += '<div style="font-weight:600;font-size:16px;margin-top:6px">' + esc(block.title) + '</div>';
    html += '</div>';
    html += '</div>';

    html += '<div class="editor-shell">';

    // Unified tab row: Screen | Question options | Preview | YAML
    html += '<div class="editor-question-tabs-row">';
    html += '<ul class="nav nav-tabs editor-question-tabs" role="tablist">';
    html += '<li class="nav-item" role="presentation"><button type="button" class="nav-link ' + (isPreview && !isMdPreview && state.questionBlockTab === 'screen' ? 'active' : '') + '" data-question-tab="screen" data-question-mode="preview">Screen</button></li>';
    html += '<li class="nav-item" role="presentation"><button type="button" class="nav-link ' + (isPreview && !isMdPreview && state.questionBlockTab === 'options' ? 'active' : '') + '" data-question-tab="options" data-question-mode="preview">Question options</button></li>';
    html += '<li class="nav-item" role="presentation"><button type="button" class="nav-link ' + (isPreview && isMdPreview ? 'active' : '') + '" id="question-preview-tab" data-question-mode="preview" data-question-preview="true"><i class="fa-regular fa-eye me-1" aria-hidden="true"></i>Preview</button></li>';
    html += '<li class="nav-item" role="presentation"><button type="button" class="nav-link ' + (state.questionEditMode === 'yaml' ? 'active' : '') + '" id="toggle-edit-mode-tab" data-question-mode="yaml"><i class="fa-solid fa-code me-1" aria-hidden="true"></i>YAML</button></li>';
    html += '</ul>';
    if (isPreview) {
      html += '<div class="form-check form-switch editor-question-mandatory-switch">';
      html += '<input class="form-check-input" type="checkbox" role="switch" id="adv-mandatory-switch"' + (Boolean(data.mandatory) ? ' checked' : '') + '>';
      html += '<label class="form-check-label" for="adv-mandatory-switch">Mandatory</label>';
      html += '</div>';
    }
    html += '</div>';

    if (isPreview) {
      if (isMdPreview || state.questionBlockTab === 'screen') {
      html += '<div class="editor-card editor-question-main-card"><div class="editor-card-body editor-card-body-compact">';

      // Block ID — always visible at top
      if (!isMdPreview) {
        html += '<div class="editor-block-id-row">';
        html += '<span class="editor-block-id-label">ID</span>';
        html += '<input class="form-control editor-form-control editor-block-id-input font-monospace" id="adv-id" value="' + esc(block.id) + '" placeholder="block_id" autocomplete="off">';
        html += '<button type="button" class="btn btn-sm btn-link p-0 ms-1 text-muted" id="gen-block-id" title="Auto-generate from question text" aria-label="Auto-generate ID"><i class="fa-solid fa-rotate" aria-hidden="true"></i></button>';
        html += '</div>';
        var eventFieldOpen = Boolean(data.event || _questionEventFieldOpen[block.id]);
        if (eventFieldOpen) {
          html += '<div class="editor-block-id-row editor-question-event-row">';
          html += '<span class="editor-block-id-label">Event</span>';
          html += '<input class="form-control editor-form-control editor-block-id-input font-monospace" id="adv-event" value="' + esc(String(data.event || '')) + '" placeholder="event_name" autocomplete="off">';
          html += '<button type="button" class="btn btn-sm btn-link p-0 ms-1 text-muted" id="remove-question-event" title="Remove event" aria-label="Remove event"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>';
          html += '</div>';
        } else {
          html += '<button type="button" class="btn btn-sm btn-link editor-add-event-btn" id="add-question-event"><i class="fa-solid fa-plus me-1" aria-hidden="true"></i>Add event</button>';
        }
      }

      // Question
      html += '<div class="editor-form-group' + (isMdPreview ? '' : ' mt-2') + '">';
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

      if (!isMdPreview && (data['continue button field'] || data['continue button label'])) {
        html += '<div class="editor-info-box mt-2">';
        if (data['continue button field']) {
          html += '<div><strong>Continue button field:</strong> ' + esc(String(data['continue button field'])) + '</div>';
        }
        if (data['continue button label']) {
          html += '<div><strong>Continue button label:</strong> ' + esc(String(data['continue button label'])) + '</div>';
        }
        html += '</div>';
      }

      // Fields section — merged into same card
      if (fields.length > 0) {
        html += '<div class="editor-section-legend mt-3">Fields</div>';
        if (!isMdPreview) {
          html += '<div class="editor-field-grid-header">';
          html += '<div>Label</div><div>Type</div><div>Variable name</div><div></div>';
          html += '</div>';
        }
        fields.forEach(function (f, fi) {
          var label = '', varName = '', dtype = 'text', choices = '', codeExpr = '';
          var contentText = '';
          // Extract all known field modifiers into a bag
          var fmods = {};
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
              if (f.code) codeExpr = typeof f.code === 'string' ? f.code.trim() : String(f.code);
              // Collect all modifiers
              FIELD_MODIFIER_KEYS.forEach(function (mk) {
                if (mk !== 'label' && mk !== 'field' && mk !== 'datatype' && mk !== 'choices' && mk !== 'code' && f[mk] !== undefined) {
                  fmods[mk] = f[mk];
                }
              });
            } else {
              var keys = Object.keys(f);
              if (keys.length > 0) {
                var firstKey = keys[0];
                var _isTypeShorthand = FIELD_TYPES.indexOf(firstKey) !== -1 || firstKey === 'no label';
                if (_isTypeShorthand) {
                  dtype = firstKey;
                  var val = f[firstKey];
                  if (_isStandaloneFieldType(firstKey)) {
                    contentText = typeof val === 'string' ? val : '';
                    label = contentText;
                    varName = '';
                  } else if (firstKey === 'no label') {
                    label = '(no label)';
                    varName = typeof val === 'string' ? val : '';
                  } else {
                    varName = typeof val === 'string' ? val : '';
                    label = varName ? varName.replace(/_/g, ' ').replace(/\[.*$/, '') : firstKey;
                  }
                } else {
                  label = firstKey;
                  var val = f[firstKey];
                  if (typeof val === 'string') {
                    varName = val;
                  } else if (typeof val === 'object' && val !== null) {
                    varName = val.variable || val.name || firstKey;
                    dtype = val.datatype || val.input_type || 'text';
                    if (val.choices && Array.isArray(val.choices)) {
                      choices = val.choices.map(function (c) {
                        if (typeof c === 'object') { var ck = Object.keys(c); return ck[0] + ': ' + c[ck[0]]; }
                        return String(c);
                      }).join('\n');
                    }
                  }
                }
                if (f.datatype && !_isTypeShorthand) dtype = f.datatype;
                if (f.input_type && dtype === 'text') dtype = f.input_type;
                if (!choices && f.choices && Array.isArray(f.choices)) {
                  choices = f.choices.map(function (c) {
                    if (typeof c === 'object') { var ck = Object.keys(c); return ck[0] + ': ' + c[ck[0]]; }
                    return String(c);
                  }).join('\n');
                }
                var _codeSource = f.code || (typeof val === 'object' && val !== null ? val.code : null);
                if (_codeSource) codeExpr = typeof _codeSource === 'string' ? _codeSource.trim() : String(_codeSource);
                FIELD_MODIFIER_KEYS.forEach(function (mk) {
                  if (mk !== 'label' && mk !== 'field' && mk !== 'datatype' && mk !== 'choices' && mk !== 'code' && f[mk] !== undefined) {
                    fmods[mk] = f[mk];
                  }
                });
              }
            }
          } else if (typeof f === 'string') {
            label = f;
          }

          var isStandaloneType = _fieldTypeSupportsStandaloneContent(dtype);
          var hasChoices = CHOICE_TYPES.indexOf(dtype) !== -1;
          var hasCode = Boolean(codeExpr);
          var requiredVal = fmods.required;
          var isRequired = requiredVal === undefined || requiredVal === true || requiredVal === 'True';
          var showIfVal = fmods['show if'] || fmods['hide if'] || '';
          var showIfKey = fmods['hide if'] ? 'hide if' : 'show if';
          if (typeof showIfVal === 'object') showIfVal = JSON.stringify(showIfVal);

          if (isMdPreview) {
            html += '<div class="editor-field-row-preview">';
            if (isStandaloneType) {
              if (dtype === 'html' || dtype === 'raw html') {
                html += '<div class="md-preview-wrapper md-preview-label">' + String(label || '') + '</div>';
              } else if (dtype === 'code') {
                html += '<div class="md-preview-wrapper md-preview-label"><pre class="mb-0"><code>' + esc(String(label || '')) + '</code></pre></div>';
              } else {
                html += '<div class="md-preview-wrapper md-preview-label">' + renderMarkdown(String(label || '')) + '</div>';
              }
              html += '<div class="editor-tiny text-muted" style="align-self:start;padding-top:6px">' + esc(_fieldTypeLabel(dtype)) + '</div>';
              html += '<div></div>';
            } else {
              html += '<div class="md-preview-wrapper md-preview-label">' + renderMarkdown(label) + '</div>';
              html += '<div class="editor-tiny text-muted" style="align-self:start;padding-top:6px">' + esc(dtype) + '</div>';
              html += '<div class="font-monospace editor-tiny" style="align-self:start;padding-top:6px">' + esc(varName) + '</div>';
            }
            html += '</div>';
          } else {
            html += '<div class="editor-field-row' + (isStandaloneType ? ' editor-field-row-special' : '') + '" data-field-idx="' + fi + '">';
            if (isStandaloneType) {
              html += '<textarea class="form-control editor-form-control editor-field-content font-monospace" data-field-prop="label" data-label-field="true" placeholder="' + esc(_fieldStandalonePlaceholder(dtype)) + '" title="Right-click for insert tools" rows="' + _fieldStandaloneRows(dtype) + '">' + esc(label) + '</textarea>';
            } else {
              html += '<input class="form-control editor-form-control" data-field-prop="label" data-label-field="true" placeholder="Field label" title="Right-click for insert tools" value="' + esc(label) + '">';
            }
            html += _renderFieldTypeDropdown(fi, dtype);
            html += '<input class="form-control editor-form-control font-monospace' + (isStandaloneType ? ' d-none' : '') + '" data-field-prop="variable" data-symbol-role="variable" value="' + esc(varName) + '" placeholder="variable_name">';
            html += '<div class="editor-field-actions">';
            if (!isStandaloneType) {
              html += '<div class="form-check form-switch editor-field-switch-wrap" title="Required">';
              html += '<input class="form-check-input editor-field-required-switch" type="checkbox" role="switch" id="field-required-' + fi + '" data-field-idx="' + fi + '"' + (isRequired ? ' checked' : '') + '>';
              html += '<label class="form-check-label editor-tiny" for="field-required-' + fi + '">Required</label>';
              html += '</div>';
              var activeIndicators = _fieldActiveIndicators(dtype, fmods, choices, codeExpr);
              if (activeIndicators.length > 0) {
                html += '<div class="editor-field-indicators" aria-label="Active options">';
                activeIndicators.slice(0, 3).forEach(function (tag) { html += '<span class="badge text-bg-light">' + esc(tag) + '</span>'; });
                html += '</div>';
              }
            }
            html += '<div class="editor-field-kebab-wrapper">';
            html += '<button type="button" class="btn btn-sm btn-ghost-secondary editor-field-kebab-btn" data-field-idx="' + fi + '" aria-haspopup="true" aria-expanded="' + (_openFieldModsPanels[fi] ? 'true' : 'false') + '" title="Field settings" aria-label="Field settings"><i class="fa-solid fa-sliders" aria-hidden="true"></i></button>';
            html += '</div>';
            html += '<button type="button" class="btn btn-sm btn-ghost-danger editor-icon-btn" data-remove-field="' + fi + '" title="Remove field"><i class="fa-solid fa-trash-can" aria-hidden="true"></i><span class="visually-hidden">Remove field</span></button>';
            html += '</div>';
            html += '<select class="form-select editor-form-control d-none" data-field-prop="type">';
            FIELD_TYPES.forEach(function (t) {
              html += '<option value="' + t + '"' + (t === dtype ? ' selected' : '') + '>' + t + '</option>';
            });
            html += '</select>';
            html += '</div>';
            html += _renderFieldModsPanel(fi, fmods, dtype, choices, codeExpr, showIfKey, showIfVal);
          }
        });
        if (!isMdPreview) {
          html += '<div class="mt-2 d-flex gap-2 align-items-center flex-wrap">';
          html += '<button class="btn btn-sm btn-outline-primary" id="add-field-btn"><i class="fa-solid fa-plus me-1" aria-hidden="true"></i>Add field</button>';
          html += '<button class="btn btn-sm btn-outline-secondary" id="ai-generate-fields"><i class="fa-solid fa-wand-magic-sparkles me-1" aria-hidden="true"></i>AI fields</button>';
          html += '</div>';
        }
      } else if (!isMdPreview) {
        html += '<div class="editor-section-legend mt-3">Fields</div>';
        html += '<p class="text-muted small mb-2">No fields defined yet.</p>';
        html += '<div class="d-flex gap-2 align-items-center flex-wrap">';
        html += '<button class="btn btn-sm btn-outline-primary" id="add-field-btn"><i class="fa-solid fa-plus me-1" aria-hidden="true"></i>Add field</button>';
        html += '<button class="btn btn-sm btn-outline-secondary" id="ai-generate-fields"><i class="fa-solid fa-wand-magic-sparkles me-1" aria-hidden="true"></i>AI fields</button>';
        html += '</div>';
      }

      html += '</div></div>';

      // Attachment info
      if (data.attachment || data.attachments) {
        html += '<div class="editor-card"><div class="editor-card-header">Attachment</div><div class="editor-card-body">';
        html += '<div class="editor-info-box">This block has an attachment. Edit in YAML mode for full control.</div>';
        html += '</div></div>';
      }

      }

      if (!isMdPreview && state.questionBlockTab === 'options') {
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
          onChange: function () { state.dirty = true; updateTopbarSaveState(); }
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
      // Live uniqueness hint on the block ID field
      var idInput = document.getElementById('adv-id');
      if (idInput) {
        idInput.addEventListener('input', function () {
          var val = idInput.value.trim();
          var unique = !val || isBlockIdUnique(val, state.blocks, block.id);
          idInput.style.borderColor = (!val || unique) ? '' : '#dc3545';
          idInput.title = unique ? '' : 'This ID is already used by another block';
        });
      }
    }
  }

  function _reviewItemSummary(item, index) {
    if (typeof item === 'string') {
      var firstLine = item.trim().split('\n')[0] || 'Review item ' + (index + 1);
      return { kind: firstLine.indexOf('html:') !== -1 ? 'HTML' : (firstLine.indexOf('note:') !== -1 ? 'Note' : 'Field'), title: firstLine.replace(/^- /, ''), meta: '' };
    }
    if (!item || typeof item !== 'object') return { kind: 'Item', title: 'Review item ' + (index + 1), meta: '' };
    if (Object.prototype.hasOwnProperty.call(item, 'note')) {
      return { kind: 'Note', title: String(item.note || '').split('\n')[0] || 'Note', meta: item['show if'] ? 'show if' : '' };
    }
    if (Object.prototype.hasOwnProperty.call(item, 'html')) {
      return { kind: 'HTML', title: String(item.html || '').split('\n')[0] || 'Raw HTML', meta: item['show if'] ? 'show if' : '' };
    }
    var label = item.label || '';
    var keys = Object.keys(item);
    var actionKey = '';
    for (var i = 0; i < keys.length; i++) {
      if (['button', 'help', 'show if', 'css class', 'fields'].indexOf(keys[i]) === -1) {
        actionKey = keys[i];
        break;
      }
    }
    if (!label && actionKey) label = actionKey;
    var actionVal = actionKey ? item[actionKey] : item.fields;
    var meta = '';
    if (Array.isArray(actionVal)) meta = actionVal.map(function (v) {
      if (typeof v === 'string') return v;
      if (v && typeof v === 'object') return Object.keys(v)[0];
      return '';
    }).filter(Boolean).join(', ');
    else if (actionVal !== undefined && actionVal !== null && typeof actionVal !== 'object') meta = String(actionVal);
    if (item['show if']) meta = meta ? meta + ' - show if' : 'show if';
    return { kind: 'Field', title: String(label || 'Edit'), meta: meta };
  }

  function renderReviewBlock(block) {
    var data = block.data || {};
    var reviewItems = Array.isArray(data.review) ? data.review : [];
    var isYaml = state.questionEditMode === 'yaml';
    var html = '';

    html += '<div class="editor-center-bar">';
    html += '<div>';
    html += '<span class="editor-pill editor-pill-review">Review</span>';
    if (data.event) html += ' <span class="editor-pill">event</span>';
    if (data['continue button field'] || data.field) html += ' <span class="editor-pill">continue field</span>';
    html += '<div style="font-weight:600;font-size:16px;margin-top:6px">' + esc(block.title || 'Review') + '</div>';
    html += '</div>';
    html += '<div class="d-flex gap-2 flex-wrap">';
    html += '<button class="btn btn-sm btn-outline-secondary" id="draft-review-screen"><i class="fa-solid fa-wand-magic-sparkles me-1" aria-hidden="true"></i>Draft review</button>';
    html += '<button class="btn btn-sm btn-outline-secondary" id="toggle-edit-mode">' + (isYaml ? 'Structured view' : 'Edit full YAML') + '</button>';
    html += '</div>';
    html += '</div>';

    html += '<div class="editor-shell">';
    if (isYaml) {
      html += '<div class="editor-card"><div class="editor-card-body">';
      html += '<div class="editor-monaco-container" id="block-yaml-monaco" style="height:500px"></div>';
      html += '</div></div></div>';
      canvasContent.innerHTML = html;
      initMonaco(function () {
        createMonacoEditor('block-yaml-monaco', block.yaml, 'yaml', {
          onChange: function () { state.dirty = true; updateTopbarSaveState(); }
        });
      });
      return;
    }

    html += '<div class="editor-card editor-question-main-card"><div class="editor-card-body editor-card-body-compact">';
    html += '<div class="editor-block-id-row">';
    html += '<span class="editor-block-id-label">ID</span>';
    html += '<input class="form-control editor-form-control editor-block-id-input font-monospace" id="review-block-id" value="' + esc(data.id || block.id || '') + '" autocomplete="off">';
    html += '</div>';

    html += '<div class="editor-review-route-grid mt-2">';
    html += '<div><label class="editor-tiny" for="review-event">Event</label><input class="form-control editor-form-control font-monospace" id="review-event" value="' + esc(String(data.event || '')) + '"></div>';
    html += '<div><label class="editor-tiny" for="review-continue-field">Continue button field</label><input class="form-control editor-form-control font-monospace" id="review-continue-field" data-symbol-role="variable" data-continue-key="' + (data.field && !data['continue button field'] ? 'field' : 'continue button field') + '" value="' + esc(String(data['continue button field'] || data.field || '')) + '"></div>';
    html += '</div>';

    var hasMeta = Boolean(data.need || data.tabular || Object.prototype.hasOwnProperty.call(data, 'skip undefined'));
    html += '<button type="button" class="editor-advanced-toggle editor-review-meta-toggle mt-2" id="toggle-review-meta"><i class="fa-solid fa-chevron-down editor-collapse-icon' + (state.reviewMetaOpen ? '' : ' collapsed') + '" aria-hidden="true"></i>Review options' + (hasMeta ? ' <span class="editor-active-dot" aria-hidden="true"></span>' : '') + '</button>';
    if (state.reviewMetaOpen) {
      var needVal = Array.isArray(data.need) ? data.need.join(', ') : String(data.need || '');
      html += '<div class="editor-advanced-body editor-review-meta-body">';
      html += '<div class="editor-form-group"><label class="editor-tiny" for="review-need">Need <span class="text-muted">(comma-separated)</span></label><input class="form-control editor-form-control font-monospace" id="review-need" value="' + esc(needVal) + '"></div>';
      html += '<div class="editor-form-group"><label class="editor-tiny" for="review-tabular">Tabular</label><input class="form-control editor-form-control" id="review-tabular" value="' + esc(String(data.tabular || '')) + '" placeholder="True or table table-striped"></div>';
      html += '<div class="editor-form-group"><label class="editor-tiny" for="review-skip-undefined">Skip undefined</label><select class="form-select editor-form-control" id="review-skip-undefined">';
      html += '<option value=""' + (data['skip undefined'] !== false ? ' selected' : '') + '>(default)</option>';
      html += '<option value="False"' + (data['skip undefined'] === false ? ' selected' : '') + '>False</option>';
      html += '</select></div>';
      html += '</div>';
    }

    html += '<div class="editor-form-group mt-3"><label class="editor-tiny" for="review-question">Question</label><input class="form-control editor-form-control" id="review-question" value="' + esc(String(data.question || 'Review your answers')) + '"></div>';
    html += '<div class="editor-form-group"><label class="editor-tiny" for="review-subquestion">Subquestion</label><textarea class="form-control editor-form-control" id="review-subquestion" rows="3">' + esc(String(data.subquestion || '')) + '</textarea></div>';
    html += '</div></div>';

    html += '<div class="editor-card"><div class="editor-card-header"><span>Review items</span></div><div class="editor-card-body editor-review-list">';
    if (!reviewItems.length) {
      html += '<div class="text-muted small mb-2">No review items yet.</div>';
    }
    reviewItems.forEach(function (item, idx) {
      var summary = _reviewItemSummary(item, idx);
      var isOpen = state.openReviewItemIndex === idx;
      var isStringRaw = typeof item === 'string';
      var isNote = !isStringRaw && item && typeof item === 'object' && Object.prototype.hasOwnProperty.call(item, 'note');
      var isHtml = !isStringRaw && item && typeof item === 'object' && Object.prototype.hasOwnProperty.call(item, 'html');
      var actionKey = isStringRaw || isNote || isHtml ? '' : _reviewItemActionKey(item);
      var supportedReviewItemKeys = {};
      if (actionKey) supportedReviewItemKeys[actionKey] = true;
      ['button', 'show if', 'help', 'fields', 'note', 'html'].forEach(function (key) { supportedReviewItemKeys[key] = true; });
      var hasUnsupportedKeys = !isStringRaw && item && typeof item === 'object' && Object.keys(item).some(function (key) { return !supportedReviewItemKeys[key]; });
      var isRaw = isStringRaw || hasUnsupportedKeys;
      var actionValue = actionKey ? item[actionKey] : item.fields;
      html += '<div class="editor-review-item" data-review-item-idx="' + idx + '">';
      html += '<input type="hidden" data-review-kind="' + idx + '" value="' + (isRaw ? 'raw' : (isNote ? 'note' : (isHtml ? 'html' : 'edit'))) + '">';
      html += '<button type="button" class="editor-review-item-summary" data-review-item-toggle="' + idx + '">';
      html += '<span class="editor-review-kind">' + esc(summary.kind) + '</span>';
      html += '<span class="editor-review-title">' + esc(summary.title) + '</span>';
      if (summary.meta) html += '<span class="editor-review-meta">' + esc(summary.meta) + '</span>';
      html += '</button>';
      html += '<div class="editor-review-item-editor' + (isOpen ? '' : ' d-none') + '">';
      if (isRaw) {
        html += '<textarea class="form-control editor-form-control font-monospace editor-review-item-yaml" id="review-item-yaml-' + idx + '" rows="8">' + esc(serializeReviewItemData(item).trim()) + '</textarea>';
      } else if (isNote || isHtml) {
        html += '<label class="editor-tiny" for="review-item-content-' + idx + '">' + (isHtml ? 'HTML' : 'Note') + '</label>';
        html += '<textarea class="form-control editor-form-control ' + (isHtml ? 'font-monospace' : '') + '" id="review-item-content-' + idx + '" rows="5">' + esc(String(item[isHtml ? 'html' : 'note'] || '')) + '</textarea>';
        html += '<label class="editor-tiny mt-2" for="review-item-show-if-' + idx + '">Show if</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="review-item-show-if-' + idx + '" value="' + esc(String(item['show if'] || '')) + '">';
        if (item.help) {
          html += '<label class="editor-tiny mt-2" for="review-item-help-' + idx + '">Help</label>';
          html += '<textarea class="form-control editor-form-control" id="review-item-help-' + idx + '" rows="2">' + esc(String(item.help || '')) + '</textarea>';
        }
      } else {
        html += '<div class="editor-review-edit-grid">';
        html += '<div><label class="editor-tiny" for="review-item-label-' + idx + '">Button label</label><input class="form-control editor-form-control" id="review-item-label-' + idx + '" value="' + esc(actionKey || 'Edit') + '"></div>';
        html += '<div><label class="editor-tiny" for="review-item-fields-' + idx + '">Field</label><textarea class="form-control editor-form-control font-monospace" id="review-item-fields-' + idx + '" data-symbol-role="variable" rows="2">' + esc(_reviewFieldsValueToText(actionValue)) + '</textarea></div>';
        html += '</div>';
        html += '<div class="editor-form-group mt-2"><label class="editor-tiny" for="review-item-button-' + idx + '">Button</label>';
        html += renderMarkdownToolbar('review-item-button-' + idx, false);
        html += '<textarea class="form-control editor-form-control" id="review-item-button-' + idx + '" rows="5">' + esc(String(item.button || '')) + '</textarea></div>';
        html += '<label class="editor-tiny" for="review-item-show-if-' + idx + '">Show if</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="review-item-show-if-' + idx + '" value="' + esc(String(item['show if'] || '')) + '">';
        if (item.help) {
          html += '<label class="editor-tiny mt-2" for="review-item-help-' + idx + '">Help</label>';
          html += '<textarea class="form-control editor-form-control" id="review-item-help-' + idx + '" rows="2">' + esc(String(item.help || '')) + '</textarea>';
        }
      }
      html += '<div class="d-flex justify-content-end mt-2"><button type="button" class="btn btn-sm btn-ghost-danger" data-remove-review-item="' + idx + '"><i class="fa-solid fa-trash-can me-1" aria-hidden="true"></i>Remove</button></div>';
      html += '</div></div>';
    });
    html += '<div class="editor-review-add-row">';
    html += '<label class="editor-tiny" for="review-new-field">Field</label>';
    html += '<div class="editor-review-add-controls">';
    html += '<input class="form-control editor-form-control font-monospace" id="review-new-field" data-symbol-role="variable">';
    html += '<button type="button" class="btn btn-sm btn-outline-primary" data-add-review-item="edit"><i class="fa-solid fa-plus me-1" aria-hidden="true"></i>Edit row</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-review-item="note">Note</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary" data-add-review-item="html">HTML</button>';
    html += '</div></div>';
    html += '</div></div>';
    html += '</div>';
    canvasContent.innerHTML = html;

    ['review-subquestion'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) _initAutoResize(el, 80);
    });
    document.querySelectorAll('.editor-review-item-yaml, [id^="review-item-button-"], [id^="review-item-fields-"], #review-new-field').forEach(function (el) {
      _initAutoResize(el, 120);
    });
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
          onChange: function () { state.dirty = true; updateTopbarSaveState(); }
        });
      } else {
        createMonacoEditor('block-yaml-monaco', block.yaml, 'yaml', {
          onChange: function () { state.dirty = true; updateTopbarSaveState(); }
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
          html += '<div><button type="button" class="btn btn-sm btn-ghost-danger editor-icon-btn" data-remove-obj="' + oi + '" title="Remove object"><i class="fa-solid fa-trash-can" aria-hidden="true"></i><span class="visually-hidden">Remove object</span></button></div>';
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
          onChange: function () { state.dirty = true; updateTopbarSaveState(); }
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
    html += '</div>';

    html += '<div class="editor-shell">';
    html += '<div class="editor-card"><div class="editor-card-body">';
    html += '<div class="editor-monaco-container" id="block-yaml-monaco" style="height:500px"></div>';
    html += '</div></div>';
    html += '</div>';

    canvasContent.innerHTML = html;

    initMonaco(function () {
      createMonacoEditor('block-yaml-monaco', block.yaml, 'yaml', {
        onChange: function () { state.dirty = true; updateTopbarSaveState(); }
      });
    });
  }

  function renderCommentedBlock(block) {
    var html = '';
    html += '<div class="editor-center-bar">';
    html += '<div>';
    html += '<span class="editor-pill editor-pill-muted">Disabled</span>';
    html += '<div style="font-weight:600;font-size:16px;margin-top:6px">' + esc(block.title || block.id) + '</div>';
    html += '</div>';
    html += '<div class="d-flex gap-2">';
    html += '<button class="btn btn-sm btn-primary" id="enable-block-btn"><i class="fa-solid fa-circle-play me-1" aria-hidden="true"></i>Re-enable block</button>';
    html += '</div></div>';

    html += '<div class="editor-shell">';
    html += '<div class="editor-card"><div class="editor-card-body">';
    html += '<div class="editor-form-group">';
    html += '<label class="editor-tiny" for="commented-block-yaml">Commented YAML</label>';
    html += '<textarea class="form-control editor-form-control font-monospace editor-commented-yaml" id="commented-block-yaml" rows="14" readonly>' + esc(block.yaml || '') + '</textarea>';
    html += '</div>';
    html += '</div></div>';
    html += '</div>';

    canvasContent.innerHTML = html;
  }

  // --- Field modifiers panel (kebab menu for individual fields) ---
  var _openFieldModsPanels = {};
  var _fieldSettingsTabs = {};

  function _fieldTypeIcon(dtype) {
    var key = String(dtype || 'text').toLowerCase();
    var map = {
      text: 'fa-pencil',
      area: 'fa-paragraph',
      raw: 'fa-code',
      number: 'fa-hashtag',
      integer: 'fa-hashtag',
      currency: 'fa-dollar-sign',
      range: 'fa-sliders',
      email: 'fa-envelope',
      password: 'fa-lock',
      url: 'fa-link',
      date: 'fa-calendar-day',
      time: 'fa-clock',
      datetime: 'fa-calendar-check',
      yesno: 'fa-toggle-on',
      yesnowide: 'fa-toggle-on',
      yesnoradio: 'fa-circle-dot',
      yesnomaybe: 'fa-circle-half-stroke',
      noyes: 'fa-toggle-off',
      noyeswide: 'fa-toggle-off',
      noyesradio: 'fa-circle-dot',
      noyesmaybe: 'fa-circle-half-stroke',
      dropdown: 'fa-chevron-down',
      radio: 'fa-circle-dot',
      checkboxes: 'fa-square-check',
      multiselect: 'fa-list-check',
      combobox: 'fa-bars-staggered',
      file: 'fa-file-arrow-up',
      files: 'fa-folder-open',
      camera: 'fa-camera',
      microphone: 'fa-microphone',
      camcorder: 'fa-video',
      hidden: 'fa-eye-slash',
      note: 'fa-note-sticky',
      html: 'fa-code',
      'raw html': 'fa-code',
      code: 'fa-file-code',
      ml: 'fa-brain',
      mlarea: 'fa-brain',
      object: 'fa-cube',
      object_radio: 'fa-circle-dot',
      object_checkboxes: 'fa-square-check',
      object_multiselect: 'fa-list-check',
      user: 'fa-user',
      environment: 'fa-server',
    };
    return map[key] || 'fa-input-text';
  }

  function _fieldActiveIndicators(dtype, fmods, choices, codeExpr) {
    var indicators = [];
    if (CHOICE_TYPES.indexOf(dtype) !== -1 && choices) indicators.push('choices');
    if (codeExpr) indicators.push('code');
    if (fmods['show if'] || fmods['hide if'] || fmods['enable if'] || fmods['disable if']) indicators.push('logic');
    if (fmods.default || fmods.help || fmods.hint) indicators.push('display');
    if (fmods.validate || fmods['validation code']) indicators.push('validation');
    return indicators;
  }

  function _fieldTypeLabel(dtype) {
    var value = String(dtype || 'text');
    return FIELD_TYPE_LABELS[value] || value.replace(/_/g, ' ');
  }

  function _fieldStandalonePlaceholder(dtype) {
    switch (_normalizeFieldType(dtype)) {
      case 'note':
        return 'Note text';
      case 'html':
      case 'raw html':
        return 'HTML content';
      case 'code':
        return 'Python expression';
      default:
        return 'Content';
    }
  }

  function _fieldStandaloneRows(dtype) {
    return _normalizeFieldType(dtype) === 'code' ? 4 : 3;
  }

  function _renderFieldTypeDropdown(fi, dtype) {
    var html = '';
    html += '<div class="dropdown editor-field-type-dropdown">';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary dropdown-toggle editor-field-type-btn" id="field-type-btn-' + fi + '" data-bs-toggle="dropdown" aria-expanded="false" title="Datatype">';
    html += '<i class="fa-solid ' + _fieldTypeIcon(dtype) + '" aria-hidden="true"></i>';
    html += '<span>' + esc(_fieldTypeLabel(dtype)) + '</span>';
    html += '</button>';
    html += '<div class="dropdown-menu editor-field-type-menu" aria-labelledby="field-type-btn-' + fi + '">';
    FIELD_TYPE_GROUPS.forEach(function (group, gi) {
      if (gi > 0) html += '<div class="dropdown-divider"></div>';
      html += '<h6 class="dropdown-header">' + esc(group.label) + '</h6>';
      group.items.forEach(function (item) {
        html += '<button type="button" class="dropdown-item editor-field-type-item' + (item === dtype ? ' active' : '') + '" data-field-datatype="' + item + '" data-field-idx="' + fi + '">';
        html += '<i class="fa-solid ' + _fieldTypeIcon(item) + ' me-2" aria-hidden="true"></i>' + esc(_fieldTypeLabel(item));
        html += '</button>';
      });
    });
    html += '</div></div>';
    return html;
  }
  function _renderFieldModsPanel(fi, fmods, dtype, choices, codeExpr, showIfKey, showIfVal) {
    // Always render (with display:none when closed) so DOM elements exist for serialization
    var isOpen = _openFieldModsPanels[fi];
    var isStandalone = _fieldTypeSupportsStandaloneContent(dtype);
    var activeTab = _fieldSettingsTabs[fi] || (isStandalone ? 'logic' : 'basic');
    var tabLabels = {
      basic: 'Basic',
      logic: 'Logic',
      help: 'Help',
      validation: 'Validation',
      appearance: 'Appearance',
      metadata: 'Metadata',
      more: 'More',
    };
    var availableTabs = isStandalone ? ['logic'] : ['basic', 'logic', 'help', 'validation', 'appearance', 'metadata', 'more'];
    if (availableTabs.indexOf(activeTab) === -1) activeTab = availableTabs[0];

    function row(labelFor, labelText, controlHtml, rowClass) {
      var out = '<div class="' + (rowClass || 'editor-field-mod-row') + '">';
      if (labelText) out += '<label class="editor-tiny" for="' + esc(labelFor) + '">' + esc(labelText) + '</label>';
      out += controlHtml;
      out += '</div>';
      return out;
    }

    function pairRow(leftHtml, rightHtml) {
      return '<div class="editor-field-mod-row editor-field-mod-row-pair">' + leftHtml + rightHtml + '</div>';
    }

    function hiddenField(name) {
      return '<input type="hidden" id="' + esc(name) + '-' + fi + '" data-fmod="' + esc(name) + '" data-field-idx="' + fi + '" value="">';
    }

    function renderBasicTab() {
      var out = '';
      out += row('field-choices-' + fi, 'choices (one per line)', '<textarea class="form-control editor-form-control editor-field-choices" id="field-choices-' + fi + '" rows="3">' + esc(String(choices || '')) + '</textarea>');
      out += row('field-code-' + fi, 'code (Python expression)', '<textarea class="form-control editor-form-control font-monospace editor-field-code" id="field-code-' + fi + '" rows="3">' + esc(String(codeExpr || '')) + '</textarea>');
      out += row('fmod-default-' + fi, 'default', '<input class="form-control editor-form-control font-monospace" id="fmod-default-' + fi + '" data-fmod="default" data-field-idx="' + fi + '" value="' + esc(String(fmods['default'] || '')) + '">');
      out += row('fmod-input-type-' + fi, 'input type', '<select class="form-select editor-form-control" id="fmod-input-type-' + fi + '" data-fmod="input type" data-field-idx="' + fi + '"><option value="">(default)</option>' + ['area', 'radio', 'dropdown', 'combobox', 'ajax', 'datalist'].map(function (t) { return '<option value="' + t + '"' + (fmods['input type'] === t ? ' selected' : '') + '>' + esc(t) + '</option>'; }).join('') + '</select>');
      out += row('fmod-disabled-' + fi, 'disabled', '<select class="form-select editor-form-control" id="fmod-disabled-' + fi + '" data-fmod="disabled" data-field-idx="' + fi + '"><option value=""' + (!fmods.disabled ? ' selected' : '') + '>No</option><option value="True"' + (fmods.disabled ? ' selected' : '') + '>Yes</option></select>');
      return out;
    }

    function renderLogicTab() {
      var out = '';
      out += '<div class="editor-field-option-row" data-field-idx="' + fi + '">';
      out += '<label class="editor-tiny" for="field-showif-' + fi + '">condition</label>';
      out += '<select class="editor-field-showif-key" data-field-idx="' + fi + '" aria-label="Condition type">';
      out += '<option value="show if"' + (showIfKey === 'show if' ? ' selected' : '') + '>show if</option>';
      out += '<option value="hide if"' + (showIfKey === 'hide if' ? ' selected' : '') + '>hide if</option>';
      out += '</select>';
      out += renderSymbolDatalist('field-showif-list-' + fi, 'variable', 120);
      out += '<input class="form-control editor-form-control font-monospace editor-field-showif-input" data-symbol-role="variable" list="field-showif-list-' + fi + '" data-field-prop="showif" data-field-idx="' + fi + '" id="field-showif-' + fi + '" value="' + esc(String(showIfVal || '')) + '" placeholder="variable_name or object condition">';
      out += '</div>';
      out += row('fmod-enableif-' + fi, 'enable if', '<input class="form-control editor-form-control font-monospace" id="fmod-enableif-' + fi + '" data-fmod="enable if" data-field-idx="' + fi + '" value="' + esc(String(fmods['enable if'] || '')) + '">');
      out += row('fmod-disableif-' + fi, 'disable if', '<input class="form-control editor-form-control font-monospace" id="fmod-disableif-' + fi + '" data-fmod="disable if" data-field-idx="' + fi + '" value="' + esc(String(fmods['disable if'] || '')) + '">');
      out += '<div class="editor-tiny mt-2 mb-1" style="color:#6b7280;letter-spacing:0.04em;text-transform:uppercase;font-size:10px;">JavaScript conditions</div>';
      out += row('fmod-jsshowif-' + fi, 'js show if', '<input class="form-control editor-form-control font-monospace" id="fmod-jsshowif-' + fi + '" data-fmod="js show if" data-field-idx="' + fi + '" value="' + esc(String(fmods['js show if'] || '')) + '" placeholder="JavaScript expression">');
      out += row('fmod-jshideif-' + fi, 'js hide if', '<input class="form-control editor-form-control font-monospace" id="fmod-jshideif-' + fi + '" data-fmod="js hide if" data-field-idx="' + fi + '" value="' + esc(String(fmods['js hide if'] || '')) + '" placeholder="JavaScript expression">');
      out += row('fmod-jsenabledif-' + fi, 'js enable if', '<input class="form-control editor-form-control font-monospace" id="fmod-jsenabledif-' + fi + '" data-fmod="js enable if" data-field-idx="' + fi + '" value="' + esc(String(fmods['js enable if'] || '')) + '" placeholder="JavaScript expression">');
      out += row('fmod-jsdisabledif-' + fi, 'js disable if', '<input class="form-control editor-form-control font-monospace" id="fmod-jsdisabledif-' + fi + '" data-fmod="js disable if" data-field-idx="' + fi + '" value="' + esc(String(fmods['js disable if'] || '')) + '" placeholder="JavaScript expression">');
      out += row('fmod-exclude-' + fi, 'exclude', '<input class="form-control editor-form-control font-monospace" id="fmod-exclude-' + fi + '" data-fmod="exclude" data-field-idx="' + fi + '" value="' + esc(String(fmods.exclude || '')) + '">');
      out += pairRow(
        '<div><label class="editor-tiny" for="fmod-nota-' + fi + '">none of the above</label><input class="form-control editor-form-control" id="fmod-nota-' + fi + '" data-fmod="none of the above" data-field-idx="' + fi + '" value="' + esc(String(fmods['none of the above'] !== undefined ? fmods['none of the above'] : '')) + '"></div>',
        '<div><label class="editor-tiny" for="fmod-aota-' + fi + '">all of the above</label><input class="form-control editor-form-control" id="fmod-aota-' + fi + '" data-fmod="all of the above" data-field-idx="' + fi + '" value="' + esc(String(fmods['all of the above'] !== undefined ? fmods['all of the above'] : '')) + '"></div>'
      );
      out += row('fmod-shuffle-' + fi, 'shuffle', '<select class="form-select editor-form-control" id="fmod-shuffle-' + fi + '" data-fmod="shuffle" data-field-idx="' + fi + '"><option value="">(default)</option><option value="True"' + (fmods.shuffle ? ' selected' : '') + '>Yes</option></select>');
      out += row('fmod-disableothers-' + fi, 'disable others', '<input class="form-control editor-form-control font-monospace" id="fmod-disableothers-' + fi + '" data-fmod="disable others" data-field-idx="' + fi + '" value="' + esc(typeof fmods['disable others'] === 'boolean' ? String(fmods['disable others']) : String(fmods['disable others'] || '')) + '" placeholder="True or list of variables">');
      return out;
    }

    function renderHelpTab() {
      var out = '';
      out += row('fmod-help-' + fi, 'help', '<input class="form-control editor-form-control" id="fmod-help-' + fi + '" data-fmod="help" data-field-idx="' + fi + '" value="' + esc(String(fmods.help || '')) + '">');
      out += row('fmod-hint-' + fi, 'hint', '<input class="form-control editor-form-control" id="fmod-hint-' + fi + '" data-fmod="hint" data-field-idx="' + fi + '" value="' + esc(String(fmods.hint || '')) + '">');
      out += row('fmod-under-text-' + fi, 'under text', '<input class="form-control editor-form-control" id="fmod-under-text-' + fi + '" data-fmod="under text" data-field-idx="' + fi + '" value="' + esc(String(fmods["under text"] || '')) + '">');
      out += row('fmod-note-' + fi, 'note', '<input class="form-control editor-form-control" id="fmod-note-' + fi + '" data-fmod="note" data-field-idx="' + fi + '" value="' + esc(String(fmods.note || '')) + '">');
      return out;
    }

    function renderValidationTab() {
      var out = '';
      var isNumericType = ['number', 'integer', 'currency', 'range'].indexOf(dtype) !== -1;
      var isLengthType = ['text', 'area', 'raw', 'email', 'password', 'url', 'ml', 'mlarea', 'checkboxes', 'multiselect'].indexOf(dtype) !== -1;
      if (isNumericType || fmods.min !== undefined || fmods.max !== undefined) {
        out += pairRow(
          '<div><label class="editor-tiny" for="fmod-min-' + fi + '">min</label><input class="form-control editor-form-control font-monospace" id="fmod-min-' + fi + '" data-fmod="min" data-field-idx="' + fi + '" value="' + esc(String(fmods.min !== undefined ? fmods.min : '')) + '"></div>',
          '<div><label class="editor-tiny" for="fmod-max-' + fi + '">max</label><input class="form-control editor-form-control font-monospace" id="fmod-max-' + fi + '" data-fmod="max" data-field-idx="' + fi + '" value="' + esc(String(fmods.max !== undefined ? fmods.max : '')) + '"></div>'
        );
      } else {
        out += hiddenField('fmod-min');
        out += hiddenField('fmod-max');
      }
      if (dtype === 'range' || fmods.step !== undefined) {
        out += row('fmod-step-' + fi, 'step', '<input class="form-control editor-form-control font-monospace" id="fmod-step-' + fi + '" data-fmod="step" data-field-idx="' + fi + '" value="' + esc(String(fmods.step !== undefined ? fmods.step : '')) + '">');
      } else {
        out += hiddenField('fmod-step');
      }
      if (isLengthType || fmods.minlength !== undefined || fmods.maxlength !== undefined) {
        out += pairRow(
          '<div><label class="editor-tiny" for="fmod-minlength-' + fi + '">minlength</label><input class="form-control editor-form-control font-monospace" id="fmod-minlength-' + fi + '" data-fmod="minlength" data-field-idx="' + fi + '" value="' + esc(String(fmods.minlength || '')) + '"></div>',
          '<div><label class="editor-tiny" for="fmod-maxlength-' + fi + '">maxlength</label><input class="form-control editor-form-control font-monospace" id="fmod-maxlength-' + fi + '" data-fmod="maxlength" data-field-idx="' + fi + '" value="' + esc(String(fmods.maxlength || '')) + '"></div>'
        );
      } else {
        out += hiddenField('fmod-minlength');
        out += hiddenField('fmod-maxlength');
      }
      out += row('fmod-validate-' + fi, 'validate', '<input class="form-control editor-form-control font-monospace" id="fmod-validate-' + fi + '" data-fmod="validate" data-field-idx="' + fi + '" value="' + esc(String(fmods.validate || '')) + '" placeholder="function_name or lambda">');
      out += row('fmod-validation-code-' + fi, 'validation code', '<textarea class="form-control editor-form-control font-monospace" id="fmod-validation-code-' + fi + '" data-fmod="validation code" data-field-idx="' + fi + '" rows="2" placeholder="Python to validate">' + esc(String(fmods['validation code'] || '')) + '</textarea>');
      out += row('fmod-validation-messages-' + fi, 'validation messages', '<textarea class="form-control editor-form-control font-monospace" id="fmod-validation-messages-' + fi + '" data-fmod="validation messages" data-field-idx="' + fi + '" rows="2" placeholder="YAML dict of rule: message">' + esc(typeof fmods['validation messages'] === 'object' ? JSON.stringify(fmods['validation messages'], null, 2) : String(fmods['validation messages'] || '')) + '</textarea>');
      if (['file', 'files'].indexOf(dtype) !== -1 || fmods.accept !== undefined) {
        out += row('fmod-accept-' + fi, 'accept', '<input class="form-control editor-form-control" id="fmod-accept-' + fi + '" data-fmod="accept" data-field-idx="' + fi + '" value="' + esc(String(fmods.accept || '')) + '">');
      }
      return out;
    }

    function renderAppearanceTab() {
      var out = '';
      out += row('fmod-no-label-' + fi, 'no label', '<select class="form-select editor-form-control" id="fmod-no-label-' + fi + '" data-fmod="no label" data-field-idx="' + fi + '"><option value="">(default)</option><option value="True"' + (fmods['no label'] ? ' selected' : '') + '>Yes</option><option value="False"' + (fmods['no label'] === false || fmods['no label'] === 'False' ? ' selected' : '') + '>No</option></select>');
      out += row('fmod-css-class-' + fi, 'css class', '<input class="form-control editor-form-control" id="fmod-css-class-' + fi + '" data-fmod="css class" data-field-idx="' + fi + '" value="' + esc(String(fmods['css class'] || '')) + '">');
      out += row('fmod-label-above-' + fi, 'label above field', '<select class="form-select editor-form-control" id="fmod-label-above-' + fi + '" data-fmod="label above field" data-field-idx="' + fi + '"><option value="">(default)</option><option value="True"' + (fmods['label above field'] ? ' selected' : '') + '>Yes</option><option value="False"' + (fmods['label above field'] === false || fmods['label above field'] === 'False' ? ' selected' : '') + '>No</option></select>');
      out += row('fmod-floating-label-' + fi, 'floating label', '<select class="form-select editor-form-control" id="fmod-floating-label-' + fi + '" data-fmod="floating label" data-field-idx="' + fi + '"><option value="">(default)</option><option value="True"' + (fmods['floating label'] ? ' selected' : '') + '>Yes</option></select>');
      out += row('fmod-grid-' + fi, 'grid', '<input class="form-control editor-form-control font-monospace" id="fmod-grid-' + fi + '" data-fmod="grid" data-field-idx="' + fi + '" value="' + esc(typeof fmods.grid === 'object' ? JSON.stringify(fmods.grid) : String(fmods.grid || '')) + '" placeholder="1-12">');
      out += row('fmod-item-grid-' + fi, 'item grid', '<input class="form-control editor-form-control font-monospace" id="fmod-item-grid-' + fi + '" data-fmod="item grid" data-field-idx="' + fi + '" value="' + esc(typeof fmods['item grid'] === 'object' ? JSON.stringify(fmods['item grid']) : String(fmods['item grid'] || '')) + '" placeholder="1-12">');
      out += row('fmod-rows-' + fi, 'rows', '<input class="form-control editor-form-control font-monospace" id="fmod-rows-' + fi + '" data-fmod="rows" data-field-idx="' + fi + '" value="' + esc(String(fmods.rows || '')) + '" placeholder="textarea rows">');
      out += row('fmod-inline-width-' + fi, 'inline width', '<input class="form-control editor-form-control font-monospace" id="fmod-inline-width-' + fi + '" data-fmod="inline width" data-field-idx="' + fi + '" value="' + esc(String(fmods['inline width'] || '')) + '" placeholder="15em">');
      return out;
    }

    function renderMetadataTab() {
      var out = '';
      out += row('fmod-field-metadata-' + fi, 'field metadata', '<textarea class="form-control editor-form-control font-monospace" id="fmod-field-metadata-' + fi + '" data-fmod="field metadata" data-field-idx="' + fi + '" rows="4" placeholder="YAML">' + esc(typeof fmods['field metadata'] === 'object' ? JSON.stringify(fmods['field metadata'], null, 2) : String(fmods['field metadata'] || '')) + '</textarea>');
      return out;
    }

    function renderMoreTab() {
      var out = '';
      out += row('fmod-address-auto-' + fi, 'address autocomplete', '<textarea class="form-control editor-form-control font-monospace" id="fmod-address-auto-' + fi + '" data-fmod="address autocomplete" data-field-idx="' + fi + '" rows="3" placeholder="True or YAML">' + esc(String(fmods['address autocomplete'] || '')) + '</textarea>');
      out += row('fmod-maximum-image-size-' + fi, 'maximum image size', '<input class="form-control editor-form-control font-monospace" id="fmod-maximum-image-size-' + fi + '" data-fmod="maximum image size" data-field-idx="' + fi + '" value="' + esc(String(fmods['maximum image size'] || '')) + '">');
      out += row('fmod-image-upload-type-' + fi, 'image upload type', '<input class="form-control editor-form-control" id="fmod-image-upload-type-' + fi + '" data-fmod="image upload type" data-field-idx="' + fi + '" value="' + esc(String(fmods['image upload type'] || '')) + '" placeholder="jpeg">');
      out += row('fmod-persistent-' + fi, 'persistent', '<select class="form-select editor-form-control" id="fmod-persistent-' + fi + '" data-fmod="persistent" data-field-idx="' + fi + '"><option value="">(default)</option><option value="True"' + (fmods.persistent ? ' selected' : '') + '>Yes</option><option value="False"' + (fmods.persistent === false || fmods.persistent === 'False' ? ' selected' : '') + '>No</option></select>');
      out += row('fmod-private-' + fi, 'private', '<select class="form-select editor-form-control" id="fmod-private-' + fi + '" data-fmod="private" data-field-idx="' + fi + '"><option value="">(default)</option><option value="True"' + (fmods.private ? ' selected' : '') + '>Yes</option><option value="False"' + (fmods.private === false || fmods.private === 'False' ? ' selected' : '') + '>No</option></select>');
      out += row('fmod-allow-users-' + fi, 'allow users', '<input class="form-control editor-form-control font-monospace" id="fmod-allow-users-' + fi + '" data-fmod="allow users" data-field-idx="' + fi + '" value="' + esc(String(fmods['allow users'] || '')) + '" placeholder="emails or user ids">');
      out += row('fmod-allow-privileges-' + fi, 'allow privileges', '<input class="form-control editor-form-control font-monospace" id="fmod-allow-privileges-' + fi + '" data-fmod="allow privileges" data-field-idx="' + fi + '" value="' + esc(String(fmods['allow privileges'] || '')) + '" placeholder="developer, user">');
      out += row('fmod-file-css-class-' + fi, 'file css class', '<input class="form-control editor-form-control" id="fmod-file-css-class-' + fi + '" data-fmod="file css class" data-field-idx="' + fi + '" value="' + esc(String(fmods['file css class'] || '')) + '">');
      out += row('fmod-object-labeler-' + fi, 'object labeler', '<input class="form-control editor-form-control font-monospace" id="fmod-object-labeler-' + fi + '" data-fmod="object labeler" data-field-idx="' + fi + '" value="' + esc(String(fmods['object labeler'] || '')) + '" placeholder="lambda y: y.name">');
      return out;
    }

    var html = '<div class="editor-field-mods-panel' + (isStandalone ? ' editor-field-mods-panel-standalone' : '') + '" data-field-idx="' + fi + '"' + (isOpen ? '' : ' hidden') + '>';
    html += '<ul class="nav nav-tabs nav-tabs-sm editor-field-settings-tabs" role="tablist">';
    availableTabs.forEach(function (tabKey) {
      html += '<li class="nav-item" role="presentation"><button type="button" class="nav-link ' + (activeTab === tabKey ? 'active' : '') + '" data-field-settings-tab="' + tabKey + '" data-field-idx="' + fi + '">' + esc(tabLabels[tabKey] || tabKey) + '</button></li>';
    });
    html += '</ul>';
    html += '<div class="editor-field-settings-tabcontent">';

    function pane(tabKey, bodyHtml) {
      return '<div class="editor-field-settings-tabpane" data-field-settings-pane="' + tabKey + '"' + (activeTab === tabKey ? '' : ' hidden') + '>' + bodyHtml + '</div>';
    }

    if (isStandalone) {
      html += pane('logic', renderLogicTab());
    } else {
      html += pane('basic', renderBasicTab());
      html += pane('logic', renderLogicTab());
      html += pane('help', renderHelpTab());
      html += pane('validation', renderValidationTab());
      html += pane('appearance', renderAppearanceTab());
      html += pane('metadata', renderMetadataTab());
      html += pane('more', renderMoreTab());
    }

    html += '</div></div>';
    return html;
  }

  // --- Advanced panel (shared across block types) ---
  function renderAdvancedPanel(block) {
    var data = block.data || {};
    var ifEnabled = Boolean(data['if'] || data._editor_if_enabled);
    var mandatoryEnabled = Boolean(data.mandatory);
    var showMore = state.advancedShowMore;
    var forceOpen = block && block.type === 'question' && state.questionBlockTab === 'options';
    var html = '';
    html += '<div class="editor-card" style="margin-top:12px">';
    if (!forceOpen) {
      html += '<button class="editor-advanced-toggle" id="toggle-advanced"><i class="fa-solid fa-chevron-down editor-collapse-icon' + (state.advancedOpen ? '' : ' collapsed') + '" aria-hidden="true"></i> Advanced options</button>';
    }
    if (forceOpen || state.advancedOpen) {
      html += '<div class="editor-advanced-body">';

      // Block ID (editable) — for non-question blocks; question blocks show it in the main card
      if (block.type !== 'question') {
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-id">Block ID</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-id" value="' + esc(block.id) + '"></div>';
      }

      // If condition
      var ifVal = data['if'] || '';
      html += '<div class="editor-form-group editor-form-group-compact">';
      html += '<div class="form-check form-switch editor-inline-toggle">';
      html += '<input class="form-check-input" type="checkbox" id="adv-enable-if"' + (ifEnabled ? ' checked' : '') + '>';
      html += '<label class="form-check-label" for="adv-enable-if">Condition (if)</label>';
      html += '</div>';
      if (ifEnabled) {
        html += renderSymbolDatalist('adv-if-variable-list', 'variable', 120);
        html += '<input class="form-control editor-form-control font-monospace mt-2" id="adv-if" data-symbol-role="variable" list="adv-if-variable-list" value="' + esc(String(ifVal)) + '" placeholder="Python expression">';
      }
      html += '</div>';

      // Continue button field/label — always visible
      html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-continue-field">Continue button field</label>';
      html += '<input class="form-control editor-form-control font-monospace" id="adv-continue-field" data-symbol-role="variable" value="' + esc(String(data['continue button field'] || '')) + '"></div>';

      html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-continue-label">Continue button label</label>';
      html += '<input class="form-control editor-form-control" id="adv-continue-label" value="' + esc(String(data['continue button label'] || '')) + '"></div>';

      // Sets/only sets — always visible
      var setsVal = data.sets || data['only sets'] || '';
      if (Array.isArray(setsVal)) setsVal = setsVal.join(', ');
      html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-sets">' + (data['only sets'] ? 'Only sets' : 'Sets') + ' <span class="text-muted">(comma-separated variables)</span></label>';
      html += '<input class="form-control editor-form-control font-monospace" id="adv-sets" data-sets-key="' + (data['only sets'] ? 'only sets' : 'sets') + '" value="' + esc(String(setsVal)) + '"></div>';

      // Show more toggle
      html += '<button type="button" class="btn btn-link btn-sm p-0 mt-1 mb-1" id="adv-show-more" style="font-size:12px"><i class="fa-solid ' + (showMore ? 'fa-chevron-up' : 'fa-chevron-down') + ' me-1" aria-hidden="true" style="font-size:10px"></i>' + (showMore ? 'Show fewer options' : 'Show more options') + '</button>';

      if (showMore) {
        // Need
        var needVal = data.need || '';
        if (Array.isArray(needVal)) needVal = needVal.join(', ');
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-need">Need <span class="text-muted">(blocks)</span></label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-need" value="' + esc(String(needVal)) + '"></div>';

        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-event">Event <span class="text-muted">(event name)</span></label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-event" value="' + esc(String(data.event || '')) + '"></div>';

        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-generic-object">Generic object</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-generic-object" value="' + esc(String(data['generic object'] || '')) + '"></div>';

        // Continue button color
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-continue-color">Continue button color</label>';
        html += '<select class="form-select editor-form-control" id="adv-continue-color">';
        ['', 'primary', 'secondary', 'success', 'danger', 'warning', 'info', 'light', 'dark'].forEach(function (c) {
          html += '<option value="' + c + '"' + (data['continue button color'] === c ? ' selected' : '') + '>' + (c || '(default)') + '</option>';
        });
        html += '</select></div>';

        // Hide / disable continue button
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-hide-continue">Hide continue button</label>';
        html += '<select class="form-select editor-form-control" id="adv-hide-continue">';
        html += '<option value=""' + (!data['hide continue button'] ? ' selected' : '') + '>(default)</option>';
        html += '<option value="True"' + (data['hide continue button'] ? ' selected' : '') + '>Yes</option>';
        html += '</select></div>';

        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-disable-continue">Disable continue button</label>';
        html += '<select class="form-select editor-form-control" id="adv-disable-continue">';
        html += '<option value=""' + (!data['disable continue button'] ? ' selected' : '') + '>(default)</option>';
        html += '<option value="True"' + (data['disable continue button'] ? ' selected' : '') + '>Yes</option>';
        html += '</select></div>';

        // Prevent going back / back button
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-prevent-back">Prevent going back</label>';
        html += '<select class="form-select editor-form-control" id="adv-prevent-back">';
        html += '<option value=""' + (!data['prevent going back'] ? ' selected' : '') + '>(default)</option>';
        html += '<option value="True"' + (data['prevent going back'] ? ' selected' : '') + '>Yes</option>';
        html += '</select></div>';

        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-back-button">Back button</label>';
        html += '<select class="form-select editor-form-control" id="adv-back-button">';
        html += '<option value="">(default)</option>';
        html += '<option value="True"' + (data['back button'] === true || data['back button'] === 'True' ? ' selected' : '') + '>True</option>';
        html += '<option value="False"' + (data['back button'] === false || data['back button'] === 'False' ? ' selected' : '') + '>False</option>';
        html += '</select></div>';

        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-back-button-label">Back button label</label>';
        html += '<input class="form-control editor-form-control" id="adv-back-button-label" value="' + esc(String(data['back button label'] || '')) + '"></div>';

        // Progress / section
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-progress">Progress <span class="text-muted">(0-100)</span></label>';
        html += '<input class="form-control editor-form-control" id="adv-progress" value="' + esc(String(data.progress !== undefined ? data.progress : '')) + '" placeholder="e.g. 50"></div>';

        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-section">Section</label>';
        html += '<input class="form-control editor-form-control" id="adv-section" value="' + esc(String(data.section || '')) + '"></div>';

        // Help (question level)
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-help">Help text (question level)</label>';
        html += '<textarea class="form-control editor-form-control" id="adv-help" rows="2">' + esc(String(data.help || '')) + '</textarea></div>';

        // Audio / video
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-audio">Audio URL/variable</label>';
        html += '<input class="form-control editor-form-control" id="adv-audio" value="' + esc(String(data.audio || '')) + '"></div>';

        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-video">Video URL/variable</label>';
        html += '<input class="form-control editor-form-control" id="adv-video" value="' + esc(String(data.video || '')) + '"></div>';

        // Decoration
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-decoration">Decoration</label>';
        html += '<input class="form-control editor-form-control" id="adv-decoration" value="' + esc(String(data.decoration || '')) + '"></div>';

        // Script / CSS
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-script">Script (inline JS)</label>';
        html += '<textarea class="form-control editor-form-control font-monospace" id="adv-script" rows="2">' + esc(String(data.script || '')) + '</textarea></div>';

        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-css">CSS (inline)</label>';
        html += '<textarea class="form-control editor-form-control font-monospace" id="adv-css" rows="2">' + esc(String(data.css || '')) + '</textarea></div>';

        // Language
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-language">Language</label>';
        html += '<input class="form-control editor-form-control" id="adv-language" value="' + esc(String(data.language || '')) + '" placeholder="e.g. es"></div>';

        // Allowed to set
        var allowedToSetVal = data['allowed to set'] || '';
        if (Array.isArray(allowedToSetVal)) allowedToSetVal = allowedToSetVal.join(', ');
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-allowed-to-set">Allowed to set</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-allowed-to-set" value="' + esc(String(allowedToSetVal)) + '"></div>';

        // Depends on / undefine / reconsider
        var dependsOnVal = data['depends on'] || '';
        if (Array.isArray(dependsOnVal)) dependsOnVal = dependsOnVal.join(', ');
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-depends-on">Depends on</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-depends-on" value="' + esc(String(dependsOnVal)) + '"></div>';

        var undefineVal = data.undefine || '';
        if (Array.isArray(undefineVal)) undefineVal = undefineVal.join(', ');
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-undefine">Undefine</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-undefine" value="' + esc(String(undefineVal)) + '"></div>';

        var reconsiderVal = data.reconsider || '';
        if (Array.isArray(reconsiderVal)) reconsiderVal = reconsiderVal.join(', ');
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-reconsider">Reconsider</label>';
        html += '<input class="form-control editor-form-control font-monospace" id="adv-reconsider" value="' + esc(String(reconsiderVal)) + '"></div>';

        // Scan for variables
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-scan-vars">Scan for variables</label>';
        html += '<select class="form-select editor-form-control" id="adv-scan-vars">';
        html += '<option value="">(default)</option>';
        html += '<option value="True"' + (data['scan for variables'] === true || data['scan for variables'] === 'True' ? ' selected' : '') + '>True</option>';
        html += '<option value="False"' + (data['scan for variables'] === false || data['scan for variables'] === 'False' ? ' selected' : '') + '>False</option>';
        html += '</select></div>';

        // Validation code
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-validation-code">Validation code (Python)</label>';
        html += '<textarea class="form-control editor-form-control font-monospace" id="adv-validation-code" rows="2">' + esc(String(data['validation code'] || '')) + '</textarea></div>';

        // Resume button label (for tabular)
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-resume-button-label">Resume button label</label>';
        html += '<input class="form-control editor-form-control" id="adv-resume-button-label" value="' + esc(String(data['resume button label'] || '')) + '"></div>';

        // Reload
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-reload">Reload</label>';
        html += '<select class="form-select editor-form-control" id="adv-reload">';
        html += '<option value="">(default)</option>';
        html += '<option value="True"' + (data.reload === true || data.reload === 'True' ? ' selected' : '') + '>True</option>';
        html += '</select></div>';

        // Role
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-role">Role</label>';
        html += '<input class="form-control editor-form-control" id="adv-role" value="' + esc(String(data.role || '')) + '"></div>';

        // GA / Segment IDs
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-ga-id">GA ID</label>';
        html += '<input class="form-control editor-form-control" id="adv-ga-id" value="' + esc(String(data['ga id'] || '')) + '"></div>';

        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-segment-id">Segment ID</label>';
        html += '<input class="form-control editor-form-control" id="adv-segment-id" value="' + esc(String(data['segment id'] || '')) + '"></div>';

        // Comment
        html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-comment">Comment</label>';
        html += '<textarea class="form-control editor-form-control" id="adv-comment" rows="2">' + esc(String(data.comment || '')) + '</textarea></div>';

        // Variable (read-only if present)
        if (block.variable) {
          html += '<div class="editor-form-group"><label class="editor-tiny" for="adv-variable">Variable (read-only)</label>';
          html += '<input class="form-control editor-form-control font-monospace" id="adv-variable" value="' + esc(block.variable) + '" readonly></div>';
        }
      } // end showMore

      html += '</div>';
    }
    html += '</div>';
    return html;
  }

  // -------------------------------------------------------------------------
  // Full YAML editor (Monaco)
  // -------------------------------------------------------------------------
  function _stashFullYamlContent() {
    if (state.canvasMode !== 'full-yaml') return;
    var content = getMonacoValue('full-yaml-monaco');
    if (content) {
      state.fullYamlStash[state.fullYamlTab] = content;
    }
  }

  function renderFullYaml() {
    var html = '<div class="editor-full-yaml-shell">';
    html += '<div class="editor-full-yaml-header">';
    html += '<div><h2 style="font-weight:700;font-size:18px;margin:0">Full YAML</h2></div>';
    html += '<div class="d-flex gap-2">';
    var backLabel = state._prevCanvasMode === 'order-builder' ? '\u2190 Interview Order' : 'Back to blocks';
    html += '<button class="btn btn-sm btn-outline-secondary" id="back-to-question">' + backLabel + '</button>';
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

    // Use stashed content if available, otherwise build from state
    var content = '';
    if (state.fullYamlStash[state.fullYamlTab]) {
      content = state.fullYamlStash[state.fullYamlTab];
    } else if (state.fullYamlTab === 'full') {
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
    var indentPx = depth * 20;
    var html = '<div class="editor-order-insert" style="--order-depth:' + depth + '; padding-left:' + indentPx + 'px">';
    html += '<button type="button" class="editor-order-insert-btn" data-open-add-step="true" data-parent-step-id="' + esc(parentStepId || '') + '" data-step-branch="' + esc(branch || 'then') + '" data-insert-index="' + index + '" title="Add step">';
    html += '<span class="editor-order-insert-icon"><i class="fa-solid fa-plus" aria-hidden="true"></i></span>';
    html += '<span>Add</span>';
    html += '</button>';
    html += '</div>';
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
    stepList.forEach(function (step, index) {
      var presentation = getOrderStepPresentation(step);
      var isCollapsed = Boolean(state.orderCollapsed[step.id]);
      var hasChildren = Array.isArray(step.children) && step.children.length > 0;
      var hasElse = Boolean(step.has_else);
      var kindBadge = getOrderStepBadge(step);
      var badgeCss = getOrderBadgeCssClass(step);
      html += '<div class="editor-order-step-shell" style="--order-depth:' + depth + '">';
      html += '<div class="editor-order-step' + (step.kind === 'condition' ? ' editor-order-step-condition' : '') + (_lastInsertedOrderStepId === step.id ? ' editor-order-step-new' : '') + '" data-step-id="' + esc(step.id) + '">';
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
        html += '<span class="editor-order-badge ' + badgeCss + '" title="' + esc(step.label || step.kind) + '">' + esc(kindBadge) + '</span>';
      }
      html += '<span class="editor-order-title" data-editable="true" data-step-id="' + esc(step.id) + '"' + (presentation.tooltip ? ' title="' + esc(presentation.tooltip) + '"' : '') + '>' + esc(presentation.heading) + '</span>';
      if (presentation.detail) {
        html += '<span class="editor-order-detail">' + esc(presentation.detail) + '</span>';
      }
      html += '</div>';
      html += '<div class="editor-order-step-actions">';
      // Kebab menu consolidating all actions
      html += '<div class="dropdown">';
      html += '<button type="button" class="editor-kebab-btn" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-display="dynamic" aria-expanded="false" title="Actions"><i class="fa-solid fa-ellipsis-vertical" aria-hidden="true"></i><span class="visually-hidden">Actions</span></button>';
      html += '<ul class="dropdown-menu dropdown-menu-end">';
      html += '<li><button class="dropdown-item" type="button" data-step-action="edit" data-step-id="' + esc(step.id) + '"><i class="fa-solid fa-pen-to-square me-2" aria-hidden="true"></i>Edit</button></li>';
      if (step.kind === 'condition' && !hasElse) {
        html += '<li><button class="dropdown-item" type="button" data-step-action="add-else" data-step-id="' + esc(step.id) + '"><i class="fa-solid fa-code-branch me-2" aria-hidden="true"></i>Add else branch</button></li>';
      }
      var hasBlockRef = (step.kind === 'screen' || step.kind === 'gather') && !!step.invoke;
      if (hasBlockRef) {
        var blockRef = findBlockByInvoke(step);
        if (blockRef) {
          html += '<li><button class="dropdown-item" type="button" data-step-action="go-to-block" data-step-id="' + esc(step.id) + '"><i class="fa-solid fa-arrow-up-right-from-square me-2" aria-hidden="true"></i>Go to block</button></li>';
        } else {
          var inCatalog = step.invoke && state.symbolCatalog && state.symbolCatalog.all.indexOf(step.invoke) !== -1;
          html += '<li><button class="dropdown-item" type="button" data-step-action="go-to-block" data-step-id="' + esc(step.id) + '">' + (inCatalog ? '<i class="fa-solid fa-file-import me-2"></i>Defined in included file' : '<i class="fa-solid fa-arrow-up-right-from-square me-2" aria-hidden="true"></i>Go to block') + '</button></li>';
        }
      }
      html += '<li><hr class="dropdown-divider"></li>';
      html += '<li><button class="dropdown-item text-danger" type="button" data-step-action="remove" data-step-id="' + esc(step.id) + '"><i class="fa-solid fa-trash-can me-2" aria-hidden="true"></i>Remove</button></li>';
      html += '</ul></div>';
      html += '</div>';
      html += '</div>';
      // Inline edit row shown when this step is being edited
      if (_inlineEditStepId === step.id) {
        html += renderInlineEditRow(step);
      }
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
    html += '<span class="editor-order-actions-hint">Use + to add steps</span>';
    html += '</div></div>';

    html += '<div class="editor-card-body"><div class="editor-order-timeline" id="order-sortable-list">';
    if (state.orderBuilderLoading) {
      html += '<div class="editor-info-box mb-2"><div class="d-flex align-items-center gap-2"><div class="spinner-border spinner-border-sm text-primary" role="status" aria-hidden="true"></div><div>Loading interview order...</div></div></div>';
    }
    html += renderOrderStepTree(state.orderSteps, 0, '', 'then');
    if (state.orderSteps.length === 0 && !state.orderBuilderLoading) {
      if (!activeOrderBlock) {
        html += '<div class="editor-info-box mb-2">';
        html += '<strong>No interview order block found.</strong> To use the order builder, add a mandatory code block with <code>id: interview_order</code> to your interview. ';
        html += 'For example:';
        html += '<pre class="mt-2 mb-0" style="font-size:12px">---\nid: interview_order\nmandatory: True\ncode: |\n  # Steps will go here\n  interview_order = True</pre>';
        html += '</div>';
      }
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
          // Use draggable-only indices so that interspersed insert-rows don't
          // offset the positions. Fall back to oldIndex/newIndex for older
          // versions of SortableJS that don't expose the draggable variants.
          var fromIdx = (evt.oldDraggableIndex != null) ? evt.oldDraggableIndex : evt.oldIndex;
          var toIdx   = (evt.newDraggableIndex != null) ? evt.newDraggableIndex : evt.newIndex;
          if (fromIdx < 0 || fromIdx >= state.orderSteps.length) return;
          var moved = state.orderSteps.splice(fromIdx, 1)[0];
          state.orderSteps.splice(toIdx, 0, moved);
          syncActiveOrderStepMap();
          markOrderDirty();
          renderOrderBuilder();
        }
      });
    }

  }

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
    html += '<div class="form-check form-switch m-0">';
    html += '<input class="form-check-input" type="checkbox" id="new-project-use-llm-assist" checked>';
    html += '<label class="form-check-label editor-tiny" for="new-project-use-llm-assist">Use AI assistance for drafting</label>';
    html += '<div class="text-muted small mt-1">If enabled, Weaver will use your context and reference page to refine labels and screen grouping.</div>';
    html += '</div>';
    html += '<div><label class="editor-tiny" for="new-project-help-page-url">Reference page URL (optional)</label>';
    html += '<input class="form-control form-control-sm mt-1" id="new-project-help-page-url" type="url" placeholder="https://example.com/help"></div>';
    html += '<div><label class="editor-tiny" for="new-project-help-page-title">Reference page title (optional)</label>';
    html += '<input class="form-control form-control-sm mt-1" id="new-project-help-page-title" placeholder="Page title shown to users"></div>';
    html += '<div><label class="editor-tiny" for="new-project-notes">Extra context for Weaver (optional)</label>';
    html += '<textarea class="form-control form-control-sm mt-1" id="new-project-notes" rows="4" placeholder="E.g. desired title, jurisdiction, special instructions, local context"></textarea>';
    html += '<div class="text-muted small mt-1">This text is passed through as drafting context and works whether or not AI is enabled.</div></div>';
    html += '</div></div></div>';

    html += '<div class="editor-upload-modal d-none" id="upload-progress-modal" role="dialog" aria-modal="true" aria-labelledby="upload-progress-title">';
    html += '<div class="editor-upload-modal-backdrop"></div>';
    html += '<div class="editor-upload-modal-panel">';
    html += '<div class="d-flex justify-content-between align-items-start gap-3">';
    html += '<div><div class="editor-tiny">Creating project</div><h3 class="editor-upload-modal-title" id="upload-progress-title">Generating from uploaded document</h3></div>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary d-none" id="upload-progress-close">Close</button>';
    html += '</div>';
    html += '<div class="editor-upload-modal-body">';
    html += '<div class="editor-upload-modal-running" id="upload-progress-running">';
    html += '<div class="spinner-border text-primary" role="status" aria-hidden="true"></div>';
    html += '<div><div class="fw-semibold">Creating project...</div><div class="text-muted small mt-1" id="upload-progress-msg">This may take a minute or two. Please wait.</div></div>';
    html += '</div>';
    html += '<div class="editor-upload-modal-error d-none" id="upload-progress-error"></div>';
    html += '</div></div></div>';

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

  function _getUploadProgressModalNodes() {
    return {
      modal: document.getElementById('upload-progress-modal'),
      running: document.getElementById('upload-progress-running'),
      error: document.getElementById('upload-progress-error'),
      message: document.getElementById('upload-progress-msg'),
      title: document.getElementById('upload-progress-title'),
      closeButton: document.getElementById('upload-progress-close'),
      createButton: document.getElementById('create-project-btn'),
    };
  }

  function _showUploadProgressModal(message) {
    var nodes = _getUploadProgressModalNodes();
    if (!nodes.modal) return;
    if (nodes.title) nodes.title.textContent = 'Generating from uploaded document';
    if (nodes.running) nodes.running.classList.remove('d-none');
    if (nodes.error) {
      nodes.error.classList.add('d-none');
      nodes.error.textContent = '';
    }
    if (nodes.closeButton) nodes.closeButton.classList.add('d-none');
    if (nodes.message) nodes.message.textContent = message || 'This may take a minute or two. Please wait.';
    if (nodes.createButton) nodes.createButton.disabled = true;
    nodes.modal.classList.remove('d-none');
  }

  function _setUploadProgressMessage(message) {
    var nodes = _getUploadProgressModalNodes();
    if (nodes.message) nodes.message.textContent = message || 'This may take a minute or two. Please wait.';
  }

  function _hideUploadProgressModal() {
    var nodes = _getUploadProgressModalNodes();
    if (!nodes.modal) return;
    nodes.modal.classList.add('d-none');
    if (nodes.running) nodes.running.classList.remove('d-none');
    if (nodes.error) {
      nodes.error.classList.add('d-none');
      nodes.error.textContent = '';
    }
    if (nodes.closeButton) nodes.closeButton.classList.add('d-none');
    if (nodes.message) nodes.message.textContent = 'This may take a minute or two. Please wait.';
    if (nodes.createButton) nodes.createButton.disabled = false;
  }

  function _showUploadError(message) {
    var nodes = _getUploadProgressModalNodes();
    if (!nodes.modal) return;
    nodes.modal.classList.remove('d-none');
    if (nodes.running) nodes.running.classList.add('d-none');
    if (nodes.error) {
      nodes.error.textContent = message || 'Unknown error';
      nodes.error.classList.remove('d-none');
    }
    if (nodes.title) nodes.title.textContent = 'Unable to create project';
    if (nodes.closeButton) nodes.closeButton.classList.remove('d-none');
    if (nodes.createButton) nodes.createButton.disabled = false;
  }

  function _pollNewProjectJob(jobUrl, projectName) {
    var attempts = 0;

    return new Promise(function (resolve, reject) {
      function tick() {
        attempts += 1;
        fetchResponsePayload(jobUrl, { credentials: 'same-origin' })
          .then(function (response) {
            var payload = response.body || {};
            if (!response.ok) {
              reject(new Error(_fetchErrorMessage(response)));
              return;
            }
            var jobData = payload.data || {};
            var jobStatus = String(payload.status || jobData.status || '').toLowerCase();
            if (jobStatus === 'failed') {
              reject(new Error(_fetchErrorMessage(response)));
              return;
            }
            if (jobStatus === 'succeeded') {
              resolve(payload);
              return;
            }
            _setUploadProgressMessage(jobData.message || ('Creating project "' + (projectName || 'new project') + '"...'));
            if (attempts >= UPLOAD_JOB_MAX_ATTEMPTS) {
              reject(new Error('Timed out waiting for the background job to finish.'));
              return;
            }
            setTimeout(tick, UPLOAD_JOB_POLL_INTERVAL_MS);
          })
          .catch(function (err) {
            reject(err);
          });
      }

      tick();
    });
  }

  function _showSuccessBanner(message) {
    var banner = document.createElement('div');
    banner.className = 'alert alert-success alert-dismissible fade show position-fixed';
    banner.style.cssText = 'top:1rem;left:50%;transform:translateX(-50%);z-index:9999;min-width:300px;max-width:500px;';
    banner.innerHTML = '<span>' + message + '</span><button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>';
    document.body.appendChild(banner);
    setTimeout(function () { if (banner.parentNode) banner.parentNode.removeChild(banner); }, 5000);
  }

  // -------------------------------------------------------------------------
  // Secondary view placeholder
  // -------------------------------------------------------------------------
  function sectionTitle(view) {
    if (view === 'templates') return 'Templates';
    if (view === 'modules') return 'Modules';
    if (view === 'static') return 'Static';
    if (view === 'data') return 'Data Sources';
    return 'Files';
  }

  function defaultNewFilename(view) {
    if (view === 'modules') return 'new_module.py';
    if (view === 'static') return 'new_static.css';
    if (view === 'data') return 'new_data.yml';
    return 'new_template.txt';
  }

  function renderSectionPreview(fileMeta) {
    if (!fileMeta) {
      return '<div class="editor-card"><div class="editor-card-body text-muted">No file selected.</div></div>';
    }
    var rawUrl = API + '/api/section-file/raw?project=' + encodeURIComponent(state.project) + '&section=' + encodeURIComponent(getSectionFromView(state.currentView)) + '&filename=' + encodeURIComponent(fileMeta.filename);
    if (fileMeta.preview_kind === 'pdf') {
      return '<div class="editor-card"><div class="editor-card-body"><iframe class="editor-file-preview-frame" src="' + esc(rawUrl) + '" title="PDF preview"></iframe></div></div>';
    }
    if (fileMeta.preview_kind === 'image') {
      return '<div class="editor-card"><div class="editor-card-body"><img class="editor-image-preview" src="' + esc(rawUrl) + '" alt="Preview of ' + esc(fileMeta.filename) + '"></div></div>';
    }
    if (fileMeta.preview_kind === 'docx') {
      return '<div class="editor-card"><div class="editor-card-body"><div id="docx-preview-container" class="editor-docx-preview text-muted">Loading DOCX preview&hellip;</div></div></div>';
    }
    return '<div class="editor-card"><div class="editor-card-body"><p class="text-muted mb-2">This file is not previewable inline.</p><a class="btn btn-sm btn-outline-secondary" href="' + esc(rawUrl) + '" target="_blank" rel="noopener noreferrer">Open file</a></div></div>';
  }

  function loadDocxPreview(view, filename) {
    var container = document.getElementById('docx-preview-container');
    if (!container) return;
    apiGet('/api/section-file/docx-preview?project=' + encodeURIComponent(state.project) + '&section=' + encodeURIComponent(getSectionFromView(view)) + '&filename=' + encodeURIComponent(filename))
      .then(function (res) {
        if (!res.success || !res.data || !res.data.html) {
          container.innerHTML = '<div class="text-danger">Unable to load DOCX preview.</div>';
          return;
        }
        container.innerHTML = res.data.html;
      })
      .catch(function () {
        container.innerHTML = '<div class="text-danger">Unable to load DOCX preview.</div>';
      });
  }

  function renderSecondaryView() {
    var view = state.currentView;
    var section = getSectionFromView(view);
    if (!section || !state.project) {
      canvasContent.innerHTML = '<div class="editor-secondary-center"><div class="editor-secondary-card"><h2 style="font-weight:700">' + esc(sectionTitle(view)) + '</h2><p class="text-muted mt-2">Select a project to manage files in this section.</p></div></div>';
      return;
    }

    var fileMeta = getSelectedSectionFileMeta(view);
    if (fileMeta && state.sectionSelectedFile[view] !== fileMeta.filename) {
      state.sectionSelectedFile[view] = fileMeta.filename;
    }

    var html = '';
    html += '<div class="editor-full-yaml-shell">';
    html += '<div class="editor-full-yaml-header">';
    html += '<div><h2 style="font-weight:700;font-size:18px;margin:0">' + esc(sectionTitle(view)) + (fileMeta ? ' — ' + esc(fileMeta.filename) : '') + '</h2></div>';
    html += '<div class="d-flex gap-2 flex-wrap">';
    if (fileMeta) {
      var sectionRawUrl = API + '/api/section-file/raw?project=' + encodeURIComponent(state.project) + '&section=' + encodeURIComponent(section) + '&filename=' + encodeURIComponent(fileMeta.filename);
      html += '<a class="btn btn-sm btn-outline-secondary" href="' + esc(sectionRawUrl) + '" download="' + esc(fileMeta.filename) + '"><i class="fa-solid fa-download me-1" aria-hidden="true"></i>Download</a>';
    }
    html += '</div></div>';
    html += '<input type="file" id="section-upload-input" style="display:none" multiple>';

    if (!fileMeta) {
      html += '<div class="editor-card"><div class="editor-card-body text-muted">No files in this section yet. Use Upload or + New.</div></div>';
      html += '</div>';
      canvasContent.innerHTML = html;
      return;
    }

    var editable = Boolean(fileMeta.editable);
    if (editable) {
      html += '<div class="editor-card"><div class="editor-card-body">';
      html += '<div class="d-flex justify-content-between align-items-center mb-2"><div class="editor-tiny">Editing ' + esc(fileMeta.filename) + '</div><button class="btn btn-sm btn-primary" id="save-section-file"' + (!state.sectionDirty ? ' disabled' : '') + '>Save</button></div>';
      html += '<div class="editor-monaco-container" id="section-file-monaco" style="height:620px"></div>';
      html += '</div></div>';
    } else {
      html += renderSectionPreview(fileMeta);
    }

    html += '</div>';
    canvasContent.innerHTML = html;

    if (editable) {
      apiGet('/api/section-file?project=' + encodeURIComponent(state.project) + '&section=' + encodeURIComponent(section) + '&filename=' + encodeURIComponent(fileMeta.filename))
        .then(function (res) {
          var text = (res && res.success && res.data) ? String(res.data.content || '') : '';
          var language = 'plaintext';
          var lowerName = String(fileMeta.filename || '').toLowerCase();
          if (lowerName.endsWith('.py')) language = 'python';
          else if (lowerName.endsWith('.mako')) language = 'mako';
          else if (lowerName.endsWith('.css') || lowerName.endsWith('.scss') || lowerName.endsWith('.less')) language = 'css';
          else if (lowerName.endsWith('.html') || lowerName.endsWith('.htm')) language = 'html';
          else if (lowerName.endsWith('.xml') || lowerName.endsWith('.svg')) language = 'xml';
          else if (lowerName.endsWith('.json')) language = 'json';
          else if (lowerName.endsWith('.yaml') || lowerName.endsWith('.yml')) language = 'yaml';
          else if (lowerName.endsWith('.csv')) language = 'plaintext';
          initMonaco(function () {
            createMonacoEditor('section-file-monaco', text, language, {
              onChange: function () {
                state.sectionDirty = true;
                var saveBtn = document.getElementById('save-section-file');
                if (saveBtn) saveBtn.disabled = false;
              }
            });
            state.sectionDirty = false;
          });
        });
    } else if (fileMeta.preview_kind === 'docx') {
      loadDocxPreview(view, fileMeta.filename);
    }
  }

  // -------------------------------------------------------------------------
  // Event delegation
  // -------------------------------------------------------------------------
  document.addEventListener('mousedown', function (e) {
    var target = e.target;
    // Keep the input focused when choosing an item, while still allowing
    // native scrolling and scrollbar dragging inside the suggestion list.
    if (target.closest('.editor-symbol-typeahead-item')) {
      e.preventDefault();
    }
    // Slow-click-to-edit: on mousedown on an editable title, start a timer.
    // If mouseup happens >300ms later without drag, trigger inline edit.
    var editableTitle = target.closest('.editor-order-title[data-editable]');
    if (editableTitle) {
      var stepId = editableTitle.getAttribute('data-step-id');
      if (_slowClickTimer) { clearTimeout(_slowClickTimer); _slowClickTimer = null; }
      _slowClickStepId = stepId;
    } else {
      _slowClickStepId = null;
    }
  });

  document.addEventListener('mouseup', function (e) {
    if (!_slowClickStepId) return;
    var target = e.target;
    var editableTitle = target.closest('.editor-order-title[data-editable]');
    if (!editableTitle || editableTitle.getAttribute('data-step-id') !== _slowClickStepId) {
      _slowClickStepId = null;
      return;
    }
    var capturedId = _slowClickStepId;
    _slowClickStepId = null;
    // Use a short delay to distinguish slow click from fast click (which may toggle selection)
    if (_slowClickTimer) clearTimeout(_slowClickTimer);
    _slowClickTimer = setTimeout(function () {
      _slowClickTimer = null;
      var stepRecord = findStepRecord(state.orderSteps, capturedId, null);
      if (stepRecord) {
        showOrderEdit(stepRecord.step, capturedId);
      }
    }, 350);
  });

  // Cancel slow-click on double-click (select text behavior)
  document.addEventListener('dblclick', function (e) {
    if (_slowClickTimer) { clearTimeout(_slowClickTimer); _slowClickTimer = null; }
  });

  document.addEventListener('click', function (e) {
    var target = e.target;
    var topTab = target.closest('.editor-top-tab');
    var jumpItem = target.closest('.editor-jump-item') || target.closest('.editor-jump-more-menu [data-jump]');
    var outlineInsertBtn = target.closest('.editor-outline-insert-btn');
    var insertChoiceBtn = target.closest('[data-insert]');
    var mdInsertBtn = target.closest('[data-md-insert]');
    var symbolItemBtn = target.closest('[data-symbol-name]');
    var typeaheadItemBtn = target.closest('[data-typeahead-name]');
    var labelQuickBtn = target.closest('[data-label-insert]');
    var stepActionBtn = target.closest('[data-step-action]');
    var openAddStepBtn = target.closest('[data-open-add-step]');
    var orderBlockBtn = target.closest('[data-order-block-id]');
    var orderBuilderBtn = target.closest('#btn-order-builder');
    var stepSelectInput = target.closest('[data-step-select]');
    var blockActionBtn = target.closest('[data-block-action]');
    var projectActionBtn = target.closest('[data-project-action]');
    var removeFieldBtn = target.closest('[data-remove-field]');
    var addReviewItemBtn = target.closest('[data-add-review-item]');
    var removeReviewItemBtn = target.closest('[data-remove-review-item]');
    var reviewItemToggle = target.closest('[data-review-item-toggle]');
    var removeObjBtn = target.closest('[data-remove-obj]');
    var removeUploadBtn = target.closest('[data-remove-upload]');
    var projectCardBtn = target.closest('[data-project-card]');

    if (blockActionBtn) {
      var blockAction = blockActionBtn.getAttribute('data-block-action');
      var blockActionId = blockActionBtn.getAttribute('data-block-id');
      if (!blockActionId) return;
      if (blockAction === 'move-up') {
        moveOutlineBlock(blockActionId, -1);
      } else if (blockAction === 'move-down') {
        moveOutlineBlock(blockActionId, 1);
      } else if (blockAction === 'move-top') {
        moveOutlineBlockToEdge(blockActionId, 'top');
      } else if (blockAction === 'move-bottom') {
        moveOutlineBlockToEdge(blockActionId, 'bottom');
      } else if (blockAction === 'comment') {
        if (!window.confirm('Disable this block by commenting it out?')) return;
        apiPost('/api/block/comment', {
          project: state.project,
          filename: state.filename,
          block_id: blockActionId,
        }).then(function (res) {
          if (res.success && res.data) {
            refreshFromFileResponse(res.data);
            return;
          }
          window.alert((res.error && res.error.message) || 'Unable to disable block.');
        });
      } else if (blockAction === 'delete') {
        if (!window.confirm('Delete this block permanently?')) return;
        apiPost('/api/block/delete', {
          project: state.project,
          filename: state.filename,
          block_id: blockActionId,
        }).then(function (res) {
          if (res.success && res.data) {
            refreshFromFileResponse(res.data);
            return;
          }
          window.alert((res.error && res.error.message) || 'Unable to delete block.');
        });
      } else if (blockAction === 'enable') {
        if (!window.confirm('Re-enable this block?')) return;
        apiPost('/api/block/enable', {
          project: state.project,
          filename: state.filename,
          block_id: blockActionId,
        }).then(function (res) {
          if (res.success && res.data) {
            refreshFromFileResponse(res.data);
            return;
          }
          window.alert((res.error && res.error.message) || 'Unable to re-enable block.');
        });
      }
      return;
    }

    if (projectActionBtn) {
      var projectAction = projectActionBtn.getAttribute('data-project-action');
      var projectName = projectActionBtn.getAttribute('data-project-name');
      if (!projectName) return;
      if (projectAction === 'rename') {
        var renamed = window.prompt('Rename project:', projectName);
        if (renamed === null) return;
        renamed = renamed.trim();
        if (!renamed || renamed === projectName) return;
        apiPost('/api/project/rename', { project: projectName, new_project: renamed })
          .then(function (res) {
            if (!res.success || !res.data) {
              window.alert((res.error && res.error.message) || 'Unable to rename project.');
              return;
            }
            reloadProjectsAfterMutation(projectName, res.data.project);
          });
        return;
      }
      if (projectAction === 'delete') {
        if (!window.confirm('Delete project "' + projectName + '" and all of its files?')) return;
        apiPost('/api/project/delete', { project: projectName })
          .then(function (res) {
            if (!res.success || !res.data) {
              window.alert((res.error && res.error.message) || 'Unable to delete project.');
              return;
            }
            reloadProjectsAfterMutation(projectName, null);
          });
        return;
      }
    }

    if (target.closest('.editor-outline-drag-handle') || target.closest('.editor-outline-menu-btn') || target.closest('.editor-outline-item-actions') || target.closest('.editor-project-card-menu-btn') || target.closest('.editor-project-card-actions')) {
      return;
    }

    if (!target.closest('#editor-symbol-typeahead') && !target.closest('[data-symbol-role]')) {
      hideTypeaheadMenu();
    }

    // Validation drawer toggle
    if (target.id === 'validation-toggle' || target.closest('#validation-toggle')) {
      state.validationOpen = !state.validationOpen;
      renderValidationDrawer();
      return;
    }
    if (target.id === 'btn-check-errors' || target.closest('#btn-check-errors')) {
      state.validationOpen = true;
      runValidation();
      return;
    }
    if (target.id === 'btn-run-validation' || target.closest('#btn-run-validation')) {
      state.validationOpen = true;
      runValidation();
      return;
    }
    if (target.id === 'btn-style-check' || target.closest('#btn-style-check')) {
      state.validationOpen = true;
      runStyleCheck();
      return;
    }

    var validationItem = target.closest('.editor-validation-item[data-block-id]');
    if (validationItem) {
      var validationBlockId = validationItem.getAttribute('data-block-id');
      if (validationBlockId) {
        var validationBlock = getBlockById(validationBlockId);
        if (validationBlock && !isBlockVisibleInOutline(validationBlock)) {
          state.jumpTarget = 'all';
          $$('.editor-jump-item').forEach(function (j) {
            j.classList.toggle('active', j.getAttribute('data-jump') === 'all');
          });
        }
        state.currentView = 'interview';
        state.validationOpen = true;
        state.selectedBlockId = validationBlockId;
        var interviewTab = document.querySelector('.editor-top-tab[data-view="interview"]');
        if (interviewTab) setActiveTopTab(interviewTab);
        renderOutline();
        renderCanvas();
        renderValidationDrawer();
      }
      return;
    }

    // Hamburger menu toggle
    if (target.id === 'topbar-hamburger' || target.closest('#topbar-hamburger')) {
      var mobileMenu = document.getElementById('topbar-mobile-menu');
      if (mobileMenu) mobileMenu.classList.toggle('d-none');
      return;
    }

    // View tabs
    if (topTab) {
      if (topTab.getAttribute('data-view') !== state.currentView && blockUnsavedSectionNavigation()) return;
      stashCurrentEditorState();
      state.currentView = topTab.getAttribute('data-view');
      setActiveTopTab(topTab);
      if (state.currentView === 'interview') {
        state.canvasMode = state.project ? 'question' : 'project-selector';
        if (!state.selectedBlockId || !isBlockVisibleInOutline(getBlockById(state.selectedBlockId))) {
          state.selectedBlockId = getDefaultVisibleBlockId();
        }
        renderOutline();
        renderCanvas();
      } else {
        renderOutline();
        renderCanvas();
        loadSectionFiles(state.currentView);
      }
      return;
    }

    // Project selector cards
    if (projectCardBtn) {
      if (blockUnsavedSectionNavigation()) return;
      stashCurrentEditorState();
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
      if (blockUnsavedSectionNavigation()) return;
      stashCurrentEditorState();
      var jump = jumpItem.getAttribute('data-jump');
      $$('.editor-jump-item').forEach(function (j) { j.classList.remove('active'); });
      // Only visually activate direct jump buttons, not dropdown items
      if (jumpItem.classList.contains('editor-jump-item')) {
        jumpItem.classList.add('active');
      }
      state.jumpTarget = jump;
      state.canvasMode = 'question';
      state.selectedBlockId = getDefaultVisibleBlockId();
      state.currentView = 'interview';
      var interviewTab = document.querySelector('.editor-top-tab[data-view="interview"]');
      if (interviewTab) setActiveTopTab(interviewTab);
      renderCanvas();
      renderOutline();
      return;
    }

    // Outline block selection
    var outlineItem = target.closest('.editor-outline-item');
    if (outlineItem && !target.closest('[data-stop-propagation]') && !target.closest('.editor-file-actions-kebab') && !target.closest('.dropdown-menu')) {
      if (!isInterviewView()) {
        var viewForFile = state.currentView;
        var selectedSectionFilename = outlineItem.getAttribute('data-section-filename');
        if (selectedSectionFilename !== state.sectionSelectedFile[viewForFile] && blockUnsavedSectionNavigation()) return;
        state.sectionSelectedFile[viewForFile] = selectedSectionFilename;
      } else {
        stashCurrentEditorState();
        state.selectedBlockId = outlineItem.getAttribute('data-block-id');
        state.canvasMode = 'question';
        state.questionEditMode = 'preview';
        state.questionBlockTab = 'screen';
        state.advancedOpen = false;
        state.advancedShowMore = false;
        state.markdownPreviewMode = false;
      }
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
      var isAiScreen = kind === 'ai-screen';
      var insertKind = isAiScreen ? 'question' : kind;
      var newYaml = makeNewBlockYaml(insertKind);
      if (insertKind === 'review') {
        state.jumpTarget = 'reviews';
        $$('.editor-jump-item').forEach(function (j) {
          j.classList.toggle('active', j.getAttribute('data-jump') === 'reviews');
        });
      } else if (insertKind !== 'question' && state.jumpTarget === 'questions') {
        state.jumpTarget = 'all';
        $$('.editor-jump-item').forEach(function (j) {
          j.classList.toggle('active', j.getAttribute('data-jump') === 'all');
        });
      }
      apiPost('/api/insert-block', {
        project: state.project,
        filename: state.filename,
        insert_after_id: state.insertAfterBlockId,
        block_yaml: newYaml,
      }).then(function (res) {
        if (res.success && res.data) {
          closeBootstrapModal('insert-modal');
          refreshFromFileResponse(res.data);
          if (isAiScreen) {
            var newBlock = getSelectedBlock();
            if (!newBlock || newBlock.type !== 'question') return;
            var screenInstruction = window.prompt('Optional guidance for this screen (leave blank for auto-draft):', '');
            if (screenInstruction === null) return;
            _setButtonLoading('ai-generate-screen', true, 'Drafting...');
            apiPost('/api/ai/generate-screen', {
              project: state.project,
              filename: state.filename,
              block_id: newBlock.id,
              instruction: screenInstruction,
              field_types: FIELD_TYPES,
              current_screen: {
                question: newBlock.data.question || '',
                subquestion: newBlock.data.subquestion || '',
                fields: newBlock.data.fields || [],
              },
            }).then(function (aiRes) {
              if (!aiRes.success || !aiRes.data || !aiRes.data.screen) {
                throw new Error((aiRes.error && aiRes.error.message) || 'AI screen generation failed');
              }
              applyAIGeneratedScreenToBlock(newBlock, aiRes.data.screen);
              state.dirty = true;
              renderCanvas();
            }).catch(function (err) {
              window.alert('Unable to generate screen: ' + String((err && err.message) || err || 'Unknown error'));
            }).finally(function () {
              _setButtonLoading('ai-generate-screen', false, '');
            });
          }
          return;
        }
        window.alert((res.error && res.error.message) || 'Unable to insert block.');
      });
      return;
    }

    if (mdInsertBtn) {
      var mdAction = mdInsertBtn.getAttribute('data-md-insert');
      var targetId = mdInsertBtn.getAttribute('data-target-id');
      var targetEl = targetId ? document.getElementById(targetId) : null;
      if (!targetEl) {
        var toolbar = mdInsertBtn.closest('[data-md-toolbar-for]');
        if (toolbar) {
          var fallbackId = toolbar.getAttribute('data-md-toolbar-for');
          if (fallbackId) targetEl = document.getElementById(fallbackId);
        }
      }
      if (!targetEl) {
        var activeEl = document.activeElement;
        if (activeEl && (activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'INPUT')) {
          targetEl = activeEl;
        }
      }
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
      stashCurrentEditorState();
      enterOrderBuilder(nextOrderBlockId, 'order-switcher');
      return;
    }

    // Top action buttons
    if (target.id === 'btn-project-selector') {
      if (blockUnsavedSectionNavigation()) return;
      stashCurrentEditorState();
      state.canvasMode = 'project-selector';
      state.currentView = 'interview';
      var interviewTab0 = document.querySelector('.editor-top-tab[data-view="interview"]');
      if (interviewTab0) setActiveTopTab(interviewTab0);
      renderCanvas();
      return;
    }

    if (target.id === 'btn-upload-section-file' || target.id === 'btn-upload-section-file-inline') {
      var uploadInput = document.getElementById('section-upload-input');
      if (uploadInput) uploadInput.click();
      return;
    }

    if (target.id === 'btn-new-section-file-inline') {
      if (!state.project || isInterviewView()) return;
      var inlineNewName = window.prompt('New filename', defaultNewFilename(state.currentView));
      if (!inlineNewName) return;
      var inlineSection = getSectionFromView(state.currentView);
      apiPost('/api/section-file/new', {
        project: state.project,
        section: inlineSection,
        filename: inlineNewName,
        content: '',
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to create file.');
          return;
        }
        state.sectionSelectedFile[state.currentView] = inlineNewName;
        state.sectionDirty = false;
        loadSectionFiles(state.currentView);
      });
      return;
    }

    // Inline section file kebab actions (rename/delete)
    var sectionFileRename = target.closest('.js-section-file-rename');
    if (sectionFileRename) {
      var sfName = sectionFileRename.getAttribute('data-filename');
      if (!sfName || !state.project || isInterviewView()) return;
      var sfSection = getSectionFromView(state.currentView);
      var sfNewName = window.prompt('Rename file to', sfName);
      if (!sfNewName) return;
      apiPost('/api/section-file/rename', {
        project: state.project,
        section: sfSection,
        filename: sfName,
        new_filename: sfNewName,
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to rename file.');
          return;
        }
        state.sectionSelectedFile[state.currentView] = res.data && res.data.filename ? res.data.filename : sfNewName;
        loadSectionFiles(state.currentView);
      });
      return;
    }

    var sectionFileDashboard = target.closest('.js-section-file-dashboard');
    if (sectionFileDashboard) {
      var dashboardFilename = sectionFileDashboard.getAttribute('data-filename');
      if (!dashboardFilename || !state.project || isInterviewView()) return;
      var dashboardSection = getSectionFromView(state.currentView);
      apiGet('/api/dashboard-editor-url?project=' + encodeURIComponent(state.project) + '&section=' + encodeURIComponent(dashboardSection) + '&filename=' + encodeURIComponent(dashboardFilename))
        .then(function (res) {
          if (res.success && res.data && res.data.url) {
            window.open(res.data.url, '_blank');
          } else {
            window.alert((res.error && res.error.message) || 'No dashboard editor URL is configured for this file type.');
          }
        });
      return;
    }

    var sectionFileDelete = target.closest('.js-section-file-delete');
    if (sectionFileDelete) {
      var delName = sectionFileDelete.getAttribute('data-filename');
      if (!delName || !state.project || isInterviewView()) return;
      if (!window.confirm('Delete ' + delName + '?')) return;
      var delSection = getSectionFromView(state.currentView);
      apiPost('/api/section-file/delete', {
        project: state.project,
        section: delSection,
        filename: delName,
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to delete file.');
          return;
        }
        if (state.sectionSelectedFile[state.currentView] === delName) {
          state.sectionSelectedFile[state.currentView] = null;
        }
        loadSectionFiles(state.currentView);
      });
      return;
    }

    if (target.id === 'btn-new-interview-file') {
      if (!state.project) return;
      var newInterviewName = window.prompt('New YAML filename', 'new_interview.yml');
      if (!newInterviewName) return;
      apiPost('/api/file/new', {
        project: state.project,
        filename: newInterviewName,
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to create file.');
          return;
        }
        state.filename = res.data && res.data.filename ? res.data.filename : newInterviewName;
        loadFiles();
      });
      return;
    }

    if (target.id === 'btn-upload-interview-file') {
      var interviewUploadInput = document.getElementById('interview-upload-input');
      if (interviewUploadInput) interviewUploadInput.click();
      return;
    }

    if (target.id === 'btn-download-file') {
      if (!state.project || !state.filename) return;
      apiGet('/api/file?project=' + encodeURIComponent(state.project) + '&filename=' + encodeURIComponent(state.filename))
        .then(function (res) {
          if (!res.success || !res.data) return;
          var content = res.data.content || '';
          var blob = new Blob([content], { type: 'text/yaml' });
          var url = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = state.filename;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        });
      return;
    }

    if (target.id === 'btn-rename-file') {
      if (!state.project || !state.filename || !isInterviewView()) return;
      var renamedInterviewFile = window.prompt('Rename file to', state.filename);
      if (!renamedInterviewFile) return;
      apiPost('/api/file/rename', {
        project: state.project,
        filename: state.filename,
        new_filename: renamedInterviewFile,
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to rename file.');
          return;
        }
        state.filename = res.data && res.data.filename ? res.data.filename : renamedInterviewFile;
        loadFiles();
      });
      return;
    }

    if (target.id === 'btn-delete-file') {
      if (!state.project || !state.filename || !isInterviewView()) return;
      if (!window.confirm('Delete ' + state.filename + '?')) return;
      apiPost('/api/file/delete', {
        project: state.project,
        filename: state.filename,
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to delete file.');
          return;
        }
        state.filename = null;
        loadFiles();
      });
      return;
    }

    if (target.id === 'btn-standard-playground') {
      var standardPlaygroundUrl = buildStandardPlaygroundUrl();
      if (standardPlaygroundUrl) {
        window.open(standardPlaygroundUrl, '_blank');
      }
      return;
    }

    if (target.id === 'btn-new-section-file') {
      if (!state.project || isInterviewView()) return;
      var filenamePrompt = window.prompt('New filename', defaultNewFilename(state.currentView));
      if (!filenamePrompt) return;
      var sectionForNew = getSectionFromView(state.currentView);
      apiPost('/api/section-file/new', {
        project: state.project,
        section: sectionForNew,
        filename: filenamePrompt,
        content: '',
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to create file.');
          return;
        }
        state.sectionSelectedFile[state.currentView] = filenamePrompt;
        state.sectionDirty = false;
        loadSectionFiles(state.currentView);
      });
      return;
    }

    if (target.id === 'btn-rename-section-file') {
      if (!state.project || isInterviewView()) return;
      var sectionForRename = getSectionFromView(state.currentView);
      var sectionFileMetaForRename = getSelectedSectionFileMeta(state.currentView);
      if (!sectionForRename || !sectionFileMetaForRename) return;
      var renamedSectionFile = window.prompt('Rename file to', sectionFileMetaForRename.filename);
      if (!renamedSectionFile) return;
      apiPost('/api/section-file/rename', {
        project: state.project,
        section: sectionForRename,
        filename: sectionFileMetaForRename.filename,
        new_filename: renamedSectionFile,
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to rename file.');
          return;
        }
        state.sectionSelectedFile[state.currentView] = res.data && res.data.filename ? res.data.filename : renamedSectionFile;
        loadSectionFiles(state.currentView);
      });
      return;
    }

    if (target.id === 'btn-delete-section-file') {
      if (!state.project || isInterviewView()) return;
      var sectionForDelete = getSectionFromView(state.currentView);
      var sectionFileMetaForDelete = getSelectedSectionFileMeta(state.currentView);
      if (!sectionForDelete || !sectionFileMetaForDelete) return;
      if (!window.confirm('Delete ' + sectionFileMetaForDelete.filename + '?')) return;
      apiPost('/api/section-file/delete', {
        project: state.project,
        section: sectionForDelete,
        filename: sectionFileMetaForDelete.filename,
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to delete file.');
          return;
        }
        state.sectionSelectedFile[state.currentView] = null;
        loadSectionFiles(state.currentView);
      });
      return;
    }

    if (target.id === 'save-section-file') {
      if (!state.project || isInterviewView()) return;
      var sectionForSave = getSectionFromView(state.currentView);
      var sectionFileMeta = getSelectedSectionFileMeta(state.currentView);
      if (!sectionForSave || !sectionFileMeta) return;
      var contentVal = getMonacoValue('section-file-monaco');
      apiPost('/api/section-file', {
        project: state.project,
        section: sectionForSave,
        filename: sectionFileMeta.filename,
        content: contentVal,
      }).then(function (res) {
        if (!res.success) {
          window.alert((res.error && res.error.message) || 'Unable to save file.');
          return;
        }
        state.sectionDirty = false;
        var saveSectionBtn = document.getElementById('save-section-file');
        if (saveSectionBtn) saveSectionBtn.disabled = true;
        loadSectionFiles(state.currentView);
      });
      return;
    }

    if (target.id === 'btn-new-project') {
      if (blockUnsavedSectionNavigation()) return;
      stashCurrentEditorState();
      state.canvasMode = 'new-project';
      state.currentView = 'interview';
      var interviewTab1 = document.querySelector('.editor-top-tab[data-view="interview"]');
      if (interviewTab1) setActiveTopTab(interviewTab1);
      renderCanvas();
      return;
    }
    if (target.id === 'btn-full-yaml') {
      if (blockUnsavedSectionNavigation()) return;
      stashCurrentEditorState();
      _stashFullYamlContent();
      state.canvasMode = state.canvasMode === 'full-yaml' ? 'question' : 'full-yaml';
      state.currentView = 'interview';
      var interviewTab2 = document.querySelector('.editor-top-tab[data-view="interview"]');
      if (interviewTab2) setActiveTopTab(interviewTab2);
      renderCanvas();
      return;
    }
    if (orderBuilderBtn) {
      enterOrderBuilder(state.activeOrderBlockId || getDefaultOrderBlockId(), 'topbar-order-button');
      return;
    }
    if (target.id === 'btn-save-file') {
      if (!state.filename) return;
      saveCurrentBlockIfDirty();
      return;
    }
    if (target.id === 'gen-block-id') {
      var titleEl = document.getElementById('q-title');
      var idEl = document.getElementById('adv-id');
      if (!idEl) return;
      var questionText = titleEl ? titleEl.value : '';
      var currentBlock = getSelectedBlock();
      var allBlocks = state.blocks || [];
      var newId = generateBlockId(questionText, allBlocks, currentBlock ? currentBlock.id : null);
      idEl.value = newId;
      idEl.dispatchEvent(new Event('input'));
      return;
    }
    if (target.id === 'add-question-event') {
      var eventBlock = getSelectedBlock();
      if (eventBlock && eventBlock.type === 'question') {
        syncFieldsToData(eventBlock);
        _questionEventFieldOpen[eventBlock.id] = true;
        markInterviewDirty();
        renderCanvas();
        window.setTimeout(function () {
          var eventEl = document.getElementById('adv-event');
          if (eventEl) eventEl.focus();
        }, 50);
      }
      return;
    }
    if (target.id === 'remove-question-event') {
      var removeEventBlock = getSelectedBlock();
      if (removeEventBlock && removeEventBlock.type === 'question') {
        var eventInput = document.getElementById('adv-event');
        if (eventInput) eventInput.value = '';
        syncFieldsToData(removeEventBlock);
        delete _questionEventFieldOpen[removeEventBlock.id];
        markInterviewDirty();
        renderCanvas();
      }
      return;
    }
    if (target.id === 'btn-preview-interview') {
      if (!state.filename) return;
      saveCurrentBlockIfDirty().then(function (saved) {
        if (!saved) return;
        apiGet('/api/preview-url?project=' + encodeURIComponent(state.project) + '&filename=' + encodeURIComponent(state.filename))
          .then(function (res) { if (res.success && res.data && res.data.url) window.open(res.data.url, '_blank'); });
      });
      return;
    }
    if (target.id === 'ai-generate-screen') {
      var questionBlock = getSelectedBlock();
      if (!questionBlock || questionBlock.type !== 'question' || !state.project || !state.filename) return;
      syncFieldsToData(questionBlock);
      var screenInstruction = window.prompt('Optional guidance for this screen (leave blank for auto-draft):', '');
      if (screenInstruction === null) return;
      _setButtonLoading('ai-generate-screen', true, 'Drafting...');
      apiPost('/api/ai/generate-screen', {
        project: state.project,
        filename: state.filename,
        block_id: questionBlock.id,
        instruction: screenInstruction,
        field_types: FIELD_TYPES,
        current_screen: {
          question: questionBlock.data.question || '',
          subquestion: questionBlock.data.subquestion || '',
          fields: questionBlock.data.fields || [],
        },
      }).then(function (res) {
        if (!res.success || !res.data || !res.data.screen) {
          throw new Error((res.error && res.error.message) || 'AI screen generation failed');
        }
        applyAIGeneratedScreenToBlock(questionBlock, res.data.screen);
        state.dirty = true;
        renderCanvas();
      }).catch(function (err) {
        window.alert('Unable to generate screen: ' + String((err && err.message) || err || 'Unknown error'));
      }).finally(function () {
        _setButtonLoading('ai-generate-screen', false, '');
      });
      return;
    }
    if (target.id === 'ai-generate-fields') {
      var currentQuestionBlock = getSelectedBlock();
      if (!currentQuestionBlock || currentQuestionBlock.type !== 'question' || !state.project || !state.filename) return;
      syncFieldsToData(currentQuestionBlock);
      _setButtonLoading('ai-generate-fields', true, 'Generating...');
      apiPost('/api/ai/generate-fields', {
        project: state.project,
        filename: state.filename,
        block_id: currentQuestionBlock.id,
        field_types: FIELD_TYPES,
        current_screen: {
          question: currentQuestionBlock.data.question || '',
          subquestion: currentQuestionBlock.data.subquestion || '',
          fields: currentQuestionBlock.data.fields || [],
        },
      }).then(function (res) {
        if (!res.success || !res.data || !Array.isArray(res.data.fields)) {
          throw new Error((res.error && res.error.message) || 'AI field generation failed');
        }
        applyAIGeneratedScreenToBlock(currentQuestionBlock, {
          question: currentQuestionBlock.data.question || '',
          subquestion: currentQuestionBlock.data.subquestion || '',
          fields: res.data.fields,
          continue_button_field: currentQuestionBlock.data['continue button field'] || '',
        });
        state.dirty = true;
        renderCanvas();
      }).catch(function (err) {
        window.alert('Unable to generate fields: ' + String((err && err.message) || err || 'Unknown error'));
      }).finally(function () {
        _setButtonLoading('ai-generate-fields', false, '');
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

    // Toggle edit mode (shared by question / code / objects)
    if (target.id === 'toggle-edit-mode') {
      var nextEditMode = state.questionEditMode === 'preview' ? 'yaml' : 'preview';
      saveCurrentBlockIfDirty().then(function (saved) {
        if (!saved) return;
        state.questionEditMode = nextEditMode;
        state.markdownPreviewMode = false;
        renderCanvas();
      });
      return;
    }

    // Question tab with optional mode switching (Screen/Options tabs set preview mode, Preview tab enables markdown preview, YAML tab sets yaml mode)
    var questionModeButton = target.closest('[data-question-mode]');
    if (questionModeButton) {
      var qMode = questionModeButton.getAttribute('data-question-mode');
      var qTab = questionModeButton.getAttribute('data-question-tab');
      var isPreviewTab = questionModeButton.getAttribute('data-question-preview') === 'true';
      if (qMode === 'yaml' && state.questionEditMode !== 'yaml') {
        saveCurrentBlockIfDirty().then(function (saved) {
          if (!saved) return;
          state.questionEditMode = 'yaml';
          state.markdownPreviewMode = false;
          renderCanvas();
        });
        return;
      } else if (qMode === 'preview' && state.questionEditMode !== 'preview') {
        saveCurrentBlockIfDirty().then(function (saved) {
          if (!saved) return;
          state.questionEditMode = 'preview';
          if (qTab === 'screen' || qTab === 'options') {
            state.questionBlockTab = qTab;
            state.markdownPreviewMode = false;
          } else if (isPreviewTab) {
            var selectedForPreview = getSelectedBlock();
            if (selectedForPreview && selectedForPreview.type === 'question') {
              syncFieldsToData(selectedForPreview);
            }
            state.markdownPreviewMode = true;
          }
          renderCanvas();
        });
        return;
      }
      if (qMode === 'preview') {
        stashCurrentEditorState();
        if (qTab === 'screen' || qTab === 'options') {
          state.questionBlockTab = qTab;
          state.markdownPreviewMode = false;
        } else if (isPreviewTab) {
          var selectedForPreview = getSelectedBlock();
          if (selectedForPreview && selectedForPreview.type === 'question') {
            syncFieldsToData(selectedForPreview);
          }
          state.markdownPreviewMode = true;
        }
        renderCanvas();
      }
      return;
    }

    if (target.matches('[data-field-settings-tab]')) {
      var tabFi = parseInt(target.getAttribute('data-field-idx'), 10);
      var tabBlock = getSelectedBlock();
      if (tabBlock && tabBlock.type === 'question') {
        syncFieldsToData(tabBlock);
        markInterviewDirty();
      }
      _fieldSettingsTabs[tabFi] = target.getAttribute('data-field-settings-tab') || 'basic';
      renderCanvas();
      return;
    }

    if (target.matches('[data-field-datatype]')) {
      var typeFi = parseInt(target.getAttribute('data-field-idx'), 10);
      var nextType = target.getAttribute('data-field-datatype') || 'text';
      var typeBlock = getSelectedBlock();
      if (typeBlock && typeBlock.type === 'question') {
        syncFieldsToData(typeBlock);
        if (typeBlock.data && Array.isArray(typeBlock.data.fields) && typeBlock.data.fields[typeFi]) {
          if (typeof typeBlock.data.fields[typeFi] === 'string') {
            typeBlock.data.fields[typeFi] = { label: typeBlock.data.fields[typeFi], field: '', datatype: nextType };
          } else {
            typeBlock.data.fields[typeFi].datatype = nextType;
          }
        }
        state.dirty = true;
        renderCanvas();
      }
      return;
    }

    if (target.id === 'toggle-advanced') {
      stashCurrentEditorState();
      state.advancedOpen = !state.advancedOpen;
      renderCanvas();
      return;
    }

    // Advanced show more toggle
    if (target.id === 'adv-show-more') {
      stashCurrentEditorState();
      state.advancedShowMore = !state.advancedShowMore;
      renderCanvas();
      return;
    }

    if (target.id === 'toggle-review-meta') {
      state.reviewMetaOpen = !state.reviewMetaOpen;
      renderCanvas();
      return;
    }

    if (reviewItemToggle) {
      var ri = parseInt(reviewItemToggle.getAttribute('data-review-item-toggle'), 10);
      state.openReviewItemIndex = state.openReviewItemIndex === ri ? null : ri;
      renderCanvas();
      return;
    }

    if (addReviewItemBtn) {
      var reviewBlock = getSelectedBlock();
      if (reviewBlock && reviewBlock.type === 'review') {
        stashReviewItemSnippets(reviewBlock);
        reviewBlock.data.review = Array.isArray(reviewBlock.data.review) ? reviewBlock.data.review : [];
        var kindToAdd = addReviewItemBtn.getAttribute('data-add-review-item') || 'edit';
        if (kindToAdd === 'note') {
          reviewBlock.data.review.push({ note: 'Add a note for the review screen.' });
        } else if (kindToAdd === 'html') {
          reviewBlock.data.review.push({ html: '<div class="collapse">Add accordion HTML here.</div>' });
        } else {
          var fieldEl = document.getElementById('review-new-field');
          var fieldName = fieldEl && fieldEl.value.trim() ? fieldEl.value.trim() : '';
          if (!fieldName) {
            if (fieldEl) fieldEl.focus();
            return;
          }
          reviewBlock.data.review.push({ Edit: fieldName, button: '${ showifdef("' + fieldName.replace(/"/g, '\\"') + '") }' });
        }
        state.openReviewItemIndex = reviewBlock.data.review.length - 1;
        state.dirty = true;
        updateTopbarSaveState();
        renderCanvas();
      }
      return;
    }

    if (removeReviewItemBtn) {
      var removeReviewBlock = getSelectedBlock();
      var removeRi = parseInt(removeReviewItemBtn.getAttribute('data-remove-review-item'), 10);
      if (removeReviewBlock && removeReviewBlock.type === 'review' && Array.isArray(removeReviewBlock.data.review)) {
        if (!window.confirm('Remove this review item?')) return;
        stashReviewItemSnippets(removeReviewBlock);
        removeReviewBlock.data.review.splice(removeRi, 1);
        state.openReviewItemIndex = null;
        state.dirty = true;
        updateTopbarSaveState();
        renderCanvas();
      }
      return;
    }

    if (target.id === 'draft-review-screen') {
      if (!state.project || !state.filename) return;
      apiPost('/api/draft-review-screen', { project: state.project, filename: state.filename })
        .then(function (res) {
          if (res.success && res.data && res.data.review_yaml) {
            state.canvasMode = 'full-yaml';
            state.fullYamlTab = 'full';
            state.fullYamlStash.full = (state.rawYaml || '').replace(/\s*$/, '\n---\n') + res.data.review_yaml.trim() + '\n';
            renderCanvas();
            return;
          }
          window.alert((res.error && res.error.message) || 'Unable to draft review screen.');
        });
      return;
    }

    // Kebab field options toggle
    var kebabBtn = target.closest ? target.closest('.editor-field-kebab-btn') : null;
    if (!kebabBtn && target.classList.contains('editor-field-kebab-btn')) kebabBtn = target;
    if (kebabBtn) {
      var kFi = parseInt(kebabBtn.getAttribute('data-field-idx'), 10);
      _openFieldModsPanels[kFi] = !_openFieldModsPanels[kFi];
      var modsPanel = document.querySelector('.editor-field-mods-panel[data-field-idx="' + kFi + '"]');
      if (modsPanel) {
        if (_openFieldModsPanels[kFi]) modsPanel.removeAttribute('hidden'); else modsPanel.setAttribute('hidden', '');
      }
      kebabBtn.setAttribute('aria-expanded', _openFieldModsPanels[kFi] ? 'true' : 'false');
      state.dirty = true;
      return;
    }

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
          return;
        }
        window.alert((res.error && res.error.message) || 'Unable to save block.');
      });
      return;
    }
    if (target.id === 'enable-block-btn') {
      var disabledBlock = getSelectedBlock();
      if (!disabledBlock || disabledBlock.type !== 'commented') return;
      if (!window.confirm('Re-enable this block?')) return;
      apiPost('/api/block/enable', {
        project: state.project,
        filename: state.filename,
        block_id: disabledBlock.id,
      }).then(function (res) {
        if (res.success && res.data) {
          refreshFromFileResponse(res.data);
          return;
        }
        window.alert((res.error && res.error.message) || 'Unable to re-enable block.');
      });
      return;
    }

    // Full YAML tabs
    if (target.matches('[data-yaml-tab]')) {
      _stashFullYamlContent();
      state.fullYamlTab = target.getAttribute('data-yaml-tab');
      renderCanvas();
      return;
    }
    if (target.id === 'back-to-question') {
      _stashFullYamlContent();
      var returnMode = state._prevCanvasMode || 'question';
      state._prevCanvasMode = null;
      state.canvasMode = returnMode;
      renderOutline();
      renderCanvas();
      return;
    }
    if (target.id === 'save-full-yaml') {
      var yamlContent = getMonacoValue('full-yaml-monaco');
      if (!yamlContent) return;
      state.fullYamlStash = {};
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
        .then(function (res) { if (res.success) { state.orderSteps = res.data.steps; syncActiveOrderStepMap(); markOrderDirty(); renderCanvas(); } });
      return;
    }
    if (target.id === 'wrap-selected-order-steps') {
      if (wrapSelectedOrderSteps()) { markOrderDirty(); renderCanvas(); }
      return;
    }
    if (target.id === 'order-to-raw') {
      stashCurrentEditorState();
      state._prevCanvasMode = 'order-builder';
      state.canvasMode = 'full-yaml';
      state.fullYamlTab = 'order';
      renderCanvas();
      return;
    }
    if (target.id === 'order-back-to-code') {
      stashCurrentEditorState();
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
        .then(function (res) { if (res.success) { state.orderDirty = false; state.dirty = false; loadFile(); } });
      return;
    }

    // Step actions
    if (stepActionBtn) {
      var action = stepActionBtn.getAttribute('data-step-action');
      // inline-cancel needs no step record
      if (action === 'inline-cancel') {
        _inlineEditStepId = null;
        renderCanvas();
        return;
      }
      var targetStepId = stepActionBtn.getAttribute('data-step-id');
      var stepRecord = findStepRecord(state.orderSteps, targetStepId, null);
      if (!stepRecord) return;
      if (action === 'remove') {
        stepRecord.list.splice(stepRecord.index, 1);
        delete state.selectedOrderStepIds[targetStepId];
        syncActiveOrderStepMap();
        markOrderDirty();
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
        markOrderDirty();
        renderCanvas();
      } else if (action === 'inline-save') {
        var inlineInvoke = document.getElementById('order-inline-edit-invoke');
        var inlineCondition = document.getElementById('order-inline-edit-condition');
        var inlineValue = document.getElementById('order-inline-edit-value');
        if (inlineInvoke) { stepRecord.step.invoke = inlineInvoke.value; stepRecord.step.summary = inlineInvoke.value; }
        if (inlineCondition) { stepRecord.step.condition = inlineCondition.value; stepRecord.step.summary = inlineCondition.value; }
        if (inlineValue) {
          stepRecord.step.value = inlineValue.value;
          if (stepRecord.step.kind === 'section') stepRecord.step.summary = 'Section: ' + inlineValue.value;
          if (stepRecord.step.kind === 'progress') stepRecord.step.summary = 'Progress: ' + inlineValue.value + '%';
        }
        _inlineEditStepId = null;
        syncActiveOrderStepMap();
        markOrderDirty();
        renderCanvas();
      } else if (action === 'go-to-block') {
        var targetBlock = findBlockByInvoke(stepRecord.step);
        if (targetBlock) {
          _inlineEditStepId = null;
          state.canvasMode = 'question';
          state.selectedBlockId = targetBlock.id;
          renderOutline();
          renderCanvas();
        } else {
          var invokeLabel = stepRecord.step.invoke || stepRecord.step.value || stepRecord.step.summary || '';
          var inOther = invokeLabel && state.symbolCatalog && state.symbolCatalog.all.indexOf(invokeLabel) !== -1;
          window.alert(invokeLabel
            ? '"' + invokeLabel + '" is ' + (inOther ? 'defined in an included file, not editable here.' : 'not found in this file.')
            : 'No block reference available for this step.');
        }
      }
      return;
    }

    // Open add-step modal
    if (openAddStepBtn) {
      var addParentStepId = openAddStepBtn.getAttribute('data-parent-step-id');
      var addBranch = openAddStepBtn.getAttribute('data-step-branch') || 'then';
      var addInsertIndex = parseInt(openAddStepBtn.getAttribute('data-insert-index') || '-1', 10);
      openOrderAddModal(addParentStepId, addBranch, addInsertIndex);
      return;
    }

    // Add field
    if (target.id === 'add-field-btn') {
      var blk = getSelectedBlock();
      if (blk && blk.data) {
        syncFieldsToData(blk);
        if (!blk.data.fields) blk.data.fields = [];
        blk.data.fields.push({ label: 'New field', field: 'new_variable' });
        _openFieldModsPanels = {};
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
        _openFieldModsPanels = {};
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

    if (target.id === 'cancel-new-project') { _hideUploadProgressModal(); state.canvasMode = 'project-selector'; _uploadedFiles = []; renderCanvas(); return; }

    if (target.id === 'upload-progress-close' || target.closest('#upload-progress-close')) {
      _hideUploadProgressModal();
      return;
    }

    if (removeUploadBtn) {
      var removeBtn = removeUploadBtn;
      var removeIdx = parseInt(removeBtn.getAttribute('data-remove-upload'), 10);
      _uploadedFiles.splice(removeIdx, 1);
      _renderFileList();
      return;
    }

    if (target.id === 'create-project-btn') {
      var nameInput = document.getElementById('new-project-name');
      var notesInput = document.getElementById('new-project-notes');
      var helpPageUrlInput = document.getElementById('new-project-help-page-url');
      var helpPageTitleInput = document.getElementById('new-project-help-page-title');
      var useLlmAssistInput = document.getElementById('new-project-use-llm-assist');
      var projectName = nameInput ? nameInput.value : 'NewProject';
      var notes = notesInput ? notesInput.value : '';
      var helpPageUrl = helpPageUrlInput ? helpPageUrlInput.value : '';
      var helpPageTitle = helpPageTitleInput ? helpPageTitleInput.value : '';
      var useLlmAssist = useLlmAssistInput ? useLlmAssistInput.checked : false;
      _showUploadProgressModal('This may take a minute or two. Please wait.');

      if (_uploadedFiles.length > 0) {
        var formData = new FormData();
        formData.append('project_name', projectName);
        formData.append('generation_notes', notes);
        formData.append('help_source_text', notes);
        formData.append('help_page_url', helpPageUrl);
        formData.append('help_page_title', helpPageTitle);
        formData.append('use_llm_assist', useLlmAssist ? 'true' : 'false');
        _uploadedFiles.forEach(function (f) { formData.append('files', f, f.name); });
        fetchResponsePayload(API + '/api/new-project', { method: 'POST', credentials: 'same-origin', body: formData })
          .then(function (response) {
            var payload = response.body || {};
            if (!response.ok) {
              throw new Error(_fetchErrorMessage(response));
            }
            if (String(payload.status || '').toLowerCase() === 'queued' || response.status === 202) {
              var queuedData = payload.data || {};
              var queuedProject = queuedData.project || projectName;
              var jobUrl = payload.job_url || queuedData.job_url;
              if (!jobUrl) {
                throw new Error('Queued job response did not include a status URL.');
              }
              _setUploadProgressMessage('Queued project "' + queuedProject + '". Starting Weaver generation.');
              return _pollNewProjectJob(jobUrl, queuedProject).then(function (jobPayload) {
                var jobData = jobPayload.data || {};
                _hideUploadProgressModal();
                state.project = jobData.project || queuedProject;
                state.filename = jobData.filename || 'interview.yml';
                state.canvasMode = 'question';
                _uploadedFiles = [];
                _showSuccessBanner('Project "' + esc(state.project) + '" created successfully.');
                return apiGet('/api/projects').then(function (r) {
                  if (r.success) state.projects = r.data.projects;
                  populateProjects();
                  loadFiles();
                });
              });
            }
            if (payload.success) {
              _hideUploadProgressModal();
              state.project = payload.data.project;
              state.filename = payload.data.filename;
              state.canvasMode = 'question';
              _uploadedFiles = [];
              _showSuccessBanner('Project "' + esc(payload.data.project) + '" created successfully.');
              return apiGet('/api/projects').then(function (r) {
                if (r.success) state.projects = r.data.projects;
                populateProjects();
                loadFiles();
              });
            }
            throw new Error(_fetchErrorMessage(response));
          })
          .catch(function (err) { _showUploadError(err.message || 'Network error'); });
      } else {
        apiPost('/api/new-project', {
          project_name: projectName,
          generation_notes: notes,
          help_source_text: notes,
          help_page_url: helpPageUrl,
          help_page_title: helpPageTitle,
          use_llm_assist: useLlmAssist,
        })
          .then(function (res) {
            if (res.success) {
              _hideUploadProgressModal();
              state.project = res.data.project;
              state.filename = res.data.filename;
              state.canvasMode = 'question';
              _showSuccessBanner('Project "' + esc(res.data.project) + '" created successfully.');
              apiGet('/api/projects').then(function (r) { if (r.success) state.projects = r.data.projects; populateProjects(); loadFiles(); });
            } else { _showUploadError(res.error ? res.error.message : 'Unknown error'); }
          })
          .catch(function (err) { _showUploadError(err.message || 'Network error'); });
      }
      return;
    }
  });

  document.addEventListener('dblclick', function (e) {
    var target = e.target;
    var reviewSummary = target.closest ? target.closest('[data-review-item-toggle]') : null;
    if (reviewSummary) {
      var ri = parseInt(reviewSummary.getAttribute('data-review-item-toggle'), 10);
      state.openReviewItemIndex = ri;
      renderCanvas();
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
        target.id === 'adv-event' || target.id === 'adv-generic-object' ||
        target.id === 'review-block-id' || target.id === 'review-question' ||
        target.id === 'review-subquestion' || target.id === 'review-event' ||
        target.id === 'review-continue-field' || target.id === 'review-need' ||
        target.id === 'review-tabular' || target.matches('.editor-review-item-yaml') ||
        target.closest('.editor-review-item') || target.id === 'review-new-field' ||
        target.matches('[data-fmod]') || target.matches('.editor-field-showif-input') ||
        target.matches('.editor-field-showif-key') ||
        target.id === 'order-inline-edit-invoke' || target.id === 'order-inline-edit-condition' ||
        target.id === 'order-inline-edit-value' || target.id === 'order-add-invoke' ||
        target.id === 'order-add-condition' || target.id === 'order-add-value' ||
        target.id === 'order-add-code') {
      state.dirty = true;
      if (target.id && target.id.indexOf('order-') === 0) state.orderDirty = true;
      updateTopbarSaveState();
    }
  });

  document.addEventListener('change', function (e) {
    var target = e.target;
    if (target.matches('.editor-field-required-switch') || target.id === 'adv-mandatory-switch' || target.id === 'review-skip-undefined') {
      state.dirty = true;
      updateTopbarSaveState();
      return;
    }
    if (target.id === 'section-upload-input') {
      if (!target.files || !target.files.length || !state.project || isInterviewView()) return;
      var formData = new FormData();
      formData.append('project', state.project);
      formData.append('section', getSectionFromView(state.currentView));
      for (var i = 0; i < target.files.length; i++) {
        formData.append('files', target.files[i], target.files[i].name);
      }
      fetch(API + '/api/section-file/upload', {
        method: 'POST',
        credentials: 'same-origin',
        body: formData,
      }).then(function (res) { return res.json(); })
        .then(function (res) {
          if (!res.success) {
            window.alert((res.error && res.error.message) || 'Upload failed.');
            return;
          }
          if (res.data && Array.isArray(res.data.saved_files) && res.data.saved_files.length) {
            state.sectionSelectedFile[state.currentView] = res.data.saved_files[0];
          }
          state.sectionDirty = false;
          loadSectionFiles(state.currentView);
        })
        .finally(function () {
          target.value = '';
        });
      return;
    }
    if (target.id === 'interview-upload-input') {
      if (!target.files || !target.files.length || !state.project) return;
      var file = target.files[0];
      var reader = new FileReader();
      reader.onload = function (ev) {
        var content = ev.target.result || '';
        var uploadName = file.name;
        apiPost('/api/file/new', {
          project: state.project,
          filename: uploadName,
          content: content,
        }).then(function (res) {
          if (!res.success) {
            window.alert((res.error && res.error.message) || 'Unable to upload file.');
            return;
          }
          state.filename = res.data && res.data.filename ? res.data.filename : uploadName;
          loadFiles();
        });
      };
      reader.readAsText(file);
      target.value = '';
      return;
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
  var _inlineEditStepId = null;
  var _slowClickTimer = null;
  var _slowClickStepId = null;

  function showOrderEdit(step, stepId) {
    if (!step) return;
    // Raw/multi-line code uses the modal; all other kinds use an inline edit row
    if (step.kind === 'raw') {
      _editStepId = stepId;
      _inlineEditStepId = null;
      document.getElementById('order-edit-title').textContent = step.label || step.kind;
      var body = '<div class="mb-3"><label class="editor-tiny">Python code</label>';
      body += '<textarea class="form-control form-control-sm mt-1 font-monospace" id="order-edit-code" rows="4">' + esc(step.code || '') + '</textarea></div>';
      document.getElementById('order-edit-body').innerHTML = body;
      var editModal = getOrCreateBootstrapModal('order-edit-modal');
      if (editModal) editModal.show();
      return;
    }
    _inlineEditStepId = stepId;
    _editStepId = null;
    renderCanvas();
    setTimeout(function () {
      var inlineInput = document.querySelector('.editor-order-inline-edit input, .editor-order-inline-edit textarea');
      if (inlineInput) inlineInput.focus();
    }, 50);
  }

  function renderInlineEditRow(step) {
    var html = '<div class="editor-order-inline-edit">';
    if (step.kind === 'screen' || step.kind === 'gather' || step.kind === 'function') {
      var invokeRole = step.kind === 'function' ? 'function-call' : 'variable';
      html += '<label class="editor-tiny">Variable / expression</label>';
      html += '<input class="form-control form-control-sm mt-1 font-monospace" data-symbol-role="' + invokeRole + '" id="order-inline-edit-invoke" value="' + esc(step.invoke || '') + '">';
    } else if (step.kind === 'condition') {
      html += '<label class="editor-tiny">Condition</label>';
      html += renderSymbolDatalist('order-inline-condition-list', 'variable', 120);
      html += '<input class="form-control form-control-sm mt-1 font-monospace" data-symbol-role="variable" list="order-inline-condition-list" id="order-inline-edit-condition" value="' + esc(step.condition || step.summary || '') + '">';
    } else if (step.kind === 'section') {
      // Build list of section names from sections blocks
      var sectionNames = [];
      state.blocks.forEach(function (b) {
        var secs = b.data && b.data.sections;
        if (!Array.isArray(secs)) return;
        secs.forEach(function (s) {
          if (typeof s === 'string') { if (sectionNames.indexOf(s) === -1) sectionNames.push(s); }
          else if (s && typeof s === 'object') {
            Object.keys(s).forEach(function (k) {
              var v = s[k];
              // keys are display labels, values are section identifiers
              if (v && typeof v === 'string' && sectionNames.indexOf(v) === -1) sectionNames.push(v);
              if (k && sectionNames.indexOf(k) === -1) sectionNames.push(k);
            });
          }
        });
      });
      html += '<label class="editor-tiny">Section name</label>';
      if (sectionNames.length > 0) {
        html += '<datalist id="order-section-list">' + sectionNames.map(function(n){ return '<option value="' + esc(n) + '">'; }).join('') + '</datalist>';
        html += '<input class="form-control form-control-sm mt-1" list="order-section-list" id="order-inline-edit-value" value="' + esc(step.value || '') + '" placeholder="Section name">';
      } else {
        html += '<input class="form-control form-control-sm mt-1" id="order-inline-edit-value" value="' + esc(step.value || '') + '" placeholder="Section name">';
      }
    } else if (step.kind === 'progress') {
      html += '<label class="editor-tiny">Progress value</label>';
      html += '<input class="form-control form-control-sm mt-1" id="order-inline-edit-value" value="' + esc(step.value || '') + '">';
    }
    html += '<div class="d-flex gap-2 mt-1">';
    html += '<button type="button" class="btn btn-sm btn-primary py-0 px-2" data-step-action="inline-save" data-step-id="' + esc(step.id) + '">Save</button>';
    html += '<button type="button" class="btn btn-sm btn-outline-secondary py-0 px-2" data-step-action="inline-cancel">Cancel</button>';
    html += '</div></div>';
    return html;
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
    markOrderDirty();
    closeBootstrapModal('order-edit-modal');
    renderCanvas();
  });

  var orderAddKindSelect = document.getElementById('order-add-kind');
  if (orderAddKindSelect) {
    orderAddKindSelect.addEventListener('change', function () {
      renderOrderAddBody(orderAddKindSelect.value);
    });
  }

  document.getElementById('order-add-save').addEventListener('click', function () {
    if (!_pendingOrderInsert) return;
    var kindEl = document.getElementById('order-add-kind');
    var kind = kindEl ? kindEl.value : 'screen';
    var newStep = createOrderStep(kind);

    var invokeEl = document.getElementById('order-add-invoke');
    var gatherEl = document.getElementById('order-add-gather-list');
    var conditionEl = document.getElementById('order-add-condition');
    var valueEl = document.getElementById('order-add-value');
    var codeEl = document.getElementById('order-add-code');

    if (kind === 'screen' || kind === 'function') {
      var invokeVal = invokeEl ? String(invokeEl.value || '').trim() : '';
      if (!invokeVal) return;
      newStep.invoke = invokeVal;
      newStep.summary = invokeVal;
    } else if (kind === 'gather') {
      var gatherVar = gatherEl ? String(gatherEl.value || '').trim() : '';
      if (!gatherVar) return;
      newStep.invoke = gatherVar + '.gather()';
      newStep.summary = 'Gather ' + gatherVar + ' list';
    } else if (kind === 'condition') {
      var conditionVal = conditionEl ? String(conditionEl.value || '').trim() : '';
      if (!conditionVal) return;
      newStep.condition = conditionVal;
      newStep.summary = conditionVal;
    } else if (kind === 'section') {
      var sectionVal = valueEl ? String(valueEl.value || '').trim() : '';
      if (!sectionVal) return;
      newStep.value = sectionVal;
      newStep.summary = 'Section: ' + sectionVal;
    } else if (kind === 'progress') {
      var progressRaw = valueEl ? String(valueEl.value || '').trim() : '';
      var parsed = parseInt(progressRaw || '0', 10);
      if (!Number.isFinite(parsed)) parsed = 0;
      var bounded = Math.max(0, Math.min(100, parsed));
      newStep.value = String(bounded);
      newStep.summary = 'Progress: ' + bounded + '%';
    } else {
      var codeVal = codeEl ? String(codeEl.value || '').trim() : '';
      if (!codeVal) return;
      newStep.code = codeVal;
      newStep.summary = codeVal.split('\n')[0].slice(0, 60);
    }

    insertOrderStepAtLocation(newStep, _pendingOrderInsert.parentStepId, _pendingOrderInsert.branch, _pendingOrderInsert.insertIndex);
    _lastInsertedOrderStepId = newStep.id;
    _pendingOrderInsert = null;
    syncActiveOrderStepMap();
    markOrderDirty();
    closeBootstrapModal('order-add-modal');
    renderCanvas();
    clearInsertedStepHighlightSoon(newStep.id);
  });

  // -------------------------------------------------------------------------
  // Select change handlers
  // -------------------------------------------------------------------------
  projectSelect.addEventListener('change', function () {
    var nextProject = projectSelect.value;
    if (nextProject !== state.project && blockUnsavedSectionNavigation()) {
      projectSelect.value = state.project || '';
      return;
    }
    stashCurrentEditorState();
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
    stashCurrentEditorState();
    state.filename = fileSelect.value;
    state.selectedBlockId = null;
    loadFile();
  });

  searchInput.addEventListener('input', function () {
    state.searchQuery = searchInput.value;
    if (isInterviewView()) {
      var selected = getBlockById(state.selectedBlockId);
      if (!selected || !isBlockVisibleInOutline(selected)) {
        state.selectedBlockId = getDefaultVisibleBlockId();
      }
      renderCanvas();
    }
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
  window.addEventListener('beforeunload', function (e) {
    if (!state.dirty && !state.sectionDirty) return;
    e.preventDefault();
    e.returnValue = '';
  });

  init();
})();
