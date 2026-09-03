# do not pre-load

from collections import Counter
from html.parser import HTMLParser
import os
from pathlib import Path
import subprocess
import unittest

NODE_TESTS = (
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
