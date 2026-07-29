"""Chrome DevTools Protocol (CDP) Hook — 直接连接 WorkBuddy 渲染进程。

通过 CDP 可以：
- 执行任意 JS（读取 React 状态、localStorage、IndexedDB）
- 监听 DOM 变化（实时获取新消息）
- 发送消息（操作输入框 + 触发提交）

使用前提：WorkBuddy 需带 --remote-debugging-port=9222 启动。
用 deploy/start_workbuddy_cdp.bat 启动 WorkBuddy 后自动生效。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222


async def _http_get_json(url: str, timeout: float = 3.0) -> Any:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            return await resp.json()


async def is_cdp_available() -> bool:
    """检测 CDP 端口是否可用（WorkBuddy 是否带 --remote-debugging-port 启动）。"""
    try:
        data = await _http_get_json(f"http://{CDP_HOST}:{CDP_PORT}/json/version")
        return bool(data and data.get("webSocketDebuggerUrl"))
    except Exception:
        return False


async def list_pages() -> list[dict[str, Any]]:
    """获取 CDP 页面列表（每个渲染进程一个 page）。"""
    try:
        return await _http_get_json(f"http://{CDP_HOST}:{CDP_PORT}/json/list")
    except Exception:
        return []


class CDPHook:
    """通过 CDP 连接 WorkBuddy 渲染进程，执行 JS 读取/控制。"""

    def __init__(self) -> None:
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._msg_id: int = 0
        self._connected: bool = False
        self._page_url: str = ""

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def page_url(self) -> str:
        return self._page_url

    async def connect(self) -> bool:
        """连接到 WorkBuddy 的主渲染进程。"""
        try:
            pages = await list_pages()
            if not pages:
                logger.debug("CDP: 无可用页面")
                return False

            # 找 WorkBuddy 主页面（type=page，url 含 workbuddy 或 localhost 或 file）
            target = None
            for p in pages:
                if p.get("type") == "page":
                    url = p.get("url", "")
                    if any(k in url.lower() for k in ["workbuddy", "localhost", "file://", "chrome-extension"]):
                        target = p
                        break
            # 回退：取第一个 page
            if not target:
                for p in pages:
                    if p.get("type") == "page":
                        target = p
                        break
            if not target:
                logger.debug("CDP: 无 page 类型目标")
                return False

            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                return False

            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(ws_url, max_msg_size=64 * 1024 * 1024)
            self._page_url = target.get("url", "")
            self._connected = True
            logger.info("CDP 已连接: %s", self._page_url[:80])
            return True
        except Exception as e:
            logger.debug("CDP 连接失败: %s", e)
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
        self._ws = None
        self._session = None
        self._connected = False

    async def evaluate(self, expression: str, timeout: float = 10.0) -> Optional[Any]:
        """执行 JS 表达式，返回结果值。失败返回 None。"""
        if not self._connected or not self._ws:
            return None

        self._msg_id += 1
        msg_id = self._msg_id
        try:
            await self._ws.send_str(json.dumps({
                "id": msg_id,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                    "timeout": int(timeout * 1000),
                },
            }))
        except Exception as e:
            logger.debug("CDP send 失败: %s", e)
            self._connected = False
            return None

        # 等待响应
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self._ws.receive(), timeout=timeout)
            except asyncio.TimeoutError:
                break
            if raw.type != aiohttp.WSMsgType.TEXT:
                if raw.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    self._connected = False
                    break
                continue
            try:
                msg = json.loads(raw.data)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == msg_id:
                result = msg.get("result", {})
                if "error" in msg:
                    logger.debug("CDP evaluate 错误: %s", msg["error"])
                    return None
                val = result.get("result", {})
                if val.get("type") == "undefined":
                    return None
                return val.get("value")

        return None

    async def get_conversations(self) -> list[dict[str, Any]]:
        """通过 CDP 执行 JS 读取 WorkBuddy 的会话列表。

        探索性实现：尝试从 localStorage / 全局变量 / DOM 读取。
        WorkBuddy 的前端框架不同，读取方式可能需要调整。
        """
        expr = """
        (function() {
            var result = [];
            // 1. 尝试从 localStorage 读取会话
            try {
                for (var i = 0; i < localStorage.length; i++) {
                    var key = localStorage.key(i);
                    if (key && key.toLowerCase().includes('session')) {
                        try { result.push({source:'localStorage', key:key, value: JSON.parse(localStorage[key])}); } catch(e){}
                    }
                }
            } catch(e){}
            // 2. 尝试从全局变量找会话数据
            try {
                if (typeof window.__workbuddy_sessions !== 'undefined') {
                    result.push({source:'global', value: window.__workbuddy_sessions});
                }
            } catch(e){}
            // 3. 返回页面标题和 URL 用于诊断
            result.push({source:'meta', url: window.location.href, title: document.title});
            return JSON.stringify(result);
        })()
        """
        val = await self.evaluate(expr)
        if val and isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                pass
        return []

    async def get_messages(self, conversation_id: Optional[str] = None) -> list[dict[str, Any]]:
        """通过 CDP 执行 JS 读取会话消息。

        探索性实现：尝试从 DOM 读取当前显示的消息。
        """
        expr = """
        (function() {
            var messages = [];
            // 尝试找消息元素（WorkBuddy 的 DOM 结构需要探索）
            // 常见模式：[data-role], .message, [class*="message"], [class*="bubble"]
            var selectors = [
                '[data-role="message"]',
                '.message-content',
                '[class*="message"]',
                '[class*="bubble"]',
                '[class*="chat-message"]',
                '[class*="conversation-message"]',
                'div[role="article"]',
            ];
            for (var i = 0; i < selectors.length; i++) {
                var els = document.querySelectorAll(selectors[i]);
                if (els.length > 0) {
                    messages.push({selector: selectors[i], count: els.length,
                        samples: Array.from(els).slice(0,3).map(function(e){
                            return {text: e.innerText ? e.innerText.substring(0,200) : '',
                                    className: e.className,
                                    tagName: e.tagName};
                        })});
                }
            }
            // 也获取页面所有文本的大致结构（用于诊断）
            var bodyText = document.body ? document.body.innerText.substring(0, 500) : '';
            return JSON.stringify({messages: messages, bodyPreview: bodyText, url: window.location.href});
        })()
        """
        val = await self.evaluate(expr)
        if val and isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                pass
        return []

    async def send_message(self, content: str) -> dict[str, Any]:
        """通过 CDP 执行 JS 在 WorkBuddy 输入框中发送消息。

        探索性实现：尝试多种方式定位输入框。
        """
        # 转义引号
        safe_content = content.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        expr = f"""
        (function() {{
            var content = '{safe_content}';
            // 尝试多种方式找输入框
            var inputSelectors = [
                'textarea',
                '[contenteditable="true"]',
                '[role="textbox"]',
                'div[contenteditable]',
                '.chat-input',
                '[class*="input"][class*="message"]',
                '[class*="composer"]',
                'div[data-role="input"]',
            ];
            var found = null;
            for (var i = 0; i < inputSelectors.length; i++) {{
                var els = document.querySelectorAll(inputSelectors[i]);
                if (els.length > 0) {{
                    // 取最后一个（通常是输入框，不是历史消息）
                    var el = els[els.length - 1];
                    if (el.offsetWidth > 0 && el.offsetHeight > 0) {{
                        found = {{el: el, selector: inputSelectors[i]}};
                        break;
                    }}
                }}
            }}
            if (!found) return JSON.stringify({{ok: false, error: 'input not found'}});
            var el = found.el;
            // 设置内容
            if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {{
                // 使用 React 兼容的方式设值
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.{{0:HTMLTextAreaElement,1:HTMLInputElement}}[el.tagName === 'TEXTAREA' ? 0 : 1].prototype, 'value').set;
                nativeInputValueSetter.call(el, content);
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
            }} else if (el.contentEditable === 'true') {{
                el.focus();
                el.innerText = content;
                el.dispatchEvent(new InputEvent('input', {{bubbles: true, data: content}}));
            }}
            // 找提交按钮并点击
            var btnSelectors = [
                'button[type="submit"]',
                'button[class*="send"]',
                'button[aria-label*="send"]',
                'button[aria-label*="发送"]',
                'div[role="button"][aria-label*="send"]',
                'button[class*="submit"]',
            ];
            var btn = null;
            for (var j = 0; j < btnSelectors.length; j++) {{
                btn = document.querySelector(btnSelectors[j]);
                if (btn) break;
            }}
            // 也尝试用 Enter 键提交
            if (!btn) {{
                var enterEvent = new KeyboardEvent('keydown', {{
                    key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
                }});
                el.dispatchEvent(enterEvent);
                return JSON.stringify({{ok: true, method: 'enter_key', selector: found.selector}});
            }}
            btn.click();
            return JSON.stringify({{ok: true, method: 'button_click', selector: found.selector, button: btnSelectors[j]}});
        }})()
        """
        val = await self.evaluate(expr)
        if val and isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                pass
        return {"ok": False, "error": "evaluate failed"}

    async def explore_dom(self) -> dict[str, Any]:
        """探索 WorkBuddy 的 DOM 结构（诊断用）。

        返回页面 URL、标题、body 前 2000 字符、所有 button/textarea/input 信息。
        """
        expr = """
        (function() {
            var info = {url: window.location.href, title: document.title};
            // body 文本预览
            info.bodyText = document.body ? document.body.innerText.substring(0, 2000) : '';
            // 所有 textarea/input
            info.inputs = [];
            document.querySelectorAll('textarea, input[type="text"], [contenteditable="true"], [role="textbox"]').forEach(function(el) {
                info.inputs.push({tag: el.tagName, type: el.type || '', className: (el.className||'').substring(0,100),
                    placeholder: el.placeholder || '', visible: el.offsetWidth > 0});
            });
            // 所有 button
            info.buttons = [];
            document.querySelectorAll('button, [role="button"]').forEach(function(el) {
                info.buttons.push({text: (el.innerText||el.getAttribute('aria-label')||'').substring(0,50),
                    className: (el.className||'').substring(0,80), visible: el.offsetWidth > 0});
            });
            // localStorage keys
            info.localStorageKeys = [];
            for (var i = 0; i < Math.min(localStorage.length, 50); i++) {
                info.localStorageKeys.push(localStorage.key(i));
            }
            // 尝试找 React fiber root
            info.reactRoots = [];
            document.querySelectorAll('[id]').forEach(function(el) {
                if (el.id && (el.id.includes('root') || el.id.includes('app'))) {
                    info.reactRoots.push({id: el.id, childCount: el.children.length});
                }
            });
            return JSON.stringify(info);
        })()
        """
        val = await self.evaluate(expr)
        if val and isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                pass
        return {}
