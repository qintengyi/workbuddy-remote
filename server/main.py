"""WorkBuddy Remote Server 入口。

监听 0.0.0.0:10372，HTTP + WebSocket 同进程。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# 确保以本目录为工作/模块路径
BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from aiohttp import web

import api_rest
import auth
import config
import storage
import websocket

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


async def on_startup(app: web.Application) -> None:
    config.init_config()
    storage.init_db()
    auth.ensure_default_admin()
    config.print_boot_info()
    logger.info("服务启动完成")


async def on_cleanup(app: web.Application) -> None:
    logger.info("服务正在关闭…")


def create_app() -> web.Application:
    app = web.Application(middlewares=[api_rest.auth_middleware])
    api_rest.setup_routes(app)

    # WebSocket
    app.router.add_get("/ws/app", websocket.ws_app_handler)
    app.router.add_get("/ws/agent", websocket.ws_agent_handler)

    # 静态截图文件
    config.STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.router.add_static("/files/", path=str(config.STATIC_DIR), name="files")

    # 健康检查（无需认证）
    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "service": "workbuddy-remote"})

    app.router.add_get("/health", health)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    app = create_app()
    web.run_app(
        app,
        host=config.HOST,
        port=config.PORT,
        print=lambda *args: logger.info(" ".join(str(a) for a in args) if args else ""),
    )


if __name__ == "__main__":
    main()
