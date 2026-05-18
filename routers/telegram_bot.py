
import asyncio
import logging
import json
import re
import aiohttp
import httpx
import traceback
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from sql.database_postgresql import get_session
from sql import models
# 延迟导入以避免循环依赖
# from routers.downloader import download_manager 

logger = logging.getLogger(__name__)
BOT_BATCH_SUPPRESS_TTL_SECONDS = 12 * 60 * 60
TG_SEND_MAX_ATTEMPTS = 3
TG_SEND_LOG_SUPPRESS_SECONDS = 120

class TelegramBotService:
    """Telegram 机器人服务（轻量级实现，基于aiohttp）"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TelegramBotService, cls).__new__(cls)
            cls._instance.is_running = False
            cls._instance.task = None
            cls._instance.token = None
            cls._instance.chat_id_whitelist = [] # 允许的 Chat ID 列表（当前只支持单用户，即配置中的 chat_id）
            cls._instance.proxy = None
            cls._instance.last_update_id = 0
            cls._instance.base_url = "https://api.telegram.org"
            cls._instance.music_search_states = {}
            # Bot 发起的批量下载上下文：subscription_id -> {chat_ids:set, started_at:datetime}
            cls._instance._bot_batch_context = {}
            # 发送类错误的限频状态：key -> {"last_log": monotonic, "suppressed": int}
            cls._instance._tg_send_log_state = {}
        return cls._instance

    @staticmethod
    def _tg_is_retryable_http_status(status: int) -> bool:
        return status in {429, 500, 502, 503, 504}

    @staticmethod
    def _tg_is_retryable_exception(exc: Exception) -> bool:
        return isinstance(exc, (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError))

    @staticmethod
    def _tg_retry_delay(attempt: int) -> float:
        # 0.6s, 1.2s, 2.4s
        return min(2.4, 0.6 * (2 ** max(0, attempt - 1)))

    def _log_tg_send_issue(self, key: str, message: str, level: str = "error") -> None:
        """
        Telegram 发送失败日志降噪：
        同类错误在窗口期内只记录一次，其余计数抑制，窗口后补充抑制次数。
        """
        now = time.monotonic()
        state = self._tg_send_log_state.get(key)
        if state and (now - state.get("last_log", 0.0) < TG_SEND_LOG_SUPPRESS_SECONDS):
            state["suppressed"] = int(state.get("suppressed", 0)) + 1
            self._tg_send_log_state[key] = state
            return

        suppressed = int(state.get("suppressed", 0)) if state else 0
        if suppressed > 0:
            message = f"{message}（同类报错已抑制 {suppressed} 次）"

        if level == "warning":
            logger.warning(message)
        elif level == "info":
            logger.info(message)
        else:
            logger.error(message)

        self._tg_send_log_state[key] = {"last_log": now, "suppressed": 0}

        # 简单清理，避免状态字典无限增长
        if len(self._tg_send_log_state) > 256:
            stale_before = now - TG_SEND_LOG_SUPPRESS_SECONDS * 4
            self._tg_send_log_state = {
                k: v for k, v in self._tg_send_log_state.items()
                if v.get("last_log", 0.0) >= stale_before
            }

    @staticmethod
    def escape_markdown(text: str) -> str:
        """转义 Markdown 特殊字符 (v1)，防止消息发送失败"""
        if not text:
            return ""
        # 针对 Markdown v1，只需要转义 _, *, [, `
        return text.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')

    def _build_sub_nav_token(self, entry: str = "list", page: int = 1, platform: str = "all") -> str:
        """构建订阅菜单导航 token（用于 callback_data 上下文传递）。"""
        if entry == "notif":
            return "n"
        safe_platform = (platform or "all").replace(":", "")
        safe_page = max(1, int(page or 1))
        return f"l{safe_page}_{safe_platform}"

    def _parse_sub_nav_token(self, token: Optional[str]) -> Dict[str, Any]:
        """解析订阅菜单导航 token。"""
        default_ctx = {"entry": "list", "page": 1, "platform": "all"}
        if not token:
            return default_ctx
        raw = str(token).strip().lower()
        if raw == "n":
            return {"entry": "notif", "page": 1, "platform": "all"}
        if raw.startswith("l"):
            payload = raw[1:]
            if "_" in payload:
                page_str, platform = payload.split("_", 1)
                try:
                    page = max(1, int(page_str))
                except Exception:
                    page = 1
                return {"entry": "list", "page": page, "platform": platform or "all"}
        return default_ctx

    def _build_sub_detail_callback(self, sub_id: str, nav_ctx: Optional[Dict[str, Any]] = None) -> str:
        """生成订阅详情 callback。"""
        ctx = nav_ctx or {"entry": "list", "page": 1, "platform": "all"}
        token = self._build_sub_nav_token(
            entry=ctx.get("entry", "list"),
            page=ctx.get("page", 1),
            platform=ctx.get("platform", "all")
        )
        return f"si:{sub_id}:{token}"

    def mark_bot_batch_started(self, subscription_id: str, chat_id: Optional[str] = None):
        """标记 Bot 发起的批量下载开始（用于通知降噪）。"""
        if not subscription_id:
            return
        sid = str(subscription_id).strip()
        if not sid:
            return
        ctx = self._bot_batch_context.get(sid) or {"chat_ids": set(), "started_at": datetime.now()}
        if chat_id:
            ctx["chat_ids"].add(str(chat_id))
        self._bot_batch_context[sid] = ctx

    def mark_bot_batch_finished(self, subscription_id: str, chat_id: Optional[str] = None):
        """标记 Bot 发起的批量下载结束。"""
        if not subscription_id:
            return
        sid = str(subscription_id).strip()
        if not sid:
            return
        if sid not in self._bot_batch_context:
            return
        if chat_id:
            ctx = self._bot_batch_context.get(sid) or {}
            chat_ids = ctx.get("chat_ids") or set()
            chat_ids.discard(str(chat_id))
            if chat_ids:
                ctx["chat_ids"] = chat_ids
                self._bot_batch_context[sid] = ctx
                return
        self._bot_batch_context.pop(sid, None)

    def should_suppress_completed_notification_for_bot_batch(self, subscription_id: str) -> bool:
        """是否应在 Bot 场景下静默单条下载完成通知。"""
        if not subscription_id:
            return False
        sid = str(subscription_id).strip()
        if not sid:
            return False
        ctx = self._bot_batch_context.get(sid)
        if not ctx:
            return False
        started_at = ctx.get("started_at")
        if isinstance(started_at, datetime):
            age_seconds = (datetime.now() - started_at).total_seconds()
            if age_seconds > BOT_BATCH_SUPPRESS_TTL_SECONDS:
                self._bot_batch_context.pop(sid, None)
                return False
        return True

    @contextmanager
    def _db_session(self):
        """统一数据库会话作用域，确保异常回滚与连接关闭。"""
        db = get_session()
        try:
            yield db
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                if db.in_transaction():
                    db.rollback()
            except Exception:
                pass
            try:
                db.close()
            except Exception:
                pass

    def load_config(self, db: Session):
        """从数据库加载配置"""
        try:
            # 获取第一个用户的设置（通常是管理员）
            # 或者遍历所有开启了 Bot 的用户？目前系统设计似乎偏向单用户或统一配置
            # 这里我们逻辑是：使用系统中第一个配置了 Token 的用户的设置
            
            # 查找所有设置
            settings = db.query(models.NotificationSetting).filter(
                models.NotificationSetting.telegram_bot_enabled == "true"
            ).all()
            
            valid_setting = None
            for s in settings:
                if s.telegram_bot_token:
                    valid_setting = s
                    break
            
            if valid_setting:
                self.token = valid_setting.telegram_bot_token
                # 支持逗号分隔的 chat_id (虽然数据库字段是 String，但预留多用户扩展)
                if valid_setting.telegram_chat_id:
                     self.chat_id_whitelist = [cid.strip() for cid in valid_setting.telegram_chat_id.split(',') if cid.strip()]
                else:
                    self.chat_id_whitelist = []

                # 安全加固：启用 Bot 时必须配置白名单 Chat ID，避免意外对外开放
                if not self.chat_id_whitelist:
                    logger.error("Telegram Bot 已启用但未配置 Chat ID 白名单，已拒绝启动")
                    self.token = None
                    return False
                
                self.proxy = valid_setting.telegram_proxy or None
                # 脱敏显示 Token 和 用户ID
                masked_token = f"{self.token[:3]}******" if self.token and len(self.token) > 3 else "******"
                logger.info(f"Telegram Bot配置已加载: {masked_token}, 允许的用户数: {len(self.chat_id_whitelist)}, 代理: {self.proxy}")
                return True
            else:
                logger.info("未找到有效的 Telegram Bot 配置或未启用")
                self.token = None
                return False
                
        except Exception as e:
            logger.error(f"加载 Telegram 配置失败: {e}")
            return False

    async def _set_bot_commands(self):
        """设置 Telegram Bot 的命令菜单"""
        if not self.token:
            return
            
        url = f"{self.base_url}/bot{self.token}/setMyCommands"
        commands = [
            {"command": "status", "description": "📊 查看系统与下载状态"},
            {"command": "failed", "description": "❌ 查看失败任务并处理"},
            {"command": "subs", "description": "📺 视频订阅列表"},
            {"command": "lives", "description": "📡 直播订阅列表"},
            {"command": "sub", "description": "➕ 添加视频 (例如: /sub 链接)"},
            {"command": "live", "description": "🔴 添加直播 (例如: /live 链接)"},
            {"command": "dl", "description": "⬇️ 强制下载 (例如: /dl 链接)"},
            {"command": "music", "description": "🎵 搜索网易云并点选下载"},
            {"command": "id", "description": "🆔 获取您的 Chat ID"},
            {"command": "help", "description": "❓ 帮助预览"},
            {"command": "restart", "description": "🔄 重启后端服务"}
        ]
        
        payload = {"commands": commands}
        
        async with aiohttp.ClientSession() as session:
            try:
                # 尝试设置新命令（会自动覆盖旧的）
                async with session.post(url, json=payload, proxy=self.proxy, timeout=10) as resp:
                    if resp.status == 200:
                        logger.debug("✅ Telegram Bot 命令菜单已更新")
                    else:
                        logger.warning(f"更新 Telegram 命令菜单失败: {resp.status} - {await resp.text()}")
            except Exception as e:
                logger.error(f"设置 Telegram 命令菜单异常: {e}")

    async def start(self):
        """启动轮询服务"""
        if self.is_running:
            return

        with self._db_session() as db:
            if not self.load_config(db):
                return

        if not self.token:
            return

        self.is_running = True
        # 启动时自动刷新命令菜单
        asyncio.create_task(self._set_bot_commands())
        self.task = asyncio.create_task(self._polling_loop())
        logger.info("🚀 Telegram Bot 服务已启动")

    async def stop(self):
        """停止服务"""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("Telegram Bot 服务已停止")

    async def reload(self):
        """重载配置并重启"""
        await self.stop()
        await self.start()

    async def _run_sync_videos_task(self, subscription_id: str, chat_id: str = None, progress_msg_id: int = None, title: str = ""):
        """后台执行全量同步，并支持向 TG 推送实时进度"""
        import time
        from routers.subscribe.sync import sync_videos
        
        last_update_time = time.time()
        
        async def bot_progress_callback(count: int, finished: bool = False, result: dict = None, error: Exception = None):
            if not self.token or not chat_id or not progress_msg_id:
                return
            
            now = time.time()
            nonlocal last_update_time
            
            if finished:
                if error:
                    text = f"❌ [{title}] 同步异常中止:\n{str(error)}"
                else:
                    new_count = result.get('new_videos', 0) if result else 0
                    text = f"✅ [{title}] 数据爬取及入库完成！\n本次共扫描 {count} 条记录，新增 {new_count} 个视频。"
                
                # 结束时无论间隔多久都强制发送一次
                asyncio.create_task(
                    self._edit_message(chat_id, progress_msg_id, text)
                )
            else:
                # 频率限制，3秒更新一次避免被滥用或API封禁 (TG limit default 1 update per sec)
                if now - last_update_time >= 3.0:
                    text = f"🔄 正在同步博主 **{title}** 的视频数据...\n> 已扫描: {count} 条记录"
                    asyncio.create_task(
                        self._edit_message(chat_id, progress_msg_id, text)
                    )
                    last_update_time = now

        try:
            with self._db_session() as db:
                await sync_videos(subscription_id, db, progress_callback=bot_progress_callback)
        except Exception as e:
            logger.error(f"后台同步任务失败 subscription_id={subscription_id}: {e}")
            if chat_id and progress_msg_id:
                asyncio.create_task(
                    self._edit_message(chat_id, progress_msg_id, f"❌ [{title}] 后台同步异常: {str(e)}")
                )

    async def _polling_loop(self):
        """长轮询主循环"""
        logger.debug("Telegram Bot 开始轮询...")
        retry_count = 0
        
        # 首次启动先清空积压的消息（可选，如果不希望处理停机期间的消息）
        # await self._get_updates(offset=-1) 

        while self.is_running:
            try:
                updates = await self._get_updates(offset=self.last_update_id + 1, timeout=60)
                
                if updates:
                    for update in updates:
                        update_id = update.get('update_id')
                        self.last_update_id = max(self.last_update_id, update_id)
                        
                        # 异步处理每条消息，不阻塞轮询
                        asyncio.create_task(self._process_update_safe(update))
                
                if retry_count > 0:
                    logger.debug("Telegram 连接已恢复")
                retry_count = 0  # 成功后重置重试计数
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                retry_count += 1
                wait_time = min(retry_count * 2, 30)
                
                # 只有连续失败多次才警告，避免网络波动刷屏
                if retry_count <= 3:
                    logger.debug(f"Telegram 轮询连接波动 (重试 {retry_count}): {e}")
                else:
                    logger.warning(f"Telegram 轮询连接失败 (已重试 {retry_count} 次): {e}")
                
                await asyncio.sleep(wait_time)

    async def _get_updates(self, offset: int, timeout: int = 60) -> List[Dict]:
        """调用 getUpdates API"""
        url = f"{self.base_url}/bot{self.token}/getUpdates"
        params = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"] # 增加回调查询支持
        }
        
        # 强制使用 IPv4，避免 Docker 环境下 IPv6 解析导致连接失败
        import socket
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.get(url, params=params, proxy=self.proxy, timeout=timeout + 10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("ok"):
                            return data.get("result", [])
                        else:
                            logger.error(f"Telegram API 错误: {data}")
                    elif resp.status == 401: # Token 无效
                        logger.error("Telegram Token 无效，停止服务")
                        self.is_running = False
                    else:
                        logger.warning(f"Telegram HTTP 错误: {resp.status}")
            except Exception as e:
                raise e
        return []

    async def _process_update_safe(self, update: Dict):
        """安全地处理单条更新"""
        try:
            if 'message' in update:
                await self._handle_message(update)
            elif 'callback_query' in update:
                await self._handle_callback_query(update['callback_query'])
        except Exception as e:
            logger.error(f"处理更新失败: {e}\n{traceback.format_exc()}")

    async def _handle_message(self, update: Dict):
        """处理消息逻辑"""
        message = update.get('message')
        if not message:
            return

        chat_id = str(message.get('chat', {}).get('id'))
        text = message.get('text', '').strip()
        user = message.get('from', {})
        username = user.get('username') or user.get('first_name')
        
        # 1. 鉴权：白名单机制
        # 如果是私聊且不在白名单中
        if self.chat_id_whitelist and chat_id not in self.chat_id_whitelist:
            logger.warning(f"收到未授权的消息: {text[:20]}... from {chat_id} ({username})")
            await self.send_message(chat_id, f"🚫 **未授权的访问**\n\n您的 Chat ID 是: `{chat_id}`\n请在 Easy-VDL 设置 -> 通知的 Telegram 配置中添加此 ID。")
            return
            
        logger.debug(f"收到 TG 消息 [{username}]: {text}")

        # 2. 命令路由
        # 2.0 媒体入站（独立模块）：接收用户发送的视频/图片并保存
        if (
            message.get('video')
            or message.get('photo')
            or message.get('document')
            or message.get('animation')
            or message.get('sticker')
        ):
            try:
                from services.telegram_media_service import telegram_media_service
                with self._db_session() as db:
                    result = await telegram_media_service.ingest_update(update, db)
                media_type = result.get("media_type") or "media"
                deleted_hint = "（原消息已删除）" if result.get("source_message_deleted") else ""
                
                # 如果取消下载，size_bytes 会返回 0，不需要再次发送成功通知
                if result.get("size_bytes", -1) != 0:
                    await self.send_message(
                        chat_id,
                        f"✅ 已接收并转存{media_type}{deleted_hint}",
                        parse_mode=None
                    )
            except Exception as e:
                err_text = str(e)
                # 对可预期的业务错误（如文件过大/白名单/授权）降级为警告，避免刷 traceback。
                if isinstance(e, (ValueError, PermissionError)):
                    logger.warning(f"Telegram 媒体入站失败(业务): chat_id={chat_id}, reason={err_text}")
                else:
                    logger.error(f"处理 Telegram 媒体入站失败: {e}\n{traceback.format_exc()}")
                await self.send_message(chat_id, f"❌ 媒体保存失败: {err_text}", parse_mode=None)
            return

        if text.startswith('/'):
            command_parts = text.split()
            command = command_parts[0].lower()
            args = command_parts[1:]
            
            if command == '/start':
                await self.send_message(chat_id, 
                    "👋 **欢迎使用 Easy-VDL 全能管家**\n\n"
                    "🤖 **智能识别模式已开启**\n"
                    "您可以直接粘贴视频/直播/主页链接，我会自动识别处理！\n"
                    "_(如果识别不准确或无法下载，请尝试使用下方指令手动添加)_\n\n"
                    "也支持使用以下命令：\n"
                    "📊 `/status` - 查看系统状态\n"
                    "❌ `/failed` - 失败任务列表\n"
                    "📺 `/subs` - 视频订阅列表\n"
                    "📡 `/lives` - 直播订阅列表\n"
                    "➕ `/sub <链接>` - 强制添加订阅\n"
                    "🔴 `/live <链接>` - 强制添加直播\n"
                    "⬇️ `/dl <链接>` - 强制加入下载队列\n"
                    "🎵 `/music <关键词>` - 搜索网易云并点选下载\n"
                    "❓ `/help` - 完整功能菜单\n"
                    f"\n您的 Chat ID: `{chat_id}`"
                )
            elif command == '/lives':
                from routers.license import license_manager
                if not await license_manager.verify():
                    await self.send_message(chat_id, "🔒 **功能限制**\n\n直播订阅功能是高级功能，您的授权无效或已过期。")
                    return
                await self._handle_lives_command(chat_id)
            elif command == '/help':
                await self.send_message(chat_id,
                    "🛠 **功能菜单**\n\n"
                    "🚀 **直接使用**\n"
                    "直接粘贴链接发送给机器人，支持自动识别：\n"
                    "• **单视频**：直接下载\n"
                    "• **博主/合集**：引导添加订阅（支持抖音、YouTube、B站、TikTok、Instagram、小红书、网易云）\n"
                    "• **直播间**：引导添加监控录制\n\n"
                    "📥 **媒体转存 · LIFETIME**\n"
                    "直接发送 **视频/图片** 给机器人可自动转存到本地（静默保存，不进入下载列表）。\n"
                    "⚠️ 转存功能当前为 **LIFETIME（永久高级授权）** 专享测试特权，且仅白名单 Chat ID 可用。\n\n"
                    "📏 **大小限制**\n"
                    "系统已内置 MTProto 协议支持突破原本的 20MB 限制，最高支持约 **2000MB (2GB)** 的文件直连下载。\n"
                    "超过 2GB 的文件会提示失败，请截取后再发送或改用其它转存方式。\n\n"
                    "⚠️ **注意**：智能识别依赖平台适配，可能存在遗漏。\n"
                    "如果您发送链接后**未弹出引导**或**下载失败**，请配合使用下方的 **强制指令** 进行手动添加。\n\n"
                    "1️⃣ **强制指令** (兜底方案)\n"
                    "• `/sub <链接>`: 强制解析为订阅源\n"
                    "• `/live <链接>`: 强制解析为直播间\n"
                    "• `/dl <链接>`: 强制解析为下载任务（跳过订阅/直播分流）\n\n"
                    "3️⃣ **音乐搜索下载**\n"
                    "• `/music <关键词>`: 搜索网易云歌曲并点选下载\n"
                    "• `/sub <网易云歌单链接>`: 添加网易云歌单订阅\n\n"
                    "2️⃣ **系统指令**\n"
                    "/status - 查看系统状态\n"
                    "/failed - 失败任务列表（可重试/删除）\n"
                    "/subs - 视频订阅列表\n"
                    "/lives - 直播订阅列表\n"
                    "/restart confirm - 重启后端服务\n"
                    "/id - 获取当前 Chat ID\n\n"
                    "📪 **反馈与建议**\n"
                    "遇到未适配的链接？欢迎加入 [Easy-VDL 交流群](https://t.me/+7jcTMePlNVwwZjg1) 反馈！"
                )
            elif command == '/id':
                await self.send_message(chat_id, f"🆔 您的 Chat ID: `{chat_id}`")
            
            elif command == '/status':
                await self._handle_status_command(chat_id)
            elif command == '/failed':
                await self._handle_failed_tasks_command(chat_id, page=1)
                
            elif command == '/subs':
                await self._handle_subs_command(chat_id, page=1)
                
            elif command == '/sub':
                if not args:
                    await self.send_message(chat_id, "用法：`/sub <博主主页链接>`")
                else:
                    # 从整个消息中提取URL
                    urls = re.findall(r'https?://[^\s]+', text)
                    if urls:
                        await self._handle_subscribe_command(chat_id, urls[0])
                    else:
                        await self._handle_subscribe_command(chat_id, args[0])

            elif command == '/live':
                from routers.license import license_manager
                if not await license_manager.verify():
                    await self.send_message(chat_id, "🔒 **功能限制**\n\n直播订阅功能是高级功能，您的授权无效或已过期。")
                    return
                if not args:
                    await self.send_message(chat_id, "用法：`/live <直播间链接>`")
                else:
                    urls = re.findall(r'https?://[^\s]+', text)
                    if urls:
                        await self._handle_add_live_subscription(chat_id, urls[0])
                    else:
                        await self.send_message(chat_id, "❌ 请提供有效的链接")

            elif command == '/dl':
                if not args:
                    await self.send_message(chat_id, "用法：`/dl <视频链接>`")
                else:
                    await self._handle_download_request(chat_id, text, force_download=True)
            elif command == '/music':
                if not args:
                    await self.send_message(chat_id, "用法：`/music <歌曲名或歌手>`")
                else:
                    keyword = " ".join(args).strip()
                    await self._handle_netease_search_command(chat_id, keyword)
            
            elif command == '/restart':
                if not args or args[0].lower() != 'confirm':
                    await self.send_message(chat_id, "⚠️ 重启是高风险操作。\n请使用 `/restart confirm` 确认执行。")
                    return
                await self.send_message(chat_id, "🔄 正在重启服务...")
                import os, sys
                # 这种重启方式比较暴力，但在容器里通常由 supervisor 或 docker 接管
                os.execv(sys.executable, ['python'] + sys.argv)
                
            else:
                await self.send_message(chat_id, "🤔 未知命令，输入 /help 查看帮助。")

        # 3. 链接识别 (非命令文本)
        elif self._is_url(text):
            # 提取 URL
            url_match = re.search(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', text)
            if url_match:
                url = url_match.group(0)
                
                # 智能识别明确的直播链接。
                # 注意：xhslink.com 是小红书通用短链，包含笔记/主页/直播，不能仅凭域名判定为直播。
                if any(host in url for host in [
                    'live.douyin.com',
                    'live.bilibili.com',
                    'huya.com',
                    'xiaohongshu.com/livestream',
                    'youtube.com/live/',
                    'miguvideo.com',
                ]):
                    msg = (
                        "💡 **检测到直播录制链接**\n\n"
                        "这是一个直播间链接，建议使用直播订阅功能进行监控录制：\n"
                        f"`/live {url}`\n\n"
                        "订阅后系统将自动监控开播并录制。"
                    )
                    await self.send_message(chat_id, msg)
                    return

            await self._handle_download_request(chat_id, text)
        
        else:
            # 只有在私聊时才回复闲聊，群组里不回复
            if message.get('chat', {}).get('type') == 'private':
                await self.send_message(chat_id, "我听不懂... 请发送视频链接或使用命令。")

    def _is_url(self, text: str) -> bool:
        """简单检查是否包含 URL"""
        return 'http://' in text or 'https://' in text

    def _clean_url(self, url: str) -> str:
        """清洗 URL，剔除冗余的追踪参数"""
        if not url:
            return url
        try:
            from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
            u = urlparse(url)

            # 小红书链接目前强依赖 query 参数中的 xsec_token 等做鉴权/反爬
            # 如果清洗掉这些参数，yt-dlp 很容易出现 "No video formats found"。
            # 因此对 xiaohongshu 相关域名直接返回原始 URL，不做任何裁剪。
            host = (u.netloc or '').lower()
            if 'xiaohongshu.com' in host or 'xhslink.com' in host:
                return url

            # 其他平台：只保留必要的关键参数，避免追踪参数过长导致存库/日志问题
            keep_params = ['v', 'id', 'room_id', 'p']  # 视频ID，直播间ID，分P等

            # 如果是抖音直播间或者 Webcast 链接，保留 room_id
            if 'douyin.com' in u.netloc or 'amemv.com' in u.netloc:
                keep_params.append('room_id')

            # B站部分页面（如 festival）依赖 query 中的 bvid/aid/cid 才能定位具体视频
            # 若清洗时丢失这些参数，yt-dlp 会报 Unsupported URL。
            if 'bilibili.com' in host or 'b23.tv' in host:
                keep_params.extend(['bvid', 'aid', 'cid', 'sid', 'ep_id', 'season_id'])
                
            query_params = parse_qsl(u.query)
            clean_params = [(k, v) for k, v in query_params if k in keep_params]
            
            # 如果清洗后没有参数了，直接返回不带问号的路径
            if not clean_params:
                return urlunparse((u.scheme, u.netloc, u.path, '', '', ''))
            
            return urlunparse((u.scheme, u.netloc, u.path, '', urlencode(clean_params), ''))
        except:
            return url

    async def _check_if_douyin_collection(self, url: str) -> bool:
        """检查抖音链接是否为合集"""
        from routers.subscribe.utils import _is_douyin_collection_url
        return await _is_douyin_collection_url(url)

    def _detect_subscription_link(self, url: str) -> Optional[str]:
        """检测是否为订阅类链接，并返回描述名称"""
        if not url: return None
        
        # 抖音相关
        if 'douyin.com/collection/' in url or '/collection/' in url:
            return "抖音合集"
        if 'douyin.com/user/' in url or '/user/' in url or '/share/user/' in url:
            return "抖音博主主页"
            
        # YouTube 播放列表
        if ('youtube.com' in url or 'youtu.be' in url) and 'list=' in url:
            return "YouTube播放列表"
            
        # YouTube 频道
        if ('youtube.com/@' in url or 'youtube.com/c/' in url or 'youtube.com/channel/' in url) and 'list=' not in url and '/watch' not in url:
            return "YouTube频道主页"
            
        # B站相关
        if 'bilibili.com' in url:
            if 'favlist' in url or 'fid=' in url:
                return "B站收藏夹"
            if 'space.bilibili.com' in url or '/space/' in url:
                return "B站UP主主页"
                
        # TikTok
        if 'tiktok.com/@' in url and '/video/' not in url:
            return "TikTok博主主页"
            
        # 小红书相关
        if 'xiaohongshu.com/user/profile/' in url or 'xhslink.com' in url:
            # 排除笔记链接（/explore/）和直播链接
            if '/explore/' not in url and '/livestream' not in url:
                return "小红书博主主页"

        # Instagram
        if 'instagram.com' in url and '/p/' not in url and '/reel/' not in url and '/stories/' not in url:
            return "Instagram博主主页"

        # 网易云歌单
        if 'music.163.com' in url and ('playlist' in url or 'id=' in url):
            return "网易云歌单"
            
        return None

    @staticmethod
    def _get_dir_size_bytes(path: str) -> int:
        """获取目录大小（字节），用于在线程池执行，避免阻塞事件循环。"""
        if not path or not os.path.exists(path):
            return 0
        try:
            import subprocess
            res = subprocess.run(['du', '-sb', path], capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout:
                return int(res.stdout.split()[0])
        except Exception:
            pass
        try:
            import subprocess
            res = subprocess.run(['du', '-sk', path], capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout:
                return int(res.stdout.split()[0]) * 1024
        except Exception:
            pass
        return 0

    def _collect_status_snapshot(self, task_ids: List[str]) -> Dict[str, Any]:
        """同步采集 /status 所需指标（在线程池执行）。"""
        import psutil
        import shutil
        from datetime import date
        DIVISOR = 1000 ** 3

        snapshot: Dict[str, Any] = {
            "cpu_percent": 0.0,
            "mem_used_gb": 0.0,
            "mem_total_gb": 0.0,
            "disk_used_gb": 0.0,
            "disk_total_gb": 0.0,
            "disk_percent": 0.0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "active_subscriptions": 0,
            "total_subscriptions": 0,
            "paused_subscriptions": 0,
            "error_subscriptions": 0,
            "subscription_videos": 0,
            "total_live_subs": 0,
            "active_live_subs": 0,
            "live_count": 0,
            "recording_count": 0,
            "today_records": 0,
            "active_downloads": [],
            "queued_tasks": 0,
            "subscription_storage_gb": 0.0,
            "live_storage_gb": 0.0,
        }

        try:
            cpu_percent = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            snapshot["cpu_percent"] = cpu_percent
            snapshot["mem_used_gb"] = mem.used / (1024**3)
            snapshot["mem_total_gb"] = mem.total / (1024**3)
        except Exception:
            pass

        try:
            disk = shutil.disk_usage('/app/downloads')
            snapshot["disk_used_gb"] = disk.used / DIVISOR
            snapshot["disk_total_gb"] = disk.total / DIVISOR
            snapshot["disk_percent"] = (disk.used / disk.total) * 100
        except Exception:
            pass

        try:
            with self._db_session() as db:
                snapshot["completed_tasks"] = db.query(models.Task).filter(
                    models.Task.status == models.TaskStatus.COMPLETED.value
                ).count()
                snapshot["failed_tasks"] = db.query(models.Task).filter(
                    models.Task.status == models.TaskStatus.ERROR.value
                ).count()
                all_subscriptions = db.query(models.Subscription).all()
                snapshot["total_subscriptions"] = len(all_subscriptions)
                active_subscriptions = 0
                paused_subscriptions = 0
                error_subscriptions = 0
                for sub in all_subscriptions:
                    status = str(getattr(sub, "status", "") or "").lower()
                    if status == "error":
                        error_subscriptions += 1
                        continue
                    interval = getattr(sub, "check_interval", None)
                    if interval is None:
                        interval = getattr(sub, "update_interval", 0)
                    try:
                        interval_enabled = float(interval or 0) > 0
                    except Exception:
                        interval_enabled = False
                    auto_download = getattr(sub, "auto_download", False)
                    auto_download_enabled = (auto_download is True) or (str(auto_download).lower() == "true")
                    if status == "active" and interval_enabled and auto_download_enabled:
                        active_subscriptions += 1
                    else:
                        paused_subscriptions += 1
                snapshot["active_subscriptions"] = active_subscriptions
                snapshot["paused_subscriptions"] = paused_subscriptions
                snapshot["error_subscriptions"] = error_subscriptions
                snapshot["subscription_videos"] = db.query(models.SubscriptionVideo).count()
                snapshot["total_live_subs"] = db.query(models.LiveSubscription).count()
                snapshot["active_live_subs"] = db.query(models.LiveSubscription).filter(
                    models.LiveSubscription.auto_record == "true"
                ).count()
                snapshot["live_count"] = db.query(models.LiveSubscription).filter(
                    models.LiveSubscription.is_live == "true"
                ).count()
                snapshot["recording_count"] = db.query(models.LiveSubscription).filter(
                    models.LiveSubscription.is_recording == "true"
                ).count()
                today_start = datetime.combine(date.today(), datetime.min.time())
                snapshot["today_records"] = db.query(models.LiveRecord).filter(
                    models.LiveRecord.start_time >= today_start
                ).count()

                if task_ids:
                    tasks = db.query(models.Task).filter(models.Task.id.in_(task_ids)).all()
                    snapshot["active_downloads"] = [
                        {
                            "title": t.title,
                            "progress": t.progress,
                            "speed": "",
                            "total_size": ""
                        } for t in tasks
                    ]
                snapshot["queued_tasks"] = db.query(models.Task).filter(
                    models.Task.status == models.TaskStatus.PENDING.value
                ).count()
        except Exception:
            pass

        try:
            from live.recorder import live_recorder
            snapshot["recording_count"] = len(live_recorder.get_all_recording_ids())
        except Exception:
            pass

        try:
            size_bytes = self._get_dir_size_bytes("/app/downloads/subscriptions")
            if size_bytes > 0:
                snapshot["subscription_storage_gb"] = size_bytes / DIVISOR
        except Exception:
            pass

        try:
            from live.routers import _stats_data
            if _stats_data and _stats_data.get('total_size', 0) > 0:
                snapshot["live_storage_gb"] = _stats_data['total_size'] / DIVISOR
        except Exception:
            pass

        return snapshot


    async def _handle_status_command(self, chat_id: str):
        """处理 /status 命令"""
        try:
            from routers.downloader import download_manager
            query_ids = list(download_manager.tasks.keys())[:10] if download_manager.tasks else []

            # 获取授权信息
            from routers.license import license_manager, LicenseStatus
            from routers.version import get_build_version
            from routers.system import _get_core_version_with_cache

            snapshot, is_licensed, build_info, core_info = await asyncio.gather(
                asyncio.to_thread(self._collect_status_snapshot, query_ids),
                license_manager.verify(),
                get_build_version(),
                asyncio.to_thread(_get_core_version_with_cache)
            )

            license_status = license_manager.status
            remaining_days = license_manager.remaining_days
            
            # 判断授权类型
            if is_licensed and license_status == LicenseStatus.VALID:
                if remaining_days == -1 or remaining_days > 3650:
                    license_text = "👑 永久高级版"
                else:
                    license_text = f"⭐ 高级版 (剩余 {remaining_days} 天)"
            else:
                license_text = "🔰 基础版"
            
            app_version = "未知版本"
            core_version = "未知版本"
            if build_info and 'version' in build_info:
                app_version = build_info['version']
            if core_info and 'current_version' in core_info and core_info['current_version']:
                core_version = core_info['current_version']
            
            # 构建消息
            msg = f"📊 **系统状态**\n\n"
            
            # 授权信息
            msg += f"🔐 **授权信息**\n"
            msg += f"{license_text}\n\n"
            
            # 版本信息
            msg += f"📦 **版本信息**\n"
            msg += f"版本: `{app_version}`\n"
            msg += f"核心: `{core_version}`\n\n"
            
            # 系统资源
            msg += f"💻 **系统资源**\n"
            msg += f"CPU: `{snapshot['cpu_percent']}%` | 内存: `{snapshot['mem_used_gb']:.1f}/{snapshot['mem_total_gb']:.1f} GB`\n\n"
            
            # 数据统计
            msg += f"📈 **数据统计**\n"
            msg += f"✅ 已下载: `{snapshot['completed_tasks']}` 个视频\n"
            if snapshot['queued_tasks'] > 0:
                msg += f"⏳ 等待队列: `{snapshot['queued_tasks']}` 个\n"
            if snapshot['failed_tasks'] > 0:
                msg += f"❌ 下载失败: `{snapshot['failed_tasks']}` 个\n"
            msg += f"📺 订阅博主: `{snapshot['active_subscriptions']}/{snapshot['total_subscriptions']}` 个\n"
            if snapshot['paused_subscriptions'] > 0:
                msg += f"⏸️ 暂停订阅: `{snapshot['paused_subscriptions']}` 个\n"
            if snapshot['error_subscriptions'] > 0:
                msg += f"⚠️ 异常订阅: `{snapshot['error_subscriptions']}` 个\n"
            msg += f"📝 订阅视频: `{snapshot['subscription_videos']}` 条记录\n"
            msg += f"📡 直播监控: `{snapshot['active_live_subs']}/{snapshot['total_live_subs']}` 个\n"
            msg += f"🔴 正在直播: `{snapshot['live_count']}` 个\n"
            msg += f"📹 正在录制: `{snapshot['recording_count']}` 个\n"
            if snapshot['today_records'] > 0:
                msg += f"🎬 今日已录: `{snapshot['today_records']}` 个\n"
            msg += "\n"
            
            # 存储空间
            msg += f"💾 **存储空间**\n"
            msg += f"总空间: `{snapshot['disk_used_gb']:.2f} GB(1000) / {snapshot['disk_total_gb']:.2f} GB(1000)` ({snapshot['disk_percent']:.1f}%)\n"
            
            # 进度条
            bar_len = 15
            filled = int(snapshot['disk_percent'] / 100 * bar_len)
            bar = '█' * filled + '░' * (bar_len - filled)
            msg += f"`[{bar}]`\n"
            
            # 分类存储占用
            if snapshot['subscription_storage_gb'] > 0:
                msg += f"📁 视频订阅: `{snapshot['subscription_storage_gb']:.2f} GB(1000)`\n"
            if snapshot['live_storage_gb'] > 0:
                msg += f"📹 直播录制: `{snapshot['live_storage_gb']:.2f} GB(1000)`\n"
            msg += "\n"
            
            # 下载任务
            active_downloads = snapshot['active_downloads']
            if active_downloads:
                msg += f"⬇️ **正在下载 ({len(download_manager.tasks)})**\n"
                for i, task in enumerate(active_downloads[:5]):
                     title = task.get('title', '未知任务')
                     title = title.replace('*', '').replace('_', '').replace('`', '')
                     progress = task.get('progress', 0) or 0
                     
                     # 进度条
                     task_bar_len = 10
                     task_filled = int(progress / 100 * task_bar_len)
                     task_bar = '█' * task_filled + '░' * (task_bar_len - task_filled)
                     
                     msg += f"{i+1}. {title[:20]}...\n"
                     msg += f"   `[{task_bar}] {progress:.1f}%`\n"
            else:
                msg += "💤 当前没有正在进行的下载任务"
            
            await self.send_message(chat_id, msg)
            
        except Exception as e:
            logger.error(f"获取状态失败: {e}")
            await self.send_message(chat_id, f"❌ 获取状态失败: {str(e)}", parse_mode=None)

    async def _handle_subs_command(self, chat_id: str, page: int = 1, message_id: int = None, platform: str = "all"):
        """分页显示订阅列表"""
        page_size = 10
        try:
            with self._db_session() as db:
                # 1. 构建查询
                query = db.query(models.Subscription)
                if platform != "all":
                    query = query.filter(models.Subscription.platform == platform)
                
                total_count = query.count()
                total_pages = (total_count + page_size - 1) // page_size
                
                if total_count == 0:
                    await self.send_message(chat_id, "📭 您还没有任何订阅。\n直接发送博主主页链接即可添加。")
                    return

                # 确保页码合法
                page = max(1, min(page, total_pages))
                
                # 2. 获取当前页数据
                subs = query.order_by(models.Subscription.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
                
                # 3. 构建消息
                title_map = {
                    "all": "全部订阅",
                    "douyin": "抖音",
                    "bilibili": "B站",
                    "youtube": "YouTube",
                    "tiktok": "TikTok",
                    "netease": "网易云",
                    "xiaohongshu": "小红书",
                    "instagram": "Instagram"
                }
                msg = f"📺 **{title_map.get(platform, '订阅')} 列表** (第 {page}/{total_pages} 页)\n"
                msg += "------------------------\n"
                
                inline_keyboard = []
                nav_token = self._build_sub_nav_token(entry="list", page=page, platform=platform)
                
                platform_names = {
                    "douyin": "抖音",
                    "bilibili": "B站",
                    "youtube": "YouTube",
                    "tiktok": "TikTok",
                    "xiaohongshu": "小红书",
                    "netease": "网易云",
                    "instagram": "Instagram"
                }

                for i, sub in enumerate(subs):
                    p_name = platform_names.get(sub.platform, "其他")
                    # 避免 Markdown 报错
                    safe_name = self.escape_markdown(sub.nickname)
                    idx = (page - 1) * page_size + i + 1
                    msg += f"{idx}. [{p_name}] {safe_name}\n"
                    
                    # 每一行配备一个详情按钮
                    # 注意：Telegram 按钮 callback_data 限制为 64 字节，所以我们只传 ID 的前几位或完整 ID 如果长度允许
                    # 为了万无一失，我们使用 sub_info:<id>
                    if i % 2 == 0:
                        inline_keyboard.append([
                            {"text": f"{idx}. {safe_name[:10]}", "callback_data": f"si:{sub.id}:{nav_token}"}
                        ])
                    else:
                        inline_keyboard[-1].append(
                            {"text": f"{idx}. {safe_name[:10]}", "callback_data": f"si:{sub.id}:{nav_token}"}
                        )

                msg += "------------------------\n"
                msg += f"共 {total_count} 个订阅，点击下方按钮管理"

                # 4. 分页控制按钮
                nav_btns = []
                if page > 1:
                    nav_btns.append({"text": "⬅️ 上一页", "callback_data": f"sp:{page-1}:{platform}"})
                if page < total_pages:
                    nav_btns.append({"text": "下一页 ➡️", "callback_data": f"sp:{page+1}:{platform}"})
                
                if nav_btns:
                    inline_keyboard.append(nav_btns)
                
                # 5. 平台筛选按钮
                platform_btns = []
                filter_options = [
                    ("all", "全部"),
                    ("douyin", "抖音"),
                    ("bilibili", "B站"),
                    ("youtube", "油管"),
                    ("tiktok", "TK"),
                    ("netease", "网易云"),
                    ("xiaohongshu", "小红书"),
                    ("instagram", "Ins")
                ]
                
                for code, label in filter_options:
                    # 高亮当前选中的平台
                    btn_text = f"✅ {label}" if code == platform else label
                    platform_btns.append({"text": btn_text, "callback_data": f"sp:1:{code}"})
                
                # 第一行放前3个
                inline_keyboard.append(platform_btns[:3])
                # 第二行放剩下的
                if len(platform_btns) > 3:
                    inline_keyboard.append(platform_btns[3:])

                # 5. 发送或编辑消息
                if message_id:
                    await self._edit_message(chat_id, message_id, msg, inline_keyboard)
                else:
                    await self.send_message(chat_id, msg, reply_markup={"inline_keyboard": inline_keyboard})
        except Exception as e:
            logger.error(f"显示订阅列表失败: {e}\n{traceback.format_exc()}")
            await self.send_message(chat_id, "❌ 获取订阅列表失败")

    async def _handle_lives_command(self, chat_id: str, page: int = 1, message_id: int = None):
        """分页显示直播订阅列表"""
        page_size = 10
        try:
            with self._db_session() as db:
                # 1. 构建查询
                from sql.models import LiveSubscription
                total_count = db.query(LiveSubscription).count()
                total_pages = (total_count + page_size - 1) // page_size
                
                if total_count == 0:
                    text = "📭 您还没有任何直播订阅。\n使用 `/live <链接>` 添加。"
                    if message_id:
                        # 如果是回调编辑，但数据空了（例如全删了）
                        await self.send_message(chat_id, text)
                    else:
                        await self.send_message(chat_id, text)
                    return

                # 确保页码合法
                page = max(1, min(page, total_pages))
                
                # 2. 获取当前页数据
                subs = db.query(LiveSubscription).order_by(
                    LiveSubscription.is_live.desc(),  # 开播的排前面
                    LiveSubscription.is_recording.desc(), # 录制中的排前面
                    LiveSubscription.created_at.desc()
                ).offset((page - 1) * page_size).limit(page_size).all()
                
                # 3. 构建消息
                msg = f"📡 **直播订阅列表** (第 {page}/{total_pages} 页)\n"
                msg += "------------------------\n"
                
                inline_keyboard = []
                
                for i, sub in enumerate(subs):
                    # 状态图标
                    status_icon = "💤" # 默认休眠
                    if sub.is_recording == "true":
                        status_icon = "🔴" # 录制中
                    elif sub.is_live == "true":
                        status_icon = "🟢" # 直播中(未录制)
                    elif sub.auto_record == "true":
                        status_icon = "📡" # 监控中
                        
                    # 平台名称
                    platform_map = {"douyin": "抖音", "bilibili": "B站", "youtube": "油管", "migu": "咪咕", "tiktok": "TK"}
                    p_name = platform_map.get(sub.platform, sub.platform)
                    
                    # 避免 Markdown 报错
                    name = sub.anchor_name or "未知主播"
                    safe_name = self.escape_markdown(name)
                    
                    idx = (page - 1) * page_size + i + 1
                    msg += f"{idx}. {status_icon} [{p_name}] {safe_name}\n"

                    # [新增] 详情按钮 (每行2个)
                    btn_text = f"{idx}. {safe_name[:6]}"
                    if i % 2 == 0:
                        inline_keyboard.append([
                            {"text": btn_text, "callback_data": f"li:{sub.id}:{page}"}
                        ])
                    else:
                        inline_keyboard[-1].append(
                            {"text": btn_text, "callback_data": f"li:{sub.id}:{page}"}
                        )
                
                msg += "------------------------\n"
                msg += f"共 {total_count} 个订阅，点击上方按钮管理"

                # 4. 分页控制按钮
                nav_btns = []
                if page > 1:
                    nav_btns.append({"text": "⬅️ 上一页", "callback_data": f"lp:{page-1}"})
                if page < total_pages:
                    nav_btns.append({"text": "下一页 ➡️", "callback_data": f"lp:{page+1}"})
                
                if nav_btns:
                    inline_keyboard.append(nav_btns)

                # 5. 发送或编辑消息
                if message_id:
                    await self._edit_message(chat_id, message_id, msg, inline_keyboard)
                else:
                    await self.send_message(chat_id, msg, reply_markup={"inline_keyboard": inline_keyboard})
        except Exception as e:
            logger.error(f"显示直播订阅列表失败: {e}\n{traceback.format_exc()}")
            await self.send_message(chat_id, "❌ 获取直播列表失败")

    @staticmethod
    def _task_source_display(source: Optional[str]) -> str:
        source_map = {
            "douyin": "抖音",
            "bilibili": "B站",
            "youtube": "YouTube",
            "tiktok": "TikTok",
            "xiaohongshu": "小红书",
            "netease": "网易云",
            "x": "X",
            "others": "其他"
        }
        return source_map.get((source or "").lower(), source or "未知")

    async def _handle_failed_tasks_command(self, chat_id: str, page: int = 1, message_id: int = None):
        """分页展示失败任务，支持详情/重试/删除。"""
        page_size = 8
        try:
            with self._db_session() as db:
                query = db.query(models.Task).filter(models.Task.status == models.TaskStatus.ERROR.value)
                total_count = query.count()
                if total_count == 0:
                    text = "✅ 当前没有失败任务。"
                    if message_id:
                        await self._edit_message(chat_id, message_id, text, [[{"text": "🔄 刷新", "callback_data": "ff:1"}]])
                    else:
                        await self.send_message(chat_id, text)
                    return

                total_pages = (total_count + page_size - 1) // page_size
                page = max(1, min(page, total_pages))
                tasks = query.order_by(desc(models.Task.updated_at), desc(models.Task.created_at)).offset(
                    (page - 1) * page_size
                ).limit(page_size).all()

                msg = f"❌ **失败任务列表** (第 {page}/{total_pages} 页)\n"
                msg += "------------------------\n"
                inline_keyboard: List[List[Dict[str, str]]] = []

                for i, task in enumerate(tasks):
                    idx = (page - 1) * page_size + i + 1
                    source_text = self._task_source_display(task.source)
                    title = self.escape_markdown((task.title or "无标题").strip())
                    short_title = title[:20]
                    err_text = (task.error_message or "未知错误").strip().replace("\n", " ")
                    err_text = self.escape_markdown(err_text[:38])
                    msg += f"{idx}. [{source_text}] {short_title}\n"
                    msg += f"   `错误: {err_text}`\n"
                    inline_keyboard.append([
                        {"text": f"{idx}. {short_title[:10]}", "callback_data": f"fd:{task.id}:{page}"}
                    ])

                msg += "------------------------\n"
                msg += f"共 {total_count} 个失败任务，点击按钮查看详情并处理"

                nav_btns: List[Dict[str, str]] = []
                if page > 1:
                    nav_btns.append({"text": "⬅️ 上一页", "callback_data": f"ff:{page-1}"})
                if page < total_pages:
                    nav_btns.append({"text": "下一页 ➡️", "callback_data": f"ff:{page+1}"})
                if nav_btns:
                    inline_keyboard.append(nav_btns)
                inline_keyboard.append([{"text": "🔄 刷新", "callback_data": f"ff:{page}"}])

                if message_id:
                    await self._edit_message(chat_id, message_id, msg, inline_keyboard)
                else:
                    await self.send_message(chat_id, msg, reply_markup={"inline_keyboard": inline_keyboard})
        except Exception as e:
            logger.error(f"显示失败任务列表失败: {e}\n{traceback.format_exc()}")
            await self.send_message(chat_id, "❌ 获取失败任务列表失败")

    async def _handle_failed_task_detail(self, chat_id: str, task_id: str, message_id: int, return_page: int = 1):
        """显示失败任务详情和操作按钮。"""
        try:
            with self._db_session() as db:
                task = db.query(models.Task).filter(models.Task.id == task_id).first()
                if not task:
                    await self._edit_message(
                        chat_id,
                        message_id,
                        "⚠️ 任务不存在或已被处理。",
                        [[{"text": "⬅️ 返回失败列表", "callback_data": f"ff:{return_page}"}]]
                    )
                    return

                source_text = self._task_source_display(task.source)
                title = self.escape_markdown((task.title or "无标题").strip())
                url_text = self.escape_markdown((task.url or "无").strip())
                if len(url_text) > 120:
                    url_text = f"{url_text[:120]}..."
                err_text = self.escape_markdown((task.error_message or "未知错误").strip())
                if len(err_text) > 360:
                    err_text = f"{err_text[:360]}..."

                updated_at = task.updated_at or task.created_at
                updated_str = updated_at.strftime("%Y-%m-%d %H:%M:%S") if updated_at else "未知"

                msg = (
                    "📝 **失败任务详情**\n"
                    "----------------------\n"
                    f"🆔 任务ID: `{task.id[:8]}`\n"
                    f"🏷️ 来源: `{source_text}`\n"
                    f"📌 标题: `{title}`\n"
                    f"🕒 更新时间: `{updated_str}`\n"
                    f"🔗 链接: `{url_text}`\n\n"
                    f"❌ 错误信息:\n`{err_text}`"
                )
                inline_keyboard = [
                    [
                        {"text": "🔁 重试任务", "callback_data": f"fr:{task.id}:{return_page}"},
                        {"text": "🗑️ 删除任务", "callback_data": f"fx:{task.id}:{return_page}"}
                    ],
                    [{"text": "⬅️ 返回失败列表", "callback_data": f"ff:{return_page}"}]
                ]
                await self._edit_message(chat_id, message_id, msg, inline_keyboard)
        except Exception as e:
            logger.error(f"显示失败任务详情失败: {e}\n{traceback.format_exc()}")
            await self.send_message(chat_id, "❌ 获取失败任务详情失败")

    async def _retry_failed_task_by_id(self, task_id: str) -> str:
        """重试指定失败任务，复用下载中心重试逻辑。"""
        try:
            from routers.file_manager import retry_task_internal

            def _enqueue_task(func, *args):
                result = func(*args)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)

            with self._db_session() as db_session:
                res = retry_task_internal(task_id, db_session, _enqueue_task)
                return res.get("message", "任务已开始重试")
        except Exception as e:
            detail = getattr(e, "detail", None)
            raise RuntimeError(str(detail or e))

    async def _delete_failed_task_by_id(self, task_id: str) -> str:
        """删除失败任务并清理关联文件/临时残留。"""
        try:
            from routers.file_manager import cleanup_task_before_delete

            with self._db_session() as db_session:
                task = db_session.query(models.Task).filter(models.Task.id == task_id).first()
                if not task:
                    raise RuntimeError("任务不存在")

                cleanup_res = cleanup_task_before_delete(task, delete_output=True, delete_temp=True)
                related_videos = db_session.query(models.SubscriptionVideo).filter(
                    models.SubscriptionVideo.download_task_id == task_id
                ).all()
                for video in related_videos:
                    video.downloaded = "false"
                    video.download_task_id = None
                    video.error_message = None

                db_session.delete(task)
                db_session.commit()

                deleted_count = len(cleanup_res.get("output", [])) + len(cleanup_res.get("temp", []))
                if deleted_count > 0:
                    return f"任务已删除，并清理 {deleted_count} 个文件"
                return "任务已删除"
        except Exception as e:
            detail = getattr(e, "detail", None)
            raise RuntimeError(str(detail or e))

    async def _handle_callback_query(self, callback_query: Dict):
        """处理内联按钮点击回调"""
        query_id = callback_query.get('id')
        callback_message = callback_query.get('message', {}) or {}
        chat_id = str(callback_message.get('chat', {}).get('id'))
        message_id = callback_message.get('message_id')
        # 仅文本消息可使用 editMessageText；图片/视频消息需要新发文本消息
        can_edit_text_message = bool(callback_message.get('text'))
        data = callback_query.get('data', '')

        # 鉴权
        if self.chat_id_whitelist and chat_id not in self.chat_id_whitelist:
            return

        # 授权检查：订阅/直播相关操作都需要高级版授权
        if data.startswith((
            'si:', 'sc:', 'ss:', 'svl:', 'svd:', 'sdl:', 'sda:', 'sdr:', 'sdc:', 'sst:', 'sf:', 'sd:', 'lp:',
            'trn:', 'tdn:',
            'li:', 'lar:', 'ldel:', 'ldel_confirm:', 'lstart:', 'lstop:'
        )):
            from routers.license import license_manager
            if not await license_manager.verify():
                await self._answer_callback_query(query_id, "🔒 需要高级版授权\n请前往爱发电获取授权", show_alert=True)
                return

        try:
            callback_answered = False

            async def ack_once(text: str = "", show_alert: bool = False):
                nonlocal callback_answered
                if callback_answered:
                    return
                await self._answer_callback_query(query_id, text, show_alert=show_alert)
                callback_answered = True

            if data.startswith('cancel_mtproto:'):
                try:
                    from services.telegram_media_service import telegram_media_service
                    download_msg_id = int(data.split(':')[1])
                    telegram_media_service.cancel_download(download_msg_id)
                    await ack_once("🛑 已发送取消请求", show_alert=True)
                except Exception as e:
                    logger.error(f"取消下载失败: {e}")
                    await ack_once("取消失败", show_alert=False)
                return

            # 1. 分页处理: sp:page:platform
            if data.startswith('sp:'):
                await ack_once("📄 已切换页面")
                _, page, platform = data.split(':')
                await self._handle_subs_command(chat_id, page=int(page), message_id=message_id, platform=platform)

            # 1.1 直播分页: lp:page
            elif data.startswith('lp:'):
                await ack_once("📄 已切换页面")
                page = data.split(':')[1]
                await self._handle_lives_command(chat_id, page=int(page), message_id=message_id)

            # 1.2 失败任务分页: ff:page
            elif data.startswith('ff:'):
                await ack_once("📄 已切换页面")
                page = data.split(':')[1]
                await self._handle_failed_tasks_command(chat_id, page=int(page), message_id=message_id)

            # 1.3 失败任务详情: fd:task_id:page
            elif data.startswith('fd:'):
                await ack_once("📝 正在打开失败任务详情")
                parts = data.split(':')
                task_id = parts[1]
                return_page = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 1
                await self._handle_failed_task_detail(chat_id, task_id, message_id, return_page=return_page)

            # 1.4 失败任务重试: fr:task_id:page
            elif data.startswith('fr:'):
                await ack_once("⏳ 正在重试任务...")
                parts = data.split(':')
                task_id = parts[1]
                return_page = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 1
                try:
                    retry_msg = await self._retry_failed_task_by_id(task_id)
                    await self.send_message(chat_id, f"✅ {retry_msg}")
                except Exception as ex:
                    await self.send_message(chat_id, f"❌ 重试失败: {str(ex)}", parse_mode=None)
                await self._handle_failed_tasks_command(chat_id, page=return_page, message_id=message_id)

            # 1.5 失败任务删除: fx:task_id:page
            elif data.startswith('fx:'):
                await ack_once("🗑️ 正在删除任务...")
                parts = data.split(':')
                task_id = parts[1]
                return_page = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 1
                try:
                    delete_msg = await self._delete_failed_task_by_id(task_id)
                    await self.send_message(chat_id, f"✅ {delete_msg}")
                except Exception as ex:
                    await self.send_message(chat_id, f"❌ 删除失败: {str(ex)}", parse_mode=None)
                await self._handle_failed_tasks_command(chat_id, page=return_page, message_id=message_id)
            
            # 2.2 直播详情: li:id
            elif data.startswith('li:'):
                await ack_once("🔧 正在打开直播详情")
                parts = data.split(':')
                sub_id = parts[1]
                return_page = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 1
                await self._handle_live_subscription_info(chat_id, sub_id, message_id, return_page=return_page)

            # 2.3 直播自动录制切换: lar:id:action (on/off)
            elif data.startswith('lar:'):
                await ack_once("⏳ 正在更新设置")
                parts = data.split(':')
                _, sub_id, action = parts[:3]
                return_page = int(parts[3]) if len(parts) > 3 and str(parts[3]).isdigit() else 1
                await self._handle_live_toggle_auto_record(chat_id, sub_id, action, message_id, return_page=return_page)
            
            # 2.4 直播删除: ldel:id (确认) / ldel_confirm:id (执行)
            elif data.startswith('ldel:'):
                await ack_once("⚠️ 请确认删除")
                parts = data.split(':')
                sub_id = parts[1]
                return_page = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 1
                await self._handle_delete_live_subscription(chat_id, sub_id, confirmed=False, message_id=message_id, return_page=return_page)
            elif data.startswith('ldel_confirm:'):
                await ack_once("🗑️ 正在删除")
                parts = data.split(':')
                sub_id = parts[1]
                return_page = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 1
                await self._handle_delete_live_subscription(chat_id, sub_id, confirmed=True, message_id=message_id, return_page=return_page)

            # 2.5 直播手动控制: lstart:id / lstop:id
            elif data.startswith('lstart:'):
                await ack_once("▶️ 正在开始录制")
                parts = data.split(':')
                sub_id = parts[1]
                return_page = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 1
                await self._handle_live_manual_control(chat_id, sub_id, 'start', message_id, return_page=return_page)
            elif data.startswith('lstop:'):
                await ack_once("⏹️ 正在停止录制")
                parts = data.split(':')
                sub_id = parts[1]
                return_page = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 1
                await self._handle_live_manual_control(chat_id, sub_id, 'stop', message_id, return_page=return_page)

            # 3. 详情管理: si:id (视频订阅详情)
            elif data.startswith('si:'):
                parts = data.split(':')
                sub_id = parts[1]
                nav_ctx = self._parse_sub_nav_token(parts[2] if len(parts) > 2 else None)
                # 先快速应答回调，避免按钮长时间保持高亮/加载态
                await ack_once("🔧 正在打开订阅管理")
                # 通知入口统一使用“新发临时菜单”，避免覆盖原通知内容后被“返回通知”误删
                target_message_id = None if nav_ctx.get("entry") == "notif" else (message_id if can_edit_text_message else None)
                await self._handle_sub_detail(chat_id, sub_id, target_message_id, nav_ctx=nav_ctx)
            
            # 3. 手动检测更新: sc:id
            elif data.startswith('sc:'):
                parts = data.split(':')
                sub_id = parts[1]
                nav_ctx = self._parse_sub_nav_token(parts[2] if len(parts) > 2 else None)
                await ack_once("⏳ 正在检测更新...")
                from routers.subscribe import router as subscriptions_api
                try:
                    from routers.subscribe.sync import check_subscription_update
                    with self._db_session() as db_session:
                        res = await check_subscription_update(sub_id, db_session)
                        count = res.get('new_videos_count', 0)
                        msg = f"✅ 检测完成" + (f"，发现 {count} 个新视频！" if count > 0 else "，暂无更新")
                        await self.send_message(chat_id, msg)
                    await self._handle_sub_detail(chat_id, sub_id, message_id, nav_ctx=nav_ctx)
                except Exception as ex:
                    await self.send_message(chat_id, f"❌ 检测失败: {str(ex)}")

            # 4. 视频全量同步: ss:id
            elif data.startswith('ss:'):
                parts = data.split(':')
                sub_id = parts[1]
                nav_ctx = self._parse_sub_nav_token(parts[2] if len(parts) > 2 else None)
                
                # 获取博主昵称用于进度提示
                title = "未知博主"
                try:
                    with self._db_session() as db:
                        from sql.models import Subscription
                        sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
                        if sub:
                            title = sub.nickname or sub.user_id
                except Exception:
                    pass
                
                await ack_once("🚀 已开始全量同步视频信息...")
                try:
                    progress_msg_id = await self.send_message(chat_id, f"🔄 正在加载博主 [{title}] 的数据...", return_message_id=True)
                    asyncio.create_task(self._run_sync_videos_task(sub_id, chat_id, progress_msg_id, title))
                except Exception as ex:
                    await self.send_message(chat_id, f"❌ 启动同步失败: {str(ex)}")

            # 6. 视频记录列表: svl:id:page
            elif data.startswith('svl:'):
                await ack_once("📋 正在打开视频列表")
                parts = data.split(':')
                sub_id = parts[1]
                vpage = int(parts[2]) if len(parts) > 2 else 1
                nav_ctx = self._parse_sub_nav_token(parts[3] if len(parts) > 3 else None)
                await self._handle_sub_video_list(chat_id, sub_id, vpage, message_id, nav_ctx=nav_ctx)

            # 7. 视频详情: svd:vid[:video_page][:nav_token]
            elif data.startswith('svd:'):
                await ack_once("📝 正在打开视频详情")
                parts = data.split(':')
                vid = parts[1]
                video_page = 1
                nav_token_idx = 2
                if len(parts) > 2 and str(parts[2]).isdigit():
                    video_page = int(parts[2])
                    nav_token_idx = 3
                nav_ctx = self._parse_sub_nav_token(parts[nav_token_idx] if len(parts) > nav_token_idx else None)
                await self._handle_video_detail(chat_id, vid, message_id, nav_ctx=nav_ctx, video_page=video_page)

            # 8. 视频下载: sdl:vid[:video_page][:nav_token]
            elif data.startswith('sdl:'):
                parts = data.split(':')
                vid = parts[1]
                video_page = 1
                nav_token_idx = 2
                if len(parts) > 2 and str(parts[2]).isdigit():
                    video_page = int(parts[2])
                    nav_token_idx = 3
                nav_ctx = self._parse_sub_nav_token(parts[nav_token_idx] if len(parts) > nav_token_idx else None)
                from routers.subscribe.download import download_video
                from routers.subscribe.models import VideoDownloadRequest
                try:
                    with self._db_session() as db_session:
                        await download_video(vid, VideoDownloadRequest(quality="best"), db_session)
                        await ack_once("📥 已加入下载队列")
                        await self._handle_video_detail(chat_id, vid, message_id, nav_ctx=nav_ctx, video_page=video_page)
                except Exception as ex:
                    await ack_once(f"❌ 下载失败: {str(ex)}", show_alert=True)

            # 8.2 /subs 视频详情里的“发送到Bot”按钮: sdv:vid
            elif data.startswith('sdv:'):
                vid = data.split(':', 1)[1]
                await ack_once("⏳ 正在发送内容...")
                asyncio.create_task(self._handle_send_video_from_subscription_video(chat_id, vid))

            # 8.1 下载完成通知内的“发送视频到Bot”按钮: tsv:notification_id
            elif data.startswith('tsv:'):
                notification_id = data.split(':', 1)[1]
                await ack_once("⏳ 正在尝试发送内容...")
                asyncio.create_task(self._handle_send_video_from_notification(chat_id, notification_id))

            # 8.3 下载失败通知内的“重试下载”按钮: trn:notification_id
            elif data.startswith('trn:'):
                notification_id = data.split(':', 1)[1]
                await ack_once("⏳ 正在准备重试...")
                asyncio.create_task(self._handle_retry_download_from_notification(chat_id, notification_id))

            # 8.4 下载失败通知内的“删除任务”按钮: tdn:notification_id
            elif data.startswith('tdn:'):
                notification_id = data.split(':', 1)[1]
                await ack_once("🗑️ 正在删除任务...")
                asyncio.create_task(self._handle_delete_download_task_from_notification(chat_id, notification_id))

            # 12. 批量下载所有未下载: sda:id[:video_page][:nav_token]
            elif data.startswith('sda:'):
                await ack_once("⏳ 正在准备批量下载...")
                parts = data.split(':')
                sub_id = parts[1]
                video_page = 1
                nav_token_idx = 2
                if len(parts) > 2 and str(parts[2]).isdigit():
                    video_page = int(parts[2])
                    nav_token_idx = 3
                nav_ctx = self._parse_sub_nav_token(parts[nav_token_idx] if len(parts) > nav_token_idx else None)
                from routers.subscribe.download import batch_download
                from routers.subscribe.models import BatchDownloadRequest
                
                # 获取博主昵称
                title = "未知博主"
                sub_quality = "best"
                try:
                    with self._db_session() as db:
                        from sql.models import Subscription
                        sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
                        if sub:
                            title = sub.nickname or sub.user_id
                            sub_quality = sub.quality or "best"
                except Exception:
                    pass
                
                try:
                    # 仅对 Bot 发起的批量下载开启通知降噪上下文
                    self.mark_bot_batch_started(sub_id, chat_id)
                    progress_msg_id = await self.send_message(chat_id, f"📥 正在准备批量下载 **{title}** ...", return_message_id=True)
                    import time
                    last_update_time = time.time()
                    
                    async def bot_batch_progress_callback(completed: int, failed: int, total: int, finished: bool = False, error: Exception = None):
                        if not self.token or not chat_id or not progress_msg_id:
                            return
                        now = time.time()
                        nonlocal last_update_time
                        
                        if finished:
                            if error:
                                text = f"❌ [{title}] 批量下载异常中止:\n{str(error)}"
                            else:
                                text = f"✅ [{title}] 批量下载处理结束！\n总计分发 {total} 个视频，成功完成 {completed} 个，失败 {failed} 个。"
                            asyncio.create_task(self._edit_message(chat_id, progress_msg_id, text))
                            self.mark_bot_batch_finished(sub_id, chat_id)
                        else:
                            if now - last_update_time >= 3.0:
                                text = f"📥 正在批量下载 **{title}** 的视频...\n> 总计: {total} 个任务\n> 已完成: {completed} | 失败: {failed}"
                                inline_keyboard = [[{"text": "❌ 取消批量下载", "callback_data": f"sdc:{sub_id}"}]]
                                asyncio.create_task(self._edit_message(chat_id, progress_msg_id, text, inline_keyboard))
                                last_update_time = now

                    with self._db_session() as db_session:
                        req = BatchDownloadRequest(type="count", quality=sub_quality, batch_size=2)
                        res = await batch_download(sub_id, req, db_session, progress_callback=bot_batch_progress_callback)
                        
                        count = res.get("count", 0)
                        if count == 0:
                            asyncio.create_task(self._edit_message(chat_id, progress_msg_id, f"ℹ️ **{title}** 没有需要下载的视频。"))
                            self.mark_bot_batch_finished(sub_id, chat_id)
                            
                        msg = res.get("message", "任务已创建")
                        await self.send_message(
                            chat_id,
                            f"✅ {msg} (共{count}个)\n🔕 已开启静默下载：单条完成通知不再推送，请关注本条进度和最终汇总。"
                        )
                        
                        # 刷新列表页
                        await self._handle_sub_video_list(chat_id, sub_id, video_page, message_id, nav_ctx=nav_ctx)
                except Exception as ex:
                    safe_err = str(ex).replace("400: ", "")
                    if 'progress_msg_id' in locals():
                        asyncio.create_task(self._edit_message(chat_id, progress_msg_id, f"❌ **{title}** 批量下载失败:\n{safe_err}"))
                    await self.send_message(chat_id, f"❌ {safe_err}")
                    self.mark_bot_batch_finished(sub_id, chat_id)

            # 12.1 重试失败任务: sdr:id[:video_page][:nav_token]
            elif data.startswith('sdr:'):
                await ack_once("⏳ 正在准备重试失败任务...")
                parts = data.split(':')
                sub_id = parts[1]
                video_page = 1
                nav_token_idx = 2
                if len(parts) > 2 and str(parts[2]).isdigit():
                    video_page = int(parts[2])
                    nav_token_idx = 3
                nav_ctx = self._parse_sub_nav_token(parts[nav_token_idx] if len(parts) > nav_token_idx else None)
                from routers.subscribe.download import retry_failed_downloads_batch
                from routers.subscribe.models import RetryFailedDownloadsRequest
                sub_quality = "best"
                try:
                    with self._db_session() as db:
                        from sql.models import Subscription
                        sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
                        if sub:
                            sub_quality = sub.quality or "best"
                    with self._db_session() as db_session:
                        req = RetryFailedDownloadsRequest(quality=sub_quality, batch_size=1)
                        res = await retry_failed_downloads_batch(sub_id, req, db_session)
                        count = res.get("count", 0)
                        msg = res.get("message", "重试任务已创建")
                        await self.send_message(chat_id, f"✅ {msg} (共{count}个)")
                        await self._handle_sub_video_list(chat_id, sub_id, video_page, message_id, nav_ctx=nav_ctx)
                except Exception as ex:
                    safe_err = str(ex).replace("400: ", "")
                    await self.send_message(chat_id, f"❌ {safe_err}")

            # 13. 取消批量下载: sdc:id
            elif data.startswith('sdc:'):
                await ack_once("🛑 正在取消批量下载...")
                sub_id = data.split(':')[1]
                from routers.subscribe.download import cancel_batch_download
                try:
                    with self._db_session() as db_session:
                        res = await cancel_batch_download(sub_id, db_session)
                        msg = res.get("message", "已发起取消")
                        await self.send_message(chat_id, msg)
                        self.mark_bot_batch_finished(sub_id, chat_id)
                except Exception as ex:
                    await self.send_message(chat_id, f"❌ 取消失败: {str(ex)}")

            # 14. 网易云搜索结果下载: nmd:song_id
            elif data.startswith('nmd:'):
                song_id = data.split(':', 1)[1].strip()
                if not song_id:
                    await ack_once("❌ 无效歌曲ID", show_alert=True)
                    return
                try:
                    song_title = None
                    song_artist = None
                    if message_id:
                        state = self._get_music_search_state(chat_id, message_id)
                        for s in (state or {}).get("songs", []):
                            if str(s.get("id", "")).strip() == song_id:
                                song_title = s.get("title")
                                song_artist = s.get("artist")
                                break

                    task_id = await self._enqueue_netease_song_download(song_id, song_title=song_title, song_artist=song_artist)
                    if not task_id:
                        await ack_once("❌ 创建任务失败", show_alert=True)
                        return
                    await ack_once("✅ 已加入下载队列")
                    await self.send_message(
                        chat_id,
                        f"✅ **网易云歌曲已加入下载队列**\n🆔 任务ID: `{task_id[:8]}`\n🎧 音质: `best`"
                    )
                except Exception as ex:
                    logger.error(f"[TG Bot] 网易云歌曲入队失败: {ex}")
                    await ack_once(f"❌ 下载失败: {str(ex)}", show_alert=True)
            # 14.1 网易云搜索结果翻页: nmp:prev / nmp:next
            elif data.startswith('nmp:'):
                action = data.split(':', 1)[1].strip().lower()
                if not message_id:
                    await self._answer_callback_query(query_id, "❌ 分页上下文缺失", show_alert=True)
                    return

                state = self._get_music_search_state(chat_id, message_id)
                if not state:
                    await self._answer_callback_query(query_id, "⚠️ 搜索会话已过期，请重新使用 /music 搜索", show_alert=True)
                    return

                keyword = state.get("keyword", "")
                limit = max(1, int(state.get("limit", 8) or 8))
                current_offset = max(0, int(state.get("offset", 0) or 0))
                total = max(0, int(state.get("total", 0) or 0))

                if action == 'prev':
                    new_offset = max(0, current_offset - limit)
                elif action == 'next':
                    new_offset = min(max(0, total - 1), current_offset + limit)
                else:
                    await self._answer_callback_query(query_id, "❌ 无效分页动作", show_alert=False)
                    return

                try:
                    result = await self._search_netease_songs(keyword, limit=limit, offset=new_offset)
                    songs = result.get("songs") or []
                    total = int(result.get("total") or total)
                    has_more = bool(result.get("has_more"))
                    if not songs:
                        await self._answer_callback_query(query_id, "已到最后一页", show_alert=False)
                        return

                    msg, inline_keyboard = self._build_netease_search_message(
                        keyword=keyword,
                        songs=songs,
                        total=total,
                        offset=new_offset,
                        limit=limit,
                        has_more=has_more
                    )
                    await self._edit_message(chat_id, message_id, msg, inline_keyboard)
                    self._set_music_search_state(chat_id, message_id, keyword, new_offset, limit, total, songs=songs)
                    await self._answer_callback_query(query_id, "✅ 已翻页", show_alert=False)
                except Exception as ex:
                    logger.error(f"[TG Bot] 网易云搜索翻页失败: {ex}")
                    await self._answer_callback_query(query_id, "❌ 翻页失败，请重试", show_alert=False)

            # 9. 更多设置: sst:id
            elif data.startswith('sst:'):
                await ack_once("⚙️ 正在打开设置")
                parts = data.split(':')
                sub_id = parts[1]
                nav_ctx = self._parse_sub_nav_token(parts[2] if len(parts) > 2 else None)
                await self._handle_sub_settings(chat_id, sub_id, message_id, nav_ctx=nav_ctx)

            # 10. 修改设置字段: sf:id:field:value
            elif data.startswith('sf:'):
                parts = data.split(':')
                _, sub_id, field, value = parts[:4]
                nav_ctx = self._parse_sub_nav_token(parts[4] if len(parts) > 4 else None)
                from routers.subscribe.subscription import update_subscription
                from sql.models import SubscriptionUpdate
                try:
                    with self._db_session() as db_session:
                        update_data = {}
                        if field == 'ad': # auto_download
                            # 需要传递字符串 "true" 或 "false" 以符合 SubscriptionUpdate 模型的校验要求
                            update_data['auto_download'] = "true" if value.lower() == 'true' else "false"
                        elif field == 'ui': # update_interval
                            val = int(value)
                            update_data['update_interval'] = val
                            # 网页端逻辑：设置间隔为0即视为进入"暂停/关闭自检"状态
                            update_data['status'] = 'paused' if val <= 0 else 'active'
                        
                        await update_subscription(sub_id, SubscriptionUpdate(**update_data), db_session)
                        await self._answer_callback_query(query_id, "✅ 设置已更新")
                        await self._handle_sub_settings(chat_id, sub_id, message_id, nav_ctx=nav_ctx)
                except Exception as ex:
                    await self._answer_callback_query(query_id, f"❌ 更新失败: {str(ex)}", show_alert=True)

            # 11. 删除订阅: sd:id[:nav_token]
            elif data.startswith('sd:'):
                parts = data.split(':')
                sub_id = parts[1]
                nav_ctx = self._parse_sub_nav_token(parts[2] if len(parts) > 2 else None)
                from routers.subscribe.subscription import delete_subscription
                try:
                    with self._db_session() as db_session:
                        await delete_subscription(sub_id, db_session)
                        await self._answer_callback_query(query_id, "🗑️ 订阅已成功移除", show_alert=False)
                        if nav_ctx.get("entry") == "notif":
                            if message_id:
                                await self._delete_message(chat_id, message_id)
                            await self.send_message(chat_id, "🗑️ 订阅已成功移除")
                        else:
                            await self._handle_subs_command(
                                chat_id,
                                page=nav_ctx.get("page", 1),
                                message_id=message_id,
                                platform=nav_ctx.get("platform", "all")
                            )
                except Exception as ex:
                    await self._answer_callback_query(query_id, f"❌ 删除失败: {str(ex)}", show_alert=True)

            # 5. 返回列表: sb:page:platform
            elif data.startswith('sb:'):
                await ack_once("↩️ 已返回列表")
                _, page, platform = data.split(':')
                await self._handle_subs_command(chat_id, page=int(page), message_id=message_id, platform=platform)
            elif data == 'sbn':
                await ack_once("↩️ 已返回通知")
                try:
                    if message_id:
                        await self._delete_message(chat_id, message_id)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"处理回调查询失败: {e}\n{traceback.format_exc()}")
            if not callback_answered:
                await self._answer_callback_query(query_id, "❌ 操作执行失败")

    async def _handle_sub_detail(self, chat_id: str, sub_id: str, message_id: Optional[int] = None, nav_ctx: Optional[Dict[str, Any]] = None):
        """显示单个订阅的详细信息和管理按钮"""
        try:
            nav_ctx = nav_ctx or {"entry": "list", "page": 1, "platform": "all"}
            nav_token = self._build_sub_nav_token(
                entry=nav_ctx.get("entry", "list"),
                page=nav_ctx.get("page", 1),
                platform=nav_ctx.get("platform", "all")
            )
            with self._db_session() as db:
                sub = db.query(models.Subscription).filter(models.Subscription.id == sub_id).first()
                if not sub:
                    if message_id:
                        await self._edit_message(chat_id, message_id, "❌ 该订阅已不存在")
                    else:
                        await self.send_message(chat_id, "❌ 该订阅已不存在")
                    return

                # 构建详细信息
                status_text = "🟢 正常" if sub.status == "active" else "⚪️ 暂停"
                auto_dl = "✅ 开启" if str(sub.auto_download).lower() == 'true' else "❌ 关闭"
                interval = "不自动检测"
                # 网页端逻辑：如果间隔小于 600 秒(10分钟)通常视为不自动检测，或者状态为暂停
                if sub.status == "active" and sub.update_interval and sub.update_interval >= 360:
                    if sub.update_interval >= 3600:
                        interval = f"{sub.update_interval // 3600} 小时"
                    else:
                        interval = f"{sub.update_interval // 60} 分钟"
                
                def calculate_next_check_time(sub):
                    if sub.status != "active" or not sub.update_interval:
                        return "已停止"
                    last_check = sub.last_check or datetime.now()
                    next_time = last_check + timedelta(seconds=sub.update_interval)
                    now = datetime.now()
                    if next_time < now:
                        return "即将开始"
                    return next_time.strftime("%Y-%m-%d %H:%M")

                next_check = calculate_next_check_time(sub)
                
                safe_name = self.escape_markdown(sub.nickname)
                msg = (
                    f"👤 **博主详情**: {safe_name}\n\n"
                    f"🏷️ 平台: `{sub.platform}`\n"
                    f"📊 视频总数: `{sub.video_count}`\n"
                    f"⏰ 检测频率: `{interval}`\n"
                    f"📥 自动下载: `{auto_dl}`\n"
                    f"📉 当前状态: {status_text}\n"
                    f"⏭️ 下次检测: `{next_check}`\n"
                )

                # 简化按钮布局，更符合网页端逻辑
                back_button = {"text": "⬅️ 返回订阅列表", "callback_data": f"sb:{nav_ctx.get('page', 1)}:{nav_ctx.get('platform', 'all')}"}
                if nav_ctx.get("entry") == "notif":
                    back_button = {"text": "⬅️ 返回通知", "callback_data": "sbn"}
                inline_keyboard = [
                    [
                        {"text": "🕒 更新", "callback_data": f"sc:{sub.id}:{nav_token}"},
                        {"text": "📋 列表", "callback_data": f"svl:{sub.id}:1:{nav_token}"},
                        {"text": "🔄 同步", "callback_data": f"ss:{sub.id}:{nav_token}"},
                        {"text": "⚙️ 设置", "callback_data": f"sst:{sub.id}:{nav_token}"}
                    ],
                    [back_button]
                ]

                # 如果有头像，可以考虑发送带图详情，但为了编辑消息方便，这里使用纯文本编辑
                if message_id:
                    await self._edit_message(chat_id, message_id, msg, inline_keyboard)
                else:
                    await self.send_message(chat_id, msg, reply_markup={"inline_keyboard": inline_keyboard})
        except Exception as e:
            logger.error(f"显示详情失败: {e}")
            if message_id:
                await self._edit_message(chat_id, message_id, "❌ 获取详情失败")
            else:
                await self.send_message(chat_id, "❌ 获取详情失败")

    async def _handle_sub_video_list(self, chat_id: str, sub_id: str, page: int, message_id: int, nav_ctx: Optional[Dict[str, Any]] = None):
        """显示订阅博主的视频列表"""
        page_size = 10
        try:
            nav_ctx = nav_ctx or {"entry": "list", "page": 1, "platform": "all"}
            nav_token = self._build_sub_nav_token(
                entry=nav_ctx.get("entry", "list"),
                page=nav_ctx.get("page", 1),
                platform=nav_ctx.get("platform", "all")
            )
            with self._db_session() as db:
                sub = db.query(models.Subscription).filter(models.Subscription.id == sub_id).first()
                if not sub:
                    await self._edit_message(chat_id, message_id, "❌ 订阅已不存在")
                    return

                # 获取视频
                query = db.query(models.SubscriptionVideo).filter(
                    models.SubscriptionVideo.subscription_id == sub_id
                ).order_by(models.SubscriptionVideo.publish_time.desc())
                
                total_count = query.count()
                total_pages = (total_count + page_size - 1) // page_size
                videos = query.offset((page - 1) * page_size).limit(page_size).all()
                failed_count = db.query(models.SubscriptionVideo).outerjoin(
                    models.Task, models.SubscriptionVideo.download_task_id == models.Task.id
                ).filter(
                    models.SubscriptionVideo.subscription_id == sub_id,
                    models.SubscriptionVideo.downloaded == "false",
                    or_(
                        models.SubscriptionVideo.error_message.isnot(None),
                        models.Task.status == models.TaskStatus.ERROR.value
                    )
                ).count()

                safe_nickname = self.escape_markdown(sub.nickname)
                msg = f"📋 **{safe_nickname}** 的视频列表\n"
                msg += f"第 {page}/{total_pages} 页 (共 {total_count} 条记录)\n"
                msg += "------------------------\n"

                inline_keyboard = []
                for i, v in enumerate(videos):
                    status_icon = "🎥"
                    if v.downloaded == "true": status_icon = "✅"
                    elif v.download_task_id: status_icon = "⏳"
                    
                    title = v.title or "无标题"
                    # 清理特殊字符
                    safe_title_text = self.escape_markdown(title)
                    display_title = f"{status_icon} {title[:20]}"
                    
                    inline_keyboard.append([
                        {"text": display_title, "callback_data": f"svd:{v.id}:{page}:{nav_token}"}
                    ])

                # 分页导航
                nav_btns = []
                if page > 1:
                    nav_btns.append({"text": "⬅️ 上一页", "callback_data": f"svl:{sub_id}:{page-1}:{nav_token}"})
                if page < total_pages:
                    nav_btns.append({"text": "下一页 ➡️", "callback_data": f"svl:{sub_id}:{page+1}:{nav_token}"})
                
                if nav_btns:
                    inline_keyboard.append(nav_btns)

                # 添加批量下载按钮
                inline_keyboard.append([
                    {"text": "📥 一键下载本账号所有未下载视频", "callback_data": f"sda:{sub_id}:{page}:{nav_token}"}
                ])
                if failed_count > 0:
                    inline_keyboard.append([
                        {"text": f"🔁 重试失败任务 ({failed_count})", "callback_data": f"sdr:{sub_id}:{page}:{nav_token}"}
                    ])

                inline_keyboard.append([{"text": "🔙 返回博主详情", "callback_data": self._build_sub_detail_callback(sub_id, nav_ctx)}])

                await self._edit_message(chat_id, message_id, msg, inline_keyboard)
        except Exception as e:
            logger.error(f"显示视频列表失败: {e}")
            await self._edit_message(chat_id, message_id, "❌ 获取列表失败")

    async def _handle_video_detail(
        self,
        chat_id: str,
        vid: str,
        message_id: int,
        nav_ctx: Optional[Dict[str, Any]] = None,
        video_page: int = 1
    ):
        """显示单个视频记录的详情"""
        try:
            nav_ctx = nav_ctx or {"entry": "list", "page": 1, "platform": "all"}
            nav_token = self._build_sub_nav_token(
                entry=nav_ctx.get("entry", "list"),
                page=nav_ctx.get("page", 1),
                platform=nav_ctx.get("platform", "all")
            )
            with self._db_session() as db:
                video = db.query(models.SubscriptionVideo).filter(models.SubscriptionVideo.id == vid).first()
                if not video:
                    await self._edit_message(chat_id, message_id, "❌ 该视频记录已不存在")
                    return

                # 构建状态文本
                status = "未下载"
                if video.downloaded == "true":
                    status = "✅ 已下载完成"
                elif video.download_task_id:
                    # 获取任务实时状态
                    task = db.query(models.Task).filter(models.Task.id == video.download_task_id).first()
                    if task:
                        status = f"⏳ 正在处理 ({task.status})"
                        if task.progress: status += f" {task.progress}%"
                    else:
                        status = "⚠️ 任务异常 (记录丢失)"
                
                time_str = video.publish_time.strftime("%m-%d %H:%M") if video.publish_time else "未知"
                
                msg = (
                    f"📝 **视频详情**\n"
                    f"----------------------\n"
                    f"🎬 标题: `{video.title or '无标题'}`\n"
                    f"📅 发布: `{time_str}`\n"
                    f"📊 状态: **{status}**\n\n"
                    f"🔗 原文: [点击查看]({video.url})"
                )

                inline_keyboard = [
                    [{"text": "📥 立即下载", "callback_data": f"sdl:{vid}:{video_page}:{nav_token}"}] if video.downloaded != "true" else [],
                    [{"text": "📤 发送到Bot", "callback_data": f"sdv:{vid}"}] if video.downloaded == "true" else [],
                    [{"text": "📋 视频列表", "callback_data": f"svl:{video.subscription_id}:{video_page}:{nav_token}"}]
                ]
                # 过滤空的行
                inline_keyboard = [row for row in inline_keyboard if row]

                await self._edit_message(chat_id, message_id, msg, inline_keyboard)
        except Exception as e:
            logger.error(f"显示视频详情失败: {e}")
            await self._edit_message(chat_id, message_id, "❌ 获取详情信息失败")

    async def _handle_sub_settings(self, chat_id: str, sub_id: str, message_id: int, nav_ctx: Optional[Dict[str, Any]] = None):
        """显示订阅设置面板"""
        try:
            nav_ctx = nav_ctx or {"entry": "list", "page": 1, "platform": "all"}
            nav_token = self._build_sub_nav_token(
                entry=nav_ctx.get("entry", "list"),
                page=nav_ctx.get("page", 1),
                platform=nav_ctx.get("platform", "all")
            )
            with self._db_session() as db:
                sub = db.query(models.Subscription).filter(models.Subscription.id == sub_id).first()
                if not sub:
                    return

                auto_dl_bool = str(sub.auto_download).lower() == 'true'
                auto_dl_icon = "✅ 开启" if auto_dl_bool else "❌ 关闭"
                new_auto_dl = "false" if auto_dl_bool else "true"

                # 格式化当前频率文字 (严格对齐网页端逻辑)
                if sub.status != "active" or not sub.update_interval or sub.update_interval == 0:
                    current_freq_desc = "已关闭 (不自动检测)"
                elif int(sub.update_interval) >= 3600:
                    current_freq_desc = f"{int(sub.update_interval) // 3600} 小时"
                else:
                    current_freq_desc = f"{int(sub.update_interval) // 60} 分钟"

                safe_nickname = self.escape_markdown(sub.nickname or "未知订阅")

                msg = (
                    f"⚙️ **订阅设置**: {safe_nickname}\n"
                    f"--------------------------\n"
                    f"修改设置将立即生效。\n\n"
                    f"当前检测频率: `{current_freq_desc}`"
                )

                # 循环频率列表
                intervals = [600, 1800, 3600, 21600, 86400, 0] # 10m, 30m, 1h, 6h, 24h, off
                current_idx = 0
                try: 
                    current_idx = intervals.index(int(sub.update_interval or 0))
                except: pass
                next_interval = intervals[(current_idx + 1) % len(intervals)]
                
                freq_text = "调节频率"
                if next_interval == 0: freq_text = "切换为: 关闭检测"
                elif next_interval < 3600: freq_text = f"切换为: {next_interval // 60} 分钟"
                else: freq_text = f"切换为: {next_interval // 3600} 小时"

                inline_keyboard = [
                    [{"text": f"📥 自动下载: {auto_dl_icon}", "callback_data": f"sf:{sub_id}:ad:{new_auto_dl}:{nav_token}"}],
                    [{"text": f"⏱️ {freq_text}", "callback_data": f"sf:{sub_id}:ui:{next_interval}:{nav_token}"}],
                    [{"text": "🗑️ 删除此订阅", "callback_data": f"sd:{sub_id}:{nav_token}"}],
                    [{"text": "🔙 返回详情页", "callback_data": self._build_sub_detail_callback(sub_id, nav_ctx)}]
                ]

                await self._edit_message(chat_id, message_id, msg, inline_keyboard)
        except Exception as e:
            logger.error(f"显示设置面板失败: {e}")

    async def _edit_message(self, chat_id: str, message_id: int, text: str, inline_keyboard: List[List[Dict]] = None):
        """编辑已发送的消息"""
        url = f"{self.base_url}/bot{self.token}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}

        async with aiohttp.ClientSession() as session:
            for attempt in range(1, TG_SEND_MAX_ATTEMPTS + 1):
                try:
                    async with session.post(url, json=payload, proxy=self.proxy, timeout=10) as resp:
                        if resp.status == 200:
                            return

                        err = await resp.text()

                        # Markdown 解析失败：移除 parse_mode 后重试
                        if resp.status == 400 and "can't parse entities" in err and payload.get("parse_mode"):
                            payload.pop("parse_mode", None)
                            self._log_tg_send_issue(
                                "edit_markdown_parse",
                                f"TG Markdown 编辑失败，自动降级为纯文本重试: {err}",
                                level="warning"
                            )
                            if attempt < TG_SEND_MAX_ATTEMPTS:
                                continue

                        if self._tg_is_retryable_http_status(resp.status) and attempt < TG_SEND_MAX_ATTEMPTS:
                            await asyncio.sleep(self._tg_retry_delay(attempt))
                            continue

                        self._log_tg_send_issue(
                            f"edit_http_{resp.status}",
                            f"编辑 TG 消息失败 ({resp.status}): {err}",
                            level="warning"
                        )
                        return
                except Exception as e:
                    if self._tg_is_retryable_exception(e) and attempt < TG_SEND_MAX_ATTEMPTS:
                        await asyncio.sleep(self._tg_retry_delay(attempt))
                        continue
                    self._log_tg_send_issue(
                        f"edit_exc_{type(e).__name__}",
                        f"编辑 TG 消息异常: {e}",
                        level="warning"
                    )
                    return

    async def _delete_message(self, chat_id: str, message_id: int):
        """删除指定消息（用于通知上下文临时菜单返回）。"""
        if not self.token:
            return
        url = f"{self.base_url}/bot{self.token}/deleteMessage"
        payload = {"chat_id": chat_id, "message_id": message_id}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, proxy=self.proxy, timeout=10) as resp:
                    if resp.status != 200:
                        logger.warning(f"删除 TG 消息失败: {await resp.text()}")
            except Exception as e:
                logger.warning(f"删除 TG 消息异常: {e}")

    async def _answer_callback_query(self, callback_query_id: str, text: str, show_alert: bool = False):
        """响应回调查询（弹出顶端提示或弹窗）"""
        url = f"{self.base_url}/bot{self.token}/answerCallbackQuery"
        # Telegram answerCallbackQuery 的 text 长度有限制（通常建议不超过 200 字符，否则会报错 MESSAGE_TOO_LONG）
        if text and len(text) > 200:
            text = text[:197] + "..."
            
        payload = {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, proxy=self.proxy) as resp:
                    if resp.status != 200:
                        logger.warning(f"响应回调失败: {await resp.text()}")
            except Exception as e:
                logger.error(f"响应回调异常: {e}")

    async def _search_netease_songs(self, keyword: str, limit: int = 8, offset: int = 0) -> Dict[str, Any]:
        """搜索网易云歌曲。"""
        kw = (keyword or "").strip()
        if not kw:
            return {"songs": [], "total": 0, "has_more": False}

        params = {
            "s": kw,
            "type": 1,
            "limit": max(1, min(limit, 20)),
            "offset": max(0, offset),
            "csrf_token": ""
        }
        headers = {
            "Referer": "https://music.163.com",
            "User-Agent": "Mozilla/5.0"
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://music.163.com/api/search/get", params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json() or {}

        result = data.get("result") or {}
        raw_songs = result.get("songs") or []
        total = int(result.get("songCount") or len(raw_songs))

        songs: List[Dict[str, Any]] = []
        for s in raw_songs:
            try:
                song_id = str(s.get("id") or "").strip()
                if not song_id:
                    continue
                title = (s.get("name") or "").strip() or f"歌曲 {song_id}"
                artists = s.get("ar") or s.get("artists") or []
                artist = ""
                if isinstance(artists, list) and artists:
                    first = artists[0]
                    if isinstance(first, dict):
                        artist = (first.get("name") or "").strip()
                    else:
                        artist = str(first).strip()
                songs.append({
                    "id": song_id,
                    "title": title,
                    "artist": artist or "未知歌手",
                })
            except Exception:
                continue

        has_more = (offset + len(songs)) < total
        return {"songs": songs, "total": total, "has_more": has_more}

    @staticmethod
    def _music_state_key(chat_id: str, message_id: int) -> str:
        return f"{chat_id}:{message_id}"

    def _set_music_search_state(
        self,
        chat_id: str,
        message_id: int,
        keyword: str,
        offset: int,
        limit: int,
        total: int,
        songs: Optional[List[Dict[str, Any]]] = None
    ):
        """缓存音乐搜索状态，用于上一页/下一页。"""
        key = self._music_state_key(chat_id, message_id)
        self.music_search_states[key] = {
            "keyword": (keyword or "").strip(),
            "offset": max(0, int(offset or 0)),
            "limit": max(1, int(limit or 8)),
            "total": max(0, int(total or 0)),
            "songs": songs or [],
            "updated_at": datetime.now().timestamp(),
        }

        # 防止状态无限增长，保留最近 200 条。
        if len(self.music_search_states) > 200:
            old_keys = sorted(
                self.music_search_states.keys(),
                key=lambda k: self.music_search_states.get(k, {}).get("updated_at", 0)
            )[:-200]
            for k in old_keys:
                self.music_search_states.pop(k, None)

    def _get_music_search_state(self, chat_id: str, message_id: int) -> Optional[Dict[str, Any]]:
        key = self._music_state_key(chat_id, message_id)
        return self.music_search_states.get(key)

    def _build_netease_search_message(
        self,
        keyword: str,
        songs: List[Dict[str, Any]],
        total: int,
        offset: int,
        limit: int,
        has_more: bool
    ) -> tuple[str, List[List[Dict[str, str]]]]:
        """构造网易云搜索分页消息和按钮。"""
        page = (offset // limit) + 1 if limit > 0 else 1
        msg = (
            f"🎵 **网易云搜索结果**\n"
            f"关键词: `{self.escape_markdown(keyword)}`\n"
            f"共找到约 `{total}` 首，第 `{page}` 页：\n"
        )
        inline_keyboard: List[List[Dict[str, str]]] = []
        for idx, song in enumerate(songs, 1):
            title = self.escape_markdown(song.get("title", "未知标题"))
            artist = self.escape_markdown(song.get("artist", "未知歌手"))
            song_id = song.get("id", "")
            item_no = offset + idx
            msg += f"\n{item_no}. {title} - {artist}"
            raw_btn_text = f"{song.get('title', '未知标题')} - {song.get('artist', '未知歌手')}"
            short_btn_text = raw_btn_text if len(raw_btn_text) <= 22 else (raw_btn_text[:21] + "…")
            inline_keyboard.append([
                {"text": f"{item_no}. {short_btn_text}", "callback_data": f"nmd:{song_id}"}
            ])

        nav_btns: List[Dict[str, str]] = []
        if offset > 0:
            nav_btns.append({"text": "⬅️ 上一页", "callback_data": "nmp:prev"})
        if has_more:
            nav_btns.append({"text": "下一页 ➡️", "callback_data": "nmp:next"})
        if nav_btns:
            inline_keyboard.append(nav_btns)

        return msg, inline_keyboard

    async def _handle_netease_search_command(self, chat_id: str, keyword: str):
        """处理 /music 命令，返回可点选下载的结果。"""
        kw = (keyword or "").strip()
        if not kw:
            await self.send_message(chat_id, "用法：`/music <歌曲名或歌手>`")
            return

        await self.send_message(chat_id, f"🔎 正在搜索网易云：`{self.escape_markdown(kw)}`")
        try:
            result = await self._search_netease_songs(kw, limit=8, offset=0)
        except Exception as e:
            logger.error(f"[TG Bot] 网易云搜索失败: {e}")
            await self.send_message(chat_id, "❌ 网易云搜索失败，请稍后重试。", parse_mode=None)
            return

        songs = result.get("songs") or []
        total = int(result.get("total") or 0)
        has_more = bool(result.get("has_more"))
        limit = 8
        offset = 0
        if not songs:
            await self.send_message(chat_id, f"😕 没有找到与“{self.escape_markdown(kw)}”相关的歌曲。")
            return

        msg, inline_keyboard = self._build_netease_search_message(
            keyword=kw,
            songs=songs,
            total=total,
            offset=offset,
            limit=limit,
            has_more=has_more
        )
        message_id = await self.send_message(chat_id, msg, reply_markup={"inline_keyboard": inline_keyboard}, return_message_id=True)
        if message_id:
            self._set_music_search_state(chat_id, message_id, kw, offset, limit, total, songs=songs)

    async def _enqueue_netease_song_download(
        self,
        song_id: str,
        song_title: Optional[str] = None,
        song_artist: Optional[str] = None
    ) -> Optional[str]:
        """按 song_id 创建网易云下载任务并入队。"""
        sid = str(song_id or "").strip()
        if not sid:
            return None

        from routers.downloader import download_manager
        import uuid

        url = f"https://music.163.com/#/song?id={sid}"
        task_id = str(uuid.uuid4())
        display_title = (song_title or "").strip()
        display_artist = (song_artist or "").strip()
        if display_title and display_artist:
            task_title = f"{display_artist} - {display_title}"
        elif display_title:
            task_title = display_title
        else:
            task_title = f"网易云歌曲 {sid}"

        with self._db_session() as db:
            new_task = models.Task(
                id=task_id,
                url=url,
                original_url=url,
                source='netease',
                title=task_title,
                author=display_artist or None,
                status=models.TaskStatus.PENDING.value,
                format_id='best',
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db.add(new_task)
            db.commit()
            await download_manager.add_download_task(task_id)

        return task_id



    async def _handle_download_request(self, chat_id: str, text: str, force_download: bool = False):
        """处理下载请求"""
        try:
            # 提取URL
            urls = re.findall(r'https?://[^\s]+', text)
            if not urls:
                return
            
            original_input_url = urls[0]  # 这里只处理第一个
            url = original_input_url

            # 小红书短链是通用入口（笔记/主页/直播），先还原再判定类型，避免误分流。
            if 'xhslink.com' in url:
                await self.send_message(chat_id, f"🔍 正在识别链接类型...\n`{url}`")
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            url,
                            allow_redirects=True,
                            timeout=aiohttp.ClientTimeout(total=8)
                        ) as resp:
                            resolved_url = str(resp.url)
                            if resolved_url:
                                logger.debug(f"[TG Bot] 小红书短链接重定向: {url} -> {resolved_url}")
                                url = resolved_url
                except Exception as e:
                    logger.warning(f"[TG Bot] 解析小红书短链接失败: {e}，使用原URL")

            if force_download:
                await self.send_message(chat_id, "⚙️ **强制下载模式**\n已跳过订阅/直播分流，直接加入下载队列。")
            else:
                # 0. 小红书直播短链/分享文案：不要走“视频下载”，直接转为“直播订阅”
                # 典型分享文案会包含“正在直播”，链接可能是 xhslink.com 短链或 xiaohongshu.com/livestream/...
                if (
                    ('xhslink.com' in original_input_url or 'xiaohongshu.com/livestream' in url)
                    and ('正在直播' in text or 'livestream' in url)
                ):
                    await self.send_message(
                        chat_id,
                        "💡 **检测到小红书直播分享链接**\n\n"
                        "将自动按“直播订阅”方式处理（解决短链直播误入下载队列导致失败的问题）。"
                    )
                    await self._handle_add_live_subscription(chat_id, url)
                    return
            
            # 1. 快速预判明显的订阅类型链接
            subscription_hint = self._detect_subscription_link(url)
            
            # 如果是明显的订阅链接，直接提示
            if subscription_hint and not force_download:
                await self.send_message(
                    chat_id,
                    f"💡 **检测到{subscription_hint}链接**\n\n"
                    f"这是一个订阅类型的链接，建议使用订阅功能：\n"
                    f"`/sub {url}`\n\n"
                    f"订阅后可以自动下载该{subscription_hint}中的所有视频。"
                )
                return
            
            # 2. 对于抖音短链接，需要先解析获取真实URL再判断类型
            if 'v.douyin.com' in url and not force_download:
                await self.send_message(chat_id, f"🔍 正在识别链接类型...\n`{url}`")
                
                try:
                    # 使用超时保护，避免检测时间过长
                    from routers.douyin import douyin_api
                    
                    # 先尝试解析为合集
                    try:
                        is_collection = await asyncio.wait_for(
                            self._check_if_douyin_collection(url),
                            timeout=8.0
                        )
                        if is_collection:
                            await self.send_message(
                                chat_id,
                                f"💡 **检测到抖音合集链接**\n\n"
                                f"这是一个合集链接，建议使用订阅功能：\n"
                                f"`/sub {url}`\n\n"
                                f"订阅后可以自动下载该合集中的所有视频。"
                            )
                            return
                    except:
                        pass
                    
                    # 再尝试解析为博主主页
                    try:
                        user_info = await asyncio.wait_for(
                            douyin_api.parse_user_profile(url),
                            timeout=8.0
                        )
                        if user_info and user_info.get("user_id"):
                            nickname = self.escape_markdown(user_info.get('nickname', '未知'))
                            await self.send_message(
                                chat_id,
                                f"💡 **检测到抖音博主主页链接**\n\n"
                                f"这是博主「{nickname}」的主页，建议使用订阅功能：\n"
                                f"`/sub {url}`\n\n"
                                f"订阅后可以自动下载该博主的所有新视频。"
                            )
                            return
                    except:
                        pass
                    
                    # 如果都不是，则当作普通视频处理
                    
                except asyncio.TimeoutError:
                    logger.warning(f"检测抖音链接类型超时: {url}")
                    # 超时则当作普通视频处理，继续下载
                except Exception as e:
                    logger.error(f"检测抖音链接类型失败: {e}")
                    # 检测失败也当作普通视频处理
            
            # 3. 对于B站短链接，需要解析判断是UP主空间还是单个视频
            if 'b23.tv' in url and not force_download:
                await self.send_message(chat_id, f"🔍 正在识别链接类型...\n`{url}`")
                
                try:
                    # 使用超时保护
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                            final_url = str(resp.url)
                            
                            # 判断最终URL的类型
                            if 'space.bilibili.com' in final_url or '/space/' in final_url:
                                # UP主空间
                                await self.send_message(
                                    chat_id,
                                    f"💡 **检测到B站UP主空间链接**\n\n"
                                    f"这是UP主的个人空间，建议使用订阅功能：\n"
                                    f"`/sub {url}`\n\n"
                                    f"订阅后可以自动下载该UP主的所有新视频。"
                                )
                                return
                            elif 'favlist' in final_url or 'fid=' in final_url:
                                # 收藏夹
                                await self.send_message(
                                    chat_id,
                                    f"💡 **检测到B站收藏夹链接**\n\n"
                                    f"这是一个收藏夹，建议使用订阅功能：\n"
                                    f"`/sub {url}`\n\n"
                                    f"订阅后可以自动下载该收藏夹中的所有视频。"
                                )
                                return
                            # 否则当作单个视频处理，继续下载流程
                            
                except Exception as e:
                    logger.error(f"解析B站短链接失败: {e}")
                    # 解析失败则当作普通视频处理
            
            # 4. 普通链接或检测后确认不是订阅类型，继续下载流程
            await self.send_message(chat_id, f"🔍 正在解析链接...\n`{url}`")
            
            # 调用 API 添加任务
            # 这里我们需要模拟 API 的逻辑，或者直接调用内部函数
            # 为了复用逻辑，最好的方式是调用 routers.dyd.download_video 或 routers.ytd.download_video
            # 但那些是 API 处理函数，可能依赖 Request 对象。
            # 更底层的是调用 download_manager.add_task
            
            from routers.downloader import download_manager
            from sql import models
            import uuid
            
            # 简单的源识别
            source = 'others'
            if 'douyin' in url: source = 'douyin'
            elif 'youtube' in url or 'youtu.be' in url: source = 'youtube'
            elif 'bilibili' in url: source = 'bilibili'
            elif 'xhs' in url or 'xiaohongshu' in url: source = 'xiaohongshu'
            elif 'tiktok' in url: source = 'tiktok'
            elif 'music.163.com' in url: source = 'netease'
            elif 'x.com' in url or 'twitter.com' in url: source = 'x'
            
            # 4. 版权/授权检查 (仅针对通用解析 others 和 订阅功能)
            # 如果是 others (通用解析)，需要检查 License
            if source == 'others':
                from routers.license import license_manager
                if not await license_manager.verify():
                    await self.send_message(chat_id, "🔒 **功能限制**\n\n通用链接解析是高级功能，您的授权无效或已过期。\n请检查授权状态或联系管理员。")
                    return
            
            # 对抖音短链接进行重定向检测，获取最终URL
            final_url = url
            if source == 'douyin' and 'v.douyin.com' in url and '/note/' not in url and '/video/' not in url:
                try:
                    import httpx
                    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                        response = await client.head(url)
                        final_url = str(response.url)
                        logger.debug(f"[TG Bot] 短链接重定向: {url} -> {final_url}")
                        
                        # [重要优化] 针对还原后的 URL 再次进行订阅/直播间判定
                        if (not force_download) and any(host in final_url for host in ['live.douyin.com', 'webcast.amemv.com']):
                            await self.send_message(
                                chat_id,
                                f"💡 **检测到抖音直播链接**\n\n"
                                f"还原后链接为直播间，建议使用直播订阅功能：\n"
                                f"`/live {url}`\n\n"
                                f"订阅后系统将自动监控开播并录制。"
                            )
                            return
                            
                        # 再次检测是否为博主主页/合集
                        sub_hint = self._detect_subscription_link(final_url)
                        if sub_hint and not force_download:
                            await self.send_message(
                                chat_id,
                                f"💡 **检测到{sub_hint}链接**\n\n"
                                f"还原后的链接属于订阅类型，建议使用订阅功能：\n"
                                f"`/sub {url}`\n\n"
                                f"订阅后可以自动下载该{sub_hint}中的所有新内容。"
                            )
                            return
                except Exception as e:
                    logger.warning(f"[TG Bot] 获取短链接重定向失败: {e}，使用原URL")
                    final_url = url
            
            # 清洗 URL，防止追踪参数过长导致数据库报错
            final_url = self._clean_url(final_url)
            original_url_clean = self._clean_url(original_input_url)
            
            # 创建任务记录
            with self._db_session() as db:
                task_id = str(uuid.uuid4())
                new_task = models.Task(
                    id=task_id,
                    url=final_url,  # 使用重定向且清洗后的最终URL
                    original_url=original_url_clean,  # 保存清洗后的原始链接
                    source=source,
                    title=final_url, 
                    status=models.TaskStatus.PENDING.value,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                db.add(new_task)
                db.commit()
                
                # 触发下载管理器
                # download_manager.process_task(task_id) 方法不存在
                # 使用 add_download_task 将已创建的任务ID加入队列
                await download_manager.add_download_task(task_id)
                
                # 友好的平台名称显示
                display_source = source
                if source == 'others':
                    display_source = '通用解析'
                
                await self.send_message(chat_id, f"✅ **已加入下载队列**\n🆔 任务ID: `{task_id[:8]}`\n📺 来源: {display_source}\n🚀 稍后将开始下载")
                
        except Exception as e:
            logger.error(f"处理下载请求失败: {e}")
            safe_error = self.escape_markdown(str(e))
            await self.send_message(chat_id, f"❌ 处理失败: {safe_error}")

    async def _handle_subscribe_command(self, chat_id: str, url: str):
        """处理订阅命令 - 复用网页端的 add_subscription 逻辑"""
        
        # 1. 授权检查
        from routers.license import license_manager
        if not await license_manager.verify():
            await self.send_message(chat_id, "🔒 **功能限制**\n\n订阅功能是高级功能，您的授权无效或已过期。\n请检查授权状态或联系管理员。")
            return
            
        await self.send_message(chat_id, "⏳ 正在分析订阅源...")
        
        # 0. 直播链接识别与分流
        is_live_url = False
        if 'live.douyin.com' in url:
            is_live_url = True
        elif 'live.bilibili.com' in url:
            is_live_url = True
        elif 'youtube.com/live/' in url:
            # YouTube /live/ 可能既是视频也是直播，但在 /sub 上下文中，
            # 如果包含 /live/，我们优先尝试作为直播监控添加
            is_live_url = True
            
        if is_live_url:
            await self._handle_add_live_subscription(chat_id, url)
            return
        
        try:
            from sql.models import SubscriptionCreate, Platform
            from routers.subscribe.subscription import add_subscription
            from fastapi import HTTPException
            
            # 判断平台类型
            platform = None
            subscription_type = "user"
            youtube_tab_type = None  # 初始化YouTube标签页类型
            
            # 抖音相关
            if 'douyin.com' in url or 'v.douyin.com' in url:
                # 判断是否为合集
                from routers.subscribe.utils import _is_douyin_collection_url
                if await _is_douyin_collection_url(url):
                    platform = Platform.DOUYIN_COLLECTION.value
                else:
                    platform = Platform.DOUYIN.value
            # YouTube相关
            elif 'youtube.com' in url or 'youtu.be' in url:
                # 判断是否为播放列表
                if 'list=' in url:
                    platform = Platform.YOUTUBE_PLAYLIST.value
                else:
                    platform = Platform.YOUTUBE.value
                    
                    # 检测YouTube标签页类型（只支持shorts和videos）
                    if '/shorts' in url:
                        youtube_tab_type = 'shorts'
                    elif '/videos' in url:
                        youtube_tab_type = 'videos'
                    # 如果没有指定标签页，默认为videos（由add_subscription处理）
            # B站相关
            elif 'bilibili.com' in url or 'b23.tv' in url:
                # 判断是UP主、合集还是收藏夹
                if 'favlist' in url or 'fid=' in url:
                    platform = Platform.BILIBILI.value
                    subscription_type = "favorite"
                elif '/video/BV' in url:
                    platform = Platform.BILIBILI_COLLECTION.value
                else:
                    platform = Platform.BILIBILI.value
            # TikTok
            elif 'tiktok.com' in url or 'vt.tiktok.com' in url:
                platform = Platform.TIKTOK.value
            # 小红书相关
            elif 'xiaohongshu.com' in url or 'xhslink.com' in url:
                # 排除笔记链接（/explore/）和直播链接
                if '/explore/' in url:
                    await self.send_message(chat_id, "❌ 请使用创作者主页链接添加订阅，不要使用笔记链接\n\n示例：`https://www.xiaohongshu.com/user/profile/用户ID`")
                    return
                if '/livestream' in url:
                    # 直播链接已在前面处理，这里不应该到达
                    await self.send_message(chat_id, "💡 这是直播链接，请使用 `/live <链接>` 添加直播订阅")
                    return
                platform = Platform.XIAOHONGSHU.value
            # Instagram
            elif 'instagram.com' in url:
                # 排除单条帖子或 Reels 链接
                if '/p/' in url or '/reel/' in url or '/stories/' in url:
                    await self.send_message(chat_id, "❌ 请使用创作者主页链接添加订阅，不要使用帖子/Reels/快拍链接\n\n示例：`https://www.instagram.com/username/`")
                    return
                platform = Platform.INSTAGRAM.value
            # 网易云歌单
            elif 'music.163.com' in url:
                if 'playlist' not in url and 'id=' not in url:
                    await self.send_message(chat_id, "❌ 请使用网易云歌单链接添加订阅\n\n示例：`https://music.163.com/playlist?id=123456`")
                    return
                platform = Platform.NETEASE.value
                subscription_type = "playlist"
            else:
                await self.send_message(chat_id, "❌ 暂不支持该平台的订阅\n\n支持：抖音、YouTube、B站、TikTok、Instagram、小红书、网易云歌单")
                return
            
            # 构造订阅创建请求
            subscription_data = SubscriptionCreate(
                platform=platform,
                profile_url=url,
                subscription_type=subscription_type,
                auto_download="true",
                quality="best",
                update_interval=3600,
                youtube_tab_type=youtube_tab_type if 'youtube_tab_type' in locals() else None
            )
            
            # 调用网页端的 add_subscription 函数
            try:
                with self._db_session() as db:
                    result = await add_subscription(subscription_data, db)
                    
                    # 发送成功消息
                    platform_names = {
                        Platform.DOUYIN.value: "抖音博主",
                        Platform.DOUYIN_COLLECTION.value: "抖音合集",
                        Platform.YOUTUBE.value: "YouTube频道",
                        Platform.YOUTUBE_PLAYLIST.value: "YouTube播放列表",
                        Platform.BILIBILI.value: "B站UP主" if subscription_type == "user" else "B站收藏夹",
                        Platform.BILIBILI_COLLECTION.value: "B站合集",
                        Platform.TIKTOK.value: "TikTok用户",
                        Platform.XIAOHONGSHU.value: "小红书博主",
                        Platform.INSTAGRAM.value: "Instagram博主",
                        Platform.NETEASE.value: "网易云歌单"
                    }
                    platform_name = platform_names.get(platform, "订阅")
                    
                    # 为YouTube频道添加标签页类型说明
                    if platform == Platform.YOUTUBE.value and youtube_tab_type:
                        tab_names = {
                            'shorts': 'Shorts',
                            'videos': '视频'
                        }
                        tab_name = tab_names.get(youtube_tab_type, youtube_tab_type)
                        platform_name = f"YouTube频道({tab_name})"
                    
                    result_nickname = self.escape_markdown(result.nickname)
                    await self.send_message(
                        chat_id,
                        f"✅ **订阅添加成功**\n\n"
                        f"👤 {platform_name}: {result_nickname}\n"
                        f"🆔 ID: `{result.id[:8]}`\n"
                        f"📊 视频数: {result.video_count or '未知'}\n\n"
                        f"💡 系统已同步最近视频，新视频将自动下载",
                        reply_markup={
                            "inline_keyboard": [[
                                {"text": "🔧 管理此订阅", "callback_data": f"si:{result.id}:l1_all"}
                            ]]
                        }
                    )

            except HTTPException as e:
                # 处理已存在等业务异常
                error_msg = e.detail
                if "已经订阅" in error_msg or "已存在" in error_msg:
                    await self.send_message(chat_id, f"ℹ️ {error_msg}")
                else:
                    await self.send_message(chat_id, f"❌ {error_msg}", parse_mode=None)
            except Exception as ex:
                logger.error(f"创建订阅失败: {ex}")
                import traceback
                logger.error(traceback.format_exc())
                await self.send_message(chat_id, f"❌ 创建订阅失败: {str(ex)}", parse_mode=None)
            
        except Exception as e:
            logger.error(f"订阅失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await self.send_message(chat_id, f"❌ 订阅失败: {str(e)}", parse_mode=None)


    async def send_message(self, chat_id: str, text: str, parse_mode: str = "Markdown", reply_markup: Dict = None, return_message_id: bool = False):
        """发送消息"""
        if not self.token:
            return
            
        url = f"{self.base_url}/bot{self.token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text
        }
        
        # 只在 parse_mode 有值时才添加
        if parse_mode:
            payload["parse_mode"] = parse_mode
            
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with aiohttp.ClientSession() as session:
            for attempt in range(1, TG_SEND_MAX_ATTEMPTS + 1):
                try:
                    async with session.post(url, json=payload, proxy=self.proxy, timeout=10) as resp:
                        if resp.status == 200:
                            if return_message_id:
                                data = await resp.json()
                                return data.get("result", {}).get("message_id")
                            return None

                        err = await resp.text()

                        # Markdown 解析错误降级为纯文本，并进入下一轮重试
                        if resp.status == 400 and "can't parse entities" in err and payload.get("parse_mode"):
                            payload.pop("parse_mode", None)
                            self._log_tg_send_issue(
                                "send_markdown_parse",
                                f"TG Markdown 消息解析失败，自动降级为纯文本发送: {err}",
                                level="warning"
                            )
                            if attempt < TG_SEND_MAX_ATTEMPTS:
                                continue

                        if self._tg_is_retryable_http_status(resp.status) and attempt < TG_SEND_MAX_ATTEMPTS:
                            await asyncio.sleep(self._tg_retry_delay(attempt))
                            continue

                        self._log_tg_send_issue(
                            f"send_http_{resp.status}",
                            f"TG 发送失败 ({resp.status}): {err}",
                            level="error"
                        )
                        return None

                except Exception as e:
                    if self._tg_is_retryable_exception(e) and attempt < TG_SEND_MAX_ATTEMPTS:
                        await asyncio.sleep(self._tg_retry_delay(attempt))
                        continue
                    self._log_tg_send_issue(
                        f"send_exc_{type(e).__name__}",
                        f"TG 发送异常: {e}",
                        level="error"
                    )
                    return None
        return None

    async def send_photo(self, chat_id: str, photo_url_or_file: str, caption: str = "", reply_markup: Dict = None):
        """发送图片（支持 URL 或本地文件路径）"""
        if not self.token:
            return
            
        url = f"{self.base_url}/bot{self.token}/sendPhoto"
        
        # 判断是本地文件路径还是远程 URL
        is_local_file = False
        local_file_path = None
        
        # 检查是否是本地路径（以 /downloads/ 开头或 /app/downloads/ 开头）
        if photo_url_or_file.startswith('/downloads/'):
            # 相对路径，转换为绝对路径
            from urllib.parse import unquote
            local_file_path = f"/app{unquote(photo_url_or_file)}"
            is_local_file = True
        elif photo_url_or_file.startswith('/app/downloads/'):
            # 已经是绝对路径
            local_file_path = photo_url_or_file
            is_local_file = True
        elif not (photo_url_or_file.startswith('http://') or photo_url_or_file.startswith('https://')):
            # 其他本地路径
            local_file_path = photo_url_or_file
            is_local_file = True
        
        async with aiohttp.ClientSession() as session:
            try:
                if is_local_file and local_file_path:
                    # 本地文件：直接上传
                    if not os.path.exists(local_file_path):
                        logger.error(f"TG 发图失败: 文件不存在 {local_file_path}")
                        return
                    
                    # 使用 multipart/form-data 上传文件
                    data = aiohttp.FormData()
                    data.add_field('chat_id', chat_id)
                    data.add_field('caption', caption)
                    # 移除 parse_mode，使用纯文本模式避免特殊字符解析错误
                    if reply_markup:
                        data.add_field('reply_markup', json.dumps(reply_markup, ensure_ascii=False))
                    
                    # 添加文件
                    with open(local_file_path, 'rb') as f:
                        data.add_field('photo', f, filename=os.path.basename(local_file_path))
                        
                        async with session.post(url, data=data, proxy=self.proxy, timeout=30) as resp:
                            if resp.status != 200:
                                logger.error(f"TG 发图失败: {await resp.text()}")
                            else:
                                logger.debug(f"TG 发图成功（本地文件）: {local_file_path}")
                else:
                    # 远程 URL：发送 URL
                    payload = {
                        "chat_id": chat_id,
                        "photo": photo_url_or_file,
                        "caption": caption
                        # 移除 parse_mode，使用纯文本模式
                    }
                    if reply_markup:
                        payload["reply_markup"] = reply_markup
                    
                    async with session.post(url, json=payload, proxy=self.proxy, timeout=20) as resp:
                        if resp.status != 200:
                            logger.error(f"TG 发图失败: {await resp.text()}")
                        else:
                            logger.debug(f"TG 发图成功（URL）: {photo_url_or_file}")
            except Exception as e:
                logger.error(f"TG 发图异常: {e}")

    @staticmethod
    def _normalize_download_local_path(path: str) -> Optional[str]:
        """将通知中的路径统一转换为容器内本地绝对路径。"""
        if not path:
            return None

        from urllib.parse import unquote

        p = unquote(str(path)).strip()
        if not p:
            return None

        if p.startswith('/app/downloads/'):
            return p
        if p.startswith('/downloads/'):
            return f"/app{p}"
        if p.startswith('/app/'):
            return p
        if p.startswith('/'):
            return p
        return f"/app/downloads/{p.lstrip('./')}"

    @staticmethod
    def _pick_video_from_directory(folder: str) -> Optional[str]:
        """从目录中选一个最可能的视频文件（优先最大文件）。"""
        if not folder or not os.path.isdir(folder):
            return None

        video_exts = ('.mp4', '.mkv', '.webm', '.mov', '.m4v', '.flv', '.ts')
        candidates: List[str] = []
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name.lower().endswith(video_exts):
                candidates.append(path)

        if not candidates:
            return None
        candidates.sort(key=lambda p: os.path.getsize(p), reverse=True)
        return candidates[0]

    @staticmethod
    def _pick_media_from_directory(folder: str) -> Optional[str]:
        """从目录中选一个最可能的媒体文件（优先音视频中体积最大的文件）。"""
        if not folder or not os.path.isdir(folder):
            return None

        media_exts = (
            '.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg', '.opus',
            '.mp4', '.mkv', '.webm', '.mov', '.m4v', '.flv', '.ts'
        )
        candidates: List[str] = []
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name.lower().endswith(media_exts):
                candidates.append(path)

        if not candidates:
            return None
        candidates.sort(key=lambda p: os.path.getsize(p), reverse=True)
        return candidates[0]

    @staticmethod
    def _extract_title_from_notification(content: str) -> Optional[str]:
        if not content:
            return None
        m = re.search(r'(?:视频|内容|图集|歌曲|音频)《(.+?)》', content)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _is_probable_url(value: str) -> bool:
        if not value:
            return False
        return str(value).startswith("http://") or str(value).startswith("https://")

    @staticmethod
    def _infer_media_type(path_or_url: str) -> str:
        lower = (path_or_url or "").lower()
        if any(lower.endswith(ext) for ext in (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".flv", ".ts")):
            return "video"
        return "photo"

    @staticmethod
    def _is_video_file(path_or_url: str) -> bool:
        lower = (path_or_url or "").lower()
        return any(lower.endswith(ext) for ext in (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".flv", ".ts"))

    @staticmethod
    def _is_audio_file(path_or_url: str) -> bool:
        lower = (path_or_url or "").lower()
        return any(lower.endswith(ext) for ext in (".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"))

    @staticmethod
    def _is_tg_payload_too_large(err_text: str) -> bool:
        """判断 Telegram 返回是否为文件/请求体过大。"""
        text = (err_text or "").lower()
        return (
            "request entity too large" in text
            or "\"error_code\":413" in text
            or "'error_code':413" in text
            or ("413" in text and "too large" in text)
        )

    @staticmethod
    def _build_tg_oversize_reason(path: Optional[str], raw_reason: str = "") -> str:
        """统一封装超限原因，便于上层识别并降级处理。"""
        size_text = ""
        try:
            if path and os.path.exists(path) and os.path.isfile(path):
                size_mb = os.path.getsize(path) / 1024 / 1024
                size_text = f"（约 {size_mb:.1f}MB）"
        except Exception:
            pass
        detail = f" {raw_reason}" if raw_reason else ""
        return f"[TG_413] 文件过大{size_text}，Telegram 无法直接回传。{detail}".strip()

    @staticmethod
    def _is_tg_oversize_reason(reason: str) -> bool:
        return str(reason or "").startswith("[TG_413]")

    def _build_tg_oversize_fallback_message(
        self,
        title: str,
        source_url: Optional[str],
        local_path: Optional[str],
        reason: str
    ) -> str:
        lines = [
            "⚠️ 文件太大，Telegram 无法直接发送附件。",
            f"标题：{title or '下载内容'}",
        ]
        if source_url:
            lines.append(f"源链接：{source_url}")
        if local_path:
            lines.append(f"本地路径：{local_path}")
        if reason:
            lines.append(f"原因：{reason}")
        return "\n".join(lines)

    def _collect_media_files_from_dir(self, folder: str) -> List[str]:
        if not folder or not os.path.isdir(folder):
            return []
        media_exts = (
            ".jpg", ".jpeg", ".png", ".webp", ".bmp",
            ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".flv", ".ts"
        )
        items: List[str] = []
        try:
            for name in sorted(os.listdir(folder)):
                path = os.path.join(folder, name)
                if os.path.isfile(path) and name.lower().endswith(media_exts):
                    items.append(path)
        except Exception:
            return []
        return items

    def _resolve_notification_video_path(self, notification: "models.Notification", db: Session) -> Optional[str]:
        """根据通知记录尽可能解析出本地媒体文件路径。"""
        extra = {}
        if notification and notification.extra_data:
            try:
                extra = json.loads(notification.extra_data) if isinstance(notification.extra_data, str) else notification.extra_data
            except Exception:
                extra = {}

        # 1) 优先使用 extra_data 显式路径字段
        for key in ('video_path', 'file_path', 'path', 'local_path', 'download_path'):
            p = self._normalize_download_local_path(extra.get(key)) if isinstance(extra, dict) else None
            if p and os.path.exists(p) and os.path.isfile(p):
                return p

        # 2) 从封面路径推导同目录视频
        for key in ('cover', 'cover_url', 'poster'):
            p = self._normalize_download_local_path(extra.get(key)) if isinstance(extra, dict) else None
            if p:
                # 2.1 优先尝试“封面同名媒体”匹配（网易云常见：xxx.jpg + xxx.mp3）
                base, _ = os.path.splitext(p)
                for ext in ('.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg', '.opus', '.mp4', '.mkv', '.webm', '.mov', '.m4v', '.flv', '.ts'):
                    candidate = f"{base}{ext}"
                    if os.path.exists(candidate) and os.path.isfile(candidate):
                        return candidate

                # 2.2 兼容旧逻辑：先找视频
                guessed = self._pick_video_from_directory(os.path.dirname(p))
                if guessed:
                    return guessed
                # 2.3 若无视频则找任意音视频
                guessed_media = self._pick_media_from_directory(os.path.dirname(p))
                if guessed_media:
                    return guessed_media

        # 3) 回退：按通知内容中的标题匹配最近完成任务
        title = self._extract_title_from_notification(notification.content or "")
        task = None
        if title:
            task = db.query(models.Task).filter(
                models.Task.status == "completed",
                models.Task.title.isnot(None),
                models.Task.title.ilike(f"%{title}%")
            ).order_by(desc(models.Task.updated_at)).first()

        if not task:
            task = db.query(models.Task).filter(
                models.Task.status == "completed"
            ).order_by(desc(models.Task.updated_at)).first()

        # 网易云通知兜底：优先回退到最近完成的网易云任务，避免标题不一致时无法定位文件。
        if (not task) and notification:
            content = f"{getattr(notification, 'title', '')} {getattr(notification, 'content', '')}"
            if "网易云" in content:
                task = db.query(models.Task).filter(
                    models.Task.status == "completed",
                    models.Task.source == "netease",
                    models.Task.filename.isnot(None)
                ).order_by(desc(models.Task.updated_at)).first()

        if task and task.filename:
            p = self._normalize_download_local_path(task.filename)
            if p and os.path.exists(p) and os.path.isfile(p):
                return p

        return None

    def _resolve_notification_gallery_media(self, notification: "models.Notification", db: Session) -> List[str]:
        """根据通知记录尽可能解析出图集媒体列表（图片/视频）。"""
        extra: Dict[str, Any] = {}
        if notification and notification.extra_data:
            try:
                extra = json.loads(notification.extra_data) if isinstance(notification.extra_data, str) else notification.extra_data
            except Exception:
                extra = {}

        candidates: List[str] = []
        seen = set()

        def _add_candidate(v: str):
            if not v:
                return
            s = str(v).strip()
            if not s:
                return
            if self._is_probable_url(s):
                if s not in seen:
                    seen.add(s)
                    candidates.append(s)
                return
            p = self._normalize_download_local_path(s)
            if p and os.path.exists(p):
                if os.path.isdir(p):
                    for f in self._collect_media_files_from_dir(p):
                        if f not in seen:
                            seen.add(f)
                            candidates.append(f)
                elif os.path.isfile(p):
                    if p not in seen:
                        seen.add(p)
                        candidates.append(p)

        if isinstance(extra, dict):
            list_keys = ("image_urls", "images", "image_list", "photos", "gallery", "gallery_urls", "media_urls", "media_items")
            for key in list_keys:
                val = extra.get(key)
                if not isinstance(val, list):
                    continue
                for item in val:
                    if isinstance(item, str):
                        _add_candidate(item)
                    elif isinstance(item, dict):
                        for k in ("url", "src", "path", "file", "local_path", "origin_url", "download_url"):
                            if item.get(k):
                                _add_candidate(item.get(k))
                                break

            path_keys = ("gallery_path", "folder", "directory", "download_path", "file_path", "path", "local_path")
            for key in path_keys:
                if extra.get(key):
                    _add_candidate(extra.get(key))

        if len(candidates) >= 2:
            return candidates

        # 回退：从最近完成任务中推断（图集任务常为目录）
        title = self._extract_title_from_notification(notification.content or "")
        task = None
        if title:
            task = db.query(models.Task).filter(
                models.Task.status == "completed",
                models.Task.title.isnot(None),
                models.Task.title.ilike(f"%{title}%")
            ).order_by(desc(models.Task.updated_at)).first()

        if not task:
            task = db.query(models.Task).filter(
                models.Task.status == "completed"
            ).order_by(desc(models.Task.updated_at)).first()

        if task and task.filename:
            p = self._normalize_download_local_path(task.filename)
            if p and os.path.exists(p):
                if os.path.isdir(p):
                    for f in self._collect_media_files_from_dir(p):
                        if f not in seen:
                            seen.add(f)
                            candidates.append(f)
                elif os.path.isfile(p):
                    if p not in seen:
                        seen.add(p)
                        candidates.append(p)

        return candidates

    def _resolve_subscription_video_gallery_media(
        self,
        video: "models.SubscriptionVideo",
        task: Optional["models.Task"] = None
    ) -> List[str]:
        """根据订阅视频记录解析图集媒体列表。"""
        candidates: List[str] = []
        seen = set()

        def _add_candidate(v: str):
            if not v:
                return
            s = str(v).strip()
            if not s:
                return
            if self._is_probable_url(s):
                if s not in seen:
                    seen.add(s)
                    candidates.append(s)
                return
            p = self._normalize_download_local_path(s)
            if p and os.path.exists(p):
                if os.path.isdir(p):
                    for f in self._collect_media_files_from_dir(p):
                        if f not in seen:
                            seen.add(f)
                            candidates.append(f)
                elif os.path.isfile(p):
                    if p not in seen:
                        seen.add(p)
                        candidates.append(p)

        extra = {}
        if getattr(video, "extra_data", None):
            try:
                extra = json.loads(video.extra_data) if isinstance(video.extra_data, str) else video.extra_data
            except Exception:
                extra = {}
        if isinstance(extra, dict):
            for key in ("image_urls", "images", "image_list", "photos", "gallery", "gallery_urls", "media_urls", "media_items"):
                val = extra.get(key)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, str):
                            _add_candidate(item)
                        elif isinstance(item, dict):
                            for k in ("url", "src", "path", "file", "local_path", "origin_url", "download_url"):
                                if item.get(k):
                                    _add_candidate(item.get(k))
                                    break
            for key in ("gallery_path", "folder", "directory", "download_path", "file_path", "path", "local_path"):
                if extra.get(key):
                    _add_candidate(extra.get(key))

        if task and getattr(task, "filename", None):
            _add_candidate(task.filename)

        return candidates

    async def send_media_group(self, chat_id: str, media_items: List[str], caption: str = "") -> tuple[bool, str]:
        """发送图集（真正的 Telegram 相册，sendMediaGroup）。"""
        if not self.token:
            return False, "Bot 未启用"
        if not media_items:
            return False, "没有可发送的媒体"

        normalized: List[str] = []
        for item in media_items:
            if self._is_probable_url(item):
                normalized.append(str(item))
            else:
                p = self._normalize_download_local_path(item)
                if p and os.path.exists(p) and os.path.isfile(p):
                    normalized.append(p)

        if len(normalized) < 2:
            return False, "可发送媒体不足2项，未按图集发送"

        url = f"{self.base_url}/bot{self.token}/sendMediaGroup"
        chunks = [normalized[i:i + 10] for i in range(0, len(normalized), 10)]
        sent = 0

        async with aiohttp.ClientSession() as session:
            for chunk_idx, chunk in enumerate(chunks):
                data = aiohttp.FormData()
                data.add_field("chat_id", chat_id)
                media_payload = []
                opened_files = []
                try:
                    for idx, item in enumerate(chunk):
                        media_type = self._infer_media_type(item)
                        # 本地文件要用 attach://
                        if not self._is_probable_url(item):
                            field_name = f"file{chunk_idx}_{idx}"
                            f = open(item, "rb")
                            opened_files.append(f)
                            data.add_field(field_name, f, filename=os.path.basename(item))
                            media_entry = {
                                "type": media_type,
                                "media": f"attach://{field_name}",
                            }
                        else:
                            media_entry = {
                                "type": media_type,
                                "media": item,
                            }

                        # caption 仅放在第一组第一项
                        if caption and chunk_idx == 0 and idx == 0:
                            media_entry["caption"] = caption[:1024]

                        media_payload.append(media_entry)

                    data.add_field("media", json.dumps(media_payload, ensure_ascii=False))
                    async with session.post(url, data=data, proxy=self.proxy, timeout=180) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            if resp.status == 413 or self._is_tg_payload_too_large(err):
                                return False, self._build_tg_oversize_reason(None, err)
                            logger.warning(f"TG 发图集失败: {err}")
                            return False, err
                        sent += len(chunk)
                except Exception as e:
                    logger.error(f"TG 发图集异常: {e}")
                    return False, str(e)
                finally:
                    for f in opened_files:
                        try:
                            f.close()
                        except Exception:
                            pass

        return True, f"已发送 {sent} 项媒体"

    async def send_video(self, chat_id: str, video_path: str, caption: str = "") -> tuple[bool, str]:
        """发送本地视频文件到 Telegram。"""
        if not self.token:
            return False, "Bot 未启用"

        path = self._normalize_download_local_path(video_path)
        if not path or not os.path.exists(path):
            return False, "视频文件不存在"
        if not os.path.isfile(path):
            return False, "目标不是文件"

        max_mb = int(os.getenv("TG_SEND_VIDEO_MAX_MB", "100") or "100")
        size_mb = os.path.getsize(path) / 1024 / 1024
        if max_mb > 0 and size_mb > max_mb:
            return False, self._build_tg_oversize_reason(path, f"超过配置上限 {max_mb}MB")

        url = f"{self.base_url}/bot{self.token}/sendVideo"
        async with aiohttp.ClientSession() as session:
            try:
                data = aiohttp.FormData()
                data.add_field('chat_id', chat_id)
                if caption:
                    data.add_field('caption', caption[:1024])
                with open(path, 'rb') as f:
                    data.add_field('video', f, filename=os.path.basename(path))
                    async with session.post(url, data=data, proxy=self.proxy, timeout=180) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            if resp.status == 413 or self._is_tg_payload_too_large(err):
                                return False, self._build_tg_oversize_reason(path, err)
                            logger.warning(f"TG 发视频失败: {err}")
                            return False, err
                        return True, ""
            except Exception as e:
                logger.error(f"TG 发视频异常: {e}")
                return False, str(e)

    async def send_audio(self, chat_id: str, audio_path: str, caption: str = "") -> tuple[bool, str]:
        """发送本地音频文件到 Telegram。"""
        if not self.token:
            return False, "Bot 未启用"

        path = self._normalize_download_local_path(audio_path)
        if not path or not os.path.exists(path):
            return False, "音频文件不存在"
        if not os.path.isfile(path):
            return False, "目标不是文件"

        max_mb = int(os.getenv("TG_SEND_AUDIO_MAX_MB", "100") or "100")
        size_mb = os.path.getsize(path) / 1024 / 1024
        if max_mb > 0 and size_mb > max_mb:
            return False, self._build_tg_oversize_reason(path, f"超过配置上限 {max_mb}MB")

        url = f"{self.base_url}/bot{self.token}/sendAudio"
        async with aiohttp.ClientSession() as session:
            try:
                data = aiohttp.FormData()
                data.add_field('chat_id', chat_id)
                if caption:
                    data.add_field('caption', caption[:1024])
                with open(path, 'rb') as f:
                    data.add_field('audio', f, filename=os.path.basename(path))
                    async with session.post(url, data=data, proxy=self.proxy, timeout=180) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            if resp.status == 413 or self._is_tg_payload_too_large(err):
                                return False, self._build_tg_oversize_reason(path, err)
                            logger.warning(f"TG 发音频失败: {err}")
                            return False, err
                        return True, ""
            except Exception as e:
                logger.error(f"TG 发音频异常: {e}")
                return False, str(e)

    async def send_document(self, chat_id: str, file_path: str, caption: str = "") -> tuple[bool, str]:
        """发送本地文件到 Telegram（兜底）。"""
        if not self.token:
            return False, "Bot 未启用"

        path = self._normalize_download_local_path(file_path)
        if not path or not os.path.exists(path):
            return False, "文件不存在"
        if not os.path.isfile(path):
            return False, "目标不是文件"

        url = f"{self.base_url}/bot{self.token}/sendDocument"
        async with aiohttp.ClientSession() as session:
            try:
                data = aiohttp.FormData()
                data.add_field('chat_id', chat_id)
                if caption:
                    data.add_field('caption', caption[:1024])
                with open(path, 'rb') as f:
                    data.add_field('document', f, filename=os.path.basename(path))
                    async with session.post(url, data=data, proxy=self.proxy, timeout=180) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            if resp.status == 413 or self._is_tg_payload_too_large(err):
                                return False, self._build_tg_oversize_reason(path, err)
                            logger.warning(f"TG 发文件失败: {err}")
                            return False, err
                        return True, ""
            except Exception as e:
                logger.error(f"TG 发文件异常: {e}")
                return False, str(e)

    async def _handle_send_video_from_notification(self, chat_id: str, notification_id: str):
        """根据下载完成通知发送对应本地媒体（图集/视频/音频/文件）。"""
        try:
            with self._db_session() as db:
                notification = db.query(models.Notification).filter(
                    models.Notification.id == notification_id
                ).first()
                if not notification:
                    await self.send_message(chat_id, "❌ 通知记录不存在或已过期", parse_mode=None)
                    return

                safe_title = self._extract_title_from_notification(notification.content or "") or "下载完成内容"
                gallery_items = self._resolve_notification_gallery_media(notification, db)
                if len(gallery_items) >= 2:
                    ok, reason = await self.send_media_group(chat_id, gallery_items, caption=f"🖼️ {safe_title}")
                    if ok:
                        return
                    logger.warning(f"通知图集发送失败，回退视频发送: {reason}")

                local_media_path = self._resolve_notification_video_path(notification, db)
                if not local_media_path:
                    await self.send_message(chat_id, "❌ 未找到可发送的本地媒体文件", parse_mode=None)
                    return

                safe_title = self._extract_title_from_notification(notification.content or "") or "下载完成内容"
                source_url = None
                extra = {}
                if notification.extra_data:
                    try:
                        extra = json.loads(notification.extra_data) if isinstance(notification.extra_data, str) else notification.extra_data
                    except Exception:
                        extra = {}
                if isinstance(extra, dict):
                    for k in ("url", "source_url", "original_url", "webpage_url"):
                        if extra.get(k):
                            source_url = str(extra.get(k))
                            break

            if self._is_video_file(local_media_path):
                ok, reason = await self.send_video(chat_id, local_media_path, caption=f"🎬 {safe_title}")
            elif self._is_audio_file(local_media_path):
                ok, reason = await self.send_audio(chat_id, local_media_path, caption=f"🎵 {safe_title}")
            else:
                ok, reason = await self.send_document(chat_id, local_media_path, caption=f"📎 {safe_title}")
            if not ok:
                if self._is_tg_oversize_reason(reason):
                    msg = self._build_tg_oversize_fallback_message(
                        title=safe_title,
                        source_url=source_url,
                        local_path=local_media_path,
                        reason=reason
                    )
                    await self.send_message(chat_id, msg, parse_mode=None)
                else:
                    await self.send_message(chat_id, f"❌ 发送媒体失败：{reason}", parse_mode=None)
        except Exception as e:
            logger.error(f"处理通知视频发送失败 notification_id={notification_id}: {e}")
            await self.send_message(chat_id, f"❌ 发送媒体失败：{str(e)}", parse_mode=None)

    async def _handle_retry_download_from_notification(self, chat_id: str, notification_id: str):
        """根据下载失败通知重试下载。"""
        try:
            with self._db_session() as db:
                notification = db.query(models.Notification).filter(
                    models.Notification.id == notification_id
                ).first()
                if not notification:
                    await self.send_message(chat_id, "❌ 通知记录不存在或已过期", parse_mode=None)
                    return

                extra = {}
                if notification.extra_data:
                    try:
                        extra = json.loads(notification.extra_data) if isinstance(notification.extra_data, str) else notification.extra_data
                    except Exception:
                        extra = {}
                if not isinstance(extra, dict):
                    extra = {}

                task_id = None
                for key in ("task_id", "download_task_id"):
                    if extra.get(key):
                        task_id = str(extra.get(key)).strip()
                        break

                retry_url = None
                for key in ("url", "video_url", "source_url", "original_url", "webpage_url", "profile_url"):
                    if extra.get(key):
                        retry_url = str(extra.get(key)).strip()
                        break

                subscription_id = None
                for key in ("subscription_id", "sub_id"):
                    if extra.get(key):
                        subscription_id = str(extra.get(key)).strip()
                        break

                if not task_id:
                    m = re.search(r"任务[:：]\s*([0-9a-fA-F\-]{8,64})", notification.content or "")
                    if m:
                        task_id = m.group(1)

                subscription_video = None
                if task_id:
                    task = db.query(models.Task).filter(models.Task.id == task_id).first()
                    if task:
                        if not retry_url and getattr(task, "url", None):
                            retry_url = str(task.url).strip()
                        if not subscription_id and getattr(task, "subscription_id", None):
                            subscription_id = str(task.subscription_id).strip()
                    subscription_video = db.query(models.SubscriptionVideo).filter(
                        models.SubscriptionVideo.download_task_id == task_id
                    ).first()
                    if subscription_video and not subscription_id:
                        subscription_id = str(subscription_video.subscription_id or "").strip() or None
                    if subscription_video and not retry_url and subscription_video.url:
                        retry_url = str(subscription_video.url).strip()

            if task_id:
                from routers.file_manager import retry_task_internal

                def _enqueue_retry_task(func, *args):
                    result = func(*args)
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)

                with self._db_session() as db_session:
                    retry_res = retry_task_internal(task_id, db_session, _enqueue_retry_task)
                await self.send_message(chat_id, f"✅ {retry_res.get('message', '任务已开始重试')}")
                return

            if not retry_url:
                await self.send_message(chat_id, "❌ 未找到可重试的原始链接", parse_mode=None)
                return

            await self._handle_download_request(chat_id, retry_url, force_download=True)
        except Exception as e:
            logger.error(f"处理通知重试失败 notification_id={notification_id}: {e}")
            await self.send_message(chat_id, f"❌ 重试失败：{str(e)}", parse_mode=None)

    async def _handle_delete_download_task_from_notification(self, chat_id: str, notification_id: str):
        """根据下载失败通知删除对应任务并清理文件残留。"""
        try:
            task_id = None
            with self._db_session() as db:
                notification = db.query(models.Notification).filter(
                    models.Notification.id == notification_id
                ).first()
                if not notification:
                    await self.send_message(chat_id, "❌ 通知记录不存在或已过期", parse_mode=None)
                    return

                extra = {}
                if notification.extra_data:
                    try:
                        extra = json.loads(notification.extra_data) if isinstance(notification.extra_data, str) else notification.extra_data
                    except Exception:
                        extra = {}
                if not isinstance(extra, dict):
                    extra = {}

                for key in ("task_id", "download_task_id"):
                    if extra.get(key):
                        task_id = str(extra.get(key)).strip()
                        break

                if not task_id:
                    m = re.search(r"任务[:：]\s*([0-9a-fA-F\-]{8,64})", notification.content or "")
                    if m:
                        task_id = m.group(1)

                if not task_id:
                    # 尝试根据通知标题内容模糊匹配最近失败任务（兜底）
                    title_hint = (notification.title or "").strip()
                    if title_hint:
                        fallback_task = db.query(models.Task).filter(
                            models.Task.status == models.TaskStatus.ERROR.value,
                            models.Task.title.like(f"%{title_hint[:24]}%")
                        ).order_by(desc(models.Task.updated_at), desc(models.Task.created_at)).first()
                        if fallback_task:
                            task_id = fallback_task.id

            if not task_id:
                await self.send_message(chat_id, "❌ 未找到可删除的任务ID", parse_mode=None)
                return

            delete_msg = await self._delete_failed_task_by_id(task_id)
            await self.send_message(chat_id, f"✅ {delete_msg}")
        except Exception as e:
            logger.error(f"处理通知删除任务失败 notification_id={notification_id}: {e}")
            await self.send_message(chat_id, f"❌ 删除失败：{str(e)}", parse_mode=None)

    async def _handle_send_video_from_subscription_video(self, chat_id: str, vid: str):
        """根据订阅视频记录发送本地内容（图集优先，回退视频）。"""
        try:
            with self._db_session() as db:
                video = db.query(models.SubscriptionVideo).filter(models.SubscriptionVideo.id == vid).first()
                if not video:
                    await self.send_message(chat_id, "❌ 视频记录不存在", parse_mode=None)
                    return

                if str(video.downloaded).lower() != "true":
                    await self.send_message(chat_id, "❌ 该视频尚未下载完成", parse_mode=None)
                    return

                task = None
                local_video_path = None
                if video.download_task_id:
                    task = db.query(models.Task).filter(models.Task.id == video.download_task_id).first()
                    if task and task.filename:
                        candidate = self._normalize_download_local_path(task.filename)
                        if candidate and os.path.exists(candidate) and os.path.isfile(candidate):
                            local_video_path = candidate

                safe_title = (video.title or "下载完成内容").strip()[:80]
                gallery_items = self._resolve_subscription_video_gallery_media(video, task=task)
                if len(gallery_items) >= 2:
                    ok, reason = await self.send_media_group(chat_id, gallery_items, caption=f"🖼️ {safe_title}")
                    if ok:
                        return
                    logger.warning(f"订阅内容图集发送失败，回退视频发送: {reason}")

                if not local_video_path and video.title:
                    task = db.query(models.Task).filter(
                        models.Task.status == "completed",
                        models.Task.title.isnot(None),
                        models.Task.title.ilike(f"%{video.title}%")
                    ).order_by(desc(models.Task.updated_at)).first()
                    if task and task.filename:
                        candidate = self._normalize_download_local_path(task.filename)
                        if candidate and os.path.exists(candidate) and os.path.isfile(candidate):
                            local_video_path = candidate

                if not local_video_path:
                    await self.send_message(chat_id, "❌ 未找到可发送的本地媒体文件", parse_mode=None)
                    return

                safe_title = (video.title or "下载完成视频").strip()[:80]
                source_url = video.url

            if self._is_video_file(local_video_path):
                ok, reason = await self.send_video(chat_id, local_video_path, caption=f"🎬 {safe_title}")
            elif self._is_audio_file(local_video_path):
                ok, reason = await self.send_audio(chat_id, local_video_path, caption=f"🎵 {safe_title}")
            else:
                ok, reason = await self.send_document(chat_id, local_video_path, caption=f"📎 {safe_title}")
            if not ok:
                if self._is_tg_oversize_reason(reason):
                    msg = self._build_tg_oversize_fallback_message(
                        title=safe_title,
                        source_url=source_url,
                        local_path=local_video_path,
                        reason=reason
                    )
                    await self.send_message(chat_id, msg, parse_mode=None)
                else:
                    await self.send_message(chat_id, f"❌ 发送视频失败：{reason}", parse_mode=None)
        except Exception as e:
            logger.error(f"处理订阅视频发送失败 vid={vid}: {e}")
            await self.send_message(chat_id, f"❌ 发送视频失败：{str(e)}", parse_mode=None)

    async def send_sync_complete_notification(self, subscription_nickname: str, total_videos: int, new_videos: int, deleted_videos: int):
        """发送同步完成通知给所有白名单用户"""
        if not self.token or not self.chat_id_whitelist:
            return
        
        try:
            # 构建通知消息
            nickname = self.escape_markdown(subscription_nickname)
            msg = f"🎉 **同步完成**\n\n"
            msg += f"📺 博主: {nickname}\n"
            msg += f"📊 总视频数: {total_videos}\n"
            msg += f"✨ 新增视频: {new_videos}\n"
            msg += f"🗑️ 已删除: {deleted_videos}\n"
            
            # 发送给所有白名单用户
            for chat_id in self.chat_id_whitelist:
                await self.send_message(chat_id, msg)
                
            logger.debug(f"已发送同步完成通知: {subscription_nickname}")
        except Exception as e:
            logger.error(f"发送同步完成通知失败: {e}")

    async def _trigger_initial_sync(self, subscription_id: str):
        """触发订阅后的初始同步"""
        try:
            from routers.subscribe.sync import sync_videos
            
            logger.debug(f"开始初始同步订阅: {subscription_id}")
            # 使用独立 session scope，避免跨协程复用外层会话
            with self._db_session() as db_session:
                await sync_videos(subscription_id, db_session)
                logger.debug(f"初始同步完成: {subscription_id}")
        except Exception as e:
            logger.error(f"初始同步过程中出错: {e}")

    async def _handle_add_live_subscription(self, chat_id: str, url: str):
        """处理添加直播订阅"""
        try:
            from routers.license import license_manager
            if not await license_manager.verify():
                await self.send_message(chat_id, "🔒 **功能限制**\n\n直播订阅功能是高级功能，您的授权无效或已过期。")
                return

            from live import adapters
            from sql.models import LiveSubscription
            
            # 1. 获取适配器
            adapter = adapters.get_adapter(url)
            if not adapter:
                # 增强识别逻辑：处理短链和特殊域名
                if 'douyin.com' in url or 'iesdouyin.com' in url:
                    adapter = adapters.get_adapter_by_platform('douyin')
                elif 'bilibili.com' in url or 'b23.tv' in url:
                    adapter = adapters.get_adapter_by_platform('bilibili')
                elif 'xiaohongshu.com' in url or 'xhslink.com' in url:
                    adapter = adapters.get_adapter_by_platform('xhs')
                elif 'huya.com' in url:
                    adapter = adapters.get_adapter_by_platform('huya')
            
            if not adapter:
                await self.send_message(chat_id, "❌ 无法识别的直播链接，目前支持：抖音、B站、虎牙、小红书、油管、咪咕")
                return

            platform_name = adapter.platform_name
            
            # 2. 获取直播间信息
            try:
                info = await adapter.get_room_info(url)
            except Exception as e:
                logger.error(f"获取直播间信息失败: {e}")
                await self.send_message(chat_id, f"❌ 获取直播间信息失败: {str(e)}")
                return
                
            anchor_name = info.get('anchor_name', '未知主播')
            room_id = info.get('room_id')
            avatar_url = info.get('avatar_url')
            
            # 允许离线添加：某些平台（如小红书）在未开播时可能拿不到 room_id，
            # 只要能获取到主播名即可创建订阅，后续开播时再更新 room_id。
            if not room_id and not anchor_name:
                await self.send_message(chat_id, "❌ 无法获取直播间有效信息（主播名和房间ID均为空）")
                return

            with self._db_session() as db:
                # 3. 查重
                # 优先用 room_url 查重 (和网页端保持一致)
                existing = db.query(LiveSubscription).filter(
                    LiveSubscription.platform == platform_name,
                    LiveSubscription.room_url == url
                ).first()
                
                # 如果 URL 不同，再检查 room_id
                if not existing and room_id:
                    existing = db.query(LiveSubscription).filter(
                        LiveSubscription.platform == platform_name,
                        LiveSubscription.room_id == str(room_id)
                    ).first()
                
                if existing:
                    await self.send_message(chat_id, f"ℹ️ 该直播间已存在: **{existing.anchor_name}**")
                    return
                
                # 4. 创建订阅
                import uuid
                new_sub = LiveSubscription(
                    id=str(uuid.uuid4()),  # 手动生成UUID
                    platform=platform_name,
                    room_url=url,
                    room_id=str(room_id) if room_id else "",
                    anchor_name=anchor_name,
                    avatar_url=avatar_url,
                    quality="原画", # 默认配置
                    auto_record="true", # 默认自动录制
                    check_interval=60,
                    notification_enabled="true"
                )
                db.add(new_sub)
                db.commit()
                db.refresh(new_sub)
                
                # 触发即时监控
                try:
                    from live.scheduler import live_scheduler
                    # 启动监控任务（无需重启）
                    await live_scheduler.add_monitor(
                        subscription_id=new_sub.id,
                        room_url=new_sub.room_url,
                        platform=new_sub.platform,
                        check_interval=new_sub.check_interval or 60
                    )
                except Exception as scheduler_err:
                    logger.warning(f"触发监控失败（系统将在重启后自动接管）: {scheduler_err}")
                
                # 5. 反馈成功
                platform_cn = {"douyin": "抖音", "bilibili": "B站", "huya": "虎牙", "xhs": "小红书", "youtube": "油管", "migu": "咪咕"}.get(platform_name, platform_name)
                
                # 净化主播名，防止Markdown解析错误
                safe_anchor_name = self.escape_markdown(anchor_name)
                
                msg = (
                    f"✅ **直播订阅添加成功**\n\n"
                    f"👤 主播: **{safe_anchor_name}**\n"
                    f"🏷️ 平台: {platform_cn}\n"
                    f"🆔 房间号: `{room_id or '未知'}`\n\n"
                    f"📹 **自动录制已开启**\n"
                    f"检测频率: 60秒 / 画质: 原画"
                )
                await self.send_message(chat_id, msg)

        except Exception as e:
            logger.error(f"添加直播订阅流程异常: {e}\n{traceback.format_exc()}")
            await self.send_message(chat_id, f"❌ 添加失败: {str(e)}")

    async def _handle_live_subscription_info(self, chat_id: str, sub_id: str, message_id: int, return_page: int = 1):
        """显示直播订阅详情"""
        try:
            with self._db_session() as db:
                from sql.models import LiveSubscription
                sub = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
                if not sub:
                    await self.send_message(chat_id, "❌ 找不到该订阅，可能已被删除")
                    return

                # 构建详情消息
                platform_cn = {"douyin": "抖音", "bilibili": "B站", "youtube": "油管", "migu": "咪咕"}.get(sub.platform, sub.platform)
                safe_name = self.escape_markdown(sub.anchor_name or "未知")
                
                status_text = "💤 未开播"
                if sub.is_recording == "true":
                    status_text = "🔴 录制中"
                elif sub.is_live == "true":
                    status_text = "🟢 直播中"
                
                auto_rec_status = "✅ 开启" if sub.auto_record == "true" else "⛔ 关闭"
                
                # 净化 room_url 防止 Markdown 报错 (如下划线)
                safe_url = self.escape_markdown(sub.room_url) if sub.room_url else ""
                
                msg = (
                    f"📡 **直播订阅详情**\n"
                    f"------------------------\n"
                    f"👤 主播: **{safe_name}**\n"
                    f"🏷️ 平台: {platform_cn}\n"
                    f"📊 状态: {status_text}\n"
                    f"📹 自动录制: {auto_rec_status}\n"
                    f"📅 添加时间: {sub.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                    f"🆔 房间号: `{sub.room_id}`\n"
                    f"🔗 [直播间链接]({safe_url})" # 使用 Markdown 链接
                )

                # 构建操作按钮
                inline_keyboard = []
                
                # [新增] 手动控制按钮 (优先级最高)
                if sub.is_recording == "true":
                    # 正在录制 -> 显示停止
                    inline_keyboard.append([
                        {"text": "⏹️ 停止录制 (并关闭自动)", "callback_data": f"lstop:{sub.id}:{return_page}"}
                    ])
                elif sub.is_live == "true":
                    # 直播中未录制 -> 显示开始
                    inline_keyboard.append([
                        {"text": "▶️ 开始录制 (并开启自动)", "callback_data": f"lstart:{sub.id}:{return_page}"}
                    ])
                
                # 开关自动录制
                toggle_action = "off" if sub.auto_record == "true" else "on"
                toggle_text = "⛔ 关闭自动录制" if sub.auto_record == "true" else "✅ 开启自动录制"
                inline_keyboard.append([
                    {"text": toggle_text, "callback_data": f"lar:{sub.id}:{toggle_action}:{return_page}"}
                ])
                
                # 删除和返回
                inline_keyboard.append([
                    {"text": "🗑️ 删除订阅", "callback_data": f"ldel:{sub.id}:{return_page}"},
                    {"text": "🔙 返回列表", "callback_data": f"lp:{return_page}"}
                ])

                await self._edit_message(chat_id, message_id, msg, inline_keyboard)
        except Exception as e:
            logger.error(f"显示直播详情失败: {e}\n{traceback.format_exc()}")
            await self.send_message(chat_id, "❌ 获取详情失败")

    async def _handle_live_manual_control(self, chat_id: str, sub_id: str, action: str, message_id: int, return_page: int = 1):
        """处理直播手动开始/停止"""
        try:
            with self._db_session() as db:
                from sql.models import LiveSubscription
                from live.scheduler import live_scheduler
                
                sub = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
                if not sub:
                    return

                if action == 'start':
                    # 开始录制 = 开启自动录制 + 触发监控
                    sub.auto_record = "true"
                    db.commit()
                    
                    await live_scheduler.add_monitor(
                        subscription_id=sub.id,
                        room_url=sub.room_url,
                        platform=sub.platform,
                        check_interval=sub.check_interval or 60
                    )
                    await self.send_message(chat_id, f"✅ 已开启自动录制，正在尝试启动任务...\n(如果主播在线，录制将在几秒内开始)")

                elif action == 'stop':
                    # 停止录制 = 关闭自动录制 + 强制停止
                    sub.auto_record = "false"
                    db.commit()
                    
                    # 强制停止当前录制 (并转码)
                    await live_scheduler.stop_recording_for_subscription(sub.id, convert_to_mp4=True)
                    
                    # 同时移除监控，防止立刻又被拉起（虽然 auto_record已关，但根据逻辑最好还是 remove 再 add 或者保持 remove）
                    # 实际上如果 auto_record 关了，keepalive check 就会忽略它。
                    # 但为了保险，我们刷新一下状态。
                    
                    await self.send_message(chat_id, f"⏹️ 已停止录制，并关闭了该直播间的自动录制。")

                # 刷新详情页状态
                # 稍微延迟一下等待状态更新
                import asyncio
                await asyncio.sleep(1)
                await self._handle_live_subscription_info(chat_id, sub_id, message_id, return_page=return_page)
        except Exception as e:
            logger.error(f"手动控制失败: {e}")
            await self.send_message(chat_id, f"❌ 操作失败: {e}")

    async def _handle_live_toggle_auto_record(self, chat_id: str, sub_id: str, action: str, message_id: int, return_page: int = 1):
        """切换直播自动录制状态"""
        try:
            with self._db_session() as db:
                from sql.models import LiveSubscription
                from live.scheduler import live_scheduler # 动态导入
                
                sub = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
                if not sub:
                    return

                # 更新数据库
                new_state = "true" if action == "on" else "false"
                sub.auto_record = new_state
                db.commit()
                
                # 同步 Scheduler
                if new_state == "true":
                    await live_scheduler.add_monitor(
                        subscription_id=sub.id,
                        room_url=sub.room_url,
                        platform=sub.platform,
                        check_interval=sub.check_interval or 60
                    )
                else:
                    await live_scheduler.remove_monitor(sub.id)
                
                # 刷新详情页
                await self._handle_live_subscription_info(chat_id, sub_id, message_id, return_page=return_page)
        except Exception as e:
            logger.error(f"切换自动录制失败: {e}")
            await self.send_message(chat_id, "❌ 操作失败")

    async def _handle_delete_live_subscription(self, chat_id: str, sub_id: str, confirmed: bool, message_id: int, return_page: int = 1):
        """删除直播订阅"""
        try:
            with self._db_session() as db:
                from sql.models import LiveSubscription
                sub = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
                
                if not sub:
                    # 已经被删了，返回列表
                    await self._handle_lives_command(chat_id, return_page, message_id)
                    return

                if not confirmed:
                    # 显示确认界面
                    safe_name = (sub.anchor_name or "未知").replace('*', '').replace('_', '\_')
                    msg = f"⚠️ **确认删除订阅？**\n\n主播: **{safe_name}**\n\n删除后将停止所有录制任务。"
                    
                    inline_keyboard = [
                        [
                            {"text": "❌ 确认删除", "callback_data": f"ldel_confirm:{sub.id}:{return_page}"},
                            {"text": "🔙 取消", "callback_data": f"li:{sub.id}:{return_page}"}
                        ]
                    ]
                    await self._edit_message(chat_id, message_id, msg, inline_keyboard)
                else:
                    # 执行删除
                    # 1. 停止 Scheduler 监控
                    from live.scheduler import live_scheduler
                    await live_scheduler.remove_monitor(sub.id)
                    
                    # 2. 删除关联的录制历史记录 (但保留物理文件)
                    from sql.models import LiveRecord
                    db.query(LiveRecord).filter(LiveRecord.subscription_id == sub.id).delete()
                    
                    # 3. 删除订阅本身
                    db.delete(sub)
                    db.commit()
                    
                    # 4. 返回列表
                    await self._handle_lives_command(chat_id, return_page, message_id)
        except Exception as e:
            logger.error(f"删除直播订阅失败: {e}")
            await self.send_message(chat_id, "❌ 删除失败")

# 全局单例
telegram_bot = TelegramBotService()
