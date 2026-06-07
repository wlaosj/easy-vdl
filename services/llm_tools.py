# -*- coding: utf-8 -*-
"""
LLM Function Calling Tool Schema 定义
供 llm_assistant.py 使用，描述 Easy-VDL 所有可执行操作
"""

TOOLS = [
    # ===== 订阅管理 =====
    {
        "type": "function",
        "function": {
            "name": "add_subscription",
            "description": "添加视频订阅。当用户提供一个视频平台的博主主页、合集、播放列表链接时使用。支持抖音、YouTube、B站、小红书、TikTok、Instagram、X、网易云音乐。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "订阅链接"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_subscriptions",
            "description": "查看订阅列表。当用户询问有哪些订阅、订阅状态、订阅了多少博主时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "enum": ["all", "douyin", "youtube", "bilibili", "tiktok", "xiaohongshu", "instagram", "x", "netease"],
                        "description": "按平台筛选，默认 all"
                    },
                    "page": {"type": "integer", "description": "页码，默认 1"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pause_subscription",
            "description": "暂停某个订阅",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string", "description": "订阅 ID"}
                },
                "required": ["subscription_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resume_subscription",
            "description": "恢复某个已暂停的订阅",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string", "description": "订阅 ID"}
                },
                "required": ["subscription_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_subscription",
            "description": "删除某个订阅。注意：此操作不可撤销，必须先向用户确认再执行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string", "description": "订阅 ID"},
                    "confirmed": {
                        "type": "boolean",
                        "description": "是否已获得用户确认。必须先问用户「确认删除吗？」得到肯定答复后再传 true。",
                        "default": False
                    }
                },
                "required": ["subscription_id", "confirmed"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_subscription_update",
            "description": "手动检查某个订阅是否有新内容更新",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string", "description": "订阅 ID"}
                },
                "required": ["subscription_id"]
            }
        }
    },

    # ===== 视频下载 =====
    {
        "type": "function",
        "function": {
            "name": "download_video",
            "description": "下载单个视频。当用户提供一个具体视频链接（非博主主页）时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "视频链接"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_downloads",
            "description": "查看下载任务列表。当用户问正在下载什么、下载进度、有哪些任务时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["all", "downloading", "pending", "completed", "failed"],
                        "description": "按状态筛选，默认 all"
                    },
                    "page": {"type": "integer", "description": "页码，默认 1"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "retry_download",
            "description": "重试失败的下载任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任务 ID"}
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_download",
            "description": "删除下载任务。注意：此操作不可撤销，必须先向用户确认再执行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任务 ID"},
                    "confirmed": {
                        "type": "boolean",
                        "description": "是否已获得用户确认。必须先问用户「确认删除吗？」得到肯定答复后再传 true。",
                        "default": False
                    }
                },
                "required": ["task_id", "confirmed"]
            }
        }
    },

    # ===== 直播监控 =====
    {
        "type": "function",
        "function": {
            "name": "add_live_subscription",
            "description": "添加直播监控。当用户提供一个直播间链接时使用。支持抖音、B站、小红书、虎牙、斗鱼、快手、YouTube、Twitch、咪咕、CC。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "直播间链接"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_live_subscriptions",
            "description": "查看直播监控列表。当用户问谁在直播、有哪些直播监控时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "description": "页码，默认 1"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pause_live_subscription",
            "description": "关闭直播监控的自动录制（暂停监控/停止录制）。适用于用户说「关闭录制」「暂停监控」。",
            "parameters": {
                "type": "object",
                "properties": {
                    "live_id": {"type": "string", "description": "直播监控 ID"}
                },
                "required": ["live_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resume_live_subscription",
            "description": "开启直播监控的自动录制（恢复监控/开始录制）。适用于用户说「开启录制」「开始录制」「恢复监控」。",
            "parameters": {
                "type": "object",
                "properties": {
                    "live_id": {"type": "string", "description": "直播监控 ID"}
                },
                "required": ["live_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_live_subscription",
            "description": "删除直播监控。注意：此操作不可撤销，必须先向用户确认再执行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "live_id": {"type": "string", "description": "直播监控 ID"},
                    "confirmed": {
                        "type": "boolean",
                        "description": "是否已获得用户确认。必须先问用户「确认删除吗？」得到肯定答复后再传 true。",
                        "default": False
                    }
                },
                "required": ["live_id", "confirmed"]
            }
        }
    },

    # ===== 系统查询 =====
    {
        "type": "function",
        "function": {
            "name": "check_status",
            "description": "查看系统运行状态，包括 CPU、内存、磁盘使用、下载队列、订阅统计、直播统计等。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_tasks",
            "description": "查看下载任务统计信息（总数、下载中、等待中、已完成、失败数量）。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_license",
            "description": "查看授权状态（是否有效、剩余天数等）。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_failed_tasks",
            "description": "查看失败的下载任务列表。",
            "parameters": {"type": "object", "properties": {}}
        }
    },

    # ===== 智能 URL 处理 =====
    {
        "type": "function",
        "function": {
            "name": "smart_handle_url",
            "description": "智能处理 URL。当用户发送一个链接但没有明确说明要做什么时使用。会自动分析链接类型（视频/直播/博主主页）并直接执行对应操作（下载/添加订阅/添加直播监控），无需再询问用户确认。如果执行失败会返回错误信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "链接地址"},
                    "context": {"type": "string", "description": "用户发送链接时附带的文字说明", "default": ""}
                },
                "required": ["url"]
            }
        }
    },

    # ===== 录制转码 =====
    {
        "type": "function",
        "function": {
            "name": "convert_record",
            "description": "将某条录制记录转码为 MP4。适用于用户说「帮我把 xx 的录制转成 mp4」「转码 xx 的直播回放」。",
            "parameters": {
                "type": "object",
                "properties": {
                    "record_id": {"type": "string", "description": "录制记录 ID"},
                    "delete_original": {
                        "type": "boolean",
                        "description": "转码完成后是否删除原始 .ts 文件，默认 true",
                        "default": True
                    }
                },
                "required": ["record_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "convert_unconverted",
            "description": "一键转码全部未转码的录制记录。可按主播订阅筛选。适用于「把全部录制转码」「帮我把未转码的都转一下」。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "可选，按订阅 ID 筛选，只转码该主播的未转码录制"
                    },
                    "delete_original": {
                        "type": "boolean",
                        "description": "转码完成后是否删除原始 .ts 文件，默认 true",
                        "default": True
                    }
                }
            }
        }
    },

    # ===== 纯对话回复 =====
    {
        "type": "function",
        "function": {
            "name": "chat_reply",
            "description": "当用户的问题不需要调用任何操作工具时使用此函数进行回复。例如：打招呼、问平台能力、闲聊、问使用方法、问支持哪些平台等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "回复用户的文本内容"}
                },
                "required": ["message"]
            }
        }
    },
]
