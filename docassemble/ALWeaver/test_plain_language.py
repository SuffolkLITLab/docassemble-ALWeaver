import unittest

from .plain_language import flags_by_text, is_filler_subquestion, plain_language_flags


class TestFillerSubquestions(unittest.TestCase):
    def test_restating_the_screen_is_filler(self):
        for text in [
            "Type your contact information below.",
            "Confirm the method of filing and any related documents.",
            "Have the appeal issues, case decisions, facts, arguments, and result you want ready.",
            "Please provide the following information",
            "Tell us more about your case.",
        ]:
            with self.subTest(text=text):
                self.assertTrue(is_filler_subquestion(text))

    def test_help_answering_is_kept(self):
        for text in [
            "Enter the docket number. You can find it at the top of any court paper.",
            "List every child, even if they are over 18.",
            "The court uses this to decide if you can file for free.",
            "Check all that apply.",
            "Answer each of the following questions in a few sentences.",
            "Provide at least one other way for the court to reach you.",
            "Use the address where you get mail.",
        ]:
            with self.subTest(text=text):
                self.assertFalse(is_filler_subquestion(text))

    def test_mako_is_never_dropped(self):
        self.assertFalse(is_filler_subquestion("Enter ${ users[0] }'s address."))
        self.assertFalse(is_filler_subquestion(""))


class TestPlainLanguageFlags(unittest.TestCase):
    def test_flags_formal_words_and_their_endings(self):
        words = [
            word
            for word, _ in plain_language_flags(
                "Date you obtained the order prior to filing"
            )
        ]
        self.assertIn("prior to", words)
        self.assertIn("obtained", words)
        self.assertEqual(
            [word for word, _ in plain_language_flags("Date the order was submitted")],
            ["submitted"],
        )
        self.assertEqual(
            [word for word, _ in plain_language_flags("Providing your address")],
            ["Providing"],
        )

    def test_flags_words_the_table_is_missing(self):
        self.assertEqual(
            [word for word, _ in plain_language_flags("Legal arguments presented")],
            ["presented"],
        )

    def test_flags_legal_words_even_when_the_form_uses_them(self):
        # Complex forms use plenty of legal words; the draft should still be plain
        self.assertTrue(
            plain_language_flags("Commence the action pursuant to the rule")
        )

    def test_plain_text_and_contextual_words_are_not_flagged(self):
        for text in ["Your email address", "Use your home address", "Your request"]:
            with self.subTest(text=text):
                self.assertEqual(plain_language_flags(text), [])

    def test_flags_by_text_only_lists_texts_with_flags(self):
        flagged = flags_by_text(["Your email", "Date obtained"])
        self.assertEqual(list(flagged), ["Date obtained"])


if __name__ == "__main__":
    unittest.main()
