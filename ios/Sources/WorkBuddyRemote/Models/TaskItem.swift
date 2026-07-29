import Foundation

// MARK: - 团队任务

/// GET /api/tasks?team=<team_name> 返回的任务项
struct TaskItem: Codable, Identifiable, Equatable {
    /// 任务 ID（字符串或数字，统一转字符串）
    let id: String
    /// 任务标题
    var subject: String?
    /// 任务描述
    var description: String?
    /// 任务状态：pending / in_progress / completed / deleted
    var status: String?
    /// 负责人
    var owner: String?
    /// 所属团队
    var team: String?
    /// 创建时间（秒级时间戳）
    var createdAt: Int64?
    /// 更新时间（秒级时间戳）
    var updatedAt: Int64?

    enum CodingKeys: String, CodingKey {
        case id
        case subject
        case description
        case status
        case owner
        case team
        case createdAt = "created_at"
        case updatedAt = "updated_at"
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
        subject = try? c.decodeIfPresent(String.self, forKey: .subject)
        description = try? c.decodeIfPresent(String.self, forKey: .description)
        status = try? c.decodeIfPresent(String.self, forKey: .status)
        owner = try? c.decodeIfPresent(String.self, forKey: .owner)
        team = try? c.decodeIfPresent(String.self, forKey: .team)
        createdAt = c.decodeFlexibleInt64(forKey: .createdAt)
        updatedAt = c.decodeFlexibleInt64(forKey: .updatedAt)
    }

    /// 状态显示文本
    var statusText: String {
        switch (status ?? "").lowercased() {
        case "pending": return "待处理"
        case "in_progress", "inprogress": return "进行中"
        case "completed": return "已完成"
        case "deleted": return "已删除"
        default: return status ?? "未知"
        }
    }
}
