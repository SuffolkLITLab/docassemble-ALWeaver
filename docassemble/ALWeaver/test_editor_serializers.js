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

function makeDocument(type, modifiers) {
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

function serialize(type, modifiers) {
  return serializers.serializeQuestionToYaml({ id: 'question_id', data: {} }, {
    document: makeDocument(type, modifiers),
    appendYamlValue,
    appendYamlBlockValue,
    fieldTypeSupportsStandaloneContent(value) {
      return ['note', 'html', 'raw html', 'code'].indexOf(value) !== -1;
    },
    choiceTypes: [
      'radio', 'checkboxes', 'combobox', 'multiselect', 'dropdown',
      'object', 'object_radio', 'object_checkboxes', 'object_multiselect',
    ],
    state: { markdownPreviewMode: false, questionBlockTab: 'screen' },
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
