#!/bin/bash

# Easy-VDL Docker启动脚本 (重构版 - 基于 easyvdl 用户)
# 处理用户ID映射并启动 Supervisor

set -e

# 定义日志文件路径
ENTRYPOINT_LOG="/app/logs/docker-entrypoint.log"

# 确保日志目录存在
mkdir -p /app/logs
chown easyvdl:easyvdl /app/logs 2>/dev/null || true

# 清理所有旧日志文件
echo "🧹 清理旧日志文件..."
find /app/logs -type f -name "*.log" -delete 2>/dev/null || true

# 日志函数
log_message() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] $1" | tee -a "$ENTRYPOINT_LOG"
}

log_message "🚀 启动Easy-VDL服务 (User Mode)..."

# 1. 处理 PUID/PGID 映射
target_uid=${PUID:-1000}
target_gid=${PGID:-1001}

# 兼容 Ubuntu 24.04 基础镜像可能已存在 UID=1000 用户
if getent group easyvdl >/dev/null 2>&1; then
    RUN_GROUP="easyvdl"
elif getent group "$target_gid" >/dev/null 2>&1; then
    RUN_GROUP="$(getent group "$target_gid" | cut -d: -f1)"
else
    groupadd -g "$target_gid" easyvdl
    RUN_GROUP="easyvdl"
fi

if getent passwd easyvdl >/dev/null 2>&1; then
    RUN_USER="easyvdl"
elif getent passwd "$target_uid" >/dev/null 2>&1; then
    # 允许重复 UID，创建一个 easyvdl 别名用户，兼容 supervisord 里写死的 user=easyvdl
    useradd -o -u "$target_uid" -g "$RUN_GROUP" -s /bin/bash -m easyvdl
    RUN_USER="easyvdl"
else
    useradd -u "$target_uid" -g "$RUN_GROUP" -s /bin/bash -m easyvdl
    RUN_USER="easyvdl"
fi

# 让 easyvdl 成为该 UID 的“主显示名”，便于统一日志与工具输出
if getent passwd easyvdl >/dev/null 2>&1 && getent passwd "$target_uid" >/dev/null 2>&1; then
    easyvdl_uid=$(getent passwd easyvdl | cut -d: -f3)
    primary_uid=$(getent passwd "$target_uid" | cut -d: -f3)
    if [ "$easyvdl_uid" = "$primary_uid" ]; then
        tmp_passwd=$(mktemp)
        {
            getent passwd easyvdl
            getent passwd | grep -vE '^(easyvdl|ubuntu):'
            # 保留原 ubuntu 记录但放到后面，避免影响 UID 显示名
            getent passwd ubuntu 2>/dev/null || true
        } > "$tmp_passwd"
        cat "$tmp_passwd" > /etc/passwd
        rm -f "$tmp_passwd"
    fi
fi

current_uid=$(id -u "$RUN_USER")
current_gid=$(id -g "$RUN_USER")
current_group=$(id -gn "$RUN_USER")

log_message "👤 用户权限检查: 当前 ${RUN_USER}($current_uid:$current_gid/$current_group) -> 目标($target_uid:$target_gid)"

