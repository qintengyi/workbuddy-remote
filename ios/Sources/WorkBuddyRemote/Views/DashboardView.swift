import SwiftUI
import Observation

// MARK: - 仪表盘 ViewModel

@Observable
final class DashboardViewModel {
    var status: StatusInfo = StatusInfo()
    var screenshotURL: URL? = nil
    var screenshotTakenAt: Int64? = nil
    var isLoading: Bool = false
    var isRefreshingScreenshot: Bool = false
    var errorMessage: String? = nil
    var showError: Bool = false

    private let api = WorkBuddyAPI.shared

    /// 加载状态 + 截图
    func loadStatus() async {
        isLoading = true
        defer { isLoading = false }

        // 并行获取状态和截图，各自独立捕获错误（错误隔离）
        async let statusTask = try? api.fetchStatus()
        async let screenshotTask = try? api.fetchScreenshot()

        let statusResult = await statusTask
        let screenshotResult = await screenshotTask

        if let s = statusResult { status = s }
        if let ss = screenshotResult {
            screenshotTakenAt = ss.takenAt
            if let relative = ss.url, !relative.isEmpty {
                screenshotURL = try? api.buildFileURL(relativePath: relative)
            } else {
                screenshotURL = nil
            }
        }

        // 全部失败才提示错误
        if statusResult == nil && screenshotResult == nil {
            errorMessage = "无法连接服务器，请检查网络或服务器地址。"
            showError = true
        }
    }

    /// 仅刷新截图
    func refreshScreenshot() async {
        isRefreshingScreenshot = true
        defer { isRefreshingScreenshot = false }
        do {
            let ss = try await api.fetchScreenshot()
            screenshotTakenAt = ss.takenAt
            if let relative = ss.url, !relative.isEmpty {
                screenshotURL = try api.buildFileURL(relativePath: relative)
            } else {
                screenshotURL = nil
            }
        } catch {
            // 静默失败，不打断仪表盘
        }
    }

    /// 处理 WebSocket 推送的状态更新
    func applyStatusUpdate(_ newStatus: StatusInfo) {
        status = newStatus
    }

    /// 处理 WebSocket 推送的截图事件
    func onScreenshotEvent(takenAt: Int64) {
        screenshotTakenAt = takenAt
        Task { await refreshScreenshot() }
    }
}

// MARK: - 仪表盘视图

struct DashboardView: View {
    @Environment(AppStateManager.self) private var appState
    @State private var vm = DashboardViewModel()
    @Binding var selectedTab: Int

    /// 自动刷新定时器
    @State private var refreshTimer: Timer?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    // Agent 状态卡片
                    agentStatusCard

                    // WorkBuddy 进程卡片
                    workbuddyProcessCard

                    // 系统资源卡片
                    resourceCard

                    // 活动信息卡片
                    activityCard

