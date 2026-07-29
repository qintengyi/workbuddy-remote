# WorkBuddy Remote 使用指南

## 系统状态（已部署）

| 组件 | 状态 | 地址 |
|------|------|------|
| 服务端 | ✅ 运行中 | http://192.168.1.8:80（nginx 反代到 10372） |
| 本机 Agent | ✅ 运行中 | 后台进程，连 ws://192.168.1.8:80 |
| iOS App | 🔄 编译中 | GitHub Actions 云编译 IPA |

## iOS App 安装

1. 获取 `WorkBuddyRemote-unsigned.ipa`（GitHub Actions 编译产物）
2. 用**全能签**重签安装到 iPhone
3. 打开 App，输入服务器地址：`http://192.168.1.8`
4. 登录：`admin` / `qty8520123`

## 功能说明

### 仪表盘
- Agent 在线状态（绿/红徽章）
- WorkBuddy 进程状态 + PID
- CPU / 内存占用
- 最后活动时间
- 实时截图（15 秒刷新，双指缩放）

### 会话
- 查看会话列表
- 查看消息历史
- 发送消息到当前活动会话（通过 UI 自动化输入到 WorkBuddy 输入框 + 回车）

### 自动化
- 查看所有自动化及状态（ACTIVE/PAUSED）
- 暂停 / 恢复 / 立即触发
- 查看运行历史

### 任务
- 查看 WorkBuddy 团队任务列表

### 事件流
- 实时日志（WebSocket 推送）
- 历史事件查看

## 后台运行

### 服务端（已配置 systemd 自启）
```bash
# 服务器上
systemctl status workbuddy-remote   # 查看状态
systemctl restart workbuddy-remote  # 重启
journalctl -u workbuddy-remote -f   # 实时日志
```

### 本机 Agent（需配置开机自启）
当前在后台运行。如需开机自启，创建 Windows 计划任务：
1. 打开「任务计划程序」
2. 创建任务 → 触发器：登录时 → 操作：启动程序
3. 程序：`C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe`
4. 参数：`E:\code\workbuddy-remote\agent\main.py`
5. 起始位置：`E:\code\workbuddy-remote\agent`

## 网络说明

- 服务端实际监听 `0.0.0.0:10372`
- 因服务器端口白名单防火墙（只放行 22/80/443/16601），用 nginx 反代 80 → 10372
- Agent 和 iOS 都通过 80 端口访问（`http://192.168.1.8`）
- 如需外网访问，配置域名 + nginx HTTPS（443 已开放）

## 配置文件

| 文件 | 位置 | 说明 |
|------|------|------|
| 服务端 config.json | 服务器 `/www/wwwroot/workbuddy-remote/server/config.json` | secret_key + agent_token |
| Agent config.json | `E:\code\workbuddy-remote\agent\config.json` | server_url + agent_token |
| nginx 配置 | 服务器 `/www/server/panel/vhost/nginx/workbuddy-remote.conf` | 80 → 10372 反代 |

## 已知限制

1. **发送消息**：通过 UI 自动化（pywinauto）输入到 WorkBuddy 当前前台会话，不能切换会话
2. **触发自动化**：通过 DB 插入 pending 记录，WorkBuddy 调度器可能不立即拾取
3. **截图**：只截 WorkBuddy 窗口区域（隐私），15 秒刷新
4. **WebSocket 后台 Tab**：iOS 后台 Tab 不收实时事件，切回时刷新

## 故障排查

### Agent 连不上服务端
- 检查 `agent/config.json` 的 `server_url` 是 `ws://192.168.1.8:80`（不是 10372）
- 检查服务端 `systemctl status workbuddy-remote`
- 检查 nginx `nginx -t && nginx -s reload`

### iOS 登录失败
- 确认服务器地址输入 `http://192.168.1.8`（不带端口）
- 确认账号 `admin` / `qty8520123`

### 截图不显示
- Agent 需要 WorkBuddy 窗口在前台（非最小化）
- 截图通过 `/files/screenshot_latest.jpg` 访问，无需 auth
