"""API tests for /api/drive/* and the drive fields on /api/me.

No network: Google's token/userinfo endpoints are mocked with pytest-httpx (patches only
httpx.HTTPTransport, so the TestClient's own ASGI-transport requests are unaffected)."""
from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi.testclient import TestClient

from tests.api_fixtures import make_test_app
from vocal_coach.drive import crypto, oauth, state
from vocal_coach.storage import repo

FRONTEND = "http://localhost:5173"


def _overrides(**extra) -> dict:
    return {
        "google_client_id": "cid",
        "google_client_secret": "sec",
        "google_redirect_uri": "http://localhost:8000/api/drive/callback",
        "drive_token_key": crypto.generate_key(),
        "secret_key": "test-secret-key-0123456789abcdefghij",
        **extra,
    }


def _state_from_url(url: str) -> str:
    return parse_qs(urlsplit(url).query)["state"][0]


def _connect_and_get_state(client, ctx, sub="user-1") -> str:
    url = client.get("/api/drive/connect", headers=ctx["auth"](sub)).json()["url"]
    return _state_from_url(url)


def _mock_google_token_and_email(httpx_mock, *, refresh_token="1//refresh", email="singer@example.com"):
    httpx_mock.add_response(url=oauth.TOKEN_URL, json={"refresh_token": refresh_token, "access_token": "access-tok"})
    httpx_mock.add_response(url=oauth.USERINFO_URL, json={"email": email})


def test_connect_returns_google_url_with_state_bound_to_caller(tmp_path):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app) as client:
        me = client.get("/api/me", headers=ctx["auth"]()).json()
        r = client.get("/api/drive/connect", headers=ctx["auth"]())
        assert r.status_code == 200
        url = r.json()["url"]
        assert url.startswith(oauth.AUTH_URL)
        bound_user, nonce = state.verify_state(ctx["settings"].secret_key, _state_from_url(url))
        assert str(bound_user) == me["id"]
        set_cookie = r.headers["set-cookie"]
        assert set_cookie.startswith(f"vc_drive_oauth={nonce};")
        lowered = set_cookie.lower()
        assert "httponly" in lowered and "samesite=lax" in lowered
        assert "path=/api/drive/callback" in lowered and "max-age=600" in lowered
        assert "secure" not in lowered  # http frontend origin in tests


def test_connect_cookie_is_secure_for_https_frontend(tmp_path):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides(frontend_origin="https://coach.example.com"))
    with TestClient(app) as client:
        r = client.get("/api/drive/connect", headers=ctx["auth"]())
        assert "secure" in r.headers["set-cookie"].lower()


