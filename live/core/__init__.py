# -*- coding: utf-8 -*-
"""
直播录制核心服务模块
复用 DouyinLiveRecorder 的核心代码
"""
import os
import sys
from pathlib import Path

current_file_path = Path(__file__).resolve()
current_dir = current_file_path.parent
JS_SCRIPT_PATH = str(current_dir / 'javascript')

# 日志统一管理到 /app/logs/easy-vdl.log
# 不再需要创建 live 子文件夹
# log_dir = Path("/app/logs/live")
# log_dir.mkdir(parents=True, exist_ok=True)
