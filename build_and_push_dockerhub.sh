#!/bin/bash
# 构建并上传 easy-vdl 镜像到 DockerHub
# 默认镜像名: qq918652593/easy-vdl:latest
# 测试推送示例: TAG=test ./build_and_push_dockerhub.sh

set -e

# 自动切换到脚本所在目录
cd "$(dirname "$0")"

STREAMGET_VENDOR_DIR="./_vendor_streamget-main"

IMAGE_NAME="qq918652593/easy-vdl"
TAG="${TAG:-latest}"
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

# 直接使用 vendored streamget 源码（不依赖 ../streamget-main）
echo "[0/2] 校验 vendored streamget 源码..."
if [ ! -d "$STREAMGET_VENDOR_DIR" ]; then
    echo "❌ 未找到目录: $STREAMGET_VENDOR_DIR"
    echo "   请先将 streamget 源码放入该目录后再构建"
    exit 1
fi
if [ ! -f "$STREAMGET_VENDOR_DIR/pyproject.toml" ]; then
    echo "❌ vendored streamget 源码不完整（缺少 pyproject.toml）"
    exit 1
fi

# 构建镜像
echo "[1/2] 开始构建 Docker 镜像..."
docker build \
    --build-arg ENABLE_OBFUSCATION=true \
    --build-arg BUILD_VERSION="$BUILD_VERSION" \
    --build-arg BUILD_TIME="$BUILD_TIME" \
    -t $IMAGE_NAME:$TAG \
    .

echo "[2/2] 推送镜像到 DockerHub..."
docker push $IMAGE_NAME:$TAG

echo "✅ 镜像已成功推送到 DockerHub: $IMAGE_NAME:$TAG" 
