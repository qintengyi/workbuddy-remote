import SwiftUI
import Observation

// MARK: - 设置 ViewModel

@Observable
final class SettingsViewModel {
    var serverURL: String
    var isTesting: Bool = false
    var showAlert: Bool = false
    var alertTitle: String = ""
    var alertMessage: String = ""
    var showLogoutConfirm: Bool = false

    private let store = SettingsStore.shared
    private let api = WorkBuddyAPI.shared
    var appState: AppStateManager?

    init() {
        let settings = store.settings
        self.serverURL = settings.serverURL
    }

    func save() {
        let trimmed = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        var settings = store.settings
        settings.serverURL = trimmed
        store.save(settings)
        alertTitle = "已保存"
        alertMessage = "服务器地址已保存。"
        showAlert = true
    }

    func testConnection() async {
        isTesting = true
        defer { isTesting = false }
        let trimmed = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        var settings = store.settings
        settings.serverURL = trimmed
        store.save(settings)

        let ok = await api.checkHealth()
        if ok {
            alertTitle = "连接成功"
            alertMessage = "服务器可达且认证有效。"
        } else {
            alertTitle = "连接失败"
            alertMessage = "无法连接服务器或 token 无效，请检查地址与登录状态。"
        }
        showAlert = true
    }

    func logout() {
        appState?.logout()
    }
}

// MARK: - 设置视图

struct SettingsView: View {
    @Environment(AppStateManager.self) private var appState
    @State private var vm = SettingsViewModel()

    var body: some View {
        Form {
            Section {
                TextField("http://192.168.1.8:10372", text: $vm.serverURL)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            } header: {
                Text("服务器地址")
            } footer: {
                Text("WorkBuddy Remote 服务端地址，可填局域网 IP 或反代域名（含端口）。")
            }

            Section {
                Button {
                    vm.save()
                } label: {
                    Label("保存设置", systemImage: "checkmark.circle.fill")
                        .frame(maxWidth: .infinity)
                }

                Button {
                    Task { await vm.testConnection() }
                } label: {
                    HStack {
                        if vm.isTesting {
                            ProgressView()
                                .padding(.trailing, 4)
                        }
                        Label(vm.isTesting ? "测试中..." : "测试连接", systemImage: "antenna.radiowaves.left.and.right")
                    }
                    .frame(maxWidth: .infinity)
                }
                .disabled(vm.isTesting)
            }

            Section {
                if let username = SettingsStore.shared.settings.username {
                    HStack {
                        Image(systemName: "person.circle.fill")
                            .foregroundStyle(.blue)
                        Text(username)
                            .font(.body)
                        Spacer()
                        Text("已登录")
                            .font(.caption)
                            .foregroundStyle(.green)
                    }
                }

                Button(role: .destructive) {
                    vm.showLogoutConfirm = true
                } label: {
                    Label("退出登录", systemImage: "rectangle.portrait.and.arrow.right")
                        .frame(maxWidth: .infinity)
                }
            } header: {
                Text("账号")
            }

            Section {
                HStack {
                    Text("WS 连接")
                    Spacer()
                    Text(appState.webSocketClient.isConnected ? "已连接" : "未连接")
                        .foregroundStyle(appState.webSocketClient.isConnected ? .green : .red)
                }
                HStack {
                    Text("WS 连接次数")
                    Spacer()
                    Text("\(appState.webSocketClient.connectCount)")
                        .foregroundStyle(.secondary)
                }
                if let err = appState.webSocketClient.lastError, !err.isEmpty {
                    HStack {
                        Text("WS 错误")
                        Spacer()
                        Text(err)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .lineLimit(2)
                    }
                }
                if !appState.webSocketClient.lastEventReceivedAt.isEmpty {
                    HStack {
                        Text("最近事件")
                        Spacer()
                        Text(appState.webSocketClient.lastEventReceivedAt)
                            .foregroundStyle(.secondary)
                    }
                }
            } header: {
                Text("连接状态")
            } footer: {
                Text("WebSocket 实时事件通道，用于推送状态变化、新消息、自动化运行等事件。")
            }

            Section {
                HStack {
                    Text("版本")
                    Spacer()
                    Text("1.0 (1)")
                        .foregroundStyle(.secondary)
                }
                HStack {
                    Text("Bundle ID")
                    Spacer()
                    Text("cn.workbuddy.remote")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("关于")
            }

            Section {
                Text("通过卧室 iPhone 远程查看/控制书房 Windows 电脑上运行的 WorkBuddy 桌面应用。服务端默认监听 0.0.0.0:10372，建议通过 nginx 反代后启用 HTTPS。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } header: {
                Text("说明")
            }
        }
        .scrollContentBackground(.hidden)
        .background(Color(.systemGroupedBackground))
        .navigationTitle("设置")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.bar, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .alert(vm.alertTitle, isPresented: $vm.showAlert, actions: {
            Button("好") {}
        }, message: {
            Text(vm.alertMessage)
        })
        .alert("退出登录", isPresented: $vm.showLogoutConfirm, actions: {
            Button("取消", role: .cancel) {}
            Button("退出", role: .destructive) {
                vm.logout()
            }
        }, message: {
            Text("退出后将返回登录页面，需要重新输入用户名和密码。")
        })
        .onAppear {
            vm.appState = appState
        }
    }
}

#Preview {
    NavigationStack {
        SettingsView()
            .environment(AppStateManager())
    }
}
