# do not pre load

from collections import Counter
from html.parser import HTMLParser
import os
from pathlib import Path
import subprocess
import unittest

NODE_TESTS = (
    "test_editor_api_client.js",
    "test_editor_codemirror_adapter.js",
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
            "editor_command_manager.js",
            "editor_dirty_state.js",
            "editor_serializers.js",
            "editor_source_adapter.js",
            "editor_state_store.js",
            "editor_validation_source.js",
        ):
            self.assertLess(template.index(module), template.index("editor.js"))
        self.assertNotIn("monaco", editor.lower())
        self.assertNotIn("cdn.jsdelivr.net", editor)

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
