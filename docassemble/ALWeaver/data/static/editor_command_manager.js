/* Reversible editor commands and undo/redo history. */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverCommands = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var nextCommandNumber = 1;

  function clone(value) {
    if (value === undefined) return undefined;
    return JSON.parse(JSON.stringify(value));
  }

  function createCommand(options) {
    options = options || {};
    if (!options.type) throw new TypeError('Commands require a type.');
    if (!options.file) throw new TypeError('Commands require a file.');
    var command = {
      id: options.id || ('cmd-' + nextCommandNumber++),
      type: String(options.type),
      file: String(options.file),
      blockId: options.blockId || null,
      before: clone(options.before),
      after: clone(options.after),
      description: options.description || String(options.type),
      sourcePatchFactory: options.sourcePatchFactory || null,
    };
    command.apply = function (target) {
      if (!target || typeof target.applyCommandValue !== 'function') {
        throw new TypeError('The command target must implement applyCommandValue().');
      }
      return target.applyCommandValue(command, clone(command.after));
    };
    command.invert = function () {
      return createCommand({
        id: command.id + ':inverse',
        type: command.type,
        file: command.file,
        blockId: command.blockId,
        before: command.after,
        after: command.before,
        description: 'Undo ' + command.description,
        sourcePatchFactory: command.sourcePatchFactory,
      });
    };
    command.describe = function () { return command.description; };
    command.generateSourcePatches = function (sourceDocument) {
      if (typeof command.sourcePatchFactory !== 'function') return [];
      var patches = command.sourcePatchFactory(command, sourceDocument);
      return Array.isArray(patches) ? clone(patches) : [];
    };
    command.affectedFiles = function () { return [command.file]; };
    return Object.freeze(command);
  }

  function createCommandManager(target) {
    var undoStack = [];
    var redoStack = [];

    function execute(command) {
      command.apply(target);
      undoStack.push(command);
      redoStack = [];
      return command;
    }

    function recordApplied(command) {
      undoStack.push(command);
      redoStack = [];
      return command;
    }

    function undo() {
      var command = undoStack.pop();
      if (!command) return null;
      command.invert().apply(target);
      redoStack.push(command);
      return command;
    }

    function redo() {
      var command = redoStack.pop();
      if (!command) return null;
      command.apply(target);
      undoStack.push(command);
      return command;
    }

    return {
      execute: execute,
      recordApplied: recordApplied,
      undo: undo,
      redo: redo,
      canUndo: function () { return undoStack.length > 0; },
      canRedo: function () { return redoStack.length > 0; },
      pending: function () { return undoStack.slice(); },
      clear: function () { undoStack = []; redoStack = []; },
    };
  }

  return {
    createCommand: createCommand,
    createCommandManager: createCommandManager,
  };
});
