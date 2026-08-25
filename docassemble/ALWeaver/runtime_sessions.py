"""Server-owned records for Weaver target interview sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

from .docassemble_compat import TargetSession

RUNTIME_SESSION_KEY_PREFIX = "da:alweaver:editor:runtime-session:"
RUNTIME_SESSION_EXPIRE_SECONDS = 8 * 60 * 60


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
        history=[{"event": "session_created", "at": timestamp.isoformat()}],
    )


def _key(weaver_session_id: str) -> str:
    return RUNTIME_SESSION_KEY_PREFIX + weaver_session_id


def store_runtime_record(redis_client: Any, record: WeaverTargetSession) -> None:
    payload = asdict(record)
    payload["created_at"] = record.created_at.isoformat()
    payload["last_accessed_at"] = record.last_accessed_at.isoformat()
    redis_client.set(
        _key(record.weaver_session_id),
        json.dumps(payload, sort_keys=True),
        ex=RUNTIME_SESSION_EXPIRE_SECONDS,
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
    value["created_at"] = datetime.fromisoformat(value["created_at"])
    value["last_accessed_at"] = datetime.fromisoformat(value["last_accessed_at"])
    record = WeaverTargetSession(**value)
    record.last_accessed_at = utc_now()
    store_runtime_record(redis_client, record)
    return record


def delete_runtime_record(
    redis_client: Any, weaver_session_id: str, owner_user_id: int
) -> bool:
    record = load_runtime_record(redis_client, weaver_session_id, owner_user_id)
    if record is None:
        return False
    redis_client.delete(_key(weaver_session_id))
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
    store_runtime_record(redis_client, record)
