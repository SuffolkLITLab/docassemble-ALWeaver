from pathlib import Path
import subprocess
import unittest


class TestEditorFrontendModules(unittest.TestCase):
    def test_state_and_command_modules_load_before_controller(self):
        package_dir = Path(__file__).resolve().parent
        template = (package_dir / "data/templates/editor.html").read_text()
        editor = (package_dir / "data/static/editor.js").read_text()

        self.assertLess(template.index("editor_state_store.js"), template.index("editor.js"))
        self.assertLess(
            template.index("editor_command_manager.js"), template.index("editor.js")
        )
        self.assertIn("ALWeaverStateStore.createEditorStore", editor)
        self.assertIn("ALWeaverCommands.createCommandManager", editor)

    def test_frontend_module_unit_tests(self):
        package_dir = Path(__file__).resolve().parent
        for test_file in (
            "test_editor_state_store.js",
            "test_editor_command_manager.js",
        ):
            completed = subprocess.run(
                ["node", str(package_dir / test_file)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"{test_file} failed:\n{completed.stdout}\n{completed.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
