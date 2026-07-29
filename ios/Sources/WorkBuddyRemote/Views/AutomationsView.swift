import SwiftUI
import Observation

// MARK: - 自动化 ViewModel

@Observable
final class AutomationsViewModel {
    var automations: [Automation] = []
    var isLoading: Bool = false
    var isOperating: Bool = false
    var errorMessage: String? = nil
    var showError: Bool = false
    var successMessage: String? = nil
    var showSuccess: Bool = false

    private let api = WorkBuddyAPI.shared

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            automations = try await api.fetchAutomations()
        } catch let err as APIError {
            errorMessage = err.errorDescription
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    func pause(_ automation: Automation) async {
        isOperating = true
        defer { isOperating = false }
        do {
            _ = try await api.pauseAutomation(id: automation.id)
            updateAutomationStatus(id: automation.id, status: "PAUSED")
            successMessage = "已暂停「\(automation.name ?? automation.id)」"
            showSuccess = true
        } catch let err as APIError {
            errorMessage = err.errorDescription
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    func resume(_ automation: Automation) async {
        isOperating = true
        defer { isOperating = false }
        do {
            _ = try await api.resumeAutomation(id: automation.id)
            updateAutomationStatus(id: automation.id, status: "ACTIVE")
            successMessage = "已恢复「\(automation.name ?? automation.id)」"
            showSuccess = true
        } catch let err as APIError {
            errorMessage = err.errorDescription
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    func run(_ automation: Automation) async {
        isOperating = true
        defer { isOperating = false }
        do {
            _ = try await api.runAutomation(id: automation.id)
            successMessage = "已触发「\(automation.name ?? automation.id)」"
            showSuccess = true
        } catch let err as APIError {
            errorMessage = err.errorDescription
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    private func updateAutomationStatus(id: String, status: String) {
        guard let idx = automations.firstIndex(where: { $0.id == id }) else { return }
        automations[idx].status = status
    }

    /// 处理 WebSocket 推送的自动化运行状态
    func onAutomationRun(id: String, status: String) {
        guard let idx = automations.firstIndex(where: { $0.id == id }) else { return }
        // automation_run 事件 status 是运行状态（running/completed/failed），
        // 与 Automation.status（ACTIVE/PAUSED）不同，这里只刷新 lastRunAt
        automations[idx].lastRunAt = Int64(Date().timeIntervalSince1970)
    }
}

// MARK: - 自动化列表视图

struct AutomationsView: View {
    @Environment(AppStateManager.self) private var appState
    @State private var vm = AutomationsViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.automations.isEmpty {
                    LoadingView(text: "加载自动化...")
                } else if vm.automations.isEmpty {
                    EmptyStateView(
                        icon: "clock.arrow.2.circlepath",
                        title: "暂无自动化",
                        description: "书房 WorkBuddy 暂无自动化任务"
                    )
                } else {
                    List {
                        ForEach(vm.automations) { auto in
                            NavigationLink {
                                AutomationRunHistoryView(automation: auto)
                            } label: {
                                automationRow(auto)
                            }
                            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                Button(role: .destructive) {
                                    Task { await vm.pause(auto) }
                                } label: {
                                    Label("暂停", systemImage: "pause.fill")
                                }
                                .disabled(auto.isPaused || vm.isOperating)

                                Button {
                                    Task { await vm.run(auto) }
                                } label: {
                                    Label("触发", systemImage: "play.fill")
                                }
                                .tint(.blue)
                                .disabled(vm.isOperating)
                            }
                            .swipeActions(edge: .leading, allowsFullSwipe: false) {
                                Button {
                                    Task { await vm.resume(auto) }
                                } label: {
                                    Label("恢复", systemImage: "arrow.forward.fill")
                                }
                                .tint(.green)
                                .disabled(!auto.isPaused || vm.isOperating)
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                    .refreshable {
                        await vm.load()
                    }
                }
            }
            .navigationTitle("自动化")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(.bar, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .alert("提示", isPresented: $vm.showSuccess, actions: {
                Button("好") {}
            }, message: {
                Text(vm.successMessage ?? "")
            })
            .alert("出错", isPresented: $vm.showError, actions: {
                Button("好") {}
            }, message: {
                Text(vm.errorMessage ?? "")
            })
            .onAppear {
                if vm.automations.isEmpty && !vm.isLoading {
                    Task { await vm.load() }
                }
                registerWSCallback()
            }
        }
    }

    private func automationRow(_ auto: Automation) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Image(systemName: auto.isPaused ? "pause.circle.fill" : "play.circle.fill")
                    .foregroundStyle(AutomationStatusStyle.color(auto.status))
                Text(auto.name ?? "未命名自动化")
                    .font(.headline)
                    .lineLimit(1)
                Spacer()
                Text(AutomationStatusStyle.text(auto.status))
                    .font(.caption2)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 2)
                    .background(AutomationStatusStyle.color(auto.status).opacity(0.15))
                    .foregroundStyle(AutomationStatusStyle.color(auto.status))
                    .clipShape(Capsule())
            }
            HStack {
                if let lastRun = auto.lastRunAt, lastRun > 0 {
                    Text("上次运行：\(DateUtil.format(timestamp: lastRun))")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                } else {
                    Text("暂无运行记录")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if let next = auto.nextRunAt, next > 0 {
                    Text("下次：\(DateUtil.formatShort(timestamp: next))")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func registerWSCallback() {
        appState.webSocketClient.onAutomationRun = { id, _, status in
            vm.onAutomationRun(id: id, status: status)
        }
    }
}

// MARK: - 运行历史 ViewModel

@Observable
final class AutomationRunHistoryViewModel {
    var runs: [AutomationRun] = []
    var isLoading: Bool = false
    var errorMessage: String? = nil
    var showError: Bool = false

    private let api = WorkBuddyAPI.shared

    func load(automationId: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            let raw = try await api.fetchAutomationRuns(id: automationId, limit: 50)
            // 按时间降序（新的在上）
            runs = raw.sorted { (a, b) in (a.startedAt ?? 0) > (b.startedAt ?? 0) }
        } catch let err as APIError {
            errorMessage = err.errorDescription
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }
}

// MARK: - 运行历史视图

struct AutomationRunHistoryView: View {
    let automation: Automation
    @State private var vm = AutomationRunHistoryViewModel()

    var body: some View {
        Group {
            if vm.isLoading && vm.runs.isEmpty {
                LoadingView(text: "加载运行历史...")
            } else if vm.runs.isEmpty {
                EmptyStateView(
                    icon: "clock.badge.questionmark",
                    title: "暂无运行记录",
                    description: nil
                )
            } else {
                List {
                    ForEach(vm.runs) { run in
                        runRow(run)
                    }
                }
                .listStyle(.insetGrouped)
                .refreshable {
                    await vm.load(automationId: automation.id)
                }
            }
        }
        .navigationTitle("运行历史")
        .navigationBarTitleDisplayMode(.inline)
        .alert("提示", isPresented: $vm.showError, actions: {
            Button("好") {}
        }, message: {
            Text(vm.errorMessage ?? "")
        })
        .onAppear {
            if vm.runs.isEmpty {
                Task { await vm.load(automationId: automation.id) }
            }
        }
    }

    private func runRow(_ run: AutomationRun) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Circle()
                    .fill(RunStatusStyle.color(run.status))
                    .frame(width: 8, height: 8)
                Text(RunStatusStyle.text(run.status))
                    .font(.subheadline.bold())
                    .foregroundStyle(RunStatusStyle.color(run.status))
                Spacer()
                Text(DateUtil.format(timestamp: run.startedAt))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            if let finished = run.finishedAt, finished > 0 {
                HStack {
                    Text("结束：\(DateUtil.format(timestamp: finished))")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    if let started = run.startedAt, started > 0 {
                        let duration = finished - started
                        if duration > 0 {
                            Text("耗时：\(formatDuration(duration))")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            if let err = run.error, !err.isEmpty {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .lineLimit(3)
            }
        }
        .padding(.vertical, 4)
    }

    private func formatDuration(_ seconds: Int64) -> String {
        if seconds < 60 { return "\(seconds)s" }
        if seconds < 3600 { return "\(seconds / 60)m \(seconds % 60)s" }
        return "\(seconds / 3600)h \((seconds % 3600) / 60)m"
    }
}

#Preview {
    AutomationsView()
        .environment(AppStateManager())
}
