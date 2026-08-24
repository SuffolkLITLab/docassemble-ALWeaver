/* Per-file and per-block unsaved-change tracking for the graphical editor. */
(function (/** @type {any} */ root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverDirtyState = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function clone(value) {
    if (value === undefined) return undefined;
    return JSON.parse(JSON.stringify(value));
  }

  function createFileState(revision) {
    return {
      revision: revision || null,
      sourceDirty: false,
      dirtyBlockIds: [],
      pendingCommandIds: [],
    };
  }

  function preserveDirtyBlocks(
    serverBlocks,
    localBlocks,
    dirtyBlockIds,
    savedBlockId,
  ) {
    var localById = {};
    (localBlocks || []).forEach(function (block) {
      if (block && block.id) localById[block.id] = block;
    });
    var preserveIds = (dirtyBlockIds || []).filter(function (blockId) {
      return blockId !== savedBlockId;
    });
    return (serverBlocks || []).map(function (serverBlock) {
      if (
        !serverBlock ||
        preserveIds.indexOf(serverBlock.id) === -1 ||
        !localById[serverBlock.id]
      ) {
        return clone(serverBlock);
      }
      return clone(localById[serverBlock.id]);
    });
  }

  function createDirtyState() {
    var state = {
      files: {},
      activeFile: null,
      activeBlockId: null,
    };
    var savedModels = {};
    var commandBlocks = {};

    function requireFile(filename, revision) {
      var target = filename || state.activeFile;
      if (!target) return null;
      if (!state.files[target]) state.files[target] = createFileState(revision);
      if (revision !== undefined) state.files[target].revision = revision;
      if (!commandBlocks[target]) commandBlocks[target] = {};
      return state.files[target];
    }

    function activate(filename, blockId) {
      state.activeFile = filename || null;
      state.activeBlockId = blockId || null;
      if (filename) requireFile(filename);
    }

    function setActiveBlock(blockId) {
      state.activeBlockId = blockId || null;
    }

    function addCommand(fileState, filename, commandId, blockId) {
      if (!commandId || fileState.pendingCommandIds.indexOf(commandId) !== -1)
        return;
      fileState.pendingCommandIds.push(commandId);
      commandBlocks[filename][commandId] = blockId || null;
    }

    function markBlockDirty(blockId, commandId, filename) {
      var target = filename || state.activeFile;
      var fileState = requireFile(target);
      var targetBlock = blockId || state.activeBlockId;
      if (!fileState || !targetBlock) return;
      if (fileState.dirtyBlockIds.indexOf(targetBlock) === -1) {
        fileState.dirtyBlockIds.push(targetBlock);
      }
      addCommand(
        fileState,
        target,
        commandId || 'edit-block:' + targetBlock,
        targetBlock,
      );
    }

    function markSourceDirty(commandId, filename) {
      var target = filename || state.activeFile;
      var fileState = requireFile(target);
      if (!fileState) return;
      fileState.sourceDirty = true;
      addCommand(fileState, target, commandId || 'edit-source:' + target, null);
    }

    function setFileSaved(filename, revision, model) {
      var fileState = requireFile(filename, revision);
      if (!fileState) return;
      fileState.sourceDirty = false;
      fileState.dirtyBlockIds = [];
      fileState.pendingCommandIds = [];
      commandBlocks[filename] = {};
      savedModels[filename] = clone(model);
    }

    function markBlockSaved(blockId, revision, model, filename) {
      var target = filename || state.activeFile;
      var fileState = requireFile(target, revision);
      if (!fileState) return;
      fileState.dirtyBlockIds = fileState.dirtyBlockIds.filter(function (id) {
        return id !== blockId;
      });
      fileState.pendingCommandIds = fileState.pendingCommandIds.filter(
        function (commandId) {
          var keep = commandBlocks[target][commandId] !== blockId;
          if (!keep) delete commandBlocks[target][commandId];
          return keep;
        },
      );
      savedModels[target] = clone(model);
    }

    function getFileState(filename) {
      var fileState = state.files[filename || state.activeFile];
      return fileState ? clone(fileState) : null;
    }

    function hasDirty(filename) {
      var fileState = state.files[filename || state.activeFile];
      return Boolean(
        fileState &&
        (fileState.sourceDirty ||
          fileState.dirtyBlockIds.length ||
          fileState.pendingCommandIds.length),
      );
    }

    function getSavedModel(filename) {
      return clone(savedModels[filename || state.activeFile]);
    }

    function discardFile(filename) {
      var target = filename || state.activeFile;
      if (!Object.prototype.hasOwnProperty.call(savedModels, target))
        return undefined;
      var fileState = requireFile(target);
      if (!fileState) return undefined;
      fileState.sourceDirty = false;
      fileState.dirtyBlockIds = [];
      fileState.pendingCommandIds = [];
      commandBlocks[target] = {};
      return getSavedModel(target);
    }

    return {
      activate: activate,
      setActiveBlock: setActiveBlock,
      setFileSaved: setFileSaved,
      markBlockDirty: markBlockDirty,
      markSourceDirty: markSourceDirty,
      markBlockSaved: markBlockSaved,
      getFileState: getFileState,
      getSavedModel: getSavedModel,
      discardFile: discardFile,
      hasDirty: hasDirty,
      getState: function () {
        return clone(state);
      },
    };
  }

  return {
    createDirtyState: createDirtyState,
    preserveDirtyBlocks: preserveDirtyBlocks,
  };
});
