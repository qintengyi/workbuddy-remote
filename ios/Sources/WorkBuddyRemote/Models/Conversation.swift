import Foundation

// MARK: - 会话

/// GET /api/conversations 返回的会话列表项
struct Conversation: Codable, Identifiable, Equatable {
    /// 会话 ID
    let id: String
    /// 会话标题
    var title: String?
    /// 最后一条消息时间（秒级时间戳）
    var lastMessageAt: Int64?
    /// 最后活动时间（秒级时间戳）
    var lastActivityAt: Int64?
    /// 更新时间（秒级时间戳）
    var updatedAt: Int64?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case lastMessageAt = "last_message_at"
        case lastActivityAt = "last_activity_at"
        case updatedAt = "updated_at"
    }

    init(id: String, title: String? = nil, lastMessageAt: Int64? = nil, lastActivityAt: Int64? = nil, updatedAt: Int64? = nil) {
        self.id = id
        self.title = title
        self.lastMessageAt = lastMessageAt
        self.lastActivityAt = lastActivityAt
        self.updatedAt = updatedAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(String.self, forKey: .id)) ?? UUID().uuidString
        title = try? c.decodeIfPresent(String.self, forKey: .title)
        lastMessageAt = c.decodeFlexibleInt64(forKey: .lastMessageAt)
        lastActivityAt = c.decodeFlexibleInt64(forKey: .lastActivityAt)
        updatedAt = c.decodeFlexibleInt64(forKey: .updatedAt)
    }
}

// MARK: - 消息

/// GET /api/conversations/{id}/messages 返回的消息项
struct Message: Codable, Identifiable, Equatable {
    /// 消息自增 ID（服务端 messages.id）
    let id: Int
    /// 会话 ID
    var conversationId: String?
    /// 角色：user / assistant / system
    var role: String?
    /// 消息内容
    var content: String?
    /// 时间戳（秒级）
    var ts: Int64?

    enum CodingKeys: String, CodingKey {
        case id
        case conversationId = "conversation_id"
        case role
        case content
        case ts
    }

    init(id: Int, conversationId: String? = nil, role: String? = nil, content: String? = nil, ts: Int64? = nil) {
        self.id = id
        self.conversationId = conversationId
        self.role = role
        self.content = content
        self.ts = ts
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.decodeFlexibleInt(forKey: .id) ?? 0
        conversationId = try? c.decodeIfPresent(String.self, forKey: .conversationId)
        role = try? c.decodeIfPresent(String.self, forKey: .role)
        content = try? c.decodeIfPresent(String.self, forKey: .content)
        ts = c.decodeFlexibleInt64(forKey: .ts)
    }

    /// 用于 Identifiable 兜底（id 为 0 时用内容前缀生成稳定 id）
    var stableId: String {
        if id > 0 { return String(id) }
        return "\(role ?? "")_\(ts ?? 0)_\(content?.prefix(16) ?? "")"
    }
}

// MARK: - 角色显示

extension Message {
    /// 是否为用户消息
    var isUser: Bool { (role ?? "").lowercased() == "user" }

    /// 是否为系统消息
    var isSystem: Bool { (role ?? "").lowercased() == "system" }
}
