# do not pre-load

"""Exercise shared Playground access through the real editor request boundary."""

import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from flask import session

from .test_editor_api import api_editor
from . import docassemble_compat


@pytest.fixture
def playground(monkeypatch):
    monkeypatch.setitem(api_editor.app.config, "SECRET_KEY", "playground-test-secret")
    monkeypatch.setitem(api_editor.app.config, "ENABLE_PLAYGROUND", True)
    monkeypatch.setitem(api_editor.app.config, "ENABLE_SHARING_PLAYGROUNDS", True)
    actor = SimpleNamespace(
        id=7,
        email="author@example.org",
        first_name="Author",
        last_name="",
        is_authenticated=True,
        has_role=lambda *roles: "developer" in roles,
    )
    monkeypatch.setattr(api_editor, "current_user", actor)
    users = [
        {"id": 7, "email": actor.email, "name": "Author"},
        {"id": 12, "email": "colleague@example.org", "name": "Colleague"},
    ]
    listing = Mock(return_value=users)
    monkeypatch.setattr(api_editor, "list_playground_users", listing)

    def select(uid):
        if uid == actor.id:
            session.pop("playground_user", None)
        else:
            session["playground_user"] = uid

    selecting = Mock(side_effect=select)
    monkeypatch.setattr(api_editor, "select_playground_user", selecting)
    monkeypatch.setattr(api_editor, "_project_github_sync_summaries", lambda *a: {})
    projects = Mock(return_value=["default", "Housing"])
    monkeypatch.setattr(api_editor, "playground_list_projects", projects)
    return SimpleNamespace(
        client=api_editor.app.test_client(),
        actor=actor,
        users=users,
        listing=listing,
        selecting=selecting,
        projects=projects,
    )


