# do not pre-load

import os
import tempfile
import unittest
from unittest import mock

from . import variable_report
from .variable_report import (
    ALDashboardUnavailable,
    court_form_options,
    supports_court_form_shapes,
    write_variable_report_docx,
)

SAMPLE_YAML = """---
id: intro
question: |
  Tell us about your case
fields:
  - Docket number: docket_number
"""


class _FakeDashboard:
    """Stands in for ALDashboard's generator, recording how it was called.

    ALDashboard is an optional dependency and is not installed in the Weaver's
    test environment, which is exactly the condition these tests care about.
    """

    def __init__(self, court_shapes: bool = True):
        self.court_shapes = court_shapes
        self.calls = []

    def generate(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        output_path = kwargs.get("output_docx_path")
        if output_path:
            with open(output_path, "wb") as handle:
                handle.write(b"docx bytes")
        result = {
            "variables_count": 4,
            "list_count": 1,
            "scalar_count": 3,
            "shape": kwargs.get("shape", "intake"),
        }
        if kwargs.get("shape") and kwargs["shape"] != "intake":
            result.update(
                {
                    "profile_id": kwargs.get("court_profile") or "generic",
                    "profile_name": "Massachusetts Trial Court",
                    "sections": {"caption": "yaml", "signature": "yaml"},
                }
            )
        return result

    def shapes(self):
        return [
            {"value": "intake", "label": "Intake summary"},
            {"value": "motion", "label": "Motion"},
        ]

    def profiles(self):
        return [
            {"value": "generic", "label": "Generic court form"},
            {"value": "ma_trial_court", "label": "Massachusetts Trial Court"},
        ]

    def install(self, test_case):
        test_case.enterContext(
            mock.patch.object(
                variable_report,
                "_load_dashboard_report",
                return_value=(None, self.generate),
            )
        )
        loaded = (self.shapes, self.profiles) if self.court_shapes else None
        test_case.enterContext(
            mock.patch.object(
                variable_report, "_load_dashboard_court_forms", return_value=loaded
            )
        )


class TestCourtFormOptions(unittest.TestCase):
    def test_options_come_from_the_installed_dashboard(self):
        _FakeDashboard().install(self)
        options = court_form_options()
        self.assertTrue(options["supported"])
        self.assertIn("motion", {shape["value"] for shape in options["shapes"]})
        self.assertIn("ma_trial_court", {item["value"] for item in options["profiles"]})
        self.assertTrue(supports_court_form_shapes())

    def test_an_older_dashboard_reports_no_court_shapes(self):
        _FakeDashboard(court_shapes=False).install(self)
        options = court_form_options()
        self.assertFalse(options["supported"])
        self.assertEqual(options["shapes"], [])
        self.assertEqual(options["profiles"], [])
        self.assertFalse(supports_court_form_shapes())

    def test_a_broken_profile_on_the_server_is_not_fatal(self):
        def explode():
            raise RuntimeError("malformed profile")

        with mock.patch.object(
            variable_report,
            "_load_dashboard_court_forms",
            return_value=(explode, explode),
        ):
            self.assertFalse(court_form_options()["supported"])


class TestWriteVariableReportDocx(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="weaver_variable_report_")

    def _path(self, name="draft.docx"):
        return os.path.join(self.tempdir, name)

    def test_intake_is_the_default_and_asks_for_no_shape(self):
        """The original behavior has to survive: the Dashboard's own default."""
        fake = _FakeDashboard()
        fake.install(self)
        summary = write_variable_report_docx(
            [SAMPLE_YAML], self._path(), report_title="Main Draft"
        )
        _texts, kwargs = fake.calls[0]
        self.assertNotIn("shape", kwargs)
        self.assertNotIn("court_profile", kwargs)
        self.assertEqual(summary["shape"], "intake")
        self.assertEqual(summary["variables_count"], 4)
        self.assertNotIn("profile_id", summary)

    def test_a_court_shape_passes_the_profile_through(self):
        fake = _FakeDashboard()
        fake.install(self)
        summary = write_variable_report_docx(
            [SAMPLE_YAML],
            self._path(),
            report_title="Motion to Vacate",
            shape="motion",
            court_profile="ma_trial_court",
            include_certificate_of_service=True,
        )
        _texts, kwargs = fake.calls[0]
        self.assertEqual(kwargs["shape"], "motion")
        self.assertEqual(kwargs["court_profile"], "ma_trial_court")
        self.assertIs(kwargs["include_certificate_of_service"], True)
        self.assertEqual(summary["profile_id"], "ma_trial_court")
        self.assertEqual(summary["profile_name"], "Massachusetts Trial Court")
        self.assertEqual(summary["sections"]["caption"], "yaml")

    def test_certificate_of_service_is_omitted_when_not_chosen(self):
        fake = _FakeDashboard()
        fake.install(self)
        write_variable_report_docx(
            [SAMPLE_YAML], self._path(), shape="motion", court_profile="generic"
        )
        _texts, kwargs = fake.calls[0]
        self.assertNotIn("include_certificate_of_service", kwargs)

    def test_a_court_shape_against_an_older_dashboard_explains_itself(self):
        _FakeDashboard(court_shapes=False).install(self)
        with self.assertRaises(ALDashboardUnavailable) as caught:
            write_variable_report_docx([SAMPLE_YAML], self._path(), shape="motion")
        self.assertIn("newer ALDashboard", str(caught.exception))

    def test_the_intake_report_still_works_against_an_older_dashboard(self):
        fake = _FakeDashboard(court_shapes=False)
        fake.install(self)
        summary = write_variable_report_docx([SAMPLE_YAML], self._path())
        self.assertEqual(summary["variables_count"], 4)
        self.assertGreater(summary["size"], 0)

    def test_empty_yaml_is_rejected_before_the_dashboard_is_called(self):
        fake = _FakeDashboard()
        fake.install(self)
        with self.assertRaises(ValueError):
            write_variable_report_docx(["", "   "], self._path())
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
