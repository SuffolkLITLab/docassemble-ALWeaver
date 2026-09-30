#!/usr/bin/env python3
"""Run a bounded, disposable 15-developer stress test against localhost.

Uses saved local admin credentials only for fixture creation/removal. Every
virtual developer signs in separately. No credentials, cookies, source text,
or model prompts are written to the public result files. AI calls require a
configured provider; use a local delayed provider fixture for a cost-free run.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


class StressRun:
    def __init__(self, args):
        self.args = args
        self.base = args.base_url.rstrip("/")
        self.admin = json.loads(Path(args.credentials).expanduser().read_text())
        self.prefix = "WeaverStress" + datetime.now(timezone.utc).strftime(
            "%Y%m%d%H%M%S"
        )
        self.users = []
        self.samples = []
        self.resources = []
        self.jobs = []
        self.failures = []
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.started = 0.0
        self.phases = ("legacy_polling_replay", "adaptive_polling", "mixed_editor_ai")
        self.output = Path(args.output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.private = self.output / "cleanup-private.json"
        self.private.touch(mode=0o600)
        self.private.chmod(0o600)

    def save_cleanup(self):
        self.private.write_text(json.dumps(self.users))
        self.private.chmod(0o600)

    def login(self, email, password):
        session = requests.Session()
        response = session.get(self.base + "/user/sign-in", timeout=30)
        form = BeautifulSoup(response.text, "html.parser").find("form")
        data = {
            field["name"]: field.get("value", "")
            for field in form.select("input[name]")
        }
        data.update(email=email, password=password)
        response = session.post(self.base + "/user/sign-in", data=data, timeout=30)
        response = session.get(self.base + "/al/editor/api/projects", timeout=30)
        response.raise_for_status()
        session.headers["X-CSRFToken"] = data["csrf_token"]
        return session

    def call(self, session, method, path, phase="setup", expected=(200,), **kwargs):
        started = time.monotonic()
        status = 0
        payload = {}
        try:
            response = session.request(method, self.base + path, timeout=30, **kwargs)
            status = response.status_code
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if status not in expected:
                raise RuntimeError(
                    f"HTTP {status}: {str(payload.get('error', ''))[:220]}"
                )
        except Exception as exc:
            with self.lock:
                self.failures.append(
                    {
                        "phase": phase,
                        "endpoint": path.split("?")[0],
                        "error": str(exc)[:300],
                    }
                )
        elapsed = time.monotonic() - started
        if phase in self.phases:
            with self.lock:
                self.samples.append(
                    {
                        "phase": phase,
                        "endpoint": re.sub(
                            r"/sessions/[^/]+",
                            "/sessions/<id>",
                            re.sub(r"/jobs/[^/?]+", "/jobs/<id>", path.split("?")[0]),
                        ),
                        "method": method,
                        "status": status,
                        "seconds": elapsed,
                        "at": time.monotonic() - self.started,
                    }
                )
        return status, payload

    def setup(self):
        api_headers = {"X-API-Key": self.admin["api_key"]}
        native = requests.Session()
        for index in range(self.args.clients):
            email = f"{self.prefix.lower()}-{index}@example.com"
            password = secrets.token_urlsafe(24)
            response = native.post(
                self.base + "/api/user/new",
                headers=api_headers,
                json={
                    "username": email,
                    "password": password,
                    "privileges": ["developer"],
                    "first_name": "Stress",
                    "last_name": f"Fixture {index}",
                },
                timeout=30,
            )
            response.raise_for_status()
            uid = response.json()["user_id"]
            user = {
                "user_id": uid,
                "email": email,
                "project": self.prefix,
                "runtime_id": None,
                "cookies": None,
            }
            self.users.append(user)
            self.save_cleanup()
            session = self.login(email, password)
            response = native.post(
                self.base + "/api/playground/project",
                headers=api_headers,
                data={"project": self.prefix, "user_id": uid},
                timeout=30,
            )
            response.raise_for_status()
            sources = {
                "main.yml": "include:\n  - symbols.yml\n---\nid: order\nmandatory: True\ncode: |\n  demo_name\n  final_screen\n---\nid: intro\nquestion: Classroom stress fixture\nfields:\n  - Name: demo_name\n---\nid: final\nevent: final_screen\nquestion: Complete\n",
                "symbols.yml": "include:\n  - leaf.yml\n"
                + "".join(
                    f"---\nid: helper_{n}\ncode: |\n  helper_value_{n} = {n}\n"
                    for n in range(40)
                ),
                "leaf.yml": "".join(
                    f"---\nid: included_{n}\nquestion: Included question {n}\nfields:\n  - Answer: included_value_{n}\n"
                    for n in range(40)
                ),
            }
            for filename, content in sources.items():
                response = native.post(
                    self.base + "/api/playground",
                    headers=api_headers,
                    data={
                        "project": self.prefix,
                        "folder": "questions",
                        "user_id": uid,
                    },
                    files={"file": (filename, content.encode(), "application/yaml")},
                    timeout=30,
                )
                response.raise_for_status()
            status, payload = self.call(
                session,
                "POST",
                "/al/editor/api/runtime/sessions",
                expected=(201,),
                json={"project": self.prefix, "filename": "main.yml"},
            )
            if status != 201:
                raise RuntimeError("Runtime fixture creation failed")
            user["runtime_id"] = payload["data"]["weaver_session_id"]
            user["cookies"] = requests.utils.dict_from_cookiejar(session.cookies)
            user["csrf"] = session.headers["X-CSRFToken"]
            self.save_cleanup()
            print(
                f"Prepared disposable developer {index + 1}/{self.args.clients}",
                flush=True,
            )

    def session(self, user):
        session = requests.Session()
        session.cookies.update(user["cookies"])
        session.headers["X-CSRFToken"] = user["csrf"]
        return session

    def phase(self):
        elapsed = time.monotonic() - self.started
        index = (
            0
            if elapsed < self.args.seconds / 4
            else (1 if elapsed < self.args.seconds / 2 else 2)
        )
        return self.phases[index]

    def client(self, index, user):
        rng = random.Random(index)
        session = self.session(user)
        path = "/al/editor/api/runtime/sessions/" + user["runtime_id"]
        next_poll = 0.0
        next_editor = index * 0.17
        next_seed = 30 + index * 0.1
        previous = None
        delay = 5.0
        while (
            not self.stop.is_set()
            and time.monotonic() - self.started < self.args.seconds
        ):
            elapsed = time.monotonic() - self.started
            phase = self.phase()
            if phase == "legacy_polling_replay" and elapsed >= next_poll:
                before = time.monotonic()
                self.call(session, "GET", path + "/question", phase)
                self.call(session, "GET", path + "/variables", phase)
                next_poll = elapsed + max(1.0, time.monotonic() - before)
            elif phase != "legacy_polling_replay" and elapsed >= next_poll:
                status, payload = self.call(session, "GET", path + "/snapshot", phase)
                data = payload.get("data")
                if status == 200:
                    delay = min(10, delay * 1.5) if previous == data else 5
                    previous = data
                else:
                    delay = min(30, delay * 2)
                next_poll = (
                    time.monotonic() - self.started + delay * rng.uniform(0.9, 1.1)
                )
            if elapsed >= next_editor:
                params = {"project": user["project"], "filename": "main.yml"}
                for endpoint in (
                    "file",
                    "variables",
                    "weaver/validate",
                    "weaver/style-check",
                ):
                    extra = (
                        {"include_llm": "0"} if endpoint.endswith("style-check") else {}
                    )
                    self.call(
                        session,
                        "GET",
                        "/al/editor/api/" + endpoint,
                        phase,
                        params={**params, **extra},
                    )
                next_editor = time.monotonic() - self.started + 15 + rng.uniform(0, 3)
            if elapsed >= next_seed:
                self.call(
                    session,
                    "POST",
                    path + "/variables",
                    phase,
                    json={
                        "variables": {"stress_counter": int(elapsed)},
                        "overwrite": True,
                    },
                )
                next_seed = time.monotonic() - self.started + 30
            self.stop.wait(0.05)

    def ai(self, index, user):
        session = self.session(user)
        self.stop.wait(self.args.seconds / 2 + index * 0.1)
        if self.stop.is_set():
            return
        for operation in ("generate-screen", "generate-fields"):
            phase = "mixed_editor_ai"
            body = {
                "project": user["project"],
                "filename": "main.yml",
                "block_id": "intro",
                "field_types": ["text"],
            }
            started = time.monotonic()
            status, queued = self.call(
                session,
                "POST",
                "/al/editor/api/ai/" + operation,
                phase,
                expected=(202,),
                json=body,
            )
            if status != 202:
                return
            status, _ = self.call(
                session,
                "POST",
                "/al/editor/api/ai/" + operation,
                phase,
                expected=(429,),
                json=body,
            )
            if status != 429:
                return
            job_url = queued["data"]["job_url"]
            terminal = None
            while (
                not self.stop.is_set()
                and time.monotonic() - self.started < self.args.seconds
            ):
                self.stop.wait(3)
                _, result = self.call(session, "GET", job_url, phase)
                terminal = result.get("data", {}).get("status")
                if terminal in {"succeeded", "failed", "expired", "cancelled"}:
                    break
            with self.lock:
                self.jobs.append(
                    {
                        "client": index,
                        "operation": operation,
                        "status": terminal,
                        "seconds": time.monotonic() - started,
                    }
                )
            if terminal != "succeeded":
                with self.lock:
                    self.failures.append(
                        {
                            "phase": phase,
                            "endpoint": operation,
                            "error": f"Job ended in {terminal}",
                        }
                    )
                return

    def monitor(self):
        code = """
