/* Deferred server restarts for Playground Python module changes.
 *
 * Docassemble loads a module once per server process, so editing one has no
 * effect until every process restarts. The stock Playground restarts the
 * server the moment you press Save. This controller defers that: saving marks
 * the project as having pending module changes, and the restart is offered at
 * the point the developer actually runs the interview, where they are already
 * waiting on a new tab. Several module edits then cost one restart instead of
 * one each.
 *
 * Restarting is server-wide and disruptive, so the developer is told what it
 * costs and can always decline and keep working.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverModuleRestart = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var POLL_INTERVAL_MS = 3000;
  var POLL_TIMEOUT_MS = 180000;

  function describeFiles(files) {
    var names = (files || []).map(function (entry) {
      return entry && entry.filename ? String(entry.filename) : '';
    }).filter(Boolean);
    if (!names.length) return '';
    if (names.length === 1) return names[0];
    if (names.length === 2) return names[0] + ' and ' + names[1];
    return names.slice(0, -1).join(', ') + ', and ' + names[names.length - 1];
  }

  function createModuleRestartController(options) {
    options = options || {};
    var api = options.api;
    var doc = options.document;
    var win = options.window;
    var getProject = options.getProject || function () { return null; };
    var sleep = options.sleep || function (ms) {
      return new Promise(function (resolve) { win.setTimeout(resolve, ms); });
    };
    var now = options.now || function () { return Date.now(); };
    var state = null;
    var restartInFlight = null;
    // The modal is a single static element, so a second prompt opened before
    // the first is answered would double-register the button handlers.
    var promptInFlight = null;

    function el(id) {
      return doc ? doc.getElementById(id) : null;
    }

    function currentState() {
      return state;
    }

    function renderBanner() {
      var banner = el('editor-module-restart-banner');
      if (!banner) return;
      if (!state || !state.pending) {
        banner.classList.add('d-none');
        return;
      }
      var message = banner.querySelector('[data-module-restart-banner-message]');
      if (message) {
        var listed = describeFiles(state.files);
        message.textContent = listed
          ? ('Restart the server to load ' + listed + '.')
          : 'Restart the server to load them.';
      }
      var button = banner.querySelector('[data-action="restart-for-modules"]');
      if (button) {
        // A server that cannot restart itself still gets the banner, so the
        // developer knows why their module has no effect, but no button that
        // would only fail.
        button.classList.toggle('d-none', !state.restart_allowed);
      }
      banner.classList.remove('d-none');
    }

    function adopt(payload) {
      if (payload && typeof payload === 'object') state = payload;
      renderBanner();
      return state;
    }

    /* Pick up the restart_state a save response carries, so the banner appears
     * the moment a module is saved without a second round trip. */
    function noteSaveResult(data) {
      if (data && data.restart_state) adopt(data.restart_state);
      return state;
    }

    function refresh() {
      var project = getProject();
      if (!project) return Promise.resolve(state);
      return api.get('/api/server/restart-state?project=' + encodeURIComponent(project))
        .then(function (response) {
          return adopt(response && response.data);
        })
        .catch(function () {
          // The banner is advisory; a failed poll must not interrupt editing.
          return state;
        });
    }

    function setProgress(text) {
      var progress = el('module-restart-progress');
      var label = el('module-restart-progress-text');
      if (label && text) label.textContent = text;
      if (progress) progress.classList.toggle('d-none', !text);
    }

    function setError(text) {
      var alertEl = el('module-restart-error');
      if (!alertEl) return;
      alertEl.textContent = String(text || '');
      alertEl.classList.toggle('d-none', !text);
    }

    function pollUntilRestarted(taskId) {
      var deadline = now() + POLL_TIMEOUT_MS;
      function tick() {
        if (now() > deadline) {
          // The server is normally back well inside this window. Saying so is
          // more useful than spinning forever.
          return Promise.resolve(false);
        }
        return sleep(POLL_INTERVAL_MS)
          .then(function () {
            return api.get('/api/server/restart-status?task_id=' + encodeURIComponent(taskId));
          })
          .then(function (response) {
            var status = response && response.data ? response.data.status : '';
            if (status === 'completed') return true;
            return tick();
          })
          .catch(function () {
            // Requests fail while the workers are down; that is the expected
            // middle of a restart, not an error worth reporting.
            return tick();
          });
      }
      return tick();
    }

    /* Trigger a restart and resolve once the server answers again. */
    function restartNow() {
      if (restartInFlight) return restartInFlight;
      var project = getProject();
      setError('');
      setProgress('Restarting the server… this normally takes 10 to 30 seconds.');
      restartInFlight = api.post('/api/server/restart', { project: project })
        .then(function (response) {
          var taskId = response && response.data ? response.data.task_id : null;
          if (!taskId) return false;
          return pollUntilRestarted(taskId);
        })
        .then(function (completed) {
          setProgress('');
          if (completed) {
            state = null;
            renderBanner();
          } else {
            setProgress('The server is taking longer than usual to come back. It should finish shortly.');
          }
          return completed;
        })
        .catch(function (error) {
          setProgress('');
          setError((error && error.message) || 'The server could not be restarted.');
          throw error;
        })
        .finally(function () {
          restartInFlight = null;
        });
      return restartInFlight;
    }

    function openModal() {
      if (!win || !win.bootstrap || !win.bootstrap.Modal) return null;
      var node = el('module-restart-modal');
      if (!node) return null;
      return win.bootstrap.Modal.getOrCreateInstance(node);
    }

    function fillModal(actionLabel, allowSkip) {
      var list = el('module-restart-files');
      if (list) {
        list.innerHTML = '';
        (state.files || []).forEach(function (entry) {
          var item = doc.createElement('li');
          item.textContent = entry.reason && entry.reason !== 'changed'
            ? (entry.filename + ' (' + entry.reason + ')')
            : entry.filename;
          list.appendChild(item);
        });
      }
      var message = el('module-restart-message');
      if (message) {
        message.textContent = actionLabel
          ? ('Before you ' + actionLabel
            + ', note that these Python modules have changed since the server last started:')
          : 'These Python modules have changed since the server last started:';
      }
      var restartButton = doc.querySelector('[data-module-restart-choice="restart"]');
      if (restartButton) restartButton.classList.toggle('d-none', !state.restart_allowed);
      // Asked from the banner there is no pending action to continue to, so
      // the only choices are restarting and closing the dialog.
      var skipButton = doc.querySelector('[data-module-restart-choice="skip"]');
      if (skipButton) skipButton.classList.toggle('d-none', !allowSkip);
      var cancelButton = doc.querySelector('[data-module-restart-choice="cancel"]');
      if (cancelButton) cancelButton.textContent = allowSkip ? 'Cancel' : 'Not now';
      setError(state.restart_allowed ? '' : state.restart_blocked_reason);
      setProgress('');
    }

    /* Resolves true to go ahead with the action, false if the developer
     * cancelled it. */
    function promptForRestart(actionLabel, allowSkip) {
      var modal = openModal();
      if (!modal) {
        // Without Bootstrap there is no modal to show; never block the action.
        return Promise.resolve(true);
      }
      if (promptInFlight) return promptInFlight;
      fillModal(actionLabel, allowSkip !== false);
      promptInFlight = new Promise(function (resolve) {
        var buttons = Array.prototype.slice.call(
          doc.querySelectorAll('[data-module-restart-choice]')
        );

        function cleanup() {
          buttons.forEach(function (button) {
            button.removeEventListener('click', onClick);
            button.disabled = false;
          });
        }

        function finish(result) {
          cleanup();
          promptInFlight = null;
          modal.hide();
          resolve(result);
        }

        function onClick(event) {
          var choice = event.currentTarget.getAttribute('data-module-restart-choice');
          if (choice === 'cancel') return finish(false);
          if (choice === 'skip') return finish(true);
          buttons.forEach(function (button) { button.disabled = true; });
          restartNow()
            .then(function () { finish(true); })
            .catch(function () {
              // The failure is already shown in the modal; let the developer
              // decide whether to continue anyway.
              buttons.forEach(function (button) { button.disabled = false; });
            });
        }

        buttons.forEach(function (button) {
          button.addEventListener('click', onClick);
        });
        modal.show();
      });
      return promptInFlight;
    }

    /* Call before anything that runs the interview. Resolves true if the
     * caller should proceed. */
    function ensureModulesLoaded(actionLabel) {
      return refresh().then(function (current) {
        if (!current || !current.pending) return true;
        if (current.policy === 'never') return true;
        if (current.policy === 'auto' && current.restart_allowed) {
          return restartNow().then(function () { return true; }, function () { return true; });
        }
        return promptForRestart(actionLabel, true);
      });
    }

    /* The banner's own button: same dialog, but with nothing to continue to. */
    function openRestartDialog() {
      return refresh().then(function (current) {
        if (!current || !current.pending) return false;
        return promptForRestart(null, false);
      });
    }

    return {
      currentState: currentState,
      ensureModulesLoaded: ensureModulesLoaded,
      openRestartDialog: openRestartDialog,
      noteSaveResult: noteSaveResult,
      refresh: refresh,
      renderBanner: renderBanner,
      restartNow: restartNow,
    };
  }

  return {
    createModuleRestartController: createModuleRestartController,
    describeFiles: describeFiles,
  };
});
