# Easy-VDL 统一服务 Dockerfile (多阶段构建优化版)
#
# 构建参数:
# - ENABLE_OBFUSCATION: 是否启用代码混淆 (true/false，默认 true)
#   注意：生产默认开启混淆；本地调试请显式传递 false
# 
# 构建命令:
# 1. 生产发布（启用混淆，必须）:
#    DOCKER_BUILDKIT=1 docker build --build-arg ENABLE_OBFUSCATION=true -t easy-vdl .
#   或使用发布脚本: ./build_and_push_dockerhub.sh
#
# 2. 本地调试（禁用混淆，默认）:
#    DOCKER_BUILDKIT=1 docker build --build-arg ENABLE_OBFUSCATION=false -t easy-vdl .
#   或使用调试脚本: ./build_and_run.sh
#

# 构建参数定义
ARG ENABLE_OBFUSCATION=true
ARG REQUIRE_OBFUSCATION=true

# =================================================================
# 第一阶段: 前端构建 (Frontend Builder)
# - 独立构建前端，避免 node_modules 和构建过程影响后端缓存
# =================================================================
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend-v2

# 利用层缓存：先只复制 package.json 安装依赖
COPY frontend-v2/package*.json ./
RUN npm install

# 再复制源代码进行构建
COPY frontend-v2/ ./
RUN npm run build && \
    echo "✅ Frontend v2 构建完成"

# =================================================================
# 第二阶段: 后端构建 (Backend Builder)
# - 安装 Python 环境和所有依赖
# =================================================================
FROM ubuntu:24.04 AS builder

# --- 环境设置 ---
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1

# --- 安装构建时依赖 ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl wget git build-essential ca-certificates gnupg lsb-release \
    nodejs npm && \
    install -d -m 0755 /etc/apt/keyrings && \
    curl -fsSL "http://keyserver.ubuntu.com/pks/lookup?op=get&search=0xF23C5A6CF475977595C89F51BA6932366A755776" | \
        gpg --dearmor -o /etc/apt/keyrings/deadsnakes.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/deadsnakes.gpg] https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu noble main" > /etc/apt/sources.list.d/deadsnakes.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3.10-dev && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3 && \
    rm -rf /var/lib/apt/lists/*

# --- 安装Python依赖 ---
# 创建虚拟环境，方便管理和复用
WORKDIR /
RUN python3.10 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 预先安装wheel，加速后续安装
RUN pip install --no-cache-dir wheel

# 安装本地 streamget 源码（由构建脚本同步到 _vendor_streamget-main）
COPY _vendor_streamget-main /tmp/streamget-main

# 安装所有Python包 (只要列表不变，此层缓存一直有效)
# 注意：已移除 debugpy，防止生产环境被远程调试
RUN pip install --no-cache-dir \
    fastapi==0.109.2 \
    uvicorn[standard]==0.27.1 \
    gunicorn==20.1.0 \
    playwright==1.41.2 \
    blinker==1.6.3 \
    httpx[http2]==0.28.1 \
    requests==2.34.2 \
    websocket-client==1.6.3 \
    brotli==1.2.0 \
    python-multipart==0.0.9 \
    aiosqlite==0.19.0 \
    python-jose==3.3.0 \
    loguru==0.7.3 \
    SQLAlchemy==2.0.23 \
    aiofiles==23.2.1 \
    pydantic==2.13.4 \
    yt-dlp==2026.03.17 \
    instagrapi==2.6.7 \
    orjson==3.9.10 \
    ujson==5.9.0 \
    uvloop==0.19.0 \
    httptools==0.6.1 \
    aiodns==3.1.1 \
    asyncio-pool==0.6.0 \
    aiohttp==3.9.3 \
    cachetools==5.3.2 \
    prometheus-client==0.19.0 \
    psutil==5.9.8 \
    pycryptodome==3.20.0 \
    cryptography==42.0.2 \
    pyOpenSSL==24.0.0 \
    bcrypt==4.0.1 \
    PyJWT==2.8.0 \
    passlib==1.7.4 \
    psycopg2-binary==2.9.9 \
    asyncpg==0.29.0 \
    ijson==3.2.3 \
    PyExecJS==1.5.1 \
    pillow-heif==0.13.1 \
    PySocks==1.7.1 \
    protobuf==4.24.3 \
    faster-whisper==1.2.1 \
    curl_cffi==0.6.2 \
    Telethon==1.36.0

