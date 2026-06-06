"""
企业微信应用Bot服务
处理回调（验签+收消息）、交互指令、菜单管理
"""
import asyncio
import base64
import hashlib
import logging
import os
import struct
import sys
import time
import xml.etree.ElementTree as ET
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from fastapi import APIRouter, Request, Response, Depends
from sqlalchemy.orm import Session

from sql.database_postgresql import get_session
from services.wecom_api import WecomApiClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wecom", tags=["企业微信Bot"])

# 默认菜单配置（对标 TG Bot）
DEFAULT_MENU = {
    "button": [
        {"type": "click", "name": "查状态", "key": "查状态"},
        {"type": "click", "name": "查任务", "key": "查任务"},
        {
            "name": "更多",
            "sub_button": [
                {"type": "click", "name": "查授权", "key": "查授权"},
                {"type": "click", "name": "查订阅", "key": "查订阅"},
                {"type": "click", "name": "查直播", "key": "查直播"},
                {"type": "click", "name": "失败任务", "key": "失败任务"},
                {"type": "click", "name": "帮助", "key": "帮助"},
            ]
        }
    ]
}


class WecomBotService:
    """企业微信应用Bot服务（单例）"""

    _instance: Optional["WecomBotService"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.client: Optional[WecomApiClient] = None
        self.callback_token: Optional[str] = None
        self.callback_aes_key: Optional[str] = None
        self.enabled: bool = False

    def load_config(self, db: Session) -> bool:
        """从数据库加载配置"""
        try:
            from sql.models import NotificationSetting
            setting = db.query(NotificationSetting).filter(
                NotificationSetting.wecom_bot_enabled == "true"
            ).first()

            if setting and setting.wecom_corp_id and setting.wecom_secret and setting.wecom_agent_id:
                self.client = WecomApiClient(
                    corp_id=setting.wecom_corp_id,
                    agent_id=setting.wecom_agent_id,
                    secret=setting.wecom_secret,
                    proxy=getattr(setting, 'wecom_api_proxy', None),
                )
                self.callback_token = setting.wecom_callback_token
                self.callback_aes_key = setting.wecom_callback_aes_key
                self.enabled = True
                logger.info(f"企业微信Bot配置已加载: corp_id={setting.wecom_corp_id[:8]}...")
                return True

            logger.info("企业微信Bot未配置或未启用")
            self.enabled = False
            return False
        except Exception as e:
            logger.error(f"加载企业微信Bot配置失败: {e}")
            self.enabled = False
            return False

    async def start(self):
        """启动Bot"""
        try:
            from sql.database_postgresql import get_session
            db = get_session()
            try:
                if self.load_config(db):
                    await self._setup_menu()
                    logger.info("企业微信Bot已启动")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"企业微信Bot启动失败: {e}")

    async def stop(self):
        """停止Bot"""
        self.enabled = False
        self.client = None
        logger.info("企业微信Bot已停止")

    async def reload(self):
        """重载配置"""
        await self.stop()
        await self.start()

    async def _setup_menu(self):
        """设置默认菜单"""
        if not self.client:
            return
        try:
            result = await self.client.set_menu(DEFAULT_MENU["button"])
            if result.get("errcode") == 0:
                logger.info("企业微信菜单设置成功")
            else:
                logger.warning(f"企业微信菜单设置失败: {result}")
        except Exception as e:
            logger.error(f"设置企业微信菜单异常: {e}")

    def _decrypt_echostr(self, echostr: str) -> Optional[str]:
        """解密企业微信回调的 echostr（AES-256-CBC）"""
        if not self.callback_aes_key:
            return echostr  # 没有 AES key 则直接返回原文

        try:
            aes_key = base64.b64decode(self.callback_aes_key + "=")
            iv = aes_key[:16]
            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            plain = decryptor.update(base64.b64decode(echostr)) + decryptor.finalize()
            pad_len = plain[-1]
            plain = plain[:-pad_len]
            msg_len = struct.unpack(">I", plain[16:20])[0]
            return plain[20:20 + msg_len].decode("utf-8")
        except Exception as e:
            logger.error(f"解密 echostr 失败: {e}")
            return None

    def _decrypt_message(self, encrypt_content: str, msg_signature: str, timestamp: str, nonce: str) -> Optional[str]:
        """解密企业微信回调消息"""
        if not self.callback_aes_key or not self.callback_token:
            logger.warning("企业微信回调AES Key或Token未配置")
            return None

        try:
            # 先验证签名
            params = sorted([self.callback_token, timestamp, nonce, encrypt_content])
            hash_str = hashlib.sha1("".join(params).encode("utf-8")).hexdigest()
            if hash_str != msg_signature:
                logger.warning(f"企业微信消息签名验证失败")
                return None

            # AES 解密
            aes_key = base64.b64decode(self.callback_aes_key + "=")
            iv = aes_key[:16]
            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            plain = decryptor.update(base64.b64decode(encrypt_content)) + decryptor.finalize()
            pad_len = plain[-1]
            plain = plain[:-pad_len]
            # 前16字节随机字符串，4字节消息长度，消息内容，最后是corp_id
            msg_len = struct.unpack(">I", plain[16:20])[0]
            msg_content = plain[20:20 + msg_len].decode("utf-8")
            return msg_content
        except Exception as e:
            logger.error(f"解密企业微信消息失败: {e}", exc_info=True)
            return None

    def _verify_signature(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> Optional[str]:
        """验证企业微信回调签名"""
        if not self.callback_token:
            logger.warning("企业微信回调Token未配置")
            return None

        # 企业微信签名: sha1(sort([token, timestamp, nonce, echostr]))
        params = sorted([self.callback_token, timestamp, nonce, echostr])
        hash_str = hashlib.sha1("".join(params).encode("utf-8")).hexdigest()

        if hash_str == msg_signature:
            # 签名匹配，解密 echostr 返回
            return self._decrypt_echostr(echostr)
        logger.warning(f"企业微信回调签名验证失败: 计算={hash_str[:16]}..., 期望={msg_signature[:16]}...")
        return None

    def _parse_xml_message(self, xml_data: str) -> Optional[dict]:
        """解析企业微信XML消息"""
        try:
            root = ET.fromstring(xml_data)
            msg = {}
            for child in root:
                msg[child.tag] = child.text
            return msg
        except Exception as e:
            logger.error(f"解析企业微信XML失败: {e}")
            return None

    def _encrypt_message(self, reply_xml: str, nonce: str, timestamp: str) -> str:
        """加密企业微信回复消息"""
        if not self.callback_aes_key or not self.callback_token:
            return reply_xml

        try:
            aes_key = base64.b64decode(self.callback_aes_key + "=")
            iv = aes_key[:16]
            # 16字节随机 + 4字节长度 + 消息内容 + corp_id
            random_bytes = os.urandom(16)
            msg_bytes = reply_xml.encode("utf-8")
            msg_len = struct.pack(">I", len(msg_bytes))
            plain = random_bytes + msg_len + msg_bytes + self.client.corp_id.encode("utf-8")
            # PKCS7 padding
            pad_len = 32 - len(plain) % 32
            plain += bytes([pad_len] * pad_len)
            # AES 加密
            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
            encryptor = cipher.encryptor()
            encrypted = base64.b64encode(encryptor.update(plain) + encryptor.finalize()).decode("utf-8")
            # 生成签名
            sign_params = sorted([self.callback_token, timestamp, nonce, encrypted])
            sign = hashlib.sha1("".join(sign_params).encode("utf-8")).hexdigest()
            return f"""<xml>
<Encrypt><![CDATA[{encrypted}]]></Encrypt>
<MsgSignature><![CDATA[{sign}]]></MsgSignature>
<TimeStamp>{timestamp}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""
        except Exception as e:
            logger.error(f"加密回复消息失败: {e}", exc_info=True)
            return reply_xml

    def _build_reply_xml(self, from_user: str, to_user: str, content: str) -> str:
        """构建回复XML"""
        timestamp = int(time.time())
        return f"""<xml>
<ToUserName><![CDATA[{from_user}]]></ToUserName>
<FromUserName><![CDATA[{to_user}]]></FromUserName>
<CreateTime>{timestamp}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""

    async def handle_callback(self, request: Request) -> Response:
        """处理企业微信回调请求"""
        # GET 请求：验签
        if request.method == "GET":
            params = dict(request.query_params)
            logger.info(f"企业微信回调验签请求: {params}")
            echostr = self._verify_signature(
                msg_signature=params.get("msg_signature", ""),
                timestamp=params.get("timestamp", ""),
                nonce=params.get("nonce", ""),
                echostr=params.get("echostr", ""),
            )
            if echostr:
                logger.info("企业微信回调验签成功")
                return Response(content=echostr, media_type="text/plain")
            logger.warning("企业微信回调验签失败")
            return Response(content="verification failed", status_code=403)

        # POST 请求：接收消息
        try:
            body = await request.body()
            xml_data = body.decode("utf-8")
            logger.info(f"企业微信收到回调POST: {xml_data[:500]}")

            # 企业微信消息可能加密，需要先解密
            if "<Encrypt>" in xml_data:
                import xml.etree.ElementTree as _ET
                root = _ET.fromstring(xml_data)
                encrypt_node = root.find("Encrypt")
                if encrypt_node is not None and encrypt_node.text:
                    # 解密消息
                    params = dict(request.query_params)
                    decrypted = self._decrypt_message(
                        encrypt_node.text,
                        params.get("msg_signature", ""),
                        params.get("timestamp", ""),
                        params.get("nonce", ""),
                    )
                    if decrypted:
                        xml_data = decrypted
                        logger.info(f"企业微信解密后: {xml_data[:500]}")
                    else:
                        logger.error("企业微信消息解密失败")
                        return Response(content="success", media_type="text/plain")

            msg = self._parse_xml_message(xml_data)

            if not msg:
                logger.warning("企业微信回调XML解析失败")
                return Response(content="success", media_type="text/plain")

            msg_type = msg.get("MsgType", "")
            from_user = msg.get("FromUserName", "")
            to_user = msg.get("ToUserName", "")
            logger.info(f"企业微信消息: type={msg_type}, from={from_user}, to={to_user}")

            # 只处理文本消息和菜单事件
            if msg_type == "text":
                content = msg.get("Content", "").strip()
                logger.info(f"企业微信文本消息: {content}")
                reply = await self._process_text_command(content, from_user)
            elif msg_type == "event":
                event_key = msg.get("EventKey", "")
                event_type = msg.get("Event", "")
                logger.info(f"企业微信事件: event={event_type}, key={event_key}")
                reply = await self._process_menu_click(event_key, from_user)
            else:
                reply = f"收到消息类型: {msg_type}，暂不支持处理"

            # 通过API异步回复消息（不能在回调响应体中直接回复）
            if reply:
                logger.info(f"企业微信回复: {reply[:100]}...")
                asyncio.create_task(self.send_notification(from_user, reply))

            return Response(content="success", media_type="text/plain")

            return Response(content="success", media_type="text/plain")

        except Exception as e:
            logger.error(f"处理企业微信回调异常: {e}", exc_info=True)
            return Response(content="success", media_type="text/plain")

    async def _process_text_command(self, content: str, from_user: str) -> str:
        """处理文本命令"""
        content_lower = content.lower().strip()

        # 基础命令
        if content_lower in ("帮助", "help"):
            return self._help_text()
        elif content_lower in ("查授权", "授权"):
            return await self._check_license()
        elif content_lower in ("查任务", "任务"):
            return await self._check_tasks()
        elif content_lower in ("关于", "about"):
            return self._about_text()
        elif content_lower in ("查状态", "状态", "status"):
            return await self._check_status()
        elif content_lower in ("查订阅", "订阅"):
            return await self._check_subscriptions()
        elif content_lower in ("查直播", "直播"):
            return await self._check_live_subscriptions()
        elif content_lower in ("失败任务", "失败"):
            return await self._check_failed_tasks()
        elif content_lower in ("重启", "restart"):
            return await self._restart_service()
        # 重试任务: "重试 任务ID"
        elif content_lower.startswith("重试 "):
            task_id = content.split(" ", 1)[1].strip() if " " in content else ""
            if task_id:
                return await self._retry_task(task_id)
            return "格式: 重试 任务ID"
        # 删除任务: "删除 任务ID"
        elif content_lower.startswith("删除 "):
            task_id = content.split(" ", 1)[1].strip() if " " in content else ""
            if task_id:
                return await self._delete_task(task_id)
            return "格式: 删除 任务ID"
        # 暂停订阅: "暂停 订阅ID"
        elif content_lower.startswith("暂停 "):
            sub_id = content.split(" ", 1)[1].strip() if " " in content else ""
            if sub_id:
                return await self._pause_subscription(sub_id)
            return "格式: 暂停 订阅ID"
        # 恢复订阅: "恢复 订阅ID"
        elif content_lower.startswith("恢复 "):
            sub_id = content.split(" ", 1)[1].strip() if " " in content else ""
            if sub_id:
                return await self._resume_subscription(sub_id)
            return "格式: 恢复 订阅ID"
        # 删除订阅: "删订 订阅ID"
        elif content_lower.startswith("删订 "):
            sub_id = content.split(" ", 1)[1].strip() if " " in content else ""
            if sub_id:
                return await self._delete_subscription(sub_id)
            return "格式: 删订 订阅ID"
        # URL 下载命令: "下载 https://..."
        elif content_lower.startswith("下载 ") or content_lower.startswith("dl "):
            import re as _re
            urls = _re.findall(r'https?://[^\s<>"\']+', content)
            if urls:
                return await self._download_url(urls[0].rstrip("/"))
            return "格式: 下载 URL\n例如: 下载 https://v.douyin.com/xxx"
        # URL 订阅命令: "订阅 https://..."
        elif content_lower.startswith("订阅 "):
            import re as _re
            urls = _re.findall(r'https?://[^\s<>"\']+', content)
            if urls:
                return await self._add_subscription(urls[0].rstrip("/"))
            return "格式: 订阅 URL\n例如: 订阅 https://v.douyin.com/xxx"
        # URL 直播命令: "直播 https://..."
        elif content_lower.startswith("直播 "):
            import re as _re
            urls = _re.findall(r'https?://[^\s<>"\']+', content)
            if urls:
                return await self._add_live_subscription(urls[0].rstrip("/"))
            return "格式: 直播 URL\n例如: 直播 https://live.douyin.com/xxx"
        # 智能 URL 识别（直接发链接或文字中包含链接）
        elif "http://" in content or "https://" in content:
            import re
            urls = re.findall(r'https?://[^\s<>"\']+', content)
            if urls:
                return await self._handle_url(urls[0].rstrip("/"))
            return "未识别到有效链接"
        elif content_lower.startswith("http://") or content_lower.startswith("https://"):
            return await self._handle_url(content.strip())
        else:
            return f"收到: {content}\n\n发送「帮助」查看可用命令"

    async def _process_menu_click(self, event_key: str, from_user: str) -> str:
        """处理菜单点击事件"""
        return await self._process_text_command(event_key, from_user)

    def _help_text(self) -> str:
        """帮助信息"""
        return """【Easy-VDL 帮助】

📊 查询命令：
• 查状态 - 系统状态详情
• 查任务 - 下载任务统计
• 查授权 - 授权状态
• 查订阅 - 视频订阅列表
• 查直播 - 直播录制列表
• 失败任务 - 查看失败任务

🎬 操作命令：
• 下载 URL - 下载单个视频
• 订阅 URL - 添加视频订阅
• 直播 URL - 添加直播录制
• 重试 任务ID - 重试失败任务
• 删除 任务ID - 删除任务
• 暂停 订阅ID - 暂停订阅
• 恢复 订阅ID - 恢复订阅
• 删订 订阅ID - 删除订阅
• 直接发链接 - 智能识别并操作

🔧 其他：
• 重启 - 重启服务
• 帮助 - 显示此帮助

也可以点击底部菜单快速操作。"""

    def _about_text(self) -> str:
        """关于信息"""
        return "Easy-VDL - 视频下载与直播录制工具\n版本: v2.x\nGitHub: easy-vdl"

    async def _check_license(self) -> str:
        """查授权"""
        try:
            from routers.license import license_manager, LicenseStatus
            status = license_manager.status
            remaining = license_manager.remaining_days
            is_lifetime = license_manager.is_lifetime

            if status == LicenseStatus.VALID:
                if is_lifetime:
                    return "【授权状态】✅ LIFETIME 永久授权"
                elif remaining > 0:
                    return f"""【授权状态】✅ 有效
• 剩余天数: {remaining} 天"""
                else:
                    return "【授权状态】✅ 有效"
            elif status == LicenseStatus.EXPIRED:
                return "【授权状态】❌ 已过期"
            else:
                return "【授权状态】❌ 未授权"
        except Exception as e:
            return f"查询授权失败: {str(e)}"

    async def _check_tasks(self) -> str:
        """查任务"""
        try:
            from sql.database_postgresql import get_session
            from sql.models import Task, TaskStatus
            db = get_session()
            try:
                total = db.query(Task).count()
                downloading = db.query(Task).filter(Task.status == TaskStatus.DOWNLOADING.value).count()
                pending = db.query(Task).filter(Task.status == TaskStatus.PENDING.value).count()
                completed = db.query(Task).filter(Task.status == TaskStatus.COMPLETED.value).count()
                failed = db.query(Task).filter(Task.status == TaskStatus.ERROR.value).count()
                return f"""【下载任务】
• 总数: {total}
• 下载中: {downloading}
• 等待中: {pending}
• 已完成: {completed}
• 失败: {failed}"""
            finally:
                db.close()
        except Exception as e:
            return f"查询任务失败: {str(e)}"

    async def _check_status(self) -> str:
        """查系统状态（对标 TG Bot）"""
        try:
            import psutil
            from sql.database_postgresql import get_session
            from sql.models import Task, TaskStatus, Subscription, LiveSubscription

            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            db = get_session()
            try:
                downloading = db.query(Task).filter(Task.status == TaskStatus.DOWNLOADING.value).count()
                pending = db.query(Task).filter(Task.status == TaskStatus.PENDING.value).count()
                total_tasks = db.query(Task).count()
                subs = db.query(Subscription).filter(Subscription.status == "active").count()
                lives = db.query(LiveSubscription).count()
                recording = db.query(LiveSubscription).filter(LiveSubscription.is_recording == "true").count()
            finally:
                db.close()

            from routers.license import license_manager, LicenseStatus
            lic_status = "✅" if license_manager.status == LicenseStatus.VALID else "❌"
            lic_type = "LIFETIME" if license_manager.is_lifetime else f"{license_manager.remaining_days}天"

            return f"""【系统状态】
💻 系统资源:
• CPU: {cpu}%
• 内存: {mem.percent}% ({mem.used // (1024**3)}GB/{mem.total // (1024**3)}GB)
• 磁盘: {disk.percent}% ({disk.used // (1024**3)}GB/{disk.total // (1024**3)}GB)

📥 下载队列:
• 下载中: {downloading}
• 等待中: {pending}
• 总任务: {total_tasks}

📋 订阅:
• 视频订阅: {subs} 个
• 直播监控: {lives} 个 (录制中: {recording})

🔑 授权: {lic_status} {lic_type}"""
        except Exception as e:
            return f"查询状态失败: {str(e)}"

    async def _check_subscriptions(self) -> str:
        """查订阅"""
        try:
            from sql.database_postgresql import get_session
            from sql.models import Subscription
            db = get_session()
            try:
                subs = db.query(Subscription).all()
                if not subs:
                    return "【视频订阅】暂无订阅"
                lines = [f"【视频订阅】共 {len(subs)} 个\n"]
                for sub in subs[:10]:
                    status_icon = "✅" if sub.status == "active" else "⏸" if sub.status == "paused" else "❌"
                    name = sub.nickname or sub.url[:30]
                    lines.append(f"• {status_icon} {name}\n  ID: {sub.id[:8]}")
                if len(subs) > 10:
                    lines.append(f"... 还有 {len(subs) - 10} 个")
                lines.append("\n发送「暂停 ID」「恢复 ID」「删订 ID」管理订阅")
                return "\n".join(lines)
            finally:
                db.close()
        except Exception as e:
            return f"查询订阅失败: {str(e)}"

    async def _check_live_subscriptions(self) -> str:
        """查直播订阅"""
        try:
            from sql.database_postgresql import get_session
            from sql.models import LiveSubscription
            db = get_session()
            try:
                lives = db.query(LiveSubscription).all()
                if not lives:
                    return "【直播订阅】暂无订阅"
                lines = [f"【直播订阅】共 {len(lives)} 个\n"]
                for live in lives[:10]:
                    status_icon = "🔴" if live.is_recording else "⚪"
                    lines.append(f"• {status_icon} {live.anchor_name or live.room_url[:30]}")
                if len(lives) > 10:
                    lines.append(f"... 还有 {len(lives) - 10} 个")
                return "\n".join(lines)
            finally:
                db.close()
        except Exception as e:
            return f"查询直播订阅失败: {str(e)}"

    async def _check_failed_tasks(self) -> str:
        """查失败任务"""
        try:
            from sql.database_postgresql import get_session
            from sql.models import Task, TaskStatus
            db = get_session()
            try:
                failed_tasks = db.query(Task).filter(
                    Task.status == TaskStatus.ERROR.value
                ).order_by(Task.created_at.desc()).limit(10).all()
                if not failed_tasks:
                    return "【失败任务】暂无失败任务 🎉"
                lines = [f"【失败任务】共 {len(failed_tasks)} 个\n"]
                for t in failed_tasks:
                    name = t.title or t.url[:30] if hasattr(t, 'title') and t.title else (t.url[:30] if t.url else "未知")
                    error = t.error_message[:30] if t.error_message else "未知错误"
                    lines.append(f"• ❌ {name}\n  ID: {t.id[:8]} | {error}")
                lines.append("\n发送「重试 任务ID」重试，「删除 任务ID」删除")
                return "\n".join(lines)
            finally:
                db.close()
        except Exception as e:
            return f"查询失败任务失败: {str(e)}"

    async def _download_url(self, url: str) -> str:
        """下载单个视频"""
        try:
            from sql.database_postgresql import get_session
            from sql.models import Task, TaskStatus
            from routers.downloader import download_manager
            import uuid
            from datetime import datetime

            # 清洗 URL
            url = url.split("?")[0] if "?" in url and len(url) > 200 else url

            # 识别来源
            source = "others"
            if "douyin.com" in url or "tiktok.com" in url:
                source = "douyin"
            elif "bilibili.com" in url or "b23.tv" in url:
                source = "bilibili"
            elif "youtube.com" in url or "youtu.be" in url:
                source = "youtube"
            elif "xiaohongshu.com" in url or "xhslink.com" in url:
                source = "xiaohongshu"
            elif "kuaishou.com" in url:
                source = "kuaishou"

            task_id = str(uuid.uuid4())
            db = get_session()
            try:
                new_task = Task(
                    id=task_id,
                    url=url,
                    original_url=url,
                    source=source,
                    title=url,
                    status=TaskStatus.PENDING.value,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(new_task)
                db.commit()
                await download_manager.add_download_task(task_id)
                return f"✅ 已加入下载队列\n• 任务ID: {task_id[:8]}\n• 来源: {source}\n• URL: {url[:50]}..."
            finally:
                db.close()
        except Exception as e:
            return f"创建下载任务失败: {str(e)}"

    async def _add_subscription(self, url: str) -> str:
        """添加订阅（对标 TG Bot）"""
        try:
            from routers.license import license_manager
            if not await license_manager.is_active_for("wecom.subscribe"):
                return "🔒 订阅功能是高级功能，授权无效或已过期。"

            from routers.subscribe.subscription import add_subscription
            from sql.models import SubscriptionCreate, Platform

            # 判断平台
            platform = None
            if "douyin.com" in url or "v.douyin.com" in url:
                platform = Platform.douyin
            elif "bilibili.com" in url or "b23.tv" in url:
                platform = Platform.bilibili
            elif "youtube.com" in url or "youtu.be" in url:
                platform = Platform.youtube
            elif "xiaohongshu.com" in url or "xhslink.com" in url:
                platform = Platform.xiaohongshu
            elif "tiktok.com" in url:
                platform = Platform.tiktok
            elif "instagram.com" in url:
                platform = Platform.instagram
            elif "music.163.com" in url:
                platform = Platform.netease

            sub_create = SubscriptionCreate(
                url=url,
                platform=platform,
                auto_download=True,
            )
            result = await add_subscription(sub_create)
            if result:
                name = getattr(result, 'name', None) or getattr(result, 'url', url[:40])
                return f"✅ 订阅已添加\n• 名称: {name}\n• 平台: {platform or '自动识别'}"
            return "添加订阅失败"
        except Exception as e:
            return f"添加订阅失败: {str(e)}"

    async def _add_live_subscription(self, url: str) -> str:
        """添加直播录制订阅（对标 TG Bot）"""
        try:
            from routers.license import license_manager
            if not await license_manager.is_active_for("wecom.add_live_subscription"):
                return "🔒 直播订阅功能是高级功能，授权无效或已过期。"

            from live import adapters
            from sql.models import LiveSubscription
            from live.danmu import is_danmu_supported
            import uuid as _uuid
            import json as _json

            # 获取适配器
            adapter = adapters.get_adapter(url)
            if not adapter:
                if "douyin.com" in url or "iesdouyin.com" in url:
                    adapter = adapters.get_adapter_by_platform("douyin")
                elif "bilibili.com" in url or "b23.tv" in url:
                    adapter = adapters.get_adapter_by_platform("bilibili")
                elif "xiaohongshu.com" in url or "xhslink.com" in url:
                    adapter = adapters.get_adapter_by_platform("xhs")
                elif "huya.com" in url:
                    adapter = adapters.get_adapter_by_platform("huya")
                elif "kuaishou.com" in url:
                    adapter = adapters.get_adapter_by_platform("kuaishou")
                elif "douyu.com" in url:
                    adapter = adapters.get_adapter_by_platform("douyu")
                elif "twitch.tv" in url:
                    adapter = adapters.get_adapter_by_platform("twitch")

            if not adapter:
                return "❌ 无法识别的直播链接，目前支持：抖音、B站、快手、虎牙、小红书、斗鱼、Twitch"

            platform_name = adapter.platform_name
            info = await adapter.get_room_info(url)
            anchor_name = info.get("anchor_name", "未知主播")
            room_id = info.get("room_id")
            avatar_url = info.get("avatar_url")

            if not room_id and not anchor_name:
                return "❌ 无法获取直播间信息"

            db = get_session()
            try:
                existing = db.query(LiveSubscription).filter(
                    LiveSubscription.platform == platform_name,
                    LiveSubscription.room_url == url
                ).first()
                if existing:
                    return f"ℹ️ 该直播间已存在: {existing.anchor_name}"

                new_sub = LiveSubscription(
                    id=str(_uuid.uuid4()),
                    platform=platform_name,
                    room_url=url,
                    room_id=str(room_id) if room_id else "",
                    anchor_name=anchor_name,
                    avatar_url=avatar_url,
                    quality="原画",
                    auto_record="true",
                    check_interval=60,
                    notification_enabled="true",
                    extra_data=_json.dumps({"danmu_enabled": is_danmu_supported(platform_name)}),
                )
                db.add(new_sub)
                db.commit()
                db.refresh(new_sub)

                from live.scheduler import live_scheduler
                await live_scheduler.add_monitor(
                    subscription_id=new_sub.id,
                    room_url=new_sub.room_url,
                    platform=new_sub.platform,
                    check_interval=new_sub.check_interval or 60,
                )
                return f"✅ 直播录制已添加\n• 主播: {anchor_name}\n• 平台: {platform_name}"
            finally:
                db.close()
        except Exception as e:
            return f"添加直播录制失败: {str(e)}"

    async def _handle_url(self, url: str) -> str:
        """智能 URL 识别"""
        url_lower = url.lower()
        # 直播 URL
        if any(x in url_lower for x in ["live.douyin", "live.bilibili", "huya.com", "kuaishou.com/live"]):
            return await self._add_live_subscription(url)
        # 订阅 URL（用户主页/合集）
        if any(x in url_lower for x in ["/user/", "/collection/", "/playlist/", "channel/", "/space/"]):
            return await self._add_subscription(url)
        # 默认当作单个视频下载
        return await self._download_url(url)

    async def _restart_service(self) -> str:
        """重启服务"""
        try:
            import os
            asyncio.create_task(self._delayed_restart())
            return "🔄 服务正在重启，请稍后..."
        except Exception as e:
            return f"重启失败: {str(e)}"

    async def _delayed_restart(self):
        """延迟重启"""
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    async def _retry_task(self, task_id: str) -> str:
        """重试失败任务"""
        try:
            from sql.database_postgresql import get_session
            from sql.models import Task, TaskStatus
            from routers.downloader import download_manager
            db = get_session()
            try:
                task = db.query(Task).filter(Task.id.startswith(task_id)).first()
                if not task:
                    return f"❌ 未找到任务: {task_id}"
                task.status = TaskStatus.PENDING.value
                task.error_message = None
                task.updated_at = __import__('datetime').datetime.now()
                db.commit()
                await download_manager.add_download_task(task.id)
                return f"✅ 任务已重试\n• ID: {task.id[:8]}\n• URL: {task.url[:50]}..."
            finally:
                db.close()
        except Exception as e:
            return f"重试失败: {str(e)}"

    async def _delete_task(self, task_id: str) -> str:
        """删除任务"""
        try:
            from sql.database_postgresql import get_session
            from sql.models import Task
            db = get_session()
            try:
                task = db.query(Task).filter(Task.id.startswith(task_id)).first()
                if not task:
                    return f"❌ 未找到任务: {task_id}"
                db.delete(task)
                db.commit()
                return f"✅ 任务已删除\n• ID: {task.id[:8]}"
            finally:
                db.close()
        except Exception as e:
            return f"删除失败: {str(e)}"

    async def _pause_subscription(self, sub_id: str) -> str:
        """暂停订阅"""
        try:
            from sql.database_postgresql import get_session
            from sql.models import Subscription
            db = get_session()
            try:
                sub = db.query(Subscription).filter(Subscription.id.startswith(sub_id)).first()
                if not sub:
                    return f"❌ 未找到订阅: {sub_id}"
                sub.status = "paused"
                db.commit()
                return f"✅ 订阅已暂停\n• 名称: {sub.nickname or sub.url[:30]}"
            finally:
                db.close()
        except Exception as e:
            return f"暂停失败: {str(e)}"

    async def _resume_subscription(self, sub_id: str) -> str:
        """恢复订阅"""
        try:
            from sql.database_postgresql import get_session
            from sql.models import Subscription
            db = get_session()
            try:
                sub = db.query(Subscription).filter(Subscription.id.startswith(sub_id)).first()
                if not sub:
                    return f"❌ 未找到订阅: {sub_id}"
                sub.status = "active"
                db.commit()
                return f"✅ 订阅已恢复\n• 名称: {sub.nickname or sub.url[:30]}"
            finally:
                db.close()
        except Exception as e:
            return f"恢复失败: {str(e)}"

    async def _delete_subscription(self, sub_id: str) -> str:
        """删除订阅"""
        try:
            from sql.database_postgresql import get_session
            from sql.models import Subscription
            db = get_session()
            try:
                sub = db.query(Subscription).filter(Subscription.id.startswith(sub_id)).first()
                if not sub:
                    return f"❌ 未找到订阅: {sub_id}"
                db.delete(sub)
                db.commit()
                return f"✅ 订阅已删除\n• 名称: {sub.nickname or sub.url[:30]}"
            finally:
                db.close()
        except Exception as e:
            return f"删除失败: {str(e)}"

    async def send_notification(self, user_id: str, content: str, msg_type: str = "text") -> bool:
        """发送通知消息"""
        logger.info(f"企业微信发送消息: to={user_id}, content={content[:80]}...")
        if not self.client:
            logger.warning("企业微信Bot未初始化，无法发送通知")
            return False
        try:
            result = await self.client.send_message(user_id, content, msg_type)
            logger.info(f"企业微信发送结果: {result}")
            if result.get("errcode") == 0:
                logger.info(f"企业微信通知发送成功")
                return True
            else:
                logger.error(f"企业微信通知发送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"企业微信通知发送异常: {e}", exc_info=True)
            return False


# 全局单例
wecom_bot = WecomBotService()


# ========== 回调路由 ==========

@router.api_route("/callback", methods=["GET", "POST"])
async def wecom_callback(request: Request):
    """企业微信回调接口（GET验签 + POST收消息）"""
    return await wecom_bot.handle_callback(request)


@router.post("/test")
async def test_wecom_bot(config: dict):
    """测试企业微信Bot连接"""
    try:
        client = WecomApiClient(
            corp_id=config.get("corp_id", ""),
            agent_id=config.get("agent_id", ""),
            secret=config.get("secret", ""),
        )
        success, message = await client.test_connection()
        return {"success": success, "message": message}
    except Exception as e:
        return {"success": False, "message": f"测试失败: {str(e)}"}
