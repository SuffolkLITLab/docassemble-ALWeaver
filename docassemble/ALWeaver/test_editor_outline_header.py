import unittest
from pathlib import Path


class TestEditorOutlineHeader(unittest.TestCase):
    def test_outline_header_switches_by_view(self):
        base = Path(__file__).resolve().parent
        editor_js = (base / "data" / "static" / "editor.js").read_text(encoding="utf-8")
        editor_html = (base / "data" / "templates" / "editor.html").read_text(encoding="utf-8")
        editor_css = (base / "data" / "static" / "editor.css").read_text(encoding="utf-8")

        self.assertIn("function updateOutlineHeader()", editor_js)
        self.assertIn("isInterviewView() ? 'Outline' : 'File list'", editor_js)
        self.assertIn("classList.toggle('d-none', !isInterviewView())", editor_js)
        self.assertIn("return isInterviewView() && !state.searchQuery.trim();", editor_js)
        self.assertIn("function getBlockDisplayType(block)", editor_js)
        self.assertIn("function buildFullOutlineOrderFromVisibleIds(visibleIds)", editor_js)
        self.assertIn("function enterOrderBuilder(requestedBlockId, source)", editor_js)
        self.assertIn("function scrollOrderBuilderIntoView()", editor_js)
        self.assertIn("console.warn('[Order] No interview-order block found for order builder.')", editor_js)
        self.assertIn("data-block-action=\"move-up\"", editor_js)
        self.assertIn("enableAction = block.type === 'commented' ? 'enable' : 'comment'", editor_js)
        self.assertIn("Disable (comment out)", editor_js)
        self.assertIn("Re-enable block", editor_js)
        self.assertIn("data-project-action=\"rename\"", editor_js)
        self.assertIn("editor-order-builder-btn", editor_html)
        self.assertNotIn("editor-icon-btn\" id=\"btn-order-builder\"", editor_html)
        self.assertIn("editor-project-card-actions", editor_js)
        self.assertIn("editor-outline-drag-handle", editor_js)
        self.assertIn("editor-outline-item-actions", editor_js)
        self.assertIn("editor-outline-item-commented", editor_js)
        self.assertIn("renderCommentedBlock(block)", editor_js)
        self.assertIn(".editor-order-builder-btn {", editor_css)
        self.assertIn("display: inline-flex;", editor_css)
        self.assertIn("white-space: nowrap;", editor_css)
        self.assertIn("overflow-x: hidden;", editor_css)
        self.assertIn("padding: 6px 8px;", editor_css)
        self.assertIn("font-size: 11px;", editor_css)
        self.assertIn(".editor-project-card-shell {", editor_css)
        self.assertIn(".editor-outline-menu-btn {", editor_css)
        self.assertIn(".editor-outline-item-commented {", editor_css)


if __name__ == "__main__":
    unittest.main()
