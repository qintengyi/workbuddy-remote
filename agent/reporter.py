"""WebSocket 客户端：连接服务端，上行状态/事件，下行命令分发。"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import socket
import time
from typing import Any, Optional

from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType

logger = logging.getLogger(__name__)

try:
    from config import AGENT_VERSION
except Exception:
    AGENT_VERSION = "1.0.0"


class Reporter:
    """Agent ↔ Server WebSocket 桥。"""

    def __init__(
        self,
        cfg: Any,
        monitor_hub: Any,
        controller: Any,
    ) -> None:
        self.cfg = cfg
        self.hub = monitor_hub
        self.controller = controller
        self._stop = asyncio.Event()
        self._ws: Optional[ClientWebSocketResponse] = None
        self._session: Optional[ClientSession] = None
        self._send_lock = asyncio.Lock()
        self._connected = asyncio.Event()

    @property
    def online(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def send(self, msg: dict[str, Any]) -> bool:
        """发送一条 JSON 消息。"""
        ws = self._ws
        if ws is None or ws.closed:
            return False
        if "ts" not in msg:
            msg = {**msg, "ts": int(time.time())}
        raw = json.dumps(msg, ensure_ascii=False)
        async with self._send_lock:
            try:
                await ws.send_str(raw)
                return True
            except Exception as e:
                logger.warning("WS 发送失败: %s", e)
                return False

    def _hello_payload(self) -> dict[str, Any]:
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "unknown"
        return {
            "type": "hello",
            "data": {
                "agent_version": AGENT_VERSION,
                "hostname": hostname,
                "os": f"{platform.system()} {platform.release()}",
                "workbuddy_data_dir": self.cfg.workbuddy_data_dir,
                "python": platform.python_version(),
            },
            "ts": int(time.time()),
        }

    async def _status_loop(self) -> None:
        interval = float(self.cfg.status_interval)
        while not self._stop.is_set():
            if self.online:
                payload = {
                    "type": "status",
                    "data": self.hub.state.status_payload(),
                    "ts": int(time.time()),
                }
                # 兼容：顶层也带字段
                payload.update(payload["data"])
                await self.send(payload)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _event_loop(self) -> None:
        """从 monitor 事件队列取消息上行。"""
        while not self._stop.is_set():
            try:
                msg = await asyncio.wait_for(
                    self.hub.event_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.debug("读事件队列失败: %s", e)
                continue

            # 未连接时：status/screenshot 可丢，业务 event 尽量保留但队列有限
            if not self.online:
                if msg.get("type") in ("screenshot", "status"):
                    continue
                # 尝试短暂等待连接
                try:
                    await asyncio.wait_for(self._connected.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue

            ok = await self.send(msg)
            if not ok and msg.get("type") not in ("screenshot", "status"):
                logger.debug("事件发送失败 type=%s", msg.get("type"))

    async def _handle_server_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("无法解析服务端消息: %s", raw[:200])
            return

        if not isinstance(msg, dict):
            return

        cmd = msg.get("type") or ""
        logger.info("收到下行命令: %s request_id=%s", cmd, msg.get("request_id"))

        if cmd == "ping":
            await self.send(
                {
                    "type": "command_result",
                    "request_id": msg.get("request_id"),
                    "command": "ping",
                    "ok": True,
                    "data": {"ok": True, "pong": True},
                    "ts": int(time.time()),
                }
            )
            # 也回一个轻量 pong
            await self.send({"type": "pong", "ts": int(time.time())})
            return

        if cmd in (
            "send_message",
            "pause_automation",
            "resume_automation",
            "run_automation",
            "take_screenshot",
        ):
            result = await self.controller.handle_command(msg)
            await self.send(result)
            return

        # 未知：回 result
        if msg.get("request_id"):
            await self.send(
                {
                    "type": "command_result",
                    "request_id": msg.get("request_id"),
                    "command": cmd,
                    "ok": False,
                    "error": f"unknown command: {cmd}",
                    "data": {"ok": False, "error": f"unknown command: {cmd}"},
                    "ts": int(time.time()),
                }
            )
        else:
            logger.debug("忽略未知服务端消息: %s", cmd)

    async def _session_once(self) -> None:
        """单次连接生命周期。"""
        url = self.cfg.ws_url
        # 日志里隐藏 token
        safe_url = url.split("token=")[0] + "token=***"
        logger.info("连接服务端: %s", safe_url)

        assert self._session is not None
        async with self._session.ws_connect(
            url,
            autoclose=True,
            autoping=True,
            max_msg_size=16 * 1024 * 1024,
        ) as ws:
            self._ws = ws
            self._connected.set()
            logger.info("WebSocket 已连接")

            # hello
            await self.send(self._hello_payload())
            # 立即发一次 status
            status = {
                "type": "status",
                "data": self.hub.state.status_payload(),
                "ts": int(time.time()),
            }
            status.update(status["data"])
            await self.send(status)
            await self.send(
                {
                    "type": "log",
                    "data": {
                        "level": "info",
                        "msg": f"agent connected, version={AGENT_VERSION}",
                    },
                }
            )

            async for ws_msg in ws:
                if self._stop.is_set():
                    break
                if ws_msg.type == WSMsgType.TEXT:
                    await self._handle_server_message(ws_msg.data)
                elif ws_msg.type == WSMsgType.BINARY:
                    try:
                        await self._handle_server_message(
                            ws_msg.data.decode("utf-8")
                        )
                    except Exception:
                        pass
                elif ws_msg.type in (
                    WSMsgType.CLOSED,
                    WSMsgType.CLOSE,
                    WSMsgType.CLOSING,
                ):
                    logger.info("WebSocket 关闭: %s", ws_msg)
                    break
                elif ws_msg.type == WSMsgType.ERROR:
                    logger.warning("WebSocket 错误: %s", ws.exception())
                    break

        self._ws = None
        self._connected.clear()
        logger.info("WebSocket 会话结束")

    async def run(self) -> None:
        """主循环：指数退避重连。"""
        backoff = 1.0
        max_backoff = 60.0

        from aiohttp import ClientTimeout

        self._session = ClientSession(
            timeout=ClientTimeout(total=None, sock_connect=30, sock_read=None),
        )

        # 并行：状态周期 + 事件转发
        status_task = asyncio.create_task(
            self._status_loop(), name="status_loop"
        )
        event_task = asyncio.create_task(
            self._event_loop(), name="event_loop"
        )

        try:
            while not self._stop.is_set():
                try:
                    await self._session_once()
                    backoff = 1.0  # 成功连过，重置
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("连接失败: %s", e)

                if self._stop.is_set():
                    break

                logger.info("%.0f 秒后重连…", backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(max_backoff, backoff * 2)
        finally:
            status_task.cancel()
            event_task.cancel()
            await asyncio.gather(status_task, event_task, return_exceptions=True)
            if self._session is not None:
                await self._session.close()
                self._session = None
            logger.info("Reporter 已停止")

    def stop(self) -> None:
        self._stop.set()
        self._connected.set()  # 解除等待
