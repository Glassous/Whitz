from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def build_profile_context(user) -> str | None:
    """Build sanitized profile context only when explicitly opted-in and consented."""
    if user is None:
        return None
    if not getattr(user, "profile_context_enabled", False) or not getattr(
        user, "profile_context_consented_at", None
    ):
        return None

    tz_name = (getattr(user, "timezone", None) or "").strip() or "Asia/Shanghai"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz_name = "Asia/Shanghai"
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone(timedelta(hours=8))
    local_now = datetime.now(tz).strftime("%Y-%m-%d %H:%M (%Z)")

    lines = ["【已授权的个人资料上下文（仅用于个性化沟通，禁止收集或泄露邮箱/手机号/生日等敏感信息）】"]
    display_name = (getattr(user, "display_name", None) or "").strip()
    if display_name:
        lines.append(f"- 昵称 / 称呼：{display_name}")
    preferred_language = (getattr(user, "preferred_language", None) or "").strip()
    if preferred_language:
        lines.append(f"- 偏好语言：{preferred_language}")
    lines.append(f"- 时区与当地当前时间：{tz_name}（{local_now}）")
    occupation = (getattr(user, "occupation", None) or "").strip()
    if occupation:
        lines.append(f"- 职业 / 身份：{occupation}")
    location = (getattr(user, "location", None) or "").strip()
    if location:
        lines.append(f"- 所在地：{location}")
    gender = (getattr(user, "gender", None) or "").strip()
    if gender:
        lines.append(f"- 性别：{gender}")
    bio = (getattr(user, "bio", None) or "").strip()
    if bio:
        lines.append(f"- 个人简介：{bio}")
    return "\n".join(lines)
