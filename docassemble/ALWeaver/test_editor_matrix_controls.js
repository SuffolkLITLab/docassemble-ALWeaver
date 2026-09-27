'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const serializers = require('./data/static/editor_serializers.js');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const body = { innerHTML: '' };
const save = { disabled: true };
const context = {
  window: { ALWeaverSerializers: serializers },
  state: {
    blocks: [
      {
        type: 'objects',
        data: { objects: [{ 'household.jobs': 'custom.DAList' }] },
      },
    ],
    symbolCatalog: { groups: { lists: ['x.incomes', 'people[i].jobs'] } },
  },
  _openFieldModsPanels: { 0: true },
  _fieldSettingsTabs: {},
  CHOICE_TYPES: ['checkboxes'],
  FIELD_TYPES: ['checkboxes'],
  _fieldTypeSupportsStandaloneContent: () => false,
  expressionFieldValue: (value) => (value === undefined ? '' : String(value)),
  requiredExpressionValue: () => '',
  renderSymbolDatalist: () => '',
  document: { getElementById: (id) => (id === 'order-add-body' ? body : save) },
  esc: String,
  escapeYamlStr: serializers.escapeYamlStr,
};
vm.createContext(context);
for (const name of [
  '_normalizeObjectClassName',
  '_isDaListLikeClass',
  'getGatherListCandidates',
  'renderOrderAddBody',
  'renderOrderCodePreview',
  'readExpressionModifier',
  'appendYamlValue',
]) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0);
  vm.runInContext(
    source.slice(start, source.indexOf('\n  }\n', start) + 5),
    context,
  );
}
assert.deepStrictEqual(
  Array.from(context.getGatherListCandidates(), (v) => v.variable),
  ['household.jobs', 'people[i].jobs', 'x.incomes'],
);
context.state.blocks = [];
context.state.symbolCatalog.groups = {};
context.renderOrderAddBody('gather');
assert.ok(body.innerHTML.includes('<input'));
assert.ok(body.innerHTML.includes('custom or nested list variable'));
assert.strictEqual(save.disabled, false);
assert.strictEqual(context.readExpressionModifier({ value: '0' }, 0), 0);
assert.strictEqual(
  context.readExpressionModifier({ value: 'false' }, false),
  false,
);
assert.strictEqual(
  context.appendYamlValue('', 'progress', '99'),
  'progress: 99\n',
);
assert.strictEqual(
  context.appendYamlValue('', 'continue button label', 'No'),
  'continue button label: "No"\n',
);
assert.strictEqual(
  context.appendYamlValue('', 'back button', 'false'),
  'back button: false\n',
);
const label = "Client's \\ details\nnext";
for (const call of ['set_parts', 'nav.set_section']) {
  const expected =
    call === 'set_parts' ? 'set_parts(subtitle=' : 'nav.set_section(';
  assert.strictEqual(
    context.renderOrderCodePreview(
      [{ kind: 'section', call, value: label }],
      2,
    ),
    '  ' + expected + JSON.stringify(label) + ')',
  );
}

for (const declaration of [
  'ALPeopleList.using(ask_number=True)',
  'module.ALPeopleList.using(ask_number=True)',
  'module.DAList.using(object_type=Thing)',
  'DAList',
  'module.DAList',
]) {
  assert.strictEqual(
    context._isDaListLikeClass(declaration),
    true,
    declaration,
  );
}
assert.strictEqual(context._isDaListLikeClass('Individual.using()'), false);
assert.strictEqual(
  context._normalizeObjectClassName(
    'module.ALPeopleList.using(ask_number=True)',
  ),
  'ALPeopleList',
);

