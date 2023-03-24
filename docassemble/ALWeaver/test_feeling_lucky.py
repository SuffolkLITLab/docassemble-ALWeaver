import unittest
from .interview_generator import (
    DAInterview,
)
from docassemble.base.util import DAStaticFile
import docassemble.base.functions
from pathlib import Path


class MockDAStaticFile(DAStaticFile):
    def init(self, *pargs, **kwargs):
        if "full_path" in kwargs:
            full_path = kwargs["full_path"]
            self.full_path = str(full_path)
            if isinstance(full_path, Path):
                kwargs["filename"] = full_path.name
                kwargs["extension"] = full_path.suffix[1:]
            else:
                kwargs["filename"] = self.full_path.split("/")[-1]
                kwargs["extension"] = self.full_path.split(".")[-1]
            if kwargs["extension"] == "pdf":
                kwargs["mimetype"] = "application/pdf"
        super().init(*pargs, **kwargs)

    def path(self):
        return self.full_path


class test_feeling_lucky(unittest.TestCase):
    def test_load_fields(self):
        test_lucky_pdf = (
            Path(__file__).parent / "test/test_petition_to_enforce_sanitary_code.pdf"
        )
        docassemble.base.functions.this_thread.current_question = type("", (), {})
        docassemble.base.functions.this_thread.current_question.package = "ALWeaver"
        da_pdf = MockDAStaticFile(
            full_path=str(test_lucky_pdf), extension="pdf", mimetype="application/pdf"
        )

        interview = DAInterview()
        interview.auto_assign_attributes(input_file=da_pdf)
        self.assertEqual(len(interview.all_fields), 36)
        self.assertEqual(len(interview.all_fields.builtins()), 24)


if __name__ == "__main__":
    unittest.main()
