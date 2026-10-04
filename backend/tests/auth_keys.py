"""RSA test keys and token minting for auth tests. Never used in production."""
from __future__ import annotations

import base64
import time
import uuid

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64url(n: int, length: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()


def make_rsa_jwks() -> tuple[bytes, dict, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = key.public_key().public_numbers()
    kid = uuid.uuid4().hex
    jwks = {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
                      "n": _b64url(pub.n, 256), "e": _b64url(pub.e, 3)}]}
    return pem, jwks, kid


def mint(private_pem: bytes, kid: str, *, iss: str, aud, sub="user-1", email="u@x.test", username="user1",
         exp_delta_s: int = 600, extra: dict | None = None) -> str:
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "sub": sub, "email": email, "preferred_username": username,
              "iat": now, "exp": now + exp_delta_s, "azp": "vocal-coach-web"}
    claims.update(extra or {})
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})
