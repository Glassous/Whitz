from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger("whitz.cos")


class CosError(Exception):
    def __init__(self, detail: str, status_code: int = 502) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class CosCredentials:
    secret_id: str
    secret_key: str
    session_token: str | None = None


def _rfc3986_quote(value: str, safe: str = "") -> str:
    return quote(str(value), safe=safe)


def _cos_host(settings: Settings) -> str:
    custom = settings.cos_public_host.strip()
    if custom:
        return custom.removeprefix("https://").removeprefix("http://").rstrip("/")
    return f"{settings.cos_bucket.strip()}.cos.{settings.cos_region.strip()}.myqcloud.com"


def _cos_origin(settings: Settings) -> str:
    custom = settings.cos_public_host.strip()
    if custom.startswith("http://") or custom.startswith("https://"):
        return custom.rstrip("/")
    return f"https://{_cos_host(settings)}"


def build_storage_key(
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    file_id: uuid.UUID,
    filename: str,
    settings: Settings | None = None,
) -> str:
    s = settings or get_settings()
    prefix = s.cos_key_prefix.strip().strip("/") or "whitz/uploads"
    scope = str(conversation_id) if conversation_id is not None else "global"
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"{prefix}/{user_id}/{scope}/{file_id}/{safe_name}"


def _encode_uri_path(key: str) -> str:
    parts = [quote(seg, safe="") for seg in key.lstrip("/").split("/")]
    return "/" + "/".join(parts)


def sign_v5(
    *,
    method: str,
    key: str,
    secret_id: str,
    secret_key: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    start_ts: int | None = None,
    expires_seconds: int = 600,
) -> tuple[str, str]:
    """Compute Tencent COS V5 authorization string and return ``(authorization, key_time)``."""
    now = int(time.time()) if start_ts is None else int(start_ts)
    end_ts = now + max(1, int(expires_seconds))
    sign_time = f"{now};{end_ts}"

    norm_headers: dict[str, str] = {}
    for k, v in (headers or {}).items():
        lk = k.strip().lower()
        if lk:
            norm_headers[lk] = str(v).strip()
    header_keys = sorted(norm_headers.keys())
    header_list = ";".join(header_keys)
    canonical_headers = "&".join(f"{k}={_rfc3986_quote(norm_headers[k])}" for k in header_keys)

    norm_params: dict[str, str] = {}
    for k, v in (params or {}).items():
        lk = _rfc3986_quote(k.strip()).lower()
        if lk:
            norm_params[lk] = str(v)
    param_keys = sorted(norm_params.keys())
    param_list = ";".join(param_keys)
    canonical_params = "&".join(f"{k}={_rfc3986_quote(norm_params[k])}" for k in param_keys)

    uri_path = "/" + key.lstrip("/") if key else "/"
    http_string = f"{method.lower()}\n{uri_path}\n{canonical_params}\n{canonical_headers}\n"
    http_sha1 = hashlib.sha1(http_string.encode("utf-8")).hexdigest()
    string_to_sign = f"sha1\n{sign_time}\n{http_sha1}\n"

    sign_key = hmac.new(secret_key.encode("utf-8"), sign_time.encode("utf-8"), hashlib.sha1).hexdigest()
    signature = hmac.new(sign_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest()

    auth = (
        f"q-sign-algorithm=sha1"
        f"&q-ak={_rfc3986_quote(secret_id)}"
        f"&q-sign-time={sign_time}"
        f"&q-key-time={sign_time}"
        f"&q-header-list={header_list}"
        f"&q-url-param-list={param_list}"
        f"&q-signature={signature}"
    )
    return auth, sign_time


def _tc3_signature(
    secret_id: str,
    secret_key: str,
    service: str,
    host: str,
    action: str,
    version: str,
    region: str,
    payload: str,
    timestamp: int,
) -> dict[str, str]:
    from datetime import datetime, timezone

    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_payload}"

    credential_scope = f"{date}/{service}/tc3_request"
    hashed_req = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n{hashed_req}"

    def _hmac(key_bytes: bytes, msg: str) -> bytes:
        return hmac.new(key_bytes, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac(secret_date, service)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    auth = (
        f"TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
    }
    if region:
        headers["X-TC-Region"] = region
    return headers


async def fetch_sts_credentials(
    key_prefix: str,
    settings: Settings | None = None,
    *,
    allow_actions: list[str] | None = None,
) -> CosCredentials:
    s = settings or get_settings()
    bucket = s.cos_bucket.strip()
    region = s.cos_region.strip()
    appid = bucket.rsplit("-", 1)[-1] if "-" in bucket else "*"
    prefix = key_prefix.lstrip("/")
    resource = f"qcs::cos:{region}:uid/{appid}:{bucket}/{prefix}"
    actions = allow_actions or [
        "name/cos:PutObject",
        "name/cos:GetObject",
        "name/cos:HeadObject",
    ]
    policy = json.dumps(
        {
            "version": "2.0",
            "statement": [
                {
                    "effect": "allow",
                    "action": actions,
                    "resource": [resource],
                }
            ],
        },
        separators=(",", ":"),
    )
    body = json.dumps(
        {
            "Name": "whitz-upload",
            "Policy": policy,
            "DurationSeconds": max(900, min(7200, int(s.cos_sts_duration_seconds))),
        },
        separators=(",", ":"),
    )
    host = "sts.tencentcloudapi.com"
    ts = int(time.time())
    headers = _tc3_signature(
        s.cos_secret_id.strip(),
        s.cos_secret_key.strip(),
        "sts",
        host,
        "GetFederationToken",
        "2018-08-13",
        region,
        body,
        ts,
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), trust_env=False) as client:
        resp = await client.post(f"https://{host}/", headers=headers, content=body)
    if resp.status_code >= 400:
        raise CosError(f"STS 请求失败 ({resp.status_code})", status_code=502)
    data = resp.json().get("Response") or {}
    if "Error" in data:
        err = data["Error"]
        raise CosError(f"STS 错误: {err.get('Message') or err.get('Code')}", status_code=502)
    creds = data.get("Credentials") or {}
    if not creds.get("TmpSecretId") or not creds.get("TmpSecretKey"):
        raise CosError("STS 返回凭证不完整", status_code=502)
    return CosCredentials(
        secret_id=creds["TmpSecretId"],
        secret_key=creds["TmpSecretKey"],
        session_token=creds.get("Token"),
    )


