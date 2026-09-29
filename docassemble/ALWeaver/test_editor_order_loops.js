'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const serializers = require('./data/static/editor_serializers.js');
const inputs = {};
const context = {
  state: {
    blocks: [],
    symbolCatalog: { groups: {} },
    orderSteps: [],
    orderCollapsed: {},
    selectedOrderStepIds: {},
  },
  document: {
    getElementById: (id) => inputs[id] || null,
    querySelector: () => null,
  },
  window: { ALWeaverSerializers: serializers },
  esc: (text) =>
    String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/"/g, '&quot;'),
  _inlineEditStepId: null,
  _lastInsertedOrderStepId: null,
};
vm.createContext(context);
for (const name of [
  'createOrderStep',
  'findStepRecord',
  'getOrderBranchSteps',
  'orderLocationInsideLoop',
  'orderStepFitsLoopContext',
  'insertOrderStepAtLocation',
  'renderOrderStructuredFields',
  'readOrderStructuredFields',
  'getGatherListCandidates',
  'getConditionChain',
  'getChainTail',
  'chainHasFinalElse',
  'renderOrderCodePreview',
  'getOrderStepTypeLabel',
  'getOrderStepHeading',
  'getOrderStepDetail',
  'getOrderStepPresentation',
  'cleanOrderText',
  'renderOrderInsertRow',
  'renderOrderBranch',
  'renderOrderStepTree',
  'renderInlineEditRow',
  'renderOrderChainBranchMenuItems',
  'renderOrderChainLink',
  'syncInlineOrderEdit',
]) {
  const start = source.indexOf(`  function ${name}(`);
  const end = source.indexOf('\n  }', start) + 4;
  assert.ok(start >= 0 && end > start, name);
  vm.runInContext(source.slice(start, end), context);
}
const loop = context.createOrderStep('loop');
loop.target = 'person';
loop.iterable = 'users.complete_elements()';
const branch = context.createOrderStep('condition');
branch.condition = 'person.skip';
const skip = context.createOrderStep('continue');
branch.children.push(skip);
loop.children.push(branch);
context.state.orderSteps = [loop];
assert.strictEqual(context.orderLocationInsideLoop(branch.id), true);
assert.strictEqual(context.orderLocationInsideLoop(''), false);
assert.strictEqual(context.orderStepFitsLoopContext(branch, false), false);
assert.strictEqual(context.orderStepFitsLoopContext(branch, true), true);
assert.strictEqual(context.orderStepFitsLoopContext(loop, false), true);
assert.strictEqual(context.getOrderStepTypeLabel({ kind: 'gather' }), 'gather');
const assignment = context.createOrderStep('assignment');
assignment.target = 'person.complete';
assignment.expression = 'True';
context.insertOrderStepAtLocation(assignment, loop.id, 'then', 1);
assert.strictEqual(loop.children[1], assignment);
assert.strictEqual(
  context.findStepRecord(context.state.orderSteps, skip.id, null).parent,
  branch,
);
assert.strictEqual(
  context.renderOrderCodePreview([loop]),
  '  for person in users.complete_elements():\n    if person.skip:\n      continue\n    person.complete = True',
);
const html = context.renderOrderStepTree([loop], 0, '', 'then');
assert.ok(html.includes(`data-order-parent-step-id="${loop.id}"`));
assert.ok(html.includes('person.complete = True'));
assert.ok(html.includes('Continue with next item'));
const fields = context.renderOrderStructuredFields(
  assignment,
  'order-inline-edit',
);
assert.ok(fields.includes('data-expression-context="value"'));
assert.ok(fields.includes('data-order-field="target"'));
assert.ok(fields.includes('data-order-field="expression"'));
const multiline = context.renderOrderStructuredFields(
  { kind: 'assignment', target: 'result', expression: '(\n  a + b\n)' },
  'order-add',
);
assert.ok(multiline.includes('>(\n  a + b\n)</textarea>'));
inputs['order-inline-edit-target'] = {
  value: 'person.ready',
  hasAttribute: () => true,
};
inputs['order-inline-edit-expression'] = {
  value: 'person.age >= 18',
  hasAttribute: () => true,
};
context._inlineEditStepId = assignment.id;
context.syncInlineOrderEdit();
assert.strictEqual(assignment.target, 'person.ready');
assert.strictEqual(assignment.expression, 'person.age >= 18');
const comment = context.createOrderStep('comment');
inputs['order-add-code'] = {
  value: 'Ask everyone\n# Keep this\n',
  hasAttribute: () => true,
};
context.readOrderStructuredFields(comment, 'order-add');
assert.strictEqual(comment.code, '# Ask everyone\n# Keep this\n');
const commentLoop = {
  kind: 'loop',
  target: 'item',
  iterable: 'items',
  children: [comment],
};
assert.ok(context.renderOrderCodePreview([commentLoop]).endsWith('    pass'));
const commentedElse = {
  kind: 'condition',
  condition: 'a',
  children: [],
  has_else: true,
  _order_else_comment: '# explanation',
  else_children: [{ kind: 'condition', condition: 'b', children: [] }],
};
assert.strictEqual(context.getConditionChain(commentedElse).length, 1);
assert.ok(
  context
    .renderOrderCodePreview([commentedElse])
    .includes('else:  # explanation'),
);
const outer = {
  kind: 'condition',
  condition: 'first',
  has_else: true,
  _order_else_comment: '# fallback',
  else_children: [{ kind: 'screen', invoke: 'last' }],
};
const addedLink = { kind: 'condition', condition: 'second', children: [] };
serializers.appendChainElif(outer, addedLink);
assert.strictEqual(outer._order_else_comment, undefined);
assert.strictEqual(addedLink._order_else_comment, '# fallback');
serializers.removeChainLink(outer, addedLink);
assert.strictEqual(outer._order_else_comment, '# fallback');
