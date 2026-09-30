/* Pure URL parsing and serialization for the Weaver editor. */
(function (global) {
  'use strict';

  var BASE = '/al/editor';
  var VIEWS = ['interview', 'templates', 'modules', 'static', 'data'];
  var MODES = [
    'project-selector',
    'new-project',
    'question',
    'full-yaml',
    'order-builder',
    'assemblyline-settings',
    'tests-overview',
    'runtime-inspector',
    'documents',
  ];

  function decodePart(part) {
    if (!part) return null;
    var decoded;
    try {
      decoded = decodeURIComponent(part);
    } catch {
      return null;
    }
    if (
      !decoded ||
      decoded === '.' ||
      decoded === '..' ||
      decoded.indexOf('/') !== -1 ||
      decoded.indexOf('\\') !== -1
    ) {
      return null;
    }
    return decoded;
  }

  function route(view, mode, project, filename, blockId, sectionFilename) {
    return {
      project: project,
      filename: filename,
      blockId: blockId,
      view: view,
      mode: mode,
      sectionFilename: sectionFilename,
    };
  }

  // Block IDs are opaque Docassemble values, not filenames. Protect separators
  // from the server's URL decoding and dot segments from browser normalization.
  // Escape literal leading tildes too, so the marker cannot collide with an ID.
  function encodeBlockId(value) {
    if (typeof value !== 'string' || !value) return null;
    if (/[/\\]/.test(value) || /^\.{1,2}$/.test(value) || value[0] === '~')
      return '~' + encodeURIComponent(encodeURIComponent(value));
    return encodeURIComponent(value);
  }

  function decodeBlockId(part) {
    if (part[0] !== '~') return decodePart(part);
    try {
      return decodeURIComponent(decodeURIComponent(part.slice(1))) || null;
    } catch {
      return null;
    }
  }

  function parseRoute(pathname) {
    if (
      typeof pathname !== 'string' ||
      pathname.indexOf('?') !== -1 ||
      pathname.indexOf('#') !== -1
    ) {
      return null;
    }
    var path = pathname;
    while (path.length > 1 && path.endsWith('/')) path = path.slice(0, -1);
    if (path !== BASE && path.indexOf(BASE + '/') !== 0) return null;
    var suffix = path === BASE ? '' : path.slice(BASE.length + 1);
    if (!suffix)
      return route('interview', 'project-selector', null, null, null, null);
    var parts = suffix.split('/');
    var decoded = [];
    for (var i = 0; i < parts.length; i += 1) {
      var isBlockId =
        i === 5 &&
        parts.length === 6 &&
        decoded[0] === 'projects' &&
        decoded[2] === 'interviews' &&
        decoded[4] === 'blocks';
      var value = isBlockId ? decodeBlockId(parts[i]) : decodePart(parts[i]);
      if (value === null) return null;
      decoded.push(value);
    }
    if (decoded.length === 1 && decoded[0] === 'create') {
      return route('interview', 'new-project', null, null, null, null);
    }
    if (decoded[0] === 'projects' && decoded.length === 1) {
      return route('interview', 'project-selector', null, null, null, null);
    }
    if (decoded[0] !== 'projects' || decoded.length < 2) return null;
    var project = decoded[1];
    if (decoded.length === 3 && decoded[2] === 'documents') {
      return route('templates', 'documents', project, null, null, null);
    }
    if (decoded.length === 2) {
      return route('interview', 'question', project, null, null, null);
    }
    if (decoded.length < 3) return null;
    var section = decoded[2];
    var editorModes = {
      source: ['interview', 'full-yaml'],
      order: ['interview', 'order-builder'],
      settings: ['interview', 'assemblyline-settings'],
      tests: ['interview', 'tests-overview'],
      debug: ['interview', 'runtime-inspector'],
    };
    if (section === 'interviews') {
      if (decoded.length === 3)
        return route('interview', 'question', project, null, null, null);
      if (decoded.length < 4) return null;
      var interview = decoded[3];
      if (decoded.length === 4)
        return route('interview', 'question', project, interview, null, null);
      if (decoded.length === 5 && decoded[4] === 'blocks')
        return route('interview', 'question', project, interview, null, null);
      if (decoded.length === 5 && decoded[4] === 'documents') {
        return route('templates', 'documents', project, interview, null, null);
      }
      if (decoded.length === 6 && decoded[4] === 'blocks') {
        return route(
          'interview',
          'question',
          project,
          interview,
          decoded[5],
          null,
        );
      }
      if (
        decoded.length === 5 &&
        Object.prototype.hasOwnProperty.call(editorModes, decoded[4])
      ) {
        return route(
          'interview',
          editorModes[decoded[4]][1],
          project,
          interview,
          null,
          null,
        );
      }
      return null;
    }
    var views = {
      templates: 'templates',
      modules: 'modules',
      static: 'static',
      sources: 'data',
    };
    if (Object.prototype.hasOwnProperty.call(views, section)) {
      if (decoded.length > 4) return null;
      return route(
        views[section],
        'question',
        project,
        null,
        null,
        decoded[3] || null,
      );
    }
    return null;
  }

  function encodePart(value) {
    if (
      typeof value !== 'string' ||
      !value ||
      value === '.' ||
      value === '..' ||
      /[\\/]/.test(value)
    ) {
      return null;
    }
    return encodeURIComponent(value);
  }

  function routeForState(value) {
    if (
      !value ||
      typeof value !== 'object' ||
      VIEWS.indexOf(value.view) === -1 ||
      MODES.indexOf(value.mode) === -1
    ) {
      return null;
    }
    var project = value.project == null ? null : encodePart(value.project);
    var filename = value.filename == null ? null : encodePart(value.filename);
    var blockId = value.blockId == null ? null : encodeBlockId(value.blockId);
    var sectionFilename =
      value.sectionFilename == null ? null : encodePart(value.sectionFilename);
    if (
      (value.project != null && project === null) ||
      (value.filename != null && filename === null) ||
      (value.blockId != null && blockId === null) ||
      (value.sectionFilename != null && sectionFilename === null)
    )
      return null;
    if (value.mode === 'project-selector')
      return value.project == null ? BASE : null;
    if (value.mode === 'new-project')
      return value.project == null ? BASE + '/create' : null;
    if (value.mode === 'documents') {
      if (!project) return null;
      return filename
        ? BASE +
            '/projects/' +
            project +
            '/interviews/' +
            filename +
            '/documents'
        : BASE + '/projects/' + project + '/documents';
    }
    if (!project) return null;
    var root = BASE + '/projects/' + project;
    if (value.mode === 'question') {
      if (value.view === 'interview') {
        if (!filename && !blockId) return root;
        if (!filename) return null;
        return (
          root +
          '/interviews/' +
          filename +
          (blockId ? '/blocks/' + blockId : '')
        );
      }
      var names = {
        templates: 'templates',
        modules: 'modules',
        static: 'static',
        data: 'sources',
      };
      if (!names[value.view]) return null;
      if (blockId || filename) return null;
      return (
        root +
        '/' +
        names[value.view] +
        (sectionFilename ? '/' + sectionFilename : '')
      );
    }
    var modeNames = {
      'full-yaml': 'source',
      'order-builder': 'order',
      'assemblyline-settings': 'settings',
      'tests-overview': 'tests',
      'runtime-inspector': 'debug',
    };
    if (!modeNames[value.mode] || value.view !== 'interview' || blockId)
      return null;
    if (!filename || sectionFilename) return null;
    return root + '/interviews/' + filename + '/' + modeNames[value.mode];
  }

  global.ALWeaverRouter = {
    parseRoute: parseRoute,
    routeForState: routeForState,
  };
})(typeof window === 'undefined' ? globalThis : window);
