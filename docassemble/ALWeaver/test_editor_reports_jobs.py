# do not pre-load
"""Reports leave HTTP workers immediately and preserve owner/review boundaries."""

from contextlib import ExitStack
from unittest.mock import patch
import base64
from datetime import date
import time

import pytest

from .test_editor_api import api_editor
from .test_editor_ai_jobs import Redis


class ReportRedis(Redis):
    def delete(self, key):
        self.values.pop(key, None)

    def exists(self, key):
        return key in self.values

    def hset(self, key, field, value):
        self.values.setdefault(key, {})[field] = value

    def hget(self, key, field):
        return self.values.get(key, {}).get(field)

    def hgetall(self, key):
        return self.values.get(key, {}).copy()


@pytest.fixture
def reports():
    redis = ReportRedis()
    with ExitStack() as stack:
        stack.enter_context(patch.object(api_editor, "r", redis))
        stack.enter_context(
            patch.object(api_editor, "_editor_auth_check", return_value=True)
        )
        stack.enter_context(
            patch.object(api_editor, "_current_user_id", return_value=7)
        )
        stack.enter_context(
            patch.object(api_editor, "worker_configuration_is_ready", return_value=True)
        )
        send = stack.enter_context(patch.object(api_editor.workerapp, "send_task"))
        yield api_editor.app.test_client(), redis, send


@pytest.mark.parametrize(
    "operation", ["scan", "wording/prepare", "wording/export", "wording/import"]
)
def test_submit_only_queues_and_worker_completes(reports, operation):
    from io import BytesIO

    client, redis, send = reports
    payload = {"project": "default", "filename": "main.yml"}
    with patch.object(
        api_editor,
        "_scan_report_result",
        return_value={"blocks": [], "date": date(2026, 1, 1)},
    ) as scan, patch.object(
        api_editor, "_wording_report_result", return_value={"changes": []}
    ) as wording:
        if operation == "wording/import":
            response = client.post(
                "/al/editor/api/reports/" + operation,
                data={**payload, "workbook": (BytesIO(b"xlsx"), "test.xlsx")},
            )
        else:
            response = client.post("/al/editor/api/reports/" + operation, json=payload)
        assert response.status_code == 202
        scan.assert_not_called()
        wording.assert_not_called()
        job = response.json["data"]
        assert send.call_args.kwargs["kwargs"] == {"job_id": job["job_id"], "uid": 7}
        assert client.get(job["job_url"]).json["data"]["status"] == "queued"
        # Deliberately no Flask request context in the worker.
        api_editor._complete_report_job(job["job_id"], 7)
        result = client.get(job["job_url"]).json["data"]
        assert result["status"] == "succeeded"
        if operation == "wording/import":
            assert base64.b64decode(wording.call_args.args[2]["workbook"]) == b"xlsx"
        assert (
            redis.get(
                api_editor._job_state_key(api_editor.REPORT_JOB, job["job_id"])
                + ":payload"
            )
            is None
        )
        # Duplicate delivery cannot repeat an import write.
        api_editor._complete_report_job(job["job_id"], 7)
        assert scan.call_count + wording.call_count == 1
        with patch.object(api_editor, "_current_user_id", return_value=8):
            assert client.get(job["job_url"]).status_code == 404
        with patch.object(api_editor, "_editor_auth_check", return_value=False):
            assert client.get(job["job_url"]).status_code == 401


def test_failure_and_lost_worker_are_terminal(reports):
    client, _, _ = reports
    response = client.post(
        "/al/editor/api/reports/scan",
        json={"project": "default", "filename": "main.yml"},
    )
    job = response.json["data"]
    with patch.object(
        api_editor, "_scan_report_result", side_effect=ValueError("Missing interview")
    ):
        api_editor._complete_report_job(job["job_id"], 7)
    assert (
        client.get(job["job_url"]).json["data"]["error"]["message"]
        == "Missing interview"
    )
    api_editor._update_job_state(
        api_editor.REPORT_JOB,
        job["job_id"],
        status="running",
        started_at=time.time() - api_editor.REPORT_HARD_LIMIT - 61,
    )
    assert client.get(job["job_url"]).json["data"]["status"] == "expired"