const fieldPanelStart = source.indexOf('  function _renderFieldModsPanel(');
vm.runInContext(
  source.slice(fieldPanelStart, source.indexOf('\n  }\n', fieldPanelStart) + 5),
  context,
);
const choicePanel = context._renderFieldModsPanel(
  0,
  {
    'check others': true,
    'uncheck others': false,
    'disable others': false,
  },
  'checkboxes',
  ['Alpha', 'Beta'],
  '',
  'show if',
  '',
);
assert.ok(choicePanel.includes('data-fmod="none of the above"'));
assert.ok(choicePanel.includes('data-fmod="all of the above"'));
assert.ok(!choicePanel.includes('data-fmod="check others"'));
assert.ok(!choicePanel.includes('data-fmod="uncheck others"'));
assert.ok(!choicePanel.includes('data-fmod="disable others"'));
assert.ok(choicePanel.includes('data-source-only-fmod="check others"'));
assert.ok(choicePanel.includes('data-source-only-fmod="uncheck others"'));
assert.ok(choicePanel.includes('data-source-only-fmod="disable others"'));
assert.ok(choicePanel.includes('is not supported for checkboxes'));
assert.ok(choicePanel.includes('is preserved. Edit it in Full YAML.'));

const yesNoPanel = context._renderFieldModsPanel(
  0,
  { 'check others': true, 'uncheck others': false },
  'yesno',
  [],
  '',
  'show if',
  '',
);
assert.ok(yesNoPanel.includes('data-fmod="check others"'));
assert.ok(yesNoPanel.includes('data-fmod="uncheck others"'));
assert.ok(!yesNoPanel.includes('data-fmod="none of the above"'));
assert.ok(!yesNoPanel.includes('data-fmod="all of the above"'));
assert.ok(yesNoPanel.includes('data-fmod="disable others"'));

const yesNoListModifierPanel = context._renderFieldModsPanel(
  0,
  { 'check others': ['first_choice', 'second_choice'] },
  'yesno',
  [],
  '',
  'show if',
  '',
);
assert.ok(!yesNoListModifierPanel.includes('data-fmod="check others"'));
assert.ok(
  yesNoListModifierPanel.includes(
    'data-source-only-fmod="check others"',
  ),
);
assert.ok(
  yesNoListModifierPanel.includes(
    'list value is preserved:',
  ),
);

const disableOthersListPanel = context._renderFieldModsPanel(
  0,
  { 'disable others': ['first_choice', 'second_choice'] },
  'text',
  [],
  '',
  'show if',
  '',
);
assert.ok(
  disableOthersListPanel.includes(
    'data-fmod="disable others" data-field-idx="0" value="["first_choice","second_choice"]"',
  ),
);
const disableOthersFalsePanel = context._renderFieldModsPanel(
  0,
  { 'disable others': false },
  'text',
  [],
  '',
  'show if',
  '',
);
assert.ok(
  disableOthersFalsePanel.includes(
    'data-fmod="disable others" data-field-idx="0" value="false"',
  ),
);

const defaultYesNoPanel = context._renderFieldModsPanel(
  0,
  {},
  'yesno',
  [],
  '',
  'show if',
  '',
);
assert.ok(
  defaultYesNoPanel.includes('id="fmod-checkothers-0" data-fmod="check others" data-field-idx="0"><option value="">(default)</option><option value="True">Yes</option><option value="False">No'),
);
assert.ok(
  defaultYesNoPanel.includes('id="fmod-uncheckothers-0" data-fmod="uncheck others" data-field-idx="0"><option value="">(default)</option><option value="True">Yes</option><option value="False">No'),
);
const defaultChoicePanel = context._renderFieldModsPanel(
  0,
  {},
  'checkboxes',
  ['Alpha', 'Beta'],
  '',
  'show if',
  '',
);
assert.ok(
  !defaultChoicePanel.includes('data-fmod="check others"'),
);
assert.ok(!defaultChoicePanel.includes('data-fmod="uncheck others"'));
assert.ok(!body.innerHTML.includes('placeholder='));
assert.ok(body.innerHTML.includes('<code>household[i].jobs</code>'));
assert.ok(body.innerHTML.includes('aria-describedby="order-gather-help"'));
assert.strictEqual(
  context.appendYamlValue('', 'skip undefined', 'False'),
  'skip undefined: false\n',
);
assert.strictEqual(
  context.appendYamlValue('', 'skip undefined', 'True'),
  'skip undefined: true\n',
);

