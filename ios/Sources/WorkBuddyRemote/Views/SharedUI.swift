import Foundation
import SwiftUI

// MARK: - 日期格式化（北京时间）

enum DateUtil {
    /// 北京时间格式化器：yyyy-MM-dd HH:mm:ss
    static let beijingFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        f.locale = Locale(identifier: "zh_CN")
        return f
    }()

    static let beijingShortFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MM-dd HH:mm"
        f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        f.locale = Locale(identifier: "zh_CN")
        return f
    }()

    static let beijingTimeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        f.locale = Locale(identifier: "zh_CN")
        return f
    }()

    /// 将秒级时间戳格式化为北京时间字符串
    static func format(timestamp seconds: Int64?) -> String {
        guard let s = seconds, s > 0 else { return "-" }
        let date = Date(timeIntervalSince1970: TimeInterval(s))
        return beijingFormatter.string(from: date)
    }

    /// 短日期时间（MM-dd HH:mm）
    static func formatShort(timestamp seconds: Int64?) -> String {
        guard let s = seconds, s > 0 else { return "-" }
        let date = Date(timeIntervalSince1970: TimeInterval(s))
        return beijingShortFormatter.string(from: date)
    }

    /// 仅时间（HH:mm:ss）
    static func formatTime(timestamp seconds: Int64?) -> String {
        guard let s = seconds, s > 0 else { return "-" }
        let date = Date(timeIntervalSince1970: TimeInterval(s))
        return beijingTimeFormatter.string(from: date)
    }

    /// 相对时间（如 "刚刚"、"5 分钟前"）
    static func relative(timestamp seconds: Int64?) -> String {
        guard let s = seconds, s > 0 else { return "-" }
        let date = Date(timeIntervalSince1970: TimeInterval(s))
        let interval = Date().timeIntervalSince(date)
        if interval < 60 { return "刚刚" }
        if interval < 3600 { return "\(Int(interval / 60)) 分钟前" }
        if interval < 86400 { return "\(Int(interval / 3600)) 小时前" }
        if interval < 86400 * 7 { return "\(Int(interval / 86400)) 天前" }
        return format(timestamp: seconds)
    }
}

// MARK: - 卡片容器修饰器

struct CardBackground: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(16)
            .background(Color(.secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

extension View {
    /// 应用 iOS 18 风格卡片背景
    func cardStyle() -> some View {
        modifier(CardBackground())
    }
}

// MARK: - 状态徽章

struct StatusBadge: View {
    let online: Bool
    let onlineText: String
    let offlineText: String

    init(online: Bool, onlineText: String = "在线", offlineText: String = "离线") {
        self.online = online
        self.onlineText = onlineText
        self.offlineText = offlineText
    }

    var body: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(online ? Color.green : Color.red)
                .frame(width: 8, height: 8)
            Text(online ? onlineText : offlineText)
                .font(.caption)
                .foregroundStyle(online ? .green : .red)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background((online ? Color.green : Color.red).opacity(0.12))
        .clipShape(Capsule())
    }
}

// MARK: - 加载视图

struct LoadingView: View {
    var text: String = "加载中..."

    var body: some View {
        VStack(spacing: 8) {
            ProgressView()
                .controlSize(.large)
            Text(text)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
    }
}

// MARK: - 错误视图

struct ErrorView: View {
    let message: String
    let retryAction: (() -> Void)?

    init(message: String, retryAction: (() -> Void)? = nil) {
        self.message = message
        self.retryAction = retryAction
    }

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 40))
                .foregroundStyle(.orange)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            if let retryAction = retryAction {
                Button("重试", action: retryAction)
                    .buttonStyle(.bordered)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(32)
    }
}

// MARK: - 空状态视图

struct EmptyStateView: View {
    let icon: String
    let title: String
    let description: String?

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 40))
                .foregroundStyle(.secondary)
            Text(title)
                .font(.headline)
            if let desc = description {
                Text(desc)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(32)
    }
}

// MARK: - 自动化状态颜色

enum AutomationStatusStyle {
    static func color(_ status: String?) -> Color {
        switch (status ?? "").uppercased() {
        case "ACTIVE": return .green
        case "PAUSED": return .orange
        default: return .secondary
        }
    }

    static func text(_ status: String?) -> String {
        switch (status ?? "").uppercased() {
        case "ACTIVE": return "运行中"
        case "PAUSED": return "已暂停"
        default: return status ?? "未知"
        }
    }
}

// MARK: - 运行记录状态

enum RunStatusStyle {
    static func color(_ status: String?) -> Color {
        switch (status ?? "").lowercased() {
        case "running": return .blue
        case "completed": return .green
        case "failed": return .red
        case "pending": return .orange
        default: return .secondary
        }
    }

    static func text(_ status: String?) -> String {
        switch (status ?? "").lowercased() {
        case "running": return "运行中"
        case "completed": return "已完成"
        case "failed": return "失败"
        case "pending": return "等待中"
        default: return status ?? "未知"
        }
    }
}

// MARK: - 任务状态颜色

enum TaskStatusStyle {
    static func color(_ status: String?) -> Color {
        switch (status ?? "").lowercased() {
        case "pending": return .orange
        case "in_progress", "inprogress": return .blue
        case "completed": return .green
        case "deleted": return .red
        default: return .secondary
        }
    }
}

// MARK: - 日志级别颜色

enum LogLevelStyle {
    static func color(_ level: String?) -> Color {
        switch (level ?? "info").lowercased() {
        case "error", "fatal": return .red
        case "warning", "warn": return .orange
        case "info": return .blue
        case "debug": return .secondary
        default: return .primary
        }
    }
}
