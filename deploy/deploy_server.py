"""
部署 WorkBuddy Remote 服务端到 192.168.1.8

用法：
    C:\\Users\\Administrator\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe deploy/deploy_server.py

流程：
1. SSH 连接 192.168.1.8:22 (root/qty8520123)
2. 创建 /www/wwwroot/workbuddy-remote/
3. 上传 server/ 全部文件
4. 在服务器创建 venv 并 pip install -r requirements.txt
5. 安装 systemd unit，enable + start
6. 首次启动读取 AGENT_TOKEN 并打印
"""
import paramiko
import os
import sys
import stat

SSH_HOST = "192.168.1.8"
SSH_PORT = 22
SSH_USER = "root"
SSH_PASS = "qty8520123"
REMOTE_BASE = "/www/wwwroot/workbuddy-remote"
REMOTE_SERVER = f"{REMOTE_BASE}/server"

LOCAL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_SERVER = os.path.join(LOCAL_ROOT, "server")
LOCAL_DEPLOY = os.path.join(LOCAL_ROOT, "deploy")


def ssh_exec(ssh, cmd, timeout=120):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(f"[stderr] {err.rstrip()}")
    print(f"[exit={rc}]")
    return rc, out, err


def sftp_mkdirs(sftp, remote_dir):
    parts = remote_dir.strip("/").split("/")
    cur = ""
    for p in parts:
        cur = f"{cur}/{p}"
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)
            print(f"  mkdir {cur}")


def sftp_put_dir(sftp, local_dir, remote_dir, exclude=("__pycache__", ".pyc", "data.db", "config.json", "static")):
    for item in os.listdir(local_dir):
        if any(ex in item for ex in exclude):
            continue
        local_path = os.path.join(local_dir, item)
        remote_path = f"{remote_dir}/{item}"
        if os.path.isdir(local_path):
            try:
                sftp.stat(remote_path)
            except FileNotFoundError:
                sftp.mkdir(remote_path)
            sftp_put_dir(sftp, local_path, remote_path, exclude)
        else:
            print(f"  upload {local_path} -> {remote_path}")
            sftp.put(local_path, remote_path)


def main():
    print(f"=== WorkBuddy Remote Server Deployment ===")
    print(f"Target: {SSH_USER}@{SSH_HOST}:{SSH_PORT} -> {REMOTE_BASE}")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\nConnecting to {SSH_HOST}:{SSH_PORT}...")
    ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=15)
    print("Connected.")

    # 1. 检查 python3
    rc, out, _ = ssh_exec(ssh, "python3 --version")
    if rc != 0:
        print("ERROR: python3 not found on server")
        sys.exit(1)

    # 2. 创建目录
    sftp = ssh.open_sftp()
    sftp_mkdirs(sftp, REMOTE_SERVER)
    sftp_mkdirs(sftp, f"{REMOTE_SERVER}/static")

    # 3. 上传 server/ 文件
    print(f"\n=== Uploading server/ files ===")
    sftp_put_dir(sftp, LOCAL_SERVER, REMOTE_SERVER)

    # 4. 上传 systemd unit
    print(f"\n=== Uploading systemd unit ===")
    local_unit = os.path.join(LOCAL_DEPLOY, "workbuddy-remote.service")
    remote_unit = "/etc/systemd/system/workbuddy-remote.service"
    sftp.put(local_unit, remote_unit)
    sftp.chmod(remote_unit, 0o644)
    sftp.close()

    # 5. 创建 venv + 装依赖
    print(f"\n=== Setting up Python venv + dependencies ===")
    ssh_exec(ssh, f"python3 -m venv {REMOTE_BASE}/venv")
    ssh_exec(ssh, f"{REMOTE_BASE}/venv/bin/pip install --upgrade pip")
    ssh_exec(ssh, f"{REMOTE_BASE}/venv/bin/pip install -r {REMOTE_SERVER}/requirements.txt", timeout=180)

    # 6. 修正 systemd unit 里的 python 路径（用 venv 的 python）
    fix_cmd = f"""sed -i 's|ExecStart=/usr/bin/python3 {REMOTE_SERVER}/main.py|ExecStart={REMOTE_BASE}/venv/bin/python {REMOTE_SERVER}/main.py|' /etc/systemd/system/workbuddy-remote.service"""
    ssh_exec(ssh, fix_cmd)

    # 7. 停止旧服务（如果在跑）+ reload + enable + start
    print(f"\n=== Installing + starting systemd service ===")
    ssh_exec(ssh, "systemctl daemon-reload")
    ssh_exec(ssh, "systemctl stop workbuddy-remote.service 2>/dev/null; true")
    ssh_exec(ssh, "systemctl enable workbuddy-remote.service")
    ssh_exec(ssh, "systemctl start workbuddy-remote.service")

    # 8. 检查状态
    import time
    time.sleep(3)
    print(f"\n=== Service status ===")
    ssh_exec(ssh, "systemctl is-active workbuddy-remote.service")
    ssh_exec(ssh, "systemctl status workbuddy-remote.service --no-pager -l | head -20")

    # 9. 读取 AGENT_TOKEN（首次启动生成）
    print(f"\n=== Reading AGENT_TOKEN ===")
    ssh_exec(ssh, f"cat {REMOTE_SERVER}/config.json 2>/dev/null || echo 'config.json not yet created'")

    # 10. 端口监听检查
    print(f"\n=== Port 10372 check ===")
    ssh_exec(ssh, "ss -tlnp | grep 10372 || echo 'port 10372 not listening yet'")

    ssh.close()
    print(f"\n=== Deployment complete ===")
    print(f"Server: http://{SSH_HOST}:10372")
    print(f"Login: admin / qty8520123")
    print(f"Check AGENT_TOKEN above and fill it into agent/config.json")


if __name__ == "__main__":
    main()