// Run the real review and inactive-field serializers, not only their helpers.
context._explicitBlockId = (block) => block.data.id;
context.document = { getElementById: () => null, querySelectorAll: () => [] };
context._yamlKeyValueLines = () => [];
context.serializeReviewItemData = () => '- Edit: answer';
for (const name of [
  'serializeReviewToYaml',
  'expressionModifierYamlValue',
  'fieldChoicesAreExpression',
  '_serializeQuestionFieldFromData',
]) {
  const start = source.indexOf(`  function ${name}(`);
  vm.runInContext(
    source.slice(start, source.indexOf('\n  }\n', start) + 5),
    context,
  );
}
context._fieldTypeSupportsStandaloneContent = () => false;
const reviewYaml = context.serializeReviewToYaml({
  data: {
    id: 'review',
    question: 'Review',
    review: [{ Edit: 'answer' }],
    'skip undefined': false,
  },
});
assert.ok(reviewYaml.includes('skip undefined: false\n'));
const { spawnSync } = require('child_process');
for (const field of [
  { label: 'Name', field: 'name', 'disable others': true },
  {
    label: 'Pick',
    field: 'pick',
    datatype: 'radio',
    choices: ['Yes', 'No'],
    shuffle: false,
  },
  {
    label: 'Person',
    field: 'person',
    datatype: 'object_radio',
    choices: 'people',
  },
]) {
  const encoded = 'fields:\n' + context._serializeQuestionFieldFromData(field);
  const result = spawnSync(
    process.env.PYTHON || 'python',
    [
      '-c',
      'import sys,json,yaml;print(json.dumps(yaml.safe_load(sys.stdin.read())))',
    ],
    { input: encoded, encoding: 'utf8' },
  );
  assert.strictEqual(result.status, 0, result.stderr);
  const actual = JSON.parse(result.stdout).fields[0];
  for (const key of ['disable others', 'shuffle'])
    if (key in field) assert.strictEqual(actual[key], field[key]);
  if (typeof field.choices === 'string')
    assert.strictEqual(actual.choices, field.choices);
}
if (process.argv.includes('--review-yaml')) process.stdout.write(reviewYaml);
if (process.argv.includes('--field-yaml')) {
  process.stdout.write(
    'id: typed_settings\nquestion: Test settings\nfields:\n' +
      context._serializeQuestionFieldFromData({
        label: 'Name',
        field: 'name',
        'disable others': true,
      }) +
      context._serializeQuestionFieldFromData({
        label: 'Pick',
        field: 'pick',
        datatype: 'radio',
        choices: ['Yes', 'No'],
        shuffle: false,
      }),
  );
}

// A rapid Add action may finish while Bootstrap is still opening the modal.
{
  const start = source.indexOf('  function closeBootstrapModal(');
  vm.runInContext(
    source.slice(start, source.indexOf('\n  }\n', start) + 5),
    context,
  );
  let shown = true,
    transitioning = true,
    deferred = null,
    calls = 0;
  const modal = {
    classList: { contains: () => shown },
    addEventListener: (event, fn, options) => {
      assert.strictEqual(event, 'shown.bs.modal');
      assert.strictEqual(options.once, true);
      deferred = fn;
    },
  };
  const instance = {
    hide: () => {
      calls++;
      if (!transitioning) shown = false;
    },
  };
  context.bootstrap = { Modal: { getInstance: () => instance } };
  context.document = { getElementById: () => modal };
  context.closeBootstrapModal('order-add-modal');
  assert.strictEqual(calls, 1);
  assert.ok(deferred);
  transitioning = false;
  deferred();
  assert.strictEqual(shown, false);
  deferred = null;
  shown = true;
  context.closeBootstrapModal('order-add-modal');
  assert.strictEqual(shown, false);
  assert.strictEqual(deferred, null);
}

