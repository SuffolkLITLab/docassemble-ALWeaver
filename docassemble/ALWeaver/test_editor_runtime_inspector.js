'use strict';

const assert = require('assert');
const runtime = require('./data/static/editor_runtime_inspector.js');

assert.deepStrictEqual(
  runtime.filterVariables({ zebra: 1, Alpha: 2, beta: 3 }, 'a'),
  { Alpha: 2, beta: 3, zebra: 1 },
);
const configNames = [
  'AL_ORGANIZATION_TITLE',
  'AL_ORGANIZATION_HOMEPAGE',
  'AL_DEFAULT_COUNTRY',
  'AL_DEFAULT_STATE',
  'AL_DEFAULT_LANGUAGE',
  'AL_DEFAULT_OVERFLOW_MESSAGE',
  'interview_metadata',
  'addresses_to_search',
  'allowed_courts',
  'al_logo',
  'al_form_requires_digital_signature',
  'al_typed_signature_prefix',
  'al_typed_signature_font',
  'al_form_type',
  'al_person_answering',
  'github_repo_name',
  'github_user',
  'enable_al_language',
  'al_user_default_language',
  'al_interview_languages',
  'al_user_language',
  'al_menu_items_custom_items',
  'signature_fields',
  'feedback_form',
  'multi_user',
  'nav',
  'speak_text',
  'package_version_number',
  'al_session_store_default_filename',
  'al_sessions_interview_title',
  'al_terms_of_use',
  'al_name_suffixes',
  'al_name_titles',
  'alkiln_trigger_html',
  'alkiln_proxy_html',
  '_alkiln_generated',
  '_internal',
];
const config = Object.fromEntries(configNames.map((name) => [name, true]));
const importedTypes = {
  List: null,
  Optional: null,
  Any: null,
  Dict: null,
  Tuple: null,
  Union: null,
  Callable: null,
  TypedDict: null,
  TypeVar: null,
};
const answers = {
  users: [{ name: 'Pat' }],
  trial_court: 'Boston',
  user_ask_role: 'plaintiff',
  user_role: 'plaintiff',
  user_started_case: true,
  al_custom_answer: 0,
  al_user_bundle: {},
  feedback: 'My answer',
  ListOfClaims: ['One claim'],
  OptionalAnswer: 'Keep this answer',
};
assert.deepStrictEqual(
  runtime.filterVariables({ ...config, ...importedTypes, ...answers }, ''),
  answers,
);
assert.deepStrictEqual(runtime.filterVariables(config, '', true), config);
assert.deepStrictEqual(runtime.filterVariables(importedTypes, ''), {});
assert.deepStrictEqual(
  runtime.filterVariables(importedTypes, '', true),
  importedTypes,
);
assert.deepStrictEqual(runtime.filterVariables(importedTypes, 'optional'), {});
assert.deepStrictEqual(
  runtime.filterVariables(importedTypes, 'optional', true),
  { Optional: null },
);
assert.deepStrictEqual(runtime.filterVariables(config, 'feedback'), {});
assert.deepStrictEqual(runtime.filterVariables(config, 'feedback', true), {
  feedback_form: true,
});
assert.ok(runtime.isInternalVariable('nav.sections'));
assert.ok(runtime.isInternalVariable('interview_metadata["form"]'));
for (const value of [null, false, 0, '', 'answer'])
  assert.equal(runtime.isNestedValue(value), false);
for (const value of [{}, [], { nested: true }])
  assert.equal(runtime.isNestedValue(value), true);
assert.equal(runtime.simpleValue(null), 'None');
assert.equal(runtime.simpleValue(undefined), 'None');
assert.equal(runtime.simpleValue(false), 'False');
assert.equal(runtime.simpleValue(true), 'True');
assert.equal(runtime.simpleValue(0), '0');
assert.equal(runtime.simpleValue(''), '\"\"');
assert.equal(runtime.simpleValue('<b>answer</b>'), '<b>answer</b>');

// Match Docassemble's serialized DADict, including its non-choice metadata.
const benefits = {
  _class: 'docassemble.base.util.DADict',
  instanceName: 'benefits',
  elements: { SNAP: true, SSI: false, TAFDC: true },
  auto_gather: true,
  ask_number: false,
  minimum_number: null,
  object_type: null,
  object_type_parameters: {},
  complete_attribute: null,
  ask_object_type: false,
};
assert.deepStrictEqual(runtime.checkboxValues(benefits), benefits.elements);
assert.equal(runtime.variableType(benefits), 'checkboxes');
assert.equal(runtime.variablePreview(benefits), 'Checked: SNAP, TAFDC');
assert.deepStrictEqual(runtime.checkboxValues({ SNAP: false }), {
  SNAP: false,
});
assert.equal(runtime.variablePreview({ SNAP: false }), 'None checked');
for (const value of [
  null,
  {},
  [],
  [true, false],
  { SNAP: true, income: 42 },
  { _class: 'docassemble.base.util.DADict', elements: {} },
  { _class: 'docassemble.base.util.DADict', elements: { name: 'Pat' } },
  { _class: 'docassemble.base.util.DAObject', elements: { SNAP: true } },
])
  assert.equal(runtime.checkboxValues(value), null);
