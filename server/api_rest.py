"""REST API 路由：严格按 API_SPEC.md 第3节。"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from aiohttp import web

import auth
import broker
import storage
from config import SCREENSHOT_PATH

logger = logging.getLogger(__name__)


def _ok(data: Any = None, msg: str = "success") -> web.Response:
    return web.json_response({"code": 200, "msg": msg, "data": data})


def _err(code: int, msg: str, data: Any = None) -> web.Response:
    return web.json_response({"code": code, "msg": msg, "data": data}, status=200)


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """除 login 外，所有 /api/* 需要 Bearer token。"""
    path = request.path
    if path == "/api/auth/login" or not path.startswith("/api/"):
        return await handler(request)

    token = auth.extract_bearer(request.headers.get("Authorization"))
    if not token:
        # 也允许 ?token=
        token = request.rel_url.query.get("token")
    payload = auth.verify_token(token) if token else None
    if not payload:
        return _err(401, "unauthorized")
    request["user"] = payload
    return await handler(request)


# ─── auth ───


async def login(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _err(400, "invalid json body")
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return _err(400, "username and password required")
    result = auth.login(username, password)
    if not result:
        return _err(401, "invalid username or password")
    return _ok(result)


# ─── status ───


async def get_status(request: web.Request) -> web.Response:
    return _ok(broker.get_status_payload())


# ─── conversations / messages ───


async def list_conversations(request: web.Request) -> web.Response:
    try:
        limit = int(request.rel_url.query.get("limit", "20"))
        offset = int(request.rel_url.query.get("offset", "0"))
    except ValueError:
        return _err(400, "invalid limit/offset")
    items = storage.list_conversations(limit=limit, offset=offset)
    return _ok(items)


async def list_messages(request: web.Request) -> web.Response:
    conv_id = request.match_info.get("id") or ""
    if not conv_id:
        return _err(400, "conversation id required")
    try:
        limit = int(request.rel_url.query.get("limit", "50"))
    except ValueError:
        return _err(400, "invalid limit")
    before_raw = request.rel_url.query.get("before")
    before: Optional[int] = None
    if before_raw:
        try:
            before = int(before_raw)
        except ValueError:
            return _err(400, "invalid before")
    items = storage.list_messages(conv_id, limit=limit, before=before)
    return _ok(items)


async def post_message(request: web.Request) -> web.Response:
    """向当前活动会话发送消息，转发给 agent。"""
    if not broker.is_agent_online():
        return _err(503, "agent offline")
    try:
        body = await request.json()
    except Exception:
        return _err(400, "invalid json body")
    content = body.get("content")
    if not content or not isinstance(content, str):
        return _err(400, "content required")
    conversation_id = body.get("conversation_id")  # null = 当前活动会话

    try:
        result = await broker.send_command(
            "send_message",
            {"content": content, "conversation_id": conversation_id},
            wait=False,
        )
        # 本地也记一条 user 消息（若有 conversation_id）
        if conversation_id:
            storage.insert_message(str(conversation_id), "user", content, int(time.time()))
        return _ok({"ok": True, "queued": True, **{k: v for k, v in result.items() if k != "ok"}})
    except broker.AgentOfflineError:
        return _err(503, "agent offline")
    except Exception as e:
        logger.exception("post_message 失败")
        return _err(500, str(e))


# ─── automations ───


async def list_automations(request: web.Request) -> web.Response:
    items = storage.list_automations()
    return _ok(items)


async def pause_automation(request: web.Request) -> web.Response:
    return await _automation_action(request, "pause_automation", "PAUSED")


async def resume_automation(request: web.Request) -> web.Response:
    return await _automation_action(request, "resume_automation", "ACTIVE")


async def run_automation(request: web.Request) -> web.Response:
    return await _automation_action(request, "run_automation", None)


async def _automation_action(
    request: web.Request,
    cmd_type: str,
    local_status: Optional[str],
) -> web.Response:
    if not broker.is_agent_online():
        return _err(503, "agent offline")
    auto_id = request.match_info.get("id") or ""
    if not auto_id:
        return _err(400, "automation id required")
    try:
        result = await broker.send_command(cmd_type, {"id": auto_id}, wait=False)
        if local_status:
            storage.update_automation_status(auto_id, local_status)
            # 若不存在则创建占位
            if not storage.get_automation(auto_id):
                storage.upsert_automation(auto_id, status=local_status)
        if cmd_type == "run_automation":
            storage.insert_automation_run(auto_id, status="pending", started_at=int(time.time()))
        return _ok({"ok": True, "queued": True, "id": auto_id, **result})
    except broker.AgentOfflineError:
        return _err(503, "agent offline")
    except Exception as e:
        logger.exception("%s 失败", cmd_type)
        return _err(500, str(e))


async def list_automation_runs(request: web.Request) -> web.Response:
    auto_id = request.match_info.get("id") or ""
    if not auto_id:
        return _err(400, "automation id required")
    try:
        limit = int(request.rel_url.query.get("limit", "20"))
    except ValueError:
        return _err(400, "invalid limit")
    items = storage.list_automation_runs(auto_id, limit=limit)
    return _ok(items)


# ─── tasks ───


async def list_tasks(request: web.Request) -> web.Response:
    team = request.rel_url.query.get("team") or None
    items = storage.list_tasks(team=team)
    return _ok(items)


# ─── screenshot ───


async def get_screenshot(request: web.Request) -> web.Response:
    row = storage.get_agent_status_row()
    taken_at = row.get("screenshot_updated_at")
    if not SCREENSHOT_PATH.exists():
        return _ok({"url": None, "taken_at": taken_at})
    return _ok(
        {
            "url": "/files/screenshot_latest.jpg",
            "taken_at": taken_at,
        }
    )


# ─── events ───


async def list_events(request: web.Request) -> web.Response:
    try:
        limit = int(request.rel_url.query.get("limit", "100"))
    except ValueError:
        return _err(400, "invalid limit")
    since_raw = request.rel_url.query.get("since")
    since: Optional[int] = None
    if since_raw:
        try:
            since = int(since_raw)
        except ValueError:
            return _err(400, "invalid since")
    items = storage.list_events(limit=limit, since=since)
    return _ok(items)


# ─── 注册路由 ───


def setup_routes(app: web.Application) -> None:
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/api/status", get_status)
    app.router.add_get("/api/conversations", list_conversations)
    app.router.add_get("/api/conversations/{id}/messages", list_messages)
    app.router.add_post("/api/messages", post_message)
    app.router.add_get("/api/automations", list_automations)
    app.router.add_post("/api/automations/{id}/pause", pause_automation)
    app.router.add_post("/api/automations/{id}/resume", resume_automation)
    app.router.add_post("/api/automations/{id}/run", run_automation)
    app.router.add_get("/api/automations/{id}/runs", list_automation_runs)
    app.router.add_get("/api/tasks", list_tasks)
    app.router.add_get("/api/screenshot", get_screenshot)
    app.router.add_get("/api/events", list_events)