import json, pathlib, urllib.request
p = pathlib.Path('/sys/fs/cgroup')
def fields(path):
    return dict(line.split() for line in path.read_text().splitlines())
if (p / 'memory.current').exists():
    stats = fields(p / 'memory.stat')
    data = {'cgroup_version': 2, 'memory_bytes': int((p / 'memory.current').read_text()),
            'inactive_file_bytes': int(stats.get('inactive_file', 0)),
            'swap_bytes': int((p / 'memory.swap.current').read_text()),
            'cpu': fields(p / 'cpu.stat'), 'memory_events': fields(p / 'memory.events')}
else:
    memory = p / 'memory'
    stats = fields(memory / 'memory.stat')
    used = int((memory / 'memory.usage_in_bytes').read_text())
    combined = memory / 'memory.memsw.usage_in_bytes'
    cpu = fields(p / 'cpu' / 'cpu.stat')
    cpu['usage_usec'] = int((p / 'cpuacct' / 'cpuacct.usage').read_text()) // 1000
    data = {'cgroup_version': 1, 'memory_bytes': used,
            'inactive_file_bytes': int(stats.get('total_inactive_file', stats.get('inactive_file', 0))),
            'swap_bytes': max(0, int(combined.read_text()) - used) if combined.exists() else None,
            'cpu': cpu, 'memory_events': fields(memory / 'memory.oom_control')}
