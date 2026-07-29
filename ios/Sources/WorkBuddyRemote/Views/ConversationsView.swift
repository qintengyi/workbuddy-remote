import SwiftUI
import Observation

// MARK: - 会话列表 ViewModel

@Observable
final class ConversationsViewModel {
    var conversations: [Conversation] = []
    var isLoading: Bool = false
    var errorMessage: String? = nil
    var showError: Bool = false

    private let api = WorkBuddyAPI.shared

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            conversations = try await api.fetchConversations(limit: 50, offset: 0)
        } catch let err as APIError {
            errorMessage = err.errorDescription
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    /// 处理 WebSocket 推送的新消息（更新会话列表的 lastMessageAt / 顺序）
    func onNewMessage(conversationId: String) {
        guard !conversationId.isEmpty else { return }
        // 找到对应会话，更新时间戳并移到顶部
        if let idx = conversations.firstIndex(where: { $0.id == conversationId }) {
            var conv = conversations[idx]
            conv.lastMessageAt = Int64(Date().timeIntervalSince1970)
            conversations.remove(at: idx)
            conversations.insert(conv, at: 0)
        } else {
            // 不在列表中，可能是新会话，重新加载
            Task { await load() }
        }
    }
}

// MARK: - 会话列表视图

struct ConversationsView: View {
    @Environment(AppStateManager.self) private var appState
    @State private var vm = ConversationsViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.conversations.isEmpty {
                    LoadingView(text: "加载会话...")
                } else if vm.conversations.isEmpty {
                    EmptyStateView(
                        icon: "bubble.left.and.bubble.right",
                        title: "暂无会话",
                        description: "书房 WorkBuddy 暂无会话记录"
                    )
                } else {
                    List {
                        ForEach(vm.conversations) { conv in
                            NavigationLink {
                                ConversationDetailView(conversation: conv)
                            } label: {
                                conversationRow(conv)
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                    .refreshable {
                        await vm.load()
                    }
                }
            }
            .navigationTitle("会话")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(.bar, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .alert("提示", isPresented: $vm.showError, actions: {
                Button("好") {}
            }, message: {
                Text(vm.errorMessage ?? "")
            })
            .onAppear {
                if vm.conversations.isEmpty && !vm.isLoading {
                    Task { await vm.load() }
                }
                registerWSCallback()
            }
        }
    }

    private func conversationRow(_ conv: Conversation) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Image(systemName: "bubble.left.fill")
                    .foregroundStyle(.blue)
                    .font(.caption)
                Text(conv.title ?? "未命名会话")
                    .font(.headline)
                    .lineLimit(1)
                Spacer()
            }
            HStack {
                Text(DateUtil.format(timestamp: conv.lastMessageAt))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(DateUtil.relative(timestamp: conv.lastMessageAt))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    private func registerWSCallback() {
        appState.webSocketClient.onNewMessage = { conversationId, _, _ in
            vm.onNewMessage(conversationId: conversationId)
        }
    }
}

#Preview {
    ConversationsView()
        .environment(AppStateManager())
}
