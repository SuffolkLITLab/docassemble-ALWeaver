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
        ):
            self.assertLess(template.index(module), template.index("editor.js"))
        self.assertNotIn("monaco", editor.lower())
        self.assertNotIn("cdn.jsdelivr.net", editor)

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
        no accessible name and no mobile equivalent, which left navigating away
        and hitting the unsaved-changes prompt as the only way to notice
        unsaved work."""
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        # Present in both the desktop bar and the mobile menu.
        self.assertEqual(template.count('data-action="save-file"'), 2)
        self.assertEqual(template.count("js-save-file-btn"), 2)
        self.assertIn('aria-label="Save your changes"', template)

        # Routed by data-action, not by an id that icon clicks never match.
        self.assertIn("uiAction === 'save-file'", editor)
        self.assertNotIn("target.id === 'btn-save-file'", editor)
        self.assertIn("saveCurrentFile", editor)

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
