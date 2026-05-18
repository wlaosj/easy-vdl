#!/bin/bash
# =========================================
# Easy-VDL 前端开发服务器启动脚本
# =========================================

set -e

# 切换到脚本所在目录
cd "$(dirname "$0")"

echo "🚀 启动 Easy-VDL 前端开发服务器..."
echo ""
echo "📋 当前配置："
echo "   - 目录: $(pwd)"
echo "   - Node版本: $(node --version)"
echo "   - NPM版本: $(npm --version)"
echo ""

# 停止占用 5173 端口的旧进程
OLD_PID=$(lsof -ti:5173 2>/dev/null || true)
if [ -n "$OLD_PID" ]; then
    echo "🛑 检测到端口 5173 被占用，正在停止旧进程 (PID: $OLD_PID)..."
    kill -9 $OLD_PID 2>/dev/null || true
    sleep 1
    echo "✅ 旧进程已停止"
    echo ""
fi

# 检查 node_modules 是否存在
if [ ! -d "node_modules" ]; then
    echo "📦 检测到依赖未安装，正在安装..."
    npm install
    echo ""
fi

# 注意：已启用轮询模式，不再需要增加文件描述符限制
# 轮询模式会定期检查文件变化，而不是使用文件系统事件监听
# 这样可以避免 EMFILE: too many open files 错误

# 启动开发服务器
echo "🌐 启动 Vite 开发服务器..."
echo "   - 本地访问: http://localhost:5173"
echo "   - 按 Ctrl+C 停止服务器"
echo ""

npm run dev -- --host