// Missing required bundle must explain the failure in the pane itself.
const sourcePane = {
  innerHTML: '',
  appendChild(el) {
    this.alert = el;
  },
};
context.document = {
  getElementById: () => sourcePane,
  createElement: () => ({
    setAttribute(name, value) {
      this[name] = value;
    },
  }),
};
const sourceStart = source.indexOf('  function createSourceEditor(');
vm.runInContext(
  source.slice(sourceStart, source.indexOf('\n  }\n', sourceStart) + 5),
  context,
);
assert.throws(
  () => context.createSourceEditor('source', 'title: Keep', 'yaml'),
  /CodeMirror bundle is missing/,
);
assert.strictEqual(sourcePane.alert.role, 'alert');
assert.ok(sourcePane.alert.textContent.includes('Reload this page'));
context.window.daNewEditor = () => null;
assert.throws(
  () => context.createSourceEditor('source', '', 'yaml'),
  /could not initialize/,
);
assert.ok(sourcePane.alert.textContent.includes('administrator'));
assert.strictEqual(
  context.expressionModifierYamlValue('none of the above', 'False'),
  '"False"',
);
assert.strictEqual(
  context.expressionModifierYamlValue('all of the above', false),
  'false',
);

// Completed jobs keep result warnings nested, unlike their summary fields.
const warningStart = source.indexOf(
  '  function _newProjectGenerationWarnings(',
);
vm.runInContext(
  source.slice(warningStart, source.indexOf('\n  }\n', warningStart) + 5),
  context,
);
assert.deepStrictEqual(
  Array.from(
    context._newProjectGenerationWarnings({
      status: 'succeeded',
      result: { warnings: ['Conflicting text and checkbox types', '', null] },
    }),
  ),
  ['Conflicting text and checkbox types'],
);
assert.deepStrictEqual(
  Array.from(context._newProjectGenerationWarnings({ result: {} })),
  [],
);
assert.deepStrictEqual(
  Array.from(
    context._newProjectGenerationWarnings({ warnings: ['Direct result'] }),
  ),
  ['Direct result'],
);

// A failed rollback must expose recovery content, not only a generic error.
const recoveryStatus = {
  children: [],
  appendChild(node) {
    this.children.push(node);
  },
};
context.projectSearchElement = () => recoveryStatus;
context.document = {
  createElement: (tag) => ({
    tag,
    addEventListener(name, callback) {
      this[name] = callback;
    },
  }),
};
const recoveryStart = source.indexOf(
  '  function showProjectReplacementRecovery(',
);
vm.runInContext(
  source.slice(recoveryStart, source.indexOf('\n  }\n', recoveryStart) + 5),
  context,
);
context.showProjectReplacementRecovery({
  details: {
    recovery_files: [
      {
        section: 'interview',
        filename: 'second.yml',
        original_content: 'question: Original',
      },
    ],
  },
});
assert.ok(
  recoveryStatus.children[0].textContent.includes('interview/second.yml'),
);
assert.strictEqual(
  recoveryStatus.children[1].textContent,
  'Download recovery JSON',
);
assert.strictEqual(typeof recoveryStatus.children[1].click, 'function');

