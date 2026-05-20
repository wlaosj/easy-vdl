#!/bin/bash

# Easy-VDL ARM64 专用构建和运行脚本

set -e

# 自动切换到脚本所在目录
cd "$(dirname "$0")"

STREAMGET_VENDOR_DIR="./_vendor_streamget-main"
DOCKERFILE="./Dockerfile.arm64"
PLATFORM="linux/arm64"

# 定义变量
CONTAINER_NAME="${CONTAINER_NAME:-easy-vdl-arm64}"
IMAGE_NAME="${IMAGE_NAME:-easy-vdl:arm64}"
# FFmpeg 使用 BtbN master 分支构建（Dockerfile 内置），此处无需额外参数

# ARM64 本地调试默认不混淆；生产发布可手动选择启用
ENABLE_OBFUSCATION="false"
REQUIRE_OBFUSCATION="false"

# ARM64 脚本默认使用独立端口，避免和 x86 本地容器冲突
FRONTEND_PORT="${FRONTEND_PORT:-5858}"
VNC_PORT="${VNC_PORT:-5901}"

# ARM 设备硬件加速差异较大，默认关闭；需要时可 ENABLE_DRI_MAPPING=true ./build_and_run_arm64.sh
ENABLE_DRI_MAPPING="${ENABLE_DRI_MAPPING:-false}"

# 安全配置 - 保持与本地调试脚本一致，支持环境变量覆盖
SNIFFER_LICENSE_KEY="${SNIFFER_LICENSE_KEY:-ETJWYP3DCMGYVD9DV1V0RRENI0LKBHM2}"
ADMIN_USERNAME="${EASY_VDL_ADMIN_USERNAME:-bigv}"
ADMIN_PASSWORD="${EASY_VDL_ADMIN_PASSWORD:-778421973}"

# 用户权限配置
PUID="${PUID:-1000}"
PGID="${PGID:-100}"
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

echo "🚀 开始构建 Easy-VDL ARM64 统一服务..."

if ! command -v docker >/dev/null 2>&1; then
    echo "❌ 未找到 docker 命令，请先安装并启动 Docker"
    exit 1
fi

if [ ! -f "$DOCKERFILE" ]; then
    echo "❌ 未找到 ARM64 Dockerfile: $DOCKERFILE"
    exit 1
fi

if ! docker buildx version >/dev/null 2>&1; then
    echo "❌ 当前 Docker 不支持 buildx，请升级 Docker 或启用 buildx"
    exit 1
fi

echo "📋 当前配置："
echo "   - Dockerfile: $DOCKERFILE"
echo "   - 平台: $PLATFORM"
echo "   - 镜像名称: $IMAGE_NAME"
echo "   - 容器名称: $CONTAINER_NAME"
echo "   - FFmpeg: BtbN master 分支（Dockerfile内置）"
echo "   - 万能嗅探密钥: ${SNIFFER_LICENSE_KEY:0:10}..."
echo "   - 管理员用户名: $ADMIN_USERNAME"
echo "   - 管理员密码: ${ADMIN_PASSWORD:0:3}******"
echo "   - PostgreSQL用户ID: $PUID"
echo "   - PostgreSQL组ID: $PGID"
echo "   - 内存限制: 4GB"
echo "   - Web端口: $FRONTEND_PORT"
echo "   - VNC端口: $VNC_PORT"
echo "   - /dev/dri 映射: $ENABLE_DRI_MAPPING"
echo "   - 构建版本: $BUILD_VERSION"
echo "   - 构建时间: $BUILD_TIME"
echo ""

echo ">>> 当前为 ARM64 本地调试构建脚本（默认不混淆）"
read -r -p ">>> 是否启用代码混淆构建（ARM64 首次建议先选 N）？[y/N]: " OBF_INPUT
case "$OBF_INPUT" in
    [yY]|[yY][eE][sS])
        ENABLE_OBFUSCATION="true"
        ;;
    *)
        ENABLE_OBFUSCATION="false"
        ;;
esac
REQUIRE_OBFUSCATION="$ENABLE_OBFUSCATION"
echo ">>> 混淆开关: ENABLE_OBFUSCATION=$ENABLE_OBFUSCATION"
echo ">>> 强制混淆校验: REQUIRE_OBFUSCATION=$REQUIRE_OBFUSCATION"
if [ "$ENABLE_OBFUSCATION" != "true" ]; then
    echo ">>> ⚠️ 当前将构建明文 ARM64 调试镜像（仅建议本地使用）"
fi

echo ">>> 正在停止并删除旧的 ARM64 容器 ($CONTAINER_NAME)..."
docker stop --time=30 "$CONTAINER_NAME" 2>/dev/null || true
sleep 2
docker rm "$CONTAINER_NAME" 2>/dev/null || true

