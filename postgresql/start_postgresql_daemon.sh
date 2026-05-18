#!/bin/bash

# PostgreSQL 守护进程启动脚本
# 使用pg_ctl启动PostgreSQL服务
# 本脚本应以 easyvdl 用户身份运行

set -e

# 初始化数据库和用户的函数
init_database_and_user() {
    echo "🔍 检查应用数据库..."
    if ! /usr/lib/postgresql/15/bin/psql -U postgres -lqt | cut -d \| -f 1 | grep -qw easy_vdl; then
        echo "创建应用数据库 easy_vdl..."
        /usr/lib/postgresql/15/bin/createdb -U postgres easy_vdl
        echo "✅ 数据库 easy_vdl 创建成功"
    else
        echo "✅ 数据库 easy_vdl 已存在"
    fi

    echo "👤 检查应用用户..."
    if ! /usr/lib/postgresql/15/bin/psql -U postgres -t -c "SELECT 1 FROM pg_roles WHERE rolname='easy_vdl_user'" | grep -q 1; then
        echo "创建应用用户 easy_vdl_user..."
        /usr/lib/postgresql/15/bin/createuser -U postgres --no-superuser --no-createdb --no-createrole easy_vdl_user
        /usr/lib/postgresql/15/bin/psql -U postgres -c "ALTER USER easy_vdl_user WITH PASSWORD 'easy_vdl_password';"
        /usr/lib/postgresql/15/bin/psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE easy_vdl TO easy_vdl_user;"
        echo "✅ 用户 easy_vdl_user 创建成功"
    else
        echo "✅ 用户 easy_vdl_user 已存在"
    fi
}

echo "🚀 启动PostgreSQL服务 (守护进程模式)..."

# 配置同步函数
sync_source_config() {
    echo "🔧 同步源码中的数据库配置..."
    
    # 直接复制源码中的配置文件到数据目录
    cp /app/postgresql/postgresql.conf "$PGDATA/postgresql.conf"
    cp /app/postgresql/pg_hba.conf "$PGDATA/pg_hba.conf"
    
    echo "✅ 配置同步完成，使用源码中的最新配置"
}

# 设置环境变量
export PGDATA="/app/database/PostgreSQL"
export PGPORT="5432"
export PGDATABASE="postgres"
export PGUSER="postgres"
export PGHOST="localhost"

# 检查数据目录
if [ ! -d "$PGDATA" ]; then
    echo "❌ 数据目录不存在: $PGDATA"
    exit 1
fi

# 检查配置文件
if [ ! -f "$PGDATA/postgresql.conf" ]; then
    echo "❌ 配置文件不存在: $PGDATA/postgresql.conf"
    exit 1
fi

# 检查PostgreSQL是否已经在运行（改进的检查逻辑）
echo "🔍 检查PostgreSQL服务状态..."
if /usr/lib/postgresql/15/bin/pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
    echo "✅ PostgreSQL已经在运行，开始监控服务状态"
    # 保持脚本运行，监控服务状态
    while true; do
        sleep 5
        if ! /usr/lib/postgresql/15/bin/pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
            echo "❌ PostgreSQL服务已停止，尝试重启..."
            # 尝试重启服务
            /usr/lib/postgresql/15/bin/pg_ctl -D "$PGDATA" start 2>/dev/null || true
            sleep 3
            if /usr/lib/postgresql/15/bin/pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
                echo "✅ PostgreSQL服务重启成功"
            else
                echo "❌ PostgreSQL服务重启失败，退出监控"
                exit 1
            fi
        fi
    done
fi

echo "🔄 启动PostgreSQL服务..."
echo "数据目录: $PGDATA"
echo "配置文件: $PGDATA/postgresql.conf"

# 同步源码中的最新配置
sync_source_config

# 使用pg_ctl启动服务（改进的启动逻辑）
echo "🚀 启动PostgreSQL服务..."
if ! /usr/lib/postgresql/15/bin/pg_ctl -D "$PGDATA" start 2>/dev/null; then
    echo "⚠️ 启动时检测到可能的冲突，尝试强制启动..."
    # 如果启动失败，尝试停止可能存在的进程后重新启动
    /usr/lib/postgresql/15/bin/pg_ctl -D "$PGDATA" stop 2>/dev/null || true
    sleep 2
    /usr/lib/postgresql/15/bin/pg_ctl -D "$PGDATA" start
fi

# 等待服务启动
echo "⏳ 等待PostgreSQL服务启动..."
sleep 5

# 检查服务状态
if /usr/lib/postgresql/15/bin/pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
    echo "✅ PostgreSQL服务启动成功"
    
    # 初始化数据库和用户（如果不存在）
    echo "🏗️ 初始化数据库结构..."
    init_database_and_user
    
    # 保持脚本运行，监控服务状态
    while true; do
        sleep 5
        if ! /usr/lib/postgresql/15/bin/pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
            echo "❌ PostgreSQL服务已停止"
            break
        fi
    done
    
    # 如果服务停止，尝试重启（改进的重启逻辑）
    echo "🔄 尝试重启PostgreSQL服务..."
    # 先尝试优雅停止
    /usr/lib/postgresql/15/bin/pg_ctl -D "$PGDATA" stop -m fast 2>/dev/null || true
    sleep 3
    # 强制停止（如果优雅停止失败）
    /usr/lib/postgresql/15/bin/pg_ctl -D "$PGDATA" stop -m immediate 2>/dev/null || true
    sleep 2
    # 重新启动
    /usr/lib/postgresql/15/bin/pg_ctl -D "$PGDATA" start
    sleep 5
    
    # 再次检查状态
    if /usr/lib/postgresql/15/bin/pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
        echo "✅ PostgreSQL服务重启成功"
        # 继续监控
        while true; do
            sleep 5
            if ! /usr/lib/postgresql/15/bin/pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
                echo "❌ PostgreSQL服务最终停止"
                exit 1
            fi
        done
    else
        echo "❌ PostgreSQL服务重启失败"
        exit 1
    fi
else
    echo "❌ PostgreSQL服务启动失败"
    exit 1
fi
