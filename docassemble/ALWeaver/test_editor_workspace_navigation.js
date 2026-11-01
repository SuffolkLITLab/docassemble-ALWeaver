const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, 'data/static/editor.js'),
  'utf8',
);

function extractFunction(name) {
  if (name === 'conciseBlockTitle') {
    const start = source.indexOf('  function conciseBlockTitle(');
    return source.slice(start, source.indexOf('\n  function ', start + 1));
  }
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

const state = {
  project: 'one',
  filename: 'main.yml',
  currentView: 'interview',
  canvasMode: 'question',
  questionEditMode: 'yaml',
  selectedBlockId: 'about',
  sectionSelectedFile: {},
  fullYamlStash: {},
  rawYaml: '---\nid: about\nquestion: About you\n',
  jumpTarget: 'all',
  searchQuery: '',
};
const block = {
  id: 'about',
  title: 'About you',
  type: 'question',
  yaml: state.rawYaml,
};
state.blocks = [block];
let outlineRenders = 0;
let canvasRenders = 0;
let revealed = null;
const status = { textContent: '' };
const h = vm.createContext({
  state,
  workspaceReturn: null,
  sourceCursorBlockId: 'about',
  sourceWorkspacePositions: {},
  _sourceEditors: {},
  isInterviewView: () => state.currentView === 'interview',
  getBlockById: (id) => (id === block.id ? block : null),
  getSelectedBlock: () => block,
  isQuestionEditorBlock: (b) => b.type === 'question',
  isTemplateEditorBlock: (b) => b.type === 'template',
  outlineList: { scrollTop: 73 },
  searchInput: { value: '' },
  syncJumpSelect() {},
  renderOutline() {
    outlineRenders++;
  },
  renderCanvas() {
    canvasRenders++;
  },
  renderWorkspaceLocation() {},
  dirtyState: { setActiveBlock() {} },
  document: { getElementById: () => status },
});
for (const name of [
  'blockRepresentationName',
  'sourceWorkspaceIdentity',
  '_stashFullYamlContent',
  'resetOutlineForFullFile',
  'enterFullYaml',
  'rememberWorkspace',
  'validWorkspaceReturn',
  'workspaceReturnLabel',
  'restoreWorkspace',
  'editingLocation',
  'applyOutlineFilter',
  'sourceBlockRange',
  'updateSourceCursorBlock',
  'sourceBlockActionLabel',
  'conciseBlockTitle',
  'sourceBlockMenu',
  'revealBlockInFullSource',
]) {
  vm.runInContext(extractFunction(name), h);
}
function mount(content) {
  h._sourceEditors['full-source-editor'] = {
    identity: h.sourceWorkspaceIdentity('full-source-editor'),
    getValue: () => content,
    reveal: (from, to) => {
      revealed = [from, to];
    },
  };
}
// Block YAML -> whole file -> Templates -> Interview -> whole file.
h.rememberWorkspace();
state.canvasMode = 'full-yaml';
mount(state.rawYaml);
h._stashFullYamlContent();
assert.equal(state.fullYamlStash.full, state.rawYaml);
state.currentView = 'templates';
delete h._sourceEditors['full-source-editor'];
h._stashFullYamlContent();
state.currentView = 'interview';
h._stashFullYamlContent();
assert.equal(
  state.fullYamlStash.full,
  state.rawYaml,
  'missing editor must not overwrite real source',
);
mount('');
h._stashFullYamlContent();
assert.equal(
  state.fullYamlStash.full,
  '',
  'intentional empty buffer is real content',
);
state.filename = 'other.yml';
h._stashFullYamlContent();
assert.equal(state.fullYamlStash.full, '', 'foreign editor must not be read');
state.filename = 'main.yml';
assert.equal(h.workspaceReturnLabel(), 'Return to About you · Block YAML');
state.questionEditMode = 'preview';
h.restoreWorkspace();
assert.equal(state.questionEditMode, 'yaml');
assert.equal(state.selectedBlockId, 'about');
assert.equal(h.outlineList.scrollTop, 73);
assert.equal(h.editingLocation().resource, 'About you');
state.canvasMode = 'full-yaml';
h.applyOutlineFilter('code');
assert.equal(state.canvasMode, 'full-yaml');
assert.equal(state.selectedBlockId, 'about');
assert.equal(canvasRenders, 0, 'filtering must never replace the editor');
mount(state.rawYaml);
h.revealBlockInFullSource('about');
assert.deepEqual(revealed, [0, state.rawYaml.length]);
assert.equal(state.canvasMode, 'full-yaml');
assert.equal(status.textContent, '');
revealed = null;
mount(state.rawYaml + '# unsaved\n');
h.revealBlockInFullSource('about');
assert.equal(revealed, null);
assert.match(status.textContent, /last parsed version/);
state.filename = 'other.yml';
assert.equal(h.workspaceReturnLabel(), 'Open blocks');
console.log('editor workspace navigation tests passed');

// Exercise actual click handlers, including idempotence and dirty-state guards.
Object.assign(h, {
  window: { WeaverMarkdown: { source: (target) => target } },
  hideTypeaheadMenu() {},
  stashCurrentEditorState: () => true,
  deferNavigationForUnsavedChanges: () => false,
  setActiveTopTab() {},
  loadSectionFiles() {},
  isBlockVisibleInOutline: () => true,
  getDefaultBlockId: () => 'about',
});
h.document.querySelector = () => null;
vm.runInContext(
  source.slice(
    source.indexOf('  function handleEditorClick(e)'),
    source.indexOf(
      "  document.addEventListener('dblclick'",
      source.indexOf('  function handleEditorClick(e)'),
    ),
  ),
  h,
);
function click(action, attributes = {}) {
  const target = {
    id: attributes.id || '',
    classList: { contains: () => false },
    closest(selector) {
      if (selector === '[data-action]' && action) return target;
      if (selector === '.editor-validation-item' && attributes.validation)
        return target;
      if (
        selector === '.editor-outline-item' &&
        attributes['data-section-filename']
      )
        return target;
      if (
        selector === '.editor-top-tab, .editor-view-switch' &&
        attributes['data-view']
      )
        return target;
      if (
        selector === '[data-question-mode]' &&
        attributes['data-question-mode']
      )
        return target;
      return null;
    },
    getAttribute: (name) =>
      name === 'data-action' ? action : attributes[name],
    matches: () => false,
  };
  h.handleEditorClick({ target, preventDefault() {} });
}
state.filename = 'main.yml';
state.canvasMode = 'question';
state.questionEditMode = 'yaml';
click('open-full-yaml');
assert.equal(state.canvasMode, 'full-yaml');
const beforeRepeat = canvasRenders;
click('open-full-yaml');
assert.equal(canvasRenders, beforeRepeat);
click(null, { 'data-view': 'templates' });
assert.equal(state.currentView, 'templates');
click(null, { 'data-view': 'interview' });
click('open-full-yaml');
assert.equal(state.canvasMode, 'full-yaml');
let guarded = 0;
h.deferNavigationForUnsavedChanges = () => {
  guarded++;
  return true;
};
click('open-block-workspace');
assert.equal(guarded, 1);
assert.equal(state.canvasMode, 'full-yaml', 'Stay/failed save keeps source');
h.deferNavigationForUnsavedChanges = () => false;
click(null, { id: 'back-to-question' });
assert.equal(state.canvasMode, 'question');
assert.equal(state.questionEditMode, 'preview');
const beforeSelected = canvasRenders;
click(null, { 'data-question-mode': 'preview' });
assert.equal(
  canvasRenders,
  beforeSelected,
  'selected representation must not recreate its buffer',
);
console.log('editor workspace click tests passed');

// Render the real full-source surface after disposing it in another section.
h.canvasContent = { innerHTML: '' };
h.esc = (value) => String(value || '');
h.initSourceEditor = (callback) => callback();
h.createSourceEditor = (_id, content) => {
  mount(content);
  return h._sourceEditors['full-source-editor'];
};
state.blocks = [block];
h.getOrderTargets = () => [];
vm.runInContext(extractFunction('renderFullYaml'), h);
state.canvasMode = 'full-yaml';
state.fullYamlStash = {};
h.renderFullYaml();
assert.equal(h._sourceEditors['full-source-editor'].getValue(), state.rawYaml);
h._stashFullYamlContent();
state.currentView = 'templates';
delete h._sourceEditors['full-source-editor'];
h._stashFullYamlContent();
state.currentView = 'interview';
h._stashFullYamlContent();
h.renderFullYaml();
assert.equal(h._sourceEditors['full-source-editor'].getValue(), state.rawYaml);
assert.doesNotMatch(h.canvasContent.innerHTML, /data-yaml-tab/);
console.log('editor full-source round-trip rendering passed');

// Use production selection logic: filtering the list must not redirect saves
// or validation to another block, including when nothing matches the filter.
state.blocks = [block, { id: 'other', type: 'code', yaml: 'code: pass\n' }];
h.getBlockById = (id) =>
  state.blocks.find((candidate) => candidate.id === id) || null;
h.filteredBlocks = () => [state.blocks[1]];
vm.runInContext(extractFunction('getDefaultBlockId'), h);
vm.runInContext(extractFunction('getSelectedBlock'), h);
state.selectedBlockId = 'about';
assert.equal(h.getSelectedBlock(), block);
h.filteredBlocks = () => [];
assert.equal(h.getSelectedBlock(), block);
state.selectedBlockId = null;
assert.equal(h.getDefaultBlockId(), 'about');
assert.equal(
  h.getSelectedBlock(),
  block,
  'nonempty files still have a workspace when filtered out',
);

// Non-menu entry points replace stale contextual returns and always pick full scope.
state.selectedBlockId = 'about';
state.canvasMode = 'question';
state.questionEditMode = 'yaml';
h._reviewSync = { data: { full_yaml: state.rawYaml } };
h.closeBootstrapModal = () => {};
h.markInterviewDirty = () => {};
vm.runInContext(extractFunction('openReviewSyncInFullYaml'), h);
h.openReviewSyncInFullYaml();
assert.equal(h.workspaceReturnLabel(), 'Open blocks');
state.canvasMode = 'question';
state.selectedBlockId = 'other';
state.questionEditMode = 'preview';
h.openReviewSyncInFullYaml();
assert.equal(h.workspaceReturnLabel(), 'Open blocks');
h.enterFullYaml();
assert.equal(
  h.workspaceReturnLabel(),
  'Open blocks',
  'cross-file search must not invent a return origin',
);

// Duplicate source text is not an unsaved-buffer problem.
state.rawYaml = block.yaml + block.yaml;
mount(state.rawYaml);
h.revealBlockInFullSource('about');
assert.match(status.textContent, /cannot be located uniquely/);
assert.doesNotMatch(status.textContent, /Save your YAML/);
console.log(
  'editor filter selection and alternate source entry regressions passed',
);

// Re-selecting a section file must not prompt, recreate the editor, or drop its cursor.
state.currentView = 'modules';
state.sectionSelectedFile.modules = 'helper.py';
const beforeSectionRepeat = canvasRenders;
h.deferNavigationForUnsavedChanges = () => {
  throw new Error('same file must not prompt');
};
click(null, { 'data-section-filename': 'helper.py' });
assert.equal(canvasRenders, beforeSectionRepeat);
state.currentView = 'templates';
state.sectionSelectedFile.templates = 'form.docx';
state.templatesMode = 'files';
click(null, { 'data-section-filename': 'form.docx' });
assert.equal(canvasRenders, beforeSectionRepeat);
state.templatesMode = 'documents';
let sectionGuarded = false;
h.deferNavigationForUnsavedChanges = () => {
  sectionGuarded = true;
  return true;
};
click(null, { 'data-section-filename': 'form.docx' });
assert.equal(
  sectionGuarded,
  true,
  'document setup -> file is a real guarded transition',
);

// Section cursor identity excludes unrelated interview filenames and blocks.
state.currentView = 'modules';
const moduleIdentity = h.sourceWorkspaceIdentity('section-file-source-editor');
state.filename = 'another.yml';
state.selectedBlockId = 'other';
assert.equal(
  h.sourceWorkspaceIdentity('section-file-source-editor'),
  moduleIdentity,
);
state.sectionSelectedFile.modules = 'different.py';
assert.notEqual(
  h.sourceWorkspaceIdentity('section-file-source-editor'),
  moduleIdentity,
);

// CRLF files use the exact offsets in CodeMirror's normalized LF buffer.
state.currentView = 'interview';
state.filename = 'main.yml';
state.canvasMode = 'full-yaml';
state.rawYaml = '---\r\nid: about\r\nquestion: About you\r\n';
block.yaml = state.rawYaml;
const normalized = state.rawYaml.replace(/\r\n/g, '\n');
mount(normalized);
revealed = null;
h.revealBlockInFullSource('about');
assert.deepEqual(revealed, [0, normalized.length]);
assert.equal(
  state.rawYaml,
  block.yaml,
  'navigation must not rewrite original source',
);

// Validation links for the same block still replace full-file scope and need a guard.
h.renderValidationDrawer = () => {};
state.selectedBlockId = 'about';
state.validationDock = 'bottom';
let validationGuarded = 0;
h.deferNavigationForUnsavedChanges = () => {
  validationGuarded++;
  return true;
};
click(null, { validation: true, 'data-block-id': 'about' });
assert.equal(validationGuarded, 1);
assert.equal(state.canvasMode, 'full-yaml');
assert.equal(h._sourceEditors['full-source-editor'].getValue(), normalized);
state.canvasMode = 'question';
const beforeValidationRepeat = canvasRenders;
click(null, { validation: true, 'data-block-id': 'about' });
assert.equal(validationGuarded, 1);
assert.equal(
  canvasRenders,
  beforeValidationRepeat,
  'same-block validation must not recreate a block buffer',
);

h.workspaceReturn = null;
state.selectedBlockId = null;
h.restoreWorkspace();
assert.equal(
  state.selectedBlockId,
  'about',
  'direct-link returns establish a real selected block',
);
console.log('editor review regressions passed');

// Parser ranges identify the second of two textually identical documents.
const duplicateSource = 'code: pass\n---\n\ncode: pass\n';
const secondDuplicate = { line_start: 3, line_end: 4 };
const duplicateRange = h.sourceBlockRange(
  duplicateSource,
  secondDuplicate,
  'code: pass',
);
assert.equal(duplicateRange.from, duplicateSource.indexOf('\n\n') + 1);
assert.equal(duplicateRange.to, duplicateSource.length - 1);
assert.equal(
  h.sourceBlockRange(
    duplicateSource,
    { line_start: 99, line_end: 100 },
    'code: pass',
  ),
  null,
);
console.log('editor parsed source-range regression passed');

state.currentView = 'interview';
state.canvasMode = 'order-builder';
state.activeOrderBlockId = 'other';
state.questionEditMode = 'preview';
h.deferNavigationForUnsavedChanges = () => false;
click(null, { id: 'order-to-raw' });
assert.equal(state.canvasMode, 'question');
assert.equal(state.selectedBlockId, 'other');
assert.equal(state.questionEditMode, 'yaml');
assert.doesNotMatch(source, /fullYamlTab|data-yaml-tab/);
console.log('order source uses the block workspace; full-file subsets removed');

state.canvasMode = 'question';
state.selectedBlockId = 'about';
state.questionEditMode = 'yaml';
state.jumpTarget = 'code';
state.searchQuery = 'no-matching-block';
h.searchInput.value = state.searchQuery;
h.enterFullYaml();
assert.equal(state.jumpTarget, 'all');
assert.equal(state.searchQuery, '');
assert.equal(h.searchInput.value, '');
assert.equal(h.workspaceReturn, null);
state.canvasMode = 'question';
assert.equal(h.editingLocation().fileMode, 'full-yaml');
state.questionEditMode = 'preview';
assert.equal(h.editingLocation().fileMode, 'question');
state.canvasMode = 'full-yaml';
assert.equal(h.editingLocation().fileMode, 'full-yaml');
console.log(
  'full-file source clears filters; YAML breadcrumbs retain representation',
);

// Cursor movement follows the current document, not the remembered origin.
const income = {
  id: 'income',
  title: 'Income',
  type: 'question',
  yaml: 'id: income\nquestion: Income\n',
};
block.yaml = 'id: about\nquestion: About you\n';
state.blocks = [block, income];
h.getBlockById = (id) => state.blocks.find((item) => item.id === id);
h.sourceCursorBlockId = null;
const cursorSource = block.yaml + '---\n' + income.yaml;
h.updateSourceCursorBlock(
  cursorSource,
  cursorSource.indexOf('question: Income'),
);
assert.equal(state.selectedBlockId, 'income');
assert.equal(h.sourceBlockActionLabel(), 'Edit Income visually');
h.updateSourceCursorBlock(cursorSource, 3);
assert.equal(state.selectedBlockId, 'about');
assert.equal(h.sourceBlockActionLabel(), 'Edit About you visually');
h.updateSourceCursorBlock('unrecognizable edited source', 2);
assert.equal(
  h.sourceCursorBlockId,
  null,
  'never offer a stale block for unknown source',
);
console.log(
  'PASS source cursor action follows the current block in both directions',
);

state.rawYaml = cursorSource + '\n# trailing comment\n';
h.updateSourceCursorBlock(state.rawYaml, state.rawYaml.length);
assert.equal(h.sourceCursorBlockId, 'income');
console.log('PASS trailing source comments retain the final block context');

h.PREVIEWABLE_BLOCK_TYPES = ['question', 'review', 'table'];
state.canvasMode = 'full-yaml';
h.sourceCursorBlockId = 'about';
assert.match(h.sourceBlockMenu(), /data-action="open-screen-preview">Preview/);
h.sourceCursorBlockId = null;
assert.match(h.sourceBlockMenu(), /data-action="open-screen-preview" disabled/);
assert.match(h.sourceBlockMenu(), /data-action="edit-source-block" disabled/);
console.log('PASS YAML menu actions use current block availability');

const makoBlock = {
  id: 'users there_is_another',
  data: {
    question:
      '% if represented:\nIs there another parent making this Petition with your client?\n% else:\nIs anyone else joining?\n% endif',
  },
};
assert.equal(
  h.conciseBlockTitle(makoBlock),
  'Is there another parent making this Petition…',
);
assert.equal(
  h.conciseBlockTitle({
    id: 'name',
    data: { question: 'Hello ${ user.name }' },
  }),
  'Hello …',
);
console.log('PASS source shortcut titles omit Mako syntax and stay concise');

// Route hydration can reset selection while the cursor returns to the same block.
state.selectedBlockId = 'about';
h.sourceCursorBlockId = 'income';
h.updateSourceCursorBlock(
  cursorSource,
  cursorSource.indexOf('question: Income'),
);
assert.equal(state.selectedBlockId, 'income');
console.log('PASS restored source cursor synchronizes a stale route selection');

state.canvasMode = 'full-yaml';
state.selectedBlockId = 'income';
h.rememberWorkspace();
state.canvasMode = 'assemblyline-settings';
assert.equal(h.workspaceReturnLabel(), 'Return to Full file YAML');
h.restoreWorkspace();
assert.equal(state.canvasMode, 'full-yaml');
assert.equal(state.selectedBlockId, 'income');
console.log('PASS Settings returns to its originating full-source workspace');

h.sourceCursorBlockId = 'income';
income.type = 'code';
assert.equal(h.sourceBlockActionLabel(), 'Edit Income in Python');
assert.match(h.sourceBlockMenu(), />Edit Python</);
income.type = 'metadata';
assert.equal(h.sourceBlockActionLabel(), 'Open Income · Block YAML');
assert.match(h.sourceBlockMenu(), />Open block YAML</);
income.type = 'question';
console.log(
  'PASS source actions accurately name non-visual editing destinations',
);

state.canvasMode = 'question';
state.questionEditMode = 'yaml';
state.selectedBlockId = 'about';
let blockYamlGuarded = 0;
h.deferNavigationForUnsavedChanges = () => {
  blockYamlGuarded++;
  return true;
};
click('edit-source-block');
assert.equal(blockYamlGuarded, 1);
assert.equal(state.questionEditMode, 'yaml');
console.log('PASS block-YAML kebab visual transition uses the unsaved guard');
