#!/bin/bash

# PostgreSQL 基础初始化脚本
# 负责初始化数据库集群（如果不存在）
# 本脚本应以 easyvdl 用户身份运行

set -e

echo "🚀 开始初始化PostgreSQL引擎..."

# 设置环境变量
export PGDATA="/app/database/PostgreSQL"
export PGPORT="5432"

# 确保数据目录存在
echo "📁 检查数据目录..."
mkdir -p "$PGDATA"
# 注意：权限已由 entrypoint 统一处理，这里不再尝试修改所有者

# PostgreSQL严格要求数据目录权限必须为700（只有所有者可访问）
chmod 700 "$PGDATA"
echo "✅ 数据目录权限位设置为: 700"

# 初始化数据库集群
echo "🗄️ 初始化数据库集群..."
if [ ! -f "$PGDATA/PG_VERSION" ]; then
    echo "执行 initdb..."
    # 直接运行 initdb，因为本脚本将以 easyvdl 身份运行
    /usr/lib/postgresql/15/bin/initdb -D "$PGDATA" --encoding=UTF8 --locale=C -U postgres
    echo "数据库集群初始化完成"
else
    echo "数据库集群已存在，跳过初始化"
fi

# 复制配置文件
echo "⚙️ 配置PostgreSQL..."
if [ -f "/app/postgresql/postgresql.conf" ]; then
    # 复制到数据目录（PostgreSQL实际读取的位置）
    cp /app/postgresql/postgresql.conf "$PGDATA/"
    chmod 644 "$PGDATA"/postgresql.conf
    echo "postgresql.conf 数据目录配置已更新"
fi

if [ -f "/app/postgresql/pg_hba.conf" ]; then
    # 复制到数据目录
    cp /app/postgresql/pg_hba.conf "$PGDATA/"
    chmod 644 "$PGDATA"/pg_hba.conf
    echo "pg_hba.conf 数据目录配置已更新"
fi

# 注意：本脚本不再负责启动服务，只负责初始化数据
# 服务启动由 Supervisor 管理的 start_postgresql_daemon.sh 负责

echo "✅ PostgreSQL引擎初始化完成"
