'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const serializers = require('./data/static/editor_serializers.js');
const source = fs.readFileSync(path.join(__dirname, 'data/static/editor.js'), 'utf8');
function editorFunction(name) {
  const start = source.indexOf('  function ' + name + '(');
  assert.notStrictEqual(start, -1, name);
  return source.slice(start, source.indexOf('\n  }\n', start) + 5);
}
function harness(values = {}) {
  const document = {
    getElementById(id) { return values[id] || null; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
  };
  const messages = [];
  const context = {document, window: {ALWeaverSerializers: serializers, alert: message => messages.push(message)},
    esc: text => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'),
    escapeYamlStr: serializers.escapeYamlStr,
    renderMarkdownToolbar: () => '',
    syncMandatoryToData: () => {},
  };
  vm.createContext(context);
  vm.runInContext(source.match(/  var QUESTION_MODIFIER_KEYS = \[[\s\S]*?\n  \];/)[0] + '\n' +
    ['appendYamlText', 'appendYamlValue', 'appendYamlListValue', '_appendQuestionAdvancedYaml', 'renderScreenControls', 'isQuestionEditorBlock', 'syncQuestionMetaToData'].map(editorFunction).join('\n'), context);
  const managed = context.QUESTION_MODIFIER_KEYS.filter(key =>
    !['terms', 'auto terms', 'segment', 'breadcrumb', 'supersedes', 'action buttons', 'tabular'].includes(key));
  return {
    document,
    messages,
    sync(data) {
      const block = {type: 'question', data};
      return context.syncQuestionMetaToData(block) === false ? false : block.data;
    },
    render(data) { return context.renderScreenControls(data, serializers.questionScreenType(data)); },
    serialize(data) {
      return serializers.serializeQuestionToYaml({id: data.id || 'anonymous', data}, {
        document, appendYamlValue: context.appendYamlValue,
        appendQuestionAdvancedYaml: context._appendQuestionAdvancedYaml,
        state: {questionBlockTab: 'options'}, questionModifierKeys: managed,
        serializeQuestionFieldFromData: field => '  - ' + JSON.stringify(field) + '\n',
      });
    },
  };
}

if (process.argv.includes('--serialize')) {
  const blocks = JSON.parse(fs.readFileSync(0, 'utf8'));
  process.stdout.write(JSON.stringify(blocks.map(data => harness().serialize(data))));
} else {
  const signature = {id: 'sign', question: 'Please sign', signature: 'x.signature',
    under: '${ x }\n', required: false, 'pen color': '#33f', 'generic object': 'ALIndividual',
    'validation code': 'x.signature.alt_text = f"Signature of {x.name_full()}"\n'};
  const ui = harness().render(signature);
  ['screen-signature', 'screen-under', 'screen-pen-color', 'screen-required'].forEach(id => assert.ok(ui.includes('id="' + id + '"')));
  assert.ok(!ui.includes('add-field-btn'));
  assert.ok(harness().render({...signature, required: 'must_sign'}).includes(' disabled'));
  const structuredHelp = {label: 'More', content: 'Explanation'};
  const synced = harness({'adv-help': {value: JSON.stringify(structuredHelp), readOnly: true},
    'adv-validation-code': {value: 'x.signature.alt_text = "Signature"  \n'}}).sync({...signature, help: structuredHelp});
  assert.deepStrictEqual(synced.help, structuredHelp);
  assert.strictEqual(synced['validation code'], 'x.signature.alt_text = "Signature"  \n');
  const edited = harness({'screen-signature': {value: 'users[0].signature'},
    'screen-under': {value: ''}, 'screen-required': {value: ''},
    'screen-pen-color': {value: 'navy'}}).serialize(signature);
  assert.ok(edited.includes('"signature": "users[0].signature"'));
  assert.ok(!edited.includes('"under":'));
  assert.ok(!edited.includes('"required":'));
  assert.ok(edited.includes('"pen color": "navy"'));
  assert.ok(edited.includes('generic object: ALIndividual'));
  assert.ok(edited.includes('validation code:'));
  assert.ok(harness().serialize({...signature, required: 'must_sign'}).includes('"required": "must_sign"'));

  const action = {buttons: [{Exit: 'exit', url: 'https://example.com'},
    {Continue: {code: 'agreed = True'}}, {code: 'get_buttons()'},
    {label: 'Yes', value: true, color: 'success', 'show if': 'eligible'}]};
  const editedAction = serializers.readScreenControls(action, harness({
    'screen-choice-label-0': {value: 'Leave'}, 'screen-choice-value-0': {value: 'exit'}, 'screen-choice-type-0': {value: 'string'},
    'screen-choice-label-1': {value: 'Proceed'}, 'screen-choice-value-1': {value: 'ignored', readOnly: true},
    'screen-choice-label-3': {value: 'Agree'}, 'screen-choice-value-3': {value: 'false'}, 'screen-choice-type-3': {value: 'boolean'},
  }).document);
  assert.deepStrictEqual(editedAction.buttons, [{url: 'https://example.com', Leave: 'exit'},
    {Proceed: {code: 'agreed = True'}}, {code: 'get_buttons()'},
    {label: 'Agree', value: false, color: 'success', 'show if': 'eligible'}]);
  assert.deepStrictEqual(serializers.readScreenControls(action, harness().document), action);
  assert.ok(harness().render(action).includes('edit in YAML'));
  // Labels used as mapping keys must never replace metadata or become code.
  const reservedLabels = ['color', 'url', 'code', 'image', 'help', 'default',
    'css class', 'show if', 'label', 'value', '__proto__'];
  ['buttons', 'choices', 'dropdown', 'combobox'].forEach(kind => {
    reservedLabels.forEach(label => {
      const controls = harness({'screen-choice-label-0': {value: label}});
      [{Exit: 'exit', color: 'danger', url: 'https://example.com'},
        {Continue: {code: 'agreed = True'}, color: 'success'}, 'Exit'].forEach(item => {
        const original = {question: 'Choose', [kind]: [item]};
        const before = JSON.stringify(original);
        assert.strictEqual(controls.sync(original), false);
        assert.match(controls.messages.at(-1), /choice label.*reserved or conflicts/);
        assert.throws(() => controls.serialize(original), /choice label.*reserved or conflicts/);
        assert.strictEqual(JSON.stringify(original), before, 'Rejected renames leave all data intact');
      });
      // Explicit label/value entries can safely display reserved words.
      const expanded = {label: 'Exit', value: 'exit', color: 'danger'};
      const updated = controls.sync({[kind]: [expanded]})[kind][0];
      assert.deepStrictEqual(updated, {...expanded, label});
      assert.strictEqual(serializers.screenChoice(updated).label, label);
      assert.strictEqual(serializers.screenChoice(updated).computed, undefined);
    });
  });
  const collision = {buttons: [{Exit: 'exit', custom_setting: 'preserve me'}]};
  assert.strictEqual(harness({'screen-choice-label-0': {value: 'custom_setting'}}).sync(collision), false);
  assert.deepStrictEqual(collision.buttons[0], {Exit: 'exit', custom_setting: 'preserve me'});
  // A literal reserved word may remain a scalar, but cannot become shorthand.
  const scalarWord = {buttons: ['color']};
  const scalarControls = {'screen-choice-label-0': {value: 'color'},
    'screen-choice-value-0': {value: 'color'}, 'screen-choice-type-0': {value: 'string'}};
  assert.deepStrictEqual(harness(scalarControls).sync(scalarWord), scalarWord);
  assert.strictEqual(harness({...scalarControls, 'screen-choice-value-0': {value: 'exit'}}).sync(scalarWord), false);

  assert.throws(() => harness({'screen-choice-label-0': {value: 'Bad'},
    'screen-choice-value-0': {value: 'no number'}, 'screen-choice-type-0': {value: 'number'}}).serialize(action), /valid number/);
  assert.throws(() => harness({'screen-signature': {value: ''}}).serialize(signature), /variable/);
  ['yesno', 'noyes', 'yesnomaybe', 'noyesmaybe'].forEach(kind => {
    ['', '   '].forEach(value => {
      const control = harness({['screen-' + kind]: {value}});
      const original = {question: 'Agree?', [kind]: 'answer'};
      assert.strictEqual(control.sync(original), false);
      assert.match(control.messages.at(-1), /Enter an answer variable/);
      assert.throws(() => control.serialize(original), /Enter an answer variable/);
      assert.strictEqual(original[kind], 'answer');
    });
  });
  const legacy = {question: 'Terms', field: 'accepted', fields: [{Name: 'name'}]};
  assert.strictEqual(serializers.questionScreenType(legacy), 'fields');
  assert.strictEqual(serializers.normalizeQuestionData(legacy)['continue button field'], 'accepted');
  assert.strictEqual(serializers.normalizeQuestionData({...legacy, 'continue button field': 'explicit'})['continue button field'], 'explicit');
  const migrated = harness().serialize(legacy);
  assert.ok(migrated.includes('continue button field: accepted'));
  assert.ok(!migrated.includes('"field":'));
  assert.strictEqual(legacy.field, 'accepted'); // Loading does not modify the source object.
  ['signature', 'buttons', 'yesno', 'noyes', 'yesnomaybe', 'noyesmaybe', 'choices', 'dropdown', 'combobox', 'field'].forEach(kind => {
    const yaml = serializers.makeNewBlockYaml(kind, 123);
    assert.ok(yaml.includes('\n' + kind + ':'), kind);
    assert.ok(!yaml.includes('\nfields:'), kind);
  });
  console.log('editor screen type checks passed');
}
