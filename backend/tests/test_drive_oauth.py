import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from vocal_coach.drive import crypto, oauth, state
from vocal_coach.drive.errors import DriveError, DriveNotConnected
from vocal_coach.settings import Settings


def test_state_round_trip_and_tamper():
    uid = uuid.uuid4()
    s = state.sign_state("k", uid)
    assert state.verify_state("k", s) == uid
    with pytest.raises(DriveError, match="invalid or expired state"):
        state.verify_state("k", s[:-2] + "xx")
    with pytest.raises(DriveError):
        state.verify_state("other-key", s)


def test_state_expired(monkeypatch):
    import itsdangerous
    uid = uuid.uuid4()
    s = state.sign_state("k", uid)
    real = itsdangerous.URLSafeTimedSerializer.loads

    def expired(self, value, max_age=None, **kw):
        raise itsdangerous.SignatureExpired("old")

    monkeypatch.setattr(itsdangerous.URLSafeTimedSerializer, "loads", expired)
    with pytest.raises(DriveError, match="invalid or expired state"):
        state.verify_state("k", s)


def test_token_encrypt_decrypt_round_trip():
    key = crypto.generate_key()
    blob = crypto.encrypt_token(key, "1//refresh")
    assert blob != b"1//refresh" and crypto.decrypt_token(key, blob) == "1//refresh"
    with pytest.raises(DriveError):
        crypto.decrypt_token(crypto.generate_key(), blob)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, google_client_id="cid", google_client_secret="sec",
                    google_redirect_uri="http://localhost:8000/api/drive/callback", **overrides)


def test_consent_url_contains_required_params():
    url = oauth.consent_url(_settings(), "the-state")
    scheme_rest = urlsplit(url)
    assert f"{scheme_rest.scheme}://{scheme_rest.netloc}{scheme_rest.path}" == oauth.AUTH_URL
    params = parse_qs(scheme_rest.query)
    assert params["client_id"] == ["cid"]
    assert params["redirect_uri"] == ["http://localhost:8000/api/drive/callback"]
    assert params["response_type"] == ["code"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["include_granted_scopes"] == ["true"]
    assert params["state"] == ["the-state"]
    assert params["scope"] == [" ".join(oauth.SCOPES)]
    assert "drive.readonly" in params["scope"][0]
    assert "userinfo.email" in params["scope"][0]


def test_exchange_code_posts_form_and_returns_tokens_and_email(httpx_mock):
    httpx_mock.add_response(url=oauth.TOKEN_URL, json={"refresh_token": "1//refresh", "access_token": "access-tok"})
    httpx_mock.add_response(url=oauth.USERINFO_URL, json={"email": "singer@example.com"})

    result = oauth.exchange_code(_settings(), "auth-code")

    assert result.refresh_token == "1//refresh"
    assert result.access_token == "access-tok"
    assert result.email == "singer@example.com"
    token_request = httpx_mock.get_requests(url=oauth.TOKEN_URL)[0]
    posted = parse_qs(token_request.content.decode())
    assert posted == {
        "code": ["auth-code"], "client_id": ["cid"], "client_secret": ["sec"],
        "redirect_uri": ["http://localhost:8000/api/drive/callback"], "grant_type": ["authorization_code"],
    }
    userinfo_request = httpx_mock.get_requests(url=oauth.USERINFO_URL)[0]
    assert userinfo_request.headers["Authorization"] == "Bearer access-tok"


def test_exchange_code_missing_refresh_token_raises_drive_error(httpx_mock):
    httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "access-tok"})

    with pytest.raises(DriveError, match="google did not return a refresh token"):
        oauth.exchange_code(_settings(), "auth-code")


def test_exchange_code_userinfo_failure_yields_none_email(httpx_mock):
    httpx_mock.add_response(url=oauth.TOKEN_URL, json={"refresh_token": "1//refresh", "access_token": "tok"})
    httpx_mock.add_response(url=oauth.USERINFO_URL, status_code=500)

    result = oauth.exchange_code(_settings(), "auth-code")

    assert result.email is None


def test_exchange_code_non_2xx_raises_drive_error_with_status_only(httpx_mock):
    httpx_mock.add_response(url=oauth.TOKEN_URL, status_code=400, json={"error": "invalid_grant", "secret": "nope"})

    with pytest.raises(DriveError, match="google token error 400") as exc_info:
        oauth.exchange_code(_settings(), "replayed-code")
    assert "nope" not in str(exc_info.value)


def test_exchange_code_transport_error_raises_drive_error(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("boom"), url=oauth.TOKEN_URL)

    with pytest.raises(DriveError, match="google token connection error"):
        oauth.exchange_code(_settings(), "auth-code")


def test_refresh_access_token_returns_access_token(httpx_mock):
    httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "new-access-tok"})

    assert oauth.refresh_access_token(_settings(), "1//refresh") == "new-access-tok"

    token_request = httpx_mock.get_requests(url=oauth.TOKEN_URL)[0]
    posted = parse_qs(token_request.content.decode())
    assert posted == {
        "client_id": ["cid"], "client_secret": ["sec"], "refresh_token": ["1//refresh"],
        "grant_type": ["refresh_token"],
    }


def test_refresh_access_token_invalid_grant_raises_drive_not_connected(httpx_mock):
    httpx_mock.add_response(url=oauth.TOKEN_URL, status_code=400, json={"error": "invalid_grant"})

    with pytest.raises(DriveNotConnected, match="drive_not_connected"):
        oauth.refresh_access_token(_settings(), "1//revoked")


def test_refresh_access_token_other_400_raises_drive_error(httpx_mock):
    httpx_mock.add_response(url=oauth.TOKEN_URL, status_code=400, json={"error": "invalid_request"})

    with pytest.raises(DriveError, match="google token error 400"):
        oauth.refresh_access_token(_settings(), "1//refresh")


def test_refresh_access_token_other_non_2xx_raises_drive_error(httpx_mock):
    httpx_mock.add_response(url=oauth.TOKEN_URL, status_code=500)

    with pytest.raises(DriveError, match="google token error 500"):
        oauth.refresh_access_token(_settings(), "1//refresh")


def test_refresh_access_token_transport_error_raises_drive_error(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("boom"), url=oauth.TOKEN_URL)

    with pytest.raises(DriveError, match="google token connection error"):
        oauth.refresh_access_token(_settings(), "1//refresh")


def test_revoke_swallows_non_2xx(httpx_mock):
    httpx_mock.add_response(url=oauth.REVOKE_URL, status_code=400)

    oauth.revoke("1//refresh")  # must not raise


def test_revoke_swallows_transport_error(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("boom"), url=oauth.REVOKE_URL)

    oauth.revoke("1//refresh")  # must not raise