if [ "$target_uid" != "$current_uid" ] || [ "$target_gid" != "$current_gid" ]; then
    log_message "🔧 检测到自定义 PUID/PGID，正在调整运行用户..."
    
    # 修改组 ID
    if [ "$target_gid" != "$current_gid" ]; then
        groupmod -o -g "$target_gid" "$RUN_GROUP"
        final_group=$(id -gn "$RUN_USER")
        log_message "✅ 组 ID 已修改为: $target_gid ($final_group)"
    fi
    
    # 修改用户 ID
    if [ "$target_uid" != "$current_uid" ]; then
        usermod -o -u "$target_uid" "$RUN_USER"
        log_message "✅ 用户 ID 已修改为: $target_uid"
    fi
    
    # 修正挂载目录的文件所有权（容器内部文件已在镜像构建时设置正确）
    log_message "🔐 正在修正挂载目录权限..."
    
    # 只修复挂载的目录，不修复容器内部代码文件（已在 Dockerfile 中设置正确）
    # 使用 + 批量执行 chown，提升性能
    # downloads 目录：只修复顶层目录所有者，不递归（避免几万个视频文件导致启动慢）
    # 因为主应用以 root 运行且设置 777 权限，内部文件所有者不重要
    [ -d "/app/downloads" ] && chown "$RUN_USER:$RUN_GROUP" /app/downloads 2>/dev/null || true
    [ -d "/app/logs" ] && chown -R "$RUN_USER:$RUN_GROUP" /app/logs 2>/dev/null || true
    [ -d "/app/sockets" ] && chown -R "$RUN_USER:$RUN_GROUP" /app/sockets 2>/dev/null || true
    # database 目录（排除 PostgreSQL 和 chrome，chrome 已设置 777 权限且主应用以 root 运行）
    if [ -d "/app/database" ]; then
        find /app/database \
            -path /app/database/PostgreSQL -prune -o \
            -path /app/database/chrome -prune -o \
            -type d -exec chown "$RUN_USER:$RUN_GROUP" {} + 2>/dev/null || true
        find /app/database \
            -path /app/database/PostgreSQL -prune -o \
            -path /app/database/chrome -prune -o \
            -type f -exec chown "$RUN_USER:$RUN_GROUP" {} + 2>/dev/null || true
    fi
    
    log_message "✅ 挂载目录权限修正完成"
else
    log_message "✅ 用户 ID 与目标一致，无需调整"
    
    # 确保关键目录归属正确
    chown "$RUN_USER:$RUN_GROUP" /app/downloads /app/database /app/sockets 2>/dev/null || true
    chown -R "$RUN_USER:$RUN_GROUP" /app/logs 2>/dev/null || true
fi

# 下载目录设置为 777 权限（NAS 环境兼容性）
# 视频文件不涉及敏感数据，777 权限方便多用户访问
if [ -d "/app/downloads" ]; then
    log_message "🔐 设置 downloads 目录为 777 权限（NAS 兼容模式）..."
    # 只修复目录权限，不修复文件权限（避免几万个视频文件导致启动慢）
    # 新下载的文件会自动设置 666 权限（主应用 umask=000 + 代码中的 chmod）
    find /app/downloads -type d -exec chmod 777 {} + 2>/dev/null || true
fi

# PostgreSQL 数据目录特殊处理（必须保持 700 权限）
if [ -d "/app/database/PostgreSQL" ]; then
    log_message "🔐 确保 PostgreSQL 数据目录权限正确..."
    # 修复所有者（递归）
    chown -R "$RUN_USER:$RUN_GROUP" /app/database/PostgreSQL 2>/dev/null || true
    # 修复顶层目录权限为 700（PostgreSQL 严格要求）
    chmod 700 /app/database/PostgreSQL 2>/dev/null || true
    # 修复内部目录权限（PostgreSQL 要求目录为 700）
    find /app/database/PostgreSQL -type d -exec chmod 700 {} + 2>/dev/null || true
    # 修复内部文件权限（PostgreSQL 要求文件为 600）
    find /app/database/PostgreSQL -type f -exec chmod 600 {} + 2>/dev/null || true
fi

# Cookie 数据目录安全加固（防止凭证泄露）
if [ -d "/app/database/cookie" ]; then
    log_message "🔐 确保 Cookie 目录权限安全 (仅所有者可读写)..."
    # 修复所有者
    chown -R "$RUN_USER:$RUN_GROUP" /app/database/cookie 2>/dev/null || true
    # 修复目录权限为 700 (只有所有者可进入)
    chmod 700 /app/database/cookie 2>/dev/null || true
    # 修复文件权限为 600 (只有所有者可读写)
    find /app/database/cookie -type f -exec chmod 600 {} + 2>/dev/null || true
fi

