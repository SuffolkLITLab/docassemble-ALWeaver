'use strict';

const assert = require('assert');
const serializers = require('./data/static/editor_serializers.js');

function appendYamlValue(yaml, key, value) {
  if (value === undefined || value === null) return yaml;
  const text = String(value).trim();
  if (!text) return yaml;
  return yaml + key + ': ' + serializers.escapeYamlStr(text) + '\n';
}

function appendYamlBlockValue(yaml, key, value) {
  if (value === undefined || value === null) return yaml;
  const text = String(value);
  if (!text.trim()) return yaml;
  yaml += key + ': |\n';
  text.split('\n').forEach((line) => { yaml += '      ' + line + '\n'; });
  return yaml;
}

function makeDocument(type, modifiers, methodArgs) {
  const values = {
    'adv-id': { value: 'question_id' },
    'q-title': { value: 'Question text' },
    'q-subquestion': { value: '' },
    'field-choices-0': { value: 'One\nTwo' },
    'field-code-0': { value: '' },
    'field-showif-0': { value: '' },
  };
  const row = {
    getAttribute(name) { return name === 'data-field-idx' ? '0' : null; },
    querySelector(selector) {
      if (selector === '[data-field-prop="type"]') return { value: type };
      if (selector === '[data-field-prop="label"]') return { value: 'Label' };
      if (selector === '[data-field-prop="variable"]') return { value: 'answer' };
      if (selector === '[data-field-method-args]') return { value: methodArgs || '' };
      return null;
    },
  };
  const modifierInputs = (modifiers || []).map((key) => ({
    value: 'modifier_value',
    getAttribute(name) { return name === 'data-fmod' ? key : null; },
  }));
  return {
    getElementById(id) { return values[id] || null; },
    querySelectorAll(selector) { return selector === '.editor-field-row' ? [row] : []; },
    querySelector(selector) {
      if (selector.indexOf('.editor-field-required-switch') === 0) return { checked: true };
      if (selector.indexOf('.editor-field-mods-panel') === 0) {
        return { querySelectorAll() { return modifierInputs; } };
      }
      return null;
    },
  };
}

function serialize(type, modifiers, methodArgs) {
  return serializers.serializeQuestionToYaml({ id: 'question_id', data: {} }, {
    document: makeDocument(type, modifiers, methodArgs),
    appendYamlValue,
    appendYamlBlockValue,
    fieldTypeSupportsStandaloneContent(value) {
      return ['note', 'html', 'raw html', 'code'].indexOf(value) !== -1;
    },
    fieldMethodTypes: ['name_fields', 'address_fields', 'gender_fields', 'pronoun_fields', 'language_fields'],
    choiceTypes: [
      'radio', 'checkboxes', 'combobox', 'multiselect', 'dropdown',
      'object', 'object_radio', 'object_checkboxes', 'object_multiselect',
    ],
    state: { questionBlockTab: 'screen' },
    serializeQuestionFieldFromData() { throw new Error('unexpected fallback'); },
    appendQuestionAdvancedYaml(yaml) { return yaml; },
  });
}

assert.strictEqual(serializers.escapeYamlStr('plain'), 'plain');
assert.strictEqual(serializers.escapeYamlStr(''), '""');
assert.strictEqual(serializers.escapeYamlStr(0), '0');
assert.strictEqual(serializers.escapeYamlStr(false), 'false');
assert.strictEqual(serializers.escapeYamlStr(null), null);
assert.strictEqual(serializers.escapeYamlStr(undefined), undefined);
assert.strictEqual(serializers.escapeYamlStr('with: colon'), '"with: colon"');
assert.strictEqual(serializers.escapeYamlStr('two\nlines'), '|\n  two\n  lines');
assert.strictEqual(serializers.escapeYamlStr('a\\b"c'), '"a\\\\b\\"c"');

