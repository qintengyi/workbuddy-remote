import Foundation

// MARK: - 状态信息

/// GET /api/status 返回的状态信息
/// 字段全部可选 + 灵活解码，服务端可能不返回全部字段
struct StatusInfo: Codable, Equatable {
    /// Agent 是否在线
    var agentOnline: Bool?
    /// WorkBuddy 进程是否在运行
    var workbuddyRunning: Bool?
    /// WorkBuddy 进程 PID
    var workbuddyPid: Int?
    /// 最后活动时间（秒级时间戳）
    var lastActivityAt: Int64?
    /// 当前活动会话 ID
    var activeConversationId: String?
    /// 当前活动会话标题
    var activeConversationTitle: String?
    /// CPU 占用百分比
    var cpuPercent: Double?
    /// 内存占用 MB
    var memoryMb: Int?
    /// Agent 运行时长（秒）
    var uptimeSeconds: Int64?
    /// 截图更新时间（秒级时间戳）
    var screenshotUpdatedAt: Int64?

    enum CodingKeys: String, CodingKey {
        case agentOnline = "agent_online"
        case workbuddyRunning = "workbuddy_running"
        case workbuddyPid = "workbuddy_pid"
        case lastActivityAt = "last_activity_at"
        case activeConversationId = "active_conversation_id"
        case activeConversationTitle = "active_conversation_title"
        case cpuPercent = "cpu_percent"
        case memoryMb = "memory_mb"
        case uptimeSeconds = "uptime_seconds"
        case screenshotUpdatedAt = "screenshot_updated_at"
    }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        agentOnline = c.decodeFlexibleBool(forKey: .agentOnline)
        workbuddyRunning = c.decodeFlexibleBool(forKey: .workbuddyRunning)
        workbuddyPid = c.decodeFlexibleInt(forKey: .workbuddyPid)
        lastActivityAt = c.decodeFlexibleInt64(forKey: .lastActivityAt)
        activeConversationId = try? c.decodeIfPresent(String.self, forKey: .activeConversationId)
        activeConversationTitle = try? c.decodeIfPresent(String.self, forKey: .activeConversationTitle)
        cpuPercent = c.decodeFlexibleDouble(forKey: .cpuPercent)
        memoryMb = c.decodeFlexibleInt(forKey: .memoryMb)
        uptimeSeconds = c.decodeFlexibleInt64(forKey: .uptimeSeconds)
        screenshotUpdatedAt = c.decodeFlexibleInt64(forKey: .screenshotUpdatedAt)
    }
}
