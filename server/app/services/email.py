"""SMTP email delivery and Redis-backed verification codes."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from typing import Literal

from app.core.config import Settings, get_settings
from app.core.redis import get_redis

logger = logging.getLogger("whitz.email")

EmailCodePurpose = Literal["register", "login", "reset_password"]

_PURPOSE_META: dict[EmailCodePurpose, tuple[str, str, str]] = {
    "register": (
        "Whitz 注册验证码",
        "欢迎注册 Whitz",
        "你正在使用该邮箱注册 Whitz 账号，请在页面中输入以下验证码完成验证：",
    ),
    "login": (
        "Whitz 登录验证码",
        "邮箱验证码登录",
        "你正在通过邮箱验证码登录 Whitz，请在页面中输入以下验证码完成登录：",
    ),
    "reset_password": (
        "Whitz 重置密码验证码",
        "找回并重置密码",
        "你正在重置 Whitz 账号密码，请在页面中输入以下验证码完成验证：",
    ),
}


class EmailServiceError(Exception):
    """Base error for email verification operations."""


class EmailNotConfiguredError(EmailServiceError):
    """Raised when SMTP settings are incomplete."""


class EmailDeliveryError(EmailServiceError):
    """Raised when sending an email via SMTP fails."""


class EmailCooldownError(EmailServiceError):
    """Raised when requesting a verification code during cooldown."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(f"发送过于频繁，请 {self.retry_after} 秒后再试")


class InvalidEmailCodeError(EmailServiceError):
    """Raised when a verification code is missing, expired, or incorrect."""


@dataclass(frozen=True)
class EmailCodeSendResult:
    expires_in: int
    cooldown: int


def _code_key(purpose: EmailCodePurpose, email: str) -> str:
    return f"auth:email_code:{purpose}:{email}"


def _cooldown_key(purpose: EmailCodePurpose, email: str) -> str:
    return f"auth:email_code_cd:{purpose}:{email}"


def _hash_code(purpose: EmailCodePurpose, email: str, code: str) -> str:
    settings = get_settings()
    msg = f"{purpose}:{email}:{code}".encode("utf-8")
    return hmac.new(settings.jwt_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _build_verification_email(
    purpose: EmailCodePurpose, code: str, ttl_minutes: int
) -> tuple[str, str, str]:
    subject, heading, lead = _PURPOSE_META[purpose]
    text_body = (
        f"{heading}\n\n"
        f"{lead}\n\n"
        f"验证码：{code}\n\n"
        f"验证码 {ttl_minutes} 分钟内有效，请勿泄露给他人。如非本人操作，请忽略此邮件。"
    )
    html_body = f"""<!doctype html>
<html lang="zh-CN">
<body style="margin:0;padding:24px;background:#f5f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;color:#18181b;">
  <div style="max-width:480px;margin:0 auto;background:#ffffff;border:1px solid #e4e4e7;border-radius:16px;padding:28px;">
    <div style="font-size:18px;font-weight:700;letter-spacing:-0.02em;margin-bottom:8px;">Whitz</div>
    <h1 style="font-size:16px;font-weight:600;margin:0 0 12px;">{heading}</h1>
    <p style="font-size:14px;line-height:1.6;color:#52525b;margin:0 0 20px;">{lead}</p>
    <div style="background:#f4f4f5;border-radius:12px;padding:16px;text-align:center;margin-bottom:20px;">
      <span style="font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:28px;font-weight:700;letter-spacing:0.22em;color:#18181b;">{code}</span>
    </div>
    <p style="font-size:12.5px;line-height:1.6;color:#71717a;margin:0;">
      验证码有效期为 {ttl_minutes} 分钟，请勿转发或泄露给他人。如果这不是你的操作，请直接忽略本邮件。
    </p>
  </div>
</body>
</html>"""
    return subject, text_body, html_body


def _send_sync(msg: EmailMessage, from_email: str, to_email: str, settings: Settings) -> None:
    context = ssl.create_default_context()
    host = settings.smtp_host.strip()
    if settings.smtp_use_ssl:
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
            context=context,
        )
    else:
        client = smtplib.SMTP(host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)
        client.ehlo()
        if settings.smtp_use_tls:
            client.starttls(context=context)
            client.ehlo()

    try:
        username = settings.smtp_username.strip()
        if username:
            client.login(username, settings.smtp_password)
        client.send_message(msg, from_addr=from_email, to_addrs=[to_email])
    finally:
        # QQ Mail occasionally closes the connection abruptly during QUIT after accepting the message.
        try:
            client.quit()
        except smtplib.SMTPException:
            client.close()


