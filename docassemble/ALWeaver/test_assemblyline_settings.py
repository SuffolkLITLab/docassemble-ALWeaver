# do not pre-load

import unittest

import yaml

from docassemble.ALWeaver.assemblyline_settings import (
    MANAGED_BLOCK_ID,
    METADATA_DOCUMENT_ID,
    SETTINGS_SCHEMA,
    read_settings,
    update_settings,
)

SOURCE = """# keep header
metadata:
  title: Original
  description: |
    Existing description
  authors:
    - Original Author
---
# author-owned code remains untouched
code: |
  AL_DEFAULT_COUNTRY = "CA"
---
id: main order
mandatory: True
code: |
  al_intro_screen
  interview_order = True
"""


class AssemblyLineSettingsTest(unittest.TestCase):
    def test_reads_metadata_and_literal_code_variables(self):
        result = read_settings(SOURCE)
        self.assertEqual(result["values"]["title"], "Original")
        self.assertEqual(result["values"]["AL_DEFAULT_COUNTRY"], "CA")
        self.assertEqual(result["sources"]["AL_DEFAULT_COUNTRY"], "code block")

    def test_update_adds_managed_block_before_mandatory_and_preserves_other_code(self):
        updated = update_settings(
            SOURCE,
            {
                "title": "Updated",
                "AL_DEFAULT_COUNTRY": "US",
                "allowed_courts": ["Housing Court", "Superior Court"],
                "speak_text": False,
            },
        )
        self.assertIn("# author-owned code remains untouched", updated)
        # The author's own block keeps its comment and its structure, and the
        # changed value is written there rather than duplicated in Weaver's
        # block -- two assignments of one name would let document order decide.
        self.assertIn("AL_DEFAULT_COUNTRY = 'US'", updated)
        self.assertEqual(updated.count("AL_DEFAULT_COUNTRY = "), 1)
        self.assertLess(
            updated.index(f"id: {MANAGED_BLOCK_ID}"), updated.index("id: main order")
        )
        result = read_settings(updated)
        self.assertEqual(result["values"]["title"], "Updated")
        self.assertEqual(result["values"]["AL_DEFAULT_COUNTRY"], "US")
        self.assertEqual(
            result["values"]["allowed_courts"],
            ["Housing Court", "Superior Court"],
        )
        self.assertFalse(result["values"]["speak_text"])
        list(yaml.safe_load_all(updated))

    def test_metadata_update_preserves_untouched_literal_scalar_bytes(self):
        updated = update_settings(SOURCE, {"title": "Updated"})

        original_metadata = SOURCE.split("---", 1)[0]
        updated_metadata = updated.split("---", 1)[0]
        self.assertEqual(
            updated_metadata,
            original_metadata.replace("title: Original", "title: Updated"),
        )
        self.assertIn("  description: |\n    Existing description\n", updated)

    def test_changed_multiline_metadata_uses_literal_block_style(self):
        updated = update_settings(
            SOURCE,
            {"description": "First updated line\nSecond updated line"},
        )

        self.assertIn(
            "  description: |\n    First updated line\n    Second updated line\n",
            updated,
        )
        self.assertNotIn("description: '", updated)
        self.assertEqual(
            read_settings(updated)["values"]["description"].rstrip("\n"),
            "First updated line\nSecond updated line",
        )

    def test_new_multiline_metadata_uses_literal_block_style(self):
        updated = update_settings(
            SOURCE,
            {"can_I_use_this_form": "People filing a claim\nPeople responding"},
        )

        self.assertIn(
            "  can_I_use_this_form: |-\n"
            "    People filing a claim\n"
            "    People responding",
            updated,
        )

    def test_multiline_list_items_use_literal_block_style(self):
        updated = update_settings(
            SOURCE,
            {"authors": ["First author\nSecond line"]},
        )

        self.assertIn(
            "  authors:\n" "    - |-\n" "      First author\n" "      Second line",
            updated,
        )
        self.assertEqual(
            read_settings(updated)["values"]["authors"],
            ["First author\nSecond line"],
        )

    def test_repeated_update_replaces_one_managed_block(self):
        once = update_settings(SOURCE, {"github_user": "first"})
        twice = update_settings(once, {"github_user": "second"})
        self.assertEqual(twice.count(f"id: {MANAGED_BLOCK_ID}"), 1)
        self.assertEqual(read_settings(twice)["values"]["github_user"], "second")

    def test_optional_integer_metadata_round_trips_when_blank(self):
        source = SOURCE.replace(
            "  authors:\n    - Original Author\n",
            "  authors:\n    - Original Author\n  estimated_completion_delta: ''\n",
        )

        updated = update_settings(
            source,
            {
                **read_settings(source)["values"],
                "AL_ORGANIZATION_TITLE": "Example Legal Aid",
            },
        )

        values = read_settings(updated)["values"]
        self.assertEqual(values["estimated_completion_delta"], "")
        self.assertEqual(values["AL_ORGANIZATION_TITLE"], "Example Legal Aid")
        self.assertNotIn("can_I_use_this_form:", updated)

    def test_rejects_runtime_logic_as_a_setting(self):
        with self.assertRaisesRegex(ValueError, "Unsupported settings"):
            update_settings(SOURCE, {"addresses_to_search": "[broken"})


