#!/bin/bash
# Easy-VDL Docker Hub README 推送脚本
# 复用 ~/.docker/config.json 的登录状态，无需额外输入密码
# 用法: ./dockerhub_sync_readme.sh
#       IMAGE_NAME=custom-repo ./dockerhub_sync_readme.sh

set -e

cd "$(dirname "$0")"

IMAGE_NAME="${IMAGE_NAME:-qq918652593/easy-vdl}"
README_FILE="README.md"
DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.docker/config.json}"

# 检查 README 文件
if [ ! -f "$README_FILE" ]; then
    echo "❌ 未找到 $README_FILE，请确保在仓库根目录运行此脚本"
    exit 1
fi

# 从 ~/.docker/config.json 读取 Docker Hub 登录信息
if [ ! -f "$DOCKER_CONFIG" ]; then
    echo "❌ 未找到 Docker 配置文件: $DOCKER_CONFIG"
    echo "   请先执行 docker login"
    exit 1
fi

AUTH=$(jq -r '.auths["https://index.docker.io/v1/"].auth // .auths["https://index.docker.io/v1/"]."auth" // empty' "$DOCKER_CONFIG")
if [ -z "$AUTH" ]; then
    # 尝试从 credential store 获取（macOS / Linux 桌面环境）
    echo "⚠️  config.json 中未找到内联凭证，尝试 credential helper..."
    STORE=$(jq -r '.credsStore // empty' "$DOCKER_CONFIG")
    if [ -n "$STORE" ] && command -v "docker-credential-$STORE" >/dev/null 2>&1; then
        CREDS=$(echo "https://index.docker.io/v1/" | "docker-credential-$STORE" get 2>/dev/null || true)
        if [ -n "$CREDS" ]; then
            USERNAME=$(echo "$CREDS" | jq -r '.Username')
            PASSWORD=$(echo "$CREDS" | jq -r '.Secret')
        fi
    fi
    if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
        echo "❌ 无法获取 Docker Hub 登录凭证，请先执行 docker login"
        exit 1
    fi
else
    # base64 解码获取用户名和密码
    DECODED=$(echo "$AUTH" | base64 -d 2>/dev/null || echo "")
    USERNAME="${DECODED%%:*}"
    PASSWORD="${DECODED#*:}"
fi

if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
    echo "❌ 无法解析 Docker Hub 登录凭证，请重新执行 docker login"
    exit 1
fi

# 获取 JWT Token
echo "🔑 正在获取 Docker Hub API Token..."
TOKEN=$(curl -s -H "Content-Type: application/json" \
    -X POST -d "{\"username\": \"${USERNAME}\", \"password\": \"${PASSWORD}\"}" \
    "https://hub.docker.com/v2/users/login/" | jq -r .token)

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
    echo "❌ API 登录失败"
    exit 1
fi

# 推送 README
echo "📤 正在推送 README 到 ${IMAGE_NAME}..."
RESPONSE=$(curl -s -X PATCH -H "Authorization: JWT $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"full_description\": $(jq -Rs . < "$README_FILE")}" \
    "https://hub.docker.com/v2/repositories/${IMAGE_NAME}/")

if echo "$RESPONSE" | jq -e '.full_description' > /dev/null 2>&1; then
    echo "✅ README 推送成功！"
else
    echo "⚠️  推送响应: $RESPONSE"
fi
