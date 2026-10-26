# do not pre-load
"""Regression checks for the expanded field contracts, through real imports."""

from pathlib import Path
import tempfile
import unittest

from docx import Document

from .interview_generator import (
    generate_interview_from_path,
    map_raw_to_final_display,
    docx_variables_in_order,
)
from .question_library import library_catalog, singular_label
from .test_generate_from_path import _build_pdf_with_fields, _build_pdf_with_typed_field


class TestExpandedVariables(unittest.TestCase):
    def generate(self, labels, *, docx=False, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ("sample.docx" if docx else "sample.pdf")
            if docx:
                document = Document()
                for label in labels:
                    document.add_paragraph("{{ " + label + " }}")
                document.save(path)
            else:
                _build_pdf_with_fields(str(path), labels)
            result = generate_interview_from_path(
                str(path),
                output_dir=directory,
                create_package_zip=False,
                include_next_steps=False,
                **kwargs
            )
            return Path(result.yaml_path).read_text()

    def test_grandchildren_full_name_only(self):
        self.assertEqual(
            map_raw_to_final_display("grandchildren1_name"), "grandchildren[0]"
        )
        self.assertEqual(singular_label("grandchildren"), "grandchild")
        source = self.generate(["grandchildren1_name", "grandchildren2_name"])
        self.assertIn("grandchildren: ALPeopleList", source)
        self.assertIn("grandchildren[i].name_fields()", source)

    def test_service_attributes(self):
        self.assertEqual(
            map_raw_to_final_display("users1_service_address_block"),
            "users[0].service_address.block()",
        )
        source = self.generate(
            ["users1_service_address_block", "users1_service_method", "service_date"]
        )
        self.assertIn("users[0].service_address.address", source)
        self.assertIn("users[0].service_method", source)
        self.assertIn("datatype: date", source)
        self.assertEqual(
            docx_variables_in_order("{{ users[0].service_address.block() }}"),
            ["users[0].service_address.address"],
        )

    def test_name_and_address_dependencies(self):
        self.assertEqual(
            map_raw_to_final_display("users1_address_block"), "users[0].address.block()"
        )
        self.assertEqual(
            map_raw_to_final_display("users1_name_and_address_block"),
            "users[0].address_block()",
        )
        self.assertEqual(
            docx_variables_in_order("{{ users[0].address_block() }}"),
            ["users[0].name.first", "users[0].address.address"],
        )
        source = self.generate(["users1_name_and_address_block"])
        self.assertIn("users[i].name_fields()", source)
        self.assertIn("users.gather()", source)
        self.assertIn("users[i].address_fields(", source)
        self.assertIn("users[0].address.address", source)
        self.assertIn("users[0].address_block()", source)

    def test_declared_address_pdf_and_docx(self):
        for docx, labels in [
            (False, ["property_address_city", "property_address_block"]),
            (True, ["property_address.city", "property_address.block()"]),
            (True, ["property_address.block()"]),
            (True, ["property_address.address"]),
            (False, ["property_address.city", "property_address.block()"]),
        ]:
            with self.subTest(docx=docx):
                source = self.generate(
                    labels,
                    docx=docx,
                    interview_overrides={
                        "object_types": {"property_address": "ALAddress"}
                    },
                )
                self.assertIn("property_address: ALAddress", source)
                self.assertIn("property_address.address_fields(", source)
                self.assertNotIn("property_address.name", source)
                self.assertNotIn("property_address.address.address", source)
                self.assertNotIn("property_address: ALIndividual", source)
                self.assertIn("Edit: property_address.address", source)

    def test_address_catalog(self):
        catalog = library_catalog(
            [{"name": "incident_location", "class_name": "ALAddress"}]
        )
        self.assertEqual(
            [q["kind"] for q in catalog[0]["questions"]], ["standalone_address"]
        )
        self.assertIn(
            "incident_location.address_fields(", catalog[0]["questions"][0]["yaml"]
        )

    def test_circuit_survives_jurisdiction_details(self):
        source = self.generate(["trial_court_circuit"], jurisdiction="Massachusetts")
        self.assertIn("trial_court_circuit", source)
        self.assertIn("Circuit (leave blank if not applicable)", source)
        self.assertIn("required: False", source)
        self.assertNotIn("trial_court.circuit", source)

    def test_circuit_checkbox_stays_a_checkbox(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _build_pdf_with_typed_field(
                str(Path(directory) / "court.pdf"), "trial_court_circuit", "/Btn"
            )
            result = generate_interview_from_path(
                path,
                output_dir=directory,
                create_package_zip=False,
                include_next_steps=False,
            )
            source = Path(result.yaml_path).read_text()
        self.assertNotIn("Circuit (leave blank if not applicable)", source)
        self.assertIn("datatype: yesno", source)

    def test_existing_singleton_name_and_address_stays_a_person(self):
        # Shapes from MAEvictionDefense and ssareportchangesletter templates.
        for name in ("client", "tenant", "landlords_attorney"):
            with self.subTest(name=name):
                source = self.generate([name, name + ".address_block()"], docx=True)
                self.assertIn(name + ": ALIndividual", source)
                self.assertNotIn(name + ": ALPeopleList", source)
                self.assertNotIn(name + ".gather()", source)
                self.assertNotIn("Edit: " + name + "\n", source)
                self.assertIn(name + ".name.first", source)

    def test_service_fields_alone_do_not_invent_people(self):
        from .test_person_heuristics import candidates_for

        self.assertNotIn("notice", candidates_for(["notice_service_method"]))
        self.assertNotIn(
            "courier",
            candidates_for(["courier_service_method", "courier_service_address_city"]),
        )
        self.assertIn(
            "courier",
            candidates_for(["courier1_name_first", "courier1_service_method"]),
        )

    def test_address_override_replaces_guessed_screens_and_people(self):
        import yaml

        source = self.generate(
            [
                "property_address_city",
                "property_address_zip",
                "property_address_county",
                "case_notes",
            ],
            interview_overrides={"object_types": {"property_address": "ALAddress"}},
        )
        blocks = list(yaml.safe_load_all(source))
        ids = [b["id"] for b in blocks if isinstance(b, dict) and "id" in b]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("property: ALPeopleList", source)
        self.assertNotIn("property[0]", source)
        self.assertIn("property_address.county", source)
        self.assertEqual(source.count("Edit: property_address.address"), 1)
        self.assertNotIn('"Property address city": property_address.address', source)

    def test_service_address_prefix_is_not_an_attribute_match(self):
        self.assertEqual(
            docx_variables_in_order(
                "{{ notice.service_addresses }} {{ notice.service_address_confirmed }}"
            ),
            ["notice.service_addresses", "notice.service_address_confirmed"],
        )

    def test_authored_circuit_field_definition_takes_precedence(self):
        source = self.generate(
            ["trial_court_circuit"],
            field_definitions=[
                {
                    "field": "trial_court_circuit",
                    "label": "Your circuit",
                    "datatype": "text",
                    "required": True,
                }
            ],
        )
        self.assertNotIn("Circuit (leave blank if not applicable)", source)
        self.assertIn("Your circuit", source)

    def test_name_dependency_survives_address_trigger_deduplication(self):
        source = self.generate(["users1_address_city", "users1_name_and_address_block"])
        self.assertIn("users.gather()", source)

    def test_docx_loop_name_and_address_collects_both_per_person(self):
        from .interview_generator import get_docx_loop_attribute_hints

        self.assertEqual(
            get_docx_loop_attribute_hints(
                "{% for person in other_parties %}{{ person.address_block() }}{% endfor %}"
            ),
            {"other_parties": ["name.first", "address.address"]},
        )

    def test_authored_address_and_circuit_screens(self):
        source = self.generate(
            [
                "property_address_city",
                "property_address_address",
                "trial_court_circuit",
            ],
            interview_overrides={"object_types": {"property_address": "ALAddress"}},
            screen_definitions=[
                {
                    "question": "My location wording",
                    "fields": [
                        {"field": "property_address_address", "label": "Street"},
                        {"field": "property_address_city", "label": "Town"},
                        {"field": "trial_court_circuit", "label": "My circuit wording"},
                    ],
                }
            ],
        )
        self.assertIn('"Town": property_address.city', source)
        self.assertIn('"Street": property_address.address', source)
        self.assertNotIn("property_address.address_fields(", source)
        self.assertNotIn("Circuit (leave blank if not applicable)", source)
        self.assertIn('"My circuit wording": trial_court_circuit', source)
