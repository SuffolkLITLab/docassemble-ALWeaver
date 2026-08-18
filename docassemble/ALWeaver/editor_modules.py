# do not pre-load

"""Safe saving of Playground Python modules from the Weaver editor.

Docassemble does not load a Playground module from the place the Playground
saves it. Saved modules live in the ``playgroundmodules`` storage area, but an
interview importing ``docassemble.playground7Housing.util`` resolves that name
against ``site-packages/docassemble/playground7Housing/``. Copying between the
two happens in the server's ``copy_playground_modules()``, which runs *only at
startup* — in 1.9.x from ``server.py`` and in 1.10.x from
``webapp/develop/helpers.py``, called from ``startup.py`` in both.

That is why the stock Playground redirects to ``/restart`` after every module
save, and why a module saved without a restart has no effect whatsoever: the
bytes never reach the directory Python imports from.

This module implements a less disruptive version of the same contract:

* **New modules go live immediately.** A file that does not exist in the
  package directory yet cannot be in any worker's ``sys.modules``, so copying
  it across and invalidating the import caches is enough — no restart.
* **Changed, renamed, and deleted modules mark the project dirty.** Those need
  every worker process to drop its ``sys.modules`` entry, which only a restart
  does. The flag is recorded and the restart is deferred until the developer
  actually runs the interview.
* **Broken modules are refused at save time.** The stock Playground will
  happily save a module that does not compile and restart the server for it;
  the failure then surfaces far from the edit. A compile check costs nothing.

Nothing here imports Docassemble, so it is testable on its own; callers pass
in the Redis client, the package root, and the server start time.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

__all__ = [
    "MODULE_FILENAME_PATTERN",
    "ModuleSyntaxError",
    "RESTART_POLICIES",
    "check_module_syntax",
    "clear_modules_dirty",
    "mark_modules_dirty",
    "module_package_directory",
    "modules_dirty_key",
    "normalize_restart_policy",
    "publish_module_source",
    "read_modules_dirty",
    "restart_status_key",
    "validate_module_filename",
]


# ``copy_playground_modules`` only ever copies files matching this shape:
#
#     [f for f in os.listdir(mod_directory) if re.search(r'^[A-Za-z].*\.py$', f)]
#
# A module called ``_helpers.py`` or ``2col.py`` is therefore saved happily and
# then silently never loaded, in the stock Playground as much as here. We reject
# those names up front rather than let the developer find out at runtime. The
# stricter tail (identifier characters only) is ours: a name that is not a
# Python identifier cannot be written in a ``modules:`` block anyway.
MODULE_FILENAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*\.py$")

MODULES_DIRTY_KEY_PREFIX = "da:weaver:modules_dirty:"
MODULES_DIRTY_TTL_SECONDS = 30 * 24 * 60 * 60

# Shared with Docassemble's own /restart machinery, deliberately: the polling
# endpoint has to agree with whatever else on the server may have started a
# restart, and the server's own check_restart_status reads this same key shape.
RESTART_STATUS_KEY_PREFIX = "da:restart_status:"
RESTART_STATUS_TTL_SECONDS = 3600

RESTART_POLICIES = ("prompt", "auto", "never")
DEFAULT_RESTART_POLICY = "prompt"

# What a restart actually costs, quoted to the developer before they trigger
# one. reset.sh stops and starts celery, rabbitmq, and websockets, and touches
# the wsgi file; ten to thirty seconds is the normal range on a healthy server.
RESTART_DISRUPTION_SECONDS = (10, 30)


class ModuleSyntaxError(ValueError):
    """A module was saved with source that does not compile.

    Carries the position so the editor can put the cursor on the offending
    line instead of just showing a message.
    """

    def __init__(
        self,
        message: str,
        *,
        filename: str,
        line: Optional[int] = None,
        offset: Optional[int] = None,
        text: Optional[str] = None,
    ):
        super().__init__(message)
        self.filename = filename
        self.line = line
        self.offset = offset
        self.text = text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "module_syntax_error",
            "message": str(self),
            "filename": self.filename,
            "line": self.line,
            "offset": self.offset,
            "text": self.text,
        }


def validate_module_filename(filename: str) -> None:
    """Raise ``ValueError`` unless Docassemble will actually load this name."""
    name = str(filename or "").strip()
    if not name:
        raise ValueError("A module needs a filename")
    if not name.endswith(".py"):
        raise ValueError(f"{name} is not a Python module: the name must end in .py")
    if not MODULE_FILENAME_PATTERN.match(name):
        raise ValueError(
            f"{name} would be saved but never loaded. Docassemble only imports "
            "modules whose names start with a letter and contain only letters, "
            "numbers, and underscores — for example utility.py or "
            "custom_fields.py."
        )


def check_module_syntax(filename: str, content: str) -> None:
    """Compile the source, raising :class:`ModuleSyntaxError` if it will not.

    This catches syntax errors only. A module that compiles can still raise on
    import; nothing short of importing it would find that, and importing
    untrusted source in the request handler is exactly what we are avoiding.
    """
    try:
        compile(content, filename, "exec")
    except SyntaxError as exc:
        detail = exc.msg or "invalid syntax"
        where = f" on line {exc.lineno}" if exc.lineno else ""
        raise ModuleSyntaxError(
            f"{filename} has a Python syntax error{where}: {detail}",
            filename=filename,
            line=exc.lineno,
            offset=exc.offset,
            text=(exc.text or "").rstrip("\n") or None,
        ) from exc
    except ValueError as exc:
        # Source containing a null byte, and similar, raise ValueError here.
        raise ModuleSyntaxError(
            f"{filename} could not be compiled: {exc}",
            filename=filename,
        ) from exc


def module_package_name(user_id: int, project: str) -> str:
    """The importable package a project's modules live under."""
    suffix = "" if project == "default" else str(project)
    return f"docassemble.playground{int(user_id)}{suffix}"


