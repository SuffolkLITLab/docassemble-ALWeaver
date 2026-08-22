/* Interview Flow Report generator for the graphical editor.
 *
 * Produces a self-contained HTML document that renders every screen in
 * interview-order at full size, so an author can read and print the whole
 * interview in one pass, with a Mermaid flowchart of the same walk on top.
 *
 * The screens are drawn by the same renderer the Screen preview modal uses,
 * and this document loads the same Docassemble stylesheets and scripts that
 * ``ALWeaverScreenPreview.buildDocument`` loads into the preview iframe, so a
 * screen looks here exactly as it looks there. The preview gets an iframe per
 * screen; a report cannot -- a browser clips an iframe at the page break -- so
 * the screens share one document instead, and the markup Docassemble keys its
 * CSS to (``#dabody``, ``.container``, ``.row.tab-content``) is reproduced
 * around each one.
 *
 * Usage:
 *   var html = ALWeaverInterviewReport.buildReport(orderSteps, blocks, options);
 *
 * options (all optional):
 *   assets        — same shape as ALWeaverScreenPreview DEFAULT_ASSETS
 *   extraCss      — array of extra stylesheet URLs to inject
 *   labelLayout   — 'horizontal' | 'above' | 'floating'
 *   continueLabel — text for the continue button
 *   backButtonLabel — text for the back button
 *   theme         — 'light' | 'dark'
 *   interview     — context object from ALWeaverScreenPreview.buildInterviewContext()
 *   title         — report title string
 *   subtitle      — line under the title (defaults to the filename line)
 *   mermaidCdn    — URL for mermaid.min.js (defaults to jsDelivr)
 *   origin        — where root-relative asset URLs point, e.g. window.location.origin
 */
