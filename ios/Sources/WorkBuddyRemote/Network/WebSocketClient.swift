import Foundation
import Observation

// MARK: - WebSocket 事件

struct WSEvent: Decodable {
    let type: String
    /// 事件 data（保留原始 JSON，由各 View 自行解析）
    let dataRaw: Any?
    /// 事件时间戳（秒级）
    let ts: Int64?

    enum CodingKeys: String, CodingKey {
        case type
        case dataRaw = "data"
        case ts
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = (try? c.decode(String.self, forKey: .type)) ?? ""
        // data 可能是字典或数组，用 AnyDecodable 兜底
        let raw = try? c.decodeIfPresent(AnyDecodable.self, forKey: .dataRaw)
        dataRaw = raw?.value
        // ts 灵活解码（数字或字符串）
        ts = c.decodeFlexibleInt64(forKey: .ts)
    }

    /// 将 data 转换为指定类型
    func decodeData<T: Decodable>(_ type: T.Type) -> T? {
        guard let raw = dataRaw else { return nil }
        guard JSONSerialization.isValidJSONObject(raw) else { return nil }
        guard let data = try? JSONSerialization.data(withJSONObject: raw, options: []) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }
}

// MARK: - 事件流项（GET /api/events）

struct EventItem: Codable, Identifiable, Equatable {
    let id: Int
    let type: String?
    let data: String?    // 原始 JSON 字符串
    let ts: Int64?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.decodeFlexibleInt(forKey: .id) ?? 0
        type = try? c.decodeIfPresent(String.self, forKey: .type)
        data = try? c.decodeIfPresent(String.self, forKey: .data)
        ts = c.decodeFlexibleInt64(forKey: .ts)
    }
}

// MARK: - JSON 兜底解码辅助

/// 用于解析任意 JSON 值
struct AnyDecodable: Decodable {
    let value: Any?

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            value = nil
        } else if let v = try? container.decode(Bool.self) {
            value = v
        } else if let v = try? container.decode(Int64.self) {
            value = v
        } else if let v = try? container.decode(Double.self) {
            value = v
        } else if let v = try? container.decode(String.self) {
            value = v
        } else if let v = try? container.decode([AnyDecodable].self) {
            value = v.map { $0.value }
        } else if let v = try? container.decode([String: AnyDecodable].self) {
            value = v.mapValues { $0.value }
        } else {
            value = nil
        }
    }
}

// MARK: - WebSocket 客户端

/// 连接服务端 /ws/app，接收实时事件推送
/// 事件分发：通过回调通知各 View
@Observable
final class WebSocketClient {
    static let shared = WebSocketClient()

    // MARK: - 对外状态

    var isConnected: Bool = false
    var lastError: String? = nil
    var connectCount: Int = 0
    var lastEventReceivedAt: String = ""

    // MARK: - 事件回调

    /// status_update 事件（仪表盘状态变化）
    var onStatusUpdate: ((StatusInfo) -> Void)?
    /// new_message 事件（新会话消息）
    var onNewMessage: ((String, String, String) -> Void)?  // conversationId, role, content
    /// automation_run 事件（自动化运行状态）
    var onAutomationRun: ((String, String, String) -> Void)?  // id, name, status
    /// task_update 事件（任务状态变化）
    var onTaskUpdate: ((String, String) -> Void)?  // team, status
    /// screenshot 事件（新截图可用）
    var onScreenshot: ((Int64) -> Void)?
    /// agent_offline / agent_online 事件
    var onAgentOnlineChanged: ((Bool) -> Void)?
    /// log 事件（日志行）
    var onLog: ((String, String) -> Void)?  // level, msg

    // MARK: - 私有

    private var task: URLSessionWebSocketTask?
    private var session: URLSession?
    private var pingTimer: Timer?
    private var reconnectAttempts: Int = 0
    private var shouldRun: Bool = false
    private let settingsStore = SettingsStore.shared

    /// 连接代次，用于识别过期回调
    private var generation: Int = 0

    // MARK: - 连接管理

    func start() {
        shouldRun = true
        guard !isConnected else { return }
        if Thread.isMainThread {
            connect()
        } else {
            DispatchQueue.main.async { [weak self] in
                self?.connect()
            }
        }
    }

    func stop() {
        shouldRun = false
        if Thread.isMainThread {
            teardown()
        } else {
            DispatchQueue.main.async { [weak self] in
                self?.teardown()
            }
        }
    }

    private func teardown() {
        pingTimer?.invalidate()
        pingTimer = nil
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        session?.invalidateAndCancel()
        session = nil
        isConnected = false
    }

    /// 必须在主线程调用
    private func connect() {
        assert(Thread.isMainThread, "connect() must be on main thread")
        guard shouldRun else { return }
        let settings = settingsStore.settings
        guard settings.isLoggedIn, let token = settings.token, !token.isEmpty else { return }
        guard let url = buildWSURL(serverURL: settings.serverURL, token: token) else { return }

        teardown()
        generation += 1
        let gen = generation

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.waitsForConnectivity = true
        let session = URLSession(configuration: config)
        self.session = session
        let task = session.webSocketTask(with: url)
        self.task = task
        task.resume()

        isConnected = true
        reconnectAttempts = 0
        connectCount += 1
        lastError = nil

        receiveLoop(generation: gen)
        startPing()
    }

