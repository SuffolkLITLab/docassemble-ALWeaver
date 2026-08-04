'use strict';

const assert = require('assert');
const validationSource = require('./data/static/editor_validation_source.js');

const original = [
  '# leading comment',
  '---',
  "metadata:",
  "  title: 'Saved'",
  '---',
  '# keep this comment',
  'id: intro',
  'question: Saved question',
  '---',
  'code: |',
  '  untouched = True',
  '',
].join('\n');

const blocks = [
  { id: 'metadata-0', type: 'metadata', line_start: 3, line_end: 4 },
  { id: 'intro', type: 'question', line_start: 6, line_end: 8 },
  { id: 'code-2', type: 'code', line_start: 10, line_end: 11 },
];

const blockResult = validationSource.buildValidationSource({
  rawYaml: original,
  blocks,
  blockReplacements: {
    intro: '# keep this comment\nid: intro\nquestion: Unsaved question',
  },
});
assert.strictEqual(
  blockResult,
  original.replace('question: Saved question', 'question: Unsaved question')
);

const crlfOriginal = original.replace(/\n/g, '\r\n');
const crlfBlockResult = validationSource.buildValidationSource({
  rawYaml: crlfOriginal,
  blocks,
  blockReplacements: {
    intro: '# keep this comment\nid: intro\nquestion: Unsaved question',
  },
});
assert.strictEqual(
  crlfBlockResult,
  crlfOriginal.replace('question: Saved question', 'question: Unsaved question')
);
assert.ok(!/(^|[^\r])\n/.test(crlfBlockResult), 'validation snapshot contains mixed LF line endings');

const metadataResult = validationSource.buildValidationSource({
  rawYaml: original,
  blocks,
  metadataSource: "metadata:\n  title: 'Unsaved'",
});
assert.strictEqual(
  metadataResult,
  original.replace("title: 'Saved'", "title: 'Unsaved'")
);

const fullSource = 'invalid: [unsaved';
assert.strictEqual(
  validationSource.buildValidationSource({ rawYaml: original, blocks, fullSource }),
  fullSource
);

assert.throws(
  () => validationSource.buildValidationSource({
    rawYaml: original,
    blocks,
    metadataSource: 'metadata:\n  title: One\n---\ninclude:\n  - extra.yml',
  }),
  /no longer match/
);
