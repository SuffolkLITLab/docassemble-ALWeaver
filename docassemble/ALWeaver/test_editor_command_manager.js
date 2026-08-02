'use strict';

const assert = require('assert');
const commands = require('./data/static/editor_command_manager.js');

function run() {
  const target = {
    value: 'old',
    applyCommandValue: function (_command, value) { this.value = value; },
  };
  const manager = commands.createCommandManager(target);
  const command = commands.createCommand({
    id: 'cmd-title',
    type: 'set-question-text',
    file: 'main.yml',
    blockId: 'question-3',
    before: 'old',
    after: 'new',
    description: 'Change question text',
    sourcePatchFactory: function (_command, document) {
      return [{ type: 'replace-range', start: document.start, end: document.end, text: 'new' }];
    },
  });

  manager.execute(command);
  assert.strictEqual(target.value, 'new');
  assert.strictEqual(command.describe(), 'Change question text');
  assert.deepStrictEqual(command.affectedFiles(), ['main.yml']);
  assert.deepStrictEqual(command.generateSourcePatches({ start: 4, end: 7 }), [
    { type: 'replace-range', start: 4, end: 7, text: 'new' },
  ]);
  assert.strictEqual(manager.canUndo(), true);
  manager.undo();
  assert.strictEqual(target.value, 'old');
  assert.strictEqual(manager.canRedo(), true);
  manager.redo();
  assert.strictEqual(target.value, 'new');

  manager.clear();
  assert.strictEqual(manager.canUndo(), false);
  assert.strictEqual(manager.canRedo(), false);
}

run();