@pytest.mark.parametrize("role", ["anonymous", "user", "developer", "admin"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_playground_selector_requires_native_roles(playground, role, method):
    playground.actor.is_authenticated = role != "anonymous"
    playground.actor.has_role = lambda *roles: role in roles
    response = playground.client.open(
        "/al/editor/api/playground", method=method, json={"user_id": 12}
    )
    assert response.status_code == (200 if role in {"admin", "developer"} else 401)
    if role in {"anonymous", "user"}:
        playground.listing.assert_not_called()
        playground.selecting.assert_not_called()


@pytest.mark.parametrize("flag", ["ENABLE_PLAYGROUND", "ENABLE_SHARING_PLAYGROUNDS"])
def test_sharing_requires_both_native_flags(playground, monkeypatch, flag):
    monkeypatch.setitem(api_editor.app.config, flag, False)
    assert playground.client.get("/al/editor/api/playground").status_code == 404
    assert (
        playground.client.post(
            "/al/editor/api/playground", json={"user_id": 12}
        ).status_code
        == 404
    )
    playground.listing.assert_not_called()
    playground.selecting.assert_not_called()


@pytest.mark.parametrize("target", [None, True, "12", 0, -1, 12.5, {}, []])
def test_selection_rejects_invalid_ids(playground, target):
    response = playground.client.post(
        "/al/editor/api/playground", json={"user_id": target}
    )
    assert response.status_code == 400
    playground.selecting.assert_not_called()


def test_selection_rejects_users_outside_native_list(playground):
    response = playground.client.post("/al/editor/api/playground", json={"user_id": 13})
    assert response.status_code == 403
    playground.selecting.assert_not_called()


def test_selection_rejects_non_object_request(playground):
    response = playground.client.post("/al/editor/api/playground", json=[12])
    assert response.status_code == 400
    playground.selecting.assert_not_called()


def test_shared_bootstrap_and_raw_preview_use_native_owner(playground, tmp_path):
    playground.users[1]["name"] = "</script><script>owner</script>"
    with playground.client.session_transaction() as cookie:
        cookie["playground_user"] = 12
    with (
        patch.object(
            api_editor,
            "_get_template_content",
            return_value="__EDITOR_BOOTSTRAP_JSON__",
        ),
        patch.object(api_editor, "_editor_feature_bootstrap", return_value={}),
        patch.object(api_editor, "generate_csrf", return_value="csrf-test"),
    ):
        response = playground.client.get("/al/editor/projects")
    bootstrap = json.loads(response.get_data(as_text=True))
    assert "</script>" not in response.get_data(as_text=True)
    assert bootstrap["playground"]["name"] == playground.users[1]["name"]
    assert bootstrap["authenticated"] is True
    assert bootstrap["playground"]["user_id"] == 12
    assert bootstrap["playground"]["own_user_id"] == 7
    assert bootstrap["auth"]["email"] == playground.actor.email
    assert response.headers["Cache-Control"] == "no-store"
    playground.projects.assert_called_once_with(12)
    (tmp_path / "form.pdf").write_bytes(b"%PDF-colleague")
    with patch.object(
        api_editor, "_editor_storage_directory", return_value=(None, str(tmp_path))
    ) as directory:
        response = playground.client.get(
            "/al/editor/api/section-file/raw?project=Housing&section=templates&filename=form.pdf&playground_user_id=12"
        )
    assert response.status_code == 200
    assert response.data == b"%PDF-colleague"
    assert response.headers["Cache-Control"] == "no-store"
    directory.assert_called_once_with(
        12, "Housing", api_editor.EDITOR_SECTION_TO_STORAGE["templates"]
    )


def test_native_selection_controls_reads_and_writes(playground):
    response = playground.client.post("/al/editor/api/playground", json={"user_id": 12})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["data"]["playground"]["own"] is False
    with playground.client.session_transaction() as cookie:
        assert cookie["playground_user"] == 12
    headers = {"X-Weaver-Playground-User": "12"}
    response = playground.client.get("/al/editor/api/projects", headers=headers)
    assert response.status_code == 200
    playground.projects.assert_called_once_with(12)
    with patch.object(api_editor, "playground_write_yaml") as write:
        response = playground.client.post(
            "/al/editor/api/file/new",
            headers=headers,
            json={"project": "Housing", "filename": "main.yml"},
        )
        assert response.status_code == 200, response.get_json()
        assert write.call_args.args[:3] == (12, "Housing", "main.yml")


@pytest.mark.parametrize("expected", [None, "7", "garbage"])
def test_old_or_unscoped_tabs_cannot_read_or_write_selected_playground(
    playground, expected
):
    with playground.client.session_transaction() as cookie:
        cookie["playground_user"] = 12
    headers = {"X-Weaver-Playground-User": expected} if expected is not None else {}
    assert (
        playground.client.get("/al/editor/api/projects", headers=headers).status_code
        == 409
    )
    with patch.object(api_editor, "playground_write_yaml") as write:
        response = playground.client.post(
            "/al/editor/api/file/new",
            headers=headers,
            json={"filename": "main.yml"},
        )
        assert response.status_code == 409
        write.assert_not_called()
    playground.projects.assert_not_called()


def test_raw_preview_query_pins_owner_but_does_not_select_it(playground):
    with playground.client.session_transaction() as cookie:
        cookie["playground_user"] = 12
    assert (
        playground.client.get(
            "/al/editor/api/projects?playground_user_id=12"
        ).status_code
        == 200
    )
    playground.projects.assert_called_once_with(12)
    assert (
        playground.client.get(
            "/al/editor/api/projects?playground_user_id=7"
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "revoked", ["disabled", "deleted", "sharing_off", "playground_off"]
)
def test_revoked_selection_blocks_old_tab_and_returns_storage_home(
    playground, monkeypatch, revoked
):
    with playground.client.session_transaction() as cookie:
        cookie["playground_user"] = 12
    if revoked in {"disabled", "deleted"}:
        # Both cases are removed by Docassemble's own list query.
        playground.users.pop()
    else:
        flag = (
            "ENABLE_SHARING_PLAYGROUNDS"
            if revoked == "sharing_off"
            else "ENABLE_PLAYGROUND"
        )
        monkeypatch.setitem(api_editor.app.config, flag, False)
    response = playground.client.get(
        "/al/editor/api/projects", headers={"X-Weaver-Playground-User": "12"}
    )
    assert response.status_code == 409
    playground.projects.assert_not_called()
    # Docassemble's own navigation is reset too, not just the session key.
    playground.selecting.assert_called_once_with(7)
    with playground.client.session_transaction() as cookie:
        assert "playground_user" not in cookie
    assert (
        playground.client.get(
            "/al/editor/api/projects", headers={"X-Weaver-Playground-User": "7"}
        ).status_code
        == 200
    )
    playground.projects.assert_called_once_with(7)


def test_return_home_works_after_sharing_disabled_and_blocks_old_shared_tab(
    playground, monkeypatch
):
    with playground.client.session_transaction() as cookie:
        cookie["playground_user"] = 12
    monkeypatch.setitem(api_editor.app.config, "ENABLE_SHARING_PLAYGROUNDS", False)
    response = playground.client.post("/al/editor/api/playground", json={"user_id": 7})
    assert response.status_code == 200
    assert response.get_json()["data"]["playground"]["own"] is True
    playground.listing.assert_not_called()
    assert (
        playground.client.get(
            "/al/editor/api/projects", headers={"X-Weaver-Playground-User": "12"}
        ).status_code
        == 409
    )


def test_native_list_failure_never_touches_storage(playground):
    with playground.client.session_transaction() as cookie:
        cookie["playground_user"] = 12
    playground.listing.side_effect = RuntimeError("database unavailable")
    response = playground.client.get(
        "/al/editor/api/projects", headers={"X-Weaver-Playground-User": "12"}
    )
    assert response.status_code == 503
    playground.projects.assert_not_called()


def test_shared_playground_keeps_actor_github_credentials(playground):
    with playground.client.session_transaction() as cookie:
        cookie["playground_user"] = 12
    with (
        patch.object(
            api_editor,
            "get_native_github_integration",
            return_value={"enabled": True, "connected": False},
        ) as integration,
        patch.object(api_editor, "find_project_github_sync", return_value=None) as sync,
    ):
        response = playground.client.get(
            "/al/editor/api/github/status?project=Housing",
            headers={"X-Weaver-Playground-User": "12"},
        )
    assert response.status_code == 200
    integration.assert_called_once_with(7)
    sync.assert_called_once_with(user_id=12, project_name="Housing")


def test_shared_publish_worker_keeps_files_and_credentials_separate():
    with (
        patch.object(api_editor, "_update_job_state"),
        patch.object(api_editor, "_assert_github_publish_branch_is_current") as branch,
        patch.object(
            api_editor, "ensure_github_repository", return_value={}
        ) as repository,
        patch.object(
            api_editor, "load_project_github_manifest", return_value=({}, "manifest")
        ) as manifest,
        patch.object(
            api_editor,
            "repository_publish_files",
            return_value={"files": {}, "managed_paths": []},
        ),
        patch.object(
            api_editor,
            "publish_github_package",
            return_value={"sha": "commit", "files": 1},
        ) as publish,
        patch.object(api_editor, "record_project_github_sync") as sync,
    ):
        api_editor._complete_github_publish_job(
            job_id="shared-job",
            uid=12,
            credential_user_id=7,
            project="Housing",
            package="Housing",
            repository="docassemble-Housing",
            owner="author",
            owner_type="user",
            author_name="Author",
            author_email="author@example.org",
            branch="main",
            commit_message="Update",
            repository_url="https://github.com/author/docassemble-Housing",
        )
    assert branch.call_args.kwargs["uid"] == 12
    assert branch.call_args.kwargs["credential_user_id"] == 7
    assert repository.call_args.kwargs["user_id"] == 7
    assert manifest.call_args.kwargs["user_id"] == 12
    assert publish.call_args.kwargs["user_id"] == 12
    assert publish.call_args.kwargs["credential_user_id"] == 7
    assert sync.call_args.kwargs["user_id"] == 12


def test_package_snapshot_uses_owner_while_oauth_uses_actor():
    with (
        patch.object(
            docassemble_compat, "build_github_package_snapshot", return_value={}
        ) as snapshot,
        patch.object(
            docassemble_compat,
            "_github_authorized_http",
            side_effect=RuntimeError("OAuth boundary"),
        ) as oauth,
        pytest.raises(RuntimeError, match="OAuth boundary"),
    ):
        docassemble_compat.publish_github_package(
            owner="author",
            repository="docassemble-Housing",
            package="Housing",
            project="Housing",
            user_id=12,
            credential_user_id=7,
            package_info={},
            author_name="Author",
            author_email="author@example.org",
            branch="main",
            commit_message="Update",
        )
    assert snapshot.call_args.kwargs["user_id"] == 12
    oauth.assert_called_once_with(user_id=7)


def test_native_helpers_resolve_both_docassemble_versions_and_deduplicate():
    users = [{"id": 7, "name": "Author", "email": "author@example.org"}] * 2
    clear = Mock()
    setter = Mock()

    def resolve(candidates, capability):
        name = candidates[0][1]
        assert candidates[-1][0] == "docassemble.webapp.server"
        return {
            "get_list_of_playgrounds": lambda: users,
            "clear_current_playground_info": clear,
            "set_playground_user": setter,
        }[name]

    with patch.object(docassemble_compat, "_first_webapp_attr", side_effect=resolve):
        assert docassemble_compat.list_playground_users() == users[:1]
        docassemble_compat.select_playground_user(12)
    clear.assert_called_once_with()
    setter.assert_called_once_with(12)


@pytest.fixture
def zip_archive():
    """A self-deleting temp ZIP like the native builder's, closed even on failure."""
    archive = tempfile.NamedTemporaryFile(suffix=".zip")
    archive.write(b"zip-bytes")
    archive.seek(0)
    yield archive
    archive.close()


@pytest.mark.parametrize("owner", [7, 12])
def test_download_uses_selected_project_and_owner_without_writing_manifest(
    playground, monkeypatch, owner, zip_archive
):
    if owner != 7:
        with playground.client.session_transaction() as selected:
            selected["playground_user"] = owner
    prepare = Mock(
        return_value={"manifest": {"interview_files": ["main.yml", "extra.yml"]}}
    )
    archive = zip_archive
    build = Mock(return_value=archive)
    dependencies = Mock(return_value=["docassemble.AssemblyLine", "requests"])
    monkeypatch.setattr(api_editor, "repository_dependency_names", dependencies)
    monkeypatch.setattr(api_editor, "find_project_github_sync", lambda **kw: None)
    monkeypatch.setattr(api_editor, "prepare_project_github_package", prepare)
    monkeypatch.setattr(api_editor, "build_project_zip", build)
    response = playground.client.get(
        f"/al/editor/api/project/download?project=Housing&playground_user_id={owner}"
    )
    assert response.status_code == 200
    assert response.data == b"zip-bytes"
    assert response.content_length == len(b"zip-bytes")
    response.close()
    # Streamed from the native temp file, which is deleted once the response closes.
    assert archive.closed
    assert not os.path.exists(archive.name)
    assert response.mimetype == "application/zip"
    assert (
        response.headers["Content-Disposition"]
        == "attachment; filename=docassemble-Housing.zip"
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert prepare.call_args.kwargs == dict(
        user_id=owner,
        project_name="Housing",
        package_name="Housing",
        author_name="Author" if owner == 7 else "Colleague",
        author_email="author@example.org" if owner == 7 else "colleague@example.org",
        dependencies=["docassemble.AssemblyLine", "requests"],
        persist_manifest=False,
        require_interview=False,
    )
    dependencies.assert_called_once_with(owner, "Housing", "Housing")
    assert build.call_args.kwargs["user_id"] == owner
    assert build.call_args.kwargs["project"] == "Housing"
    assert build.call_args.kwargs["package_info"] == prepare.return_value["manifest"]


def test_download_closes_archive_when_response_cannot_be_built(
    playground, monkeypatch, zip_archive
):
    monkeypatch.setattr(
        api_editor, "repository_dependency_names", Mock(return_value=[])
    )
    monkeypatch.setattr(api_editor, "find_project_github_sync", lambda **kw: None)
    monkeypatch.setattr(
        api_editor,
        "prepare_project_github_package",
        Mock(return_value={"manifest": {}}),
    )
    monkeypatch.setattr(api_editor, "build_project_zip", Mock(return_value=zip_archive))
    monkeypatch.setattr(api_editor, "send_file", Mock(side_effect=ValueError("bad")))
    response = playground.client.get("/al/editor/api/project/download?project=Housing")
    assert response.status_code == 400
    assert zip_archive.closed
    assert not os.path.exists(zip_archive.name)


def test_download_rejects_missing_project_and_unauthenticated_user(
    playground, monkeypatch
):
    build = Mock()
    monkeypatch.setattr(api_editor, "build_project_zip", build)
    assert (
        playground.client.get(
            "/al/editor/api/project/download?project=Missing"
        ).status_code
        == 400
    )
    playground.actor.is_authenticated = False
    assert (
        playground.client.get(
            "/al/editor/api/project/download?project=Housing"
        ).status_code
        == 401
    )
    build.assert_not_called()
