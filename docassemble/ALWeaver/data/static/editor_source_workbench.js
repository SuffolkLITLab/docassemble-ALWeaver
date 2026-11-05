/* Reviewed, undoable source operations. All previews are read-only on the server. */
(function (root) {
  'use strict';
  function minimalEdit(before, after) {
    var from = 0,
      oldEnd = before.length,
      newEnd = after.length;
    while (from < oldEnd && from < newEnd && before[from] === after[from])
      from++;
    while (
      oldEnd > from &&
      newEnd > from &&
      before[oldEnd - 1] === after[newEnd - 1]
    ) {
      oldEnd--;
      newEnd--;
    }
    return { from: from, to: oldEnd, insert: after.slice(from, newEnd) };
  }
  function filterRecipes(nodes, query) {
    query = query.trim().toLowerCase();
    if (!query) return nodes;
    return nodes.flatMap(function (node) {
      if (node.title.toLowerCase().includes(query)) return [node];
      if (node.children) {
        var children = filterRecipes(node.children, query);
        return children.length
          ? [Object.assign({}, node, { children: children })]
          : [];
      }
      return (node.source || '').toLowerCase().includes(query) ? [node] : [];
    });
  }
  function attach(bundle, container, actions) {
    var view = bundle.ev,
      doc = container.ownerDocument;
    var disposed = false,
      sequence = 0,
      snapshot = '',
      cursor = 0;
    var dialog = doc.createElement('dialog');
    dialog.className = 'editor-source-workbench-dialog';
    dialog.setAttribute('aria-labelledby', 'source-workbench-title');
    var title = doc.createElement('h2');
    title.id = 'source-workbench-title';
    title.className = 'h5';
    dialog.appendChild(title);
    var status = doc.createElement('p');
    status.setAttribute('role', 'status');
    dialog.appendChild(status);
    var body = doc.createElement('div');
    dialog.appendChild(body);
    var close = doc.createElement('button');
    close.type = 'button';
    close.className = 'btn btn-secondary mt-3';
    close.textContent = 'Close';
    close.addEventListener('click', function () {
      dialog.close();
    });
    dialog.appendChild(close);
    dialog.addEventListener('close', function () {
      sequence++;
      if (!disposed) view.focus();
    });
    doc.body.appendChild(dialog);
    function control(parent, label, handler) {
      var button = doc.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-sm btn-outline-secondary m-1';
      button.textContent = label;
      button.addEventListener('click', handler);
      parent.appendChild(button);
      return button;
    }
    var toolbar = container.querySelector('.editor-source-tools');
    var menu = doc.createElement('details');
    menu.className = 'editor-source-actions';
    var summary = doc.createElement('summary');
    summary.className = 'btn btn-sm btn-link';
    summary.textContent = 'Tools';
    menu.appendChild(summary);
    var menuItems = doc.createElement('div');
    menuItems.className = 'editor-source-actions-menu';
    menu.appendChild(menuItems);
    toolbar.appendChild(menu);
    var expression = container.querySelector(':scope > button');
    if (expression) {
      expression.className = 'dropdown-item';
      menuItems.appendChild(expression);
    }
    var buttons = [];
    [
      ['diff', 'Changes'],
      ['repair', 'Repair block IDs'],
      ['recipes', 'Recipes'],
      ['outline', 'Source outline'],
    ].forEach(function (entry) {
      buttons.push(
        control(menuItems, entry[1], function () {
          menu.open = false;
          open(entry[0]);
        }),
      );
    });
    if (actions.insertBlock)
      buttons.push(
        control(menuItems, 'Insert block…', function () {
          menu.open = false;
          actions.insertBlock();
        }),
      );
    function current() {
      return !disposed && snapshot === view.state.doc.toString();
    }
    function apply(edit) {
      if (!current()) {
        status.textContent =
          'Source changed. Close this preview and open it again.';
        return;
      }
      if (
        edit.before !== undefined &&
        snapshot.slice(edit.from, edit.to) !== edit.before
      ) {
        status.textContent =
          'The selected source range changed. Open a fresh preview.';
        return;
      }
      view.dispatch({
        changes: { from: edit.from, to: edit.to, insert: edit.insert },
        selection: { anchor: edit.from + edit.insert.length },
        userEvent: 'input',
        scrollIntoView: true,
      });
      dialog.close();
    }
    function showDiff(diff) {
      var pre = doc.createElement('pre');
      pre.className = 'editor-source-preview-diff';
      pre.textContent = diff || 'No source changes.';
      body.appendChild(pre);
    }
    function showProposal(data, label) {
      showDiff(data.diff);
      if (data.source !== snapshot)
        control(body, label, function () {
          apply(data.edit || minimalEdit(snapshot, data.source));
        });
      var note = doc.createElement('p');
      note.textContent =
        'Apply changes only the unsaved editor buffer. Review and Save when ready; Undo restores the previous source.';
      body.appendChild(note);
    }
    function renderDiff(data) {
      var note = doc.createElement('p');
      note.textContent =
        'Compared with the file currently saved on the server. Reverting changes only the unsaved buffer.';
      body.appendChild(note);
      showDiff(data.diff);
      data.hunks.forEach(function (hunk, index) {
        var section = doc.createElement('details');
        var summary = doc.createElement('summary');
        summary.textContent = 'Change ' + (index + 1) + ' · line ' + hunk.line;
        section.appendChild(summary);
        var pre = doc.createElement('pre');
        pre.textContent = hunk.diff;
        section.appendChild(pre);
        control(section, 'Revert change ' + (index + 1), function () {
          apply(hunk);
        });
        body.appendChild(section);
      });
      if (data.hunks.length)
        control(body, 'Restore saved source', function () {
          // The diff is already visible; applying remains an undoable local edit.
          apply(minimalEdit(snapshot, data.saved_source));
        });
    }
    function renderRecipes(data) {
      var label = doc.createElement('label');
      label.textContent = 'Search Playground examples';
      label.className = 'd-block';
      var search = doc.createElement('input');
      search.type = 'search';
      search.className = 'form-control';
      label.appendChild(search);
      body.appendChild(label);
      var catalogWarning = status.textContent;
      var resultCount = doc.createElement('p');
      resultCount.className = 'small text-muted my-1';
      resultCount.setAttribute('role', 'status');
      body.appendChild(resultCount);
      var browser = doc.createElement('div');
      browser.className = 'editor-recipe-browser';
      var tree = doc.createElement('nav');
      tree.className = 'editor-recipe-tree';
      tree.setAttribute('aria-label', 'Example categories');
      tree.tabIndex = 0;
      var preview = doc.createElement('section');
      preview.className = 'editor-recipe-preview';
      preview.setAttribute('aria-label', 'Selected example');
      preview.tabIndex = 0;
      preview.textContent = 'Choose an example to preview its source.';
      browser.append(tree, preview);
      body.appendChild(browser);
      var expanded = new Set(),
        selected = null;
      function link(parent, text, href) {
        if (!href) return;
        var url;
        try {
          url = new URL(href, doc.baseURI);
        } catch {
          return;
        }
        if (!['http:', 'https:'].includes(url.protocol)) return;
        var anchor = doc.createElement('a');
        anchor.href = url.href;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
        anchor.className = 'me-3';
        anchor.textContent = text;
        parent.appendChild(anchor);
      }
      function selectRecipe(recipe) {
        sequence++;
        status.textContent = catalogWarning;
        selected = recipe.id;
        tree.querySelectorAll('[data-recipe-id]').forEach(function (button) {
          button.setAttribute(
            'aria-pressed',
            String(button.dataset.recipeId === selected),
          );
        });
        preview.replaceChildren();
        var heading = doc.createElement('h3');
        heading.className = 'h6';
        heading.textContent = recipe.title;
        preview.appendChild(heading);
        var links = doc.createElement('p');
        link(links, 'Documentation', recipe.documentation);
        link(links, 'Run complete example', recipe.interview);
        preview.appendChild(links);
        var source = doc.createElement('pre');
        source.tabIndex = 0;
        source.textContent = recipe.source;
        preview.appendChild(source);
        if (recipe.before || recipe.after) {
          var context = doc.createElement('details');
          var contextTitle = doc.createElement('summary');
          contextTitle.textContent =
            'Surrounding code from the complete example';
          context.appendChild(contextTitle);
          var contextSource = doc.createElement('pre');
          contextSource.tabIndex = 0;
          contextSource.textContent = [
            recipe.before,
            recipe.source,
            recipe.after,
          ]
            .filter(Boolean)
            .join('\n');
          context.appendChild(contextSource);
          preview.appendChild(context);
          var note = doc.createElement('p');
          note.className = 'small text-muted';
          note.textContent =
            'Only the selected example blocks are inserted. Check the surrounding code for any setup they need.';
          preview.appendChild(note);
        }
        var insert = control(
          preview,
          'Insert after current block',
          function () {
            if (!current()) {
              status.textContent =
                'Source changed. Close this browser and open it again.';
              return;
            }
            insert.disabled = true;
            status.textContent = 'Preparing insertion…';
            var requestSequence = ++sequence;
            actions
              .preview({
                action: 'insert-block',
                raw_yaml: snapshot,
                cursor: cursor,
                block_yaml: recipe.source,
              })
              .then(function (response) {
                if (disposed || requestSequence !== sequence || !dialog.open)
                  return;
                if (!response.success)
                  throw new Error(
                    (response.error && response.error.message) ||
                      'Could not insert this example.',
                  );
                apply(response.data.edit);
              })
              .catch(function (error) {
                if (!disposed && requestSequence === sequence && dialog.open)
                  status.textContent = error.message;
              })
              .finally(function () {
                insert.disabled = false;
                if (!disposed && requestSequence === sequence && dialog.open)
                  insert.focus();
              });
          },
        );
        preview.insertBefore(insert, source);
      }
      function render() {
        tree.replaceChildren();
        var query = search.value.trim().toLowerCase();
        function append(nodes, parent) {
          nodes.forEach(function (node) {
            if (node.children) {
              var group = doc.createElement('details');
              var heading = doc.createElement('summary');
              heading.textContent = node.title;
              group.appendChild(heading);
              group.open = Boolean(query) || expanded.has(node.id);
              group.addEventListener('toggle', function () {
                if (!query) {
                  if (group.open) expanded.add(node.id);
                  else expanded.delete(node.id);
                }
              });
              append(node.children, group);
              parent.appendChild(group);
            } else {
              var button = control(parent, node.title, function () {
                selectRecipe(node);
              });
              button.dataset.recipeId = node.id;
              button.setAttribute('aria-pressed', String(node.id === selected));
            }
          });
        }
        var nodes = filterRecipes(data.recipes, query);
        append(nodes, tree);
        function count(items) {
          return items.reduce(function (total, node) {
            return total + (node.children ? count(node.children) : 1);
          }, 0);
        }
        resultCount.textContent = count(nodes) + ' matching examples';
        if (!nodes.length) tree.textContent = 'No matching examples.';
      }
      search.addEventListener('input', render);
      render();
    }
    function renderOutline(data) {
      var label = doc.createElement('label');
      label.textContent = 'Find a block, ID, or variable';
      var search = doc.createElement('input');
      search.type = 'search';
      search.className = 'form-control';
      label.appendChild(search);
      body.appendChild(label);
      var list = doc.createElement('div');
      body.appendChild(list);
      function render() {
        list.replaceChildren();
        data.blocks
          .filter(function (block) {
            return [block.id, block.title, block.type, block.variable]
              .join(' ')
              .toLowerCase()
              .includes(search.value.toLowerCase());
          })
          .forEach(function (block) {
            control(
              list,
              (block.title || block.id || block.type) +
                ' · ' +
                block.type +
                ' · line ' +
                block.line_start,
              function () {
                if (!current()) {
                  status.textContent = 'Source changed. Refresh the outline.';
                  return;
                }
                var line = Number(block.line_start);
                if (
                  !Number.isInteger(line) ||
                  line < 1 ||
                  line > view.state.doc.lines
                )
                  return;
                var from = view.state.doc.line(line).from;
                view.dispatch({
                  selection: { anchor: from },
                  effects: view.constructor.scrollIntoView(from, {
                    y: 'start',
                  }),
                });
                dialog.close();
              },
            );
          });
      }
      search.addEventListener('input', render);
      render();
    }
    function request(action, extra) {
      var requestSequence = ++sequence;
      body.replaceChildren();
      status.textContent = 'Preparing preview…';
      return actions
        .preview(
          Object.assign(
            { action: action, raw_yaml: snapshot, cursor: cursor },
            extra,
          ),
        )
        .then(function (response) {
          if (disposed || requestSequence !== sequence || !dialog.open) return;
          if (!current()) {
            status.textContent =
              'Source changed. Close this preview and open it again.';
            return;
          }
          if (!response.success)
            throw new Error(
              (response.error && response.error.message) ||
                'Could not prepare preview.',
            );
          var data = response.data;
          status.textContent =
            data.base_revision_matches === false
              ? 'The saved file changed since you opened it. Saving will still check your original revision. Use Changes to compare against the current server file.'
              : '';
          if (action === 'diff') renderDiff(data);
          else if (action === 'recipes') renderRecipes(data);
          else if (action === 'outline') renderOutline(data);
          else if (action === 'repair') {
            var summary = doc.createElement('p');
            summary.textContent =
              data.repair_count +
              ' block ID repairs proposed. ' +
              data.remaining_diagnostics.length +
              ' blocking diagnostics remain.';
            body.appendChild(summary);
            showProposal(data, 'Apply block ID repairs');
          }
        })
        .catch(function (error) {
          if (!disposed && requestSequence === sequence)
            status.textContent = error.message || 'Could not prepare preview.';
        });
    }
    function open(action) {
      snapshot = view.state.doc.toString();
      cursor = view.state.selection.main.head;
      title.textContent = {
        diff: 'Unsaved source changes',
        repair: 'Repair missing or duplicate block IDs',
        recipes: 'Source recipes',
        outline: 'Outline of the current source',
      }[action];
      if (!dialog.open) dialog.showModal();
      request(action);
    }
    return {
      dispose: function () {
        disposed = true;
        sequence++;
        dialog.remove();
        menu.remove();
        buttons.forEach(function (button) {
          button.remove();
        });
      },
    };
  }
  var api = {
    minimalEdit: minimalEdit,
    filterRecipes: filterRecipes,
    attach: attach,
  };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ALWeaverSourceWorkbench = api;
})(typeof window === 'undefined' ? globalThis : window);
