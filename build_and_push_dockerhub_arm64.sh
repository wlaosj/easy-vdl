#!/bin/bash
# 构建并上传 Easy-VDL ARM64 镜像到 DockerHub
# 镜像名: qq918652593/easy-vdl:arm64

set -e

# 自动切换到脚本所在目录
cd "$(dirname "$0")"

STREAMGET_VENDOR_DIR="./_vendor_streamget-main"
DOCKERFILE="./Dockerfile.arm64"
PLATFORM="${PLATFORM:-linux/arm64}"

IMAGE_NAME="${IMAGE_NAME:-qq918652593/easy-vdl}"
TAG="${TAG:-arm64}"
# FFmpeg 使用 BtbN master 分支构建（Dockerfile 内置），此处无需额外参数
ENABLE_OBFUSCATION="${ENABLE_OBFUSCATION:-true}"
VERSION_FILE="${VERSION_FILE:-build-version.env}"

if [ -f "$VERSION_FILE" ]; then
    # shellcheck disable=SC1090
    . "$VERSION_FILE"
    echo "📦 使用版本文件: $VERSION_FILE"
else
    BUILD_VERSION="${BUILD_VERSION:-v$(date '+%Y%m%d.%H%M%S')}"
    BUILD_TIME="${BUILD_TIME:-$(date '+%Y-%m-%d %H:%M:%S')}"
    echo "📦 未找到版本文件，使用临时构建版本"
fi
echo "   - BUILD_VERSION: $BUILD_VERSION"
echo "   - BUILD_TIME: $BUILD_TIME"

echo "[0/3] 校验 ARM64 构建环境..."
if ! command -v docker >/dev/null 2>&1; then
    echo "❌ 未找到 docker 命令，请先安装并启动 Docker"
    exit 1
fi
if ! docker buildx version >/dev/null 2>&1; then
    echo "❌ 当前 Docker 不支持 buildx，请升级 Docker 或启用 buildx"
    exit 1
fi
if [ ! -f "$DOCKERFILE" ]; then
    echo "❌ 未找到 Dockerfile: $DOCKERFILE"
    exit 1
fi
if [ ! -d "$STREAMGET_VENDOR_DIR" ]; then
    echo "❌ 未找到目录: $STREAMGET_VENDOR_DIR"
    echo "   请先将 streamget 源码放入该目录后再构建"
    exit 1
fi
if [ ! -f "$STREAMGET_VENDOR_DIR/pyproject.toml" ]; then
    echo "❌ vendored streamget 源码不完整（缺少 pyproject.toml）"
    exit 1
fi

echo "   - Dockerfile: $DOCKERFILE"
echo "   - 平台: $PLATFORM"
echo "   - 镜像: $IMAGE_NAME:$TAG"
echo "   - FFmpeg: BtbN master 分支（Dockerfile内置）"
echo "   - 混淆: $ENABLE_OBFUSCATION"

echo "[1/3] 确认 DockerHub 登录状态..."
if ! docker info 2>/dev/null | grep -q "Username:"; then
    echo "⚠️ 未检测到 DockerHub 登录信息；如果推送失败，请先执行: docker login"
fi

echo "[2/3] 构建并推送 ARM64 镜像..."
docker buildx build \
    --platform "$PLATFORM" \
    --build-arg ENABLE_OBFUSCATION="$ENABLE_OBFUSCATION" \
    # --build-arg FFMPEG_RELEASE_BRANCH 已移除，Dockerfile 直接使用 master 分支
    --build-arg BUILD_VERSION="$BUILD_VERSION" \
    --build-arg BUILD_TIME="$BUILD_TIME" \
    -f "$DOCKERFILE" \
    -t "$IMAGE_NAME:$TAG" \
    --push \
    .

echo "[3/3] 推送完成"
echo "✅ ARM64 镜像已成功推送到 DockerHub: $IMAGE_NAME:$TAG"
