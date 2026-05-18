#!/bin/bash

# 检查关键进程是否存在 (最可靠的检测方式)
if ! pgrep -f "python.*uvicorn.*main:app" > /dev/null; then
    echo "FastAPI应用进程不存在"
    exit 1
fi

if ! pgrep -f "postgres.*easy_vdl" > /dev/null; then
    echo "PostgreSQL数据库进程不存在"
    exit 1
fi

# 检查PostgreSQL数据库连接
if ! pg_isready -h localhost -p 5432 -U easy_vdl_user -d easy_vdl 2>/dev/null; then
    echo "PostgreSQL数据库连接失败"
    exit 1
fi

# 检查Unix socket文件是否存在
if [ ! -S "/app/sockets/easy-vdl.sock" ]; then
    echo "FastAPI Unix socket文件不存在"
    exit 1
fi

echo "所有关键服务正常运行"
exit 0 