try:
    data['model_fixture'] = json.load(urllib.request.urlopen('http://127.0.0.1:18089/metrics', timeout=2))
except Exception:
    data['model_fixture'] = None
print(json.dumps(data))
"""
        previous = None
        initial_oom = None
        while not self.stop.is_set():
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.args.container,
                    "/usr/share/docassemble/local3.14/bin/python",
                    "-c",
                    code,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                data.update(at=time.monotonic() - self.started, phase=self.phase())
                data["working_set_bytes"] = (
                    data["memory_bytes"] - data["inactive_file_bytes"]
                )
                if previous:
                    data["cpu_percent"] = (
                        100
                        * (
                            int(data["cpu"]["usage_usec"])
                            - int(previous["cpu"]["usage_usec"])
                        )
                        / ((data["at"] - previous["at"]) * 1_000_000)
                    )
                previous = data
                oom = int(data["memory_events"].get("oom_kill", 0))
                if initial_oom is None:
                    initial_oom = oom
                with self.lock:
                    self.resources.append(data)
                if data["working_set_bytes"] > 7.5 * 1024**3 or oom > initial_oom:
                    with self.lock:
                        self.failures.append(
                            {
                                "phase": self.phase(),
                                "error": "Stopped at memory/OOM safety threshold",
                            }
                        )
                    self.stop.set()
            else:
                with self.lock:
                    self.failures.append(
                        {
                            "phase": self.phase(),
                            "error": "Resource monitor failed: " + result.stderr[-300:],
                        }
                    )
                self.stop.set()
            self.stop.wait(5)

    def cleanup(self):
        headers = {"X-API-Key": self.admin["api_key"]}
        failed_users = []
        for user in self.users:
            try:
                if user.get("cookies"):
                    session = self.session(user)
                    if user.get("runtime_id"):
                        session.delete(
                            self.base
                            + "/al/editor/api/runtime/sessions/"
                            + user["runtime_id"],
                            timeout=30,
                        )
                    response = session.post(
                        self.base + "/al/editor/api/project/delete",
                        json={"project": user["project"]},
                        timeout=30,
                    )
                    if response.status_code != 200:
                        print(
                            f"Cleanup warning: project for fixture user {user['user_id']} HTTP {response.status_code}",
                            flush=True,
                        )
                response = requests.delete(
                    self.base + f"/api/user/{user['user_id']}",
                    params={"remove": "account"},
                    headers=headers,
                    timeout=30,
                )
                if response.status_code != 204:
                    raise RuntimeError(f"User cleanup HTTP {response.status_code}")
            except Exception as exc:
                print(f"Cleanup warning: {exc}", flush=True)
                with self.lock:
                    self.failures.append({"phase": "cleanup", "error": str(exc)})
                failed_users.append(user)
        if failed_users:
            self.private.write_text(json.dumps(failed_users))
            self.private.chmod(0o600)
        else:
            self.private.unlink(missing_ok=True)

    def report(self):
        def distribution(values):
            values = sorted(values)
            return (
                {
                    "count": len(values),
                    "p50_ms": round(values[int((len(values) - 1) * 0.5)] * 1000, 1),
                    "p95_ms": round(values[int((len(values) - 1) * 0.95)] * 1000, 1),
                    "p99_ms": round(values[int((len(values) - 1) * 0.99)] * 1000, 1),
                    "max_ms": round(values[-1] * 1000, 1),
                }
                if values
                else {}
            )

        groups = defaultdict(list)
        for sample in self.samples:
            groups[(sample["phase"], sample["endpoint"])].append(sample)
        summary = []
        for (phase, endpoint), samples in sorted(groups.items()):
            summary.append(
                {
                    "phase": phase,
                    "endpoint": endpoint,
                    **distribution([s["seconds"] for s in samples]),
                    "status_counts": dict(Counter(s["status"] for s in samples)),
                }
            )
        memory = []
        for phase in self.phases:
            samples = [s for s in self.resources if s["phase"] == phase]
            if samples:
                memory.append(
                    {
                        "phase": phase,
                        "peak_working_set_gib": round(
                            max(s["working_set_bytes"] for s in samples) / 1024**3, 3
                        ),
                        "peak_cgroup_memory_gib": round(
                            max(s["memory_bytes"] for s in samples) / 1024**3, 3
                        ),
                        "mean_cpu_percent": round(
                            sum(s.get("cpu_percent", 0) for s in samples)
                            / len(samples),
                            1,
                        ),
                        "max_cpu_percent": round(
                            max(s.get("cpu_percent", 0) for s in samples), 1
                        ),
                        "peak_swap_mib": round(
                            max(s["swap_bytes"] or 0 for s in samples) / 1024**2, 1
                        ),
                    }
                )
        result = {
            "started_utc": self.started_utc,
            "elapsed_seconds": round(time.monotonic() - self.started, 2),
            "planned_seconds": self.args.seconds,
            "clients": self.args.clients,
            "fixture": {
                "files_per_project": 3,
                "included_code_blocks": 40,
                "included_questions": 40,
            },
            "phase_seconds": dict(
                zip(
                    self.phases,
                    (
                        self.args.seconds / 4,
                        self.args.seconds / 4,
                        self.args.seconds / 2,
                    ),
                )
            ),
            "requests": summary,
            "resources": memory,
            "ai_jobs": self.jobs,
            "failures": self.failures,
            "limitations": [
                "Legacy phase replays the old request pattern against the optimized server; it is not a benchmark of the original backend.",
                "Virtual developer traffic uses HTTP sessions, not fifteen interactive browsers.",
                "Local model responses are a deterministic eight-second fixture, not live provider latency or quality.",
                "Host and container resource limits are recorded separately; an unlimited container does not validate an 8 GB deployment.",
            ],
        }
        (self.output / "results.json").write_text(json.dumps(result, indent=2))
        (self.output / "resource-samples.json").write_text(
            json.dumps(self.resources, indent=2)
        )
        (self.output / "request-samples.json").write_text(
            json.dumps(self.samples, indent=2)
        )
        print(
            json.dumps(
                {
                    "requests": len(self.samples),
                    "jobs": dict(Counter(job["status"] for job in self.jobs)),
                    "failures": len(self.failures),
                    "report": str(self.output / "results.json"),
                }
            ),
            flush=True,
        )

    def run(self):
        try:
            self.setup()
            self.started_utc = datetime.now(timezone.utc).isoformat()
            self.started = time.monotonic()
            print(
                f"Starting {self.args.seconds}s measured load, {self.args.clients} distinct developers",
                flush=True,
            )
            with ThreadPoolExecutor(max_workers=self.args.clients * 2 + 1) as pool:
                monitor = pool.submit(self.monitor)
                futures = [
                    pool.submit(self.client, i, user)
                    for i, user in enumerate(self.users)
                ]
                futures += [
                    pool.submit(self.ai, i, user) for i, user in enumerate(self.users)
                ]
                try:
                    for future in futures:
                        future.result()
                finally:
                    self.stop.set()
                monitor.result()
        finally:
            self.stop.set()
            self.cleanup()
            if self.started:
                self.report()
        return 1 if self.failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--credentials", default="~/.docassemble-local-admin.json")
    parser.add_argument("--clients", type=int, default=15)
    parser.add_argument("--seconds", type=int, default=360)
    parser.add_argument("--container", default="docassemble")
    parser.add_argument("--output", default="/tmp/alweaver-classroom-stress")
    args = parser.parse_args()
    if urlparse(args.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("This disposable fixture harness is restricted to localhost")
    if not 1 <= args.clients <= 15 or not 30 <= args.seconds <= 600:
        parser.error("Use 1–15 clients and 30–600 seconds")
    raise SystemExit(StressRun(args).run())


if __name__ == "__main__":
    main()
