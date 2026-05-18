# -*- coding: utf-8 -*-
"""
直播录制日志模块
"""
import logging
import os
from pathlib import Path

# 保留 script_path 以兼容 spider.py 等模块的调用
# 将其指向主日志目录，避免创建空的 'live' 子文件夹
log_dir = Path("/app/logs")
# log_dir.mkdir(parents=True, exist_ok=True) # 不再需要创建
script_path = str(log_dir)

# 获取 'live' logger
# 配置将由 main.py 启动时的 logging.json 控制
# 这确保了日志统一管理到 /app/logs/easy-vdl.log
logger = logging.getLogger("live")
# 默认级别由 logging.json 统一控制
# logger.setLevel(logging.DEBUG) 

# 为了兼容之前的引用
live_logger = logger
