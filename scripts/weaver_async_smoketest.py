#!/usr/bin/env python3
"""
Async smoke test for the ALWeaver REST API.

Runs:
1) POST /al/api/v1/weaver (mode=async)
2) Poll GET /al/api/v1/weaver/jobs/{job_id} until finished
3) Decode package_zip_base64 (if requested) to /tmp and extract it

Designed for quick manual verification of generated artifacts.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import yaml

DEFAULT_BASE = "https://apps-dev.suffolklitlab.org/al/api/v1/weaver"


@dataclass(frozen=True)
class JobResult:
    job_id: str
    status: str
    celery_state: str
    job_json_path: Path
    zip_path: Optional[Path]
    extract_dir: Optional[Path]
    yml_path: Optional[Path]


def _load_apikey(server_name: str) -> str:
    cfg_path = Path("~/.docassemblecli").expanduser()
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    for entry in data:
        if entry.get("name") == server_name and entry.get("apikey"):
            return str(entry["apikey"])
    raise SystemExit(f"Could not find api key for {server_name!r} in {cfg_path}.")


def _poll_job(
    session: requests.Session,
    base: str,
    apikey: str,
    job_id: str,
    *,
    timeout_s: int,
    poll_interval_s: float,
    stem: str,
) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    job_url = f"{base}/jobs/{job_id}"
    last: Dict[str, Any] = {}
    headers = {"X-API-Key": apikey}
    poll_idx = 0
    while True:
        poll_idx += 1
        resp = session.get(job_url, headers=headers, timeout=60)
        resp.raise_for_status()
        last = resp.json()
        status = (last.get("status") or "").lower()
        celery_state = (last.get("celery_state") or "").upper()
        print(f"{stem}: poll {poll_idx}: status={status} celery_state={celery_state}")
        if status in {"succeeded", "failed"}:
            return last
        if time.time() >= deadline:
            raise SystemExit(f"{stem}: timed out waiting for job {job_id}")
        time.sleep(poll_interval_s)


def _extract_first_yml(extract_dir: Path) -> Optional[Path]:
    ymls = sorted(extract_dir.rglob("*.yml"))
    return ymls[0] if ymls else None


def submit_and_fetch(
    *,
    base: str,
    apikey: str,
    file_path: Path,
    mode: str,
    include_next_steps: bool,
    include_download_screen: bool,
    create_package_zip: bool,
    include_package_zip_base64: bool,
    include_yaml_text: bool,
    timeout_s: int,
    poll_interval_s: float,
) -> JobResult:
    if not file_path.exists():
        raise SystemExit(f"File does not exist: {file_path}")
    stem = file_path.stem

    with requests.Session() as session:
        headers = {"X-API-Key": apikey}
        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f)}
            data = {
                "mode": mode,
                "include_next_steps": str(include_next_steps).lower(),
                "include_download_screen": str(include_download_screen).lower(),
                "create_package_zip": str(create_package_zip).lower(),
                "include_package_zip_base64": str(include_package_zip_base64).lower(),
                "include_yaml_text": str(include_yaml_text).lower(),
            }
            resp = session.post(
                base, headers=headers, files=files, data=data, timeout=300
            )
        # API uses 202 for async accepted; if config is wrong, we may get 503.
        try:
            post_body = resp.json()
        except Exception:
            raise SystemExit(f"{stem}: non-JSON response from POST: {resp.status_code}")
        if resp.status_code != 202:
            raise SystemExit(
                f"{stem}: POST failed: {resp.status_code} body={post_body}"
            )

        job_id = str(post_body.get("job_id") or "")
        if not job_id:
            raise SystemExit(f"{stem}: POST response missing job_id: {post_body}")
        print(f"{stem}: job_id={job_id}")

        job = _poll_job(
            session,
            base,
            apikey,
            job_id,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            stem=stem,
        )

    job_json_path = Path(f"/tmp/weaver_{stem}_job.json")
    job_json_path.write_text(
        json.dumps(job, indent=2, sort_keys=True), encoding="utf-8"
    )

    status = str(job.get("status") or "")
    celery_state = str(job.get("celery_state") or "")
    if status != "succeeded":
        return JobResult(
            job_id=job_id,
            status=status,
            celery_state=celery_state,
            job_json_path=job_json_path,
            zip_path=None,
            extract_dir=None,
            yml_path=None,
        )

    data = job.get("data") or {}
    zip_b64 = data.get("package_zip_base64")
    if not zip_b64:
        return JobResult(
            job_id=job_id,
            status=status,
            celery_state=celery_state,
            job_json_path=job_json_path,
            zip_path=None,
            extract_dir=None,
            yml_path=None,
        )

    zip_path = Path(f"/tmp/weaver_artifacts_{stem}.zip")
    zip_bytes = base64.b64decode(zip_b64)
    zip_path.write_bytes(zip_bytes)
    extract_dir = Path(f"/tmp/weaver_artifacts_{stem}")
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    yml_path = _extract_first_yml(extract_dir)

    return JobResult(
        job_id=job_id,
        status=status,
        celery_state=celery_state,
        job_json_path=job_json_path,
        zip_path=zip_path,
        extract_dir=extract_dir,
        yml_path=yml_path,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", help="Template files to upload (pdf/docx).")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--server-name", default="apps-dev.suffolklitlab.org")
    parser.add_argument("--mode", default="async", choices=["async", "sync"])
    parser.add_argument("--include-next-steps", default=False, action="store_true")
    parser.add_argument("--no-download-screen", default=False, action="store_true")
    parser.add_argument("--no-zip", default=False, action="store_true")
    parser.add_argument("--include-zip-base64", default=True, action="store_true")
    parser.add_argument("--no-yaml-text", default=False, action="store_true")
    parser.add_argument("--timeout-s", type=int, default=180)
    parser.add_argument("--poll-interval-s", type=float, default=2.0)
    args = parser.parse_args(argv)

    apikey = _load_apikey(args.server_name)

    include_download_screen = not args.no_download_screen
    create_package_zip = not args.no_zip
    include_package_zip_base64 = bool(args.include_zip_base64)
    include_yaml_text = not args.no_yaml_text

    for file_arg in args.files:
        file_path = Path(file_arg)
        try:
            res = submit_and_fetch(
                base=args.base,
                apikey=apikey,
                file_path=file_path,
                mode=args.mode,
                include_next_steps=args.include_next_steps,
                include_download_screen=include_download_screen,
                create_package_zip=create_package_zip,
                include_package_zip_base64=include_package_zip_base64,
                include_yaml_text=include_yaml_text,
                timeout_s=args.timeout_s,
                poll_interval_s=args.poll_interval_s,
            )
        except requests.RequestException as exc:
            print(f"{file_path.name}: request error: {exc}", file=sys.stderr)
            continue
        except SystemExit as exc:
            print(str(exc), file=sys.stderr)
            continue

        print(
            f"{file_path.stem}: FINAL status={res.status} celery_state={res.celery_state}"
        )
        print(f"{file_path.stem}: job_json={res.job_json_path}")
        if res.zip_path:
            print(f"{file_path.stem}: zip={res.zip_path}")
        if res.extract_dir:
            print(f"{file_path.stem}: extracted={res.extract_dir}")
        if res.yml_path:
            print(f"{file_path.stem}: yml={res.yml_path}")
            txt = res.yml_path.read_text(encoding="utf-8")
            print(
                f"{file_path.stem}: contains users.gather()={'users.gather()' in txt}"
            )
            print(f"{file_path.stem}: contains docket_number={'docket_number' in txt}")
            print(
                f"{file_path.stem}: contains users[0].email={'users[0].email' in txt}"
            )
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
