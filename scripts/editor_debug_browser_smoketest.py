"""Localhost debugger regression; creates and removes a disposable developer.

Uses the localhost entry in ~/.docassemblecli. Requires requests, PyYAML,
Playwright, a Chromium installation, and a configured Weaver assistant.
Sends one synthetic ask-only request to the configured assistant.
"""

import os, secrets, time
import re
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

        search = page.locator("#runtime-variable-search")
        search.fill("test")
        search.press("Escape")
        expect(search).to_be_focused()
        search.fill("")
        page.get_by_role("button", name="Full screen", exact=True).click()
        expect(page.get_by_role("button", name="Exit full screen")).to_be_visible()
        box = page.locator(".editor-runtime-fullscreen").bounding_box()
        assert box["x"] == 0 and box["y"] == 0, box
        expect(page.locator("#runtime-fill-samples")).to_be_visible()
        sidebar_toggle = page.locator("#runtime-toggle-sidebar")
        expect(sidebar_toggle).to_be_visible()
        expect(sidebar_toggle).to_have_attribute("aria-expanded", "false")
        sidebar_toggle.click()
        expect(sidebar_toggle).to_have_attribute("aria-expanded", "true")
        search.press("Escape")
        expect(search).to_be_focused()
        expect(page.locator(".editor-runtime-fullscreen")).to_be_visible()
        frame.locator("body").evaluate("""(body) => {
            const dialog = document.createElement('dialog');
            dialog.id = 'debug-test-dialog';
            dialog.innerHTML = '<button type="button">Dialog action</button>';
            body.appendChild(dialog);
            dialog.showModal();
        }""")
        frame.get_by_role("button", name="Dialog action").press("Escape")
        expect(frame.locator("#debug-test-dialog")).not_to_be_visible()
        expect(page.locator(".editor-runtime-fullscreen")).to_be_visible()
        frame.locator("#debug-test-dialog").evaluate("(el) => el.remove()")
        frame.locator("input[type=text]").first.press("Escape")
        expect(page.locator(".editor-runtime-fullscreen")).to_be_visible()
        expect(page.locator("#runtime-sidebar-panels")).to_be_visible()
        expect(
            frame.get_by_role("heading", name="What is your name?", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Explain", exact=True).click()
        page.get_by_role("button", name="Why this screen?", exact=True).focus()
        page.keyboard.press("Escape")
        expect(page.locator(".editor-runtime-fullscreen")).to_be_visible()
        expect(
            page.get_by_role("button", name="Why this screen?", exact=True)
        ).not_to_be_visible()
        scenario = page.locator("details").filter(has=page.locator("#runtime-scenario"))
        scenario.locator("summary").click()
        page.locator("#runtime-scenario").fill("variables: [")
        page.locator("#runtime-apply-scenario").click()
        expect(page.locator("#runtime-status")).to_have_class(
            re.compile(".*alert-danger.*")
        )
        expect(page.locator("#runtime-status")).to_be_visible()
        assert not page.locator("#runtime-status").evaluate(
            "(el) => Boolean(el.closest('[inert]'))"
        )
        scenario.locator("summary").click()
        print(
            "PASS host Escape, dropdown Escape and fullscreen scenario error visibility",
            flush=True,
        )
        sidebar_toggle.click()
        expect(sidebar_toggle).to_have_attribute("aria-expanded", "false")
        print("PASS fullscreen debugging rail expands and collapses", flush=True)
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
        for mobile_width in (320, 390):
            page.set_viewport_size({"width": mobile_width, "height": 700})
            sidebar_toggle.click()
            expect(page.locator("#runtime-sidebar-panels")).to_be_visible()
            expect(page.locator("#runtime-status")).to_be_visible()
            assert not page.locator("#runtime-status").evaluate(
                "(el) => Boolean(el.closest('[inert]'))"
            )
            for selector in (
                ".editor-runtime-workbench",
                ".editor-runtime-frame-bar",
                ".editor-runtime-fill-actions",
            ):
                assert page.locator(selector).evaluate(
                    "(el) => el.scrollWidth <= el.clientWidth + 1"
                ), selector

            expect(page.locator("#runtime-interview-frame")).to_have_css(
                "transform", "matrix(1, 0, 0, 1, 0, 0)"
            )
            sidebar_toggle.click()
            for selector in (
                ".editor-runtime-workbench",
                ".editor-runtime-frame-bar",
                ".editor-runtime-fill-actions",
            ):
                assert page.locator(selector).evaluate(
                    "(el) => el.scrollWidth <= el.clientWidth + 1"
                ), selector
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            button = page.get_by_role("button", name="Exit full screen")
            box = button.bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= mobile_width, box
        frame.get_by_role("heading", name="What is your name?", exact=True).click()
        page.keyboard.press("Escape")
        expect(page.locator(".editor-runtime-fullscreen")).to_have_count(0)
        expect(page.locator("[inert]")).to_have_count(0)
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
        page.get_by_role("button", name="Full screen", exact=True).click()
        sidebar_toggle.click()
        page.get_by_role("button", name="Open source block").click()
        expect(page.locator("[inert]")).to_have_count(0)
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
        assert fill.evaluate(
            "(el) => el.previousElementSibling.id === 'runtime-regenerate-samples'"
        )
        regenerate_box = page.locator("#runtime-regenerate-samples").bounding_box()
        assert regenerate_box["y"] == after_fill["y"]
        assert (
            abs(regenerate_box["x"] + regenerate_box["width"] + 8 - after_fill["x"]) < 1
        )
        print("PASS Fill/Continue position stays fixed", flush=True)
        for width in (320, 390, 430):
            page.set_viewport_size({"width": width, "height": 700})
            for full in (False, True):
                if full:
                    page.get_by_role("button", name="Full screen", exact=True).click()
                for selector in (
                    "#runtime-zoom",
                    "#runtime-explain-menu",
                    "#runtime-regenerate-samples",
                    "#runtime-fill-samples",
                ):
                    control = page.locator(selector)
                    control.scroll_into_view_if_needed()
                    box = control.bounding_box()
                    assert box["x"] >= 0 and box["x"] + box["width"] <= width, (
                        width,
                        full,
                        selector,
                        box,
                    )
                if full:
                    page.get_by_role(
                        "button", name="Exit full screen", exact=True
                    ).click()
                else:
                    page.get_by_role(
                        "button", name="Full screen", exact=True
                    ).scroll_into_view_if_needed()
                    box = page.get_by_role(
                        "button", name="Full screen", exact=True
                    ).bounding_box()
                    assert box["x"] >= 0 and box["x"] + box["width"] <= width, box
                page.screenshot(path=f"/tmp/debug-toolbar-{width}-{full}.png")
        page.set_viewport_size({"width": 1440, "height": 900})
        print(
            "PASS mobile toolbar button bounds in normal and fullscreen modes",
            flush=True,
        )

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
        expect(page.locator("[inert]")).to_have_count(0)
        print("PASS expired session fullscreen cleanup", flush=True)
        print("errors", errors, flush=True)
        assert not errors
        page.screenshot(path="/tmp/debug-error.png")
        browser.close()
finally:
    requests.delete(
        base + f"/api/user/{uid}", headers=headers, params={"remove": "account"}
    )