[
  'radio', 'checkboxes', 'combobox', 'multiselect', 'dropdown',
  'object', 'object_radio', 'object_checkboxes', 'object_multiselect',
].forEach((type) => {
  const yaml = serialize(type, []);
  assert.ok(yaml.includes('    datatype: ' + type + '\n'), type);
  assert.ok(yaml.includes('    choices:\n      - One\n      - Two\n'), type);
});

['note', 'html', 'raw html', 'code'].forEach((type) => {
  const yaml = serialize(type, []);
  assert.ok(yaml.includes('  - ' + type + ': |\n      Label\n'), type);
});

[
  'area', 'yesno', 'yesnowide', 'yesnoradio', 'yesnomaybe', 'noyes',
  'noyeswide', 'noyesradio', 'noyesmaybe', 'number', 'integer', 'currency',
  'date', 'time', 'datetime', 'email', 'password', 'url', 'file', 'files',
  'camera', 'range', 'ml', 'mlarea', 'microphone', 'camcorder', 'hidden',
  'raw', 'user', 'environment',
].forEach((type) => {
  assert.ok(serialize(type, []).includes('    datatype: ' + type + '\n'), type);
});
assert.ok(!serialize('text', []).includes('    datatype: text\n'));

[
  'name_fields', 'address_fields', 'gender_fields', 'pronoun_fields', 'language_fields',
].forEach((type) => {
  const yaml = serialize(type, [], "show_if={'variable': 'ready', 'is': True}");
  assert.ok(yaml.includes("  - code: |\n      answer." + type + "(show_if={'variable': 'ready', 'is': True})\n"), type);
  assert.ok(!yaml.includes('datatype: ' + type), type);
});

