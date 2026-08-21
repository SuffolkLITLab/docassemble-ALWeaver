# do not pre-load

import unittest
from unittest import mock

from . import review_screen_sync
from .review_screen_sync import (
    ALDashboardUnavailable,
    collect_interview_yaml_texts,
    interview_scope,
    generate_review_screen_yaml,
    project_include_chain,
    review_screen_identity,
    sync_review_screen,
)

MAIN_YAML = """---
include:
  - docassemble.AssemblyLine:assembly_line.yml
  - questions.yml
---
id: intro
question: |
  Hello
---
id: my review screen
event: review_my_form
question: |
  Check your answers
review:
  - Edit: rent_amount
    button: |
      **Rent**
---
id: edit tenants
continue button field: tenants.revisit
question: |
  Edit tenants
---
table: tenants.table
rows: tenants
columns:
  - Name: |
      row_item
edit:
  - name.first
---
id: download
event: my_form_download
question: |
  All done
"""


class TestIncludeChain(unittest.TestCase):
    def setUp(self):
        self.files = {
            "main.yml": MAIN_YAML,
            "questions.yml": "---\ninclude:\n  - shared.yml\n---\nid: q\nquestion: |\n  Q\n",
            "shared.yml": "---\nid: s\nquestion: |\n  S\n",
        }

    def read(self, name):
        return self.files[name]

    def test_it_follows_project_includes_but_not_other_packages(self):
        self.assertEqual(
            project_include_chain(self.read, "main.yml"),
            ["main.yml", "questions.yml", "shared.yml"],
        )

    def test_a_cycle_does_not_loop_forever(self):
        self.files["shared.yml"] = "---\ninclude:\n  - main.yml\n---\nid: s\n"
        self.assertEqual(
            project_include_chain(self.read, "main.yml"),
            ["main.yml", "questions.yml", "shared.yml"],
        )

    def test_an_unreadable_include_does_not_stop_the_rest(self):
        self.files["questions.yml"] = "---\ninclude:\n  - missing.yml\n  - shared.yml\n"
        names, texts = collect_interview_yaml_texts(self.read, "main.yml")
        self.assertEqual(names, ["main.yml", "questions.yml", "shared.yml"])
        self.assertEqual(len(texts), 3)


class TestInterviewScope(unittest.TestCase):
    """Review screens usually live in a file the interviews include."""

    def setUp(self):
        self.files = {
            "main.yml": "---\ninclude:\n  - questions.yml\n  - review.yml\n",
            "questions.yml": "---\nid: q\nquestion: |\n  Q\n",
            "review.yml": "---\nid: r\nreview:\n  - Edit: x\n",
        }

    def read(self, name):
        return self.files[name]

    def test_a_review_only_file_is_scoped_to_the_interview_that_includes_it(self):
        roots, files = interview_scope(self.read, "review.yml", list(self.files))
        self.assertEqual(roots, ["main.yml"])
        self.assertEqual(files, ["main.yml", "questions.yml", "review.yml"])

    def test_a_shared_review_screen_covers_every_interview_that_uses_it(self):
        self.files["other.yml"] = "---\ninclude:\n  - review.yml\n  - extra.yml\n"
        self.files["extra.yml"] = "---\nid: e\nquestion: |\n  E\n"
        roots, files = interview_scope(self.read, "review.yml", list(self.files))
        self.assertEqual(sorted(roots), ["main.yml", "other.yml"])
        self.assertEqual(
            sorted(files),
            ["extra.yml", "main.yml", "other.yml", "questions.yml", "review.yml"],
        )

    def test_an_interview_of_its_own_keeps_its_own_chain(self):
        roots, files = interview_scope(self.read, "main.yml", list(self.files))
        self.assertEqual(roots, ["main.yml"])
        self.assertEqual(files, ["main.yml", "questions.yml", "review.yml"])

    def test_without_a_project_listing_it_falls_back_to_the_files_own_chain(self):
        roots, files = interview_scope(self.read, "review.yml", [])
        self.assertEqual(roots, [])
        self.assertEqual(files, ["review.yml"])


class TestReviewScreenIdentity(unittest.TestCase):
    def test_it_reads_the_screen_the_interview_already_uses(self):
        identity = review_screen_identity(MAIN_YAML)
        self.assertTrue(identity["found"])
        self.assertEqual(identity["id"], "my review screen")
        self.assertEqual(identity["event"], "review_my_form")
        self.assertEqual(identity["question"].strip(), "Check your answers")

    def test_a_file_without_one_is_reported_as_a_first_draft(self):
        self.assertEqual(review_screen_identity("---\nid: x\n"), {"found": False})


