"""Localhost debugger regression; creates and removes a disposable developer.

Uses the localhost entry in ~/.docassemblecli. Requires requests, PyYAML,
Playwright, a Chromium installation, and a configured Weaver assistant.
Sends one synthetic ask-only request to the configured assistant.
"""

import os, secrets, time
from pathlib import Path
import requests, yaml
from playwright.sync_api import sync_playwright, expect  # type: ignore[import-not-found]

base = "http://localhost"
c = next(
    x
    for x in yaml.safe_load((Path.home() / ".docassemblecli").read_text())
    if x["name"] == "localhost"
)
headers = {"X-API-Key": c["apikey"]}
email = f"debug-test-{int(time.time())}@example.com"
password = secrets.token_urlsafe(24)
r = requests.post(
    base + "/api/user/new",
    headers=headers,
    json={
        "username": email,
        "password": password,
        "privileges": ["developer"],
        "first_name": "Debug",
        "last_name": "Test",
    },
)
r.raise_for_status()
uid = r.json()["user_id"]
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, executable_path=os.environ.get("BROWSER_PATH")
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(30000)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/user/sign-in")
        page.locator("[name=email]").fill(email)
        page.locator("[name=password]").fill(password)
        page.locator("input[type=submit],button[type=submit]").first.click()
        page.wait_for_url(lambda u: "/user/sign-in" not in u)
        page.goto(base + "/al/editor", wait_until="networkidle")
        csrf = page.evaluate("window.__EDITOR_BOOTSTRAP__.csrfToken")

        def post(path, data):
            r = context.request.post(
                base + "/al/editor" + path, data=data, headers={"X-CSRF-Token": csrf}
            )
            j = r.json()
            assert j["success"], j
            return j["data"]

        project = post(
            "/api/new-project",
            {"project_name": "DebugE2E" + str(int(time.time())), "create_test": False},
        )["project"]
        source = """---
mandatory: True
code: |
  person_name
  deliberate_failure = 1 / 0
---
id: name screen
question: What is your name?
fields:
  - Name: person_name
"""
        post(
            "/api/file/new",
            {"project": project, "filename": "debug.yml", "content": source},
        )
        page.goto(
            base + "/al/editor/projects/" + project + "/interviews/debug.yml",
            wait_until="networkidle",
        )
        page.locator('[data-action="open-runtime-inspector"]:visible').first.click()
        page.get_by_role("button", name="Start debugging", exact=True).click()
        frame = page.frame_locator("#runtime-interview-frame")
        expect(
            frame.get_by_role("heading", name="What is your name?", exact=True)
        ).to_be_visible(timeout=60000)
        expect(page.get_by_role("button", name="Open source block")).to_be_visible()
        expect(
            page.get_by_role("button", name="Restart interview", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="End debug session", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Back one screen", exact=True)
        ).not_to_be_visible()
        page.get_by_role("button", name="More debug actions", exact=True).click()
        expect(
            page.get_by_role("button", name="Back one screen", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Clean up old sessions", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("link", name="Open in new tab", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Refresh", exact=True).click()
        expect(
            page.get_by_role("button", name="Back one screen", exact=True)
        ).not_to_be_visible()
        print("PASS compact session controls and More menu", flush=True)

        page.get_by_role("button", name="Full screen", exact=True).click()
        expect(page.get_by_role("button", name="Exit full screen")).to_be_visible()
        box = page.locator(".editor-runtime-fullscreen").bounding_box()
        assert box["x"] == 0 and box["y"] == 0, box
        expect(page.locator("#runtime-fill-samples")).to_be_visible()
        dimensions = page.locator("#runtime-interview-frame").evaluate(
            "(el) => ({height: el.contentWindow.innerHeight, width: el.contentWindow.innerWidth})"
        )
        assert dimensions["height"] == 900 and dimensions["width"] == 1440, dimensions
        frame.locator("input[type=text]").first.fill("Zoom preserves this answer")
        page.get_by_label("Interview zoom").select_option("75")
        expect(frame.locator("input[type=text]").first).to_have_value(
            "Zoom preserves this answer"
        )
        assert (
            page.locator("#runtime-interview-frame").evaluate(
                "(el) => el.style.transform"
            )
            == "scale(0.75)"
        )
        page.get_by_label("Interview zoom").select_option("auto")
        print("PASS fit viewport and pane-only zoom without reload", flush=True)
        page.screenshot(path="/tmp/debug-fullscreen.png")
        page.set_viewport_size({"width": 390, "height": 700})
        button = page.get_by_role("button", name="Exit full screen")
        box = button.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 390, box
        frame.get_by_role("heading", name="What is your name?", exact=True).click()
        page.keyboard.press("Escape")
        expect(page.locator(".editor-runtime-fullscreen")).to_have_count(0)
        assert page.locator("[inert]").count() == 0
        page.set_viewport_size({"width": 1440, "height": 900})
        print("PASS mobile fullscreen, iframe Escape and inert cleanup", flush=True)
        page.get_by_role("button", name="Explain", exact=True).click()
        page.get_by_role("button", name="Why this screen?", exact=True).click()
        print("assistant", page.locator("#editor-assistant").is_visible(), flush=True)
        if page.locator("#editor-agent-input").is_visible():
            draft = page.locator("#editor-agent-input").input_value()
            assert (
                "What is your name?" in draft
                and "Source log" in draft
                and len(draft) <= 8000
            )
            print("PASS assistant screen draft", flush=True)
        else:
            raise AssertionError("Assistant did not open")
        page.get_by_role("button", name="Open source block").click()
        expect(page.locator(".editor-runtime-inspector")).not_to_be_visible()
        page.locator('[data-action="open-runtime-inspector"]:visible').first.click()
        expect(
            frame.get_by_role("heading", name="What is your name?", exact=True)
        ).to_be_visible()
        print("PASS source navigation and reconnect", flush=True)
        fill = page.locator("#runtime-fill-samples")
        before_fill = fill.bounding_box()
        fill.click()
        after_fill = fill.bounding_box()
        assert before_fill == after_fill, (before_fill, after_fill)
        assert fill.evaluate("(el) => el === el.parentElement.lastElementChild")
        print("PASS Fill/Continue position stays fixed", flush=True)
        fill.click()
        page.wait_for_timeout(3000)
        print(
            "frame after continue",
            frame.locator("body").inner_text()[:1200],
            flush=True,
        )
        page.get_by_role("button", name="Explain", exact=True).click()
        page.get_by_role("button", name="Explain this error", exact=True).click()
        if page.locator("#editor-agent-input").is_visible():
            draft = page.locator("#editor-agent-input").input_value()
            assert "division by zero" in draft
            print("PASS error draft", flush=True)
            expect(page.get_by_label("Ask only (no edits)")).to_be_checked()
            page.locator("#editor-assistant button[type=submit]").click()
            expect(page.locator(".editor-agent-message-assistant").last).to_be_visible(
                timeout=120000
            )
            print(
                "PASS live assistant response: "
                + page.locator(".editor-agent-message-assistant").last.inner_text()[
                    :500
                ],
                flush=True,
            )
        page.locator('[data-action="open-runtime-inspector"]:visible').first.click()
        page.get_by_role("button", name="Full screen", exact=True).click()
        j = context.request.get(
            base + "/al/editor/api/runtime/sessions",
            params={"project": project, "filename": "debug.yml"},
        ).json()
        sid = j["data"]["session"]["weaver_session_id"]
        context.request.delete(
            base + "/al/editor/api/runtime/sessions/" + sid,
            headers={"X-CSRF-Token": csrf},
        )
        expect(
            page.get_by_role("button", name="Start debugging", exact=True)
        ).to_be_visible(timeout=60000)
        assert page.locator("[inert]").count() == 0
        print("PASS expired session fullscreen cleanup", flush=True)
        print("errors", errors, flush=True)
        assert not errors
        page.screenshot(path="/tmp/debug-error.png")
        browser.close()
finally:
    requests.delete(
        base + f"/api/user/{uid}", headers=headers, params={"remove": "account"}
    )