# 仅安装本地源码版 streamget（无 PyPI 回退）
RUN pip install --no-cache-dir /tmp/streamget-main

# 安装 pyarmor 用于代码混淆
RUN pip install --no-cache-dir pyarmor==9.2.4

# --- 安装 Spider XHS 签名依赖 ---
# execjs 默认使用 node 运行时，这里提前安装 crypto-js 供 JS 签名文件 require
RUN mkdir -p /opt/xhs_js && \
    cd /opt/xhs_js && \
    npm init -y && \
    npm install crypto-js@4.2.0

# 拷贝并注册 Pyarmor 管线许可证
COPY licenses/pyarmor-ci-9675.zip /tmp/pyarmor-ci-9675.zip
RUN pyarmor reg /tmp/pyarmor-ci-9675.zip && \
    rm -f /tmp/pyarmor-ci-9675.zip



# --- 准备应用代码并进行混淆 ---
WORKDIR /src
# 只复制必要的应用代码和配置文件
COPY sql/ /src/sql/
COPY routers/ /src/routers/
COPY services/ /src/services/
COPY live/ /src/live/
COPY supervisor/ /src/supervisor/
COPY postgresql/ /src/postgresql/
COPY *.py /src/
COPY *.conf /src/
COPY docker-entrypoint.sh healthcheck.sh generate-build-version.sh /src/
COPY postgresql/init_postgresql.sh /src/

# 将 JS 签名依赖注入到运行时路径，供 execjs require
RUN mkdir -p /src/routers/xhs_static && \
    cp -r /opt/xhs_js/node_modules /src/routers/xhs_static/

