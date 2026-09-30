#!/usr/bin/env python3
"""Authenticated ALWeaver editor route regression against localhost.

The script uses a disposable fixture project and never saves or deletes files.
It checks direct deep links and real SPA navigation, including reload and browser
Back/Forward. Create an authenticated Playwright storage state for a test user,
then supply its path and the fixture project, interview, and block ID.

Example:
  python scripts/editor_route_smoketest.py \\
    --storage-state /tmp/editor-test-storage.json \\
    --project RouteFixture --interview main.yml --block-id first_question
"""

from __future__ import annotations
import argparse
import re
from urllib.parse import quote
from playwright.sync_api import expect, sync_playwright  # type: ignore[import-not-found]

PANELS = ("source", "order", "settings", "tests", "debug")


def path_has(page, fragment: str) -> None:
    expect(page).to_have_url(re.compile(re.escape(fragment) + r"/?(?:[?#].*)?$"))


def section_control(page, view: str):
    compact = page.locator("#editor-section-menu")
    if compact.is_visible():
        compact.click()
        return page.locator(f'.editor-view-switch[data-view="{view}"]:visible').first
    return page.locator(f'.editor-top-tab[data-view="{view}"]:visible').first


def open_interview_action(page, action: str) -> None:
    compact = page.locator("#editor-section-menu")
    if compact.is_visible():
        compact.click()
        submenu = page.locator('[data-section-submenu="editor-interview-submenu"]')
        if submenu.get_attribute("aria-expanded") != "true":
            submenu.click()
    menu = page.locator("#interview-menu")
    if menu.count() and menu.is_visible():
        menu.click()
    page.locator(f'[data-action="{action}"]:visible').last.click()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--storage-state", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--interview", required=True)
    parser.add_argument("--block-id", required=True)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    root = args.base_url.rstrip("/") + "/al/editor"
    project = quote(args.project, safe="")
    filename = quote(args.interview, safe="")
    block = quote(args.block_id, safe="")
    interview = f"{root}/projects/{project}/interviews/{filename}"
    start = f"{interview}/blocks/{block}"
    expected_sections: dict[str, str] = {}
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_responses: list[tuple[int, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(storage_state=args.storage_state)
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.on(
            "response",
            lambda response: (
                failed_responses.append((response.status, response.url))
                if response.status >= 400
                else None
            ),
        )

        def api_data(path: str, **params):
            response = context.request.get(f"{root}/api/{path}", params=params)
            if not response.ok:
                raise AssertionError(
                    f"fixture API {path} returned HTTP {response.status}"
                )
            return response.json().get("data", {})

        interview_data = api_data("file", project=args.project, filename=args.interview)
        fixture_blocks = interview_data.get("blocks", [])
        selected_block = next(
            (item for item in fixture_blocks if item.get("id") == args.block_id), None
        )
        if selected_block is None:
            raise AssertionError(
                f"fixture block {args.block_id!r} is absent from {args.interview}"
            )
        block_data = selected_block.get("data") or {}
        block_marker = selected_block.get("title") or block_data.get("question")
        if not isinstance(block_marker, str) or not block_marker.strip():
            raise AssertionError(
                f"fixture block {args.block_id!r} has no rendered question/title"
            )

        section_api_names = {
            "templates": "templates",
            "modules": "modules",
            "static": "static",
            "data": "sources",
        }
        section_filenames = {}
        for view, api_section in section_api_names.items():
            listing = api_data(
                "section-files", project=args.project, section=api_section
            )
            files = listing.get("files", [])
            selectable = [
                item
                for item in files
                if isinstance(item, dict)
                and item.get("editable")
                and item.get("filename") not in (None, ".placeholder")
            ]
            if not selectable:
                raise AssertionError(
                    f"fixture project has no editable {api_section} file"
                )
            section_filenames[view] = selectable[0]["filename"]
            path_section = "sources" if view == "data" else view
            expected_sections[view] = (
                f"/projects/{project}/{path_section}/{quote(section_filenames[view], safe='')}"
            )

        def load_and_check(
            url: str,
            route_fragment: str,
            *,
            marker: str | re.Pattern[str] | None = None,
            refresh: bool = True,
        ) -> None:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            path_has(page, route_fragment)
            expect(page.locator("#main-canvas")).to_be_visible()
            if marker:
                expect(page.locator("#main-canvas")).to_contain_text(marker)
            if refresh:
                page.reload(wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                path_has(page, route_fragment)
                expect(page.locator("#main-canvas")).to_be_visible()
                if marker:
                    expect(page.locator("#main-canvas")).to_contain_text(marker)
            alert = page.locator("#editor-api-error:visible")
            if alert.count():
                close = alert.locator("button.btn-close")
                if close.count():
                    close.click()
            if page_errors:
                raise AssertionError(
                    f"uncaught browser errors at {route_fragment}: {page_errors}"
                )

        # Collection URLs resolve to existing screens and replace themselves
        # with the selected resource URL, including after a hard refresh.
        first_interview = api_data("files", project=args.project)["files"][0][
            "filename"
        ]
        first_interview_path = (
            f"/projects/{project}/interviews/{quote(first_interview, safe='')}/blocks/"
        )
        for trailing in ("", "/"):
            load_and_check(
                f"{root}/projects{trailing}", "/al/editor", marker="Choose a project"
            )
            for parent in (f"/projects/{project}", f"/projects/{project}/interviews"):
                page.goto(root + parent + trailing, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                expect(page).to_have_url(
                    re.compile(re.escape(root + first_interview_path) + r"[^/]+$")
                )
                canonical = page.url
                page.reload(wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                expect(page).to_have_url(canonical)
                expect(page.locator("#file-select")).to_have_value(first_interview)
            page.goto(f"{interview}/blocks{trailing}", wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            expect(page).to_have_url(
                re.compile(re.escape(interview + "/blocks/") + r"[^/]+$")
            )
            canonical = page.url
            page.reload(wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            expect(page).to_have_url(canonical)
            for view, expected in expected_sections.items():
                section = section_api_names[view]
                load_and_check(
                    f"{root}/projects/{project}/{section}{trailing}",
                    expected,
                    marker=section_filenames[view],
                )
        print("PASS collection routes with and without trailing slashes + refresh")

        # Direct interview and panel deep links survive a hard refresh.
        load_and_check(
            start,
            f"/projects/{project}/interviews/{filename}/blocks/{block}",
            marker=block_marker,
        )
        panel_markers: dict[str, str | re.Pattern[str]] = {
            "source": "Full YAML",
            "order": "Interview Order",
            "settings": "AssemblyLine settings",
            "tests": "Tests",
            "debug": re.compile(
                r"Debug interview|runtime.{0,40}(disabled|unavailable|not enabled)|not available",
                re.I,
            ),
        }
        for panel in PANELS:
            load_and_check(
                f"{interview}/{panel}",
                f"/interviews/{filename}/{panel}",
                marker=panel_markers[panel],
            )
        load_and_check(
            f"{interview}/documents",
            f"/interviews/{filename}/documents",
            marker="Document setup",
        )
        print(
            "PASS interview block and source/order/settings/tests/debug deep links + refresh"
        )

        # Direct section URLs either retain their canonical selection or redirect
        # to the first selectable file, whose name is the canonical route.
        for section, expected in expected_sections.items():
            route = expected_sections[section]
            marker = section_filenames[section]
            load_and_check(root + route, route, marker=marker)
        load_and_check(
            f"{interview}/documents",
            f"/interviews/{filename}/documents",
            marker="Document setup",
        )
        page.goto(f"{root}/projects/{project}/documents", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        alias_url = page.url
        if not re.search(r"/projects/[^/]+/interviews/[^/]+/documents$", alias_url):
            raise AssertionError(
                f"project documents alias did not resolve to an interview: {alias_url}"
            )
        expect(page.locator("#main-canvas")).to_contain_text("Document setup")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(alias_url)
        print(
            "PASS templates/modules/static/sources/documents deep links + refresh; project documents alias resolves"
        )

        # Use visible editor controls so navigation is exercised through the SPA.
        page.goto(start, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        for view in ("templates", "modules", "static", "data"):
            control = section_control(page, view)
            expect(control).to_be_visible()
            control.click()
            page.wait_for_load_state("networkidle")
            canonical = expected_sections[view]
            path_has(page, canonical)
            expect(page.locator("#main-canvas")).to_be_visible()
            alert = page.locator("#editor-api-error:visible")
            if alert.count():
                close = alert.locator("button.btn-close")
                if close.count():
                    close.click()
            page.reload(wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            path_has(page, canonical)
            alert = page.locator("#editor-api-error:visible")
            if alert.count():
                close = alert.locator("button.btn-close")
                if close.count():
                    close.click()
        print(
            "PASS section controls update canonical URL and selection survives refresh"
        )

        # Templates' secondary menu opens Document setup without a full reload.
        selected_interview = quote(page.locator("#file-select").input_value(), safe="")
        compact = page.locator("#editor-section-menu")
        if compact.is_visible():
            compact.click()
            submenu = page.locator('[data-section-submenu="editor-templates-submenu"]')
            if submenu.get_attribute("aria-expanded") != "true":
                submenu.click()
        else:
            page.locator("#templates-menu").click()
        page.locator('[data-templates-mode="documents"]:visible').last.click()
        page.wait_for_load_state("networkidle")
        path_has(page, f"/interviews/{selected_interview}/documents")
        expect(page.locator("#main-canvas")).to_contain_text("Document setup")
        print("PASS Document setup menu route")

        # Interview actions update URL in place. Back and Forward must restore
        # the prior and next panels via the SPA's popstate handling.
        section_control(page, "interview").click()
        page.wait_for_load_state("networkidle")
        page.locator("#file-select").select_option(label=args.interview)
        page.wait_for_load_state("networkidle")
        open_interview_action(page, "open-full-yaml")
        page.wait_for_load_state("networkidle")
        source_path = f"/interviews/{filename}/source"
        path_has(page, source_path)
        open_interview_action(page, "open-interview-order")
        page.wait_for_load_state("networkidle")
        order_path = f"/interviews/{filename}/order"
        path_has(page, order_path)
        page.evaluate("history.back()")
        page.wait_for_timeout(300)
        path_has(page, source_path)
        page.evaluate("history.forward()")
        page.wait_for_timeout(300)
        path_has(page, order_path)
        print("PASS in-app Interview panel navigation and browser Back/Forward")

        module_response = page.request.get(
            f"{root}/api/section-files?project={project}&section=modules"
        )
        if not module_response.ok:
            raise AssertionError(
                f"modules listing API returned HTTP {module_response.status}"
            )
        module_files = module_response.json().get("data", {}).get("files", [])
        if not any(
            item.get("filename") == section_filenames["modules"]
            for item in module_files
            if isinstance(item, dict)
        ):
            raise AssertionError(
                "modules route did not return the selected fixture module"
            )
        if page_errors:
            raise AssertionError(f"uncaught browser errors: {page_errors}")
        if console_errors:
            raise AssertionError(f"browser console errors: {console_errors}")
        if failed_responses:
            raise AssertionError(f"failed network responses: {failed_responses}")
        print("PASS no uncaught page errors or unexpected console errors")
        browser.close()


if __name__ == "__main__":
    main()
