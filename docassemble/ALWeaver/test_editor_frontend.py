# do not pre-load

from collections import Counter
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import subprocess
import unittest

NODE_TESTS = (
    "test_editor_controls.js",
    "test_editor_project_navigation.js",
    "test_editor_github_publish.js",
    "test_editor_expressions.js",
    "test_editor_attachments.js",
    "test_editor_order_lookup.js",
    "test_editor_order_loops.js",
    "test_editor_dirty_state.js",
    "test_editor_question_label_guard.js",
    "test_editor_html.js",
    "test_editor_api_client.js",
    "test_editor_serializers.js",
    "test_editor_screen_types.js",
    "test_editor_screen_validation.js",
    "test_editor_validation_source.js",
    "test_editor_agent_chat.js",
    "test_editor_screen_preview.js",
    "test_editor_interview_report.js",
    "test_editor_include_report.js",
    "test_editor_runtime_inspector.js",
    "test_editor_router.js",
    "test_editor_route_navigation.js",
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
    def test_help_template_controls_have_accessible_labels(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        for control in (
            "template-insert-existing",
            "template-insert-name",
            "template-insert-subject",
            "template-insert-content",
        ):
            self.assertIn(f'for="{control}"', template)
        self.assertIn('id="template-insert-error" role="alert"', template)
        self.assertIn('data-insert="template"', template)

    def test_github_branch_picker_has_new_branch_field_without_helper_text(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        self.assertRegex(template, r'<select[^>]+id="github-branch-name"')
        self.assertIn('id="github-new-branch-name"', template)
        self.assertIn('aria-label="New branch name"', template)
        self.assertNotIn("Existing branches are updated and missing branches", template)

    def test_comfortable_editor_controls_remain_accessible(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()
        self.assertIn(
            'data-action="toggle-rail" aria-controls="left-rail" aria-expanded="true"',
            template,
        )
        self.assertIn(
            "railToggle.setAttribute('aria-expanded', String(!collapsed))", editor
        )
        self.assertIn('id="q-subquestion" rows="2"', editor)
        self.assertIn('class="editor-form-label-row"', editor)
        self.assertIn("data-md-more-menu>", editor)
        self.assertIn(
            "host.querySelector('[data-md-more-menu]').prepend(menuItem)", editor
        )
        self.assertIn('class="editor-content-label" for="q-title"', editor)
        self.assertIn('<dl class="editor-question-button-summary">', editor)
        self.assertNotRegex(css, r"font-size:\s*[\d.]+px")
        self.assertNotRegex(css, r"font-size:\s*0\.[0-7]\d*rem")
        renderer = editor.split("  function renderQuestionBlock(block) {", 1)[1]
        renderer = renderer.split("\n  function ", 1)[0]
        self.assertLess(
            renderer.index('id="adv-id"'), renderer.index('id="question-screen-panel"')
        )
        # Order rows grow with the browser font instead of clipping at 32px.
        order_step = css.split("\n.editor-order-step {", 1)[1].split("}", 1)[0]
        self.assertIn("min-height: 2rem;", order_step)
        self.assertNotIn("height: 32px;", order_step)

    def test_assistant_has_a_read_only_question_control(self):
        chat = (self.package_dir / "data/static/editor_agent_chat.js").read_text()
        self.assertIn("Ask only (no edits)", chat)
        self.assertIn("read_only: askingOnly", chat)

    def test_new_code_block_opens_in_expression_editor(self):
        from .editor_expressions import parse_expression
        import yaml

        completed = subprocess.run(
            [
                "node",
                "-e",
                "process.stdout.write(require('./data/static/editor_serializers.js').makeNewBlockYaml('code', 123));",
            ],
            cwd=Path(__file__).parent,
            text=True,
            capture_output=True,
            check=True,
        )
        code = yaml.safe_load(completed.stdout)["code"]
        self.assertTrue(parse_expression(code, "code")["supported"])
        self.assertEqual(parse_expression(code, "code")["rows"], [])

    def test_code_and_question_blocks_share_mandatory_switch(self):
        source = (Path(__file__).parent / "data/static/editor.js").read_text()
        for name in ("renderQuestionBlock", "renderCodeBlock"):
            renderer = source.split(f"  function {name}(block) {{", 1)[1]
            renderer = renderer.split("\n  function ", 1)[0]
            self.assertIn("renderMandatorySwitch(data)", renderer)
        self.assertEqual(source.count('id="adv-mandatory-switch"'), 1)

    def test_code_block_mandatory_switch_survives_canvas_redraw(self):
        # Toggles like "Advanced options" stash editor state, then redraw the
        # canvas from block.data; code blocks must stash the switch too.
        source = (Path(__file__).parent / "data/static/editor.js").read_text()
        stash = source.split("  function stashCurrentEditorState() {", 1)[1]
        stash = stash.split("\n  function ", 1)[0]
        self.assertRegex(
            stash,
            r"block\.type === 'code'\) \{\s*syncMandatoryToData\(block\);",
        )
        sync_meta = source.split("  function syncQuestionMetaToData(blk) {", 1)[1]
        sync_meta = sync_meta.split("\n  function ", 1)[0]
        self.assertIn("syncMandatoryToData(blk);", sync_meta)

    def test_question_id_and_event_inputs_have_visible_labels(self):
        source = (Path(__file__).parent / "data/static/editor.js").read_text()
        for input_id, label in (("adv-id", "ID"), ("adv-event", "Event")):
            self.assertIn(
                f'<label class="editor-block-id-label" for="{input_id}">{label}</label>',
                source,
            )

    def test_question_text_is_required_in_graphical_editor(self):
        source = (Path(__file__).parent / "data/static/editor.js").read_text()
        template = (Path(__file__).parent / "data/templates/editor.html").read_text()
        self.assertIn('id="q-title" rows="1"', source)
        self.assertIn('id="q-allow-blank"', source)
        self.assertIn('id="blank-question-prompt"', template)
        self.assertIn("blankQuestionNeedsDecision() ||", source)
        self.assertIn("Add a question label before saving.", source)

    def test_markdown_toolbar_has_labels_when_icons_do_not_load(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()
        toolbar = editor.split(
            "  function renderMarkdownToolbar(targetId, compact) {", 1
        )[1].split("\n  function _buildDocassembleImageToken", 1)[0]
        for label, fallback in (
            ("Bold", "Bold"),
            ("Italic", "Italic"),
            ("Link", "Link"),
            ("Insert Mako variable", "Variable"),
            ("Heading", "Heading"),
            ("List", "List"),
            ("More formatting", "More"),
        ):
            with self.subTest(label=label):
                self.assertIn(f'aria-label="{label}"', toolbar)
                self.assertIn(
                    f'<span class="editor-md-fallback">{fallback}</span></button>',
                    toolbar,
                )
        self.assertIn(".editor-md-btn svg + .editor-md-fallback", css)

    def test_check_and_uncheck_others_have_logic_tab_boolean_controls(self):
        source = (Path(__file__).parent / "data/static/editor.js").read_text()
        logic = source.split("    function renderLogicTab() {", 1)[1]
        logic = logic.split("    function renderHelpTab() {", 1)[0]
        self.assertIn("'yesno',", logic)
        self.assertIn("'yesnowide',", logic)
        self.assertIn("'noyes',", logic)
        self.assertIn("'noyeswide'", logic)
        self.assertIn("'object_radio'", logic)
        self.assertIn("'object_checkboxes'", logic)
        self.assertIn("modifierOrNotice(", logic)
        self.assertIn("sourceOnlyModifierNotice(key)", logic)
        self.assertIn("the source value <code>", logic)
        self.assertIn("Edit it in Full YAML.", logic)
        self.assertIn("(default)", logic)
        self.assertIn(">Yes</option>", logic)
        self.assertIn(">No</option>", logic)

    def test_field_settings_tabs_have_accessible_roles_and_contrast(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()
        panel = editor.split("  function _renderFieldModsPanel(", 1)[1].split(
            "  // --- Advanced panel", 1
        )[0]
        for attribute in (
            'role="tablist" aria-label="Field settings"',
            'role="tab" id="field-settings-tab-',
            'aria-controls="field-settings-pane-',
            'aria-selected="',
            'role="tabpanel" id="field-settings-pane-',
            'aria-labelledby="field-settings-tab-',
        ):
            self.assertIn(attribute, panel)
        self.assertIn(".editor-field-settings-tabs .nav-link {", css)
        self.assertIn("color: var(--editor-primary);", css)
        self.assertIn(".editor-field-settings-tabpane[hidden]", css)
        self.assertIn(".editor-field-mods-panel .btn-outline-secondary {", css)
        self.assertIn("--bs-btn-color: #5c636a;", css)

    def test_compact_section_button_has_contrast_when_open(self):
        css = (self.package_dir / "data/static/editor.css").read_text()
        section_button = css.split("#editor-section-menu.show,", 1)[1].split("}", 1)[0]
        self.assertIn("color: var(--editor-primary);", section_button)
        self.assertIn("background-color: #f8f9fa;", section_button)

    def test_github_partial_publish_shows_warning_and_setup_guidance(self):
        source = (Path(__file__).parent / "data/static/editor.js").read_text()
        self.assertIn("warnings.length ? 'warning' : 'success'", source)
        self.assertIn("guidance.textContent = 'ALKiln workflow setup guide'", source)
        self.assertIn(
            "https://assemblyline.suffolklitlab.org/docs/components/ALKiln/setup/",
            source,
        )

    def test_github_commit_message_supports_multiple_lines(self):
        root = Path(__file__).parent / "data"
        template = (root / "templates/editor.html").read_text()
        css = (root / "static/editor.css").read_text()
        editor = (root / "static/editor.js").read_text()
        control = re.search(
            r'<textarea\b(?=[^>]*\bid="github-commit-message")([^>]*)>([^<]*)</textarea>',
            template,
        )
        self.assertIsNotNone(control)
        attributes, default = control.groups()
        self.assertIn('id="github-commit-message"', attributes)
        self.assertIn('name="commit_message"', attributes)
        self.assertIn('rows="2"', attributes)
        self.assertIn('maxlength="500"', attributes)
        self.assertIn("required", attributes)
        self.assertEqual(default, "Update from Weaver")
        self.assertIn(
            ".github-commit-message-wrap textarea {\n  resize: vertical;", css
        )
        self.assertIn(".github-commit-message-wrap::after", css)
        self.assertIn("commit_message: messageInput ? messageInput.value : ''", editor)

    def test_upload_generation_warnings_are_shown_to_the_author(self):
        source = (Path(__file__).parent / "data/static/editor.js").read_text()
        self.assertIn("_newProjectGenerationWarnings(jobData)", source)
        self.assertIn("_showWarningBanner(", source)
        self.assertIn("generationWarnings.map(esc).join(' ')", source)

    def test_github_modal_manages_workflows_and_pyproject(self):
        root = Path(__file__).parent / "data"
        collector = _TemplateCollector()
        collector.feed((root / "templates/editor.html").read_text())
        for element_id in (
            "github-tab-workflows",
            "github-workflows-list",
            "github-tab-dependencies",
            "github-dependency-input",
            "github-pyproject-source",
            "github-pyproject-save",
        ):
            self.assertIn(element_id, collector.ids)
        editor = (root / "static/editor.js").read_text()
        self.assertIn("'/api/github/repository-config", editor)
        # Turning on a workflow that opens its editor asks before discarding
        # unsaved edits in another one.
        self.assertIn(
            "Discard your changes to the open workflow to edit this one?", editor
        )
        # An open editor's edits are saved before the publish reads settings.
        self.assertLess(
            editor.index("saveDirtyGithubEditors()\n        .then"),
            editor.index("return apiPost('/api/github/publish'"),
        )

    def test_attachment_controls_support_questions_and_standalone_blocks(self):
        editor = (Path(__file__).parent / "data/static/editor.js").read_text()
        self.assertIn("data-edit-attachment-mappings", editor)
        self.assertIn("function saveAttachmentMappings()", editor)
        self.assertIn("data-remove-from-bundle", editor)
        self.assertNotIn("This block has an attachment. Edit in YAML mode", editor)

    def test_separate_main_order_is_an_unchecked_advanced_option(self):
        editor = (Path(__file__).parent / "data/static/editor.js").read_text()
        self.assertIn('id="new-project-separate-main-order">', editor)
        self.assertNotIn('id="new-project-separate-main-order" checked', editor)
        self.assertIn("'separate_main_order',", editor)

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
            "editor_expressions.js",
            "editor_html.js",
            "editor_api_client.js",
            "editor_dirty_state.js",
            "editor_serializers.js",
            "editor_validation_source.js",
            "editor_agent_chat.js",
        ):
            self.assertLess(template.index(module), template.index("editor.js"))
        self.assertNotIn("monaco", editor.lower())
        self.assertNotIn("cdn.jsdelivr.net", editor)

    def test_save_and_run_remain_available_when_navigation_collapses(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()
        css = (self.package_dir / "data/static/editor.css").read_text()

        self.assertIn("navbar navbar-expand-xl editor-navbar", template)
        section_menu = template.split('id="editor-section-menu"', 1)[1]
        section_menu = section_menu.split('class="editor-compact-actions"', 1)[0]
        for view in ("interview", "templates", "modules", "static", "data"):
            self.assertIn(f'data-view="{view}"', section_menu)
        for name in ("interview", "templates"):
            compact_submenu = template.split(f'id="editor-{name}-submenu"', 1)[1].split(
                "</ul>", 1
            )[0]
            full_submenu = template.split(f'aria-labelledby="{name}-menu">', 1)[
                1
            ].split("</ul>", 1)[0]
            attributes = (
                ("data-action",) if name == "interview" else ("data-templates-mode",)
            )
            for attribute in attributes:
                self.assertEqual(
                    set(re.findall(rf'{attribute}="([^"]+)"', compact_submenu)),
                    set(re.findall(rf'{attribute}="([^"]+)"', full_submenu)),
                )
        self.assertIn('data-bs-auto-close="outside"', section_menu)
        self.assertEqual(template.count("js-github-pull-menu-item"), 2)
        compact_actions = template.split('class="editor-compact-actions"', 1)[1]
        compact_actions = compact_actions.split("</div>", 1)[0]
        for action in (
            "preview-interview",
            "open-runtime-inspector",
            "save-file",
            "toggle-assistant",
        ):
            self.assertIn(f'data-action="{action}"', compact_actions)
        self.assertLess(
            template.index('id="canvas-content"'),
            template.index('id="editor-canvas-save"'),
        )
        self.assertNotIn("editor-canvas-actions", template)
        self.assertEqual(template.count("js-save-file-btn"), 3)
        self.assertEqual(template.count("js-assistant-toggle"), 2)
        self.assertIn("querySelectorAll('.js-save-file-btn')", editor)
        self.assertIn("state.canvasMode !== 'question'", editor)
        self.assertIn("target.closest('.editor-top-tab, .editor-view-switch')", editor)
        self.assertIn("function setSectionSubmenu(openId)", editor)
        self.assertIn("@media (min-width: 576px)", css)

    def test_toolbar_uses_run_and_a_noninteractive_error_count(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        self.assertNotIn("Open interview", template)
        self.assertNotIn('data-action="check-errors"', template)
        self.assertIn('<span id="editor-error-count"', template)
        self.assertIn('aria-label="Run"', template)
        status = template.split('id="editor-error-status"', 1)[1].split("</span>")[0]
        self.assertIn('class="visually-hidden"', status)
        self.assertIn('role="status"', status)
        self.assertIn(">0 errors", status)
        self.assertGreater(
            template.index('id="editor-error-status"'), template.index("</nav>")
        )

    def test_compact_navigation_has_only_one_visible_home(self):
        css = (self.package_dir / "data/static/editor.css").read_text()
        wide_rules = css.split("@media (min-width: 576px)", 1)[1]
        self.assertIn(".editor-section-switcher {", wide_rules)
        self.assertIn("#editor-navbar-collapse,", wide_rules)
        self.assertIn(".editor-navbar .navbar-toggler {", wide_rules)
        self.assertIn("display: none !important;", wide_rules)
        desktop_rules = css.split("@container (min-width: 75rem)", 1)[1]
        self.assertIn("#editor-navbar-collapse {", desktop_rules)
        self.assertIn("display: flex !important;", desktop_rules)
        self.assertIn("#view-tabs {", desktop_rules)
        self.assertIn("flex-wrap: nowrap;", desktop_rules)
        template = (self.package_dir / "data/templates/editor.html").read_text()
        sidebar = template.split('id="left-rail"', 1)[1].split("</aside>", 1)[0]
        self.assertNotIn("Project outline", template)
        self.assertNotIn('id="project-select"', sidebar)
        self.assertIn('id="btn-project-search"', sidebar)
        self.assertIn('aria-label="Files and blocks"', template)
        self.assertIn('id="editor-project-menu"', template)
        self.assertGreater(
            template.index('id="editor-account-nav"'),
            template.index('id="editor-navbar-collapse"'),
        )

    def test_screen_preview_sandbox_does_not_share_editor_origin(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        preview_frame = template.split('id="screen-preview-frame"', 1)[1].split(">", 1)[
            0
        ]
        self.assertIn('sandbox="allow-scripts"', preview_frame)
        self.assertNotIn("allow-same-origin", preview_frame)

    def test_transient_tools_are_closed_by_editor_navigation(self):
        """A late debugger poll and an open assistant must not undo navigation."""
        editor = (self.package_dir / "data/static/editor.js").read_text()
        runtime = (
            self.package_dir / "data/static/editor_runtime_inspector.js"
        ).read_text()

        self.assertIn("hide: hide", runtime)
        # Hiding has to drop the canvas the panel was drawing into, or a late
        # observation paints the debugger back over whatever replaced it.
        self.assertIn("function hide() {", runtime)
        hide_body = runtime.split("function hide() {", 1)[1].split("}", 1)[0]
        self.assertIn("container = null;", hide_body)
        self.assertIn("runtimeInspector.hide();", editor)
        self.assertIn("!target.closest('#editor-assistant')", editor)
        self.assertIn("!target.closest('.editor-runtime-inspector')", editor)
        self.assertIn(
            "if (dismissal.assistant && state.assistantOpen) setAssistantOpen(false);",
            editor,
        )

    def test_dialogs_and_cancelled_navigation_leave_the_tools_open(self):
        """A modal is raised over the editor, not part of it -- and the
        debugger opens some of them itself. Clicking in one, or backing out of
        the unsaved-changes prompt, has to leave the tool where it was."""
        editor = (self.package_dir / "data/static/editor.js").read_text()

        dismissal_check = editor.split(
            "function transientToolsDismissedByClick(e) {", 1
        )[1].split("\n  }\n", 1)[0]
        self.assertIn(
            "if (target.closest('.modal, .modal-backdrop')) return dismissal;",
            dismissal_check,
        )
        # The dismissal waits on the queued navigation instead of running
        # while the prompt is still open, because the user may cancel it.
        self.assertIn(
            "if (_pendingNavigationAction) _pendingNavigationDismissal", editor
        )
        self.assertIn(
            "if (pendingDismissal) dismissTransientTools(pendingDismissal);", editor
        )
        # Raising a dialog has not left anything either: the editor behind it
        # is unchanged and the user can still back out of it. The check waits
        # a microtask because publishing to GitHub opens its modal behind a
        # save prompt that settles immediately when there is nothing to save.
        self.assertIn("Promise.resolve().then(function () {", editor)
        self.assertIn("if (!dialogIsOpen()) dismissTransientTools(dismissal);", editor)
        self.assertIn("document.querySelector('.modal.show')", editor)
        self.assertIn("classList.contains('modal-open')", editor)

    def test_a_session_started_after_the_debugger_closed_is_released(self):
        """Leaving while the session POST is in flight must not strand a test
        session on the server with no debugger to own it."""
        runtime = (
            self.package_dir / "data/static/editor_runtime_inspector.js"
        ).read_text()

        start_body = runtime.split("function startSession() {", 1)[1].split(
            "\n    }\n", 1
        )[0]
        self.assertEqual(start_body.count("if (hidden)"), 2)
        self.assertIn("if (hidden) return releaseSession();", start_body)

    def test_the_magic_icon_marks_only_features_that_use_ai(self):
        """A wand promises generative AI. Deterministic screens and actions
        have to be drawn with something that does not."""
        ai_markers = (
            "toggle-assistant",
            "run-style-check-ai",
            "ai-screen",
            "ai-generate-screen",
            "ai-generate-fields",
        )
        for relative_path in (
            "data/templates/editor.html",
            "data/static/editor.js",
            "data/questions/review_screen.yml",
        ):
            lines = (self.package_dir / relative_path).read_text().splitlines()
            for index, line in enumerate(lines):
                if "fa-magic" not in line and "wand-magic" not in line:
                    continue
                # An icon often sits on its own line inside the control that
                # names the feature, so read a little of the way around it.
                context = "\n".join(lines[max(0, index - 3) : index + 2])
                with self.subTest(path=relative_path, line=index + 1):
                    self.assertTrue(
                        any(marker in context for marker in ai_markers),
                        f"{relative_path}:{index + 1} uses the magic icon "
                        "without using AI: " + line.strip(),
                    )

    def test_scrollable_source_editors_have_focusable_content(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()
        create = editor.split("  function createSourceEditor(", 1)[1]
        create = create.split("\n  function ", 1)[0]
        # axe's scrollable-region-focusable ignores bare contenteditable.
        self.assertIn("view.contentDOM.setAttribute('tabindex', '0')", create)

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
