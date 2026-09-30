# Classroom editor performance: implementation and localhost stress test

The optimized editor completed a six-minute localhost run with **15 distinct developer accounts, 5,442 measured HTTP requests, 30 successful AI jobs, and no unexpected failures**. Container working set peaked at **3.782 GiB**, with no new OOM kills. This supports reducing editor background load and protecting web requests during model waits. It does **not** establish capacity for document generation on an 8 GB machine.

## Scope and code changes

Branch: `optimize-classroom-performance`. Base: `8b2f6d52e3621a7922635a4a657d53c8d9b483a3`. The deployed implementation tested here is commit `dbda37e`; the earlier review supplied with the request referred to a different snapshot (`0a931134...`). The follow-up commit adds the harness and these findings, cleanup robustness in the harness, and a directory-invalidation fix discovered by the final full suite. The reported six-minute load predates that small fix; its correctness is verified by a deterministic regression test and the subsequent full suite.

| Area | Change | Important limits |
| --- | --- | --- |
| Debugger client | One combined snapshot request; completion-based polling at 5 seconds after changes, backing off to 10 seconds unchanged and 30 seconds after errors; ±10% jitter; suspend when hidden or closed; refresh on return/navigation | Each snapshot still obtains full question and simplified variables; no cheap revision protocol and no atomic snapshot |
| Runtime Redis | Reads touch the lifetime at most once per minute; question/variable polling no longer appends history events | Explicit action/scenario history remains; variable size rejection still happens after simplification |
| AI HTTP handlers | Screen drafts, field drafts, and explicit AI style checking return 202/job URL; browser follows terminal result and rejects stale editor context | This changes the API contract; web and worker versions must match |
| AI admission/execution | One outstanding job per account, two active jobs server-wide; nonblocking capacity retry after 5–10 seconds; 15-minute queue expiry; 150-second soft / 180-second hard Celery limits | Use prefork workers. These bounds cover these three editor operations, not all existing generation/assistant jobs. Provider retries share the execution deadline |
| Style checking | Deterministic checking remains synchronous and is the default; AI requires explicit `include_llm=1` | Deterministic linting still costs CPU |
| Symbol discovery | Cache serialized results for 60 seconds, track main file and transitive includes by content/hash/filesystem revision and include-directory metadata plus an entry-name hash; coalesce same-key work | Per-process, not cross-worker; skip unsafe/dynamic/untrackable sources and failures; validation still runs its other checks |
| Memory bounds | Symbol cache: 32 entries / 2 MiB total serialized, 256 KiB per result; template excerpts: separate 256 KiB cache; no retained Interview objects | Python object overhead is additional; template invalidation uses file/directory metadata |
| Deployment guidance | README documents trial worker sizing, required Celery module, API compatibility, and coordinated module restarts | Does not restrict the explicit server restart endpoint or isolate all background jobs |

Implementation files: `analysis_cache.py`, `editor_utils.py`, `runtime_sessions.py`, `api_editor.py`, `api_weaver_worker.py`, and the editor, API client, and runtime inspector JavaScript. Tests cover ownership, queueing, failure/expiry reconciliation, admission limits, template invalidation, transitive/empty include invalidation, cache bounds and concurrent misses, polling lifecycle, and stale results.

## Test environment and method

- Local Docker Docassemble 1.10.12, server Python 3.14; test client Python 3.12.
- Host RAM: 15.34 GiB. Container had **no memory or CPU limit**. Thus the test was not performed under an enforced 8 GB cap.
- One uWSGI request worker. Temporary `celery processes: 3` produced **two general prefork workers plus one dedicated single worker**. The original configuration restored afterwards starts seven general workers plus one single worker. Do not interpret the measured footprint as applying to that original worker count.
- Temporary configuration registered `docassemble.ALWeaver.api_weaver_worker` and routed model calls to a loopback-only fixture. The fixture delayed every completion eight seconds and returned deterministic JSON through the real SDK, Celery task, and YAML validation paths. It made no paid or external model requests.
- Fifteen disposable developer users, each owning a project with three YAML files, 40 included code blocks, 40 included question blocks, and a simple running interview. Requests used individual authenticated sessions and CSRF tokens.
- A 60-second, one-user preflight completed 65 requests and two AI jobs without failures. Its resource monitor initially assumed cgroup v2; it produced no resource samples. The harness was fixed to support this host's cgroup v1 **before** the reported 15-user run.
- Main measured window began `2026-09-30T21:00:01Z`: 90 seconds replaying legacy polling, 90 seconds using adaptive snapshots, then 180 seconds mixing adaptive snapshots, ordinary editor requests, and AI work. Recorded elapsed time is 361.27 seconds including approximately one second of cleanup.
- Each client read file/symbols/validation/deterministic style every 15–18 seconds and seeded a runtime variable every 30 seconds. AI phase submitted one screen and one field job per account, plus one deliberate duplicate submission per operation expecting 429; job polling used three-second intervals.
- Legacy traffic replay issued question then variables about once per second per account, sequentially; the original browser issued them concurrently. Both phases used the **optimized backend and the same reduced worker configuration**. This comparison measures traffic-pattern effects, not an original-versus-new backend benchmark. Cache warmup and phase order also affect latency comparisons.
- One Chromium browser probe ran during the load, creating an additional temporary debugger for a fixture account. A transitive include was edited once during the load to verify immediate cache invalidation. These probe requests are not included in the harness's 5,442-request count.
- Container resources were sampled every five seconds, 71 samples total. Working set subtracts inactive file pages from cgroup memory, matching the Docker working-set convention. CPU percentages are aggregate process/container usage where 100% is one CPU core. Abort threshold: working set above 7.5 GiB or a new OOM kill.

