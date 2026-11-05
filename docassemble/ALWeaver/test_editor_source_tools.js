const assert = require('node:assert/strict');
const {
  completions,
  diagnosticRanges,
} = require('./data/static/editor_source_tools');
const options = completions(
  { project_variables: ['users.name', 'answer'], templates: ['letter'] },
  ['answer', 'users.name'],
  [{ name: 'currency', signature: 'currency(amount)' }],
);
assert.equal(options.length, 4);
assert.equal(options.find((x) => x.label === 'currency').type, 'function');
let transaction;
const view = {
  state: { doc: { sliceString: (from, to) => 'users.na'.slice(from, to) } },
  dispatch: (value) => {
    transaction = value;
  },
};
const option = options.find((x) => x.label === 'users.name');
option.apply(view, option, 6, 8);
assert.deepEqual(transaction.changes, { from: 0, to: 8, insert: 'users.name' });
assert.equal(transaction.selection.anchor, 10);
const text = '# 😀\nquestion: Hello\n';
assert.deepEqual(
  diagnosticRanges(
    text,
    [
      { filename: 'main.yml', line_number: 2, message: 'Review' },
      { filename: 'other.yml', line_number: 1, message: 'Not here' },
      { line_number: 999 },
      { line_number: 0 },
      { message: 'No location' },
      {
        source_range: { start: { line: 1, column: 4 } },
        message: 'After emoji',
      },
    ],
    'main.yml',
  ).map((x) => [x.from, x.to, x.message]),
  [
    [4, 4, 'After emoji'],
    [5, 20, 'Review'],
  ],
);
console.log('source tools tests passed');
const { completionEdit } = require('./data/static/editor_source_tools');
assert.deepEqual(completionEdit('users[0].', 'users[i].name', 9, 11), {
  from: 0,
  to: 11,
  insert: 'users[0].name',
});
assert.deepEqual(completionEdit('other.', 'users.name', 6, 8), {
  from: 0,
  to: 8,
  insert: 'users.name',
});
assert.deepEqual(
  diagnosticRanges(
    'one\ntwo\n',
    [
      {
        source_range: {
          start: { line: 1, column: 2 },
          end: { line: 2, column: 3 },
        },
      },
    ],
    'main.yml',
  ).map((x) => [x.from, x.to]),
  [[1, 6]],
);
