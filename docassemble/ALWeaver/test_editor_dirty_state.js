'use strict';

const assert = require('assert');
const dirtyStateModule = require('./data/static/editor_dirty_state.js');

const dirty = dirtyStateModule.createDirtyState();
dirty.activate('interview.yml', 'intro');
dirty.setFileSaved('interview.yml', 'revision-1', [{ id: 'intro', question: 'Saved' }]);
assert.strictEqual(dirty.hasDirty('interview.yml'), false);

dirty.markBlockDirty('intro', 'edit:intro');
assert.strictEqual(dirty.hasDirty('interview.yml'), true);
assert.deepStrictEqual(dirty.getFileState('interview.yml').dirtyBlockIds, ['intro']);

dirty.markBlockSaved('intro', 'revision-2', [{ id: 'intro', question: 'Changed' }]);
assert.strictEqual(dirty.hasDirty('interview.yml'), false);

dirty.markSourceDirty('edit:source');
assert.strictEqual(dirty.hasDirty('interview.yml'), true);
assert.deepStrictEqual(dirty.discardFile('interview.yml'), [
  { id: 'intro', question: 'Changed' },
]);
assert.strictEqual(dirty.hasDirty('interview.yml'), false);

const merged = dirtyStateModule.preserveDirtyBlocks(
  [
    { id: 'intro', question: 'Server intro' },
    { id: 'details', question: 'Server details' },
  ],
  [
    { id: 'intro', question: 'Local intro' },
    { id: 'details', question: 'Local details' },
  ],
  ['intro', 'details'],
  'intro'
);
assert.deepStrictEqual(merged, [
  { id: 'intro', question: 'Server intro' },
  { id: 'details', question: 'Local details' },
]);
