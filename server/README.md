# WorkBuddy Remote — Server

Python 异步服务端：为 iOS 提供 REST + WebSocket，为本机 Agent 提供 WebSocket 中转。

## 环境要求

- Python 3.10+
- 依赖见 `requirements.txt`（aiohttp、bcrypt）

## 安装

```bash
cd /www/wwwroot/workbuddy-remote/server
python3 -m venv .venv
source .venv/bin/activate   # 或 Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 启动

```bash
python3 main.py
# 监听 0.0.0.0:10372
```

首次启动会：

1. 生成 `config.json`（含 `secret_key`、`AGENT_TOKEN`）
2. 在 `data.db` 创建默认账号 `admin` / `qty8520123`
3. 将 **AGENT_TOKEN** 打印到 stdout（同时写入 config.json）

请把打印的 `AGENT_TOKEN` 配置到本机 Agent。

## 关键文件

| 路径 | 说明 |
|------|------|
| `config.json` | secret_key、agent_token |
| `data.db` | SQLite 数据库 |
| `static/screenshot_latest.jpg` | 最新截图 |

## systemd 部署

unit 文件见 `../deploy/workbuddy-remote.service`：

```bash
sudo cp /www/wwwroot/workbuddy-remote/deploy/workbuddy-remote.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now workbuddy-remote
sudo systemctl status workbuddy-remote
```

查看首次 AGENT_TOKEN：

```bash
sudo journalctl -u workbuddy-remote -n 50 --no-pager
# 或
cat /www/wwwroot/workbuddy-remote/server/config.json
```

## API 摘要

- `POST /api/auth/login` — 登录，返回 Bearer token（7 天）
- `GET  /api/status` — Agent / WorkBuddy 状态
- `GET  /api/conversations` / `.../messages` / `POST /api/messages`
- `GET  /api/automations` + pause/resume/run
- `GET  /api/tasks` / `/api/events` / `/api/screenshot`
- `WS   /ws/app?token=<user_token>` — iOS 实时推送
- `WS   /ws/agent?token=<AGENT_TOKEN>` — Agent 长连接
- `GET  /files/screenshot_latest.jpg` — 截图文件
- `GET  /health` — 健康检查

统一响应：`{ "code": 200, "msg": "success", "data": ... }`  
`code=401` 未认证；`code=503` Agent 离线。

详细协议见 `../docs/API_SPEC.md`。

## nginx 反代示例

```nginx
server {
    listen 443 ssl;
    server_name remote.example.com;
    # ssl_certificate ...;

    location / {
        proxy_pass http://127.0.0.1:10372;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }
}
```
