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
// if / elif / else chains in the interview order
// ---------------------------------------------------------------------------

const {
  getConditionChain,
  getChainTail,
  chainHasFinalElse,
  isChainLink,
  appendChainElif,
  removeChainLink,
} = serializers;

let _stepSeq = 0;
function cond(condition, children) {
  _stepSeq += 1;
  return {
    id: 'step-' + _stepSeq,
    kind: 'condition',
    condition: condition,
    children: children || [],
    has_else: false,
    else_children: [],
  };
}
function screen(name) {
  _stepSeq += 1;
  return { id: 'step-' + _stepSeq, kind: 'screen', invoke: name, summary: name };
}
function conditions(chain) {
  return chain.map((link) => link.condition);
}

// A lone `if` is a chain of one.
const single = cond('a', [screen('one')]);
assert.deepStrictEqual(conditions(getConditionChain(single)), ['a']);
assert.strictEqual(getChainTail(single), single);
assert.strictEqual(chainHasFinalElse(single), false);

// An `else` that is not a lone condition ends the chain.
const withElse = cond('a', [screen('one')]);
withElse.has_else = true;
withElse.else_children = [screen('two')];
assert.deepStrictEqual(conditions(getConditionChain(withElse)), ['a']);
assert.strictEqual(chainHasFinalElse(withElse), true);

// An `else` holding exactly one condition is an `elif`, and chains.
const chained = cond('a', [screen('one')]);
const linkB = cond('b', [screen('two')]);
const linkC = cond('c', [screen('three')]);
chained.has_else = true;
chained.else_children = [linkB];
linkB.has_else = true;
linkB.else_children = [linkC];
assert.deepStrictEqual(conditions(getConditionChain(chained)), ['a', 'b', 'c']);
assert.strictEqual(getChainTail(chained), linkC);
assert.strictEqual(isChainLink(linkB, chained), true);
assert.strictEqual(isChainLink(linkC, linkB), true);
assert.strictEqual(isChainLink(linkC, chained), false);
assert.strictEqual(isChainLink(chained, null), false);
// An `else` with a condition *plus* something else is a real else, not a link.
const notALink = cond('a');
const inner = cond('b');
notALink.has_else = true;
notALink.else_children = [inner, screen('tail')];
assert.strictEqual(isChainLink(inner, notALink), false);
assert.deepStrictEqual(conditions(getConditionChain(notALink)), ['a']);

// Adding an elif appends to the end of the chain...
const growing = cond('a', [screen('one')]);
appendChainElif(growing, cond('b'));
assert.deepStrictEqual(conditions(getConditionChain(growing)), ['a', 'b']);
appendChainElif(growing, cond('c'));
assert.deepStrictEqual(conditions(getConditionChain(growing)), ['a', 'b', 'c']);
// ...from any link, not just the head.
appendChainElif(getConditionChain(growing)[1], cond('d'));
assert.deepStrictEqual(conditions(getConditionChain(growing)), ['a', 'b', 'c', 'd']);

// A chain that already ends in `else` keeps it; the new branch goes in front.
const withTrailingElse = cond('a', [screen('one')]);
withTrailingElse.has_else = true;
withTrailingElse.else_children = [screen('fallback')];
appendChainElif(withTrailingElse, cond('b'));
const grownChain = getConditionChain(withTrailingElse);
assert.deepStrictEqual(conditions(grownChain), ['a', 'b']);
assert.strictEqual(chainHasFinalElse(withTrailingElse), true);
assert.deepStrictEqual(
  getChainTail(withTrailingElse).else_children.map((s) => s.invoke),
  ['fallback']
);

// Removing a link closes the chain up behind it rather than dropping the rest.
const shrinking = cond('a', [screen('one')]);
const midLink = appendChainElif(shrinking, cond('b', [screen('two')]));
appendChainElif(shrinking, cond('c', [screen('three')]));
assert.strictEqual(removeChainLink(shrinking, midLink), true);
assert.deepStrictEqual(conditions(getConditionChain(shrinking)), ['a', 'c']);

// Removing the only link leaves a plain `if` with no empty else behind it.
const lastLink = cond('a', [screen('one')]);
const onlyLink = appendChainElif(lastLink, cond('b'));
assert.strictEqual(removeChainLink(lastLink, onlyLink), true);
assert.strictEqual(lastLink.has_else, false);
assert.deepStrictEqual(lastLink.else_children, []);

// Removing a link that is not one is refused, so the caller falls back to a
// normal list removal instead of silently rewriting the wrong branch.
assert.strictEqual(removeChainLink(notALink, inner), false);
assert.strictEqual(removeChainLink(null, onlyLink), false);

// A malformed self-referencing branch terminates instead of hanging.
const looped = cond('a');
looped.has_else = true;
looped.else_children = [looped];
assert.deepStrictEqual(conditions(getConditionChain(looped)), ['a']);
