"""Run inside Docassemble to verify and remove one survey smoke-test row."""

import json
import sys

marker = sys.argv[1]
sys.argv = [sys.argv[0], "/usr/share/docassemble/config/config.yml"]
from docassemble.base import config

config.load(arguments=sys.argv)
from docassemble.ALWeaver.docassemble_compat import get_flask_app
from docassemble.webapp.extensions import db
from docassemble.webapp.jsonstorage.helpers import JsonStorage

app = get_flask_app()
with app.app_context():
    rows = (
        db.session.query(JsonStorage)
        .filter(JsonStorage.filename.like("%survey_answer_filter_smoke_test.yml"))
        .order_by(JsonStorage.modtime.desc())
        .limit(200)
        .all()
    )
    match = next(
        (row for row in rows if (row.data or {}).get("survey_name") == marker), None
    )
    assert match is not None, "No matching survey answer row was found"
    try:
        data = match.data or {}
        expected_keys = {
            "title",
            "field_type_list",
            "survey_name",
            "survey_count",
        }
        assert (
            set(data) == expected_keys
        ), f"Unexpected saved answer keys: {sorted(data)}"
        assert data["survey_count"] == 41 and type(data["survey_count"]) is int
        assert data["field_type_list"] == {
            "survey_name": "text",
            "survey_count": "int",
        }
        assert "internal_skipped_answer" not in data
        assert "internal_computed_answer" not in data
    finally:
        db.session.delete(match)
        db.session.commit()
    print(json.dumps({"ok": True, "keys": sorted(data), "fixture_row_removed": True}))
