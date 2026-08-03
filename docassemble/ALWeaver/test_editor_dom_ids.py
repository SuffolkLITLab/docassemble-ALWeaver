from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import unittest


class _IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.actions = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if attributes.get("data-action"):
            self.actions.append(attributes["data-action"])


class TestEditorDomIds(unittest.TestCase):
    def test_editor_template_ids_are_unique(self):
        template = (
            Path(__file__).resolve().parent / "data" / "templates" / "editor.html"
        ).read_text(encoding="utf-8")
        parser = _IdCollector()
        parser.feed(template)

        duplicates = sorted(
            element_id for element_id, count in Counter(parser.ids).items() if count > 1
        )
        self.assertEqual(duplicates, [])

    def test_repeated_top_bar_controls_use_data_actions(self):
        template = (
            Path(__file__).resolve().parent / "data" / "templates" / "editor.html"
        ).read_text(encoding="utf-8")
        parser = _IdCollector()
        parser.feed(template)
        counts = Counter(parser.actions)

        for action in (
            "open-project-selector",
            "open-full-yaml",
            "check-errors",
            "open-standard-playground",
            "preview-interview",
        ):
            self.assertEqual(counts[action], 2)


if __name__ == "__main__":
    unittest.main()
