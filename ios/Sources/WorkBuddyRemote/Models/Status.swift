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
    /// CPU 核心数
    var cpuCount: Int?
    /// 内存占用 MB（WorkBuddy 进程）
    var memoryMb: Int?
    /// 内存总量 MB
    var memoryTotalMb: Int?
    /// 内存使用百分比
    var memoryPercent: Double?
    /// 磁盘已用 GB
    var diskUsedGb: Double?
    /// 磁盘总量 GB
    var diskTotalGb: Double?
    /// 磁盘使用百分比
    var diskPercent: Double?
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
        case cpuCount = "cpu_count"
        case memoryMb = "memory_mb"
        case memoryTotalMb = "memory_total_mb"
        case memoryPercent = "memory_percent"
        case diskUsedGb = "disk_used_gb"
        case diskTotalGb = "disk_total_gb"
        case diskPercent = "disk_percent"
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
        cpuCount = c.decodeFlexibleInt(forKey: .cpuCount)
        memoryMb = c.decodeFlexibleInt(forKey: .memoryMb)
        memoryTotalMb = c.decodeFlexibleInt(forKey: .memoryTotalMb)
        memoryPercent = c.decodeFlexibleDouble(forKey: .memoryPercent)
        diskUsedGb = c.decodeFlexibleDouble(forKey: .diskUsedGb)
        diskTotalGb = c.decodeFlexibleDouble(forKey: .diskTotalGb)
        diskPercent = c.decodeFlexibleDouble(forKey: .diskPercent)
        uptimeSeconds = c.decodeFlexibleInt64(forKey: .uptimeSeconds)
        screenshotUpdatedAt = c.decodeFlexibleInt64(forKey: .screenshotUpdatedAt)
    }
}
