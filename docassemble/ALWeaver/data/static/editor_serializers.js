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

  return {
    escapeYamlStr: escapeYamlStr,
    serializeQuestionToYaml: serializeQuestionToYaml,
  };
});