    private func reconnect() {
        guard shouldRun else { return }
        reconnectAttempts += 1
        // 指数退避，最大 60s
        let delay = min(pow(2.0, Double(reconnectAttempts)), 60.0)
        let attempts = reconnectAttempts
        let gen = generation
        print("[WSClient] reconnect in \(delay)s (attempt \(attempts))")
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self = self else { return }
            guard self.shouldRun else { return }
            guard self.generation == gen else {
                print("[WSClient] stale reconnect (gen \(gen), current \(self.generation)), skipping")
                return
            }
            self.connect()
        }
    }

    // MARK: - URL 构建

    /// http(s)://host:port → ws(s)://host:port/ws/app?token=xxx
    private func buildWSURL(serverURL: String, token: String) -> URL? {
        var s = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.hasPrefix("http://") { s = "ws://" + s.dropFirst(7) }
        else if s.hasPrefix("https://") { s = "wss://" + s.dropFirst(8) }
        else if !s.hasPrefix("ws://") && !s.hasPrefix("wss://") { s = "ws://" + s }
        if s.hasSuffix("/") { s.removeLast() }
        let encoded = token.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? token
        s += "/ws/app?token=\(encoded)"
        return URL(string: s)
    }

    // MARK: - 接收循环

    private func receiveLoop(generation gen: Int) {
        task?.receive { [weak self] result in
            guard let self = self else { return }
            DispatchQueue.main.async {
                guard self.generation == gen else {
                    print("[WSClient] stale receive callback (gen \(gen), current \(self.generation)), ignoring")
                    return
                }
                switch result {
                case .failure(let error):
                    self.isConnected = false
                    if self.shouldRun {
                        self.lastError = error.localizedDescription
                        print("[WSClient] receive error: \(error.localizedDescription)")
                        self.reconnect()
                    } else {
                        print("[WSClient] connection closed by stop(), ignoring error")
                    }
                case .success(let msg):
                    switch msg {
                    case .data(let data):
                        self.handleData(data)
                    case .string(let str):
                        if let data = str.data(using: .utf8) {
                            self.handleData(data)
                        }
                    @unknown default:
                        break
                    }
                    self.receiveLoop(generation: gen)
                }
            }
        }
    }

    private func handleData(_ data: Data) {
        guard let event = try? JSONDecoder().decode(WSEvent.self, from: data) else {
            print("[WSClient] failed to decode event: \(String(data: data, encoding: .utf8) ?? "")")
            return
        }

        // 记录最近收到事件时间
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        lastEventReceivedAt = formatter.string(from: Date())

        switch event.type {
        case "status_update":
            if let status = event.decodeData(StatusInfo.self) {
                onStatusUpdate?(status)
            }
        case "new_message":
            // data: { conversation_id, role, content, preview }
            if let dict = event.dataRaw as? [String: Any] {
                let convId = dict["conversation_id"] as? String ?? ""
                let role = dict["role"] as? String ?? ""
                let content = dict["content"] as? String ?? (dict["preview"] as? String ?? "")
                onNewMessage?(convId, role, content)
            }
        case "automation_run":
            // data: { id, name, status }
            if let dict = event.dataRaw as? [String: Any] {
                let id = dict["id"] as? String ?? ""
                let name = dict["name"] as? String ?? ""
                let status = dict["status"] as? String ?? ""
                onAutomationRun?(id, name, status)
            }
        case "task_update":
            // data: { team, task_id, status }
            if let dict = event.dataRaw as? [String: Any] {
                let team = dict["team"] as? String ?? ""
                let status = dict["status"] as? String ?? ""
                onTaskUpdate?(team, status)
            }
        case "screenshot":
            // data: { taken_at }
            var takenAt: Int64 = 0
            if let dict = event.dataRaw as? [String: Any] {
                if let n = dict["taken_at"] as? Int64 { takenAt = n }
                else if let n = dict["taken_at"] as? Int { takenAt = Int64(n) }
                else if let n = dict["taken_at"] as? Double { takenAt = Int64(n) }
                else if let s = dict["taken_at"] as? String, let n = Int64(s) { takenAt = n }
            }
            onScreenshot?(takenAt)
        case "agent_offline":
            onAgentOnlineChanged?(false)
        case "agent_online":
            onAgentOnlineChanged?(true)
        case "log":
            // data: { level, msg }
            if let dict = event.dataRaw as? [String: Any] {
                let level = dict["level"] as? String ?? "info"
                let msg = dict["msg"] as? String ?? ""
                onLog?(level, msg)
            }
        case "pong":
            break
        default:
            print("[WSClient] unknown event type: \(event.type)")
        }
    }

    // MARK: - 发送

    private func send(_ dict: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: dict),
              let str = String(data: data, encoding: .utf8) else { return }
        task?.send(.string(str)) { error in
            if let error = error {
                print("[WSClient] send error: \(error.localizedDescription)")
            }
        }
    }

    private func startPing() {
        pingTimer?.invalidate()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
            self?.send(["type": "ping"])
        }
    }
}
