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


def fetch_jwks(url: str) -> dict:
    response = httpx.get(url, timeout=JWKS_HTTP_TIMEOUT_S)
    response.raise_for_status()
    return response.json()


class JWKSCache:
    def __init__(self, url: str, fetch: Callable[[str], dict] | None = None,
                 min_refresh_interval_s: float = DEFAULT_MIN_REFRESH_INTERVAL_S):
        self._url = url
        self._fetch = fetch or fetch_jwks
        self._min_interval = min_refresh_interval_s
        self._keys: dict[str, PyJWK] = {}
        self._last_refresh = 0.0
        self._lock = threading.Lock()

    def refresh(self) -> None:
        with self._lock:
            data = self._fetch(self._url)
            self._keys = {k["kid"]: PyJWK(k) for k in data.get("keys", []) if "kid" in k}
            self._last_refresh = time.monotonic()

    def key_for(self, kid: str) -> PyJWK:
        if kid not in self._keys and (time.monotonic() - self._last_refresh) >= self._min_interval:
            self.refresh()
        try:
            return self._keys[kid]
        except KeyError:
            raise AuthError(f"unknown signing key {kid!r}") from None


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