assert.equal(
  runtime.variableType({ ...benefits, elements: { name: 'Pat' } }),
  'DADict',
);
assert.equal(runtime.variableType(null), 'NoneType');
assert.equal(runtime.variableType(true), 'bool');
assert.equal(runtime.variableType('answer'), 'str');
assert.equal(runtime.variableType([]), 'list');
assert.equal(runtime.variableType({}), 'dict');
assert.equal(runtime.pythonValue(undefined), 'None');
assert.equal(runtime.variablePreview(false), 'False');
assert.equal(runtime.variablePreview(null), 'None');
assert.equal(
  runtime.pythonValue({
    true: 'true',
    null: 'null',
    false: 'false',
    escaped: '"true"\\null',
    nested: [true, false, null],
  }),
  '{"true":"true","null":"null","false":"false","escaped":"\\"true\\"\\\\null","nested":[True,False,None]}',
);
assert.equal(
  runtime.pythonValue([true, false, null], true),
  '[\n  True,\n  False,\n  None\n]',
);

assert.deepStrictEqual(
  runtime.changedVariableNames(
    { unchanged: 1, changed: 'old', removed: true },
    { unchanged: 1, changed: 'new', added: false },
  ),
  ['added', 'changed', 'removed'],
);

assert.strictEqual(
  runtime.questionLabel({
    questionText: '<p>What is <strong>your name</strong>?</p>',
  }),
  'What is your name?',
);
assert.strictEqual(
  runtime.questionIdentity({
    questionName: 'user_name',
    questionText: 'Your name',
  }),
  'user_name',
);
assert.strictEqual(
  runtime.findQuestionSource({ questionName: 'user_name' }, [
    { id: 'other' },
    { id: 'user_name', type: 'question' },
  ]).id,
  'user_name',
);
assert.strictEqual(
  runtime.findQuestionSource({ questionName: 'review_answers' }, [
    { id: 'generated', data: { event: 'review_answers' } },
  ]).id,
  'generated',
);
// Docassemble prefixes Question.name with "ID " when the block has an
// explicit `id:` field (docassemble_base/base/parse.py: self.name = "ID " +
// self.id). The step recorder must strip that prefix so the label matches
// the literal `id: <value>` text in the source YAML.
assert.strictEqual(
  runtime.blockIdLabel('ID tenancy_address', 'question'),
  'id: tenancy_address',
);
// A name with no explicit id is an auto-generated Question_N/Block_N label,
// not a literal id, so it is shown as-is rather than mislabeled "id: ...".
assert.strictEqual(
  runtime.blockIdLabel('Question_12', 'question'),
  'Question_12',
);
assert.strictEqual(runtime.blockIdLabel('', 'question'), 'question');

assert.strictEqual(runtime.variablePreview(undefined), '(removed)');
assert.ok(runtime.variablePreview('x'.repeat(200)).length <= 90);

let steps = runtime.updateStepHistory(
  [],
  { questionName: 'name', questionText: 'Your name' },
  {},
  [],
);
steps = runtime.updateStepHistory(
  steps,
  { questionName: 'address', questionText: 'Your address' },
  { user_name: 'Pat' },
  ['user_name'],
);
assert.strictEqual(steps.length, 2, 'a new screen adds a recorder step');
assert.deepStrictEqual(
  steps[0].answers,
  [{ name: 'user_name', value: 'Pat', provenance: 'observed_runtime' }],
  'changed variables are attributed to the screen that collected them',
);
const seededSteps = runtime.updateStepHistory(
  [
    {
      identity: 'name',
      label: 'Your name',
      questionName: 'name',
      questionType: 'fields',
      answers: [],
    },
  ],
  { questionName: 'name', questionText: 'Your name' },
  { person_name: 'Fixture name' },
  ['person_name'],
  ['person_name'],
);
assert.strictEqual(
  seededSteps[0].answers[0].provenance,
  'scenario_seeded',
  'scenario values are never mislabeled as observed user answers',
);
steps = runtime.updateStepHistory(
  steps,
  { questionName: 'address', questionText: 'Your address' },
  { user_name: 'Pat' },
  [],
);
assert.strictEqual(
  steps.length,
  2,
  'refreshing one screen does not duplicate it',
);

