"""安全模块：bcrypt 密码哈希 + JWT 签发/解码。

- access token（30 分钟）：每次 API 请求携带
- refresh token（7 天）：带 jti 落库，换新时旋转吊销旧 jti；改密时全部吊销
"""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt as pyjwt

from app.config import settings

ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(
        plain.encode("utf-8"), bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    ).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def validate_password_strength(plain: str) -> str | None:
    """密码强度规则：至少 8 位且同时包含字母与数字。返回 None 表示通过。"""
    if len(plain) < 8:
        return "密码长度至少 8 位"
    if not any(c.isalpha() for c in plain) or not any(c.isdigit() for c in plain):
        return "密码必须同时包含字母和数字"
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: int, username: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "iat": _now(),
        "exp": _now() + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return pyjwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """返回 (token, jti, expires_at)。jti 落库用于吊销。"""
    jti = uuid.uuid4().hex
    expires_at = _now() + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": jti,
        "iat": _now(),
        "exp": expires_at,
    }
    token = pyjwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    return token, jti, expires_at


def decode_token(token: str, expected_type: str) -> dict:
    """解码并校验 JWT；类型不符或签名/过期错误抛 pyjwt.PyJWTError。"""
    payload = pyjwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    if payload.get("type") != expected_type:
        raise pyjwt.InvalidTokenError("token 类型不匹配")
    return payload
