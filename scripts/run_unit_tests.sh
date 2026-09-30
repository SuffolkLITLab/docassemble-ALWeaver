#!/usr/bin/env bash
set -euo pipefail

# Prefer a virtual environment installed for this checkout. A globally active
# Python may have pytest but lack Docassemble's test dependencies.
if [[ -x .venv/bin/python ]]; then
  test_python=".venv/bin/python"
elif [[ -x venv/bin/python ]]; then
  test_python="venv/bin/python"
else
  if command -v python >/dev/null 2>&1; then
    test_python="python"
  elif command -v python3 >/dev/null 2>&1; then
    test_python="python3"
  else
    printf 'Error: neither python nor python3 is available on PATH, and no checkout virtual environment was found.\n' >&2
    exit 127
  fi
fi

ISUNITTEST=true "$test_python" -m pytest "$@"
