# -*- coding: utf-8 -*-
"""
共享 LLM 自然语言助手 - 前端 / Telegram / 企微 三通道共用
复用 live/highlights 的 LLM Provider 基础设施（DeepSeek / MiniMax / Ollama 等）
LLM 只做意图解析 + 参数提取，实际执行由 bot_commands / 现有 API 完成
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from sql.models import GlobalConfig
from .llm_tools import TOOLS
from . import bot_commands as cmd

logger = logging.getLogger(__name__)

# ==================== System Prompt ====================

SYSTEM_PROMPT = """你是 Easy-VDL 智能助手，一个视频订阅、直播监控、自动下载、录制转码平台的 AI 管理员。

你的能力：
1. 订阅管理：添加/查看/暂停/恢复/删除视频订阅（支持 抖音、YouTube、B站、小红书、TikTok、Instagram、X、网易云音乐）
2. 视频下载：下载单个视频、查看下载任务、重试/删除任务
3. 直播监控：添加/查看/暂停/恢复/删除直播监控（支持 抖音、B站、小红书、虎牙、斗鱼、快手、YouTube、Twitch、咪咕、CC）
4. 录制转码：将录制回放转码为 MP4，支持单条和批量转码
5. 系统查询：查看系统状态、任务统计、授权信息、失败任务
6. 智能链接处理：当用户发送一个链接时，自动分析类型并操作

