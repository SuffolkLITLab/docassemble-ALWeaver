"""Live regression test for a dedicated project on a running Docassemble server.

Creates two uniquely named scratch interview files (through rename), exercises
refresh/save/rename/delete, and removes the surviving scratch file on success.
Requires Playwright with Chromium and an authenticated storage-state file.
"""

from playwright.sync_api import sync_playwright, expect  # type: ignore[import-not-found]
from urllib.parse import quote
import argparse
import uuid

parser = argparse.ArgumentParser(
    description="Test editor file routes and source preservation using disposable YAML files."
)
parser.add_argument("--base-url", default="http://localhost")
parser.add_argument("--storage-state", required=True)
parser.add_argument(
    "--project",
    required=True,
    help="Existing disposable test project with at least one interview",
)
args = parser.parse_args()
base = args.base_url.rstrip("/")
project = args.project
root = base + "/al/editor/projects/" + quote(project, safe="")
tag = uuid.uuid4().hex[:8]
original = f"route lifecycle #{tag}.yml"
renamed = f"route lifecycle renamed {tag}.yml"
content = """# Exact source preservation fixture
metadata:
  title: 'Route lifecycle'
---
# Leave this comment intact
id: route_lifecycle
question: Original lifecycle question
fields:
  - Answer: lifecycle_answer # inline comment
---
id: lifecycle_code
code: |
  # Keep this Python comment
  lifecycle_done = True
"""
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        storage_state=args.storage_state, viewport={"width": 1440, "height": 1000}
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(root)
    expect(page.locator("#file-select option")).not_to_have_count(0, timeout=30000)
    page.wait_for_load_state("networkidle")
    csrf = page.evaluate("window.__EDITOR_BOOTSTRAP__.csrfToken")
    headers = {"X-CSRFToken": csrf}
    api = context.request
    # Unique filenames keep existing interviews untouched.
    res = api.post(
        base + "/al/editor/api/file/new",
        data={"project": project, "filename": original, "content": content},
        headers=headers,
    )
    assert res.ok, (res.status, res.text())
    page.reload()
    expect(page.locator(f'#file-select option[value="{original}"]')).to_have_count(
        1, timeout=30000
    )
    page.select_option("#file-select", original)
    path = root + "/interviews/" + quote(original, safe="") + "/blocks/route_lifecycle"
    expect(page).to_have_url(path, timeout=30000)
    expect(page.locator("#q-title")).to_have_value("Original lifecycle question")
    page.reload()
    expect(page.locator("#q-title")).to_have_value(
        "Original lifecycle question", timeout=30000
    )
    print("PASS encoded filename selection and refresh")
    page.locator("#q-title").fill("Updated lifecycle question")
    page.locator("#editor-canvas-save button").click()
    expect(page.locator("#editor-canvas-save button")).to_be_disabled(timeout=30000)
    saved = api.get(
        base + "/al/editor/api/file", params={"project": project, "filename": original}
    ).json()["data"]["raw_yaml"]
    assert saved == content.replace(
        "question: Original lifecycle question",
        'question: "Updated lifecycle question"',
    ), repr(saved)
    print("PASS graphical save preserves all unrelated source bytes")
    before_index = page.evaluate("history.state.alEditorIndex")
    before_length = page.evaluate("history.length")
    page.once("dialog", lambda dialog: dialog.accept(renamed))
    page.locator('#editor-file-section [aria-label="File actions"]').click()
    page.locator("#btn-rename-file").click()
    newpath = (
        root + "/interviews/" + quote(renamed, safe="") + "/blocks/route_lifecycle"
    )
    expect(page).to_have_url(newpath, timeout=30000)
    expect(page.locator("#q-title")).to_have_value("Updated lifecycle question")
    assert page.evaluate("history.state.alEditorIndex") == before_index
    assert page.evaluate("history.length") == before_length
    page.reload()
    expect(page.locator("#q-title")).to_have_value(
        "Updated lifecycle question", timeout=30000
    )
    print("PASS rename replaces URL/history and refresh works")
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator('#editor-file-section [aria-label="File actions"]').click()
    page.locator("#btn-delete-file").click()
    expect(page.locator("#file-select")).not_to_have_value(renamed, timeout=30000)
    expect(page).not_to_have_url(newpath)
    assert page.evaluate("history.state.alEditorIndex") == before_index
    assert page.evaluate("history.length") == before_length
    selected = page.locator("#file-select").input_value()
    page.reload()
    expect(page.locator("#file-select")).to_have_value(selected, timeout=30000)
    print("PASS delete replaces URL/history with surviving interview")
    assert not errors, errors
    print("PASS no browser page errors")
    browser.close()
