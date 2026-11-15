import uuid

import jwt

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_hermes_key,
    generate_refresh_token,
    hash_answer,
    hash_password,
    hash_refresh_token,
    normalize_answer,
    verify_answer,
    verify_password,
)


def test_password_roundtrip():
    h = hash_password("Sup3rSecret!")
    assert verify_password("Sup3rSecret!", h)
    assert not verify_password("wrong", h)


def test_normalize_answer():
    assert normalize_answer("  New   York ") == "new york"
    assert normalize_answer("ALPHA") == "alpha"
    assert normalize_answer("\t a  b \n") == "a b"


def test_answer_verification_is_normalized():
    h = hash_answer("New York")
    assert verify_answer("  new   YORK ", h)
    assert not verify_answer("boston", h)


def test_access_token_roundtrip():
    uid = uuid.uuid4()
    token = create_access_token(uid)
    assert decode_access_token(token) == uid


def test_access_token_rejects_wrong_type():
    settings = get_settings()
    uid = uuid.uuid4()
    token = jwt.encode({"sub": str(uid), "type": "refresh"}, settings.jwt_secret, algorithm="HS256")
    assert decode_access_token(token) is None


def test_access_token_rejects_tampered():
    token = create_access_token(uuid.uuid4())
    assert decode_access_token(token + "x") is None
    assert decode_access_token("not-a-token") is None


def test_refresh_token_hash():
    t = generate_refresh_token()
    assert hash_refresh_token(t) == hash_refresh_token(t)
    assert len(hash_refresh_token(t)) == 64
    assert generate_refresh_token() != t


def test_hermes_key_is_64_hex():
    key = generate_hermes_key()
    assert len(key) == 64
    int(key, 16)  # raises if not hex