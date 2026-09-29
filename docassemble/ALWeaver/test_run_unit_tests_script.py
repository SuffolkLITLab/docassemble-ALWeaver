# do not pre-load
"""Coverage for interpreter selection in scripts/run_unit_tests.sh."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_unit_tests.sh"


def _stub_interpreter(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' '{path.name if path.parent.name == 'path' else path.parent.parent.name}' \"$ISUNITTEST\" \"$@\" > \"$CAPTURE\"\n"
    )
    path.chmod(0o755)


def _run_script(
    tmp_path: Path, path_dir: Path, capture: Path
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update({"PATH": str(path_dir), "CAPTURE": str(capture)})
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), "tests with spaces", "--maxfail=1"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("preferred", "also_available", "expected"),
    [
        (".venv/bin/python", "venv/bin/python", ".venv/bin/python"),
        ("venv/bin/python", "python", "venv/bin/python"),
    ],
)
def test_virtual_environment_interpreters_keep_priority(
    tmp_path: Path, preferred: str, also_available: str, expected: str
) -> None:
    path_dir = tmp_path / "path"
    _stub_interpreter(tmp_path / preferred)
    if "/" in also_available:
        _stub_interpreter(tmp_path / also_available)
    else:
        _stub_interpreter(path_dir / also_available)
    capture = tmp_path / "capture"

    result = _run_script(tmp_path, path_dir, capture)

    assert result.returncode == 0, result.stderr
    assert capture.read_text().splitlines() == [
        expected.split("/")[0],
        "true",
        "-m",
        "pytest",
        "tests with spaces",
        "--maxfail=1",
    ]


@pytest.mark.parametrize("available", ["python", "python3"])
def test_system_python_fallbacks(tmp_path: Path, available: str) -> None:
    path_dir = tmp_path / "path"
    _stub_interpreter(path_dir / available)
    capture = tmp_path / "capture"

    result = _run_script(tmp_path, path_dir, capture)

    assert result.returncode == 0, result.stderr
    assert capture.read_text().splitlines() == [
        available,
        "true",
        "-m",
        "pytest",
        "tests with spaces",
        "--maxfail=1",
    ]


def test_missing_python_interpreters_has_clear_error(tmp_path: Path) -> None:
    path_dir = tmp_path / "empty-path"
    path_dir.mkdir()
    result = _run_script(tmp_path, path_dir, tmp_path / "capture")

    assert result.returncode == 127
    assert "neither python nor python3 is available on PATH" in result.stderr
    assert not (tmp_path / "capture").exists()