## Measurements

The legacy phase made **2,626 runtime GETs / 90 seconds = 29.18 requests/second**. The adaptive phase made **271 snapshot GETs / 90 seconds = 3.01 requests/second**, about **89.7% fewer observation requests**. Periodic variable edits kept this fixture changing, so the run did not reach the theoretical steady-idle rate of about 1.5 requests/second for fifteen debuggers at a ten-second interval. Runtime variable POSTs are excluded from those rates.

| Phase | Mean CPU, % of one core | Peak working set, GiB | Peak total cgroup memory, GiB |
| --- | ---: | ---: | ---: |
| Legacy polling replay | 46.3 | 3.624 | 3.694 |
| Adaptive polling | 22.8 | 3.646 | 3.719 |
| Adaptive editor + AI | 24.7 | 3.782 | 3.856 |

Container swap already existed before the test: 347.101 MiB initially and 347.055 MiB at the last sample, with a peak around 347.2 MiB. There were zero new OOM kills. This is not evidence that the host had never experienced memory pressure.

| Endpoint during mixed AI phase | Requests | p50, ms | p95, ms | Maximum, ms |
| --- | ---: | ---: | ---: | ---: |
| File read | 162 | 9.2 | 36.4 | 490.7 |
| Symbol discovery | 162 | 9.9 | 43.3 | 683.5 |
| Saved-file validation | 162 | 11.8 | 24.5 | 199.8 |
| Deterministic style check | 162 | 121.1 | 185.3 | 870.7 |
| Runtime snapshot | 532 | 26.7 | 106.3 | 793.0 |
| AI job status | 472 | 9.0 | 57.9 | 644.7 |
| Screen submission, including deliberate 429s | 30 | 8.2 | 12.4 | 67.8 |
| Field submission, including deliberate 429s | 30 | 7.4 | 14.1 | 37.7 |

All 30 accepted AI jobs succeeded: 15 screen drafts and 15 field drafts. All 30 deliberate duplicate submissions returned 429. Job completion including queue wait and polling detection: median **57.24 seconds**, p95 **63.59 seconds**, maximum **63.60 seconds**. The provider saw at most two concurrent calls; because the general pool itself had two workers, this live run alone does not prove the Redis cap works with a larger pool (unit tests exercise that admission path). AI-enabled style was covered by unit tests, not this live load.

Browser checks passed: combined snapshot traffic while visible; zero requests during twelve seconds after a simulated hidden-page visibility event; immediate refresh after a foreground event; zero requests during twelve seconds after leaving Debug; no JavaScript page errors. Visibility was simulated by overriding `document.hidden` and dispatching `visibilitychange`, rather than switching a physical browser tab.

The live include check saved a renamed field in `leaf.yml`, then reread symbols from `main.yml`: the old symbol disappeared and the new symbol appeared immediately despite the primed cache.

## Final validation finding

The first final full-suite run had one failure: the new template-cache test passed alone but missed a rapidly added file in the full run. Filesystem directory metadata can remain identical across rapid additions. Directory dependencies now hash sorted entry names with length prefixes in addition to metadata, covering template additions and newly shadowing includes. A deterministic regression freezes directory metadata while adding a file and proves invalidation. The final fixed module was also installed locally and services restarted; the six-minute load was not repeated after this small change.

## Validation and artifacts

