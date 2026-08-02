import re

with open(
    "/home/quinten/docassemble-ALWeaver/docassemble/ALWeaver/data/static/editor.js"
) as f:
    text = f.read()

replacement = """
    if (target.id === 'save-block-btn') {
      var block = getSelectedBlock();
      if (!block) return;
      var yamlVal = '';

      if (state.questionEditMode === 'preview' && block.type === 'question') {
        yamlVal = serializeQuestionToYaml();
      } else {
        yamlVal = getMonacoValue('block-yaml-monaco');
        if (!yamlVal && _monacoEditors['code-monaco']) {
          yamlVal = block.yaml;
        }
        if (!yamlVal) yamlVal = block.yaml;
      }
"""

text = re.sub(
    r"    if \(target\.id === 'save-block-btn'\) \{\n      var block = getSelectedBlock\(\);\n      if \(!block\) return;\n      // Get YAML from Monaco if available, else from current block\n      var yamlVal = getMonacoValue\('block-yaml-monaco'\);\n      if \(!yamlVal && _monacoEditors\['code-monaco'\]\) \{\n        // Code blocks in structured mode: we'd need to reconstruct YAML\n        // For now, saving from code editor isn't full — user should use YAML mode\n        yamlVal = block\.yaml;\n      \}\n      if \(!yamlVal\) yamlVal = block\.yaml;",
    replacement,
    text,
)

# add serialize logic
func = """
  function escapeYamlStr(str) {
    if (!str) return str;
    if (str.indexOf('\\n') !== -1) {
      return '|\\n  ' + str.replace(/\\n/g, '\\n  ');
    }
    if (str.match(/[:\\#\\{\\}\\[\\]\\,\\&\\*\\!\\>\\|\\'\\"\\%\\@\\`]/) || str.trim() !== str || str === '') {
      return '"' + str.replace(/"/g, '\\\\"') + '"';
    }
    return str;
  }

  function serializeQuestionToYaml() {
    var yaml = '---\\n';
    
    var idInput = document.getElementById('adv-id');
    if (idInput && idInput.value) yaml += 'id: ' + escapeYamlStr(idInput.value) + '\\n';
    
    var qTitle = document.getElementById('q-title');
    if (qTitle && qTitle.value) yaml += 'question: ' + escapeYamlStr(qTitle.value) + '\\n';
    
    var qSub = document.getElementById('q-subquestion');
    if (qSub && qSub.value) yaml += 'subquestion: ' + escapeYamlStr(qSub.value) + '\\n';

    var contField = document.getElementById('q-continue-field');
    if (contField && contField.value) yaml += 'continue button field: ' + escapeYamlStr(contField.value) + '\\n';

    var rows = Array.from(document.querySelectorAll('.editor-field-row'));
    if (rows.length > 0) {
      yaml += 'fields:\\n';
      rows.forEach(function(row) {
        var label = row.querySelector('.editor-field-label-input').value || 'Label';
        var type = row.querySelector('.editor-field-type-select').value;
        var variable = row.querySelector('.editor-field-var-input').value;
        var choicesEl = row.querySelector('.editor-field-choices');
        
        if (!variable && type === 'text') {
           yaml += '  - ' + escapeYamlStr(label) + '\\n';
           return;
        }
        
        yaml += '  - ' + escapeYamlStr(label) + ': ' + escapeYamlStr(variable) + '\\n';
        if (type !== 'text') yaml += '    datatype: ' + type + '\\n';
        
        if (choicesEl && choicesEl.value && ['radio', 'checkboxes', 'combobox', 'multiselect', 'dropdown', 'buttons'].indexOf(type) !== -1) {
            yaml += '    choices:\\n';
            choicesEl.value.split('\\n').forEach(function(c) {
                if(c.trim()) yaml += '      - ' + escapeYamlStr(c.trim()) + '\\n';
            });
        }
      });
    }
    return yaml;
  }

  // -------------------------------------------------------------------------
"""

text = text.replace(
    "  // -------------------------------------------------------------------------",
    func,
    1,
)

with open(
    "/home/quinten/docassemble-ALWeaver/docassemble/ALWeaver/data/static/editor.js", "w"
) as f:
    f.write(text)
