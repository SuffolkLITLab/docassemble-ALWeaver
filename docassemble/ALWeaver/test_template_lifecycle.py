# do not pre-load

"""End to end: a template's whole life inside one project.

Every other suite tests a layer. This one drives the editor's HTTP endpoints in
the order an author does -- create a project from two uploads, look at what the
Templates tab would show, import a third form, rearrange the download, switch a
document off, and re-read a form the court revised -- against real Playground
files and real YAML, with only Docassemble's storage and Celery stubbed.

It is the test that would have caught a Weaver that writes YAML naming fields
its templates do not have, or a Templates tab offering an edit that always
fails.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import editor_utils as real_editor_utils
from . import interview_generator as interview_generator_module
from .document_bundles import interview_documents, template_status
from .template_analysis import analyze_template
from .test_editor_api import api_editor
from .test_generate_from_path import _TestAutoDraftBase, _build_pdf_with_fields

DOCX_FIXTURE = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"


class _Project:
    """A Playground project on disk, standing in for Docassemble's storage."""

    def __init__(self, root: str):
        self.root = root
        self.templates = os.path.join(root, "templates")
        os.makedirs(self.templates, exist_ok=True)
        self.yaml_files: dict = {}

    def read_yaml(self, _uid, _project, filename):
        try:
            return self.yaml_files[filename]
        except KeyError:
            raise FileNotFoundError(filename)

    def write_yaml(self, _uid, _project, filename, content):
        self.yaml_files[filename] = content

    def list_templates(self, _uid, _project, _section):
        return [{"filename": name} for name in sorted(os.listdir(self.templates))]

    def add_pdf(self, filename, field_names):
        return _build_pdf_with_fields(
            os.path.join(self.templates, filename), field_names
        )

    def add_docx(self, filename):
        path = os.path.join(self.templates, filename)
        shutil.copyfile(DOCX_FIXTURE, path)
        return path


