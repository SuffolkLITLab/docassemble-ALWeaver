'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const report = require('./data/static/editor_interview_report.js');

const responses = {
  'child.yml': {
    blocks: [
      { id: 'child_include', data: { include: ['nested.yml'] } },
      { id: 'child_question', data: { question: 'Child screen' } },
    ],
    named_order_steps: {
      child_done: [{ kind: 'screen', invoke: 'child_screen' },
        { kind: 'screen', invoke: 'nested_done' }],
    },
  },
  'nested.yml': {
    blocks: [
      { id: 'nested_include', data: { include: 'docassemble.Framework:flow.yml' } },
    ],
    named_order_steps: {
      nested_done: [{ kind: 'screen', invoke: 'nested_screen' },
        { kind: 'screen', invoke: 'framework_done' }],
    },
  },
  'docassemble.Framework:flow.yml': {
    blocks: [{ id: 'framework_question', data: { question: 'Framework screen' } }],
    named_order_steps: {
      framework_done: [{ kind: 'screen', invoke: 'framework_screen' }],
    },
  },
};
const requested = [];
const context = {
  state: {
    filename: 'main.yml', project: 'default',
    blocks: [{ id: 'main_include', data: { include: 'child.yml' } }],
    orderStepMap: {}, orderSteps: [], activeOrderBlockId: null,
  },
  MAX_REPORT_INCLUDED_FILES: 40,
  apiGet: (url) => {
    const name = new URL(url, 'https://example.test').searchParams.get(
      url.startsWith('/api/package-file') ? 'reference' : 'filename');
    requested.push(name);
    return Promise.resolve({ success: true, data: responses[name] });
  },
};
vm.createContext(context);
for (const name of ['_includeTargets', '_collectInterviewBlocks']) {
  const start = source.indexOf(`  function ${name}(`);
  const end = source.indexOf('\n  }', start) + 4;
  assert.ok(start >= 0 && end > start, name);
  vm.runInContext(source.slice(start, end), context);
}

context._collectInterviewBlocks().then((collected) => {
  assert.deepStrictEqual(requested, [
    'child.yml', 'nested.yml', 'docassemble.Framework:flow.yml',
  ]);
  const expanded = report.expandNamedOrders(
    [{ kind: 'screen', invoke: 'child_done' }], collected.namedOrders);
  assert.deepStrictEqual(expanded.map((step) => step.invoke), [
    'child_screen', 'nested_screen', 'framework_screen',
  ]);
  assert.strictEqual(collected.blocks.length, 5);
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
