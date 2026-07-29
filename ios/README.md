# WorkBuddy Remote iOS

在卧室通过 iPhone 实时查看/控制书房 Windows 电脑上运行的 WorkBuddy 桌面应用。

纯 SwiftUI 实现（iOS 17+，@Observable 宏），视觉风格对齐 iOS 18，无第三方依赖。

## 架构

```
iPhone (卧室)  ←HTTPS/WSS→  Server (10372)  ←WebSocket→  Local Agent (书房 PC)
                                                                    ↓
                                                              WorkBuddy 桌面应用
```

iOS App 通过 REST API 获取状态/会话/自动化/任务，通过 WebSocket 接收实时事件（status_update / new_message / automation_run / task_update / screenshot / agent_offline / agent_online / log）。

## 功能

| 模块 | 功能 |
|------|------|
| 登录 | 账号密码登录（`POST /api/auth/login`） |
| 仪表盘 | Agent 在线/进程状态/最后活动/CPU 内存/最新截图（自动刷新 + 双指缩放） |
| 会话 | 列表 + 消息历史 + 发送消息 |
| 自动化 | 列表 + 暂停/恢复/触发 + 运行历史 |
| 任务 | 团队任务列表 |
| 事件流 | 实时日志（WebSocket log + 历史事件） |
| 设置 | 服务器地址、token、登出、关于 |

## 快速打包成 ipa（无需 Mac）

1. 把本目录 `ios/` 和 `.github/` 上传到 GitHub 公开仓库（注意 `.github/workflows/build-ipa.yml` 路径要在仓库根的 `.github/workflows/` 下）。
2. 推送到 `main` 分支，或手动在 Actions 页面触发 `Build IPA` workflow。
3. 等待云端 macOS 编译完成，下载 artifact `WorkBuddyRemote-unsigned-ipa`。
4. 用**全能签**或自有 p12/.mobileprovision 重签 `WorkBuddyRemote.ipa` 后安装到 iPhone。

> 全程免费。打包用 **XcodeGen**（`project.yml`）生成 `.xcodeproj`，由 GitHub Actions `macos-15` + Xcode 16.x 驱动 `xcodebuild` 编译。

## 在 Xcode 16 中打开运行

### 方式一：用 XcodeGen 生成工程

```bash
brew install xcodegen
cd ios
xcodegen generate
open WorkBuddyRemote.xcodeproj
```

### 方式二：作为 Swift Package 打开

1. Xcode → `File → Open` 选择 `ios/Package.swift`。
2. 选择 iOS 17+ 模拟器或真机运行。

## 技术栈

- SwiftUI（iOS 17+）
- @Observable 宏（Observation 框架）
- Swift 5.9
- URLSession + async/await
- URLSessionWebSocketTask（WebSocket，自动重连）
- 无第三方依赖

## 文件结构

```
ios/
├── project.yml                              # XcodeGen 工程配置
├── Package.swift                            # SwiftPM 组织
├── README.md
├── .github/workflows/build-ipa.yml          # GitHub Actions 云编译
└── Sources/WorkBuddyRemote/
    ├── WorkBuddyRemoteApp.swift             # App 入口 + AppStateManager
    ├── Info.plist                           # 显式配置（关键：UILaunchStoryboardName）
    ├── LaunchScreen.storyboard              # 启动屏
    ├── Assets.xcassets/                     # AppIcon
    ├── Models/
    │   ├── APIResponse.swift                # {code,msg,data} + 灵活解码
    │   ├── AppModels.swift                  # AppSettings / SettingsStore
    │   ├── Status.swift                     # StatusInfo
    │   ├── Conversation.swift               # Conversation / Message
    │   ├── Automation.swift                 # Automation / AutomationRun
    │   └── TaskItem.swift                   # TaskItem（团队任务）
    ├── Network/
    │   ├── WorkBuddyAPI.swift               # REST 网络层
    │   └── WebSocketClient.swift            # WebSocket 封装 + 自动重连
    └── Views/
        ├── LoginView.swift                  # 登录页
        ├── ContentView.swift                # 主 TabView
        ├── DashboardView.swift              # 仪表盘
        ├── ConversationsView.swift          # 会话列表
        ├── ConversationDetailView.swift     # 消息历史 + 发送
        ├── AutomationsView.swift            # 自动化列表 + 运行历史
        ├── TasksView.swift                  # 团队任务
        ├── EventsView.swift                 # 实时事件流
        ├── SettingsView.swift               # 设置
        └── SharedUI.swift                   # 共享 UI 组件
```

## 关键设计

- **未签名构建**：`CODE_SIGNING_ALLOWED=NO`，`.app` → `Payload/` → zip 成 `.ipa`。
- **XcodeGen + Xcode 26 兼容**：不用 `info:` 键，显式设置 `GENERATE_INFOPLIST_FILE: NO` + `INFOPLIST_FILE: Sources/WorkBuddyRemote/Info.plist`，启动屏用 `UILaunchStoryboardName`（非 `UILaunchScreen`）。
- **灵活 JSON 解码**：所有 `Int/Int64/Double` 字段用 `decodeFlexibleInt/Int64/Double`，兼容服务端返回字符串数字。
- **Dashboard 错误隔离**：并行获取数据时各请求独立捕获错误（`async let` + `try?`），单点失败不影响其他数据。
- **WebSocket 自动重连**：指数退避（最大 60s），代次机制防止旧回调干扰新连接。
- **时间显示**：北京时间 `yyyy-MM-dd HH:mm:ss`（`Asia/Shanghai`）。
- **截图缩放**：双指缩放（`MagnifyGesture`）。

## 服务端默认账号

- username: `admin`
- password: `qty8520123`

首次登录后 token 持久化到 UserDefaults，后续请求自动附加 `Authorization: Bearer <token>`。