def test_callback_without_browser_cookie_returns_400(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        state_value = _connect_and_get_state(client, ctx)
        client.cookies.clear()  # e.g. a victim's browser following an attacker's callback link

        r = client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        assert r.status_code == 400
        assert r.json()["detail"] == "invalid or expired state"
        assert not httpx_mock.get_requests()  # never reached Google


def test_callback_with_mismatched_cookie_returns_400(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        state_value = _connect_and_get_state(client, ctx)
        client.cookies.clear()
        client.cookies.set("vc_drive_oauth", "some-other-nonce", path="/api/drive/callback")

        r = client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        assert r.status_code == 400
        assert r.json()["detail"] == "invalid or expired state"
        assert not httpx_mock.get_requests()


def test_callback_replayed_state_returns_400_and_cookie_cleared(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        url = client.get("/api/drive/connect", headers=ctx["auth"]()).json()["url"]
        state_value = _state_from_url(url)
        nonce = client.cookies.get("vc_drive_oauth")
        _mock_google_token_and_email(httpx_mock)

        first = client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})
        assert first.status_code == 303
        assert 'vc_drive_oauth="";' in first.headers["set-cookie"] or "vc_drive_oauth=;" in first.headers["set-cookie"]
        assert "max-age=0" in first.headers["set-cookie"].lower()

        client.cookies.set("vc_drive_oauth", nonce, path="/api/drive/callback")  # replay with the cookie too
        second = client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        assert second.status_code == 400
        assert second.json()["detail"] == "invalid or expired state"
        assert len(httpx_mock.get_requests(url=oauth.TOKEN_URL)) == 1


def test_callback_with_state_omitted_returns_400(tmp_path):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        _connect_and_get_state(client, ctx)
        r = client.get("/api/drive/callback", params={"code": "auth-code"})
        assert r.status_code == 400
        assert r.json()["detail"] == "invalid or expired state"


def test_callback_expired_state_returns_400(tmp_path, monkeypatch, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        state_value = _connect_and_get_state(client, ctx)
        monkeypatch.setattr(state, "STATE_MAX_AGE_S", -1)

        r = client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        assert r.status_code == 400
        assert r.json()["detail"] == "invalid or expired state"
        assert not httpx_mock.get_requests()


def test_reconnect_revokes_the_previous_refresh_token(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        _mock_google_token_and_email(httpx_mock, refresh_token="1//old")
        client.get("/api/drive/callback", params={"code": "c1", "state": _connect_and_get_state(client, ctx)})
        _mock_google_token_and_email(httpx_mock, refresh_token="1//new")
        httpx_mock.add_response(url=oauth.REVOKE_URL, status_code=200)

        r = client.get("/api/drive/callback", params={"code": "c2", "state": _connect_and_get_state(client, ctx)})

        assert r.status_code == 303
        revokes = httpx_mock.get_requests(url=oauth.REVOKE_URL)
        assert [parse_qs(req.content.decode()) for req in revokes] == [{"token": ["1//old"]}]
        me = client.get("/api/me", headers=ctx["auth"]()).json()
        with ctx["session_factory"]() as session:
            row = repo.get_drive_connection(session, uuid.UUID(me["id"]))
            assert crypto.decrypt_token(ctx["settings"].drive_token_key, row.encrypted_refresh_token) == "1//new"


def test_callback_success_stores_connection_and_redirects(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        me = client.get("/api/me", headers=ctx["auth"]()).json()
        state_value = _connect_and_get_state(client, ctx)
        _mock_google_token_and_email(httpx_mock)

        r = client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        assert r.status_code == 303
        assert r.headers["location"] == f"{FRONTEND}/settings?drive=connected"
        with ctx["session_factory"]() as session:
            row = repo.get_drive_connection(session, uuid.UUID(me["id"]))
            assert row is not None
            assert row.google_email == "singer@example.com"
            assert crypto.decrypt_token(ctx["settings"].drive_token_key, row.encrypted_refresh_token) == "1//refresh"

        me_after = client.get("/api/me", headers=ctx["auth"]()).json()
        assert me_after["drive_connected"] is True
        assert me_after["google_email"] == "singer@example.com"


def test_callback_tampered_state_returns_400(tmp_path):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        state_value = _connect_and_get_state(client, ctx)
        tampered = state_value[:-2] + "xx"

        r = client.get("/api/drive/callback", params={"code": "auth-code", "state": tampered})

        assert r.status_code == 400
        assert r.json()["detail"] == "invalid or expired state"


def test_callback_missing_code_or_state_returns_400(tmp_path):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        state_value = _connect_and_get_state(client, ctx)
        r = client.get("/api/drive/callback", params={"state": state_value})
        assert r.status_code == 400
        assert r.json()["detail"] == "invalid or expired state"


def test_callback_replayed_code_redirects_to_settings_error(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        state_value = _connect_and_get_state(client, ctx)
        httpx_mock.add_response(url=oauth.TOKEN_URL, status_code=400, json={"error": "invalid_grant"})

        r = client.get("/api/drive/callback", params={"code": "already-used-code", "state": state_value})

        assert r.status_code == 303
        assert r.headers["location"] == f"{FRONTEND}/settings?drive=error"
        assert "max-age=0" in r.headers["set-cookie"].lower()  # cookie cleared on failure too


def test_callback_missing_drive_scope_redirects_to_settings_error(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        me = client.get("/api/me", headers=ctx["auth"]()).json()
        state_value = _connect_and_get_state(client, ctx)
        httpx_mock.add_response(url=oauth.TOKEN_URL, json={
            "refresh_token": "1//r", "access_token": "a", "scope": "https://www.googleapis.com/auth/userinfo.email"})

        r = client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        assert r.status_code == 303
        assert r.headers["location"] == f"{FRONTEND}/settings?drive=error"
        with ctx["session_factory"]() as session:
            assert repo.get_drive_connection(session, uuid.UUID(me["id"])) is None


def test_callback_other_google_error_redirects_to_settings_error(tmp_path):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        r = client.get("/api/drive/callback", params={"error": "server_error"})
        assert r.status_code == 303
        assert r.headers["location"] == f"{FRONTEND}/settings?drive=error"


def test_callback_access_denied_redirects_to_cancelled(tmp_path):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app, follow_redirects=False) as client:
        r = client.get("/api/drive/callback", params={"error": "access_denied"})
        assert r.status_code == 303
        assert r.headers["location"] == f"{FRONTEND}/settings?drive=cancelled"


def test_drive_files_lists_mocked_media(tmp_path, httpx_mock):
    from vocal_coach.drive.client import DRIVE_API

    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app) as client:
        state_value = _connect_and_get_state(client, ctx)
        _mock_google_token_and_email(httpx_mock)
        client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "listing-tok"})
        httpx_mock.add_response(
            url=httpx.URL(DRIVE_API, params={
                "q": "'root' in parents and trashed = false",
                "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size)",
                "pageSize": 200,
            }),
            json={"files": [
                {"id": "f1", "name": "take.wav", "mimeType": "audio/wav", "modifiedTime": "2026-10-04T10:00:00.000Z", "size": "99"},
            ]},
        )

        r = client.get("/api/drive/files", headers=ctx["auth"]())

        assert r.status_code == 200
        assert r.json() == [{
            "id": "f1", "name": "take.wav", "mime_type": "audio/wav",
            "modified_time": "2026-10-04T10:00:00.000Z", "size": 99, "is_folder": False,
        }]


def test_drive_files_lists_folders_first_with_is_folder_true_and_no_size(tmp_path, httpx_mock):
    from vocal_coach.drive.client import DRIVE_API

    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app) as client:
        state_value = _connect_and_get_state(client, ctx)
        _mock_google_token_and_email(httpx_mock)
        client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "listing-tok"})
        httpx_mock.add_response(
            url=httpx.URL(DRIVE_API, params={
                "q": "'root' in parents and trashed = false",
                "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size)",
                "pageSize": 200,
            }),
            json={"files": [
                {"id": "f1", "name": "take.wav", "mimeType": "audio/wav",
                 "modifiedTime": "2026-10-04T10:00:00.000Z", "size": "99"},
                {"id": "d1", "name": "Live Takes", "mimeType": "application/vnd.google-apps.folder",
                 "modifiedTime": "2026-10-03T10:00:00.000Z"},
            ]},
        )

        r = client.get("/api/drive/files", headers=ctx["auth"]())

        assert r.status_code == 200
        assert r.json() == [
            {"id": "d1", "name": "Live Takes", "mime_type": "application/vnd.google-apps.folder",
             "modified_time": "2026-10-03T10:00:00.000Z", "size": None, "is_folder": True},
            {"id": "f1", "name": "take.wav", "mime_type": "audio/wav",
             "modified_time": "2026-10-04T10:00:00.000Z", "size": 99, "is_folder": False},
        ]