ARG ENABLE_OBFUSCATION
RUN /bin/bash -c '\
    set -eo pipefail && \
    mkdir -p /app_build && \
    cp -r /src/* /app_build/ && \
    cd /app_build && \
    \
    # 检查是否启用混淆 \
    if [ "${ENABLE_OBFUSCATION}" != "true" ]; then \
        echo "⚠️  代码混淆已禁用（ENABLE_OBFUSCATION=${ENABLE_OBFUSCATION}）"; \
        echo "🚀 跳过混淆步骤，保留原始代码"; \
        exit 0; \
    fi && \
    \
    echo "🔧 开始代码混淆..." && \
    \
    # 查找所有需要混淆的Python文件 \
    # 排除：venv、tests、pyarmor运行时、备份文件、文档文件 \
    TEMP_FILE_LIST="/tmp/py_files.txt" && \
    find . -name "*.py" \
        ! -path "*/venv/*" \
        ! -path "*/tests/*" \
        ! -path "*/pyarmor_runtime_*/*" \
        ! -path "*/旧版*" \
        ! -path "*/*备份*" \
        ! -path "*/*backup*" \
        ! -path "*/*.backup" \
        ! -path "routers/backup.py" \
        -type f | sed "s|^\./||" > "$TEMP_FILE_LIST" && \
    \
    TOTAL_FILES=$(wc -l < "$TEMP_FILE_LIST") && \
    echo "📝 找到 $TOTAL_FILES 个Python文件需要混淆" && \
    \
    # 创建临时输出目录 \
    OBFUSCATED_DIR="/tmp/obfuscated" && \
    mkdir -p "$OBFUSCATED_DIR" && \
    \
    # 单次批量混淆（确保所有文件共享同一 runtime，避免逐文件生成导致格式不兼容） \
    if [ "$TOTAL_FILES" -le 0 ]; then \
        echo "❌ 未找到可混淆的 Python 文件" >&2; \
        exit 1; \
    fi && \
    echo "🔄 开始批量混淆（统一 runtime）..." && \
    if pyarmor gen --recursive \
        --exclude "*/venv/*" \
        --exclude "*/tests/*" \
        --exclude "*/pyarmor_runtime_*/*" \
        --exclude "*/旧版*" \
        --exclude "*/*备份*" \
        --exclude "*/*backup*" \
        --exclude "*/*.backup" \
        --exclude "routers/backup.py" \
        --output "$OBFUSCATED_DIR" . 2>&1; then \
        SUCCESS_COUNT=$(find "$OBFUSCATED_DIR" -name "*.py" \
            ! -path "*/pyarmor_runtime_*/*" -type f | wc -l); \
        echo "✅ 批量混淆完成: $SUCCESS_COUNT 个文件"; \
    else \
        echo "❌ 批量混淆失败" >&2; \
        exit 1; \
    fi && \
    \
    # 复制pyarmor运行时模块 \
    echo "📦 复制 pyarmor 运行时模块..." && \
    RUNTIME_DIR=$(find "$OBFUSCATED_DIR" -type d -name "pyarmor_runtime_*" | head -1) && \
    if [ -n "$RUNTIME_DIR" ] && [ -d "$RUNTIME_DIR" ]; then \
        cp -r "$RUNTIME_DIR" /app_build/ && \
        echo "✅ 运行时模块已复制: $(basename $RUNTIME_DIR)"; \
    else \
        echo "❌ 未找到 pyarmor 运行时模块" >&2; \
        exit 1; \
    fi && \
    \
    # 替换原始文件为混淆后的文件 \
    echo "🔄 替换原始文件为混淆文件..." && \
    while IFS= read -r file; do \
        if [ -z "$file" ] || [ ! -f "$OBFUSCATED_DIR/$file" ]; then \
            continue; \
        fi && \
        \
        # 备份并替换 \
        if cp "$OBFUSCATED_DIR/$file" "$file"; then \
            echo "✅ 已替换: $file"; \
        else \
            echo "❌ 替换失败: $file" >&2; \
            exit 1; \
        fi; \
    done < "$TEMP_FILE_LIST" && \
    \
    # 清理临时文件 \
    rm -rf "$OBFUSCATED_DIR" "$TEMP_FILE_LIST" && \
    rm -rf /root/.pyarmor && \
    \
    # 验证混淆结果 \
    echo "🔍 验证混淆结果..." && \
    if [ -d "pyarmor_runtime_009675" ]; then \
        echo "✅ pyarmor_runtime_009675 模块存在"; \
    else \
        echo "❌ pyarmor_runtime_009675 模块不存在" >&2; \
        exit 1; \
    fi && \
    \
    # 检查几个关键文件是否被混淆 \
    SAMPLE_FILE=$(find . -name "*.py" \
        ! -path "*/venv/*" \
        ! -path "*/tests/*" \
        ! -path "*/pyarmor_runtime_*/*" \
        ! -path "*/旧版*" \
        ! -path "*/*备份*" \
        ! -path "*/*backup*" \
        ! -path "*/*.backup" \
        ! -path "routers/backup.py" \
        -type f | head -1) && \
    if [ -n "$SAMPLE_FILE" ]; then \
        if grep -q "from pyarmor_runtime" "$SAMPLE_FILE" 2>/dev/null; then \
            echo "✅ 混淆验证成功: 文件包含 pyarmor_runtime 导入"; \
        else \
            echo "⚠️ 警告: 混淆文件可能不包含 pyarmor_runtime 导入"; \
        fi; \
    fi && \
    \
    echo "✅ 代码混淆完成！" \
'



# =================================================================
# 第二阶段: 最终镜像 (Final Stage)
# - 使用相同的基础镜像
# - 只安装运行时依赖
# - 从Builder复制应用代码和依赖
# =================================================================
FROM ubuntu:24.04

ARG BUILD_VERSION
ARG REQUIRE_OBFUSCATION=true
LABEL org.easy-vdl.obfuscated="true" \
      org.easy-vdl.build.version="${BUILD_VERSION}"

# --- 环境设置 ---
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
ENV CHROME_SANDBOX=false
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/app/database/huggingface
WORKDIR /app

# --- 管理员凭据环境变量（可选，用于密码重置） ---
# 如果设置了这些环境变量，将覆盖数据库中的管理员凭据（通过 docker run -e）

# --- 用户权限环境变量（可选，用于解决权限问题） ---
# 如果设置了这些环境变量，将使用指定的用户ID运行PostgreSQL
# 使用方式：docker run -e PUID=1000 -e PGID=1000 easy-vdl
# 不设置时使用系统默认的postgres用户ID
ENV PUID=""
ENV PGID=""

