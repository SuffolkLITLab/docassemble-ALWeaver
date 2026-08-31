"""Create and re-sync ALKiln smoke tests for Weaver projects."""

import re
from typing import Any, Dict, Optional

DEFAULT_ALKILN_WORKFLOW = """name: ALKiln v5 tests

on:
  push:
  workflow_dispatch:
    inputs:
      tags:
        description: Optional ALKiln tag expression
        default: ''

jobs:
  interview-testing:
    runs-on: ubuntu-latest
    name: Run interview tests
    steps:
      - uses: actions/checkout@v4
      - name: Use ALKiln to run tests
        uses: SuffolkLITLab/ALKiln@v5
        with:
          SERVER_URL: ${{ secrets.SERVER_URL }}
          DOCASSEMBLE_DEVELOPER_API_KEY: ${{ secrets.DOCASSEMBLE_DEVELOPER_API_KEY }}
"""


def default_feature_filename(interview_filename: str) -> str:
    """Return a flat, Playground-safe feature filename."""
    stem = re.sub(r"\.(?:yml|yaml)$", "", str(interview_filename), flags=re.I)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_-") or "interview"
    return f"{stem}.feature"


def _dashboard_story_api() -> tuple[Any, Any, Any, Any]:
    try:
        from docassemble.ALDashboard.alkiln_story import (
            StoryOptions,
            detect_yaml_ending_screen,
            story_from_docassemble_yaml,
            sync_story_from_docassemble_yaml,
        )
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "This ALDashboard version does not support Weaver ALKiln test sync. "
            "Install the ALDashboard kiln-story-sync update."
        ) from exc
    return (
        StoryOptions,
        detect_yaml_ending_screen,
        story_from_docassemble_yaml,
        sync_story_from_docassemble_yaml,
    )


def create_kiln_feature(
    yaml_text: str,
    *,
    interview_filename: str,
    feature_description: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the default test that supplies values for every generated screen."""
    StoryOptions, detect_ending, story_from_yaml, _sync_story = _dashboard_story_api()
    title = feature_description or f"{interview_filename} runs to completion"
    options = StoryOptions(
        feature_description=title,
        scenario_description=title,
        yaml_file_name=interview_filename,
        question_id=detect_ending(yaml_text),
        include_screen_definitions=True,
    )
    return story_from_yaml(
        yaml_text,
        filename=interview_filename,
        source_path=None,
        options=options,
    )


def sync_kiln_feature(
    existing_feature_text: str,
    yaml_text: str,
    *,
    interview_filename: str,
) -> Dict[str, Any]:
    """Draft a synchronized feature and report changed screens/variables."""
    StoryOptions, detect_ending, _story_from_yaml, sync_story = _dashboard_story_api()
    title = f"{interview_filename} runs to completion"
    return sync_story(
        existing_feature_text,
        yaml_text,
        filename=interview_filename,
        source_path=None,
        options=StoryOptions(
            feature_description=title,
            scenario_description=title,
            yaml_file_name=interview_filename,
            question_id=detect_ending(yaml_text),
            include_screen_definitions=True,
        ),
    )
