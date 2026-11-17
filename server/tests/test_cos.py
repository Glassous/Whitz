from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import Settings
from app.services import cos


def _cos_settings(**overrides) -> Settings:
    defaults = dict(
        cos_secret_id="AKIDtest123",
        cos_secret_key="SecretKeyTest456",
        cos_bucket="whitz-test-1250000000",
        cos_region="ap-shanghai",
        cos_key_prefix="whitz/uploads",
        cos_use_sts=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_sign_v5_deterministic_and_binds_headers():
    auth1, key_time1 = cos.sign_v5(
        method="PUT",
        key="whitz/uploads/u/c/f/demo.txt",
        secret_id="AKIDtest123",
        secret_key="SecretKeyTest456",
        headers={
            "host": "whitz-test-1250000000.cos.ap-shanghai.myqcloud.com",
            "content-type": "text/plain",
            "content-length": "42",
        },
        start_ts=1700000000,
        expires_seconds=600,
    )
    auth2, key_time2 = cos.sign_v5(
        method="PUT",
        key="whitz/uploads/u/c/f/demo.txt",
        secret_id="AKIDtest123",
        secret_key="SecretKeyTest456",
        headers={
            "content-length": "42",
            "content-type": "text/plain",
            "host": "whitz-test-1250000000.cos.ap-shanghai.myqcloud.com",
        },
        start_ts=1700000000,
        expires_seconds=600,
    )
    assert key_time1 == "1700000000;1700000600"
    assert auth1 == auth2
    assert "q-sign-algorithm=sha1" in auth1
    assert "q-ak=AKIDtest123" in auth1
    assert "q-header-list=content-length;content-type;host" in auth1


def test_sign_v5_uses_decoded_utf8_uri_in_http_string():
    import hashlib, hmac

    key = "whitz/uploads/u/c/f/中文 报告(1).png"
    headers = {"host": "whitz-test-1250000000.cos.ap-shanghai.myqcloud.com"}
    auth, key_time = cos.sign_v5(
        method="PUT",
        key=key,
        secret_id="AKIDtest123",
        secret_key="SecretKeyTest456",
        headers=headers,
        start_ts=1700000000,
        expires_seconds=600,
    )
    http_string = (
        f"put\n/{key}\n\n"
        f"host=whitz-test-1250000000.cos.ap-shanghai.myqcloud.com\n"
    )
    http_sha1 = hashlib.sha1(http_string.encode("utf-8")).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{http_sha1}\n"
    sign_key = hmac.new(b"SecretKeyTest456", key_time.encode("utf-8"), hashlib.sha1).hexdigest()
    expected_sig = hmac.new(sign_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest()
    assert f"q-signature={expected_sig}" in auth


@pytest.mark.asyncio
async def test_presign_put_and_get_urls():
    s = _cos_settings()
    put_info = await cos.presign_put(
        key="whitz/uploads/u/c/f/中文报告.pdf",
        content_type="application/pdf",
        content_length=1024,
        settings=s,
    )
    assert put_info["method"] == "PUT"
    assert put_info["headers"] == {"Content-Type": "application/pdf"}
    parsed = urlsplit(put_info["url"])
    assert parsed.scheme == "https"
    assert parsed.netloc == "whitz-test-1250000000.cos.ap-shanghai.myqcloud.com"
    qs = parse_qs(parsed.query)
    assert qs["q-sign-algorithm"] == ["sha1"]
    assert qs["q-header-list"] == ["content-length;content-type;host"]

    get_url = cos.presign_get(
        key="whitz/uploads/u/c/f/中文报告.pdf",
        filename="中文报告.pdf",
        inline=False,
        settings=s,
    )
    get_qs = parse_qs(urlsplit(get_url).query)
    assert "response-content-disposition" in get_qs
    assert "q-url-param-list" in get_qs
    assert "response-content-disposition" in get_qs["q-url-param-list"][0]


@pytest.mark.asyncio
async def test_presign_put_with_sts_uses_security_token(monkeypatch):
    s = _cos_settings(cos_use_sts=True)

    async def _fake_sts(key_prefix, settings=None, *, allow_actions=None):
        return cos.CosCredentials(
            secret_id="TMP_ID",
            secret_key="TMP_KEY",
            session_token="STS_TOKEN_XYZ",
        )

    monkeypatch.setattr(cos, "fetch_sts_credentials", _fake_sts)
    put_info = await cos.presign_put(
        key="whitz/uploads/u/c/f/data.csv",
        content_type="text/csv",
        content_length=512,
        settings=s,
    )
    assert put_info["headers"]["x-cos-security-token"] == "STS_TOKEN_XYZ"
    qs = parse_qs(urlsplit(put_info["url"]).query)
    assert qs["q-ak"] == ["TMP_ID"]
    assert "x-cos-security-token" in qs["q-header-list"][0]
