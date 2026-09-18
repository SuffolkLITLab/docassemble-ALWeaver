'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
// Exercise the actual editor functions with the model returned for YAML that
// opens with --- and has an empty document between its two order blocks.
const context = {
  state: {
    blocks: [
      { id: 'metadata', index: 1 },
      { id: 'interview_order_form', index: 2, type: 'code' },
      { id: 'main', index: 4, type: 'code' },
      { id: 'intro', index: 5, type: 'question' },
    ],
    orderIndices: [2, 4],
    activeOrderBlockId: null,
    jumpTarget: 'order',
  },
  getBlockDisplayType: (block) => block.type,
};
vm.createContext(context);
for (const name of [
  'getBlockById',
  'getOrderBlocks',
  'isOrderBlockId',
  'getDefaultOrderBlockId',
  'jumpTargetMatcher',
]) {
  const start = source.indexOf(`  function ${name}(`);
  const end = source.indexOf('\n  }', start) + 4;
  assert.ok(start >= 0 && end > start);
  vm.runInContext(source.slice(start, end), context);
}
assert.deepStrictEqual(
  Array.from(context.getOrderBlocks(), (b) => b.id),
  ['interview_order_form', 'main'],
);
assert.strictEqual(context.getDefaultOrderBlockId(), 'interview_order_form');
assert.strictEqual(context.isOrderBlockId('intro'), false);
assert.strictEqual(context.isOrderBlockId('main'), true);
assert.deepStrictEqual(
  context.state.blocks.filter(context.jumpTargetMatcher()).map((b) => b.id),
  ['interview_order_form', 'main'],
);
context.state.activeOrderBlockId = 'main';
assert.strictEqual(context.getDefaultOrderBlockId(), 'main');
// The final document may be the only order block.
context.state.blocks = [{ id: 'only_order', index: 3, type: 'code' }];
context.state.orderIndices = [3];
context.state.activeOrderBlockId = null;
assert.strictEqual(context.getDefaultOrderBlockId(), 'only_order');
