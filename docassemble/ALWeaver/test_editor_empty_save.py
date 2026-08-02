from pathlib import Path
import unittest


class TestEditorEmptySave(unittest.TestCase):
    def test_full_source_save_distinguishes_empty_from_missing_content(self):
        editor_js = (
            Path(__file__).resolve().parent / "data" / "static" / "editor.js"
        ).read_text(encoding="utf-8")
        handler_start = editor_js.index("if (target.id === 'save-full-yaml')")
        handler_end = editor_js.index("// Order builder", handler_start)
        handler = editor_js[handler_start:handler_end]

        self.assertIn("yamlContent === undefined || yamlContent === null", handler)
        self.assertNotIn("if (!yamlContent) return", handler)


if __name__ == "__main__":
    unittest.main()
