import SwiftUI
import Observation

// MARK: - 任务 ViewModel

@Observable
final class TasksViewModel {
    var tasks: [TaskItem] = []
    var teamFilter: String = ""
    var isLoading: Bool = false
    var errorMessage: String? = nil
    var showError: Bool = false

    private let api = WorkBuddyAPI.shared

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let team = teamFilter.trimmingCharacters(in: .whitespacesAndNewlines)
            tasks = try await api.fetchTasks(team: team.isEmpty ? nil : team)
            // 按更新时间降序（新的在上）
            tasks.sort { (a, b) in (a.updatedAt ?? 0) > (b.updatedAt ?? 0) }
        } catch let err as APIError {
            errorMessage = err.errorDescription
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    /// 处理 WebSocket 推送的任务状态变化
    func onTaskUpdate() {
        Task { await load() }
    }

    /// 已知团队列表（从 tasks 提取）
    var knownTeams: [String] {
        let teams = tasks.compactMap { $0.team }.filter { !$0.isEmpty }
        return Array(Set(teams)).sorted()
    }
}

// MARK: - 任务视图

struct TasksView: View {
    @Environment(AppStateManager.self) private var appState
    @State private var vm = TasksViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.tasks.isEmpty {
                    LoadingView(text: "加载任务...")
                } else if vm.tasks.isEmpty {
                    EmptyStateView(
                        icon: "checklist",
                        title: "暂无任务",
                        description: vm.teamFilter.isEmpty ? "书房 WorkBuddy 暂无团队任务" : "未找到该团队的任务"
                    )
                } else {
                    List {
                        if !vm.knownTeams.isEmpty {
                            Section("团队筛选") {
                                Picker("团队", selection: $vm.teamFilter) {
                                    Text("全部").tag("")
                                    ForEach(vm.knownTeams, id: \.self) { team in
                                        Text(team).tag(team)
                                    }
                                }
                                .onChange(of: vm.teamFilter) { _, _ in
                                    Task { await vm.load() }
                                }
                            }
                        }
                        Section("任务列表") {
                            ForEach(vm.tasks) { task in
                                taskRow(task)
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                    .refreshable {
                        await vm.load()
                    }
                }
            }
            .navigationTitle("任务")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(.bar, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .alert("提示", isPresented: $vm.showError, actions: {
                Button("好") {}
            }, message: {
                Text(vm.errorMessage ?? "")
            })
            .onAppear {
                if vm.tasks.isEmpty && !vm.isLoading {
                    Task { await vm.load() }
                }
                registerWSCallback()
            }
        }
    }

    private func taskRow(_ task: TaskItem) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Image(systemName: "checkmark.circle")
                    .foregroundStyle(TaskStatusStyle.color(task.status))
                Text(task.subject ?? "未命名任务")
                    .font(.headline)
                    .lineLimit(2)
                Spacer()
                Text(task.statusText)
                    .font(.caption2)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 2)
                    .background(TaskStatusStyle.color(task.status).opacity(0.15))
                    .foregroundStyle(TaskStatusStyle.color(task.status))
                    .clipShape(Capsule())
            }
            if let desc = task.description, !desc.isEmpty {
                Text(desc)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
            HStack {
                if let team = task.team, !team.isEmpty {
                    Label(team, systemImage: "person.3.fill")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                if let owner = task.owner, !owner.isEmpty {
                    Label(owner, systemImage: "person.fill")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(DateUtil.format(timestamp: task.updatedAt))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    private func registerWSCallback() {
        appState.webSocketClient.onTaskUpdate = { _, _ in
            vm.onTaskUpdate()
        }
    }
}

#Preview {
    TasksView()
        .environment(AppStateManager())
}
