#!/bin/bash

# Easy-VDL 统一服务构建和运行脚本

set -e

# 自动切换到脚本所在目录
cd "$(dirname "$0")"

# 构建上下文内的 vendored streamget 源码目录（必须预先准备）
STREAMGET_VENDOR_DIR="./_vendor_streamget-main"

# 定义变量
CONTAINER_NAME="easy-vdl"
IMAGE_NAME="qq918652593/easy-vdl"  # 修改为完整的镜像名称
# 是否启用代码混淆（运行时交互选择，默认 false）
# 注意：这是本地调试脚本，默认不混淆；生产发布请使用 push 脚本（固定启用混淆）
ENABLE_OBFUSCATION="false"
# 前端(网页)端口，传入容器作为 EASY_VDL_PORT，默认 888
FRONTEND_PORT=5858
# 是否启用 /dev/dri 核显映射（true/false）。用于测试可临时关闭。
ENABLE_DRI_MAPPING="${ENABLE_DRI_MAPPING:-true}"
# 安全配置 - 直接在脚本中设置API密钥
SNIFFER_LICENSE_KEY="ETJWYP3DCMGYVD9DV1V0RRENI0LKBHM2"    # 内测功能授权密钥

# 管理员账号配置 - 支持环境变量覆盖
ADMIN_USERNAME="${EASY_VDL_ADMIN_USERNAME:-bigv}"          # 管理员用户名，默认 admin
ADMIN_PASSWORD="${EASY_VDL_ADMIN_PASSWORD:-778421973}"    # 管理员密码，默认 admin123456

# 用户权限配置 - 强制设置为正确值
PUID="1000"                                                # PostgreSQL用户ID，固定1000
PGID="100"                                                # PostgreSQL组ID，固定1001
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

echo "🚀 开始构建 Easy-VDL 统一服务..."

# 显示配置信息
echo "📋 当前配置："
echo "   - 万能嗅探密钥: ${SNIFFER_LICENSE_KEY:0:10}..."
echo "   - 管理员用户名: $ADMIN_USERNAME"
echo "   - 管理员密码: ${ADMIN_PASSWORD:0:3}******"
echo "   - PostgreSQL用户ID: $PUID"
echo "   - PostgreSQL组ID: $PGID"
echo "   - 内存限制: 4GB"
echo "   - 核显映射开关: $ENABLE_DRI_MAPPING"
echo "   - 构建版本: $BUILD_VERSION"
echo "   - 构建时间: $BUILD_TIME"
echo ""
echo "🔍 调试信息："
echo "   - 原始环境变量 PUID: '${PUID}'"
echo "   - 原始环境变量 PGID: '${PGID}'"
echo "   - 传递给容器的 PUID: '$PUID'"
echo "   - 传递给容器的 PGID: '$PGID'"
echo "   - 镜像名称: $IMAGE_NAME"

# 运行时选择是否开启代码混淆（默认关闭，用于本地调试）
echo ">>> 当前为本地调试构建脚本（默认不混淆）"
echo ">>> 生产发布请使用: ./build_and_push_dockerhub.sh"
echo ">>> 测试推送请使用: TAG=test ./build_and_push_dockerhub.sh"
read -r -p ">>> 是否启用代码混淆构建（调试场景可选）？[y/N]: " OBF_INPUT
case "$OBF_INPUT" in
    [yY]|[yY][eE][sS])
        ENABLE_OBFUSCATION="true"
        ;;
    *)
        ENABLE_OBFUSCATION="false"
        ;;
esac
echo ">>> 混淆开关: ENABLE_OBFUSCATION=$ENABLE_OBFUSCATION"
if [ "$ENABLE_OBFUSCATION" != "true" ]; then
    echo ">>> ⚠️ 当前将构建明文调试镜像（仅建议本地使用）"
fi


# 1. 停止并删除同名容器（如果存在）
echo ">>> 正在停止并删除旧的容器 ($CONTAINER_NAME)..."
docker stop --time=30 $CONTAINER_NAME 2>/dev/null || true
sleep 2
docker rm $CONTAINER_NAME 2>/dev/null || true

# 添加短暂延时，确保Docker守护进程完全释放文件句柄
echo ">>> 等待1秒，确保文件句柄已释放..."
sleep 1

# 2. 删除旧的镜像（如果存在）
echo ">>> 正在删除旧的镜像 ($IMAGE_NAME)..."
docker rmi $IMAGE_NAME 2>/dev/null || true

