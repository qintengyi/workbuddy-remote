"""认证：用户登录、Bearer token 校验、Agent token 校验。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional

import bcrypt

from config import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USER,
    TOKEN_TTL_SECONDS,
    get_agent_token,
    get_secret_key,
)
from storage import ensure_admin, get_user_by_username

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def ensure_default_admin() -> None:
    """首次启动创建 admin / qty8520123。"""
    ensure_admin(DEFAULT_ADMIN_USER, hash_password(DEFAULT_ADMIN_PASSWORD))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def create_token(username: str, ttl: int = TOKEN_TTL_SECONDS) -> tuple[str, int]:
    """生成 HMAC-SHA256 签名的 JWT-like token。

    格式：base64url(payload).base64url(signature)
    payload: {"username": ..., "exp": ...}
    返回 (token, expires_at)
    """
    exp = int(time.time()) + ttl
    payload = {"username": username, "exp": exp}
    payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    sig = hmac.new(
        get_secret_key().encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    token = f"{payload_b64}.{_b64url_encode(sig)}"
    return token, exp


def verify_token(token: str) -> Optional[dict[str, Any]]:
    """校验用户 token，成功返回 payload，失败返回 None。"""
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.rsplit(".", 1)
        expected = hmac.new(
            get_secret_key().encode("utf-8"),
            payload_b64.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        if not payload.get("username"):
            return None
        return payload
    except Exception as e:
        logger.debug("token 校验失败: %s", e)
        return None


def login(username: str, password: str) -> Optional[dict[str, Any]]:
    """登录成功返回 {token, expires_at}，失败返回 None。"""
    user = get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    token, exp = create_token(username)
    return {"token": token, "expires_at": exp}


def verify_agent_token(token: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(token, get_agent_token())


def extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    """从 Authorization header 提取 Bearer token。"""
    if not auth_header:
        return None
    parts = auth_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