def test_drive_files_invalid_grant_is_409_and_deletes_row_and_flips_me(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app) as client:
        me = client.get("/api/me", headers=ctx["auth"]()).json()
        state_value = _connect_and_get_state(client, ctx)
        _mock_google_token_and_email(httpx_mock)
        client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        httpx_mock.add_response(url=oauth.TOKEN_URL, status_code=400, json={"error": "invalid_grant"})

        r = client.get("/api/drive/files", headers=ctx["auth"]())

        assert r.status_code == 409
        assert r.json()["detail"] == "drive_not_connected"
        with ctx["session_factory"]() as session:
            assert repo.get_drive_connection(session, uuid.UUID(me["id"])) is None
        me_after = client.get("/api/me", headers=ctx["auth"]()).json()
        assert me_after["drive_connected"] is False


def test_delete_connect_revokes_then_204_then_404(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app) as client:
        state_value = _connect_and_get_state(client, ctx)
        _mock_google_token_and_email(httpx_mock)
        client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        httpx_mock.add_response(url=oauth.REVOKE_URL, status_code=200)

        r = client.delete("/api/drive/connect", headers=ctx["auth"]())
        assert r.status_code == 204
        revoke_requests = httpx_mock.get_requests(url=oauth.REVOKE_URL)
        assert len(revoke_requests) == 1
        assert parse_qs(revoke_requests[0].content.decode()) == {"token": ["1//refresh"]}

        r2 = client.delete("/api/drive/connect", headers=ctx["auth"]())
        assert r2.status_code == 404
        assert r2.json()["detail"] == "drive_not_connected"


