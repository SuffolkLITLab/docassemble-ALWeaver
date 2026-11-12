# do not pre-load
import base64
import io
from unittest.mock import patch

import pandas as pd
import pytest

from . import editor_translations
from .editor_translations import (
    add_translation_reference,
    language_code,
    localize_report,
)


def test_reference_preserves_source_and_is_idempotent():
    source = '# A comment\n---\nquestion: "Your name" # keep quotes\nfields:\n  - Name: user_name\n'
    result = add_translation_reference(source, "reviewed_es.xlsx")
    assert result.startswith(source)
    assert result.endswith("translations:\n  - reviewed_es.xlsx\n")
    assert add_translation_reference(result, "reviewed_es.xlsx") == result


@pytest.mark.parametrize("value", ["", "../es", "es\ncode: evil", "<script>"])
def test_language_rejects_invalid_codes(value):
    with pytest.raises(ValueError):
        language_code(value)


def test_report_reuses_dashboard_and_keeps_variables_and_values():
    rows = [
        ["demo", "name", 0, "hash", "en", "es", a, b]
        for a, b in [
            ("Your name", "Su nombre"),
            ("Name", "Nombre"),
            ("Yes", "Sí"),
            ("Case", "Caso"),
        ]
    ]
    output = io.BytesIO()
    pd.DataFrame(
        rows,
        columns=[
            "interview",
            "question_id",
            "index_num",
            "hash",
            "orig_lang",
            "tr_lang",
            "orig_text",
            "tr_text",
        ],
    ).to_excel(output, index=False)
    workbook = {
        "translations": [
            {
                "xlsx_base64": base64.b64encode(output.getvalue()).decode(),
                "untranslated_segments": 1,
            }
        ]
    }
    scan = {
        "blocks": [
            {
                "id": "name",
                "sourceFile": "main.yml",
                "data": {
                    "question": "Your name",
                    "fields": [{"Name": "person_name", "choices": [{"Yes": "yes"}]}],
                    "code": 'Name = "Case"',
                },
            }
        ],
        "warnings": [],
    }
    with patch.object(
        editor_translations, "dashboard_translation", return_value=workbook
    ) as translate:
        result = localize_report(scan, "demo:main.yml", "es")
    translate.assert_called_once_with("demo:main.yml", "es")
    data = result["blocks"][0]["data"]
    assert data["question"] == "Su nombre"
    assert data["fields"] == [{"Nombre": "person_name", "choices": [{"Sí": "yes"}]}]
    assert data["code"] == 'Name = "Case"'
    assert scan["blocks"][0]["data"]["question"] == "Your name"
    assert result["language"] == "es"
    assert "untranslated" in result["warnings"][0]


def test_report_prefers_language_specific_screen():
    output = io.BytesIO()
    pd.DataFrame(
        columns=[
            "interview",
            "question_id",
            "index_num",
            "hash",
            "orig_lang",
            "tr_lang",
            "orig_text",
            "tr_text",
        ]
    ).to_excel(output, index=False)
    workbook = {
        "translations": [{"xlsx_base64": base64.b64encode(output.getvalue()).decode()}]
    }
    blocks = [
        {"defines": ["name"], "data": {"language": lang, "question": title}}
        for lang, title in [("en", "Name"), ("es", "Nombre"), ("fr", "Nom")]
    ]
    with patch.object(
        editor_translations, "dashboard_translation", return_value=workbook
    ):
        result = localize_report(
            {"blocks": blocks, "warnings": []}, "demo:main.yml", "es"
        )
    assert [b["data"]["question"] for b in result["blocks"]] == ["Nombre"]


@pytest.mark.parametrize(
    "selection, expected",
    [
        ({"language": "es"}, ["es"]),
        ({"tr_langs": ["es", "fr", "es"]}, ["es", "fr"]),
        ({"languages": "es\nfr"}, ["es", "fr"]),
    ],
)
def test_generation_queues_only_owned_interview_and_supported_options(
    selection, expected
):
    from .test_editor_api import api_editor
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(api_editor, "_editor_auth_check", return_value=True)
        )
        stack.enter_context(
            patch.object(api_editor, "_current_user_id", return_value=7)
        )
        read = stack.enter_context(
            patch.object(api_editor, "playground_read_yaml", return_value="")
        )
        queue = stack.enter_context(
            patch.object(
                api_editor, "_queue_report_job", return_value={"success": True}
            )
        )
        response = api_editor.app.test_client().post(
            "/al/editor/api/translations/generate",
            json={
                "project": "default",
                "filename": "main.yml",
                **selection,
                "use_gpt": True,
                "interview_path": "/etc/passwd",
                "openai_base_url": "https://untrusted.invalid",
            },
        )
        assert response.status_code == 200
        read.assert_called_once_with(7, "default", "main.yml")
        args = queue.call_args.args
        assert args[:2] == (7, "translation")
        assert args[2] == {
            "project": "default",
            "filename": "main.yml",
            "tr_langs": expected,
            "use_gpt": True,
        }


