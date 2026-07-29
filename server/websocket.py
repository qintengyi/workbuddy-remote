"""WebSocket 处理：/ws/app（iOS）与 /ws/agent（Agent）。"""

from __future__ import annotations

import json
import logging
import time

from aiohttp import WSMsgType, web

import auth
import broker

logger = logging.getLogger(__name__)


async def ws_app_handler(request: web.Request) -> web.WebSocketResponse:
    """iOS 客户端 WebSocket：?token=<user_token>。"""
    token = request.rel_url.query.get("token") or ""
    payload = auth.verify_token(token)
    if not payload:
        # 尝试从 header
        bearer = auth.extract_bearer(request.headers.get("Authorization"))
        if bearer:
            payload = auth.verify_token(bearer)
    if not payload:
        raise web.HTTPUnauthorized(text="invalid token")

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    broker.register_app(ws)
    logger.info("iOS WS 连接: user=%s", payload.get("username"))

    # 连接后立即推一次状态
    try:
        await ws.send_str(
            json.dumps(
                {
                    "type": "status_update",
                    "data": broker.get_status_payload(),
                    "ts": int(time.time()),
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await _handle_app_text(ws, msg.data)
            elif msg.type == WSMsgType.ERROR:
                logger.warning("iOS WS 错误: %s", ws.exception())
                break
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                break
    except Exception as e:
        logger.warning("iOS WS 异常: %s", e)
    finally:
        broker.unregister_app(ws)
        if not ws.closed:
            try:
                await ws.close()
            except Exception:
                pass
    return ws


async def _handle_app_text(ws: web.WebSocketResponse, raw: str) -> None:
    """处理 iOS 下行：ping / send_message 等。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        await ws.send_str(json.dumps({"type": "error", "data": {"msg": "invalid json"}, "ts": int(time.time())}))
        return

    msg_type = data.get("type") or ""
    if msg_type == "ping":
        await ws.send_str(json.dumps({"type": "pong", "ts": int(time.time())}))
        return

    # iOS 通过 WS 下发控制命令，转给 agent
    if msg_type in (
        "send_message",
        "pause_automation",
        "resume_automation",
        "run_automation",
        "take_screenshot",
    ):
        if not broker.is_agent_online():
            await ws.send_str(
                json.dumps(
                    {"type": "error", "data": {"code": 503, "msg": "agent offline"}, "ts": int(time.time())},
                    ensure_ascii=False,
                )
            )
            return
        try:
            # 直接转发（带 type 与其余字段）
            ok = await broker.send_to_agent(data)
            if not ok:
                await ws.send_str(
                    json.dumps(
                        {"type": "error", "data": {"code": 503, "msg": "agent offline"}, "ts": int(time.time())},
                        ensure_ascii=False,
                    )
                )
            else:
                await ws.send_str(
                    json.dumps(
                        {"type": "ack", "data": {"ok": True, "queued": True}, "ts": int(time.time())},
                        ensure_ascii=False,
                    )
                )
        except Exception as e:
            await ws.send_str(
                json.dumps(
                    {"type": "error", "data": {"msg": str(e)}, "ts": int(time.time())},
                    ensure_ascii=False,
                )
            )
        return

    logger.debug("iOS 未处理消息类型: %s", msg_type)


async def ws_agent_handler(request: web.Request) -> web.WebSocketResponse:
    """Agent WebSocket：?token=<AGENT_TOKEN>。"""
    token = request.rel_url.query.get("token") or ""
    if not auth.verify_agent_token(token):
        raise web.HTTPUnauthorized(text="invalid agent token")

    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=16 * 1024 * 1024)
    await ws.prepare(request)
    await broker.register_agent(ws)
    logger.info("Agent WS 连接已建立")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await _handle_agent_text(msg.data)
            elif msg.type == WSMsgType.BINARY:
                # 不期望二进制，忽略
                logger.debug("Agent 发来 binary %d bytes，忽略", len(msg.data))
            elif msg.type == WSMsgType.ERROR:
                logger.warning("Agent WS 错误: %s", ws.exception())
                break
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                break
    except Exception as e:
        logger.warning("Agent WS 异常: %s", e)
    finally:
        await broker.unregister_agent(ws)
        if not ws.closed:
            try:
                await ws.close()
            except Exception:
                pass
        logger.info("Agent WS 连接已关闭")
    return ws


async def _handle_agent_text(raw: str) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Agent 发来非法 JSON")
        return
    if not isinstance(data, dict):
        logger.warning("Agent 消息不是 object")
        return
    try:
        await broker.handle_agent_message(data)
    except Exception as e:
        logger.exception("处理 Agent 消息失败: %s", e)
