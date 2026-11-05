"""Exercise the bundled next-steps shells as generated interviews use them."""

from pathlib import Path

import pytest
from docx import Document
from docxtpl import DocxTemplate
from jinja2 import Environment, StrictUndefined

from .interview_generator import _runtime_next_steps_template


@pytest.mark.parametrize(
    "form_type",
    ["appeal", "existing_case", "letter", "other", "other_form", "starts_case"],
)
@pytest.mark.parametrize("enabled", [False, True])
def test_next_steps_runtime_headings_and_independent_custom_sections(
    tmp_path, form_type, enabled
):
    source = Path(__file__).parent / "data/templates" / f"next_steps_{form_type}.docx"
    runtime = Path(_runtime_next_steps_template(str(source)))
    try:
        context = {
            "al_next_steps_intro_prompt": "Your next steps",
            "al_next_steps_document_title": "your completed papers",
            "al_next_steps_enabled": enabled,
            "al_next_steps_what_happens_next": "",
            "al_next_steps_what_can_decision_maker_do": "",
            # This must appear independently of the preceding empty section.
            "al_next_steps_what_happens_if_i_win": "Keep the signed order",
            "al_next_steps_help_url": "",
            "al_next_steps_generate_qr_code": False,
            "fix_punctuation": lambda text: text.rstrip(".") + ".",
        }
        context["showifdef"] = lambda name, default="": context.get(name, default)
        document = DocxTemplate(str(runtime))
        environment = Environment(undefined=StrictUndefined)
        environment.filters["markdown"] = lambda value: value
        document.render(context, jinja_env=environment)
        output = tmp_path / "rendered.docx"
        document.save(output)
        paragraphs = Document(output).paragraphs
        headings = [p for p in paragraphs if p.style.name.startswith("Heading")]
        assert headings[0].style.name == "Heading 1"
        assert headings[0].text == "Your next steps"
        assert all(p.style.name == "Heading 2" for p in headings[1:])
        text = "\n".join(p.text for p in paragraphs)
        assert ("Keep the signed order." in text) is enabled
        assert "{{" not in text and "{%" not in text
        assert "30 days" not in text
    finally:
        runtime.unlink(missing_ok=True)