echo ">>> 等待1秒，确保文件句柄已释放..."
sleep 1

echo ">>> 正在删除旧的 ARM64 镜像 ($IMAGE_NAME)..."
docker rmi "$IMAGE_NAME" 2>/dev/null || true

echo ">>> 校验 vendored streamget 源码..."
if [ ! -d "$STREAMGET_VENDOR_DIR" ]; then
    echo "❌ 未找到目录: $STREAMGET_VENDOR_DIR"
    echo "   请先将 streamget 源码放入该目录后再构建"
    exit 1
fi
if [ ! -f "$STREAMGET_VENDOR_DIR/pyproject.toml" ]; then
    echo "❌ vendored streamget 源码不完整（缺少 pyproject.toml）"
    exit 1
fi
echo "   ✅ 使用本地目录: $STREAMGET_VENDOR_DIR"

echo ">>> 正在从 $DOCKERFILE 构建 ARM64 镜像（buildx --load）..."
if [ "$ENABLE_OBFUSCATION" = "true" ]; then
    echo "    ✅ 启用混淆构建"
else
    echo "    ⚠️ 调试构建（不混淆）"
fi

docker buildx build \
    --platform "$PLATFORM" \
    --load \
    --build-arg ENABLE_OBFUSCATION="$ENABLE_OBFUSCATION" \
    --build-arg REQUIRE_OBFUSCATION="$REQUIRE_OBFUSCATION" \
    --build-arg BUILD_VERSION="$BUILD_VERSION" \
    --build-arg BUILD_TIME="$BUILD_TIME" \
    -f "$DOCKERFILE" \
    -t "$IMAGE_NAME" \
    .

echo ">>> 正在运行新的 ARM64 容器..."

DRI_OPTS=""
DRI_GROUPS=""
if [ "$ENABLE_DRI_MAPPING" != "true" ]; then
    echo "   ⚠ 已禁用 /dev/dri 映射（ENABLE_DRI_MAPPING=$ENABLE_DRI_MAPPING），将使用 CPU 编码"
elif [ -d "/dev/dri" ]; then
    DRI_OPTS="--device=/dev/dri:/dev/dri"
    RENDER_GID=$(stat -c '%g' /dev/dri/renderD128 2>/dev/null || echo "")
    if [ -n "$RENDER_GID" ]; then
        DRI_GROUPS="--group-add $RENDER_GID"
        echo "   ✓ 检测到 /dev/dri，已启用设备映射 (render GID: $RENDER_GID)"
    else
        echo "   ✓ 检测到 /dev/dri，已启用设备映射"
    fi
else
    echo "   ⚠ 未检测到 /dev/dri，将使用 CPU 编码"
fi

docker run -d \
    --platform "$PLATFORM" \
    --name "$CONTAINER_NAME" \
    --memory=4g \
    --memory-swap=4g \
    -p "$FRONTEND_PORT:$FRONTEND_PORT" \
    -p "$VNC_PORT:5900" \
    -v "$(pwd)/downloads:/app/downloads" \
    -v "$(pwd)/logs:/app/logs" \
    -v "$(pwd)/database:/app/database" \
    $DRI_OPTS \
    $DRI_GROUPS \
    -e SNIFFER_LICENSE_KEY="$SNIFFER_LICENSE_KEY" \
    -e EASY_VDL_PORT="$FRONTEND_PORT" \
    -e EASY_VDL_ADMIN_USERNAME="$ADMIN_USERNAME" \
    -e EASY_VDL_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    -e PUID="$PUID" \
    -e PGID="$PGID" \
    -e ENABLE_VNC=true \
    --restart always \
    "$IMAGE_NAME"

echo ">>> 正在验证容器状态..."
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    echo "❌ 错误: ARM64 容器未能正常启动，请检查日志:"
    docker logs "$CONTAINER_NAME"
    exit 1
fi

echo ">>> 正在验证 FFmpeg 版本..."
docker exec "$CONTAINER_NAME" sh -lc 'ffmpeg -hide_banner -version | head -1; ffmpeg -hide_banner -hwaccels | sed -n "1,12p"' || true

echo "✅ 完成！"
echo ""
echo "📋 服务信息："
echo "   - 容器名称: $CONTAINER_NAME"
echo "   - 镜像名称: $IMAGE_NAME"
echo "   - 平台: $PLATFORM"
echo "   - 访问地址: http://localhost:$FRONTEND_PORT"
echo "   - 端口映射: $FRONTEND_PORT:$FRONTEND_PORT, $VNC_PORT:5900 (VNC)"
echo "   - 本地下载目录: $(pwd)/downloads"
echo "   - 本地日志目录: $(pwd)/logs"
echo "   - 本地数据库目录: $(pwd)/database"
