# do not pre-load

import subprocess
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from . import playground_publish
from .playground_publish import (
    _source_path_and_filename,
    load_project_github_manifest,
    next_available_project_name,
    normalize_github_package_name,
    normalize_project_name,
    prepare_project_github_package,
    merge_github_snapshot,
)


class test_playground_publish(unittest.TestCase):
    def test_merge_file_subprocess_failures_become_merge_conflicts(self):
        failures = (
            subprocess.TimeoutExpired(["git", "merge-file"], 30),
            OSError("git could not start"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch.object(
                    playground_publish.subprocess, "run", side_effect=failure
                ) as merge_file:
                    result = playground_publish._merge_file_content(
                        b"local\n", b"base\n", b"remote\n"
                    )

                self.assertIsNone(result)
                self.assertEqual(merge_file.call_args.kwargs["timeout"], 30)

    def test_github_pull_three_way_merges_non_overlapping_edits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class FakeArea:
                def __init__(self, section):
                    self.directory = str(root / section)
                    Path(self.directory).mkdir(parents=True, exist_ok=True)

                def finalize(self):
                    pass

            areas = {
                section: FakeArea(section)
                for section in playground_publish.PLAYGROUND_SECTIONS
            }
            project_dir = Path(areas["playground"].directory) / "Housing"
            project_dir.mkdir()
            base_text = "title: Original\nline2: same\nline3: same\nline4: same\nending: Original\n"
            local_text = base_text.replace("title: Original", "title: Local")
            remote_text = base_text.replace("ending: Original", "ending: Remote")
            (project_dir / "main.yml").write_text(local_text, encoding="utf-8")
            repo_path = "docassemble/HousingForms/data/questions/main.yml"
            sync = {
                "package": "HousingForms",
                "repository_url": "https://github.com/LegalAid/docassemble-HousingForms",
                "branch": "main",
            }
            with (
                patch.object(
                    playground_publish,
                    "create_saved_file",
                    side_effect=lambda _uid, fix, section: areas[section],
                ),
                patch.object(playground_publish, "prepare_project_github_package"),
                patch.object(
                    playground_publish, "record_project_github_sync"
                ) as record,
            ):
                result = merge_github_snapshot(
                    user_id=7,
                    project_name="Housing",
                    base_snapshot={"files": {repo_path: base_text.encode()}},
                    remote_snapshot={
                        "files": {repo_path: remote_text.encode()},
                        "branch": "main",
                        "sha": "remote-sha",
                    },
                    sync=sync,
                )

            merged = (project_dir / "main.yml").read_text(encoding="utf-8")
            self.assertTrue(result["merged"])
            self.assertIn("title: Local", merged)
            self.assertIn("ending: Remote", merged)
            record.assert_called_once()

    def test_github_pull_leaves_project_untouched_on_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class FakeArea:
                def __init__(self, section):
                    self.directory = str(root / section)
                    Path(self.directory).mkdir(parents=True, exist_ok=True)

                def finalize(self):
                    pass

            areas = {
                section: FakeArea(section)
                for section in playground_publish.PLAYGROUND_SECTIONS
            }
            project_dir = Path(areas["playground"].directory) / "Housing"
            project_dir.mkdir()
            original = b"question: Local title\n"
            (project_dir / "main.yml").write_bytes(original)
            repo_path = "docassemble/HousingForms/data/questions/main.yml"
            with (
                patch.object(
                    playground_publish,
                    "create_saved_file",
                    side_effect=lambda _uid, fix, section: areas[section],
                ),
                patch.object(
                    playground_publish, "prepare_project_github_package"
                ) as prepare,
            ):
                result = merge_github_snapshot(
                    user_id=7,
                    project_name="Housing",
                    base_snapshot={"files": {repo_path: b"question: Base title\n"}},
                    remote_snapshot={
                        "files": {repo_path: b"question: Remote title\n"},
                        "branch": "main",
                        "sha": "remote-sha",
                    },
                    sync={
                        "package": "HousingForms",
                        "repository_url": "https://github.com/LegalAid/docassemble-HousingForms",
                        "branch": "main",
                    },
                )

            self.assertFalse(result["merged"])
            self.assertEqual((project_dir / "main.yml").read_bytes(), original)
            prepare.assert_not_called()

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

    def test_record_github_sync_normalizes_fallback_commit_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "Housing"
            project_dir.mkdir()
            manifest_path = project_dir / "docassemble.HousingForms"
            manifest_path.write_text("dependencies: []\n", encoding="utf-8")

            class FakeArea:
                directory = temp_dir

                def finalize(self):
                    pass

            with patch.object(
                playground_publish,
                "create_saved_file",
                return_value=FakeArea(),
            ):
                playground_publish.record_project_github_sync(
                    user_id=7,
                    project_name="Housing",
                    package_name="docassemble-HousingForms",
                    repository_url=(
                        "https://github.com/LegalAid/docassemble-HousingForms"
                    ),
                    branch="main",
                    commit_sha="abc123",
                )

            self.assertEqual(
                (project_dir / ".docassemble-HousingForms").read_text(encoding="utf-8"),
                "abc123\n",
            )
            self.assertFalse(
                (project_dir / ".docassemble-docassemble-HousingForms").exists()
            )

    def test_snapshot_project_files_rejects_nested_data_files(self):
        with self.assertRaisesRegex(ValueError, "nested files"):
            playground_publish._snapshot_project_files(
                {
                    "docassemble/HousingForms/data/questions/main.yml": b"question: Hi\n",
                    "docassemble/HousingForms/data/static/images/logo.svg": b"<svg />",
                }
            )

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

            # The publishing worker reads the manifest back through the saved
            # file area, which may be a different host than wrote it.
            fetched = []

            def fake_create_saved_file(_uid, fix, section):
                fetched.append((section, fix))
                return areas[section]

            with patch.object(
                playground_publish,
                "create_saved_file",
                side_effect=fake_create_saved_file,
            ):
                loaded, loaded_path = load_project_github_manifest(
                    user_id=7,
                    project_name="Housing",
                    package_name="HousingForms",
                )

            self.assertEqual(loaded_path, result["manifest_path"])
            self.assertEqual(loaded, manifest)
            self.assertEqual(fetched, [("playgroundpackages", True)])

    def test_load_project_github_manifest_reports_a_missing_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:

            class FakeArea:
                directory = temp_dir

            with patch.object(
                playground_publish,
                "create_saved_file",
                return_value=FakeArea(),
            ):
                with self.assertRaises(ValueError) as raised:
                    load_project_github_manifest(
                        user_id=7,
                        project_name="Housing",
                        package_name="HousingForms",
                    )

        self.assertIn("prepare the project again", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
