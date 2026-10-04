"""Keycloak access-token verification against a cached JWKS."""
from __future__ import annotations

import threading
import time
from typing import Callable

import httpx
import jwt
from jwt import PyJWK

ALGORITHMS = ["RS256"]  # Keycloak signs access tokens with RS256 by default
JWKS_HTTP_TIMEOUT_S = 5.0
DEFAULT_MIN_REFRESH_INTERVAL_S = 60.0  # an attacker cannot make us hammer Keycloak with unknown kids


class AuthError(Exception):
    pass


class JWKSUnavailable(AuthError):
    """The identity provider's JWKS endpoint could not be reached (IdP outage, not a bad token)."""


def fetch_jwks(url: str) -> dict:
    response = httpx.get(url, timeout=JWKS_HTTP_TIMEOUT_S)
    response.raise_for_status()
    return response.json()


def _signing_keys(data: dict) -> dict[str, PyJWK]:
    """Keycloak's JWKS also lists an RSA-OAEP key with ``use: enc``; PyJWT cannot load it, and it
    never signs tokens. Keep signing keys only, and skip any key PyJWT cannot load (unknown alg)."""
    keys: dict[str, PyJWK] = {}
    for k in data.get("keys", []):
        if "kid" not in k or k.get("use", "sig") != "sig":
            continue
        try:
            keys[k["kid"]] = PyJWK(k)
        except jwt.PyJWTError:
            continue
    return keys


class JWKSCache:
    def __init__(self, url: str, fetch: Callable[[str], dict] | None = None,
                 min_refresh_interval_s: float = DEFAULT_MIN_REFRESH_INTERVAL_S):
        self._url = url
        self._fetch = fetch or fetch_jwks
        self._min_interval = min_refresh_interval_s
        self._keys: dict[str, PyJWK] = {}
        self._last_refresh = float("-inf")  # never refreshed: the first unknown kid always fetches, even right after boot
        self._lock = threading.Lock()

    def refresh(self) -> None:
        with self._lock:
            self._refresh_locked()

    def _refresh_locked(self) -> None:
        try:
            data = self._fetch(self._url)
        except httpx.HTTPError as e:
            raise JWKSUnavailable(f"could not fetch JWKS: {e}") from e
        except ValueError as e:  # the endpoint answered with something that is not JSON (proxy error page, etc.)
            raise JWKSUnavailable(f"JWKS response is not valid JSON: {e}") from e
        self._keys = _signing_keys(data)
        self._last_refresh = time.monotonic()

    def key_for(self, kid: str) -> PyJWK:
        with self._lock:
            if kid not in self._keys and (time.monotonic() - self._last_refresh) >= self._min_interval:
                self._refresh_locked()
            key = self._keys.get(kid)
        if key is None:
            raise AuthError(f"unknown signing key {kid!r}")
        return key


def verify_token(token: str, *, issuer: str, audience: str, jwks: JWKSCache) -> dict:
    try:
        header = jwt.get_unverified_header(token)
        key = jwks.key_for(header.get("kid", ""))
        return jwt.decode(
            token, key=key.key, algorithms=ALGORITHMS, audience=audience, issuer=issuer,
            options={"require": ["exp", "iss", "sub", "aud"]},
        )
    except AuthError:
        raise
    except jwt.PyJWTError as e:
        raise AuthError(str(e)) from e
    except Exception as e:  # malformed header etc.
        raise AuthError(f"invalid token: {e}") from e