                    // 截图卡片
                    screenshotCard
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
            }
            .navigationTitle("仪表盘")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(.bar, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .refreshable {
                await vm.loadStatus()
            }
            .alert("提示", isPresented: $vm.showError, actions: {
                Button("好") {}
            }, message: {
                Text(vm.errorMessage ?? "")
            })
            .onAppear {
                if !vm.isLoading && vm.status.agentOnline == nil {
                    Task { await vm.loadStatus() }
                }
                registerWSCallbacks()
                startAutoRefresh()
            }
            .onDisappear {
                stopAutoRefresh()
            }
        }
    }

    // MARK: - Agent 状态卡片

    private var agentStatusCard: some View {
        HStack(spacing: 16) {
            ZStack {
                Circle()
                    .fill((vm.status.agentOnline ?? false) ? Color.green.opacity(0.15) : Color.red.opacity(0.15))
                    .frame(width: 52, height: 52)
                Image(systemName: (vm.status.agentOnline ?? false) ? "antenna.radiowaves.left.and.right" : "exclamationmark.triangle.fill")
                    .font(.title2)
                    .foregroundStyle((vm.status.agentOnline ?? false) ? .green : .red)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("Agent 状态")
                    .font(.headline)
                Text((vm.status.agentOnline ?? false) ? "在线" : "离线")
                    .font(.subheadline)
                    .foregroundStyle((vm.status.agentOnline ?? false) ? .green : .red)
                if let uptime = vm.status.uptimeSeconds, uptime > 0 {
                    Text("运行时长：\(formatUptime(uptime))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            if vm.isLoading {
                ProgressView()
            }
        }
        .cardStyle()
    }

    // MARK: - WorkBuddy 进程卡片

    private var workbuddyProcessCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "macwindow")
                    .foregroundStyle(.blue)
                Text("WorkBuddy 进程")
                    .font(.headline)
                Spacer()
                StatusBadge(online: vm.status.workbuddyRunning ?? false, onlineText: "运行中", offlineText: "未运行")
            }
            if let pid = vm.status.workbuddyPid, pid > 0 {
                HStack {
                    Text("PID")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("\(pid)")
                        .font(.caption.monospaced())
                }
            }
            if let title = vm.status.activeConversationTitle, !title.isEmpty {
                HStack(alignment: .top, spacing: 4) {
                    Image(systemName: "bubble.left")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("当前会话")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(title)
                            .font(.subheadline)
                            .lineLimit(2)
                    }
                }
            }
        }
        .cardStyle()
    }

    // MARK: - 系统资源卡片

    private var resourceCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "gauge.high")
                    .foregroundStyle(.orange)
                Text("系统资源")
                    .font(.headline)
                Spacer()
            }
            HStack(spacing: 16) {
                // CPU
                VStack(alignment: .leading, spacing: 4) {
                    Text("CPU")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    HStack(alignment: .firstTextBaseline, spacing: 2) {
                        Text(String(format: "%.1f", vm.status.cpuPercent ?? 0))
                            .font(.title3.monospacedDigit().bold())
                        Text("%")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Divider()
                    .frame(height: 32)
                // 内存
                VStack(alignment: .leading, spacing: 4) {
                    Text("内存")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    HStack(alignment: .firstTextBaseline, spacing: 2) {
                        Text("\(vm.status.memoryMb ?? 0)")
                            .font(.title3.monospacedDigit().bold())
                        Text("MB")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
            }
        }
        .cardStyle()
    }

    // MARK: - 活动信息卡片

    private var activityCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: "clock")
                    .foregroundStyle(.purple)
                Text("活动信息")
                    .font(.headline)
                Spacer()
            }
            HStack {
                Text("最后活动")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(DateUtil.format(timestamp: vm.status.lastActivityAt))
                    .font(.caption.monospaced())
            }
            HStack {
                Text("相对时间")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(DateUtil.relative(timestamp: vm.status.lastActivityAt))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .cardStyle()
    }

    // MARK: - 截图卡片

    private var screenshotCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "camera.viewfinder")
                    .foregroundStyle(.blue)
                Text("最新截图")
                    .font(.headline)
                Spacer()
                if vm.isRefreshingScreenshot {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Button {
                        Task { await vm.refreshScreenshot() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                            .font(.caption)
                    }
                }
            }
            if let url = vm.screenshotURL {
                ScreenshotImageView(url: url, takenAt: vm.screenshotTakenAt)
            } else {
                EmptyStateView(icon: "photo", title: "暂无截图", description: vm.isLoading ? "加载中..." : "点击右上角刷新")
                    .frame(maxWidth: .infinity)
                    .frame(minHeight: 200)
                    .background(Color(.tertiarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            if let takenAt = vm.screenshotTakenAt, takenAt > 0 {
                HStack {
                    Text("截图时间")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(DateUtil.format(timestamp: takenAt))
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
        }
        .cardStyle()
    }

    // MARK: - 自动刷新

    private func startAutoRefresh() {
        stopAutoRefresh()
        // 每 30 秒自动刷新状态
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { _ in
            Task { await vm.loadStatus() }
        }
    }

    private func stopAutoRefresh() {
        refreshTimer?.invalidate()
        refreshTimer = nil
    }

    // MARK: - WebSocket 回调

    private func registerWSCallbacks() {
        appState.webSocketClient.onStatusUpdate = { newStatus in
            vm.applyStatusUpdate(newStatus)
        }
        appState.webSocketClient.onScreenshot = { takenAt in
            vm.onScreenshotEvent(takenAt: takenAt)
        }
        appState.webSocketClient.onAgentOnlineChanged = { online in
            var s = vm.status
            s.agentOnline = online
            vm.applyStatusUpdate(s)
        }
    }

    // MARK: - 工具

    private func formatUptime(_ seconds: Int64) -> String {
        let s = Int(seconds)
        let days = s / 86400
        let hours = (s % 86400) / 3600
        let mins = (s % 3600) / 60
        if days > 0 { return "\(days)d \(hours)h \(mins)m" }
        if hours > 0 { return "\(hours)h \(mins)m" }
        return "\(mins)m"
    }
}

// MARK: - 截图视图（支持双指缩放）

struct ScreenshotImageView: View {
    let url: URL
    let takenAt: Int64?

    @State private var scale: CGFloat = 1.0
    @State private var lastScale: CGFloat = 1.0

    var body: some View {
        AsyncImage(url: url) { phase in
            switch phase {
            case .empty:
                LoadingView(text: "加载截图...")
                    .frame(minHeight: 200)
            case .success(let image):
                image
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .scaleEffect(scale)
                    .gesture(
                        MagnifyGesture()
                            .onChanged { value in
                                scale = max(1.0, min(5.0, lastScale * value.magnification))
                            }
                            .onEnded { value in
                                lastScale = scale
                                if scale < 1.0 {
                                    withAnimation { scale = 1.0; lastScale = 1.0 }
                                }
                            }
                    )
                    .onTapGesture(count: 2) {
                        withAnimation {
                            if scale > 1.0 {
                                scale = 1.0
                            } else {
                                scale = 2.0
                            }
                            lastScale = scale
                        }
                    }
            case .failure:
                EmptyStateView(icon: "exclamationmark.triangle", title: "截图加载失败", description: nil)
                    .frame(minHeight: 200)
            @unknown default:
                EmptyStateView(icon: "questionmark", title: "未知状态", description: nil)
                    .frame(minHeight: 200)
            }
        }
        .frame(maxWidth: .infinity)
        .background(Color(.tertiarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

#Preview {
    DashboardView(selectedTab: .constant(0))
        .environment(AppStateManager())
}
