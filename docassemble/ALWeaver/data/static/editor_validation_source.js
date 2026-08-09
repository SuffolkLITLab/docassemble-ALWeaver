/* Compose a working-source snapshot of the file from narrow editor buffers.
 *
 * Validation, the editing assistant and any future preview operation all need
 * the same thing: the source the developer is currently looking at, including
 * unsaved edits. When a dirty subsystem cannot be mapped onto the source file
 * safely, these helpers throw rather than quietly fall back to the saved file.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverValidationSource = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function lineStartOffset(source, lineNumber) {
    if (lineNumber <= 1) return 0;
    var currentLine = 1;
    for (var index = 0; index < source.length; index++) {
      if (source.charAt(index) !== '\n') continue;
      currentLine += 1;
      if (currentLine === lineNumber) return index + 1;
    }
    return source.length;
  }

  function blockReplacement(source, block, text) {
    var startLine = Number(block && block.line_start);
    var endLine = Number(block && block.line_end);
    if (!Number.isFinite(startLine) || !Number.isFinite(endLine) || startLine < 1 || endLine < startLine) {
      throw new Error('Cannot map an unsaved block to the source file safely.');
    }
    var start = lineStartOffset(source, startLine);
    var end = lineStartOffset(source, endLine + 1);
    var original = source.slice(start, end);
    var replacement = String(text === undefined || text === null ? '' : text);
    var newline = original.indexOf('\r\n') !== -1 ||
      (original.indexOf('\n') === -1 && source.indexOf('\r\n') !== -1)
      ? '\r\n'
      : '\n';
    replacement = replacement.replace(/\r\n|\r|\n/g, newline);
    if (/(?:\r\n|\r|\n)$/.test(original) && !/(?:\r\n|\r|\n)$/.test(replacement)) {
      replacement += newline;
    }
    return { start: start, end: end, text: replacement };
  }

  function splitDocumentBodies(source) {
    var bodies = [];
    var bodyStart = 0;
    var separator = /^---[ \t]*(?:\r?\n|$)/gm;
    var match;
    while ((match = separator.exec(source)) !== null) {
      bodies.push(source.slice(bodyStart, match.index));
      bodyStart = match.index + match[0].length;
    }
    bodies.push(source.slice(bodyStart));
    return bodies.filter(function (body) { return body.trim() !== ''; });
  }

  function applyOperations(source, operations) {
    var result = source;
    operations.slice().sort(function (left, right) {
      return right.start - left.start;
    }).forEach(function (operation) {
      result = result.slice(0, operation.start) + operation.text + result.slice(operation.end);
    });
    return result;
  }

  function buildValidationSource(options) {
    options = options || {};
    if (typeof options.fullSource === 'string') return options.fullSource;
    var source = String(options.rawYaml === undefined || options.rawYaml === null ? '' : options.rawYaml);
    var blocks = Array.isArray(options.blocks) ? options.blocks : [];
    var replacements = options.blockReplacements || {};
    var operations = [];

    Object.keys(replacements).forEach(function (blockId) {
      var block = blocks.find(function (candidate) {
        return String(candidate && candidate.id) === String(blockId);
      });
      if (!block) throw new Error('Cannot find unsaved block ' + blockId + ' in the source file.');
      operations.push(blockReplacement(source, block, replacements[blockId]));
    });

    if (typeof options.metadataSource === 'string') {
      var metadataBlocks = blocks.filter(function (block) {
        return block && ['metadata', 'includes', 'default_screen_parts'].indexOf(block.type) !== -1;
      });
      var editedDocuments = splitDocumentBodies(options.metadataSource);
      if (metadataBlocks.length !== editedDocuments.length) {
        throw new Error('Metadata documents no longer match the source file. Validate in full source mode.');
      }
      metadataBlocks.forEach(function (block, index) {
        operations.push(blockReplacement(source, block, editedDocuments[index]));
      });
    }

    return applyOperations(source, operations);
  }

  function hasUnsavedEdits(options) {
    if (typeof options.fullSource === 'string') return true;
    if (typeof options.metadataSource === 'string') return true;
    if (options.blockReplacements && Object.keys(options.blockReplacements).length) return true;
    return Boolean(options.hasUnsavedChanges);
  }

  /* Build the snapshot every server-side source operation should be given.
   *
   * `working_revision` is intentionally left to the server: the browser has no
   * synchronous SHA-256, and the server already hashes whatever it receives.
   */
  function buildWorkingSourceSnapshot(options) {
    options = options || {};
    if (options.orderDirty) {
      throw new Error(options.orderDirtyMessage ||
        'Unsaved order-builder changes cannot be represented safely. ' +
        'Save them or discard them before using the assistant.');
    }
    var rawYaml = buildValidationSource(options);
    var unsaved = hasUnsavedEdits(options);
    return {
      raw_yaml: rawYaml,
      base_revision: options.baseRevision || null,
      working_revision: options.workingRevision || null,
      has_unsaved_changes: unsaved,
      source_scope: unsaved ? 'working_source' : 'saved_source',
    };
  }

  return {
    buildValidationSource: buildValidationSource,
    buildWorkingSourceSnapshot: buildWorkingSourceSnapshot,
  };
});
