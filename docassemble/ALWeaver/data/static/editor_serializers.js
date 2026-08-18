/* YAML serializers used by the graphical editor. */
(function (root, factory) {
  'use strict';
  var serializers = factory();
  if (typeof module === 'object' && module.exports) module.exports = serializers;
  root.ALWeaverSerializers = serializers;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function escapeYamlStr(str) {
    if (str === undefined || str === null) return str;
    str = String(str);
    if (str.indexOf('\n') !== -1) {
      return '|\n  ' + str.replace(/\n/g, '\n  ');
    }
    if (/[:\#\{\}\[\],&*!>|'"%@`]/.test(str) || str.trim() !== str || str === '') {
      return '"' + str.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
    }
    return str;
  }

  function serializeQuestionToYaml(block, options) {
    var document = options.document;
    var appendYamlValue = options.appendYamlValue;
    var appendYamlBlockValue = options.appendYamlBlockValue;
    var fieldTypeSupportsStandaloneContent = options.fieldTypeSupportsStandaloneContent;
    var fieldMethodTypes = options.fieldMethodTypes || [];
    var choiceTypes = options.choiceTypes;
    var state = options.state;
    var serializeQuestionFieldFromData = options.serializeQuestionFieldFromData;
    var appendQuestionAdvancedYaml = options.appendQuestionAdvancedYaml;
    var yaml = '';

    var idInput = document.getElementById('adv-id');
    var blockId = (idInput && idInput.value) ? idInput.value : (block && block.id ? block.id : 'question_block');
    yaml = appendYamlValue(yaml, 'id', blockId);

    var qTitle = document.getElementById('q-title');
    var questionText = qTitle && qTitle.value ? qTitle.value : (block && block.data && block.data.question ? String(block.data.question) : '');
    if (questionText) yaml = appendYamlValue(yaml, 'question', questionText);

    var qSub = document.getElementById('q-subquestion');
    var subquestionText = qSub && qSub.value ? qSub.value : (block && block.data && block.data.subquestion ? String(block.data.subquestion) : '');
    if (subquestionText) yaml = appendYamlValue(yaml, 'subquestion', subquestionText);

    var rows = document.querySelectorAll('.editor-field-row');
    if (rows.length > 0) {
      yaml += 'fields:\n';
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var rowIdx = row.getAttribute('data-field-idx') !== null ? row.getAttribute('data-field-idx') : String(i);
        var type = row.querySelector('[data-field-prop="type"]').value;
        var isStandaloneType = fieldTypeSupportsStandaloneContent(type);
        var isFieldMethodType = fieldMethodTypes.indexOf(type) !== -1;
        var labelEl = row.querySelector('[data-field-prop="label"]');
        var label = labelEl ? String(labelEl.value || '') : '';
        if (!isStandaloneType && !label) label = 'Label';
        var variable = row.querySelector('[data-field-prop="variable"]').value;
        var choicesEl = document.getElementById('field-choices-' + rowIdx);
        var codeEl = document.getElementById('field-code-' + rowIdx);
        var showIfEl = document.getElementById('field-showif-' + rowIdx);
        var showIfKeyEl = document.querySelector('.editor-field-showif-key[data-field-idx="' + rowIdx + '"]');
        var requiredSwitch = document.querySelector('.editor-field-required-switch[data-field-idx="' + rowIdx + '"]');
        var fieldModsPanel = document.querySelector('.editor-field-mods-panel[data-field-idx="' + rowIdx + '"]');
        var fmodInputs = fieldModsPanel ? fieldModsPanel.querySelectorAll('[data-fmod]') : [];
        var sfmods = {};
        fmodInputs.forEach(function (el) {
          var key = el.getAttribute('data-fmod');
          var value = el.value.trim();
          if (value) sfmods[key] = value;
        });
        var hasCodeExpr = codeEl && codeEl.value.trim();
        var hasChoices = choicesEl && choicesEl.value.trim() && choiceTypes.indexOf(type) !== -1;
        var showIfVal = showIfEl ? showIfEl.value.trim() : '';
        var showIfKey = showIfKeyEl ? showIfKeyEl.value : 'show if';
        var isRequired = requiredSwitch ? requiredSwitch.checked : true;
        var hasMods = hasCodeExpr || showIfVal || !isRequired || Object.keys(sfmods).length > 0;
        var isMultiLineLabel = label.indexOf('\n') !== -1;
        if (isFieldMethodType) {
          var methodArgsEl = row.querySelector('[data-field-method-args]');
          var methodArgs = methodArgsEl ? String(methodArgsEl.value || '').trim() : '';
          if (variable) {
            yaml += '  - code: |\n';
            yaml += '      ' + variable + '.' + type + '(' + methodArgs + ')\n';
          }
          continue;
        }
        if (isStandaloneType) {
          yaml = appendYamlBlockValue(yaml, '  - ' + type, label);
          if (hasChoices) {
            yaml += '    choices:\n';
            choicesEl.value.split('\n').forEach(function (choice) {
              if (choice.trim()) yaml += '      - ' + escapeYamlStr(choice.trim()) + '\n';
            });
          }
          if (hasCodeExpr) {
            var standaloneCode = codeEl.value.trim();
            yaml += '    code: |\n';
            standaloneCode.split('\n').forEach(function (line) { yaml += '      ' + line + '\n'; });
          }
          if (!isRequired) yaml += '    required: False\n';
          if (showIfVal) yaml += '    ' + showIfKey + ': ' + escapeYamlStr(showIfVal) + '\n';
          Object.keys(sfmods).forEach(function (key) { yaml += '    ' + key + ': ' + escapeYamlStr(sfmods[key]) + '\n'; });
          continue;
        }
        if (isMultiLineLabel || hasMods) {
          yaml += '  - label: ' + escapeYamlStr(label) + '\n';
          if (variable) yaml += '    field: ' + escapeYamlStr(variable) + '\n';
        } else {
          yaml += '  - ' + escapeYamlStr(label) + ':';
          yaml += variable ? ' ' + escapeYamlStr(variable) + '\n' : '\n';
        }
        if (type && type !== 'text') yaml += '    datatype: ' + type + '\n';
        if (hasChoices) {
          yaml += '    choices:\n';
          choicesEl.value.split('\n').forEach(function (choice) {
            if (choice.trim()) yaml += '      - ' + escapeYamlStr(choice.trim()) + '\n';
          });
        }
        if (hasCodeExpr) {
          var codeText = codeEl.value.trim();
          if (codeText.indexOf('\n') !== -1) {
            yaml += '    code: |\n';
            codeText.split('\n').forEach(function (line) { yaml += '      ' + line + '\n'; });
          } else {
            yaml += '    code: ' + codeText + '\n';
          }
        }
        if (!isRequired) yaml += '    required: False\n';
        if (showIfVal) yaml += '    ' + showIfKey + ': ' + escapeYamlStr(showIfVal) + '\n';
        Object.keys(sfmods).forEach(function (key) { yaml += '    ' + key + ': ' + escapeYamlStr(sfmods[key]) + '\n'; });
      }
    } else if (state.questionBlockTab !== 'screen' && block && block.data && Array.isArray(block.data.fields) && block.data.fields.length > 0) {
      yaml += 'fields:\n';
      block.data.fields.forEach(function (field) {
        yaml += serializeQuestionFieldFromData(field);
      });
    }

    return appendQuestionAdvancedYaml(yaml, block);
  }

  // -------------------------------------------------------------------------
  // ALPeopleList quantity
  //
  // "Setting the number of people in a group" in the AssemblyLine authoring
  // docs is one `.using()` call with a handful of recognised shapes.  Reading
  // those shapes back out of source is the part that has to be exact: the
  // graphical control may only take over a parameter list it fully
  // understands, because anything it takes over it also rewrites.  Anything
  // else -- an expression instead of a literal, a repeated key, a positional
  // argument, unbalanced brackets -- is reported as not editable, and the
  // caller leaves the author's own text alone.
  // -------------------------------------------------------------------------

  var PEOPLE_LIST_QUANTITY_KEYS = ['there_are_any', 'ask_number', 'target_number'];

  var PEOPLE_LIST_QUANTITY_MODES = [
    {
      value: 'ask',
      label: 'Ask whether there are any',
      hint: 'The default. Asks if there are any, then collects them one at a time.',
    },
    {
      value: 'at_least_one',
      label: 'At least one',
      hint: 'Skips the "are there any?" question and starts with one.',
    },
    {
      value: 'ask_count',
      label: 'Ask how many',
      hint: 'Asks for a number first, then collects that many.',
    },
    {
      value: 'exactly',
      label: 'Exactly this many',
      hint: 'Never asks. Use this when the form has room for a fixed number.',
    },
  ];

  /* Split a `.using()` argument list into its arguments.

     Top-level commas separate arguments, and so do newlines: the editor
     normalizes any call with more than one argument onto separate lines
     before the browser ever sees it (`_format_object_using_args`), so
     `ask_number=True, target_number=1` arrives here as two lines with no
     comma between them. Splitting on commas alone made every multi-argument
     call look like one malformed argument.

     Returns null when brackets or quotes are unbalanced, because a partial
     split would silently drop an argument. */
  function splitUsingArgs(argText) {
    var text = String(argText === undefined || argText === null ? '' : argText).trim();
    if (!text) return [];
    var parts = [];
    var current = '';
    var depth = 0;
    var quote = null;
    for (var i = 0; i < text.length; i++) {
      var ch = text.charAt(i);
      if (quote) {
        current += ch;
        if (ch === '\\' && i + 1 < text.length) {
          current += text.charAt(i + 1);
          i++;
        } else if (ch === quote) {
          quote = null;
        }
        continue;
      }
      if (ch === '"' || ch === "'") {
        quote = ch;
        current += ch;
        continue;
      }
      if (ch === '(' || ch === '[' || ch === '{') depth++;
      if (ch === ')' || ch === ']' || ch === '}') {
        depth--;
        if (depth < 0) return null;
      }
      if ((ch === ',' || ch === '\n') && depth === 0) {
        parts.push(current);
        current = '';
        continue;
      }
      current += ch;
    }
    if (depth !== 0 || quote) return null;
    parts.push(current);
    return parts
      .map(function (part) { return part.trim(); })
      .filter(function (part) { return part !== ''; });
  }

  /* Pull the quantity parameters out of a `.using()` argument list.

     Returns `{ editable, mode, number, otherArgs }`.  When `editable` is
     false the argument list holds something this control cannot own, and the
     caller must fall back to editing the text directly. */
  function readPeopleListQuantity(argText) {
    var fallback = {
      editable: false,
      mode: 'ask',
      number: 1,
      otherArgs: String(argText === undefined || argText === null ? '' : argText).trim(),
    };

    var parts = splitUsingArgs(argText);
    if (parts === null) return fallback;

    var quantity = {};
    var others = [];
    var seen = {};
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i];
      var eq = _topLevelAssignmentIndex(part);
      if (eq === -1) {
        // A positional argument or `**kwargs`. Either could carry a quantity
        // parameter this control would then contradict, so say nothing.
        return fallback;
      }
      var key = part.slice(0, eq).trim();
      var value = part.slice(eq + 1).trim();
      if (PEOPLE_LIST_QUANTITY_KEYS.indexOf(key) === -1) {
        others.push(part);
        continue;
      }
      if (seen[key]) return fallback;
      seen[key] = true;
      quantity[key] = value;
    }

    var hasAny = Object.prototype.hasOwnProperty.call(quantity, 'there_are_any');
    var hasAsk = Object.prototype.hasOwnProperty.call(quantity, 'ask_number');
    var hasTarget = Object.prototype.hasOwnProperty.call(quantity, 'target_number');
    var otherArgs = others.join(', ');

    if (!hasAny && !hasAsk && !hasTarget) {
      return { editable: true, mode: 'ask', number: 1, otherArgs: otherArgs };
    }
    if (hasAny && !hasAsk && !hasTarget && quantity.there_are_any === 'True') {
      return { editable: true, mode: 'at_least_one', number: 1, otherArgs: otherArgs };
    }
    if (hasAsk && !hasAny && quantity.ask_number === 'True') {
      if (!hasTarget) {
        return { editable: true, mode: 'ask_count', number: 1, otherArgs: otherArgs };
      }
      if (/^\d+$/.test(quantity.target_number)) {
        return {
          editable: true,
          mode: 'exactly',
          number: parseInt(quantity.target_number, 10),
          otherArgs: otherArgs,
        };
      }
    }
    return fallback;
  }

  /* Build the `.using()` argument list for a chosen quantity, keeping any
     parameters the control does not own in the order the author wrote them. */
  function composePeopleListUsingArgs(mode, number, otherArgs) {
    var quantityArgs = [];
    if (mode === 'at_least_one') {
      quantityArgs.push('there_are_any=True');
    } else if (mode === 'ask_count') {
      quantityArgs.push('ask_number=True');
    } else if (mode === 'exactly') {
      var count = parseInt(number, 10);
      if (isNaN(count) || count < 0) count = 1;
      quantityArgs.push('ask_number=True');
      quantityArgs.push('target_number=' + count);
    }
    var rest = splitUsingArgs(otherArgs);
    if (rest === null) {
      var raw = String(otherArgs === undefined || otherArgs === null ? '' : otherArgs).trim();
      rest = raw ? [raw] : [];
    }
    return quantityArgs.concat(rest).join(', ');
  }

  function _topLevelAssignmentIndex(part) {
    var depth = 0;
    var quote = null;
    for (var i = 0; i < part.length; i++) {
      var ch = part.charAt(i);
      if (quote) {
        if (ch === '\\') { i++; continue; }
        if (ch === quote) quote = null;
        continue;
      }
      if (ch === '"' || ch === "'") { quote = ch; continue; }
      if (ch === '(' || ch === '[' || ch === '{') depth++;
      if (ch === ')' || ch === ']' || ch === '}') depth--;
      if (ch !== '=' || depth !== 0) continue;
      // Skip ==, <=, >=, != so a comparison is never read as a keyword.
      if (part.charAt(i + 1) === '=') { i++; continue; }
      if ('=!<>'.indexOf(part.charAt(i - 1)) !== -1) continue;
      return i;
    }
    return -1;
  }

  // if / elif / else chains in the interview order
  //
  // A chain is stored the way Python means it: each `elif` is an `else` branch
  // holding exactly one condition.  One shape on the wire keeps the server's
  // parser and serializer able to round-trip a chain of any length.  Authors
  // think in flat chains though, so the order builder reads that nesting back
  // through these helpers and edits it through the two mutations below.
  // -------------------------------------------------------------------------

  /* The condition an `else` branch consists entirely of, or null. */
  function getSoleElseCondition(step) {
    if (!step || !step.has_else) return null;
    var elseChildren = Array.isArray(step.else_children) ? step.else_children : [];
    if (elseChildren.length !== 1) return null;
    var only = elseChildren[0];
    return only && only.kind === 'condition' ? only : null;
  }

  /* [if, elif, elif, ...] starting at `step`. */
  function getConditionChain(step) {
    var chain = [];
    var current = step;
    while (current && current.kind === 'condition' && chain.indexOf(current) === -1) {
      chain.push(current);
      current = getSoleElseCondition(current);
    }
    return chain;
  }

  /* The last link, whose `else` branch is the chain's real else body. */
  function getChainTail(step) {
    var chain = getConditionChain(step);
    return chain.length ? chain[chain.length - 1] : step;
  }

  function chainHasFinalElse(step) {
    var tail = getChainTail(step);
    return Boolean(tail && tail.has_else);
  }

  /* True when `step` is an `elif` -- the whole content of `parentStep`'s else. */
  function isChainLink(step, parentStep) {
    return Boolean(parentStep) && getSoleElseCondition(parentStep) === step;
  }

  /* Add `newLink` as the last `elif` of the chain `step` belongs to.

     A chain already ending in `else` keeps it: the new branch goes in front,
     which is where an author adding one means it. Returns the link. */
  function appendChainElif(step, newLink) {
    var tail = getChainTail(step);
    if (tail.has_else) {
      newLink.has_else = true;
      newLink.else_children = Array.isArray(tail.else_children) ? tail.else_children : [];
    }
    tail.has_else = true;
    tail.else_children = [newLink];
    return newLink;
  }

  /* Drop one `elif` and close the chain up behind it, so whatever it was
     holding for the rest of the chain is not dropped with it. */
  function removeChainLink(parentStep, link) {
    if (!isChainLink(link, parentStep)) return false;
    parentStep.has_else = Boolean(link.has_else);
    parentStep.else_children = Array.isArray(link.else_children) ? link.else_children : [];
    return true;
  }

  return {
    escapeYamlStr: escapeYamlStr,
    serializeQuestionToYaml: serializeQuestionToYaml,
    splitUsingArgs: splitUsingArgs,
    readPeopleListQuantity: readPeopleListQuantity,
    composePeopleListUsingArgs: composePeopleListUsingArgs,
    PEOPLE_LIST_QUANTITY_MODES: PEOPLE_LIST_QUANTITY_MODES,
    getSoleElseCondition: getSoleElseCondition,
    getConditionChain: getConditionChain,
    getChainTail: getChainTail,
    chainHasFinalElse: chainHasFinalElse,
    isChainLink: isChainLink,
    appendChainElif: appendChainElif,
    removeChainLink: removeChainLink,
  };
});