- Final full unit run: **1,216 passed, 2 skipped, 1,003 subtests passed**, 9 dependency warnings, 52.69 seconds. Earlier focused and full runs are described above, including the fixed directory-invalidation failure.
- `npm run check`: passed Prettier, ESLint, and TypeScript checks.
- `mypy . --exclude '^build/' --explicit-package-bases`: passed, 111 source files including the two new scripts.
- Initial Black 26.5 checks on changed Python files and `git diff --check`: passed. GitHub uses Black 26.3, which formatted three already-changed files differently (`api_editor.py`, `test_editor_function_catalog.py`, and the stress harness). The final formatting commit aligns with CI; all three Python ASTs were verified identical before/after. **Full-repository Black 26.3 check passed: 111 files unchanged.**
- `pre-commit run --all-files` was attempted. Mypy, JavaScript, pytest, and subsequently the YAML checker passed. Black reformatted three unrelated baseline files (`editor_agent.py`, `interview_generator.py`, `test_document_bundles.py`); those unrelated edits were reverted. This local Black 26.5 pre-commit attempt was not clean; the final full-repository check with CI's Black 26.3 version passed.
- The neighboring upstream checkout lacked the tags needed by the optional Docassemble source-contract test. Full tests used `DOCASSEMBLE_SOURCE_CHECKOUT=/tmp/alweaver-no-upstream-checkout` to skip that optional upstream checkout check. No upstream source verification is claimed. Dependency deprecation warnings remain.

Public artifacts in [classroom-2026-09-30](classroom-2026-09-30/): aggregate results, all 71 resource samples, environment metadata, browser checks, include check, and cleanup check. The aggregate groups endpoints without HTTP method: runtime `/variables` rows can include both GET observations and POST seeds; the rate calculation above uses the raw method-separated samples. Raw per-request timings remain locally in `/tmp/alweaver-classroom-stress/request-samples.json`; test logs remain under `/tmp/alweaver-classroom-*`. These temporary paths are not durable deliverables. Committed artifacts contain no passwords, cookies, API keys, configuration files, interview source, or prompts.

## Reproduction

The checked-in harness is `scripts/editor_classroom_stress.py`; the loopback model fixture is `scripts/editor_stress_model.py`. Use a disposable localhost Docassemble installation with the tested branch installed in **both** web and Celery processes. The harness creates developer users and owned projects through native APIs; account creation does not invoke the invite/email route.

1. Privately back up the exact server configuration bytes. Temporarily merge `celery modules: [docassemble.ALWeaver.api_weaver_worker]` with existing modules and set `celery processes: 3` to reproduce this two-general-worker run. For a different RAM budget, size the actual general pool deliberately.
2. Copy the fixture into the container and launch it with the server Python. It listens only on container loopback port 18089. Temporarily set `open ai: {key: local-stress-fixture, base url: 'http://127.0.0.1:18089/v1'}`. Restart web and Celery services. Confirm no real provider credentials or external endpoint will be used.
3. Create a mode-0600 local credentials JSON with `email`, `password`, and `api_key` for a local administrator. Never commit it. Supply it with `--credentials`; the default is `~/.docassemble-local-admin.json`.
4. Run `.venv/bin/python scripts/editor_classroom_stress.py --base-url http://localhost --clients 15 --seconds 360 --container docassemble --output /tmp/alweaver-classroom-stress`. Dependencies are `requests` and `beautifulsoup4`; Docker access is needed for monitoring. The script permits only localhost destinations, 1–15 clients, and 30–600 seconds. Use at least 360 seconds for this 30-job, eight-second model fixture; shorter runs can end before queued jobs finish.
5. Review `results.json`, exit status, and resources. The harness removes its users/projects/runtime sessions in `finally`; if account cleanup fails it retains only the failed accounts' mode-0600 `cleanup-private.json` for manual recovery. This private file contains cookies and must not be shared. Abrupt termination or machine failure can require cleanup.
6. After outstanding jobs settle, stop the fixture, restore the exact original configuration bytes, restart services, and verify health and fixture-account removal. **The harness manages its accounts, not the server configuration or model process**; those are operator responsibilities.

Unit/static commands used:

```sh
DOCASSEMBLE_SOURCE_CHECKOUT=/tmp/alweaver-no-upstream-checkout scripts/run_unit_tests.sh -q
.venv/bin/mypy . --exclude '^build/' --explicit-package-bases
npm run check
```

## Final localhost state and remaining work

All stress accounts were independently confirmed absent through `/api/user_list`, including inactive accounts. Runtime sessions and projects were deleted by cleanup. The model fixture was stopped with zero active calls. Original configuration bytes were restored and verified against the private backup; uWSGI, Celery, and celerysingle are running. Temporary cookie material was removed. The optimization code remains installed locally, but the original configuration does not register the new AI worker module; apply the documented Celery configuration before using queued AI drafts there.

Next capacity validation should impose the target host/container limit and use representative large interviews, concurrent DOCX/PDF conversion and generation, uploads, assistant turns, and real provider latency. Existing generation jobs still share CPU/RAM and Celery capacity, the legacy Weaver API can still run synchronously, and full variable snapshots still cost work proportional to session size. This run did not exercise server-wide restarts, every background workflow, or hours of cache/process growth. The measured improvement and bounded admission justify a classroom trial with deliberate worker sizing; they do not justify increasing worker count to match developer count.