# 直接使用 vendored streamget 源码（不依赖 ../streamget-main）
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

# 3. 构建新的 Docker 镜像（根据运行时选择是否启用混淆）
echo ">>> 正在从 Dockerfile 构建新镜像（使用 BuildKit）..."
if [ "$ENABLE_OBFUSCATION" = "true" ]; then
    echo "    ✅ 启用混淆构建"
else
    echo "    ⚠️ 调试构建（不混淆）"
fi
DOCKER_BUILDKIT=1 docker build \
    --build-arg ENABLE_OBFUSCATION="$ENABLE_OBFUSCATION" \
    --build-arg BUILD_VERSION="$BUILD_VERSION" \
    --build-arg BUILD_TIME="$BUILD_TIME" \
    -t $IMAGE_NAME \
    .

# 4. 运行新的 Docker 容器
echo ">>> 正在运行新的容器..."

# 检查 /dev/dri 是否存在（核显设备）
DRI_OPTS=""
DRI_GROUPS=""
GPU_PERF_OPTS=""
if [ "$ENABLE_DRI_MAPPING" != "true" ]; then
    echo "   ⚠ 已禁用核显映射（ENABLE_DRI_MAPPING=$ENABLE_DRI_MAPPING），将使用 CPU 编码"
elif [ -d "/dev/dri" ]; then
    # 使用 --device 将 /dev/dri 映射为设备（与 Jellyfin 相同的工作方式）
    DRI_OPTS="--device=/dev/dri:/dev/dri"
    # 获取 render 设备的组 ID 并加入容器进程的附加组
    RENDER_GID=$(stat -c '%g' /dev/dri/renderD128 2>/dev/null || echo "")
    if [ -n "$RENDER_GID" ]; then
        DRI_GROUPS="--group-add $RENDER_GID"
        echo "   ✓ 检测到核显设备 (/dev/dri)，已启用硬件加速支持 (render GID: $RENDER_GID)"
    else
        echo "   ✓ 检测到核显设备 (/dev/dri)，已启用硬件加速支持"
    fi

    # GPU 实时监控权限（用于 intel_gpu_top 访问 PMU）
    # 说明：
    # - PERFMON: 允许 perf 采样（新内核）
    # - seccomp=unconfined: 放行 perf_event_open（默认 seccomp 常会拦截）
    GPU_PERF_OPTS="--cap-add PERFMON --security-opt seccomp=unconfined"
    echo "   ✓ 已启用 GPU 监控权限: PERFMON + seccomp=unconfined"
else
    echo "   ⚠ 未检测到核显设备 (/dev/dri)，将使用 CPU 编码"
fi

docker run -d \
    --name $CONTAINER_NAME \
    --memory=4g \
    --memory-swap=4g \
    -p $FRONTEND_PORT:$FRONTEND_PORT \
    -p 5900:5900 \
    -v "$(pwd)/downloads:/app/downloads" \
    -v "$(pwd)/logs:/app/logs" \
    -v "$(pwd)/database:/app/database" \
    $DRI_OPTS \
    $DRI_GROUPS \
    $GPU_PERF_OPTS \
    -e SNIFFER_LICENSE_KEY="$SNIFFER_LICENSE_KEY" \
    -e EASY_VDL_PORT="$FRONTEND_PORT" \
    -e PUID="$PUID" \
    -e PGID="$PGID" \
    -e ENABLE_VNC=true \
    --restart always \
    $IMAGE_NAME

# 5. 验证容器是否正常运行
echo ">>> 正在验证容器状态..."
if ! docker ps | grep -q $CONTAINER_NAME; then
    echo "❌ 错误: 容器未能正常启动，请检查日志:"
    docker logs $CONTAINER_NAME
    exit 1
fi

echo "✅ 完成！"
echo ""
echo "📋 服务信息："
echo "   - 容器名称: $CONTAINER_NAME"
echo "   - 镜像名称: $IMAGE_NAME"
echo "   - 访问地址: http://localhost:$FRONTEND_PORT"
echo "   - 端口映射: $FRONTEND_PORT:$FRONTEND_PORT, 5900:5900 (VNC)"
echo "   - 本地下载目录: $(pwd)/downloads"
echo "   - 本地日志目录: $(pwd)/logs"
echo "   - 本地数据库目录: $(pwd)/database"
