/* Guided Python expressions. Python source is the only persisted representation. */
(function (root) {
  'use strict';
  var functions = [
    'len',
    'str',
    'int',
    'float',
    'round',
    'min',
    'max',
    'sum',
    'abs',
    'defined',
    'value',
    'showifdef',
    'currency',
    'today',
    'as_datetime',
  ];
  var comparisons = ['==', '!=', '<', '<=', '>', '>=', 'in', 'not in'];
  var operators = ['and', 'or', 'not', '+', '-', '*', '/'];
  var labels = {
    '==': 'equals',
    '!=': 'does not equal',
    '<': 'is less than',
    '<=': 'is at most',
    '>': 'is greater than',
    '>=': 'is at least',
    in: 'is in',
    'not in': 'is not in',
  };
  var serial = 0;

  function python(node) {
    var args = (node.args || []).map(python);
    if (node.kind === 'text')
      return JSON.stringify(node.value)
        .replace(/\u2028/g, '\\u2028')
        .replace(/\u2029/g, '\\u2029');
    if (node.kind === 'none') return 'None';
    if (['variable', 'number', 'boolean'].indexOf(node.kind) !== -1)
      return String(node.value);
    if (node.kind === 'function')
      return (
        node.name +
        '(' +
        args
          .map(function (arg, index) {
            var keyword = (node.keywords || [])[index];
            return (keyword ? keyword + '=' : '') + arg;
          })
          .join(', ') +
        ')'
      );
    if (node.kind === 'list') return '[' + args.join(', ') + ']';
    if (node.kind === 'tuple')
      return '(' + args.join(', ') + (args.length === 1 ? ',' : '') + ')';
    if (node.kind === 'comparison')
      return (
        '(' +
        args
          .map(function (arg, i) {
            return (i ? node.ops[i - 1] + ' ' : '') + arg;
          })
          .join(' ') +
        ')'
      );
    if (node.kind === 'operator')
      return (
        '(' +
        (args.length === 1
          ? node.op + ' ' + args[0]
          : args.join(' ' + node.op + ' ')) +
        ')'
      );
    throw new Error('Unknown expression node');
  }

  function fresh(kind) {
    if (kind === 'comparison')
      return {
        kind: kind,
        ops: ['=='],
        args: [fresh('variable'), fresh('number')],
      };
    if (kind === 'operator')
      return {
        kind: kind,
        op: 'and',
        args: [fresh('variable'), fresh('variable')],
      };
    if (kind === 'function')
      return { kind: kind, name: 'len', args: [fresh('variable')] };
    if (kind === 'list' || kind === 'tuple') return { kind: kind, args: [] };
    return {
      kind: kind,
      value: {
        variable: 'variable_name',
        text: '',
        number: '0',
        boolean: 'True',
        none: 'None',
      }[kind],
    };
  }

  function changeType(node, kind) {
    if (kind === 'function' && node.kind === 'function') return node;
    // Conditions and Calculation are both operator nodes, so switching between
    // them only changes the operator: keep the operands already entered.
    if (kind === 'calculation' || kind === 'operator') {
      if (node.kind === 'operator') {
        var arithmetic = ['+', '-', '*', '/'].indexOf(node.op) !== -1;
        if (kind === 'calculation') node.op = arithmetic ? node.op : '+';
        else if (arithmetic) node.op = 'and';
        if (node.args.length === 1 && node.op !== 'not')
          node.args.push(fresh('variable'));
        return node;
      }
    }
    var next = fresh(kind === 'calculation' ? 'operator' : kind);
    if (kind === 'calculation') next.op = '+';
    if (kind === 'function') next.args = [node];
    return next;
  }

  // Keep comments in place for leaf edits. A structural replacement carries
  // comments from the replaced subtree inside its new parenthesized value.
  function codeChanges(row, comments) {
    var edits = [];
    function visit(before, after) {
      if (python(before) === python(after)) return;
      var sameShape =
        before.kind === after.kind &&
        before.op === after.op &&
        before.name === after.name &&
        JSON.stringify(before.keywords) === JSON.stringify(after.keywords) &&
        JSON.stringify(before.ops) === JSON.stringify(after.ops) &&
        before.args &&
        after.args &&
        before.args.length === after.args.length;
      if (sameShape) {
        before.args.forEach(function (child, i) {
          visit(child, after.args[i]);
        });
        return;
      }
      var kept = comments.filter(function (comment) {
        return comment.start >= before.start && comment.start < before.end;
      });
      var replacement = python(after);
      if (kept.length)
        replacement =
          '(\n' +
          kept
            .map(function (comment) {
              return '  ' + comment.text + '\n';
            })
            .join('') +
          '  ' +
          replacement +
          '\n)';
      edits.push({ start: before.start, end: before.end, text: replacement });
    }
    visit(row.originalTree, row.tree);
    if (row.originalTarget !== undefined && row.target !== row.originalTarget)
      edits.push({
        start: row.target_start,
        end: row.target_end,
        text: row.target,
      });
    return edits;
  }

  // Always patch against the original ranges, including after repeated edits.
  function codeSource(parsed) {
    var chars = Array.from(parsed.original);
    var edits = [];
    var added = [];
    parsed.rows.forEach(function (row) {
      if (row.deleted) {
        if (row.added) return;
        var end = row.statement_end;
        var tail = chars.slice(end).join('');
        var separator = /^[ \t]*;[ \t]*/.exec(tail);
        if (separator) end += Array.from(separator[0]).length;
        var comments = (parsed.comments || []).filter(function (comment) {
          return comment.start >= row.statement_start && comment.start < end;
        });
        edits.push({
          start: row.statement_start,
          end: end,
          text: comments
            .map(function (comment) {
              return comment.text + '\n';
            })
            .join(''),
        });
      } else if (row.added) added.push(row.target + ' = ' + python(row.tree));
      else if (row.edited)
        edits = edits.concat(codeChanges(row, parsed.comments || []));
    });
    edits
      .sort(function (a, b) {
        return b.start - a.start;
      })
      .forEach(function (edit) {
        chars.splice(
          edit.start,
          edit.end - edit.start,
          ...Array.from(edit.text),
        );
      });
    var result = chars.join('');
    if (added.length) {
      var newline = parsed.original.indexOf('\r\n') !== -1 ? '\r\n' : '\n';
      if (result && !/[\r\n]$/.test(result)) result += newline;
      result += added.join(newline) + newline;
    }
    return result;
  }

  function el(tag, cls, text) {
    var result = document.createElement(tag);
    if (cls) result.className = cls;
    if (text !== undefined) result.textContent = text;
    return result;
  }
  function button(text, action) {
    var result = el('button', 'btn btn-sm btn-outline-secondary', text);
    result.type = 'button';
    result.addEventListener('click', action);
    return result;
  }
  function select(label, values, value, action, names) {
    var result = el('select', 'form-select form-select-sm');
    result.setAttribute('aria-label', label);
    values.forEach(function (v) {
      var option = el('option', '', (names && names[v]) || labels[v] || v);
      option.value = v;
      option.selected = v === value;
      result.appendChild(option);
    });
    result.addEventListener('change', function () {
      action(result.value);
    });
    return result;
  }

  // A local combobox works inside native dialogs, unlike the editor's global
  // popup. Read candidates on every interaction, not when the view is mounted.
  function picker(input, candidates, commit) {
    var wrapper = el('div', 'expression-picker');
    var menu = el('div', 'expression-suggestions');
    menu.id = 'expression-suggestions-' + ++serial;
    menu.setAttribute('role', 'listbox');
    menu.hidden = true;
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-controls', menu.id);
    input.setAttribute('aria-expanded', 'false');
    input.autocomplete = 'off';
    var active = -1,
      matches = [];
    function close() {
      menu.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    }
    function choose(index) {
      input.value = matches[index].name;
      close();
      commit(input.value);
    }
    function refresh() {
      var query = input.value.toLowerCase().trim();
      matches = candidates()
        .map(function (item) {
          return typeof item === 'string' ? { name: item } : item;
        })
        .filter(function (item) {
          return item.name.toLowerCase().indexOf(query) !== -1;
        })
        .slice(0, 40);
      active = -1;
      menu.replaceChildren();
      matches.forEach(function (item, index) {
        var option = el('div', 'expression-suggestion', item.name);
        option.id = menu.id + '-' + index;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        if (item.signature) option.appendChild(el('small', '', item.signature));
        option.addEventListener('mousedown', function (event) {
          event.preventDefault();
        });
        option.addEventListener('click', function () {
          choose(index);
        });
        menu.appendChild(option);
      });
      if (!matches.length)
        menu.appendChild(
          el(
            'div',
            'expression-no-matches',
            'No matching suggestions. You can type a name.',
          ),
        );
      menu.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      input.removeAttribute('aria-activedescendant');
    }
    input.addEventListener('focus', refresh);
    input.addEventListener('input', refresh);
    input.addEventListener('expression-catalog-refresh', refresh);
    input.addEventListener('blur', close);
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !menu.hidden) {
        event.preventDefault();
        event.stopPropagation();
        close();
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        event.stopPropagation();
        if (menu.hidden) refresh();
        if (!matches.length) return;
        var step = event.key === 'ArrowDown' ? 1 : -1;
        if (active < 0) active = step > 0 ? 0 : matches.length - 1;
        else active = (active + step + matches.length) % matches.length;
        Array.from(menu.children).forEach(function (option, index) {
          option.setAttribute('aria-selected', String(index === active));
        });
        input.setAttribute('aria-activedescendant', menu.children[active].id);
        menu.children[active].scrollIntoView({ block: 'nearest' });
      } else if (event.key === 'Enter' && !menu.hidden && active >= 0) {
        event.preventDefault();
        event.stopPropagation();
        choose(active);
      }
    });
    wrapper.append(input, menu);
    return wrapper;
  }

  function draw(node, replace, changed, catalog, depth) {
    var isGroup =
      node.kind === 'operator' && ['and', 'or', 'not'].indexOf(node.op) !== -1;
    var box = el(
      'div',
      'expression-node expression-node--' +
        node.kind +
        (isGroup ? ' expression-group' : '') +
        (!node.args ? ' expression-leaf' : ''),
    );
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', depth ? 'Operand' : 'Expression');
    var header = el('div', 'expression-node-header');
    box.appendChild(header);
    header.appendChild(
      select(
        'Expression type',
        [
          'variable',
          'text',
          'number',
          'boolean',
          'none',
          'comparison',
          'operator',
          'calculation',
          'function',
          'list',
          'tuple',
        ],
        node.kind === 'operator' && !isGroup ? 'calculation' : node.kind,
        function (kind) {
          replace(changeType(node, kind));
        },
        {
          variable: 'Variable',
          text: 'Text',
          number: 'Number',
          boolean: 'Boolean',
          none: 'None',
          comparison: 'Compare',
          operator: 'Conditions',
          calculation: 'Calculation',
          function: 'Function',
          list: 'List',
          tuple: 'Tuple',
        },
      ),
    );
    if (['variable', 'text', 'number'].indexOf(node.kind) !== -1) {
      var input = el(
        node.kind === 'text' ? 'textarea' : 'input',
        'form-control form-control-sm',
      );
      if (node.kind === 'text')
        input.rows = node.value.indexOf('\n') === -1 ? 1 : 3;
      else input.type = 'text';
      input.value = node.value;
      input.placeholder = {
        variable: 'Find a variable…',
        text: 'Enter text',
        number: '0',
      }[node.kind];
      input.setAttribute(
        'aria-label',
        {
          variable: 'Variable or attribute',
          text: 'Text value',
          number: 'Number value',
        }[node.kind],
      );
      input.addEventListener('input', function () {
        node.value = input.value;
        changed();
      });
      box.appendChild(
        node.kind === 'variable'
          ? picker(input, catalog.variables, function (value) {
              node.value = value;
              changed();
            })
          : input,
      );
    } else if (node.kind === 'boolean') {
      box.appendChild(
        select('Boolean value', ['True', 'False'], node.value, function (v) {
          node.value = v;
          changed();
        }),
      );
    } else if (node.kind === 'none') {
      box.appendChild(el('div', 'expression-empty-value', 'None'));
    }
    function operatorControl() {
      return select(
        'Operator',
        operators,
        node.op,
        function (v) {
          var previous = node.op;
          node.op = v;
          // Not takes a single operand: negate what is there rather than
          // dropping every operand after the first.
          if (v === 'not') {
            if (node.args.length > 1)
              node.args = [{ kind: 'operator', op: previous, args: node.args }];
          } else if (node.args.length === 1) node.args.push(fresh('variable'));
          replace(node);
        },
        { and: 'All of (AND)', or: 'Any of (OR)', not: 'Not' },
      );
    }
    if (node.kind === 'operator' && (isGroup || node.args.length === 1)) {
      header.appendChild(operatorControl());
    }
    if (node.kind === 'function') {
      var callable = el(
        'input',
        'form-control form-control-sm expression-function-name',
      );
      callable.value = node.name;
      callable.setAttribute('aria-label', 'Function');
      function setFunction(value) {
        if (!value.trim() || value === node.name) return;
        node.name = value.trim();
        var signature = catalog.functions().find(function (entry) {
          return entry.name === node.name;
        });
        if (
          signature &&
          signature.parameters &&
          !signature.parameters.length &&
          node.args.length === 1 &&
          node.args[0].kind === 'variable' &&
          node.args[0].value === 'variable_name'
        ) {
          node.args = [];
          node.keywords = [];
        }
        // Retain authored arguments when changing the callable. Never silently
        // discard values based on a signature (variadic functions are common).
        replace(node);
      }
      callable.addEventListener('change', function () {
        setFunction(callable.value);
      });
      header.appendChild(picker(callable, catalog.functions, setFunction));
      header.appendChild(el('span', 'expression-delimiter', '('));
      var metadata = catalog.functions().find(function (item) {
        return item.name === node.name;
      });
      var help = el('details', 'expression-function-help');
      help.appendChild(el('summary', '', 'Parameters & help'));
      help.appendChild(
        el(
          'code',
          'expression-signature',
          metadata ? metadata.signature : node.name + '(…)',
        ),
      );
      help.appendChild(
        el('p', '', metadata ? metadata.origin : 'Custom function'),
      );
      help.appendChild(
        el(
          'pre',
          'expression-docstring',
          metadata
            ? metadata.doc
            : 'No help is available for this function. You can still edit its arguments.',
        ),
      );
      box.appendChild(help);
      help.addEventListener('toggle', function () {
        if (!help.open) return;
        var current = catalog.functions().find(function (item) {
          return item.name === node.name;
        });
        if (!current) return;
        help.querySelector('code').textContent = current.signature;
        help.querySelector('p').textContent = current.origin;
        help.querySelector('pre').textContent = current.doc;
      });
    }
    var operands = el('div', 'expression-operands');
    if (node.args) box.appendChild(operands);
    (node.args || []).forEach(function (child, index) {
      if (node.kind === 'comparison' && index)
        operands.appendChild(
          select('Comparison', comparisons, node.ops[index - 1], function (v) {
            node.ops[index - 1] = v;
            changed();
          }),
        );
      else if (node.kind === 'operator' && index && !isGroup)
        operands.appendChild(operatorControl());
      var item = el('div', 'expression-operand');
      if (node.kind === 'function') {
        var parameter = (node.keywords || [])[index];
        var info = catalog.functions().find(function (entry) {
          return entry.name === node.name;
        });
        var positional = info
          ? (info.parameters || []).filter(function (entry) {
              return (
                entry.kind === 'POSITIONAL_ONLY' ||
                entry.kind === 'POSITIONAL_OR_KEYWORD' ||
                entry.kind === 'VAR_POSITIONAL'
              );
            })
          : [];
        var hint =
          positional[index] ||
          positional.find(function (entry) {
            return entry.kind === 'VAR_POSITIONAL';
          });
        var argumentLabel = 'Argument ' + (index + 1);
        if (hint) argumentLabel += ' · ' + hint.name;
        if (parameter) argumentLabel = parameter + ' =';
        item.appendChild(
          el('span', 'expression-argument-label', argumentLabel),
        );
        var keywordInput = el(
          'input',
          'form-control form-control-sm expression-keyword',
        );
        keywordInput.value = parameter || '';
        keywordInput.placeholder = 'Positional (or keyword name)';
        keywordInput.setAttribute(
          'aria-label',
          'Keyword for argument ' + (index + 1),
        );
        keywordInput.addEventListener('change', function () {
          node.keywords =
            node.keywords ||
            node.args.map(function () {
              return null;
            });
          node.keywords[index] = keywordInput.value.trim() || null;
          replace(node);
        });
        var argumentOptions = el('details', 'expression-argument-options');
        argumentOptions.append(
          el('summary', '', 'Name argument'),
          keywordInput,
        );
        item.appendChild(argumentOptions);
      }
      function weight(value) {
        return value.args && value.args.length
          ? value.args.reduce(function (sum, arg) {
              return sum + weight(arg);
            }, 0)
          : 1;
      }
      item.style.setProperty('--expression-weight', weight(child));
      var childBox = draw(
        child,
        function (replacement) {
          node.args[index] = replacement;
          replace(node);
        },
        changed,
        catalog,
        depth + 1,
      );
      item.appendChild(childBox);
      operands.appendChild(item);
      if (
        ['function', 'list', 'tuple'].indexOf(node.kind) !== -1 &&
        index < node.args.length - 1
      )
        operands.appendChild(el('span', 'expression-argument-comma', ','));
      if (
        ['function', 'list', 'tuple'].indexOf(node.kind) !== -1 ||
        (node.kind === 'operator' &&
          node.args.length > 2 &&
          ['and', 'or'].indexOf(node.op) !== -1)
      ) {
        var remove = button('×', function () {
          node.args.splice(index, 1);
          if (node.keywords) node.keywords.splice(index, 1);
          replace(node);
        });
        remove.className = 'expression-remove';
        remove.setAttribute('aria-label', 'Remove operand ' + (index + 1));
        remove.title = 'Remove this ' + (isGroup ? 'condition' : 'value');
        item.appendChild(remove);
      }
    });
    if (node.kind === 'function' && node.name === 'as_datetime')
      box.appendChild(
        el(
          'p',
          'small text-muted mt-2 mb-0',
          'Use a text date, such as 2026-09-18.',
        ),
      );
    if (
      ['function', 'list', 'tuple'].indexOf(node.kind) !== -1 ||
      (node.kind === 'operator' && ['and', 'or'].indexOf(node.op) !== -1)
    ) {
      var addLabel =
        node.kind === 'function' ? '+ Add argument' : '+ Add value';
      if (isGroup) addLabel = '+ Add condition';
      var add = button(addLabel, function () {
        node.args.push(fresh('variable'));
        if (node.keywords) node.keywords.push(null);
        replace(node);
      });
      add.className = 'btn btn-sm expression-add';
      add.setAttribute('aria-label', 'Add operand');
      box.appendChild(add);
    }
    if (node.kind === 'function') {
      box.appendChild(
        el('span', 'expression-delimiter expression-call-close', ')'),
      );
      if (
        node.args.some(function (arg) {
          return arg.kind === 'function';
        })
      )
        box.appendChild(
          el(
            'p',
            'expression-call-order',
            'Inner calls run first. Their results become arguments to ' +
              node.name +
              '.',
          ),
        );
    }
    return box;
  }

  function mount(host, options) {
    var alive = true,
      sequence = 0,
      guided = false,
      parsed = null;
    var source = options.source;
    var catalog = {
      variables: function () {
        return typeof options.variables === 'function'
          ? options.variables()
          : options.variables || [];
      },
      functions: function () {
        var entries = options.functions ? options.functions() : [];
        return entries.length
          ? entries
          : functions.map(function (name) {
              return {
                name: name,
                signature: name + '(…)',
                doc: 'Function help is loading or unavailable.',
                origin: 'Python / Docassemble',
              };
            });
      },
    };
    var toolbar = el('div', 'expression-toolbar expression-view-toolbar');
    var intro = el('div', 'expression-intro');
    var heading = {
      code: 'Define variables',
      boolean: 'Build a condition',
      value: 'Build a value',
    };
    intro.appendChild(el('h3', '', heading[options.context] || heading.value));
    toolbar.appendChild(intro);
    var modes = el('div', 'expression-mode-switch');
    modes.setAttribute('role', 'group');
    modes.setAttribute('aria-label', 'Editing view');
    var guideButton = button('Expression editor', function () {
      inspect();
    });
    var sourceButton = button('Python', function () {
      sequence++;
      show(false);
    });
    modes.append(guideButton, sourceButton);
    toolbar.appendChild(modes);
    var status = el('p', 'small text-muted expression-status');
    status.setAttribute('role', 'status');
    var body = el('div', 'expression-guided');
    var preview = el('pre', 'expression-preview');
    preview.setAttribute('aria-label', 'Generated Python');
    var previewPanel = el('details', 'expression-preview-panel');
    previewPanel.append(el('summary', '', 'Python preview'), preview);
    host.append(toolbar, status, body, previewPanel);
    host.appendChild(options.sourceHost);

    function show(value) {
      guided = value;
      body.hidden = !value;
      previewPanel.hidden = !value;
      options.sourceHost.hidden = value;
      guideButton.setAttribute('aria-pressed', String(value));
      sourceButton.setAttribute('aria-pressed', String(!value));
      if (!value)
        status.textContent =
          'Python source. Switch to Expression editor to check guided support.';
    }
    function render() {
      body.replaceChildren();
      var rows =
        options.context === 'code'
          ? parsed.rows.filter(function (row) {
              return !row.deleted;
            })
          : [{ tree: parsed.tree }];
      var comments = parsed.comments || [];
      var originalRows = rows.filter(function (row) {
        return !row.added;
      });
      if (options.context === 'code') {
        var columns = el('div', 'expression-columns');
        columns.append(
          el('span', '', 'Variable'),
          el('span', '', ''),
          el('span', '', 'Value / calculation'),
        );
        body.appendChild(columns);
      }
      rows.forEach(function (row, index) {
        var section = el(
          'section',
          'expression-assignment' +
            (options.context === 'code' ? ' expression-definition' : ''),
        );
        if (options.context === 'code') {
          var firstOperand = row.tree,
            headerDepth = 0;
          while (firstOperand.args && firstOperand.args.length) {
            if (firstOperand.kind === 'function') break;
            headerDepth++;
            firstOperand = firstOperand.args[0];
          }
          section.style.setProperty(
            '--expression-label-offset',
            headerDepth * 29 +
              (firstOperand.kind === 'function' ? 9 : 0) +
              'px',
          );
          comments
            .filter(function (comment) {
              return (
                comment.line < row.line &&
                (!index || comment.line > rows[index - 1].end_line)
              );
            })
            .forEach(function (comment) {
              body.appendChild(
                el(
                  'div',
                  'expression-comment expression-leading-comment',
                  comment.text,
                ),
              );
            });
          var target = el('div', 'expression-target');
          var targetInput = el(
            'input',
            'form-control form-control-sm font-monospace',
          );
          targetInput.value = row.target;
          targetInput.setAttribute(
            'aria-label',
            'Assignment variable ' + (index + 1),
          );
          targetInput.placeholder = 'Variable to define';
          function rename(value) {
            row.target = value;
            section.setAttribute('aria-label', 'Define ' + value);
            change();
          }
          targetInput.addEventListener('input', function () {
            rename(targetInput.value);
          });
          target.appendChild(picker(targetInput, catalog.variables, rename));
          var equals = el('span', 'expression-equals', '=');
          equals.setAttribute('aria-label', 'is defined as');
          section.append(target, equals);
          section.setAttribute('aria-label', 'Define ' + row.target);
        }
        function change() {
          row.edited = true;
          var next;
          if (options.context === 'code') next = codeSource(parsed);
          else next = python(row.tree);
          source.setValue(next);
          preview.textContent = next;
        }
        function redraw(next) {
          var controls = Array.from(
            body.querySelectorAll('input, textarea, select, button'),
          );
          var focusedIndex = controls.indexOf(document.activeElement);
          row.tree = next;
          if (options.context !== 'code') parsed.tree = next;
          change();
          render();
          var updatedControls = body.querySelectorAll(
            'input, textarea, select, button',
          );
          if (focusedIndex >= 0 && updatedControls.length)
            updatedControls[
              Math.min(focusedIndex, updatedControls.length - 1)
            ].focus();
        }
        var value = el('div', 'expression-definition-value');
        value.appendChild(draw(row.tree, redraw, change, catalog, 0));
        if (row.target)
          comments
            .filter(function (comment) {
              return (
                comment.line >= row.line &&
                comment.line <= row.end_line &&
                (!rows[index + 1] ||
                  rows[index + 1].added ||
                  comment.start < rows[index + 1].start)
              );
            })
            .forEach(function (comment) {
              value.appendChild(el('div', 'expression-comment', comment.text));
            });
        section.appendChild(value);
        if (options.context === 'code') {
          var remove = button('Delete assignment', function () {
            row.deleted = true;
            source.setValue(codeSource(parsed));
            render();
            var remaining = body.querySelectorAll(
              '.expression-delete-assignment',
            );
            var focus =
              remaining[Math.min(index, remaining.length - 1)] ||
              body.querySelector('.expression-add-assignment');
            if (focus) focus.focus();
          });
          remove.classList.add('expression-delete-assignment');
          remove.setAttribute('aria-label', 'Delete assignment ' + (index + 1));
          value.appendChild(remove);
        }
        body.appendChild(section);
      });
      if (options.context === 'code')
        comments
          .filter(function (comment) {
            return (
              !originalRows.length ||
              comment.line > originalRows[originalRows.length - 1].end_line
            );
          })
          .forEach(function (comment) {
            body.appendChild(
              el(
                'div',
                'expression-comment expression-leading-comment',
                comment.text,
              ),
            );
          });
      if (options.context === 'code') {
        body.appendChild(
          button('Add assignment', function () {
            var name = 'new_variable',
              suffix = 2;
            var names = catalog.variables().map(function (item) {
              return typeof item === 'string' ? item : item.name;
            });
            names = names.concat(
              rows.map(function (row) {
                return row.target;
              }),
            );
            while (names.indexOf(name) !== -1)
              name = 'new_variable_' + suffix++;
            parsed.rows.push({
              target: name,
              tree: fresh('none'),
              added: true,
            });
            source.setValue(codeSource(parsed));
            render();
            var inputs = body.querySelectorAll('.expression-target input');
            inputs[inputs.length - 1].focus();
            inputs[inputs.length - 1].select();
          }),
        );
      }
      var addButton = body.lastElementChild;
      if (options.context === 'code' && addButton)
        addButton.classList.add('expression-add-assignment');
      preview.textContent = source.getValue();
    }
    async function inspect() {
      var ticket = ++sequence,
        before = source.getValue();
      status.textContent = 'Checking expression…';
      try {
        var result =
          before.trim() || options.context === 'code'
            ? await options.parse(before, options.context)
            : {
                supported: true,
                valid: true,
                tree: fresh(
                  options.context === 'boolean' ? 'comparison' : 'variable',
                ),
              };
        if (!alive || ticket !== sequence || before !== source.getValue())
          return;
        parsed = result;
        if (result.supported) {
          parsed.original = before;
          (parsed.rows || []).forEach(function (row) {
            row.originalTree = JSON.parse(JSON.stringify(row.tree));
            row.originalTarget = row.target;
          });
          render();
          show(true);
          var hints = {
            boolean: 'Condition: use comparisons and AND / OR groups.',
            code: 'Each row defines one variable. Comments stay with your code.',
            value: 'Choose a value, comparison, or calculation.',
          };
          status.textContent = hints[options.context] || hints.value;
        } else {
          show(false);
          status.textContent =
            (result.valid ? 'Advanced Python. ' : 'Python needs attention. ') +
            result.reason;
        }
      } catch (error) {
        if (alive && ticket === sequence) {
          show(false);
          status.textContent =
            'Guided editor unavailable. Your Python is unchanged. ' +
            error.message;
        }
      }
    }
    show(false);
    inspect();
    return {
      dispose: function () {
        alive = false;
        sequence++;
      },
      isGuided: function () {
        return guided;
      },
    };
  }

  function install(options) {
    var active = null;
    async function open(value, context, apply, title, opener) {
      if (active) {
        var activeFeedback = active.querySelector('[role="alert"]');
        if (activeFeedback) {
          activeFeedback.textContent =
            'Finish or cancel the expression editor that is already open.';
          activeFeedback.tabIndex = -1;
          activeFeedback.focus();
        }
        return;
      }
      var dialog = el('dialog', 'expression-dialog');
      dialog.setAttribute('aria-labelledby', 'expression-dialog-title');
      var heading = el('h2', 'h5', title || 'Edit expression');
      heading.id = 'expression-dialog-title';
      var host = el('div', 'expression-workspace');
      var sourceHost = el('div', 'editor-source-container expression-source');
      sourceHost.id = 'expression-modal-source';
      var feedback = el('p', 'text-danger');
      feedback.setAttribute('role', 'alert');
      var footer = el('div', 'expression-toolbar expression-dialog-footer');
      dialog.append(heading, host, feedback, footer);
      document.body.appendChild(dialog);
      // Bootstrap modals may be underneath this native modal. Keep their focus
      // trap from pulling keyboard focus out of the top-level dialog.
      dialog.addEventListener('focusin', function (event) {
        event.stopPropagation();
      });
      dialog.addEventListener('input', function (event) {
        event.stopPropagation();
      });
      dialog.addEventListener('change', function (event) {
        event.stopPropagation();
      });
      host.appendChild(sourceHost);
      var source = options.createSource(sourceHost.id, value, 'python', {
        ariaLabel: 'Python expression',
      });
      var view = mount(host, {
        source: source,
        sourceHost: sourceHost,
        context: context,
        parse: options.parse,
        variables: options.variables,
        functions: options.functions,
      });
      active = dialog;
      function close() {
        view.dispose();
        source.dispose();
        dialog.close();
        dialog.remove();
        active = null;
        if (opener && opener.isConnected) opener.focus();
      }
      dialog.addEventListener('cancel', function (event) {
        event.preventDefault();
        close();
      });
      footer.appendChild(button('Cancel', close));
      var applyButton = button('Apply expression', async function () {
        var candidate = source.getValue();
        applyButton.disabled = true;
        try {
          // A no-op must preserve exact bytes, even for an incomplete expression.
          if (candidate !== value) {
            var result = await options.parse(candidate, context);
            if (active !== dialog) return;
            if (candidate !== source.getValue()) {
              feedback.textContent =
                'The expression changed while checking. Apply again.';
              return;
            }
            if (!result.valid) {
              feedback.textContent = result.reason;
              return;
            }
            apply(candidate);
          }
          close();
        } catch (error) {
          feedback.textContent = error.message;
        } finally {
          applyButton.disabled = false;
        }
      });
      applyButton.className = 'btn btn-primary';
      footer.appendChild(applyButton);
      dialog.showModal();
    }

    function write(input, value) {
      if (!input.isConnected)
        throw new Error('The original field is no longer open.');
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }
    function enhance() {
      document
        .querySelectorAll(
          'input[data-expression-context], textarea[data-expression-context]',
        )
        .forEach(function (input) {
          if (input.dataset.expressionReady || input.disabled || input.readOnly)
            return;
          input.dataset.expressionReady = 'true';
          var action = button('Edit expression', function () {
            var original = input.value;
            var wrapper = input.dataset.expressionWrapper;
            var value = original;
            if (wrapper === 'mako') {
              var templateExpression = /^\$\{([\s\S]*)\}$/.exec(
                original.trim(),
              );
              value = original.trim() ? JSON.stringify(original) : '';
              if (templateExpression) value = templateExpression[1].trim();
            }
            if (wrapper === 'code') {
              try {
                var obj = JSON.parse(original);
                if (obj && typeof obj === 'object') {
                  if (
                    Object.keys(obj).length !== 1 ||
                    typeof obj.code !== 'string'
                  ) {
                    options.alert(
                      'This field uses a variable/is or other structured condition. Edit its YAML to preserve that structure.',
                    );
                    return;
                  }
                  value = obj.code;
                }
              } catch {
                // Plain variable: explicitly converting to server-side code.
                value = original;
              }
            }
            open(
              value,
              input.dataset.expressionContext,
              function (next) {
                if (input.value !== original)
                  throw new Error(
                    'The field changed while the expression editor was open. Reopen it.',
                  );
                var replacement = next;
                input.dataset.expressionApplied = 'true';
                if (wrapper === 'code') {
                  input.dataset.expressionMapping = 'true';
                  replacement = JSON.stringify({ code: next });
                }
                if (wrapper === 'mako') replacement = '${ ' + next + ' }';
                write(input, replacement);
              },
              wrapper === 'code'
                ? 'Python expression (evaluated before the screen is shown)'
                : 'Edit expression',
              action,
            );
          });
          var group = el('div', 'expression-input-group');
          input.insertAdjacentElement('beforebegin', group);
          group.append(input, action);
        });
    }
    var pending = false;
    new MutationObserver(function () {
      if (!pending) {
        pending = true;
        queueMicrotask(function () {
          pending = false;
          options.annotate();
          enhance();
        });
      }
    }).observe(document.body, { childList: true, subtree: true });
    options.annotate();
    enhance();
    return { open: open, write: write };
  }
  var api = {
    python: python,
    fresh: fresh,
    changeType: changeType,
    codeChanges: codeChanges,
    codeSource: codeSource,
    mount: mount,
    install: install,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.WeaverExpressions = api;
})(typeof window !== 'undefined' ? window : globalThis);
