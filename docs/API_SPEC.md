# WorkBuddy Remote — API / 协议规范

> 三端共同契约：服务端 (server/)、本机 Agent (agent/)、iOS App (ios/)。
>
> 任何字段变更必须先更新本文档。

---

## 1. 总体架构

```
┌─────────────┐   HTTPS/WSS    ┌──────────────┐   WebSocket    ┌────────────────┐
│  iOS App    │ ←────────────→ │   Server     │ ←────────────→ │  Local Agent   │
│ (Bedroom)   │   port 10372   │ 192.168.1.8  │   persistent   │  (Windows PC)  │
└─────────────┘                └──────────────┘                └────────────────┘
                                                                      │
                                                                      ▼
                                                              ┌──────────────┐
                                                              │ WorkBuddy    │
                                                              │ Desktop App  │
                                                              └──────────────┘
```

- **Agent → Server**：WebSocket 长连接（Agent 作为客户端），上报状态/事件，订阅指令
- **iOS → Server**：HTTPS REST + WebSocket 长连接（订阅实时事件）
- **Server**：双角色，对 Agent 是命令下行+状态上行；对 iOS 是数据源+控制台

---

## 2. 认证

### 2.1 用户登录（iOS 用）

```
POST /api/auth/login
Body: { "username": "admin", "password": "<明文>" }
Response: { "token": "<jwt-like-string>", "expires_at": 1234567890 }
```

后续所有 REST 请求需带 header：`Authorization: Bearer <token>`

### 2.2 Agent 认证

Agent 启动时连接 WebSocket：

```
ws://<server>:10372/ws/agent?token=<AGENT_TOKEN>
```

`AGENT_TOKEN` 在服务端首次启动时生成并打印，配置到 agent 端。
iOS 不能用此 token，iOS 必须用账号密码登录。

---

## 3. REST API（iOS → Server）

所有响应统一格式：

```json
{ "code": 200, "msg": "success", "data": <T> }
```

`code=401` 表示未认证；`code=503` 表示 Agent 离线；`code=400` 表示参数错误。

### 3.1 状态

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 综合：agent在线、workbuddy进程、最后活动时间、CPU/内存 |

`GET /api/status` 返回：

```json
{
  "code": 200, "msg": "success",
  "data": {
    "agent_online": true,
    "workbuddy_running": true,
    "workbuddy_pid": 12345,
    "last_activity_at": 1700000000,
    "active_conversation_id": "abc123",
    "active_conversation_title": "PIR 重构",
    "cpu_percent": 12.5,
    "memory_mb": 850,
    "uptime_seconds": 3600,
    "screenshot_updated_at": 1700000000
  }
}
```

### 3.2 会话/对话

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/conversations?limit=20&offset=0` | 会话列表 |
| GET | `/api/conversations/{id}/messages?limit=50&before=<ts>` | 消息历史 |
| POST | `/api/messages` | 向当前活动会话发送消息 |

`POST /api/messages`：

```json
{ "content": "继续上一步", "conversation_id": null }
```

`conversation_id=null` 表示发到当前活动会话。返回 `{ "ok": true, "queued": true }`。

### 3.3 自动化

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/automations` | 列出所有自动化及运行状态 |
| POST | `/api/automations/{id}/pause` | 暂停 |
| POST | `/api/automations/{id}/resume` | 恢复 |
| POST | `/api/automations/{id}/run` | 立即触发一次 |
| GET | `/api/automations/{id}/runs?limit=20` | 运行历史 |

### 3.4 任务（WorkBuddy 团队任务）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks?team=<team_name>` | 任务列表 |

### 3.5 截图

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/screenshot` | 返回最新截图（302 跳转到文件 URL，或直接 base64） |

实际返回：

```json
{ "code": 200, "data": { "url": "/files/screenshot_latest.jpg", "taken_at": 1700000000 } }
```

### 3.6 日志/事件

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/events?limit=100&since=<ts>` | 事件流（agent上行的所有事件） |

---

## 4. WebSocket 协议

### 4.1 iOS 订阅

```
ws://<server>:10372/ws/app?token=<user_token>
```

服务端推送消息格式（服务端 → iOS）：

```json
{ "type": "<event_type>", "data": { ... }, "ts": 1700000000 }
```

事件类型：

| type | 说明 | data 示例 |
|------|------|-----------|
| `status_update` | 状态变化 | 同 GET /api/status 的 data |
| `new_message` | 新会话消息 | `{ "conversation_id": "...", "role": "assistant", "content": "...", "preview": "前50字" }` |
| `automation_run` | 自动化运行状态 | `{ "id": "...", "name": "...", "status": "running\|completed\|failed" }` |
| `task_update` | 任务状态变化 | `{ "team": "...", "task_id": "1", "status": "completed" }` |
| `screenshot` | 新截图可用 | `{ "taken_at": 1700000000 }` |
| `agent_offline` | Agent 掉线 | `{}` |
| `agent_online` | Agent 上线 | `{}` |
| `log` | 日志行 | `{ "level": "info", "msg": "..." }` |

