# -*- coding: utf-8 -*-
"""AI 高光任务状态常量。"""

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELLED = "cancelled"

TASK_ACTIVE_STATUSES = {TASK_STATUS_QUEUED, TASK_STATUS_RUNNING}
TASK_TERMINAL_STATUSES = {TASK_STATUS_SUCCESS, TASK_STATUS_FAILED, TASK_STATUS_CANCELLED}


def normalize_task_status(value: str) -> str:
    status = str(value or "").strip().lower()
    if status in TASK_ACTIVE_STATUSES or status in TASK_TERMINAL_STATUSES:
        return status
    return TASK_STATUS_FAILED
