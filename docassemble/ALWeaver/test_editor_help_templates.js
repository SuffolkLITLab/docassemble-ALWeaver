'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
function editorFunction(name) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, name);
  const end = source.indexOf('\n  }\n', start);
  return source.slice(start, end + '\n  }'.length);
}
function template(id, name, subject) {
  return {id, type: 'template', data: {template: name, content: 'Help', subject}};
}
const context = {
  state: {selectedBlockId: 'question', blocks: [
    template('en', 'shared_help', 'English'),
    template('es', 'shared_help', 'Spanish'),
    template('no-subject', 'other_help', ''),
    template('with-subject', 'other_help', 'Other'),
    template('advanced', 'person[i].help', 'Advanced'),
  ]},
  window: {ALWeaverSerializers: require('./data/static/editor_serializers.js')},
};
context.getSelectedBlock = () => context.state.blocks.find((block) => block.id === context.state.selectedBlockId);
vm.createContext(context);
vm.runInContext(['isTemplateEditorBlock', 'availableHelpTemplates'].map(editorFunction).join('\n'), context);
assert.deepEqual(Array.from(context.availableHelpTemplates(), (block) => block.id), ['en', 'with-subject']);
// Exclude every variant of the current name to prevent indirect self-insertion.
context.state.selectedBlockId = 'es';
assert.deepEqual(Array.from(context.availableHelpTemplates(), (block) => block.id), ['with-subject']);
console.log('Help template picker groups variants and prevents self-insertion');
