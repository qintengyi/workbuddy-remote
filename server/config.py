"""服务端配置：首次启动生成 AGENT_TOKEN 与默认账号，持久化到 config.json。"""

from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 服务端根目录（本文件所在目录）
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR
DB_PATH = DATA_DIR / "data.db"
CONFIG_PATH = DATA_DIR / "config.json"
STATIC_DIR = BASE_DIR / "static"
SCREENSHOT_PATH = STATIC_DIR / "screenshot_latest.jpg"

HOST = "0.0.0.0"
PORT = 10372

DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "qty8520123"

# token 签名密钥 & agent token
_SECRET_KEY: str = ""
_AGENT_TOKEN: str = ""

# 用户 token 有效期：7 天
TOKEN_TTL_SECONDS = 7 * 24 * 3600


def _load_or_create() -> dict[str, Any]:
    """读取或创建 config.json。"""
    global _SECRET_KEY, _AGENT_TOKEN

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        _SECRET_KEY = cfg.get("secret_key") or secrets.token_urlsafe(32)
        _AGENT_TOKEN = cfg.get("agent_token") or secrets.token_urlsafe(32)
        # 补全缺失字段
        changed = False
        if "secret_key" not in cfg:
            cfg["secret_key"] = _SECRET_KEY
            changed = True
        if "agent_token" not in cfg:
            cfg["agent_token"] = _AGENT_TOKEN
            changed = True
        if changed:
            _save(cfg)
        return cfg

    # 首次启动
    _SECRET_KEY = secrets.token_urlsafe(32)
    _AGENT_TOKEN = secrets.token_urlsafe(32)
    cfg = {
        "secret_key": _SECRET_KEY,
        "agent_token": _AGENT_TOKEN,
        "host": HOST,
        "port": PORT,
        "default_admin": DEFAULT_ADMIN_USER,
        "created_first_boot": True,
    }
    _save(cfg)
    logger.info("首次启动：已生成 config.json")
    return cfg


def _save(cfg: dict[str, Any]) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def init_config() -> dict[str, Any]:
    """初始化配置，返回 config dict。"""
    return _load_or_create()


def get_secret_key() -> str:
    if not _SECRET_KEY:
        init_config()
    return _SECRET_KEY


def get_agent_token() -> str:
    if not _AGENT_TOKEN:
        init_config()
    return _AGENT_TOKEN


def print_boot_info() -> None:
    """启动时打印关键信息。"""
    logger.info("=" * 60)
    logger.info("WorkBuddy Remote Server")
    logger.info("  listen       : %s:%s", HOST, PORT)
    logger.info("  db           : %s", DB_PATH)
    logger.info("  AGENT_TOKEN  : %s", get_agent_token())
    logger.info("  admin user   : %s", DEFAULT_ADMIN_USER)
    logger.info("  admin pass   : %s", DEFAULT_ADMIN_PASSWORD)
    logger.info("=" * 60)
    # 同时打印到 stdout，方便首次部署抓取
    print(f"[BOOT] AGENT_TOKEN={get_agent_token()}", flush=True)
    print(f"[BOOT] admin={DEFAULT_ADMIN_USER} / {DEFAULT_ADMIN_PASSWORD}", flush=True)
    print(f"[BOOT] listening on {HOST}:{PORT}", flush=True)