def test_import_requires_revision_before_validating_or_writing():
    from .test_editor_api import api_editor
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(api_editor, "_editor_auth_check", return_value=True)
        )
        stack.enter_context(
            patch.object(api_editor, "_current_user_id", return_value=7)
        )
        stack.enter_context(
            patch.object(
                api_editor, "playground_read_yaml", return_value="question: Hello\n"
            )
        )
        storage = stack.enter_context(
            patch.object(api_editor, "_editor_storage_directory")
        )
        response = api_editor.app.test_client().post(
            "/al/editor/api/translations/import",
            json={"project": "default", "filename": "main.yml", "content": "invalid"},
        )
        assert response.status_code == 400
        storage.assert_not_called()


@pytest.mark.parametrize("value", ["es\nfr es", ["es", "fr", "es"]])
def test_language_codes_preserve_order_and_deduplicate(value):
    assert editor_translations.language_codes(value) == ["es", "fr"]


@pytest.mark.parametrize("value", [[], " ", ["es", "bad/language"], ["es", None]])
def test_language_codes_reject_bad_lists(value):
    with pytest.raises(ValueError):
        editor_translations.language_codes(value)


def test_multiple_languages_delegate_once_to_dashboard():
    import sys
    import types
    from unittest.mock import Mock
    from docassemble.base import functions

    dashboard = types.ModuleType("docassemble.ALDashboard.api_dashboard_utils")
    dashboard.translation_payload_from_options = Mock(return_value={"translations": []})
    with patch.dict(sys.modules, {dashboard.__name__: dashboard}), patch.object(
        functions, "get_uid", return_value="session"
    ), patch.object(functions, "set_uid"):
        editor_translations.dashboard_translation(
            "docassemble.playground7:main.yml", ["es", "fr"], True
        )
    dashboard.translation_payload_from_options.assert_called_once_with(
        {
            "interview_path": "docassemble.playground7:main.yml",
            "tr_langs": ["es", "fr"],
            "use_gpt": True,
            "include_xlsx_base64": True,
        }
    )


def test_multi_language_result_is_one_archive_with_all_workbooks():
    import importlib
    from zipfile import ZipFile
    from .test_editor_api import api_editor

    adapter = importlib.import_module(api_editor.__package__ + ".editor_translations")
    translations = [
        {
            "language": language,
            "xlsx_base64": base64.b64encode(content).decode(),
            "untranslated_segments": 2,
        }
        for language, content in [
            ("es", b"spanish workbook"),
            ("fr", b"french workbook"),
        ]
    ]
    with patch.object(
        api_editor, "playground_read_yaml", return_value=""
    ), patch.object(
        adapter, "dashboard_translation", return_value={"translations": translations}
    ) as generate:
        result = api_editor._translation_result(
            7, {"project": "default", "filename": "main.yml", "tr_langs": ["es", "fr"]}
        )
    generate.assert_called_once_with(
        "docassemble.playground7:main.yml", ["es", "fr"], False
    )
    with ZipFile(io.BytesIO(base64.b64decode(result["archive_base64"]))) as archive:
        assert archive.namelist() == ["main_es.xlsx", "main_fr.xlsx"]
        assert archive.read("main_es.xlsx") == b"spanish workbook"
        assert archive.read("main_fr.xlsx") == b"french workbook"
    assert result["archive_filename"] == "main_translations.zip"
    assert [item["language"] for item in result["translations"]] == ["es", "fr"]
    assert all("xlsx_base64" not in item for item in result["translations"])


def test_single_language_result_remains_a_workbook():
    import importlib
    from .test_editor_api import api_editor

    adapter = importlib.import_module(api_editor.__package__ + ".editor_translations")
    expected = {"translations": [{"language": "es", "xlsx_base64": "ZXM="}]}
    with patch.object(
        api_editor, "playground_read_yaml", return_value=""
    ), patch.object(adapter, "dashboard_translation", return_value=expected):
        result = api_editor._translation_result(
            7, {"project": "default", "filename": "main.yml", "language": "es"}
        )
    assert result == expected
    assert "archive_base64" not in result


def test_scope_names_owned_root_and_its_revision_for_import():
    from contextlib import ExitStack
    from .test_editor_api import api_editor

    source = "include:\n  - details.yml\n"
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(api_editor, "_editor_auth_check", return_value=True)
        )
        stack.enter_context(
            patch.object(api_editor, "_current_user_id", return_value=7)
        )
        resolve = stack.enter_context(
            patch.object(api_editor, "_report_entrypoint", return_value="main.yml")
        )
        read = stack.enter_context(
            patch.object(api_editor, "playground_read_yaml", return_value=source)
        )
        response = api_editor.app.test_client().post(
            "/al/editor/api/translations/scope",
            json={"project": "default", "filename": "details.yml"},
        )
        assert response.status_code == 200
        assert response.json["data"] == {
            "project": "default",
            "filename": "main.yml",
            "expected_revision": api_editor.source_revision(source),
        }
        resolve.assert_called_once_with(7, "default", "details.yml")
        read.assert_called_once_with(7, "default", "main.yml")
