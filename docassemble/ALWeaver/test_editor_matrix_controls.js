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

for (const declaration of ['ALPeopleList.using(ask_number=True)', 'module.ALPeopleList.using(ask_number=True)', 'module.DAList.using(object_type=Thing)', 'DAList', 'module.DAList']) {
  assert.strictEqual(context._isDaListLikeClass(declaration), true, declaration);
}
assert.strictEqual(context._isDaListLikeClass('Individual.using()'), false);
assert.strictEqual(context._normalizeObjectClassName('module.ALPeopleList.using(ask_number=True)'), 'ALPeopleList');
assert.ok(!body.innerHTML.includes('placeholder='));
assert.ok(body.innerHTML.includes('<code>household[i].jobs</code>'));
assert.ok(body.innerHTML.includes('aria-describedby="order-gather-help"'));
assert.strictEqual(context.appendYamlValue('', 'skip undefined', 'False'), 'skip undefined: false\n');
assert.strictEqual(context.appendYamlValue('', 'skip undefined', 'True'), 'skip undefined: true\n');

// Run the real review and inactive-field serializers, not only their helpers.
context._explicitBlockId = block => block.data.id;
context.document = {getElementById: () => null, querySelectorAll: () => []};
context._yamlKeyValueLines = () => [];
context.serializeReviewItemData = () => '- Edit: answer';
for (const name of ['serializeReviewToYaml', 'expressionModifierYamlValue', 'fieldChoicesAreExpression', '_serializeQuestionFieldFromData']) {
  const start = source.indexOf(`  function ${name}(`);
  vm.runInContext(source.slice(start, source.indexOf('\n  }\n', start)+5), context);
}
context._fieldTypeSupportsStandaloneContent = () => false;
const reviewYaml = context.serializeReviewToYaml({data:{id:'review',question:'Review',review:[{Edit:'answer'}], 'skip undefined':false}});
assert.ok(reviewYaml.includes('skip undefined: false\n'));
const {spawnSync} = require('child_process');
for (const field of [{label:'Name',field:'name','disable others':true}, {label:'Pick',field:'pick',datatype:'radio',choices:['Yes','No'],shuffle:false}, {label:'Person',field:'person',datatype:'object_radio',choices:'people'}]) {
  const encoded = 'fields:\n' + context._serializeQuestionFieldFromData(field);
  const result = spawnSync(process.env.PYTHON || 'python', ['-c', 'import sys,json,yaml;print(json.dumps(yaml.safe_load(sys.stdin.read())))'], {input:encoded,encoding:'utf8'});
  assert.strictEqual(result.status,0,result.stderr);
  const actual = JSON.parse(result.stdout).fields[0];
  for (const key of ['disable others','shuffle']) if (key in field) assert.strictEqual(actual[key],field[key]);
  if (typeof field.choices === 'string') assert.strictEqual(actual.choices, field.choices);
}
if (process.argv.includes('--review-yaml')) process.stdout.write(reviewYaml);
if (process.argv.includes('--field-yaml')) {
  process.stdout.write('id: typed_settings\nquestion: Test settings\nfields:\n' +
    context._serializeQuestionFieldFromData({label:'Name',field:'name','disable others':true}) +
    context._serializeQuestionFieldFromData({label:'Pick',field:'pick',datatype:'radio',choices:['Yes','No'],shuffle:false}));
}

// A rapid Add action may finish while Bootstrap is still opening the modal.
{
  const start=source.indexOf('  function closeBootstrapModal(');
  vm.runInContext(source.slice(start,source.indexOf('\n  }\n',start)+5),context);
  let shown=true, transitioning=true, deferred=null, calls=0;
  const modal={classList:{contains:()=>shown},addEventListener:(event,fn,options)=>{
    assert.strictEqual(event,'shown.bs.modal');assert.strictEqual(options.once,true);deferred=fn;
  }};
  const instance={hide:()=>{calls++;if(!transitioning)shown=false;}};
  context.bootstrap={Modal:{getInstance:()=>instance}};
  context.document={getElementById:()=>modal};
  context.closeBootstrapModal('order-add-modal');
  assert.strictEqual(calls,1);assert.ok(deferred);
  transitioning=false;deferred();assert.strictEqual(shown,false);
  deferred=null;shown=true;
  context.closeBootstrapModal('order-add-modal');
  assert.strictEqual(shown,false);assert.strictEqual(deferred,null);
}

// Missing required bundle must explain the failure in the pane itself.
const sourcePane = {innerHTML: '', appendChild(el) { this.alert = el; }};
context.document = {
  getElementById: () => sourcePane,
  createElement: () => ({setAttribute(name, value) { this[name] = value; }}),
};
const sourceStart = source.indexOf('  function createSourceEditor(');
vm.runInContext(source.slice(sourceStart, source.indexOf('\n  }\n', sourceStart) + 5), context);
assert.throws(() => context.createSourceEditor('source', 'title: Keep', 'yaml'), /CodeMirror bundle is missing/);
assert.strictEqual(sourcePane.alert.role, 'alert');
assert.ok(sourcePane.alert.textContent.includes('Reload this page'));
context.window.daNewEditor = () => null;
assert.throws(() => context.createSourceEditor('source', '', 'yaml'), /could not initialize/);
assert.ok(sourcePane.alert.textContent.includes('administrator'));
assert.strictEqual(context.expressionModifierYamlValue('none of the above', 'False'), '"False"');
assert.strictEqual(context.expressionModifierYamlValue('all of the above', false), 'false');

// Completed jobs keep result warnings nested, unlike their summary fields.
const warningStart = source.indexOf('  function _newProjectGenerationWarnings(');
vm.runInContext(source.slice(warningStart, source.indexOf('\n  }\n', warningStart) + 5), context);
assert.deepStrictEqual(Array.from(context._newProjectGenerationWarnings({status: 'succeeded', result: {warnings: ['Conflicting text and checkbox types', '', null]}})), ['Conflicting text and checkbox types']);
assert.deepStrictEqual(Array.from(context._newProjectGenerationWarnings({result: {}})), []);
assert.deepStrictEqual(Array.from(context._newProjectGenerationWarnings({warnings: ['Direct result']})), ['Direct result']);

// A failed rollback must expose recovery content, not only a generic error.
const recoveryStatus = {children: [], appendChild(node) { this.children.push(node); }};
context.projectSearchElement = () => recoveryStatus;
context.document = {createElement: tag => ({tag, addEventListener(name, callback) { this[name] = callback; }})};
const recoveryStart = source.indexOf('  function showProjectReplacementRecovery(');
vm.runInContext(source.slice(recoveryStart, source.indexOf('\n  }\n', recoveryStart) + 5), context);
context.showProjectReplacementRecovery({details: {recovery_files: [{section:'interview', filename:'second.yml', original_content:'question: Original'}]}});
assert.ok(recoveryStatus.children[0].textContent.includes('interview/second.yml'));
assert.strictEqual(recoveryStatus.children[1].textContent, 'Download recovery JSON');
assert.strictEqual(typeof recoveryStatus.children[1].click, 'function');
