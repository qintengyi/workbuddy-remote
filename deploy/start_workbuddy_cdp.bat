@echo off
REM WorkBuddy Remote - 带 CDP 调试端口启动 WorkBuddy
REM 用这个脚本启动后，agent 可以通过 CDP 直接 hook WorkBuddy 进程
REM 功能：实时读取会话消息、发送消息、监听状态变化

REM 关闭已运行的 WorkBuddy
taskkill /F /IM WorkBuddy.exe 2>nul

REM 等待 2 秒确保进程完全退出
timeout /t 2 /nobreak >nul

REM 带 remote-debugging-port 启动 WorkBuddy
start "" "D:\Program Files\WorkBuddy\WorkBuddy.exe" --remote-debugging-port=9222

echo WorkBuddy 已启动（CDP 端口 9222）
echo Agent 会自动检测并连接 CDP
