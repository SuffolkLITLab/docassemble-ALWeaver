import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from . import playground_publish
from .playground_publish import (
    _source_path_and_filename,
    next_available_project_name,
    normalize_github_package_name,
    normalize_project_name,
    prepare_project_github_package,
)


class test_playground_publish(unittest.TestCase):
    def test_normalize_project_name(self):
        self.assertEqual(normalize_project_name("My New Project"), "MyNewProject")
        self.assertEqual(
            normalize_project_name("123 starts with digits"), "P123startswithdigits"
        )
        self.assertEqual(normalize_project_name("default"), "defaultProject")
        self.assertEqual(normalize_project_name("!!!"), "ALWeaverProject")

    def test_next_available_project_name_when_unused(self):
        self.assertEqual(
            next_available_project_name(
                "HousingCase", ["OtherProject", "HousingCase2"]
            ),
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
            next_available_project_name(
                "HousingCase9", ["HousingCase9", "HousingCase10"]
            ),
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

    def test_normalize_github_package_name_accepts_docassemble_prefix(self):
        self.assertEqual(
            normalize_github_package_name("docassemble-HousingForms"),
            "HousingForms",
        )
        with self.assertRaises(ValueError):
            normalize_github_package_name("housing-forms")

    def test_prepare_project_github_package_lists_every_visible_project_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class FakeArea:
                def __init__(self, section):
                    self.directory = str(root / section)
                    Path(self.directory).mkdir(parents=True, exist_ok=True)
                    self.finalized = False

                def finalize(self):
                    self.finalized = True

            areas = {
                section: FakeArea(section)
                for section in (
                    "playground",
                    "playgroundtemplate",
                    "playgroundmodules",
                    "playgroundstatic",
                    "playgroundsources",
                    "playgroundpackages",
                )
            }
            for section, filename in (
                ("playground", "main.yml"),
                ("playgroundtemplate", "form.docx"),
                ("playgroundmodules", "helpers.py"),
                ("playgroundstatic", "logo.svg"),
                ("playgroundsources", "terms.yml"),
            ):
                project_dir = Path(areas[section].directory) / "Housing"
                project_dir.mkdir(parents=True, exist_ok=True)
                (project_dir / filename).write_text("test", encoding="utf-8")
                (project_dir / ".placeholder").write_text("", encoding="utf-8")

            with patch.object(
                playground_publish,
                "create_saved_file",
                side_effect=lambda _uid, fix, section: areas[section],
            ):
                result = prepare_project_github_package(
                    user_id=7,
                    project_name="Housing",
                    package_name="HousingForms",
                    author_name="Ada Developer",
                    author_email="ada@example.com",
                    github_url="https://github.com/LegalAid/docassemble-HousingForms",
                )

            manifest = yaml.safe_load(Path(result["manifest_path"]).read_text())
            self.assertEqual(result["repository"], "docassemble-HousingForms")
            self.assertEqual(manifest["interview_files"], ["main.yml"])
            self.assertEqual(manifest["template_files"], ["form.docx"])
            self.assertEqual(manifest["module_files"], ["helpers.py"])
            self.assertEqual(manifest["static_files"], ["logo.svg"])
            self.assertEqual(manifest["sources_files"], ["terms.yml"])
            self.assertEqual(manifest["author_email"], "ada@example.com")
            self.assertEqual(
                manifest["github_url"],
                "https://github.com/LegalAid/docassemble-HousingForms",
            )
            self.assertNotIn(".placeholder", str(manifest))
            self.assertTrue(areas["playgroundpackages"].finalized)


if __name__ == "__main__":
    unittest.main()
