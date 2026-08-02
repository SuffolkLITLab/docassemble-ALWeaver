from pathlib import Path
import subprocess
import unittest


class TestEditorApiClient(unittest.TestCase):
    def test_api_client_javascript_unit_suite(self):
        test_file = Path(__file__).with_suffix(".js")
        result = subprocess.run(
            ["node", str(test_file)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_editor_loads_and_uses_centralized_client(self):
        package_dir = Path(__file__).parent
        template = (package_dir / "data/templates/editor.html").read_text()
        editor = (package_dir / "data/static/editor.js").read_text()

        self.assertLess(
            template.index("editor_api_client.js"),
            template.index("editor.js"),
        )
        self.assertIn("ALWeaverApiClient.createClient", editor)
        self.assertNotIn("function apiFetch", editor)


if __name__ == "__main__":
    unittest.main()
