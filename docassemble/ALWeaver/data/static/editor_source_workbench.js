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
      label.textContent = 'Search recipes';
      var search = doc.createElement('input');
      search.type = 'search';
      search.className = 'form-control';
      label.appendChild(search);
      body.appendChild(label);
      var list = doc.createElement('div');
      body.appendChild(list);
      function render() {
        list.replaceChildren();
        data.recipes
          .filter(function (recipe) {
            return (recipe.title + ' ' + recipe.description)
              .toLowerCase()
              .includes(search.value.toLowerCase());
          })
          .forEach(function (recipe) {
            var section = doc.createElement('section');
            var heading = doc.createElement('h3');
            heading.className = 'h6 mt-3';
            heading.textContent = recipe.title;
            section.appendChild(heading);
            var description = doc.createElement('p');
            description.textContent =
              recipe.description + ' ' + recipe.dependencies;
            section.appendChild(description);
            var link = doc.createElement('a');
            link.href = recipe.documentation;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = 'Documentation';
            section.appendChild(link);
            var example = doc.createElement('pre');
            example.textContent = recipe.source;
            section.appendChild(example);
            control(section, 'Preview ' + recipe.title, function () {
              request('recipe', { recipe_id: recipe.id });
            });
            list.appendChild(section);
          });
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
          else {
            if (action === 'repair') {
              var summary = doc.createElement('p');
              summary.textContent =
                data.repair_count +
                ' block ID repairs proposed. ' +
                data.remaining_diagnostics.length +
                ' blocking diagnostics remain.';
              body.appendChild(summary);
            }
            showProposal(
              data,
              action === 'repair' ? 'Apply block ID repairs' : 'Insert recipe',
            );
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
  var api = { minimalEdit: minimalEdit, attach: attach };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ALWeaverSourceWorkbench = api;
})(typeof window === 'undefined' ? globalThis : window);
