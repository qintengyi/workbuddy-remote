"""控制模块：执行服务端下发的命令。

- send_message: pywinauto UIA → 回退 pyautogui
- pause/resume_automation: 写 workbuddy.db（WAL 短事务）
- run_automation: 插入 automation_runs pending
- take_screenshot: 委托 MonitorHub
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Controller:
    def __init__(
        self,
        db_path: Path,
        monitor_hub: Any = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.hub = monitor_hub

    # ─── send_message ───────────────────────────────────────

    async def send_message(
        self, content: str, conversation_id: Optional[str] = None
    ) -> dict[str, Any]:
        """向 WorkBuddy 当前会话发送消息。

        优先级：
        1. CDP hook（直接执行 JS 操作输入框，最可靠）
        2. pywinauto UIA（定位窗口控件）
        3. pyautogui（键盘输入回退）
        """
        if not content:
            return {"ok": False, "error": "empty content"}

        logger.info(
            "send_message len=%d conversation_id=%s",
            len(content),
            conversation_id,
        )

        # 0) 优先 CDP hook
        if self.hub and hasattr(self.hub, "cdp") and self.hub.cdp.connected:
            try:
                result = await self.hub.cdp.send_message(content)
                if result.get("ok"):
                    logger.info("CDP 发送成功: %s", result.get("method"))
                    return {"ok": True, "method": "cdp", **result}
                logger.warning("CDP 发送失败: %s，回退 pywinauto", result.get("error"))
            except Exception as e:
                logger.warning("CDP 发送异常: %s，回退 pywinauto", e)

        # 1) pywinauto UIA
        try:
            ok, err = await asyncio.to_thread(self._send_via_pywinauto, content)
            if ok:
                return {"ok": True, "method": "pywinauto"}
            logger.warning("pywinauto 发送失败: %s，尝试 pyautogui", err)
        except Exception as e:
            logger.warning("pywinauto 异常: %s，尝试 pyautogui", e)
            err = str(e)

        # 2) 回退 pyautogui
        try:
            ok, err2 = await asyncio.to_thread(self._send_via_pyautogui, content)
            if ok:
                return {"ok": True}
            return {"ok": False, "error": err2 or err or "send failed"}
        except Exception as e:
            logger.exception("pyautogui 发送失败")
            return {"ok": False, "error": str(e)}

    def _find_workbuddy_window(self):  # noqa: ANN201
        from pywinauto import Desktop

        desk = Desktop(backend="uia")
        # 模糊匹配标题
        matches = []
        for w in desk.windows():
            try:
                title = w.window_text() or ""
            except Exception:
                continue
            if "workbuddy" in title.lower():
                try:
                    rect = w.rectangle()
                    if rect.width() < 200 or rect.height() < 200:
                        continue
                except Exception:
                    pass
                matches.append(w)
        if not matches:
            return None
        # 选最大的窗口作为主窗
        def area(w):  # noqa: ANN001
            try:
                r = w.rectangle()
                return r.width() * r.height()
            except Exception:
                return 0

        matches.sort(key=area, reverse=True)
        return matches[0]

    def _foreground(self, window) -> None:  # noqa: ANN001
        try:
            window.set_focus()
        except Exception:
            pass
        try:
            # 额外用 win32 置前
            import win32gui
            import win32con

            hwnd = int(window.handle)
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(0.2)

    def _send_via_pywinauto(self, content: str) -> tuple[bool, str]:
        try:
            from pywinauto import keyboard as pw_keyboard
        except ImportError as e:
            return False, f"pywinauto not installed: {e}"

        window = self._find_workbuddy_window()
        if window is None:
            return False, "WorkBuddy window not found"

        self._foreground(window)

        # 尝试找输入控件：Edit / Document / 自定义
        edit = self._locate_input(window)
        if edit is not None:
            try:
                edit.set_focus()
                time.sleep(0.1)
                # 优先 set_edit_text / set_text
                try:
                    if hasattr(edit, "set_edit_text"):
                        edit.set_edit_text(content)
                    elif hasattr(edit, "set_value"):
                        edit.set_value(content)
                    else:
                        edit.type_keys(content, with_spaces=True, pause=0.01)
                except Exception:
                    # type_keys 对特殊字符更稳妥用 clipboard
                    self._paste_text(content)
                time.sleep(0.05)
                pw_keyboard.send_keys("{ENTER}")
                logger.info("pywinauto 发送成功（控件）")
                return True, ""
            except Exception as e:
                logger.warning("控件输入失败: %s", e)

        # 控件找不到：焦点窗口后粘贴 + 回车
        try:
            self._foreground(window)
            self._paste_text(content)
            time.sleep(0.05)
            pw_keyboard.send_keys("{ENTER}")
            logger.info("pywinauto 发送成功（粘贴）")
            return True, ""
        except Exception as e:
            return False, str(e)

    def _locate_input(self, window):  # noqa: ANN001, ANN201
        """在窗口树中找输入框。"""
        candidates = []
        try:
            # 常见：Edit
            for ctrl in window.descendants(control_type="Edit"):
                try:
                    if ctrl.is_visible() and ctrl.is_enabled():
                        candidates.append(ctrl)
                except Exception:
                    continue
        except Exception:
            pass

        try:
            for ctrl in window.descendants(control_type="Document"):
                try:
                    if ctrl.is_visible() and ctrl.is_enabled():
                        candidates.append(ctrl)
                except Exception:
                    continue
        except Exception:
            pass

        # Electron 可能用 Group + 自定义，按名称关键字
        keywords = ("message", "input", "prompt", "chat", "composer", "编辑", "输入")
        try:
            for ctrl in window.descendants():
                try:
                    name = (ctrl.element_info.name or "").lower()
                    ctype = (ctrl.element_info.control_type or "").lower()
                    if any(k in name for k in keywords) and ctype in (
                        "edit",
                        "document",
                        "text",
                        "group",
                    ):
                        if ctrl.is_visible():
                            candidates.append(ctrl)
                except Exception:
                    continue
        except Exception:
            pass

        if not candidates:
            return None

        # 选最靠底部的（聊天输入通常在底部）
        def bottom_key(c):  # noqa: ANN001
            try:
                return c.rectangle().bottom
            except Exception:
                return 0

        candidates.sort(key=bottom_key, reverse=True)
        return candidates[0]

    def _paste_text(self, content: str) -> None:
        """经剪贴板粘贴，避免特殊字符问题。"""
        try:
            import win32clipboard
            import win32con

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, content)
            finally:
                win32clipboard.CloseClipboard()
            time.sleep(0.05)
            try:
                from pywinauto import keyboard as pw_keyboard

                pw_keyboard.send_keys("^v")
            except Exception:
                import pyautogui

                pyautogui.hotkey("ctrl", "v")
        except Exception:
            # 最后手段：直接打字（仅 ASCII 可靠）
            try:
                from pywinauto import keyboard as pw_keyboard

                pw_keyboard.send_keys(content, with_spaces=True, pause=0.01)
            except Exception:
                import pyautogui

                pyautogui.typewrite(content, interval=0.02)

    def _send_via_pyautogui(self, content: str) -> tuple[bool, str]:
        try:
            import pyautogui
        except ImportError as e:
            return False, f"pyautogui not installed: {e}"

        # 尝试把 WorkBuddy 窗口置前
        try:
            from monitor import find_workbuddy_hwnd

            hwnd = find_workbuddy_hwnd()
            if hwnd:
                try:
                    import win32gui
                    import win32con

                    if win32gui.IsIconic(hwnd):
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
                    time.sleep(0.25)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            # 点击窗口底部中央，试图激活输入框
            try:
                import win32gui
                from monitor import find_workbuddy_hwnd

                hwnd = find_workbuddy_hwnd()
                if hwnd:
                    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                    cx = (left + right) // 2
                    cy = bottom - 60
                    pyautogui.click(cx, cy)
                    time.sleep(0.15)
            except Exception:
                pass

            self._paste_text(content)
            time.sleep(0.05)
            pyautogui.press("enter")
            logger.info("pyautogui 发送成功")
            return True, ""
        except Exception as e:
            return False, str(e)

    # ─── automations ────────────────────────────────────────

    def _connect_rw(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            isolation_level=None,  # 手动事务
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def pause_automation(self, automation_id: str) -> dict[str, Any]:
        return self._set_automation_status(automation_id, "PAUSED")

    def resume_automation(self, automation_id: str) -> dict[str, Any]:
        return self._set_automation_status(automation_id, "ACTIVE")

    def _set_automation_status(
        self, automation_id: str, status: str
    ) -> dict[str, Any]:
        if not automation_id:
            return {"ok": False, "error": "missing id"}
        if not self.db_path.is_file():
            return {"ok": False, "error": f"db not found: {self.db_path}"}

        now_ms = int(time.time() * 1000)
        try:
            conn = self._connect_rw()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(
                    "UPDATE automations SET status = ?, updated_at = ? "
                    "WHERE id = ? AND deleted_at IS NULL",
                    (status, now_ms, automation_id),
                )
                if cur.rowcount == 0:
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "error": f"automation not found: {automation_id}",
                    }
                conn.execute("COMMIT")
                logger.info(
                    "自动化 %s 状态 -> %s", automation_id, status
                )
                return {"ok": True, "id": automation_id, "status": status}
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.exception("更新自动化状态失败")
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.exception("更新自动化状态异常")
            return {"ok": False, "error": str(e)}

    def run_automation(self, automation_id: str) -> dict[str, Any]:
        """插入一条 pending 运行记录，尝试触发立即执行。

        WorkBuddy 实际调度依赖自身 runtime；我们做最大努力：
        1) 写 automation_runs status=pending
        2) 刷新 automations.next_run_at / last 相关字段
        3) 标记 runtime_state
        """
        if not automation_id:
            return {"ok": False, "error": "missing id"}
        if not self.db_path.is_file():
            return {"ok": False, "error": f"db not found: {self.db_path}"}

        now_ms = int(time.time() * 1000)
        thread_id = f"manual-{uuid.uuid4()}"
        try:
            conn = self._connect_rw()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT id, name, status FROM automations "
                    "WHERE id = ? AND deleted_at IS NULL",
                    (automation_id,),
                ).fetchone()
                if not row:
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "error": f"automation not found: {automation_id}",
                    }
                name = row[1] or automation_id

                # 插入 run 记录（主键 thread_id）
                conn.execute(
                    "INSERT OR REPLACE INTO automation_runs "
                    "(thread_id, automation_id, status, thread_title, "
                    " created_at, updated_at, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        thread_id,
                        automation_id,
                        "pending",
                        f"[remote] {name}",
                        now_ms,
                        now_ms,
                        '{"source":"workbuddy-remote-agent"}',
                    ),
                )

                # 将 next_run_at 设为现在，促使调度器拾取
                conn.execute(
                    "UPDATE automations SET next_run_at = ?, updated_at = ? "
                    "WHERE id = ?",
                    (float(now_ms), now_ms, automation_id),
                )

                # runtime_state 若不存在则插入
                conn.execute(
                    "INSERT INTO automation_runtime_state "
                    "(automation_id, last_run_at, running, metadata_json) "
                    "VALUES (?, ?, 0, ?) "
                    "ON CONFLICT(automation_id) DO UPDATE SET "
                    "metadata_json=excluded.metadata_json",
                    (
                        automation_id,
                        now_ms,
                        '{"trigger":"remote","pending_thread":"%s"}' % thread_id,
                    ),
                )

                conn.execute("COMMIT")
                logger.info(
                    "已请求运行自动化 %s，thread=%s", automation_id, thread_id
                )
                return {
                    "ok": True,
                    "id": automation_id,
                    "thread_id": thread_id,
                    "status": "pending",
                }
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.exception("触发自动化失败")
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.exception("触发自动化异常")
            return {"ok": False, "error": str(e)}

    # ─── screenshot ─────────────────────────────────────────

    async def take_screenshot(self) -> dict[str, Any]:
        if self.hub is None:
            return {"ok": False, "error": "monitor hub not ready"}
        try:
            msg = await self.hub.take_screenshot_now()
            if msg is None:
                return {
                    "ok": False,
                    "error": "screenshot failed (window not found?)",
                }
            return {"ok": True, "taken_at": msg.get("data", {}).get("taken_at")}
        except Exception as e:
            logger.exception("立即截图失败")
            return {"ok": False, "error": str(e)}

    # ─── 统一分发 ───────────────────────────────────────────

    async def handle_command(self, msg: dict[str, Any]) -> dict[str, Any]:
        """处理服务端下行命令，返回 command_result 的 data 部分。"""
        cmd = msg.get("type") or ""
        request_id = msg.get("request_id")

        try:
            if cmd == "send_message":
                content = msg.get("content") or ""
                if not content and isinstance(msg.get("data"), dict):
                    content = msg["data"].get("content") or ""
                conv = msg.get("conversation_id")
                if conv is None and isinstance(msg.get("data"), dict):
                    conv = msg["data"].get("conversation_id")
                result = await self.send_message(content, conv)

            elif cmd == "pause_automation":
                aid = msg.get("id") or (msg.get("data") or {}).get("id")
                result = await _to_thread(self.pause_automation, str(aid or ""))

            elif cmd == "resume_automation":
                aid = msg.get("id") or (msg.get("data") or {}).get("id")
                result = await _to_thread(self.resume_automation, str(aid or ""))

            elif cmd == "run_automation":
                aid = msg.get("id") or (msg.get("data") or {}).get("id")
                result = await _to_thread(self.run_automation, str(aid or ""))

            elif cmd == "take_screenshot":
                result = await self.take_screenshot()

            elif cmd == "ping":
                result = {"ok": True, "pong": True}

            else:
                result = {"ok": False, "error": f"unknown command: {cmd}"}

        except Exception as e:
            logger.exception("命令处理异常 type=%s", cmd)
            result = {"ok": False, "error": str(e)}

        out = {
            "type": "command_result",
            "request_id": request_id,
            "command": cmd,
            "ok": bool(result.get("ok")),
            **{k: v for k, v in result.items() if k != "ok"},
        }
        # 规范：同时在 data 里带一份
        out["data"] = result
        return out


async def _to_thread(fn, *args):  # noqa: ANN001, ANN201
    import asyncio

    return await asyncio.to_thread(fn, *args)
