import Foundation

// MARK: - 自动化

/// GET /api/automations 返回的自动化项
struct Automation: Codable, Identifiable, Equatable {
    let id: String
    var name: String?
    /// 状态：ACTIVE / PAUSED
    var status: String?
    /// 上次运行时间（秒级时间戳）
    var lastRunAt: Int64?
    /// 下次运行时间（秒级时间戳）
    var nextRunAt: Int64?
    var updatedAt: Int64?

    enum CodingKeys: String, CodingKey {
        case id, name, status
        case lastRunAt = "last_run_at"
        case nextRunAt = "next_run_at"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(String.self, forKey: .id)) ?? UUID().uuidString
        name = try? c.decodeIfPresent(String.self, forKey: .name)
        status = try? c.decodeIfPresent(String.self, forKey: .status)
        lastRunAt = c.decodeFlexibleInt64(forKey: .lastRunAt)
        nextRunAt = c.decodeFlexibleInt64(forKey: .nextRunAt)
        updatedAt = c.decodeFlexibleInt64(forKey: .updatedAt)
    }

    /// 是否已暂停
    var isPaused: Bool {
        (status ?? "").uppercased() == "PAUSED"
    }
}

// MARK: - 自动化运行历史

/// GET /api/automations/{id}/runs 返回的单次运行记录
struct AutomationRun: Codable, Identifiable, Equatable {
    /// 运行记录 ID（可能为字符串或数字）
    let id: String
    /// 自动化 ID
    var automationId: String?
    /// 自动化名称
    var automationName: String?
    /// 状态：running / completed / failed / pending
    var status: String?
    /// 开始时间（秒级时间戳）
    var startedAt: Int64?
    /// 结束时间（秒级时间戳）
    var finishedAt: Int64?
    /// 错误信息
    var error: String?

    enum CodingKeys: String, CodingKey {
        case id
        case automationId = "automation_id"
        case automationName = "automation_name"
        case status
        case startedAt = "started_at"
        case finishedAt = "finished_at"
        case error
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // id 可能是字符串或数字
        if let s = try? c.decodeIfPresent(String.self, forKey: .id), !s.isEmpty {
            id = s
        } else if let n = c.decodeFlexibleInt(forKey: .id) {
            id = String(n)
        } else {
            id = UUID().uuidString
        }
        automationId = try? c.decodeIfPresent(String.self, forKey: .automationId)
        automationName = try? c.decodeIfPresent(String.self, forKey: .automationName)
        status = try? c.decodeIfPresent(String.self, forKey: .status)
        startedAt = c.decodeFlexibleInt64(forKey: .startedAt)
        finishedAt = c.decodeFlexibleInt64(forKey: .finishedAt)
        error = try? c.decodeIfPresent(String.self, forKey: .error)
    }
}