# --- 安装运行时系统依赖 ---
RUN sed -i 's/archive.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    sed -i 's/security.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    # 启用非自由软件仓库（用于 Intel 核显驱动）
    sed -i 's/^deb \(.*\) main$/deb \1 main restricted universe multiverse/' /etc/apt/sources.list && \
    sed -i 's/^deb \(.*\) main$/deb \1 main restricted universe multiverse/' /etc/apt/sources.list.d/*.list 2>/dev/null || true && \
    # 先更新 apt 索引并安装基础工具（包括 wget）
    apt-get update && \
    apt-get install -y --no-install-recommends wget curl gnupg ca-certificates && \
    install -d -m 0755 /etc/apt/keyrings && \
    # 添加 deadsnakes PPA 以安装 Python 3.10；避免 add-apt-repository 依赖 Launchpad API。
    curl -fsSL "http://keyserver.ubuntu.com/pks/lookup?op=get&search=0xF23C5A6CF475977595C89F51BA6932366A755776" | \
        gpg --dearmor -o /etc/apt/keyrings/deadsnakes.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/deadsnakes.gpg] https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu noble main" > /etc/apt/sources.list.d/deadsnakes.list && \
    # 添加PostgreSQL官方仓库（使用新的密钥管理方式）
    wget --quiet -O /etc/apt/trusted.gpg.d/postgresql.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc && \
    echo "deb http://apt.postgresql.org/pub/repos/apt noble-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
    # 再次更新 apt 索引（包含 PostgreSQL 仓库）
    apt-get update && \
    # 一次性安装所有系统依赖（按功能分组，便于维护）
    apt-get install -y --no-install-recommends \
        # 基础工具（wget curl gnupg ca-certificates 已安装）
        apt-transport-https locales unzip xz-utils lsb-release \
        # Python 环境（固定 3.10）
        python3.10 python3.10-dev \
        # 核显硬件加速支持库
        libva-dev libva-drm2 libva-x11-2 libva2 \
        mesa-va-drivers intel-media-va-driver-non-free \
        libmfx-gen1.2 \
        libmfx1 \
        libdrm2 libdrm-intel1 libdrm-amdgpu1 libdrm-radeon1 \
        vainfo mesa-vulkan-drivers \
        # GPU 监控采集工具（仪表盘 GPU 卡片）
        intel-gpu-tools pciutils radeontop \
        # Web 服务
        nginx supervisor \
        # VNC 远程桌面
        xvfb x11vnc fluxbox novnc websockify \
        # 数据库
        sqlite3 postgresql-15 postgresql-contrib-15 postgresql-client-15 \
        # Chrome 浏览器依赖
        libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
        libxcomposite1 libxdamage1 libxrandr2 libgbm1 libxss1 libasound2t64 \
        libgtk-3-0 libx11-xcb1 libxcb-dri3-0 libxcb1 libxcb-glx0 \
        libxcb-keysyms1 libxcb-image0 libxcb-shm0 libxcb-icccm4 \
        libxcb-sync1 libxcb-xfixes0 libxcb-shape0 libxcb-render0 \
        libxcb-render-util0 libxcb-util1 libxcb-xinerama0 libxcb-xkb1 \
        libxkbcommon0 libxkbcommon-x11-0 libxfixes3 libxrender1 \
        libxext6 libx11-6 libvpx9 libopus0 libwebp7 libwebpmux3 \
        libwebpdemux2 fonts-wqy-zenhei \
        # Chrome 额外依赖
        fonts-liberation libvulkan1 xdg-utils && \
    # 使 python3 指向 3.10（避免默认 3.12）
    ln -sf /usr/bin/python3.10 /usr/bin/python3 && \
    # 安装 Node.js 20 (streamget 部分平台签名依赖较新 Node 运行时)
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    node -v && npm -v && \
    # 配置语言环境
    locale-gen en_US.UTF-8 && \
    update-locale LANG=en_US.UTF-8 && \
    # 清理 apt 缓存
    rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 仓库中的 FFmpeg 6.1.1 对部分直播源 AAC ADTS 帧兼容性不足。
# 使用 BtbN 的 FFmpeg master 分支静态构建（含虎牙 AAC RDB/Gain control 支持）。
RUN set -eux; \
    ARCH="$(uname -m)"; \
    case "$ARCH" in \
        x86_64) FFMPEG_ARCH="linux64" ;; \
        aarch64|arm64) FFMPEG_ARCH="linuxarm64" ;; \
        *) echo "Unsupported FFmpeg arch: $ARCH" >&2; exit 1 ;; \
    esac; \
    FFMPEG_PKG="ffmpeg-master-latest-${FFMPEG_ARCH}-gpl.tar.xz"; \
    FFMPEG_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/${FFMPEG_PKG}"; \
    curl -fL "$FFMPEG_URL" -o "/tmp/${FFMPEG_PKG}"; \
    mkdir -p /tmp/ffmpeg-btbn; \
    tar -xJf "/tmp/${FFMPEG_PKG}" -C /tmp/ffmpeg-btbn --strip-components=1; \
    install -m 0755 /tmp/ffmpeg-btbn/bin/ffmpeg /usr/local/bin/ffmpeg; \
    install -m 0755 /tmp/ffmpeg-btbn/bin/ffprobe /usr/local/bin/ffprobe; \
    if [ -f /tmp/ffmpeg-btbn/bin/ffplay ]; then install -m 0755 /tmp/ffmpeg-btbn/bin/ffplay /usr/local/bin/ffplay; fi; \
    ffmpeg -version | head -1; \
    ffprobe -version | head -1; \
    rm -rf "/tmp/${FFMPEG_PKG}" /tmp/ffmpeg-btbn

# 安装 Deno (yt-dlp 2025.11.12+ 需要用于 YouTube 支持)
RUN curl -fsSL https://deno.land/install.sh | sh && \
    mv /root/.deno/bin/deno /usr/local/bin/deno && \
    chmod +x /usr/local/bin/deno && \
    rm -rf /root/.deno

# --- 安装 Google Chrome 和 ChromeDriver (用于调试和Playwright) ---
# Chrome 所有依赖已在上面统一安装
RUN wget --no-check-certificate -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    # 安装 Chrome（依赖已满足，应该直接成功）
    dpkg -i /tmp/google-chrome.deb && \
    rm /tmp/google-chrome.deb && \
    # 验证 Chrome 安装成功
    google-chrome --version && \
    # 获取 Chrome 版本并下载对应的 ChromeDriver
    CHROME_VERSION=$(google-chrome --version | awk '{print $3}') && \
    CHROMEDRIVER_VERSION=$(curl -sS "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json" | python3 -c "import sys, json; print(json.load(sys.stdin)['channels']['Stable']['version'])") && \
    wget --no-check-certificate -O /tmp/chromedriver-linux64.zip "https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/${CHROMEDRIVER_VERSION}/linux64/chromedriver-linux64.zip" && \
    unzip /tmp/chromedriver-linux64.zip -d /usr/local/bin/ && \
    mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver && \
    chmod +x /usr/local/bin/chromedriver && \
    # 清理临时文件
    rm -rf /usr/local/bin/chromedriver-linux64 /tmp/chromedriver-linux64.zip

# --- 设置VNC密码 ---
RUN mkdir -p /root/.vnc && \
    touch /root/.vnc/passwd && \
    chmod 600 /root/.vnc/passwd

# --- 复制已安装的Python环境 ---
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 清理本地源码安装残留的构建来源路径信息（不影响运行）
RUN find /opt/venv/lib -type f -path "*/streamget-*.dist-info/direct_url.json" -delete 2>/dev/null || true

