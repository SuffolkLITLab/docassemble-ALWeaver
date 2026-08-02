from pathlib import Path
import subprocess
import unittest


class TestEditorRuntimeInspector(unittest.TestCase):
    def test_runtime_inspector_javascript_helpers(self):
        test_file = Path(__file__).with_suffix(".js")
        completed = subprocess.run(
            ["node", str(test_file)], check=False, capture_output=True, text=True
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_ui_uses_runtime_ownership_language_and_no_arbitrary_action_box(self):
        package_dir = Path(__file__).resolve().parent
        template = (package_dir / "data/templates/editor.html").read_text()
        runtime_source = (
            package_dir / "data/static/editor_runtime_inspector.js"
        ).read_text()
        editor_source = (package_dir / "data/static/editor.js").read_text()

        self.assertLess(
            template.index("editor_runtime_inspector.js"), template.index("editor.js")
        )
        for label in (
            "Open interview",
            "Start new test session",
            "Apply scenario",
            "Inspect current question",
        ):
            self.assertIn(label, template + runtime_source)
        self.assertIn("Docassemble is the authoritative runtime", runtime_source)
        self.assertIn("observed runtime fact", runtime_source)
        self.assertNotIn(
            "Run from this screen", template + runtime_source + editor_source
        )
        self.assertNotIn("action name", runtime_source.lower())

    def test_runtime_control_is_feature_flagged(self):
        package_dir = Path(__file__).resolve().parent
        editor_source = (package_dir / "data/static/editor.js").read_text()
        api_source = (package_dir / "api_editor.py").read_text()
        self.assertIn("BOOT.features && BOOT.features.runtimeInspector", editor_source)
        self.assertIn('"WEAVER_ENABLE_RUNTIME_INSPECTOR"', api_source)


if __name__ == "__main__":
    unittest.main()
