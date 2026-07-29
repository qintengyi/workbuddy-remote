import Foundation

// MARK: - 通用响应

/// 后端统一响应结构
/// - code: 200 表示成功，401 未认证，503 Agent 离线，400 参数错误
/// - msg: 提示信息
/// - data: 业务数据（泛型）
struct APIResponse<T: Decodable>: Decodable {
    let code: Int
    let msg: String?
    let data: T?

    var isSuccess: Bool { code == 200 }
}

// MARK: - 空数据类型

/// 用于无返回数据的接口（POST 类操作）
struct EmptyData: Decodable {}

// MARK: - 登录响应

struct LoginData: Decodable {
    let token: String
    let expiresAt: Int64?

    enum CodingKeys: String, CodingKey {
        case token
        case expiresAt = "expires_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        token = (try? c.decode(String.self, forKey: .token)) ?? ""
        expiresAt = c.decodeFlexibleInt64(forKey: .expiresAt)
    }
}

// MARK: - 截图响应

struct ScreenshotData: Decodable {
    /// 截图相对路径，如 "/files/screenshot_latest.jpg"
    let url: String?
    /// 截图时间戳（秒）
    let takenAt: Int64?

    enum CodingKeys: String, CodingKey {
        case url
        case takenAt = "taken_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try? c.decodeIfPresent(String.self, forKey: .url)
        takenAt = c.decodeFlexibleInt64(forKey: .takenAt)
    }
}

// MARK: - 发送消息响应

struct SendMessageResult: Decodable {
    let ok: Bool?
    let queued: Bool?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try? c.decodeIfPresent(Bool.self, forKey: .ok)
        queued = try? c.decodeIfPresent(Bool.self, forKey: .queued)
    }
}

// MARK: - 宽松 JSON 解码

/// 服务端可能返回数字字段为字符串（如 "12.5"），所有 Int/Int64/Double 字段统一用此扩展解码
extension KeyedDecodingContainer {
    /// 灵活解码 Int：兼容 Int / Double / String("12" / "12.5" / "85%")
    func decodeFlexibleInt(forKey key: Key) -> Int? {
        if let value = try? decodeIfPresent(Int.self, forKey: key) { return value }
        if let value = try? decodeIfPresent(Double.self, forKey: key) { return Int(value) }
        if let value = try? decodeIfPresent(String.self, forKey: key) {
            let normalized = value.replacingOccurrences(of: "%", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
            if let intValue = Int(normalized) { return intValue }
            if let doubleValue = Double(normalized) { return Int(doubleValue) }
            return nil
        }
        return nil
    }

    /// 灵活解码 Int64：兼容 Int64 / Int / Double / String（秒级时间戳）
    func decodeFlexibleInt64(forKey key: Key) -> Int64? {
        if let value = try? decodeIfPresent(Int64.self, forKey: key) { return value }
        if let value = try? decodeIfPresent(Int.self, forKey: key) { return Int64(value) }
        if let value = try? decodeIfPresent(Double.self, forKey: key) { return Int64(value) }
        if let value = try? decodeIfPresent(String.self, forKey: key) {
            let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines)
            if let intValue = Int64(normalized) { return intValue }
            if let doubleValue = Double(normalized) { return Int64(doubleValue) }
            return nil
        }
        return nil
    }

    /// 灵活解码 Double：兼容 Double / Int / String
    func decodeFlexibleDouble(forKey key: Key) -> Double? {
        if let value = try? decodeIfPresent(Double.self, forKey: key) { return value }
        if let value = try? decodeIfPresent(Int.self, forKey: key) { return Double(value) }
        if let value = try? decodeIfPresent(String.self, forKey: key) {
            return Double(value.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return nil
    }

    /// 灵活解码 Bool：兼容 Bool / Int(0/1) / String("true"/"false"/"1"/"0")
    func decodeFlexibleBool(forKey key: Key) -> Bool? {
        if let value = try? decodeIfPresent(Bool.self, forKey: key) { return value }
        if let value = try? decodeIfPresent(Int.self, forKey: key) { return value != 0 }
        if let value = try? decodeIfPresent(String.self, forKey: key) {
            let s = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            if s == "true" || s == "1" || s == "yes" { return true }
            if s == "false" || s == "0" || s == "no" { return false }
            return nil
        }
        return nil
    }
}
