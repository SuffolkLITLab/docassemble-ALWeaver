import unittest
from pathlib import Path

from .api_utils import (
    DEFAULT_MAX_UPLOAD_BYTES,
    WEAVER_API_BASE_PATH,
    WeaverAPIValidationError,
    build_openapi_spec,
    coerce_async_flag,
    coerce_generation_options,
    coerce_response_flags,
    generate_interview_from_bytes,
    merge_raw_options,
    parse_bool,
    validate_upload_metadata,
)


class test_api_utils(unittest.TestCase):
    def test_parse_bool(self):
        self.assertTrue(parse_bool("true"))
        self.assertTrue(parse_bool("1"))
        self.assertFalse(parse_bool("false"))
        self.assertFalse(parse_bool("0"))
        self.assertTrue(parse_bool(None, default=True))

    def test_parse_bool_invalid(self):
        with self.assertRaises(WeaverAPIValidationError):
            parse_bool("maybe")

    def test_coerce_generation_options_from_json_strings(self):
        options = coerce_generation_options(
            {
                "title": "Example",
                "create_package_zip": "false",
                "include_next_steps": "true",
                "field_definitions": '[{"field":"x","datatype":"text"}]',
                "screen_definitions": '[{"question":"Screen 1","fields":[{"field":"x"}]}]',
                "interview_overrides": '{"foo":"bar"}',
            }
        )
        self.assertEqual(options["title"], "Example")
        self.assertFalse(options["create_package_zip"])
        self.assertTrue(options["include_next_steps"])
        self.assertEqual(options["field_definitions"][0]["field"], "x")
        self.assertEqual(options["screen_definitions"][0]["question"], "Screen 1")
        self.assertEqual(options["interview_overrides"]["foo"], "bar")

    def test_merge_raw_options_prefers_explicit_form_keys(self):
        merged = merge_raw_options(
            {
                "title": "Explicit",
                "options": '{"title":"From options","include_next_steps":false}',
            }
        )
        self.assertEqual(merged["title"], "Explicit")
        self.assertEqual(merged["include_next_steps"], False)

    def test_coerce_response_flags(self):
        flags = coerce_response_flags(
            {"include_package_zip_base64": "true", "include_yaml_text": "false"}
        )
        self.assertTrue(flags["include_package_zip_base64"])
        self.assertFalse(flags["include_yaml_text"])

    def test_coerce_async_flag(self):
        self.assertFalse(coerce_async_flag({}))
        self.assertTrue(coerce_async_flag({"async": "true"}))
        self.assertFalse(coerce_async_flag({"async": "false"}))
        self.assertTrue(coerce_async_flag({"mode": "async"}))
        self.assertFalse(coerce_async_flag({"mode": "sync"}))

    def test_coerce_async_flag_invalid_mode(self):
        with self.assertRaises(WeaverAPIValidationError):
            coerce_async_flag({"mode": "later"})

    def test_validate_upload_metadata_from_extension(self):
        filename, extension = validate_upload_metadata(
            filename="example.pdf", content_bytes=b"123", mimetype="application/pdf"
        )
        self.assertEqual(filename, "example.pdf")
        self.assertEqual(extension, ".pdf")

    def test_validate_upload_metadata_from_mimetype(self):
        filename, extension = validate_upload_metadata(
            filename="example", content_bytes=b"123", mimetype="application/pdf"
        )
        self.assertEqual(filename, "example.pdf")
        self.assertEqual(extension, ".pdf")

    def test_validate_upload_metadata_unsupported_type(self):
        with self.assertRaises(WeaverAPIValidationError):
            validate_upload_metadata(
                filename="example.txt", content_bytes=b"123", mimetype="text/plain"
            )

    def test_validate_upload_metadata_too_large(self):
        with self.assertRaises(WeaverAPIValidationError):
            validate_upload_metadata(
                filename="example.pdf",
                content_bytes=b"x" * (DEFAULT_MAX_UPLOAD_BYTES + 1),
                mimetype="application/pdf",
            )

    def test_build_openapi_spec_has_expected_paths(self):
        spec = build_openapi_spec()
        self.assertIn(WEAVER_API_BASE_PATH, spec["paths"])
        self.assertIn(f"{WEAVER_API_BASE_PATH}/openapi.json", spec["paths"])
        self.assertIn(f"{WEAVER_API_BASE_PATH}/docs", spec["paths"])
        self.assertIn(f"{WEAVER_API_BASE_PATH}/jobs/{{job_id}}", spec["paths"])

    def test_generate_interview_from_bytes_docx(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        result = generate_interview_from_bytes(
            filename=docx_path.name,
            content_bytes=docx_path.read_bytes(),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            generation_options={
                "create_package_zip": False,
                "include_next_steps": False,
            },
            include_package_zip_base64=False,
            include_yaml_text=True,
        )
        self.assertIn("yaml_text", result)
        self.assertIn("yaml_filename", result)
        self.assertNotIn("package_zip_base64", result)


if __name__ == "__main__":
    unittest.main()
