/* Runtime inspector UI backed exclusively by Weaver's authenticated endpoints. */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverRuntimeInspector = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function clone(value) {
    if (value === undefined) return undefined;
    return JSON.parse(JSON.stringify(value));
  }

  function filterVariables(variables, query) {
    var needle = String(query || '').trim().toLowerCase();
    var result = {};
    Object.keys(variables || {}).sort().forEach(function (name) {
      if (!needle || name.toLowerCase().indexOf(needle) !== -1) result[name] = variables[name];
    });
    return result;
  }

  function changedVariableNames(before, after) {
    var names = {};
    Object.keys(before || {}).concat(Object.keys(after || {})).forEach(function (name) {
      if (JSON.stringify((before || {})[name]) !== JSON.stringify((after || {})[name])) {
        names[name] = true;
      }
    });
    return Object.keys(names).sort();
  }

  function findQuestionSource(question, blocks) {
    var questionName = question && question.questionName;
    if (!questionName) return null;
    return (blocks || []).find(function (block) {
      return block && (
        block.id === questionName ||
        (block.data && (block.data.id === questionName || block.data.event === questionName))
      );
    }) || null;
  }

  function createRuntimeInspector(options) {
    options = options || {};
    var api = options.api;
    var getContext = options.getContext;
    var getBlocks = options.getBlocks || function () { return []; };
    var onSessionChange = options.onSessionChange || function () {};
    // Runs before a test session is created, so pending Python module changes
    // can be loaded first. Resolving false abandons the start.
    var beforeStart = options.beforeStart || function () { return Promise.resolve(true); };
    var session = null;
    var question = null;
    var variables = {};
    var previousVariables = {};
    var changed = [];
    var includeInternal = false;
    var variableQuery = '';
    var status = '';
    var error = '';
    var container = null;

    function sessionPath(suffix) {
      if (!session || !session.weaver_session_id) throw new Error('Start a test session first.');
      return '/api/runtime/sessions/' + encodeURIComponent(session.weaver_session_id) + (suffix || '');
    }

    function setStatus(message, isError) {
      status = isError ? '' : String(message || '');
      error = isError ? String(message || '') : '';
    }

    function startSession() {
      var context = getContext();
      return Promise.resolve(beforeStart()).then(function (proceed) {
        if (proceed === false) return undefined;
        setStatus('Starting a separate Docassemble test session...');
        render(container);
        return api.post('/api/runtime/sessions', {
          project: context.project,
          filename: context.filename,
          purpose: 'test',
        }).then(function (response) {
          session = clone(response.data);
          question = null;
          variables = {};
          previousVariables = {};
          changed = [];
          onSessionChange(clone(session));
          setStatus('Test session started.');
          render(container);
          return refreshAll();
        }).catch(function (requestError) {
          setStatus(requestError.message || 'Unable to start the test session.', true);
          render(container);
        });
      });
    }

    function endSession() {
      if (!session) return Promise.resolve();
      return api.delete(sessionPath()).then(function () {
        session = null;
        question = null;
        variables = {};
        changed = [];
        onSessionChange(null);
        setStatus('Inspector access to the test session ended.');
        render(container);
      });
    }

    function refreshQuestion() {
      return api.get(sessionPath('/question')).then(function (response) {
        question = clone(response.data.question || {});
        setStatus('Current question observed from Docassemble.');
        render(container);
      });
    }

    function refreshVariables() {
      var path = sessionPath('/variables') + (includeInternal ? '?include_internal=true' : '');
      return api.get(path).then(function (response) {
        previousVariables = variables;
        variables = clone(response.data.variables || {});
        changed = changedVariableNames(previousVariables, variables);
        render(container);
      });
    }

    function refreshAll() {
      if (!session) return Promise.resolve();
      return Promise.all([refreshQuestion(), refreshVariables()]).catch(function (requestError) {
        setStatus(requestError.message || 'Unable to refresh runtime facts.', true);
        render(container);
      });
    }

    function goBack() {
      return api.post(sessionPath('/back'), {}).then(refreshAll).catch(function (requestError) {
        setStatus(requestError.message || 'Docassemble could not go back.', true);
        render(container);
      });
    }

    function applyScenario(text) {
      return api.post(sessionPath('/variables'), { scenario_yaml: String(text || '') }).then(function () {
        setStatus('Scenario applied. Seeded state may bypass earlier questions.');
        return refreshAll();
      }).catch(function (requestError) {
        setStatus(requestError.message || 'Unable to apply the scenario.', true);
        render(container);
      });
    }

    function appendVariableRows(target) {
      var visible = filterVariables(variables, variableQuery);
      var names = Object.keys(visible);
      if (!names.length) {
        target.textContent = 'No matching variables.';
        target.className = 'text-muted small';
        return;
      }
      names.forEach(function (name) {
        var details = document.createElement('details');
        details.className = 'editor-runtime-variable border rounded p-2 mb-2';
        if (changed.indexOf(name) !== -1) details.classList.add('border-warning', 'bg-warning-subtle');
        var summary = document.createElement('summary');
        summary.textContent = name + ' · ' + (visible[name] === null ? 'null' : typeof visible[name]);
        details.appendChild(summary);
        var value = document.createElement('pre');
        value.className = 'small mt-2 mb-0 text-wrap';
        value.textContent = JSON.stringify(visible[name], null, 2);
        details.appendChild(value);
        target.appendChild(details);
      });
    }

    function renderQuestion(target) {
      if (!question) {
        target.textContent = 'No runtime question has been inspected yet.';
        return;
      }
      var name = question.questionName || '(no stable question name)';
      var type = question.questionType || question.type || 'unknown';
      var heading = document.createElement('h3');
      heading.className = 'h6';
      heading.textContent = name;
      target.appendChild(heading);
      var meta = document.createElement('p');
      meta.className = 'small text-muted';
      meta.textContent = 'Question type: ' + type + ' · observed runtime fact';
      target.appendChild(meta);
      var undefinedName = question.undefinedVariable || question.undefined;
      if (undefinedName) {
        var undefinedEl = document.createElement('p');
        undefinedEl.textContent = 'Undefined variable: ' + String(undefinedName);
        target.appendChild(undefinedEl);
      }
      var sourceBlock = findQuestionSource(question, getBlocks());
      var mapping = document.createElement('p');
      mapping.className = 'small';
      mapping.textContent = sourceBlock
        ? 'Source match: ' + sourceBlock.id
        : 'No confident source-block match is available.';
      target.appendChild(mapping);
      if (question.fields) {
        var fields = document.createElement('pre');
        fields.className = 'small bg-light border rounded p-2';
        fields.textContent = JSON.stringify(question.fields, null, 2);
        target.appendChild(fields);
      }
    }

    function render(target) {
      container = target || container;
      if (!container) return;
      container.innerHTML = '';
      var wrapper = document.createElement('section');
      wrapper.className = 'editor-runtime-inspector p-3';
      wrapper.setAttribute('aria-labelledby', 'runtime-inspector-title');
      wrapper.innerHTML =
        '<div class="d-flex flex-wrap justify-content-between gap-2 align-items-start">' +
          '<div><h2 class="h4 mb-1" id="runtime-inspector-title">Runtime inspector</h2>' +
          '<p class="text-muted small">Docassemble is the authoritative runtime. This view only inspects a separate test session.</p></div>' +
          '<div class="d-flex flex-wrap gap-2" id="runtime-session-actions"></div>' +
        '</div>' +
        '<div class="alert alert-info py-2" id="runtime-status" role="status" aria-live="polite"></div>' +
        '<div id="runtime-session-content"></div>';
      container.appendChild(wrapper);
      var statusNode = wrapper.querySelector('#runtime-status');
      statusNode.textContent = error || status || (session ? 'Test session is active.' : 'Start a test session to inspect Docassemble runtime facts.');
      statusNode.classList.toggle('alert-danger', Boolean(error));
      statusNode.classList.toggle('alert-info', !error);
      var actions = wrapper.querySelector('#runtime-session-actions');
      var content = wrapper.querySelector('#runtime-session-content');

      if (!session) {
        var start = document.createElement('button');
        start.type = 'button';
        start.className = 'btn btn-primary';
        start.textContent = 'Start new test session';
        start.addEventListener('click', startSession);
        actions.appendChild(start);
        return;
      }

      var open = document.createElement('a');
      open.className = 'btn btn-primary';
      open.textContent = 'Open interview';
      open.target = '_blank';
      open.rel = 'noopener';
      open.href = session.target_url;
      actions.appendChild(open);
      [['Inspect current question', refreshQuestion], ['Refresh variables', refreshVariables], ['Back', goBack]].forEach(function (item) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-outline-secondary';
        button.textContent = item[0];
        button.addEventListener('click', item[1]);
        actions.appendChild(button);
      });
      var restart = document.createElement('button');
      restart.type = 'button';
      restart.className = 'btn btn-outline-secondary';
      restart.textContent = 'Start new test session';
      restart.addEventListener('click', function () { endSession().then(startSession); });
      actions.appendChild(restart);
      var end = document.createElement('button');
      end.type = 'button';
      end.className = 'btn btn-outline-danger';
      end.textContent = 'End inspection';
      end.addEventListener('click', endSession);
      actions.appendChild(end);

      content.innerHTML =
        '<div class="row g-3">' +
          '<div class="col-12 col-xl-6"><div class="card h-100"><div class="card-body">' +
            '<h3 class="h5">Current question</h3><div id="runtime-question"></div>' +
          '</div></div></div>' +
          '<div class="col-12 col-xl-6"><div class="card h-100"><div class="card-body">' +
            '<h3 class="h5">Apply scenario</h3>' +
            '<p class="small text-muted">A scenario is a test fixture and may bypass earlier questions.</p>' +
            '<label for="runtime-scenario" class="form-label">Scenario YAML</label>' +
            '<textarea id="runtime-scenario" class="form-control font-monospace" rows="7">name: Test scenario\nvariables:\n  user.marital_status: married\ndelete:\n  - final_document</textarea>' +
            '<button type="button" class="btn btn-outline-primary mt-2" id="runtime-apply-scenario">Apply scenario</button>' +
          '</div></div></div>' +
          '<div class="col-12"><div class="card"><div class="card-body">' +
            '<div class="d-flex flex-wrap justify-content-between gap-2"><h3 class="h5">Session variables</h3>' +
              '<label class="form-check"><input class="form-check-input" type="checkbox" id="runtime-include-internal"> <span class="form-check-label">Show _internal data</span></label></div>' +
            '<label for="runtime-variable-search" class="visually-hidden">Search variables</label>' +
            '<input id="runtime-variable-search" class="form-control form-control-sm mb-3" placeholder="Search variables">' +
            '<div id="runtime-variable-list"></div>' +
          '</div></div></div>' +
        '</div>';
      renderQuestion(content.querySelector('#runtime-question'));
      appendVariableRows(content.querySelector('#runtime-variable-list'));
      content.querySelector('#runtime-apply-scenario').addEventListener('click', function () {
        applyScenario(content.querySelector('#runtime-scenario').value);
      });
      var internalToggle = content.querySelector('#runtime-include-internal');
      internalToggle.checked = includeInternal;
      internalToggle.addEventListener('change', function () {
        includeInternal = internalToggle.checked;
        refreshVariables();
      });
      var search = content.querySelector('#runtime-variable-search');
      search.value = variableQuery;
      search.addEventListener('input', function () {
        variableQuery = search.value;
        var list = content.querySelector('#runtime-variable-list');
        list.innerHTML = '';
        appendVariableRows(list);
      });
    }

    return {
      render: render,
      refreshAll: refreshAll,
      getSession: function () { return clone(session); },
      setSession: function (value) { session = clone(value); onSessionChange(clone(session)); },
    };
  }

  return {
    createRuntimeInspector: createRuntimeInspector,
    filterVariables: filterVariables,
    changedVariableNames: changedVariableNames,
    findQuestionSource: findQuestionSource,
  };
});
