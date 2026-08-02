'use strict';

const assert = require('assert');
const dirty = require('./data/static/editor_dirty_state.js');

function run() {
  const tracker = dirty.createDirtyState();
  const initialModel = {
    rawYaml: '---\nid: first\nquestion: Original\n',
    blocks: [
      { id: 'first', data: { question: 'Original' } },
      { id: 'second', data: { question: 'Second' } },
    ],
  };

  tracker.setFileSaved('main.yml', 'rev-1', initialModel);
  tracker.activate('main.yml', 'first');
  assert.deepStrictEqual(tracker.getState(), {
    files: {
      'main.yml': {
        revision: 'rev-1',
        sourceDirty: false,
        dirtyBlockIds: [],
        pendingCommandIds: [],
      },
    },
    activeFile: 'main.yml',
    activeBlockId: 'first',
  });

  tracker.markBlockDirty('first', 'cmd-first');
  tracker.markBlockDirty('second', 'cmd-second');
  assert.strictEqual(tracker.hasDirty('main.yml'), true);
  assert.deepStrictEqual(tracker.getFileState('main.yml').dirtyBlockIds, ['first', 'second']);

  tracker.markBlockSaved('first', 'rev-2', {
    rawYaml: 'saved first',
    blocks: [
      { id: 'first', data: { question: 'Changed' } },
      { id: 'second', data: { question: 'Second' } },
    ],
  });
  assert.deepStrictEqual(tracker.getFileState('main.yml').dirtyBlockIds, ['second']);
  assert.deepStrictEqual(tracker.getFileState('main.yml').pendingCommandIds, ['cmd-second']);
  assert.strictEqual(tracker.hasDirty('main.yml'), true);

  const restored = tracker.discardFile('main.yml');
  assert.strictEqual(restored.rawYaml, 'saved first');
  assert.strictEqual(restored.blocks[0].data.question, 'Changed');
  assert.strictEqual(tracker.hasDirty('main.yml'), false);

  restored.blocks[0].data.question = 'Mutated copy';
  assert.strictEqual(tracker.getSavedModel('main.yml').blocks[0].data.question, 'Changed');

  tracker.markSourceDirty('cmd-source');
  assert.strictEqual(tracker.getFileState('main.yml').sourceDirty, true);
  assert.deepStrictEqual(tracker.getFileState('main.yml').pendingCommandIds, ['cmd-source']);
  tracker.setFileSaved('main.yml', 'rev-3', { rawYaml: '', blocks: [] });
  assert.strictEqual(tracker.hasDirty('main.yml'), false);

  const mergedBlocks = dirty.preserveDirtyBlocks(
    [
      { id: 'first', data: { question: 'Saved first' } },
      { id: 'second', data: { question: 'Remote second' } },
    ],
    [
      { id: 'first', data: { question: 'Local first' } },
      { id: 'second', data: { question: 'Unsaved local second' } },
    ],
    ['first', 'second'],
    'first'
  );
  assert.strictEqual(mergedBlocks[0].data.question, 'Saved first');
  assert.strictEqual(mergedBlocks[1].data.question, 'Unsaved local second');

  const unsnapshotted = dirty.createDirtyState();
  unsnapshotted.activate('draft.yml', 'draft-block');
  unsnapshotted.markBlockDirty('draft-block');
  assert.strictEqual(unsnapshotted.discardFile('draft.yml'), undefined);
  assert.strictEqual(unsnapshotted.hasDirty('draft.yml'), true);
}

run();
