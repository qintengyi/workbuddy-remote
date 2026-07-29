import SwiftUI
import Observation

// MARK: - 事件流 ViewModel

@Observable
final class EventsViewModel {
    /// 历史事件（从服务端拉取）
    var historyEvents: [EventItem] = []
    /// 实时日志（WebSocket 推送）
    var liveLogs: [LogEntry] = []
    var isLoading: Bool = false
    var errorMessage: String? = nil
    var showError: Bool = false
    /// 是否只显示实时日志（切换历史/实时）
    var showLiveOnly: Bool = true

    /// 最大保留日志条数
    private let maxLiveLogs = 500
    private let api = WorkBuddyAPI.shared

    func loadHistory() async {
        isLoading = true
        defer { isLoading = false }
        do {
            historyEvents = try await api.fetchEvents(limit: 100)
            // 按时间降序（新的在上）
            historyEvents.sort { (a, b) in (a.ts ?? 0) > (b.ts ?? 0) }
        } catch let err as APIError {
            errorMessage = err.errorDescription
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    /// 处理 WebSocket 推送的日志
    func onLog(level: String, msg: String) {
        let entry = LogEntry(
            id: UUID().uuidString,
            level: level,
            msg: msg,
            timestamp: Int64(Date().timeIntervalSince1970)
        )
        liveLogs.insert(entry, at: 0)
        // 超过上限截断
        if liveLogs.count > maxLiveLogs {
            liveLogs.removeLast(liveLogs.count - maxLiveLogs)
        }
    }

    /// 清空实时日志
    func clearLiveLogs() {
        liveLogs.removeAll()
    }
}

// MARK: - 日志条目（UI 用）

struct LogEntry: Identifiable {
    let id: String
    let level: String
    let msg: String
    let timestamp: Int64
}

// MARK: - 事件流视图

struct EventsView: View {
    @Environment(AppStateManager.self) private var appState
    @State private var vm = EventsViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // 切换：实时 / 历史
                Picker("模式", selection: $vm.showLiveOnly) {
                    Text("实时日志").tag(true)
                    Text("历史事件").tag(false)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)

                if vm.showLiveOnly {
                    liveLogsView
                } else {
                    historyEventsView
                }
            }
            .navigationTitle("事件流")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(.bar, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .alert("提示", isPresented: $vm.showError, actions: {
                Button("好") {}
            }, message: {
                Text(vm.errorMessage ?? "")
            })
            .toolbar {
                if vm.showLiveOnly && !vm.liveLogs.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("清空") {
                            vm.clearLiveLogs()
                        }
                    }
                }
            }
            .onAppear {
                registerWSCallback()
                if !vm.showLiveOnly && vm.historyEvents.isEmpty {
                    Task { await vm.loadHistory() }
                }
            }
            .onChange(of: vm.showLiveOnly) { _, live in
                if !live && vm.historyEvents.isEmpty {
                    Task { await vm.loadHistory() }
                }
            }
        }
    }

    // MARK: - 实时日志

    private var liveLogsView: some View {
        Group {
            if vm.liveLogs.isEmpty {
                EmptyStateView(
                    icon: "waveform",
                    title: "等待实时事件",
                    description: "WebSocket 连接后会实时显示日志"
                )
            } else {
                List {
                    ForEach(vm.liveLogs) { log in
                        logRow(log)
                    }
                }
                .listStyle(.insetGrouped)
            }
        }
    }

    private func logRow(_ log: LogEntry) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(log.level.uppercased())
                    .font(.caption2.bold().monospaced())
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(LogLevelStyle.color(log.level).opacity(0.15))
                    .foregroundStyle(LogLevelStyle.color(log.level))
                    .clipShape(Capsule())
                Spacer()
                Text(DateUtil.formatTime(timestamp: log.timestamp))
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
            }
            Text(log.msg)
                .font(.caption.monospaced())
                .lineLimit(4)
        }
        .padding(.vertical, 2)
    }

    // MARK: - 历史事件

    private var historyEventsView: some View {
        Group {
            if vm.isLoading && vm.historyEvents.isEmpty {
                LoadingView(text: "加载历史事件...")
            } else if vm.historyEvents.isEmpty {
                EmptyStateView(
                    icon: "tray.full",
                    title: "暂无历史事件",
                    description: nil
                )
            } else {
                List {
                    ForEach(vm.historyEvents) { event in
                        eventRow(event)
                    }
                }
                .listStyle(.insetGrouped)
                .refreshable {
                    await vm.loadHistory()
                }
            }
        }
    }

    private func eventRow(_ event: EventItem) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(event.type ?? "unknown")
                    .font(.caption.bold().monospaced())
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(eventColor(event.type).opacity(0.15))
                    .foregroundStyle(eventColor(event.type))
                    .clipShape(Capsule())
                Spacer()
                Text(DateUtil.format(timestamp: event.ts))
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
            }
            if let data = event.data, !data.isEmpty {
                Text(data)
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(4)
            }
        }
        .padding(.vertical, 2)
    }

    private func eventColor(_ type: String?) -> Color {
        switch type ?? "" {
        case "status_update": return .blue
        case "new_message": return .green
        case "automation_run": return .purple
        case "task_update": return .orange
        case "screenshot": return .teal
        case "agent_offline": return .red
        case "agent_online": return .green
        case "log": return .secondary
        default: return .secondary
        }
    }

    private func registerWSCallback() {
        appState.webSocketClient.onLog = { level, msg in
            vm.onLog(level: level, msg: msg)
        }
    }
}

#Preview {
    EventsView()
        .environment(AppStateManager())
}
