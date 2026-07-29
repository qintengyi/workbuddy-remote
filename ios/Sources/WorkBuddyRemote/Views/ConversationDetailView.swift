import SwiftUI
import Observation

// MARK: - 会话详情 ViewModel

@Observable
final class ConversationDetailViewModel {
    var messages: [Message] = []
    var isLoading: Bool = false
    var isSending: Bool = false
    var inputText: String = ""
    var errorMessage: String? = nil
    var showError: Bool = false
    var successMessage: String? = nil
    var showSuccess: Bool = false

    private let api = WorkBuddyAPI.shared

    /// 加载消息历史
    func loadMessages(conversationId: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            let msgs = try await api.fetchMessages(conversationId: conversationId, limit: 50)
            // 按时间升序显示（旧的在上）
            messages = msgs.sorted { (a, b) in
                (a.ts ?? 0) < (b.ts ?? 0)
            }
        } catch let err as APIError {
            errorMessage = err.errorDescription
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    /// 加载更多（向上翻页）
    func loadMore(conversationId: String) async {
        guard let firstMsg = messages.first, let before = firstMsg.ts, before > 0 else { return }
        do {
            let msgs = try await api.fetchMessages(conversationId: conversationId, limit: 50, before: before)
            let sorted = msgs.sorted { (a, b) in (a.ts ?? 0) < (b.ts ?? 0) }
            messages.insert(contentsOf: sorted, at: 0)
        } catch {
            // 静默失败
        }
    }

    /// 发送消息
    func sendMessage(conversationId: String) async {
        let content = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else { return }
        isSending = true
        defer { isSending = false }
        do {
            _ = try await api.sendMessage(content: content, conversationId: conversationId)
            // 乐观更新：立即把消息加到列表
            let newMsg = Message(id: Int.random(in: -100000...(-1)),
                                 conversationId: conversationId,
                                 role: "user",
                                 content: content,
                                 ts: Int64(Date().timeIntervalSince1970))
            messages.append(newMsg)
            inputText = ""
            successMessage = "消息已发送"
            showSuccess = true
        } catch let err as APIError {
            errorMessage = err.errorDescription
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    /// 处理 WebSocket 推送的新消息
    func onNewMessage(conversationId: String, role: String, content: String) {
        guard conversationId == self.currentConversationId else { return }
        let msg = Message(id: Int.random(in: -100000...(-1)),
                          conversationId: conversationId,
                          role: role,
                          content: content,
                          ts: Int64(Date().timeIntervalSince1970))
        messages.append(msg)
    }

    var currentConversationId: String = ""
}

// MARK: - 会话详情视图

struct ConversationDetailView: View {
    let conversation: Conversation

    @Environment(AppStateManager.self) private var appState
    @State private var vm = ConversationDetailViewModel()

    var body: some View {
        VStack(spacing: 0) {
            // 消息列表
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        if vm.isLoading {
                            LoadingView(text: "加载消息...")
                                .frame(minHeight: 200)
                        } else if vm.messages.isEmpty {
                            EmptyStateView(
                                icon: "text.bubble",
                                title: "暂无消息",
                                description: "在下方输入框发送消息"
                            )
                            .padding(.top, 60)
                        } else {
                            ForEach(vm.messages) { msg in
                                messageRow(message: msg)
                                    .id(msg.stableId)
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                }
                .onChange(of: vm.messages.count) { _, _ in
                    // 新消息到达时滚动到底部
                    if let last = vm.messages.last {
                        withAnimation {
                            proxy.scrollTo(last.stableId, anchor: .bottom)
                        }
                    }
                }
            }

            Divider()

            // 输入框
            inputBar
        }
        .navigationTitle(conversation.title ?? "会话")
        .navigationBarTitleDisplayMode(.inline)
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
            vm.currentConversationId = conversation.id
            if vm.messages.isEmpty {
                Task { await vm.loadMessages(conversationId: conversation.id) }
            }
            registerWSCallback()
        }
        .onDisappear {
            vm.currentConversationId = ""
        }
    }

    // MARK: - 消息行

    private func messageRow(message: Message) -> some View {
        HStack {
            if message.isUser { Spacer(minLength: 40) }
            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 4) {
                if !message.isSystem {
                    Text(message.role ?? "")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 4)
                }
                Text(message.content ?? "")
                    .font(.body)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(message.isSystem ? Color.gray.opacity(0.12) :
                                (message.isUser ? Color.blue.opacity(0.12) : Color(.secondarySystemBackground)))
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                Text(DateUtil.format(timestamp: message.ts))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 4)
            }
            if !message.isUser { Spacer(minLength: 40) }
        }
    }

    // MARK: - 输入栏

    private var inputBar: some View {
        HStack(spacing: 8) {
            TextField("输入消息...", text: $vm.inputText, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...4)
                .submitLabel(.send)
                .onSubmit {
                    if !vm.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        Task { await vm.sendMessage(conversationId: conversation.id) }
                    }
                }

            Button {
                Task { await vm.sendMessage(conversationId: conversation.id) }
            } label: {
                Image(systemName: "paperplane.fill")
                    .font(.body)
                    .foregroundStyle(.white)
                    .frame(width: 36, height: 36)
                    .background(vm.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? Color.gray.opacity(0.3) : Color.blue)
                    .clipShape(Circle())
            }
            .disabled(vm.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || vm.isSending)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color(.systemBackground))
    }

    private func registerWSCallback() {
        appState.webSocketClient.onNewMessage = { conversationId, role, content in
            vm.onNewMessage(conversationId: conversationId, role: role, content: content)
        }
    }
}

#Preview {
    NavigationStack {
        ConversationDetailView(conversation: Conversation(id: "preview", title: "预览会话", lastMessageAt: nil, lastActivityAt: nil, updatedAt: nil))
            .environment(AppStateManager())
    }
}
