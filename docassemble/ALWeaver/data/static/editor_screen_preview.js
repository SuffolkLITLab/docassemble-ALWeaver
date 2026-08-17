/* High-fidelity screen preview for the graphical editor.
 *
 * Renders a question block as the markup Docassemble's own
 * ``standardformatter`` would emit, so the preview can be styled with
 * Docassemble's real stylesheets (``/static/app/bundle.css``) and finished by
 * Docassemble's real labelauty plugin.  Everything here is deliberately
 * framework-free so it can be unit-tested under Node.
 *
 * The markup mirrors docassemble.base.standardformatter as of 1.9.13 and
 * 1.10.7; the two versions emit identical field HTML (1.10 only renamed
 * internals), and ship byte-identical app.css / labelauty assets, so one
 * renderer serves both.
 */
(function (root, factory) {
  'use strict';
  var preview = factory();
  if (typeof module === 'object' && module.exports) module.exports = preview;
  root.ALWeaverScreenPreview = preview;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // -------------------------------------------------------------------------
  // Small helpers
  // -------------------------------------------------------------------------

  function esc(text) {
    return String(text === undefined || text === null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function attr(text) {
    return esc(text);
  }

  /* Put an already-rendered HTML fragment into an attribute value. Only the
   * quote needs escaping here — running it through esc() again would turn the
   * entities the fragment already contains into visible &amp;quot; text. */
  function attrHtml(html) {
    return String(html === undefined || html === null ? '' : html).replace(/"/g, '&quot;');
  }

  /* Docassemble's Markdown lets raw HTML through, and interviews lean on that
   * for Bootstrap alerts, cards and the like, so the preview passes it through
   * too. Scripts and inline event handlers are the exception: the preview frame
   * shares an origin with the editor, and an author debugging a screen should
   * not be able to reach into their own unsaved work by accident. */
  var SCRIPT_PATTERNS = [
    /<script\b[\s\S]*?<\/script\s*>/gi,
    /<script\b[^>]*>/gi,
    /\son[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi,
  ];

  function sanitizeHtml(html, report) {
    var out = String(html === undefined || html === null ? '' : html);
    SCRIPT_PATTERNS.forEach(function (pattern) {
      out = out.replace(pattern, function () {
        if (report) report.scriptRemoved = true;
        return '';
      });
    });
    out = out.replace(
      /\s(href|src)\s*=\s*(?:"\s*javascript:[^"]*"|'\s*javascript:[^']*'|javascript:[^\s>]*)/gi,
      function (_, name) {
        if (report) report.scriptRemoved = true;
        return ' ' + name + '=""';
      }
    );
    return out;
  }

  // -------------------------------------------------------------------------
  // Mako widgets
  //
  // A handful of expressions turn into substantial screen furniture in a real
  // interview — a document table, a collapse, a PDF thumbnail. Showing those as
  // ${ code } tells an author nothing about the screen, so each one renders as
  // the markup its library emits, filled from the interview where we can read
  // it and with obvious placeholder content where we cannot.
  // -------------------------------------------------------------------------

  /* Docassemble's ``:name:`` icon markup (filter.get_icon_html). A bare name
   * takes the default `fa-solid` prefix; `fas-fa-`, `far-fa-` and `fab-fa-`
   * choose solid, regular and brands. Docassemble only substitutes these when
   * the server sets `default icons: font awesome`, which is what AssemblyLine's
   * README tells you to configure, so the preview assumes it. */
  var ICON_PREFIXES = { fas: 'fa-solid', far: 'fa-regular', fab: 'fa-brands' };

  function iconHtml(name) {
    var text = String(name);
    var prefix = 'fa-solid';
    var prefixed = text.match(/^(fa[a-z])-fa-(.*)$/);
    if (prefixed) {
      prefix = ICON_PREFIXES[prefixed[1]] || prefixed[1];
      text = prefixed[2];
    }
    return '<i class="' + prefix + ' fa-' + esc(text) + '"></i>';
  }

  function _iconSubstitute(text) {
    return text.replace(/:([A-Za-z][A-Za-z0-9_-]+):/g, function (whole, name) {
      return iconHtml(name);
    });
  }

  /* Substitute only in text, never inside a tag, so URLs, class lists and data
   * attributes cannot be mangled by a stray colon pair. */
  function applyIconMarkup(html) {
    var text = String(html === undefined || html === null ? '' : html);
    var out = '';
    var index = 0;
    while (index < text.length) {
      var open = text.indexOf('<', index);
      if (open === -1) {
        out += _iconSubstitute(text.slice(index));
        break;
      }
      out += _iconSubstitute(text.slice(index, open));
      var close = text.indexOf('>', open);
      if (close === -1) {
        out += text.slice(open);
        break;
      }
      out += text.slice(open, close + 1);
      index = close + 1;
    }
    return out;
  }

  /* Each widget says what, if anything, it had to invent, so the preview can
   * name it rather than let filler pass for the real thing. */
  var PLACEHOLDER_NOTES = {
    thumbnail: 'The document thumbnail is a stand-in. The running interview shows the first page of the real PDF.',
    documents: 'This bundle’s documents could not be read from the interview, so the table shows two stand-in rows.',
    template: 'The collapsed section shows filler text because its template block is not in this file.',
    rows: 'Table rows are examples. The running interview shows one row per item the list has gathered.',
    table: 'This table’s block is not in this file, so its columns are not known.',
  };

  function _recordPlaceholder(report, kind) {
    if (!report || !kind) return;
    if (!report.placeholders) report.placeholders = [];
    if (report.placeholders.indexOf(kind) === -1) report.placeholders.push(kind);
  }

  /* Collect a ``${ ... }`` that may run over several lines, so a call written
   * with one keyword argument per line is still recognised. */
  function _gatherMakoExpression(lines, startIndex) {
    var text = '';
    for (var i = startIndex; i < lines.length; i++) {
      text += (i > startIndex ? '\n' : '') + lines[i];
      var depth = 0;
      var closed = -1;
      for (var c = 0; c < text.length; c++) {
        if (text[c] === '{') depth++;
        else if (text[c] === '}') {
          depth--;
          if (depth === 0) { closed = c; break; }
        }
      }
      if (closed !== -1) {
        if (text.slice(closed + 1).trim()) return null; // trailing prose
        return { expression: text.slice(text.indexOf('{') + 1, closed), endIndex: i };
      }
    }
    return null;
  }

  /* ``users[0].bundle.download_list_html(key='final')`` ->
   * {receiver: 'users[0].bundle', name: 'download_list_html', args: "key='final'"} */
  function _parseCall(expression) {
    var text = String(expression || '').trim();
    var open = text.indexOf('(');
    if (open === -1 || !/\)$/.test(text)) return null;
    var target = text.slice(0, open).trim();
    var args = text.slice(open + 1, text.length - 1);
    var dot = target.lastIndexOf('.');
    return {
      receiver: dot === -1 ? '' : target.slice(0, dot),
      name: dot === -1 ? target : target.slice(dot + 1),
      args: args,
    };
  }

  function humanizeVariable(name) {
    var text = String(name || '').replace(/\[[^\]]*\]/g, '').replace(/^.*\./, '');
    text = text.replace(/_/g, ' ').trim();
    if (!text) return 'Document';
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  var LOREM_IPSUM = [
    'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.',
    'Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
  ];

  /* A stand-in for the first-page thumbnail Docassemble renders from the real
   * PDF: a blank page with ruled lines, obviously not a real document. */
  var PLACEHOLDER_PAGE_SVG = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 612 792" width="612" height="792">' +
    '<rect width="612" height="792" fill="#ffffff"/>' +
    '<g fill="#c9ced4">' +
    '<rect x="72" y="88" width="300" height="18" rx="4"/>' +
    '<rect x="72" y="150" width="468" height="10" rx="3"/>' +
    '<rect x="72" y="176" width="468" height="10" rx="3"/>' +
    '<rect x="72" y="202" width="360" height="10" rx="3"/>' +
    '<rect x="72" y="252" width="468" height="10" rx="3"/>' +
    '<rect x="72" y="278" width="468" height="10" rx="3"/>' +
    '<rect x="72" y="304" width="420" height="10" rx="3"/>' +
    '<rect x="72" y="354" width="468" height="10" rx="3"/>' +
    '<rect x="72" y="380" width="264" height="10" rx="3"/>' +
    '</g>' +
    '<text x="306" y="620" text-anchor="middle" font-family="sans-serif" font-size="26" fill="#adb5bd">Preview placeholder</text>' +
    '</svg>'
  );

  /* Docassemble's own paper-stack markup for a PDF (see filter.image_url), so
   * app.css draws the same stacked-pages thumbnail it draws in the interview. */
  function pdfStackHtml(title) {
    var width = 300;
    var aspect = 612 / 792;
    return '<div class="da-paper-stack" style="width:' + width + 'px; height: auto; aspect-ratio: ' +
      aspect + ';">' +
      '<div class="da-paper"><a target="_blank" title="' + attr(title) + '" class="daimageref" href="#">' +
      '<img alt="Thumbnail image of document" class="daicon" width="612" height="792" ' +
      'style="width: 100%; height: auto" src="' + PLACEHOLDER_PAGE_SVG + '"/></a></div>' +
      '<div class="da-paper"></div><div class="da-paper"></div></div>';
  }

  var BUTTON_COLORS = ['primary', 'secondary', 'tertiary', 'success', 'danger',
    'warning', 'info', 'light', 'dark', 'link'];

  /* docassemble.base.util.action_button_html */
  function actionButtonHtml(options) {
    var color = BUTTON_COLORS.indexOf(options.color) !== -1 ? options.color : 'dark';
    var requested = options.size;
    if (['sm', 'md', 'lg'].indexOf(requested) === -1) requested = 'sm';
    var size = requested === 'md' ? '' : ' btn-' + requested;
    var block = options.block ? ' btn-block' : '';
    var icon = options.icon
      ? '<i class="' + (/^fa[a-z] fa-/.test(options.icon) ? options.icon : 'fa-solid fa-' +
        String(options.icon).replace(/^(fa[a-z])-fa-/, '')) + '"></i> '
      : '';
    return '<a ' + (options.target ? 'target="' + attr(options.target) + '" ' : '') +
      'href="' + attr(options.url || '#') + '" class="btn' + size + block + ' btn-' +
      color + ' btn-darevisit' +
      (options.classname ? ' ' + options.classname : '') + '">' + icon + options.label + '</a> ';
  }

  /* ${ action_button_html(url_action('x'), label=word("Edit"), icon="pencil") } */
  function makoActionButton(args) {
    var parsed = parseArguments(args);
    var label = argValue(parsed, 'label', null);
    var newWindow = argValue(parsed, 'new_window', null);
    var target = '';
    if (newWindow === true) target = '_blank';
    else if (newWindow === false) target = '_self';
    else if (typeof newWindow === 'string' && newWindow) target = newWindow;
    return actionButtonHtml({
      // The preview never navigates, so the destination stays inert; everything
      // the author can see about the button is faithful.
      url: '#',
      target: target,
      label: esc(typeof label === 'string' && label.trim() ? label : 'Edit'),
      icon: argValue(parsed, 'icon', null),
      color: argValue(parsed, 'color', 'success'),
      size: argValue(parsed, 'size', 'sm'),
      block: argValue(parsed, 'block', false) === true,
      classname: typeof parsed.values.classname === 'string' ? parsed.values.classname : null,
    });
  }

  /* docassemble.AssemblyLine.al_document.table_row */
  function alTableRow(title, buttons) {
    return '\n\t<div class="row al_doc_table_row">' +
      '\n\t\t<div class="col col-12 col-sm-6 al_doc_title">' + title + '</div>' +
      '\n\t\t<div class="col col-12 col-sm-6 al_buttons">' + buttons.join('') + '</div>' +
      '\n\t</div>';
  }

  function lookupBundle(context, name) {
    if (!context || !context.bundles) return null;
    return context.bundles[String(name || '').trim()] || null;
  }

  function bundleTitle(context, name) {
    var bundle = lookupBundle(context, name);
    if (bundle && bundle.title) return bundle.title;
    var templates = (context && context.templates) || {};
    var titleTemplate = templates[String(name || '').trim() + '.title'];
    if (titleTemplate && titleTemplate.content) return titleTemplate.content;
    return humanizeVariable(name);
  }

  /* The documents a bundle will actually offer, when the interview's objects:
   * blocks say; otherwise two obvious stand-ins. */
  function bundleDocuments(context, name) {
    var bundle = lookupBundle(context, name);
    var documents = (context && context.documents) || {};
    var templates = (context && context.templates) || {};
    if (bundle && bundle.elements && bundle.elements.length) {
      return bundle.elements.map(function (element) {
        var declared = documents[element];
        if (declared && declared.title) return { title: declared.title, real: true };
        var titleTemplate = templates[element + '.title'];
        if (titleTemplate && titleTemplate.content) return { title: titleTemplate.content, real: true };
        return { title: humanizeVariable(element), real: true };
      });
    }
    return [
      { title: 'Your first document', real: false },
      { title: 'Your second document', real: false },
    ];
  }

  function downloadListHtml(receiver, args, context) {
    var parsed = parseArguments(args);
    var showView = argValue(parsed, 'view', true) !== false;
    var includeZip = argValue(parsed, 'include_zip', true) !== false;
    var includeEmail = argValue(parsed, 'include_email', false) === true;
    var viewLabel = argValue(parsed, 'view_label', null) || 'View';
    var downloadLabel = argValue(parsed, 'download_label', null) || 'Download';
    var title = bundleTitle(context, receiver);
    var documents = bundleDocuments(context, receiver);
    var placeholder = documents.some(function (doc) { return !doc.real; });

    var html = '<div class="container al_table al_doc_table" id="' + attr(receiver || 'al_bundle') + '">';
    documents.forEach(function (doc) {
      var buttons = [];
      if (showView) {
        buttons.push(actionButtonHtml({
          label: esc(viewLabel) + ' <span class="visually-hidden">' + esc(doc.title) + '</span>',
          icon: argValue(parsed, 'view_icon', null) || 'eye',
          color: 'secondary',
          size: 'md',
          classname: 'al_view al_button',
        }));
      }
      buttons.push(actionButtonHtml({
        label: esc(downloadLabel) + ' <span class="visually-hidden">' + esc(doc.title) + '</span>',
        icon: argValue(parsed, 'download_icon', null) || 'download',
        color: 'primary',
        size: 'md',
        classname: 'al_download al_button',
      }));
      html += alTableRow(esc(doc.title), buttons);
    });
    if (includeZip) {
      html += alTableRow(esc(title), [actionButtonHtml({
        label: 'Download all <span class="visually-hidden">' + esc(title) + '</span> documents',
        icon: argValue(parsed, 'zip_icon', null) || 'file-archive',
        color: 'primary',
        size: 'md',
        classname: 'al_zip al_button',
      })]);
    }
    if (includeEmail) html += sendButtonHtml(receiver, '', context);
    html += '\n</div>';
    return { html: html, block: true, placeholder: placeholder ? 'documents' : null };
  }

  function sendButtonHtml(receiver, args, context) {
    var parsed = parseArguments(args);
    var showCheckbox = argValue(parsed, 'show_editable_checkbox', true) !== false;
    var label = argValue(parsed, 'label', null) || 'Send';
    var emailLabel = argValue(parsed, 'email_label', null) || 'Email';
    var legendClass = argValue(parsed, 'email_legend_class', null) || 'h4';
    var name = String(receiver || 'al_bundle').replace(/[^A-Za-z0-9_]/g, '_');
    var title = bundleTitle(context, receiver);

    var html = '<fieldset class="al_send_bundle al_send_section_alone ' + attr(name) +
      '" id="al_send_bundle_' + attr(name) + '">' +
      '<legend class="' + attr(legendClass) + ' al_doc_email_header">Get a copy of the documents in email</legend>';
    if (showCheckbox) {
      html += '<div class="form-check-container"><div class="form-check">' +
        '<input class="form-check-input al_wants_editable" type="checkbox" id="_ignore_al_wants_editable_' + attr(name) + '">' +
        '<label class="al_wants_editable form-check-label" for="_ignore_al_wants_editable_' + attr(name) + '">' +
        'Include an editable copy</label></div></div>';
    }
    html += '<div class="al_email_container">' +
      '<span class="al_email_address ' + attr(name) + ' container form-group row da-field-container da-field-container-datatype-email">' +
      '<label for="_ignore_al_doc_email_' + attr(name) + '" class="col-form-label da-form-label datext-right">' +
      esc(emailLabel) + '</label>' +
      '<input alt="Email address" class="form-control" type="email" size="35" ' +
      'name="_ignore_al_doc_email_' + attr(name) + '" id="_ignore_al_doc_email_' + attr(name) + '">' +
      '</span>' +
      actionButtonHtml({
        label: esc(label) + ' <span class="visually-hidden">' + esc(title) + ' documents</span>',
        icon: argValue(parsed, 'icon', null) || 'envelope',
        color: 'primary',
        size: 'md',
        classname: 'al_send_email_button',
      }) +
      '</div></fieldset>';
    return html;
  }

  function collapseTemplateHtml(args, context) {
    var parts = splitArguments(args);
    var templateName = parts.length ? parts[0].trim() : '';
    var parsed = parseArguments(args);
    var collapsed = argValue(parsed, 'collapsed', true) !== false;
    var classname = argValue(parsed, 'classname', null);
    var openIcon = argValue(parsed, 'open_icon', null) || 'caret-down';
    var closedIcon = argValue(parsed, 'closed_icon', null) || 'caret-right';
    var templates = (context && context.templates) || {};
    var found = templates[templateName] || null;
    var subject = found && found.subject ? found.subject : humanizeVariable(templateName);
    var content = found && found.content
      ? renderMarkdown(found.content, null, context)
      : LOREM_IPSUM.map(function (line) { return '<p>' + esc(line) + '</p>'; }).join('');
    var id = 'dapv_collapse_' + String(templateName || 'template').replace(/[^A-Za-z0-9_]/g, '_');

    var html = '<div id="' + attr(id) + '" class="al_collapse_template">' +
      '<a class="' + (collapsed ? 'collapsed ' : '') + 'al_toggle" data-bs-toggle="collapse" href="#' +
      attr(id) + '_contents" role="button" aria-expanded="' + (collapsed ? 'false' : 'true') +
      '" aria-controls="' + attr(id) + '_contents">' +
      '<span class="toggle-icon pdcaretopen"><i class="fa-solid fa-' + attr(openIcon) + '"></i></span>' +
      '<span class="toggle-icon pdcaretclosed"><i class="fa-solid fa-' + attr(closedIcon) + '"></i></span>' +
      '<span class="subject">' + renderInlineMarkdown(subject, null, context) + '</span></a>' +
      '<div class="collapse' + (collapsed ? '' : ' show') + '" id="' + attr(id) + '_contents">' +
      '<div class="card card-body pb-1 ' + attr(classname ? String(classname).trim() : 'bg-light') + '">' +
      content + '</div></div></div>';
    return { html: html, block: true, placeholder: found ? null : 'template' };
  }

  function renderMakoWidget(expression, context) {
    // ``${ users.table }`` is an attribute, not a call, and names a table:
    // block elsewhere in the file.
    var tableName = String(expression || '').trim();
    if (/^[A-Za-z_][A-Za-z0-9_.[\]'"]*\.table$/.test(tableName)) {
      var tables = (context && context.tables) || {};
      var declared = tables[tableName];
      if (declared) {
        return {
          html: renderTable(declared, { context: context }),
          block: true,
          placeholder: 'rows',
        };
      }
      return {
        html: renderTable({ columns: [{ Item: 'row_item.name.full()' }] }, { context: context }),
        block: true,
        placeholder: 'table',
      };
    }

    var call = _parseCall(expression);
    if (!call) return null;
    if (call.name === 'as_pdf') {
      return {
        html: pdfStackHtml(bundleTitle(context, call.receiver)),
        block: true,
        placeholder: 'thumbnail',
      };
    }
    if (call.name === 'download_list_html' || call.name === 'download_html') {
      return downloadListHtml(call.receiver, call.args, context);
    }
    if (call.name === 'send_button_html') {
      return { html: sendButtonHtml(call.receiver, call.args, context), block: true };
    }
    if (call.name === 'collapse_template' && !call.receiver) {
      return collapseTemplateHtml(call.args, context);
    }
    if (call.name === 'action_button_html' && !call.receiver) {
      // An anchor, so it reads correctly mid-sentence as well as on its own line.
      return { html: makoActionButton(call.args), block: false };
    }
    if (call.name === 'add_action') {
      return { html: addActionHtml(call.args), block: false };
    }
    return null;
  }

  /* Block-level tags start a raw HTML block that runs to the next blank line,
   * the way Python-Markdown treats them. Inline tags stay inside a paragraph. */
  var BLOCK_LEVEL_TAGS = ['address', 'article', 'aside', 'blockquote', 'button', 'canvas',
    'dd', 'details', 'dialog', 'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure',
    'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'hr',
    'iframe', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table', 'tbody',
    'td', 'tfoot', 'th', 'thead', 'tr', 'ul', 'video'];

  /* Whether a line is a lazy continuation of the block above it, rather than
   * the start of something new. */
  function _continuesBlock(line) {
    if (!line || !line.trim()) return false;
    if (/^\s*[-*+]\s+/.test(line)) return false;
    if (/^\s*\d+[.)]\s+/.test(line)) return false;
    if (/^#{1,6}\s+/.test(line)) return false;
    if (/^\s*%/.test(line)) return false;
    if (/^\s*\$\{/.test(line)) return false;
    if (startsBlockHtml(line)) return false;
    return true;
  }

  function startsBlockHtml(line) {
    var match = line.trim().match(/^<\/?([a-zA-Z][a-zA-Z0-9-]*)/);
    return Boolean(match) && BLOCK_LEVEL_TAGS.indexOf(match[1].toLowerCase()) !== -1;
  }

  /* Docassemble runs the text through Mako and then Markdown.  We cannot
   * evaluate Mako without an interview session, so expressions are shown as
   * inline code — an author reading the preview still sees where the value
   * lands, and nothing silently disappears. */
  function renderMarkdown(text, report, context) {
    var source = String(text === undefined || text === null ? '' : text);
    if (!source.trim()) return '';
    var lines = source.split('\n');
    var html = '';
    var listTag = '';
    var paragraph = [];

    function inline(str) {
      var out = String(str);
      out = out.replace(/\$\{([^}]*)\}/g, function (whole, expr) {
        var widget = renderMakoWidget(expr, context);
        if (widget && !widget.block) {
          _recordPlaceholder(report, widget.placeholder);
          return widget.html;
        }
        return '<code class="dapv-mako">${' + expr + '}</code>';
      });
      out = out.replace(/\*\*\*([\s\S]+?)\*\*\*/g, '<strong><em>$1</em></strong>');
      out = out.replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>');
      out = out.replace(/(^|[^*])\*([^*\n<]+)\*/g, '$1<em>$2</em>');
      out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
      // The link text may wrap across lines, so [^\]] has to allow newlines;
      // the URL may not, which is what stops a stray bracket running away.
      out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      // Docassemble's explicit line break.
      out = out.replace(/ *\[BR\] */g, '<br />');
      return out;
    }

    function closeList() {
      if (listTag) { html += '</' + listTag + '>'; listTag = ''; }
    }

    /* The inline pass runs over the whole block, never line by line: Markdown
     * spans lack of line discipline, and a link split across a newline has to be
     * matched as one thing. A single newline is whitespace, not a break —
     * Docassemble does not load the nl2br extension; [BR] is the way to force
     * one. */
    function flushParagraph() {
      if (!paragraph.length) return;
      html += '<p>' + inline(paragraph.join('\n')) + '</p>';
      paragraph = [];
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      // A Mako expression standing alone on its line may render as a
      // block-level widget (a document table, a collapse, a PDF preview), which
      // cannot live inside a <p>. Gather it, braces and all, before deciding.
      if (/^\s*\$\{/.test(line)) {
        var gathered = _gatherMakoExpression(lines, i);
        if (gathered) {
          var standalone = renderMakoWidget(gathered.expression, context);
          if (standalone && standalone.block) {
            flushParagraph();
            closeList();
            html += standalone.html;
            _recordPlaceholder(report, standalone.placeholder);
            i = gathered.endIndex;
            continue;
          }
        }
      }
      if (/^\s*%/.test(line)) {
        flushParagraph();
        closeList();
        html += '<div class="dapv-mako-line"><code>' + esc(line.trim()) + '</code></div>';
        continue;
      }
      if (!line.trim()) { flushParagraph(); closeList(); continue; }
      if (startsBlockHtml(line)) {
        // Raw HTML block: emit verbatim, with no Markdown or Mako rewriting
        // inside it, so attributes and nested markup survive intact.
        flushParagraph();
        closeList();
        var block = [];
        while (i < lines.length && lines[i].trim()) {
          block.push(lines[i]);
          i++;
        }
        html += sanitizeHtml(block.join('\n'), report);
        continue;
      }
      var heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        flushParagraph();
        closeList();
        var level = Math.min(heading[1].length + 1, 6);
        html += '<h' + level + '>' + inline(heading[2]) + '</h' + level + '>';
        continue;
      }
      var bullet = line.match(/^\s*[-*+]\s+(.*)$/);
      var numbered = bullet ? null : line.match(/^\s*\d+[.)]\s+(.*)$/);
      if (bullet || numbered) {
        flushParagraph();
        var wanted = bullet ? 'ul' : 'ol';
        if (listTag !== wanted) { closeList(); html += '<' + wanted + '>'; listTag = wanted; }
        // Markdown's lazy continuation: a wrapped list item keeps going on the
        // next line, so gather those before running the inline pass — otherwise
        // a link whose text wraps would never be seen whole.
        var itemLines = [(bullet || numbered)[1]];
        while (i + 1 < lines.length && _continuesBlock(lines[i + 1])) {
          i++;
          itemLines.push(lines[i].trim());
        }
        html += '<li>' + inline(itemLines.join('\n')) + '</li>';
        continue;
      }
      var quote = line.match(/^\s*>\s?(.*)$/);
      if (quote) {
        flushParagraph();
        closeList();
        var quoteLines = [quote[1]];
        while (i + 1 < lines.length && _continuesBlock(lines[i + 1])) {
          i++;
          quoteLines.push(lines[i].replace(/^\s*>\s?/, '').trim());
        }
        html += '<blockquote class="blockquote">' + inline(quoteLines.join('\n')) + '</blockquote>';
        continue;
      }
      paragraph.push(line.trim());
    }
    flushParagraph();
    closeList();
    return applyIconMarkup(sanitizeHtml(html, report));
  }

  /* Markdown for a one-line context (labels, question text): Docassemble
   * strips the wrapping <p> so the text sits inline in the label. */
  function renderInlineMarkdown(text, report, context) {
    var html = renderMarkdown(text, report, context);
    var single = html.match(/^<p>([\s\S]*)<\/p>$/);
    if (single && single[1].indexOf('<p>') === -1) return single[1];
    return html;
  }

  // -------------------------------------------------------------------------
  // AssemblyLine constants, mirrored from ql_baseline.yml
  // -------------------------------------------------------------------------

  var AL_LABELS = {
    name_title: 'Title (optional)',
    first_name: 'First name',
    middle_name: 'Middle name',
    last_name: 'Last name',
    suffix: 'Suffix',
    person_type: 'Is this a person, or a business?',
    business_name: 'Name of business or organization',
    individual_choice: 'Person',
    business_choice: 'Business or organization',
    address: 'Street address',
    unit: 'Apartment',
    city: 'City',
    state: 'State',
    state_or_province: 'State / Province',
    zip: 'Zip or postal code',
    postal_code: 'Postal code',
    county: 'County',
    country: 'Country',
    impounded: 'This address is impounded',
    has_no_address: 'I do not have an address',
    has_no_address_explanation: 'Anything else you want to add about your living situation?',
    has_no_address_explanation_help: 'Example: "I normally sleep at 5th and Main."',
    gender: 'Gender',
    gender_self_described: 'Self-described gender',
    gender_help_text:
      'Some forms require you to select either "Male" or "Female". If you do not select "Male" or "Female", your form may include an empty checkbox.',
    pronouns: 'Choose one or more pronouns',
    pronouns_users0: 'Check one or more pronouns that you want people to use to refer to you',
    pronoun_self_described: 'Self described pronouns',
    pronouns_help_text:
      'A pronoun is a word that can be used in place of your name. For example: he, she, or they. Learn more at [pronouns.org](https://pronouns.org/)',
    pronoun_prefer_not_to_say: 'Prefer not to say',
    pronoun_prefer_self_described: 'Something else',
    pronoun_unknown: 'Unknown',
    language: 'Language',
    language_other: 'Other',
  };

  var AL_GENDER_CHOICES = [
    { label: 'Female', value: 'female' },
    { label: 'Male', value: 'male' },
    { label: 'Nonbinary', value: 'nonbinary' },
    { label: 'Prefer not to say', value: 'prefer-not-to-say' },
    { label: 'Prefer to write something else', value: 'self-described' },
    { label: 'Unknown', value: 'unknown' },
  ];

  var AL_PRONOUN_CHOICES = [
    { label: 'He/him/his', value: 'he/him/his' },
    { label: 'She/her/hers', value: 'she/her/hers' },
    { label: 'They/them/theirs', value: 'they/them/theirs' },
    { label: 'Ze/zir/zirs', value: 'ze/zir/zirs' },
  ];

  var AL_LANGUAGE_CHOICES = [
    { label: 'English', value: 'en' },
    { label: 'Spanish', value: 'es' },
    { label: 'Other', value: 'other' },
  ];

  var AL_NAME_SUFFIXES = ['Jr', 'Junior', 'Sr', 'Senior', 'I', 'II', 'III', 'IV', 'V', 'VI',
    'Esq.', 'Ph.D.', 'M.D.', 'J.D.', 'D.D.S.', 'D.V.M.', 'Ed.D.', 'Ret.', 'OBE', 'CBE',
    'MBE', 'QC', 'KC', 'Bart.', 'Bt.'];

  var AL_NAME_TITLES = ['Mr.', 'Mrs.', 'Miss', 'Ms.', 'Mx.', 'Dr.', 'Prof.', 'Hon.', 'Rev.',
    'Sir', 'Lord', 'Lady', 'Dame', 'Maj.', 'Gen.', 'Capt.', 'Lt.', 'Sgt.', 'Fr.', 'Sr.'];

  var AL_METHOD_NAMES = [
    'name_fields',
    'address_fields',
    'gender_fields',
    'pronoun_fields',
    'language_fields',
  ];

  // -------------------------------------------------------------------------
  // Parsing ``users[0].name_fields(show_suffix=False)`` style field rows
  // -------------------------------------------------------------------------

  function parseMethodCall(code) {
    if (typeof code !== 'string') return null;
    var text = code.trim();
    var match = text.match(/^([A-Za-z_][A-Za-z0-9_.[\]'"\- ]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(([\s\S]*)\)\s*$/);
    if (!match) return null;
    if (AL_METHOD_NAMES.indexOf(match[2]) === -1) return null;
    return { object: match[1].trim(), method: match[2], args: match[3].trim() };
  }

  /* Split on top-level commas only: nested calls, lists and dicts survive. */
  function splitArguments(text) {
    var parts = [];
    var depth = 0;
    var quote = null;
    var current = '';
    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      if (quote) {
        current += ch;
        if (ch === quote && text[i - 1] !== '\\') quote = null;
        continue;
      }
      if (ch === '"' || ch === "'") { quote = ch; current += ch; continue; }
      if (ch === '(' || ch === '[' || ch === '{') depth++;
      if (ch === ')' || ch === ']' || ch === '}') depth--;
      if (ch === ',' && depth === 0) { parts.push(current); current = ''; continue; }
      current += ch;
    }
    if (current.trim()) parts.push(current);
    return parts.map(function (part) { return part.trim(); }).filter(Boolean);
  }

  /* Turn a Python literal into a JS value.  Anything we cannot resolve comes
   * back as {expression: "<source>"} so the caller can fall back to the
   * documented default and tell the author it did. */
  function parsePythonLiteral(raw) {
    var text = String(raw === undefined || raw === null ? '' : raw).trim();
    // word("Send") is Docassemble's translation call; at runtime it resolves to
    // the phrase itself unless a translation is loaded, so show the phrase.
    var translated = text.match(/^word\s*\(\s*(['"])([\s\S]*)\1\s*\)$/);
    if (translated) return translated[2];
    if (text === 'True') return true;
    if (text === 'False') return false;
    if (text === 'None') return null;
    if (/^-?\d+$/.test(text)) return parseInt(text, 10);
    if (/^-?\d*\.\d+$/.test(text)) return parseFloat(text);
    var quoted = text.match(/^(['"])([\s\S]*)\1$/);
    if (quoted) return quoted[2];
    if (/^[[{]/.test(text)) {
      try {
        return JSON.parse(
          text
            .replace(/'/g, '"')
            .replace(/\bTrue\b/g, 'true')
            .replace(/\bFalse\b/g, 'false')
            .replace(/\bNone\b/g, 'null')
        );
      } catch (err) {
        return { expression: text };
      }
    }
    return { expression: text };
  }

  function parseArguments(argString) {
    var values = {};
    var unresolved = [];
    splitArguments(String(argString || '')).forEach(function (part) {
      var eq = part.indexOf('=');
      if (eq === -1) return;
      var name = part.slice(0, eq).trim();
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) return;
      var value = parsePythonLiteral(part.slice(eq + 1));
      if (value && typeof value === 'object' && !Array.isArray(value) && value.expression) {
        unresolved.push({ name: name, expression: value.expression });
        return;
      }
      values[name] = value;
    });
    return { values: values, unresolved: unresolved };
  }

  function argValue(parsed, name, fallback) {
    return Object.prototype.hasOwnProperty.call(parsed.values, name) ? parsed.values[name] : fallback;
  }

  function normalizeChoiceList(raw, fallback) {
    if (!Array.isArray(raw)) return fallback;
    return raw.map(function (item) {
      if (item && typeof item === 'object') {
        var key = Object.keys(item)[0];
        return { label: String(key), value: String(item[key]) };
      }
      return { label: String(item), value: String(item) };
    });
  }

  // -------------------------------------------------------------------------
  // AssemblyLine ``*_fields()`` emulation
  //
  // Each generator returns the same list of field dictionaries that the real
  // Python method returns, so the renderer below treats them exactly like
  // fields the author typed by hand.
  // -------------------------------------------------------------------------

  function attrName(receiver, suffix) {
    var base = String(receiver || 'x').trim() || 'x';
    return suffix ? base + '.' + suffix : base;
  }

  function applyOverrides(fields, parsed, prefix) {
    var maxlengths = argValue(parsed, 'maxlengths', null);
    var required = argValue(parsed, 'required', null);
    function withPrefix(key) {
      return key.indexOf(prefix) === 0 ? key : prefix + key;
    }
    if (maxlengths && typeof maxlengths === 'object') {
      Object.keys(maxlengths).forEach(function (key) {
        var target = withPrefix(key);
        fields.forEach(function (f) { if (f.field === target) f.maxlength = maxlengths[key]; });
      });
    }
    if (required && typeof required === 'object' && !Array.isArray(required)) {
      Object.keys(required).forEach(function (key) {
        var target = withPrefix(key);
        fields.forEach(function (f) { if (f.field === target) f.required = required[key]; });
      });
    }
    return fields;
  }

  function alNameFields(receiver, parsed) {
    var personOrBusiness = argValue(parsed, 'person_or_business', 'person');
    var showSuffix = argValue(parsed, 'show_suffix', true);
    var showTitle = argValue(parsed, 'show_title', false);
    var showIf = argValue(parsed, 'show_if', null);
    var suffixChoices = normalizeChoiceList(argValue(parsed, 'suffix_choices', null), null) ||
      AL_NAME_SUFFIXES.map(function (s) { return { label: s, value: s }; });
    var titleChoices = normalizeChoiceList(argValue(parsed, 'title_choices', null), null) ||
      AL_NAME_TITLES.map(function (s) { return { label: s, value: s }; });
    var fields;

    if (personOrBusiness === 'business') {
      fields = [{ label: AL_LABELS.business_name, field: attrName(receiver, 'name.first') }];
      if (showIf) fields[0]['show if'] = showIf;
    } else if (personOrBusiness === 'person') {
      fields = [
        { label: AL_LABELS.first_name, field: attrName(receiver, 'name.first') },
        { label: AL_LABELS.middle_name, field: attrName(receiver, 'name.middle'), required: false },
        { label: AL_LABELS.last_name, field: attrName(receiver, 'name.last') },
      ];
      if (showSuffix) {
        fields.push({
          label: AL_LABELS.suffix,
          field: attrName(receiver, 'name.suffix'),
          choices: suffixChoices,
          required: false,
        });
      }
      if (showTitle) {
        fields.unshift({
          label: AL_LABELS.name_title,
          field: attrName(receiver, 'name.title'),
          choices: titleChoices,
          required: false,
        });
      }
      if (showIf) fields.forEach(function (f) { f['show if'] = showIf; });
    } else {
      // person_or_business is None / 'unsure': ask, then branch on the answer.
      var showIfIndiv = { variable: attrName(receiver, 'person_type'), is: 'ALIndividual' };
      var showIfBusiness = { variable: attrName(receiver, 'person_type'), is: 'business' };
      fields = [
        {
          label: AL_LABELS.person_type,
          field: attrName(receiver, 'person_type'),
          choices: [
            { label: AL_LABELS.individual_choice, value: 'ALIndividual' },
            { label: AL_LABELS.business_choice, value: 'business' },
          ],
          'input type': 'radio',
          required: true,
        },
        { label: AL_LABELS.first_name, field: attrName(receiver, 'name.first'), 'show if': showIfIndiv },
        { label: AL_LABELS.middle_name, field: attrName(receiver, 'name.middle'), required: false, 'show if': showIfIndiv },
        { label: AL_LABELS.last_name, field: attrName(receiver, 'name.last'), 'show if': showIfIndiv },
      ];
      if (showIf) fields[0]['show if'] = showIf;
      if (showSuffix) {
        fields.push({
          label: AL_LABELS.suffix,
          field: attrName(receiver, 'name.suffix'),
          choices: suffixChoices,
          required: false,
          'show if': showIfIndiv,
        });
      }
      fields.push({
        label: AL_LABELS.business_name,
        field: attrName(receiver, 'name.first'),
        'show if': showIfBusiness,
      });
    }
    return applyOverrides(fields, parsed, attrName(receiver, 'name.'));
  }

  function alAddressFields(receiver, parsed) {
    var countryCodeArg = argValue(parsed, 'country_code', null);
    var countryCode = countryCodeArg || 'US';
    var defaultState = argValue(parsed, 'default_state', null);
    var showCountry = argValue(parsed, 'show_country', false);
    var showCounty = argValue(parsed, 'show_county', false);
    var showIf = argValue(parsed, 'show_if', null);
    var allowNoAddress = argValue(parsed, 'allow_no_address', false);
    var askIfImpounded = argValue(parsed, 'ask_if_impounded', false);
    // ALIndividual.address_fields() delegates to self.address.address_fields().
    var base = /\.address$/.test(String(receiver || '')) ? receiver : attrName(receiver, 'address');
    var fields = [];

    if (allowNoAddress) {
      fields.push({
        label: AL_LABELS.has_no_address,
        field: attrName(base, 'has_no_address'),
        datatype: 'yesno',
      });
      fields.push({
        label: AL_LABELS.has_no_address_explanation,
        field: attrName(base, 'has_no_address_explanation'),
        datatype: 'area',
        rows: 2,
        help: AL_LABELS.has_no_address_explanation_help,
        'show if': attrName(base, 'has_no_address'),
        required: false,
      });
    }
    fields.push({
      label: AL_LABELS.address,
      field: attrName(base, 'address'),
      'address autocomplete': false,
    });
    fields.push({ label: AL_LABELS.unit, field: attrName(base, 'unit'), required: false });
    if (allowNoAddress) {
      fields[fields.length - 1]['hide if'] = attrName(base, 'has_no_address');
      fields[fields.length - 2]['hide if'] = attrName(base, 'has_no_address');
    }
    fields.push({ label: AL_LABELS.city, field: attrName(base, 'city') });

    if (countryCode && !showCountry) {
      fields.push({
        label: AL_LABELS.state,
        field: attrName(base, 'state'),
        code: "states_list(country_code='" + countryCode + "')",
        default: defaultState || '',
      });
    } else {
      fields.push({
        label: AL_LABELS.state_or_province,
        field: attrName(base, 'state'),
        default: defaultState || '',
      });
    }
    if (countryCode === 'US' && !showCountry) {
      fields.push({ label: AL_LABELS.zip, field: attrName(base, 'zip'), required: false });
    } else {
      fields.push({ label: AL_LABELS.postal_code, field: attrName(base, 'zip'), required: false });
    }
    if (allowNoAddress) fields[fields.length - 1]['hide if'] = attrName(base, 'has_no_address');
    if (showCounty) {
      fields.push({ label: AL_LABELS.county, field: attrName(base, 'county'), required: false });
    }
    if (showCountry) {
      fields.push({
        label: AL_LABELS.country,
        field: attrName(base, 'country'),
        required: false,
        code: 'countries_list()',
        default: countryCode,
      });
    }
    if (!allowNoAddress && showIf) {
      fields.forEach(function (f) { f['show if'] = showIf; });
    }
    if (askIfImpounded) {
      fields.push({
        label: AL_LABELS.impounded,
        field: attrName(base, 'impounded'),
        datatype: 'yesno',
      });
    }
    return applyOverrides(fields, parsed, attrName(base, ''));
  }

  function alGenderFields(receiver, parsed) {
    var choices = normalizeChoiceList(argValue(parsed, 'choices', null), null) || AL_GENDER_CHOICES;
    var showHelp = argValue(parsed, 'show_help', false);
    var showIf = argValue(parsed, 'show_if', null);
    var fields = [
      { label: AL_LABELS.gender, field: attrName(receiver, 'gender'), choices: choices },
      {
        label: AL_LABELS.gender_self_described,
        field: attrName(receiver, 'gender'),
        'show if': { variable: attrName(receiver, 'gender'), is: 'self-described' },
      },
    ];
    if (showHelp) fields[0].help = AL_LABELS.gender_help_text;
    if (showIf) fields[0]['show if'] = showIf;
    return applyOverrides(fields, parsed, attrName(receiver, ''));
  }

  function alPronounFields(receiver, parsed) {
    var choices = normalizeChoiceList(argValue(parsed, 'choices', null), null) || AL_PRONOUN_CHOICES;
    var showHelp = argValue(parsed, 'show_help', false);
    var showIf = argValue(parsed, 'show_if', null);
    var required = argValue(parsed, 'required', false);
    var showUnknown = argValue(parsed, 'show_unknown', 'guess');
    var finalChoices = [{ label: AL_LABELS.pronoun_prefer_self_described, value: 'self-described' }];
    if (showUnknown === true || (showUnknown === 'guess' && String(receiver).trim() !== 'users[0]')) {
      finalChoices.push({ label: AL_LABELS.pronoun_unknown, value: 'unknown' });
    }
    var fields = [
      {
        label: String(receiver).trim() === 'users[0]' ? AL_LABELS.pronouns_users0 : AL_LABELS.pronouns,
        field: attrName(receiver, 'pronouns'),
        datatype: 'checkboxes',
        choices: choices.concat(finalChoices),
        'none of the above': AL_LABELS.pronoun_prefer_not_to_say,
        required: typeof required === 'boolean' ? required : false,
      },
      {
        label: AL_LABELS.pronoun_self_described,
        field: attrName(receiver, 'pronouns_self_described'),
        'show if': attrName(receiver, "pronouns['self-described']"),
      },
    ];
    if (showHelp) fields[0].help = AL_LABELS.pronouns_help_text;
    if (showIf) fields[0]['show if'] = showIf;
    if (required && typeof required === 'object' && !Array.isArray(required)) {
      Object.keys(required).forEach(function (key) {
        fields.forEach(function (f) { if (f.field === key) f.required = required[key]; });
      });
    }
    return fields;
  }

  function alLanguageFields(receiver, parsed) {
    var choices = normalizeChoiceList(argValue(parsed, 'choices', null), null) || AL_LANGUAGE_CHOICES;
    var style = argValue(parsed, 'style', 'radio');
    var showIf = argValue(parsed, 'show_if', null);
    var fields = [
      { label: AL_LABELS.language, field: attrName(receiver, 'language'), choices: choices },
      {
        label: AL_LABELS.language_other,
        field: attrName(receiver, 'language_other'),
        'show if': { variable: attrName(receiver, 'language'), is: 'other' },
      },
    ];
    if (style === 'radio') fields[0]['input type'] = 'radio';
    if (showIf) fields[0]['show if'] = showIf;
    return applyOverrides(fields, parsed, attrName(receiver, ''));
  }

  var AL_GENERATORS = {
    name_fields: alNameFields,
    address_fields: alAddressFields,
    gender_fields: alGenderFields,
    pronoun_fields: alPronounFields,
    language_fields: alLanguageFields,
  };

  /* Expand one ``code: users[0].name_fields(...)`` row into the field
   * dictionaries AssemblyLine would have produced at runtime. */
  function expandALMethod(call) {
    var generator = AL_GENERATORS[call.method];
    if (!generator) return { fields: [], notes: [] };
    var parsed = parseArguments(call.args);
    var notes = parsed.unresolved.map(function (item) {
      return call.object + '.' + call.method + '(): ' + item.name + '=' + item.expression +
        ' is computed at runtime; the preview uses the default.';
    });
    return { fields: generator(call.object, parsed), notes: notes };
  }

  // -------------------------------------------------------------------------
  // Normalizing the block's ``fields:`` list into field descriptors
  // -------------------------------------------------------------------------

  var STANDALONE_TYPES = ['note', 'html', 'raw html', 'code', 'script', 'css'];
  var CHOICE_DATATYPES = ['checkboxes', 'object_checkboxes', 'multiselect', 'object_multiselect', 'dropdown', 'combobox', 'radio', 'object', 'object_radio'];

  function choiceEntries(raw) {
    if (!Array.isArray(raw)) return null;
    return raw.map(function (item) {
      if (item && typeof item === 'object') {
        // Already normalized — the AssemblyLine generators emit this shape.
        if (Object.prototype.hasOwnProperty.call(item, 'label') &&
            Object.prototype.hasOwnProperty.call(item, 'value')) {
          return { label: String(item.label), value: String(item.value) };
        }
        var key = Object.keys(item)[0];
        var value = item[key];
        if (value && typeof value === 'object') return { label: String(key), value: String(key) };
        return { label: String(key), value: String(value) };
      }
      return { label: String(item), value: String(item) };
    });
  }

  function baseDescriptor() {
    return {
      kind: 'input',
      label: '',
      variable: '',
      datatype: 'text',
      inputType: null,
      choices: null,
      choiceCode: null,
      required: true,
      help: null,
      hint: null,
      defaultValue: null,
      showIf: null,
      hideIf: null,
      rows: null,
      maxlength: null,
      min: null,
      max: null,
      step: null,
      currencySymbol: '$',
      noneOfTheAbove: null,
      content: '',
      source: 'literal',
    };
  }

  /* YAML gives us real booleans; a Python expression written as a string is
   * only resolvable at runtime, so treat anything unrecognised as "on". */
  function _truthy(value) {
    if (typeof value === 'boolean') return value;
    var text = String(value === undefined || value === null ? '' : value).trim();
    if (/^(false|no|off|none|0)$/i.test(text)) return false;
    return true;
  }

  // Docassemble makes these optional unless the author says otherwise.
  var OPTIONAL_BY_DEFAULT = ['yesno', 'yesnowide', 'noyes', 'noyeswide', 'range'];

  function applyModifiers(desc, raw) {
    if (Object.prototype.hasOwnProperty.call(raw, 'datatype')) {
      desc.datatype = String(raw.datatype);
      if (OPTIONAL_BY_DEFAULT.indexOf(desc.datatype) !== -1 &&
          !Object.prototype.hasOwnProperty.call(raw, 'required')) {
        desc.required = false;
      }
    }
    if (raw['input type']) desc.inputType = String(raw['input type']);
    if (raw.input_type) desc.inputType = String(raw.input_type);
    if (raw.choices) desc.choices = choiceEntries(raw.choices);
    if (raw.code) desc.choiceCode = typeof raw.code === 'string' ? raw.code.trim() : String(raw.code);
    if (Object.prototype.hasOwnProperty.call(raw, 'required')) {
      desc.required = !(raw.required === false || raw.required === 'False' || raw.required === 'false');
    }
    if (raw.help) desc.help = String(raw.help);
    if (raw.hint) desc.hint = String(raw.hint);
    if (Object.prototype.hasOwnProperty.call(raw, 'default')) desc.defaultValue = raw.default;
    if (raw['show if'] !== undefined) desc.showIf = raw['show if'];
    if (raw['hide if'] !== undefined) desc.hideIf = raw['hide if'];
    if (raw.rows) desc.rows = parseInt(raw.rows, 10) || null;
    if (raw.maxlength) desc.maxlength = raw.maxlength;
    if (raw.min !== undefined) desc.min = raw.min;
    if (raw.max !== undefined) desc.max = raw.max;
    if (raw.step !== undefined) desc.step = raw.step;
    if (raw['currency symbol']) desc.currencySymbol = String(raw['currency symbol']);
    if (raw['none of the above']) desc.noneOfTheAbove = String(raw['none of the above']);
    if (raw['address autocomplete']) desc.addressAutocomplete = true;
    // Per-field overrides of the interview-wide label layout.
    if (raw['label above field'] !== undefined) desc.labelAbove = _truthy(raw['label above field']);
    if (raw['floating label'] !== undefined) desc.floatingLabel = _truthy(raw['floating label']);
    return desc;
  }

  function descriptorFromDict(raw, source) {
    var desc = baseDescriptor();
    desc.source = source || 'literal';
    desc.label = String(raw.label === undefined || raw.label === null ? '' : raw.label);
    desc.variable = String(raw.field === undefined || raw.field === null ? '' : raw.field);
    applyModifiers(desc, raw);
    // A choices list with no datatype and no input type is a dropdown.
    if (desc.choices && desc.datatype === 'text' && !desc.inputType) desc.datatype = 'dropdown';
    if (desc.choiceCode && desc.datatype === 'text' && !desc.inputType) desc.datatype = 'dropdown';
    return desc;
  }

  /* Field rows come in several YAML shapes.  Match Docassemble's own reading
   * order: expanded (label/field), type shorthand ({yesno: var}), standalone
   * content ({note: text}) and finally {Label: variable}. */
  function describeField(raw) {
    if (typeof raw === 'string') {
      var plain = baseDescriptor();
      plain.label = raw;
      return { fields: [plain], notes: [] };
    }
    if (!raw || typeof raw !== 'object') return { fields: [], notes: [] };

    if (typeof raw.code === 'string' && !raw.label && !raw.field) {
      var call = parseMethodCall(raw.code);
      if (call) {
        var expanded = expandALMethod(call);
        return {
          fields: expanded.fields.map(function (item) {
            return descriptorFromDict(item, 'al:' + call.method);
          }),
          notes: expanded.notes,
        };
      }
    }

    var keys = Object.keys(raw);
    var hasLabel = Object.prototype.hasOwnProperty.call(raw, 'label');
    var hasField = Object.prototype.hasOwnProperty.call(raw, 'field');
    if (hasLabel && (hasField || raw.datatype || raw.choices)) {
      return { fields: [descriptorFromDict(raw, 'literal')], notes: [] };
    }

    if (keys.length === 0) return { fields: [], notes: [] };
    var firstKey = keys[0];
    var firstValue = raw[firstKey];

    if (STANDALONE_TYPES.indexOf(firstKey) !== -1) {
      var standalone = baseDescriptor();
      standalone.kind = firstKey === 'note' ? 'note' : (firstKey === 'html' || firstKey === 'raw html' ? 'html' : 'hidden');
      standalone.datatype = firstKey;
      standalone.content = typeof firstValue === 'string' ? firstValue : '';
      applyModifiers(standalone, raw);
      return { fields: [standalone], notes: [] };
    }

    if (firstKey === 'no label') {
      var noLabel = descriptorFromDict({ label: '', field: firstValue }, 'literal');
      applyModifiers(noLabel, raw);
      noLabel.noLabel = true;
      if (noLabel.choices && noLabel.datatype === 'text' && !noLabel.inputType) noLabel.datatype = 'dropdown';
      return { fields: [noLabel], notes: [] };
    }

    // Type shorthand: ``- yesno: some_variable``
    if (/^[a-z_ ]+$/.test(firstKey) && typeof firstValue === 'string' &&
        (raw.datatype === undefined) && firstKey !== 'label' &&
        (firstKey === 'yesno' || firstKey === 'noyes' || firstKey === 'yesnowide' ||
         firstKey === 'noyeswide' || firstKey === 'yesnoradio' || firstKey === 'noyesradio' ||
         firstKey === 'yesnomaybe' || firstKey === 'noyesmaybe')) {
      var shorthand = baseDescriptor();
      shorthand.datatype = firstKey;
      shorthand.variable = firstValue;
      shorthand.label = firstValue.replace(/_/g, ' ');
      if (OPTIONAL_BY_DEFAULT.indexOf(firstKey) !== -1) shorthand.required = false;
      applyModifiers(shorthand, raw);
      return { fields: [shorthand], notes: [] };
    }

    // ``- Label text: variable_name`` with sibling modifiers.
    var shaped = baseDescriptor();
    shaped.label = firstKey;
    if (typeof firstValue === 'string') {
      shaped.variable = firstValue;
    } else if (firstValue && typeof firstValue === 'object') {
      shaped.variable = String(firstValue.variable || firstValue.name || '');
      applyModifiers(shaped, firstValue);
    }
    applyModifiers(shaped, raw);
    if (shaped.choices && shaped.datatype === 'text' && !shaped.inputType) shaped.datatype = 'dropdown';
    if (shaped.choiceCode && shaped.datatype === 'text' && !shaped.inputType) shaped.datatype = 'dropdown';
    return { fields: [shaped], notes: [] };
  }

  function describeFields(fields) {
    var descriptors = [];
    var notes = [];
    (Array.isArray(fields) ? fields : []).forEach(function (raw) {
      var result = describeField(raw);
      descriptors = descriptors.concat(result.fields);
      notes = notes.concat(result.notes);
    });
    return { fields: descriptors, notes: notes };
  }

  // -------------------------------------------------------------------------
  // Rendering field descriptors as Docassemble markup
  // -------------------------------------------------------------------------

  var LABELAUTY_COLOR = 'primary';

  function fieldId(index) {
    return 'dapv_field_' + index;
  }

  function labelautyInput(options) {
    var label = options.label || '';
    return '<input aria-label="' + attr(label) + '" alt="' + attr(label) + '" data-color="' +
      LABELAUTY_COLOR + '" data-labelauty="' + attr(label) + '|' + attr(label) + '" class="' +
      attr(options.classes) + '" id="' + attr(options.id) + '" name="' + attr(options.name) +
      '" type="' + options.type + '" value="' + attr(options.value) + '"' +
      (options.checked ? ' checked="checked"' : '') + ' />';
  }

  function helpMarkup(desc) {
    if (!desc.help) return '';
    return '<a tabindex="0" class="text-info ms-1 dapointer" data-bs-container="body" ' +
      'data-bs-toggle="popover" data-bs-placement="bottom" data-bs-content="' +
      attrHtml(renderInlineMarkdown(desc.help)) + '" aria-label="Information" role="button">' +
      '<i class="fa-solid fa-question-circle"></i></a>';
  }

  function choicesFor(desc) {
    if (desc.choices && desc.choices.length) return desc.choices;
    if (desc.choiceCode) {
      // The real choices come from Python at runtime; show where they come from
      // rather than inventing values an author might mistake for the real list.
      return [
        { label: '— choices from ' + desc.choiceCode + ' —', value: '' },
      ];
    }
    return [];
  }

  function renderTextualInput(desc, id) {
    var type = 'text';
    var extraClass = '';
    var extra = '';
    switch (desc.datatype) {
      case 'date': type = 'date'; break;
      case 'time': type = 'time'; break;
      case 'datetime':
      case 'datetime-local': type = 'datetime-local'; break;
      case 'email': type = 'email'; break;
      case 'password': type = 'password'; break;
      case 'integer': type = 'number'; extra += ' step="1"'; break;
      case 'number':
      case 'float': type = 'number'; extra += ' step="any"'; break;
      case 'currency': type = 'number'; extraClass = ' dacurrency'; extra += ' step="0.01"'; break;
      case 'range': type = 'range'; break;
      default: type = 'text';
    }
    if (desc.maxlength) extra += ' maxlength="' + attr(desc.maxlength) + '"';
    if (desc.min !== null && desc.min !== undefined) extra += ' min="' + attr(desc.min) + '"';
    if (desc.max !== null && desc.max !== undefined) extra += ' max="' + attr(desc.max) + '"';
    var placeholder = desc.hint ? ' placeholder="' + attr(desc.hint) + '"' : '';
    var value = desc.defaultValue !== null && desc.defaultValue !== undefined && typeof desc.defaultValue !== 'object'
      ? ' value="' + attr(desc.defaultValue) + '"'
      : '';
    var input = '<input alt="Input box" class="form-control' + extraClass + '" type="' + type + '"' +
      extra + placeholder + value + ' name="' + attr(id) + '" id="' + attr(id) + '"' +
      (desc.required ? ' required' : '') + ' />';
    if (desc.datatype === 'currency') {
      return '<div class="input-group"><span class="input-group-text">' + esc(desc.currencySymbol) +
        '</span>' + input + '</div>';
    }
    return input;
  }

  function renderSelect(desc, id) {
    var entries = choicesFor(desc);
    var isCombobox = desc.inputType === 'combobox' || desc.datatype === 'combobox';
    var isMulti = desc.datatype === 'multiselect' || desc.datatype === 'object_multiselect';
    var classes = isCombobox ? 'form-control dasingleselect combobox' : 'form-select dasingleselect';
    var html = '<select class="' + classes + '" name="' + attr(id) + '" id="' + attr(id) + '"' +
      (isMulti ? ' multiple' : '') + (desc.required ? ' required' : '') + '>';
    if (!isMulti) {
      html += '<option value="">' + esc(isCombobox ? 'Select one' : 'Select...') + '</option>';
    }
    entries.forEach(function (choice) {
      var selected = desc.defaultValue !== null && desc.defaultValue !== undefined &&
        String(desc.defaultValue) === String(choice.value);
      html += '<option value="' + attr(choice.value) + '"' + (selected ? ' selected="selected"' : '') +
        '>' + esc(choice.label) + '</option>';
    });
    html += '</select>';
    return html;
  }

  function renderChoiceGroup(desc, id, type) {
    var entries = choicesFor(desc);
    var groupClass = type === 'radio' ? 'da-field-group da-field-radio' : 'da-field-group da-field-checkbox';
    var html = '<div class="' + groupClass + '">';
    entries.forEach(function (choice, index) {
      html += labelautyInput({
        label: choice.label,
        classes: type === 'radio' ? 'da-to-labelauty' : 'da-to-labelauty checkbox-icon',
        id: id + '_' + index,
        name: type === 'radio' ? id : id + '_' + index,
        type: type,
        value: choice.value,
        checked: desc.defaultValue !== null && desc.defaultValue !== undefined &&
          String(desc.defaultValue) === String(choice.value),
      });
    });
    if (type === 'checkbox' && desc.noneOfTheAbove) {
      html += labelautyInput({
        label: desc.noneOfTheAbove,
        classes: 'da-to-labelauty checkbox-icon danota-checkbox',
        id: id + '_nota',
        name: id + '_nota',
        type: 'checkbox',
        value: 'True',
      });
    }
    html += '</div>';
    return html;
  }

  function renderYesNoCheckbox(desc, id) {
    var label = renderInlineMarkdown(desc.label) || esc(desc.variable);
    return '<div class="da-field-group da-field-checkbox">' +
      '<input aria-label="' + attr(desc.label) + '" alt="' + attr(desc.label) +
      '" class="da-to-labelauty checkbox-icon dauncheckable" type="checkbox" value="' +
      (desc.datatype.indexOf('noyes') === 0 ? 'False' : 'True') + '" data-color="' + LABELAUTY_COLOR +
      '" data-labelauty="' + attrHtml(label) + '|' + attrHtml(label) + '" name="' + attr(id) +
      '" id="' + attr(id) + '" /></div>';
  }

  function renderYesNoRadio(desc, id) {
    var order = desc.datatype.indexOf('noyes') === 0
      ? [{ label: 'No', value: 'False' }, { label: 'Yes', value: 'True' }]
      : [{ label: 'Yes', value: 'True' }, { label: 'No', value: 'False' }];
    if (desc.datatype === 'yesnomaybe' || desc.datatype === 'noyesmaybe') {
      order = order.concat([{ label: 'I am not sure', value: 'None' }]);
    }
    var html = '<div class="da-field-group da-field-radio">';
    order.forEach(function (choice, index) {
      html += labelautyInput({
        label: choice.label,
        classes: 'da-to-labelauty',
        id: id + '_' + index,
        name: id,
        type: 'radio',
        value: choice.value,
      });
    });
    html += '</div>';
    return html;
  }

  function renderFileInput(desc, id) {
    return '<input alt="You can upload a file here" type="file" class="dafile" name="' + attr(id) +
      '" id="' + attr(id) + '"' + (desc.datatype === 'files' ? ' multiple' : '') + ' />';
  }

  function renderTextarea(desc, id) {
    var rows = desc.rows || 4;
    var placeholder = desc.hint ? ' placeholder="' + attr(desc.hint) + '"' : '';
    var value = typeof desc.defaultValue === 'string' ? esc(desc.defaultValue) : '';
    return '<textarea alt="Input box" class="form-control datextarea" rows="' + rows + '" name="' +
      attr(id) + '" id="' + attr(id) + '"' + placeholder + (desc.required ? ' required' : '') + '>' +
      value + '</textarea>';
  }

  var YESNO_CHECKBOX_TYPES = ['yesno', 'noyes', 'yesnowide', 'noyeswide'];
  var YESNO_RADIO_TYPES = ['yesnoradio', 'noyesradio', 'yesnomaybe', 'noyesmaybe'];

  function renderInput(desc, id) {
    if (YESNO_CHECKBOX_TYPES.indexOf(desc.datatype) !== -1) return renderYesNoCheckbox(desc, id);
    if (YESNO_RADIO_TYPES.indexOf(desc.datatype) !== -1) return renderYesNoRadio(desc, id);
    if (desc.datatype === 'checkboxes' || desc.datatype === 'object_checkboxes') {
      return renderChoiceGroup(desc, id, 'checkbox');
    }
    if (desc.inputType === 'radio' || desc.datatype === 'radio' || desc.datatype === 'object_radio') {
      return renderChoiceGroup(desc, id, 'radio');
    }
    if (desc.datatype === 'area' || desc.datatype === 'mlarea') return renderTextarea(desc, id);
    if (desc.datatype === 'file' || desc.datatype === 'files' || desc.datatype === 'camera') {
      return renderFileInput(desc, id);
    }
    if (desc.choices || desc.choiceCode || desc.datatype === 'dropdown' ||
        desc.datatype === 'combobox' || desc.datatype === 'multiselect' ||
        desc.datatype === 'object' || desc.datatype === 'object_multiselect') {
      return renderSelect(desc, id);
    }
    return renderTextualInput(desc, id);
  }

  function conditionText(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value;
    if (typeof value === 'object' && value.variable !== undefined) {
      return String(value.variable) + ' is ' + JSON.stringify(value.is);
    }
    return JSON.stringify(value);
  }

  // Docassemble's ``grid classes`` defaults: label md-4, field md-8.
  var GRID_LABEL_WIDTH = 'md-4';
  var GRID_FIELD_WIDTH = 'md-8';

  var LABEL_LAYOUTS = ['horizontal', 'above', 'floating'];

  /* Which of Docassemble's four label treatments a field gets, in the branch
   * order as_html() uses. ``horizontal`` — label to the left — is the default
   * when the interview says nothing; ``features: labels above fields: True``
   * and ``features: floating labels: True`` change it, and the per-field
   * ``label above field:`` / ``floating label:`` modifiers override again. */
  function labelPlacement(desc, layout) {
    if (desc.noLabel) return 'wide';
    if (desc.datatype === 'yesnowide' || desc.datatype === 'noyeswide') return 'wide';
    if (layout === 'floating' || desc.floatingLabel === true) return 'floating';
    if ((layout === 'above' && desc.labelAbove !== false) || desc.labelAbove === true) return 'above';
    return 'horizontal';
  }

  var FILE_DATATYPES = ['file', 'files', 'camera', 'user', 'environment', 'camcorder', 'microphone'];
  var YESNO_INLINE_TYPES = ['yesno', 'noyes'];

  /* Docassemble wraps radio and checkbox groups in an ARIA group whose "label"
   * is a div, not a <label>, because there is no single control to point at. */
  function fieldsetKind(desc) {
    if (desc.datatype === 'checkboxes' || desc.datatype === 'object_checkboxes') return 2;
    if (YESNO_INLINE_TYPES.indexOf(desc.datatype) !== -1) return 1;
    if (desc.datatype === 'yesnowide' || desc.datatype === 'noyeswide') return 1;
    if (YESNO_RADIO_TYPES.indexOf(desc.datatype) !== -1) return 1;
    if (desc.inputType === 'radio' || desc.datatype === 'radio' || desc.datatype === 'object_radio') return 1;
    return 0;
  }

  function inputTypeClass(desc) {
    if (desc.inputType) return ' da-field-container-inputtype-' + desc.inputType;
    if (desc.datatype === 'checkboxes' || desc.datatype === 'object_checkboxes') {
      return ' da-field-container-inputtype-checkboxes';
    }
    if (desc.datatype === 'multiselect' || desc.datatype === 'object_multiselect') {
      return ' da-field-container-inputtype-multiselect';
    }
    if (desc.datatype === 'object_radio') return ' da-field-container-inputtype-radio';
    if (desc.choices || desc.choiceCode || desc.datatype === 'dropdown' || desc.datatype === 'object') {
      return ' da-field-container-inputtype-dropdown';
    }
    if (YESNO_INLINE_TYPES.indexOf(desc.datatype) !== -1 ||
        YESNO_RADIO_TYPES.indexOf(desc.datatype) !== -1 ||
        desc.datatype === 'yesnowide' || desc.datatype === 'noyeswide') {
      return ' da-field-container-inputtype-' + desc.datatype;
    }
    return '';
  }

  function conditionText(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value;
    if (typeof value === 'object' && value.variable !== undefined) {
      return String(value.variable) + ' is ' + JSON.stringify(value.is);
    }
    return JSON.stringify(value);
  }

  /* The JavaScript twin of standardformatter.field_item() for the ungridded
   * case: one container, an optional label, and a content div whose classes
   * depend on the layout. */
  function fieldItem(spec) {
    var classes = ['da-container'];
    if (spec.useFieldset) classes.push('da-fieldset');
    if (!spec.floating) classes.push('da-form-group');
    if (spec.row) classes.push('row');
    if (spec.floating) classes.push('da-form-group-floating', 'form-floating', 'mb-3');
    (spec.classes || []).forEach(function (name) { if (name) classes.push(name); });

    var attrs = '';
    if (spec.useFieldset) {
      attrs += ' aria-labelledby="' + attr(spec.labelId) + '"';
      if (spec.required) attrs += ' aria-required="true"';
      if (spec.useFieldset === 1) attrs += ' role="radiogroup"';
    }
    if (spec.condition) attrs += ' data-dapv-condition="' + attr(spec.condition) + '"';

    var labelHtml = '';
    if (spec.labelContent) {
      var labelTag = spec.useFieldset ? 'div' : 'label';
      var labelClasses = [];
      if (spec.useFieldset) labelClasses.push('da-legend');
      (spec.labelClasses || []).forEach(function (name) { if (name) labelClasses.push(name); });
      labelHtml = '<' + labelTag + (spec.useFieldset ? ' id="' + attr(spec.labelId) + '"' : '') +
        (spec.labelFor && !spec.useFieldset ? ' for="' + attr(spec.labelFor) + '"' : '') +
        (labelClasses.length ? ' class="' + labelClasses.join(' ') + '"' : '') + '>' +
        spec.labelContent + '</' + labelTag + '>';
    }

    var html = '<div class="' + classes.join(' ') + '"' + attrs + '>';
    if (labelHtml && !spec.floating) html += labelHtml;
    var contentClasses = (spec.contentClasses || []).filter(Boolean);
    if (contentClasses.length) {
      html += '<div class="' + contentClasses.join(' ') + '" aria-live="polite">' + spec.content + '</div>';
    } else {
      html += spec.content;
    }
    if (labelHtml && spec.floating) html += labelHtml;
    html += '</div>';
    return html;
  }

  function renderFieldItem(desc, index, options) {
    var opts = options || {};
    var layout = LABEL_LAYOUTS.indexOf(opts.labelLayout) !== -1 ? opts.labelLayout : 'horizontal';
    var report = opts.report;
    var id = fieldId(index);

    if (desc.kind === 'note') {
      return '<div class="da-container da-form-group danote">' +
        renderMarkdown(desc.content, report, opts.context) + '</div>';
    }
    if (desc.kind === 'html') {
      return '<div class="da-container da-form-group dahtml">' +
        sanitizeHtml(desc.content, report) + '</div>';
    }
    if (desc.kind === 'hidden') return '';

    var placement = labelPlacement(desc, layout);
    var useFieldset = fieldsetKind(desc);
    var hasLabelText = Boolean(String(desc.label || '').trim());
    var isYesNoInline = YESNO_INLINE_TYPES.indexOf(desc.datatype) !== -1;
    var isFile = FILE_DATATYPES.indexOf(desc.datatype) !== -1;
    var fieldClass = 'da-field-container da-field-container-datatype-' + desc.datatype + inputTypeClass(desc);
    var requiredClass = desc.required ? 'darequired' : '';
    var condition = desc.showIf
      ? 'show if: ' + conditionText(desc.showIf)
      : (desc.hideIf ? 'hide if: ' + conditionText(desc.hideIf) : '');
    var labelContent = hasLabelText
      ? renderInlineMarkdown(desc.label, report, opts.context) + helpMarkup(desc)
      : '';
    // Checkbox groups have no single control for a `for` attribute to name.
    var labelFor = (desc.datatype === 'checkboxes' || desc.datatype === 'object_checkboxes' || useFieldset)
      ? '' : id;

    var base = {
      condition: condition,
      required: desc.required,
      useFieldset: useFieldset,
      labelId: 'da-label-' + index,
      labelFor: labelFor,
      content: renderInput(desc, id),
    };

    function build(extra) {
      var spec = {};
      Object.keys(base).forEach(function (key) { spec[key] = base[key]; });
      Object.keys(extra).forEach(function (key) { spec[key] = extra[key]; });
      return fieldItem(spec);
    }

    if (placement === 'wide') {
      return build({
        row: true,
        classes: [isYesNoInline || desc.datatype === 'yesnowide' || desc.datatype === 'noyeswide' ? 'dayesnospacing' : '',
          desc.noLabel ? requiredClass : '', fieldClass, 'da-field-container-nolabel'],
        contentClasses: ['col', 'dawidecol', 'dafieldpart'],
      });
    }

    if (placement === 'floating') {
      if (isYesNoInline) {
        return build({
          classes: ['dayesnospacing', fieldClass, 'da-field-container-nolabel'],
          contentClasses: ['offset-' + GRID_LABEL_WIDTH, 'col-' + GRID_FIELD_WIDTH, 'dafieldpart'],
        });
      }
      if (!hasLabelText) {
        return build({
          classes: [requiredClass, fieldClass, 'da-field-container-emptylabel'],
          contentClasses: ['dafieldpart'],
        });
      }
      if (isFile) {
        return build({
          classes: [requiredClass, fieldClass],
          labelContent: labelContent,
          labelClasses: ['form-label', 'da-top-label'],
          contentClasses: ['dafieldpart'],
        });
      }
      // A floating label is drawn over the control, so the placeholder carries
      // the text and the <label> follows the input.
      var floatingDesc = {};
      Object.keys(desc).forEach(function (key) { floatingDesc[key] = desc[key]; });
      floatingDesc.hint = String(desc.label || '');
      return build({
        floating: true,
        classes: [requiredClass, fieldClass],
        labelContent: labelContent,
        content: renderInput(floatingDesc, id),
      });
    }

    if (placement === 'above') {
      if (isYesNoInline) {
        return build({
          classes: ['dayesnospacing', fieldClass, 'da-field-container-nolabel'],
          contentClasses: ['dafieldpart'],
        });
      }
      if (!hasLabelText) {
        return build({
          classes: [requiredClass, fieldClass, 'da-field-container-emptylabel'],
          contentClasses: ['dafieldpart'],
        });
      }
      return build({
        classes: [requiredClass, fieldClass],
        labelContent: labelContent,
        labelClasses: ['form-label', 'da-top-label'],
        contentClasses: ['dafieldpart'],
      });
    }

    // horizontal — Docassemble's default: label to the left of the field.
    if (isYesNoInline) {
      return build({
        row: true,
        classes: ['dayesnospacing', requiredClass, fieldClass, 'da-field-container-emptylabel'],
        contentClasses: ['offset-' + GRID_LABEL_WIDTH, 'col-' + GRID_FIELD_WIDTH, 'dafieldpart'],
      });
    }
    if (!hasLabelText) {
      return build({
        row: true,
        classes: [requiredClass, fieldClass, 'da-field-container-emptylabel'],
        contentClasses: ['offset-' + GRID_LABEL_WIDTH, 'col-' + GRID_FIELD_WIDTH, 'dafieldpart', 'danolabel'],
      });
    }
    return build({
      row: true,
      classes: [requiredClass, fieldClass],
      labelContent: labelContent,
      labelClasses: ['col-' + GRID_LABEL_WIDTH, 'col-form-label', 'da-form-label', 'datext-right'],
      contentClasses: ['col-' + GRID_FIELD_WIDTH, 'dafieldpart'],
    });
  }

  // -------------------------------------------------------------------------
  // table: blocks
  //
  // The rows are whatever the list holds at runtime, so the preview invents two
  // of them. The cell expressions say what each column is for, which is enough
  // to pick sample text that reads like a real ALPeopleList table rather than
  // "value 1 / value 2".
  // -------------------------------------------------------------------------

  var SAMPLE_CELL_VALUES = [
    [/address|on_one_line|\bblock\s*\(/i, ['123 Main St, Boston, MA 02114', '45 Oak Ave, Apt 2, Somerville, MA 02143']],
    [/e-?mail/i, ['alex.kim@example.com', 'jordan.rivera@example.com']],
    [/phone|mobile|sms/i, ['(617) 555-0134', '(617) 555-0198']],
    [/birth|dob|\bage\b/i, ['January 4, 1985', 'March 22, 1990']],
    [/pronoun/i, ['they/them/theirs', 'she/her/hers']],
    [/gender/i, ['Nonbinary', 'Female']],
    [/language/i, ['English', 'Spanish']],
    [/relationship|role|party/i, ['Parent', 'Sibling']],
    [/\bname\b|familiar|full\s*\(/i, ['Alex Kim', 'Jordan Rivera']],
    [/date|filed|served/i, ['June 3, 2026', 'July 18, 2026']],
    [/amount|income|rent|cost|\$/i, ['$1,450.00', '$980.00']],
    [/yes|no|has_|is_|\bboolean\b/i, ['Yes', 'No']],
  ];

  function sampleCellValue(expression, rowIndex) {
    var text = String(expression || '');
    for (var i = 0; i < SAMPLE_CELL_VALUES.length; i++) {
      if (SAMPLE_CELL_VALUES[i][0].test(text)) return SAMPLE_CELL_VALUES[i][1][rowIndex % 2];
    }
    return rowIndex % 2 === 0 ? 'First value' : 'Second value';
  }

  function tableColumns(data) {
    var columns = Array.isArray(data.columns) ? data.columns : [];
    return columns.map(function (column) {
      if (!column || typeof column !== 'object') {
        return { header: String(column || ''), cell: '' };
      }
      if (column.header !== undefined && column.cell !== undefined) {
        return { header: String(column.header), cell: String(column.cell).trim() };
      }
      var key = Object.keys(column)[0];
      return { header: String(key === undefined ? '' : key), cell: String(column[key] || '').trim() };
    });
  }

  /* DAList.item_actions: an Edit and a Delete button per row. */
  function itemActionsHtml(options) {
    var html = '';
    if (options.edit !== false) {
      html += '<a href="#" role="button" class="btn btn-sm btn-secondary btn-darevisit">' +
        '<span class="text-nowrap"><i class="fa-solid fa-pencil-alt"></i> Edit</span></a> ';
    }
    if (options.del !== false) {
      html += '<a href="#" role="button" class="btn btn-sm btn-danger btn-darevisit' +
        (options.confirm ? ' daremovebutton' : '') + '">' +
        '<span class="text-nowrap"><i class="fa-solid fa-trash"></i> Delete</span></a>';
    }
    return html;
  }

  /* DAList.add_action */
  function addActionHtml(args) {
    var parsed = parseArguments(args);
    var label = argValue(parsed, 'label', null) || argValue(parsed, 'message', null) || 'Add another';
    var color = argValue(parsed, 'color', 'secondary');
    if (BUTTON_COLORS.indexOf(color) === -1 || color === 'link' || color === 'tertiary') color = 'success';
    var requested = argValue(parsed, 'size', 'sm');
    if (['sm', 'md', 'lg'].indexOf(requested) === -1) requested = 'sm';
    var size = requested === 'md' ? '' : ' btn-' + requested;
    var icon = argValue(parsed, 'icon', null);
    if (icon === null) icon = 'plus-circle';
    var iconMarkup = icon
      ? '<i class="' + (/^fa[a-z] fa-/.test(icon) ? icon : 'fa-solid fa-' + String(icon).replace(/^(fa[a-z])-fa-/, '')) + '"></i> '
      : '';
    return '<a href="#" class="btn' + size + (argValue(parsed, 'block', false) ? ' btn-block' : '') +
      ' btn-' + color + ' btn-darevisit">' + iconMarkup + esc(label) + '</a>';
  }

  function renderTable(data, options) {
    var opts = options || {};
    var block = data || {};
    var columns = tableColumns(block);
    var hasEdit = block.edit !== undefined && block.edit !== false;
    var hasDelete = Boolean(block['delete buttons']);
    var reorder = block['allow reordering'] !== undefined && block['allow reordering'] !== false;
    var showActions = hasEdit || hasDelete || reorder;
    var actionsHeader = block['edit header'] !== undefined
      ? String(block['edit header'])
      : 'Actions';
    var tableClass = opts.tableClass || 'table table-striped';

    if (!columns.length) {
      return '<div class="dapv-empty-table text-muted">This table has no columns yet.</div>';
    }

    var html = '<div class="table-responsive"><table class="' + attr(tableClass) + '"><thead><tr>';
    columns.forEach(function (column) {
      html += '<th>' + (column.header ? renderInlineMarkdown(column.header, opts.report, opts.context) : '&nbsp;') + '</th>';
    });
    if (showActions) html += '<th>' + (actionsHeader ? esc(actionsHeader) : '&nbsp;') + '</th>';
    html += '</tr></thead><tbody>';
    for (var row = 0; row < 2; row++) {
      html += '<tr>';
      columns.forEach(function (column) {
        html += '<td>' + esc(sampleCellValue(column.cell || column.header, row)) + '</td>';
      });
      if (showActions) {
        html += '<td>' + itemActionsHtml({
          edit: hasEdit,
          del: hasDelete || hasEdit,
          confirm: Boolean(block.confirm),
        }) + '</td>';
      }
      html += '</tr>';
    }
    html += '</tbody></table></div>';
    return html;
  }

  // -------------------------------------------------------------------------
  // Whole-screen rendering
  // -------------------------------------------------------------------------

  var DEFAULT_GRID_CLASS = 'col-xl-6 col-lg-8 col-md-10 offset-xl-3 offset-lg-2 offset-md-1';

  /* AssemblyLine's al_visual.yml renames Docassemble's "Back" to "Undo" in its
   * default screen parts, and that is the house style this editor builds for. */
  var DEFAULT_BACK_BUTTON_LABEL = 'Undo';

  // -------------------------------------------------------------------------
  // review: screens
  //
  // Docassemble draws each item either as a plain link to revisit the answer,
  // or — when the item has a `button:` — as a button beside the answer text.
  // -------------------------------------------------------------------------

  var REVIEW_RESERVED_KEYS = ['button', 'help', 'show if', 'hide if', 'css class', 'fields', 'label', 'note', 'html'];

  function describeReviewItem(raw) {
    if (typeof raw === 'string') {
      return { kind: 'label', label: raw, action: raw };
    }
    if (!raw || typeof raw !== 'object') return null;
    if (Object.prototype.hasOwnProperty.call(raw, 'note')) {
      return { kind: 'note', content: String(raw.note || ''), condition: raw['show if'] || raw['hide if'] || null };
    }
    if (Object.prototype.hasOwnProperty.call(raw, 'html')) {
      return { kind: 'html', content: String(raw.html || ''), condition: raw['show if'] || raw['hide if'] || null };
    }
    var label = raw.label ? String(raw.label) : '';
    var action = '';
    Object.keys(raw).forEach(function (key) {
      if (REVIEW_RESERVED_KEYS.indexOf(key) !== -1 || action) return;
      action = key;
    });
    if (!label && action) label = action;
    return {
      kind: raw.button !== undefined ? 'button' : 'label',
      label: label || 'Edit',
      action: action || (Array.isArray(raw.fields) ? String(raw.fields[0] || '') : ''),
      text: raw.button !== undefined ? String(raw.button || '') : String(raw.help || ''),
      condition: raw['show if'] || raw['hide if'] || null,
    };
  }

  function renderReviewItems(items, opts) {
    var tabularClass = opts.tabular;
    var html = '';
    (Array.isArray(items) ? items : []).forEach(function (raw) {
      var item = describeReviewItem(raw);
      if (!item) return;
      var condition = item.condition
        ? ' data-dapv-condition="' + attr('show if: ' + conditionText(item.condition)) + '"'
        : '';

      if (item.kind === 'note' || item.kind === 'html') {
        var content = item.kind === 'html'
          ? sanitizeHtml(item.content, opts.report)
          : renderMarkdown(item.content, opts.report, opts.context);
        if (tabularClass) {
          html += '<tr class="da-field-container da-field-container-note da-review"' + condition +
            '><td colspan="2">' + content + '</td></tr>';
        } else {
          html += '<div class="row da-field-container da-field-container-note da-review da-review-button pt-2 my-2"' +
            condition + '><div class="col">' + content + '</div></div>';
        }
        return;
      }

      var labelHtml = renderInlineMarkdown(item.label, opts.report, opts.context);
      if (item.kind === 'button') {
        var buttonHtml = '<a href="#" role="button" class="btn btn-sm btn-' + esc(opts.reviewButtonColor) +
          ' da-review-action da-review-action-button' + (tabularClass ? '' : ' ms-2 mb-1') + '">' +
          iconHtml(opts.reviewButtonIcon) + ' ' + labelHtml + '</a>';
        var text = renderMarkdown(item.text, opts.report, opts.context);
        if (tabularClass) {
          html += '<tr class="da-review da-review-button-tabular"' + condition + '><td>' + text +
            '</td><td>' + buttonHtml + '</td></tr>';
        } else {
          html += '<div class="row da-review da-review-button bg-secondary-subtle pt-2 my-2"' + condition +
            '><div class="col">' + buttonHtml + text + '</div></div>';
        }
        return;
      }

      if (tabularClass) {
        html += '<tr class="da-review da-review-label"' + condition +
          '><td colspan="2"><a href="#" class="da-review-action">' + labelHtml + '</a></td></tr>';
      } else {
        html += '<div class="da-form-group row da-review da-review-label"' + condition +
          '><div class="col"><a href="#" class="da-review-action">' + labelHtml + '</a></div></div>';
      }
      if (item.text) {
        var helpHtml = renderMarkdown(item.text, opts.report, opts.context);
        if (tabularClass) {
          html += '<tr class="da-review da-review-help"><td colspan="2">' + helpHtml + '</td></tr>';
        } else {
          html += '<div class="row da-review da-review-help"><div class="col">' + helpHtml + '</div></div>';
        }
      }
    });
    return html;
  }

  function renderReview(data, options) {
    var opts = options || {};
    var block = data || {};
    var report = {};
    var context = opts.interview || null;
    var notes = [];
    var items = Array.isArray(block.review) ? block.review : [];
    var tabularClass = '';
    if (block.tabular) {
      tabularClass = typeof block.tabular === 'string' ? block.tabular : 'table table-borderless';
    }
    var itemOptions = {
      tabular: tabularClass,
      report: report,
      context: context,
      reviewButtonColor: opts.reviewButtonColor || 'secondary',
      reviewButtonIcon: opts.reviewButtonIcon || 'pencil-alt',
    };

    var html = '';
    html += '<div id="daquestion" aria-labelledby="dapagetitle" role="main" class="tab-pane fade show active ' +
      esc(opts.gridClass || DEFAULT_GRID_CLASS) + '">';
    html += '<form aria-labelledby="daMainQuestion" action="#" id="daform" class="form-horizontal daformreview" method="POST" onsubmit="return false;">';
    html += '<div class="da-page-header"><h1 class="h3" id="daMainQuestion">' +
      renderInlineMarkdown(block.question || 'Review your answers', report, context) +
      '</h1><div class="daclear"></div></div>';
    if (block.subquestion) {
      html += '<div class="da-subquestion">' + renderMarkdown(block.subquestion, report, context) + '</div>';
    }
    if (items.length) {
      var itemsHtml = renderReviewItems(items, itemOptions);
      if (tabularClass) {
        html += '<table class="da-review-tabular ' + attr(tabularClass) + '"><tbody>' + itemsHtml + '</tbody></table>';
      } else {
        html += itemsHtml;
      }
    } else {
      notes.push('This review screen has no items yet, so only its heading and the Resume button are shown.');
    }
    html += '<fieldset class="da-button-set da-field-buttons">';
    html += '<legend class="visually-hidden">Press one of the following buttons:</legend>';
    if (opts.showBackButton !== false) {
      html += '<button type="button" class="btn btn-link btn-da daquestionbackbutton danonsubmit" ' +
        'title="Go back to the previous question"><i class="fa-solid fa-chevron-left me-1"></i>' +
        esc(opts.backButtonLabel || DEFAULT_BACK_BUTTON_LABEL) + '</button>';
    }
    // A review screen's continue button says "Resume" unless the author or the
    // interview's default screen parts rename it.
    html += '<button class="btn btn-' + esc(opts.continueButtonColor || 'primary') + ' btn-da" type="submit">' +
      esc(block['continue button label'] || opts.continueButtonLabel || 'Resume') + '</button>';
    html += '</fieldset>';
    html += '</form>';
    html += '</div>';

    (report.placeholders || []).forEach(function (kind) {
      if (PLACEHOLDER_NOTES[kind]) notes.push(kind && PLACEHOLDER_NOTES[kind]);
    });
    if (report.scriptRemoved) {
      notes.push('Your HTML is rendered as HTML, but <script> tags and inline event handlers were left out of the preview. The running interview still executes them.');
    }
    (opts.notes || []).forEach(function (note) { notes.push(note); });
    return { html: html, notes: notes, itemCount: items.length };
  }

  function renderQuestion(data, options) {
    var opts = options || {};
    var block = data || {};
    var described = describeFields(block.fields);
    var notes = described.notes.slice();
    var buttonColor = opts.continueButtonColor || 'primary';
    var report = {};
    var labelLayout = LABEL_LAYOUTS.indexOf(opts.labelLayout) !== -1 ? opts.labelLayout : 'horizontal';
    var context = opts.interview || null;
    var html = '';

    html += '<div id="daquestion" aria-labelledby="dapagetitle" role="main" class="tab-pane fade show active ' +
      esc(opts.gridClass || DEFAULT_GRID_CLASS) + '">';
    html += '<form aria-labelledby="daMainQuestion" action="#" id="daform" class="form-horizontal daformfields" method="POST" onsubmit="return false;">';
    html += '<div class="da-page-header"><h1 class="h3" id="daMainQuestion">' +
      renderInlineMarkdown(block.question || '(no question text)', report, context) +
      '</h1><div class="daclear"></div></div>';
    if (block.subquestion) {
      html += '<div class="da-subquestion">' + renderMarkdown(block.subquestion, report, context) + '</div>';
    }

    described.fields.forEach(function (desc, index) {
      html += renderFieldItem(desc, index, {
        labelLayout: labelLayout,
        report: report,
        context: context,
      });
    });

    // Docassemble emits the back button first, so it sits to the left of
    // Continue. AssemblyLine renames it "Undo" in its default screen parts.
    html += '<fieldset class="da-button-set da-field-buttons">';
    html += '<legend class="visually-hidden">Press one of the following buttons:</legend>';
    if (opts.showBackButton !== false) {
      html += '<button type="button" class="btn btn-link btn-da daquestionbackbutton danonsubmit" ' +
        'title="Go back to the previous question"><i class="fa-solid fa-chevron-left me-1"></i>' +
        esc(opts.backButtonLabel || DEFAULT_BACK_BUTTON_LABEL) + '</button>';
    }
    html += '<button class="btn btn-' + esc(buttonColor) + ' btn-da" type="submit">' +
      esc(block['continue button label'] || opts.continueButtonLabel || 'Continue') + '</button>';
    html += '</fieldset>';
    html += '</form>';
    if (block.help) {
      html += '<div class="dahelp"><h2 class="h4">Help</h2>' + renderMarkdown(block.help, report, context) + '</div>';
    }
    html += '</div>';

    if (!described.fields.length && !String(block.subquestion || '').trim()) {
      notes.push('This screen has no fields, so only the question text and Continue button are shown.');
    }
    (report.placeholders || []).forEach(function (kind) {
      if (PLACEHOLDER_NOTES[kind]) notes.push(PLACEHOLDER_NOTES[kind]);
    });
    if (report.scriptRemoved) {
      notes.push('Your HTML is rendered as HTML, but <script> tags and inline event handlers were left out of the preview. The running interview still executes them.');
    }
    (opts.notes || []).forEach(function (note) { notes.push(note); });
    return {
      html: html,
      notes: notes,
      fieldCount: described.fields.length,
      labelLayout: labelLayout,
    };
  }

  // -------------------------------------------------------------------------
  // Reading the rest of the interview
  //
  // Widgets look better when they show the author's own templates and bundles
  // instead of filler, and the editor has already parsed every block, so pull
  // what we can out of the file.
  // -------------------------------------------------------------------------

  function _keywordFromCall(declaration, keyword) {
    var pattern = new RegExp(keyword + '\\s*=\\s*(?:"([^"]*)"|\'([^\']*)\')');
    var match = String(declaration).match(pattern);
    if (!match) return null;
    return match[1] !== undefined ? match[1] : match[2];
  }

  function _elementsFromCall(declaration) {
    var match = String(declaration).match(/elements\s*=\s*\[([\s\S]*?)\]/);
    if (!match) return [];
    return match[1]
      .split(',')
      .map(function (item) { return item.trim(); })
      .filter(function (item) { return /^[A-Za-z_][A-Za-z0-9_.]*$/.test(item); });
  }

  /* ``blocks`` is the editor's parsed block list; each entry carries the YAML
   * document as ``.data``. */
  function buildInterviewContext(blocks) {
    var templates = {};
    var documents = {};
    var bundles = {};
    var tables = {};

    (Array.isArray(blocks) ? blocks : []).forEach(function (block) {
      var data = block && block.data;
      if (!data || typeof data !== 'object') return;

      if (typeof data.template === 'string' && data.template.trim()) {
        templates[data.template.trim()] = {
          subject: data.subject === undefined || data.subject === null ? '' : String(data.subject),
          content: data.content === undefined || data.content === null ? '' : String(data.content),
        };
      }

      if (typeof data.table === 'string' && data.table.trim()) {
        tables[data.table.trim()] = data;
      }

      var objects = data.objects;
      if (!Array.isArray(objects)) return;
      objects.forEach(function (entry) {
        if (!entry || typeof entry !== 'object') return;
        Object.keys(entry).forEach(function (name) {
          var declaration = String(entry[name] === undefined || entry[name] === null ? '' : entry[name]);
          if (/ALDocumentBundle\s*\.\s*using/.test(declaration)) {
            bundles[name] = {
              title: _keywordFromCall(declaration, 'title'),
              filename: _keywordFromCall(declaration, 'filename'),
              elements: _elementsFromCall(declaration),
            };
          } else if (/ALDocument\s*\.\s*using/.test(declaration)) {
            documents[name] = {
              title: _keywordFromCall(declaration, 'title'),
              filename: _keywordFromCall(declaration, 'filename'),
            };
          }
        });
      });
    });

    return { templates: templates, documents: documents, bundles: bundles, tables: tables };
  }

  /* A table: block defines a variable rather than a screen, so there is no form
   * or button set to draw — just the table, in the page chrome that styles it. */
  function renderTableBlock(data, options) {
    var opts = options || {};
    var block = data || {};
    var report = {};
    var name = String(block.table || 'table');
    var html = '';
    html += '<div id="daquestion" aria-labelledby="dapagetitle" role="main" class="tab-pane fade show active ' +
      esc(opts.gridClass || DEFAULT_GRID_CLASS) + '">';
    html += '<div class="da-page-header"><h1 class="h3" id="daMainQuestion"><code>${ ' + esc(name) +
      ' }</code></h1><div class="daclear"></div></div>';
    html += renderTable(block, { report: report, context: opts.interview || null });
    if (block.rows) {
      html += '<p>' + addActionHtml('') + '</p>';
    }
    html += '</div>';
    var notes = [PLACEHOLDER_NOTES.rows];
    if (block.rows) {
      notes.push('A table block defines a variable. This is how ${ ' + name +
        ' } will look wherever a screen refers to it.');
    }
    (opts.notes || []).forEach(function (note) { notes.push(note); });
    return { html: html, notes: notes };
  }

  /* Pick the renderer from the shape of the block, the way Docassemble picks a
   * question type from the keys it finds. */
  function renderScreen(data, options) {
    var block = data || {};
    if (Array.isArray(block.review)) return renderReview(block, options);
    if (typeof block.table === 'string' && block.table.trim()) return renderTableBlock(block, options);
    return renderQuestion(block, options);
  }

  /* What a `features:` block asks for, or null when it says nothing — in which
   * case Docassemble's own default (horizontal) applies. */
  function labelLayoutFromFeatures(features) {
    if (!features || typeof features !== 'object') return null;
    if (features['floating labels'] === true) return 'floating';
    if (features['labels above fields'] === true) return 'above';
    if (features['labels above fields'] === false) return 'horizontal';
    return null;
  }

  // -------------------------------------------------------------------------
  // The iframe document
  // -------------------------------------------------------------------------

  /* Docassemble serves all of these from its own webapp static folder, at the
   * same URLs on 1.9.x and 1.10.x — the 1.10 blueprint refactor renamed Flask
   * endpoints but not the ``/static`` paths, and the asset files themselves are
   * byte-identical between the two. */
  var DEFAULT_ASSETS = {
    bootstrapCss: '/static/bootstrap/css/bootstrap.min.css',
    bundleCss: '/static/app/bundle.css',
    fontAwesome: '/static/fontawesome/js/all.min.js',
    jquery: '/static/app/jquery.min.js',
    labelauty: '/static/labelauty/source/jquery-labelauty.min.js',
    bootstrapJs: '/static/bootstrap/js/bootstrap.bundle.min.js',
  };

  /* Conditional fields are annotated rather than hidden, so an author can see
   * every branch at once. The marker takes a whole flex line and the rule uses
   * an inset shadow so it never shifts a Bootstrap row's own layout. */
  var PREVIEW_CSS = [
    'body { background-color: var(--bs-body-bg); }',
    '.dapv-mako, .dapv-mako-line code { background: rgba(13,110,253,.08); color: #0a58ca; border-radius: 3px; padding: 0 .25em; font-size: .9em; }',
    '[data-dapv-condition] { box-shadow: inset 2px 0 0 rgba(108,117,125,.5); }',
    '[data-dapv-condition]::before { content: attr(data-dapv-condition); display: block; flex: 0 0 100%; width: 100%; font-size: .72rem; font-family: monospace; color: #6c757d; margin-bottom: .2rem; padding-left: .6rem; }',
    '.dapv-notes { font-size: .8rem; }',
    // Which caret a collapse shows is decided purely in CSS. The preview emits
    // both spans, so without a rule they both draw; repeat ALToolbox's own
    // toggle here so the widget is right even where that package is missing.
    '.al_collapse_template a span.pdcaretopen { display: inline; }',
    '.al_collapse_template a span.pdcaretclosed { display: none; }',
    '.al_collapse_template a.collapsed .pdcaretopen { display: none; }',
    '.al_collapse_template a.collapsed .pdcaretclosed { display: inline; }',
  ].join('\n');

  function buildDocument(data, options) {
    var opts = options || {};
    var assets = {};
    Object.keys(DEFAULT_ASSETS).forEach(function (key) { assets[key] = DEFAULT_ASSETS[key]; });
    Object.keys(opts.assets || {}).forEach(function (key) { assets[key] = opts.assets[key]; });
    var rendered = renderScreen(data, opts);
    var theme = opts.theme === 'dark' ? 'dark' : 'light';

    var head = '';
    head += '<meta charset="utf-8">';
    head += '<meta name="viewport" content="width=device-width, initial-scale=1">';
    if (assets.fontAwesome) head += '<script defer src="' + attr(assets.fontAwesome) + '"></script>';
    if (assets.bootstrapCss) head += '<link rel="stylesheet" href="' + attr(assets.bootstrapCss) + '">';
    // If an installation ever moves this bundle, say so instead of quietly
    // showing an unstyled screen that the author would read as a real result.
    if (assets.bundleCss) {
      head += '<link rel="stylesheet" href="' + attr(assets.bundleCss) +
        '" onerror="document.documentElement.setAttribute(\'data-dapv-css-missing\', \'' +
        attr(assets.bundleCss) + '\')">';
    }
    (opts.extraCss || []).forEach(function (href) {
      head += '<link rel="stylesheet" href="' + attr(href) + '">';
    });
    head += '<style>' + PREVIEW_CSS + '</style>';

    var body = '';
    body += '<div id="dabody"><div class="container"><div class="row tab-content">';
    body += rendered.html;
    body += '</div>';
    if (rendered.notes.length) {
      body += '<div class="row"><div class="col"><div class="alert alert-secondary dapv-notes mt-3" role="note"><strong>Preview notes</strong><ul class="mb-0">';
      rendered.notes.forEach(function (note) { body += '<li>' + esc(note) + '</li>'; });
      body += '</ul></div></div></div>';
    }
    body += '</div></div>';

    var script = '';
    if (assets.jquery && assets.labelauty) {
      script += '<script src="' + attr(assets.jquery) + '"></script>';
      script += '<script src="' + attr(assets.labelauty) + '"></script>';
    }
    if (assets.bootstrapJs) script += '<script src="' + attr(assets.bootstrapJs) + '"></script>';
    script += '<script>(function(){' +
      'if (window.jQuery && jQuery.fn.labelauty) {' +
      'jQuery(".da-to-labelauty").labelauty({class: "labelauty da-active-invisible dafullwidth"});' +
      'jQuery(".da-to-labelauty-icon").labelauty({label: false});' +
      '}' +
      'if (window.bootstrap && bootstrap.Popover) {' +
      'Array.prototype.forEach.call(document.querySelectorAll(\'[data-bs-toggle="popover"]\'), function (el) { new bootstrap.Popover(el, {html: true}); });' +
      '}' +
      'document.addEventListener("submit", function (e) { e.preventDefault(); });' +
      'var missing = document.documentElement.getAttribute("data-dapv-css-missing");' +
      'if (missing) {' +
      'var warning = document.createElement("div");' +
      'warning.style.cssText = "margin:1rem;padding:.75rem;border:1px solid #f5c2c7;background:#f8d7da;color:#58151c;font-family:sans-serif";' +
      'warning.textContent = "This preview could not load " + missing + ", so it is not showing Docassemble\'s real styling.";' +
      'document.body.insertBefore(warning, document.body.firstChild);' +
      '}' +
      '})();</script>';

    return '<!DOCTYPE html><html lang="en" data-bs-theme="' + theme + '"><head>' + head +
      '<title>Screen preview</title></head><body class="dabody">' + body + script + '</body></html>';
  }

  return {
    AL_METHOD_NAMES: AL_METHOD_NAMES,
    DEFAULT_ASSETS: DEFAULT_ASSETS,
    LABEL_LAYOUTS: LABEL_LAYOUTS,
    DEFAULT_LABEL_LAYOUT: 'horizontal',
    DEFAULT_BACK_BUTTON_LABEL: DEFAULT_BACK_BUTTON_LABEL,
    labelLayoutFromFeatures: labelLayoutFromFeatures,
    buildInterviewContext: buildInterviewContext,
    renderMakoWidget: renderMakoWidget,
    applyIconMarkup: applyIconMarkup,
    sanitizeHtml: sanitizeHtml,
    parseMethodCall: parseMethodCall,
    parseArguments: parseArguments,
    expandALMethod: expandALMethod,
    describeField: describeField,
    describeFields: describeFields,
    renderMarkdown: renderMarkdown,
    renderInlineMarkdown: renderInlineMarkdown,
    renderQuestion: renderQuestion,
    renderReview: renderReview,
    renderTable: renderTable,
    renderScreen: renderScreen,
    buildDocument: buildDocument,
  };
});