METADATA_WITH_LISTS = """metadata:
  title: >-
    Test form
  description: |-
    A test form
  LIST_topics:
    - "CO-00-00-00-00"
  # Keep legacy tags behavior for compatibility with downstream tools.
  tags:
    - "CO-00-00-00-00"

  authors:
    - Court Forms Online
---
code: |
  x = 1
"""


class MetadataListEditingTest(unittest.TestCase):
    """A metadata list has to survive being edited into more than one item.

    PyYAML ends a block sequence's node where the *next* token begins, so the
    node text runs past the last item and over any comment or blank line before
    the following key. Replacing that whole span used to glue the next key onto
    the last item, which the round-trip guard then rejected with "did not
    round-trip safely" -- every multi-item list in `metadata` was unwritable.
    """

    def _metadata(self, source):
        return yaml.safe_load(source.split("---")[0])["metadata"]

    def test_a_list_can_grow_past_one_item(self):
        updated = update_settings(
            METADATA_WITH_LISTS,
            {"LIST_topics": ["HO-00-00-00-00", "HO-05-00-00-00", "HO-06-00-00-00"]},
        )
        self.assertEqual(
            self._metadata(updated)["LIST_topics"],
            ["HO-00-00-00-00", "HO-05-00-00-00", "HO-06-00-00-00"],
        )

    def test_editing_a_list_leaves_the_following_key_alone(self):
        updated = update_settings(
            METADATA_WITH_LISTS, {"LIST_topics": ["HO-00-00-00-00", "HO-05-00-00-00"]}
        )
        self.assertIn("\n  tags:\n", updated)
        self.assertEqual(self._metadata(updated)["tags"], ["CO-00-00-00-00"])
        # The comment sits inside the span PyYAML reports for the sequence.
        self.assertIn(
            "# Keep legacy tags behavior for compatibility with downstream tools.",
            updated,
        )

    def test_a_blank_line_between_keys_survives(self):
        updated = update_settings(METADATA_WITH_LISTS, {"authors": ["A", "B"]})
        self.assertIn('- "CO-00-00-00-00"\n\n  authors:', updated)
        self.assertEqual(self._metadata(updated)["authors"], ["A", "B"])

    def test_a_list_can_shrink_and_empty(self):
        shrunk = update_settings(METADATA_WITH_LISTS, {"authors": ["Solo"]})
        self.assertEqual(self._metadata(shrunk)["authors"], ["Solo"])
        emptied = update_settings(METADATA_WITH_LISTS, {"authors": []})
        self.assertEqual(self._metadata(emptied)["authors"], [])

    def test_a_list_as_the_final_key_still_works(self):
        source = "metadata:\n  title: A\n  authors:\n    - One\n"
        updated = update_settings(source, {"authors": ["One", "Two"]})
        self.assertEqual(self._metadata(updated)["authors"], ["One", "Two"])

    def test_a_literal_block_still_round_trips(self):
        updated = update_settings(
            METADATA_WITH_LISTS, {"description": "First line\nSecond line"}
        )
        self.assertEqual(
            self._metadata(updated)["description"], "First line\nSecond line"
        )
        self.assertIn("\n  LIST_topics:\n", updated)

    def test_untouched_values_keep_their_original_quoting(self):
        updated = update_settings(METADATA_WITH_LISTS, {"authors": ["A"]})
        self.assertIn('  tags:\n    - "CO-00-00-00-00"', updated)


