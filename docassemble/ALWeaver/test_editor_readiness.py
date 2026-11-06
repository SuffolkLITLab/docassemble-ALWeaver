# do not pre-load

import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

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
    kwargs.setdefault("include_research", False)
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
        include_research=False,
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
            json={
                "project": "test",
                "filename": "main.yml",
                "raw_yaml": SOURCE,
                "include_research": False,
            },
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
                json={
                    "project": "missing",
                    "filename": "main.yml",
                    "raw_yaml": SOURCE,
                    "include_research": False,
                },
            ).status_code
            == 400
        )


@pytest.mark.parametrize(
    "mode",
    [
        {},
        {"include_research": True, "ai_second_opinion": False},
        {"include_research": False, "ai_second_opinion": True},
    ],
)
def test_readiness_api_research_defaults_on_and_ai_stages_are_queued(mode):
    from .test_editor_api import api_editor

    payload = {
        "project": "test",
        "filename": "main.yml",
        "raw_yaml": SOURCE,
        **mode,
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
        "include_research": False,
        "_readiness_package": "Test",
        "_readiness_owner": {"name": "Tester", "email": "test@example.com"},
    }
    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(
            api_editor,
            "_daconfig",
            return_value={
                "open ai": {
                    "key": "test-secret",
                    "base url": "https://provider.example/v1",
                    "model": "server-model",
                },
                "assembly line": {"weaver llm model": "weaver-model"},
            },
        ),
        patch(
            f"{api_editor.__package__}.editor_readiness.check_package_snapshot",
            wraps=check_package_snapshot,
        ) as run,
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
        assert run.call_args.kwargs["openai_api_key"] == "test-secret"
        assert run.call_args.kwargs["openai_base_url"] == "https://provider.example/v1"
        assert run.call_args.kwargs["model"] == "weaver-model"
        api_editor._readiness_check_result(
            7, dict(payload, model="selected-deployment")
        )
        assert run.call_args.kwargs["model"] == "selected-deployment"
        assert "test-secret" not in json.dumps(report)
        assert "test-secret" not in json.dumps(payload)
    assert (
        report["working_source_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    )


def test_failed_second_opinion_preserves_local_findings():
    with patch(
        "dayamlchecker.readiness_ai_review.review_candidates",
        return_value={"execution_status": "failed"},
    ):
        result = check(ai_second_opinion=True)
    assert result["ai_review"]["execution_status"] == "failed"
    assert result["review"]["actionable"]
    assert result["findings"] == check()["findings"]


def test_repair_context_accepts_crlf_and_cr_source_with_normalized_checker_blocks():
    docs, _ = parse_interview_documents(SOURCE)
    block = docs[1]
    finding = {
        "context": {
            "repair_context": {
                "schema_version": 1,
                "block_index": block.index,
                "source_yaml": block.source_code,
                "source_sha256": hashlib.sha256(block.source_code.encode()).hexdigest(),
            }
        }
    }
    assert repair_context_current(SOURCE.replace("\n", "\r\n"), finding)
    assert repair_context_current(SOURCE.replace("\n", "\r"), finding)


def test_second_opinion_timeout_retains_local_report_and_server_configuration():
    from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]

    with patch(
        "dayamlchecker.readiness_ai_review.review_candidates",
        side_effect=SoftTimeLimitExceeded(),
    ) as run:
        result = check(
            ai_second_opinion=True,
            model="deployment",
            openai_api_key="test-secret",
            openai_base_url="https://provider.example/v1",
        )
    options = run.call_args.args[2]
    assert options.model == "deployment"
    assert options.timeout == 480
    assert options.api_key == "test-secret"
    assert options.base_url == "https://provider.example/v1"
    assert result["review"]["actionable"]
    assert result["ai_review"]["execution_status"] == "failed"
    assert "timed out" in result["ai_review"]["error"]
    assert "test-secret" not in json.dumps(result)


def test_readiness_disables_style_and_applies_second_opinion():
    from dayamlchecker.readiness import publication_readiness

    with (
        patch(
            "dayamlchecker.readiness.publication_readiness", wraps=publication_readiness
        ) as run,
        patch(
            "dayamlchecker.readiness_ai_review.review_candidates",
            return_value={"execution_status": "not_needed"},
        ),
        patch("dayamlchecker.readiness_ai_review.apply_ai_review") as apply,
    ):
        check(ai_second_opinion=True)
    assert run.call_count == 1
    assert run.call_args.kwargs["style_options"].style_enabled is False
    assert run.call_args.kwargs["style_options"].style_include_llm is False
    apply.assert_called_once()


def test_repeated_block_source_is_deduplicated_only_in_model_payload():
    context = {"repair_context": {"source_yaml": SOURCE, "source_sha256": "same-block"}}
    diagnostic = {"context": context}
    result = AgentToolResult(
        "validate", "success", diagnostics=[diagnostic, diagnostic]
    )
    model = result.model_dict()["diagnostics"]
    assert model[0]["context"]["repair_context"]["source_yaml"] == SOURCE
    assert "source_yaml" not in model[1]["context"]["repair_context"]
    assert (
        model[1]["context"]["repair_context"]["source_yaml_reference_sha256"]
        == "same-block"
    )
    assert result.diagnostics[1]["context"]["repair_context"]["source_yaml"] == SOURCE


def test_real_jinja_findings_keep_rendered_location_without_original_offsets():
    source = "# use jinja\n{% if True %}\ncode: |\n  this is not python!\n{% endif %}\n"
    findings = dayamlchecker_findings(source, "main.yml")
    assert findings
    for finding in findings:
        assert finding["rendered_jinja"] is True
        assert finding["rendered_line_number"] is not None
        assert finding["line_number"] is None
        assert finding["source_range"] is None


def test_author_report_demotes_missing_ids_and_explains_delivery_errors():
    from .editor_readiness import author_review

    report = {
        "findings": [
            {"message_id": "missing_question_id"},
            {"message_id": "yaml_duplicate_block_id"},
        ],
        "review": {
            "actionable": [
                {
                    "source": "static",
                    "finding_indexes": [0],
                    "release_gate": True,
                    "priority": "high",
                },
                {
                    "source": "static",
                    "finding_indexes": [1],
                    "release_gate": True,
                    "priority": "high",
                },
                {
                    "source": "check",
                    "check_id": "document_delivery",
                    "release_gate": True,
                    "priority": "high",
                    "message": "Generic delivery summary",
                    "evidence": {
                        "errors": [
                            {
                                "file": "questions/main.yml",
                                "reference": "missing.pdf",
                                "detail": "Missing template",
                            },
                            {
                                "file": "questions/other.yml",
                                "reference": "other.docx",
                                "detail": "Missing template",
                            },
                        ]
                    },
                },
            ],
            "cleanup": [],
        },
    }
    original = copy.deepcopy(report)
    view = author_review(report)
    assert report == original
    assert len(view["actionable"]) == 3
    assert view["actionable"][0]["finding_indexes"] == [1]
    assert view["actionable"][1]["file"] == "questions/main.yml"
    assert "missing.pdf" in view["actionable"][1]["message"]
    assert "cannot be generated" in view["actionable"][1]["reason"]
    assert "other.docx" in view["actionable"][2]["message"]
    assert len(view["cleanup"]) == 1
    assert view["cleanup"][0]["release_gate"] is False


def test_author_report_groups_repeated_advice_without_losing_repair_indexes():
    from .editor_readiness import author_review

    report = {
        "review": {
            "actionable": [
                {
                    "source": "static",
                    "file": "main.yml",
                    "message": "Duplicate ID",
                    "line": line,
                    "finding_indexes": [index],
                }
                for index, line in enumerate([12, 20])
            ]
        },
        "findings": [{}, {}],
    }
    items = author_review(report)["actionable"]
    assert len(items) == 1
    assert items[0]["lines"] == [12, 20]
    assert items[0]["finding_indexes"] == [0, 1]


def test_research_runs_by_default_before_second_opinion_and_preserves_citations():
    research = {
        "status": "needs_review",
        "execution_status": "completed",
        "coverage_gaps": [],
        "findings": [
            {
                "file": QUESTION,
                "line_number": 5,
                "concern": "Check the filing instruction",
                "local_quote": "What is your name?",
                "source_urls": ["https://court.example/rules"],
                "source_explanation": "The instructions differ from the cited rule.",
            }
        ],
    }
    with (
        patch(
            "dayamlchecker.readiness_research.research_readiness", return_value=research
        ) as run,
        patch(
            "dayamlchecker.readiness_ai_review.review_candidates",
            return_value={"execution_status": "not_needed"},
        ) as second,
    ):
        result = check_package_snapshot(
            snapshot(),
            package="Test",
            filename="main.yml",
            raw_yaml=SOURCE,
            ai_second_opinion=True,
            model="server-model",
            openai_api_key="secret",
            openai_base_url="https://provider.example/v1",
        )
    options = run.call_args.args[1]
    assert options.model == "server-model"
    assert options.api_key == "secret"
    assert options.timeout == 480
    assert second.call_args.args[0]["research"] == research
    items = [
        item
        for item in result["author_review"]["actionable"]
        if item["source"] == "research"
    ]
    assert len(items) == 1
    assert items[0]["release_gate"] is False
    assert result["research"]["findings"][0]["source_urls"] == [
        "https://court.example/rules"
    ]
    assert "secret" not in json.dumps(result)


def test_research_opt_out_does_not_call_provider():
    with patch("dayamlchecker.readiness_research.research_readiness") as run:
        report = check(include_research=False)
    run.assert_not_called()
    assert report["research"] is None


def test_research_soft_timeout_preserves_local_report_and_skips_second_opinion():
    from billiard.exceptions import SoftTimeLimitExceeded

    with (
        patch(
            "dayamlchecker.readiness_research.research_readiness",
            side_effect=SoftTimeLimitExceeded,
        ),
        patch("dayamlchecker.readiness_ai_review.review_candidates") as second,
    ):
        report = check(include_research=True, ai_second_opinion=True)
    assert report["checks"]
    assert report["research"]["execution_status"] == "failed"
    assert report["ai_review"]["execution_status"] == "failed"
    assert report["review"]["coverage"]
    second.assert_not_called()


def test_author_metadata_identifies_actual_missing_fields():
    from .editor_readiness import author_review

    view = author_review(
        {
            "review": {
                "actionable": [
                    {
                        "check_id": "metadata",
                        "file": "main.yml",
                        "evidence": {"missing": ["jurisdiction", "before_you_start"]},
                    }
                ],
                "process_evidence": [{"id": "legal_review"}],
            }
        }
    )
    assert (
        view["actionable"][0]["message"]
        == "Add publication metadata: jurisdiction, before_you_start."
    )
    assert "process_evidence" not in view


def test_word_paragraph_tag_is_not_a_jinja_syntax_defect(tmp_path):
    from docx import Document
    from .editor_readiness import recheck_template_syntax

    path = tmp_path / "instructions.docx"
    doc = Document()
    doc.add_paragraph('{{p qr_code(help_url, width="1in") | markdown }}')
    doc.save(path)
    note = {
        "kind": "template_syntax_unverified",
        "detail": "Static extraction is incomplete",
    }
    report = {
        "root": str(tmp_path),
        "checks": [
            {
                "id": "document_templates",
                "status": "warning",
                "templates": [
                    {
                        "file": "instructions.docx",
                        "notes": [
                            note,
                            {"kind": "title", "detail": "Missing document title"},
                        ],
                    }
                ],
            }
        ],
        "findings": [],
        "local_scope": {},
    }
    recheck_template_syntax(report, tmp_path)
    template = report["checks"][0]["templates"][0]
    assert [n["kind"] for n in template["notes"]] == ["title"]
    assert "docxtpl" in template["syntax_recheck"]
    # A genuinely invalid expression must keep its warning.
    doc = Document()
    doc.add_paragraph("{{p qr_code( }}")
    doc.save(path)
    template["notes"] = [note]
    recheck_template_syntax(report, tmp_path)
    assert template["notes"] == [note]