# --- 物理隔离：只从Builder阶段拉取最终混淆后的代码，杜绝源码泄露 ---
COPY --from=builder /app_build /app/

# --- 最终镜像混淆校验：生产构建必须确认关键代码已混淆 ---
RUN if [ "$REQUIRE_OBFUSCATION" = "true" ]; then \
        echo "🔒 验证最终镜像混淆状态..." && \
        if ! find /app -maxdepth 1 -type d -name "pyarmor_runtime_*" | grep -q .; then \
            echo "❌ 未找到 pyarmor_runtime_*，生产镜像拒绝构建"; \
            exit 1; \
        fi && \
        for file in \
            /app/routers/license.py \
            /app/routers/auth.py \
            /app/routers/subscribe/subscription.py \
            /app/live/routers.py \
            /app/live/scheduler.py; do \
            if [ ! -f "$file" ]; then \
                echo "❌ 关键文件不存在: $file"; \
                exit 1; \
            fi; \
            if ! grep -qE "pyarmor_runtime|__pyarmor__" "$file"; then \
                echo "❌ 关键文件未混淆: $file"; \
                exit 1; \
            fi; \
        done && \
        echo "✅ 最终镜像混淆校验通过"; \
    else \
        echo "⚠️  最终镜像混淆校验已禁用（REQUIRE_OBFUSCATION=$REQUIRE_OBFUSCATION）"; \
    fi

# 安装 Node.js 斗鱼弹幕依赖
RUN cd /app/live/douyu_danmu && npm install --omit=dev

