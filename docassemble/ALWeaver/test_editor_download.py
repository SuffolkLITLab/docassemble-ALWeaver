from pathlib import Path
import unittest


class TestEditorDownload(unittest.TestCase):
    def test_download_uses_canonical_raw_yaml_and_validates_it(self):
        editor_js = (
            Path(__file__).resolve().parent / "data" / "static" / "editor.js"
        ).read_text(encoding="utf-8")
        handler_start = editor_js.index("if (target.id === 'btn-download-file')")
        handler_end = editor_js.index(
            "if (target.id === 'btn-rename-file')", handler_start
        )
        handler = editor_js[handler_start:handler_end]

        self.assertIn("typeof res.data.raw_yaml !== 'string'", handler)
        self.assertIn("var content = res.data.raw_yaml;", handler)
        self.assertNotIn("res.data.content", handler)
        self.assertIn("Unable to download", handler)


if __name__ == "__main__":
    unittest.main()
