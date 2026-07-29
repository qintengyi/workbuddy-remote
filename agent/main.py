"""WorkBuddy Remote — 本机 Agent 入口。

启动 monitor + reporter + controller 三个协作模块：
- monitor: 进程/DB/文件/系统/截图
- reporter: WebSocket 上下行
- controller: 执行服务端命令
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from config import load_config, AGENT_VERSION
from controller import Controller
from monitor import MonitorHub
from reporter import Reporter


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # 降噪
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


async def amain(config_path: str | None, verbose: bool) -> int:
    setup_logging(verbose)
    logger = logging.getLogger("main")
    logger.info("WorkBuddy Remote Agent v%s 启动中…", AGENT_VERSION)

    cfg = load_config(config_path)
    logger.info(
        "server=%s data_dir=%s",
        cfg.server_url,
        cfg.workbuddy_data_dir,
    )

    if not cfg.agent_token or cfg.agent_token.startswith("<"):
        logger.error(
            "请先在 config.json 中配置有效的 agent_token（服务端首次启动时打印）"
        )
        return 2

    hub = MonitorHub(cfg)
    controller = Controller(db_path=cfg.db_path, monitor_hub=hub)
    reporter = Reporter(cfg=cfg, monitor_hub=hub, controller=controller)

    await hub.start()

    stop_event = asyncio.Event()

    def _request_stop(*_args):  # noqa: ANN001
        logger.info("收到停止信号")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except (NotImplementedError, RuntimeError):
            # Windows 上 add_signal_handler 有限
            signal.signal(sig, lambda s, f: _request_stop())

    reporter_task = asyncio.create_task(reporter.run(), name="reporter")

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("KeyboardInterrupt")
    finally:
        logger.info("正在关闭…")
        reporter.stop()
        await hub.stop()
        reporter_task.cancel()
        try:
            await reporter_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("Agent 已退出")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WorkBuddy Remote 本机 Agent"
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="config.json 路径（默认与 main.py 同目录）",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG 日志",
    )
    args = parser.parse_args()

    # Windows 事件循环策略
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
        except Exception:
            pass

    try:
        code = asyncio.run(amain(args.config, args.verbose))
    except KeyboardInterrupt:
        code = 0
    sys.exit(code)


if __name__ == "__main__":
    main()
