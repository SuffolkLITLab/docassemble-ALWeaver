/* First-class interview debugger backed by Weaver's authenticated runtime API. */
(function (/** @type {any} */ root, factory) {
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
    var needle = String(query || '')
      .trim()
      .toLowerCase();
    var result = {};
    Object.keys(variables || {})
      .sort()
      .forEach(function (name) {
        if (!needle || name.toLowerCase().indexOf(needle) !== -1)
          result[name] = variables[name];
      });
    return result;
  }

  function changedVariableNames(before, after) {
    var names = {};
    Object.keys(before || {})
      .concat(Object.keys(after || {}))
      .forEach(function (name) {
        if (
          JSON.stringify((before || {})[name]) !==
          JSON.stringify((after || {})[name])
        ) {
          names[name] = true;
        }
      });
    return Object.keys(names).sort();
  }

  function plainText(value) {
    return (
      String(value || '')
        // Each pattern here has a single unbounded quantifier whose
        // character class excludes the delimiter that ends it, so matching
        // is linear in the input length despite sonarjs's generic warning.
        // eslint-disable-next-line sonarjs/super-linear-regex
        .replace(/<[^>]*>/g, ' ')
        .replace(/&nbsp;/gi, ' ')
        .replace(/&amp;/gi, '&')
        .replace(/&lt;/gi, '<')
        .replace(/&gt;/gi, '>')
        .replace(/&quot;/gi, '"')
        .replace(/&#(?:39|x27);/gi, "'")
        .replace(/\s+/g, ' ')
        // eslint-disable-next-line sonarjs/super-linear-regex
        .replace(/\s+([?!.,:;])/g, '$1')
        .trim()
    );
  }

  function questionLabel(question) {
    question = question || {};
    var candidate =
      question.questionText ||
      question.question ||
      question.title ||
      question.questionName ||
      'Unnamed screen';
    if (typeof candidate !== 'string')
      candidate = question.questionName || 'Unnamed screen';
    var label =
      plainText(candidate) || question.questionName || 'Unnamed screen';
    return label.length > 120 ? label.slice(0, 117) + '...' : label;
  }

  function questionIdentity(question) {
    question = question || {};
    return (
      String(question.questionName || '') ||
      [
        questionLabel(question),
        question.questionType || question.type || '',
      ].join('|')
    );
  }

  function findQuestionSource(question, blocks) {
    var questionName = question && question.questionName;
    if (!questionName) return null;
    return (
      (blocks || []).find(function (block) {
        return (
          block &&
          (block.id === questionName ||
            (block.data &&
              (block.data.id === questionName ||
                block.data.event === questionName)))
        );
      }) || null
    );
  }

  function blockIdLabel(questionName, questionType) {
    // Docassemble prefixes its own internal Question.name with "ID " when a
    // block has an explicit `id:` field (docassemble_base/base/parse.py:
    // ``self.name = "ID " + self.id``). Strip that prefix so the label
    // matches the literal ``id: <value>`` text in the source YAML and can be
    // pasted straight into a source search. A name without that prefix is an
    // auto-generated Question_N/Block_N label, not a literal id, so it is
    // not one Weaver can claim matches the source.
    var name = String(questionName || '');
    if (name.indexOf('ID ') === 0) return 'id: ' + name.slice(3);
    return name || questionType;
  }

  function variablePreview(value) {
    if (value === undefined) return '(removed)';
    var serialized;
    try {
      serialized = JSON.stringify(value);
    } catch {
      // A circular or otherwise unserializable value still needs a preview.
      serialized = String(value);
    }
    if (serialized === undefined) serialized = String(value);
    return serialized.length > 90
      ? serialized.slice(0, 87) + '...'
      : serialized;
  }

  function updateStepHistory(
    history,
    nextQuestion,
    nextVariables,
    nextChanged,
  ) {
    var result = clone(history || []);
    var latest = result.length ? result[result.length - 1] : null;
    if (latest && nextChanged.length) {
      latest.answers = nextChanged.map(function (name) {
        return { name: name, value: clone(nextVariables[name]) };
      });
    }
    var identity = questionIdentity(nextQuestion);
    if (!latest || latest.identity !== identity) {
      result.push({
        identity: identity,
        label: questionLabel(nextQuestion),
        questionName: nextQuestion.questionName || '',
        questionType:
          nextQuestion.questionType || nextQuestion.type || 'unknown',
        visitedAt: new Date().toISOString(),
        answers: [],
      });
    }
    return result.slice(-100);
  }

  function createRuntimeInspector(options) {
    options = options || {};
    var api = options.api;
    var getContext = options.getContext;
    var getBlocks =
      options.getBlocks ||
      function () {
        return [];
      };
    var onSessionChange = options.onSessionChange || function () {};
    var onOpenSource = options.onOpenSource || function () {};
    var onClose = options.onClose || function () {};
    // Runs before a test session is created, so pending Python module changes
    // can be loaded first. Resolving false abandons the start.
    var beforeStart =
      options.beforeStart ||
      function () {
        return Promise.resolve(true);
      };
    var session = null;
    var question = null;
    var variables = {};
    var changed = [];
    var hasVariableSnapshot = false;
    var steps = [];
    var includeInternal = false;
    var variableQuery = '';
    // Polling rebuilds the variable list every second (see startPolling), so
    // <details> elements are recreated from scratch on every refresh. Without
    // remembering which names were open, an expanded variable snaps shut on
    // the next poll tick, mid-read.
    var expandedVariables = {};
    // See refreshRenderedDebugger: lets a poll tick skip rebuilding a panel
    // whose underlying data has not changed.
    var lastRenderedQuestionKey = null;
    var lastRenderedStepsKey = null;
    var scenarioText =
      'name: Test scenario\nvariables:\n  user.marital_status: married\ndelete:\n  - final_document';
    var status = '';
    var error = '';
    var container = null;
    var busy = false;
    var observing = false;
    var observeAgain = false;
    var observationPromise = null;
    var pollTimer = null;
    var hidden = true;

    function sessionPath(suffix) {
      if (!session || !session.weaver_session_id)
        throw new Error('Start a test session first.');
      return (
        '/api/runtime/sessions/' +
        encodeURIComponent(session.weaver_session_id) +
        (suffix || '')
      );
    }

    function setStatus(message, isError) {
      status = isError ? '' : String(message || '');
      error = isError ? String(message || '') : '';
    }

    function resetObservedState() {
      question = null;
      variables = {};
      changed = [];
      hasVariableSnapshot = false;
      steps = [];
      expandedVariables = {};
      lastRenderedQuestionKey = null;
      lastRenderedStepsKey = null;
    }

    function stopPolling() {
      if (pollTimer !== null) {
        window.clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    function startPolling() {
      stopPolling();
      // The interview runs in an iframe and normally advances through AJAX,
      // so its load event is not a reliable navigation signal.  Coalesced
      // observations make this inexpensive while ensuring every click is
      // eventually reflected in the debugger panels.
      pollTimer = window.setInterval(function () {
        if (session && !busy) observeRuntime();
      }, 1000);
    }

    function recordObservation(nextQuestion, nextVariables, nextChanged) {
      steps = updateStepHistory(
        steps,
        nextQuestion,
        nextVariables,
        nextChanged,
      );
    }

    function startSession() {
      var context = getContext();
      busy = true;
      return Promise.resolve(beforeStart())
        .then(function (proceed) {
          if (proceed === false) return undefined;
          setStatus('Starting a separate Docassemble test session...');
          render(container);
          return api
            .post('/api/runtime/sessions', {
              project: context.project,
              filename: context.filename,
              purpose: 'test',
            })
            .then(function (response) {
              session = clone(response.data);
              resetObservedState();
              startPolling();
              onSessionChange(clone(session));
              setStatus(
                'Test session started. Use the interview and the debugger will follow along.',
              );
              render(container);
              return observeRuntime(
                'Debugger synchronized with the interview.',
              );
            });
        })
        .catch(function (requestError) {
          setStatus(
            requestError.message || 'Unable to start the test session.',
            true,
          );
        })
        .finally(function () {
          busy = false;
          render(container);
        });
    }

    function endSession() {
      if (!session) return Promise.resolve();
      busy = true;
      stopPolling();
      return api
        .delete(sessionPath())
        .then(function () {
          session = null;
          resetObservedState();
          onSessionChange(null);
          setStatus('Debugger access to the test session ended.');
        })
        .catch(function (requestError) {
          setStatus(
            requestError.message || 'Unable to end the test session.',
            true,
          );
        })
        .finally(function () {
          busy = false;
          render(container);
        });
    }

    function releaseSession() {
      if (!session) return Promise.resolve();
      var path = sessionPath();
      stopPolling();
      session = null;
      resetObservedState();
      onSessionChange(null);
      return api.delete(path).catch(function () {
        // The owner-scoped server record expires on its own. Context changes
        // should not be blocked just because revocation could not finish.
      });
    }

    function observeRuntime(successMessage) {
      if (!session) return Promise.resolve();
      if (observing) {
        observeAgain = true;
        return observationPromise || Promise.resolve();
      }
      observing = true;
      var variablePath =
        sessionPath('/variables') +
        (includeInternal ? '?include_internal=true' : '');
      observationPromise = Promise.all([
        api.get(sessionPath('/question')),
        api.get(variablePath),
      ])
        .then(function (responses) {
          var nextQuestion = clone((responses[0].data || {}).question || {});
          var nextVariables = clone((responses[1].data || {}).variables || {});
          var nextChanged = hasVariableSnapshot
            ? changedVariableNames(variables, nextVariables)
            : [];
          recordObservation(nextQuestion, nextVariables, nextChanged);
          question = nextQuestion;
          variables = nextVariables;
          changed = nextChanged;
          hasVariableSnapshot = true;
          setStatus(
            successMessage || 'Debugger synchronized with the interview.',
          );
        })
        .catch(function (requestError) {
          setStatus(
            requestError.message || 'Unable to refresh runtime facts.',
            true,
          );
        })
        .finally(function () {
          observing = false;
          observationPromise = null;
          render(container);
          if (observeAgain) {
            observeAgain = false;
            window.setTimeout(function () {
              observeRuntime();
            }, 100);
          }
        });
      return observationPromise;
    }

    function reloadInterview() {
      var frame =
        container && container.querySelector('#runtime-interview-frame');
      if (frame && session) frame.src = session.target_url;
    }

    function goBack() {
      busy = true;
      return api
        .post(sessionPath('/back'), {})
        .then(function () {
          setStatus('Moved the test session back one screen.');
          reloadInterview();
          return observeRuntime();
        })
        .catch(function (requestError) {
          setStatus(
            requestError.message || 'Docassemble could not go back.',
            true,
          );
        })
        .finally(function () {
          busy = false;
          render(container);
        });
    }

    function applyScenario(text) {
      scenarioText = String(text || '');
      busy = true;
      return api
        .post(sessionPath('/variables'), { scenario_yaml: scenarioText })
        .then(function () {
          setStatus(
            'Scenario applied. Seeded state may bypass earlier questions.',
          );
          reloadInterview();
          return observeRuntime();
        })
        .catch(function (requestError) {
          setStatus(
            requestError.message || 'Unable to apply the scenario.',
            true,
          );
        })
        .finally(function () {
          busy = false;
          render(container);
        });
    }

    function appendVariableRows(target) {
      var visible = filterVariables(variables, variableQuery);
      var names = Object.keys(visible);
      if (!names.length) {
        target.textContent = hasVariableSnapshot
          ? 'No matching variables.'
          : 'Variables will appear after the session starts.';
        target.className = 'text-muted small';
        return;
      }
      names.forEach(function (name) {
        var details = document.createElement('details');
        details.className = 'editor-runtime-variable';
        details.open = Boolean(expandedVariables[name]);
        details.addEventListener('toggle', function () {
          if (details.open) expandedVariables[name] = true;
          else delete expandedVariables[name];
        });
        if (changed.indexOf(name) !== -1)
          details.classList.add('editor-runtime-variable-changed');
        var summary = document.createElement('summary');
        summary.textContent =
          name +
          ' · ' +
          (visible[name] === null ? 'null' : typeof visible[name]);
        details.appendChild(summary);
        var value = document.createElement('pre');
        value.textContent = JSON.stringify(visible[name], null, 2);
        details.appendChild(value);
        target.appendChild(details);
      });
    }

    function renderQuestion(target) {
      if (!question) {
        target.innerHTML =
          '<p class="text-muted small mb-0">The current screen will appear here.</p>';
        return;
      }
      var heading = document.createElement('h3');
      heading.className = 'h6 mb-1';
      heading.textContent = questionLabel(question);
      target.appendChild(heading);
      var meta = document.createElement('p');
      meta.className = 'editor-tiny text-muted mb-2';
      meta.textContent =
        (question.questionName || 'No stable question name') +
        ' · ' +
        (question.questionType || question.type || 'unknown') +
        ' · observed runtime';
      target.appendChild(meta);
      var undefinedName = question.undefinedVariable || question.undefined;
      if (undefinedName) {
        var undefinedEl = document.createElement('p');
        undefinedEl.className = 'small mb-2';
        undefinedEl.textContent =
          'Undefined variable: ' + String(undefinedName);
        target.appendChild(undefinedEl);
      }
      var sourceBlock = findQuestionSource(question, getBlocks());
      if (sourceBlock) {
        var source = document.createElement('button');
        source.type = 'button';
        source.className = 'btn btn-sm btn-outline-secondary';
        source.textContent = 'Open source block';
        source.addEventListener('click', function () {
          onOpenSource(sourceBlock.id);
        });
        target.appendChild(source);
      } else {
        var mapping = document.createElement('p');
        mapping.className = 'editor-tiny text-muted mb-0';
        mapping.textContent = 'No confident source-block match is available.';
        target.appendChild(mapping);
      }
    }

    function renderSteps(target) {
      if (!steps.length) {
        target.innerHTML =
          '<p class="text-muted small mb-0">Visited screens and changed answers will be recorded here.</p>';
        return;
      }
      var list = document.createElement('ol');
      list.className = 'editor-runtime-steps';
      steps.forEach(function (step, index) {
        var item = document.createElement('li');
        if (index === steps.length - 1) item.className = 'is-current';
        var label = document.createElement('div');
        label.className = 'editor-runtime-step-label';
        label.textContent = step.label;
        item.appendChild(label);
        var meta = document.createElement('div');
        meta.className = 'editor-tiny text-muted';
        meta.textContent = blockIdLabel(step.questionName, step.questionType);
        item.appendChild(meta);
        if (step.answers && step.answers.length) {
          var answers = document.createElement('ul');
          answers.className = 'editor-runtime-step-answers';
          step.answers.forEach(function (answer) {
            var answerItem = document.createElement('li');
            answerItem.textContent =
              answer.name + ': ' + variablePreview(answer.value);
            answers.appendChild(answerItem);
          });
          item.appendChild(answers);
        }
        list.appendChild(item);
      });
      target.appendChild(list);
      target.scrollTop = target.scrollHeight;
    }

    function makeButton(label, className, handler) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = className;
      button.textContent = label;
      button.disabled = busy;
      button.addEventListener('click', handler);
      return button;
    }

    function refreshRenderedDebugger(wrapper) {
      var statusNode = wrapper.querySelector('#runtime-status');
      statusNode.textContent =
        error ||
        status ||
        'The debugger is synchronized with this test session.';
      statusNode.classList.toggle('alert-danger', Boolean(error));
      statusNode.classList.toggle('alert-info', !error);
      wrapper
        .querySelectorAll('#runtime-session-actions button')
        .forEach(function (button) {
          button.disabled = busy;
        });

      // Polling calls this every second (see startPolling). Rebuilding a
      // panel that has not actually changed destroys and recreates its
      // elements for nothing — which, mid double-click, makes the browser's
      // word-selection lose its anchor node and fall back to selecting the
      // nearest surviving ancestor (the whole step, label included) instead
      // of just the word that was clicked. Skipping the rebuild when the
      // observed data is unchanged avoids that, along with the flicker.
      var questionTarget = wrapper.querySelector('#runtime-question');
      var questionKey = JSON.stringify(question);
      if (questionKey !== lastRenderedQuestionKey) {
        lastRenderedQuestionKey = questionKey;
        questionTarget.innerHTML = '';
        renderQuestion(questionTarget);
      }
      var stepTarget = wrapper.querySelector('#runtime-step-list');
      var stepsKey = JSON.stringify(steps);
      if (stepsKey !== lastRenderedStepsKey) {
        lastRenderedStepsKey = stepsKey;
        var previousScrollTop = stepTarget.scrollTop;
        var wasAtBottom =
          stepTarget.scrollHeight -
            stepTarget.scrollTop -
            stepTarget.clientHeight <
          24;
        stepTarget.innerHTML = '';
        renderSteps(stepTarget);
        // Keep a user's scroll position instead of forcing them back to the
        // newest step on every refresh. New sessions and users already at
        // the bottom still follow the latest step.
        if (!wasAtBottom) stepTarget.scrollTop = previousScrollTop;
      }
      wrapper.querySelector('#runtime-step-count').textContent = String(
        steps.length,
      );
      wrapper.querySelector('#runtime-variable-count').textContent = String(
        Object.keys(variables).length,
      );
      var variableTarget = wrapper.querySelector('#runtime-variable-list');
      variableTarget.innerHTML = '';
      variableTarget.className = '';
      appendVariableRows(variableTarget);
      wrapper.querySelector('#runtime-include-internal').checked =
        includeInternal;
    }

    // Editor.js owns the canvas this panel draws into, so an internal re-render
    // that arrives after the developer left the debugger would paint over
    // whatever replaced it.
    function show(target) {
      hidden = false;
      container = target || container;
      if (session) startPolling();
      render(container);
    }

    function render(target) {
      container = target || container;
      if (!container || hidden) return;
      // Never replace or detach a live iframe merely to update observations.
      // Removing it can destroy its browsing context in some browsers.
      var liveFrame =
        session && container.querySelector
          ? container.querySelector('#runtime-interview-frame')
          : null;
      if (liveFrame) {
        refreshRenderedDebugger(liveFrame.closest('.editor-runtime-inspector'));
        return;
      }
      container.innerHTML = '';

      var wrapper = document.createElement('section');
      wrapper.className = 'editor-runtime-inspector';
      wrapper.setAttribute('aria-labelledby', 'runtime-inspector-title');
      wrapper.innerHTML =
        '<header class="editor-runtime-header">' +
        '<div><div class="d-flex align-items-center gap-2"><h2 class="h4 mb-0" id="runtime-inspector-title">Debug interview</h2>' +
        '<span class="badge text-bg-success ' +
        (session ? '' : 'd-none') +
        '">Live test session</span></div>' +
        '<p class="text-muted small mb-0">Run the real interview while Weaver follows its screens, answers, and variables.</p></div>' +
        '<div class="d-flex flex-wrap gap-2" id="runtime-session-actions"></div>' +
        '</header>' +
        '<div class="alert py-2 mb-0 ' +
        (error ? 'alert-danger' : 'alert-info') +
        '" id="runtime-status" role="status" aria-live="polite"></div>' +
        '<div id="runtime-session-content"></div>';
      container.appendChild(wrapper);
      wrapper.querySelector('#runtime-status').textContent =
        error ||
        status ||
        (session
          ? 'The debugger is synchronized with this test session.'
          : 'Start a test session. It is separate from every end-user interview.');
      var actions = wrapper.querySelector('#runtime-session-actions');
      var content = wrapper.querySelector('#runtime-session-content');
      // Going back to the editor keeps the test session alive but tears down
      // this panel, so stop polling for observations nothing is displaying.
      // Reopening the debugger re-renders and starts it again.
      actions.appendChild(
        makeButton(
          'Back to editor',
          'btn btn-sm btn-outline-secondary',
          function () {
            hidden = true;
            stopPolling();
            onClose();
          },
        ),
      );

      if (!session) {
        actions.appendChild(
          makeButton('Start debugging', 'btn btn-sm btn-primary', startSession),
        );
        content.innerHTML =
          '<div class="editor-runtime-empty">' +
          '<i class="fa-solid fa-bug" aria-hidden="true"></i>' +
          '<h3 class="h5">See what your interview is doing</h3>' +
          '<p class="text-muted">Weaver opens a fresh test session here and records each screen you visit. Your regular interview sessions are untouched.</p>' +
          '</div>';
        return;
      }

      var open = document.createElement('a');
      open.className = 'btn btn-sm btn-outline-secondary';
      open.textContent = 'Open in new tab';
      open.target = '_blank';
      open.rel = 'noopener';
      open.href = session.target_url;
      actions.appendChild(open);
      actions.appendChild(
        makeButton('Refresh', 'btn btn-sm btn-outline-secondary', function () {
          observeRuntime('Runtime facts refreshed.');
        }),
      );
      actions.appendChild(
        makeButton(
          'Back one screen',
          'btn btn-sm btn-outline-secondary',
          goBack,
        ),
      );
      actions.appendChild(
        makeButton('Restart', 'btn btn-sm btn-outline-secondary', function () {
          endSession().then(function () {
            if (!session) startSession();
          });
        }),
      );
      actions.appendChild(
        makeButton('End', 'btn btn-sm btn-outline-danger', endSession),
      );

      content.innerHTML =
        '<div class="editor-runtime-workbench">' +
        '<aside class="editor-runtime-sidebar" aria-label="Interview debugging details">' +
        '<details class="editor-runtime-panel" open><summary>Current screen</summary><div id="runtime-question" class="editor-runtime-panel-body"></div></details>' +
        '<details class="editor-runtime-panel" open><summary>Step recorder <span class="badge text-bg-secondary" id="runtime-step-count"></span></summary><div id="runtime-step-list" class="editor-runtime-panel-body editor-runtime-step-list"></div></details>' +
        '<details class="editor-runtime-panel" open><summary>Session variables <span class="badge text-bg-secondary" id="runtime-variable-count"></span></summary>' +
        '<div class="editor-runtime-panel-body"><div class="d-flex gap-2 mb-2">' +
        '<label for="runtime-variable-search" class="visually-hidden">Search variables</label>' +
        '<input id="runtime-variable-search" class="form-control form-control-sm" type="search" placeholder="Filter variables">' +
        '</div><label class="form-check editor-tiny mb-2"><input class="form-check-input" type="checkbox" id="runtime-include-internal"> <span class="form-check-label">Show _internal data</span></label>' +
        '<div id="runtime-variable-list"></div></div></details>' +
        '<details class="editor-runtime-panel"><summary>Test scenario</summary><div class="editor-runtime-panel-body">' +
        '<p class="editor-tiny text-muted">Seed variables for a test path. This fixture can bypass earlier screens.</p>' +
        '<label for="runtime-scenario" class="form-label editor-tiny">Scenario YAML</label>' +
        '<textarea id="runtime-scenario" class="form-control form-control-sm font-monospace" rows="7"></textarea>' +
        '<button type="button" class="btn btn-sm btn-outline-primary mt-2" id="runtime-apply-scenario">Apply and reload</button>' +
        '</div></details>' +
        '</aside>' +
        '<div class="editor-runtime-interview"><div class="editor-runtime-frame-bar"><span><i class="fa-solid fa-display me-1" aria-hidden="true"></i>Live interview</span><span class="editor-tiny text-muted">Actions here are recorded automatically</span></div><div id="runtime-frame-host"></div></div>' +
        '</div>';

      renderQuestion(content.querySelector('#runtime-question'));
      renderSteps(content.querySelector('#runtime-step-list'));
      content.querySelector('#runtime-step-count').textContent = String(
        steps.length,
      );
      content.querySelector('#runtime-variable-count').textContent = String(
        Object.keys(variables).length,
      );
      appendVariableRows(content.querySelector('#runtime-variable-list'));

      var internalToggle = /** @type {HTMLInputElement} */ (
        content.querySelector('#runtime-include-internal')
      );
      internalToggle.checked = includeInternal;
      internalToggle.addEventListener('change', function () {
        includeInternal = internalToggle.checked;
        hasVariableSnapshot = false;
        observeRuntime('Variable visibility updated.');
      });
      var search = /** @type {HTMLInputElement} */ (
        content.querySelector('#runtime-variable-search')
      );
      search.value = variableQuery;
      search.addEventListener('input', function () {
        variableQuery = search.value;
        var list = content.querySelector('#runtime-variable-list');
        list.innerHTML = '';
        appendVariableRows(list);
      });
      var scenario = /** @type {HTMLTextAreaElement} */ (
        content.querySelector('#runtime-scenario')
      );
      scenario.value = scenarioText;
      scenario.addEventListener('input', function () {
        scenarioText = scenario.value;
      });
      content
        .querySelector('#runtime-apply-scenario')
        .addEventListener('click', function () {
          applyScenario(scenario.value);
        });

      var frame = document.createElement('iframe');
      frame.id = 'runtime-interview-frame';
      frame.className = 'editor-runtime-frame';
      frame.title = 'Live Docassemble test interview';
      frame.src = session.target_url;
      frame.addEventListener('load', function () {
        if (session)
          observeRuntime('Interview advanced; debugger synchronized.');
      });
      content.querySelector('#runtime-frame-host').appendChild(frame);
    }

    return {
      render: show,
      refreshAll: observeRuntime,
      getSession: function () {
        return clone(session);
      },
      releaseSession: releaseSession,
      setSession: function (value) {
        session = clone(value);
        resetObservedState();
        onSessionChange(clone(session));
      },
    };
  }

  return {
    createRuntimeInspector: createRuntimeInspector,
    filterVariables: filterVariables,
    changedVariableNames: changedVariableNames,
    findQuestionSource: findQuestionSource,
    questionLabel: questionLabel,
    questionIdentity: questionIdentity,
    blockIdLabel: blockIdLabel,
    variablePreview: variablePreview,
    updateStepHistory: updateStepHistory,
  };
});
