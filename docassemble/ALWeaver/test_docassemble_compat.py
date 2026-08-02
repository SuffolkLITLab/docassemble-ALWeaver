import os
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import patch

from . import docassemble_compat


class TestDocassembleCompatibilityInterface(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls

        class FakeFunctions:
            server = types.SimpleNamespace()

            @staticmethod
            def create_session(yaml_filename, secret=None, url_args=None):
                calls.append(("create", yaml_filename, secret, url_args))
                return "session-123"

            @staticmethod
            def get_session_variables(*args, **kwargs):
                calls.append(("variables", args, kwargs))
                return {"answer": 42}

            @staticmethod
            def set_session_variables(*args, **kwargs):
                calls.append(("set", args, kwargs))

            @staticmethod
            def get_question_data(*args, **kwargs):
                calls.append(("question", args, kwargs))
                return {"questionName": "intro"}

            @staticmethod
            def go_back_in_session(*args, **kwargs):
                calls.append(("back", args, kwargs))
                return "back"

            @staticmethod
            def run_action_in_session(*args, **kwargs):
                calls.append(("action", args, kwargs))
                return True

        self.functions = FakeFunctions()
        self.functions.server.run_action_in_session = lambda **kwargs: {
            "status": "success",
            "data": {"observed": kwargs["action"]},
            "warnings": ["test warning"],
        }
        self.base_patch = patch.object(
            docassemble_compat, "_base_functions", return_value=self.functions
        )
        self.hook_patch = patch.object(
            docassemble_compat, "_pluggy_action_hook", return_value=None
        )
        self.base_patch.start()
        self.hook_patch.start()

    def tearDown(self):
        self.hook_patch.stop()
        self.base_patch.stop()

    def test_target_session_wrappers_use_stable_high_level_functions(self):
        target = docassemble_compat.create_target_session(
            "pkg:interview.yml", secret="secret", url_args={"test": "1"}
        )
        self.assertEqual(target.session_id, "session-123")
        self.assertEqual(
            docassemble_compat.get_target_variables(target), {"answer": 42}
        )
        docassemble_compat.set_target_variables(
            target,
            {"seeded": True},
            delete=["old"],
            overwrite=True,
            process_objects=True,
        )
        self.assertEqual(
            docassemble_compat.get_target_question(target)["questionName"], "intro"
        )
        self.assertEqual(docassemble_compat.go_back_target_session(target), "back")
        docassemble_compat.run_target_action(target, "inspect", read_only=True)

        set_call = next(call for call in self.calls if call[0] == "set")
        self.assertEqual(set_call[2]["delete"], ["old"])
        self.assertTrue(set_call[2]["overwrite"])
        action_call = next(call for call in self.calls if call[0] == "action")
        self.assertTrue(action_call[2]["read_only"])

    def test_raw_action_uses_19_server_and_normalizes_result(self):
        target = docassemble_compat.TargetSession("pkg:interview.yml", "session-123")
        result = docassemble_compat.run_target_action_raw(
            target, "al_weaver.inspect_object"
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data, {"observed": "al_weaver.inspect_object"})
        self.assertEqual(result.warnings, ["test warning"])

    def test_raw_action_prefers_110_pluggy_hook(self):
        captured = {}

        def hook(**kwargs):
            captured.update(kwargs)
            return {"status": "success", "data": {"hook": True}}

        target = docassemble_compat.TargetSession("pkg:interview.yml", "session-123")
        with patch.object(docassemble_compat, "_pluggy_action_hook", return_value=hook):
            result = docassemble_compat.run_target_action_raw(target, "inspect")

        self.assertEqual(result.data, {"hook": True})
        self.assertTrue(captured["read_only"])


class TestDocassembleSourceCompatibility(unittest.TestCase):
    def test_19_and_110_session_contracts_when_checkout_available(self):
        repo_dir = Path(__file__).resolve().parents[2]
        checkout = Path(
            os.environ.get(
                "DOCASSEMBLE_SOURCE_CHECKOUT", str(repo_dir.parent / "docassemble")
            )
        )
        if not (checkout / ".git").is_dir():
            self.skipTest("Set DOCASSEMBLE_SOURCE_CHECKOUT to verify upstream APIs")

        functions_path = "docassemble_base/docassemble/base/functions.py"
        expected_signatures = (
            "def create_session(yaml_filename, secret=None, url_args=None):",
            "def get_session_variables(yaml_filename, session_id, secret=None, simplify=True):",
            "def set_session_variables(yaml_filename, session_id, variables, secret=None, question_name=None, overwrite=False, process_objects=False, delete=None):",
            "def run_action_in_session(yaml_filename, session_id, action, arguments=None, secret=None, persistent=False, overwrite=False, read_only=False):",
            "def get_question_data(yaml_filename, session_id, secret=None):",
            "def go_back_in_session(yaml_filename, session_id, secret=None):",
        )
        for ref in ("v1.9.0", "v1.9.13", "v1.10.0", "v1.10.7"):
            result = subprocess.run(
                ["git", "-C", str(checkout), "show", f"{ref}:{functions_path}"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, f"{ref}: {result.stderr}")
            for signature in expected_signatures:
                self.assertIn(signature, result.stdout, f"{ref}: {signature}")

        hooks_result = subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "show",
                "v1.10.7:docassemble_base/docassemble/base/hooks.py",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(hooks_result.returncode, 0, hooks_result.stderr)
        self.assertIn("def server_run_action_in_session(**kwargs)", hooks_result.stdout)


if __name__ == "__main__":
    unittest.main()
