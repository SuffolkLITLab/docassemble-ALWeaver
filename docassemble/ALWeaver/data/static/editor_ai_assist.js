/* AI help on a field: the kinds of help, and the order builder's AI step.

   A field with AI help is three ordinary pieces of source: the field, an
   `AIAssist` declaration in an objects block, and a review question. The
   server describes each one as `block.ai_assists`; this module turns those
   descriptions into what the field list, the AI help dialog and the order
   builder show. It has no DOM code, so the node tests can load it. */
(function (root) {
  'use strict';

  // `output`: what the review screen shows. `input`: the datatype the field
  // needs for AI to read it.
  var TASKS = [
    {
      value: 'rewrite',
      label: 'Improve writing',
      help: 'Rewrites the answer so it is clear and organized, without adding facts.',
      output: 'text',
      input: 'area',
      outputSuffix: '_reviewed',
      reviewQuestion: 'Review your answer',
    },
    {
      value: 'goal',
      label: 'Ask follow-up questions until a goal is met',
      help: 'Asks up to a set number of follow-up questions, then writes one complete answer from all of them.',
      output: 'text',
      input: 'area',
      outputSuffix: '_complete',
      reviewQuestion: 'Review your answer',
    },
    {
      value: 'prompt',
      label: 'Apply a custom prompt',
      help: 'Sends the answer to AI with your own instructions.',
      output: 'text',
      input: 'area',
      outputSuffix: '_result',
      reviewQuestion: 'Review the result',
    },
    {
      value: 'summarize',
      label: 'Summarize',
      help: 'Writes a short summary of the answer.',
      output: 'text',
      input: 'area',
      outputSuffix: '_summary',
      reviewQuestion: 'Review the summary',
    },
    {
      value: 'translate',
      label: 'Translate',
      help: 'Translates the answer into another language and keeps the original.',
      output: 'text',
      input: 'area',
      outputSuffix: '_translated',
      reviewQuestion: 'Review the translation',
    },
    {
      value: 'extract',
      label: 'Find answers in text',
      help: 'Fills in several fields from text the person pastes.',
      output: 'fields',
      input: 'area',
      reviewQuestion: 'Check the information we found',
    },
    {
      value: 'extract_file',
      label: 'Find answers in a document',
      help: 'Fills in several fields from a document the person uploads.',
      output: 'fields',
      input: 'file',
      reviewQuestion: 'Check the information we found',
    },
    {
      value: 'classify',
      label: 'Suggest a choice',
      help: 'Picks the choice that fits the answer best, for the person to confirm.',
      output: 'choice',
      input: 'area',
      outputSuffix: '_choice',
      reviewQuestion: 'Check this choice',
    },
  ];

  var LANGUAGES = [
    ['en', 'English'],
    ['es', 'Spanish'],
    ['zh', 'Chinese'],
    ['vi', 'Vietnamese'],
    ['ht', 'Haitian Creole'],
    ['pt', 'Portuguese'],
    ['ru', 'Russian'],
    ['ar', 'Arabic'],
    ['fr', 'French'],
    ['ko', 'Korean'],
  ];

  var EXTRACT_DATATYPES = [
    ['text', 'Text'],
    ['area', 'Long text'],
    ['date', 'Date'],
    ['number', 'Number'],
    ['integer', 'Whole number'],
    ['currency', 'Money'],
    ['email', 'Email'],
  ];

  function task(value) {
    for (var i = 0; i < TASKS.length; i++) {
      if (TASKS[i].value === value) return TASKS[i];
    }
    return null;
  }

  function assistsFromBlocks(blocks) {
    var found = [];
    (blocks || []).forEach(function (block) {
      (block && block.ai_assists ? block.ai_assists : []).forEach(
        function (assist) {
          found.push(assist);
        },
      );
    });
    return found;
  }

  function assistForSource(blocks, variable) {
    var name = String(variable || '').trim();
    if (!name) return null;
    var all = assistsFromBlocks(blocks);
    for (var i = 0; i < all.length; i++) {
      if (all[i].settings && all[i].settings.source === name) return all[i];
    }
    return null;
  }

  function assistByName(blocks, name) {
    var all = assistsFromBlocks(blocks);
    for (var i = 0; i < all.length; i++) {
      if (all[i].name === name) return all[i];
    }
    return null;
  }

  function reviewVariable(assist) {
    var fields = (assist && assist.review_fields) || [];
    return fields.length ? fields[0].variable : '';
  }

  // "incident_description" -> "incident_description_reviewed".
  function suggestedOutput(source, taskValue) {
    var info = task(taskValue);
    var base = String(source || 'answer')
      .replace(/\[[^\]]*\]/g, '')
      .replace(/\W+/g, '_')
      .replace(/^_+|_+$/g, '');
    return (base || 'answer') + ((info && info.outputSuffix) || '_reviewed');
  }

  // A short line for the field list: "Improve writing -> incident_reviewed".
  function summary(assist) {
    var info = task(assist.task);
    var label = info ? info.label : assist.task;
    var fields = assist.review_fields || [];
    var outputs =
      fields.length > 1
        ? fields.length + ' fields'
        : fields.length
          ? fields[0].variable
          : 'no review screen';
    return { label: label, outputs: outputs };
  }

  // The dialog's form state for an existing AI help, or for a new one.
  function formState(assist, source, taskValue) {
    var settings = (assist && assist.settings) || {};
    var value = taskValue || (assist && assist.task) || 'rewrite';
    var info = task(value) || TASKS[0];
    var reviewFields = (assist && assist.review_fields) || [];
    var outputsDescribed = settings.outputs || {};
    var choicesDescribed = settings.choices || {};
    var outputs = [];
    var choices = [];
    if (info.output === 'fields') {
      reviewFields.forEach(function (field) {
        outputs.push({
          label: field.label,
          variable: field.variable,
          datatype: field.datatype || 'text',
          description:
            outputsDescribed[field.variable] &&
            outputsDescribed[field.variable] !== field.label
              ? outputsDescribed[field.variable]
              : '',
        });
      });
      if (!outputs.length)
        outputs.push({
          label: '',
          variable: '',
          datatype: 'text',
          description: '',
        });
    }
    if (info.output === 'choice') {
      var reviewChoices = (reviewFields[0] && reviewFields[0].choices) || [];
      reviewChoices.forEach(function (choice) {
        choices.push({
          label: choice.label,
          value: choice.value,
          description:
            choicesDescribed[choice.value] &&
            choicesDescribed[choice.value] !== choice.label
              ? choicesDescribed[choice.value]
              : '',
        });
      });
      while (choices.length < 2)
        choices.push({ label: '', value: '', description: '' });
    }
    var sameTask = assist && assist.task === value;
    return {
      task: value,
      source: settings.source || source || '',
      output:
        (sameTask && info.output !== 'fields' && reviewVariable(assist)) ||
        suggestedOutput(settings.source || source, value),
      reviewQuestion:
        (sameTask && assist.review_question) || info.reviewQuestion,
      instructions: settings.instructions || '',
      inputs: (settings.inputs || []).join('\n'),
      language: settings.language || 'es',
      rubric: settings.rubric || '',
      initialQuestion: settings.initial_question || '',
      questionLimit: settings.question_limit || 3,
      model: settings.model || '',
      askPermission: settings.ask_permission !== false,
      outputs: outputs,
      choices: choices,
    };
  }

  // What the dialog sends to /api/ai-assist.
  function configFromForm(form) {
    var info = task(form.task) || TASKS[0];
    var config = {
      task: form.task,
      source: String(form.source || '').trim(),
      instructions: String(form.instructions || '').trim(),
      inputs: String(form.inputs || '')
        .split(/[\n,]+/)
        .map(function (name) {
          return name.trim();
        })
        .filter(Boolean),
      model: String(form.model || '').trim(),
      ask_permission: form.askPermission !== false,
      review_question: String(form.reviewQuestion || '').trim(),
    };
    if (info.output !== 'fields')
      config.output = String(form.output || '').trim();
    if (info.output === 'fields')
      config.outputs = (form.outputs || []).filter(function (row) {
        return String(row.variable || row.label || '').trim();
      });
    if (info.output === 'choice')
      config.choices = (form.choices || []).filter(function (row) {
        return String(row.value || row.label || '').trim();
      });
    if (form.task === 'translate') config.language = form.language;
    if (form.task === 'goal') {
      config.rubric = String(form.rubric || '').trim();
      config.initial_question = String(form.initialQuestion || '').trim();
      config.question_limit = parseInt(form.questionLimit, 10) || 3;
    }
    return config;
  }

  // The datatype the field should have so AI can read it, or null when the
  // current one already works.
  function inputDatatypeFor(taskValue, currentDatatype) {
    var info = task(taskValue);
    if (!info) return null;
    var current = String(currentDatatype || 'text');
    var fileTypes = ['file', 'files', 'camera'];
    if (info.input === 'file')
      return fileTypes.indexOf(current) === -1 ? 'file' : null;
    if (fileTypes.indexOf(current) !== -1 || current === 'text') return 'area';
    return null;
  }

  // --- The order builder's AI step --------------------------------------
  //
  // In the code an AI step is two lines: the question with the field, then
  // its review question. The builder shows them as one step whose children
  // are those two screen steps, and the server writes the children back out
  // unchanged.

  function mergeOrderSteps(steps, blocks, questionVariables) {
    var assists = assistsFromBlocks(blocks);
    if (!assists.length || !Array.isArray(steps)) return steps;

    function askFor(assist) {
      var names = [assist.settings && assist.settings.source].concat(
        questionVariables
          ? questionVariables(assist.settings && assist.settings.source) || []
          : [],
      );
      return names.filter(Boolean);
    }

    function pairAt(list, index) {
      var ask = list[index];
      var review = list[index + 1];
      if (!ask || !review || ask.kind !== 'screen' || review.kind !== 'screen')
        return null;
      var reviewName = String(review.invoke || '').trim();
      var askName = String(ask.invoke || '').trim();
      for (var i = 0; i < assists.length; i++) {
        if (
          reviewVariable(assists[i]) === reviewName &&
          askFor(assists[i]).indexOf(askName) !== -1
        )
          return assists[i];
      }
      return null;
    }

    function merge(list) {
      var out = [];
      for (var index = 0; index < list.length; index++) {
        var step = list[index];
        if (step && step.kind === 'ai') {
          out.push(step);
          continue;
        }
        var assist = pairAt(list, index);
        if (assist) {
          out.push({
            id: 'ai-' + step.id,
            kind: 'ai',
            label: 'AI help',
            assist: assist.name,
            children: [step, list[index + 1]],
          });
          index += 1;
          continue;
        }
        if (step && Array.isArray(step.children) && step.kind !== 'ai')
          step.children = merge(step.children);
        if (step && Array.isArray(step.else_children))
          step.else_children = merge(step.else_children);
        out.push(step);
      }
      return out;
    }

    return merge(steps);
  }

  function newOrderStep(assist, askInvoke) {
    var stamp = Date.now() + '-' + Math.floor(Math.random() * 1000);
    var source = askInvoke || (assist.settings && assist.settings.source);
    return {
      id: 'ai-step-' + stamp,
      kind: 'ai',
      label: 'AI help',
      assist: assist.name,
      children: [
        {
          id: 'step-' + stamp + '-ask',
          kind: 'screen',
          label: 'Screen',
          invoke: source,
          summary: source,
        },
        {
          id: 'step-' + stamp + '-review',
          kind: 'screen',
          label: 'Screen',
          invoke: reviewVariable(assist),
          summary: reviewVariable(assist),
        },
      ],
    };
  }

  var api = {
    TASKS: TASKS,
    LANGUAGES: LANGUAGES,
    EXTRACT_DATATYPES: EXTRACT_DATATYPES,
    task: task,
    assistsFromBlocks: assistsFromBlocks,
    assistForSource: assistForSource,
    assistByName: assistByName,
    reviewVariable: reviewVariable,
    suggestedOutput: suggestedOutput,
    summary: summary,
    formState: formState,
    configFromForm: configFromForm,
    inputDatatypeFor: inputDatatypeFor,
    mergeOrderSteps: mergeOrderSteps,
    newOrderStep: newOrderStep,
  };
  root.ALWeaverAIAssist = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window === 'object' ? window : globalThis);
