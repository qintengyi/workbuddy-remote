"""Agent ↔ iOS 消息中转：维护在线 agent 与 iOS 客户端集合。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional, Set

from aiohttp import web

import storage

logger = logging.getLogger(__name__)

# 当前在线 Agent 连接（单 agent 模式）
_agent_ws: Optional[web.WebSocketResponse] = None
# 所有 iOS App WebSocket 连接
_app_clients: Set[web.WebSocketResponse] = set()
# 等待 command_result 的 future：request_id -> Future
_pending_commands: dict[str, asyncio.Future] = {}
_lock = asyncio.Lock()

# 递增命令 id
_cmd_seq = 0


def is_agent_online() -> bool:
    return _agent_ws is not None and not _agent_ws.closed


def get_status_payload() -> dict[str, Any]:
    """综合状态，供 REST /api/status 与 WS status_update。"""
    row = storage.get_agent_status_row()
    return {
        "agent_online": is_agent_online(),
        "workbuddy_running": bool(row.get("workbuddy_running")),
        "workbuddy_pid": row.get("workbuddy_pid"),
        "last_activity_at": row.get("last_activity_at"),
        "active_conversation_id": row.get("active_conversation_id"),
        "active_conversation_title": row.get("active_conversation_title"),
        "cpu_percent": row.get("cpu_percent"),
        "memory_mb": row.get("memory_mb"),
        "uptime_seconds": row.get("uptime_seconds"),
        "screenshot_updated_at": row.get("screenshot_updated_at"),
    }


async def register_agent(ws: web.WebSocketResponse) -> None:
    global _agent_ws
    async with _lock:
        # 踢掉旧 agent
        old = _agent_ws
        _agent_ws = ws
    if old is not None and old is not ws and not old.closed:
        try:
            await old.close(code=4000, message=b"replaced by new agent")
        except Exception:
            pass
    logger.info("Agent 已上线")
    await broadcast_to_apps({"type": "agent_online", "data": {}, "ts": int(time.time())})
    # 同时推送最新状态
    await broadcast_to_apps(
        {"type": "status_update", "data": get_status_payload(), "ts": int(time.time())}
    )


async def unregister_agent(ws: web.WebSocketResponse) -> None:
    global _agent_ws
    async with _lock:
        if _agent_ws is ws:
            _agent_ws = None
        else:
            return
    logger.info("Agent 已离线")
    # 取消所有等待中的命令
    for rid, fut in list(_pending_commands.items()):
        if not fut.done():
            fut.set_exception(ConnectionError("agent offline"))
        _pending_commands.pop(rid, None)
    await broadcast_to_apps({"type": "agent_offline", "data": {}, "ts": int(time.time())})
    await broadcast_to_apps(
        {"type": "status_update", "data": get_status_payload(), "ts": int(time.time())}
    )


def register_app(ws: web.WebSocketResponse) -> None:
    _app_clients.add(ws)
    logger.info("iOS 客户端接入，当前 %d 个", len(_app_clients))


def unregister_app(ws: web.WebSocketResponse) -> None:
    _app_clients.discard(ws)
    logger.info("iOS 客户端断开，剩余 %d 个", len(_app_clients))


async def broadcast_to_apps(message: dict[str, Any]) -> None:
    """向所有 iOS 客户端广播 JSON 消息。"""
    if not _app_clients:
        return
    raw = json.dumps(message, ensure_ascii=False)
    dead: list[web.WebSocketResponse] = []
    for ws in list(_app_clients):
        if ws.closed:
            dead.append(ws)
            continue
        try:
            await ws.send_str(raw)
        except Exception as e:
            logger.warning("广播到 iOS 失败: %s", e)
            dead.append(ws)
    for ws in dead:
        _app_clients.discard(ws)


async def send_to_agent(message: dict[str, Any]) -> bool:
    """向 agent 发送消息，成功返回 True，离线返回 False。"""
    ws = _agent_ws
    if ws is None or ws.closed:
        return False
    try:
        await ws.send_str(json.dumps(message, ensure_ascii=False))
        return True
    except Exception as e:
        logger.warning("发送到 agent 失败: %s", e)
        return False


def _next_cmd_id() -> str:
    global _cmd_seq
    _cmd_seq += 1
    return f"cmd-{int(time.time())}-{_cmd_seq}"


async def send_command(
    cmd_type: str,
    data: Optional[dict[str, Any]] = None,
    wait: bool = False,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """向 agent 下发指令。

    wait=True 时等待 command_result，返回结果 dict；
    离线时 raise AgentOfflineError。
    """
    if not is_agent_online():
        raise AgentOfflineError("agent offline")

    request_id = _next_cmd_id()
    message = {
        "type": cmd_type,
        "request_id": request_id,
        **(data or {}),
    }
    # data 字段里可能也有内容，按协议直接展开字段
    # 若调用方把 payload 放在 data 里：send_command("send_message", {"content": "..."})
    # 最终消息: {type, request_id, content, ...}

    fut: Optional[asyncio.Future] = None
    if wait:
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        _pending_commands[request_id] = fut

    ok = await send_to_agent(message)
    if not ok:
        if fut is not None:
            _pending_commands.pop(request_id, None)
        raise AgentOfflineError("agent offline")

    if not wait or fut is None:
        return {"ok": True, "queued": True, "request_id": request_id}

    try:
        result = await asyncio.wait_for(fut, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        _pending_commands.pop(request_id, None)
        return {"ok": False, "queued": True, "request_id": request_id, "error": "timeout"}
    finally:
        _pending_commands.pop(request_id, None)


def resolve_command_result(msg: dict[str, Any]) -> None:
    """Agent 上报 command_result 时调用。"""
    request_id = msg.get("request_id")
    if not request_id:
        return
    fut = _pending_commands.get(request_id)
    if fut is not None and not fut.done():
        fut.set_result(msg)


class AgentOfflineError(Exception):
    """Agent 当前不在线。"""


# ─── 处理 Agent 上行消息 ───


async def handle_agent_message(msg: dict[str, Any]) -> None:
    """处理 agent 上行的各类消息：存库 + 广播给 iOS。"""
    msg_type = msg.get("type") or ""
    ts = int(msg.get("ts") or time.time())
    data = msg.get("data") if isinstance(msg.get("data"), dict) else None

    if msg_type == "hello":
        info = data or {k: v for k, v in msg.items() if k not in ("type", "ts")}
        storage.insert_event("hello", info, ts)
        logger.info("Agent hello: %s", info)
        await broadcast_to_apps({"type": "log", "data": {"level": "info", "msg": f"agent hello: {info}"}, "ts": ts})
        return

    if msg_type == "status":
        status_data = data or {k: v for k, v in msg.items() if k not in ("type", "ts")}
        storage.update_agent_status(status_data)
        # status 也写 events（可选，避免过于频繁；只广播）
        payload = get_status_payload()
        await broadcast_to_apps({"type": "status_update", "data": payload, "ts": ts})
        return

    if msg_type == "event":
        # event 内再带 type/data
        inner_type = (data or msg).get("event_type") or (data or {}).get("type") or msg.get("event_type") or "event"
        inner_data = (data or msg).get("data") if data else msg.get("data", msg)
        if not isinstance(inner_data, dict):
            inner_data = data or {k: v for k, v in msg.items() if k not in ("type", "ts")}
        # 规范化：很多 agent 直接 {type:"event", event_type:"new_message", data:{...}}
        if "event_type" in msg and data is None:
            inner_type = msg["event_type"]
            inner_data = msg.get("data") or {}
        await _process_business_event(inner_type, inner_data if isinstance(inner_data, dict) else {}, ts)
        return

    if msg_type in ("new_message", "automation_run", "task_update", "log"):
        event_data = data or {k: v for k, v in msg.items() if k not in ("type", "ts")}
        await _process_business_event(msg_type, event_data, ts)
        return

    if msg_type == "screenshot":
        await _handle_screenshot(msg, ts)
        return

    if msg_type == "command_result":
        resolve_command_result(msg)
        storage.insert_event("command_result", msg, ts)
        return

    if msg_type == "log":
        log_data = data or {"level": msg.get("level", "info"), "msg": msg.get("msg", "")}
        storage.insert_event("log", log_data, ts)
        await broadcast_to_apps({"type": "log", "data": log_data, "ts": ts})
        return

    # 未知类型：存库并广播
    storage.insert_event(msg_type or "unknown", data or msg, ts)
    await broadcast_to_apps({"type": msg_type or "unknown", "data": data or msg, "ts": ts})


async def _process_business_event(event_type: str, data: dict[str, Any], ts: int) -> None:
    storage.insert_event(event_type, data, ts)

    if event_type == "new_message":
        conv_id = data.get("conversation_id") or "unknown"
        role = data.get("role") or "assistant"
        content = data.get("content") or ""
        title = data.get("title") or data.get("conversation_title") or ""
        storage.upsert_conversation(conv_id, title=title, last_message_at=ts, last_activity_at=ts)
        if content:
            storage.insert_message(conv_id, role, content, ts)
        # 广播时带 preview
        preview = content[:50] if content else data.get("preview", "")
        out = {
            "conversation_id": conv_id,
            "role": role,
            "content": content,
            "preview": preview,
        }
        await broadcast_to_apps({"type": "new_message", "data": out, "ts": ts})
        return

    if event_type == "automation_run":
        auto_id = str(data.get("id") or data.get("automation_id") or "")
        name = data.get("name") or ""
        status = data.get("status") or "running"
        if auto_id:
            storage.upsert_automation(auto_id, name=name)
            storage.insert_automation_run(
                auto_id,
                status=status,
                started_at=ts,
                finished_at=ts if status in ("completed", "failed") else None,
                result=json_dumps_safe(data),
            )
            if status in ("ACTIVE", "PAUSED"):
                storage.update_automation_status(auto_id, status)
        await broadcast_to_apps({"type": "automation_run", "data": data, "ts": ts})
        return

    if event_type == "task_update":
        task_id = str(data.get("task_id") or data.get("id") or "")
        if task_id:
            storage.upsert_task(
                task_id,
                team=data.get("team") or "",
                subject=data.get("subject") or "",
                status=data.get("status") or "pending",
                owner=data.get("owner") or "",
                description=data.get("description") or "",
            )
        await broadcast_to_apps({"type": "task_update", "data": data, "ts": ts})
        return

    if event_type == "log":
        await broadcast_to_apps({"type": "log", "data": data, "ts": ts})
        return

    # 自动化列表同步等
    if event_type == "automations_sync":
        items = data.get("items") or data.get("automations") or []
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                storage.upsert_automation(
                    str(item["id"]),
                    name=item.get("name") or "",
                    status=item.get("status") or "ACTIVE",
                    last_run_at=item.get("last_run_at"),
                    next_run_at=item.get("next_run_at"),
                )
        await broadcast_to_apps({"type": "automations_sync", "data": data, "ts": ts})
        return

    if event_type == "conversations_sync":
        items = data.get("items") or data.get("conversations") or []
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                storage.upsert_conversation(
                    str(item["id"]),
                    title=item.get("title") or "",
                    last_message_at=item.get("last_message_at"),
                    last_activity_at=item.get("last_activity_at"),
                )
        return

    if event_type == "tasks_sync":
        items = data.get("items") or data.get("tasks") or []
        for item in items:
            if isinstance(item, dict) and (item.get("id") or item.get("task_id")):
                storage.upsert_task(
                    str(item.get("id") or item.get("task_id")),
                    team=item.get("team") or "",
                    subject=item.get("subject") or "",
                    status=item.get("status") or "pending",
                    owner=item.get("owner") or "",
                    description=item.get("description") or "",
                )
        return

    await broadcast_to_apps({"type": event_type, "data": data, "ts": ts})


async def _handle_screenshot(msg: dict[str, Any], ts: int) -> None:
    """保存 base64 jpg 到 static/screenshot_latest.jpg。"""
    import base64
    from config import SCREENSHOT_PATH, STATIC_DIR

    data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
    b64 = (
        msg.get("image")
        or msg.get("base64")
        or (data.get("image") if data else None)
        or (data.get("base64") if data else None)
        or msg.get("data")  # data 可能直接是 base64 字符串
    )
    if isinstance(b64, dict):
        b64 = b64.get("image") or b64.get("base64")
    if not b64 or not isinstance(b64, str):
        logger.warning("screenshot 消息缺少 base64 数据")
        return

    # 去掉 data:image/jpeg;base64, 前缀
    if "," in b64 and b64.strip().startswith("data:"):
        b64 = b64.split(",", 1)[1]

    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        logger.warning("screenshot base64 解码失败: %s", e)
        return

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_PATH.write_bytes(raw)
    storage.set_screenshot_updated_at(ts)
    storage.insert_event("screenshot", {"taken_at": ts, "size": len(raw)}, ts)
    await broadcast_to_apps({"type": "screenshot", "data": {"taken_at": ts}, "ts": ts})
    logger.info("已保存截图 %d bytes -> %s", len(raw), SCREENSHOT_PATH)


def json_dumps_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)
