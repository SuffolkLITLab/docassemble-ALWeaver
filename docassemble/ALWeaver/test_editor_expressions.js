const assert = require('node:assert/strict');
// Controls absent from the Screen tab must not delete the Options condition.
const fs = require('fs');
const path = require('path');
const editorSource = fs.readFileSync(path.join(__dirname, 'data/static/editor.js'), 'utf8');
const syncSource = editorSource.slice(editorSource.indexOf('  function syncQuestionMetaToData('), editorSource.indexOf('  function syncFieldsToData('));
const controls = {};
const syncQuestion = new Function('document', 'window', syncSource + '\nreturn syncQuestionMetaToData;')(
  { getElementById: id => controls[id] || null },
  { ALWeaverSerializers: require('./data/static/editor_serializers.js') },
);
const question = {type: 'question', data: {if: 'eligible', mandatory: 'run_question'}};
syncQuestion(question);
assert.deepEqual(question.data, {if: 'eligible', mandatory: 'run_question'});
controls['adv-enable-if'] = {checked: true};
controls['adv-if'] = {value: 'approved'};
syncQuestion(question);
assert.equal(question.data.if, 'approved');
controls['adv-enable-if'].checked = false;
syncQuestion(question);
assert.equal(question.data.if, undefined);
const {python, fresh, changeType} = require('./data/static/editor_expressions.js');
const variable = value => ({kind: 'variable', value});
assert.equal(python({kind: 'operator', op: 'and', args: [
  {kind: 'comparison', ops: ['<='], args: [variable('household_income'), variable('poverty_limit')]},
  {kind: 'comparison', ops: ['>='], args: [variable('applicant.age'), {kind: 'number', value: '18'}]},
]}), '((household_income <= poverty_limit) and (applicant.age >= 18))');
assert.equal(python({kind: 'comparison', ops: ['<', '<='], args: [variable('low'), variable('middle'), variable('high')]}), '(low < middle <= high)');
assert.equal(python({kind: 'text', value: 'quote "\n\\😀'}), '"quote \\"\\n\\\\😀"');
assert.equal(python({kind: 'tuple', args: [variable('x')]}), '(x,)');
assert.equal(python({kind: 'function', name: 'today', args: []}), 'today()');
assert.equal(python({kind: 'operator', op: 'not', args: [variable('eligible')]}), '(not eligible)');
assert.equal(python(fresh('boolean')), 'True');
assert.equal(python(fresh('none')), 'None');
const wrapped = changeType(variable('household_income'), 'function');
assert.equal(python(wrapped), 'len(household_income)');
assert.equal(changeType(wrapped, 'function'), wrapped);
const calculation = changeType(fresh('operator'), 'calculation');
assert.equal(calculation.op, '+');
assert.equal(changeType(calculation, 'operator').op, 'and');
// Switching between Conditions and Calculation keeps the author's operands.
const twoOperands = {kind: 'operator', op: 'and', args: [variable('a'), variable('b'), variable('c')]};
assert.equal(python(changeType(twoOperands, 'calculation')), '(a + b + c)');
assert.equal(python(changeType(twoOperands, 'operator')), '(a and b and c)');
assert.equal(python(changeType({kind: 'operator', op: 'not', args: [variable('a')]}, 'operator')), '(not a)');
assert.equal(python({kind: 'function', name: 'custom', args: [wrapped, variable('poverty_limit')], keywords: [null, 'limit']}), 'custom(len(household_income), limit=poverty_limit)');
console.log('Expression generation passed');
