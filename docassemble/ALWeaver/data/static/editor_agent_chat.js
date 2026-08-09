/* Editing-assistant chat panel.
 *
 * This module owns the conversation and the server-side candidate; it never
 * owns editor state. When the developer clicks Apply, the candidate source is
 * handed to editor.js, which folds it into the current unsaved buffer. No
 * intermediate agent step touches the editor or the Playground.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverAgentChat = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var STATE_LABELS = {
    idle: 'Ready',
    starting: 'Starting the assistant…',
    thinking: 'Thinking…',
    inspecting: 'Inspecting the interview…',
    editing: 'Editing the candidate…',
    validating: 'Validating…',
    testing: 'Testing in Docassemble…',
    ready: 'Ready to apply',
    no_changes: 'No changes were needed',
    failed: 'Could not produce a valid edit',
    cancelled: 'Stopped',
    stale: 'The saved file changed — restart the assistant',
    error: 'Something went wrong',
  };

  var STOP_REASON_NOTES = {
    step_limit: 'This one request needed more steps than the assistant is ' +
      'allowed to take at once. Apply what it managed, then ask for the rest ' +
      'as a smaller, separate request.',
    mutating_tool_limit: 'This one request needed more edits than the ' +
      'assistant makes at once. Apply what it managed, then ask for the rest.',
    runtime_operation_limit: 'The assistant reached its runtime-inspection limit.',
    validation_repair_limit: 'The assistant could not repair the validation errors.',
    repeated_blocking_diagnostic: 'The same validation error kept coming back.',
    malformed_model_responses: 'The assistant kept returning an unusable response.',
    repeated_invalid_arguments: 'The assistant kept sending invalid arguments.',
    unavailable_capability: 'The assistant asked for a capability it does not have.',
    unsupported_source: 'The change would need to rewrite source Weaver cannot edit safely.',
    stale_candidate: 'The candidate changed mid-request.',
    model_call_failed: 'The language model could not be reached.',
    cancelled: 'You stopped the request.',
  };

  function clone(value) {
    if (value === undefined) return undefined;
    return JSON.parse(JSON.stringify(value));
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function statusIcon(status) {
    if (status === 'success') return '✓';
    if (status === 'rejected' || status === 'error') return '⚠';
    return '·';
  }

  function createAgentChat(options) {
    options = options || {};
    var api = options.api;
    var getContext = options.getContext || function () { return {}; };
    var getWorkingSource = options.getWorkingSource;
    var onApply = options.onApply || function () {};
    var onStateChange = options.onStateChange || function () {};

    var session = null;
    var transcript = [];
    var uiState = 'idle';
    var statusMessage = '';
    var errorMessage = '';
    var latest = null;
    var busy = false;
    var container = null;
    var draft = '';
    var repairOffer = null;
    var lastRequest = '';
    // When the server says no model is configured, the panel explains that
    // instead of offering a composer that would fail on submit.
    var availability = options.getAvailability
      ? options.getAvailability()
      : { available: true, code: 'ready', message: '' };

    var liveEvents = [];
    var liveStartedAt = 0;
    var pollTimer = null;
    var tickTimer = null;

    function isAvailable() {
      return Boolean(availability && availability.available);
    }

    function turnsRemaining() {
      if (!session || typeof session.turns_remaining !== 'number') return null;
      return session.turns_remaining;
    }

    function isExhausted() {
      return turnsRemaining() === 0;
    }

    // A turn runs on the server for longer than any request can be held open,
    // so starting one only kicks it off. Everything after that — the running
    // list of steps and the final result — comes from polling this record.
    function watchTurn() {
      stopProgressWatch();
      tickTimer = setInterval(function () {
        if (busy) renderWorkingBanner();
      }, 1000);
      return new Promise(function (resolve, reject) {
        var missedPolls = 0;
        pollTimer = setInterval(function () {
          if (!busy || !session) return;
          api.get(sessionPath('/progress'), { preventStale: false })
            .then(function (response) {
              missedPolls = 0;
              var data = (response && response.data) || {};
              if (Array.isArray(data.events)) liveEvents = data.events;
              if (data.running) {
                renderWorkingBanner();
                return;
              }
              stopProgressWatch();
              if (data.error) {
                var failure = new Error(data.error.message || 'The assistant request failed.');
                failure.code = data.error.code;
                reject(failure);
                return;
              }
              if (data.result) {
                resolve(data.result);
                return;
              }
              // Not running, no result, no error: the worker went away.
              reject(new Error(
                'The assistant stopped unexpectedly. Nothing was applied — try again.'
              ));
            })
            .catch(function (pollError) {
              missedPolls += 1;
              // A dropped poll is normal; losing the record is not.
              if (missedPolls >= 5) {
                stopProgressWatch();
                reject(pollError);
              }
            });
        }, 1500);
      });
    }

    function stopProgressWatch() {
      if (pollTimer) clearInterval(pollTimer);
      if (tickTimer) clearInterval(tickTimer);
      pollTimer = null;
      tickTimer = null;
    }

    function elapsedLabel() {
      var seconds = Math.max(0, Math.round((Date.now() - liveStartedAt) / 1000));
      if (seconds < 60) return seconds + 's';
      return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's';
    }

    function currentActivity() {
      for (var index = liveEvents.length - 1; index >= 0; index--) {
        var event = liveEvents[index];
        if (event && event.type === 'status' && event.label) return event.label;
      }
      return 'Working';
    }

    // Repaint only the banner, so polling does not tear down the composer or
    // scroll the transcript out from under the developer.
    function renderWorkingBanner() {
      if (!container) return;
      var host = container.querySelector
        ? container.querySelector('.editor-agent-working')
        : null;
      if (!host) {
        render();
        return;
      }
      host.innerHTML = '';
      buildWorkingBanner(host);
    }

    function buildWorkingBanner(host) {
      var head = element('div', 'editor-agent-working-head');
      head.appendChild(element('span', 'editor-agent-spinner'));
      head.appendChild(element(
        'span',
        'editor-agent-working-label',
        currentActivity() + '…'
      ));
      head.appendChild(element('span', 'editor-agent-working-time', elapsedLabel()));
      host.appendChild(head);
      host.appendChild(element('div', 'editor-agent-working-bar'));

      var done = liveEvents.filter(function (event) {
        return event && event.type === 'tool_result';
      });
      if (!done.length) return;
      var list = element('ul', 'editor-agent-steps editor-agent-steps-live');
      done.slice(-6).forEach(function (event) {
        var item = element(
          'li',
          'editor-agent-step editor-agent-step-' + (event.status || 'info')
        );
        item.appendChild(element('span', 'editor-agent-step-icon', statusIcon(event.status)));
        item.appendChild(element('span', 'editor-agent-step-label', event.label || event.tool));
        list.appendChild(item);
      });
      host.appendChild(list);
    }

    function setState(next, message) {
      uiState = next;
      statusMessage = message || '';
      if (next !== 'error') errorMessage = '';
      onStateChange(next);
    }

    function fail(error) {
      stopProgressWatch();
      var code = error && error.code;
      if (code === 'agent_session_stale' || code === 'agent_base_revision_stale') {
        setState('stale');
        errorMessage = error.message;
      } else {
        setState('error');
        errorMessage = (error && error.message) || 'The assistant request failed.';
      }
      busy = false;
      render();
    }

    function sessionPath(suffix) {
      if (!session || !session.agent_session_id) {
        throw new Error('The assistant session has not started yet.');
      }
      return '/api/agent/sessions/' + encodeURIComponent(session.agent_session_id) +
        (suffix || '');
    }

    function ensureSession(autoHeal) {
      if (session) return Promise.resolve(session);
      var context = getContext();
      var snapshot;
      try {
        snapshot = getWorkingSource();
      } catch (error) {
        return Promise.reject(error);
      }
      setState('starting');
      render();
      return api.post('/api/agent/sessions', {
        project: context.project,
        filename: context.filename,
        raw_yaml: snapshot.raw_yaml,
        base_revision: snapshot.base_revision,
        auto_heal: Boolean(autoHeal),
      }, { preventStale: false }).then(function (response) {
        session = clone(response.data);
        repairOffer = null;
        if (session.repairs && session.repairs.length) {
          transcript.push({
            role: 'assistant',
            content: 'I fixed ' + session.repairs.length +
              (session.repairs.length === 1 ? ' problem' : ' problems') +
              ' with block ids before starting. These are part of the change you ' +
              'will review before saving.',
            status: 'ready',
            repairs: session.repairs,
            events: [],
          });
        }
        return session;
      }).catch(function (error) {
        // A file the validator rejects is not a dead end when every problem is
        // mechanical: offer the fix rather than making the developer hand-edit.
        var details = (error && error.details) || {};
        if (error && error.code === 'invalid_working_source') {
          repairOffer = {
            canAutoHeal: Boolean(details.can_auto_heal),
            repairs: details.repairs || [],
            repairableCount: Number(details.repairable_count || 0),
            unrepairableCount: Number(details.unrepairable_count || 0),
            diagnostics: details.diagnostics || [],
          };
        }
        throw error;
      });
    }

    function healAndRetry() {
      if (!repairOffer || !repairOffer.canAutoHeal || busy) return Promise.resolve();
      var pending = lastRequest;
      repairOffer = null;
      busy = true;
      setState('starting');
      render();
      return ensureSession(true).then(function () {
        busy = false;
        setState('idle');
        render();
        if (pending) return send(pending);
        return undefined;
      }).catch(function (error) {
        fail(error);
      });
    }

    function send(message) {
      var text = String(message || '').trim();
      if (!text || busy || !isAvailable() || isExhausted()) return Promise.resolve();
      busy = true;
      draft = '';
      lastRequest = text;
      transcript.push({ role: 'user', content: text });
      setState('thinking');
      // The clock starts when the developer hits send, not when the first poll
      // comes back, so the first paint already shows an honest elapsed time.
      liveEvents = [];
      liveStartedAt = Date.now();
      render();

      return ensureSession().then(function () {
        var context = getContext();
        // Kicking the turn off is the only thing this request does; the work
        // itself outlives it.
        var started = api.post(sessionPath('/turn'), {
          message: text,
          selected_block_id: context.selectedBlockId || null,
        }, { preventStale: false });
        var watching = watchTurn();
        return started.then(function () { return watching; });
      }).then(function (data) {
        latest = clone(data);
        if (data.session) session = clone(data.session);
        transcript.push({
          role: 'assistant',
          content: data.summary,
          status: data.status,
          stopReason: data.stop_reason,
          events: data.turn && data.turn.events ? data.turn.events : [],
          diagnostics: data.diagnostics || [],
          diff: data.diff || null,
        });
        setState(data.status === 'ready' ? 'ready' : data.status);
        busy = false;
        stopProgressWatch();
        render();
      }).catch(function (error) {
        stopProgressWatch();
        transcript.push({
          role: 'error',
          content: (error && error.message) || 'The assistant request failed.',
        });
        fail(error);
      });
    }

    function stop() {
      if (!session || !busy) return Promise.resolve();
      // Cancelling is safe because the loop never writes: at worst it leaves a
      // valid intermediate candidate that is not presented as finished.
      return api.post(sessionPath('/cancel'), {}, { preventStale: false })
        .catch(function () { /* the turn may already have finished */ });
    }

    function reset() {
      if (!session) {
        transcript = [];
        latest = null;
        setState('idle');
        render();
        return Promise.resolve();
      }
      busy = true;
      render();
      return api.post(sessionPath('/reset'), {}, { preventStale: false })
        .then(function (response) {
          session = clone(response.data);
          transcript = [];
          latest = null;
          busy = false;
          setState('idle', 'Conversation reset to the source the assistant started from.');
          render();
        }).catch(fail);
    }

    function apply() {
      if (!session || busy) return Promise.resolve();
      busy = true;
      setState('validating');
      render();
      return api.post(sessionPath('/apply'), {}, { preventStale: false })
        .then(function (response) {
          busy = false;
          onApply(clone(response.data));
          setState('idle', 'Applied to the editor. Use Save to write it to the Playground.');
          render();
        }).catch(fail);
    }

    // Distinct from Reset: Reset rewinds the candidate inside this chat, while
    // this drops the chat entirely and starts over from whatever the editor now
    // holds — including anything already applied.
    function startFreshChat() {
      if (busy) return Promise.resolve();
      var finished = endSession();
      setState('idle', 'Started a new chat. The assistant works from your current editor state.');
      render();
      return finished;
    }

    function endSession() {
      if (!session) return Promise.resolve();
      var path = sessionPath();
      session = null;
      transcript = [];
      latest = null;
      setState('idle');
      return api.delete(path).catch(function () { /* expiry is fine */ });
    }

    // -----------------------------------------------------------------------
    // Rendering
    // -----------------------------------------------------------------------

    function renderEvents(target, events) {
      var interesting = (events || []).filter(function (event) {
        return event && event.type === 'tool_result';
      });
      if (!interesting.length) return;
      var list = element('ul', 'editor-agent-steps');
      interesting.forEach(function (event) {
        var item = element('li', 'editor-agent-step editor-agent-step-' + (event.status || 'info'));
        item.appendChild(element('span', 'editor-agent-step-icon', statusIcon(event.status)));
        var label = event.label || event.tool;
        if (event.status === 'rejected') {
          label = 'Attempted change failed; trying a corrected edit — ' + label;
        }
        item.appendChild(element('span', 'editor-agent-step-label', label));
        list.appendChild(item);
      });
      target.appendChild(list);
    }

    function renderDiagnostics(target, diagnostics) {
      var problems = (diagnostics || []).filter(function (item) {
        var level = String((item && (item.level || item.severity)) || '').toLowerCase();
        return level === 'error' || level === 'warning';
      });
      if (!problems.length) return;
      var list = element('ul', 'editor-agent-diagnostics');
      problems.slice(0, 12).forEach(function (item) {
        var level = String(item.level || item.severity || 'error').toLowerCase();
        var row = element('li', 'editor-agent-diagnostic editor-agent-diagnostic-' + level);
        var where = item.block_id ? item.block_id + ': ' : '';
        row.textContent = where + (item.message || 'Unknown issue');
        list.appendChild(row);
      });
      target.appendChild(list);
    }

    function renderRepairs(target, repairs) {
      if (!repairs || !repairs.length) return;
      var list = element('ul', 'editor-agent-repairs');
      repairs.forEach(function (repair) {
        var row = element('li', 'editor-agent-repair', repair.summary);
        list.appendChild(row);
      });
      target.appendChild(list);
    }

    function renderRepairOffer(target) {
      if (!repairOffer) return;
      var box = element('div', 'editor-agent-repair-offer');
      var fixable = repairOffer.repairableCount;
      var blocked = repairOffer.unrepairableCount;
      if (repairOffer.canAutoHeal) {
        box.appendChild(element(
          'p',
          'editor-agent-repair-offer-text',
          'This interview has ' + fixable +
          (fixable === 1 ? ' problem' : ' problems') +
          ' with block ids. I can fix ' +
          (fixable === 1 ? 'it' : 'them') +
          ' automatically — the change will appear in the diff for you to review ' +
          'before you save.'
        ));
        renderRepairs(box, repairOffer.repairs);
        var fixButton = element(
          'button',
          'btn btn-primary btn-sm',
          'Fix ' + fixable + (fixable === 1 ? ' problem' : ' problems') + ' and continue'
        );
        fixButton.type = 'button';
        fixButton.disabled = busy;
        fixButton.addEventListener('click', healAndRetry);
        box.appendChild(fixButton);
      } else {
        box.appendChild(element(
          'p',
          'editor-agent-repair-offer-text',
          blocked === 1
            ? 'One problem here needs a human decision, so the assistant cannot start yet.'
            : blocked + ' problems here need a human decision, so the assistant cannot start yet.'
        ));
        renderDiagnostics(box, repairOffer.diagnostics);
      }
      target.appendChild(box);
    }

    function renderDiff(target, diff) {
      if (!diff || !diff.diff) return;
      var details = element('details', 'editor-agent-diff');
      var blocks = Number(diff.changed_blocks || 0);
      var summary = element(
        'summary',
        null,
        'Assistant changed ' + blocks + (blocks === 1 ? ' block' : ' blocks') +
        ' · +' + Number(diff.added || 0) + ' −' + Number(diff.removed || 0) + ' lines'
      );
      details.appendChild(summary);
      var pre = element('pre', 'editor-agent-diff-body', diff.diff);
      details.appendChild(pre);
      if (diff.truncated) {
        details.appendChild(element(
          'p',
          'editor-agent-diff-note',
          'This diff is too large to show in full. Apply and review it in the editor.'
        ));
      }
      target.appendChild(details);
    }

    function renderTranscript(target) {
      if (!transcript.length) {
        target.appendChild(element(
          'p',
          'editor-agent-empty',
          'Describe the change you want. For example: “Add a screen asking ' +
          'whether the client has children, before the address questions.”'
        ));
        return;
      }
      transcript.forEach(function (entry) {
        var row = element('article', 'editor-agent-message editor-agent-message-' + entry.role);
        var who = entry.role === 'user' ? 'You' :
          (entry.role === 'error' ? 'Error' : 'Assistant');
        row.appendChild(element('h4', 'editor-agent-message-role', who));
        row.appendChild(element('div', 'editor-agent-message-body', entry.content));
        if (entry.role === 'assistant') {
          renderRepairs(row, entry.repairs);
          renderEvents(row, entry.events);
          if (entry.stopReason && STOP_REASON_NOTES[entry.stopReason]) {
            row.appendChild(element(
              'p',
              'editor-agent-stop-reason',
              STOP_REASON_NOTES[entry.stopReason]
            ));
          }
          renderDiagnostics(row, entry.diagnostics);
          renderDiff(row, entry.diff);
        }
        target.appendChild(row);
      });
    }

    function canApply() {
      return Boolean(
        latest &&
        latest.status === 'ready' &&
        latest.has_candidate_changes &&
        !busy &&
        uiState !== 'stale'
      );
    }

    function renderActions(target) {
      // Apply and Reset act on a candidate that cannot exist yet.
      if (!isAvailable()) return;
      var applyButton = element('button', 'btn btn-primary btn-sm', 'Apply');
      applyButton.type = 'button';
      applyButton.disabled = !canApply();
      applyButton.title = canApply()
        ? 'Replace the editor buffer with this candidate. You still need to Save.'
        : 'Apply becomes available once a validated change is ready.';
      applyButton.addEventListener('click', apply);
      target.appendChild(applyButton);

      var resetButton = element('button', 'btn btn-outline-secondary btn-sm', 'Reset');
      resetButton.type = 'button';
      resetButton.disabled = busy;
      resetButton.title = 'Discard the assistant candidate and clear the conversation.';
      resetButton.addEventListener('click', reset);
      target.appendChild(resetButton);

      if (busy) {
        var stopButton = element('button', 'btn btn-outline-danger btn-sm', 'Stop');
        stopButton.type = 'button';
        stopButton.addEventListener('click', stop);
        target.appendChild(stopButton);
      }
    }

    function render(target) {
      container = target || container;
      if (!container) return;
      container.innerHTML = '';

      var panel = element('section', 'editor-agent-panel');
      panel.setAttribute('aria-labelledby', 'editor-agent-title');

      var header = element('header', 'editor-agent-header');
      var title = element('h3', 'editor-agent-title h6 mb-0', 'Assistant');
      title.id = 'editor-agent-title';
      header.appendChild(title);
      var actions = element('div', 'editor-agent-actions');
      renderActions(actions);
      header.appendChild(actions);
      panel.appendChild(header);

      if (!isAvailable()) {
        var notice = element('div', 'editor-agent-unavailable');
        notice.setAttribute('role', 'status');
        notice.appendChild(element(
          'p',
          'editor-agent-unavailable-title',
          'The assistant is not available on this server.'
        ));
        notice.appendChild(element(
          'p',
          'editor-agent-unavailable-detail',
          (availability && availability.message) ||
          'Ask your server administrator to finish setting it up.'
        ));
        panel.appendChild(notice);
        container.appendChild(panel);
        return;
      }

      var status = element('p', 'editor-agent-status');
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
      status.textContent = errorMessage || statusMessage || STATE_LABELS[uiState] || '';
      status.classList.toggle('editor-agent-status-error', Boolean(errorMessage));
      panel.appendChild(status);

      var log = element('div', 'editor-agent-transcript');
      log.setAttribute('role', 'log');
      log.setAttribute('aria-live', 'polite');
      log.setAttribute('aria-label', 'Assistant conversation');
      renderTranscript(log);
      renderRepairOffer(log);
      panel.appendChild(log);

      if (busy) {
        var working = element('div', 'editor-agent-working');
        working.setAttribute('role', 'status');
        working.setAttribute('aria-live', 'polite');
        buildWorkingBanner(working);
        panel.appendChild(working);
      }

      var remaining = turnsRemaining();
      if (remaining !== null && remaining <= 3) {
        var nudge = element('div', 'editor-agent-nudge');
        nudge.setAttribute('role', 'status');
        nudge.appendChild(element(
          'p',
          'editor-agent-nudge-text',
          remaining === 0
            ? 'This chat has reached its limit. Apply what you have, then start a ' +
              'new chat for the next change.'
            : 'The assistant works best on one task at a time. ' + remaining +
              (remaining === 1 ? ' request left' : ' requests left') +
              ' in this chat — apply your changes and start a new one for the next task.'
        ));
        var fresh = element('button', 'btn btn-outline-secondary btn-sm', 'New chat');
        fresh.type = 'button';
        fresh.disabled = busy;
        fresh.addEventListener('click', startFreshChat);
        nudge.appendChild(fresh);
        panel.appendChild(nudge);
      }

      var form = element('form', 'editor-agent-composer');
      var label = element('label', 'visually-hidden', 'Ask the assistant to change this interview');
      label.setAttribute('for', 'editor-agent-input');
      form.appendChild(label);
      var input = element('textarea', 'form-control');
      input.id = 'editor-agent-input';
      input.rows = 3;
      input.value = draft;
      input.placeholder = 'Describe the change you want…';
      input.disabled = busy || isExhausted();
      input.addEventListener('input', function () { draft = input.value; });
      input.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          send(input.value);
        }
      });
      form.appendChild(input);
      var submit = element('button', 'btn btn-primary btn-sm mt-2', busy ? 'Working…' : 'Send');
      submit.type = 'submit';
      submit.disabled = busy || isExhausted();
      form.appendChild(submit);
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        send(input.value);
      });
      panel.appendChild(form);

      container.appendChild(panel);
      log.scrollTop = log.scrollHeight;
    }

    return {
      render: render,
      send: send,
      stop: stop,
      reset: reset,
      apply: apply,
      endSession: endSession,
      startFreshChat: startFreshChat,
      turnsRemaining: turnsRemaining,
      getState: function () { return uiState; },
      getSession: function () { return clone(session); },
      canApply: canApply,
      markStale: function (message) {
        setState('stale');
        errorMessage = message || STATE_LABELS.stale;
        render();
      },
    };
  }

  return {
    createAgentChat: createAgentChat,
    STATE_LABELS: STATE_LABELS,
    STOP_REASON_NOTES: STOP_REASON_NOTES,
  };
});