### 4.2 Agent 上下行

Agent 连接：`ws://<server>:10372/ws/agent?token=<AGENT_TOKEN>`

**Agent → Server**（上行，type 字段）：

| type | 说明 |
|------|------|
| `hello` | 首次握手，带 agent 版本和主机信息 |
| `status` | 周期状态上报（每 5 秒） |
| `event` | 事件（new_message/automation_run/task_update 等） |
| `log` | 日志 |
| `screenshot` | 截图数据（base64 jpg，每 15 秒或按需） |
| `command_result` | 指令执行结果 |

**Server → Agent**（下行，type 字段）：

| type | 说明 |
|------|------|
| `send_message` | 发送会话消息 `{ "content": "...", "conversation_id": null }` |
| `pause_automation` | `{ "id": "..." }` |
| `resume_automation` | `{ "id": "..." }` |
| `run_automation` | `{ "id": "..." }` |
| `take_screenshot` | 立即截图 |
| `ping` | 心跳 |

---

## 5. 数据存储

服务端 SQLite (`/www/wwwroot/workbuddy-remote/data.db`)：

```sql
-- 用户（单用户）
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  username TEXT UNIQUE,
  password_hash TEXT,
  created_at INTEGER
);

-- 事件流（agent 上报的所有事件都存这里）
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT,           -- status/new_message/automation_run/task_update/log
  data TEXT,           -- JSON
  ts INTEGER
);
CREATE INDEX idx_events_ts ON events(ts);

-- 会话/消息快照（agent 上报，非完整 DB 镜像）
CREATE TABLE conversations (
  id TEXT PRIMARY KEY,
  title TEXT,
  last_message_at INTEGER,
  last_activity_at INTEGER,
  updated_at INTEGER
);

CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT,
  role TEXT,           -- user/assistant/system
  content TEXT,
  ts INTEGER
);
CREATE INDEX idx_msg_conv ON messages(conversation_id, ts);

-- 自动化状态
CREATE TABLE automations (
  id TEXT PRIMARY KEY,
  name TEXT,
  status TEXT,         -- ACTIVE/PAUSED
  last_run_at INTEGER,
  next_run_at INTEGER,
  updated_at INTEGER
);
```

---

## 6. 默认账号

服务端首次启动时创建默认账号：

- **username**: `admin`
- **password**: `qty8520123`（与服务端 SSH 一致，便于记忆）

首次启动打印 `AGENT_TOKEN`，agent 配置文件使用此 token。

---

## 7. Agent 监听能力

| 监听对象 | 方法 | 频率 |
|---------|------|------|
| WorkBuddy 进程 | psutil 进程扫描 | 5s |
| `~/.workbuddy/workbuddy.db` | sqlite 轮询 automations/automation_runs 表 | 5s |
| `~/.workbuddy/teams/` `~/.workbuddy/tasks/` `~/.workbuddy/memory/` | watchdog 文件监听 | 实时 |
| WorkBuddy 窗口截图 | pywin32 + pillow，截取 WorkBuddy 窗口 | 15s |
| 系统资源 | psutil cpu/mem | 5s |

## 8. Agent 控制能力

| 控制对象 | 方法 | 可靠性 |
|---------|------|--------|
| 发送会话消息 | pywinauto UIA 后端定位 WorkBuddy 窗口输入框，set_text + 回车；失败回退 pyautogui | 中（依赖窗口结构） |
| 暂停/恢复自动化 | 直接更新 workbuddy.db automations.status（带文件锁） | 高 |
| 立即触发自动化 | 在 automation_runs 插入 pending 记录 | 中 |

---

## 9. iOS App 功能对照

| 模块 | 功能 | API |
|------|------|-----|
| 登录 | 账号密码登录 | `POST /api/auth/login` |
| 仪表盘 | Agent在线/进程状态/最后活动/CPU内存/截图 | `GET /api/status` + WS `status_update` + `screenshot` |
| 会话 | 列表+消息历史+发送 | `GET /api/conversations` + `GET /api/conversations/{id}/messages` + `POST /api/messages` |
| 自动化 | 列表+暂停/恢复/触发+运行历史 | `GET /api/automations` + `POST ...` |
| 任务 | 团队任务列表 | `GET /api/tasks` |
| 事件流 | 实时日志 | `GET /api/events` + WS `log` |
| 设置 | 服务器地址 + token + 主题 | 本地 UserDefaults |

---

## 10. 端口与部署

- 服务端监听 `0.0.0.0:10372`（HTTP + WS 同端口）
- 用户手动配置 nginx 反代到 10372，启用 HTTPS
- iOS 配置反代后的域名
- Agent 直连 `ws://192.168.1.8:10372`（局域网，无需反代）