async def _upload_credentials(key: str, settings: Settings) -> CosCredentials:
    if settings.cos_use_sts:
        return await fetch_sts_credentials(key, settings, allow_actions=["name/cos:PutObject"])
    return CosCredentials(
        secret_id=settings.cos_secret_id.strip(),
        secret_key=settings.cos_secret_key.strip(),
    )


def _master_credentials(settings: Settings) -> CosCredentials:
    return CosCredentials(
        secret_id=settings.cos_secret_id.strip(),
        secret_key=settings.cos_secret_key.strip(),
    )


def _require_cos(settings: Settings | None = None) -> Settings:
    s = settings or get_settings()
    if not s.cos_configured:
        raise CosError("对象存储 COS 尚未配置", status_code=503)
    return s


async def presign_put(
    *,
    key: str,
    content_type: str,
    content_length: int,
    expires_seconds: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    s = _require_cos(settings)
    ttl = int(expires_seconds or s.cos_upload_expires_seconds or 600)
    creds = await _upload_credentials(key, s)
    host = _cos_host(s)
    signed_headers: dict[str, str] = {
        "host": host,
        "content-type": content_type,
        "content-length": str(content_length),
    }
    client_headers: dict[str, str] = {
        "Content-Type": content_type,
    }
    if creds.session_token:
        signed_headers["x-cos-security-token"] = creds.session_token
        client_headers["x-cos-security-token"] = creds.session_token

    auth, _ = sign_v5(
        method="PUT",
        key=key,
        secret_id=creds.secret_id,
        secret_key=creds.secret_key,
        headers=signed_headers,
        expires_seconds=ttl,
    )
    url = f"{_cos_origin(s)}{_encode_uri_path(key)}?{auth}"
    return {
        "url": url,
        "method": "PUT",
        "headers": client_headers,
        "expires_in": ttl,
    }


def _parse_query_params(raw_query: str) -> dict[str, str]:
    cleaned = raw_query.strip().lstrip("?&")
    if not cleaned:
        return {}
    parsed: dict[str, str] = {}
    for part in cleaned.split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            k_clean = unquote(k.strip())
            if k_clean:
                parsed[k_clean] = unquote(v)
        else:
            k_clean = unquote(part.strip())
            if k_clean:
                parsed[k_clean] = ""
    return parsed


def presign_get(
    *,
    key: str,
    filename: str | None = None,
    inline: bool = False,
    include_disposition: bool = True,
    expires_seconds: int | None = None,
    extra_params: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> str:
    s = _require_cos(settings)
    ttl = int(expires_seconds or s.cos_download_expires_seconds or 300)
    creds = _master_credentials(s)
    host = _cos_host(s)
    params: dict[str, str] = {}
    if filename and include_disposition:
        disp = "inline" if inline else "attachment"
        encoded = quote(filename, safe="")
        params["response-content-disposition"] = f"{disp}; filename*=UTF-8''{encoded}"
    if extra_params:
        for k, v in extra_params.items():
            cleaned_k = k.strip()
            if cleaned_k:
                params[cleaned_k] = str(v)

    auth, _ = sign_v5(
        method="GET",
        key=key,
        secret_id=creds.secret_id,
        secret_key=creds.secret_key,
        headers={"host": host},
        params=params,
        expires_seconds=ttl,
    )
    query_parts: list[str] = []
    for k, v in sorted(params.items()):
        if v == "":
            query_parts.append(_rfc3986_quote(k, safe="/-_.~!"))
        else:
            query_parts.append(f"{_rfc3986_quote(k, safe='/-_.~')}={_rfc3986_quote(v)}")
    query_parts.append(auth)
    return f"{_cos_origin(s)}{_encode_uri_path(key)}?{'&'.join(query_parts)}"


def presign_ai_media_url(
    *,
    key: str,
    size_bytes: int = 0,
    expires_seconds: int = 900,
    settings: Settings | None = None,
) -> str:
    """Sign a clean, short-lived COS GET URL for upstream LLM image fetching (zero server download, uncompressed original)."""
    s = _require_cos(settings)
    extra_params: dict[str, str] | None = None
    ai_query = (getattr(s, "cos_ai_image_query", "") or "").strip()
    max_raw_bytes = max(1, int(getattr(s, "llm_image_url_max_mb", 16) or 16)) * 1024 * 1024
    if ai_query and size_bytes > max_raw_bytes:
        extra_params = _parse_query_params(ai_query)
    return presign_get(
        key=key,
        filename=None,
        inline=True,
        include_disposition=False,
        expires_seconds=max(60, int(expires_seconds or 900)),
        extra_params=extra_params,
        settings=s,
    )


def presign_preview_urls(
    key: str,
    filename: str,
    category: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    s = _require_cos(settings)
    ttl = int(s.cos_download_expires_seconds or 300)
    preview_url = presign_get(
        key=key,
        filename=filename or None,
        inline=True,
        expires_seconds=ttl,
        settings=s,
    )
    thumb_url: str | None = None
    if category == "image":
        thumb_query = s.cos_image_thumb_query.strip()
        if thumb_query:
            thumb_params = _parse_query_params(thumb_query)
            thumb_url = presign_get(
                key=key,
                filename=filename or None,
                inline=True,
                expires_seconds=ttl,
                extra_params=thumb_params,
                settings=s,
            )
        else:
            thumb_url = preview_url
    return {
        "preview_url": preview_url,
        "thumb_url": thumb_url,
        "expires_in": ttl,
    }


async def head_object(key: str, settings: Settings | None = None) -> dict[str, Any] | None:
    s = _require_cos(settings)
    creds = _master_credentials(s)
    host = _cos_host(s)
    auth, _ = sign_v5(
        method="HEAD",
        key=key,
        secret_id=creds.secret_id,
        secret_key=creds.secret_key,
        headers={"host": host},
        expires_seconds=60,
    )
    url = f"{_cos_origin(s)}{_encode_uri_path(key)}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), trust_env=False) as client:
            resp = await client.head(url, headers={"Authorization": auth, "Host": host})
    except httpx.HTTPError as exc:
        raise CosError(f"校验 COS 文件失败: {exc}", status_code=502) from exc
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        raise CosError(f"COS HEAD 返回异常 ({resp.status_code})", status_code=502)
    length_raw = resp.headers.get("content-length")
    return {
        "content_length": int(length_raw) if length_raw and length_raw.isdigit() else None,
        "etag": (resp.headers.get("etag") or "").strip('"') or None,
        "content_type": resp.headers.get("content-type"),
    }


async def get_object_bytes(
    key: str,
    *,
    max_bytes: int,
    settings: Settings | None = None,
) -> bytes:
    s = _require_cos(settings)
    creds = _master_credentials(s)
    host = _cos_host(s)
    auth, _ = sign_v5(
        method="GET",
        key=key,
        secret_id=creds.secret_id,
        secret_key=creds.secret_key,
        headers={"host": host},
        expires_seconds=120,
    )
    url = f"{_cos_origin(s)}{_encode_uri_path(key)}"
    buf = bytearray()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as client:
            async with client.stream("GET", url, headers={"Authorization": auth, "Host": host}) as resp:
                if resp.status_code == 404:
                    raise CosError("文件在对象存储中不存在", status_code=404)
                if resp.status_code >= 400:
                    raise CosError(f"读取 COS 文件失败 ({resp.status_code})", status_code=502)
                async for chunk in resp.aiter_bytes(65536):
                    if len(buf) + len(chunk) > max_bytes:
                        raise CosError("文件内容过大，超出服务端解析内存限制", status_code=413)
                    buf.extend(chunk)
    except httpx.HTTPError as exc:
        raise CosError(f"下载 COS 文件失败: {exc}", status_code=502) from exc
    return bytes(buf)


async def get_object_head_bytes(
    key: str,
    *,
    num_bytes: int = 32,
    settings: Settings | None = None,
) -> bytes | None:
    """Read only the first ``num_bytes`` via HTTP Range for zero-cost magic-byte verification."""
    s = _require_cos(settings)
    creds = _master_credentials(s)
    host = _cos_host(s)
    end_byte = max(0, int(num_bytes) - 1)
    auth, _ = sign_v5(
        method="GET",
        key=key,
        secret_id=creds.secret_id,
        secret_key=creds.secret_key,
        headers={"host": host},
        expires_seconds=60,
    )
    url = f"{_cos_origin(s)}{_encode_uri_path(key)}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), trust_env=False) as client:
            resp = await client.get(
                url,
                headers={"Authorization": auth, "Host": host, "Range": f"bytes=0-{end_byte}"},
            )
        if resp.status_code in (200, 206):
            return resp.content[:num_bytes]
        return None
    except httpx.HTTPError:
        return None


async def put_object_bytes(
    key: str,
    data: bytes,
    content_type: str,
    settings: Settings | None = None,
) -> str | None:
    s = _require_cos(settings)
    creds = _master_credentials(s)
    host = _cos_host(s)
    mime = (content_type or "application/octet-stream").strip()
    auth, _ = sign_v5(
        method="PUT",
        key=key,
        secret_id=creds.secret_id,
        secret_key=creds.secret_key,
        headers={
            "host": host,
            "content-type": mime,
            "content-length": str(len(data)),
        },
        expires_seconds=120,
    )
    url = f"{_cos_origin(s)}{_encode_uri_path(key)}"
    headers = {
        "Authorization": auth,
        "Host": host,
        "Content-Type": mime,
        "Content-Length": str(len(data)),
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as client:
            resp = await client.put(url, content=data, headers=headers)
    except httpx.HTTPError as exc:
        raise CosError(f"上传 COS 文件失败: {exc}", status_code=502) from exc
    if resp.status_code >= 400:
        raise CosError(f"写入 COS 文件失败 ({resp.status_code})", status_code=502)
    return (resp.headers.get("etag") or "").strip('"') or None


async def delete_object(key: str, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    if not s.cos_configured or not key:
        return
    creds = _master_credentials(s)
    host = _cos_host(s)
    auth, _ = sign_v5(
        method="DELETE",
        key=key,
        secret_id=creds.secret_id,
        secret_key=creds.secret_key,
        headers={"host": host},
        expires_seconds=60,
    )
    url = f"{_cos_origin(s)}{_encode_uri_path(key)}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), trust_env=False) as client:
            resp = await client.delete(url, headers={"Authorization": auth, "Host": host})
        if resp.status_code not in (200, 204, 404):
            logger.warning("COS delete_object %s returned %s", key, resp.status_code)
    except httpx.HTTPError as exc:
        logger.warning("COS delete_object %s failed: %s", key, exc)


async def delete_objects(keys: list[str], settings: Settings | None = None) -> None:
    for key in keys:
        await delete_object(key, settings=settings)
