import SwiftUI
import Observation

// MARK: - 登录 ViewModel

@Observable
final class LoginViewModel {
    var serverURL: String
    var username: String
    var password: String = ""
    var isLoggingIn: Bool = false
    var errorMessage: String?
    var showError: Bool = false

    private let store = SettingsStore.shared
    private let api = WorkBuddyAPI.shared
    var appState: AppStateManager?

    init() {
        let settings = store.settings
        self.serverURL = settings.serverURL
        self.username = settings.username ?? "admin"
    }

    var canLogin: Bool {
        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedUser = username.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmedURL.isEmpty && !trimmedUser.isEmpty && !password.isEmpty && !isLoggingIn
    }

    func login() async {
        isLoggingIn = true
        defer { isLoggingIn = false }

        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedUser = username.trimmingCharacters(in: .whitespacesAndNewlines)

        // 先保存服务器地址
        var settings = store.settings
        settings.serverURL = trimmedURL
        store.save(settings)

        do {
            let token = try await api.login(
                username: trimmedUser,
                password: password,
                serverURL: trimmedURL
            )
            store.saveLogin(token: token, username: trimmedUser)
            password = ""
            await appState?.onLoginSuccess()
        } catch let err as APIError {
            errorMessage = err.errorDescription ?? "登录失败"
            showError = true
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }
}

// MARK: - 登录视图

struct LoginView: View {
    @Environment(AppStateManager.self) private var appState
    @State private var vm = LoginViewModel()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    // Logo 区域
                    VStack(spacing: 12) {
                        ZStack {
                            Circle()
                                .fill(Color.blue.opacity(0.12))
                                .frame(width: 80, height: 80)
                            Image(systemName: "macwindow.on.rectangle")
                                .font(.system(size: 36))
                                .foregroundStyle(.blue)
                        }
                        Text("WorkBuddy Remote")
                            .font(.title2.bold())
                        Text("远程查看/控制书房电脑")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.top, 20)

                    // 服务器地址
                    VStack(alignment: .leading, spacing: 6) {
                        Text("服务器地址")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        TextField("http://192.168.1.8", text: $vm.serverURL)
                            .textFieldStyle(.roundedBorder)
                            .keyboardType(.URL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                    .padding(.horizontal, 4)

                    // 用户名
                    VStack(alignment: .leading, spacing: 6) {
                        Text("用户名")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        TextField("用户名", text: $vm.username)
                            .textFieldStyle(.roundedBorder)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                    .padding(.horizontal, 4)

                    // 密码
                    VStack(alignment: .leading, spacing: 6) {
                        Text("密码")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        SecureField("密码", text: $vm.password)
                            .textFieldStyle(.roundedBorder)
                            .submitLabel(.go)
                            .onSubmit {
                                if vm.canLogin {
                                    Task { await vm.login() }
                                }
                            }
                    }
                    .padding(.horizontal, 4)

                    // 登录按钮
                    Button {
                        Task { await vm.login() }
                    } label: {
                        HStack {
                            if vm.isLoggingIn {
                                ProgressView()
                                    .tint(.white)
                                    .padding(.trailing, 4)
                            }
                            Text(vm.isLoggingIn ? "登录中..." : "登录")
                                .font(.headline)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(vm.canLogin ? Color.blue : Color.gray.opacity(0.3))
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                    .disabled(!vm.canLogin)
                    .padding(.horizontal, 4)

                    // 提示信息
                    VStack(alignment: .leading, spacing: 6) {
                        Label("默认账号 admin / qty8520123", systemImage: "info.circle")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Label("地址填 http://192.168.1.8（不要带 :10372）", systemImage: "network")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Label("10372 被防火墙拦截，已用 80 端口反代", systemImage: "exclamationmark.shield")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                    .padding(.horizontal, 8)

                    Spacer(minLength: 20)
                }
                .padding(.horizontal, 24)
            }
            .navigationTitle("登录")
            .navigationBarTitleDisplayMode(.inline)
            .alert("登录失败", isPresented: $vm.showError, actions: {
                Button("好") {}
            }, message: {
                Text(vm.errorMessage ?? "")
            })
            .onAppear {
                vm.appState = appState
            }
        }
    }
}

#Preview {
    LoginView()
        .environment(AppStateManager())
}
