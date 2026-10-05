import uuid

import pytest

from vocal_coach.drive import crypto, state
from vocal_coach.drive.errors import DriveError


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
