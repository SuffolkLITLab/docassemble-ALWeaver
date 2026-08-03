import os
from pathlib import Path
import subprocess
import unittest


class TestEditorCodeMirrorAdapter(unittest.TestCase):
    def setUp(self):
        self.package_dir = Path(__file__).resolve().parent
        self.repo_dir = self.package_dir.parents[1]

    def test_adapter_javascript_unit_suite(self):
        test_file = Path(__file__).with_suffix(".js")
        result = subprocess.run(
            ["node", str(test_file)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_docassemble_asset_and_adapter_load_before_editor(self):
        template = (self.package_dir / "data/templates/editor.html").read_text()
        editor = (self.package_dir / "data/static/editor.js").read_text()

        self.assertLess(
            template.index("/static/app/cm6.min.js"), template.index("editor.js")
        )
        self.assertLess(
            template.index("editor_source_adapter.js"), template.index("editor.js")
        )
        self.assertIn("ALWeaverSourceEditor.createSourceEditor", editor)
        self.assertNotIn("monaco", editor.lower())
        self.assertNotIn("cdn.jsdelivr.net", editor)

    def test_docassemble_19_and_110_contract_when_checkout_available(self):
        checkout = Path(
            os.environ.get(
                "DOCASSEMBLE_SOURCE_CHECKOUT",
                str(self.repo_dir.parent / "docassemble"),
            )
        )
        if not (checkout / ".git").is_dir():
            self.skipTest("Set DOCASSEMBLE_SOURCE_CHECKOUT to verify upstream assets")

        asset = "docassemble_webapp/docassemble/webapp/static/app/cm6.js"
        for ref in ("v1.9.0", "v1.9.13", "v1.10.0", "v1.10.7"):
            result = subprocess.run(
                ["git", "-C", str(checkout), "show", f"{ref}:{asset}"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, f"{ref}: {result.stderr}")
            source = result.stdout
            self.assertIn(
                "function daNewEditor(parent, initial_contents, mode, keymapping, lineWrapping)",
                source,
            )
            self.assertIn("window.daNewEditor = daNewEditor", source)
            self.assertIn("this.ev = ev", source)
            self.assertIn("disable()", source)
            self.assertIn("enable()", source)


if __name__ == "__main__":
    unittest.main()
