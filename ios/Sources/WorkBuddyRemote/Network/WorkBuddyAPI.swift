import Foundation

// MARK: - API 错误

enum APIError: LocalizedError {
    case invalidURL
    case invalidResponse
    case networkError(String)
    case httpError(Int)
    case decodeError(String)
    case businessError(code: Int, message: String?)
    case emptyData
    case authRequired
    case agentOffline

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "服务器地址无效，请在设置中检查服务器地址。"
        case .invalidResponse:
            return "服务器响应格式异常。"
        case .networkError(let msg):
            return msg
        case .httpError(let code):
            return "网络请求失败（HTTP \(code)）。"
        case .decodeError(let msg):
            return "数据解析失败：\(msg)"
        case .businessError(let code, let message):
            if code == 503 { return message ?? "Agent 离线，请检查书房电脑上的 Agent 是否运行。" }
            return message ?? "业务错误（code=\(code)）"
        case .emptyData:
            return "服务器未返回数据。"
        case .authRequired:
            return "登录已过期，请重新登录。"
        case .agentOffline:
            return "Agent 离线，请检查书房电脑上的 Agent 是否运行。"
        }
    }
}

// MARK: - WorkBuddyAPI

/// WorkBuddy Remote 网络层
/// 通过 REST API 获取状态/会话/自动化/任务，自动附加 Authorization: Bearer token
final class WorkBuddyAPI {
    static let shared = WorkBuddyAPI()

    private let session: URLSession
    private let settingsStore: SettingsStore

    init(session: URLSession = .shared, settingsStore: SettingsStore = .shared) {
        self.session = session
        self.settingsStore = settingsStore
    }

    // MARK: - URL 构建

    /// 构建服务端 REST URL（如 http://host:10372/api/status）
    /// - Parameter path: /api/ 之后的路径，如 "status"、"conversations"、"automations/abc/pause"
    private func buildURL(path: String, queryItems: [URLQueryItem] = []) throws -> URL {
        let settings = settingsStore.settings
        let base = settings.serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !base.isEmpty else {
            throw APIError.invalidURL
        }

        guard var components = URLComponents(string: base) else {
            throw APIError.invalidURL
        }
        var basePath = components.path ?? ""
        if basePath.hasSuffix("/") { basePath.removeLast() }
        let cleanPath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        components.path = basePath + "/api/" + cleanPath
        if !queryItems.isEmpty {
            components.queryItems = queryItems
        }

        guard let url = components.url else {
            throw APIError.invalidURL
        }
        return url
    }

    /// 构建截图完整 URL（服务端返回相对路径 /files/xxx）
    func buildFileURL(relativePath: String) throws -> URL {
        let settings = settingsStore.settings
        let base = settings.serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !base.isEmpty, var components = URLComponents(string: base) else {
            throw APIError.invalidURL
        }
        var basePath = components.path ?? ""
        if basePath.hasSuffix("/") { basePath.removeLast() }
        let cleanPath = relativePath.hasPrefix("/") ? relativePath : "/" + relativePath
        components.path = basePath + cleanPath
        guard let url = components.url else {
            throw APIError.invalidURL
        }
        return url
    }

    // MARK: - 统一请求

    /// GET 请求
    func get<T: Decodable>(path: String, queryItems: [URLQueryItem] = [], timeout: TimeInterval = 15) async throws -> APIResponse<T> {
        let url = try buildURL(path: path, queryItems: queryItems)
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        req.timeoutInterval = timeout
        return try await perform(req)
    }

