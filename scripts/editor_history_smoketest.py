import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright  # type: ignore[import-not-found]

parser = argparse.ArgumentParser(
    description="Exercise dirty browser-history guards in a local Weaver editor."
)
parser.add_argument("--base-url", default="http://localhost")
parser.add_argument("--storage-state", required=True, type=Path)
parser.add_argument("--project", required=True)
parser.add_argument("--fixture-filename", default="history_guard.yml")
args = parser.parse_args()

BASE = args.base_url.rstrip("/")
PROJECT = args.project
FILENAME = args.fixture_filename
STORAGE_STATE = str(args.storage_state)
if not args.storage_state.is_file():
    parser.error("--storage-state must point to an existing Playwright storage state")
print(
    f"Fixture mutation: this smoke test creates or resets only "
    f"{PROJECT}/{FILENAME}; use a dedicated test fixture."
)
CONTENT = "---\nid: guard_one\nquestion: First history question\n---\nid: guard_two\nquestion: Second history question\n"


def editor_url(block_id):
    return (
        f"{BASE}/al/editor/projects/{PROJECT}/interviews/{FILENAME}/blocks/{block_id}"
    )


def response_json(response):
    payload = response.json()
    assert response.ok and payload.get("success"), payload
    return payload


def create_fixture(page):
    token = page.evaluate("window.__EDITOR_BOOTSTRAP__.csrfToken")
    assert token, "editor bootstrap did not contain a CSRF token"
    existing = page.request.get(
        f"{BASE}/al/editor/api/file",
        params={"project": PROJECT, "filename": FILENAME},
    )
    if existing.ok:
        response_json(
            page.request.post(
                f"{BASE}/al/editor/api/file",
                headers={"X-CSRFToken": token},
                data={"project": PROJECT, "filename": FILENAME, "content": CONTENT},
            )
        )
    else:
        assert (
            existing.status == 404
        ), f"Could not inspect fixture file (HTTP {existing.status}): {existing.text()}"
        response_json(
            page.request.post(
                f"{BASE}/al/editor/api/file/new",
                headers={"X-CSRFToken": token},
                data={"project": PROJECT, "filename": FILENAME, "content": CONTENT},
            )
        )


def saved_source(page):
    result = response_json(
        page.request.get(
            f"{BASE}/al/editor/api/file",
            params={"project": PROJECT, "filename": FILENAME},
        )
    )
    return result["data"]["raw_yaml"]


def open_second_block(page):
    page.goto(editor_url("guard_one"))
    expect(page.locator("#q-title")).to_have_value(
        "First history question", timeout=30000
    )
    page.locator('.editor-outline-item[data-block-id="guard_two"]').click()
    expect(page).to_have_url(editor_url("guard_two"), timeout=10000)
    expect(page.locator("#q-title")).to_have_value("Second history question")


def make_dirty_and_go_back(page, value):
    page.locator("#q-title").fill(value)
    page.evaluate("history.back()")
    expect(page.locator("#unsaved-changes-modal")).to_be_visible(timeout=10000)
    expect(page).to_have_url(editor_url("guard_two"), timeout=10000)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 1000},
    )
    page_errors = []
    bootstrap_page = context.new_page()
    bootstrap_page.on("pageerror", lambda error: page_errors.append(str(error)))

    bootstrap_page.goto(f"{BASE}/al/editor/projects/{PROJECT}")
    expect(bootstrap_page.locator("#canvas-content")).to_be_visible(timeout=30000)
    create_fixture(bootstrap_page)
    original_source = CONTENT
    csrf_token = bootstrap_page.evaluate("window.__EDITOR_BOOTSTRAP__.csrfToken")
    bootstrap_page.close()

    def new_scenario_page():
        scenario_page = context.new_page()
        scenario_page.on("pageerror", lambda error: page_errors.append(str(error)))
        return scenario_page

    def restore_fixture():
        response_json(
            context.request.post(
                f"{BASE}/al/editor/api/file",
                headers={"X-CSRFToken": csrf_token},
                data={"project": PROJECT, "filename": FILENAME, "content": CONTENT},
            )
        )

    page = new_scenario_page()
    open_second_block(page)
    make_dirty_and_go_back(page, "Stay keeps this unsaved title")
    assert saved_source(page) == original_source
    page.locator('[data-unsaved-choice="stay"]').click()
    expect(page.locator("#unsaved-changes-modal")).to_be_hidden(timeout=10000)
    expect(page).to_have_url(editor_url("guard_two"))
    expect(page.locator("#q-title")).to_have_value("Stay keeps this unsaved title")
    assert saved_source(page) == original_source
    print("PASS Stay preserves URL and buffer without changing server bytes")
    page.close()

    page = new_scenario_page()
    restore_fixture()
    open_second_block(page)
    make_dirty_and_go_back(page, "Discard must not persist")
    page.locator('[data-unsaved-choice="discard"]').click()
    expect(page.locator("#unsaved-changes-modal")).to_be_hidden(timeout=10000)
    expect(page).to_have_url(editor_url("guard_one"), timeout=10000)
    assert saved_source(page) == original_source
    print("PASS Discard traverses Back and leaves server bytes unchanged")
    page.close()

    page = new_scenario_page()
    restore_fixture()
    open_second_block(page)
    make_dirty_and_go_back(page, "Save persists this title")
    page.locator('[data-unsaved-choice="save"]').click()
    expect(page.locator("#unsaved-changes-modal")).to_be_hidden(timeout=30000)
    expect(page).to_have_url(editor_url("guard_one"), timeout=10000)
    assert "Save persists this title" in saved_source(page)
    print("PASS Save persists the edit before traversing Back")
    page.close()

    page = new_scenario_page()
    restore_fixture()
    open_second_block(page)
    make_dirty_and_go_back(page, "Failed save stays here")

    def fail_block_save(route):
        route.fulfill(
            status=500,
            content_type="application/json",
            body='{"success": false, "error": {"message": "Injected save failure"}}',
        )

    page.route("**/al/editor/api/block", fail_block_save)
    page.locator('[data-unsaved-choice="save"]').click()
    expect(page.locator("#unsaved-changes-error")).to_be_visible(timeout=10000)
    expect(page.locator("#unsaved-changes-error")).to_contain_text("could not be saved")
    expect(page).to_have_url(editor_url("guard_two"))
    expect(page.locator("#q-title")).to_have_value("Failed save stays here")
    assert saved_source(page) == CONTENT
    print("PASS failed Save keeps modal, URL, buffer, and server bytes")

    assert not page_errors, page_errors
    browser.close()