// Large outlines must not search the full block array once per row.
const outlineBlocks = Array.from({ length: 1000 }, (_, index) => ({
  id: `block_${index}`,
  type: 'question',
  title: `Question ${index}`,
  yaml: `id: block_${index}\nquestion: Question ${index}`,
  tags: [],
}));
let blockArrayIndexOfCalls = 0;
outlineBlocks.indexOf = function (block) {
  blockArrayIndexOfCalls += 1;
  return Array.prototype.indexOf.call(this, block);
};
let blockLookupCalls = 0;
const outlineIndices = [];
const outlineList = { innerHTML: '' };
const outlineContext = {
  state: {
    blocks: outlineBlocks,
    selectedBlockId: 'block_0',
    validationErrors: [],
  },
  outlineList,
  updateOutlineHeader() {},
  updateOutlineFilterSummary() {},
  isInterviewView: () => true,
  filteredBlocks: () => outlineBlocks,
  getBlockDisplayType: (block) => block.type,
  typeLabel: () => 'Question',
  typeClass: () => 'question',
  getBlockById(id) {
    blockLookupCalls += 1;
    return outlineBlocks.find((block) => block.id === id);
  },
  _findingsMatchBlock: () => false,
  getBlockLintFeedbackClass: () => '',
  getBlockLintHighestLevel: () => '',
  getBlockLintLeadMessage: () => '',
  blockQuickView: (block) => block.yaml,
  esc: String,
  isOutlineDragEnabled: () => false,
  getBlockMenuHtml: (_block, index, total) => {
    assert.strictEqual(total, 1000);
    outlineIndices.push(index);
    return '';
  },
  initOutlineSortable() {},
};
vm.createContext(outlineContext);
for (const name of ['getBlockLintFindings', 'renderOutline']) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, name);
  vm.runInContext(
    source.slice(start, source.indexOf('\n  }\n', start) + 5),
    outlineContext,
  );
}
outlineContext.renderOutline();
assert.strictEqual(blockLookupCalls, 0);
assert.strictEqual(blockArrayIndexOfCalls, 0);
assert.deepStrictEqual(
  outlineIndices,
  Array.from({ length: 1000 }, (_, index) => index),
);
assert.ok(outlineList.innerHTML.includes('data-block-id="block_999"'));

// A successful block save refreshes and renders the model once while keeping
// the saved block selected. The save callback uses this same helper, avoiding
// a second expensive outline and canvas render after refresh.
{
  const block = { id: 'saved', type: 'question', data: { id: 'saved' } };
  const calls = { outline: 0, canvas: 0, validation: 0, savedId: null };
  const refreshContext = {
    state: {
      filename: 'matrix.yml',
      blocks: [{ id: 'old', type: 'question', data: { id: 'old' } }],
      selectedBlockId: 'old',
      orderStepMap: {},
    },
    window: {
      ALWeaverDirtyState: {
        preserveDirtyBlocks: (blocks) => blocks,
      },
    },
    dirtyState: {
      getFileState: () => null,
      markBlockSaved: (id) => {
        calls.savedId = id;
      },
      activate() {},
    },
    cloneData: (value) => JSON.parse(JSON.stringify(value)),
    getBlockById: (id) =>
      refreshContext.state.blocks.find((item) => item.id === id),
    getDefaultOrderBlockId: () => null,
    setActiveOrderBlock() {},
    isBlockVisibleInOutline: () => true,
    getDefaultVisibleBlockId: () => 'saved',
    captureInterviewModel: () => ({ blocks: refreshContext.state.blocks }),
    loadAvailableSymbols() {},
    renderOutline: () => {
      calls.outline += 1;
    },
    renderCanvas: () => {
      calls.canvas += 1;
    },
    runCurrentValidationCheck: () => {
      calls.validation += 1;
    },
  };
  vm.createContext(refreshContext);
  for (const name of ['refreshFromFileResponse', 'refreshAfterBlockSave']) {
    const start = source.indexOf(`  function ${name}(`);
    assert.ok(start >= 0, name);
    vm.runInContext(
      source.slice(start, source.indexOf('\n  }\n', start) + 5),
      refreshContext,
    );
  }
  refreshContext.refreshAfterBlockSave(
    { blocks: [block], revision: 'revision-2' },
    'old',
    'saved',
  );
  assert.strictEqual(refreshContext.state.selectedBlockId, 'saved');
  assert.strictEqual(calls.savedId, 'old');
  assert.strictEqual(calls.outline, 1);
  assert.strictEqual(calls.canvas, 1);
  assert.strictEqual(calls.validation, 1);
}
