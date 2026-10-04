import pytest

from tests.auth_keys import make_rsa_jwks, mint
from vocal_coach.auth.jwt import AuthError, JWKSCache, verify_token

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