# 确保 PostgreSQL 运行时目录权限 (无论是否修改UID都执行)
# 上面的else块中只包含了针对默认UID的逻辑，实际上需要全局执行
# 移动到这里确保总是执行
if [ ! -d "/var/run/postgresql" ] || [ "$(stat -c '%U' /var/run/postgresql)" != "$RUN_USER" ]; then
    mkdir -p /var/run/postgresql
    chown -R "$RUN_USER:$RUN_GROUP" /var/run/postgresql
    chmod 775 /var/run/postgresql
fi

# 2. 环境变量设置
# 设置代理
PROXY_CONFIG_FILE="/app/database/proxy_config.env"
if [ -f "$PROXY_CONFIG_FILE" ]; then
    log_message "🌐 加载代理配置..."
    source "$PROXY_CONFIG_FILE"
    if [ "$GLOBAL_PROXY_ENABLED" = "true" ] && [ -n "$PROXY_URL" ]; then
        export HTTP_PROXY="$PROXY_URL"
        export HTTPS_PROXY="$PROXY_URL"
        export http_proxy="$PROXY_URL"
        export https_proxy="$PROXY_URL"
        export NO_PROXY="${NO_PROXY_LIST:-localhost,127.0.0.1,*.local}"
        export no_proxy="${NO_PROXY_LIST:-localhost,127.0.0.1,*.local}"
        log_message "✅ 代理已启用: $PROXY_URL"
    fi
fi

# 3. 初始化工作目录和链接
log_message "🔧 初始化临时工作目录..."
rm -rf /app/database/chrome/tmp/*
mkdir -p /app/database/chrome/tmp/unified_work
mkdir -p /app/database/chrome/tmp/dyd_work
mkdir -p /app/database/chrome/unified/Default

chmod 777 /app/database/chrome/tmp/unified_work
chmod 777 /app/database/chrome/tmp/dyd_work
chmod 777 /app/database/chrome/unified/Default
ln -sf /app/database/chrome/unified/Default /app/database/chrome/tmp/unified_work/Default

# 确保 Chrome 目录所有者正确（PUID 修改后可能需要）
# 如果是自定义 PUID，上面的递归 chown 已经处理
# 如果是默认 PUID，这里确保新创建的目录归属正确
if [ "$(stat -c '%U' /app/database/chrome 2>/dev/null)" != "$RUN_USER" ]; then
    chown -R "$RUN_USER:$RUN_GROUP" /app/database/chrome
fi

# 4. 初始化数据库 (如果需要)
if [ ! -f "/app/database/PostgreSQL/PG_VERSION" ]; then
    log_message "🗄️ 首次启动，初始化PostgreSQL数据库..."
    
    # 确保初始化脚本有执行权限
    if [ -f "/app/init_postgresql.sh" ]; then
        chmod +x /app/init_postgresql.sh
        log_message "✅ PostgreSQL初始化脚本权限已修复"
    else
        log_message "❌ PostgreSQL初始化脚本不存在: /app/init_postgresql.sh"
        exit 1
    fi
    
    # 使用 easyvdl 用户身份执行初始化脚本
    # 用 bash 解释执行，避免 noexec 挂载导致 Permission denied
    if su - "$RUN_USER" -c "/bin/bash /app/init_postgresql.sh"; then
        log_message "✅ PostgreSQL 初始化成功"
    else
        log_message "❌ PostgreSQL 初始化失败"
        exit 1
    fi
fi

# 5. 配置 Nginx 端口
EASY_VDL_PORT=${EASY_VDL_PORT:-80}
if [ "$EASY_VDL_PORT" != "80" ]; then
    log_message "🌐 配置Nginx监听端口: $EASY_VDL_PORT"
    sed -i "s/listen[[:space:]]\+[0-9]\+;/listen ${EASY_VDL_PORT};/" /etc/nginx/sites-available/easy-vdl
fi



# 6. 启动 Supervisor
log_message "🚀 启动 Supervisor..."
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