class SettingsTransparencyTest(unittest.TestCase):
    """The panel has to be able to say where every value it writes ends up."""

    def test_each_section_names_the_documents_it_writes_to(self):
        sections = {section["id"]: section for section in SETTINGS_SCHEMA}

        # Publishing identity spans both: metadata keys plus allowed_courts.
        self.assertEqual(
            [document["id"] for document in sections["identity"]["documents"]],
            [METADATA_DOCUMENT_ID, MANAGED_BLOCK_ID],
        )
        # Predefined variables are code only.
        for section_id in ("organization", "interview", "language", "next_steps"):
            with self.subTest(section_id=section_id):
                self.assertEqual(
                    [document["id"] for document in sections[section_id]["documents"]],
                    [MANAGED_BLOCK_ID],
                )
        # The read-only notes section writes nothing.
        self.assertEqual(sections["advanced"]["documents"], [])

    def test_documents_follow_the_field_scopes_rather_than_a_hand_written_list(self):
        for section in SETTINGS_SCHEMA:
            scopes = {field.get("scope") for field in section.get("fields", [])}
            ids = [document["id"] for document in section["documents"]]
            with self.subTest(section=section["id"]):
                self.assertEqual(
                    METADATA_DOCUMENT_ID in ids, bool(scopes & {"metadata", "both"})
                )
                self.assertEqual(MANAGED_BLOCK_ID in ids, bool(scopes & {None, "both"}))

    def test_every_document_carries_an_explanation(self):
        for section in SETTINGS_SCHEMA:
            for document in section["documents"]:
                with self.subTest(section=section["id"], document=document["id"]):
                    self.assertTrue(document["description"])
                    self.assertIn(document["kind"], {"metadata", "code"})

    def test_read_settings_reports_where_a_value_currently_lives(self):
        result = read_settings(SOURCE)
        # SOURCE sets AL_DEFAULT_COUNTRY in an author-owned block, not Weaver's.
        self.assertEqual(result["sources"]["AL_DEFAULT_COUNTRY"], "code block")
        self.assertNotEqual(result["sources"]["AL_DEFAULT_COUNTRY"], MANAGED_BLOCK_ID)
        self.assertEqual(result["managed_block_id"], MANAGED_BLOCK_ID)
        self.assertEqual(result["metadata_document_id"], METADATA_DOCUMENT_ID)

    def test_the_panel_explains_both_kinds_of_setting(self):
        explainer = read_settings(SOURCE)["explainer"]
        self.assertIn("metadata", explainer)
        self.assertIn("al_form_type", explainer)
        # Popover content travels through a double-quoted HTML attribute.
        self.assertNotIn('"', explainer)


AUTHOR_OWNED_SOURCE = """metadata:
  title: Original
---
# author-owned code
code: |
  # my own settings
  AL_DEFAULT_COUNTRY = "CA"
  AL_ORGANIZATION_TITLE = org_title()
  something_else = compute()
---
id: main order
mandatory: True
code: |
  interview_order = True
"""


class AuthorOwnedAssignmentTest(unittest.TestCase):
    """A setting the author already assigns has exactly one home.

    Writing Weaver's own copy on top of an author's assignment leaves two blocks
    setting one name, with the winner decided by document order. The panel edits
    the assignment where it already lives instead.
    """

    def _author_block(self, source):
        return source.split("---")[1]

    def _saved(self, **overrides):
        current = read_settings(AUTHOR_OWNED_SOURCE)["values"]
        return update_settings(AUTHOR_OWNED_SOURCE, {**current, **overrides})

    def test_a_changed_value_is_rewritten_in_the_authors_own_block(self):
        saved = self._saved(AL_DEFAULT_COUNTRY="US")
        self.assertIn("AL_DEFAULT_COUNTRY = 'US'", self._author_block(saved))
        self.assertEqual(read_settings(saved)["values"]["AL_DEFAULT_COUNTRY"], "US")

    def test_the_managed_block_does_not_repeat_it(self):
        saved = self._saved(AL_DEFAULT_COUNTRY="US")
        managed = saved.split("id: " + MANAGED_BLOCK_ID)[1]
        self.assertNotIn("AL_DEFAULT_COUNTRY = ", managed)
        self.assertIn(
            "# AL_DEFAULT_COUNTRY is set in one of your own code blocks, not here.",
            managed,
        )
        # Exactly one assignment survives anywhere in the file.
        self.assertEqual(saved.count("AL_DEFAULT_COUNTRY = "), 1)

    def test_the_rest_of_the_authors_block_is_untouched(self):
        saved = self._saved(AL_DEFAULT_COUNTRY="US")
        block = self._author_block(saved)
        self.assertIn("# my own settings", block)
        self.assertIn("something_else = compute()", block)

    def test_saving_without_changes_does_not_rewrite_author_code(self):
        saved = self._saved()
        # Down to the author's own quoting.
        self.assertIn('AL_DEFAULT_COUNTRY = "CA"', self._author_block(saved))
        self.assertEqual(saved.count("AL_DEFAULT_COUNTRY = "), 1)

    def test_a_computed_value_is_never_flattened_into_a_string(self):
        """`AL_ORGANIZATION_TITLE = org_title()` reaches the panel as its source
        text. Writing that back through repr() would turn working code into the
        string "org_title()"."""
        saved = self._saved()
        self.assertIn("AL_ORGANIZATION_TITLE = org_title()", self._author_block(saved))
        self.assertNotIn("'org_title()'", saved)
        managed = saved.split("id: " + MANAGED_BLOCK_ID)[1]
        self.assertNotIn("AL_ORGANIZATION_TITLE = ", managed)

    def test_a_computed_value_is_read_only_and_survives_a_submitted_value(self):
        """The control is disabled, but a stale or hand-made request must not be
        able to replace the author's expression either."""
        saved = self._saved(AL_ORGANIZATION_TITLE="Legal Aid")
        self.assertIn("AL_ORGANIZATION_TITLE = org_title()", self._author_block(saved))
        self.assertNotIn("Legal Aid", saved)
        self.assertEqual(
            read_settings(saved)["values"]["AL_ORGANIZATION_TITLE"], "org_title()"
        )

    def test_settings_with_no_author_assignment_still_use_the_managed_block(self):
        saved = self._saved(al_typed_signature_prefix="/sig/")
        managed = saved.split("id: " + MANAGED_BLOCK_ID)[1]
        self.assertIn("al_typed_signature_prefix = '/sig/'", managed)

    def test_the_managed_block_is_still_rewritten_in_place_on_a_second_save(self):
        once = self._saved(AL_DEFAULT_COUNTRY="US")
        twice = update_settings(once, read_settings(once)["values"])
        self.assertEqual(twice.count("id: " + MANAGED_BLOCK_ID), 1)
        self.assertEqual(twice.count("AL_DEFAULT_COUNTRY = "), 1)
        self.assertEqual(read_settings(twice)["values"]["AL_DEFAULT_COUNTRY"], "US")


