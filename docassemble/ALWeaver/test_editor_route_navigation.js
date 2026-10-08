const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, 'data/static/editor.js'),
  'utf8',
);

function extractFunction(name) {
  const match = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`).exec(
    source,
  );
  assert.ok(match, `could not find function ${name}`);
  const open = source.indexOf('{', match.index);
  let depth = 0;
  let quote = null;
  let lineComment = false;
  let blockComment = false;
  let escaped = false;
  for (let i = open; i < source.length; i += 1) {
    const ch = source[i];
    const next = source[i + 1];
    if (lineComment) {
      if (ch === '\n') lineComment = false;
      continue;
    }
    if (blockComment) {
      if (ch === '*' && next === '/') {
        blockComment = false;
        i += 1;
      }
      continue;
    }
    if (quote) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '/' && next === '/') {
      lineComment = true;
      i += 1;
    } else if (ch === '/' && next === '*') {
      blockComment = true;
      i += 1;
    } else if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch;
    } else if (ch === '{') {
      depth += 1;
    } else if (ch === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(match.index, i + 1);
    }
  }
  throw new Error(`unterminated function ${name}`);
}

function extractPopstateHandler() {
  const marker = "window.addEventListener('popstate', function (event) {";
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, 'could not find popstate handler');
  const endMarker = '\n  });\n\n  var RECENT_PROJECTS_STORAGE_KEY';
  const end = source.indexOf(endMarker, start);
  assert.notEqual(end, -1, 'could not find end of popstate handler');
  return source.slice(start, end + '\n  });'.length);
}

function makeHarness({ dirty = false } = {}) {
  let popstate = null;
  const historyEntries = [
    {
      url: 'http://localhost/al/editor/projects/one',
      state: { alEditorIndex: 0 },
    },
  ];
  let pointer = 0;
  const transitions = [];
  const prompts = [];
  const decisions = [];
  const applied = [];
  let currentDirty = dirty;
  const history = {
    get state() {
      return historyEntries[pointer].state;
    },
    get length() {
      return historyEntries.length;
    },
    pushState(stateValue, _title, path) {
      historyEntries.splice(pointer + 1);
      historyEntries.push({
        url: new URL(path, historyEntries[pointer].url).href,
        state: stateValue,
      });
      pointer += 1;
      transitions.push('push');
    },
    replaceState(stateValue, _title, path) {
      historyEntries[pointer] = {
        url: new URL(path, historyEntries[pointer].url).href,
        state: stateValue,
      };
      transitions.push('replace');
    },
    go(delta) {
      const target = Math.max(
        0,
        Math.min(historyEntries.length - 1, pointer + delta),
      );
      if (target === pointer) return;
      pointer = target;
      popstate({ state: historyEntries[pointer].state });
    },
  };
  const window = {
    history,
    addEventListener(name, handler) {
      if (name === 'popstate') popstate = handler;
    },
    get location() {
      const url = new URL(historyEntries[pointer].url);
      return { href: url.href, pathname: url.pathname };
    },
  };
  const state = {
    project: 'P',
    filename: null,
    selectedBlockId: null,
    currentView: 'interview',
    canvasMode: 'project-selector',
    templatesMode: 'files',
    sectionSelectedFile: {
      templates: null,
      modules: null,
      static: null,
      data: null,
    },
  };
  const context = vm.createContext({
    URL,
    window,
    state,
    router: {
      routeForState(route) {
        if (route.mode === 'project-selector') return '/al/editor';
        return `/al/editor/projects/${route.project || 'none'}${route.filename ? `/interviews/${route.filename}` : ''}`;
      },
      parseRoute(pathname) {
        return {
          project: pathname.endsWith('/two') ? 'two' : 'one',
          view: 'interview',
          mode: 'question',
        };
      },
    },
    routeReady: true,
    routeApplying: false,
    routeSequence: 0,
    routeSyncQueued: false,
    routeReplaceNext: false,
    routeError: null,
    routeIndex: 0,
    routeCommittedUrl: historyEntries[0].url,
    routeRestoring: null,
    routeAcceptedPop: null,
    _pendingNavigationAction: null,
    _pendingNavigationDismissal: null,
    loadedInterviewKey: null,
    loadingFilesProject: null,
    dirtyState: { activate() {} },
    routeForState: undefined,
    dismissTransientTools() {},
    applyEditorRoute(route) {
      applied.push(route);
    },
    applied,
    stashCurrentEditorState() {
      return true;
    },
    hasUnsavedChanges() {
      return currentDirty;
    },
    promptAndSaveUnsavedChanges(label) {
      prompts.push(label);
      return new Promise((resolve) => decisions.push(resolve));
    },
    setDirty(value) {
      currentDirty = value;
    },
    get pointer() {
      return pointer;
    },
    transitions,
    prompts,
    decisions,
  });
  vm.runInContext(
    [
      extractFunction('editorRoute'),
      extractFunction('interviewKey'),
      extractFunction('commitEditorRoute'),
      extractFunction('scheduleEditorRoute'),
      extractFunction('deferNavigationForUnsavedChanges'),
      extractPopstateHandler(),
    ].join('\n'),
    context,
  );
  return context;
}

function makeHydrationHarness() {
  const pendingLoads = {};
  const renderedProjects = [];
  const committedProjects = [];
  const state = {
    projects: ['P'],
    project: 'P',
    files: [],
    filename: null,
    blocks: [],
    selectedBlockId: null,
    currentView: 'interview',
    canvasMode: 'project-selector',
    templatesMode: 'files',
    searchQuery: '',
    fullYamlTab: 'full',
    questionEditMode: 'preview',
    sectionSelectedFile: {
      templates: null,
      modules: null,
      static: null,
      data: null,
    },
    jumpTarget: 'questions',
  };
  const context = vm.createContext({
    state,
    BOOT: { features: {} },
    router: {
      routeForState() {
        return '/al/editor';
      },
    },
    routeSequence: 0,
    routeApplying: false,
    routeError: null,
    loadedInterviewKey: null,
    routeFailure(message) {
      this.routeError = { message };
    },
    interviewKey: null,
    resetProjectNavigation() {},
    searchInput: { value: '' },
    populateProjects() {},
    loadFiles(route) {
      return new Promise((resolve) => {
        pendingLoads[route.filename] = resolve;
      });
    },
    isSupersededRequest() {
      return false;
    },
    loadSectionFiles() {
      return Promise.resolve();
    },
    getBlockById() {
      return null;
    },
    isBlockVisibleInOutline() {
      return true;
    },
    syncJumpSelect() {},
    loadAssemblyLineSettings() {
      return Promise.resolve();
    },
    loadKilnTestsOverview() {
      return Promise.resolve();
    },
    enterOrderBuilder() {
      return Promise.resolve();
    },
    dirtyState: { activate() {} },
    populateFiles() {},
    renderOutline() {},
    renderCanvas() {
      renderedProjects.push(state.filename);
    },
    commitEditorRoute() {
      committedProjects.push(state.filename);
    },
    pendingLoads,
    renderedProjects,
    committedProjects,
  });
  vm.runInContext(
    [extractFunction('interviewKey'), extractFunction('applyEditorRoute')].join(
      '\n',
    ),
    context,
  );
  return context;
}

async function flushMicrotasks() {
  await Promise.resolve();
  await Promise.resolve();
}

async function testProjectFileDefaultPrefersMainYaml() {
  async function openProject(files, filename, requestedRoute) {
    const loaded = [];
    let context;
    context = vm.createContext({
      state: {
        project: 'P',
        files: [],
        filename: filename || null,
        selectedBlockId: 'old-block',
      },
      routeSequence: 0,
      loadingFilesProject: null,
      cancelRouteHydration() {},
      apiGet: async () => ({ success: true, data: { files } }),
      rememberRecentProject() {},
      populateProjects() {},
      populateFiles() {},
      refreshGithubSyncAction() {},
      moduleRestart: { refresh() {} },
      loadFile(route) {
        loaded.push({ filename: context.state.filename, route });
        return Promise.resolve();
      },
      loadSectionFiles() {},
      renderOutline() {},
      renderCanvas() {},
      routeFailure(message) {
        throw new Error(message);
      },
      isSupersededRequest() {
        return false;
      },
      swallowNavigationLoadError() {},
    });
    vm.runInContext(extractFunction('loadFiles'), context);
    await context.loadFiles(requestedRoute);
    return { filename: context.state.filename, loaded };
  }

  const files = [{ filename: 'helper.yml' }, { filename: 'main.yml' }];
  assert.equal(
    (await openProject(files, null)).filename,
    'main.yml',
    'main.yml is the default even when another interview sorts first',
  );
  assert.equal(
    (await openProject([{ filename: 'helper.yml' }], null)).filename,
    'helper.yml',
    'projects without main.yml keep the first-file fallback',
  );
  assert.equal(
    (await openProject(files, 'helper.yml')).filename,
    'helper.yml',
    'an existing selection is preserved',
  );
  assert.equal(
    (
      await openProject(files, 'helper.yml', {
        filename: 'helper.yml',
        blockId: 'target',
      })
    ).filename,
    'helper.yml',
    'a valid explicit route is preserved',
  );
}

async function testCleanBackForward() {
  const h = makeHarness();
  h.state.canvasMode = 'question';
  h.state.filename = 'a.yml';
  h.commitEditorRoute(false);
  h.state.filename = 'b.yml';
  h.commitEditorRoute(false);
  assert.equal(h.pointer, 2);
  h.window.history.go(-1);
  assert.equal(h.pointer, 1);
  assert.equal(h.applied.length, 1);
  h.window.history.go(1);
  assert.equal(h.pointer, 2);
  assert.equal(h.applied.length, 2);
}

function testDirtyStayRestoresHistoryPointer() {
  const h = makeHarness({ dirty: true });
  h.state.canvasMode = 'question';
  h.state.filename = 'a.yml';
  h.commitEditorRoute(false);
  h.state.filename = 'b.yml';
  h.commitEditorRoute(false);
  h.window.history.go(-1);
  assert.equal(
    h.pointer,
    2,
    'Stay restores the URL pointer to the current entry',
  );
  assert.equal(h.routeIndex, 2);
  assert.equal(h.applied.length, 0);
  assert.ok(h.prompts.length >= 1);
}

async function testSaveAndDiscardCanAcceptTraversal() {
  for (const decision of ['save', 'discard']) {
    const h = makeHarness({ dirty: true });
    h.state.canvasMode = 'question';
    h.state.filename = 'a.yml';
    h.commitEditorRoute(false);
    h.state.filename = 'b.yml';
    h.commitEditorRoute(false);
    h.window.history.go(-1);
    assert.equal(
      h.prompts.length,
      1,
      `${decision} should show the unsaved changes prompt`,
    );
    assert.equal(h.decisions.length, 1);
    h.setDirty(false);
    // A successful Save and an explicit Discard both resolve the prompt with
    // permission to continue the same queued history traversal.
    h.decisions[0](true);
    await flushMicrotasks();
    assert.equal(
      h.pointer,
      1,
      `${decision} should traverse to the requested entry`,
    );
    assert.equal(h.applied.length, 1);
  }
}

async function testRejectedSaveStaysOnCurrentEntry() {
  const h = makeHarness({ dirty: true });
  h.state.canvasMode = 'question';
  h.state.filename = 'a.yml';
  h.commitEditorRoute(false);
  h.state.filename = 'b.yml';
  h.commitEditorRoute(false);
  h.window.history.go(-1);
  assert.equal(h.decisions.length, 1);
  h.decisions[0](false);
  await flushMicrotasks();
  // Failed Save or prompt dismissal does not call the queued resume.
  assert.equal(h.pointer, 2);
  assert.equal(h.applied.length, 0);
  assert.equal(h.routeIndex, 2);
}

async function testDuplicatePushesAndHydrationGate() {
  const h = makeHarness();
  h.state.canvasMode = 'question';
  h.state.filename = 'ready.yml';
  h.routeReady = true;
  h.scheduleEditorRoute();
  await flushMicrotasks();
  assert.equal(
    h.transitions.filter((item) => item === 'push').length,
    0,
    'route waits for interview hydration',
  );
  h.loadedInterviewKey = JSON.stringify(['P', 'ready.yml']);
  h.scheduleEditorRoute();
  await flushMicrotasks();
  assert.equal(h.transitions.filter((item) => item === 'push').length, 1);
  h.commitEditorRoute(false);
  assert.equal(
    h.transitions.filter((item) => item === 'push').length,
    1,
    'same route must not add duplicate history entries',
  );
}

async function testSupersededInterviewHydrationCannotCommit() {
  const h = makeHydrationHarness();
  const first = h.applyEditorRoute({
    project: 'P',
    filename: 'first.yml',
    blockId: null,
    view: 'interview',
    mode: 'question',
    sectionFilename: null,
  });
  const second = h.applyEditorRoute({
    project: 'P',
    filename: 'second.yml',
    blockId: null,
    view: 'interview',
    mode: 'question',
    sectionFilename: null,
  });
  const rendersBeforeStaleCompletion = h.renderedProjects.length;
  h.pendingLoads['first.yml']();
  await first;
  assert.deepEqual(
    h.committedProjects,
    [],
    'stale hydration cannot commit its route',
  );
  assert.equal(
    h.renderedProjects.length,
    rendersBeforeStaleCompletion,
    'stale completion cannot render over the newer loading state',
  );
  h.pendingLoads['second.yml']();
  await second;
  assert.deepEqual(h.committedProjects, ['second.yml']);
  assert.deepEqual(h.renderedProjects, [
    'first.yml',
    'second.yml',
    'second.yml',
  ]);
}

// Validation asks the editor to stash its DOM while loading a deep link. The
// loading screen has no field rows, which must never mean "delete all fields".
function testLoadingAndOtherPanelsPreserveQuestionFields() {
  const fields = [{ label: 'Answer', field: 'answer', datatype: 'text' }];
  const block = { type: 'question', data: { question: 'Question', fields } };
  const h = vm.createContext({
    routeApplying: true,
    state: {
      canvasMode: 'question',
      questionEditMode: 'preview',
      questionBlockTab: 'screen',
    },
    document: { querySelectorAll: () => [] },
    window: { ALWeaverSerializers: { questionScreenType: () => 'fields' } },
    _stashFullYamlContent() {},
    isInterviewView: () => true,
    getSelectedBlock: () => block,
    isQuestionEditorBlock: () => true,
    _generatedALFieldSets: () => [],
    _syncGeneratedALFieldSets() {},
    syncQuestionMetaToData: () => true,
  });
  vm.runInContext(
    [
      extractFunction('stashCurrentEditorState'),
      extractFunction('syncFieldsToData'),
    ].join('\n'),
    h,
  );
  h.stashCurrentEditorState();
  assert.strictEqual(
    block.data.fields,
    fields,
    'loading must preserve loaded fields',
  );
  h.routeApplying = false;
  for (const mode of [
    'full-yaml',
    'assemblyline-settings',
    'tests-overview',
    'runtime-inspector',
  ]) {
    h.state.canvasMode = mode;
    h.stashCurrentEditorState();
    assert.strictEqual(
      block.data.fields,
      fields,
      mode + ' must not read an absent question form',
    );
  }
  h.state.canvasMode = 'question';
  h.stashCurrentEditorState();
  assert.equal(
    block.data.fields.length,
    0,
    'an actual empty question form can still remove its fields',
  );
}

(async () => {
  testLoadingAndOtherPanelsPreserveQuestionFields();
  await testProjectFileDefaultPrefersMainYaml();
  await testCleanBackForward();
  testDirtyStayRestoresHistoryPointer();
  await testSaveAndDiscardCanAcceptTraversal();
  await testRejectedSaveStaysOnCurrentEntry();
  await testDuplicatePushesAndHydrationGate();
  await testSupersededInterviewHydrationCannotCommit();
  console.log('editor route navigation tests passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
