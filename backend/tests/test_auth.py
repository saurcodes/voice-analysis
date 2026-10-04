import threading

import httpx
import pytest

from tests.auth_keys import make_rsa_jwks, mint
from vocal_coach.auth.jwt import AuthError, JWKSCache, JWKSUnavailable, verify_token

ISS = "http://kc.test/realms/vocal-coach"
AUD = "vocal-coach-web"


@pytest.fixture
def keys():
    pem, jwks, kid = make_rsa_jwks()
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        return jwks

    return pem, kid, JWKSCache("http://kc.test/jwks", fetch=fetch, min_refresh_interval_s=0.0), calls


def test_valid_token_returns_claims(keys):
    pem, kid, cache, _ = keys
    claims = verify_token(mint(pem, kid, iss=ISS, aud=AUD), issuer=ISS, audience=AUD, jwks=cache)
    assert claims["sub"] == "user-1" and claims["preferred_username"] == "user1"


def test_audience_list_containing_target_is_accepted(keys):
    pem, kid, cache, _ = keys
    claims = verify_token(mint(pem, kid, iss=ISS, aud=["account", AUD]), issuer=ISS, audience=AUD, jwks=cache)
    assert claims["sub"] == "user-1"


def test_account_only_audience_is_rejected(keys):
    pem, kid, cache, _ = keys
    with pytest.raises(AuthError):
        verify_token(mint(pem, kid, iss=ISS, aud="account"), issuer=ISS, audience=AUD, jwks=cache)


def test_expired_wrong_issuer_bad_signature(keys):
    pem, kid, cache, _ = keys
    with pytest.raises(AuthError):
        verify_token(mint(pem, kid, iss=ISS, aud=AUD, exp_delta_s=-10), issuer=ISS, audience=AUD, jwks=cache)
    with pytest.raises(AuthError):
        verify_token(mint(pem, kid, iss="http://other/realms/x", aud=AUD), issuer=ISS, audience=AUD, jwks=cache)
    other_pem, _, _ = make_rsa_jwks()
    with pytest.raises(AuthError):
        verify_token(mint(other_pem, kid, iss=ISS, aud=AUD), issuer=ISS, audience=AUD, jwks=cache)


def test_unknown_kid_triggers_one_refetch_then_fails(keys):
    pem, kid, cache, calls = keys
    verify_token(mint(pem, kid, iss=ISS, aud=AUD), issuer=ISS, audience=AUD, jwks=cache)
    n0 = calls["n"]
    with pytest.raises(AuthError):
        verify_token(mint(pem, "missing-kid", iss=ISS, aud=AUD), issuer=ISS, audience=AUD, jwks=cache)
    assert calls["n"] == n0 + 1


def test_garbage_token_is_auth_error(keys):
    _, _, cache, _ = keys
    with pytest.raises(AuthError):
        verify_token("not.a.jwt", issuer=ISS, audience=AUD, jwks=cache)


def test_concurrent_unknown_kid_fetches_once():
    _, jwks, _ = make_rsa_jwks()
    calls = {"n": 0}
    lock = threading.Lock()

    def counting_fetch(url):
        with lock:
            calls["n"] += 1
        return jwks

    cache = JWKSCache("http://kc.test/jwks", fetch=counting_fetch, min_refresh_interval_s=60.0)

    errors = []

    def worker():
        try:
            cache.key_for("missing")
        except AuthError:
            errors.append(True)
        except Exception:
            pass

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 10
    assert calls["n"] == 1


def test_jwks_fetch_failure_raises_jwks_unavailable(keys):
    pem, kid, _, _ = keys

    def failing_fetch(url):
        raise httpx.ConnectError("boom")

    cache = JWKSCache("http://kc.test/jwks", fetch=failing_fetch, min_refresh_interval_s=0.0)
    with pytest.raises(JWKSUnavailable):
        verify_token(mint(pem, kid, iss=ISS, aud=AUD), issuer=ISS, audience=AUD, jwks=cache)


def test_encryption_keys_in_jwks_are_ignored():
    # Keycloak's realm JWKS also publishes an RSA-OAEP key with use=enc; PyJWT cannot load it as a
    # signing key, and it must not stop the RS256 signing key from verifying tokens.
    pem, jwks, kid = make_rsa_jwks()
    sig = jwks["keys"][0]
    enc = {**sig, "kid": "enc-key", "use": "enc", "alg": "RSA-OAEP"}
    cache = JWKSCache("http://kc.test/jwks", fetch=lambda url: {"keys": [enc, sig]}, min_refresh_interval_s=0.0)
    claims = verify_token(mint(pem, kid, iss=ISS, aud=AUD), issuer=ISS, audience=AUD, jwks=cache)
    assert claims["sub"] == "user-1"
    with pytest.raises(AuthError, match="unknown signing key"):
        cache.key_for("enc-key")
