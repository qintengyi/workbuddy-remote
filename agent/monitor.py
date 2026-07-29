"""WorkBuddy 本机监听模块。

- ProcessMonitor: 进程存活
- DBMonitor: workbuddy.db 轮询（只读）
- FileMonitor: teams/tasks/memory 文件变化
- SystemMonitor: CPU / 内存
- ScreenshotMonitor: WorkBuddy 窗口截图
- MonitorHub: 统一状态快照 + 事件队列
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import psutil

logger = logging.getLogger(__name__)

# 事件回调类型: async 或 sync 均可，由 hub 放入 asyncio.Queue
EventCallback = Callable[[dict[str, Any]], None]


def _now_ts() -> int:
    return int(time.time())


def _ms_to_sec(ms: Any) -> Optional[int]:
    """WorkBuddy DB 时间戳多为毫秒，转秒；若已是秒则原样。"""
    if ms is None:
        return None
    try:
        v = int(float(ms))
    except (TypeError, ValueError):
        return None
    if v > 10_000_000_000:  # 毫秒
        return v // 1000
    return v


# ─────────────────────────────────────────────────────────────
# 共享状态
# ─────────────────────────────────────────────────────────────


@dataclass
class SharedState:
    """跨 monitor 共享的状态，供 status 上报使用。"""

    workbuddy_running: bool = False
    workbuddy_pid: Optional[int] = None
    last_activity_at: Optional[int] = None
    active_conversation_id: Optional[str] = None
    active_conversation_title: Optional[str] = None
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    agent_started_at: float = field(default_factory=time.time)
    last_screenshot_at: Optional[int] = None

    def uptime_seconds(self) -> int:
        return int(time.time() - self.agent_started_at)

    def status_payload(self) -> dict[str, Any]:
        return {
            "agent_online": True,
            "workbuddy_running": self.workbuddy_running,
            "workbuddy_pid": self.workbuddy_pid,
            "last_activity_at": self.last_activity_at,
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_mb": round(self.memory_mb, 1),
            "uptime_seconds": self.uptime_seconds(),
            "active_conversation_id": self.active_conversation_id,
            "active_conversation_title": self.active_conversation_title,
        }


# ─────────────────────────────────────────────────────────────
# ProcessMonitor
# ─────────────────────────────────────────────────────────────


class ProcessMonitor:
    """用 psutil 模糊匹配 WorkBuddy 进程。"""

    def __init__(self, state: SharedState, interval: float = 5.0) -> None:
        self.state = state
        self.interval = interval
        self._stop = asyncio.Event()

    def check_once(self) -> tuple[bool, Optional[int]]:
        """扫描进程，返回 (running, pid)。"""
        candidates: list[tuple[int, str]] = []
        try:
            for proc in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    info = proc.info
                    name = (info.get("name") or "").lower()
                    exe = (info.get("exe") or "").lower()
                    if "workbuddy" in name or "workbuddy" in exe:
                        # 排除自己/无关：只要主进程风格
                        candidates.append((info["pid"], name))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception as e:
            logger.debug("进程扫描异常: %s", e)
            return self.state.workbuddy_running, self.state.workbuddy_pid

        if not candidates:
            return False, None

        # 优先匹配 WorkBuddy.exe
        for pid, name in candidates:
            if name in ("workbuddy.exe", "workbuddy"):
                return True, pid
        return True, candidates[0][0]

    async def run(self, emit: Callable[[dict], Any]) -> None:
        logger.info("ProcessMonitor 启动，间隔 %.1fs", self.interval)
        while not self._stop.is_set():
            try:
                running, pid = await asyncio.to_thread(self.check_once)
                changed = running != self.state.workbuddy_running or pid != self.state.workbuddy_pid
                self.state.workbuddy_running = running
                self.state.workbuddy_pid = pid
                if changed:
                    logger.info(
                        "WorkBuddy 进程状态: running=%s pid=%s", running, pid
                    )
                    await _maybe_await(
                        emit(
                            {
                                "type": "event",
                                "data": {
                                    "type": "process_status",
                                    "data": {
                                        "running": running,
                                        "pid": pid,
                                    },
                                },
                            }
                        )
                    )
            except Exception as e:
                logger.exception("ProcessMonitor 错误: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()


# ─────────────────────────────────────────────────────────────
# SystemMonitor
# ─────────────────────────────────────────────────────────────


class SystemMonitor:
    def __init__(self, state: SharedState, interval: float = 5.0) -> None:
        self.state = state
        self.interval = interval
        self._stop = asyncio.Event()
        # 预热 cpu_percent
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    def sample(self) -> None:
        try:
            self.state.cpu_percent = float(psutil.cpu_percent(interval=None))
        except Exception:
            self.state.cpu_percent = 0.0

        # 优先取 WorkBuddy 进程内存，否则取系统内存占用（本 agent + 系统概览）
        mem_mb = 0.0
        try:
            if self.state.workbuddy_pid:
                try:
                    p = psutil.Process(self.state.workbuddy_pid)
                    mem_mb = p.memory_info().rss / (1024 * 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if mem_mb <= 0:
                # 累加所有 workbuddy 相关进程
                for proc in psutil.process_iter(["pid", "name", "memory_info"]):
                    try:
                        name = (proc.info.get("name") or "").lower()
                        if "workbuddy" in name:
                            mi = proc.info.get("memory_info")
                            if mi:
                                mem_mb += mi.rss / (1024 * 1024)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            if mem_mb <= 0:
                mem_mb = psutil.virtual_memory().used / (1024 * 1024)
        except Exception as e:
            logger.debug("采样内存失败: %s", e)
        self.state.memory_mb = mem_mb

    async def run(self, emit: Callable[[dict], Any]) -> None:
        logger.info("SystemMonitor 启动，间隔 %.1fs", self.interval)
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.sample)
            except Exception as e:
                logger.exception("SystemMonitor 错误: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()


# ─────────────────────────────────────────────────────────────
# DBMonitor（只读）
# ─────────────────────────────────────────────────────────────


class DBMonitor:
    """只读轮询 workbuddy.db，diff 后上报。"""

    def __init__(
        self,
        state: SharedState,
        db_path: Path,
        interval: float = 5.0,
    ) -> None:
        self.state = state
        self.db_path = Path(db_path)
        self.interval = interval
        self._stop = asyncio.Event()
        self._auto_status: dict[str, str] = {}
        self._auto_names: dict[str, str] = {}
        self._runtime_running: dict[str, int] = {}
        self._run_keys: set[str] = set()
        self._session_fingerprint: dict[str, tuple] = {}
        self._initialized = False

    def _connect_ro(self) -> sqlite3.Connection:
        # mode=ro 避免锁；immutable 不用，避免看不到 WAL 新写入
        uri = self.db_path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        # 只读查询，短超时
        try:
            conn.execute("PRAGMA query_only=ON")
        except sqlite3.Error:
            pass
        return conn

    def poll_once(self) -> list[dict[str, Any]]:
        """返回需要上报的 event 列表（业务 event 的 data 层）。"""
        events: list[dict[str, Any]] = []
        if not self.db_path.is_file():
            logger.debug("DB 不存在: %s", self.db_path)
            return events

        try:
            conn = self._connect_ro()
        except sqlite3.Error as e:
            logger.warning("打开 workbuddy.db 失败: %s", e)
            return events

        try:
            events.extend(self._poll_automations(conn))
            events.extend(self._poll_runtime(conn))
            events.extend(self._poll_runs(conn))
            self._poll_sessions(conn)
        except sqlite3.Error as e:
            logger.warning("轮询 DB 出错: %s", e)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        self._initialized = True
        return events

    def _poll_automations(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        rows = conn.execute(
            "SELECT id, name, status, last_run_at, next_run_at, updated_at "
            "FROM automations WHERE deleted_at IS NULL"
        ).fetchall()
        current: dict[str, str] = {}
        for r in rows:
            aid = r["id"]
            status = r["status"] or ""
            name = r["name"] or ""
            current[aid] = status
            self._auto_names[aid] = name
            old = self._auto_status.get(aid)
            if self._initialized and old is not None and old != status:
                events.append(
                    {
                        "type": "automation_run",
                        "data": {
                            "id": aid,
                            "automation_id": aid,
                            "name": name,
                            "status": status,
                        },
                    }
                )
                logger.info("自动化状态变化: %s %s -> %s", name, old, status)
        self._auto_status = current
        return events

    def _poll_runtime(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        try:
            rows = conn.execute(
                "SELECT automation_id, running, last_run_at, last_error, "
                "running_started_at, running_conversation_id "
                "FROM automation_runtime_state"
            ).fetchall()
        except sqlite3.Error:
            return events

        for r in rows:
            aid = r["automation_id"]
            running = int(r["running"] or 0)
            old = self._runtime_running.get(aid)
            self._runtime_running[aid] = running
            if not self._initialized or old is None or old == running:
                continue
            name = self._auto_names.get(aid, "")
            if running:
                status = "running"
            else:
                status = "failed" if r["last_error"] else "completed"
            events.append(
                {
                    "type": "automation_run",
                    "data": {
                        "id": aid,
                        "automation_id": aid,
                        "name": name,
                        "status": status,
                        "last_error": r["last_error"],
                        "running_conversation_id": r["running_conversation_id"],
                    },
                }
            )
            logger.info("自动化运行态: %s -> %s", name or aid, status)
        return events

    def _poll_runs(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        try:
            rows = conn.execute(
                "SELECT thread_id, automation_id, status, thread_title, "
                "result_success, created_at, updated_at "
                "FROM automation_runs ORDER BY updated_at DESC LIMIT 50"
            ).fetchall()
        except sqlite3.Error:
            return events

        for r in rows:
            key = f"{r['thread_id']}:{r['status']}:{r['updated_at']}"
            if key in self._run_keys:
                continue
            # 初始化阶段只记指纹，不上报历史
            if not self._initialized:
                self._run_keys.add(key)
                continue
            self._run_keys.add(key)
            # 限制集合大小
            if len(self._run_keys) > 500:
                self._run_keys = set(list(self._run_keys)[-300:])
            aid = r["automation_id"]
            name = self._auto_names.get(aid, r["thread_title"] or "")
            events.append(
                {
                    "type": "automation_run",
                    "data": {
                        "id": aid,
                        "automation_id": aid,
                        "thread_id": r["thread_id"],
                        "name": name,
                        "status": r["status"] or "unknown",
                        "result_success": r["result_success"],
                    },
                }
            )
        return events

    def _poll_sessions(self, conn: sqlite3.Connection) -> None:
        """更新 active conversation / last_activity，不直接发 new_message
        （消息体在 sessions 文件里，此处只刷新状态字段）。
        """
        try:
            row = conn.execute(
                "SELECT id, title, custom_title, status, last_activity_at, updated_at "
                "FROM sessions WHERE deleted_at IS NULL "
                "ORDER BY COALESCE(last_activity_at, updated_at) DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error as e:
            logger.debug("读 sessions 失败: %s", e)
            return
        if not row:
            return
        sid = row["id"]
        title = row["custom_title"] or row["title"] or ""
        if len(title) > 80:
            title = title[:77] + "..."
        activity = _ms_to_sec(row["last_activity_at"] or row["updated_at"])
        self.state.active_conversation_id = sid
        self.state.active_conversation_title = title
        if activity:
            # 取较大值
            if not self.state.last_activity_at or activity > self.state.last_activity_at:
                self.state.last_activity_at = activity

        fp = (row["status"], row["updated_at"], row["last_activity_at"])
        old = self._session_fingerprint.get(sid)
        self._session_fingerprint[sid] = fp
        if self._initialized and old is not None and old != fp:
            logger.debug("会话活动更新: %s %s", sid, title)

    async def run(self, emit: Callable[[dict], Any]) -> None:
        logger.info("DBMonitor 启动，间隔 %.1fs，db=%s", self.interval, self.db_path)
        while not self._stop.is_set():
            try:
                events = await asyncio.to_thread(self.poll_once)
                for ev in events:
                    await _maybe_await(
                        emit({"type": "event", "data": ev})
                    )
            except Exception as e:
                logger.exception("DBMonitor 错误: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()


# ─────────────────────────────────────────────────────────────
# FileMonitor（watchdog + debounce）
# ─────────────────────────────────────────────────────────────


class _DebouncedHandler:
    """在 watchdog 回调线程里 debounce，再通过 call_soon_threadsafe 投递。"""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        emit: Callable[[dict], Any],
        debounce_ms: int = 500,
        state: Optional[SharedState] = None,
    ) -> None:
        self.loop = loop
        self.emit = emit
        self.debounce_s = debounce_ms / 1000.0
        self.state = state
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def schedule(self, path: str, event_kind: str) -> None:
        with self._lock:
            old = self._pending.pop(path, None)
            if old is not None:
                old.cancel()
            t = threading.Timer(
                self.debounce_s, self._fire, args=(path, event_kind)
            )
            t.daemon = True
            self._pending[path] = t
            t.start()

    def _fire(self, path: str, event_kind: str) -> None:
        with self._lock:
            self._pending.pop(path, None)
        try:
            self.loop.call_soon_threadsafe(self._emit_safe, path, event_kind)
        except RuntimeError:
            pass

    def _emit_safe(self, path: str, event_kind: str) -> None:
        p = Path(path)
        payload = self._classify(p, event_kind)
        if payload is None:
            return
        if self.state is not None:
            self.state.last_activity_at = _now_ts()
        try:
            result = self.emit(payload)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result, loop=self.loop)
        except Exception as e:
            logger.debug("文件事件 emit 失败: %s", e)

    def _classify(self, path: Path, event_kind: str) -> Optional[dict[str, Any]]:
        parts = [x.lower() for x in path.parts]
        name = path.name

        # tasks/<team>/<id>.json
        if "tasks" in parts and name.endswith(".json") and name != "config.json":
            team = ""
            try:
                idx = [x.lower() for x in path.parts].index("tasks")
                if idx + 1 < len(path.parts):
                    team = path.parts[idx + 1]
            except ValueError:
                pass
            task_data: dict[str, Any] = {
                "team": team,
                "task_id": path.stem,
                "path": str(path),
                "event": event_kind,
            }
            if path.is_file():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    task_data["status"] = raw.get("status")
                    task_data["subject"] = raw.get("subject")
                    task_data["owner"] = raw.get("owner")
                    task_data["id"] = raw.get("id") or path.stem
                except Exception:
                    pass
            return {
                "type": "event",
                "data": {"type": "task_update", "data": task_data},
            }

        # teams/<name>/config.json
        if "teams" in parts:
            return {
                "type": "event",
                "data": {
                    "type": "task_update",
                    "data": {
                        "kind": "team_file",
                        "path": str(path),
                        "event": event_kind,
                        "name": name,
                    },
                },
            }

        # memory/*
        if "memory" in parts:
            return {
                "type": "log",
                "data": {
                    "level": "info",
                    "msg": f"memory file {event_kind}: {name}",
                },
            }

        return {
            "type": "log",
            "data": {
                "level": "debug",
                "msg": f"file {event_kind}: {path}",
            },
        }


class FileMonitor:
    def __init__(
        self,
        state: SharedState,
        watch_dirs: list[Path],
        debounce_ms: int = 500,
    ) -> None:
        self.state = state
        self.watch_dirs = [Path(d) for d in watch_dirs]
        self.debounce_ms = debounce_ms
        self._observer = None
        self._stop = asyncio.Event()

    async def run(self, emit: Callable[[dict], Any]) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            logger.error("watchdog 未安装，FileMonitor 禁用")
            await self._stop.wait()
            return

        loop = asyncio.get_running_loop()
        debouncer = _DebouncedHandler(
            loop, emit, debounce_ms=self.debounce_ms, state=self.state
        )

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):  # type: ignore[override]
                if getattr(event, "is_directory", False):
                    return
                src = getattr(event, "src_path", None)
                if not src:
                    return
                # 忽略临时/备份
                low = str(src).lower()
                if low.endswith((".tmp", ".swp", ".bak", "~")):
                    return
                kind = getattr(event, "event_type", "modified")
                debouncer.schedule(str(src), kind)

        observer = Observer()
        self._observer = observer
        handler = Handler()
        watched = 0
        for d in self.watch_dirs:
            if not d.exists():
                try:
                    d.mkdir(parents=True, exist_ok=True)
                    logger.info("创建监听目录: %s", d)
                except OSError as e:
                    logger.warning("无法创建监听目录 %s: %s", d, e)
                    continue
            try:
                observer.schedule(handler, str(d), recursive=True)
                watched += 1
                logger.info("监听目录: %s", d)
            except Exception as e:
                logger.warning("监听失败 %s: %s", d, e)

        if watched == 0:
            logger.warning("没有可监听目录")
            await self._stop.wait()
            return

        observer.start()
        logger.info("FileMonitor 启动，debounce=%dms", self.debounce_ms)
        try:
            await self._stop.wait()
        finally:
            observer.stop()
            observer.join(timeout=5)
            logger.info("FileMonitor 已停止")

    def stop(self) -> None:
        self._stop.set()


# ─────────────────────────────────────────────────────────────
# ScreenshotMonitor
# ─────────────────────────────────────────────────────────────


def find_workbuddy_hwnd() -> Optional[int]:
    """查找 WorkBuddy 主窗口句柄（模糊匹配标题）。"""
    try:
        import win32gui
    except ImportError:
        logger.debug("pywin32 不可用，尝试 pywinauto 找窗口")
        return _find_hwnd_pywinauto()

    result: list[int] = []

    def enum_cb(hwnd, _):  # noqa: ANN001
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            title = win32gui.GetWindowText(hwnd) or ""
        except Exception:
            return
        if "workbuddy" in title.lower():
            # 排除尺寸过小的子窗
            try:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                if (right - left) < 200 or (bottom - top) < 200:
                    return
            except Exception:
                return
            result.append(hwnd)

    try:
        win32gui.EnumWindows(enum_cb, None)
    except Exception as e:
        logger.debug("EnumWindows 失败: %s", e)
        return _find_hwnd_pywinauto()

    return result[0] if result else None


def _find_hwnd_pywinauto() -> Optional[int]:
    try:
        from pywinauto import Desktop

        desk = Desktop(backend="uia")
        for w in desk.windows():
            try:
                title = w.window_text() or ""
                if "workbuddy" in title.lower():
                    return int(w.handle)
            except Exception:
                continue
    except Exception as e:
        logger.debug("pywinauto 找窗失败: %s", e)
    return None


def capture_workbuddy_window(
    max_width: int = 1280,
    jpeg_quality: int = 70,
) -> Optional[tuple[str, int]]:
    """截取 WorkBuddy 窗口，返回 (base64_jpg, taken_at) 或 None。

    只截窗口区域，不截全屏（隐私）。
    """
    hwnd = find_workbuddy_hwnd()
    if not hwnd:
        logger.debug("未找到 WorkBuddy 窗口，跳过截图")
        return None

    try:
        from PIL import ImageGrab, Image
    except ImportError:
        logger.error("pillow 未安装，无法截图")
        return None

    # 获取窗口矩形
    try:
        import win32gui
        import win32con

        # 还原最小化
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.15)
        except Exception:
            pass
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except ImportError:
        # 无 pywin32：用 pywinauto
        try:
            from pywinauto import Application

            app = Application(backend="uia").connect(handle=hwnd)
            w = app.window(handle=hwnd)
            rect = w.rectangle()
            left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        except Exception as e:
            logger.warning("获取窗口矩形失败: %s", e)
            return None
    except Exception as e:
        logger.warning("GetWindowRect 失败: %s", e)
        return None

    width = right - left
    height = bottom - top
    if width < 50 or height < 50:
        logger.debug("窗口尺寸异常: %sx%s", width, height)
        return None

    try:
        # bbox 是屏幕坐标
        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    except TypeError:
        # 老版本 pillow 无 all_screens
        try:
            img = ImageGrab.grab(bbox=(left, top, right, bottom))
        except Exception as e:
            logger.warning("截图失败: %s", e)
            return None
    except Exception as e:
        logger.warning("截图失败: %s", e)
        return None

    try:
        # 缩放到不超过 max_width
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_size = (max_width, max(1, int(img.height * ratio)))
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS  # type: ignore[attr-defined]
            img = img.resize(new_size, resample)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        taken = _now_ts()
        logger.debug(
            "截图成功: %dx%d -> %d bytes b64", img.width, img.height, len(b64)
        )
        return b64, taken
    except Exception as e:
        logger.warning("编码截图失败: %s", e)
        return None


class ScreenshotMonitor:
    def __init__(
        self,
        state: SharedState,
        interval: float = 15.0,
    ) -> None:
        self.state = state
        self.interval = interval
        self._stop = asyncio.Event()
        self._demand = asyncio.Event()  # 按需立即截图

    def request_now(self) -> None:
        self._demand.set()

    async def capture_and_emit(
        self, emit: Callable[[dict], Any]
    ) -> Optional[dict[str, Any]]:
        result = await asyncio.to_thread(capture_workbuddy_window)
        if not result:
            return None
        b64, taken = result
        self.state.last_screenshot_at = taken
        msg = {
            "type": "screenshot",
            "data": {
                "taken_at": taken,
                "image_base64": b64,
            },
        }
        await _maybe_await(emit(msg))
        return msg

    async def run(self, emit: Callable[[dict], Any]) -> None:
        logger.info("ScreenshotMonitor 启动，间隔 %.1fs", self.interval)
        while not self._stop.is_set():
            try:
                await self.capture_and_emit(emit)
            except Exception as e:
                logger.exception("ScreenshotMonitor 错误: %s", e)

            # 等待 interval，或被 request_now 打断
            self._demand.clear()
            try:
                await asyncio.wait_for(self._demand.wait(), timeout=self.interval)
                # 被按需触发，立即再截一张（循环顶部）
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
        self._demand.set()


# ─────────────────────────────────────────────────────────────
# MonitorHub
# ─────────────────────────────────────────────────────────────


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


class MonitorHub:
    """聚合所有 monitor，提供统一 event 队列与状态。"""

    def __init__(self, cfg: Any) -> None:
        from config import Config  # 类型

        self.cfg: Config = cfg
        self.state = SharedState()
        self.event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)

        self.process = ProcessMonitor(
            self.state, interval=cfg.process_poll_interval
        )
        self.system = SystemMonitor(
            self.state, interval=cfg.system_poll_interval
        )
        self.db = DBMonitor(
            self.state, cfg.db_path, interval=cfg.db_poll_interval
        )
        watch_dirs = [cfg.teams_dir, cfg.tasks_dir, cfg.memory_dir]
        # 额外监听工作区 memory（若存在）
        extra_mem = Path(r"E:\code\.workbuddy\memory")
        if extra_mem.exists():
            watch_dirs.append(extra_mem)
        self.files = FileMonitor(
            self.state, watch_dirs, debounce_ms=cfg.file_debounce_ms
        )
        self.screenshot = ScreenshotMonitor(
            self.state, interval=cfg.screenshot_interval
        )
        self._tasks: list[asyncio.Task] = []

    async def _emit(self, msg: dict[str, Any]) -> None:
        """投递到队列；满则丢弃最旧。"""
        if "ts" not in msg:
            msg = {**msg, "ts": _now_ts()}
        try:
            self.event_queue.put_nowait(msg)
        except asyncio.QueueFull:
            try:
                _ = self.event_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.event_queue.put_nowait(msg)
            except asyncio.QueueFull:
                logger.warning("事件队列已满，丢弃事件 type=%s", msg.get("type"))

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self.process.run(self._emit), name="process"),
            asyncio.create_task(self.system.run(self._emit), name="system"),
            asyncio.create_task(self.db.run(self._emit), name="db"),
            asyncio.create_task(self.files.run(self._emit), name="files"),
            asyncio.create_task(self.screenshot.run(self._emit), name="screenshot"),
        ]
        logger.info("MonitorHub 已启动 %d 个协程", len(self._tasks))

    async def stop(self) -> None:
        self.process.stop()
        self.system.stop()
        self.db.stop()
        self.files.stop()
        self.screenshot.stop()
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("MonitorHub 已停止")

    async def take_screenshot_now(self) -> Optional[dict[str, Any]]:
        return await self.screenshot.capture_and_emit(self._emit)
