"""Localhost report regression using a disposable account and Missouri sources.

Run with requests, PyYAML, openpyxl and Playwright installed. Reads localhost
credentials from ~/.docassemblecli; never logs them. Artifacts go to /tmp.
"""

import json
import os
from pathlib import Path
import secrets
import time
import zipfile

import openpyxl
from playwright.sync_api import sync_playwright, expect  # type: ignore[import-not-found]
import requests
import yaml

base = "http://localhost"
output = Path("/tmp/weaver-reports-e2e")
output.mkdir(exist_ok=True)
config = next(
    x
    for x in yaml.safe_load((Path.home() / ".docassemblecli").read_text())
    if x["name"] == "localhost"
)
headers = {"X-API-Key": config["apikey"]}
email = f"reports-e2e-{int(time.time())}@example.com"
password = secrets.token_urlsafe(24)
response = requests.post(
    base + "/api/user/new",
    headers=headers,
    json={
        "username": email,
        "password": password,
        "privileges": ["developer"],
        "first_name": "Reports",
        "last_name": "Test",
    },
    timeout=60,
)
response.raise_for_status()
uid = response.json()["user_id"]
print("Disposable account created", flush=True)
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("BROWSER_PATH")
        )
        context = browser.new_context(
            viewport={"width": 1500, "height": 1000}, accept_downloads=True
        )
        page = context.new_page()
        page.set_default_timeout(60000)
        errors = []
        jobs: list[dict[str, str | int]] = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def record(response):
            if (
                "/api/reports/" in response.url
                and response.request.method == "POST"
                and "/uploads" not in response.url
                and not response.url.endswith("/ack")
                and not response.url.endswith("/entrypoints")
            ):
                jobs.append(
                    {
                        "path": response.url.split("/api/reports/")[-1],
                        "status": response.status,
                    }
                )
                print("Report request:", jobs[-1], flush=True)

        page.on("response", record)
        page.goto(base + "/user/sign-in")
        page.locator("[name=email]").fill(email)
        page.locator("[name=password]").fill(password)
        page.locator("input[type=submit],button[type=submit]").first.click()
        page.wait_for_url(lambda url: "/user/sign-in" not in url)
        page.goto(base + "/al/editor", wait_until="networkidle")
        csrf = page.evaluate("window.__EDITOR_BOOTSTRAP__.csrfToken")

        def post(path, body):
            response = context.request.post(
                base + "/al/editor" + path,
                data=body,
                headers={"X-CSRF-Token": csrf},
                timeout=120000,
            )
            result = response.json()
            assert result.get("success"), result
            return result["data"]

        project = post(
            "/api/new-project", {"project_name": "ReportsE2E", "create_test": False}
        )["project"]
        sources = Path(
            os.environ.get(
                "REPORT_SOURCE",
                str(
                    Path.home()
                    / "docassemble-MODivorceForms/docassemble/MODivorceForms/data/questions"
                ),
            )
        )
        post("/api/file/delete", {"project": project, "filename": "main.yml"})
        for path in sorted(sources.glob("*.yml")):
            post(
                "/api/file/new",
                {
                    "project": project,
                    "filename": path.name,
                    "content": path.read_text(),
                },
            )
        print("Copied interview YAML into disposable project", flush=True)
        page.goto(
            base + "/al/editor/projects/" + project + "/interviews/main.yml",
            wait_until="networkidle",
        )

        def action(name):
            page.locator("#interview-menu").click()
            page.locator('[data-action="' + name + '"]:visible').last.click()

        downloads = []
        page.on("download", lambda download: downloads.append(download))
        action("export-wording-workbook")
        dialog = page.get_by_role("dialog", name="Export wording workbook", exact=True)
        start = time.monotonic()
        last_log = 0.0
        while not downloads and time.monotonic() - start < 1800:
            page.wait_for_timeout(1000)
            status = dialog.locator("[role=status]").inner_text()
            if time.monotonic() - last_log > 20:
                print("Export:", status, flush=True)
                last_log = time.monotonic()
            if not any(
                word in status
                for word in ("Reading", "Capturing", "Building", "downloaded")
            ):
                page.screenshot(path=str(output / "export-error.png"))
                raise AssertionError(status)
        assert downloads, "Export did not finish within 30 minutes"
        workbook = output / "missouri-wording.xlsx"
        downloads[-1].save_as(str(workbook))
        export_seconds = round(time.monotonic() - start, 1)
        with zipfile.ZipFile(workbook) as archive:
            images = [
                name for name in archive.namelist() if name.startswith("xl/media/")
            ]
            drawings = [
                name
                for name in archive.namelist()
                if name.startswith("xl/drawings/drawing") and name.endswith(".xml")
            ]
        assert len(drawings) > 250, len(drawings)
        print(
            f"PASS export: {len(drawings)} screenshot sheets, {len(images)} images, {workbook.stat().st_size} bytes, {export_seconds}s",
            flush=True,
        )
        page.screenshot(path=str(output / "export-complete.png"))
        dialog.get_by_role("button", name="Close report dialog").click()
        action("import-wording-workbook")
        dialog = page.get_by_role("dialog", name="Import wording workbook", exact=True)
        dialog.locator("input[type=file]").set_input_files(str(workbook))
        dialog.get_by_role("button", name="Review changes", exact=True).click()
        expect(dialog.locator("[role=status]")).to_contain_text(
            "0 wording changes ready", timeout=180000
        )
        print("PASS unchanged workbook import", flush=True)
        dialog.get_by_role("button", name="Close report dialog").click()
        edited = output / "missouri-wording-edited.xlsx"
        book = openpyxl.load_workbook(workbook)
        marker = " E2E reviewed wording."
        changed = False
        for sheet in book:
            if sheet.title in {"Instructions", "_ALWeaver"}:
                continue
            for row in sheet.iter_rows(min_row=4, max_col=5):
                value = row[2].value
                if (
                    row[2].protection.locked is False
                    and isinstance(value, str)
                    and value.strip()
                    and not any(char in value for char in "<${%")
                ):
                    original_wording = value
                    edited_wording = "Updated wording: " + value[1:] + marker
                    row[2].value = edited_wording
                    changed_id = row[4].value
                    changed = True
                    break
            if changed:
                break
        assert changed
        manifest = [
            json.loads(row[0].value)
            for row in book["_ALWeaver"].iter_rows(min_row=2)
            if row[0].value
        ]
        changed_filename = next(
            item["filename"] for item in manifest if item["id"] == changed_id
        )
        book.save(edited)
        action("import-wording-workbook")
        dialog = page.get_by_role("dialog", name="Import wording workbook", exact=True)
        dialog.locator("input[type=file]").set_input_files(str(edited))
        dialog.get_by_role("button", name="Review changes", exact=True).click()
        expect(dialog.locator("[role=status]")).to_contain_text(
            "1 wording changes ready", timeout=180000
        )
        expect(dialog.locator("tbody")).to_contain_text(marker)
        expect(dialog.locator("tbody del").first).to_be_visible()
        expect(dialog.locator("tbody ins").first).to_be_visible()
        assert (
            dialog.locator("tbody tr").first.locator("td").nth(1).text_content()
            == original_wording
        )
        assert (
            dialog.locator("tbody tr").first.locator("td").nth(2).text_content()
            == edited_wording
        )
        page.screenshot(path=str(output / "wording-diff-preview.png"))
        dialog.get_by_role("button", name="Apply reviewed changes", exact=True).click()
        expect(dialog.locator("[role=status]")).to_contain_text(
            "1 wording changes saved", timeout=180000
        )
        page.screenshot(path=str(output / "import-applied.png"))
        saved = context.request.get(
            base + "/al/editor/api/file",
            params={"project": project, "filename": changed_filename},
        ).json()
        assert (
            marker in saved["data"]["raw_yaml"]
        ), "Apply did not persist the reviewed wording"
        print("PASS reviewed edit applied and source verified", flush=True)
        dialog.get_by_role("button", name="Close report dialog").click()
        with page.expect_popup(timeout=60000) as popup:
            action("open-interview-flow-report")
        report = popup.value
        report.set_default_timeout(180000)
        report.wait_for_url("blob:**")
        expect(report.locator(".alwr-report")).to_be_visible()
        expect(report.locator(".alwr-mermaid-wrap svg")).to_be_visible(timeout=120000)
        assert report.locator(".alwr-flow").get_attribute("data-mermaid") != "failed"
        assert len(report.content()) > 500000
        (output / "missouri-flow-report.html").write_text(report.content())
        report.screenshot(path=str(output / "flow-report.png"))
        print("PASS flow report rendered", flush=True)
        action("open-repository-reports")
        repository = page.get_by_role(
            "dialog", name="Repository flow reports", exact=True
        )
        expect(repository.locator('input[value="main.yml"]')).to_be_visible()
        for checkbox in repository.locator("input[type=checkbox]").all():
            checkbox.uncheck()
        repository.locator('input[value="main.yml"]').check()
        with page.expect_download(timeout=180000) as archive_download:
            repository.get_by_role(
                "button", name="Download selected reports (ZIP)"
            ).click()
        archive_path = output / "repository-flow-reports.zip"
        archive_download.value.save_as(str(archive_path))
        with zipfile.ZipFile(archive_path) as archive:
            assert set(archive.namelist()) == {"index.html", "main.yml.html"}
            assert len(archive.read("main.yml.html")) > 500000
        print(
            "PASS repository ZIP via chunked upload and background archive job",
            flush=True,
        )
        assert not errors, errors
        assert jobs and all(job["status"] == 202 for job in jobs), jobs
        result = {
            "screenshots": len(drawings),
            "unique_images": len(images),
            "workbook_bytes": workbook.stat().st_size,
            "export_seconds": export_seconds,
            "jobs": jobs,
            "browser_errors": errors,
        }
        (output / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
        browser.close()
finally:
    response = requests.delete(
        base + f"/api/user/{uid}",
        headers=headers,
        params={"remove": "account"},
        timeout=60,
    )
    response.raise_for_status()
    print("Disposable account removed", flush=True)
