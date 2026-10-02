"""Localhost-only lifecycle probe; run inside Docassemble as www-data.

Save IDs of this regression's sessions so deletion can be checked in the database
after Weaver has correctly removed its tracking record. Never prints answers or
encryption keys. This is separate from the production cleanup command.
"""

import json
import sys
from pathlib import Path
from datetime import timedelta

action, session_id = sys.argv[1:3]
sys.argv = [sys.argv[0], "/usr/share/docassemble/config/config.yml"]
from docassemble.base import config

config.load(arguments=sys.argv)
from docassemble.ALWeaver.docassemble_compat import (
    TargetSession,
    get_flask_app,
    get_redis_client,
    get_target_session_revision,
    create_target_session,
    delete_target_session,
    get_worker_app,
)
from docassemble.ALWeaver.runtime_sessions import (
    load_runtime_record,
    store_runtime_record,
    utc_now,
    RUNTIME_SESSION_KEY_PREFIX,
    RUNTIME_SESSION_DUE_KEY,
)

cache_path = Path("/tmp/alweaver_runtime_probe_targets.json")
known = json.loads(cache_path.read_text()) if cache_path.exists() else {}
app = get_flask_app()
with app.app_context(), app.test_request_context("/interview"):
    app.preprocess_request()
    redis_client = get_redis_client()
    raw = redis_client.get(RUNTIME_SESSION_KEY_PREFIX + session_id)
    record = None
    if raw:
        owner = int(json.loads(raw)["owner_user_id"])
        record = load_runtime_record(redis_client, session_id, owner)
    if action == "capture":
        assert record is not None
        known[session_id] = {
            "yaml_filename": record.yaml_filename,
            "docassemble_session_id": record.docassemble_session_id,
            "owner_user_id": record.owner_user_id,
        }
    item = known[session_id]
    target = TargetSession(item["yaml_filename"], item["docassemble_session_id"])
    if action == "normal":
        from flask_login import login_user
        from sqlalchemy import select
        from docassemble.webapp.extensions import db
        from docassemble.webapp.users.models import UserModel
        from docassemble.webapp.main.helpers import set_admin_interviews
        from docassemble.webapp.interview.config import page_parts

        login_user(
            db.session.execute(
                select(UserModel).where(UserModel.id == item["owner_user_id"])
            ).scalar_one()
        )
        app.config["ADMIN_INTERVIEWS"] = set_admin_interviews()
        app.config["PARTS"] = page_parts
        normal = create_target_session(target.yaml_filename)
        item["normal_session_id"] = normal.session_id
    elif action == "cleanup-normal" and item.get("normal_session_id"):
        delete_target_session(
            TargetSession(target.yaml_filename, item["normal_session_id"]),
            item["owner_user_id"],
        )
        item.pop("normal_session_id")
    elif action == "age":
        assert record is not None
        record.last_progress_at = utc_now() - timedelta(minutes=31)
        revision = get_target_session_revision(target)
        assert revision is not None
        record.progress_revision = revision[0]
        store_runtime_record(redis_client, record)
    elif action == "worker":
        assert record is not None
        get_worker_app().send_task(
            "docassemble.ALWeaver.api_weaver_worker.weaver_cleanup_runtime_session_task",
            kwargs={"session_id": session_id, "owner_user_id": item["owner_user_id"]},
            countdown=0,
        )
    cache_path.write_text(json.dumps(known))
    cache_path.chmod(0o600)
    saved = (
        TargetSession(target.yaml_filename, item["normal_session_id"])
        if item.get("normal_session_id")
        else None
    )
    print(
        json.dumps(
            {
                "tracked": redis_client.get(RUNTIME_SESSION_KEY_PREFIX + session_id)
                is not None,
                "database": get_target_session_revision(target) is not None,
                "deadline_index": redis_client.zscore(
                    RUNTIME_SESSION_DUE_KEY, session_id
                )
                is not None,
                "normal_database": (
                    get_target_session_revision(saved) is not None if saved else None
                ),
            }
        )
    )
