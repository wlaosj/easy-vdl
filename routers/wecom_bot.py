"""
企业微信应用Bot服务
处理回调（验签+收消息）、交互指令、菜单管理
业务逻辑调用 services/bot_commands.py 共享层
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

from fastapi import APIRouter, Request, Response
from sqlalchemy.orm import Session

from sql.database_postgresql import get_session
from services.wecom_api import WecomApiClient
from services import bot_commands as cmd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wecom", tags=["企业微信Bot"])

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
        try:
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
        self.enabled = False
        self.client = None
        logger.info("企业微信Bot已停止")

    async def reload(self):
        await self.stop()
        await self.start()

    async def _setup_menu(self):
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

    # ==================== 加解密 ====================

    def _decrypt_echostr(self, echostr: str) -> Optional[str]:
        if not self.callback_aes_key:
            return echostr
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
        if not self.callback_aes_key or not self.callback_token:
            return None
        try:
            params = sorted([self.callback_token, timestamp, nonce, encrypt_content])
            hash_str = hashlib.sha1("".join(params).encode("utf-8")).hexdigest()
            if hash_str != msg_signature:
                logger.warning("企业微信消息签名验证失败")
                return None
            aes_key = base64.b64decode(self.callback_aes_key + "=")
            iv = aes_key[:16]
            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            plain = decryptor.update(base64.b64decode(encrypt_content)) + decryptor.finalize()
            pad_len = plain[-1]
            plain = plain[:-pad_len]
            msg_len = struct.unpack(">I", plain[16:20])[0]
            return plain[20:20 + msg_len].decode("utf-8")
        except Exception as e:
            logger.error(f"解密企业微信消息失败: {e}", exc_info=True)
            return None

    def _verify_signature(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> Optional[str]:
        if not self.callback_token:
            return None
        params = sorted([self.callback_token, timestamp, nonce, echostr])
        hash_str = hashlib.sha1("".join(params).encode("utf-8")).hexdigest()
        if hash_str == msg_signature:
            return self._decrypt_echostr(echostr)
        logger.warning(f"企业微信回调签名验证失败")
        return None

    def _parse_xml_message(self, xml_data: str) -> Optional[dict]:
        try:
            root = ET.fromstring(xml_data)
            return {child.tag: child.text for child in root}
        except Exception as e:
            logger.error(f"解析企业微信XML失败: {e}")
            return None

    # ==================== 回调处理 ====================

    async def handle_callback(self, request: Request) -> Response:
        if request.method == "GET":
            params = dict(request.query_params)
            echostr = self._verify_signature(
                msg_signature=params.get("msg_signature", ""),
                timestamp=params.get("timestamp", ""),
                nonce=params.get("nonce", ""),
                echostr=params.get("echostr", ""),
            )
            if echostr:
                return Response(content=echostr, media_type="text/plain")
            return Response(content="verification failed", status_code=403)

        try:
            body = await request.body()
            xml_data = body.decode("utf-8")

            if "<Encrypt>" in xml_data:
                root = ET.fromstring(xml_data)
                encrypt_node = root.find("Encrypt")
                if encrypt_node is not None and encrypt_node.text:
                    params = dict(request.query_params)
                    decrypted = self._decrypt_message(
                        encrypt_node.text,
                        params.get("msg_signature", ""),
                        params.get("timestamp", ""),
                        params.get("nonce", ""),
                    )
                    if decrypted:
                        xml_data = decrypted
                    else:
                        return Response(content="success", media_type="text/plain")

            msg = self._parse_xml_message(xml_data)
            if not msg:
                return Response(content="success", media_type="text/plain")

            msg_type = msg.get("MsgType", "")
            from_user = msg.get("FromUserName", "")

            if msg_type == "text":
                content = msg.get("Content", "").strip()
                reply = await self._process_text_command(content, from_user)
            elif msg_type == "event":
                event_key = msg.get("EventKey", "")
                reply = await self._process_text_command(event_key, from_user)
            else:
                reply = None

            if reply:
                asyncio.create_task(self.send_notification(from_user, reply))

            return Response(content="success", media_type="text/plain")
        except Exception as e:
            logger.error(f"处理企业微信回调异常: {e}", exc_info=True)
            return Response(content="success", media_type="text/plain")

    # ==================== 命令处理（调用共享层） ====================

    async def _process_text_command(self, content: str, from_user: str) -> str:
        cl = content.lower().strip()

        if cl in ("帮助", "help"):
            return self._help_text()
        elif cl in ("关于", "about"):
            return "Easy-VDL - 视频下载与直播录制工具"
        elif cl in ("重启", "restart"):
            asyncio.create_task(self._delayed_restart())
            return "🔄 服务正在重启，请稍后..."
        elif cl in ("查授权", "授权"):
            return self._fmt_license(await cmd.check_license())
        elif cl in ("查任务", "任务"):
            return self._fmt_tasks(await cmd.check_tasks())
        elif cl in ("查状态", "状态", "status"):
            return self._fmt_status(await cmd.check_status())
        elif cl in ("查订阅", "订阅"):
            return self._fmt_subscriptions(await cmd.check_subscriptions())
        elif cl in ("查直播", "直播") and not cl.startswith("直播 "):
            return self._fmt_live(await cmd.check_live_subscriptions())
        elif cl in ("失败任务", "失败"):
            return self._fmt_failed(await cmd.check_failed_tasks())
        elif cl.startswith("重试 "):
            tid = content.split(" ", 1)[1].strip()
            return self._fmt_op(await cmd.retry_task(tid), "任务已重试")
        elif cl.startswith("删除 "):
            tid = content.split(" ", 1)[1].strip()
            return self._fmt_op(await cmd.delete_task(tid), "任务已删除")
        elif cl.startswith("暂停 "):
            sid = content.split(" ", 1)[1].strip()
            return self._fmt_op(await cmd.pause_subscription(sid), "订阅已暂停")
        elif cl.startswith("恢复 "):
            sid = content.split(" ", 1)[1].strip()
            return self._fmt_op(await cmd.resume_subscription(sid), "订阅已恢复")
        elif cl.startswith("删订 "):
            sid = content.split(" ", 1)[1].strip()
            return self._fmt_op(await cmd.delete_subscription(sid), "订阅已删除")
        elif cl.startswith("停录 "):
            sid = content.split(" ", 1)[1].strip()
            return self._fmt_op(await cmd.pause_live_subscription(sid), "直播录制已暂停")
        elif cl.startswith("开录 "):
            sid = content.split(" ", 1)[1].strip()
            return self._fmt_op(await cmd.resume_live_subscription(sid), "直播录制已开启")
        elif cl.startswith("删直 "):
            sid = content.split(" ", 1)[1].strip()
            return self._fmt_op(await cmd.delete_live_subscription(sid), "直播订阅已删除")
        elif cl.startswith("下载 ") or cl.startswith("dl "):
            url = cmd.extract_url(content)
            return self._fmt_op(await cmd.download_url(url), "已加入下载队列") if url else "格式: 下载 URL"
        elif cl.startswith("订阅 "):
            url = cmd.extract_url(content)
            return self._fmt_op(await cmd.add_subscription(url), "订阅已添加") if url else "格式: 订阅 URL"
        elif cl.startswith("直播 "):
            url = cmd.extract_url(content)
            return self._fmt_op(await cmd.add_live_subscription(url), "直播录制已添加") if url else "格式: 直播 URL"
        elif "http://" in content or "https://" in content:
            url = cmd.extract_url(content)
            return self._fmt_op(await cmd.handle_url(url, content), "已处理") if url else "未识别到有效链接"
        else:
            return f"收到: {content}\n\n发送「帮助」查看可用命令"

    # ==================== 格式化（企业微信纯文本） ====================

    def _fmt_license(self, r: dict) -> str:
        if not r.get("success"):
            return f"查询授权失败: {r.get('error')}"
        if r["status"] == "valid":
            if r.get("type") == "lifetime":
                return "【授权状态】✅ LIFETIME 永久授权"
            return f"【授权状态】✅ 有效\n• 剩余: {r.get('remaining_days', '?')} 天"
        return "【授权状态】❌ " + ("已过期" if r["status"] == "expired" else "未授权")

    def _fmt_tasks(self, r: dict) -> str:
        if not r.get("success"):
            return f"查询任务失败: {r.get('error')}"
        return f"【下载任务】\n• 总数: {r['total']}\n• 下载中: {r['downloading']}\n• 等待中: {r['pending']}\n• 已完成: {r['completed']}\n• 失败: {r['failed']}"

    def _fmt_status(self, r: dict) -> str:
        if not r.get("success"):
            return f"查询状态失败: {r.get('error')}"

        # 授权
        lic = "✅ LIFETIME" if r.get("license_lifetime") else (
            f"✅ {r.get('license_remaining', '?')}天" if r.get("license_valid") else "❌ 未授权/已过期")

        # 内存
        mem_used = r.get("mem_used_gb", 0)
        mem_total = r.get("mem_total_gb", 0)
        mem_pct = r.get("mem_percent", 0)
        mem_str = f"{mem_used}/{mem_total} GB" if mem_total else f"{mem_pct}%"

        # 磁盘 + 进度条
        du = r.get("disk_used_gb", 0)
        dt = r.get("disk_total_gb", 0)
        dp = r.get("disk_percent", 0)
        bar_len = 12
        filled = int(dp / 100 * bar_len) if dt else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        disk_str = f"{du:.1f}/{dt:.1f} GB ({dp:.0f}%) [{bar}]" if dt else f"{dp:.0f}%"

        lines = [f"【系统状态】"]

        # 版本信息
        app_ver = r.get("app_version", "")
        core_ver = r.get("core_version", "")
        if app_ver or core_ver:
            ver_str = app_ver if app_ver else ""
            if core_ver:
                ver_str += f" 核心: v{core_ver}" if ver_str else f"核心: v{core_ver}"
            if ver_str:
                lines.append(f"📦 版本: {ver_str}")

        # 系统资源
        lines.append(f"💻 CPU: {r['cpu']}% | 内存: {mem_str}")
        lines.append(f"💾 磁盘: {disk_str}")

        # 数据统计
        stats = (
            f"📥 下载中: {r['downloading']} | 等待: {r['pending']}"
            f" | 完成: {r.get('completed', 0)} | 失败: {r.get('failed', 0)}"
        )
        lines.append(stats)

        sub_line = (
            f"📋 订阅: {r.get('total_subs', 0)} 个"
            f" (活跃: {r.get('active_subs', 0)}"
            f" | 暂停: {r.get('paused_subs', 0)}"
        )
        if r.get("error_subs"):
            sub_line += f" | ⚠️ 异常: {r['error_subs']}"
        sub_line += f") 视频: {r.get('sub_videos', 0)} 条"
        lines.append(sub_line)

        live_line = (
            f"📺 直播: {r.get('total_lives', 0)} 个"
            f" (录制中: {r['recording']}"
            f" | 直播中: {r.get('live_count', 0)}"
        )
        if r.get("today_records"):
            live_line += f" | 今日录制: {r['today_records']}"
        live_line += ")"
        lines.append(live_line)

        # 存储
        sub_storage = r.get("sub_storage_gb", 0)
        live_storage = r.get("live_storage_gb", 0.0)
        if sub_storage:
            lines.append(f"📁 订阅存储: {sub_storage} GB")
        if live_storage:
            lines.append(f"📹 直播录制: {live_storage} GB")

        # 正在下载
        active_dls = r.get("active_downloads", [])
        if active_dls:
            lines.append("")
            lines.append(f"⬇️ 正在下载 ({len(active_dls)}):")
            for i, dl in enumerate(active_dls[:5]):
                progress = dl.get("progress", 0) or 0
                pbar_len = 10
                pbar_filled = int(progress / 100 * pbar_len)
                pbar = "█" * pbar_filled + "░" * (pbar_len - pbar_filled)
                title = dl.get("title", "未知")[:20]
                lines.append(f"  {i+1}. {title}")
                lines.append(f"     [{pbar}] {progress:.0f}%")

        lines.append(f"🔑 授权: {lic}")

        return "\n".join(lines)

    def _fmt_subscriptions(self, r: dict) -> str:
        if not r.get("success"):
            return f"查询订阅失败: {r.get('error')}"
        if not r["items"]:
            return "【视频订阅】暂无订阅"
        lines = [f"【视频订阅】共 {r['total']} 个\n"]
        for s in r["items"]:
            icon = "✅" if s["status"] == "active" else "⏸" if s["status"] == "paused" else "❌"
            lines.append(f"• {icon} {s['name']}\n  ID: {s['id']}")
        lines.append("\n发送「暂停 ID」「恢复 ID」「删订 ID」管理")
        return "\n".join(lines)

    def _fmt_live(self, r: dict) -> str:
        if not r.get("success"):
            return f"查询直播失败: {r.get('error')}"
        if not r["items"]:
            return "【直播订阅】暂无订阅"
        lines = [f"【直播订阅】共 {r['total']} 个\n"]
        for l in r["items"]:
            icon = "🔴" if l["is_recording"] else "⚪"
            auto = "📹开" if l.get("auto_record") == "true" else "📹关"
            lines.append(f"• {icon} {l['anchor_name']} {auto}\n  ID: {l['id']}")
        lines.append("\n发送「停录 ID」「开录 ID」「删直 ID」管理")
        return "\n".join(lines)

    def _fmt_failed(self, r: dict) -> str:
        if not r.get("success"):
            return f"查询失败任务失败: {r.get('error')}"
        if not r["items"]:
            return "【失败任务】暂无失败任务 🎉"
        lines = [f"【失败任务】共 {r['total']} 个\n"]
        for t in r["items"]:
            lines.append(f"• ❌ {t['title']}\n  ID: {t['id']} | {t['error']}")
        lines.append("\n发送「重试 ID」「删除 ID」操作")
        return "\n".join(lines)

    def _fmt_op(self, r: dict, action: str) -> str:
        if r.get("success"):
            name = r.get("name") or r.get("anchor_name") or r.get("task_id") or ""
            return f"✅ {action}\n• {name}" if name else f"✅ {action}"
        return f"❌ {r.get('error', '操作失败')}"

    def _help_text(self) -> str:
        return """【Easy-VDL 帮助】

📊 查询: 查状态 | 查任务 | 查授权 | 查订阅 | 查直播 | 失败任务
🎬 操作: 下载 URL | 订阅 URL | 直播 URL | 直接发链接
📋 订阅管理: 暂停 ID | 恢复 ID | 删订 ID
📺 直播管理: 停录 ID | 开录 ID | 删直 ID
⚡ 其他: 重启 | 帮助"""

    async def _delayed_restart(self):
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # ==================== 消息发送 ====================

    async def send_notification(self, user_id: str, content: str, msg_type: str = "text") -> bool:
        if not self.client:
            return False
        try:
            result = await self.client.send_message(user_id, content, msg_type)
            if result.get("errcode") == 0:
                return True
            else:
                logger.error(f"企业微信通知发送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"企业微信通知发送异常: {e}")
            return False


wecom_bot = WecomBotService()


@router.api_route("/callback", methods=["GET", "POST"])
async def wecom_callback(request: Request):
    return await wecom_bot.handle_callback(request)


@router.post("/test")
async def test_wecom_bot(config: dict):
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