NEW_REVIEW = """id: my review screen
event: review_my_form
question: |
  Check your answers
review:
  - Edit: tenants.revisit
    button: |
      **Tenants**
---
id: revisit tenants
continue button field: tenants.revisit
question: |
  Edit your answers about tenants
---
table: tenants.table
rows: tenants
columns:
  - Name: |
      row_item
edit:
  - name.first
"""


class TestSync(unittest.TestCase):
    def test_the_old_review_screen_is_replaced_where_it_stood(self):
        result, replaced = sync_review_screen(MAIN_YAML, NEW_REVIEW)

        self.assertTrue(replaced)
        self.assertEqual(result.count("review:"), 1)
        self.assertIn("Edit: tenants.revisit", result)
        self.assertNotIn("Edit: rent_amount", result)
        # Everything around it survives, in place.
        self.assertLess(result.index("id: intro"), result.index("review:"))
        self.assertLess(result.index("review:"), result.index("id: download"))
        self.assertIn("id: download", result)

    def test_regenerated_tables_are_not_left_behind_in_duplicate(self):
        result, _replaced = sync_review_screen(MAIN_YAML, NEW_REVIEW)
        self.assertEqual(result.count("table: tenants.table"), 1)
        self.assertEqual(result.count("continue button field: tenants.revisit"), 1)
        self.assertIn("Edit your answers about tenants", result)

    def test_a_table_the_draft_says_nothing_about_is_the_authors_own(self):
        source = MAIN_YAML + "\n---\ntable: exhibits.table\nrows: exhibits\n"
        result, _replaced = sync_review_screen(source, NEW_REVIEW)
        self.assertIn("table: exhibits.table", result)

    def test_a_file_with_no_review_screen_gets_the_draft_appended(self):
        source = "---\nid: intro\nquestion: |\n  Hi\n"
        result, replaced = sync_review_screen(source, NEW_REVIEW)
        self.assertFalse(replaced)
        self.assertIn("id: intro", result)
        self.assertTrue(result.rstrip().endswith("- name.first"))


class TestGeneration(unittest.TestCase):
    def test_a_missing_dashboard_is_reported_not_raised_as_an_import_error(self):
        with mock.patch.object(
            review_screen_sync,
            "_load_dashboard_generator",
            side_effect=ALDashboardUnavailable("nope"),
        ):
            with self.assertRaises(ALDashboardUnavailable):
                generate_review_screen_yaml(["---\nid: x\n"])

    def test_the_interviews_own_event_and_id_survive_an_older_dashboard(self):
        def old_dashboard(
            yaml_texts, build_revisit_blocks=True, point_sections_to_review=True
        ):
            return (
                "id: review screen\n"
                "event: review_form\n"
                "question: |\n  Review your answers\n"
                "review:\n"
                "  - Edit: rent_amount\n"
                "    button: |\n      **Rent**\n"
            )

        with mock.patch.object(
            review_screen_sync, "_load_dashboard_generator", return_value=old_dashboard
        ):
            result = generate_review_screen_yaml(
                ["---\nid: x\n"],
                screen_id="my review screen",
                event_name="review_my_form",
                question_text="Check your answers\n",
            )

        self.assertIn("review_my_form", result)
        self.assertNotIn("review_form\n", result.replace("review_my_form", ""))
        self.assertIn("my review screen", result)
        self.assertIn("Check your answers", result)

    def test_a_newer_dashboard_is_asked_for_the_names_directly(self):
        seen = {}

        def new_dashboard(
            yaml_texts,
            build_revisit_blocks=True,
            point_sections_to_review=True,
            review_id=None,
            review_event_name=None,
            review_question=None,
        ):
            seen.update(
                {
                    "review_id": review_id,
                    "review_event_name": review_event_name,
                    "review_question": review_question,
                    "point_sections_to_review": point_sections_to_review,
                }
            )
            return "id: review screen\nreview: []\n"

        with mock.patch.object(
            review_screen_sync, "_load_dashboard_generator", return_value=new_dashboard
        ):
            generate_review_screen_yaml(
                ["---\nid: x\n"],
                screen_id="my review screen",
                event_name="review_my_form",
                question_text="Check your answers",
            )

        self.assertEqual(seen["review_id"], "my review screen")
        self.assertEqual(seen["review_event_name"], "review_my_form")
        self.assertEqual(seen["review_question"], "Check your answers")
        # The Weaver's `sections:` are navigation headings, not events.
        self.assertFalse(seen["point_sections_to_review"])


if __name__ == "__main__":
    unittest.main()
