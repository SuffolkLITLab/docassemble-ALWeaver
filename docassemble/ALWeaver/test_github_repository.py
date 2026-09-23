# do not pre-load
import importlib.metadata
import tomllib
import unittest
from unittest.mock import patch

import yaml

from . import github_repository as repo

MANIFEST = {
    "version": "1.2.0",
    "description": "Housing forms",
    "license": "MIT License",
    "author_name": "Ada",
    "author_email": "ada@example.com",
    "url": "",
}


def _resolve(config=None, *, detected=(), has_features=True, has_modules=False):
    return repo.resolve_config(
        repo.normalize_config(config or {}),
        package="HousingForms",
        manifest=MANIFEST,
        detected=list(detected),
        has_features=has_features,
        has_modules=has_modules,
    )


def _apply(config, operation, detected=()):
    return repo.apply_operation(
        repo.normalize_config(config),
        operation,
        package="HousingForms",
        manifest=MANIFEST,
        detected=list(detected),
    )


def _enabled(resolved):
    return {item["id"] for item in resolved["workflows"] if item["enabled"]}


class TestWorkflowDefaults(unittest.TestCase):
    def test_install_and_hall_monitor_are_offered_but_off(self):
        resolved = _resolve(has_features=True, has_modules=True)
        self.assertEqual(
            _enabled(resolved),
            {
                "alkiln",
                "build_and_check",
                "validate_docx",
                "word_diff",
                "python_quality",
            },
        )
        offered = {item["id"] for item in resolved["workflows"]}
        self.assertTrue(
            {"deploy_playground", "deploy_package", "hall_monitor"} <= offered
        )

    def test_python_checks_need_modules_and_alkiln_needs_tests(self):
        enabled = _enabled(_resolve(has_features=False, has_modules=False))
        self.assertNotIn("python_quality", enabled)
        self.assertNotIn("alkiln", enabled)

    def test_alkiln_runs_on_githubs_isolated_server(self):
        files = _resolve()["files"]
        workflow = yaml.safe_load(files[".github/workflows/run_interview_tests.yml"])
        steps = workflow["jobs"]["interview-testing"]["steps"]
        uses = [step.get("uses") for step in steps]
        self.assertIn("SuffolkLITLab/ALKiln/action_for_github_server@v5", uses)
        kiln = next(
            step for step in steps if step.get("uses") == "SuffolkLITLab/ALKiln@v5"
        )
        self.assertEqual(kiln["with"]["INSTALL_METHOD"], "server")
        self.assertIn(
            "steps.github_server.outputs.SERVER_URL", kiln["with"]["SERVER_URL"]
        )
        self.assertNotIn(
            "secrets.SERVER_URL", files[".github/workflows/run_interview_tests.yml"]
        )

    def test_every_standard_workflow_is_valid_yaml_with_jobs(self):
        for workflow in repo.STANDARD_WORKFLOWS:
            with self.subTest(workflow.id):
                self.assertIn("jobs", yaml.safe_load(workflow.content))

    def test_turning_off_and_editing_workflows(self):
        config = _apply({}, {"type": "workflow", "id": "word_diff", "enabled": False})
        custom = repo.BUILD_AND_CHECK_WORKFLOW.replace("3.12", "3.11")
        config = _apply(
            config, {"type": "workflow", "id": "build_and_check", "content": custom}
        )
        resolved = _resolve(config)
        self.assertNotIn(".github/workflows/word_diff.yml", resolved["files"])
        self.assertEqual(
            resolved["files"][".github/workflows/build_and_check.yml"], custom
        )
        build = next(
            item for item in resolved["workflows"] if item["id"] == "build_and_check"
        )
        self.assertTrue(build["customized"])
        # Turned-off workflows stay managed, so publishing removes them.
        self.assertIn(".github/workflows/word_diff.yml", resolved["managed_paths"])

        reset = _apply(
            config, {"type": "workflow", "id": "build_and_check", "content": None}
        )
        self.assertEqual(
            _resolve(reset)["files"][".github/workflows/build_and_check.yml"],
            repo.BUILD_AND_CHECK_WORKFLOW,
        )

    def test_rejects_workflow_that_is_not_a_workflow(self):
        for content in ("name: [unclosed", "just text"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                _apply({}, {"type": "workflow", "id": "alkiln", "content": content})
        with self.assertRaises(ValueError):
            _apply({}, {"type": "workflow", "id": "nope", "enabled": True})


class TestDependencies(unittest.TestCase):
    def test_detects_included_and_imported_packages_only(self):
        yaml_text = """
include:
  - docassemble.AssemblyLine:assembly_line.yml
  - "docassemble.MassAccess:massaccess.yml"
  - docassemble.HousingForms:shared.yml
  - docassemble.playground7Housing:other.yml
modules:
  - docassemble.ALToolbox.misc
  - docassemble.base.util
  - .custom
---
question: Mentions docassemble.NotADependency in prose
"""
        module_text = (
            "from docassemble.ALRecipes.stuff import x\nimport docassemble.webapp\n"
        )
        self.assertEqual(
            repo.detect_dependencies([yaml_text], [module_text], "HousingForms"),
            [
                "docassemble.ALRecipes",
                "docassemble.ALToolbox",
                "docassemble.AssemblyLine",
                "docassemble.MassAccess",
            ],
        )

    def test_generated_pyproject_lists_detected_and_added_dependencies(self):
        config = _apply(
            {},
            {
                "type": "dependencies",
                "dependencies": ["docassemble.AssemblyLine", "requests>=2"],
            },
            detected=["docassemble.AssemblyLine"],
        )
        # The detected package is added back on every publish, so it is not
        # stored as the author's own.
        self.assertEqual(config["dependencies"], ["requests>=2"])
        resolved = _resolve(config, detected=["docassemble.AssemblyLine"])
        data = tomllib.loads(resolved["files"]["pyproject.toml"])
        self.assertEqual(data["project"]["name"], "docassemble.HousingForms")
        self.assertEqual(data["project"]["version"], "1.2.0")
        self.assertEqual(data["project"]["license"], "MIT")
        self.assertEqual(
            data["project"]["dependencies"], ["docassemble.AssemblyLine", "requests>=2"]
        )
        rows = {row["name"]: row for row in resolved["dependencies"]}
        self.assertFalse(rows["docassemble.AssemblyLine"]["removable"])
        self.assertTrue(rows["requests"]["removable"])
        self.assertEqual(
            resolved["dependency_names"], ["docassemble.AssemblyLine", "requests"]
        )

    def test_author_version_overrides_a_detected_dependency(self):
        detected = ["docassemble.AssemblyLine"]
        config = _apply(
            {},
            {"type": "dependencies", "dependencies": ["docassemble.AssemblyLine>=3.0"]},
            detected=detected,
        )
        resolved = _resolve(config, detected=detected)
        self.assertEqual(
            tomllib.loads(resolved["files"]["pyproject.toml"])["project"][
                "dependencies"
            ],
            ["docassemble.AssemblyLine>=3.0"],
        )
        self.assertTrue(resolved["dependencies"][0]["removable"])

    def test_rejects_invalid_and_self_dependencies(self):
        for spec in ("", "not a requirement!!", "docassemble.HousingForms"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                _apply({}, {"type": "dependencies", "dependencies": [spec]})


class TestManifestSeeding(unittest.TestCase):
    def test_existing_manifest_dependencies_are_kept_until_settings_exist(self):
        """A project set up on Docassemble's Packages page must not lose them."""
        detected = ["docassemble.AssemblyLine"]
        config = repo.seed_config_from_manifest(
            {"dependencies": ["requests", "docassemble.AssemblyLine", 3]}, detected
        )
        self.assertEqual(config["dependencies"], ["requests"])
        resolved = _resolve(config, detected=detected)
        self.assertEqual(
            resolved["dependency_names"], ["docassemble.AssemblyLine", "requests"]
        )
        self.assertTrue(
            next(row for row in resolved["dependencies"] if row["name"] == "requests")[
                "removable"
            ]
        )


class TestGithubDependencies(unittest.TestCase):
    def test_pasted_github_urls_become_git_requirements(self):
        cases = {
            "https://github.com/SuffolkLITLab/docassemble-MassAccess": (
                "docassemble.MassAccess @ "
                "git+https://github.com/SuffolkLITLab/docassemble-MassAccess.git"
            ),
            "https://github.com/org/docassemble-Foo.git/": (
                "docassemble.Foo @ git+https://github.com/org/docassemble-Foo.git"
            ),
            "https://github.com/org/docassemble-Foo/tree/feature/x": (
                "docassemble.Foo @ git+https://github.com/org/docassemble-Foo.git"
                "@feature/x"
            ),
        }
        for pasted, requirement in cases.items():
            with self.subTest(pasted=pasted):
                self.assertEqual(repo.validate_dependency(pasted), requirement)

    def test_git_requirement_overrides_detected_name_and_round_trips(self):
        detected = ["docassemble.MassAccess"]
        git = "docassemble.MassAccess @ git+https://github.com/org/docassemble-MassAccess.git@main"
        config = _apply(
            {}, {"type": "dependencies", "dependencies": [git]}, detected=detected
        )
        resolved = _resolve(config, detected=detected)
        text = resolved["files"]["pyproject.toml"]
        self.assertEqual(tomllib.loads(text)["project"]["dependencies"], [git])
        row = resolved["dependencies"][0]
        self.assertTrue(row["github"] and row["detected"] and row["user_set"])
        # The manifest keeps only the name, as Docassemble's Packages page expects.
        self.assertEqual(resolved["dependency_names"], ["docassemble.MassAccess"])

        # A repository that already lists it keeps it through an import.
        adopted = repo.adopt_repository_files(
            repo.normalize_config({}),
            {"pyproject.toml": text.encode()},
            None,
            package="HousingForms",
            manifest=MANIFEST,
            detected=detected,
        )
        self.assertEqual(
            _resolve(adopted, detected=detected)["files"]["pyproject.toml"], text
        )

    def test_detected_package_installed_from_github_keeps_its_source(self):
        class FakeDistribution:
            def read_text(self, name):
                return (
                    '{"url": "https://github.com/org/docassemble-Private", '
                    '"vcs_info": {"vcs": "git", "requested_revision": "main", '
                    '"commit_id": "abc"}}'
                )

        with patch("importlib.metadata.distribution", return_value=FakeDistribution()):
            self.assertEqual(
                repo.installed_requirement("docassemble.Private"),
                "docassemble.Private @ "
                "git+https://github.com/org/docassemble-Private@main",
            )
        with patch(
            "importlib.metadata.distribution",
            side_effect=importlib.metadata.PackageNotFoundError,
        ):
            self.assertEqual(
                repo.installed_requirement("docassemble.Nope"), "docassemble.Nope"
            )


class TestCustomPyproject(unittest.TestCase):
    CUSTOM = """[project]
name = "docassemble.HousingForms"
version = "9.9.9"
dependencies = ["docassemble.ALToolbox"]

[tool.black]
line-length = 100
"""

    def test_custom_file_is_published_as_written(self):
        config = _apply({}, {"type": "pyproject", "text": self.CUSTOM})
        resolved = _resolve(config, detected=["docassemble.AssemblyLine"])
        self.assertEqual(resolved["files"]["pyproject.toml"], self.CUSTOM)
        self.assertTrue(resolved["pyproject"]["custom"])
        # Not silently added to a hand-written file, but flagged.
        self.assertEqual(resolved["missing_dependencies"], ["docassemble.AssemblyLine"])

    def test_visual_dependency_edits_rewrite_the_custom_file(self):
        config = _apply({}, {"type": "pyproject", "text": self.CUSTOM})
        config = _apply(
            config,
            {
                "type": "dependencies",
                "dependencies": ["docassemble.ALToolbox", "docassemble.AssemblyLine"],
            },
        )
        data = tomllib.loads(config["pyproject_toml"])
        self.assertEqual(
            data["project"]["dependencies"],
            ["docassemble.ALToolbox", "docassemble.AssemblyLine"],
        )
        self.assertEqual(data["tool"]["black"]["line-length"], 100)

    def test_going_back_to_generated_keeps_listed_dependencies(self):
        config = _apply({}, {"type": "pyproject", "text": self.CUSTOM})
        config = _apply(config, {"type": "pyproject", "text": None})
        self.assertIsNone(config["pyproject_toml"])
        self.assertEqual(config["dependencies"], ["docassemble.ALToolbox"])

    def test_saving_the_generated_text_stays_generated(self):
        generated = _resolve()["files"]["pyproject.toml"]
        config = _apply({}, {"type": "pyproject", "text": generated})
        self.assertIsNone(config["pyproject_toml"])

    def test_rejects_invalid_toml(self):
        for text in ("[project\nname=", "[tool.black]\nline-length = 1\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                _apply({}, {"type": "pyproject", "text": text})


class TestAdoptRepositoryFiles(unittest.TestCase):
    def _adopt(self, remote, base=None, config=None):
        return repo.adopt_repository_files(
            repo.normalize_config(config or {}),
            {path: text.encode() for path, text in remote.items()},
            (
                None
                if base is None
                else {path: text.encode() for path, text in base.items()}
            ),
            package="HousingForms",
            manifest=MANIFEST,
            detected=[],
        )

    def test_import_keeps_hand_edited_workflows_and_upgrades_the_old_one(self):
        edited = repo.BUILD_AND_CHECK_WORKFLOW.replace("3.12", "3.10")
        config = self._adopt(
            {
                ".github/workflows/build_and_check.yml": edited,
                ".github/workflows/run_interview_tests.yml": repo.LEGACY_ALKILN_SERVER_WORKFLOW,
            }
        )
        self.assertEqual(
            config["workflows"]["build_and_check"], {"enabled": True, "content": edited}
        )
        # Weaver's old server-based workflow is replaced by the sandbox one.
        self.assertEqual(config["workflows"]["alkiln"], {"enabled": True})
        # Standard workflows the repository lacks keep their defaults.
        self.assertNotIn("word_diff", config["workflows"])

    def test_import_takes_dependencies_from_the_repository(self):
        config = self._adopt({"pyproject.toml": TestCustomPyproject.CUSTOM})
        self.assertEqual(config["pyproject_toml"], TestCustomPyproject.CUSTOM)

        config = self._adopt(
            {
                "setup.py": "setup(install_requires=['docassemble.ALToolbox>=0.9', \"requests\"],)"
            }
        )
        self.assertEqual(
            config["dependencies"], ["docassemble.ALToolbox>=0.9", "requests"]
        )

    # What Docassemble's own package builder writes: its setuptools pin, a
    # blank author, a real version, and a version it pinned itself.
    DOCASSEMBLE_BUILT = """[build-system]
requires = ["setuptools>=80.9.0"]
build-backend = "setuptools.build_meta"

[project]
name = "docassemble.HousingForms"
version = "2.1.0"
description = "Housing forms"
readme = "README.md"
authors = [{ name = "", email = "" }]
dependencies = ["docassemble.AssemblyLine>=3.1.0", "requests"]
license = "MIT"
license-files = ["LICENSE"]

[project.urls]
Homepage = "https://courtformsonline.org"

[tool.setuptools.packages.find]
where = ["."]
"""

    def test_import_of_a_builder_written_pyproject_stays_generated(self):
        config = self._adopt({"pyproject.toml": self.DOCASSEMBLE_BUILT})
        # Not frozen as a hand-edited file, so later version bumps and newly
        # detected packages still reach the published file.
        self.assertIsNone(config["pyproject_toml"])
        self.assertEqual(
            config["dependencies"], ["docassemble.AssemblyLine>=3.1.0", "requests"]
        )
        # The import brings the real version along instead of 0.0.1.
        self.assertEqual(
            repo.pyproject_manifest_fields(self.DOCASSEMBLE_BUILT),
            {
                "version": "2.1.0",
                "description": "Housing forms",
                "url": "https://courtformsonline.org",
            },
        )
        self.assertEqual(repo.pyproject_manifest_fields(TestCustomPyproject.CUSTOM), {})

    def test_pull_takes_only_changes_made_on_github(self):
        local = {
            "workflows": {"word_diff": {"enabled": False}},
            "pyproject_toml": TestCustomPyproject.CUSTOM,
        }
        unchanged = {
            ".github/workflows/word_diff.yml": repo.WORD_DIFF_WORKFLOW,
            ".github/workflows/validate_docx.yml": repo.VALIDATE_DOCX_WORKFLOW,
            "pyproject.toml": "[project]\nname = 'old'\n",
        }
        remote = dict(unchanged)
        del remote[".github/workflows/validate_docx.yml"]
        config = self._adopt(remote, base=unchanged, config=local)
        self.assertEqual(config["workflows"]["word_diff"], {"enabled": False})
        self.assertEqual(config["workflows"]["validate_docx"], {"enabled": False})
        self.assertEqual(config["pyproject_toml"], TestCustomPyproject.CUSTOM)


if __name__ == "__main__":
    unittest.main()
