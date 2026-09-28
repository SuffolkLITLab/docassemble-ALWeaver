'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const start = source.indexOf('  function _newProjectJobFailureMessage(');
const end = source.indexOf('\n  function _pollNewProjectJob(', start);
assert.notStrictEqual(start, -1);
assert.notStrictEqual(end, -1);
const context = {};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

const message = context._newProjectJobFailureMessage({
  status: 'failed',
  data: {
    stage: 'copy_templates',
    error: { message: 'ALWeaver generation failed.' },
    result: {
      partial_artifacts: ['petition.yml'],
      incomplete_artifacts: ['petition.pdf'],
      incomplete_stage: 'copy_templates',
    },
  },
});
assert.ok(message.includes('Stopped during copy_templates.'));
assert.ok(message.includes('Partial files saved: petition.yml.'));
assert.ok(message.includes('Outputs that may be incomplete: petition.pdf.'));
assert.ok(!message.includes('/tmp/'));

const noArtifacts = context._newProjectJobFailureMessage({
  data: {
    stage: 'generate_interview',
    error: { message: 'Generation failed.' },
  },
});
assert.strictEqual(
  noArtifacts,
  'Generation failed. Stopped during generate_interview.',
);
console.log('new-project job failure reporting checks passed');
