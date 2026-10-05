# do not pre-load
import unittest

from .titles import title_from_filename


class TestTitleFromFilename(unittest.TestCase):
    def test_real_upload_names(self):
        """Filenames from published MA interviews, and the titles they give."""
        expected = {
            "petition_to_name_change_minor_cjp25_fielded.pdf": "Petition to name change minor CJP 25",
            "Interpreternotice-with variables.docx": "Interpreternotice",
            "Petition-to-deem-satisfied-v1.3.pdf": "Petition to deem satisfied",
            "generic_motion_family_law_re-labeled.docx": "Generic motion family law",
            "guardians_care_plan_report_mpc_821.pdf": "Guardians care plan report MPC 821",
            "209A_plaintiff_s_motion_to_modify.pdf": "209A plaintiff's motion to modify",
            "93A_demand_letter_sample-labeled-highlighted (1).docx": "93A demand letter sample",
            "CJP_34_Docassemble_project.pdf": "CJP 34",
            "Motion_to_Reconsider.docx": "Motion to reconsider",
        }
        for filename, title in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(title_from_filename(filename), title)

    def test_a_name_that_is_only_upload_words_is_kept(self):
        self.assertEqual(title_from_filename("template.pdf"), "Template")
        self.assertEqual(title_from_filename("Final Draft.pdf"), "Final draft")

    def test_long_numbers_are_not_form_numbers(self):
        self.assertEqual(
            title_from_filename("form_eoir28_omb11250006.pdf"),
            "Form EOIR 28 omb11250006",
        )