class TemplateLifecycleTest(unittest.TestCase):
    """Drives the editor endpoints the way the Templates tab does."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.project = _Project(self.tmpdir)
        self._cluster = patch.object(
            interview_generator_module.formfyxer,
            "cluster_screens",
            side_effect=_TestAutoDraftBase._offline_cluster,
        )
        self._cluster.start()
        self.addCleanup(self._cluster.stop)

    # -- plumbing -----------------------------------------------------------

    def _editor(self):
        """Patch the editor onto this project's files and real YAML helpers."""
        return [
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor, "playground_read_yaml", side_effect=self.project.read_yaml
            ),
            patch.object(
                api_editor,
                "playground_write_yaml",
                side_effect=self.project.write_yaml,
            ),
            patch.object(
                api_editor,
                "_list_editor_section_files",
                side_effect=self.project.list_templates,
            ),
            patch.object(
                api_editor,
                "source_revision",
                side_effect=real_editor_utils.source_revision,
            ),
            patch.object(
                api_editor,
                "parse_interview_yaml",
                side_effect=real_editor_utils.parse_interview_yaml,
            ),
            patch.object(
                api_editor,
                "insert_block_in_yaml",
                side_effect=real_editor_utils.insert_block_in_yaml,
            ),
            patch.object(
                api_editor,
                "update_block_in_yaml",
                side_effect=real_editor_utils.update_block_in_yaml,
            ),
        ]

    def _call(self, path, handler, method="GET", json=None):
        stack = self._editor()
        for entered in stack:
            entered.start()
        try:
            with api_editor.app.test_request_context(path, method=method, json=json):
                return handler()
        finally:
            for entered in reversed(stack):
                entered.stop()

    def _documents(self, filename="main.yml"):
        response = self._call(
            f"/al/editor/api/documents?project=P&filename={filename}",
            api_editor.editor_api_documents,
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["data"]

    def _import(self, template, filename="main.yml"):
        """Run the analysis the import job runs, without Celery in the way."""
        return analyze_template(
            template_path=os.path.join(self.project.templates, template),
            template_filename=template,
            interview_yaml=self.project.read_yaml(7, "P", filename),
        )

    def _apply(self, analysis, filename="main.yml", skip=()):
        blocks = []
        for key, block in (
            ("document_object", analysis.document_object),
            ("attachment", analysis.attachment),
            ("objects", analysis.objects),
        ):
            if block is None or key in skip:
                continue
            blocks.append(
                {"yaml": block.yaml, "replace_block_id": block.replaces_block_id}
                if block.replaces_block_id
                else block.yaml
            )
        if "questions" not in skip:
            blocks.extend(question.yaml for question in analysis.questions)
        payload = {
            "project": "P",
            "filename": filename,
            "expected_revision": real_editor_utils.source_revision(
                self.project.read_yaml(7, "P", filename)
            ),
            "blocks": blocks,
            "bundles": [
                {"bundle": addition["bundle"], "elements": addition["elements"]}
                for addition in analysis.bundle_additions
            ],
        }
        response = self._call(
            "/al/editor/api/template/apply",
            api_editor.editor_api_apply_template_analysis,
            method="POST",
            json=payload,
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["data"]

    def _save_documents(self, bundles=(), enabled=(), filename="main.yml"):
        payload = {
            "project": "P",
            "filename": filename,
            "expected_revision": real_editor_utils.source_revision(
                self.project.read_yaml(7, "P", filename)
            ),
            "bundles": list(bundles),
            "enabled": list(enabled),
        }
        return self._call(
            "/al/editor/api/documents",
            api_editor.editor_api_save_documents,
            method="POST",
            json=payload,
        )

    def _generate(self, templates, **options):
        """Create the project's interview the way new-project generation does."""
        paths = [self.project.add_pdf(name, fields) for name, fields in templates]
        output_dir = os.path.join(self.tmpdir, "generated")
        os.makedirs(output_dir, exist_ok=True)
        result = interview_generator_module.generate_interview_from_path(
            paths[0],
            output_dir=output_dir,
            create_package_zip=False,
            include_next_steps=False,
            additional_templates=paths[1:],
            **options,
        )
        self.project.write_yaml(7, "P", "main.yml", result.yaml_text)
        return result

    def _lint(self, filename="main.yml"):
        from dayamlchecker.yaml_structure import find_errors_from_string

        source = self.project.read_yaml(7, "P", filename)
        return [
            str(getattr(error, "err_str", "") or error)
            for error in find_errors_from_string(source, input_file=filename)
            # Publishing metadata is the author's to supply and is not what
            # any of this touches.
            if "missing_metadata_fields" not in str(getattr(error, "message_id", ""))
        ]

    # -- the lifecycle ------------------------------------------------------

    def test_two_uploads_become_two_documents_in_one_interview(self):
        self._generate(
            [
                ("petition.pdf", ["users1_name_first", "rent_amount"]),
                ("affidavit.pdf", ["users1_name_first", "landlord_visits"]),
            ]
        )

        model = self._documents()
        self.assertEqual(
            [document["name"] for document in model["documents"]],
            ["petition", "affidavit"],
        )
        self.assertEqual(
            [
                (document["name"], document["template_filename"])
                for document in model["documents"]
            ],
            [("petition", "petition.pdf"), ("affidavit", "affidavit.pdf")],
        )
        for bundle in model["bundles"]:
            self.assertEqual(bundle["elements"], ["petition", "affidavit"])
        self.assertEqual(
            {name: entry["status"] for name, entry in model["templates"].items()},
            {"petition.pdf": "attached", "affidavit.pdf": "attached"},
        )
        self.assertEqual(self._lint(), [])

    def test_a_template_dropped_in_later_shows_as_not_imported(self):
        self._generate([("petition.pdf", ["users1_name_first"])])
        self.project.add_pdf("cover_sheet.pdf", ["docket_number"])

        model = self._documents()
        self.assertEqual(
            model["templates"]["cover_sheet.pdf"],
            {"status": "not_imported", "document": ""},
        )
        self.assertEqual(model["templates"]["petition.pdf"]["status"], "attached")

    def test_importing_it_makes_it_a_document_in_every_bundle(self):
        self._generate([("petition.pdf", ["users1_name_first"])])
        self.project.add_pdf("cover_sheet.pdf", ["docket_number", "hearing_is_remote"])

        analysis = self._import("cover_sheet.pdf")
        self.assertFalse(analysis.already_imported)
        self.assertEqual(analysis.document_variable, "cover_sheet")
        self._apply(analysis)

        model = self._documents()
        self.assertIn("cover_sheet", [d["name"] for d in model["documents"]])
        # A project generated from one template calls its document
        # `<label>_attachment`; a document added later is named after its file.
        for bundle in model["bundles"]:
            self.assertEqual(bundle["elements"], ["petition_attachment", "cover_sheet"])
        self.assertEqual(model["templates"]["cover_sheet.pdf"]["status"], "attached")
        source = self.project.read_yaml(7, "P", "main.yml")
        self.assertIn("pdf template file: cover_sheet.pdf", source)
        # A field only the new form has is now asked about.
        self.assertIn("hearing_is_remote", source)
        self.assertEqual(self._lint(), [])

    def test_a_field_the_interview_already_asks_is_not_asked_twice(self):
        self._generate([("petition.pdf", ["users1_name_first", "rent_amount"])])
        self.project.add_pdf(
            "cover_sheet.pdf", ["users1_name_first", "landlord_visits"]
        )

        analysis = self._import("cover_sheet.pdf")
        offered = "\n".join(question.yaml for question in analysis.questions)
        self.assertIn("landlord_visits", offered)
        self.assertNotIn("users[0].name.first", offered)

    def test_the_download_order_can_be_rearranged(self):
        self._generate(
            [
                ("petition.pdf", ["users1_name_first"]),
                ("affidavit.pdf", ["rent_amount"]),
            ]
        )

        response = self._save_documents(
            bundles=[
                {"bundle": "al_user_bundle", "elements": ["affidavit", "petition"]}
            ]
        )
        self.assertEqual(response.status_code, 200, response.get_json())

        model = self._documents()
        by_name = {bundle["name"]: bundle for bundle in model["bundles"]}
        self.assertEqual(
            by_name["al_user_bundle"]["elements"], ["affidavit", "petition"]
        )
        # Only the bundle asked for moved.
        self.assertEqual(
            by_name["al_court_bundle"]["elements"], ["petition", "affidavit"]
        )
        self.assertEqual(self._lint(), [])

    def test_a_document_can_be_switched_off_by_a_rule(self):
        self._generate(
            [
                ("petition.pdf", ["users1_name_first"]),
                ("affidavit.pdf", ["rent_amount"]),
            ]
        )

        response = self._save_documents(
            enabled=[{"name": "affidavit", "expression": "user_is_low_income"}]
        )
        self.assertEqual(response.status_code, 200, response.get_json())

        model = self._documents()
        by_name = {document["name"]: document for document in model["documents"]}
        self.assertEqual(by_name["affidavit"]["enabled"], "user_is_low_income")
        self.assertEqual(by_name["petition"]["enabled"], "True")
        self.assertEqual(self._lint(), [])

    def test_a_rule_that_is_not_an_expression_changes_nothing(self):
        self._generate([("petition.pdf", ["users1_name_first"])])
        before = self.project.read_yaml(7, "P", "main.yml")

        response = self._save_documents(
            enabled=[{"name": "petition", "expression": "if x: y"}]
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.project.read_yaml(7, "P", "main.yml"), before)

    def test_a_revised_form_is_re_read_into_the_block_it_already_has(self):
        self._generate([("petition.pdf", ["users1_name_first"])])
        source_before = self.project.read_yaml(7, "P", "main.yml")
        self.assertNotIn("court_ordered_relief", source_before)
        # The court publishes a new version of the same form.
        self.project.add_pdf(
            "petition.pdf", ["users1_name_first", "court_ordered_relief"]
        )

        analysis = self._import("petition.pdf")
        self.assertTrue(analysis.already_imported)
        assert analysis.attachment is not None
        self.assertEqual(analysis.attachment.kind, "attachment_replacement")
        self.assertFalse(analysis.attachment.recommended)
        self.assertIsNone(analysis.document_object)
        self.assertEqual(analysis.bundle_additions, [])

        self._apply(analysis)

        source = self.project.read_yaml(7, "P", "main.yml")
        # One attachment block, now naming the new field.
        self.assertEqual(source.count("pdf template file: petition.pdf"), 1)
        self.assertIn('- "court_ordered_relief"', source)
        model = self._documents()
        self.assertEqual(
            [d["name"] for d in model["documents"]], ["petition_attachment"]
        )
        for bundle in model["bundles"]:
            self.assertEqual(bundle["elements"], ["petition_attachment"])
        self.assertEqual(self._lint(), [])

    def test_a_companion_named_like_the_first_gets_the_extension(self):
        self._generate([("petition.pdf", ["users1_name_first"])])
        self.project.add_docx("petition.docx")

        analysis = self._import("petition.docx")
        self.assertEqual(analysis.document_variable, "petition_docx")
        self._apply(analysis)

        source = self.project.read_yaml(7, "P", "main.yml")
        model = self._documents()
        self.assertEqual(
            [document["name"] for document in model["documents"]],
            ["petition_attachment", "petition_docx"],
        )
        # The PDF is already `petition`, whatever its document is called, so
        # the DOCX keeps its extension rather than quietly taking that name.
        self.assertIn(
            '- petition_docx: ALDocument.using(filename="petition_docx"', source
        )
        self.assertIn("docx template file: petition.docx", source)
        for bundle in model["bundles"]:
            self.assertEqual(
                bundle["elements"], ["petition_attachment", "petition_docx"]
            )
        self.assertEqual(self._lint(), [])

    def test_an_import_against_a_changed_interview_is_refused(self):
        self._generate([("petition.pdf", ["users1_name_first"])])
        self.project.add_pdf("cover_sheet.pdf", ["docket_number"])
        analysis = self._import("cover_sheet.pdf")

        # Someone edits the interview between reading it and accepting.
        self.project.write_yaml(
            7, "P", "main.yml", self.project.read_yaml(7, "P", "main.yml") + "---\n"
        )

        response = self._call(
            "/al/editor/api/template/apply",
            api_editor.editor_api_apply_template_analysis,
            method="POST",
            json={
                "project": "P",
                "filename": "main.yml",
                "expected_revision": "stale",
                "blocks": [analysis.attachment.yaml],
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_nothing_is_written_when_one_accepted_block_is_invalid(self):
        self._generate([("petition.pdf", ["users1_name_first"])])
        before = self.project.read_yaml(7, "P", "main.yml")

        response = self._call(
            "/al/editor/api/template/apply",
            api_editor.editor_api_apply_template_analysis,
            method="POST",
            json={
                "project": "P",
                "filename": "main.yml",
                "expected_revision": real_editor_utils.source_revision(before),
                "blocks": ["objects:\n  - ok: ALDocument.using()\n", "id: nothing\n"],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.project.read_yaml(7, "P", "main.yml"), before)

    def test_the_whole_sequence_in_one_project(self):
        """Every step in order, on cumulative state, ending in valid YAML."""
        # 1. A project generated from two forms.
        self._generate(
            [
                ("petition.pdf", ["users1_name_first", "rent_amount"]),
                ("affidavit.pdf", ["users1_name_first", "landlord_visits"]),
            ]
        )
        model = self._documents()
        self.assertEqual(
            [document["name"] for document in model["documents"]],
            ["petition", "affidavit"],
        )

        # 2. A third form is dropped into templates/ and is nobody's document.
        self.project.add_pdf("cover_sheet.pdf", ["hearing_is_remote"])
        self.assertEqual(
            self._documents()["templates"]["cover_sheet.pdf"]["status"],
            "not_imported",
        )

        # 3. Imported, it becomes one, and joins every bundle.
        self._apply(self._import("cover_sheet.pdf"))
        self.assertEqual(
            self._documents()["templates"]["cover_sheet.pdf"]["status"], "attached"
        )

        # 4. The cover sheet belongs on top of the filing.
        response = self._save_documents(
            bundles=[
                {
                    "bundle": bundle["name"],
                    "elements": ["cover_sheet", "petition", "affidavit"],
                }
                for bundle in self._documents()["bundles"]
            ]
        )
        self.assertEqual(response.status_code, 200, response.get_json())

        # 5. The affidavit is only filed by some users.
        response = self._save_documents(
            enabled=[{"name": "affidavit", "expression": "user_is_low_income"}]
        )
        self.assertEqual(response.status_code, 200, response.get_json())

        # 6. The court revises the petition.
        self.project.add_pdf(
            "petition.pdf",
            ["users1_name_first", "rent_amount", "court_ordered_relief"],
        )
        reload = self._import("petition.pdf")
        self.assertTrue(reload.already_imported)
        self._apply(reload)

        model = self._documents()
        by_name = {document["name"]: document for document in model["documents"]}
        self.assertEqual(sorted(by_name), ["affidavit", "cover_sheet", "petition"])
        self.assertEqual(by_name["affidavit"]["enabled"], "user_is_low_income")
        self.assertEqual(by_name["petition"]["enabled"], "True")
        for bundle in model["bundles"]:
            self.assertEqual(
                bundle["elements"], ["cover_sheet", "petition", "affidavit"]
            )
        self.assertEqual(
            {name: entry["status"] for name, entry in model["templates"].items()},
            {
                "affidavit.pdf": "attached",
                "cover_sheet.pdf": "attached",
                "petition.pdf": "attached",
            },
        )

        source = self.project.read_yaml(7, "P", "main.yml")
        # One attachment per template, and the revision's new field reached it.
        for template in ("petition.pdf", "affidavit.pdf", "cover_sheet.pdf"):
            self.assertEqual(source.count(f"pdf template file: {template}"), 1)
        self.assertIn('- "court_ordered_relief"', source)
        self.assertIn("hearing_is_remote", source)
        self.assertEqual(self._lint(), [])

    def test_the_modules_agree_with_the_endpoints(self):
        """The Templates tab and the source both read the same file."""
        self._generate(
            [
                ("petition.pdf", ["users1_name_first"]),
                ("affidavit.pdf", ["rent_amount"]),
            ]
        )
        self.project.add_pdf("orphan.pdf", ["docket_number"])
        source = self.project.read_yaml(7, "P", "main.yml")

        endpoint = self._documents()
        direct = interview_documents(source)
        self.assertEqual(
            [document["name"] for document in endpoint["documents"]],
            [document.name for document in direct.documents],
        )
        self.assertEqual(
            endpoint["templates"],
            template_status(source, ["affidavit.pdf", "orphan.pdf", "petition.pdf"]),
        )


if __name__ == "__main__":
    unittest.main()
