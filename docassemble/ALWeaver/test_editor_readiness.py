# do not pre-load

import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

from dayamlchecker.readiness import REVIEWS
from dayamlchecker.yaml_structure import RuntimeOptions, parse_interview_documents

from .editor_readiness import check_package_snapshot, repair_context_current
from .editor_agent_validation import (
    annotate_lint_findings,
    dayamlchecker_findings,
    validate_candidate_source,
)
from .editor_agent_models import AgentToolResult

SOURCE = """---
metadata:
  title: Test form
---
id: name
question: What is your name?
fields:
  - code: users[0].name_fields()
"""
QUESTION = "docassemble/Test/data/questions/main.yml"


def snapshot(source=SOURCE, template=b"original"):
    return {
        QUESTION: {"content": source.encode()},
        "docassemble/Test/data/templates/form.txt": {"content": template},
    }


def check(files=None, **kwargs):
    return check_package_snapshot(
        files or snapshot(),
        package="Test",
        filename="main.yml",
        raw_yaml=SOURCE,
        **kwargs,
    )


def test_snapshot_includes_unsaved_source_templates_and_invalidates_evidence():
    files = snapshot("question: Old saved source\n")
    before = copy.deepcopy(files)
    report = check(files)
    assert files == before  # overlay never writes to the saved project
    assert (
        report["working_source_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    )
    assert all("weaver-readiness-" not in json.dumps(f) for f in report["findings"])
    assert not report["review_evidence_current"]
    evidence = {"source_sha256": report["source_sha256"]}
    for key in REVIEWS:
        evidence[key] = {
            "passed": True,
            "reviewer": "Reviewer",
            "date": "2026-11-05",
            "evidence": "Reviewed source",
        }
    current = check(files, evidence=evidence)
    assert current["source_sha256"] == report["source_sha256"]
    assert current["review_evidence_current"]
    assert all(c["status"] == "pass" for c in current["checks"] if c["id"] in REVIEWS)
    changed = check(snapshot(template=b"changed"), evidence=evidence)
    assert not changed["review_evidence_current"]
    assert all(
        c["status"] == "needs_review" for c in changed["checks"] if c["id"] in REVIEWS
    )
    unsaved = check_package_snapshot(
        files,
        package="Test",
        filename="main.yml",
        raw_yaml=SOURCE + "# edit\n",
        evidence=evidence,
    )
    assert not unsaved["review_evidence_current"]
    assert current["maturity"]["assessed_level"] is None


def test_checker_context_survives_adapter_annotation_and_model_serialization():
    docs, _ = parse_interview_documents(SOURCE, "main.yml")
    block = docs[1]
    context = {
        "snippet": "What is your name?",
        "repair_context": {
            "schema_version": 1,
            "block_index": block.index,
            "source_yaml": block.source_code,
            "source_sha256": hashlib.sha256(block.source_code.encode()).hexdigest(),
        },
    }
    finding = SimpleNamespace(
        err_str='Consider "What is your name?"',
        severity="warning",
        line_number=5,
        message_id="style_test",
        code="STYLE001",
        finding_class="style",
        context=context,
    )
    with patch(
        "dayamlchecker.yaml_structure.find_errors_from_string", return_value=[finding]
    ):
        diagnostics = dayamlchecker_findings(SOURCE, "main.yml")
    assert diagnostics[0]["context"] == context
    assert diagnostics[0]["variable"] == ""
    assert diagnostics[0]["message_id"] == "style_test"
    annotated = annotate_lint_findings(
        diagnostics, [{"id": "name", "line_start": 5, "line_end": 9}]
    )
    payload = AgentToolResult("validate", "success", diagnostics=annotated).model_dict()
    assert json.loads(json.dumps(payload))["diagnostics"][0]["context"] == context
    assert repair_context_current(SOURCE, diagnostics[0])
    assert not repair_context_current(
        SOURCE.replace("What is your name?", "Your name?"), diagnostics[0]
    )
    bad_hash = copy.deepcopy(diagnostics[0])
    bad_hash["context"]["repair_context"]["source_sha256"] = "old"
    assert not repair_context_current(SOURCE, bad_hash)


def test_older_checker_and_rendered_jinja_have_safe_locations():
    old = SimpleNamespace(err_str='Warning: Check "quote"', line_number=1)
    rendered = SimpleNamespace(err_str="Rendered", line_number=1, rendered_jinja=True)
    with patch(
        "dayamlchecker.yaml_structure.find_errors_from_string",
        return_value=[old, rendered],
    ):
        diagnostics = dayamlchecker_findings(SOURCE, "main.yml")
    assert diagnostics[0]["level"] == "warning"
    assert diagnostics[0]["context"] == {}
    assert diagnostics[0]["variable"] == ""
    assert diagnostics[1]["source_range"] is None
    annotated = annotate_lint_findings(
        diagnostics, [{"id": "first", "line_start": 1, "line_end": 9}]
    )
    assert "block_id" not in annotated[1]
    assert not repair_context_current(SOURCE, diagnostics[1])


def test_precision_style_handles_generated_name_and_contextual_choices():
    source = SOURCE + """---
id: choice
question: Do you have children?
fields:
  - Children: has_children
    choices:
      - Yes: yes
      - No: no
      - Other: other
---
id: ambiguous
question: Tell us more
fields:
  - "???": ambiguous_thing
"""
    findings = dayamlchecker_findings(
        source,
        "main.yml",
        runtime_options=RuntimeOptions(
            style_enabled=True, style_review_level="precision"
        ),
        lint_mode="accessibility",
    )
    messages = [f["message"] for f in findings]
    assert not any("generated" in m.lower() and "count" in m.lower() for m in messages)
    assert not any(
        f.get("context", {}).get("snippet") in {"Yes", "No", "Other"} for f in findings
    )
    assert any("label" in m.lower() and "???" in m for m in messages)


def test_readiness_api_checks_working_package_without_writing_manifest():
    from .test_editor_api import api_editor

    with (
        patch.object(api_editor, "_editor_auth_check", return_value=True),
        patch.object(api_editor, "_current_user_id", return_value=7),
        patch.object(api_editor, "playground_list_projects", return_value=["test"]),
        patch.object(api_editor, "_repository_config_package", return_value="Test"),
        patch.object(
            api_editor,
            "_editor_playground_context",
            return_value={"name": "Tester", "email": "test@example.com"},
        ),
        patch.object(api_editor, "repository_dependency_names", return_value=[]),
        patch.object(
            api_editor,
            "prepare_project_github_package",
            return_value={"manifest": {}, "manifest_path": ""},
        ) as prepare,
        patch.object(
            api_editor, "repository_publish_files", return_value={"files": {}}
        ),
        patch.object(
            api_editor,
            "build_github_package_snapshot",
            return_value=snapshot("question: Old source\n"),
        ),
    ):
        client = api_editor.app.test_client()
        response = client.post(
            "/al/editor/api/weaver/readiness",
            json={"project": "test", "filename": "main.yml", "raw_yaml": SOURCE},
        )
        assert response.status_code == 200, response.get_json()
        assert (
            response.get_json()["data"]["working_source_sha256"]
            == hashlib.sha256(SOURCE.encode()).hexdigest()
        )
        assert prepare.call_args.kwargs["persist_manifest"] is False
        assert (
            client.post(
                "/al/editor/api/weaver/readiness", json={"review_level": "unknown"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/al/editor/api/weaver/readiness",
                json={"project": "missing", "filename": "main.yml", "raw_yaml": SOURCE},
            ).status_code
            == 400
        )


def test_readiness_api_remote_review_is_explicit_and_queued():
    from .test_editor_api import api_editor

    payload = {
        "project": "test",
        "filename": "main.yml",
        "raw_yaml": SOURCE,
        "include_llm": True,
        "review_level": "thorough",
        "model": "deployment-name",
    }
    with (
        patch.object(api_editor, "_editor_auth_check", return_value=True),
        patch.object(api_editor, "_current_user_id", return_value=7),
        patch.object(api_editor, "_repository_config_package", return_value="Test"),
        patch.object(
            api_editor,
            "_editor_playground_context",
            return_value={"name": "Tester", "email": "test@example.com"},
        ),
        patch.object(
            api_editor,
            "_queue_ai_job",
            return_value=api_editor.app.response_class("{}", status=202),
        ) as queue,
        patch.object(api_editor, "_readiness_check_result") as check_result,
    ):
        response = api_editor.app.test_client().post(
            "/al/editor/api/weaver/readiness", json=payload
        )
        assert response.status_code == 202
        assert queue.call_args.args[:2] == ("readiness-check", 7)
        queued = queue.call_args.args[2]
        assert all(queued[key] == value for key, value in payload.items())
        assert queued["_readiness_owner"] == {
            "name": "Tester",
            "email": "test@example.com",
        }
        assert queued["_readiness_package"] == "Test"
        check_result.assert_not_called()


def test_readiness_routes_require_auth_and_reject_stale_repair_context():
    from .test_editor_api import api_editor

    with patch.object(api_editor, "_editor_auth_check", return_value=False):
        assert (
            api_editor.app.test_client()
            .post("/al/editor/api/weaver/readiness", json={})
            .status_code
            == 401
        )
    with patch.object(api_editor, "_editor_auth_check", return_value=True):
        response = api_editor.app.test_client().post(
            "/al/editor/api/weaver/readiness/repair-context",
            json={"raw_yaml": SOURCE, "finding": {"rendered_jinja": True}},
        )
        assert response.status_code == 409


def test_readiness_worker_uses_captured_identity_without_a_logged_in_user():
    from .test_editor_api import api_editor

    payload = {
        "project": "test",
        "filename": "main.yml",
        "raw_yaml": SOURCE,
        "_readiness_package": "Test",
        "_readiness_owner": {"name": "Tester", "email": "test@example.com"},
    }
    with (
        patch.object(
            api_editor,
            "_current_user_id",
            side_effect=AssertionError("No request identity in Celery"),
        ),
        patch.object(
            api_editor,
            "_editor_playground_context",
            side_effect=AssertionError("No request context in Celery"),
        ),
        patch.object(api_editor, "playground_list_projects", return_value=["test"]),
        patch.object(api_editor, "repository_dependency_names", return_value=[]),
        patch.object(
            api_editor,
            "prepare_project_github_package",
            return_value={"manifest": {}, "manifest_path": ""},
        ),
        patch.object(
            api_editor, "repository_publish_files", return_value={"files": {}}
        ),
        patch.object(
            api_editor, "build_github_package_snapshot", return_value=snapshot()
        ),
    ):
        report = api_editor._readiness_check_result(7, payload)
    assert (
        report["working_source_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    )


def test_failed_ai_review_cannot_produce_a_clean_report():
    report = {
        "status": "pass",
        "checks": [],
        "findings": [
            {
                "message_id": "style_llm_request_failed",
                "severity": "warning",
                "message": "Provider unavailable",
            }
        ],
    }
    with patch("dayamlchecker.readiness.publication_readiness", return_value=report):
        result = check(include_llm=True)
    assert result["status"] == "needs_review"
    assert result["checks"][-1]["id"] == "ai_style_review"
    assert result["checks"][-1]["status"] == "needs_review"
