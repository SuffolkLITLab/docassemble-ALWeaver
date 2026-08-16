# do not pre-load
"""End-to-end checks on the attachment blocks the Weaver writes for addenda.

An addendum only works if three separate parts of the generated YAML agree:
the ALDocument has to be created with `has_addendum=True`, the PDF field has to
be filled from `safe_value()` rather than the variable itself, and a code block
has to register the field in `overflow_fields` with the character limit that
`safe_value()` is measuring against. Any one of them missing silently produces
either a truncated form or an addendum page that never appears.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from . import interview_generator as interview_generator_module
from .interview_generator import (
    DAInterview,
    _make_static_file_from_path,
    _render_interview_yaml,
)

ADDENDUM_FIELD = "inspector_name"


def _offline_cluster_screens(fields, tools_token=None):
    """Deterministic fallback grouping for test runs without OpenAI credentials."""
    del tools_token
    unique_fields = list(dict.fromkeys(fields or []))
    return {
        f"Screen {index // 4 + 1}": unique_fields[index : index + 4]
        for index in range(0, len(unique_fields), 4)
    }


class TestAddendumAttachmentBlock(unittest.TestCase):
    @classmethod
    def _generate(cls, with_addendum: bool) -> str:
        pdf_path = (
            Path(__file__).parent / "test/test_petition_to_enforce_sanitary_code.pdf"
        )
        with patch.object(
            interview_generator_module.formfyxer,
            "cluster_screens",
            side_effect=_offline_cluster_screens,
        ):
            interview = DAInterview()
            interview.auto_assign_attributes(
                input_file=_make_static_file_from_path(
                    str(pdf_path), filename=pdf_path.name
                ),
                jurisdiction="MA",
            )
            interview.include_next_steps = False
            interview.use_llm_assist = False
            if with_addendum:
                for field in interview.all_fields:
                    if field.variable == ADDENDUM_FIELD:
                        field.field_type = "area"
                        field.maxlength = 100
                        field.send_to_addendum = True
            return _render_interview_yaml(
                interview=interview,
                include_download_screen=True,
                output_mako_choice="Default configuration:standard AssemblyLine",
                objects=interview._guess_objects_list(),
                screen_reordered=None,
            )

    # Generating is slow, and the result is a plain string, so cache it. This
    # cannot happen in setUpClass: the Docassemble thread context the generator
    # needs is set up by a per-test fixture.
    _cache: dict = {}

    @property
    def with_addendum(self) -> str:
        return self._cached(True)

    @property
    def without_addendum(self) -> str:
        return self._cached(False)

    @classmethod
    def _cached(cls, with_addendum: bool) -> str:
        if with_addendum not in cls._cache:
            cls._cache[with_addendum] = cls._generate(with_addendum=with_addendum)
        return cls._cache[with_addendum]

    def test_generated_yaml_is_parseable(self):
        blocks = list(yaml.safe_load_all(self.with_addendum))
        self.assertTrue(blocks)

    def test_document_is_created_with_an_addendum(self):
        self.assertIn("has_addendum=True", self.with_addendum)
        self.assertIn(
            "default_overflow_message=AL_DEFAULT_OVERFLOW_MESSAGE", self.with_addendum
        )

    def test_addendum_field_is_filled_from_safe_value(self):
        """The PDF has to get the truncated text, not the whole answer."""
        self.assertRegex(
            self.with_addendum,
            r'- "inspector_name": \$\{ \w+_attachment\.safe_value\("inspector_name"',
        )

    def test_other_fields_are_filled_from_the_variable(self):
        self.assertIn(
            '- "defendant_address": ${ defendant_address }', self.with_addendum
        )
        self.assertNotIn('safe_value("defendant_address"', self.with_addendum)

    def test_overflow_field_is_registered_with_the_character_limit(self):
        """`safe_value()` truncates at `overflow_trigger`, so it has to be set."""
        self.assertRegex(
            self.with_addendum,
            r'\w+_attachment\.overflow_fields\["inspector_name"\]\.overflow_trigger = 100',
        )
        self.assertRegex(
            self.with_addendum,
            r'\w+_attachment\.overflow_fields\["inspector_name"\]\.label = "[^"]+"',
        )

    def test_overflow_fields_are_marked_gathered(self):
        """Without this the interview stops to ask for the addendum's contents."""
        self.assertRegex(
            self.with_addendum, r"\w+_attachment\.overflow_fields\.gathered = True"
        )

    def test_addendum_field_question_has_no_maxlength(self):
        """A maxlength would cut the answer off before it could ever overflow."""
        self.assertNotIn(
            "maxlength", self._question_field(self.with_addendum, ADDENDUM_FIELD)
        )

    def test_fields_that_stay_on_the_form_keep_their_maxlength(self):
        self.assertIn(
            "maxlength: ",
            self._question_field(self.with_addendum, "defendant_address"),
        )

    def test_no_addendum_machinery_without_addendum_fields(self):
        self.assertIn("has_addendum=False", self.without_addendum)
        self.assertNotIn("overflow_fields", self.without_addendum)
        self.assertNotIn("safe_value(", self.without_addendum)
        self.assertNotIn("AL_DEFAULT_OVERFLOW_MESSAGE", self.without_addendum)

    @staticmethod
    def _question_field(yaml_text: str, variable: str) -> str:
        """The one `fields:` entry that asks for `variable`, with its options."""
        lines = yaml_text.splitlines()
        for index, line in enumerate(lines):
            if not line.startswith('  - "') or not line.endswith(f": {variable}"):
                continue
            entry = [line]
            for following in lines[index + 1 :]:
                if not following.startswith("    "):
                    break
                entry.append(following)
            return "\n".join(entry)
        raise AssertionError(f"No question asks for {variable}")