const modifierKeys = [
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
const modifierYaml = serialize('text', modifierKeys);
modifierKeys.forEach((key) => {
  assert.ok(modifierYaml.includes('    ' + key + ': modifier_value\n'), key);
});

// ---------------------------------------------------------------------------
// ALPeopleList quantity — "Setting the number of people in a group"
// ---------------------------------------------------------------------------

const {
  splitUsingArgs,
  readPeopleListQuantity,
  composePeopleListUsingArgs,
  PEOPLE_LIST_QUANTITY_MODES,
} = serializers;

// The editor normalizes any multi-argument `.using()` call onto separate lines
// before the browser sees it, so newlines separate arguments just like commas.
// Testing only the comma form hid this: the docs' own "exactly one" example
// reaches this code as two lines and got no control at all.
assert.deepStrictEqual(
  splitUsingArgs('ask_number=True\ntarget_number=1'),
  ['ask_number=True', 'target_number=1']
);
const normalizedExactly = readPeopleListQuantity('ask_number=True\ntarget_number=1');
assert.strictEqual(normalizedExactly.editable, true);
assert.strictEqual(normalizedExactly.mode, 'exactly');
assert.strictEqual(normalizedExactly.number, 1);

const normalizedWithOthers = readPeopleListQuantity(
  "ask_number=True\ntarget_number=2\ncomplete_attribute='name'"
);
assert.strictEqual(normalizedWithOthers.editable, true);
assert.strictEqual(normalizedWithOthers.mode, 'exactly');
assert.strictEqual(normalizedWithOthers.number, 2);
assert.strictEqual(normalizedWithOthers.otherArgs, "complete_attribute='name'");

// A newline inside brackets or quotes is not a separator.
assert.deepStrictEqual(splitUsingArgs('elements=[\n  a,\n  b\n]'), ['elements=[\n  a,\n  b\n]']);
assert.deepStrictEqual(splitUsingArgs('title="two\nlines"'), ['title="two\nlines"']);

// Splitting on top-level commas.
assert.deepStrictEqual(splitUsingArgs(''), []);
assert.deepStrictEqual(splitUsingArgs('a=1, b=2'), ['a=1', 'b=2']);
assert.deepStrictEqual(splitUsingArgs('a=[1, 2], b=f(3, 4)'), ['a=[1, 2]', 'b=f(3, 4)']);
assert.deepStrictEqual(splitUsingArgs('a="x, y", b=2'), ['a="x, y"', 'b=2']);
// Unbalanced input is refused rather than half-parsed.
assert.strictEqual(splitUsingArgs('a=[1, 2'), null);
assert.strictEqual(splitUsingArgs("a='unterminated"), null);

// The three shapes the AssemblyLine docs describe.
const bare = readPeopleListQuantity('');
assert.strictEqual(bare.editable, true);
assert.strictEqual(bare.mode, 'ask');

const atLeastOne = readPeopleListQuantity('there_are_any=True');
assert.strictEqual(atLeastOne.editable, true);
assert.strictEqual(atLeastOne.mode, 'at_least_one');

const exactlyOne = readPeopleListQuantity('ask_number=True, target_number=1');
assert.strictEqual(exactlyOne.editable, true);
assert.strictEqual(exactlyOne.mode, 'exactly');
assert.strictEqual(exactlyOne.number, 1);

const askCount = readPeopleListQuantity('ask_number=True');
assert.strictEqual(askCount.editable, true);
assert.strictEqual(askCount.mode, 'ask_count');

// Parameters the control does not own survive untouched, in source order.
const withOthers = readPeopleListQuantity('there_are_any=True, complete_attribute="name"');
assert.strictEqual(withOthers.editable, true);
assert.strictEqual(withOthers.mode, 'at_least_one');
assert.strictEqual(withOthers.otherArgs, 'complete_attribute="name"');

// Anything the control cannot fully account for is left to the author.
[
  'target_number=how_many',            // an expression, not a literal
  'ask_number=True, target_number=n+1',
  'there_are_any=False',               // a real setting, but not one of the modes
  'there_are_any=True, ask_number=True',
  'there_are_any=True, there_are_any=True',
  'target_number=2',                   // target without ask_number
  'there_are_any=maybe_any',
  '**overrides',
  'ask_number=[1',                     // unbalanced
].forEach((args) => {
  assert.strictEqual(readPeopleListQuantity(args).editable, false, args);
  // A refusal must hand the original text back for the plain editor.
  assert.strictEqual(readPeopleListQuantity(args).otherArgs, args, args);
});

// Composing is the exact inverse for every mode the control offers.
assert.strictEqual(composePeopleListUsingArgs('ask', 1, ''), '');
assert.strictEqual(composePeopleListUsingArgs('at_least_one', 1, ''), 'there_are_any=True');
assert.strictEqual(composePeopleListUsingArgs('ask_count', 1, ''), 'ask_number=True');
assert.strictEqual(
  composePeopleListUsingArgs('exactly', 1, ''),
  'ask_number=True, target_number=1'
);
assert.strictEqual(
  composePeopleListUsingArgs('exactly', 3, 'complete_attribute="name"'),
  'ask_number=True, target_number=3, complete_attribute="name"'
);
// A blank or nonsense count falls back to one rather than writing target_number=NaN.
assert.strictEqual(
  composePeopleListUsingArgs('exactly', '', ''),
  'ask_number=True, target_number=1'
);

// Every offered mode round-trips through read -> compose -> read.
PEOPLE_LIST_QUANTITY_MODES.forEach((mode) => {
  const args = composePeopleListUsingArgs(mode.value, 2, 'complete_attribute="name"');
  const parsed = readPeopleListQuantity(args);
  assert.strictEqual(parsed.editable, true, mode.value);
  assert.strictEqual(parsed.mode, mode.value, mode.value);
  assert.strictEqual(parsed.otherArgs, 'complete_attribute="name"', mode.value);
  if (mode.value === 'exactly') assert.strictEqual(parsed.number, 2);
});

// Reading a list and composing it again without touching the control is a no-op.
[
  '',
  'there_are_any=True',
  'ask_number=True',
  'ask_number=True, target_number=1',
  'ask_number=True, target_number=4, complete_attribute="name"',
].forEach((args) => {
  const parsed = readPeopleListQuantity(args);
  assert.strictEqual(
    composePeopleListUsingArgs(parsed.mode, parsed.number, parsed.otherArgs),
    args,
    args
  );
});