async function testHideStopsPollingAndBlocksPendingRepaint() {
  let intervalStarts = 0;
  const timers = new Map();
  let visibilityChanged;
  global.document = {
    createElement: () => fakeNode(),
    hidden: false,
    addEventListener(name, fn) {
      visibilityChanged = fn;
    },
    removeEventListener() {},
  };
  let intervalStops = 0;
  global.window = {
    setTimeout(callback, delay) {
      intervalStarts += 1;
      timers.set(intervalStarts, { callback, delay });
      return intervalStarts;
    },
    clearTimeout(id) {
      intervalStops += 1;
      timers.delete(id);
    },
  };

  const pendingResponses = [];
  const inspector = runtime.createRuntimeInspector({
    api: {
      get(path) {
        assert.ok(path.endsWith('/snapshot'));
        return new Promise((resolve) => pendingResponses.push(resolve));
      },
      post() {
        return Promise.resolve({ data: {} });
      },
      delete() {
        return Promise.resolve({ data: {} });
      },
    },
    getContext() {
      return { project: 'example', filename: 'example.yml' };
    },
  });
  inspector.setSession({
    weaver_session_id: 'session-1',
    target_url: '/interview?session=1',
  });

  function fakeNode() {
    return {
      checked: false,
      className: '',
      disabled: false,
      innerHTML: '',
      scrollHeight: 0,
      scrollTop: 0,
      clientHeight: 0,
      textContent: '',
      classList: { toggle() {}, add() {} },
      querySelectorAll() {
        return [];
      },
      appendChild() {},
      setAttribute() {},
      addEventListener() {},
    };
  }

  const nodes = {
    '#runtime-status': fakeNode(),
    '#runtime-question': fakeNode(),
    '#runtime-step-list': fakeNode(),
    '#runtime-step-count': fakeNode(),
    '#runtime-variable-count': fakeNode(),
    '#runtime-variable-list': fakeNode(),
    '#runtime-include-internal': fakeNode(),
  };
  const wrapper = {
    querySelector(selector) {
      return nodes[selector] || null;
    },
    querySelectorAll() {
      return [];
    },
  };
  const frame = { closest: () => wrapper };
  const previousFiller = global.ALWeaverFakeFiller;
  global.ALWeaverFakeFiller = { createController: () => ({ dispose() {} }) };
  let canvasQueries = 0;
  const container = {
    querySelector(selector) {
      canvasQueries += 1;
      return selector === '#runtime-interview-frame' ? frame : null;
    },
  };

  inspector.render(container);
  assert.strictEqual(
    intervalStarts,
    1,
    'showing a live session starts polling',
  );
  const observation = inspector.refreshAll();
  assert.strictEqual(pendingResponses.length, 1);
  assert.strictEqual(timers.size, 0, 'no timer while a request is in flight');

  inspector.hide();
  assert.strictEqual(intervalStops, 1, 'observation cancels the pending timer');
  const queriesBeforeResolution = canvasQueries;
  pendingResponses[0]({
    data: { question: { questionName: 'next' }, variables: { answer: true } },
  });
  await observation;
  assert.strictEqual(
    canvasQueries,
    queriesBeforeResolution,
    'a pending observation cannot repaint after the inspector is hidden',
  );

  await inspector.refreshAll();
  assert.strictEqual(
    pendingResponses.length,
    1,
    'a hidden inspector does not start another observation',
  );
  assert.strictEqual(
    timers.size,
    0,
    'completion after hide cannot restart polling',
  );
  inspector.render(container);
  assert.strictEqual(timers.size, 1);
  global.document.hidden = true;
  visibilityChanged();
  assert.strictEqual(timers.size, 0, 'background tabs stop polling');
  global.document.hidden = false;
  visibilityChanged();
  assert.strictEqual(
    pendingResponses.length,
    2,
    'foregrounding refreshes immediately',
  );
  pendingResponses[1]({
    data: { question: { questionName: 'next' }, variables: { answer: true } },
  });
  await new Promise((resolve) => setImmediate(resolve));
  let timer = [...timers.values()][0];
  assert.ok(
    timer.delay >= 6750 && timer.delay <= 8250,
    'unchanged snapshot backs off to 7.5 seconds plus jitter',
  );
  timers.clear();
  timer.callback();
  assert.strictEqual(
    timers.size,
    0,
    'slow observations never schedule overlapping polls',
  );
  pendingResponses[2]({
    data: { question: { questionName: 'next' }, variables: { answer: true } },
  });
  await new Promise((resolve) => setImmediate(resolve));
  timer = [...timers.values()][0];
  assert.ok(
    timer.delay >= 9000 && timer.delay <= 11000,
    'idle polling caps at ten seconds plus jitter',
  );
  const refresh = inspector.refreshAll();
  pendingResponses[3]({
    data: {
      question: { questionName: 'changed' },
      variables: { answer: false },
    },
  });
  await refresh;
  timer = [...timers.values()][0];
  assert.ok(
    timer.delay >= 4500 && timer.delay <= 5500,
    'activity restores five second polling',
  );
  inspector.hide();
  global.ALWeaverFakeFiller = previousFiller;
}

testHideStopsPollingAndBlocksPendingRepaint()
  .then(function () {
    console.log('editor_runtime_inspector.js: all assertions passed');
  })
  .catch(function (error) {
    console.error(error);
    process.exitCode = 1;
  });
