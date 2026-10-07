# do not pre-load

"""DAYamlChecker severity must agree across validation and save routes."""

from types import SimpleNamespace
from unittest.mock import patch

from .test_editor_api import api_editor
from .editor_agent_validation import validate_source_text


def test_validation_endpoint_preserves_checker_severity():
    findings = [
        SimpleNamespace(err_str="Advisory", severity="warning", line_number=1),
        SimpleNamespace(err_str="Suggestion", severity="info", line_number=1),
        SimpleNamespace(err_str="Invalid Python", severity="error", line_number=1),
    ]
    with (
        patch.object(api_editor, "_editor_auth_check", return_value=True),
        patch.object(api_editor, "_current_user_id", return_value=1),
        patch.object(
            api_editor, "playground_read_yaml", return_value="question: Hello\n"
        ),
        patch.object(api_editor, "playground_get_variables", return_value={}),
        patch(
            "dayamlchecker.yaml_structure.find_errors_from_string",
            return_value=findings,
        ),
    ):
        response = api_editor.app.test_client().get(
            "/al/editor/api/weaver/validate?project=test&filename=main.yml"
        )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert [finding["level"] for finding in data["errors"]] == [
        "warning",
        "info",
        "error",
    ]
    assert data["summary"] == {"count": 3, "errors": 1, "warnings": 1, "infos": 1}


def test_checker_advisory_does_not_require_draft_save():
    saved = "---\nid: example\nquestion: Saved\n"
    updated = saved + "# author edit\n"
    with (
        patch.object(api_editor, "_editor_auth_check", return_value=True),
        patch.object(api_editor, "_current_user_id", return_value=7),
        patch.object(api_editor, "playground_read_yaml", return_value=saved),
        patch.object(api_editor, "playground_write_yaml") as write,
        patch.object(api_editor, "_validate_source_text", wraps=validate_source_text),
        patch(
            "dayamlchecker.yaml_structure.find_errors_from_string",
            return_value=[
                SimpleNamespace(err_str="Consider a clearer label", severity="warning")
            ],
        ),
    ):
        with api_editor.app.test_request_context(
            "/al/editor/api/file",
            method="POST",
            json={
                "project": "default",
                "filename": "test.yml",
                "content": updated,
                "expected_revision": api_editor.source_revision(saved),
            },
        ):
            response = api_editor.editor_api_save_file()
    assert response.status_code == 200, response.get_json()
    write.assert_called_once_with(7, "default", "test.yml", updated)
