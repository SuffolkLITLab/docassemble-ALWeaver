# do not pre-load

"""Optimistic concurrency checks for interview source mutations."""

import unittest
import types
import hashlib
import os
import tempfile
import threading
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from .test_editor_api import api_editor


class TestEditorRevisionConflicts(unittest.TestCase):
    current = "---\nid: question\nquestion: Current title\n"

    def _post(self, handler, path, payload):
        write = patch.object(api_editor, "playground_write_yaml")
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=17),
            patch.object(api_editor, "playground_read_yaml", return_value=self.current),
            write as mock_write,
        ):
            with api_editor.app.test_request_context(path, method="POST", json=payload):
                response = handler()
        return response, mock_write

    def _assert_conflict(self, response, mock_write):
        self.assertEqual(response.status_code, 409)
        error = response.get_json()["error"]
        self.assertEqual(error["type"], "revision_conflict")
        self.assertEqual(error["code"], "revision_conflict")
        self.assertEqual(error["current_raw_yaml"], self.current)
        self.assertTrue(error["current_revision"])
        mock_write.assert_not_called()

    def test_stale_block_save_is_rejected_without_overwriting(self):
        with patch.object(
            api_editor,
            "update_block_in_yaml",
            side_effect=lambda content, *_args, **_kwargs: content + "\n# candidate",
        ):
            response, mock_write = self._post(
                api_editor.editor_api_save_block,
                "/al/editor/api/block",
                {
                    "project": "default",
                    "filename": "main.yml",
                    "block_id": "question",
                    "block_yaml": "id: question\nquestion: Stale title\n",
                    "expected_revision": "stale-revision",
                },
            )
        self._assert_conflict(response, mock_write)

    def test_stale_order_save_is_rejected_without_overwriting(self):
        with patch.object(
            api_editor,
            "parse_interview_yaml",
            return_value={"blocks": [], "order_blocks": []},
        ):
            response, mock_write = self._post(
                api_editor.editor_api_save_order,
                "/al/editor/api/order",
                {
                    "project": "default",
                    "filename": "main.yml",
                    "steps": [{"kind": "screen", "invoke": "stale_screen"}],
                    "expected_revision": "stale-revision",
                },
            )
        self._assert_conflict(response, mock_write)

    def test_stale_full_source_save_is_rejected_without_overwriting(self):
        response, mock_write = self._post(
            api_editor.editor_api_save_file,
            "/al/editor/api/file",
            {
                "project": "default",
                "filename": "main.yml",
                "content": "---\nid: question\nquestion: Stale full source\n",
                "expected_revision": "stale-revision",
            },
        )
        self._assert_conflict(response, mock_write)

    def test_stale_metadata_save_preserves_competing_source_bytes(self):
        from . import editor_utils as real_utils

        original = (
            "# starting version\r\n"
            "metadata:\r\n"
            "  title: Original\r\n"
            "---\r\n"
            "id: question\r\n"
            "question: Current title\r\n"
        )
        competing = (
            "# concurrent editor update\r\n"
            "metadata:\r\n"
            "  title: Teammate's title\r\n"
            "---\r\n"
            "id: question\r\n"
            "question: Current title\r\n"
        )
        self.current = competing
        with (
            patch.object(
                api_editor,
                "update_metadata_documents_in_yaml",
                return_value=original.replace("Original", "Stale edit"),
            ),
            patch.object(
                api_editor,
                "source_revision",
                side_effect=real_utils.source_revision,
            ),
        ):
            response, mock_write = self._post(
                api_editor.editor_api_save_metadata,
                "/al/editor/api/file/metadata",
                {
                    "project": "default",
                    "filename": "main.yml",
                    "raw_yaml": "metadata:\r\n  title: Stale edit\r\n",
                    "expected_revision": real_utils.source_revision(original),
                },
            )

        self._assert_conflict(response, mock_write)
        self.assertEqual(response.get_json()["error"]["current_raw_yaml"], competing)

    def test_structural_interview_mutators_reject_stale_revisions(self):
        operations = (
            (
                api_editor.editor_api_delete_block,
                "/al/editor/api/block/delete",
                {"block_id": "question"},
                "delete_block_from_yaml",
            ),
            (
                api_editor.editor_api_comment_block,
                "/al/editor/api/block/comment",
                {"block_id": "question"},
                "comment_out_block_in_yaml",
            ),
            (
                api_editor.editor_api_enable_block,
                "/al/editor/api/block/enable",
                {"block_id": "question"},
                "enable_commented_block_in_yaml",
            ),
            (
                api_editor.editor_api_reorder_blocks,
                "/al/editor/api/block/reorder",
                {"block_ids": ["question"]},
                "reorder_blocks_in_yaml",
            ),
            (
                api_editor.editor_api_insert_block,
                "/al/editor/api/insert-block",
                {
                    "insert_after_id": "question",
                    "block_yaml": "id: added\nquestion: Added\n",
                },
                "insert_block_in_yaml",
            ),
            (
                api_editor.editor_api_question_library_insert,
                "/al/editor/api/question-library/insert",
                {"questions": [{"var": "people", "kind": "basic"}]},
                "insert_block_in_yaml",
            ),
            (
                api_editor.editor_api_question_library_object,
                "/al/editor/api/question-library/object",
                {"name": "people", "class_name": "ALPeopleList"},
                "insert_block_in_yaml",
            ),
        )
        for handler, path, extra, mutator in operations:
            with self.subTest(path=path):
                payload = {
                    "project": "default",
                    "filename": "main.yml",
                    "expected_revision": "stale-revision",
                    **extra,
                }
                with ExitStack() as patches:
                    patches.enter_context(
                        patch.object(
                            api_editor,
                            mutator,
                            side_effect=lambda content, *_args, **_kwargs: content
                            + "\n# candidate",
                        )
                    )
                    if path == "/al/editor/api/question-library/insert":
                        patches.enter_context(
                            patch.object(
                                api_editor,
                                "_question_library_catalog",
                                return_value=[
                                    {
                                        "var": "people",
                                        "questions": [
                                            {
                                                "kind": "basic",
                                                "question_id": "people_name",
                                                "present": False,
                                                "yaml": "id: people_name\nquestion: Name\n",
                                            }
                                        ],
                                    }
                                ],
                            )
                        )
                    response, mock_write = self._post(handler, path, payload)
                self._assert_conflict(response, mock_write)

    def test_legacy_full_source_save_without_revision_still_works(self):
        content = "---\nid: question\nquestion: Legacy client\n"
        response, mock_write = self._post(
            api_editor.editor_api_save_file,
            "/al/editor/api/file",
            {
                "project": "default",
                "filename": "main.yml",
                "content": content,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["data"]["revision"],
            api_editor.source_revision(content),
        )
        mock_write.assert_called_once_with(17, "default", "main.yml", content)

    def test_revision_is_rechecked_at_commit_after_candidate_was_built(self):
        current = self.current
        changed = "---\nid: question\nquestion: Saved by another editor\n"
        with (
            patch.object(api_editor, "playground_read_yaml", return_value=changed),
            patch.object(api_editor, "playground_write_yaml") as mock_write,
            patch.object(api_editor, "source_revision", side_effect=lambda text: text),
        ):
            with api_editor.app.test_request_context("/al/editor/api/file"):
                response = api_editor._write_source_content(
                    17,
                    "default",
                    "main.yml",
                    "---\nid: question\nquestion: My candidate\n",
                    {"expected_revision": current},
                    "request-123",
                )
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["current_raw_yaml"], changed)
        mock_write.assert_not_called()

    def test_identical_stale_candidate_is_acknowledged_without_rewriting(self):
        already_committed = "---\nid: question\nquestion: Saved response\n"
        with (
            patch.object(
                api_editor, "playground_read_yaml", return_value=already_committed
            ),
            patch.object(api_editor, "playground_write_yaml") as mock_write,
            patch.object(api_editor, "source_revision", side_effect=lambda text: text),
        ):
            with api_editor.app.test_request_context("/al/editor/api/file"):
                result = api_editor._write_source_content(
                    17,
                    "default",
                    "main.yml",
                    already_committed,
                    {"expected_revision": "old-revision"},
                    "request-123",
                )
        self.assertIsNone(result)
        mock_write.assert_not_called()

    def test_missing_shared_lock_fails_closed_outside_test_mode(self):
        original_testing = api_editor.app.testing
        api_editor.app.testing = False
        try:
            with (
                patch.object(api_editor, "r", types.SimpleNamespace()),
                patch.object(api_editor, "playground_read_yaml") as mock_read,
                patch.object(api_editor, "playground_write_yaml") as mock_write,
            ):
                with api_editor.app.test_request_context("/al/editor/api/file"):
                    response = api_editor._write_source_content(
                        17,
                        "default",
                        "main.yml",
                        self.current,
                        {"expected_revision": "any"},
                        "request-123",
                    )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.get_json()["error"]["code"], "source_lock_unavailable"
            )
            mock_read.assert_not_called()
            mock_write.assert_not_called()
        finally:
            api_editor.app.testing = original_testing

    def test_two_same_revision_writes_serialize_and_reject_the_loser(self):
        original_testing = api_editor.app.testing
        api_editor.app.testing = True
        store = {"content": self.current}
        outcomes = []
        ready = threading.Barrier(2)

        def revision(text):
            return hashlib.sha256(text.encode("utf-8")).hexdigest()

        def write(candidate):
            ready.wait(timeout=5)
            with api_editor.app.test_request_context("/al/editor/api/file"):
                outcomes.append(
                    api_editor._write_source_content(
                        17,
                        "default",
                        "main.yml",
                        candidate,
                        {"expected_revision": revision(self.current)},
                        "request-123",
                    )
                )

        candidates = [
            "---\nid: question\nquestion: Editor A\n",
            "---\nid: question\nquestion: Editor B\n",
        ]
        original_read = api_editor.playground_read_yaml
        original_write = api_editor.playground_write_yaml
        original_revision = api_editor.source_revision
        api_editor.playground_read_yaml = lambda *_args: store["content"]
        api_editor.playground_write_yaml = lambda *_args: store.update(
            content=_args[-1]
        )
        api_editor.source_revision = revision
        threads = [
            threading.Thread(target=write, args=(candidate,))
            for candidate in candidates
        ]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        finally:
            api_editor.playground_read_yaml = original_read
            api_editor.playground_write_yaml = original_write
            api_editor.source_revision = original_revision
            api_editor.app.testing = original_testing

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(sum(result is None for result in outcomes), 1)
        conflicts = [result for result in outcomes if result is not None]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].status_code, 409)
        self.assertIn(store["content"], candidates)

    def test_secondary_section_file_stale_save_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = "matrix_sec_concurrency.txt"
            path = os.path.join(directory, filename)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("newer content from editor A\n")
            with (
                patch.object(api_editor, "_editor_auth_check", return_value=True),
                patch.object(api_editor, "_current_user_id", return_value=17),
                patch.object(
                    api_editor,
                    "_editor_storage_directory",
                    return_value=(SimpleNamespace(finalize=lambda: None), directory),
                ),
                patch.object(
                    api_editor,
                    "source_revision",
                    side_effect=lambda text: hashlib.sha256(
                        text.encode("utf-8")
                    ).hexdigest(),
                ),
            ):
                with api_editor.app.test_request_context(
                    "/al/editor/api/section-file",
                    method="POST",
                    json={
                        "project": "default",
                        "section": "static",
                        "filename": filename,
                        "content": "stale editor B content\n",
                        "expected_revision": hashlib.sha256(
                            b"baseline from both editors\n"
                        ).hexdigest(),
                    },
                ):
                    response = api_editor.editor_api_save_section_file()
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()["error"]["code"], "revision_conflict")
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "newer content from editor A\n")

    def test_secondary_section_rename_and_delete_reject_stale_revisions(self):
        operations = (
            (
                api_editor.editor_api_rename_section_file,
                "/al/editor/api/section-file/rename",
                {"new_filename": "renamed.txt"},
                "rename_saved_file",
            ),
            (
                api_editor.editor_api_delete_section_file,
                "/al/editor/api/section-file/delete",
                {},
                "delete_saved_file",
            ),
        )
        for handler, route, extra, mutation in operations:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as directory:
                filename = "matrix_sec_concurrency.txt"
                path = os.path.join(directory, filename)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("newer content from editor A\n")
                mutation_mock = patch.object(api_editor, mutation)
                with (
                    patch.object(api_editor, "_editor_auth_check", return_value=True),
                    patch.object(api_editor, "_current_user_id", return_value=17),
                    patch.object(
                        api_editor,
                        "_editor_storage_directory",
                        return_value=(
                            SimpleNamespace(finalize=lambda: None),
                            directory,
                        ),
                    ),
                    patch.object(
                        api_editor,
                        "source_revision",
                        side_effect=lambda text: hashlib.sha256(
                            text.encode("utf-8")
                        ).hexdigest(),
                    ),
                    mutation_mock as mock_mutation,
                ):
                    with api_editor.app.test_request_context(
                        route,
                        method="POST",
                        json={
                            "project": "default",
                            "section": "static",
                            "filename": filename,
                            "expected_revision": hashlib.sha256(
                                b"baseline from both editors\n"
                            ).hexdigest(),
                            **extra,
                        },
                    ):
                        response = handler()
                self.assertEqual(response.status_code, 409)
                self.assertEqual(
                    response.get_json()["error"]["code"], "revision_conflict"
                )
                mock_mutation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
