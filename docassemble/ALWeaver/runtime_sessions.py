"""Server-owned records for Weaver target interview sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import logging
import math
from typing import Any, Dict, List, Optional, Iterator

from .docassemble_compat import (
    TargetSession,
    delete_target_session,
    get_target_session_revision,
    get_worker_app,
)

RUNTIME_SESSION_KEY_PREFIX = "da:alweaver:editor:runtime-session:"
RUNTIME_SESSION_EXPIRE_SECONDS = 30 * 60
RUNTIME_SESSION_DUE_KEY = RUNTIME_SESSION_KEY_PREFIX + "deadlines"
RUNTIME_SESSION_OWNER_PREFIX = RUNTIME_SESSION_KEY_PREFIX + "owner:"
logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class WeaverTargetSession:
    weaver_session_id: str
    owner_user_id: int
    project: str
    filename: str
    yaml_filename: str
    docassemble_session_id: str
    encrypted: bool
    encrypted_secret: Optional[str]
    created_at: datetime
    last_accessed_at: datetime
    purpose: str
    history: List[Dict[str, Any]] = field(default_factory=list)
    seeded_variables: List[str] = field(default_factory=list)
    last_progress_at: Optional[datetime] = None
    progress_revision: Optional[int] = None

    def target(self, secret: Optional[str] = None) -> TargetSession:
        """Address the Docassemble session, decrypting it with ``secret``.

        The developer's own Docassemble key is deliberately not part of this
        record: it can decrypt every session they own, so callers supply it per
        request from the browser cookie that already carries it. ``encrypted_secret``
        holds a key only for a session Weaver had to encrypt with a generated
        one, which no browser can open.
        """
        secret = secret or self.encrypted_secret
        if self.encrypted and not secret:
            raise ValueError(
                "This target session is encrypted and no decryption key is available"
            )
        return TargetSession(
            yaml_filename=self.yaml_filename,
            session_id=self.docassemble_session_id,
            secret=secret,
        )

    def public_dict(self, target_url: str) -> Dict[str, Any]:
        return {
            "weaver_session_id": self.weaver_session_id,
            "project": self.project,
            "filename": self.filename,
            "yaml_filename": self.yaml_filename,
            "encrypted": self.encrypted,
            "created_at": self.created_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat(),
            "purpose": self.purpose,
            "expires_at": deadline(self).isoformat(),
            "idle_timeout_seconds": RUNTIME_SESSION_EXPIRE_SECONDS,
            "target_url": target_url,
            "history": list(self.history),
        }


def playground_yaml_filename(user_id: int, project: str, filename: str) -> str:
    project_suffix = "" if project == "default" else project
    return f"docassemble.playground{user_id}{project_suffix}:{filename}"


def create_runtime_record(
    *,
    weaver_session_id: str,
    owner_user_id: int,
    project: str,
    filename: str,
    yaml_filename: str,
    target: TargetSession,
    purpose: str = "test",
    persist_secret: bool = True,
) -> WeaverTargetSession:
    """Build the server-side record for one target session.

    Pass ``persist_secret=False`` when the target was encrypted with a key the
    caller can recover on every later request, so the record never stores it.
    """
    timestamp = utc_now()
    return WeaverTargetSession(
        weaver_session_id=weaver_session_id,
        owner_user_id=owner_user_id,
        project=project,
        filename=filename,
        yaml_filename=yaml_filename,
        docassemble_session_id=target.session_id,
        encrypted=target.secret is not None,
        encrypted_secret=target.secret if persist_secret else None,
        created_at=timestamp,
        last_accessed_at=timestamp,
        purpose=purpose,
        last_progress_at=timestamp,
        history=[{"event": "session_created", "at": timestamp.isoformat()}],
    )


def _key(weaver_session_id: str) -> str:
    return RUNTIME_SESSION_KEY_PREFIX + weaver_session_id


def store_runtime_record(redis_client: Any, record: WeaverTargetSession) -> None:
    payload = asdict(record)
    payload["created_at"] = record.created_at.isoformat()
    payload["last_accessed_at"] = record.last_accessed_at.isoformat()
    payload["last_progress_at"] = (
        record.last_progress_at or record.last_accessed_at
    ).isoformat()
    # Do not expire the only pointer to the database interview. Remove it only
    # after Docassemble cleanup succeeds; failed deletions can then be retried.
    redis_client.set(
        _key(record.weaver_session_id),
        json.dumps(payload, sort_keys=True),
    )
    redis_client.zadd(
        RUNTIME_SESSION_DUE_KEY,
        {record.weaver_session_id: deadline(record).timestamp()},
    )


def load_runtime_record(
    redis_client: Any, weaver_session_id: str, owner_user_id: int
) -> Optional[WeaverTargetSession]:
    raw = redis_client.get(_key(weaver_session_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    value = json.loads(raw)
    if int(value.get("owner_user_id", -1)) != int(owner_user_id):
        return None
    for name in ("created_at", "last_accessed_at", "last_progress_at"):
        if value.get(name):
            value[name] = datetime.fromisoformat(value[name])
    record = WeaverTargetSession(**value)
    return record


def delete_runtime_record(
    redis_client: Any, weaver_session_id: str, owner_user_id: int
) -> bool:
    record = load_runtime_record(redis_client, weaver_session_id, owner_user_id)
    if record is None:
        return False
    redis_client.delete(_key(weaver_session_id))
    redis_client.zrem(RUNTIME_SESSION_DUE_KEY, weaver_session_id)
    redis_client.delete(_key(weaver_session_id) + ":cleanup-queued")
    owner_key = RUNTIME_SESSION_OWNER_PREFIX + str(owner_user_id)
    active = redis_client.get(owner_key)
    if isinstance(active, bytes):
        active = active.decode("utf-8")
    if active == weaver_session_id:
        redis_client.delete(owner_key)
    return True


def append_runtime_event(
    redis_client: Any,
    record: WeaverTargetSession,
    event: str,
    **details: Any,
) -> None:
    timestamp = utc_now()
    item = {"event": event, "at": timestamp.isoformat()}
    item.update(details)
    record.history = (record.history + [item])[-100:]
    record.last_accessed_at = timestamp
    if event in {"scenario_applied", "back_invoked"}:
        record.last_progress_at = timestamp
    store_runtime_record(redis_client, record)


def deadline(record: WeaverTargetSession) -> datetime:
    return (record.last_progress_at or record.last_accessed_at) + timedelta(
        seconds=RUNTIME_SESSION_EXPIRE_SECONDS
    )


@contextmanager
def runtime_session_lock(redis_client: Any, identity: str) -> Iterator[None]:
    lock = redis_client.lock(_key(identity) + ":lock", timeout=120, blocking_timeout=10)
    if not lock.acquire(blocking=True):
        raise RuntimeError(
            "Another debug session operation is still running. Try again."
        )
    try:
        yield
    finally:
        lock.release()


def validate_runtime_record(record: WeaverTargetSession) -> None:
    if record.yaml_filename != playground_yaml_filename(
        record.owner_user_id, record.project, record.filename
    ) or record.purpose not in {"test", "scenario", "inspection"}:
        raise ValueError("Refusing to clean up an unrecognized debug interview")


def refresh_runtime_progress(redis_client: Any, record: WeaverTargetSession) -> bool:
    validate_runtime_record(record)
    revision = get_target_session_revision(
        TargetSession(record.yaml_filename, record.docassemble_session_id)
    )
    if revision is None:
        # Already deleted through My Interviews or normal Docassemble cleanup.
        delete_runtime_record(
            redis_client, record.weaver_session_id, record.owner_user_id
        )
        return False
    if record.progress_revision != revision[0]:
        changed_at = revision[1]
        if changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=timezone.utc)
        # Legacy records have no revision baseline. Honor their last known use.
        record.last_progress_at = max(
            record.last_progress_at or record.last_accessed_at, changed_at
        )
        record.progress_revision = revision[0]
        store_runtime_record(redis_client, record)
    return True


def close_runtime_session(redis_client: Any, record: WeaverTargetSession) -> None:
    validate_runtime_record(record)
    delete_target_session(
        TargetSession(record.yaml_filename, record.docassemble_session_id),
        record.owner_user_id,
    )
    delete_runtime_record(redis_client, record.weaver_session_id, record.owner_user_id)


def get_live_runtime_record(
    redis_client: Any, session_id: str, owner: int
) -> Optional[WeaverTargetSession]:
    with runtime_session_lock(redis_client, session_id):
        record = load_runtime_record(redis_client, session_id, owner)
        if record is None or not refresh_runtime_progress(redis_client, record):
            return None
        if deadline(record) <= utc_now():
            close_runtime_session(redis_client, record)
            return None
        return record


def owned_runtime_records(redis_client: Any, owner: int) -> List[WeaverTargetSession]:
    records = []
    # Also discovers records created by older Weaver versions, before indexes.
    for key in redis_client.scan_iter(
        match=RUNTIME_SESSION_KEY_PREFIX + "*", count=100
    ):
        name = key.decode("utf-8") if isinstance(key, bytes) else key
        suffix = name[len(RUNTIME_SESSION_KEY_PREFIX) :]
        if suffix == "deadlines" or suffix.startswith("owner:") or ":" in suffix:
            continue
        record = load_runtime_record(redis_client, suffix, owner)
        if record is not None:
            records.append(record)
    return sorted(records, key=lambda record: record.created_at, reverse=True)


def cleanup_owned_runtime_sessions(
    redis_client: Any, owner: int, keep_latest: bool = True
) -> Dict[str, Any]:
    records = owned_runtime_records(redis_client, owner)
    active = None
    deleted = 0
    for candidate in records:
        with runtime_session_lock(redis_client, candidate.weaver_session_id):
            record = load_runtime_record(
                redis_client, candidate.weaver_session_id, owner
            )
            if record is None:
                continue
            if not refresh_runtime_progress(redis_client, record):
                deleted += 1
            elif deadline(record) <= utc_now() or active is not None or not keep_latest:
                close_runtime_session(redis_client, record)
                deleted += 1
            else:
                active = record
    owner_key = RUNTIME_SESSION_OWNER_PREFIX + str(owner)
    if active:
        redis_client.set(owner_key, active.weaver_session_id)
    else:
        redis_client.delete(owner_key)
    return {"session": active, "deleted": deleted}


def cleanup_due_runtime_sessions(redis_client: Any, limit: int = 20) -> int:
    deleted = 0
    for session_id in redis_client.zrangebyscore(
        RUNTIME_SESSION_DUE_KEY, "-inf", utc_now().timestamp(), start=0, num=limit
    ):
        session_id = (
            session_id.decode("utf-8") if isinstance(session_id, bytes) else session_id
        )
        raw = redis_client.get(_key(session_id))
        if raw is None:
            redis_client.zrem(RUNTIME_SESSION_DUE_KEY, session_id)
            continue
        owner = int(json.loads(raw)["owner_user_id"])
        try:
            if get_live_runtime_record(redis_client, session_id, owner) is None:
                deleted += 1
        except Exception:
            logger.exception(
                "Unable to clean up debug session %s; retaining its cleanup record",
                session_id,
            )
    return deleted


def schedule_runtime_cleanup(redis_client: Any, record: WeaverTargetSession) -> None:
    """Queue one durable deadline check; do not multiply tasks on refresh."""
    from .worker_config import worker_configuration_is_ready

    if not worker_configuration_is_ready():
        return
    # Keep broker ETA reservations short. Periodic checks still close a session
    # at its actual deadline and never keep a worker occupied between checks.
    delay = min(300, max(1, math.ceil((deadline(record) - utc_now()).total_seconds())))
    queued_key = _key(record.weaver_session_id) + ":cleanup-queued"
    if not redis_client.set(queued_key, "1", nx=True, ex=delay + 300):
        return
    try:
        get_worker_app().send_task(
            "docassemble.ALWeaver.api_weaver_worker.weaver_cleanup_runtime_session_task",
            kwargs={
                "session_id": record.weaver_session_id,
                "owner_user_id": record.owner_user_id,
            },
            countdown=delay,
        )
    except Exception:
        redis_client.delete(queued_key)
        logger.exception(
            "Unable to schedule debug cleanup; normal editor use will retry"
        )


def migrate_runtime_records(redis_client: Any) -> None:
    """Index pre-upgrade records without choosing unrelated database sessions."""
    for key in redis_client.scan_iter(
        match=RUNTIME_SESSION_KEY_PREFIX + "*", count=100
    ):
        key = key.decode("utf-8") if isinstance(key, bytes) else key
        suffix = key[len(RUNTIME_SESSION_KEY_PREFIX) :]
        if ":" in suffix or suffix == "deadlines":
            continue
        raw = redis_client.get(key)
        if raw is None:
            continue
        owner = int(json.loads(raw)["owner_user_id"])
        with runtime_session_lock(redis_client, suffix):
            record = load_runtime_record(redis_client, suffix, owner)
            if record is not None:
                validate_runtime_record(record)
                store_runtime_record(redis_client, record)
                schedule_runtime_cleanup(redis_client, record)
