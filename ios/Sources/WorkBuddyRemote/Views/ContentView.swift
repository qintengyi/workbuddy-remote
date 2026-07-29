import SwiftUI
import Observation

/// 主 TabView（仪表盘/会话/自动化/任务/事件流/设置）
struct ContentView: View {
    @Environment(AppStateManager.self) private var appState
    @State private var selectedTab: Int = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            DashboardView(selectedTab: $selectedTab)
                .tabItem {
                    Label("仪表盘", systemImage: "house.fill")
                }
                .tag(0)

            ConversationsView()
                .tabItem {
                    Label("会话", systemImage: "bubble.left.and.bubble.right.fill")
                }
                .tag(1)

            AutomationsView()
                .tabItem {
                    Label("自动化", systemImage: "clock.arrow.2.circlepath")
                }
                .tag(2)

            TasksView()
                .tabItem {
                    Label("任务", systemImage: "checklist")
                }
                .tag(3)

            EventsView()
                .tabItem {
                    Label("事件", systemImage: "waveform")
                }
                .tag(4)

            SettingsView()
                .tabItem {
                    Label("设置", systemImage: "gearshape.fill")
                }
                .tag(5)
        }
        .tint(.blue)
        .task {
            // 启动 WebSocket 实时事件订阅
            appState.webSocketClient.start()
        }
    }
}

#Preview {
    ContentView()
        .environment(AppStateManager())
}
