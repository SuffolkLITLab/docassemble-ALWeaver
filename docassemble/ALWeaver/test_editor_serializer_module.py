from pathlib import Path
import re
import subprocess
import unittest


class TestEditorSerializerModule(unittest.TestCase):
    def test_serializer_has_one_authoritative_implementation(self):
        base = Path(__file__).resolve().parent
        editor_js = (base / "data" / "static" / "editor.js").read_text(encoding="utf-8")
        serializers_js = (base / "data" / "static" / "editor_serializers.js").read_text(
            encoding="utf-8"
        )

        combined = editor_js + serializers_js
        self.assertEqual(len(re.findall(r"function escapeYamlStr\s*\(", combined)), 1)
        self.assertEqual(
            len(re.findall(r"function serializeQuestionToYaml\s*\(", combined)), 1
        )

    def test_serializer_module_loads_before_editor(self):
        template = (
            Path(__file__).resolve().parent / "data" / "templates" / "editor.html"
        ).read_text(encoding="utf-8")
        self.assertLess(
            template.index("/al/editor/static/editor_serializers.js"),
            template.index("/al/editor/static/editor.js"),
        )

    def test_serializer_javascript_unit_suite(self):
        test_file = Path(__file__).with_name("test_editor_serializers.js")
        result = subprocess.run(
            ["node", str(test_file)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
