"""Agent 配置加载。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AGENT_VERSION = "1.0.0"

# 默认配置文件位置：与本模块同目录下的 config.json
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


@dataclass
class Config:
    server_url: str = "ws://192.168.1.8:10372"
    agent_token: str = ""
    workbuddy_data_dir: str = r"C:\Users\Administrator\.workbuddy"
    screenshot_interval: float = 15.0
    status_interval: float = 5.0
    db_poll_interval: float = 5.0
    process_poll_interval: float = 5.0
    system_poll_interval: float = 5.0
    file_debounce_ms: int = 500
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return Path(self.workbuddy_data_dir) / "workbuddy.db"

    @property
    def teams_dir(self) -> Path:
        return Path(self.workbuddy_data_dir) / "teams"

    @property
    def tasks_dir(self) -> Path:
        return Path(self.workbuddy_data_dir) / "tasks"

    @property
    def memory_dir(self) -> Path:
        return Path(self.workbuddy_data_dir) / "memory"

    @property
    def ws_url(self) -> str:
        """拼接带 token 的 WebSocket 地址。"""
        base = self.server_url.rstrip("/")
        # 允许 server_url 已经是完整 /ws/agent 或仅 host
        if base.endswith("/ws/agent"):
            url = base
        else:
            url = f"{base}/ws/agent"
        if "://" not in url:
            url = f"ws://{url}"
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}token={self.agent_token}"


def load_config(path: str | Path | None = None) -> Config:
    """从 JSON 文件加载配置。路径可通过参数或环境变量 AGENT_CONFIG 指定。"""
    cfg_path = Path(path or os.environ.get("AGENT_CONFIG") or _DEFAULT_CONFIG_PATH)
    data: dict[str, Any] = {}
    if cfg_path.is_file():
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("已加载配置: %s", cfg_path)
    else:
        logger.warning("配置文件不存在: %s，使用默认值", cfg_path)

    known = {
        "server_url",
        "agent_token",
        "workbuddy_data_dir",
        "screenshot_interval",
        "status_interval",
        "db_poll_interval",
        "process_poll_interval",
        "system_poll_interval",
        "file_debounce_ms",
    }
    kwargs: dict[str, Any] = {k: data[k] for k in known if k in data}
    extra = {k: v for k, v in data.items() if k not in known}
    cfg = Config(**kwargs, extra=extra)

    if not cfg.agent_token:
        logger.warning("agent_token 为空，连接服务端会被拒绝")

    # 统一路径分隔符
    cfg.workbuddy_data_dir = str(Path(cfg.workbuddy_data_dir))
    return cfg
