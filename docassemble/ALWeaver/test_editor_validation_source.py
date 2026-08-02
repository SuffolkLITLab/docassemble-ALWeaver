from pathlib import Path
import subprocess
import unittest


class TestEditorValidationSource(unittest.TestCase):
    def setUp(self):
        self.package_dir = Path(__file__).resolve().parent

    def test_validation_source_javascript_unit_suite(self):
        test_file = Path(__file__).with_suffix(".js")
        result = subprocess.run(
            ["node", str(test_file)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_editor_posts_unsaved_source_for_validation(self):
        editor = (self.package_dir / "data/static/editor.js").read_text()
        template = (self.package_dir / "data/templates/editor.html").read_text()

        self.assertIn("/api/validate-source", editor)
        self.assertIn("raw_yaml: validationSource", editor)
        self.assertNotIn("apiGet('/api/weaver/validate", editor)
        self.assertLess(
            template.index("editor_validation_source.js"),
            template.index("editor.js"),
        )


if __name__ == "__main__":
    unittest.main()
