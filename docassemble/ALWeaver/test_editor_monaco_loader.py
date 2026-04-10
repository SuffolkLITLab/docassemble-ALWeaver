import unittest
from pathlib import Path


class TestEditorMonacoLoader(unittest.TestCase):
    def test_editor_js_uses_cdn_only_for_monaco_loader(self):
        editor_js = Path(__file__).resolve().parent / "data" / "static" / "editor.js"
        source = editor_js.read_text(encoding="utf-8")

        self.assertIn(
            "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs/loader.js",
            source,
        )
        self.assertIn(
            "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs",
            source,
        )
        self.assertNotIn("/static/app/monaco-editor/min/vs/loader.js", source)
        self.assertNotIn(
            "/packagestatic/docassemble.webapp/monaco-editor/min/vs/loader.js",
            source,
        )
        self.assertNotIn("/static/app/monaco-editor/min/vs", source)


if __name__ == "__main__":
    unittest.main()