规则：
- 如果用户发送了 URL，优先使用 smart_handle_url 自动处理，该工具直接执行操作无需再次询问用户确认
- 如果用户的意图不明确，用 chat_reply 询问澄清
- 回复使用简洁的中文
- 不要编造不存在的功能
- 每次回复只调用必要的工具，不要重复调用
- **删除类操作（删除订阅/任务/监控）必须先询问用户「确认删除吗？」并得到肯定答复后，才能将 confirmed 参数设为 true。不得擅自将 confirmed 设为 true。**
"""

# ==================== Tool 显示名称 ====================

TOOL_DISPLAY_NAMES = {
    "add_subscription": "添加订阅",
    "list_subscriptions": "查看订阅",
    "pause_subscription": "暂停订阅",
    "resume_subscription": "恢复订阅",
    "delete_subscription": "删除订阅",
    "check_subscription_update": "检查更新",
    "download_video": "下载视频",
    "list_downloads": "查看任务",
    "retry_download": "重试下载",
    "delete_download": "删除任务",
    "add_live_subscription": "添加直播监控",
    "list_live_subscriptions": "查看直播",
    "pause_live_subscription": "暂停监控",
    "resume_live_subscription": "恢复监控",
    "delete_live_subscription": "删除监控",
    "check_status": "系统状态",
    "check_tasks": "任务统计",
    "check_license": "授权信息",
    "check_failed_tasks": "失败任务",
    "smart_handle_url": "智能处理链接",
    "convert_record": "录制转码",
    "convert_unconverted": "批量转码",
    "chat_reply": "回复",
}

# ==================== 对话上下文管理 ====================

CONTEXT_TTL = 600  # 10 分钟过期
MAX_TOOL_ROUNDS = 5  # 最大 tool call 轮数
MAX_HISTORY_TURNS = 100  # 单会话最大保留轮数，防止内存泄漏


@dataclass
class ConversationTurn:
    """对话中的一轮（user / assistant / tool）"""
    role: str
    content: str
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class Conversation:
    """一个 session 的完整对话历史"""
    turns: List[ConversationTurn] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)

    def add_turn(self, turn: ConversationTurn):
        self.turns.append(turn)
        if len(self.turns) > MAX_HISTORY_TURNS:
            # 丢弃最早的 1/4 历史，保留最近的 3/4
            drop = len(self.turns) - MAX_HISTORY_TURNS
            self.turns = self.turns[drop:]
        self.last_active = time.time()

    def get_messages(self, max_turns: int = 20) -> List[Dict]:
        """构建 LLM messages 数组，截断旧对话"""
        messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        recent = self.turns[-max_turns:]
        for t in recent:
            msg: Dict[str, Any] = {"role": t.role, "content": t.content}
            if t.tool_call_id:
                msg["tool_call_id"] = t.tool_call_id
            if t.tool_calls:
                msg["tool_calls"] = t.tool_calls
            messages.append(msg)
        return messages

    def is_expired(self) -> bool:
        return time.time() - self.last_active > CONTEXT_TTL


# ==================== LLM 配置读取 ====================

def _get_config_value(db: Session, key: str) -> str:
    """从 GlobalConfig 表读取配置值"""
    row = db.query(GlobalConfig).filter(GlobalConfig.key == key).first()
    return (row.value or "").strip() if row else ""


def get_llm_config(db: Session) -> Dict[str, Any]:
    """
    从数据库读取 LLM 配置（复用 ai_config 的配置）
    优先使用 llm_chat_provider 指定的提供商，否则按原有优先级：
    DeepSeek > MiniMax > OpenAI 兼容 > Ollama
    """
    # 读取所有提供商配置
    providers = [
        {
            "name": "deepseek",
            "enabled_key": "llm_deepseek_enabled",
            "key_key": "llm_deepseek_api_key",
            "url_key": "llm_deepseek_base_url",
            "model_key": "llm_deepseek_model",
            "default_url": "https://api.deepseek.com",
            "default_model": "deepseek-chat",
        },
        {
            "name": "minimax",
            "enabled_key": "llm_minimax_enabled",
            "key_key": "llm_minimax_api_key",
            "url_key": "llm_minimax_base_url",
            "model_key": "llm_minimax_model",
            "default_url": "https://api.minimaxi.com/v1",
            "default_model": "MiniMax-Text-01",
        },
        {
            "name": "openai_compat",
            "enabled_key": "llm_compat_enabled",
            "key_key": "llm_compat_api_key",
            "url_key": "llm_compat_base_url",
            "model_key": "llm_compat_model",
            "default_url": "",
            "default_model": "",
        },
        {
            "name": "ollama",
            "enabled_key": "llm_ollama_enabled",
            "key_key": None,  # Ollama 不需要 API Key
            "url_key": "llm_ollama_base_url",
            "model_key": "llm_ollama_model",
            "default_url": "http://127.0.0.1:11434",
            "default_model": "qwen2.5:7b",
        },
    ]

    def _resolve_one(p: Dict) -> Optional[Dict]:
        """解析单个提供商配置，返回 None 表示未启用或未配置"""
        enabled = _get_config_value(db, p["enabled_key"]).lower() == "true"
        if not enabled:
            return None

        api_key = ""
        if p["key_key"]:
            api_key = _get_config_value(db, p["key_key"])
        base_url = _get_config_value(db, p["url_key"]) or p["default_url"]
        model = _get_config_value(db, p["model_key"]) or p["default_model"]

        if not base_url or not model:
            return None

        # Ollama 的 base_url 默认不含 /v1，补上以便 _call_llm 拼接 /chat/completions
        if p["name"] == "ollama":
            normalized = base_url.rstrip("/")
            if not normalized.endswith("/v1"):
                normalized += "/v1"
            base_url = normalized

        return {
            "provider": p["name"],
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
        }

    # 1) 优先使用 llm_chat_provider 指定的提供商
    chat_provider = _get_config_value(db, "llm_chat_provider")

    if chat_provider == "none":
        # 用户明确关闭 AI 对话
        return {"provider": "none", "api_key": "", "base_url": "", "model": "none"}

    if chat_provider and chat_provider != "auto":
        # 查找目标提供商，模型名直接使用该提供商自己的配置
        provider_index = {
            "deepseek": 0, "minimax": 1, "compat": 2, "ollama": 3,
        }
        idx = provider_index.get(chat_provider)
        if idx is not None:
            resolved = _resolve_one(providers[idx])
            if resolved:
                return resolved

    # 2) fallback: 按优先级取第一个启用的
    for p in providers:
        resolved = _resolve_one(p)
        if resolved:
            return resolved

    # 3) 全部未启用时 fallback 到 Ollama
    return {
        "provider": "ollama",
        "api_key": "",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
    }


# ==================== LLM 调用 ====================

async def _call_llm(messages: List[Dict], config: Dict) -> Dict:
    """调用 LLM API（OpenAI 兼容格式）"""
    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"

    body = {
        "model": config["model"],
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_tokens": 1024,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{config['base_url'].rstrip('/')}/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


# ==================== Tool 执行 ====================

async def _execute_tool(name: str, arguments: Dict, db: Session) -> Dict:
    """执行 tool call，映射到 bot_commands 或其他已有 API"""
    try:
        if name == "add_subscription":
            return await cmd.add_subscription(arguments["url"])

        elif name == "list_subscriptions":
            # LLM 调用时默认一次拿 100 条，避免需要翻页
            return await cmd.check_subscriptions(page=arguments.get("page", 1), page_size=100)

        elif name == "pause_subscription":
            return await cmd.pause_subscription(arguments["subscription_id"])

        elif name == "resume_subscription":
            return await cmd.resume_subscription(arguments["subscription_id"])

        elif name == "delete_subscription":
            if not arguments.get("confirmed"):
                return {"success": False, "error": "操作已取消，需要用户确认后才能删除"}
            return await cmd.delete_subscription(arguments["subscription_id"])

        elif name == "check_subscription_update":
            from routers.subscribe.sync import check_subscription_update
            result = await check_subscription_update(arguments["subscription_id"], db)
            # check_subscription_update 返回格式不带 success 字段，补充兼容
            if isinstance(result, dict) and "success" not in result:
                has_error = isinstance(result.get("error"), str) and result["error"]
                result["success"] = not has_error
            return result

        elif name == "download_video":
            return await cmd.download_url(arguments["url"])

        elif name == "list_downloads":
            result = await cmd.check_tasks()
            # 支持按 status 筛选
            status_filter = arguments.get("status", "all")
            if status_filter != "all" and result.get("success"):
                count_key = {
                    "downloading": "downloading",
                    "pending": "pending",
                    "completed": "completed",
                    "failed": "failed",
                }
                key = count_key.get(status_filter)
                if key and key in result:
                    result["filtered_status"] = status_filter
                    result[status_filter] = result[key]
            return result

        elif name == "retry_download":
            return await cmd.retry_task(arguments["task_id"])

        elif name == "delete_download":
            if not arguments.get("confirmed"):
                return {"success": False, "error": "操作已取消，需要用户确认后才能删除"}
            return await cmd.delete_task(arguments["task_id"])

        elif name == "add_live_subscription":
            return await cmd.add_live_subscription(arguments["url"])

        elif name == "list_live_subscriptions":
            return await cmd.check_live_subscriptions(page=arguments.get("page", 1), page_size=100)

        elif name == "pause_live_subscription":
            return await cmd.pause_live_subscription(arguments["live_id"])

        elif name == "resume_live_subscription":
            return await cmd.resume_live_subscription(arguments["live_id"])

        elif name == "delete_live_subscription":
            if not arguments.get("confirmed"):
                return {"success": False, "error": "操作已取消，需要用户确认后才能删除"}
            return await cmd.delete_live_subscription(arguments["live_id"])

        elif name == "check_status":
            return await cmd.check_status()

        elif name == "check_tasks":
            return await cmd.check_tasks()

        elif name == "check_license":
            return await cmd.check_license()

        elif name == "check_failed_tasks":
            return await cmd.check_failed_tasks()

        elif name == "smart_handle_url":
            url = arguments["url"]
            context = arguments.get("context", "")
            # handle_url 内部已包含 resolve_url，无需提前解析
            return await cmd.handle_url(url, context)

        elif name == "convert_record":
            from live.routers import convert_to_mp4 as _convert
            delete_original = arguments.get("delete_original", True)
            if isinstance(delete_original, bool):
                delete_original_val = delete_original
            else:
                delete_original_val = str(delete_original).lower() in ("true", "1")
            try:
                result = await _convert(
                    record_id=arguments["record_id"],
                    delete_original=delete_original_val,
                    db=db,
                )
                if isinstance(result, dict):
                    return result
                return {"success": True, "message": "转码任务已加入队列"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "convert_unconverted":
            from live.routers import convert_unconverted_to_mp4 as _batch_convert
            subscription_id = arguments.get("subscription_id") or None
            delete_original = arguments.get("delete_original", True)
            if isinstance(delete_original, bool):
                delete_original_val = delete_original
            else:
                delete_original_val = str(delete_original).lower() in ("true", "1")
            try:
                result = await _batch_convert(
                    subscription_id=subscription_id or None,
                    delete_original=delete_original_val,
                    db=db,
                )
                if isinstance(result, dict):
                    return result
                return {"success": True, "message": "批量转码任务已加入队列"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif name == "chat_reply":
            # chat_reply 不需要执行操作，直接返回
            return {"success": True, "reply": arguments["message"]}

        else:
            return {"success": False, "error": f"未知工具: {name}"}

    except Exception as e:
        logger.error(f"执行工具 {name} 失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# ==================== 格式化操作结果 ====================

def format_actions_summary(actions: List[Dict]) -> str:
    """将操作结果列表格式化为人类可读文本"""
    lines = []
    seen = set()
    for a in actions:
        tool = a.get("tool", "")
        r = a.get("result", {})
        if tool == "chat_reply":
            continue

        icon = "✅" if r.get("success") else "❌"
        name = TOOL_DISPLAY_NAMES.get(tool, tool)

        # 去重：相同工具名只显示一次
        key = f"{icon}{name}"
        if key in seen:
            continue
        seen.add(key)

        detail = ""
        # 提取关键信息作为详情
        if r.get("name"):
            detail = f": {r['name']}"
        elif r.get("anchor_name"):
            detail = f": {r['anchor_name']}"
        elif r.get("error"):
            detail = f": {r['error'][:50]}"
        # 停止录制时附加转码状态
        if r.get("recording_stopped") and name == "暂停监控":
            detail += (" → 已自动转码" if r.get("converted") else " → 转码排队中")

        lines.append(f"{icon} {name}{detail}")

    return "\n".join(lines) if lines else ""


# ==================== 降级关键词匹配 ====================

async def _fallback_keyword(user_message: str) -> Dict:
    """LLM 不可用时的降级：关键词匹配 + URL 检测"""
    text = user_message.strip()
    url = cmd.extract_url(text)

    # 有 URL 时走智能处理
    if url:
        resolved = await cmd.resolve_url(url)
        result = await cmd.handle_url(resolved, text)
        if result.get("success"):
            action = result.get("action", "")
            if action == "sub":
                reply = "🔗 检测到订阅链接，正在处理..."
            elif action == "live":
                reply = "📡 检测到直播链接，正在处理..."
            else:
                reply = "📥 检测到视频链接，正在处理..."
            return {
                "success": True,
                "reply": reply,
                "actions": [{"tool": "smart_handle_url", "result": result}],
                "session_id": "",
            }

    def _fmt_fallback_reply(result: Dict, fallback: str, tool: str = "") -> str:
        """将降级模式的操作结果格式化为易读文本"""
        if not result.get("success"):
            return f"{fallback}\n❌ {result.get('error', '操作失败')}"
        parts = [fallback]
        # check_status — 系统状态详细报告
        if result.get("cpu") is not None:
            parts.append(f"CPU: {result['cpu']}% | 内存: {result.get('mem_percent', '?')}% | 磁盘: {result.get('disk_percent', '?')}%")
            parts.append(f"下载: {result.get('downloading', 0)} 等待: {result.get('pending', 0)} 完成: {result.get('completed', 0)} 失败: {result.get('failed', 0)}")
            parts.append(f"订阅: {result.get('total_subs', 0)}（正常 {result.get('active_subs', 0)} 暂停 {result.get('paused_subs', 0)} 异常 {result.get('error_subs', 0)}）")
            parts.append(f"直播监控: {result.get('total_lives', 0)}（正在直播 {result.get('live_count', 0)} 录制中 {result.get('recording', 0)}）")
            lic = ""
            if result.get("license_lifetime"):
                lic = "✅ 永久授权"
            elif result.get("license_valid"):
                lic = f"✅ 有效（剩余 {result.get('license_remaining', '?')} 天）"
            else:
                lic = "❌ 无效"
            parts.append(f"授权: {lic}")
            return "\n".join(parts)
        # check_license — 独立授权查询
        if tool == "check_license":
            s = result.get("status", "")
            if s == "valid":
                if result.get("type") == "lifetime":
                    parts.append("✅ 永久授权有效")
                elif result.get("remaining_days"):
                    parts.append(f"✅ 授权有效（剩余 {result['remaining_days']} 天）")
                else:
                    parts.append("✅ 授权有效")
            elif s == "expired":
                parts.append("❌ 授权已过期")
            else:
                parts.append("❌ 授权无效或未激活")
            return "\n".join(parts)
        # 总数 + 分页
        if result.get("total") is not None:
            parts.append(f"共 {result['total']} 条")
            if result.get("total_pages", 0) > 1:
                parts.append(f"第 {result.get('page', 1)}/{result['total_pages']} 页（翻页需指定页码）")
        # 列表条目
        items = result.get("items", [])
        if items:
            for item in items[:10]:
                name = item.get("name") or item.get("anchor_name") or item.get("title") or item.get("id", "?")
                status_text = ""
                if item.get("status"):
                    status_text = f" [{item['status']}]"
                if item.get("error"):
                    status_text = f" ❌{item['error'][:30]}"
                parts.append(f"  • {name}{status_text}")
        # 下载任务统计
        if result.get("downloading") is not None and result.get("cpu") is None:
            parts.append(f"总数: {result.get('total', 0)}")
            parts.append(f"下载中: {result['downloading']} | 等待: {result.get('pending', 0)} | 完成: {result.get('completed', 0)} | 失败: {result.get('failed', 0)}")
        # 失败任务
        if result.get("total") is not None and tool == "check_failed_tasks":
            if result["total"] == 0:
                parts.append("🎉 没有失败任务")
        return "\n".join(parts)

    # 关键词匹配
    keyword_map = [
        (["状态", "系统", "运行", "cpu", "内存", "磁盘", "status"], "check_status", "📊 系统状态", cmd.check_status),
        (["任务", "下载中", "队列", "tasks"], "check_tasks", "📋 任务统计", cmd.check_tasks),
        (["订阅", "订阅列表", "我的订阅", "有哪些订阅", "订阅了", "subs"], "list_subscriptions", "📺 订阅列表", lambda: cmd.check_subscriptions()),
        (["直播", "直播列表", "直播监控", "谁在直播", "哪些直播", "lives"], "list_live_subscriptions", "📡 直播列表", lambda: cmd.check_live_subscriptions()),
        (["授权", "激活", "license"], "check_license", "🔑 授权信息", cmd.check_license),
        (["失败", "错误", "failed"], "check_failed_tasks", "❌ 失败任务", cmd.check_failed_tasks),
    ]

    for keywords, tool_name, hint, func in keyword_map:
        if any(k in text for k in keywords):
            result = await func()
            reply = _fmt_fallback_reply(result, hint, tool=tool_name)
            return {
                "success": True,
                "reply": reply,
                "actions": [{"tool": tool_name, "result": result}],
                "session_id": "",
            }

    return {
        "success": True,
        "reply": "🤖 当前未配置 AI 模型，对话能力不可用。\n可选操作：\n• 在「系统设置 → AI 模型配置 → 凭证管理」中配置并启用 DeepSeek、Ollama 等模型\n• 直接发送视频/直播/博主链接，系统自动处理\n• 输入「状态」「订阅」「任务」等关键词快速查询",
        "actions": [],
        "session_id": "",
    }


# ==================== 主入口 ====================

class LLMAssistant:
    """LLM 自然语言助手（三通道共享）"""

    def __init__(self):
        self._conversations: Dict[str, Conversation] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """获取或创建 session 级别的锁，保证同一会话消息串行处理"""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def _get_conversation(self, session_id: str) -> Conversation:
        """获取或创建对话上下文"""
        conv = self._conversations.get(session_id)
        if conv is None or conv.is_expired():
            conv = Conversation()
            self._conversations[session_id] = conv
        return conv

    def _cleanup_expired(self):
        """清理过期对话"""
        expired = [k for k, v in self._conversations.items() if v.is_expired()]
        for k in expired:
            del self._conversations[k]

    def clear_session(self, session_id: str):
        """清除指定 session 的对话历史"""
        self._conversations.pop(session_id, None)

    async def chat(self, session_id: str, user_message: str, db: Session) -> Dict:
        """
        主入口：处理用户消息，返回回复

        Args:
            session_id: 会话 ID（建议使用 前缀:id 格式，如 web:123, tg:456, wecom:abc）
            user_message: 用户输入的自然语言文本
            db: 数据库 session

        Returns:
            {
                "success": bool,
                "reply": "回复文本",
                "actions": [{"tool": "name", "result": {...}}, ...],
                "session_id": "xxx"
            }
        """
        # 用 session 级别锁保证同一会话的消息串行处理
        # 避免企微异步任务乱序 + 防止并发竞态
        async with self._get_lock(session_id):
            self._cleanup_expired()
            conv = self._get_conversation(session_id)

            # 添加用户消息
            conv.add_turn(ConversationTurn(role="user", content=user_message))

            # 获取 LLM 配置
            config = get_llm_config(db)

            # AI 对话已关闭 → 走关键词匹配，不走 LLM
            if config.get("provider") == "none":
                fallback = await _fallback_keyword(user_message)
                fallback["reply"] = "🤖 AI 对话已关闭，可前往「系统设置 → AI 模型配置 → 特征分配」重新开启。\n\n" + fallback.get("reply", "")
                fallback["session_id"] = session_id
                return fallback

            # 多轮 tool call 循环（最多 MAX_TOOL_ROUNDS 轮）
            actions: List[Dict] = []

            for _ in range(MAX_TOOL_ROUNDS):
                messages = conv.get_messages()

                try:
                    response = await _call_llm(messages, config)
                except Exception as e:
                    logger.error(f"LLM 调用失败 ({config['provider']}): {e}", exc_info=True)
                    return await _fallback_keyword(user_message)

                choice = response["choices"][0]
                msg = choice["message"]

                # 没有 tool_calls → 纯文本回复
                tool_calls = msg.get("tool_calls")
                if not tool_calls:
                    reply_text = msg.get("content", "") or ""
                    conv.add_turn(ConversationTurn(role="assistant", content=reply_text))
                    return {
                        "success": True,
                        "reply": reply_text,
                        "actions": actions,
                        "session_id": session_id,
                    }

                # 有 tool_calls → 记录 assistant 消息并执行
                conv.add_turn(ConversationTurn(
                    role="assistant",
                    content=msg.get("content", ""),
                    tool_calls=tool_calls,
                ))

                last_tool_name = None
                for tc in tool_calls:
                    fn = tc["function"]
                    tool_name = fn["name"]
                    last_tool_name = tool_name

                    try:
                        raw_args = fn["arguments"]
                        tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except (json.JSONDecodeError, TypeError):
                        tool_args = {}

                    # 执行工具
                    result = await _execute_tool(tool_name, tool_args, db)
                    actions.append({"tool": tool_name, "result": result})

                    # 记录 tool 结果
                    conv.add_turn(ConversationTurn(
                        role="tool",
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tc["id"],
                    ))

            # 如果最后一个是 chat_reply，直接返回其内容
            if last_tool_name == "chat_reply" and tool_calls:
                try:
                    last_args = json.loads(tool_calls[-1]["function"]["arguments"])
                    return {
                        "success": True,
                        "reply": last_args.get("message", ""),
                        "actions": actions,
                        "session_id": session_id,
                    }
                except (json.JSONDecodeError, TypeError, IndexError):
                    pass

        # 超过最大轮数
        summary = format_actions_summary(actions)
        reply = "操作已执行" + (f"：\n{summary}" if summary else "")
        return {
            "success": True,
            "reply": reply,
            "actions": actions,
            "session_id": session_id,
        }


# 全局单例
llm_assistant = LLMAssistant()
