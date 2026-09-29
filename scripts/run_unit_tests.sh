#!/usr/bin/env bash
set -euo pipefail

# Prefer a virtual environment installed for this checkout. A globally active
# Python may have pytest but lack Docassemble's test dependencies.
if [[ -x .venv/bin/python ]]; then
  test_python=".venv/bin/python"
elif [[ -x venv/bin/python ]]; then
  test_python="venv/bin/python"
else
  test_python="$(command -v python)"
fi

ISUNITTEST=true "$test_python" -m pytest "$@"
