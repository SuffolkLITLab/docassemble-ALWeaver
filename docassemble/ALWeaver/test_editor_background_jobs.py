from pathlib import Path
import unittest


class TestEditorBackgroundJobs(unittest.TestCase):
    def test_editor_uses_celery_and_handles_every_terminal_state(self):
        package_dir = Path(__file__).resolve().parent
        api_source = (package_dir / "api_editor.py").read_text()
        worker_source = (package_dir / "api_weaver_worker.py").read_text()
        editor_source = (package_dir / "data/static/editor.js").read_text()

        self.assertNotIn("import threading", api_source)
        self.assertNotIn("threading.Thread", api_source)
        self.assertIn("workerapp.send_task", api_source)
        self.assertIn("weaver_editor_new_project_task", worker_source)
        for status in ("failed", "cancelled", "expired", "succeeded"):
            self.assertIn(f"jobStatus === '{status}'", editor_source)


if __name__ == "__main__":
    unittest.main()
