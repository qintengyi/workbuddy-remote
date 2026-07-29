import Foundation

// MARK: - 应用设置模型

/// 本地配置（持久化到 UserDefaults）
/// 仅保存服务器地址 + 登录 token + 用户名
struct AppSettings: Codable, Equatable {
    /// 服务器地址，如 http://192.168.1.8 或 https://workbuddy.example.com
    /// 注意：当前服务器 10372 被防火墙白名单拦截，请走 nginx 反代的 80/443
    var serverURL: String
    /// 登录 token
    var token: String?
    /// 上次登录用户名
    var username: String?

    static let `default` = AppSettings(
        serverURL: "http://192.168.1.8",
        token: nil,
        username: nil
    )

    var isLoggedIn: Bool {
        guard let token = token, !token.isEmpty else { return false }
        return true
    }
}

// MARK: - 本地配置管理

/// 管理 serverURL / token / username，持久化到 UserDefaults
final class SettingsStore {
    static let shared = SettingsStore()
    private let key = "cn.workbuddy.remote.settings"
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    var settings: AppSettings {
        get {
            guard let data = defaults.data(forKey: key),
                  let decoded = try? JSONDecoder().decode(AppSettings.self, from: data) else {
                return .default
            }
            return decoded
        }
        set {
            if let data = try? JSONEncoder().encode(newValue) {
                defaults.set(data, forKey: key)
            }
        }
    }

    func save(_ settings: AppSettings) {
        self.settings = settings
    }

    /// 保存登录 token
    func saveLogin(token: String, username: String) {
        var s = settings
        s.token = token
        s.username = username
        save(s)
    }

    /// 清除登录状态（退出登录）
    func clearLogin() {
        var s = settings
        s.token = nil
        save(s)
    }
}
