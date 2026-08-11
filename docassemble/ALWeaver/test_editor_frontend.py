# do not pre load

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
        self.assertIn("_alFieldMethodPreviewFields", editor)
        self.assertIn("_renderALFieldMethodPreview", editor)
        self.assertIn("_renderQuestionFieldHelp(questionHelpTypes)", editor)
        self.assertIn("AssemblyLine.al_general.ALIndividual.name_fields", editor)
        self.assertIn("AssemblyLine.al_general.ALIndividual.address_fields", editor)
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
            self.assertIn(expected_label, editor)
        self.assertIn(".editor-al-field-preview", css)
        self.assertIn(".editor-question-context-help", css)

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
