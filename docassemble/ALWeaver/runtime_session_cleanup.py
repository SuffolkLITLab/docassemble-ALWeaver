# do not pre-load
"""Administrative cleanup of tracked Weaver debug sessions.

Run as the Docassemble web user, using its Python environment:
python -m docassemble.ALWeaver.runtime_session_cleanup /path/to/config.yml
"""

import sys


def main() -> None:
    from docassemble.base import config

    config.load(arguments=sys.argv)
    from .docassemble_compat import get_flask_app, get_redis_client
    from .runtime_sessions import migrate_runtime_records, cleanup_due_runtime_sessions

    app = get_flask_app()
    with app.app_context(), app.test_request_context("/interview"):
        app.preprocess_request()
        redis_client = get_redis_client()
        migrate_runtime_records(redis_client)
        deleted = cleanup_due_runtime_sessions(redis_client, limit=1000)
        print(f"Deleted {deleted} idle debug sessions and their Docassemble data.")


if __name__ == "__main__":
    main()
