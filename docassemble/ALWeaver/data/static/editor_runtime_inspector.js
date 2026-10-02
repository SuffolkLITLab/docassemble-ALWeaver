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

  // Configuration documented in AssemblyLine/magic_variables, plus defaults
  // in al_settings, al_visual, al_language, and saved-session configuration.
  // Keep interview answers and document bundles, including custom al_* names.
  var configurationNames = new Set([
    'AL_ORGANIZATION_TITLE',
    'AL_ORGANIZATION_HOMEPAGE',
    'AL_DEFAULT_COUNTRY',
    'AL_DEFAULT_STATE',
    'AL_DEFAULT_LANGUAGE',
    'AL_DEFAULT_OVERFLOW_MESSAGE',
    'MAIN_METADATA',
    'ORIGINAL_FORMS',
    'interview_metadata',
    'addresses_to_search',
    'allowed_courts',
    'signature_fields',
    'al_logo',
    'al_app_name',
    'al_form_requires_digital_signature',
    'al_typed_signature_prefix',
    'al_typed_signature_font',
    'al_form_type',
    'al_person_answering',
    'github_repo_name',
    'github_user',
    'github_about_repo_name',
    'github_about_user',
    'github_url',
    'package_name',
    'package_title',
    'package_version_number',
    'package_version',
    'al_version',
    'metadata_title',
    'interview_short_title',
    'enable_al_language',
    'al_user_default_language',
    'al_interview_languages',
    'al_user_language',
    'al_change_language',
    'al_get_language_list_change_language',
    'session_local',
    'speak_text',
    'multi_user',
    'allow_cron',
    'nav',
    'menu_items',
    'al_menu_items',
    'al_menu_items_custom_items',
    'al_menu_items_default_items',
    'enable_al_nav_sections',
    'al_nav_sections',
    'feedback_form',
    'form_approved_for_email_filing',
    'update_answer_title',
    'send_icon',
    'al_enable_incomplete_downloads',
    'al_show_email_to_user_on_errors',
    'al_enable_error_action_feedback_link',
    'al_custom_error_options',
    'al_sessions_additional_variables_to_filter',
    'al_session_store_default_filename',
    'al_sessions_interview_title',
    'al_terms_of_use',
    'al_name_suffixes',
    'al_name_titles',
    'al_start_over_string',
    'al_start_over_confirmation_question',
    'al_start_over_confirmation_subquestion',
    'al_exit_logout_string',
    'al_download_progress_string',
    'al_save_answer_set_string',
    'al_load_answer_set_string',
    'al_import_answer_set_string',
    'al_copy_button_label',
    'al_copy_button_tooltip_inert_text',
    'al_copy_button_tooltip_copied_text',
  ]);

  // Imported typing objects can become null in simplified runtime snapshots.
  // Recognize their exact names rather than hiding arbitrary capitalized answers.
  var importedTypeNames = new Set([
    'AbstractSet',
    'Annotated',
    'Any',
    'AnyStr',
    'AsyncContextManager',
    'AsyncGenerator',
    'AsyncIterable',
    'AsyncIterator',
    'Awaitable',
    'BinaryIO',
    'ByteString',
    'Callable',
    'ChainMap',
    'ClassVar',
    'Collection',
    'Concatenate',
    'Container',
    'ContextManager',
    'Coroutine',
    'Counter',
    'DefaultDict',
    'Deque',
    'Dict',
    'Final',
    'ForwardRef',
    'FrozenSet',
    'Generator',
    'Generic',
    'Hashable',
    'IO',
    'ItemsView',
    'Iterable',
    'Iterator',
    'KeysView',
    'List',
    'Literal',
    'LiteralString',
    'Mapping',
    'MappingView',
    'Match',
    'MutableMapping',
    'MutableSequence',
    'MutableSet',
    'NamedTuple',
    'Never',
    'NewType',
    'NoDefault',
    'NoReturn',
    'NotRequired',
    'Optional',
    'OrderedDict',
    'ParamSpec',
    'ParamSpecArgs',
    'ParamSpecKwargs',
    'Pattern',
    'Protocol',
    'ReadOnly',
    'Required',
    'Reversible',
    'Self',
    'Sequence',
    'Set',
    'Sized',
    'SupportsAbs',
    'SupportsBytes',
    'SupportsComplex',
    'SupportsFloat',
    'SupportsIndex',
    'SupportsInt',
    'SupportsRound',
    'Text',
    'TextIO',
    'Tuple',
    'Type',
    'TypeAlias',
    'TypeAliasType',
    'TypedDict',
    'TypeGuard',
    'TypeIs',
    'TypeVar',
    'TypeVarTuple',
    'Union',
    'Unpack',
    'ValuesView',
  ]);

  function isInternalVariable(name) {
    var rootName = name.split(/[.[]/, 1)[0];
    return (
      configurationNames.has(rootName) ||
      importedTypeNames.has(rootName) ||
      /^(?:_internal|_?alkiln(?:_|$)|ALKILN(?:_|$))/.test(rootName)
    );
  }

  function isNestedValue(value) {
    return value !== null && typeof value === 'object';
  }

  function simpleValue(value) {
    if (value === null || value === undefined) return 'None';
    if (typeof value === 'boolean') return value ? 'True' : 'False';
    return value === '' ? '""' : String(value);
  }

  function pythonValue(value, pretty) {
    var serialized = JSON.stringify(value, null, pretty ? 2 : undefined);
    if (serialized === undefined) return 'None';
    // Match complete quoted strings first, so strings/keys containing words
    // like "true" and "null" stay intact. The input is valid serialized JSON.
    return serialized.replace(
      /"(?:\\.|[^"\\])*"|true|false|null/g,
      function (token) {
        return { true: 'True', false: 'False', null: 'None' }[token] || token;
      },
    );
  }

  function checkboxValues(value) {
    if (!isNestedValue(value) || Array.isArray(value)) return null;
    var choices = value;
    if (Object.prototype.hasOwnProperty.call(value, '_class')) {
      if (
        typeof value._class !== 'string' ||
        !/(?:^|\.)DADict$/.test(value._class)
      )
        return null;
      choices = value.elements;
    }
    if (!isNestedValue(choices) || Array.isArray(choices)) return null;
    var names = Object.keys(choices);
    return names.length &&
      names.every(function (name) {
        return typeof choices[name] === 'boolean';
      })
      ? choices
      : null;
  }

  function variableType(value) {
    if (checkboxValues(value)) return 'checkboxes';
    if (value === null || value === undefined) return 'NoneType';
    if (typeof value === 'boolean') return 'bool';
    if (typeof value === 'string') return 'str';
    if (Array.isArray(value)) return 'list';
    if (isNestedValue(value))
      return typeof value._class === 'string'
        ? value._class.split('.').pop()
        : 'dict';
    return typeof value;
  }

  function filterVariables(variables, query, includeInternal) {
    var needle = String(query || '')
      .trim()
      .toLowerCase();
    var result = {};
    Object.keys(variables || {})
      .sort()
      .forEach(function (name) {
        if (
          (includeInternal || !isInternalVariable(name)) &&
          (!needle || name.toLowerCase().indexOf(needle) !== -1)
        )
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
      var choices = checkboxValues(value);
      if (choices) {
        var checked = Object.keys(choices).filter(function (name) {
          return choices[name];
        });
        serialized = checked.length
          ? 'Checked: ' + checked.join(', ')
          : 'None checked';
      } else serialized = pythonValue(value);
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
    seededVariables,
  ) {
    var result = clone(history || []);
    var latest = result.length ? result[result.length - 1] : null;
    seededVariables = seededVariables || [];
    if (latest && nextChanged.length) {
      latest.answers = nextChanged.map(function (name) {
        return {
          name: name,
          value: clone(nextVariables[name]),
          provenance:
            seededVariables.indexOf(name) !== -1
              ? 'scenario_seeded'
              : 'observed_runtime',
        };
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
    var onSaveAsKilnTest = options.onSaveAsKilnTest || function () {};
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
    var seededVariables = [];
    var changed = [];
    var hasVariableSnapshot = false;
    var steps = [];
    var includeInternal = false;
    var sidebarCollapsed = false;
    var variableQuery = '';
    // Polling refreshes the variable list (see startPolling), so
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
    var pollDelay = 5000;
    var hidden = true;
    var fakeFiller = null;
    var restoredContext = '';
    var restoring = false;

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
      seededVariables = [];
      changed = [];
      hasVariableSnapshot = false;
      steps = [];
      expandedVariables = {};
      lastRenderedQuestionKey = null;
      lastRenderedStepsKey = null;
    }

    function stopPolling() {
      if (pollTimer !== null) {
        window.clearTimeout(pollTimer);
        pollTimer = null;
      }
    }

    // The editor owns navigation, so leaving the debugger does not always go
    // through the panel's own Back button. Make hiding a public lifecycle
    // operation: it also prevents an observation that was already in flight
    // from rendering over the view that replaced the debugger.
    function hide() {
      if (fakeFiller) fakeFiller.dispose();
      fakeFiller = null;
      hidden = true;
      stopPolling();
      container = null;
      if (typeof document !== 'undefined')
        document.removeEventListener('visibilitychange', visibilityChanged);
    }

    function pageHidden() {
      return typeof document !== 'undefined' && document.hidden;
    }

    function visibilityChanged() {
      if (pageHidden()) stopPolling();
      else {
        pollDelay = 5000;
        observeRuntime();
      }
    }

    function startPolling() {
      stopPolling();
      if (hidden || pageHidden() || !session || observing) return;
      // Wait *after* completion: a slow server must not acquire a backlog.
      // Spread a classroom's timers out and back off when nothing changes.
      pollTimer = window.setTimeout(
        function () {
          pollTimer = null;
          if (busy) startPolling();
          else observeRuntime();
        },
        // eslint-disable-next-line sonarjs/pseudo-random -- Timer jitter only; no security token.
        Math.round(pollDelay * (0.9 + Math.random() * 0.2)),
      );
    }

    function recordObservation(
      nextQuestion,
      nextVariables,
      nextChanged,
      nextSeededVariables,
    ) {
      steps = updateStepHistory(
        steps,
        nextQuestion,
        nextVariables,
        nextChanged,
        nextSeededVariables,
      );
    }

    function startSession() {
      var context = getContext();
      busy = true;
      return Promise.resolve(beforeStart())
        .then(function (proceed) {
          if (proceed === false) return undefined;
          // beforeStart can take a while (loading modules, a restart prompt),
          // and the user may have left the debugger in the meantime. Starting
          // a Docassemble session now would leave an orphan behind.
          if (hidden) return undefined;
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
              // The user can leave while the POST is in flight. By now the
              // server record is real, so hand it back rather than stranding
              // a test session no visible debugger owns.
              if (hidden) return releaseSession();
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
          setStatus('The debug interview and its saved data were deleted.');
        })
        .catch(function (requestError) {
          if (requestError.code === 'runtime_session_not_found') {
            session = null;
            resetObservedState();
            onSessionChange(null);
            setStatus('The debug session has already ended.');
            return;
          }
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
        // Server housekeeping retries deletion if this request cannot finish.
        // Context changes should not be blocked by a temporary network failure.
      });
    }

    function observeRuntime(successMessage) {
      if (!session || hidden || pageHidden()) return Promise.resolve();
      if (observing) {
        observeAgain = true;
        return observationPromise || Promise.resolve();
      }
      stopPolling();
      observing = true;
      var observedSession = session.weaver_session_id;
      var snapshotPath =
        sessionPath('/snapshot') +
        (includeInternal ? '?include_internal=true' : '');
      observationPromise = api
        .get(snapshotPath)
        .then(function (response) {
          if (!session || session.weaver_session_id !== observedSession) return;
          var variableData = response.data || {};
          var nextQuestion = clone(variableData.question || {});
          var nextVariables = clone(variableData.variables || {});
          var nextSeededVariables = Array.isArray(variableData.seeded_variables)
            ? variableData.seeded_variables.map(String)
            : [];
          var nextChanged = hasVariableSnapshot
            ? changedVariableNames(variables, nextVariables)
            : [];
          var unchanged =
            hasVariableSnapshot &&
            !nextChanged.length &&
            JSON.stringify(question) === JSON.stringify(nextQuestion) &&
            JSON.stringify(seededVariables) ===
              JSON.stringify(nextSeededVariables);
          pollDelay = unchanged ? Math.min(pollDelay * 1.5, 10000) : 5000;
          recordObservation(
            nextQuestion,
            nextVariables,
            nextChanged,
            nextSeededVariables,
          );
          question = nextQuestion;
          variables = nextVariables;
          seededVariables = nextSeededVariables;
          changed = nextChanged;
          hasVariableSnapshot = true;
          setStatus(
            successMessage || 'Debugger synchronized with the interview.',
          );
        })
        .catch(function (requestError) {
          if (!session || session.weaver_session_id !== observedSession) return;
          if (requestError.code === 'runtime_session_not_found') {
            stopPolling();
            session = null;
            resetObservedState();
            onSessionChange(null);
            setStatus(
              requestError.message ||
                'The idle debug session was closed. Start a new test session.',
              true,
            );
            return;
          }
          pollDelay = Math.min(pollDelay * 2, 30000);
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
            observeRuntime();
          } else startPolling();
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

    function rememberVariableExpansion(target) {
      // The native toggle event is queued. Capture the actual DOM state before
      // replacing rows, including a click immediately followed by a refresh.
      target
        .querySelectorAll('details[data-variable]')
        .forEach(function (details) {
          var name = details.getAttribute('data-variable');
          if (/** @type {HTMLDetailsElement} */ (details).open)
            expandedVariables[name] = true;
          else delete expandedVariables[name];
        });
    }

    function appendVariableRows(target) {
      var visible = filterVariables(variables, variableQuery, includeInternal);
      var names = Object.keys(visible);
      if (!names.length) {
        target.textContent = hasVariableSnapshot
          ? 'No matching variables.'
          : 'Variables will appear after the session starts.';
        target.className = 'text-muted small';
        return;
      }
      names.forEach(function (name) {
        var choices = checkboxValues(visible[name]);
        var nested = isNestedValue(visible[name]);
        var details = /** @type {HTMLDetailsElement} */ (
          document.createElement(nested ? 'details' : 'div')
        );
        details.className = 'editor-runtime-variable';
        if (nested) {
          details.setAttribute('data-variable', name);
          details.open = Boolean(expandedVariables[name]);
          details.addEventListener('toggle', function () {
            if (details.open) expandedVariables[name] = true;
            else delete expandedVariables[name];
          });
        } else details.classList.add('editor-runtime-variable-simple');
        if (changed.indexOf(name) !== -1)
          details.classList.add('editor-runtime-variable-changed');
        var summary = document.createElement(nested ? 'summary' : 'div');
        var preview;
        summary.textContent = name + ' · ' + variableType(visible[name]);
        if (choices) {
          var checked = Object.keys(choices).filter(function (choice) {
            return choices[choice];
          });
          summary.textContent += ' · ' + checked.length + ' checked';
          preview = document.createElement('ul');
          preview.className = 'editor-runtime-checkbox-preview';
          Object.keys(choices).forEach(function (choice) {
            var item = document.createElement('li');
            var label = document.createElement('label');
            var checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = choices[choice];
            checkbox.disabled = true;
            var text = document.createElement('span');
            text.textContent = choice;
            label.appendChild(checkbox);
            label.appendChild(text);
            item.appendChild(label);
            preview.appendChild(item);
          });
        }
        if (seededVariables.indexOf(name) !== -1) {
          summary.textContent += ' · scenario seed (bypassed history)';
          summary.setAttribute(
            'aria-label',
            name + ', scenario seeded value, may bypass interview history',
          );
          summary.classList.add('editor-runtime-variable-seeded');
        }
        details.appendChild(summary);
        if (choices) details.appendChild(preview);
        else {
          var value = document.createElement('pre');
          value.textContent = nested
            ? pythonValue(visible[name], true)
            : simpleValue(visible[name]);
          details.appendChild(value);
        }
        target.appendChild(details);
      });
    }

    function renderQuestion(target) {
      if (seededVariables.length) {
        target.innerHTML =
          '<p class="alert alert-warning py-2 small" role="note">' +
          'Scenario-seeded values are marked below. They may bypass earlier interview history and are not answers observed from an end user.' +
          '</p>';
      }
      if (!question) {
        target.innerHTML +=
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
              answer.name +
              (answer.provenance === 'scenario_seeded'
                ? ' (scenario seed; bypassed history): '
                : ': ') +
              variablePreview(answer.value);
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
      var saveTestButton = wrapper.querySelector('#runtime-save-kiln-test');
      if (saveTestButton) {
        saveTestButton.disabled =
          busy || !hasVariableSnapshot || seededVariables.length > 0;
        saveTestButton.title = seededVariables.length
          ? 'Clear scenario-seeded state and answer the interview before saving observed answers as a Kiln test.'
          : '';
      }

      // Polling calls this after each observation. Rebuilding a
      // panel that has not actually changed destroys and recreates its
      // elements for nothing — which, mid double-click, makes the browser's
      // word-selection lose its anchor node and fall back to selecting the
      // nearest surviving ancestor (the whole step, label included) instead
      // of just the word that was clicked. Skipping the rebuild when the
      // observed data is unchanged avoids that, along with the flicker.
      var questionTarget = wrapper.querySelector('#runtime-question');
      var questionKey = JSON.stringify({
        question: question,
        seededVariables: seededVariables,
      });
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
        Object.keys(filterVariables(variables, variableQuery, includeInternal))
          .length,
      );
      var variableTarget = wrapper.querySelector('#runtime-variable-list');
      rememberVariableExpansion(variableTarget);
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
      if (typeof document !== 'undefined')
        document.addEventListener('visibilitychange', visibilityChanged);
      container = target || container;
      if (session) startPolling();
      render(container);
      var context = getContext();
      var contextKey = JSON.stringify([context.project, context.filename]);
      if (!session && !restoring && restoredContext !== contextKey) {
        restoring = true;
        restoredContext = contextKey;
        busy = true;
        setStatus('Checking for an open debug session...');
        render(container);
        api
          .get(
            '/api/runtime/sessions?project=' +
              encodeURIComponent(context.project) +
              '&filename=' +
              encodeURIComponent(context.filename),
          )
          .then(function (response) {
            if (
              hidden ||
              contextKey !==
                JSON.stringify([getContext().project, getContext().filename])
            ) {
              restoredContext = '';
              return;
            }
            if (response.data && response.data.session) {
              session = clone(response.data.session);
              resetObservedState();
              onSessionChange(clone(session));
              setStatus('Reconnected to your open debug session.');
              render(container);
              return observeRuntime();
            }
            setStatus(
              'Start a test session. Idle debug sessions close after 30 minutes without advancing a screen.',
            );
          })
          .catch(function (requestError) {
            if (!hidden)
              setStatus(
                requestError.message ||
                  'Unable to reconnect to the debug session. Try again.',
                true,
              );
            restoredContext = '';
          })
          .finally(function () {
            restoring = false;
            busy = false;
            render(container);
          });
      }
    }

    function attachFakeFiller(frame, wrapper) {
      if (fakeFiller) fakeFiller.dispose();
      fakeFiller = globalThis.ALWeaverFakeFiller.createController(
        frame,
        wrapper.querySelector('#runtime-fill-samples'),
        function (message) {
          setStatus(message, false);
          if (!hidden) refreshRenderedDebugger(wrapper);
        },
      );
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
        var liveWrapper = liveFrame.closest('.editor-runtime-inspector');
        if (!fakeFiller) attachFakeFiller(liveFrame, liveWrapper);
        refreshRenderedDebugger(liveWrapper);
        return;
      }
      if (fakeFiller) fakeFiller.dispose();
      fakeFiller = null;
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
            hide();
            onClose();
          },
        ),
      );

      actions.appendChild(
        makeButton(
          'Clean up old sessions',
          'btn btn-sm btn-outline-secondary',
          function () {
            busy = true;
            render(container);
            api
              .post('/api/runtime/sessions/cleanup', {})
              .then(function (response) {
                setStatus(
                  'Cleaned up ' +
                    response.data.deleted +
                    ' old debug sessions.',
                );
                if (session) return observeRuntime();
              })
              .catch(function (requestError) {
                setStatus(
                  requestError.message || 'Unable to clean up debug sessions.',
                  true,
                );
              })
              .finally(function () {
                busy = false;
                render(container);
              });
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
      var saveTest = makeButton(
        'Save as Kiln test',
        'btn btn-sm btn-outline-primary',
        function () {
          var questionName = String(
            (question || {}).questionName || 'review_screen',
          );
          onSaveAsKilnTest({
            variables: clone(variables),
            questionId:
              questionName.indexOf('ID ') === 0
                ? questionName.slice(3)
                : questionName,
          });
        },
      );
      saveTest.id = 'runtime-save-kiln-test';
      saveTest.disabled =
        busy || !hasVariableSnapshot || seededVariables.length > 0;
      if (seededVariables.length) {
        saveTest.title =
          'Clear scenario-seeded state and answer the interview before saving observed answers as a Kiln test.';
      }
      actions.appendChild(saveTest);
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
        '<aside id="runtime-sidebar" class="editor-runtime-sidebar" aria-label="Interview debugging details">' +
        '<details class="editor-runtime-panel" open><summary>Current screen</summary><div id="runtime-question" class="editor-runtime-panel-body"></div></details>' +
        '<details class="editor-runtime-panel" open><summary>Step recorder <span class="badge text-bg-secondary" id="runtime-step-count"></span></summary><div id="runtime-step-list" class="editor-runtime-panel-body editor-runtime-step-list"></div></details>' +
        '<details class="editor-runtime-panel" open><summary>Session variables <span class="badge text-bg-secondary" id="runtime-variable-count"></span></summary>' +
        '<div class="editor-runtime-panel-body"><div class="d-flex gap-2 mb-2">' +
        '<label for="runtime-variable-search" class="visually-hidden">Search variables</label>' +
        '<input id="runtime-variable-search" class="form-control form-control-sm" type="search" placeholder="Filter variables">' +
        '</div><label class="form-check editor-tiny mb-2"><input class="form-check-input" type="checkbox" id="runtime-include-internal"> <span class="form-check-label">Show internal data</span></label>' +
        '<div id="runtime-variable-list"></div></div></details>' +
        '<details class="editor-runtime-panel"><summary>Test scenario</summary><div class="editor-runtime-panel-body">' +
        '<p class="editor-tiny text-muted">Seed variables for a test path. This fixture can bypass earlier screens.</p>' +
        '<label for="runtime-scenario" class="form-label editor-tiny">Scenario YAML</label>' +
        '<textarea id="runtime-scenario" class="form-control form-control-sm font-monospace" rows="7"></textarea>' +
        '<button type="button" class="btn btn-sm btn-outline-primary mt-2" id="runtime-apply-scenario">Apply and reload</button>' +
        '</div></details>' +
        '</aside>' +
        '<div class="editor-runtime-interview"><div class="editor-runtime-frame-bar"><span><i class="fa-solid fa-display me-1" aria-hidden="true"></i>Live interview</span><div class="d-flex gap-2"><button type="button" class="btn btn-sm btn-outline-secondary" id="runtime-toggle-sidebar" aria-controls="runtime-sidebar" aria-expanded="true">Hide details</button><button type="button" class="btn btn-sm btn-outline-primary" id="runtime-fill-samples" disabled>Fill sample answers</button></div></div><div id="runtime-frame-host"></div></div>' +
        '</div>';

      var sidebarToggle = content.querySelector('#runtime-toggle-sidebar');
      function updateSidebar() {
        content
          .querySelector('.editor-runtime-workbench')
          .classList.toggle(
            'editor-runtime-sidebar-collapsed',
            sidebarCollapsed,
          );
        var sidebar = /** @type {HTMLElement} */ (
          content.querySelector('#runtime-sidebar')
        );
        sidebar.hidden = sidebarCollapsed;
        sidebarToggle.setAttribute('aria-expanded', String(!sidebarCollapsed));
        sidebarToggle.textContent = sidebarCollapsed
          ? 'Show details'
          : 'Hide details';
      }
      sidebarToggle.addEventListener('click', function () {
        sidebarCollapsed = !sidebarCollapsed;
        updateSidebar();
      });
      updateSidebar();
      renderQuestion(content.querySelector('#runtime-question'));
      renderSteps(content.querySelector('#runtime-step-list'));
      content.querySelector('#runtime-step-count').textContent = String(
        steps.length,
      );
      content.querySelector('#runtime-variable-count').textContent = String(
        Object.keys(filterVariables(variables, variableQuery, includeInternal))
          .length,
      );
      appendVariableRows(content.querySelector('#runtime-variable-list'));

      var internalToggle = /** @type {HTMLInputElement} */ (
        content.querySelector('#runtime-include-internal')
      );
      internalToggle.checked = includeInternal;
      internalToggle.addEventListener('change', function () {
        includeInternal = internalToggle.checked;
        refreshRenderedDebugger(wrapper);
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
        rememberVariableExpansion(list);
        list.innerHTML = '';
        list.className = '';
        appendVariableRows(list);
        content.querySelector('#runtime-variable-count').textContent = String(
          Object.keys(
            filterVariables(variables, variableQuery, includeInternal),
          ).length,
        );
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
      attachFakeFiller(frame, wrapper);
    }

    return {
      render: show,
      hide: hide,
      refreshAll: observeRuntime,
      getSession: function () {
        return clone(session);
      },
      releaseSession: releaseSession,
      setSession: function (value) {
        stopPolling();
        session = clone(value);
        pollDelay = 5000;
        resetObservedState();
        startPolling();
        onSessionChange(clone(session));
      },
    };
  }

  return {
    createRuntimeInspector: createRuntimeInspector,
    filterVariables: filterVariables,
    isInternalVariable: isInternalVariable,
    isNestedValue: isNestedValue,
    simpleValue: simpleValue,
    pythonValue: pythonValue,
    checkboxValues: checkboxValues,
    variableType: variableType,
    changedVariableNames: changedVariableNames,
    findQuestionSource: findQuestionSource,
    questionLabel: questionLabel,
    questionIdentity: questionIdentity,
    blockIdLabel: blockIdLabel,
    variablePreview: variablePreview,
    updateStepHistory: updateStepHistory,
  };
});