    /// POST 请求
    func post<T: Decodable>(path: String, body: [String: Any] = [:], timeout: TimeInterval = 15) async throws -> APIResponse<T> {
        let url = try buildURL(path: path)
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = timeout
        if !body.isEmpty {
            req.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])
        }
        return try await perform(req)
    }

    /// 执行请求（自动附加 Authorization header）
    private func perform<T: Decodable>(_ req: URLRequest) async throws -> APIResponse<T> {
        var req = req
        if let token = settingsStore.settings.token, !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (rawData, response): (Data, URLResponse)
        do {
            (rawData, response) = try await session.data(for: req)
        } catch {
            throw Self.mapNetworkError(error)
        }

        if let http = response as? HTTPURLResponse {
            if http.statusCode == 401 {
                throw APIError.authRequired
            }
            if !(200..<300).contains(http.statusCode) {
                throw APIError.httpError(http.statusCode)
            }
        }

        do {
            let decoded = try JSONDecoder().decode(APIResponse<T>.self, from: rawData)
            if decoded.code == 401 {
                throw APIError.authRequired
            }
            return decoded
        } catch let err as APIError {
            throw err
        } catch {
            let bodyPreview = String(data: rawData, encoding: .utf8) ?? "<non-utf8 \(rawData.count) bytes>"
            throw APIError.decodeError("\(error.localizedDescription) | body=\(bodyPreview.prefix(200))")
        }
    }

    /// 把 URLSession 网络错误转成可读的中文提示（不要伪装成“响应格式异常”）
    private static func mapNetworkError(_ error: Error) -> APIError {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorTimedOut:
                return .networkError("连接超时。请确认服务器地址是否正确；若填了 :10372 请改成 http://192.168.1.8（走 80 端口反代）。")
            case NSURLErrorCannotConnectToHost, NSURLErrorNetworkConnectionLost:
                return .networkError("无法连接服务器。端口可能被防火墙拦截，请使用 http://192.168.1.8（不要带 :10372）。")
            case NSURLErrorNotConnectedToInternet:
                return .networkError("当前网络不可用，请检查手机 Wi‑Fi。")
            case NSURLErrorCannotFindHost:
                return .networkError("找不到服务器主机，请检查地址拼写。")
            default:
                break
            }
        }
        return .networkError("网络请求失败：\(error.localizedDescription)")
    }

    // MARK: - 认证

    /// 登录
    /// - Parameters:
    ///   - username: 用户名
    ///   - password: 明文密码
    ///   - serverURL: 服务器地址（如 http://192.168.1.8）
    /// - Returns: 登录 token
    func login(username: String, password: String, serverURL: String) async throws -> String {
        let trimmed = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, var components = URLComponents(string: trimmed) else {
            throw APIError.invalidURL
        }
        // 无 scheme 时补 http://，避免 "192.168.1.8" 被 URLComponents 解析失败
        if components.scheme == nil {
            guard var fixed = URLComponents(string: "http://\(trimmed)") else {
                throw APIError.invalidURL
            }
            components = fixed
        }
        // 10372 在当前服务器被防火墙白名单拦截，强制提醒改 80
        if components.port == 10372 {
            // 不硬改用户输入，但给出更清晰失败路径：仍尝试；超时走 networkError 文案
        }
        var basePath = components.path
        if basePath.hasSuffix("/") { basePath.removeLast() }
        components.path = basePath + "/api/auth/login"
        guard let url = components.url else { throw APIError.invalidURL }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 15
        let body: [String: Any] = [
            "username": username,
            "password": password
        ]
        req.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])

        let (rawData, response): (Data, URLResponse)
        do {
            (rawData, response) = try await session.data(for: req)
        } catch {
            throw Self.mapNetworkError(error)
        }

        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            if let errorResp = try? JSONDecoder().decode(APIResponse<EmptyData>.self, from: rawData) {
                throw APIError.businessError(code: errorResp.code, message: errorResp.msg)
            }
            throw APIError.httpError(http.statusCode)
        }

        do {
            let decoded = try JSONDecoder().decode(APIResponse<LoginData>.self, from: rawData)
            if !decoded.isSuccess {
                throw APIError.businessError(code: decoded.code, message: decoded.msg)
            }
            guard let token = decoded.data?.token, !token.isEmpty else {
                throw APIError.decodeError("登录响应中缺少 token")
            }
            return token
        } catch let err as APIError {
            throw err
        } catch {
            let bodyPreview = String(data: rawData, encoding: .utf8) ?? "<non-utf8 \(rawData.count) bytes>"
            throw APIError.decodeError("\(error.localizedDescription) | body=\(bodyPreview.prefix(200))")
        }
    }

    // MARK: - 状态

    /// 综合：agent 在线、workbuddy 进程、最后活动时间、CPU/内存
    func fetchStatus() async throws -> StatusInfo {
        let resp: APIResponse<StatusInfo> = try await get(path: "status")
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.data ?? StatusInfo()
    }

    // MARK: - 会话

    /// 会话列表
    func fetchConversations(limit: Int = 20, offset: Int = 0) async throws -> [Conversation] {
        let resp: APIResponse<[Conversation]> = try await get(
            path: "conversations",
            queryItems: [
                URLQueryItem(name: "limit", value: String(limit)),
                URLQueryItem(name: "offset", value: String(offset))
            ]
        )
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.data ?? []
    }

    /// 消息历史
    func fetchMessages(conversationId: String, limit: Int = 50, before: Int64? = nil) async throws -> [Message] {
        var items = [
            URLQueryItem(name: "limit", value: String(limit))
        ]
        if let before = before, before > 0 {
            items.append(URLQueryItem(name: "before", value: String(before)))
        }
        let resp: APIResponse<[Message]> = try await get(
            path: "conversations/\(conversationId)/messages",
            queryItems: items
        )
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.data ?? []
    }

    /// 发送消息到当前活动会话（conversationId 为 nil 表示当前活动会话）
    func sendMessage(content: String, conversationId: String? = nil) async throws -> SendMessageResult {
        var body: [String: Any] = ["content": content]
        if let cid = conversationId, !cid.isEmpty {
            body["conversation_id"] = cid
        } else {
            body["conversation_id"] = NSNull()
        }
        let resp: APIResponse<SendMessageResult> = try await post(path: "messages", body: body)
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.data ?? SendMessageResult(ok: false, queued: false)
    }

    // MARK: - 自动化

    /// 自动化列表
    func fetchAutomations() async throws -> [Automation] {
        let resp: APIResponse<[Automation]> = try await get(path: "automations")
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.data ?? []
    }

    /// 暂停自动化
    func pauseAutomation(id: String) async throws -> String {
        let resp: APIResponse<EmptyData> = try await post(path: "automations/\(id)/pause")
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.msg ?? "已暂停"
    }

    /// 恢复自动化
    func resumeAutomation(id: String) async throws -> String {
        let resp: APIResponse<EmptyData> = try await post(path: "automations/\(id)/resume")
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.msg ?? "已恢复"
    }

    /// 立即触发自动化
    func runAutomation(id: String) async throws -> String {
        let resp: APIResponse<EmptyData> = try await post(path: "automations/\(id)/run")
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.msg ?? "已触发"
    }

    /// 自动化运行历史
    func fetchAutomationRuns(id: String, limit: Int = 20) async throws -> [AutomationRun] {
        let resp: APIResponse<[AutomationRun]> = try await get(
            path: "automations/\(id)/runs",
            queryItems: [URLQueryItem(name: "limit", value: String(limit))]
        )
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.data ?? []
    }

    // MARK: - 任务

    /// 团队任务列表
    func fetchTasks(team: String? = nil) async throws -> [TaskItem] {
        var items: [URLQueryItem] = []
        if let team = team, !team.isEmpty {
            items.append(URLQueryItem(name: "team", value: team))
        }
        let resp: APIResponse<[TaskItem]> = try await get(path: "tasks", queryItems: items)
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.data ?? []
    }

    // MARK: - 截图

    /// 获取最新截图元数据
    func fetchScreenshot() async throws -> ScreenshotData {
        let resp: APIResponse<ScreenshotData> = try await get(path: "screenshot")
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.data ?? ScreenshotData(url: nil, takenAt: nil)
    }

    // MARK: - 事件

    /// 事件流（历史事件）
    func fetchEvents(limit: Int = 100, since: Int64? = nil) async throws -> [EventItem] {
        var items = [URLQueryItem(name: "limit", value: String(limit))]
        if let since = since, since > 0 {
            items.append(URLQueryItem(name: "since", value: String(since)))
        }
        let resp: APIResponse<[EventItem]> = try await get(path: "events", queryItems: items)
        if !resp.isSuccess {
            throw APIError.businessError(code: resp.code, message: resp.msg)
        }
        return resp.data ?? []
    }

    // MARK: - 健康检查

    /// 健康检查（仅请求 /api/status 看是否可达）
    /// - Returns: true 表示服务器可达且 token 有效
    func checkHealth() async -> Bool {
        do {
            let _: APIResponse<StatusInfo> = try await get(path: "status", timeout: 10)
            return true
        } catch {
            return false
        }
    }
}