def test_unconfigured_server_drive_configured_false_and_connect_and_files_503(tmp_path):
    app, ctx = make_test_app(tmp_path)  # no overrides: no Google credentials
    with TestClient(app) as client:
        me = client.get("/api/me", headers=ctx["auth"]()).json()
        assert me["drive_configured"] is False

        r = client.get("/api/drive/connect", headers=ctx["auth"]())
        assert r.status_code == 503
        assert r.json()["detail"] == "drive is not configured on this server"

        r2 = client.get("/api/drive/files", headers=ctx["auth"]())
        assert r2.status_code == 503
        assert r2.json()["detail"] == "drive is not configured on this server"


def test_another_user_cannot_see_the_connection(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app) as client:
        state_value = _connect_and_get_state(client, ctx, sub="user-1")
        _mock_google_token_and_email(httpx_mock)
        client.get("/api/drive/callback", params={"code": "auth-code", "state": state_value})

        r = client.get("/api/drive/files", headers=ctx["auth"]("user-2"))
        assert r.status_code == 409
        assert r.json()["detail"] == "drive_not_connected"

        me_other = client.get("/api/me", headers=ctx["auth"]("user-2")).json()
        assert me_other["drive_connected"] is False


def _store_connection(ctx, key: str, sub="user-1") -> uuid.UUID:
    with ctx["session_factory"]() as session:
        user = repo.upsert_user(session, sub, None, None)
        repo.upsert_drive_connection(session, user.id, encrypted_refresh_token=crypto.encrypt_token(key, "1//r"),
                                     google_email=None)
        return user.id


def test_missing_token_key_with_existing_row_files_503_and_disconnect_deletes(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides(drive_token_key=None))
    with TestClient(app) as client:
        user_id = _store_connection(ctx, crypto.generate_key())

        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": ["abc"]})
        assert r.status_code == 503
        assert r.json()["detail"] == "drive is not configured on this server"

        r = client.delete("/api/drive/connect", headers=ctx["auth"]())
        assert r.status_code == 204
        assert not httpx_mock.get_requests()  # no decrypt, no revoke
        with ctx["session_factory"]() as session:
            assert repo.get_drive_connection(session, user_id) is None


def test_access_token_for_requires_configuration(tmp_path):
    from vocal_coach.drive import service
    from vocal_coach.drive.errors import DriveNotConfigured
    import pytest

    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides(drive_token_key=None))
    user_id = _store_connection(ctx, crypto.generate_key())
    with ctx["session_factory"]() as session, pytest.raises(DriveNotConfigured):
        service.access_token_for(session, ctx["settings"], user_id)


def test_files_rejects_malformed_folder_id_with_404(tmp_path, httpx_mock):
    app, ctx = make_test_app(tmp_path, settings_overrides=_overrides())
    with TestClient(app) as client:
        for bad in ("a b", "x' or name contains '", "a" * 201, "abc\n"):
            r = client.get("/api/drive/files", params={"folder_id": bad}, headers=ctx["auth"]())
            assert r.status_code == 404, bad
            assert r.json()["detail"] == "folder not found"
        assert not httpx_mock.get_requests()
