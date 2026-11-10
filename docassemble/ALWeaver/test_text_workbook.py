# do not pre-load
from io import BytesIO
import json

import openpyxl
import pytest
import yaml

from .text_workbook import (
    export_workbook,
    import_workbook,
    protected_parts,
    text_inventory,
    validate_wording,
)

SOURCE = """# Keep my comment
---
id: greeting
question: Hello ${ users[0] }
subquestion: | # Keep this too
  % if eligible:
  Welcome, ${ users[0] }.
  % endif
fields:
  - Your name: user_name
    hint: First and last name
    required: true
  - label: Favorite color
    field: color
    choices:
      - Red: red_value
      - Blue: blue_value
---
metadata:
  title: Not editable metadata
---
code: |
  secret = 'Not editable Python'
"""


def edit_workbook(raw, edits):
    book = openpyxl.load_workbook(BytesIO(raw))
    for sheet in book:
        if sheet.title.startswith("Screen "):
            for row in sheet.iter_rows(min_row=4):
                if row[1].value in edits:
                    row[2].value = edits[row[1].value]
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def test_inventory_only_display_text():
    items = text_inventory("main.yml", SOURCE)
    values = [i["original"] for i in items]
    assert "Your name" in values and "Red" in values
    assert "red_value" not in values and "user_name" not in values
    assert not any("Not editable" in text for text in values)


def test_round_trip_preserves_source_and_allows_expression_movement():
    raw = export_workbook({"main.yml": SOURCE}, {})
    assert import_workbook(raw, {"main.yml": SOURCE})["updated"] == {}
    changed = edit_workbook(
        raw, {"Hello ${ users[0] }": "${ users[0] }, hello!", "Your name": "Full name"}
    )
    result = import_workbook(changed, {"main.yml": SOURCE})
    updated = result["updated"]["main.yml"]
    assert updated == SOURCE.replace(
        "Hello ${ users[0] }", '"${ users[0] }, hello!"'
    ).replace("Your name:", "Full name:")
    assert len(result["changes"]) == 2


def test_rejects_code_changes_and_stale_source():
    raw = export_workbook({"main.yml": SOURCE}, {})
    changed = edit_workbook(raw, {"Hello ${ users[0] }": "Hello ${ users[1] }"})
    with pytest.raises(ValueError, match="Highlighted"):
        import_workbook(changed, {"main.yml": SOURCE})
    with pytest.raises(ValueError, match="Source changed"):
        import_workbook(raw, {"main.yml": SOURCE + "# external change\n"})


def test_nested_expression_and_control_regions():
    text = 'Hi ${ {"}": users[0]}["}"] }!'
    assert "".join(p for p, _ in protected_parts(text)) == text
    validate_wording(text, 'Welcome ${ {"}": users[0]}["}"] }!')
    with pytest.raises(ValueError):
        validate_wording(
            "% if ok:\n${ name }\n% endif\n", "${ name }\n% if ok:\n\n% endif\n"
        )


def test_multiline_blank_and_formula_text():
    source = 'question: "Hello" # comment\nsubquestion: |\n  Old text.\nyesno: done\n'
    raw = export_workbook({"main.yml": source}, {})
    edited = edit_workbook(
        raw, {"Hello": "", "Old text.\n": "New text.\n\nMore text.\n"}
    )
    updated = import_workbook(edited, {"main.yml": source})["updated"]["main.yml"]
    assert "# comment" in updated
    data = yaml.safe_load(updated)
    assert data["question"] == ""
    assert data["subquestion"] == "New text.\n\nMore text.\n"
    bad = edit_workbook(raw, {"Hello": '=HYPERLINK("https://example.org")'})
    with pytest.raises(ValueError, match="formula"):
        import_workbook(bad, {"main.yml": source})


def test_missing_rows_and_duplicate_ids_rejected():
    raw = export_workbook({"main.yml": SOURCE}, {})
    book = openpyxl.load_workbook(BytesIO(raw))
    book["Screen 001"].delete_rows(4)
    out = BytesIO()
    book.save(out)
    with pytest.raises(ValueError, match="removed"):
        import_workbook(out.getvalue(), {"main.yml": SOURCE})


def test_scalar_choice_preserves_stored_value_and_reserved_labels_rejected():
    source = "question: Choose\nfield: color\nchoices:\n  - Red\n  - Blue\n"
    raw = export_workbook({"main.yml": source}, {})
    changed = edit_workbook(raw, {"Red": "Scarlet"})
    updated = import_workbook(changed, {"main.yml": source})["updated"]["main.yml"]
    assert yaml.safe_load(updated)["choices"][0] == {"Scarlet": "Red"}
    raw = export_workbook({"main.yml": SOURCE}, {})
    with pytest.raises(ValueError, match="directive"):
        import_workbook(edit_workbook(raw, {"Your name": "code"}), {"main.yml": SOURCE})


