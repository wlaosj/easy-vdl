import logging
import os
import re
import uuid
import asyncio
from datetime import datetime
from typing import Any, Dict, Optional
import urllib.parse

import aiohttp
from sqlalchemy.orm import Session

from sql import models

logger = logging.getLogger(__name__)

class TelegramMediaService:
    def __init__(self) -> None:
        self.base_url = "https://api.telegram.org"
        raw_bot_limit_mb = os.getenv("TELEGRAM_BOT_API_MAX_FILE_MB", "2000").strip()
        try:
            bot_limit_mb = int(raw_bot_limit_mb)
        except ValueError:
            bot_limit_mb = 2000
        self.bot_api_max_file_bytes = max(1, bot_limit_mb) * 1024 * 1024
        raw_limit = os.getenv("TELEGRAM_MEDIA_MAX_CONCURRENT", "5").strip()
        self.max_concurrent_transfers = self._normalize_concurrent_limit(raw_limit, fallback=5)
        self._transfer_semaphore = asyncio.Semaphore(self.max_concurrent_transfers)
        self._transfer_limit_lock = asyncio.Lock()
        self._path_lock = asyncio.Lock()
        self._media_group_lock = asyncio.Lock()
        self._media_group_context: Dict[str, Dict[str, Any]] = {}
        self._media_group_ttl_seconds = 600
        # 单个文件名组件（basename）保守上限，避免 UTF-8 多字节触发 Errno 36。
        self._max_filename_component_bytes = 240
        # 为重名追加后缀（如 _1/_12）预留空间。
        self._collision_suffix_reserved_bytes = 12
        
        self._telethon_client = None
        self._telethon_token = None
        self._telethon_lock = asyncio.Lock()
        self.cancel_flags: Dict[int, bool] = {}
        self.auto_delete_progress_msg = os.getenv("TELEGRAM_MEDIA_AUTO_DELETE_PROGRESS_MSG", "true").strip().lower() in {"1", "true", "yes", "on"}
        raw_progress_delete_delay = os.getenv("TELEGRAM_MEDIA_PROGRESS_DELETE_DELAY_SEC", "2").strip()
        try:
            progress_delete_delay = int(raw_progress_delete_delay)
        except ValueError:
            progress_delete_delay = 2
        self.progress_delete_delay_sec = max(0, min(progress_delete_delay, 300))

    @staticmethod
    def _to_bool(value: Any, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _normalize_concurrent_limit(value: Any, fallback: int = 5) -> int:
        try:
            limit = int(str(value).strip())
        except (TypeError, ValueError):
            limit = fallback
        return max(1, min(limit, 10))

    async def _refresh_transfer_limit(self, setting: Optional[models.NotificationSetting]) -> None:
        db_limit = getattr(setting, "telegram_media_max_concurrent", None)
        desired_limit = self._normalize_concurrent_limit(db_limit, fallback=self.max_concurrent_transfers)
        if desired_limit == self.max_concurrent_transfers:
            return
        async with self._transfer_limit_lock:
            if desired_limit == self.max_concurrent_transfers:
                return
            self.max_concurrent_transfers = desired_limit
            self._transfer_semaphore = asyncio.Semaphore(desired_limit)
            logger.info(f"Telegram Bot 转存并发已更新为: {desired_limit}")

    def cancel_download(self, progress_msg_id: int):
        self.cancel_flags[progress_msg_id] = True

    async def _get_telethon_client(self, token: str, proxy: Optional[str]) -> Any:
        from telethon import TelegramClient
        async with self._telethon_lock:
            if self._telethon_client and self._telethon_client.is_connected() and self._telethon_token == token:
                return self._telethon_client
                
            if self._telethon_client:
                try:
                    await self._telethon_client.disconnect()
                except Exception:
                    pass
                
            proxy_dict = None
            if proxy:
                try:
                    parsed = urllib.parse.urlparse(proxy)
                    proxy_type = "http"
                    if parsed.scheme.startswith("socks"):
                        proxy_type = "socks5"
                        
                    proxy_dict = {
                        "proxy_type": proxy_type,
                        "addr": parsed.hostname,
                        "port": parsed.port
                    }
                    if parsed.username:
                        proxy_dict["username"] = parsed.username
                        proxy_dict["password"] = parsed.password
                except Exception as e:
                    logger.warning(f"解析代理失败(Telethon将直连): {e}")

            # 兜底公开 api_id (官方 Telegram Android 客户端 API ID，允许 Bot 登录)
            api_id = 6
            api_hash = "eb06d4abfb49dc3eeb1aeb98ae0f581e"
            
            session_path = "/app/database/telethon_bot.session"
            os.makedirs(os.path.dirname(session_path), exist_ok=True)
            
            try:
                import socks
            except ImportError:
                pass

            client = TelegramClient(session_path, api_id, api_hash, proxy=proxy_dict)
            await client.start(bot_token=token)
            self._telethon_client = client
            self._telethon_token = token
            return client

    def _load_active_bot_config(self, db: Session) -> Optional[models.NotificationSetting]:
        settings = db.query(models.NotificationSetting).filter(
            models.NotificationSetting.telegram_bot_enabled == "true"
        ).all()
        for item in settings:
            if (item.telegram_bot_token or "").strip():
                return item
        return None

    @staticmethod
    def _is_chat_allowed(chat_id: str, whitelist_raw: Optional[str]) -> bool:
        if not whitelist_raw:
            return False
        whitelist = {cid.strip() for cid in whitelist_raw.split(",") if cid.strip()}
        return chat_id in whitelist

    @staticmethod
    def _extract_media(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Priority: video -> animation -> document(video/image) -> photo -> sticker
        if message.get("video"):
            v = message["video"]
            return {
                "media_type": "video",
                "file_id": v.get("file_id"),
                "file_unique_id": v.get("file_unique_id"),
                "mime_type": v.get("mime_type"),
                "file_size": v.get("file_size"),
            }

        if message.get("animation"):
            a = message["animation"]
            return {
                "media_type": "animation",
                "file_id": a.get("file_id"),
                "file_unique_id": a.get("file_unique_id"),
                "mime_type": a.get("mime_type"),
                "file_size": a.get("file_size"),
                "file_name": a.get("file_name"),
            }

        if message.get("document"):
            d = message["document"]
            mime = (d.get("mime_type") or "").lower()
            if mime.startswith("video/"):
                media_type = "video"
            elif mime.startswith("image/"):
                media_type = "photo"
            else:
                return None
            return {
                "media_type": media_type,
                "file_id": d.get("file_id"),
                "file_unique_id": d.get("file_unique_id"),
                "mime_type": d.get("mime_type"),
                "file_size": d.get("file_size"),
                "file_name": d.get("file_name"),
            }

        if message.get("photo"):
            photos = message["photo"] or []
            if not photos:
                return None
            # Use largest size variant.
            p = photos[-1]
            return {
                "media_type": "photo",
                "file_id": p.get("file_id"),
                "file_unique_id": p.get("file_unique_id"),
                "mime_type": "image/jpeg",
                "file_size": p.get("file_size"),
            }

        if message.get("sticker"):
            s = message["sticker"]
            if s.get("is_video"):
                mime_type = "video/webm"
            elif s.get("is_animated"):
                mime_type = "application/x-tgsticker"
            else:
                mime_type = "image/webp"
            return {
                "media_type": "sticker",
                "file_id": s.get("file_id"),
                "file_unique_id": s.get("file_unique_id"),
                "mime_type": mime_type,
                "file_size": s.get("file_size"),
                "emoji": s.get("emoji"),
            }

        return None

    async def _telegram_delete_message(
        self,
        token: str,
        chat_id: str,
        message_id: int,
        proxy: Optional[str],
    ) -> bool:
        url = f"{self.base_url}/bot{token}/deleteMessage"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"chat_id": chat_id, "message_id": message_id},
                proxy=proxy,
                timeout=20,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200 and data.get("ok"):
                    return True

                # 用户可能已提前删除原消息，此时 Telegram 会返回 not found。
                # 这类场景应视为“原消息已删除”，用于正确提示。
                desc = str(data.get("description") or "").lower()
                if "message to delete not found" in desc or "message not found" in desc:
                    return True

                logger.debug(
                    "telegram deleteMessage failed: status=%s chat_id=%s message_id=%s resp=%s",
                    resp.status, chat_id, message_id, data
                )
                return False

    async def _delete_message_later(
        self,
        token: str,
        chat_id: str,
        message_id: int,
        proxy: Optional[str],
        delay_sec: int,
    ) -> None:
        if delay_sec > 0:
            await asyncio.sleep(delay_sec)
        try:
            await self._telegram_delete_message(token, chat_id, message_id, proxy)
        except Exception:
            pass

    async def _telegram_edit_message(
        self,
        token: str,
        chat_id: str,
        message_id: int,
        text: str,
        proxy: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        url = f"{self.base_url}/bot{token}/editMessageText"
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, proxy=proxy, timeout=10) as resp:
                    return resp.status == 200
            except Exception as e:
                logger.warning(f"edit message failed: {e}")
                return False

    async def _telegram_send_message(
        self,
        token: str,
        chat_id: str,
        text: str,
        proxy: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        return_message_id: bool = False
    ) -> Any:
        url = f"{self.base_url}/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url, json=payload, proxy=proxy, timeout=20
                ) as resp:
                    if return_message_id:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            return data.get("result", {}).get("message_id")
                        return None
                    return resp.status == 200
            except Exception as e:
                logger.warning(f"send message failed: {e}")
                return None if return_message_id else False

    @staticmethod
    def _pick_ext(media: Dict[str, Any]) -> str:
        file_name = (media.get("file_name") or "").lower()
        if "." in file_name:
            return "." + file_name.rsplit(".", 1)[1]
        mime_type = (media.get("mime_type") or "").lower()
        if "tgsticker" in mime_type:
            return ".tgs"
        if mime_type == "video/webm":
            return ".webm"
        if mime_type == "image/webp":
            return ".webp"
        if mime_type == "image/png":
            return ".png"
        if mime_type == "image/gif":
            return ".gif"
        if media.get("media_type") == "video" or mime_type.startswith("video/"):
            return ".mp4"
        return ".jpg"

    @staticmethod
    def _build_safe_stem(message: Dict[str, Any], fallback: str) -> str:
        # Prefer Telegram caption (text under video/photo), fallback to unique id.
        raw = str(message.get("caption") or "").strip()
        if not raw:
            return fallback

        # Normalize whitespace and keep a concise name.
        raw = re.sub(r"\s+", " ", raw)
        raw = raw[:80]

        # Remove path-sensitive characters, keep letters/digits/underscore/dash/space.
        safe = re.sub(r"[\\/:*?\"<>|]+", "", raw)
        safe = safe.strip(" .")
        if not safe:
            return fallback
        return safe

    @staticmethod
    def _trim_utf8_bytes(text: str, max_bytes: int) -> str:
        if max_bytes <= 0:
            return ""
        raw = text.encode("utf-8")
        if len(raw) <= max_bytes:
            return text

        cut = raw[:max_bytes]
        while cut:
            try:
                return cut.decode("utf-8").strip(" ._")
            except UnicodeDecodeError:
                cut = cut[:-1]
        return ""

    def _build_file_stem_with_limit(self, ts: str, stem: str, short_unique: str, ext: str) -> str:
        fixed_part = f"{ts}__{short_unique}{ext}"
        fixed_bytes = len(fixed_part.encode("utf-8"))
        allowed_stem_bytes = (
            self._max_filename_component_bytes
            - self._collision_suffix_reserved_bytes
            - fixed_bytes
        )
        safe_stem = self._trim_utf8_bytes(stem, allowed_stem_bytes)
        if not safe_stem:
            safe_stem = "media"
        return f"{ts}_{safe_stem}_{short_unique}"

    async def _reserve_unique_path(self, base_dir: str, filename_stem: str, ext: str) -> str:
        async with self._path_lock:
            candidate = os.path.join(base_dir, f"{filename_stem}{ext}")
            if not os.path.exists(candidate):
                return candidate

            suffix = 1
            while True:
                candidate = os.path.join(base_dir, f"{filename_stem}_{suffix}{ext}")
                if not os.path.exists(candidate):
                    return candidate
                suffix += 1

    def _cleanup_media_group_context(self, now_ts: float) -> None:
        stale_keys = []
        for group_id, ctx in self._media_group_context.items():
            updated_at = float(ctx.get("updated_at") or 0)
            if now_ts - updated_at > self._media_group_ttl_seconds:
                stale_keys.append(group_id)
        for key in stale_keys:
            self._media_group_context.pop(key, None)

    async def _resolve_group_stem(
        self,
        message: Dict[str, Any],
        fallback_stem: str,
    ) -> str:
        media_group_id = str(message.get("media_group_id") or "").strip()
        if not media_group_id:
            return fallback_stem

        caption = str(message.get("caption") or "").strip()
        if caption:
            caption_stem = self._build_safe_stem(message, fallback_stem)
            async with self._media_group_lock:
                now_ts = datetime.now().timestamp()
                self._cleanup_media_group_context(now_ts)
                ctx = self._media_group_context.get(media_group_id) or {
                    "title": caption_stem,
                    "counter": 0,
                    "updated_at": now_ts,
                }
                ctx["title"] = caption_stem
                ctx["updated_at"] = now_ts
                self._media_group_context[media_group_id] = ctx

        title_from_group = None
        for _ in range(8):
            async with self._media_group_lock:
                now_ts = datetime.now().timestamp()
                self._cleanup_media_group_context(now_ts)
                ctx = self._media_group_context.get(media_group_id)
                if ctx and ctx.get("title"):
                    title_from_group = str(ctx["title"])
                    break
            await asyncio.sleep(0.1)

        async with self._media_group_lock:
            now_ts = datetime.now().timestamp()
            self._cleanup_media_group_context(now_ts)
            ctx = self._media_group_context.get(media_group_id) or {
                "title": title_from_group or fallback_stem,
                "counter": 0,
                "updated_at": now_ts,
            }
            if not ctx.get("title"):
                ctx["title"] = fallback_stem
            ctx["counter"] = int(ctx.get("counter") or 0) + 1
            ctx["updated_at"] = now_ts
            self._media_group_context[media_group_id] = ctx
            counter = ctx["counter"]
            title = str(ctx.get("title") or fallback_stem)

        return f"{title}_{counter:02d}"

    async def _download_media_via_mtproto(self, token: str, proxy: Optional[str], chat_id: int, message_id: int, output_path: str, progress_msg_id: Optional[int] = None):
        client = await self._get_telethon_client(token, proxy)
        
        # Telethon fetch message by ID
        msg = await client.get_messages(chat_id, ids=message_id)
        if not msg or not msg.media:
            raise RuntimeError(f"无法定位到指定的媒体消息: chat_id={chat_id} message_id={message_id}")
            
        import time
        last_update_time = time.time()
        last_reported_percent = -1
        
        if progress_msg_id:
            self.cancel_flags[progress_msg_id] = False
            
        try:
            async def progress_callback(current, total):
                if progress_msg_id and self.cancel_flags.get(progress_msg_id):
                    raise RuntimeError("UserCancelled")
                
                nonlocal last_update_time, last_reported_percent
                if total == 0 or not progress_msg_id:
                    return
                
                now = time.time()
                percent = int((current / total) * 100)
                
                # 每隔3秒更新一次，或者当达到100%时更新，且进度需发生改变
                if (now - last_update_time > 3 and percent != last_reported_percent) or percent == 100:
                    text = f"⏳ 正在直连下载...\n进度: {percent}% ({round(current/1024/1024, 1)}MB / {round(total/1024/1024, 1)}MB)"
                    
                    # 包含取消按钮
                    reply_markup = {
                        "inline_keyboard": [[{"text": "❌ 取消转存", "callback_data": f"cancel_mtproto:{progress_msg_id}"}]]
                    }
                    
                    # 创建后台任务去更新，避免阻塞下载主流程
                    asyncio.create_task(
                        self._telegram_edit_message(token, str(chat_id), progress_msg_id, text, proxy, reply_markup=reply_markup)
                    )
                    
                    last_update_time = now
                    last_reported_percent = percent

            # Telethon 使用 MTProto 下载，突破 20MB 限制
            downloaded_path = await client.download_media(msg, file=output_path, progress_callback=progress_callback)
            if not downloaded_path or not os.path.exists(downloaded_path):
                 raise RuntimeError("Telethon MTProto 下载未生成文件")
            
            return os.path.getsize(downloaded_path)
        finally:
            if progress_msg_id:
                self.cancel_flags.pop(progress_msg_id, None)

    async def ingest_update(self, update: Dict[str, Any], db: Session) -> Dict[str, Any]:
        from routers.license import license_manager
        is_valid_license = await license_manager.verify()

        message = update.get("message") or {}
        if not message:
            raise ValueError("update.message is required")

        chat_id_str = str((message.get("chat") or {}).get("id") or "")
        if not chat_id_str:
            raise ValueError("chat_id is missing in update.message.chat.id")
            
        chat_id_int = int((message.get("chat") or {}).get("id") or 0)
        message_id = message.get("message_id")
        if not isinstance(message_id, int):
            raise ValueError("message_id is missing in update.message.message_id")

        media = self._extract_media(message)
        if not media:
            raise ValueError("no supported media found (video/animation/document/photo/sticker)")
        file_size = media.get("file_size")
        if isinstance(file_size, int) and file_size > self.bot_api_max_file_bytes:
            max_mb = int(self.bot_api_max_file_bytes / (1024 * 1024))
            current_mb = round(file_size / (1024 * 1024), 1)
            raise ValueError(
                f"文件过大（{current_mb}MB），超过全局可下载上限（约 {max_mb}MB）"
            )

        file_id = media.get("file_id")
        if not file_id:
            raise ValueError("file_id is missing")

        setting = self._load_active_bot_config(db)
        if not setting:
            raise RuntimeError("telegram bot config not found or disabled")

        if not self._is_chat_allowed(chat_id_str, setting.telegram_chat_id):
            raise PermissionError("chat_id is not in telegram whitelist")

        token = (setting.telegram_bot_token or "").strip()
        proxy = setting.telegram_proxy or None
        await self._refresh_transfer_limit(setting)
        use_date_subdir = self._to_bool(getattr(setting, "telegram_media_use_date_subdir", "true"), default=True)

        if not is_valid_license:
            error_msg = (
                "⚠️ **提示：该功能需要高级版授权**\n\n"
                "当前基础版本不支持通过机器人直接转存媒体文件。\n\n"
                "**升级高级版可获取：**\n"
                "· 支持 2GB 大文件直接转存\n"
                "· 链接智能提取与并发下载\n"
                "· 直播/视频订阅功能\n\n"
                "如需了解详情：[获取高级版](https://afdian.com/a/docker)"
            )
            await self._telegram_send_message(
                token=token,
                chat_id=chat_id_str,
                text=error_msg,
                proxy=proxy,
                reply_to_message_id=message_id
            )
            raise PermissionError("需要激活高级版才能使用 Bot 转存功能")

        if not getattr(license_manager, 'is_lifetime', False):
            promo_text = (
                "⚠️ **提示：当前大文件直连转存功能处于优先测试阶段**\n\n"
                "作为硬核进阶通讯功能，目前仅向**永久授权用户**优先开放测试。\n\n"
                "【永久授权权益说明】\n"
                "- 解锁高级版全部功能\n"
                "- 新功能（如本项直连转存）优先体验\n"
                "- 授权长期有效\n"
                "- 支持 2 台设备同时绑定\n"
                "- 专属建议反馈与处理通道\n\n"
                "注：如已有有效时限授权，可通过私信原授权码补差价升级。"
            )
            await self._telegram_send_message(
                token=token,
                chat_id=chat_id_str,
                text=promo_text,
                proxy=proxy,
                reply_to_message_id=message_id
            )
            raise PermissionError("媒体转存功能当前限永久授权用户优先测试")

        async with self._transfer_semaphore:
            ext = self._pick_ext(media)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique = str(media.get("file_unique_id") or str(uuid.uuid4()))
            short_unique = re.sub(r"[^A-Za-z0-9_-]+", "", unique)[:8] or "u"
            base_stem = self._build_safe_stem(message, unique)
            stem = await self._resolve_group_stem(message, base_stem)
            file_stem = self._build_file_stem_with_limit(ts, stem, short_unique, ext)
            # 目录结构按 Chat ID 聚合，日期子目录可在通知设置中关闭。
            if use_date_subdir:
                rel_dir = os.path.join("telegram-inbox", chat_id_str, datetime.now().strftime("%Y%m%d"))
            else:
                rel_dir = os.path.join("telegram-inbox", chat_id_str)
            abs_dir = os.path.join("/app/downloads", rel_dir)
            os.makedirs(abs_dir, exist_ok=True)
            abs_file = await self._reserve_unique_path(abs_dir, file_stem, ext)

            logger.info(f"开始使用 Telethon(MTProto) 下载媒体...")
            
            # 向用户发送开始下载的通知
            file_mb_text = ""
            if file_size:
                file_mb_text = f" ({round(file_size / (1024 * 1024), 1)} MB)"
            
            progress_msg_id = await self._telegram_send_message(
                token=token,
                chat_id=chat_id_str,
                text=f"⏳ 检测到大媒体文件，正在开始直连下载{file_mb_text}...\n(下载需要时间，完成前请勿删除原发消息)",
                proxy=proxy,
                reply_to_message_id=message_id,
                return_message_id=True
            )
            
            # 初始化消息加上取消按钮
            if progress_msg_id:
                reply_markup = {"inline_keyboard": [[{"text": "❌ 取消转存", "callback_data": f"cancel_mtproto:{progress_msg_id}"}]]}
                await self._telegram_edit_message(
                    token=token,
                    chat_id=chat_id_str,
                    message_id=progress_msg_id,
                    text=f"⏳ 检测到大媒体文件，正在开始直连下载{file_mb_text}...\n(下载需要时间，完成前请勿删除原发消息)",
                    proxy=proxy,
                    reply_markup=reply_markup
                )

            try:
                downloaded_size = await self._download_media_via_mtproto(token, proxy, chat_id_int, message_id, abs_file, progress_msg_id)
                logger.info(f"媒体下载完成，大小: {downloaded_size} bytes")
                
                if progress_msg_id:
                    await self._telegram_edit_message(
                        token=token,
                        chat_id=chat_id_str,
                        message_id=progress_msg_id,
                        text=f"✅ 下载完成并已保存到本地！\n文件大小: {round(downloaded_size/1024/1024, 1)}MB",
                        proxy=proxy
                    )
                    if self.auto_delete_progress_msg:
                        asyncio.create_task(
                            self._delete_message_later(
                                token=token,
                                chat_id=chat_id_str,
                                message_id=progress_msg_id,
                                proxy=proxy,
                                delay_sec=self.progress_delete_delay_sec,
                            )
                        )
            except Exception as e:
                err_msg = str(e)
                if err_msg == "UserCancelled":
                    logger.info("Telethon 媒体下载已被用户取消")
                    if progress_msg_id:
                        await self._telegram_edit_message(
                            token=token,
                            chat_id=chat_id_str,
                            message_id=progress_msg_id,
                            text="🛑 下载已被取消",
                            proxy=proxy
                        )
                    # 清理部分下载的文件
                    if os.path.exists(abs_file):
                        try:
                            os.remove(abs_file)
                        except:
                            pass
                    return {
                        "chat_id": chat_id_str,
                        "media_type": media.get("media_type"),
                        "file_id": file_id,
                        "size_bytes": 0,
                        "source_message_deleted": False,
                    }
                else:
                    logger.error(f"Telethon 媒体下载失败: {e}")
                    if progress_msg_id:
                        await self._telegram_edit_message(
                            token=token,
                            chat_id=chat_id_str,
                            message_id=progress_msg_id,
                            text=f"❌ 下载失败: {err_msg}",
                            proxy=proxy
                        )
                    raise e

        source_message_deleted = False
        try:
            source_message_deleted = await self._telegram_delete_message(
                token=token,
                chat_id=chat_id_str,
                message_id=message_id,
                proxy=proxy,
            )
        except Exception:
            source_message_deleted = False

        return {
            "chat_id": chat_id_str,
            "media_type": media.get("media_type"),
            "file_id": file_id,
            "size_bytes": downloaded_size,
            "source_message_deleted": source_message_deleted,
        }

telegram_media_service = TelegramMediaService()
