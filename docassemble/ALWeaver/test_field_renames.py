# do not pre-load
"""Renaming a PDF's fields must never make the interview worse.

FormFyxer's renamer rewrites every field: it drops the index from
`users1_name_first` and breaks ties with a `__1`/`__2` suffix, which is the
Weaver's multiple-appearance marker, so the fields it disambiguates end up
writing the same answer. `suggested_field_renames` narrows it to the names
that actually need help, and these are the properties that has to hold.

`test/real_pdf_field_names.json` holds the AcroForm field names of 38 court
forms from the SuffolkLITLab packages, so the checks stay tied to shapes that
actually turn up.
"""

import collections
import json
import random
import unittest
from pathlib import Path

from .interview_generator import (
    ParsingException,
    field_name_is_usable,
    map_raw_to_final_display,
    remove_multiple_appearance_indicator,
    suggested_field_renames,
    varname,
)


class TestSuggestedRenamesFuzzing(unittest.TestCase):
    """Generated field names, checked for the two ways renaming can hurt.

    Renaming is only worth offering if it cannot make things worse: it must
    never touch a name that already works, and it must never put two fields on
    the same variable.
    """

    PIECES = [
        # human-readable labels, the case renaming is actually for
        "Name",
        "Your Name",
        "Printed Name",
        "Signature",
        "Date",
        "DOB",
        "City State Zip",
        "Case No",
        "Address",
        "Phone",
        "Email",
        # machine-generated names
        "Text1",
        "Text2",
        "untitled",
        "Field",
        "form1[0].Page1[0].Text[0]",
        # names that already work
        "users1_name_first",
        "users2_name_first",
        "docket_number",
        "signature_date",
        "inspector_name",
        "patient1_phone_number",
        # awkward pieces
        "",
        "  ",
        "1",
        "#",
        "a b c",
        "ALL CAPS",
        "Mixed_Case",
    ]

    def _names(self, rng):
        """A PDF's field names, which an AcroForm keeps unique."""
        count = rng.randint(1, 10)
        chosen = []
        for _ in range(count):
            piece = rng.choice(self.PIECES)
            if piece not in chosen:
                chosen.append(piece)
        return chosen

    def test_renaming_never_touches_a_usable_name(self):
        rng = random.Random(4242)
        for round_number in range(80):
            names = self._names(rng)
            with self.subTest(round=round_number, names=names):
                for old_name, new_name in suggested_field_renames(names):
                    self.assertFalse(field_name_is_usable(old_name), old_name)
                    # A field named "  " normalizes to "_", which helps nobody
                    self.assertTrue(field_name_is_usable(new_name), new_name)
                    self.assertRegex(new_name, r"^[a-z][a-z0-9_]*$")

    def test_renaming_never_creates_a_collision(self):
        rng = random.Random(99)
        for round_number in range(80):
            names = self._names(rng)
            with self.subTest(round=round_number, names=names):
                renames = dict(suggested_field_renames(names))
                if not renames:
                    continue
                before = collections.Counter(_variable_for(name) for name in names)
                after = collections.Counter(
                    _variable_for(renames.get(name, name)) for name in names
                )
                for variable, count in after.items():
                    self.assertLessEqual(count, max(1, before[variable]), variable)

    def test_a_rename_is_never_proposed_twice_for_one_variable(self):
        rng = random.Random(5)
        for round_number in range(60):
            names = self._names(rng)
            with self.subTest(round=round_number, names=names):
                targets = [new for _old, new in suggested_field_renames(names)]
                self.assertEqual(len(targets), len(set(targets)), targets)


class TestAgainstRealPdfFieldNames(unittest.TestCase):
    """The same properties, over real court forms."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / "test/real_pdf_field_names.json"
        cls.corpus = json.loads(path.read_text(encoding="utf-8"))

    def test_renaming_leaves_usable_names_alone(self):
        for form, field_names in self.corpus.items():
            with self.subTest(form=form):
                for old_name, new_name in suggested_field_renames(field_names):
                    self.assertFalse(field_name_is_usable(old_name), old_name)
                    self.assertRegex(new_name, r"^[a-z][a-z0-9_]*$")
                    # `__1` is the Weaver's multiple-appearance marker, which it
                    # strips back off, merging the fields it disambiguated
                    self.assertNotRegex(new_name, r"__\d+$")

    def test_renaming_never_makes_two_fields_share_a_variable(self):
        for form, field_names in self.corpus.items():
            with self.subTest(form=form):
                renames = dict(suggested_field_renames(field_names))
                if not renames:
                    continue
                before = collections.Counter(
                    _variable_for(name) for name in field_names
                )
                after = collections.Counter(
                    _variable_for(renames.get(name, name)) for name in field_names
                )
                for variable, count in after.items():
                    self.assertLessEqual(
                        count,
                        max(1, before[variable]),
                        f"{form}: renaming crowded {variable}",
                    )


def _variable_for(field_name):
    stripped = remove_multiple_appearance_indicator(varname(field_name))
    try:
        return map_raw_to_final_display(stripped)
    except ParsingException:
        return stripped
