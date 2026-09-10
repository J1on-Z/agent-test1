"""安全模块单元测试：bcrypt 哈希、JWT 签发/校验/类型隔离、密码强度。"""
import time

import jwt as pyjwt
import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_strength,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("secret1234")
        assert hashed != "secret1234"
        assert verify_password("secret1234", hashed)
        assert not verify_password("wrong1234", hashed)

    def test_wrong_hash_format_returns_false(self):
        assert not verify_password("secret1234", "not-a-bcrypt-hash")

    def test_strength_rules(self):
        assert validate_password_strength("abc12345") is None
        assert validate_password_strength("short1") is not None  # 太短
        assert validate_password_strength("abcdefgh") is not None  # 无数字
        assert validate_password_strength("12345678") is not None  # 无字母


class TestJWT:
    def test_access_token_roundtrip(self):
        token = create_access_token(1, "alice", "user")
        payload = decode_token(token, "access")
        assert payload["sub"] == "1"
        assert payload["username"] == "alice"
        assert payload["role"] == "user"

    def test_type_mismatch_rejected(self):
        access = create_access_token(1, "alice", "user")
        with pytest.raises(pyjwt.PyJWTError):
            decode_token(access, "refresh")  # access 不能当 refresh 用

    def test_tampered_token_rejected(self):
        token = create_access_token(1, "alice", "user")
        tampered = token[:-4] + "AAAA"
        with pytest.raises(pyjwt.PyJWTError):
            decode_token(tampered, "access")

    def test_expired_token_rejected(self, monkeypatch):
        # 把过期时间改为过去，验证过期校验
        import datetime as dt

        from app.core import security

        class FakeNow:
            pass

        # 直接构造过期 token 验证解码失败
        payload = {
            "sub": "1",
            "type": "access",
            "iat": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2),
            "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1),
        }
        token = pyjwt.encode(payload, security.settings.secret_key, algorithm="HS256")
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_token(token, "access")

    def test_refresh_token_has_jti(self):
        token, jti, expires_at = create_refresh_token(1)
        payload = decode_token(token, "refresh")
        assert payload["jti"] == jti
        assert expires_at is not None
