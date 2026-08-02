from pathlib import Path
import subprocess
import unittest


class TestEditorDirtyState(unittest.TestCase):
    def test_dirty_state_javascript_unit_suite(self):
        test_file = Path(__file__).with_suffix(".js")
        result = subprocess.run(
            ["node", str(test_file)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_editor_loads_dirty_state_before_controller(self):
        package_dir = Path(__file__).parent
        template = (package_dir / "data/templates/editor.html").read_text()
        editor = (package_dir / "data/static/editor.js").read_text()

        self.assertLess(
            template.index("editor_dirty_state.js"),
            template.index("editor.js"),
        )
        self.assertIn("ALWeaverDirtyState.createDirtyState", editor)
        self.assertNotIn("state.dirty", editor)

        for choice in ("save", "discard", "stay"):
            self.assertIn(f'data-unsaved-choice="{choice}"', template)
        self.assertIn("discardInterviewChanges", editor)
        self.assertNotIn("You have unsaved changes. Save before", editor)


if __name__ == "__main__":
    unittest.main()
