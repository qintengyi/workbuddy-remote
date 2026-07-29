# WorkBuddy Remote — iOS 远程监控控制 WorkBuddy 桌面应用

> 晚上电脑挂机跑任务，人在卧室用手机实时查看/控制/发消息。

## 架构

```
┌─────────────┐   HTTPS/WSS    ┌──────────────┐   WebSocket    ┌────────────────┐
│  iOS App    │ ←────────────→ │   Server     │ ←────────────→ │  Local Agent   │
│ (卧室手机)  │   port 10372   │ 192.168.1.8  │   persistent   │  (书房 Win PC) │
└─────────────┘                └──────────────┘                └────────────────┘
                                                                      │
                                                                      ▼
                                                              ┌──────────────┐
                                                              │ WorkBuddy    │
                                                              │ Desktop App  │
                                                              └──────────────┘
```

## 目录结构

```
workbuddy-remote/
├── docs/API_SPEC.md          # 三端共同契约（必读）
├── server/                   # 服务端（Python aiohttp，部署到 192.168.1.8:10372）
├── agent/                    # 本机 Agent（Python，运行在 Windows PC）
├── ios/                      # iOS App（SwiftUI + XcodeGen + GitHub Actions 云编译）
├── deploy/                   # 部署脚本和 systemd unit
└── README.md
```

## 功能

| 模块 | 能力 |
|------|------|
| 仪表盘 | Agent 在线 / WorkBuddy 进程 / CPU 内存 / 最后活动 / 实时截图 |
| 会话 | 历史列表 / 消息记录 / 远程发送消息 |
| 自动化 | 列表 / 暂停 / 恢复 / 立即触发 / 运行历史 |
| 任务 | WorkBuddy 团队任务列表 |
| 事件流 | 实时日志（WebSocket 推送） |
| 设置 | 服务器地址 / 登出 |

## 监听方案（Agent）

| 对象 | 方法 | 频率 |
|------|------|------|
| WorkBuddy 进程 | psutil 进程扫描 | 5s |
| workbuddy.db | sqlite 只读轮询 automations/runs | 5s |
| teams/tasks/memory 目录 | watchdog 文件监听 | 实时 |
| WorkBuddy 窗口截图 | pywin32 + pillow（只截窗口区域） | 15s |
| 系统资源 | psutil cpu/mem | 5s |

## 控制方案（Agent）

| 对象 | 方法 | 可靠性 |
|------|------|--------|
| 发送会话消息 | pywinauto UIA 定位输入框 + 回车 | 中 |
| 暂停/恢复自动化 | sqlite 更新 workbuddy.db automations.status | 高 |
| 立即触发自动化 | 插入 automation_runs pending | 中 |

## 部署

详见各子目录 README：
- 服务端：`server/README.md`（部署到 192.168.1.8）
- 本机 Agent：`agent/README.md`（Windows 安装配置）
- iOS：`ios/README.md`（GitHub Actions 云编译 IPA + 全能签重签）

## 默认账号

- 服务端 admin 账号：`admin` / `qty8520123`
- AGENT_TOKEN：服务端首次启动时生成并打印，填入 agent/config.json

## 技术栈

- **Server**：Python 3.10+ / aiohttp / SQLite / bcrypt
- **Agent**：Python 3.13 / asyncio / aiohttp / watchdog / psutil / pywinauto / pillow
- **iOS**：SwiftUI (iOS 17+) / @Observable / URLSession / URLSessionWebSocketTask / 无第三方依赖
