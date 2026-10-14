"""Add AI help to a generated interview's long-answer fields.

Used by "I'm feeling lucky" when the author allows AI-powered questions. One
model call picks the fields where AI help makes answering easier, and what
kind; everything the model says is checked against the interview before
anything is written, and each addition goes through `editor_ai_assist`, so
the result is the same source an author would get from the field's dialog.

The reviewed answer keeps the field's variable, because the generated
documents already use it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .editor_ai_assist import (
    _question_variables,
    add_ai_help_keeping_variable,
    describe_ai_assists,
)

# Kinds of help a generated interview may get without the author choosing.
SUGGESTED_TASKS = ("goal", "rewrite")
MAX_SUGGESTIONS = 3
LONG_ANSWER_DATATYPES = ("area", "areaC")

SUGGESTION_PROMPT = """\
You help build guided court-form interviews for people without a lawyer.
Below are the long-answer fields of one interview, as JSON. Pick at most {limit}
where AI help would make it noticeably easier to give a complete, clear answer,
usually a story of what happened or the reasons for a request. Skip fields that
ask for a short fact, an address or a list. Pick none if none fit.

For each pick, choose a task:
- "goal": AI asks up to 3 follow-up questions until the answer covers what the
  form needs, then writes one answer the person reviews. Give a `rubric`: what
  a complete answer includes, in one or two plain sentences.
- "rewrite": AI organizes the person's own words without adding facts.

Also give `review_question`: a short, plain title for the screen where the
person checks the result, such as "Review your description". Leave legal
words out.

Return JSON: {{"suggestions": [{{"variable": "...", "task": "goal" or
"rewrite", "rubric": "...", "review_question": "..."}}]}}
"""


def long_answer_fields(yaml_text: str) -> List[Dict[str, str]]:
    """Each long-answer field of each question, without AI help yet."""
    from .editor_utils import parse_interview_yaml

    model = parse_interview_yaml(yaml_text)
    helped = {
        str(assist["settings"].get("source") or "")
        for assist in describe_ai_assists(model)
    }
    found: List[Dict[str, str]] = []
    for block in model["blocks"]:
        data = block.get("data") or {}
        if block.get("type") != "question" or "generic object" in data:
            continue
        fields = data.get("fields")
        fields = [fields] if isinstance(fields, dict) else fields
        variables = _question_variables(block)
        for item in fields if isinstance(fields, list) else []:
            if not isinstance(item, dict):
                continue
            # Weaver writes a long answer as `input type: area`; authors
            # often write `datatype: area`.
            if not any(
                str(item.get(key) or "") in LONG_ANSWER_DATATYPES
                for key in ("datatype", "input type")
            ):
                continue
            variable = _variable_of(item, variables)
            if not variable or variable in helped or variable.endswith("]"):
                continue
            label = item.get("label")
            if label is None:
                label = next(
                    (key for key, value in item.items() if value == variable), ""
                )
            found.append(
                {
                    "question_block_id": str(block.get("id") or ""),
                    "question": str(data.get("question") or "").strip(),
                    "label": "" if label == "no label" else str(label),
                    "variable": variable,
                }
            )
    return found


def _variable_of(item: Dict[str, Any], variables: Sequence[str]) -> Optional[str]:
    for value in [item.get("field"), item.get("no label"), *item.values()]:
        if isinstance(value, str) and value in variables:
            return value
    return None


def validated_suggestions(
    response: Any, candidates: Sequence[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """Keep only well-formed picks of real candidate fields, at most a few."""
    by_variable = {c["variable"]: c for c in candidates}
    picks = response.get("suggestions") if isinstance(response, dict) else None
    out: List[Dict[str, Any]] = []
    for pick in picks if isinstance(picks, list) else []:
        if not isinstance(pick, dict):
            continue
        candidate = by_variable.get(str(pick.get("variable") or ""))
        task = str(pick.get("task") or "")
        if candidate is None or task not in SUGGESTED_TASKS:
            continue
        if any(chosen["candidate"] is candidate for chosen in out):
            continue
        rubric = " ".join(str(pick.get("rubric") or "").split())[:500]
        if task == "goal" and not rubric:
            task = "rewrite"
        review_question = " ".join(str(pick.get("review_question") or "").split())
        out.append(
            {
                "candidate": candidate,
                "task": task,
                "rubric": rubric,
                "review_question": review_question[:120] or "Review your answer",
            }
        )
        if len(out) == MAX_SUGGESTIONS:
            break
    return out


def add_suggested_ai_questions(
    yaml_text: str, ask_model: Optional[Callable[[str, str], Any]] = None
) -> Tuple[str, List[str]]:
    """Add AI help where the model suggests it. Returns the YAML and notes.

    Never fails the generation: a model error, an unusable answer, or a
    field that can't be changed safely just means fewer additions.
    """
    import json

    candidates = long_answer_fields(yaml_text)
    if not candidates:
        return yaml_text, []
    ask = ask_model or _ask_model
    try:
        response = ask(
            SUGGESTION_PROMPT.format(limit=MAX_SUGGESTIONS),
            json.dumps(
                [
                    {k: c[k] for k in ("variable", "question", "label")}
                    for c in candidates
                ],
                ensure_ascii=False,
            ),
        )
    except Exception as exc:  # The interview is complete without AI help.
        return yaml_text, [
            f"AI-powered questions were skipped: {exc.__class__.__name__}"
        ]
    notes: List[str] = []
    for suggestion in validated_suggestions(response, candidates):
        candidate = suggestion["candidate"]
        config: Dict[str, Any] = {
            "task": suggestion["task"],
            "source": candidate["variable"],
            "review_question": suggestion["review_question"],
        }
        if suggestion["task"] == "goal":
            config.update(
                rubric=suggestion["rubric"],
                initial_question=candidate["question"] or candidate["label"],
                question_limit=3,
            )
        try:
            yaml_text, _summary = add_ai_help_keeping_variable(
                yaml_text, config, question_block_id=candidate["question_block_id"]
            )
        except ValueError as exc:
            notes.append(f"No AI help for {candidate['variable']}: {exc}")
            continue
        notes.append(
            f"Added AI help ({suggestion['task']}) to {candidate['variable']}."
        )
    return yaml_text, notes


def _ask_model(system_message: str, user_message: str) -> Any:
    from .interview_generator import _configured_llm_model, _load_llms_module

    llms = _load_llms_module()
    if llms is None:
        raise RuntimeError("ALToolbox is not available")
    return llms.chat_completion(
        system_message=system_message,
        user_message=user_message,
        json_mode=True,
        model=_configured_llm_model(),
    )
