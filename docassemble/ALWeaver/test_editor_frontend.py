# do not pre-load

from collections import Counter
from html.parser import HTMLParser
import os
from pathlib import Path
import subprocess
import unittest

NODE_TESTS = (
    "test_editor_api_client.js",
    "test_editor_serializers.js",
    "test_editor_validation_source.js",
    "test_editor_agent_chat.js",
    "test_editor_screen_preview.js",
    "test_editor_interview_report.js",
    "test_editor_runtime_inspector.js",
)


class _TemplateCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.actions = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if attributes.get("data-action"):
            self.actions.append(attributes["data-action"])


class TestEditorFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package_dir = Path(__file__).resolve().parent

    def test_frontend_module_suites(self):
        for filename in NODE_TESTS:
            with self.subTest(filename=filename):
                completed = subprocess.run(
                    ["node", str(self.package_dir / filename)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"{filename} failed:\n{completed.stdout}\n{completed.stderr}",
                )

    def test_template_has_unique_ids_and_loads_local_modules_first(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        parser = _TemplateCollector()
        parser.feed(template)

        duplicates = [name for name, count in Counter(parser.ids).items() if count > 1]
        self.assertEqual(duplicates, [])
        self.assertLess(
            template.index("/static/app/cm6.min.js"), template.index("editor.js")
        )
        for module in (
            "editor_api_client.js",
            "editor_dirty_state.js",
            "editor_serializers.js",
            "editor_validation_source.js",
            "editor_agent_chat.js",
        ):
            self.assertLess(template.index(module), template.index("editor.js"))
        self.assertNotIn("monaco", editor.lower())
        self.assertNotIn("cdn.jsdelivr.net", editor)

    def test_project_search_is_preview_first_and_offers_safe_refactoring(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        self.assertIn('id="btn-project-search"', template)
        self.assertIn('id="project-search-modal"', template)
        self.assertIn('id="project-search-variable"', template)
        self.assertIn('id="project-search-results"', template)
        self.assertIn("/api/project/search", editor)
        self.assertIn("/api/project/replace", editor)
        self.assertIn("project_revision", editor)
        self.assertIn("data-project-search-match", editor)
        self.assertIn("Display text — unchanged", editor)
        self.assertIn("hasUnsavedChanges()", editor)
        self.assertIn(".editor-project-search-context", css)

    def test_interview_debugger_is_a_first_class_editor_workbench(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        runtime = (
            self.package_dir / "data/static/editor_runtime_inspector.js"
        ).read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        self.assertIn('id="btn-debug-interview"', template)
        self.assertIn('data-action="open-runtime-inspector"', template)
        self.assertLess(
            template.index("editor_runtime_inspector.js"), template.index("editor.js")
        )
        self.assertIn("editor-layout-runtime", editor)
        self.assertIn("onOpenSource: function (blockId)", editor)
        self.assertIn("Live interview", runtime)
        self.assertIn("Step recorder", runtime)
        self.assertIn("Session variables", runtime)
        self.assertIn("frame.addEventListener('load'", runtime)
        self.assertIn("recordObservation(nextQuestion", runtime)
        self.assertIn("refreshRenderedDebugger", runtime)
        self.assertIn("if (liveFrame)", runtime)
        self.assertIn("releaseSession: releaseSession", runtime)
        self.assertIn("runtimeInspector.releaseSession()", editor)
        # Leaving the debugger keeps the test session but tears down the panel,
        # so the once-a-second polling must not outlive the view that shows it,
        # and a late observation must not repaint over the editor canvas.
        self.assertIn("hidden = true;", runtime)
        self.assertIn("stopPolling();\n            onClose();", runtime)
        self.assertIn("if (!container || hidden) return;", runtime)
        self.assertIn("render: show,", runtime)
        self.assertIn(".editor-runtime-workbench", css)
        self.assertIn(".editor-runtime-frame", css)
        # Polling rebuilds the variable list every second; an expanded
        # <details> must stay expanded across that rebuild instead of
        # snapping shut mid-read.
        self.assertIn("var expandedVariables = {};", runtime)
        self.assertIn("details.open = Boolean(expandedVariables[name]);", runtime)
        self.assertIn("details.addEventListener('toggle'", runtime)
        # The step recorder shows each screen's stable name formatted exactly
        # as it appears in the source YAML (stripping Docassemble's own "ID "
        # prefix on Question.name), so it can be copied and searched for
        # directly in the source editor.
        self.assertIn("function blockIdLabel(questionName, questionType)", runtime)
        self.assertIn("meta.textContent = blockIdLabel(", runtime)
        # Rebuilding a panel every poll tick even when nothing changed can
        # sever a double-click's word-selection anchor mid-click, expanding
        # the selection to the nearest surviving ancestor. Skip the rebuild
        # when the underlying data is unchanged.
        self.assertIn("if (questionKey !== lastRenderedQuestionKey)", runtime)
        self.assertIn("if (stepsKey !== lastRenderedStepsKey)", runtime)

    def test_new_template_offers_a_blank_file_or_a_drafted_document(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        self.assertIn('id="new-template-modal"', template)
        self.assertIn('id="new-template-kind-blank"', template)
        self.assertIn('id="new-template-kind-report"', template)
        self.assertIn('id="new-template-report-filename"', template)
        self.assertIn('id="new-template-report-shape"', template)
        self.assertIn('id="new-template-report-profile"', template)
        self.assertIn('id="new-template-report-cos"', template)
        self.assertIn('id="new-template-report-numbering"', template)
        self.assertIn('id="new-template-report-vartypes"', template)
        self.assertIn('id="new-template-report-maxcols"', template)
        self.assertIn('id="new-template-report-markdown"', template)
        self.assertIn('id="new-template-report-intake-wrap"', template)
        self.assertIn('id="new-template-report-sources"', template)
        self.assertIn(".editor-choice-card", css)

        # Both ways in: the file list's "+ New", and Document setup itself.
        self.assertIn("function openNewTemplateModal()", editor)
        self.assertIn("if (state.currentView === 'templates') {", editor)
        self.assertIn('id="btn-new-template-setup"', editor)
        self.assertIn("apiPost('/api/template/variable-report'", editor)
        self.assertIn("/api/template/variable-report/suggestion?project=", editor)
        self.assertIn("applyVariableReportOptions(res.data)", editor)
        self.assertIn("payload.court_profile", editor)
        self.assertIn("payload.include_certificate_of_service", editor)

    def test_the_question_library_is_reachable_from_the_add_block_menu(self):
        """Not only from the checkbox on the new-project form.

        The AssemblyLine questions about people are what an author needs
        whenever they declare a new `ALPeopleList`, which is usually long after
        the project was created.
        """
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn('data-insert="question-library"', template)
        self.assertIn('id="question-library-modal"', template)
        self.assertIn('id="question-library-apply"', template)
        self.assertIn("function openQuestionLibraryPicker()", editor)
        self.assertIn("if (kind === 'question-library') {", editor)
        self.assertIn("/api/question-library?project=", editor)
        self.assertIn("apiPost('/api/question-library/insert'", editor)
        # The YAML is written by the server from the Weaver's own template, so
        # the browser sends only the object and the question it picked.
        self.assertIn("data-ql-var=", editor)
        self.assertIn("data-ql-kind=", editor)
        self.assertNotIn("block_yaml: questionLibrary", editor)
        # It reads and writes the saved file, so unsaved work lands first.
        self.assertIn(
            "promptAndSaveUnsavedChanges('add questions from the AssemblyLine library')",
            editor,
        )

    def test_the_question_library_can_declare_the_people_it_asks_about(self):
        """An interview that has no `witnesses` yet has no witness questions.

        Sending the author off to write an objects block by hand and come back
        is the gap the library was meant to close, so the picker declares the
        list itself.
        """
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn('id="question-library-new-name"', template)
        # An example belongs under the field, not inside it: placeholder text
        # disappears the moment someone starts typing.
        self.assertIn("Example: <code>witnesses</code>", template)
        self.assertIn('id="question-library-new-class"', template)
        self.assertIn('value="ALPeopleList"', template)
        self.assertIn('value="ALIndividual"', template)
        self.assertIn('id="question-library-add-object"', template)
        self.assertIn("apiPost('/api/question-library/object'", editor)
        # The quantity control is the objects editor's, wording and all.
        self.assertIn("PEOPLE_LIST_QUANTITY_MODES", editor)
        self.assertIn("data-ql-quantity-mode=", editor)
        # A new object redraws the list without losing boxes already ticked.
        self.assertIn("function questionLibrarySelection()", editor)
        self.assertIn("renderQuestionLibrary(previousSelection)", editor)
        # Declaring the list is not the same as gathering it, and where that
        # goes in the interview order is the author's call.
        self.assertIn("to your interview order so the interview asks them", editor)
        self.assertIn("'.gather()'", editor)

    def test_review_screen_is_re_synced_rather_than_appended(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("Sync from questions", editor)
        self.assertIn("mode: 'sync'", editor)
        self.assertIn("res.data.full_yaml", editor)
        # The draft is built from the file on disk.
        self.assertIn("promptAndSaveUnsavedChanges('sync the review screen')", editor)

    def test_a_synced_review_screen_is_reviewed_as_a_diff_not_as_the_whole_file(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        self.assertIn('id="review-sync-modal"', template)
        self.assertIn('data-review-sync-tab="diff"', template)
        self.assertIn('data-review-sync-tab="draft"', template)
        self.assertIn('id="review-sync-apply"', template)
        self.assertIn("function renderUnifiedDiffHtml(", editor)
        self.assertIn("function openReviewSyncModal(", editor)
        self.assertIn(".editor-diff-add", css)
        self.assertIn(".editor-diff-del", css)

        # Applying saves the file and comes back to the review block, rather
        # than leaving the author in a source editor for the whole interview.
        self.assertIn("function applyReviewSync(", editor)
        self.assertIn("selectReviewBlockAfterSync()", editor)
        # The full-YAML route stays available, as a deliberate choice.
        self.assertIn('id="review-sync-full-yaml"', template)
        self.assertIn("function openReviewSyncInFullYaml(", editor)

    def test_github_publish_uses_a_main_menu_modal_and_reports_the_commit(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn('data-action="open-github-publish"', template)
        self.assertIn('id="github-publish-modal"', template)
        self.assertIn('id="github-owner"', template)
        self.assertIn('id="github-package-name"', template)
        self.assertIn('id="github-branch-name"', template)
        self.assertIn('id="github-commit-message"', template)
        self.assertIn('id="github-repository-link"', template)
        self.assertIn('id="github-commit-link"', template)
        self.assertIn("promptAndSaveUnsavedChanges('publish to GitHub')", editor)
        self.assertIn("/api/github/status?project=", editor)
        self.assertIn("apiPost('/api/github/publish'", editor)
        self.assertIn("owner: ownerSelect ? ownerSelect.value : ''", editor)
        # Publishing is queued to Celery, so the modal polls the job instead of
        # reading a commit out of the POST response.
        self.assertIn("_pollGithubPublishJob(res.data.job_url)", editor)
        self.assertIn("data.async_configured === false", editor)
        self.assertIn("repositoryLink.href = result.repository_url", editor)
        self.assertIn("commitLink.href = result.commit_url", editor)
        self.assertNotIn("window.location.assign(res.data.publish_url)", editor)

        self.assertIn('data-action="pull-github"', template)
        self.assertIn("function pullGithubChanges()", editor)
        self.assertIn("apiPost('/api/github/pull'", editor)
        self.assertIn("Local changes will be preserved", editor)

    def test_people_list_quantity_has_a_control_instead_of_a_text_box(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        # The control only claims ALPeopleList, and only when the parameter
        # list is one it fully understands.
        self.assertIn("var PEOPLE_LIST_CLASSES = ['ALPeopleList'];", editor)
        self.assertIn("readPeopleListQuantity(usingArgs)", editor)
        self.assertIn("return quantity && quantity.editable ? quantity : null;", editor)
        self.assertIn("How many people?", editor)
        self.assertIn("Other .using() parameters", editor)

        # The save path, the redraw path and the question library's "add
        # someone new" form all compose through the same helper, so what "ask
        # how many" writes cannot drift between them.
        self.assertEqual(editor.count("composePeopleListUsingArgs("), 3)
        self.assertIn("function _syncObjectEditorRowsFromDom()", editor)
        self.assertIn("target.matches('[data-obj-quantity-mode]')", editor)
        self.assertIn("target.matches('[data-obj-prop=\"class\"]')", editor)

        self.assertIn(".editor-obj-quantity", css)
        self.assertIn(".editor-obj-quantity-number", css)

    def test_new_project_accepts_an_unrestricted_github_url(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn('id="new-project-github-url"', editor)
        self.assertIn("https://github.com/owner/docassemble-package", editor)
        self.assertIn("any public GitHub repository", editor)
        self.assertIn("github_url: githubUrl", editor)
        self.assertIn('id="project-github-import-url"', editor)
        self.assertIn('id="project-github-import-submit"', editor)
        self.assertIn("Create and pull", editor)
        self.assertIn(
            "apiPost('/api/new-project', { project_name: importName, github_url: importUrl })",
            editor,
        )

    def test_generated_block_id_marks_the_interview_dirty(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn(
            "idEl.dispatchEvent(new Event('input', { bubbles: true }))", editor
        )

    def test_project_pull_actions_are_scoped_to_synced_projects(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("projectSyncs: BOOT.projectSyncs || {}", editor)
        self.assertIn("if (state.projectSyncs[projectName])", editor)
        self.assertIn('data-project-action="pull-github"', editor)
        self.assertIn("state.canvasMode === 'project-selector'", editor)
        self.assertIn("state.project !== checkedProject", editor)

    def test_alindividual_field_helpers_have_a_group_and_options_modal(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        for method in (
            "name_fields",
            "address_fields",
            "gender_fields",
            "pronoun_fields",
            "language_fields",
        ):
            self.assertIn(f"{method}:", editor)
        self.assertIn("Assembly Line person fields", editor)
        self.assertIn('id="al-field-method-modal"', template)
        self.assertIn("data-al-field-method-options", editor)
        self.assertIn("editor-field-kebab-btn", editor)
        self.assertIn("!isALMethodType && dtype !== 'code'", editor)
        self.assertIn("DEFAULT_CODE_FIELD_EXPRESSION", editor)
        self.assertIn("'num_apples'", editor)
        self.assertIn("'num_oranges'", editor)
        self.assertIn("al_individual_primitives", editor)
        self.assertIn("_syncGeneratedALFieldSets", editor)
        self.assertIn("_renderQuestionFieldHelp(questionHelpTypes)", editor)
        self.assertIn("AssemblyLine.al_general.ALIndividual.name_fields", editor)
        self.assertIn("AssemblyLine.al_general.ALIndividual.address_fields", editor)
        # The prompts these methods generate live in the screen-preview module,
        # which reproduces the real AssemblyLine field lists.
        screen_preview = (
            self.package_dir / "data/static/editor_screen_preview.js"
        ).read_text()
        for expected_label in (
            "First name",
            "Middle name",
            "Last name",
            "Suffix",
            "Street address",
            "State / Province",
            "Self-described gender",
            "Choose one or more pronouns",
            "Language",
        ):
            self.assertIn(expected_label, screen_preview)
        self.assertIn(".editor-question-context-help", css)

    def test_screen_preview_opens_a_modal_styled_by_docassemble(self):
        """The preview must look like the running interview, not like the
        editor. It renders in an iframe so Docassemble's own stylesheets and
        the labelauty plugin can be loaded whole, with nothing leaking into the
        editor chrome either way."""
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()
        screen_preview = (
            self.package_dir / "data/static/editor_screen_preview.js"
        ).read_text()

        self.assertIn('id="screen-preview-modal"', template)
        self.assertIn('id="screen-preview-frame"', template)
        self.assertIn('data-preview-width="phone"', template)
        self.assertIn("editor_screen_preview.js", template)
        self.assertIn('data-action="open-screen-preview"', editor)
        self.assertIn("function openScreenPreview()", editor)
        self.assertIn(".editor-screen-preview-frame", css)

        # Docassemble serves these at the same URLs on 1.9.x and 1.10.x.
        self.assertIn("/static/app/bundle.css", screen_preview)
        self.assertIn(
            "/static/labelauty/source/jquery-labelauty.min.js", screen_preview
        )
        self.assertIn("da-to-labelauty", screen_preview)
        self.assertIn("da-page-header", screen_preview)
        self.assertIn("dafieldpart", screen_preview)

        # Layout and back-button labelling are pickable, and the picker starts
        # from what the interview itself declares.
        self.assertIn('id="screen-preview-layout"', template)
        self.assertIn('id="screen-preview-back-label"', template)
        self.assertIn("labelLayoutFromFeatures(features)", editor)
        self.assertIn("default screen parts", editor)
        self.assertIn("DEFAULT_BACK_BUTTON_LABEL", editor)

        # Expressions that become real screen furniture are drawn, not printed
        # as ${ code }, and use the interview's own documents and templates.
        self.assertIn("buildInterviewContext(state.blocks)", editor)
        self.assertIn("/packagestatic/docassemble.AssemblyLine/aldocument.css", editor)
        self.assertIn(
            "/packagestatic/docassemble.ALToolbox/collapse_template.css", editor
        )
        for widget in (
            "as_pdf",
            "download_list_html",
            "send_button_html",
            "collapse_template",
            "action_button_html",
        ):
            self.assertIn(widget, screen_preview)
        # Docassemble's :icon: markup, per filter.get_icon_html.
        self.assertIn("applyIconMarkup", screen_preview)
        self.assertIn("fa-brands", screen_preview)
        self.assertIn("da-paper-stack", screen_preview)
        self.assertIn("al_doc_table", screen_preview)

        # review: and table: blocks get the same preview, so the button is on
        # those editors too and renderScreen picks the right renderer.
        self.assertIn("PREVIEWABLE_BLOCK_TYPES", editor)
        self.assertIn("function renderScreen(data, options)", screen_preview)
        self.assertIn("daformreview", screen_preview)
        self.assertIn("da-review-action", screen_preview)
        self.assertIn("da-review-tabular", screen_preview)
        self.assertIn("table-responsive", screen_preview)
        self.assertIn("al_collapse_template", screen_preview)
        self.assertIn("al_send_bundle", screen_preview)

        # The in-place markdown preview it replaced is fully gone.
        self.assertNotIn("markdownPreviewMode", editor)
        self.assertNotIn("md-preview-wrapper", css)

    def test_question_field_controls_shrink_without_unhelpful_badges(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        self.assertIn("indicators.push('Conditional')", editor)
        self.assertIn("indicators.push('Validation')", editor)
        self.assertNotIn("indicators.push('choices')", editor)
        self.assertNotIn("indicators.push('display')", editor)
        self.assertIn(
            ".editor-field-type-dropdown {\n  width: 100%;\n  min-width: 0;", css
        )
        self.assertIn("text-overflow: ellipsis;", css)

    def test_the_assistant_is_absent_until_its_feature_flag_is_on(self):
        """The assistant drawer ships in the template but must not be reachable
        on an installation that has not opted in. The toggle is hidden and the
        panel markup is removed outright, so there is no partly-wired UI for a
        developer to find."""
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn('id="editor-assistant"', template)
        self.assertIn('class="editor-assistant d-none"', template)
        self.assertIn("js-assistant-toggle", template)
        self.assertIn('data-action="toggle-assistant"', template)
        self.assertIn('aria-controls="editor-assistant"', template)

        self.assertIn("BOOT.features && BOOT.features.agent_editor", editor)
        self.assertIn("if (!agentEditorEnabled()) {", editor)
        self.assertIn("assistantPanel.remove()", editor)

    def test_applying_an_agent_candidate_leaves_the_editor_dirty(self):
        """Apply is not Save. The candidate already contains the developer's
        earlier unsaved edits, so treating the result as saved would drop that
        work on the next reload; the editor must stay dirty against the
        revision that is actually on disk."""
        editor = (self.package_dir / "data/static/editor.js").read_text()

        start = editor.index("function applyAgentCandidate(")
        body = editor[start : editor.index("\n  function ", start + 1)]
        self.assertIn("state.revision = data.saved_revision", body)
        self.assertIn("dirtyState.markSourceDirty(", body)
        self.assertNotIn("setFileSaved", body)

    def test_order_builder_uses_quiet_step_list_structure(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        # Screens are the unlabeled default; exceptional step kinds use words
        # in a stable right-hand gutter instead of colored abbreviations.
        self.assertIn("if (step.kind === 'screen') return '';", editor)
        for label in ("'loop'", "'condition'", "'section'", "'progress'", "'code'"):
            self.assertIn(f"return {label};", editor)
        self.assertIn("editor-order-type", editor)
        self.assertNotIn("editor-order-badge", editor)

        # Branches and insertion positions remain available without filling
        # every row with permanent controls.
        self.assertIn("editor-order-branch-label", editor)
        self.assertIn("Insert here", editor)
        self.assertIn("group: 'interview-order-steps'", editor)
        self.assertIn("data-order-parent-step-id", editor)
        self.assertIn("fa-grip-vertical", editor)
        self.assertNotIn("&#10247;", editor)
        self.assertIn(
            "Inline editors and branches must be siblings of the fixed-height row.",
            editor,
        )
        self.assertIn("color: transparent;", css)
        self.assertIn("border-left: 2px solid", css)

    def test_order_builder_can_add_and_draw_an_elif_branch(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        # Adding one is a real menu action, offered from any link of a chain.
        self.assertIn('data-step-action="add-elif"', editor)
        self.assertIn("Add else if branch", editor)
        self.assertIn("function renderOrderChainBranchMenuItems(step)", editor)
        self.assertIn("if (!chainHasFinalElse(step))", editor)

        # The chain is drawn flat, so `elif` reads as a sibling of `if`
        # instead of nesting a level deeper with every link.
        self.assertIn("function renderOrderChainLink(step, depth)", editor)
        self.assertIn("editor-order-chain-keyword", editor)
        self.assertIn("linkIndex < chain.length", editor)
        self.assertIn(".editor-order-chain-link", css)

        # The mutations live in the module the node suite exercises, so the
        # builder cannot grow its own copy of the chain rules.
        for helper in (
            "getConditionChain",
            "getChainTail",
            "chainHasFinalElse",
            "isChainLink",
            "appendChainElif",
            "removeChainLink",
        ):
            self.assertIn(f"window.ALWeaverSerializers.{helper}(", editor)

        # The code preview has to show the elif the server will actually
        # write, not the nested if the steps are stored as.
        self.assertIn("var keyword = linkIndex === 0 ? 'if ' : 'elif ';", editor)
        self.assertIn("height: 32px;", css)

    def test_unsaved_changes_modal_cannot_trap_the_page(self):
        """The unsaved-changes modal is opened by every navigation gesture and
        has a static backdrop, no keyboard dismiss and no close button, so the
        three choice buttons are the only way out. Clicking through tabs
        quickly re-enters the prompt, and Bootstrap drops both show() and
        hide() while a modal is mid-transition. Without these guards a choice
        clicked during the fade nulls out every handler and then fails to
        close, leaving a modal that nothing on the page can dismiss."""
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        modal_start = template.index('id="unsaved-changes-modal"')
        modal_markup = template[modal_start : template.index("<!--", modal_start)]
        self.assertIn('data-bs-backdrop="static"', modal_markup)
        self.assertNotIn("data-bs-dismiss", modal_markup)

        self.assertIn("_unsavedPromptPending", editor)
        self.assertIn("hidden.bs.modal", editor)
        self.assertIn("hideModalWhenSettled", editor)

    def test_save_control_is_reachable(self):
        """The topbar Save button used to be icon-only and matched on
        `target.id`, but a click on a button's Font Awesome <i> makes the icon
        the event target, so the button did nothing. It also had no text label,
        no accessible name and no narrow-screen equivalent, which left
        navigating away and hitting the unsaved-changes prompt as the only way
        to notice unsaved work.

        There is now one Save button rather than a desktop copy and a
        hand-rolled mobile copy, so what has to hold is that the single button
        sits inside the Bootstrap collapse the navbar toggler opens — that is
        what keeps it reachable once the navbar collapses."""
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertEqual(template.count('data-action="save-file"'), 1)
        self.assertEqual(template.count("js-save-file-btn"), 1)
        self.assertIn('aria-label="Save your changes"', template)

        collapse_start = template.index('id="editor-navbar-collapse"')
        collapse_end = template.index("</nav>", collapse_start)
        collapsible_markup = template[collapse_start:collapse_end]
        self.assertIn('data-action="save-file"', collapsible_markup)
        self.assertIn(
            'data-bs-target="#editor-navbar-collapse"',
            template[: template.index('id="editor-navbar-collapse"')],
        )

        # Routed by data-action, not by an id that icon clicks never match.
        self.assertIn("uiAction === 'save-file'", editor)
        self.assertNotIn("target.id === 'btn-save-file'", editor)
        self.assertIn("saveCurrentFile", editor)

    def test_new_file_and_save_failures_are_reported_to_the_user(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("Unable to create file: ", editor)
        self.assertIn("Unable to save metadata safely: ", editor)
        self.assertIn("Unable to save block: ", editor)

    def test_assemblyline_settings_are_graphical_and_next_steps_reset_is_explicit(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn('data-action="open-assemblyline-settings"', template)
        self.assertIn("/api/assemblyline-settings", editor)
        self.assertIn("data-al-setting", editor)
        self.assertIn("Back up and replace with standard shell", editor)
        self.assertIn("confirm_replace: true", editor)
        self.assertIn('id="new-project-include-next-steps"', editor)
        self.assertIn('id="new-project-output-type"', editor)
        self.assertIn('id="assemblyline-settings-filter"', editor)
        self.assertIn("applyAssemblyLineSettingsFilter", editor)
        self.assertIn("editor-al-setting-key", editor)
        self.assertIn("field.pair ? 'col-12 col-md-6' : 'col-12'", editor)
        self.assertIn("input.value === '' ? '' : Number(input.value)", editor)

    def test_assemblyline_settings_explain_themselves_and_flag_server_overrides(self):
        """Guidance that lived on the question-driven Weaver's screens has to
        travel with the control, and a setting that overrides the whole server
        has to say so."""
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("editor-al-setting-help", editor)
        self.assertIn("_settingServerDefaultHtml", editor)
        self.assertIn("Overrides ", editor)
        self.assertIn("Comes from ", editor)
        self.assertIn("server_defaults", editor)
        # Help text is searchable, so an author can find a setting by what it does.
        self.assertIn("field.help || ''", editor)

    def test_assemblyline_settings_say_which_yaml_block_holds_each_section(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("function _settingsSectionDocumentsHtml(", editor)
        self.assertIn("section.documents", editor)
        self.assertIn(">Saved to<", editor)
        # A value Weaver found in someone else's code block is flagged.
        self.assertIn("function _settingSourceHtml(", editor)
        self.assertIn("Weaver does not add a second copy", editor)
        # And the page explains what it is for.
        self.assertIn("function _settingsExplainerHtml(", editor)
        self.assertIn('data-bs-toggle="popover"', editor)
        self.assertIn("function _initSettingsPopovers(", editor)

    def test_a_computed_setting_is_read_only_and_says_where_to_edit_it(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("function _settingComputedBlock(", editor)
        self.assertIn("function _settingComputedHtml(", editor)
        self.assertIn("readonly disabled aria-disabled=", editor)
        # It has to say where the real answer lives and how to change it.
        self.assertIn("open that block in the outline, or use YAML source", editor)
        self.assertIn("Saving here leaves it exactly as it is", editor)
        # A disabled control is still in the DOM, so the save has to skip it.
        self.assertIn("if (computed[key]) return;", editor)

    def test_escaping_covers_quotes_because_almost_every_call_is_an_attribute(self):
        """`esc()` output lands in title=, data-bs-content= and friends, so a
        quote in the value would close the attribute early."""
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("function esc(text) {", editor)
        self.assertIn(".replace(/\"/g, '&quot;')", editor)
        self.assertIn("""replace(/'/g, '&#39;')""", editor)

    def test_the_style_check_does_not_dress_itself_up_as_a_blocking_error(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("var isStyleMode = state.validationMode === 'style'", editor)
        self.assertIn("var hasProblems = !isStyleMode &&", editor)
        self.assertIn("'Style suggestions'", editor)
        self.assertIn("None of these stop the interview from running", editor)

    def test_new_project_collects_publishing_metadata_and_the_filename(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        for element_id in (
            "new-project-filename",
            "new-project-title",
            "new-project-short-title",
            "new-project-description",
            "new-project-jurisdiction",
            "new-project-landing-page-url",
            "new-project-list-topics",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn('id="%s"' % element_id, editor)
        for form_key in (
            "interview_filename",
            "interview_title",
            "interview_short_title",
            "interview_description",
            "jurisdiction",
            "landing_page_url",
            "list_topics",
        ):
            with self.subTest(form_key=form_key):
                self.assertIn("formData.append('%s'" % form_key, editor)
        # The old hard-coded name must not survive as a fallback.
        self.assertNotIn("'interview.yml'", editor)

    def test_new_project_defaults_to_a_test_and_exposes_a_tests_workspace(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn('id="new-project-create-test" checked', editor)
        self.assertIn("formData.append('create_test'", editor)
        self.assertIn("create_test: createTest", editor)
        self.assertIn('data-action="open-tests-overview"', template)
        self.assertIn(">Tests</button>", template)
        self.assertIn('id="kiln-test-mode-it-runs"', template)
        self.assertIn('id="kiln-test-mode-json"', template)
        self.assertIn('id="kiln-test-json"', template)
        self.assertIn('id="kiln-test-accessibility" checked', template)
        self.assertIn('id="kiln-test-entrypoint"', template)
        self.assertIn('id="kiln-test-yaml-files"', template)
        self.assertIn("I check all pages for accessibility issues", template)
        self.assertIn("/api/kiln-tests?project=", editor)
        self.assertIn("apiPost('/api/kiln-test/draft'", editor)
        self.assertIn("apiPost('/api/kiln-test/apply'", editor)
        self.assertIn("yaml_filenames:", editor)
        self.assertIn("function renderKilnYamlFileControls(", editor)
        self.assertIn("function renderTestsOverview()", editor)
        self.assertIn("function openTestsOverview()", editor)
        self.assertIn('id="btn-new-kiln-test-overview"', editor)
        self.assertIn('data-kiln-test-sync="', editor)
        self.assertIn('id="btn-tests-overview-inline"', editor)
        self.assertIn("var KILN_CHANGE_BADGE_LIMIT = 10;", editor)
        self.assertIn("values.length > KILN_CHANGE_BADGE_LIMIT", editor)
        self.assertIn("values.length + ' new findings'", editor)
        self.assertIn("openKilnTestSyncModal({ mode: 'it_runs' });", editor)
        self.assertIn(
            "Save as Kiln test",
            (self.package_dir / "data/static/editor_runtime_inspector.js").read_text(),
        )
        self.assertNotIn("Deleted screens", editor)
        self.assertNotIn("Deleted functionality", editor)

    def test_templates_reaches_its_files_and_the_document_setup_separately(self):
        """One template and every document are different things to look at."""
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        # A menu under the Templates tab, as well as a way back and forth.
        self.assertIn('data-templates-mode="files"', template)
        self.assertIn('data-templates-mode="documents"', template)
        self.assertIn('id="templates-menu"', template)
        self.assertIn("function setTemplatesMode(", editor)
        self.assertIn("renderDocumentSetupView", editor)
        # The project-wide pane is its own view, not a card beside a file.
        self.assertIn(
            "if (view === 'templates' && state.templatesMode === 'documents') {",
            editor,
        )
        self.assertNotIn("renderDocumentsCard(fileMeta)", editor)

    def test_interview_menu_replaces_more_and_exposes_order_tools(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        self.assertNotIn("editor-brand-caret", template)
        self.assertNotIn('id="topbar-more-menu"', template)
        self.assertIn('id="interview-menu"', template)
        self.assertIn('data-action="open-interview-order"', template)
        self.assertIn('data-action="open-interview-flow-report"', template)
        self.assertIn("uiAction === 'open-interview-order'", editor)
        self.assertIn("uiAction === 'open-interview-flow-report'", editor)
        self.assertIn("color: rgba(255, 255, 255, 0.9);", css)

    def test_a_template_is_imported_not_analyzed(self):
        """The author's verb is the deed, not the means."""
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("Import into this interview", editor)
        self.assertIn("Reload fields", editor)
        self.assertIn("/api/template/import", editor)
        self.assertNotIn("Analyze this template", editor)
        self.assertNotIn("/api/template/analyze", editor)
        # Once it is imported the card says so, instead of offering a second
        # copy of the same document.
        self.assertIn("already imported", editor)
        self.assertIn("templateIsAttached", editor)

    def test_an_unused_template_says_so_in_the_file_list(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()
        styles = (self.package_dir / "data/static/editor.css").read_text()

        self.assertIn("Not imported", editor)
        self.assertIn("editor-outline-status", editor)
        self.assertIn(".editor-outline-status", styles)
        self.assertIn("'not_imported'", editor)

    def test_document_setup_edits_are_dirty_state_like_any_other(self):
        """The pane writes the interview, so it joins the same save contract."""
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("state.documentsDirty", editor)
        self.assertIn("function markDocumentsDirty(", editor)
        self.assertIn("function discardDocumentChanges(", editor)
        # Every place the editor asks "is there unsaved work" has to agree.
        for guard in (
            "function hasUnsavedChanges() {",
            "function updateTopbarSaveState() {",
        ):
            body = editor.split(guard, 1)[1].split("\n  }", 1)[0]
            self.assertIn("state.documentsDirty", body, guard)
        self.assertIn("if (state.documentsDirty) return saveDocumentChanges();", editor)
        self.assertIn("documentsDiscarded", editor)

    def test_document_setup_has_a_hierarchy_instead_of_a_wall_of_text_boxes(self):
        """Two nested questions, each shown as one, not four peer text fields."""
        editor = (self.package_dir / "data/static/editor.js").read_text()
        styles = (self.package_dir / "data/static/editor.css").read_text()

        # Each bundle owns its documents, visibly.
        self.assertIn("editor-bundle-card-header", editor)
        self.assertIn(".editor-bundle-card-header", styles)
        self.assertIn("Documents this interview assembles", editor)
        self.assertIn("Include each document when", editor)
        # A document reads as its variable over the file it fills, not as a
        # label competing with an input.
        self.assertIn("editor-doc-row-name", editor)
        self.assertIn("editor-doc-row-file", editor)
        # And the rule is a choice, with Bootstrap's own radio group.
        self.assertIn('class="btn-check"', editor)
        self.assertIn("btn-group btn-group-sm", editor)
        for label in ("Always", "Never", "Custom"):
            self.assertIn("'" + label + "'", editor)

    def test_an_enabled_rule_is_a_choice_before_it_is_an_expression(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("function enabledMode(", editor)
        self.assertIn("if (text === 'True') return 'always';", editor)
        self.assertIn("if (text === 'False') return 'never';", editor)
        # The expression box only exists for the case that needs one.
        self.assertIn("data-enabled-custom", editor)
        self.assertIn("custom.hidden = !wantsExpression;", editor)
        # Custom with nothing written would remove the rule, so it cannot save.
        self.assertIn("function documentsRuleProblem(", editor)
        self.assertIn(
            "if (documentsRuleProblem()) return Promise.resolve(false);", editor
        )
        # A declaration with no rule at all says what that means.
        self.assertIn("editor-enabled-warning", editor)
        self.assertIn("assembly will stop and ask", editor)
        # Guidance is visible underneath rather than disappearing in a placeholder.
        self.assertNotIn('placeholder="user_is_low_income"', editor)
        self.assertIn("Example: <code>user_is_low_income</code>", editor)

    def test_nothing_selected_greys_the_button_instead_of_erroring(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("function updateApplyImportButton(", editor)
        self.assertIn("button.disabled = chosen === 0;", editor)
        self.assertNotIn("Nothing is selected.", editor)

    def test_a_comment_block_can_be_inserted_like_any_other(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        serializers = (
            self.package_dir / "data/static/editor_serializers.js"
        ).read_text()

        self.assertIn('data-insert="comment"', template)
        self.assertIn("if (kind === 'comment')", serializers)

    def test_the_outline_previews_a_block_on_hover(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("function blockQuickView(", editor)
        self.assertIn("esc(blockQuickView(block))", editor)
        self.assertIn("if (type === 'comment') return 'Comment'", editor)

    def test_create_project_groups_its_settings_into_accordion_sections(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("function _newProjectSection(", editor)
        self.assertIn('class="accordion editor-new-project-accordion"', editor)
        for section in ("files", "basics", "advanced", "metadata", "context"):
            with self.subTest(section=section):
                self.assertIn("_newProjectSection('%s'" % section, editor)
        # Independent sections, not a wizard: closing what you just filled in to
        # open the next one would be hostile.
        self.assertNotIn('data-bs-parent="#new-project-accordion"', editor)
        # The advanced group is the collapsed one.
        self.assertIn(
            "_newProjectSection('advanced', 'Advanced settings', false", editor
        )
        self.assertIn("_newProjectSection('basics', 'Project settings', true", editor)

    def test_uploading_a_document_suggests_the_project_name_and_title(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("function _titleFromFilename(", editor)
        self.assertIn("function _projectNameFromTitle(", editor)
        self.assertIn("function _suggestNamesFromUpload(", editor)
        self.assertIn("suggest('new-project-name', projectName)", editor)
        self.assertIn("suggest('new-project-title', title)", editor)
        self.assertIn("suggest('new-project-short-title', shortTitle)", editor)
        # A suggestion never overwrites something the author typed.
        self.assertIn(
            "if (current && current !== _suggestedValues[elementId]) return;", editor
        )

    def test_list_topics_have_a_picker_instead_of_codes_typed_from_memory(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn('id="list-topics-modal"', template)
        self.assertIn('id="list-topics-tree"', template)
        self.assertIn('id="list-topics-filter"', template)
        self.assertIn('id="list-topics-apply"', template)
        self.assertIn("/api/list-topics", editor)
        self.assertIn("function openListTopicsPicker(", editor)
        self.assertIn("function applyListTopicsSelection(", editor)
        # Built the way ALToolbox's al_tree_select is: real disclosure groups
        # around real checkboxes, so keyboard and screen readers work unaided.
        self.assertIn('<details class="editor-topic-group"', editor)
        self.assertIn('type="checkbox"', editor)
        # Both places that hold topic codes can open it.
        self.assertIn('data-open-list-topics="new-project-list-topics"', editor)
        self.assertIn("field.key === 'LIST_topics'", editor)

    def test_new_project_offers_to_copy_the_assemblyline_person_questions(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn('id="new-project-copy-baseline-questions"', editor)
        self.assertIn(
            "formData.append('copy_baseline_questions', copyBaselineQuestions ? 'true' : 'false')",
            editor,
        )
        # The point of the option is that it is on unless somebody turns it off.
        self.assertIn(
            "copyBaselineQuestionsInput ? copyBaselineQuestionsInput.checked : true",
            editor,
        )

    def test_navbar_matches_docassemble_and_carries_the_account_menu(self):
        """The editor is a full-page app that sits where a native docassemble
        page would, so its bar has to be a real Bootstrap navbar at
        docassemble's own height and has to offer the same account menu.
        A hand-rolled bar drifts from both."""
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        self.assertIn('class="navbar navbar-expand-lg editor-navbar"', template)
        self.assertIn('data-bs-theme="dark"', template)
        self.assertIn('class="navbar-toggler"', template)
        self.assertNotIn("editor-topbar-inner", template)
        self.assertNotIn("topbar-mobile-menu", template)

        # docassemble pads its body by 66px for a navbar that renders at 56px.
        self.assertIn("--editor-navbar-height: 56px;", css)

        self.assertIn('id="editor-account-nav"', template)
        self.assertIn("function renderAccountMenu()", editor)
        self.assertIn("authState.menuItems", editor)

    def test_outline_filter_counts_reflect_kind_and_typing_filters(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertIn("function outlineFilterCounts(", editor)
        self.assertIn("function updateOutlineFilterSummary(", editor)
        self.assertIn("kindVisible: kindMatches", editor)
        self.assertIn("counts.hasSearch && counts.kindVisible < counts.total", editor)
        self.assertIn(" (' + counts.total + ' total)'", editor)

    def test_docassemble_codemirror_contract_on_supported_tags(self):
        checkout = Path(
            os.environ.get(
                "DOCASSEMBLE_SOURCE_CHECKOUT",
                str(self.package_dir.parents[2] / "docassemble"),
            )
        )
        if not (checkout / ".git").is_dir():
            self.skipTest("Set DOCASSEMBLE_SOURCE_CHECKOUT to verify upstream assets")

        asset = "docassemble_webapp/docassemble/webapp/static/app/cm6.js"
        for ref in ("v1.9.0", "v1.9.13", "v1.10.0", "v1.10.7"):
            with self.subTest(ref=ref):
                result = subprocess.run(
                    ["git", "-C", str(checkout), "show", f"{ref}:{asset}"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, f"{ref}: {result.stderr}")
                self.assertIn("function daNewEditor(", result.stdout)
                self.assertIn("window.daNewEditor = daNewEditor", result.stdout)
                self.assertIn("this.ev = ev", result.stdout)


if __name__ == "__main__":
    unittest.main()
