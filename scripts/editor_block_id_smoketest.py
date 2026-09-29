"""Live regression for opaque interview block IDs in editor routes.

Creates one uniquely named YAML file in a disposable editor project, selects
each question through the visible outline, and checks that its URL survives a
reload. Requires Playwright with Chromium and an authenticated storage state.
"""

import argparse
import json
import uuid
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright  # type: ignore[import-not-found]

parser = argparse.ArgumentParser(
    description="Check URL routing for block IDs with separators and reserved characters."
)
parser.add_argument("--base-url", default="http://localhost")
parser.add_argument("--storage-state", required=True)
parser.add_argument("--project", required=True)
args = parser.parse_args()

BASE = args.base_url.rstrip("/")
PROJECT = args.project
FILENAME = f"block id routes {uuid.uuid4().hex[:10]}.yml"
IDS = [
    "person_name",
    "intake/person",
    "intake\\person",
    ".",
    "..",
    "~",
    "~intake%2Fperson",
    "person/名字 #?%25",
    "intake\u2215person",  # U+2215 DIVISION SLASH
]
TITLES = {
    block_id: f"Question for block {index}" for index, block_id in enumerate(IDS, 1)
}
CONTENT = (
    "\n".join(
        f"---\nid: {json.dumps(block_id, ensure_ascii=True)}\n"
        f"question: {json.dumps(TITLES[block_id])}"
        for block_id in IDS
    )
    + "\n"
)


def encode_component(value: str) -> str:
    # JavaScript encodeURIComponent's unescaped ASCII set.
    return quote(value, safe="-_.!~*'()")


def block_route(block_id: str) -> str:
    if (
        "/" in block_id
        or "\\" in block_id
        or block_id in (".", "..")
        or block_id.startswith("~")
    ):
        encoded_id = "~" + encode_component(encode_component(block_id))
    else:
        encoded_id = encode_component(block_id)
    return (
        f"{BASE}/al/editor/projects/{encode_component(PROJECT)}"
        f"/interviews/{encode_component(FILENAME)}/blocks/{encoded_id}"
    )


def assert_response(response):
    payload = response.json()
    assert response.ok and payload.get("success"), (
        response.status,
        payload,
    )
    return payload


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        storage_state=args.storage_state,
        viewport={"width": 1440, "height": 1000},
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    api = context.request
    fixture_created = False
    csrf = None
    try:
        project_url = f"{BASE}/al/editor/projects/{encode_component(PROJECT)}"
        page.goto(project_url)
        expect(page.locator("#canvas-content")).to_be_visible(timeout=30000)
        csrf = page.evaluate("window.__EDITOR_BOOTSTRAP__.csrfToken")
        assert csrf, "editor bootstrap did not contain a CSRF token"
        headers = {"X-CSRFToken": csrf}

        assert_response(
            api.post(
                f"{BASE}/al/editor/api/file/new",
                headers=headers,
                data={"project": PROJECT, "filename": FILENAME, "content": CONTENT},
            )
        )
        fixture_created = True

        file_url = f"{project_url}/interviews/{encode_component(FILENAME)}"
        page.goto(file_url)
        expect(page.locator(".editor-outline-item[data-block-id]")).to_have_count(
            len(IDS), timeout=30000
        )

        previous_url = None
        for block_id in IDS:
            outline = page.locator(".editor-outline-item[data-block-id]")
            index = outline.evaluate_all(
                "(items, target) => items.findIndex(item => item.getAttribute('data-block-id') === target)",
                block_id,
            )
            assert index >= 0, f"Missing visible outline row for {block_id!r}"

            # Click by the row's position so IDs need no CSS selector escaping.
            page.locator(".editor-outline-item[data-block-id]").nth(index).click()
            expected_url = block_route(block_id)
            expect(page).to_have_url(expected_url, timeout=10000)
            expect(page.locator("#q-title")).to_have_value(TITLES[block_id])
            assert page.locator("#q-title").get_attribute("data-block-id") == block_id

            # Browser history must preserve the opaque ID as well as direct reload.
            if previous_url is not None:
                page.go_back()
                expect(page).to_have_url(previous_url, timeout=10000)
                expect(page.locator("#q-title")).to_have_value(
                    TITLES[IDS[IDS.index(block_id) - 1]], timeout=10000
                )
                page.go_forward()
                expect(page).to_have_url(expected_url, timeout=10000)
                expect(page.locator("#q-title")).to_have_value(TITLES[block_id])

            page.reload()
            expect(page).to_have_url(expected_url, timeout=30000)
            expect(page.locator("#q-title")).to_have_value(
                TITLES[block_id], timeout=30000
            )
            assert page.locator("#q-title").get_attribute("data-block-id") == block_id
            print(f"PASS click, history, and reload preserve block ID {block_id!r}")
            previous_url = expected_url

        assert not page_errors, page_errors
        print("PASS no browser page errors")
    finally:
        if fixture_created:
            assert csrf, "Cannot clean up fixture without the editor CSRF token"
            assert_response(
                api.post(
                    f"{BASE}/al/editor/api/file/delete",
                    headers={"X-CSRFToken": csrf},
                    data={"project": PROJECT, "filename": FILENAME},
                )
            )
            print(f"Removed disposable fixture {FILENAME!r}")
        browser.close()