# 安装 Node.js 虎牙弹幕依赖
RUN cd /app/live/huya_danmu && npm install --omit=dev

# 从frontend-builder阶段复制前端构建产物
COPY --from=frontend-builder /app/frontend-v2/dist /app/frontend/public

# --- 设置执行权限并生成构建版本 ---
ARG BUILD_TIME
RUN chmod +x /app/docker-entrypoint.sh && \
    chmod +x /app/healthcheck.sh && \
    chmod +x /app/generate-build-version.sh && \
    chmod +x /app/init_postgresql.sh && \
    chmod +x /app/postgresql/start_postgresql_daemon.sh && \
    # 生成构建版本 \
    BUILD_VERSION="$BUILD_VERSION" BUILD_TIME="$BUILD_TIME" /app/generate-build-version.sh

# --- 跳过字节码编译，混淆已足够保护源码 ---
# pyarmor混淆后的代码已经不可读，无需额外的字节码编译
# 字节码编译反而会导致开发时的"bad magic number"错误
RUN echo "✅ 代码已通过pyarmor混淆保护，跳过字节码编译以避免缓存问题"

# --- 创建目录和设置权限 ---
# 1. 创建固定 UID/GID 的 easyvdl 用户 (默认 1000)
# Ubuntu 24.04 基础镜像可能已存在 UID=1000 的用户，避免冲突则复用
RUN set -eux; \
    if ! getent group easyvdl >/dev/null 2>&1; then \
        groupadd -g 1001 easyvdl; \
    fi; \
    if getent passwd 1000 >/dev/null 2>&1; then \
        EXISTING_USER="$(getent passwd 1000 | cut -d: -f1)"; \
        usermod -g easyvdl "$EXISTING_USER"; \
    else \
        useradd -u 1000 -g easyvdl -s /bin/bash -m easyvdl; \
    fi

RUN mkdir -p /app/downloads && \
    mkdir -p /app/logs && \
    mkdir -p /app/sockets && \
    mkdir -p /app/database && \
    mkdir -p /app/cache && \
    mkdir -p /app/frontend/public && \
               # PostgreSQL 目录
           mkdir -p /app/postgresql && \
           mkdir -p /app/database/PostgreSQL && \
           mkdir -p /etc/postgresql/15/main && \
    # 设置目录所有权和权限
    chown -R 1000:1001 /app && \
    chmod 755 /app && \
    chmod 755 /app/downloads && \
    chmod 755 /app/logs && \
    chmod 755 /app/sockets && \
    chmod 755 /app/database && \
    chmod 755 /app/cache && \
    chmod 755 /app/frontend && \
    # 确保特定目录存在且有正确权限（统一浏览器架构，DYD使用headless无需持久化）
    mkdir -p /app/database/chrome/unified && \
    chown -R 1000:1001 /app/database/chrome && \
    chmod 775 /app/database/chrome/unified && \
    mkdir -p /app/database/chrome/tmp && \
    chmod 775 /app/database/chrome/tmp && \
    # 设置日志目录权限
    chmod 775 /app/logs && \
    # 创建socket目录
    chmod 775 /app/sockets && \
               # 设置PostgreSQL目录权限
           chown -R 1000:1001 /app/database/PostgreSQL && \
           chmod 700 /app/database/PostgreSQL && \
           chown -R 1000:1001 /etc/postgresql && \
           chmod 755 /etc/postgresql/15/main

# --- 配置Nginx和Supervisor ---
RUN rm -f /etc/nginx/sites-enabled/default && \
    cp /app/nginx.conf /etc/nginx/sites-available/easy-vdl && \
    ln -s /etc/nginx/sites-available/easy-vdl /etc/nginx/sites-enabled/easy-vdl && \
    # 设置 Nginx worker 进程以 easyvdl 用户运行
    sed -i 's/^user .*/user easyvdl;/' /etc/nginx/nginx.conf && \
    mkdir -p /etc/supervisor/conf.d

COPY supervisor/supervisord.conf /etc/supervisor/supervisord.conf

# --- 暴露端口和设置卷 ---
EXPOSE 80
VOLUME ["/app/downloads", "/app/logs", "/app/database"]

# --- 健康检查和时区 ---
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD ["/bin/bash","/app/healthcheck.sh"]
RUN ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && echo 'Asia/Shanghai' > /etc/timezone

# --- 启动命令 ---
ENTRYPOINT ["/app/docker-entrypoint.sh"]
