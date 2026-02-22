import unittest
import tempfile
from pathlib import Path

from .playground_publish import (
    _source_path_and_filename,
    next_available_project_name,
    normalize_project_name,
)


class test_playground_publish(unittest.TestCase):
    def test_normalize_project_name(self):
        self.assertEqual(normalize_project_name("My New Project"), "MyNewProject")
        self.assertEqual(normalize_project_name("123 starts with digits"), "P123startswithdigits")
        self.assertEqual(normalize_project_name("default"), "defaultProject")
        self.assertEqual(normalize_project_name("!!!"), "ALWeaverProject")

    def test_next_available_project_name_when_unused(self):
        self.assertEqual(
            next_available_project_name("HousingCase", ["OtherProject", "HousingCase2"]),
            "HousingCase",
        )

    def test_next_available_project_name_increments_suffix(self):
        self.assertEqual(
            next_available_project_name(
                "HousingCase", ["HousingCase", "HousingCase1", "HousingCase2"]
            ),
            "HousingCase3",
        )
        self.assertEqual(
            next_available_project_name("HousingCase9", ["HousingCase9", "HousingCase10"]),
            "HousingCase11",
        )

    def test_source_filename_adds_extension_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "next_steps.docx"
            source_path.write_bytes(b"test")

            class DummyFile:
                filename = "hello_planet2__copy_next_steps"

                def path(self):
                    return str(source_path)

            resolved_path, resolved_name = _source_path_and_filename(DummyFile())
            self.assertEqual(resolved_path, str(source_path))
            self.assertEqual(resolved_name, "hello_planet2__copy_next_steps.docx")


if __name__ == "__main__":
    unittest.main()