async def send_email(to_email: str, subject: str, text_body: str, html_body: str) -> None:
    """Send an email via the configured SMTP server."""
    settings = get_settings()
    host = settings.smtp_host.strip()
    username = settings.smtp_username.strip()
    from_email = settings.smtp_from_email.strip() or username

    if not host or not from_email:
        raise EmailNotConfiguredError("邮件服务尚未配置，请联系管理员配置 SMTP 参数")
    if username and not settings.smtp_password:
        raise EmailNotConfiguredError("SMTP 授权码或密码尚未配置")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = Address(
        display_name=settings.smtp_from_name.strip() or "Whitz",
        addr_spec=from_email,
    )
    msg["To"] = to_email
    msg.set_content(text_body, subtype="plain", charset="utf-8")
    msg.add_alternative(html_body, subtype="html", charset="utf-8")

    try:
        await asyncio.to_thread(_send_sync, msg, from_email, to_email, settings)
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        logger.warning("SMTP send failed to=%s host=%s err=%s", to_email, host, exc)
        raise EmailDeliveryError("验证码发送失败，请检查邮箱地址或稍后再试") from exc


async def send_verification_code(
    purpose: EmailCodePurpose, to_email: str
) -> EmailCodeSendResult:
    """Generate, email, and store a 6-digit verification code in Redis."""
    settings = get_settings()
    redis = get_redis()
    email = to_email.strip().lower()
    cd_key = _cooldown_key(purpose, email)

    existing_cd = await redis.get(cd_key)
    if existing_cd is not None:
        try:
            retry_after = max(1, int(float(existing_cd) - time.time()))
        except (TypeError, ValueError):
            retry_after = settings.email_code_cooldown_seconds
        raise EmailCooldownError(retry_after)

    cooldown = max(1, settings.email_code_cooldown_seconds)
    cd_until = str(int(time.time()) + cooldown)
    acquired = await redis.set(cd_key, cd_until, ex=cooldown, nx=True)
    if not acquired:
        raise EmailCooldownError(cooldown)

    code = f"{secrets.randbelow(1_000_000):06d}"
    ttl = max(60, settings.email_code_ttl_seconds)
    ttl_minutes = max(1, (ttl + 59) // 60)
    subject, text_body, html_body = _build_verification_email(purpose, code, ttl_minutes)

    try:
        await send_email(email, subject, text_body, html_body)
    except Exception:
        await redis.delete(cd_key)
        raise

    payload = {
        "hash": _hash_code(purpose, email, code),
        "attempts": 0,
        "expires_at": int(time.time()) + ttl,
    }
    await redis.set(_code_key(purpose, email), json.dumps(payload), ex=ttl)
    return EmailCodeSendResult(expires_in=ttl, cooldown=cooldown)


async def verify_email_code(
    purpose: EmailCodePurpose,
    email: str,
    code: str,
    *,
    consume: bool = True,
) -> None:
    """Validate a submitted email verification code against Redis."""
    settings = get_settings()
    redis = get_redis()
    normalized_email = email.strip().lower()
    normalized_code = code.strip()
    key = _code_key(purpose, normalized_email)

    raw = await redis.get(key)
    if not raw:
        raise InvalidEmailCodeError("验证码不存在或已过期，请重新获取")

    try:
        payload = json.loads(raw)
        expected_hash = str(payload["hash"])
        attempts = int(payload.get("attempts", 0))
        expires_at = int(payload.get("expires_at", time.time() + 60))
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        await redis.delete(key)
        raise InvalidEmailCodeError("验证码无效，请重新获取")

    actual_hash = _hash_code(purpose, normalized_email, normalized_code)
    if not hmac.compare_digest(expected_hash, actual_hash):
        attempts += 1
        if attempts >= settings.email_code_max_attempts:
            await redis.delete(key)
            raise InvalidEmailCodeError("验证码错误次数过多，请重新获取")
        remaining = max(1, expires_at - int(time.time()))
        payload["attempts"] = attempts
        await redis.set(key, json.dumps(payload), ex=remaining)
        raise InvalidEmailCodeError("验证码不正确")

    if consume:
        await redis.delete(key)


async def consume_verification_code(purpose: EmailCodePurpose, email: str) -> None:
    """Remove a previously verified code after downstream work succeeds."""
    await get_redis().delete(_code_key(purpose, email.strip().lower()))