(function (root, factory) {
  'use strict';
  var mod = factory(root.ALWeaverScreenPreview);
  if (typeof module === 'object' && module.exports) module.exports = mod;
  root.ALWeaverInterviewReport = mod;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Preview) {
  'use strict';

  // ---------------------------------------------------------------------------
  // Step kind constants (mirrors editor_utils.py)
  // ---------------------------------------------------------------------------
  var STEP_SCREEN    = 'screen';
  var STEP_GATHER    = 'gather';
  var STEP_SECTION   = 'section';
  var STEP_PROGRESS  = 'progress';
  var STEP_FUNCTION  = 'function';
  var STEP_CONDITION = 'condition';
  var STEP_RAW       = 'raw';

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function esc(text) {
    return String(text === undefined || text === null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function trunc(text, max) {
    var s = String(text === undefined || text === null ? '' : text);
    return s.length > max ? s.slice(0, max - 1) + '…' : s;
  }

  /* The bare name behind an invocation: ``users[0].gather()`` is the users
   * list, ``benefits.there_is_another`` is benefits. */
  function rootName(invoke) {
    var s = String(invoke === undefined || invoke === null ? '' : invoke).trim();
    s = s.replace(/\(.*\)$/, '');
    s = s.split('.')[0];
    return s.replace(/\[.*?\]/g, '').trim();
  }

  function humanize(name) {
    var s = String(name === undefined || name === null ? '' : name)
      .replace(/\[.*?\]/g, '')
      .replace(/[._]+/g, ' ')
      .replace(/\(\s*\)/g, '')
      .trim();
    if (!s) return '';
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  var IRREGULAR_PLURALS = {
    children: 'child', people: 'person', men: 'man', women: 'woman',
    persons: 'person', attorneys: 'attorney',
  };

  /* Enough of a singular to make "For each ..." read like English. */
  function singularize(name) {
    var s = String(name === undefined || name === null ? '' : name).trim();
    var lower = s.toLowerCase();
    if (IRREGULAR_PLURALS[lower]) return IRREGULAR_PLURALS[lower];
    if (/ies$/i.test(s)) return s.slice(0, -3) + 'y';
    if (/(s|x|z|ch|sh)es$/i.test(s)) return s.slice(0, -2);
    if (/[^s]s$/i.test(s)) return s.slice(0, -1);
    return s;
  }

  /* Every screen the preview renders numbers its fields from zero, which is
   * fine in an iframe of its own and wrong in a document that holds them all:
   * two screens would share input ids and radio-group names, so clicking a
   * label on one would answer another. Give each screen its own prefix. */
  function namespaceIds(html, screenNumber) {
    return String(html || '').replace(/dapv_(field|collapse)_/g,
      's' + screenNumber + '_dapv_$1_');
  }

  /* This document is opened from a blob: URL, and a blob: URL has an opaque
   * path, so a browser cannot resolve "/static/app/bundle.css" against it --
   * every stylesheet in the report would silently fail to load and the screens
   * would come out unstyled. Point the links at the server instead. */
  function absoluteUrl(href, origin) {
    var s = String(href === undefined || href === null ? '' : href);
    if (!origin || !s) return s;
    if (/^[a-z][a-z0-9+.-]*:/i.test(s) || s.indexOf('//') === 0) return s;
    if (s.charAt(0) !== '/') return s;
    return String(origin).replace(/\/+$/, '') + s;
  }

  /* "other_parties[0].address.address" -> "Address of the other party".
   * What a screen is called in the contents when its own wording is a Mako
   * expression that only means something once the interview is running. */
  function variableTitle(variable) {
    var parts = String(variable || '').split('.');
    if (parts.length < 2) return '';
    var attribute = humanize(parts[1]);
    if (!attribute) return '';
    return attribute.charAt(0).toUpperCase() + attribute.slice(1).toLowerCase() +
      ' of ' + subjectPhrase(parts[0]);
  }

  /* The first line a reader would actually read, skipping Mako directives --
   * the same rule the editor titles a question block by. */
  function firstProseLine(text) {
    var lines = String(text === undefined || text === null ? '' : text).split('\n');
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line || line.charAt(0) === '%' || line.charAt(0) === '#') continue;
      return trunc(line, 70);
    }
    return '';
  }

  /* "users[i]" is each user, "users[0]" is the user, "spouse" is the spouse. */
  function subjectPhrase(subject) {
    var indexed = /^(.*?)\[([^\]]*)\]$/.exec(String(subject || ''));
    if (!indexed) return humanize(subject).toLowerCase() || 'this person';
    var noun = humanize(singularize(indexed[1])).toLowerCase() || 'person';
    return (indexed[2] === 'i' ? 'each ' : 'the ') + noun;
  }

  /* "name", "name and address", "name, address and phone number" */
  function listSentence(items) {
    var list = (items || []).filter(function (item) { return item; });
    if (!list.length) return '';
    if (list.length === 1) return list[0];
    return list.slice(0, -1).join(', ') + ' and ' + list[list.length - 1];
  }

  function slug(text, fallback) {
    var s = String(text === undefined || text === null ? '' : text)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
    return s || fallback || 'item';
  }

  function progressValue(step) {
    var raw = step && step.value !== undefined && step.value !== null ? step.value : '';
    var num = parseFloat(String(raw).replace('%', ''));
    if (isNaN(num)) {
      var m = String((step && step.summary) || '').match(/(\d+(?:\.\d+)?)\s*%/);
      num = m ? parseFloat(m[1]) : NaN;
    }
    if (isNaN(num)) return null;
    return Math.min(100, Math.max(0, num));
  }

  // ---------------------------------------------------------------------------
  // Block lookup
  // ---------------------------------------------------------------------------

  /* The same screen is written users[0].name.first in an order block,
   * users[i].name.first in a gather loop and x.name.first in a generic
   * question, so every subscript is flattened to one form for lookup. */
  function indexKey(name) {
    return String(name === undefined || name === null ? '' : name)
      .trim()
      .replace(/\[[^\]]*\]/g, '[]');
  }

  function buildBlockMap(blocks) {
    var map = {};
    function record(name, block) {
      var key = String(name || '').trim();
      if (!key) return;
      if (!map[key]) map[key] = block;
      var flat = indexKey(key);
      if (flat !== key && !map[flat]) map[flat] = block;
    }
    /* What a `code:` block assigns is kept apart from what a question asks:
     * an order block can name a variable that only code defines (AssemblyLine
     * builds `trial_court` that way), but code that happens to assign the same
     * name as a question must never stand in for the question. */
    function recordAssignments(block) {
      var code = (block.data || {}).code;
      if (typeof code !== 'string') return;
      var pattern = /(?:^|\n)\s*([A-Za-z_][\w.[\]'"]*)\s*=(?!=)/g;
      var match;
      while ((match = pattern.exec(code))) {
        var key = 'code:' + match[1];
        if (!map[key]) map[key] = block;
      }
    }

    (blocks || []).forEach(function (block) {
      record(block.variable, block);
      var sets = (block.data || {}).sets;
      if (Array.isArray(sets)) {
        sets.forEach(function (s) { if (typeof s === 'string') record(s, block); });
      } else if (typeof sets === 'string') {
        record(sets, block);
      }
      recordAssignments(block);
    });
    return map;
  }

  /* AssemblyLine asks most of its questions generically: one block, written
   * about ``x``, answers users[0].name.first and other_parties[i].name.first
   * alike. Docassemble picks it by the type of the object in front; here the
   * pattern is enough, and the subject is put back into the wording so the
   * screen reads the way it will read to the person filling it in. */
  function substituteSubject(value, subject) {
    if (typeof value === 'string') {
      return value
        .replace(/\$\{\s*x\s*\}/g, '${ ' + subject + ' }')
        .replace(/\bx\b(?=\s*[.[])/g, subject);
    }
    if (Array.isArray(value)) {
      return value.map(function (item) { return substituteSubject(item, subject); });
    }
    if (value && typeof value === 'object') {
      var out = {};
      Object.keys(value).forEach(function (key) {
        // A field's label is the key in Docassemble's shorthand, and a label
        // can be Mako too: "- ${ x } is married: x.has_spouse".
        out[substituteSubject(key, subject)] = substituteSubject(value[key], subject);
      });
      return out;
    }
    return value;
  }

  function isGenericBlock(block) {
    return !!(block && block.data && block.data['generic object']);
  }

  /* The generic block that answers a variable, rewritten for this subject. */
  function findGenericBlock(variable, map) {
    var parts = String(variable || '').split('.');
    for (var i = 1; i < parts.length; i++) {
      var subject = parts.slice(0, i).join('.');
      var tail = parts.slice(i).join('.');
      var block = map['x.' + tail] || map[indexKey('x.' + tail)];
      if (!isGenericBlock(block)) continue;
      var rewritten = {};
      Object.keys(block).forEach(function (key) { rewritten[key] = block[key]; });
      rewritten.data = substituteSubject(block.data, subject);
      rewritten.genericSubject = subject;
      return rewritten;
    }
    return null;
  }

  function findBlock(invoke, blockMap) {
    if (!invoke) return null;
    var map = blockMap || {};
    var trimmed = String(invoke).trim();
    if (map[trimmed]) return map[trimmed];
    var flat = indexKey(trimmed);
    if (map[flat]) return map[flat];
    var parts = trimmed.split('.');
    for (var i = parts.length - 1; i >= 1; i--) {
      var candidate = parts.slice(0, i).join('.');
      if (map[candidate]) return map[candidate];
      if (map[indexKey(candidate)]) return map[indexKey(candidate)];
    }
    var stripped = trimmed.replace(/\[\d+\]/g, '').replace(/\.{2,}/g, '.');
    if (stripped !== trimmed && map[stripped]) return map[stripped];
    var generic = findGenericBlock(trimmed, map);
    if (generic) return generic;
    return map['code:' + trimmed] || null;
  }

  function isScreenBlock(block) {
    var data = (block && block.data) || null;
    if (!data) return false;
    return data.question !== undefined || Array.isArray(data.review) ||
      typeof data.table === 'string';
  }

  /* An order block often names a variable that a `code:` block assembles --
   * `trial_court` is built by code out of the answers to another screen. The
   * screen is what a reader needs, so the code is followed to whatever it
   * depends on. */
  function followToScreen(block, map, depth) {
    if (!block || isScreenBlock(block)) return block;
    var data = block.data || {};
    if (typeof data.code !== 'string' || (depth || 0) > 2) return block;

    var candidates = [];
    ['depends on', 'need'].forEach(function (key) {
      var value = data[key];
      if (typeof value === 'string') candidates.push(value);
      else if (Array.isArray(value)) {
        value.forEach(function (item) { if (typeof item === 'string') candidates.push(item); });
      }
    });
    // Failing that, whatever the code reads on the right of an assignment.
    if (!candidates.length) {
      var pattern = /=\s*([A-Za-z_][\w.[\]'"]*)/g;
      var match;
      while ((match = pattern.exec(data.code))) candidates.push(match[1]);
    }

    for (var i = 0; i < candidates.length; i++) {
      var name = String(candidates[i]).trim().replace(/\($[\s\S]*\)$/, '');
      if (!name) continue;
      var found = findBlock(name, map);
      if (found && found !== block) {
        var resolved = followToScreen(found, map, (depth || 0) + 1);
        if (isScreenBlock(resolved)) return resolved;
      }
    }
    return block;
  }

  /* What the screen is called on the screen itself. The editor already titles
   * every question block by the first line of prose in its ``question:`` key,
   * so a flowchart node and a report heading can say what the user will read
   * rather than the variable that happens to trigger it. */
  function screenTitle(step, blockMap) {
    var invoke = String((step && (step.invoke || step.summary)) || '').trim();
    var map = blockMap || {};
    var block = findBlock(invoke, map);
    if (block && !isScreenBlock(block)) block = followToScreen(block, map, 0);
    if (block && !isScreenBlock(block)) block = null;

    var title = '';
    if (block) {
      // A generic block's own title still says "x"; read the rewritten
      // question instead.
      var question = (block.data || {}).question;
      if (block.genericSubject && typeof question === 'string') {
        title = firstProseLine(question);
      }
      if (!title && block.title) title = String(block.title).trim();
      // A block that arrived without a computed title still has its wording.
      if (!title && typeof question === 'string') title = firstProseLine(question);
      // "What is ${ users[0].possessive('address') }?" is the screen's real
      // wording but a poor name for it in a contents list.
      if (title.indexOf('${') !== -1) title = variableTitle(invoke) || title;
    }
    if (title === 'Untitled question') title = '';
    if (!title) title = variableTitle(invoke) || humanize(invoke) || invoke || 'Screen';
    return { title: title, variable: invoke, block: block };
  }

  // ---------------------------------------------------------------------------
  // What a list gather actually asks
  // ---------------------------------------------------------------------------

  /* A `.gather()` does not repeat the screens around it. It loops over the
   * list, and for each item asks whatever defines that item's
   * ``complete_attribute`` -- so the only honest way to say what the user will
   * be asked is to follow that attribute to the code block that defines it.
   *
   * Where nothing defines one, AssemblyLine's own default applies: an
   * ALPeopleList item is complete once the person exists, which Docassemble
   * satisfies by asking AssemblyLine's name question. */

  var GATHER_HOUSEKEEPING = [
    'complete', 'there_is_another', 'there_are_any', 'target_number',
    'ask_number', 'gathered', 'auto_gather', 'there_is_one_other', 'minimum_number',
  ];

  var AL_PEOPLE_CLASSES = ['ALPeopleList', 'PeopleList'];

  function callArgs(invoke) {
    var m = String(invoke || '').match(/\(([\s\S]*)\)\s*$/);
    return m ? m[1] : '';
  }

  function keywordArg(args, name) {
    var m = String(args || '').match(
      new RegExp(name + "\\s*=\\s*(?:'([^']*)'|\"([^\"]*)\")"));
    return m ? (m[1] !== undefined ? m[1] : m[2]) : null;
  }

  /* `nav.set_section("your_family")` names a key, and the label a reader
   * actually sees is the value that key has in the interview's `sections:`
   * block -- or in AssemblyLine's `al_nav_sections` data, which has the same
   * shape. Without the lookup a report shows the key, which is the one name
   * nobody reviewing the wording cares about. */
  function sectionLabels(blocks) {
    var labels = {};

    function walk(items) {
      (Array.isArray(items) ? items : []).forEach(function (item) {
        if (typeof item === 'string') {
          if (!labels[item]) labels[item] = item;
          return;
        }
        if (!item || typeof item !== 'object') return;
        Object.keys(item).forEach(function (key) {
          if (key === 'hidden') return;
          var value = item[key];
          if (Array.isArray(value)) {
            // A key with subsections under it carries no label of its own.
            if (!labels[key]) labels[key] = humanize(key);
            walk(value);
          } else if (typeof value === 'string' && value.trim()) {
            if (!labels[key]) labels[key] = value.trim();
          }
        });
      });
    }

    (blocks || []).forEach(function (block) {
      var data = block.data || {};
      if (Array.isArray(data.sections)) walk(data.sections);
      if (data['variable name'] === 'al_nav_sections' && Array.isArray(data.data)) {
        walk(data.data);
      }
    });
    return labels;
  }

  function sectionLabel(value, labels) {
    var name = String(value === undefined || value === null ? '' : value).trim();
    if (!name) return '';
    return (labels && labels[name]) || name;
  }

  /* What an `objects:` block says a name is, e.g.
   * ``users: ALPeopleList.using(there_are_any=True)``. */
  function objectDeclarations(blocks) {
    var declared = {};
    (blocks || []).forEach(function (block) {
      var objects = (block.data || {}).objects;
      var entries = [];
      if (Array.isArray(objects)) entries = objects;
      else if (objects && typeof objects === 'object') entries = [objects];
      entries.forEach(function (entry) {
        if (!entry || typeof entry !== 'object') return;
        Object.keys(entry).forEach(function (name) {
          var spec = String(entry[name] === undefined ? '' : entry[name]);
          if (declared[name]) return;
          declared[name] = {
            className: spec.split('.')[0].trim(),
            args: callArgs(spec),
          };
        });
      });
    });
    return declared;
  }

  /* Attribute paths a piece of code asks for, in the order it asks, with the
   * list's own bookkeeping left out: users[i].name.first and
   * users[i].name.last are one thing to a reader -- a name. */
  function attributesFromCode(code, listName) {
    var pattern = new RegExp(
      listName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\[[^\\]]*\\]\\.([A-Za-z_][\\w.]*)', 'g');
    var seen = {};
    var found = [];
    var match;
    while ((match = pattern.exec(String(code || '')))) {
      var path = match[1];
      var head = path.split('.')[0];
      if (GATHER_HOUSEKEEPING.indexOf(head) !== -1) continue;
      if (seen[head]) continue;
      seen[head] = true;
      found.push({ head: head, path: path });
    }
    return found;
  }

  function describeGather(step, ctx) {
    var invoke = String(step.invoke || step.summary || '');
    var listName = rootName(invoke);
    var declared = (ctx.objects || {})[listName] || null;
    var className = declared ? declared.className : '';

    var completeAttribute =
      keywordArg(callArgs(invoke), 'complete_attribute') ||
      (declared ? keywordArg(declared.args, 'complete_attribute') : null);

    // The code block that defines it, whether or not the attribute was named
    // anywhere: a Weaver-drafted interview usually names none and AssemblyLine
    // defaults to `complete`.
    var attributeName = completeAttribute || 'complete';
    var definition = findBlock(listName + '[i].' + attributeName, ctx.blockMap);
    var code = definition && definition.data ? definition.data.code : '';
    var attributes = code ? attributesFromCode(code, listName) : [];

    if (attributes.length) {
      return {
        listName: listName,
        noun: singularize(listName),
        attributes: attributes,
        source: 'complete-attribute',
        attributeName: attributeName,
        className: className,
      };
    }

    // Nothing in this interview defines what completes an item, so fall back
    // to what AssemblyLine does with a list of people.
    var isPeople = !className || AL_PEOPLE_CLASSES.indexOf(className) !== -1;
    return {
      listName: listName,
      noun: isPeople ? singularize(listName) : singularize(listName),
      attributes: isPeople ? [{ head: 'name', path: 'name.first' }] : [],
      source: isPeople ? 'assembly-line-default' : 'unknown',
      attributeName: attributeName,
      className: className,
    };
  }

  function attributeLabel(attr) {
    return humanize(attr.head).toLowerCase();
  }

  // ---------------------------------------------------------------------------
  // Report-body HTML rendering
  // ---------------------------------------------------------------------------

  /* One screen, drawn by the preview renderer inside the markup Docassemble
   * keys its own stylesheets to. */
  function renderScreenCard(info, ctx, options) {
    var opts = options || {};
    var block = info.block;
    var title = info.title;
    var badgeText = opts.badge || '';

    if (!block) {
      var standIn = assemblyLineStandIn(info.variable);
      if (standIn) {
        block = standIn.block;
        title = standIn.title;
        // Not the package's own YAML, which is read when it can be: this is
        // the copy of it kept here for a server without AssemblyLine.
        badgeText = 'AssemblyLine default';
      }
    } else if (!badgeText && (block.sourceLabel || block.sourceFile)) {
      badgeText = block.sourceLabel || block.sourceFile;
    }

    var num = ++ctx.screenCount;
    var anchor = 'alwr-screen-' + num;
    var classes = 'alwr-screen' + (opts.nested ? ' alwr-screen-nested' : '');

    ctx.toc.push({
      kind: 'screen', number: num, title: title, anchor: anchor,
      missing: !block, nested: !!opts.nested,
    });

    var badge = badgeText
      ? '<span class="alwr-screen-badge">' + esc(badgeText) + '</span>'
      : '';

    var html = '<article class="' + classes + (block ? '' : ' alwr-screen-missing') + '" id="' + anchor + '">';
    html += '<header class="alwr-screen-header">';
    html += '<span class="alwr-screen-num">' + num + '</span>';
    html += '<span class="alwr-screen-heading">';
    html += '<span class="alwr-screen-name">' + esc(title) + '</span>';
    html += '<span class="alwr-screen-meta"><code>' + esc(info.variable) + '</code>' + badge + '</span>';
    html += '</span>';
    html += '</header>';

    if (!block) {
      html += '<div class="alwr-screen-absent">No screen for this was found in the interview ' +
        'or in the packages it includes, so its wording cannot be shown here.</div>';
      html += '</article>';
      return html;
    }

    var rendered = (Preview && typeof Preview.renderScreen === 'function')
      ? Preview.renderScreen(block.data || {}, ctx.previewOpts)
      : { html: '' };

    html += '<div class="alwr-screen-frame"><div class="container"><div class="row tab-content">';
    html += namespaceIds(rendered.html, num);
    html += '</div></div></div>';
    html += '</article>';
    return html;
  }

  function renderScreenStep(step, ctx) {
    return renderScreenCard(screenTitle(step, ctx.blockMap), ctx, {});
  }

  // ---------------------------------------------------------------------------
  // Screens AssemblyLine supplies
  // ---------------------------------------------------------------------------

  /* Some of the screens an interview asks for are not in the interview: an
   * AssemblyLine one answers them, and the YAML for it lives in an installed
   * package this editor cannot read. Those are the screens an author is least
   * likely to have checked and most likely to want to, so the common ones are
   * reproduced here from AssemblyLine's own questions -- rendered by the same
   * renderer as everything else, and badged so nobody goes looking for them in
   * the file.
   *
   * These are a fallback only. When AssemblyLine is installed, the report
   * reads its real YAML through /api/package-file and never gets here; this is
   * what a server without it falls back to, kept in step with that package's
   * ql_baseline.yml. */

  var AL_ADDRESS_ARGS = 'country_code=AL_DEFAULT_COUNTRY, default_state=AL_DEFAULT_STATE';

  var AL_STANDINS = [
    {
      // The court block owns every trial_court variable, including its own
      // address, so it is matched before the person patterns below.
      test: /^(?:trial_court|courts\[[^\]]*\])(?:[._].*)?$/,
      build: function () {
        return {
          title: 'Choose a court',
          question: [
            "% if al_form_type == 'starts_case':",
            'What court do you want to file in?',
            "% elif al_form_type == 'appeal':",
            'What is the name of the trial court your case was originally filed in?',
            '% else:',
            'What court is your case in?',
            '% endif',
          ].join('\n'),
          subquestion: [
            "% if not al_form_type == 'starts_case':",
            'Look at your court paperwork. Match the name listed there.',
            '% endif',
          ].join('\n'),
          fields: [
            { 'Name': 'trial_court_name' },
            { 'Address': 'trial_court_address.address', 'address autocomplete': true, 'required': false },
            { 'Suite': 'trial_court_address.unit', 'required': false },
            { 'City': 'trial_court_address.city', 'required': false },
            { 'State': 'trial_court_address.state', 'required': false },
            { 'Postal code': 'trial_court_address.zip', 'required': false },
          ],
        };
      },
    },
    {
      test: /^(.+?)\.name(?:\.(?:first|middle|last|suffix))?$/,
      build: function (match) {
        var subject = match[1];
        return {
          title: 'Name of ' + subjectPhrase(subject),
          question: 'What is ${ ' + subject + ".object_possessive('name') }?",
          fields: [{ code: subject + '.name_fields()' }],
        };
      },
    },
    {
      test: /^(.+?)\.address(?:\.(?:address|unit|city|state|zip|country))?$/,
      build: function (match) {
        var subject = match[1];
        return {
          title: 'Address of ' + subjectPhrase(subject),
          question: 'What is ${ ' + subject + ".possessive('address') }?",
          fields: [{ code: subject + '.address_fields(' + AL_ADDRESS_ARGS + ')' }],
        };
      },
    },
  ];

  /* The AssemblyLine screen that answers a variable, or null when none of the
   * ones reproduced here does. */
  function assemblyLineStandIn(variable) {
    var name = String(variable || '').trim();
    if (!name) return null;
    for (var i = 0; i < AL_STANDINS.length; i++) {
      var match = AL_STANDINS[i].test.exec(name);
      if (!match) continue;
      var spec = AL_STANDINS[i].build(match);
      var data = { question: spec.question, fields: spec.fields };
      if (spec.subquestion) data.subquestion = spec.subquestion;
      return { title: spec.title, block: { title: spec.title, data: data } };
    }
    return null;
  }

  function renderGatherStep(step, ctx) {
    var detail = describeGather(step, ctx);
    var noun = humanize(detail.noun).toLowerCase() || 'item';
    var labels = detail.attributes.map(attributeLabel);

    var sentence;
    if (labels.length) {
      sentence = 'For every ' + esc(noun) + ' in <code>' + esc(detail.listName) + '</code>, ' +
        'the interview asks for ' + esc(listSentence(labels)) + '.';
    } else {
      sentence = 'The interview loops over <code>' + esc(detail.listName) + '</code>, ' +
        'asking for each ' + esc(noun) + ' in turn.';
    }

    var body = '';
    detail.attributes.forEach(function (attr) {
      var target = detail.listName + '[i].' + attr.path;
      // Resolved the same way a screen step is, so a generic question or a
      // code block behind it reads the same here as it does anywhere else.
      var info = screenTitle({ invoke: target }, ctx.blockMap);
      if (!info.block) info.title = humanize(attr.head);
      body += renderScreenCard(info, ctx, { nested: true });
    });

    var isPeople = detail.source !== 'unknown';
    var html = '<section class="alwr-loop">';
    html += '<div class="alwr-loop-header"><span class="alwr-loop-tag">Repeats</span>' + sentence +
      ' The loop keeps going until the user says there is ' +
      (isPeople ? 'nobody' : 'nothing') + ' else to add.</div>';
    if (body) html += '<div class="alwr-loop-body">' + body + '</div>';
    html += '</section>';
    return html;
  }

  function renderProgressStep(step) {
    var pct = progressValue(step);
    if (pct === null) return '';
    return '<div class="alwr-progress" role="img" aria-label="Progress bar at ' + pct + ' percent">' +
      '<span class="alwr-progress-track"><span class="alwr-progress-fill" style="width:' + pct + '%"></span></span>' +
      '<span class="alwr-progress-label">Progress bar: ' + esc(String(pct)) + '%</span>' +
    '</div>';
  }

  /* A section step inside a branch cannot open a new part of the report the
   * way a top-level one does, so it is called out where it stands. */
  function renderInlineSectionStep(step, ctx) {
    var name = sectionLabel(step.value || step.summary || '', ctx.sectionLabels);
    if (!name) return '';
    return '<div class="alwr-inline-section">Navigation moves to <strong>' + esc(name) + '</strong></div>';
  }

  function renderBranch(label, condition, children, ctx, depth) {
    var body = renderStepList(children, ctx, depth + 1);
    if (!body) return '';
    var html = '<div class="alwr-branch" data-depth="' + (depth % 4) + '">';
    html += '<div class="alwr-branch-header"><span class="alwr-branch-label">' + esc(label) + '</span>';
    if (condition !== null) html += '<code class="alwr-branch-condition">' + esc(condition) + '</code>';
    html += '</div>';
    html += '<div class="alwr-branch-body">' + body + '</div>';
    html += '</div>';
    return html;
  }

  function renderConditionStep(step, ctx, depth) {
    var html = renderBranch('Only when', step.condition || step.summary || 'condition',
      step.children || [], ctx, depth);
    var node = step;
    while (node.has_else && (node.else_children || []).length > 0) {
      var elseCh = node.else_children;
      var isElif = elseCh.length === 1 && elseCh[0].kind === STEP_CONDITION;
      if (isElif) {
        var elifStep = elseCh[0];
        html += renderBranch('Otherwise, when', elifStep.condition || elifStep.summary || 'condition',
          elifStep.children || [], ctx, depth);
        node = elifStep;
      } else {
        html += renderBranch('Otherwise', null, elseCh, ctx, depth);
        break;
      }
    }
    return html;
  }

  /* Code that runs between screens is left out: it shows nothing to the person
   * filling the form, and this report is read to review what they see. */
  function renderStep(step, ctx, depth) {
    switch (step.kind || STEP_RAW) {
      case STEP_SCREEN:    return renderScreenStep(step, ctx);
      case STEP_GATHER:    return renderGatherStep(step, ctx);
      case STEP_SECTION:   return renderInlineSectionStep(step, ctx);
      case STEP_PROGRESS:  return renderProgressStep(step);
      case STEP_CONDITION: return renderConditionStep(step, ctx, depth || 0);
      default:             return '';
    }
  }

  function renderStepList(steps, ctx, depth) {
    var html = '';
    (steps || []).forEach(function (step) {
      html += renderStep(step, ctx, depth || 0);
    });
    return html;
  }

  /* Top-level ``section:`` steps split the report into parts, which is where a
   * printed copy gets its page breaks. A file with no sections gets one
   * unnamed part, and no heading for it. */
  function splitIntoParts(steps, labels) {
    var parts = [];
    var current = { title: null, steps: [] };
    (steps || []).forEach(function (step) {
      if ((step.kind || '') === STEP_SECTION) {
        if (current.steps.length || current.title !== null) parts.push(current);
        current = {
          title: sectionLabel(step.value || step.summary || '', labels) || 'Section',
          steps: [],
        };
        return;
      }
      current.steps.push(step);
    });
    if (current.steps.length || current.title !== null) parts.push(current);
    return parts;
  }

  function renderBody(steps, ctx) {
    var parts = splitIntoParts(steps, ctx.sectionLabels);
    var html = '';
    parts.forEach(function (part, index) {
      var anchor = 'alwr-part-' + (index + 1) + '-' + slug(part.title || 'start', 'part');
      if (part.title) {
        ctx.toc.push({ kind: 'section', title: part.title, anchor: anchor });
      }
      html += '<section class="alwr-part" id="' + anchor + '">';
      if (part.title) {
        html += '<h2 class="alwr-part-title">' +
          '<span class="alwr-part-tag">Section</span>' + esc(part.title) +
        '</h2>';
      }
      html += renderStepList(part.steps, ctx, 0);
      html += '</section>';
    });
    return html;
  }

  function renderToc(toc) {
    if (!toc.length) return '';
    var html = '<nav class="alwr-toc" aria-label="Screens in this interview"><h2 class="alwr-toc-title">Contents</h2><ol class="alwr-toc-list">';
    toc.forEach(function (entry) {
      if (entry.kind === 'section') {
        html += '<li class="alwr-toc-section"><a href="#' + entry.anchor + '">' + esc(entry.title) + '</a></li>';
      } else {
        html += '<li class="alwr-toc-screen' + (entry.missing ? ' alwr-toc-missing' : '') +
          (entry.nested ? ' alwr-toc-nested' : '') + '">' +
          '<a href="#' + entry.anchor + '"><span class="alwr-toc-num">' + entry.number + '</span>' +
          esc(entry.title) + '</a></li>';
      }
    });
    html += '</ol></nav>';
    return html;
  }

  // ---------------------------------------------------------------------------
  // Mermaid flowchart generation
  // ---------------------------------------------------------------------------

  /* Shapes carry their usual flowchart meaning, so the picture can be read
   * without a key: a screen the user sees is a box, a decision is a diamond,
   * a repeated sub-process (a list gather) is a boxed box, and code that runs
   * without the user is a hexagon. Sections become subgraphs, and a progress
   * bar change becomes a label on the arrow where it happens rather than a
   * node of its own. */
  var FLOW_STYLES = {
    light: {
      screen:   'fill:#e7f0ff,stroke:#2f6feb,stroke-width:1px,color:#0d2440',
      gather:   'fill:#e3f7f1,stroke:#127a63,stroke-width:1px,color:#08312a',
      decision: 'fill:#fff4e0,stroke:#b26b00,stroke-width:1px,color:#3d2400',
      code:     'fill:#f2ecff,stroke:#6f42c1,stroke-width:1px,color:#2a1a4d',
      raw:      'fill:#f6f7f8,stroke:#8b949e,stroke-width:1px,stroke-dasharray:4 3,color:#31363b',
      missing:  'fill:#ffffff,stroke:#adb5bd,stroke-width:1px,stroke-dasharray:5 4,color:#6c757d',
      terminal: 'fill:#212529,stroke:#212529,stroke-width:1px,color:#ffffff',
      section:  'fill:#f8f9fa,stroke:#ced4da,stroke-width:1px,color:#495057',
    },
    dark: {
      screen:   'fill:#16283f,stroke:#5b9dff,stroke-width:1px,color:#dce9ff',
      gather:   'fill:#12302a,stroke:#3fbfa2,stroke-width:1px,color:#d6f5ec',
      decision: 'fill:#3a2a09,stroke:#e0a53d,stroke-width:1px,color:#ffeecd',
      code:     'fill:#271e3d,stroke:#a98eea,stroke-width:1px,color:#e9e0ff',
      raw:      'fill:#22262b,stroke:#6c757d,stroke-width:1px,stroke-dasharray:4 3,color:#ced4da',
      missing:  'fill:#1b1f24,stroke:#6c757d,stroke-width:1px,stroke-dasharray:5 4,color:#adb5bd',
      terminal: 'fill:#e9ecef,stroke:#e9ecef,stroke-width:1px,color:#15181c',
      section:  'fill:#1b1f24,stroke:#495057,stroke-width:1px,color:#ced4da',
    },
  };

  function safeMermaid(text, maxLen) {
    var max = maxLen || 45;
    var s = String(text === undefined || text === null ? '' : text)
      .replace(/&/g, '#amp;')
      .replace(/"/g, '#quot;')
      .replace(/[<>]/g, function (c) { return c === '<' ? '#lt;' : '#gt;'; })
      .replace(/[\r\n]+/g, ' ')
      .trim();
    if (s.length > max) s = s.slice(0, max - 1) + '…';
    return s;
  }

  var SHAPES = {
    rect:       ['["',  '"]'],
    stadium:    ['(["', '"])'],
    diamond:    ['{"',  '"}'],
    hexagon:    ['{{"', '"}}'],
    subroutine: ['[["', '"]]'],
  };

  /* Walks the order the same way the report body does, and records what the
   * chart needs: nodes (in the section they belong to), edges, and the class
   * each node is drawn with. */
  function buildFlowModel(steps, blockMap, objects, labels) {
    var nodes = [];
    var edges = [];
    var sections = [];
    var counter = 0;
    var sectionCounter = 0;
    var currentSection = null;
    var pendingProgress = null;

    function addNode(label, sublabel, shape, cls) {
      var node = {
        id: 'N' + (++counter),
        label: label,
        sublabel: sublabel || '',
        shape: shape,
        cls: cls,
        section: currentSection,
      };
      nodes.push(node);
      if (currentSection) currentSection.nodes.push(node);
      return node;
    }

    /* A progress step annotates the arrow that leaves it, so the percentage
     * shows up beside the point where the bar actually moves. */
    function connect(inEdges, toId) {
      (inEdges || []).forEach(function (edge) {
        var label = edge.label || '';
        if (pendingProgress !== null) {
          label = label ? label + ' · ' + pendingProgress + '%' : pendingProgress + '%';
        }
        edges.push({ from: edge.from, to: toId, label: label });
      });
      pendingProgress = null;
    }

    function walk(list, inEdges) {
      var open = inEdges || [];
      (list || []).forEach(function (step) {
        var kind = step.kind || STEP_RAW;

        if (kind === STEP_SECTION) {
          var title = sectionLabel(step.value || step.summary || '', labels);
          currentSection = title
            ? { id: 'S' + (++sectionCounter), title: title, nodes: [] }
            : null;
          if (currentSection) sections.push(currentSection);
          return;
        }
        if (kind === STEP_PROGRESS) {
          var pct = progressValue(step);
          if (pct !== null) pendingProgress = pct;
          return;
        }

        var node;
        switch (kind) {
          case STEP_SCREEN:
            var info = screenTitle(step, blockMap);
            node = addNode(info.title, info.variable, 'rect', info.block ? 'screen' : 'missing');
            break;
          case STEP_GATHER:
            var gather = describeGather(step, { blockMap: blockMap, objects: objects || {} });
            var noun = humanize(gather.noun).toLowerCase() || 'item';
            node = addNode('For every ' + noun,
              listSentence(gather.attributes.map(attributeLabel)) || gather.listName,
              'subroutine', 'gather');
            break;
          case STEP_FUNCTION:
            node = addNode(step.invoke || step.summary || 'function()', '', 'hexagon', 'code');
            break;
          case STEP_CONDITION:
            node = addNode(step.condition || step.summary || 'condition', '', 'diamond', 'decision');
            break;
          default:
            node = addNode(trunc(String(step.code || step.summary || '…').split('\n')[0], 40),
              '', 'hexagon', 'raw');
            break;
        }

        connect(open, node.id);

        if (kind === STEP_CONDITION) {
          var yes = walk(step.children || [], [{ from: node.id, label: 'yes' }]);
          var no;
          if (step.has_else && (step.else_children || []).length > 0) {
            no = walk(step.else_children, [{ from: node.id, label: 'no' }]);
          } else {
            no = [{ from: node.id, label: 'no' }];
          }
          open = yes.concat(no);
        } else {
          open = [{ from: node.id, label: '' }];
        }
      });
      return open;
    }

    var start = { id: 'N0', label: 'Start', sublabel: '', shape: 'stadium', cls: 'terminal', section: null };
    nodes.push(start);
    var tails = walk(steps, [{ from: start.id, label: '' }]);
    var end = { id: 'NZ', label: 'Interview complete', sublabel: '', shape: 'stadium', cls: 'terminal', section: null };
    nodes.push(end);
    connect(tails, end.id);

    return { nodes: nodes, edges: edges, sections: sections };
  }

  function buildMermaidSource(steps, options) {
    var opts = options || {};
    var blockMap = opts.blockMap || {};
    var palette = FLOW_STYLES[opts.theme === 'dark' ? 'dark' : 'light'];
    var model = buildFlowModel(steps || [], blockMap, opts.objects || {}, opts.sections || {});
    var lines = ['flowchart TD'];

    function nodeLine(node) {
      var shape = SHAPES[node.shape] || SHAPES.rect;
      var label = safeMermaid(node.label, 52);
      if (node.sublabel && node.sublabel !== node.label) {
        label += '<br><small>' + safeMermaid(node.sublabel, 40) + '</small>';
      }
      return '    ' + node.id + shape[0] + label + shape[1];
    }

    model.nodes.forEach(function (node) {
      if (!node.section) lines.push(nodeLine(node));
    });

    model.sections.forEach(function (section) {
      lines.push('    subgraph ' + section.id + '["' + safeMermaid(section.title, 40) + '"]');
      lines.push('    direction TB');
      section.nodes.forEach(function (node) { lines.push('    ' + nodeLine(node)); });
      lines.push('    end');
    });

    model.edges.forEach(function (edge) {
      if (edge.label) {
        lines.push('    ' + edge.from + ' -->|"' + safeMermaid(edge.label, 24) + '"| ' + edge.to);
      } else {
        lines.push('    ' + edge.from + ' --> ' + edge.to);
      }
    });

    var byClass = {};
    model.nodes.forEach(function (node) {
      (byClass[node.cls] = byClass[node.cls] || []).push(node.id);
    });
    Object.keys(byClass).forEach(function (cls) {
      if (!palette[cls]) return;
      lines.push('    classDef ' + cls + ' ' + palette[cls]);
      lines.push('    class ' + byClass[cls].join(',') + ' ' + cls);
    });
    model.sections.forEach(function (section) {
      lines.push('    style ' + section.id + ' ' + palette.section);
    });

    return lines.join('\n');
  }

  var LEGEND = [
    ['rect',       'screen',   'A screen the user sees'],
    ['subroutine', 'gather',   'Repeats for each item in a list'],
    ['diamond',    'decision', 'A branch in the interview logic'],
    ['hexagon',    'code',     'Code that runs without the user'],
    ['stadium',    'terminal', 'Start and finish'],
  ];

  function legendShapeSvg(shape) {
    var body;
    switch (shape) {
      case 'diamond':
        body = '<polygon points="20,3 37,13 20,23 3,13"/>'; break;
      case 'stadium':
        body = '<rect x="2" y="4" width="36" height="18" rx="9"/>'; break;
      case 'hexagon':
        body = '<polygon points="9,4 31,4 38,13 31,22 9,22 2,13"/>'; break;
      case 'subroutine':
        body = '<rect x="2" y="4" width="36" height="18"/><line x1="8" y1="4" x2="8" y2="22"/><line x1="32" y1="4" x2="32" y2="22"/>'; break;
      default:
        body = '<rect x="2" y="4" width="36" height="18" rx="2"/>'; break;
    }
    return '<svg viewBox="0 0 40 26" width="40" height="26" aria-hidden="true">' + body + '</svg>';
  }

  function renderLegend() {
    var html = '<ul class="alwr-legend">';
    LEGEND.forEach(function (row) {
      html += '<li class="alwr-legend-item alwr-legend-' + row[1] + '">' +
        legendShapeSvg(row[0]) + '<span>' + esc(row[2]) + '</span></li>';
    });
    html += '<li class="alwr-legend-item alwr-legend-progress">' +
      '<svg viewBox="0 0 40 26" width="40" height="26" aria-hidden="true">' +
        '<line x1="20" y1="2" x2="20" y2="24"/>' +
        '<polygon points="20,24 16,16 24,16" class="alwr-legend-head"/>' +
      '</svg>' +
      '<span>A percentage on an arrow is where the progress bar moves</span></li>';
    html += '</ul>';
    return html;
  }

  // ---------------------------------------------------------------------------
  // Report CSS
  // ---------------------------------------------------------------------------

  /* Docassemble's own stylesheets are loaded into this document whole, so the
   * screens are right; every rule here is namespaced to .alwr- so the report
   * chrome around them does not fight those stylesheets, and each colour goes
   * through a variable so the dark theme is one block rather than a second
   * copy of the sheet. */
  var REPORT_CSS = [
    ':root{--alwr-page:#eef0f2;--alwr-surface:#fff;--alwr-surface-2:#f5f6f8;--alwr-border:#dde1e6;--alwr-text:#1f2328;--alwr-muted:#636c76;--alwr-accent:#2f6feb;--alwr-shadow:0 1px 2px rgba(31,35,40,.08)}',
    '[data-bs-theme="dark"]{--alwr-page:#15181c;--alwr-surface:#1e2227;--alwr-surface-2:#22262b;--alwr-border:#343a40;--alwr-text:#e6edf3;--alwr-muted:#9aa4ae;--alwr-accent:#5b9dff;--alwr-shadow:none}',

    'body{background:var(--alwr-page)}',
    '.alwr-report{max-width:1120px;margin:0 auto;padding:1.5rem 1.25rem 4rem;color:var(--alwr-text);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}',

    /* Toolbar */
    '.alwr-toolbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;background:var(--alwr-surface);border:1px solid var(--alwr-border);border-radius:10px;padding:.6rem .9rem;margin-bottom:1.5rem;box-shadow:var(--alwr-shadow)}',
    '.alwr-btn{font:inherit;font-size:.85rem;font-weight:600;color:#fff;background:var(--alwr-accent);border:none;border-radius:7px;padding:.45rem .9rem;cursor:pointer}',
    '.alwr-btn:hover{filter:brightness(1.06)}',

    /* Masthead */
    '.alwr-masthead{margin-bottom:1.5rem}',
    'h1.alwr-title{font-size:1.75rem;font-weight:700;margin:0 0 .3rem;color:var(--alwr-text)}',
    'p.alwr-subtitle{color:var(--alwr-muted);font-size:.9rem;margin:0 0 .75rem}',
    '.alwr-counts{display:flex;gap:.5rem;flex-wrap:wrap;list-style:none;margin:0;padding:0}',
    '.alwr-count{background:var(--alwr-surface);border:1px solid var(--alwr-border);border-radius:99px;padding:.15rem .7rem;font-size:.8rem;color:var(--alwr-muted)}',
    '.alwr-count strong{color:var(--alwr-text);font-weight:700}',

    /* Contents */
    '.alwr-toc{background:var(--alwr-surface);border:1px solid var(--alwr-border);border-radius:10px;padding:1rem 1.25rem;margin-bottom:1.75rem;box-shadow:var(--alwr-shadow)}',
    '.alwr-toc-title{font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;color:var(--alwr-muted);margin:0 0 .6rem;font-weight:700}',
    '.alwr-toc-list{list-style:none;margin:0;padding:0;columns:2;column-gap:2rem}',
    '.alwr-toc-list li{break-inside:avoid;margin-bottom:.15rem}',
    '.alwr-toc a{color:var(--alwr-text);text-decoration:none;font-size:.88rem;display:flex;gap:.5rem;align-items:baseline}',
    '.alwr-toc a:hover{text-decoration:underline}',
    '.alwr-toc-num{color:var(--alwr-muted);font-size:.75rem;font-variant-numeric:tabular-nums;min-width:1.4em;text-align:right;flex:none}',
    '.alwr-toc-section{margin-top:.7rem}',
    '.alwr-toc-section a{font-weight:700;font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:var(--alwr-muted)}',
    '.alwr-toc-missing a{color:var(--alwr-muted);font-style:italic}',
    '.alwr-toc-nested{padding-left:1.1rem}',

    /* Flowchart */
    '.alwr-flow{background:var(--alwr-surface);border:1px solid var(--alwr-border);border-radius:10px;margin-bottom:2.5rem;box-shadow:var(--alwr-shadow);overflow:hidden}',
    '.alwr-flow>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:.5rem;padding:.75rem 1.25rem;font-weight:700;font-size:1rem;border-bottom:1px solid var(--alwr-border)}',
    '.alwr-flow>summary::-webkit-details-marker{display:none}',
    '.alwr-flow-chevron{transition:transform .15s;color:var(--alwr-muted)}',
    '.alwr-flow[open] .alwr-flow-chevron{transform:rotate(90deg)}',
    '.alwr-flow-body{padding:1.25rem}',
    '.alwr-mermaid-wrap{overflow-x:auto;text-align:center}',
    '.alwr-mermaid-wrap svg{max-width:100%;height:auto}',
    '.alwr-mermaid-wrap small{opacity:.65;font-size:.72em}',
    '.alwr-mermaid-wrap .cluster-label{font-weight:700}',
    '.alwr-mermaid-fallback{display:none;background:var(--alwr-surface-2);border:1px solid var(--alwr-border);border-radius:8px;padding:1rem;font-size:.8rem;white-space:pre-wrap;text-align:left;color:var(--alwr-text)}',
    '.alwr-flow[data-mermaid="failed"] .alwr-mermaid-fallback{display:block}',
    '.alwr-flow[data-mermaid="failed"] .alwr-mermaid-wrap{display:none}',
    '.alwr-legend{list-style:none;display:flex;flex-wrap:wrap;gap:.4rem 1.4rem;margin:1.25rem 0 0;padding:1rem 0 0;border-top:1px solid var(--alwr-border)}',
    '.alwr-legend-item{display:flex;align-items:center;gap:.5rem;font-size:.8rem;color:var(--alwr-muted)}',
    '.alwr-legend svg{flex:none;fill:var(--alwr-surface-2);stroke:var(--alwr-muted);stroke-width:1.5}',
    '.alwr-legend-screen svg{fill:#e7f0ff;stroke:#2f6feb}',
    '.alwr-legend-gather svg{fill:#e3f7f1;stroke:#127a63}',
    '.alwr-legend-decision svg{fill:#fff4e0;stroke:#b26b00}',
    '.alwr-legend-code svg{fill:#f2ecff;stroke:#6f42c1}',
    '.alwr-legend-terminal svg{fill:#212529;stroke:#212529}',
    '.alwr-legend-progress .alwr-legend-head{fill:var(--alwr-muted);stroke:none}',

    /* Parts */
    '.alwr-part{margin:0 0 1rem}',
    '.alwr-part-title{display:flex;align-items:baseline;gap:.6rem;font-size:1.25rem;font-weight:700;margin:2rem 0 1rem;padding-bottom:.5rem;border-bottom:2px solid var(--alwr-border);color:var(--alwr-text)}',
    '.alwr-part-tag{font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:#fff;background:var(--alwr-accent);border-radius:4px;padding:.15rem .45rem;font-weight:700}',

    /* Screen cards */
    '.alwr-screen{background:var(--alwr-surface);border:1px solid var(--alwr-border);border-radius:10px;margin:0 0 1.5rem;overflow:hidden;box-shadow:var(--alwr-shadow);break-inside:avoid}',
    '.alwr-screen-header{display:flex;align-items:flex-start;gap:.7rem;padding:.6rem .9rem;background:var(--alwr-surface-2);border-bottom:1px solid var(--alwr-border)}',
    '.alwr-screen-num{flex:none;min-width:1.6rem;height:1.6rem;border-radius:99px;background:var(--alwr-accent);color:#fff;font-size:.78rem;font-weight:700;display:flex;align-items:center;justify-content:center;padding:0 .4rem}',
    '.alwr-screen-heading{display:flex;flex-direction:column;gap:.1rem;min-width:0}',
    '.alwr-screen-name{font-weight:600;font-size:.95rem;line-height:1.3;color:var(--alwr-text)}',
    '.alwr-screen-var{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.75rem;color:var(--alwr-muted);word-break:break-all}',
    '.alwr-screen-meta{display:flex;align-items:baseline;gap:.5rem;flex-wrap:wrap}',
    '.alwr-screen-meta code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.75rem;color:var(--alwr-muted);background:none;padding:0}',
    '.alwr-screen-badge{font-size:.68rem;letter-spacing:.04em;text-transform:uppercase;font-weight:700;color:var(--alwr-muted);background:var(--alwr-page);border:1px solid var(--alwr-border);border-radius:99px;padding:.05rem .45rem}',
    '.alwr-screen-frame{background:var(--alwr-surface);padding:1.25rem 0 1.75rem}',
    '.alwr-screen-missing{border-style:dashed}',
    '.alwr-screen-absent{padding:1rem .9rem;font-size:.85rem;color:var(--alwr-muted)}',
    '.alwr-empty{color:var(--alwr-muted)}',
    '.alwr-css-warning{background:#f8d7da;color:#58151c;border:1px solid #f5c2c7;border-radius:8px;padding:.75rem .9rem;margin-bottom:1rem;font-size:.85rem}',

    /* A repeating list: what it asks, and the screens it asks it on */
    '.alwr-loop{border:1px solid var(--alwr-border);border-left:3px solid #127a63;border-radius:10px;background:var(--alwr-surface);margin:0 0 1.5rem;overflow:hidden}',
    '.alwr-loop-header{padding:.6rem .9rem;font-size:.88rem;line-height:1.5;color:var(--alwr-text)}',
    '.alwr-loop-header code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.82rem;color:var(--alwr-muted);background:none;padding:0}',
    '.alwr-loop-tag{font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;font-weight:700;color:#127a63;margin-right:.5rem}',
    '.alwr-loop-body{padding:0 .9rem .9rem}',
    '.alwr-screen-nested{margin-bottom:.9rem}',
    '.alwr-loop-body .alwr-screen:last-child{margin-bottom:0}',
    '.alwr-inline-section{font-size:.85rem;color:var(--alwr-muted);margin:0 0 1.25rem}',
    '.alwr-progress{display:flex;align-items:center;gap:.6rem;margin:0 0 1.5rem;break-inside:avoid}',
    '.alwr-progress-track{flex:1 1 auto;height:5px;border-radius:3px;background:var(--alwr-border);overflow:hidden}',
    '.alwr-progress-fill{display:block;height:100%;background:var(--alwr-accent)}',
    '.alwr-progress-label{flex:none;font-size:.74rem;color:var(--alwr-muted)}',

    /* Branches */
    '.alwr-branch{border-left:2px solid var(--alwr-border);padding-left:1rem;margin:0 0 1rem}',
    '.alwr-branch[data-depth="0"]{border-left-color:#2f6feb}',
    '.alwr-branch[data-depth="1"]{border-left-color:#6f42c1}',
    '.alwr-branch[data-depth="2"]{border-left-color:#d63384}',
    '.alwr-branch[data-depth="3"]{border-left-color:#fd7e14}',
    '.alwr-branch-header{display:flex;align-items:baseline;gap:.45rem;flex-wrap:wrap;font-size:.85rem;margin-bottom:.75rem}',
    '.alwr-branch-label{font-weight:600;color:var(--alwr-text)}',
    '.alwr-branch-condition{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.8rem;color:var(--alwr-muted);background:var(--alwr-surface-2);border-radius:4px;padding:.05em .4em}',
    '.alwr-branch-body{padding-top:.25rem}',

    /* Print: paper, not screen. Each section starts a page, nothing that can
       fit on one page is allowed to straddle two, and the chrome goes away. */
    '@media print{',
    ':root{--alwr-page:#fff;--alwr-shadow:none}',
    'body{background:#fff}',
    '.alwr-report{max-width:none;padding:0}',
    '.alwr-no-print{display:none!important}',
    '.alwr-toc{break-inside:avoid}',
    '.alwr-flow{border:none;break-before:page;break-after:page}',
    '.alwr-mermaid-wrap{overflow:visible}',
    '.alwr-flow>summary{display:none}',
    '.alwr-flow-body{padding:0}',
    '.alwr-part+.alwr-part{break-before:page}',
    '.alwr-part-title{margin-top:0}',
    '.alwr-screen,.alwr-progress,.alwr-branch,.alwr-loop-header{break-inside:avoid}',
    '.alwr-screen{box-shadow:none}',
    '.alwr-toc a{color:#000}',
    '}',
    '@page{margin:14mm}',
  ].join('\n');

  /* The preview stylesheet, minus its body rule: in the preview that rule
   * paints the iframe, here it would paint the report page. */
  var PREVIEW_CSS = [
    '.dapv-mako,.dapv-mako-line code{background:rgba(13,110,253,.08);color:#0a58ca;border-radius:3px;padding:0 .25em;font-size:.9em}',
    '[data-dapv-condition]{box-shadow:inset 2px 0 0 rgba(108,117,125,.5)}',
    '[data-dapv-condition]::before{content:attr(data-dapv-condition);display:block;flex:0 0 100%;width:100%;font-size:.72rem;font-family:monospace;color:#6c757d;margin-bottom:.2rem;padding-left:.6rem}',
    '.al_collapse_template a span.pdcaretopen{display:inline}',
    '.al_collapse_template a span.pdcaretclosed{display:none}',
    '.al_collapse_template a.collapsed .pdcaretopen{display:none}',
    '.al_collapse_template a.collapsed .pdcaretclosed{display:inline}',
  ].join('\n');

  /* The same widget set-up the preview iframe runs, plus the things only a
   * many-screen document needs: links inside a screen must not navigate away
   * from the report, and the print button waits for Mermaid to finish so the
   * chart is on the paper. */
  var RUNTIME_SCRIPT = [
    '(function(){"use strict";',
    'if (window.jQuery && jQuery.fn.labelauty) {',
    '  jQuery(".da-to-labelauty").labelauty({class: "labelauty da-active-invisible dafullwidth"});',
    '  jQuery(".da-to-labelauty-icon").labelauty({label: false});',
    '}',
    'if (window.bootstrap && bootstrap.Popover) {',
    '  Array.prototype.forEach.call(document.querySelectorAll(\'[data-bs-toggle="popover"]\'), function (el) { new bootstrap.Popover(el, {html: true}); });',
    '}',
    'document.addEventListener("submit", function (e) { e.preventDefault(); });',
    'document.addEventListener("click", function (e) {',
    '  var link = e.target && e.target.closest ? e.target.closest(".alwr-screen-frame a") : null;',
    '  if (link) e.preventDefault();',
    '});',
    'var printBtn = document.getElementById("alwr-print");',
    'if (printBtn) printBtn.addEventListener("click", function () { window.print(); });',
    'var missing = document.documentElement.getAttribute("data-dapv-css-missing");',
    'if (missing) {',
    '  var warning = document.createElement("div");',
    '  warning.className = "alwr-css-warning";',
    '  warning.textContent = "This report could not load " + missing + ", so it is not showing Docassemble\'s real styling.";',
    '  var report = document.querySelector(".alwr-report");',
    '  if (report) report.insertBefore(warning, report.firstChild);',
    '}',
    '})();',
  ].join('\n');

  /* Mermaid centres a subgraph's title at the top of its box, which is exactly
   * where the arrow into the section's first screen arrives -- the title ends
   * up struck through by the arrow, and crowded against the node under it.
   * Once the chart is drawn, each title is moved to its box's top-left corner,
   * the way a fieldset legend sits, where nothing is routed. */
  var MERMAID_SCRIPT = [
    '(function(){"use strict";',
    'var flow = document.querySelector(".alwr-flow");',
    'function fail(){ if (flow) flow.setAttribute("data-mermaid", "failed"); }',
    'if (!window.mermaid) { fail(); return; }',
    '',
    'function moveSubgraphTitles(){',
    '  var svg = document.querySelector(".alwr-mermaid-wrap svg");',
    '  if (!svg || !svg.viewBox || !svg.viewBox.baseVal || !svg.viewBox.baseVal.width) return;',
    '  var scale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;',
    '  if (!scale || !isFinite(scale)) return;',
    '  Array.prototype.forEach.call(svg.querySelectorAll("g.cluster"), function (cluster) {',
    '    var box = cluster.querySelector("rect");',
    '    var label = cluster.querySelector(".cluster-label");',
    '    if (!box || !label) return;',
    '    var boxRect = box.getBoundingClientRect();',
    '    var labelRect = label.getBoundingClientRect();',
    '    if (!boxRect.width || !labelRect.width) return;',
    '    if (labelRect.width + 24 > boxRect.width) return;',
    '    var shift = (boxRect.left + 12 - labelRect.left) / scale;',
    '    var current = /translate\\(\\s*(-?[\\d.]+)[ ,]+(-?[\\d.]+)/.exec(label.getAttribute("transform") || "");',
    '    var x = current ? parseFloat(current[1]) : 0;',
    '    var y = current ? parseFloat(current[2]) : 0;',
    '    label.setAttribute("transform", "translate(" + (x + shift) + ", " + y + ")");',
    '  });',
    '}',
    '',
    'try {',
    '  mermaid.initialize({startOnLoad:false, theme:"__THEME__", securityLevel:"loose",',
    '    flowchart:{htmlLabels:true, useMaxWidth:true, curve:"basis", nodeSpacing:35, rankSpacing:50,',
    '      padding:16, subGraphTitleMargin:{top:10, bottom:22}},',
    '    maxTextSize:200000, maxEdges:2000});',
    '  mermaid.run({querySelector:".mermaid"})',
    '    .then(function(){ try { moveSubgraphTitles(); } catch (e) {} })',
    '    .catch(fail);',
    '} catch (e) { fail(); }',
    '})();',
  ].join('\n');

  // ---------------------------------------------------------------------------
  // Main entry point
  // ---------------------------------------------------------------------------

  function countSteps(steps, tally) {
    (steps || []).forEach(function (step) {
      var kind = step.kind || STEP_RAW;
      tally[kind] = (tally[kind] || 0) + 1;
      if (kind === STEP_CONDITION) {
        countSteps(step.children || [], tally);
        countSteps(step.else_children || [], tally);
      }
    });
    return tally;
  }

  function buildReport(orderSteps, blocks, options) {
    var opts = options || {};
    var steps = orderSteps || [];
    var title = opts.title || 'Interview flow report';
    var theme = opts.theme === 'dark' ? 'dark' : 'light';
    var origin = opts.origin || '';
    var mermaidCdn = absoluteUrl(opts.mermaidCdn || 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js', origin);

    var blockMap = buildBlockMap(blocks);

    var ctx = {
      blockMap: blockMap,
      objects: objectDeclarations(blocks),
      sectionLabels: sectionLabels(blocks),
      previewOpts: {
        labelLayout:         opts.labelLayout,
        backButtonLabel:     opts.backButtonLabel,
        continueButtonLabel: opts.continueLabel,
        interview:           opts.interview,
        notes:               [],
      },
      screenCount: 0,
      toc: [],
    };

    var bodyHtml = renderBody(steps, ctx);
    if (!ctx.screenCount && !steps.length) {
      bodyHtml = '<p class="alwr-empty">This interview has no screens in its interview order yet.</p>';
    }

    var tally = countSteps(steps, {});
    function count(number, singular, plural) {
      if (!number) return '';
      return '<li class="alwr-count"><strong>' + number + '</strong> ' +
        (number === 1 ? singular : plural) + '</li>';
    }
    var counts = '<ul class="alwr-counts">' +
      count(ctx.screenCount, 'screen', 'screens') +
      count(tally[STEP_SECTION], 'section', 'sections') +
      count(tally[STEP_CONDITION], 'branch', 'branches') +
      count(tally[STEP_GATHER], 'repeating list', 'repeating lists') +
    '</ul>';

    var mermaidSrc = buildMermaidSource(steps, {
      blockMap: blockMap, objects: ctx.objects, sections: ctx.sectionLabels, theme: theme,
    });

    var flowchartHtml =
      '<details class="alwr-flow" open>' +
        '<summary>' +
          '<svg class="alwr-flow-chevron" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">' +
            '<path d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06z"/>' +
          '</svg>' +
          'How the interview flows' +
        '</summary>' +
        '<div class="alwr-flow-body">' +
          '<div class="alwr-mermaid-wrap"><pre class="mermaid">' + esc(mermaidSrc) + '</pre></div>' +
          '<pre class="alwr-mermaid-fallback">' + esc(mermaidSrc) + '</pre>' +
          renderLegend() +
        '</div>' +
      '</details>';

    var assets = {};
    var previewDefaults = (Preview && Preview.DEFAULT_ASSETS) ? Preview.DEFAULT_ASSETS : {};
    Object.keys(previewDefaults).forEach(function (k) { assets[k] = previewDefaults[k]; });
    Object.keys(opts.assets || {}).forEach(function (k) { assets[k] = opts.assets[k]; });
    Object.keys(assets).forEach(function (k) { assets[k] = absoluteUrl(assets[k], origin); });

    var head = '';
    head += '<meta charset="utf-8">\n';
    head += '<meta name="viewport" content="width=device-width, initial-scale=1">\n';
    head += '<title>' + esc(title) + '</title>\n';
    if (assets.fontAwesome) head += '<script defer src="' + esc(assets.fontAwesome) + '"><\/script>\n';
    if (assets.bootstrapCss) head += '<link rel="stylesheet" href="' + esc(assets.bootstrapCss) + '">\n';
    if (assets.bundleCss) {
      head += '<link rel="stylesheet" href="' + esc(assets.bundleCss) +
        '" onerror="document.documentElement.setAttribute(\'data-dapv-css-missing\', \'' +
        esc(assets.bundleCss) + '\')">\n';
    }
    (opts.extraCss || []).forEach(function (href) {
      head += '<link rel="stylesheet" href="' + esc(absoluteUrl(href, origin)) + '">\n';
    });
    head += '<style>\n' + PREVIEW_CSS + '\n</style>\n';
    head += '<style>\n' + REPORT_CSS + '\n</style>\n';

    var scripts = '';
    if (assets.jquery && assets.labelauty) {
      scripts += '<script src="' + esc(assets.jquery) + '"><\/script>\n';
      scripts += '<script src="' + esc(assets.labelauty) + '"><\/script>\n';
    }
    if (assets.bootstrapJs) scripts += '<script src="' + esc(assets.bootstrapJs) + '"><\/script>\n';
    scripts += '<script src="' + esc(mermaidCdn) + '" onerror="var f=document.querySelector(\'.alwr-flow\'); if (f) f.setAttribute(\'data-mermaid\',\'failed\');"><\/script>\n';
    scripts += '<script>\n' + RUNTIME_SCRIPT + '\n<\/script>\n';
    scripts += '<script>\n' + MERMAID_SCRIPT.replace('__THEME__', theme) + '\n<\/script>\n';

    var dateStr = (function () {
      try {
        return new Date().toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
      } catch (e) { return new Date().toDateString(); }
    })();

    var subtitle = opts.subtitle
      ? opts.subtitle + ' · ' + dateStr
      : 'Every screen in interview order, as the interview would show it · ' + dateStr;

    var body = '';
    body += '<div class="alwr-report">\n';
    body += '<div class="alwr-toolbar alwr-no-print">' +
      '<button type="button" class="alwr-btn" id="alwr-print">Print or save as PDF</button>' +
    '</div>\n';
    body += '<header class="alwr-masthead">';
    body += '<h1 class="alwr-title">' + esc(title) + '</h1>';
    body += '<p class="alwr-subtitle">' + esc(subtitle) + '</p>';
    body += counts;
    body += '</header>\n';
    body += renderToc(ctx.toc) + '\n';
    body += flowchartHtml + '\n';
    // Docassemble keys some of its rules to #dabody, so the screens live
    // inside one, and the report chrome stays outside it.
    body += '<div id="dabody">\n' + bodyHtml + '\n</div>\n';
    body += '</div>\n';

    return '<!DOCTYPE html>\n' +
      '<html lang="en" data-bs-theme="' + theme + '">\n' +
      '<head>\n' + head + '</head>\n' +
      '<body class="dabody">\n' + body + scripts + '</body>\n' +
      '</html>\n';
  }

  return {
    buildReport: buildReport,
    absoluteUrl: absoluteUrl,
    buildMermaidSource: buildMermaidSource,
    buildFlowModel: buildFlowModel,
    buildBlockMap: buildBlockMap,
    findBlock: findBlock,
    screenTitle: screenTitle,
    assemblyLineStandIn: assemblyLineStandIn,
    findGenericBlock: findGenericBlock,
    substituteSubject: substituteSubject,
    followToScreen: followToScreen,
    describeGather: describeGather,
    objectDeclarations: objectDeclarations,
    attributesFromCode: attributesFromCode,
    splitIntoParts: splitIntoParts,
    sectionLabels: sectionLabels,
  };
});
