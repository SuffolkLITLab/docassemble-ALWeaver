"""Session, candidate and event records for the Weaver editing agent.

Nothing in this module talks to Flask, Docassemble or a model provider. It owns
the shapes that the orchestration loop, the tool registry and the REST layer all
agree on, plus the owner-scoped Redis persistence that keeps an agent
conversation alive between turns.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import time
from typing import Any, Callable, Dict, List, Optional

from .editor_agent_validation import CandidateValidation
from .source_document import source_revision, unified_source_diff

AGENT_SESSION_KEY_PREFIX = "da:alweaver:editor:agent-session:"
AGENT_SESSION_EXPIRE_SECONDS = 2 * 60 * 60

# Payload and transcript limits. These bound both what a browser may submit and
# how much conversation is replayed to the model on later turns.
MAX_CHAT_MESSAGE_CHARS = 8000
MAX_CANDIDATE_SOURCE_BYTES = 1024 * 1024
MAX_TRANSCRIPT_MESSAGES = 40
MAX_COMMAND_HISTORY = 60
MAX_DIFF_CHARS = 120 * 1024

# This assistant is for small, discrete edits. A long conversation accumulates
# context that makes each turn slower and vaguer, and a candidate built over
# many turns is harder to review in one diff. The limit is a nudge toward
# applying what you have and starting a fresh chat for the next task.
MAX_TURNS_PER_SESSION = 10
TURNS_REMAINING_WARNING = 3

TOOL_STATUS_SUCCESS = "success"
TOOL_STATUS_REJECTED = "rejected"
TOOL_STATUS_ERROR = "error"


def utc_timestamp() -> float:
    return time.time()


@dataclass
class AgentMessage:
    """One entry in the developer-visible transcript."""

    role: str  # "user" | "assistant" | "system"
    content: str
    at: float = field(default_factory=utc_timestamp)

    def public_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "content": self.content, "at": self.at}


@dataclass
class AgentToolCall:
    """A tool invocation the model asked for, before any dispatch happens."""

    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    expected_candidate_revision: Optional[str] = None


@dataclass
class AgentToolResult:
    """The deterministic outcome of one tool invocation."""

    tool: str
    status: str
    label: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    reason: Optional[str] = None
    message: Optional[str] = None
    before_revision: Optional[str] = None
    after_revision: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.status == TOOL_STATUS_SUCCESS

    def model_dict(self) -> Dict[str, Any]:
        """What the model sees. Terse, structured and never raw prose."""
        payload: Dict[str, Any] = {"tool_status": self.status, "tool": self.tool}
        if self.reason:
            payload["reason"] = self.reason
        if self.message:
            payload["message"] = self.message
        if self.diagnostics:
            payload["diagnostics"] = self.diagnostics
        if self.data:
            payload["result"] = self.data
        if self.after_revision:
            payload["candidate_revision"] = self.after_revision
        return payload

    def event_dict(self) -> Dict[str, Any]:
        """What the browser renders as a progress line."""
        return {
            "type": "tool_result",
            "tool": self.tool,
            "label": self.label or self.tool.replace("_", " "),
            "status": self.status,
            "reason": self.reason,
            "message": self.message,
            "diagnostics": self.diagnostics,
        }


@dataclass
class AgentCandidate:
    """The in-memory working document for one agent session.

    The candidate only ever holds source that passed the whole-candidate
    validator, so its validity is monotonic across a conversation.
    """

    base_source: str
    base_revision: str
    raw_source: str
    revision: str
    applied_commands: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_source(cls, raw_source: str) -> "AgentCandidate":
        revision = source_revision(raw_source)
        return cls(
            base_source=raw_source,
            base_revision=revision,
            raw_source=raw_source,
            revision=revision,
        )

    @property
    def changed(self) -> bool:
        return self.raw_source != self.base_source

    def accept(
        self,
        proposed_source: str,
        *,
        tool: str,
        arguments: Dict[str, Any],
        validation: CandidateValidation,
    ) -> Dict[str, Any]:
        """Commit a validated edit and record it in the command history."""
        before_revision = self.revision
        self.raw_source = proposed_source
        self.revision = validation.revision or source_revision(proposed_source)
        self.diagnostics = list(validation.diagnostics)
        record = {
            "sequence": len(self.applied_commands) + 1,
            "tool": tool,
            "arguments": arguments,
            "before_revision": before_revision,
            "after_revision": self.revision,
            "status": "accepted",
            "validation_summary": validation.public_summary(),
        }
        self.applied_commands.append(record)
        return record

    def diff(self, filename: str) -> str:
        return unified_source_diff(self.base_source, self.raw_source, filename)

    def public_dict(self) -> Dict[str, Any]:
        return {
            "candidate_revision": self.revision,
            "base_revision": self.base_revision,
            "changed": self.changed,
            "applied_commands": list(self.applied_commands),
            "diagnostics": list(self.diagnostics),
        }


@dataclass
class AgentTurn:
    """One developer request and everything the loop did in response."""

    turn_id: str
    user_message: str
    status: str = "running"
    summary: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    stop_reason: Optional[str] = None
    started_at: float = field(default_factory=utc_timestamp)
    finished_at: Optional[float] = None
    # Called as each event happens so a caller can publish live progress; a
    # turn is one blocking request, so without this the developer sees nothing
    # until it finishes.
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None

    def add_event(self, event: Dict[str, Any]) -> None:
        self.events.append(event)
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:
                # Progress reporting must never break the turn producing it.
                pass

    def public_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "status": self.status,
            "summary": self.summary,
            "events": list(self.events),
            "diagnostics": list(self.diagnostics),
            "stop_reason": self.stop_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class WeaverAgentSession:
    """An owner-scoped conversation bound to exactly one Playground file.

    ``project`` and ``filename`` are set once at creation from the authenticated
    request. No tool argument may ever change them.
    """

    session_id: str
    owner_user_id: int
    project: str
    filename: str
    base_saved_revision: str
    original_working_source: str
    candidate_source: str
    candidate_revision: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    command_history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=utc_timestamp)
    last_accessed_at: float = field(default_factory=utc_timestamp)
    cancelled: bool = False
    turn_count: int = 0
    # Set when mechanical id problems were repaired before the session began.
    # The diff still runs against the developer's own source so the repairs
    # stay visible, but Reset must return here rather than to source the
    # validator would reject.
    repaired_working_source: Optional[str] = None
    repairs: List[Dict[str, Any]] = field(default_factory=list)

    def candidate(self) -> AgentCandidate:
        candidate = AgentCandidate(
            base_source=self.original_working_source,
            base_revision=source_revision(self.original_working_source),
            raw_source=self.candidate_source,
            revision=self.candidate_revision,
            applied_commands=list(self.command_history),
        )
        return candidate

    def store_candidate(self, candidate: AgentCandidate) -> None:
        self.candidate_source = candidate.raw_source
        self.candidate_revision = candidate.revision
        self.command_history = candidate.applied_commands[-MAX_COMMAND_HISTORY:]

    def append_message(self, message: AgentMessage) -> None:
        self.messages = (self.messages + [message.public_dict()])[
            -MAX_TRANSCRIPT_MESSAGES:
        ]

    @property
    def turns_remaining(self) -> int:
        return max(0, MAX_TURNS_PER_SESSION - int(self.turn_count))

    @property
    def is_exhausted(self) -> bool:
        return self.turns_remaining <= 0

    def reset_candidate(self) -> None:
        """Return the candidate to the source the session started editing from."""
        baseline = self.repaired_working_source or self.original_working_source
        self.candidate_source = baseline
        self.candidate_revision = source_revision(baseline)
        self.command_history = []
        self.messages = []
        self.cancelled = False
        self.turn_count = 0

    def public_dict(self) -> Dict[str, Any]:
        """Session state safe to hand to the browser.

        Never includes Redis keys, model credentials or the owner's raw
        Docassemble identifiers.
        """
        return {
            "agent_session_id": self.session_id,
            "project": self.project,
            "filename": self.filename,
            "base_revision": self.base_saved_revision,
            "candidate_revision": self.candidate_revision,
            "has_candidate_changes": self.candidate_source
            != self.original_working_source,
            "repairs": list(self.repairs),
            "turn_count": int(self.turn_count),
            "turns_remaining": self.turns_remaining,
            "max_turns": MAX_TURNS_PER_SESSION,
            "messages": list(self.messages),
            "command_history": list(self.command_history),
            "created_at": self.created_at,
            "last_accessed_at": self.last_accessed_at,
        }


# Live progress lives under its own key rather than inside the session record.
# A turn is one blocking request that writes progress as it goes, while Stop
# and the polling reads touch the session concurrently; sharing one record
# would make those writers clobber each other.
AGENT_PROGRESS_KEY_PREFIX = "da:alweaver:editor:agent-progress:"
AGENT_PROGRESS_EXPIRE_SECONDS = 30 * 60
MAX_PROGRESS_EVENTS = 60
# A turn writes progress on every step. If nothing has been written for this
# long the worker running it is gone — a recycled process, say — and the record
# must not be believed to be alive forever.
PROGRESS_STALE_SECONDS = 120


def progress_is_live(progress: Optional[Dict[str, Any]]) -> bool:
    if not progress or not progress.get("running"):
        return False
    updated_at = progress.get("updated_at")
    if not isinstance(updated_at, (int, float)):
        return False
    return (utc_timestamp() - float(updated_at)) < PROGRESS_STALE_SECONDS


def _key(session_id: str) -> str:
    return AGENT_SESSION_KEY_PREFIX + session_id


def _progress_key(session_id: str) -> str:
    return AGENT_PROGRESS_KEY_PREFIX + session_id


def store_progress(
    redis_client: Any,
    session_id: str,
    owner_user_id: int,
    *,
    running: bool,
    events: List[Dict[str, Any]],
    started_at: float,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
) -> None:
    """Publish what the running turn has done so far, and its outcome.

    The finished turn's result lives here rather than in an HTTP response: a
    turn outlives any request the browser can hold open, so the browser reads
    the outcome by polling once ``running`` goes false.
    """
    payload = {
        "owner_user_id": int(owner_user_id),
        "running": bool(running),
        "events": list(events)[-MAX_PROGRESS_EVENTS:],
        "started_at": started_at,
        "updated_at": utc_timestamp(),
        "result": result,
        "error": error,
    }
    redis_client.set(
        _progress_key(session_id),
        json.dumps(payload, default=str),
        ex=AGENT_PROGRESS_EXPIRE_SECONDS,
    )


def load_progress(
    redis_client: Any, session_id: str, owner_user_id: int
) -> Optional[Dict[str, Any]]:
    raw = redis_client.get(_progress_key(session_id))
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("owner_user_id", -1)) != int(owner_user_id):
        return None
    payload.pop("owner_user_id", None)
    return payload


def clear_progress(redis_client: Any, session_id: str) -> None:
    redis_client.delete(_progress_key(session_id))


def store_agent_session(redis_client: Any, session: WeaverAgentSession) -> None:
    session.last_accessed_at = utc_timestamp()
    redis_client.set(
        _key(session.session_id),
        json.dumps(asdict(session), sort_keys=True, default=str),
        ex=AGENT_SESSION_EXPIRE_SECONDS,
    )


def load_agent_session(
    redis_client: Any, session_id: str, owner_user_id: int
) -> Optional[WeaverAgentSession]:
    """Load a session only for the developer who created it."""
    raw = redis_client.get(_key(session_id))
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    if int(value.get("owner_user_id", -1)) != int(owner_user_id):
        return None
    session = WeaverAgentSession(**value)
    session.last_accessed_at = utc_timestamp()
    return session


def delete_agent_session(
    redis_client: Any, session_id: str, owner_user_id: int
) -> bool:
    session = load_agent_session(redis_client, session_id, owner_user_id)
    if session is None:
        return False
    redis_client.delete(_key(session_id))
    return True


def truncate_diff(diff_text: str) -> Dict[str, Any]:
    """Cap an inline diff so one huge edit cannot flood the chat panel."""
    if len(diff_text) <= MAX_DIFF_CHARS:
        return {"diff": diff_text, "truncated": False}
    return {
        "diff": diff_text[:MAX_DIFF_CHARS],
        "truncated": True,
        "full_length": len(diff_text),
    }


def diff_stats(diff_text: str) -> Dict[str, int]:
    added = 0
    removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return {"added": added, "removed": removed}
