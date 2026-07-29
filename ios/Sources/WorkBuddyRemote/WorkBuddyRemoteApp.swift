import SwiftUI
import Observation

// MARK: - 全局应用状态管理

/// 全局应用状态：登录态、设置、WebSocket 客户端、全局提示
@Observable
final class AppStateManager {
    /// 是否已登录
    var isLoggedIn: Bool = false

    /// 当前登录用户名
    var currentUser: String? = nil

    /// WebSocket 客户端（实时事件）
    let webSocketClient: WebSocketClient = WebSocketClient.shared

    /// 全局 alert（authRequired 等需要跨视图展示的错误）
    var globalAlert: GlobalAlert?

    private let store = SettingsStore.shared

    init() {
        self.isLoggedIn = store.settings.isLoggedIn
        self.currentUser = store.settings.username
    }

    func refreshAuthState() {
        isLoggedIn = store.settings.isLoggedIn
        currentUser = store.settings.username
    }

    /// 登录成功后初始化
    func onLoginSuccess() async {
        refreshAuthState()
        // 启动 WebSocket 实时事件订阅
        webSocketClient.start()
    }

    /// 登出
    func logout() {
        webSocketClient.stop()
        store.clearLogin()
        refreshAuthState()
    }

    /// 抛出全局错误
    func showGlobalAlert(title: String, message: String) {
        globalAlert = GlobalAlert(title: title, message: message)
    }
}

struct GlobalAlert: Identifiable {
    let id = UUID()
    let title: String
    let message: String
}

// MARK: - App 入口

@main
struct WorkBuddyRemoteApp: App {
    @State private var appState = AppStateManager()

    var body: some Scene {
        WindowGroup {
            Group {
                if appState.isLoggedIn {
                    ContentView()
                        .environment(appState)
                } else {
                    LoginView()
                        .environment(appState)
                        .onAppear {
                            appState.refreshAuthState()
                        }
                }
            }
            .alert("提示", isPresented: Binding(
                get: { appState.globalAlert != nil },
                set: { if !$0 { appState.globalAlert = nil } }
            )) {
                Button("好", role: .cancel) {}
            } message: {
                Text(appState.globalAlert?.message ?? "")
            }
        }
        .onChange(of: appState.isLoggedIn) { _, loggedIn in
            if loggedIn {
                appState.webSocketClient.start()
            } else {
                appState.webSocketClient.stop()
            }
        }
    }
}
