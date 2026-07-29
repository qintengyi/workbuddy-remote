# WorkBuddy Remote — 本机 Agent

运行在 Windows PC 上，监控并控制 WorkBuddy 桌面应用，通过 WebSocket 与远端 Server 通信，供 iOS App 远程查看/操控。

## 功能

| 模块 | 能力 |
|------|------|
| ProcessMonitor | 5s 扫描 WorkBuddy 进程 |
| DBMonitor | 只读轮询 `workbuddy.db`（automations / runs / sessions） |
| FileMonitor | watchdog 监听 teams / tasks / memory 变化 |
| SystemMonitor | CPU / 内存 |
| ScreenshotMonitor | 15s 截取 WorkBuddy 窗口（jpg q=70，宽≤1280） |
| Controller | 发消息 / 暂停恢复自动化 / 立即触发 / 即时截图 |
| Reporter | WS 自动重连（指数退避至 60s） |

## 环境要求

- Windows 10/11
- Python 3.10+（推荐 3.13，可使用 WorkBuddy 自带解释器）
- WorkBuddy 桌面版已安装

## 安装

```bash
cd E:\code\workbuddy-remote\agent

# 使用系统 Python 或 WorkBuddy 自带环境
python -m pip install -r requirements.txt

# 或
C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe -m pip install -r requirements.txt
```

> 若 `pywin32` 安装后无法 import，执行一次：
> `python Scripts/pywin32_postinstall.py -install`

## 配置

```bash
copy config.example.json config.json
```

编辑 `config.json`：

```json
{
  "server_url": "ws://192.168.1.8:10372",
  "agent_token": "<服务端首次启动打印的 AGENT_TOKEN>",
  "workbuddy_data_dir": "C:/Users/Administrator/.workbuddy",
  "screenshot_interval": 15,
  "status_interval": 5,
  "db_poll_interval": 5
}
```

- `agent_token`：必填，与 Server 一致
- `workbuddy_data_dir`：WorkBuddy 用户数据目录
- 间隔单位均为秒

## 启动

```bash
python main.py
# 或指定配置
python main.py -c config.json
# 调试日志
python main.py -v
```

启动后日志应出现：

```
WorkBuddy Remote Agent v1.0.0 启动中…
MonitorHub 已启动 5 个协程
连接服务端: ws://192.168.1.8:10372/ws/agent?token=***
WebSocket 已连接
```

## 协议摘要

**上行**（Agent → Server）

- `hello` — 握手
- `status` — 每 5s
- `event` — 业务事件（automation_run / task_update / …）
- `screenshot` — base64 jpg
- `log` / `command_result`

**下行**（Server → Agent）

- `send_message` / `pause_automation` / `resume_automation` / `run_automation` / `take_screenshot` / `ping`

详见 `../docs/API_SPEC.md` 第 4.2 / 7 / 8 节。

## 安全设计

- 读库：`file:...?mode=ro`，不锁 WorkBuddy 主库
- 写库：仅在 iOS 明确下发 pause/resume/run 时，WAL 短事务
- 截图：只截 WorkBuddy 窗口客户区，不截全屏
- 文件监听：500ms debounce，防风暴

## 开机自启（建议）

### 方式 A：任务计划程序

1. 打开「任务计划程序」→ 创建基本任务
2. 触发器：登录时
3. 操作：启动程序
   - 程序：`C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe`
   - 参数：`E:\code\workbuddy-remote\agent\main.py`
   - 起始于：`E:\code\workbuddy-remote\agent`
4. 勾选「使用最高权限」

### 方式 B：启动文件夹快捷方式

```bat
:: 创建 start_agent.bat
@echo off
cd /d E:\code\workbuddy-remote\agent
start "WB-Agent" /min C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe main.py
```

将快捷方式放入：`shell:startup`

## 目录结构

```
agent/
├── main.py              # 入口
├── config.py            # 配置加载
├── monitor.py           # 监听
├── controller.py        # 控制
├── reporter.py          # WebSocket
├── requirements.txt
├── config.example.json
├── config.json          # 本地配置（不入库）
└── README.md
```

## 故障排查

| 现象 | 处理 |
|------|------|
| 连接 401 / 立刻断开 | 检查 `agent_token` |
| WorkBuddy running=false | 确认桌面应用已启动；进程名含 WorkBuddy |
| 截图一直失败 | 窗口是否最小化到托盘；安装 pywin32 + pillow |
| send_message 失败 | 将 WorkBuddy 窗口保持可见；Electron 控件树可能变化，已自动回退 pyautogui |
| DB 锁定报错 | 读操作用只读 URI；写操作冲突会重试 busy_timeout=5s |
| 依赖缺失 | `pip install -r requirements.txt` |

## 许可

仅供个人/内网 WorkBuddy Remote 项目使用。
