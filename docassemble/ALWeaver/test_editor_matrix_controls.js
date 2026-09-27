'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const serializers = require('./data/static/editor_serializers.js');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const body = {innerHTML: ''};
const save = {disabled: true};
const context = {
  window: {ALWeaverSerializers: serializers},
  state: {blocks: [{type: 'objects', data: {objects: [{'household.jobs': 'custom.DAList'}]}}], symbolCatalog: {groups: {lists: ['x.incomes', 'people[i].jobs']}}},
  document: {getElementById: id => id === 'order-add-body' ? body : save},
  esc: String,
  escapeYamlStr: serializers.escapeYamlStr,
};
vm.createContext(context);
for (const name of ['_normalizeObjectClassName', '_isDaListLikeClass', 'getGatherListCandidates', 'renderOrderAddBody', 'renderOrderCodePreview', 'readExpressionModifier', 'appendYamlValue']) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0);
  vm.runInContext(source.slice(start, source.indexOf('\n  }\n', start) + 5), context);
}
assert.deepStrictEqual(Array.from(context.getGatherListCandidates(), v => v.variable), ['household.jobs', 'people[i].jobs', 'x.incomes']);
context.state.blocks = [];
context.state.symbolCatalog.groups = {};
context.renderOrderAddBody('gather');
assert.ok(body.innerHTML.includes('<input'));
assert.ok(body.innerHTML.includes('custom or nested list variable'));
assert.strictEqual(save.disabled, false);
assert.strictEqual(context.readExpressionModifier({value:'0'}, 0), 0);
assert.strictEqual(context.readExpressionModifier({value:'false'}, false), false);
assert.strictEqual(context.appendYamlValue('', 'progress', '99'), 'progress: 99\n');
assert.strictEqual(context.appendYamlValue('', 'continue button label', 'No'), 'continue button label: "No"\n');
assert.strictEqual(context.appendYamlValue('', 'back button', 'false'), 'back button: false\n');
const label = "Client's \\ details\nnext";
for (const call of ['set_parts', 'nav.set_section']) {
  const expected = call === 'set_parts' ? 'set_parts(subtitle=' : 'nav.set_section(';
  assert.strictEqual(context.renderOrderCodePreview([{kind:'section',call,value:label}], 2), '  ' + expected + JSON.stringify(label) + ')');
}
