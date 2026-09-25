# do not pre-load

from collections import Counter
from html.parser import HTMLParser
import os
from pathlib import Path
import subprocess
import unittest

NODE_TESTS = (
    "test_editor_expressions.js",
    "test_editor_attachments.js",
    "test_editor_order_lookup.js",
    "test_editor_dirty_state.js",
    "test_editor_html.js",
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

    def test_github_partial_publish_shows_warning_and_setup_guidance(self):
        source = (Path(__file__).parent / "data/static/editor.js").read_text()
        self.assertIn("warnings.length ? 'warning' : 'success'", source)
        self.assertIn("guidance.textContent = 'ALKiln workflow setup guide'", source)
        self.assertIn(
            "https://assemblyline.suffolklitlab.org/docs/components/ALKiln/setup/",
            source,
        )

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
