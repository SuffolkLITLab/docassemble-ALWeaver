# do not pre-load

"""Confirmed, optimistic-concurrency replacement for binary templates."""

import hashlib
import io
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pypdf import PdfWriter

from .api_utils import validate_document_content
from .test_editor_api import api_editor


def _pdf_bytes(title):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": title})
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


class TestTemplateRevisionUpload(unittest.TestCase):
    original = _pdf_bytes("Original template")
    replacement = _pdf_bytes("Revised template")

    def _post(
        self,
        *,
        expected_revision=None,
        filename="petition.pdf",
        incoming_name=None,
        finalizer=None,
        confirm_replace=True,
        replacement=None,
    ):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.last_directory = directory.name
        path = os.path.join(directory.name, filename)
        with open(path, "wb") as handle:
            handle.write(self.original)
        area = SimpleNamespace(finalize=finalizer or Mock())
        form = {
            "project": "default",
            "filename": filename,
            "confirm_replace": "true" if confirm_replace else "false",
        }
        if expected_revision is not None:
            form["expected_revision"] = expected_revision
        form["file"] = (
            io.BytesIO(self.replacement if replacement is None else replacement),
            incoming_name or filename,
        )
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(
                api_editor,
                "validate_document_content",
                side_effect=validate_document_content,
            ),
            patch.object(api_editor, "_current_user_id", return_value=17),
            patch.object(
                api_editor,
                "_editor_storage_directory",
                return_value=(area, directory.name),
            ),
            patch.object(api_editor, "_source_file_lock", return_value=nullcontext()),
            api_editor.app.test_request_context(
                "/al/editor/api/template/revise",
                method="POST",
                data=form,
                content_type="multipart/form-data",
            ),
        ):
            response = api_editor.editor_api_revise_template()
        with open(path, "rb") as handle:
            final_bytes = handle.read()
        return response, final_bytes, area

    def test_matching_sha_replaces_bytes_and_returns_new_revision(self):
        response, final_bytes, area = self._post(
            expected_revision=hashlib.sha256(self.original).hexdigest()
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(final_bytes, self.replacement)
        result = response.get_json()["data"]
        self.assertEqual(
            result["original_revision"], hashlib.sha256(self.original).hexdigest()
        )
        self.assertEqual(
            result["revision"], hashlib.sha256(self.replacement).hexdigest()
        )
        backup_path = os.path.join(self.last_directory, result["backup_filename"])
        with open(backup_path, "rb") as handle:
            self.assertEqual(handle.read(), self.original)
        self.assertEqual(
            result["backup_revision"], hashlib.sha256(self.original).hexdigest()
        )
        area.finalize.assert_called_once()

    def test_template_file_list_exposes_binary_revision_for_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "petition.pdf"), "wb") as handle:
                handle.write(self.original)
            with patch.object(
                api_editor,
                "_editor_storage_directory",
                return_value=(SimpleNamespace(finalize=Mock()), directory),
            ):
                files = api_editor._list_editor_section_files(
                    17, "default", "templates"
                )

        self.assertEqual(len(files), 1)
        self.assertEqual(
            files[0]["revision"], hashlib.sha256(self.original).hexdigest()
        )

    def test_stale_sha_rejects_without_mutating_or_finalizing(self):
        response, final_bytes, area = self._post(expected_revision="0" * 64)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "revision_conflict")
        self.assertEqual(final_bytes, self.original)
        area.finalize.assert_not_called()

    def test_missing_sha_rejects_without_mutating(self):
        response, final_bytes, area = self._post()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(final_bytes, self.original)
        area.finalize.assert_not_called()

    def test_replacement_requires_explicit_confirmation(self):
        response, final_bytes, area = self._post(
            expected_revision=hashlib.sha256(self.original).hexdigest(),
            confirm_replace=False,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(final_bytes, self.original)
        area.finalize.assert_not_called()

    def test_oversized_replacement_is_rejected_without_mutating(self):
        with patch.object(api_editor, "MAX_TEMPLATE_REPLACEMENT_BYTES", 100):
            response, final_bytes, area = self._post(
                expected_revision=hashlib.sha256(self.original).hexdigest(),
                replacement=b"x" * 101,
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["error"]["code"], "file_too_large")
        self.assertEqual(final_bytes, self.original)
        area.finalize.assert_not_called()

    def test_malformed_replacement_is_rejected_before_backup_or_mutation(self):
        response, final_bytes, area = self._post(
            expected_revision=hashlib.sha256(self.original).hexdigest(),
            replacement=b"not a PDF",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "PDF file is unreadable or malformed",
            response.get_json()["error"]["message"],
        )
        self.assertEqual(final_bytes, self.original)
        self.assertEqual(os.listdir(self.last_directory), ["petition.pdf"])
        area.finalize.assert_not_called()

    def test_malformed_docx_replacement_is_rejected_before_backup_or_mutation(self):
        response, final_bytes, area = self._post(
            expected_revision=hashlib.sha256(self.original).hexdigest(),
            filename="petition.docx",
            replacement=b"not a DOCX archive",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "DOCX file is malformed or incomplete",
            response.get_json()["error"]["message"],
        )
        self.assertEqual(final_bytes, self.original)
        self.assertEqual(os.listdir(self.last_directory), ["petition.docx"])
        area.finalize.assert_not_called()

    def test_valid_docx_replacement_is_accepted(self):
        replacement = (
            Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        ).read_bytes()
        response, final_bytes, area = self._post(
            expected_revision=hashlib.sha256(self.original).hexdigest(),
            filename="petition.docx",
            replacement=replacement,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(final_bytes, replacement)
        area.finalize.assert_called_once()

    def test_oversized_existing_template_is_rejected_without_reading(self):
        with (
            patch.object(api_editor, "MAX_TEMPLATE_REPLACEMENT_BYTES", 100),
            patch.object(api_editor.os.path, "getsize", return_value=101),
        ):
            response, final_bytes, area = self._post(
                expected_revision=hashlib.sha256(self.original).hexdigest()
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["error"]["code"], "file_too_large")
        self.assertEqual(final_bytes, self.original)
        area.finalize.assert_not_called()

    def test_filename_mismatch_and_non_template_extension_are_rejected(self):
        mismatch, unchanged, area = self._post(
            expected_revision=hashlib.sha256(self.original).hexdigest(),
            incoming_name="other.pdf",
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(unchanged, self.original)
        area.finalize.assert_not_called()

        wrong_extension, unchanged, area = self._post(
            expected_revision=hashlib.sha256(self.original).hexdigest(),
            filename="helper.py",
        )
        self.assertEqual(wrong_extension.status_code, 400)
        self.assertEqual(unchanged, self.original)
        area.finalize.assert_not_called()

    def test_finalize_failure_restores_original_bytes(self):
        finalize = Mock(side_effect=[RuntimeError("storage finalize failure"), None])
        response, final_bytes, area = self._post(
            expected_revision=hashlib.sha256(self.original).hexdigest(),
            finalizer=finalize,
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(final_bytes, self.original)
        self.assertEqual(area.finalize.call_count, 2)
        self.assertEqual(os.listdir(self.last_directory), ["petition.pdf"])

    def test_second_writer_with_stale_sha_cannot_overwrite_first(self):
        expected = hashlib.sha256(self.original).hexdigest()
        first, first_bytes, _area = self._post(expected_revision=expected)
        self.assertEqual(first.status_code, 200)

        # A fresh endpoint call whose current bytes no longer match the original
        # revision must be refused, even when the client retries the same hash.
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "petition.pdf")
            with open(path, "wb") as handle:
                handle.write(first_bytes)
            area = SimpleNamespace(finalize=Mock())
            form = {
                "project": "default",
                "filename": "petition.pdf",
                "expected_revision": expected,
                "confirm_replace": "true",
                "file": (io.BytesIO(b"third revision"), "petition.pdf"),
            }
            with (
                patch.object(api_editor, "_editor_auth_check", return_value=True),
                patch.object(api_editor, "_current_user_id", return_value=17),
                patch.object(
                    api_editor,
                    "_editor_storage_directory",
                    return_value=(area, directory),
                ),
                patch.object(
                    api_editor, "_source_file_lock", return_value=nullcontext()
                ),
                api_editor.app.test_request_context(
                    "/al/editor/api/template/revise",
                    method="POST",
                    data=form,
                    content_type="multipart/form-data",
                ),
            ):
                second = api_editor.editor_api_revise_template()
            with open(path, "rb") as handle:
                second_bytes = handle.read()

        self.assertEqual(second.status_code, 409)
        self.assertEqual(second_bytes, self.replacement)
        area.finalize.assert_not_called()