COMPUTED_CHOICE_SOURCE = """metadata:
  title: Original
---
# author-owned code
code: |
  al_form_type = form_type_for(case)
  al_form_requires_digital_signature = needs_signature(case)
  AL_DEFAULT_COUNTRY = "CA"
---
id: main order
mandatory: True
code: |
  interview_order = True
"""


class ComputedSettingTest(unittest.TestCase):
    """A setting the interview computes is reported, never written.

    Rendering `al_form_type = form_type_for(case)` back through the panel would
    have to pick one of the allowed choices, replacing working code with a
    guess. `_coerce_value` used to reject the expression outright, so an
    interview computing any choice- or boolean-typed setting could not be saved
    from this panel at all.
    """

    def test_computed_settings_are_reported_with_the_block_that_holds_them(self):
        result = read_settings(COMPUTED_CHOICE_SOURCE)
        self.assertEqual(
            result["computed"],
            {
                "al_form_type": "code block",
                "al_form_requires_digital_signature": "code block",
            },
        )
        # A plain literal in the same block is not computed.
        self.assertNotIn("AL_DEFAULT_COUNTRY", result["computed"])
        self.assertEqual(result["values"]["al_form_type"], "form_type_for(case)")

    def test_the_panel_can_still_save(self):
        current = read_settings(COMPUTED_CHOICE_SOURCE)["values"]
        saved = update_settings(
            COMPUTED_CHOICE_SOURCE, {**current, "AL_DEFAULT_COUNTRY": "US"}
        )
        self.assertEqual(read_settings(saved)["values"]["AL_DEFAULT_COUNTRY"], "US")

    def test_the_computed_expressions_are_untouched(self):
        current = read_settings(COMPUTED_CHOICE_SOURCE)["values"]
        saved = update_settings(
            COMPUTED_CHOICE_SOURCE, {**current, "AL_DEFAULT_COUNTRY": "US"}
        )
        author_block = saved.split("---")[1]
        self.assertIn("al_form_type = form_type_for(case)", author_block)
        self.assertIn(
            "al_form_requires_digital_signature = needs_signature(case)", author_block
        )

    def test_the_managed_block_neither_writes_nor_hides_them(self):
        current = read_settings(COMPUTED_CHOICE_SOURCE)["values"]
        saved = update_settings(COMPUTED_CHOICE_SOURCE, dict(current))
        managed = saved.split("id: " + MANAGED_BLOCK_ID)[1]
        self.assertNotIn("al_form_type = ", managed)
        self.assertIn(
            "# al_form_type is computed by your own code, and is left alone.", managed
        )
        self.assertEqual(saved.count("al_form_type = "), 1)

    def test_a_literal_that_looks_like_a_choice_is_still_editable(self):
        source = COMPUTED_CHOICE_SOURCE.replace(
            "al_form_type = form_type_for(case)", 'al_form_type = "appeal"'
        )
        self.assertNotIn("al_form_type", read_settings(source)["computed"])
        current = read_settings(source)["values"]
        saved = update_settings(source, {**current, "al_form_type": "starts_case"})
        self.assertEqual(read_settings(saved)["values"]["al_form_type"], "starts_case")


if __name__ == "__main__":
    unittest.main()