def test_png_is_embedded_and_highlighting_survives_export():
    import base64
    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (320, 200), "white").save(image, format="PNG")
    raw = export_workbook(
        {"main.yml": SOURCE},
        {"main.yml#0": base64.b64encode(image.getvalue()).decode()},
    )
    book = openpyxl.load_workbook(BytesIO(raw), rich_text=True)
    assert len(book["Screen 001"]._images) == 1
    assert book["Screen 001"]["C4"].value[1].font.color.rgb == "FF0000FF"
    assert book["_ALWeaver"].sheet_state == "hidden"
    assert book["Screen 001"]["C4"].protection.locked is False
    assert book["Screen 001"]["B4"].protection.locked is True


def test_duplicate_edited_labels_do_not_overwrite_fields():
    source = "question: Name\nfields:\n  - First: first\n    hint: Your given name\n"
    raw = export_workbook({"main.yml": source}, {})
    with pytest.raises(ValueError):
        import_workbook(edit_workbook(raw, {"First": "hint"}), {"main.yml": source})


def test_unicode_comments_multiple_files_and_duplicate_wording():
    sources = {
        "one.yml": "question: Café\nsubquestion: Hello\nyesno: ready\n",
        "two.yml": "# दूसरे\nquestion: Hello\nyesno: other\n",
    }
    raw = export_workbook(sources, {})
    changed = edit_workbook(raw, {"Hello": "Good morning"})
    result = import_workbook(changed, sources)
    assert len(result["changes"]) == 2
    assert "# दूसरे" in result["updated"]["two.yml"]
    assert "Café" in result["updated"]["one.yml"]


def test_python_block_delimiter_in_string_is_still_protected():
    original = "<% x = '%>'; y = 2 %>Hello ${ x }"
    assert protected_parts(original)[0] == ("<% x = '%>'; y = 2 %>", 1)
    with pytest.raises(ValueError, match="Highlighted"):
        validate_wording(original, "<% x = '%>'; y = 3 %>Hello ${ x }")


def test_legacy_intro_readonly_and_action_title_roundtrip():
    from .test_interview_scan import LEGACY
    from .interview_scan import scan_interview
    from .text_workbook import workbook_context, workbook_screens

    context = workbook_context(
        scan_interview(LEGACY.__getitem__, "standalone.yml"), LEGACY
    )
    screens = workbook_screens(LEGACY, context)
    assert screens[0]["data"]["question"] == "${ interview_short_title }"
    assert screens[-1]["data"]["question"] == "Download your forms"
    raw = export_workbook(LEGACY, {}, context=context)
    edited = edit_workbook(raw, {"Ask for help": "Get help today"})
    result = import_workbook(edited, LEGACY, context=context)
    assert result["updated"] == {
        "reusable.yml": LEGACY["reusable.yml"].replace(
            "'Ask for help'", "'Get help today'"
        )
    }
    edited = edit_workbook(raw, {"Shared instructions.": "Changed shared wording"})
    with pytest.raises(ValueError, match="read.only"):
        import_workbook(edited, LEGACY, context=context)


def test_unicode_action_title_exact_patch_and_computed_title_excluded():
    source = 'code: | # Keep\n  café = 1; interview_short_title = "Ask for help" # Keep too\n'
    raw = export_workbook({"main.yml": source}, {})
    result = import_workbook(
        edit_workbook(raw, {"Ask for help": "Help me"}), {"main.yml": source}
    )
    assert result["updated"]["main.yml"] == source.replace(
        '"Ask for help"', "'Help me'"
    )
    assert not text_inventory(
        "main.yml", "code: |\n  interview_short_title = make_title()\n"
    )


SEQUENCE_SOURCE = """question: |
  Before

subquestion: Next
fields:
  - note: |
      A note

  - Pick: pick
    choices:
      - label: Apple label
        value: apple
      - Leave: leave
        url: https://example.com
  - no label: hidden_answer
"""