def module_package_directory(
    package_root: Optional[str], user_id: int, project: str
) -> Optional[str]:
    """Where ``copy_playground_modules`` puts this project's modules.

    Mirrors the server's own path construction: ``playground<uid>`` for the
    default project and ``playground<uid><project>`` for a named one.
    """
    if not package_root:
        return None
    suffix = "" if project == "default" else str(project)
    return os.path.join(
        str(package_root), "docassemble", f"playground{int(user_id)}{suffix}"
    )


def publish_module_source(
    *,
    package_root: Optional[str],
    user_id: int,
    project: str,
    filename: str,
    content: str,
) -> str:
    """Copy one module into the importable package directory.

    Returns:
        ``"live"``
            The module was not there before, so no worker can be holding an
            older version of it in ``sys.modules``. It is importable now.
        ``"restart_required"``
            An existing module was overwritten. Workers that already imported
            it keep the old code until the processes restart.
        ``"unavailable"``
            The package directory could not be written — a read-only file
            system, or a server that does not expose its package root. The
            caller should fall back to requiring a restart.
    """
    target_dir = module_package_directory(package_root, user_id, project)
    if not target_dir:
        return "unavailable"
    target = os.path.join(target_dir, filename)
    try:
        existed = os.path.exists(target)
        os.makedirs(target_dir, exist_ok=True)
        # Written under a temporary name and renamed so that a worker importing
        # concurrently sees either the whole old file or the whole new one, and
        # so the directory mtime changes on completion rather than on creation.
        staging = os.path.join(target_dir, f".weaver-{os.getpid()}-{filename}")
        with open(staging, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(staging, target)
    except OSError:
        return "unavailable"
    # Python caches each directory's listing keyed on its mtime, so a sibling
    # worker process would normally notice the new file by itself. Coarse mtime
    # granularity can defeat that within the same second, and invalidating here
    # at least guarantees it for this process.
    importlib.invalidate_caches()
    return "restart_required" if existed else "live"


def unpublish_module(
    *, package_root: Optional[str], user_id: int, project: str, filename: str
) -> bool:
    """Remove a module from the importable package directory.

    Deleting the copy stops the *next* import from succeeding, but any worker
    that already imported it keeps the module object, so the caller still has
    to mark the project dirty.
    """
    target_dir = module_package_directory(package_root, user_id, project)
    if not target_dir:
        return False
    try:
        os.remove(os.path.join(target_dir, filename))
    except OSError:
        return False
    importlib.invalidate_caches()
    return True


# ---------------------------------------------------------------------------
# Pending-restart bookkeeping
# ---------------------------------------------------------------------------


def modules_dirty_key(user_id: int, project: str) -> str:
    return f"{MODULES_DIRTY_KEY_PREFIX}{int(user_id)}:{project}"


def restart_status_key(code: str) -> str:
    return f"{RESTART_STATUS_KEY_PREFIX}{code}"


def _decode(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _redis_set(redis: Any, key: str, value: str, ttl: int) -> None:
    pipe = redis.pipeline()
    pipe.set(key, value)
    pipe.expire(key, ttl)
    pipe.execute()


def mark_modules_dirty(
    redis: Any,
    user_id: int,
    project: str,
    filename: str,
    *,
    server_start_time: float,
    reason: str = "changed",
) -> Dict[str, Any]:
    """Record that this project has module changes awaiting a restart."""
    key = modules_dirty_key(user_id, project)
    state = _read_raw_dirty(redis, key) or {}
    files: List[Dict[str, str]] = [
        entry
        for entry in state.get("files", [])
        if isinstance(entry, dict) and entry.get("filename") != filename
    ]
    files.append({"filename": filename, "reason": reason})
    payload = {
        "files": sorted(files, key=lambda entry: entry.get("filename", "")),
        "since": float(state.get("since") or time.time()),
        "server_start_time": float(server_start_time),
    }
    _redis_set(redis, key, json.dumps(payload), MODULES_DIRTY_TTL_SECONDS)
    return payload


def _read_raw_dirty(redis: Any, key: str) -> Optional[Dict[str, Any]]:
    raw = _decode(redis.get(key))
    if not raw:
        return None
    try:
        state = json.loads(raw)
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def read_modules_dirty(
    redis: Any, user_id: int, project: str, *, server_start_time: float
) -> Optional[Dict[str, Any]]:
    """Return the pending module changes, or ``None`` if there are none.

    A flag set before the currently running process booted is stale: the server
    has restarted since — by our hand, by the stock Playground, or by a package
    install — and the modules are loaded. Those flags clear themselves, so a
    restart from anywhere counts.
    """
    key = modules_dirty_key(user_id, project)
    state = _read_raw_dirty(redis, key)
    if not state:
        return None
    try:
        marked_at = float(state.get("server_start_time") or 0)
    except (TypeError, ValueError):
        marked_at = 0.0
    if server_start_time > marked_at:
        clear_modules_dirty(redis, user_id, project)
        return None
    files = [
        entry
        for entry in state.get("files", [])
        if isinstance(entry, dict) and entry.get("filename")
    ]
    if not files:
        return None
    return {"files": files, "since": state.get("since")}


def clear_modules_dirty(redis: Any, user_id: int, project: str) -> None:
    key = modules_dirty_key(user_id, project)
    delete = getattr(redis, "delete", None)
    if callable(delete):
        try:
            delete(key)
            return
        except Exception:  # pragma: no cover - redis client differences
            pass
    _redis_set(redis, key, json.dumps({"files": []}), 60)


def normalize_restart_policy(raw: Any) -> str:
    """Coerce the configured restart policy, defaulting to ``prompt``."""
    text = str(raw or "").strip().lower().replace("_", " ").replace("-", " ")
    if text in RESTART_POLICIES:
        return text
    if text in {"ask", "confirm"}:
        return "prompt"
    if text in {"always", "automatic", "immediately"}:
        return "auto"
    if text in {"off", "false", "no", "manual", "none"}:
        return "never"
    return DEFAULT_RESTART_POLICY