def test_large_screenshot_workbook_roundtrip(reports):
    from .editor_utils import source_revision
    from io import BytesIO
    from PIL import Image
    import zipfile

    client, redis, _ = reports
    transfer = client.post(
        "/al/editor/api/reports/uploads", json={"kind": "previews"}
    ).json["data"]["upload_id"]
    source = "---\n".join(
        f"question: Screen {i}\nyesno: answer_{i}\n" for i in range(260)
    )
    with patch.object(
        api_editor, "_report_entrypoint", return_value="main.yml"
    ), patch.object(
        api_editor, "playground_read_yaml", return_value=source
    ), patch.object(
        api_editor, "source_revision", wraps=source_revision
    ):
        payload = {"project": "default", "filename": "main.yml"}
        prepared = api_editor._wording_report_result(7, "prepare", payload)
        assert len(prepared["screens"]) == 260
        manifest = {}
        for i, screen in enumerate(prepared["screens"]):
            png = BytesIO()
            Image.new("RGB", (10, 10), (i % 256, i // 256, 0)).save(png, format="PNG")
            raw = base64.b64encode(png.getvalue())
            manifest[screen["id"] + "|"] = {"chunks": 2, "bytes": len(raw)}
            for index, part in enumerate((raw[:20], raw[20:])):
                response = client.post(
                    "/al/editor/api/reports/uploads/" + transfer,
                    data={
                        "index": screen["id"] + "|" + str(index),
                        "part": (BytesIO(part), "part"),
                    },
                )
                assert response.status_code == 200
        exported = api_editor._wording_report_result(
            7,
            "export",
            {
                **payload,
                "revisions": prepared["revisions"],
                "upload_id": transfer,
                "manifest": manifest,
            },
        )
        content = base64.b64decode(exported["content"])
        with zipfile.ZipFile(BytesIO(content)) as archive:
            assert (
                len(
                    [
                        name
                        for name in archive.namelist()
                        if name.startswith("xl/media/")
                    ]
                )
                == 260
            )
        transfer = client.post(
            "/al/editor/api/reports/uploads", json={"kind": "workbook"}
        ).json["data"]["upload_id"]
        for i, offset in enumerate(range(0, len(content), 4096)):
            response = client.post(
                "/al/editor/api/reports/uploads/" + transfer,
                data={
                    "index": str(i),
                    "part": (BytesIO(content[offset : offset + 4096]), "part"),
                },
            )
            assert response.status_code == 200
        manifest = {
            "": {"chunks": (len(content) + 4095) // 4096, "bytes": len(content)}
        }
        from . import text_workbook

        with zipfile.ZipFile(BytesIO(content)) as archive:
            xml_bytes = sum(
                info.file_size
                for info in archive.infolist()
                if not info.filename.startswith("xl/media/")
            )
        with patch.object(text_workbook, "MAX_UNCOMPRESSED", xml_bytes):
            imported = api_editor._wording_report_result(
                7, "import", {**payload, "upload_id": transfer, "manifest": manifest}
            )
        with patch.object(
            text_workbook, "MAX_UNCOMPRESSED", xml_bytes - 1
        ), pytest.raises(ValueError, match="too large"):
            api_editor._wording_report_result(
                7, "import", {**payload, "upload_id": transfer, "manifest": manifest}
            )
        assert imported["changes"] == []
        assert imported["applied"] is False


def test_unconfigured_worker_fails_without_queueing(reports):
    client, _, send = reports
    with patch.object(api_editor, "worker_configuration_is_ready", return_value=False):
        response = client.post(
            "/al/editor/api/reports/scan", json={"filename": "main.yml"}
        )
    assert response.status_code == 503
    send.assert_not_called()


def test_broker_failure_cleans_up_upload(reports):
    client, redis, send = reports
    send.side_effect = RuntimeError("broker down")
    response = client.post(
        "/al/editor/api/reports/wording/prepare", json={"filename": "main.yml"}
    )
    assert response.status_code == 503
    assert not any(key.endswith(":payload") for key in redis.values)


def test_upload_owner_size_and_retry_boundaries(reports):
    from io import BytesIO

    client, redis, _ = reports
    transfer = client.post(
        "/al/editor/api/reports/uploads", json={"kind": "workbook"}
    ).json["data"]["upload_id"]

    def upload(content):
        return client.post(
            "/al/editor/api/reports/uploads/" + transfer,
            data={"index": "0", "part": (BytesIO(content), "part")},
        )

    with patch.object(api_editor, "_current_user_id", return_value=8):
        assert upload(b"secret").status_code == 400
        with pytest.raises(ValueError, match="not found"):
            api_editor._report_upload_parts(8, transfer, "workbook")
    with patch.object(api_editor, "REPORT_UPLOAD_LIMIT", 5):
        assert upload(b"12345").status_code == 200
        assert upload(b"12345").status_code == 200  # retry replaces, not appends
        assert upload(b"123456").status_code == 400
    assert api_editor._report_upload_parts(
        7, transfer, "workbook", {"": {"chunks": 1, "bytes": 5}}
    ) == {"0": b"12345"}
    with pytest.raises(ValueError, match="Wrong upload type"):
        api_editor._report_upload_parts(7, transfer, "previews")
    redis.delete(api_editor._report_upload_key(transfer))
    assert upload(b"x").status_code == 400


def test_upload_manifest_rejects_missing_final_parts_and_tiles(reports):
    from io import BytesIO

    client, _, _ = reports
    token = client.post(
        "/al/editor/api/reports/uploads", json={"kind": "previews"}
    ).json["data"]["upload_id"]
    client.post(
        "/al/editor/api/reports/uploads/" + token,
        data={"index": "screen|0|0", "part": (BytesIO(b"png"), "part")},
    )
    for manifest in [
        {"screen|0|": {"chunks": 2, "bytes": 6}},
        {
            "screen|0|": {"chunks": 1, "bytes": 3},
            "screen|1|": {"chunks": 1, "bytes": 3},
        },
    ]:
        with pytest.raises(ValueError, match="incomplete"):
            api_editor._report_upload_parts(7, token, "previews", manifest)


def test_upload_account_quota_and_cleanup(reports):
    from io import BytesIO

    client, _, _ = reports
    tokens = [
        client.post("/al/editor/api/reports/uploads", json={"kind": "workbook"}).json[
            "data"
        ]["upload_id"]
        for _ in range(4)
    ]
    assert (
        client.post(
            "/al/editor/api/reports/uploads", json={"kind": "workbook"}
        ).status_code
        == 429
    )

    def upload(token):
        return client.post(
            "/al/editor/api/reports/uploads/" + token,
            data={"index": "0", "part": (BytesIO(b"123"), "part")},
        )

    with patch.object(api_editor, "REPORT_UPLOAD_LIMIT", 5):
        assert upload(tokens[0]).status_code == 200
        assert upload(tokens[1]).status_code == 400
        api_editor._delete_report_upload(tokens[0])
        assert upload(tokens[1]).status_code == 200
    assert (
        client.post(
            "/al/editor/api/reports/uploads", json={"kind": "workbook"}
        ).status_code
        == 200
    )


def test_large_repository_archive_uses_chunks_and_releases_results(reports):
    from io import BytesIO
    import zipfile

    client, redis, _ = reports
    token = client.post(
        "/al/editor/api/reports/uploads", json={"kind": "reports"}
    ).json["data"]["upload_id"]
    html = b"<h1>Report</h1>" + b"x" * (17 * 1024 * 1024)
    size = 512 * 1024
    with patch.dict(api_editor.app.config, {"MAX_CONTENT_LENGTH": 2 * 1024 * 1024}):
        for index, start in enumerate(range(0, len(html), size)):
            response = client.post(
                "/al/editor/api/reports/uploads/" + token,
                data={
                    "index": "main.yml|" + str(index),
                    "part": (BytesIO(html[start : start + size]), "part"),
                },
            )
            assert response.status_code == 200
        job = client.post(
            "/al/editor/api/reports/archive",
            json={
                "reports": [{"filename": "main.yml"}],
                "upload_id": token,
                "manifest": {
                    "main.yml|": {
                        "chunks": (len(html) + size - 1) // size,
                        "bytes": len(html),
                    }
                },
            },
        )
    assert job.status_code == 202
    job = job.json["data"]
    api_editor._complete_report_job(job["job_id"], 7)
    result = client.get(job["job_url"]).json["data"]
    assert result["status"] == "succeeded", result
    with zipfile.ZipFile(
        BytesIO(base64.b64decode(result["result"]["content"]))
    ) as archive:
        assert archive.read("main.yml.html") == html
    assert not redis.get(api_editor._report_upload_key(token))
    assert not redis.hgetall(api_editor._report_upload_key(token) + ":parts")
    assert (
        api_editor._load_job_state(api_editor.REPORT_JOB, job["job_id"])["result"]
        is None
    )
    with patch.object(api_editor, "_current_user_id", return_value=8):
        assert client.post(job["job_url"] + "/ack").status_code == 404
    assert client.post(job["job_url"] + "/ack").status_code == 200
    assert not redis.exists(api_editor._report_result_key(job["job_id"]))


def test_result_quota_cannot_turn_a_successful_apply_into_failure(reports):
    from io import BytesIO

    client, _, _ = reports
    job = client.post(
        "/al/editor/api/reports/wording/import",
        data={
            "filename": "main.yml",
            "apply": "true",
            "workbook": (BytesIO(b"xlsx"), "test.xlsx"),
        },
    ).json["data"]
    with patch.object(
        api_editor,
        "_wording_report_result",
        return_value={"applied": True, "changes": [{}]},
    ), patch.object(api_editor, "REPORT_UPLOAD_LIMIT", 1):
        api_editor._complete_report_job(job["job_id"], 7)
    result = client.get(job["job_url"]).json["data"]
    assert result["status"] == "succeeded"
    assert result["result"] == {"applied": True, "change_count": 1}


def test_abandoned_transfer_release_is_owned_and_idempotent(reports):
    client, redis, _ = reports
    token = client.post(
        "/al/editor/api/reports/uploads", json={"kind": "workbook"}
    ).json["data"]["upload_id"]
    url = "/al/editor/api/reports/uploads/" + token + "/release"
    with patch.object(api_editor, "_current_user_id", return_value=8):
        assert client.post(url).status_code == 404
    assert client.post(url).status_code == 200
    assert client.post(url).status_code == 200
    assert redis.get(api_editor._report_upload_key(token)) is None


def test_failed_export_releases_transfer(reports):
    client, redis, _ = reports
    token = client.post(
        "/al/editor/api/reports/uploads", json={"kind": "previews"}
    ).json["data"]["upload_id"]
    job = client.post(
        "/al/editor/api/reports/wording/export",
        json={"filename": "main.yml", "upload_id": token},
    ).json["data"]
    with patch.object(
        api_editor, "_wording_report_result", side_effect=ValueError("Source changed")
    ):
        api_editor._complete_report_job(job["job_id"], 7)
    assert client.get(job["job_url"]).json["data"]["status"] == "failed"
    assert redis.get(api_editor._report_upload_key(token)) is None


def test_poll_expiry_cannot_race_worker_start(reports):
    client, redis, _ = reports
    job = client.post(
        "/al/editor/api/reports/scan", json={"filename": "main.yml"}
    ).json["data"]
    api_editor._update_job_state(
        api_editor.REPORT_JOB,
        job["job_id"],
        queued_at=time.time() - api_editor.REPORT_QUEUE_SECONDS - 1,
    )
    lock = redis.lock(
        api_editor._job_state_key(api_editor.REPORT_JOB, job["job_id"]) + ":run"
    )
    with lock:
        assert client.get(job["job_url"]).json["data"]["status"] == "queued"
    assert client.get(job["job_url"]).json["data"]["status"] == "expired"
    with patch.object(api_editor, "_scan_report_result") as work:
        api_editor._complete_report_job(job["job_id"], 7)
        work.assert_not_called()