def test_block_text_under_sequence_item_keeps_indent_and_blank_lines():
    raw = export_workbook({"main.yml": SEQUENCE_SOURCE}, {})
    changed = edit_workbook(
        raw, {"A note\n": "A new note\non two lines\n", "Before\n": "After\n"}
    )
    updated = import_workbook(changed, {"main.yml": SEQUENCE_SOURCE})["updated"]
    source = updated["main.yml"]
    assert source == SEQUENCE_SOURCE.replace("Before", "After").replace(
        "      A note\n", "      A new note\n      on two lines\n"
    )
    data = yaml.safe_load(source)
    assert data["fields"][0]["note"] == "A new note\non two lines\n"


def test_block_text_with_leading_spaces_becomes_quoted():
    raw = export_workbook({"main.yml": SEQUENCE_SOURCE}, {})
    changed = edit_workbook(raw, {"A note\n": "  indented"})
    source = import_workbook(changed, {"main.yml": SEQUENCE_SOURCE})["updated"][
        "main.yml"
    ]
    assert '- note: "  indented"\n\n  - Pick' in source
    assert yaml.safe_load(source)["fields"][0]["note"] == "  indented"


def test_label_value_choices_offer_the_label_not_option_keys():
    values = {i["original"] for i in text_inventory("main.yml", SEQUENCE_SOURCE)}
    assert {"Apple label", "Leave"} <= values
    assert not values & {"label", "value", "url", "no label"}
    raw = export_workbook({"main.yml": SEQUENCE_SOURCE}, {})
    changed = edit_workbook(raw, {"Apple label": "Green apple"})
    source = import_workbook(changed, {"main.yml": SEQUENCE_SOURCE})["updated"][
        "main.yml"
    ]
    assert yaml.safe_load(source)["fields"][1]["choices"][0] == {
        "label": "Green apple",
        "value": "apple",
    }


def test_directives_with_arguments_are_protected():
    assert ("[FILE docassemble.demo:a.png, 50%]", 2) in protected_parts(
        "See [FILE docassemble.demo:a.png, 50%] here"
    )
    with pytest.raises(ValueError):
        validate_wording("[TARGET help] text", "[TARGET other] text")


def test_empty_wording_roundtrips_as_empty_string_or_blank_cell():
    sources = {"main.yml": 'question: Hello\nsubquestion: ""\nyesno: ready\n'}
    content = export_workbook(sources, {})
    assert import_workbook(content, sources)["changes"] == []


def test_tall_screen_image_tiles_stay_in_order_on_one_sheet():
    import base64
    from io import BytesIO
    from PIL import Image
    import zipfile
    from xml.etree import ElementTree as ET

    sources = {"main.yml": "question: Tall screen\nyesno: ready\n"}
    images = []
    for color in ("red", "blue"):
        buffer = BytesIO()
        Image.new("RGB", (1100, 1000), color).save(buffer, format="PNG")
        images.append(base64.b64encode(buffer.getvalue()).decode())
    content = export_workbook(sources, {"main.yml#0": images})
    with zipfile.ZipFile(BytesIO(content)) as archive:
        assert (
            len([name for name in archive.namelist() if name.startswith("xl/media/")])
            == 2
        )
        drawing = ET.fromstring(archive.read("xl/drawings/drawing1.xml"))
        ns = {
            "x": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
        }
        anchors = drawing.findall("x:twoCellAnchor", ns)
        assert len(anchors) == 2
        first = anchors[0].find("x:from", ns)
        second = anchors[1].find("x:from", ns)
        assert int(second.find("x:row", ns).text) > int(first.find("x:row", ns).text)
    assert import_workbook(content, sources)["changes"] == []


def test_xml_relationship_cannot_bypass_size_guard_under_media():
    from io import BytesIO
    import zipfile
    import pytest

    sources = {"main.yml": "question: Hello\nyesno: ready\n"}
    original = export_workbook(sources, {})
    malicious = BytesIO()
    with zipfile.ZipFile(BytesIO(original)) as archive, zipfile.ZipFile(
        malicious, "w", zipfile.ZIP_DEFLATED
    ) as output:
        for name in archive.namelist():
            data = archive.read(name)
            if name == "[Content_Types].xml":
                data = data.replace(b"/xl/sharedStrings.xml", b"/xl/media/strings.png")
            if name == "xl/_rels/workbook.xml.rels":
                data = data.replace(
                    b'Target="sharedStrings.xml"', b'Target="media/strings.png"'
                )
            if name == "xl/sharedStrings.xml":
                name = "xl/media/strings.png"
            output.writestr(name, data)
    # openpyxl would otherwise parse this excluded part as shared-string XML,
    # even though its name looks like an image and read_only=True is used.
    with pytest.raises(KeyError, match="xl/media/strings.png"):
        import_workbook(malicious.getvalue(), sources)
