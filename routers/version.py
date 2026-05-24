from fastapi import APIRouter, HTTPException, Query, Depends
import logging
import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx
import asyncio
from routers.websocket import broadcast_message
from routers.license import license_manager
from routers.auth import get_current_user
from sql.database_postgresql import db
from sql.models import User
from routers.notifications import NotificationService

# 将旧的版本检查路由改造为“社区公告公开接口”
router = APIRouter(prefix="/api/community/public", tags=["community-public"])
# 本地直达路由，避免被前置代理转发到社区服务器
local_router = APIRouter(prefix="/api", tags=["announcements-local"])
logger = logging.getLogger(__name__)

# 禁用 httpx 的详细日志，避免暴露服务器地址
logging.getLogger("httpx").setLevel(logging.WARNING)

ANNOUNCEMENTS_PATH = os.path.join("data", "announcements.json")
# 使用与授权验证相同的 FRP 公网入口
SHEQU_PUBLIC_BASE = "https://easy-vdl.921217.xyz"

# SSE连接管理
_sse_connection_task = None
_sse_connected = False

def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None

def _load_announcements() -> List[Dict[str, Any]]:
    if not os.path.exists(ANNOUNCEMENTS_PATH):
        return []
    try:
        with open(ANNOUNCEMENTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            items = data.get("items")
            if isinstance(items, list):
                return items
            # 兼容纯数组文件
            if isinstance(data, list):
                return data
            return []
    except Exception as e:
        logger.error(f"读取公告文件失败: {e}")
        return []

def _filter_and_sort(items: List[Dict[str, Any]], severity: Optional[str]) -> List[Dict[str, Any]]:
    now = datetime.utcnow()
    filtered: List[Dict[str, Any]] = []
    for it in items:
        status_val = (it.get("status") or "published").lower()
        if status_val not in ("published", "active"):
            continue
        start_at = _parse_time(it.get("start_at"))
        end_at = _parse_time(it.get("end_at"))
        if start_at and now < start_at:
            continue
        if end_at and now > end_at:
            continue
        if severity and (it.get("severity") or "info") != severity:
            continue
        filtered.append(it)

    def sort_key(it: Dict[str, Any]):
        sticky = 1 if it.get("sticky") else 0
        priority = it.get("priority") or 0
        updated_at = _parse_time(it.get("updated_at")) or _parse_time(it.get("start_at")) or datetime.min
        return (-sticky, -int(priority), updated_at)

    filtered.sort(key=sort_key, reverse=False)
    # sort_key 已按需要的倒序构造（负号将高优先级置前；时间使用正序+reverse=False等价于倒序），这里保持 reverse=False
    return filtered


@router.get("/feedback-progress")
async def get_feedback_progress(
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = Query(None, description="accepted|processing|resolved_next_release|resolved")
):
    """获取开发进度反馈列表（仅远端社区服务）。"""
    try:
        remote_url = f"{SHEQU_PUBLIC_BASE}/public/feedback-progress"
        params = {"limit": limit}
        if status:
            params["status"] = status

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(remote_url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    return data
                logger.warning("社区开发进度返回结构异常")
            else:
                logger.warning(f"社区开发进度拉取失败: HTTP {resp.status_code}")
    except Exception as e:
        logger.warning("社区开发进度拉取异常")

    raise HTTPException(status_code=502, detail="开发进度服务不可用")

@router.get("/announcements")
async def get_announcements(
    limit: int = Query(5, ge=1, le=50),
    severity: Optional[str] = Query(None, description="info|warn|error|success")
):
    """获取公告列表（公开接口）。数据来源：data/announcements.json。

    返回字段透传：id、title、content、severity、sticky、priority、start_at、end_at、updated_at 等。
    """
    # 仅从社区服务器获取，失败直接返回错误
    try:
        remote_url = f"{SHEQU_PUBLIC_BASE}/public/announcements"
        params = {"limit": limit}
        if severity:
            params["severity"] = severity
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(remote_url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                # 透传远端结构（items/total/timestamp）
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    return data
            else:
                logger.warning(f"社区公告拉取失败: HTTP {resp.status_code}")
    except Exception as e:
        logger.warning(f"社区公告拉取异常")

    # 不再回退本地，直接返回错误
    raise HTTPException(status_code=502, detail="社区公告服务不可用")

@router.get("/announcements/latest")
async def get_latest_announcement():
    """获取最新一条公告（公开接口）。"""
    try:
        items = _filter_and_sort(_load_announcements(), None)
        latest = items[0] if items else None
        return {"item": latest, "timestamp": datetime.utcnow().isoformat() + "Z"}
    except Exception as e:
        logger.error(f"获取最新公告失败: {e}")
        raise HTTPException(status_code=500, detail="获取最新公告失败")

@router.get("/announcements/state")
async def get_announcement_state():
    """返回公告未读状态（持久化于数据库global_config.announcement_state）。"""
    try:
        rows = await db.execute_query(
            "SELECT value FROM global_config WHERE key = :k",
            {"k": "announcement_state"}
        )
        state: Dict[str, Any] = {}
        if rows:
            try:
                state = json.loads(rows[0].get("value") or "{}")
            except Exception:
                state = {}
        latest_version = int(state.get("latest_version") or 0)
        ack_version = int(state.get("ack_version") or 0)
        pending = latest_version > ack_version
        return {
            "pending": pending,
            "latest_version": latest_version,
            "ack_version": ack_version,
            "top_severity": state.get("top_severity") or "info",
            "count": int(state.get("count") or 0),
            "pending_since": state.get("pending_since"),
            "updated_at": state.get("updated_at"),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"获取公告状态失败: {e}")
        raise HTTPException(status_code=500, detail="获取公告状态失败")

@router.post("/announcements/ack")
async def ack_announcements(current_user: User = Depends(get_current_user)):
    """用户查看公告后，确认已读：将ack_version同步为latest_version。"""
    try:
        rows = await db.execute_query(
            "SELECT value FROM global_config WHERE key = :k",
            {"k": "announcement_state"}
        )
        cur: Dict[str, Any] = {}
        if rows:
            try:
                cur = json.loads(rows[0].get("value") or "{}")
            except Exception:
                cur = {}
        latest_version = int(cur.get("latest_version") or 0)
        cur.update({
            "ack_version": latest_version,
            "updated_at": datetime.utcnow().isoformat() + "Z"
        })
        payload = json.dumps(cur, ensure_ascii=False)
        await db.execute_update(
            """
            INSERT INTO global_config(key, value, updated_at)
            VALUES(:k, :v, NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = NOW()
            """,
            {"k": "announcement_state", "v": payload}
        )

        # 向在线前端广播状态已清除（可选）
        await broadcast_message("announcements", {
            "type": "announcement_ack",
            "version": latest_version,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
        return {"ok": True}
    except Exception as e:
        logger.error(f"确认公告已读失败: {e}")
        raise HTTPException(status_code=500, detail="确认公告已读失败")

# =============== 本地直达端点（不经社区代理） ===============
@local_router.get("/announcements/state")
async def get_announcement_state_local():
    return await get_announcement_state()

@local_router.post("/announcements/ack")
async def ack_announcements_local():
    return await ack_announcements()

async def _connect_to_community_sse():
    """连接到社区服务器的SSE流"""
    global _sse_connected
    
    sse_url = f"{SHEQU_PUBLIC_BASE}/public/announcements/stream"
    reconnect_delay = 5  # 初始重连间隔(秒)，指数退避上限60秒
    
    while True:
        # 被挤下线状态：暂停SSE重连，避免重新注册会话触发二次抢占循环
        # 仅当用户手动"刷新授权"重置 kicked_off 后才恢复连接
        if getattr(license_manager, "kicked_off", False):
            await asyncio.sleep(10)
            continue
        
        try:
            # 避免在日志中暴露远端地址
            logger.debug("尝试连接社区服务器SSE")
            _sse_connected = False
            
            # 使用 license_manager 获取身份信息
            headers = {}
            try:
                if license_manager.license_key:
                    # 🛡️ 公网安全增强：发送哈希后的身份指纹，避免泄露原始密钥
                    import hashlib
                    key_hash = hashlib.md5(str(license_manager.license_key).encode()).hexdigest()
                    headers["x-license-key"] = key_hash
                # 尝试获取容器ID
                cid = license_manager.get_real_container_id()
                if cid and cid != "unknown":
                    headers["x-container-id"] = cid
                
                # 发送本地版本号，用于版本分布统计
                try:
                    version_file_path = os.path.join("data", "build-version.json")
                    if os.path.exists(version_file_path):
                        with open(version_file_path, "r", encoding="utf-8") as f:
                            version_data = json.load(f)
                            headers["x-app-version"] = version_data.get("version", "unknown")
                            build_time = version_data.get("build_time", "")
                            if build_time:
                                headers["x-build-time"] = build_time
                    else:
                        headers["x-app-version"] = "dev"
                except Exception:
                    headers["x-app-version"] = "unknown"
            except Exception:
                pass

            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=35.0, write=30.0, pool=30.0)) as client:
                async with client.stream("GET", sse_url, headers=headers) as response:
                    if response.status_code == 200:
                        _sse_connected = True
                        reconnect_delay = 5  # 连接成功，重置退避间隔
                        logger.info("社区公告SSE连接成功")
                        # 首次SSE连接成功后，再做一次离线补偿检查，确保离线期间发布的公告被识别
                        try:
                            await _offline_compensation_check()
                        except Exception as e:
                            logger.debug(f"SSE连接后补偿检查异常: {e}")
                        
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                try:
                                    data = json.loads(line[6:])  # 去掉 "data: " 前缀
                                    
                                    if data.get("type") == "announcement_updated":
                                        # 将公告未读状态落库到 global_config.announcement_state
                                        try:
                                            latest_version = int(data.get("version") or 0)
                                            # 读取当前状态
                                            rows = await db.execute_query(
                                                "SELECT value FROM global_config WHERE key = :k",
                                                {"k": "announcement_state"}
                                            )
                                            cur: Dict[str, Any] = {}
                                            if rows:
                                                try:
                                                    cur = json.loads(rows[0].get("value") or "{}")
                                                except Exception:
                                                    cur = {}
                                            ack_version = int(cur.get("ack_version") or 0)
                                            pending_since = cur.get("pending_since")

                                            # 保留已通知版本号，避免重复发送
                                            notified_version = cur.get("notified_version", 0)
                                            state = {
                                                "latest_version": latest_version,
                                                "ack_version": ack_version,
                                                "notified_version": notified_version,  # 保留已通知版本
                                                "top_severity": data.get("top_severity") or cur.get("top_severity") or "info",
                                                "count": int(data.get("count") or cur.get("count") or 0),
                                                "pending_since": pending_since if latest_version <= ack_version else (datetime.utcnow().isoformat() + "Z"),
                                                "updated_at": datetime.utcnow().isoformat() + "Z",
                                            }
                                            payload = json.dumps(state, ensure_ascii=False)
                                            await db.execute_update(
                                                """
                                                INSERT INTO global_config(key, value, updated_at)
                                                VALUES(:k, :v, NOW())
                                                ON CONFLICT (key) DO UPDATE
                                                SET value = EXCLUDED.value, updated_at = NOW()
                                                """,
                                                {"k": "announcement_state", "v": payload}
                                            )
                                        except Exception as e:
                                            logger.warning(f"公告状态落库失败: {e}")

                                        # 通过WebSocket广播给在线前端（实时提示）
                                        await broadcast_message("announcements", {
                                            "type": "announcement_updated",
                                            "version": latest_version,
                                            "top_severity": data.get("top_severity"),
                                            "count": data.get("count"),
                                            "connected_clients": data.get("connected_clients"),
                                            "timestamp": datetime.utcnow().isoformat() + "Z"
                                        })
                                        logger.info(f"公告更新已广播并持久化: v={latest_version}")

                                        # 同步推送到用户配置的平台（微信机器人、Server酱³ 等）
                                        try:
                                            asyncio.create_task(_notify_announcement_update(
                                                latest_version,
                                                data.get("top_severity"),
                                                int(data.get("count") or 0)
                                            ))
                                        except Exception as e:
                                            logger.debug(f"同步平台通知任务创建失败: {e}")
                                    
                                    elif data.get("type") == "connected":
                                        logger.debug(f"SSE连接确认: 客户端ID={data.get('client_id')}, 连接数={data.get('connected_clients')}")
                                    
                                    elif data.get("type") == "ping":
                                        # 心跳，保持连接活跃
                                        pass
                                    
                                    elif data.get("type") == "refresh":
                                        # 接收到强制刷新指令（通常因服务端状态变更，如被封禁或解封）
                                        reason = data.get("reason", "服务端要求同步状态")
                                        logger.info(f"SSE收到刷新指令: {reason}")
                                        
                                        # 立即清除缓存
                                        license_manager.clear_cache()
                                        
                                        # 如果是名额已满被挤下线，标记 kicked_off 以拦截自动重新验证网络请求，防止多实例套娃抢占
                                        if "名额已满" in reason or "挤下线" in reason:
                                            license_manager.kicked_off = True
                                            logger.warning("由于授权槽位已满被挤下线，已置为无效授权，且不再发起自动重新验证抢占。")
                                            # 主动断开当前长连接，让其重新心跳握手，重新在服务端登记在线状态
                                            _sse_connected = False
                                            break
                                        else:
                                            # 正常刷新，触发验证
                                            # 验证结果会更新 license_manager.status
                                            await license_manager.verify()
                                        
                                        # 可选：如果验证失败（被封禁），可以广播消息给前端
                                        if license_manager.status != "valid":
                                            await broadcast_message("announcements", {
                                                "type": "license_status_changed", 
                                                "status": license_manager.status,
                                                "error": license_manager.last_error,
                                                "timestamp": datetime.utcnow().isoformat() + "Z"
                                            })
                                        
                                except json.JSONDecodeError as e:
                                    logger.warning(f"SSE数据解析失败: {line}, 错误: {e}")
                    else:
                        logger.warning(f"SSE连接失败: HTTP {response.status_code}")
                        
        except httpx.ReadTimeout:
            logger.warning("SSE读超时(35s无数据)，判定为半开连接，主动断开重连")
            _sse_connected = False
        except Exception as e:
            logger.error("SSE连接异常")
            _sse_connected = False
        
        # 连接断开，指数退避重连
        logger.info(f"SSE连接断开，{reconnect_delay}秒后重连...")
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 60)  # 5→10→20→40→60→60...

async def start_sse_connection():
    """启动SSE连接任务"""
    global _sse_connection_task
    
    if _sse_connection_task is None or _sse_connection_task.done():
        _sse_connection_task = asyncio.create_task(_connect_to_community_sse())
        logger.debug("SSE连接任务已启动")
        # 补偿检查仅在SSE连接成功后触发，避免SSE未就绪时误判

async def _offline_compensation_check():
    """离线期间补偿检查：比较社区版本与本地ack_version，必要时置pending并广播一次。"""
    try:
        remote_url = f"{SHEQU_PUBLIC_BASE}/public/announcements/version"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(remote_url)
            if resp.status_code != 200:
                logger.warning(f"离线补偿检查失败：HTTP {resp.status_code}")
                raise RuntimeError(f"Remote status {resp.status_code}")
            data = resp.json() or {}
            latest = int(data.get("version") or 0)
        logger.debug(f"离线补偿检查: remote_latest={latest}")
        rows = await db.execute_query(
            "SELECT value FROM global_config WHERE key = :k",
            {"k": "announcement_state"}
        )
        cur: Dict[str, Any] = {}
        if rows:
            try:
                cur = json.loads(rows[0].get("value") or "{}")
            except Exception:
                cur = {}
        ack_version = int(cur.get("ack_version") or 0)
        logger.debug(f"离线补偿检查: ack_version={ack_version}")
        if latest > ack_version:
            # 更新latest_version并置pending，不降低ack_version
            # 保留已通知版本号，避免重复发送
            notified_version = cur.get("notified_version", 0)
            cur.update({
                "latest_version": latest,
                "notified_version": notified_version,  # 保留已通知版本
                "top_severity": data.get("top_severity") or cur.get("top_severity") or "info",
                "count": int(data.get("count") or cur.get("count") or 0),
                "pending_since": datetime.utcnow().isoformat() + "Z",
                "updated_at": datetime.utcnow().isoformat() + "Z",
            })
            await db.execute_update(
                """
                INSERT INTO global_config(key, value, updated_at)
                VALUES(:k, :v, NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
                """,
                {"k": "announcement_state", "v": json.dumps(cur, ensure_ascii=False)}
            )
            await broadcast_message("announcements", {
                "type": "announcement_updated",
                "version": latest,
                "top_severity": cur.get("top_severity"),
                "count": cur.get("count"),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
            logger.info("离线补偿：已设置pending并广播一次提醒")

            # 离线补偿场景也同步发送平台通知
            try:
                asyncio.create_task(_notify_announcement_update(
                    latest,
                    cur.get("top_severity"),
                    int(cur.get("count") or 0)
                ))
            except Exception as e:
                logger.debug(f"同步平台通知任务创建失败: {e}")
    except Exception as e:
        # 抛出由包装的重试逻辑处理
        logger.warning(f"离线补偿检查异常: {e}")
        raise

async def _offline_compensation_check_with_retry(max_retries: int = 3, base_delay: float = 1.5):
    """为离线补偿检查增加简单的重试机制。"""
    for attempt in range(1, max_retries + 1):
        try:
            await _offline_compensation_check()
            logger.info("离线补偿检查完成")
            return
        except Exception as e:
            logger.warning(f"离线补偿检查第{attempt}次失败: {e}")
            if attempt < max_retries:
                await asyncio.sleep(base_delay * attempt)
    logger.error("离线补偿检查多次失败，放弃本轮")

async def _notify_announcement_update(version: int, top_severity: Optional[str], count: int) -> None:
    """将公告更新同步发送到用户设置的平台。

    仅使用用户在 notification_settings 中开启且已配置的渠道：
    - wechat_bot: 发送文本
    - serverchan3: 发送Markdown
    需开启 system_status_enabled == 'true' 方会推送。
    
    注意：此函数包含去重机制，相同版本的通知只会发送一次。
    """
    try:
        # 去重检查：检查该版本是否已经发送过通知
        rows = await db.execute_query(
            "SELECT value FROM global_config WHERE key = :k",
            {"k": "announcement_state"}
        )
        state: Dict[str, Any] = {}
        if rows:
            try:
                state = json.loads(rows[0].get("value") or "{}")
            except Exception:
                state = {}
        
        notified_version = int(state.get("notified_version") or 0)
        if version <= notified_version:
            logger.debug(f"公告版本 {version} 已发送过通知（notified_version={notified_version}），跳过重复发送")
            return
        
        logger.info(f"准备发送公告通知: version={version}, notified_version={notified_version}")
        # 优先尝试从社区端拉取具体公告内容，用于拼装更完整的消息
        items: List[Dict[str, Any]] = []
        try:
            remote_url = f"{SHEQU_PUBLIC_BASE}/public/announcements"
            params = {"limit": 5}
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(remote_url, params=params)
                if resp.status_code == 200:
                    data = resp.json() or {}
                    if isinstance(data, dict) and isinstance(data.get("items"), list):
                        items = data.get("items")
                        logger.debug(f"成功获取公告内容: {len(items)}条")
        except Exception as e:
            # 拉取失败时保持 items 为空，后续使用摘要消息
            logger.debug(f"获取公告内容失败，使用摘要消息: {e}")
            pass

        # 查询已开启系统状态通知的用户设置
        rows = await db.execute_query(
            """
            SELECT user_id, wechat_bot_enabled, wechat_webhook_url,
                   serverchan3_enabled, serverchan3_uid, serverchan3_sendkey,
                   email_enabled, email_address,
                   web_push_enabled, websocket_enabled,
                   COALESCE(telegram_bot_enabled, 'false') AS telegram_bot_enabled,
                   telegram_chat_id,
                   COALESCE(system_status_enabled, 'true') AS system_status_enabled
            FROM notification_settings
            """,
            {}
        )
        if not rows:
            return

        # 组装消息
        sev = (top_severity or "info").lower()
        sev_icon = {"error": "❗", "warn": "⚠️", "success": "✅", "info": "ℹ️"}.get(sev, "ℹ️")
        title = f"{sev_icon} 社区公告"
        # 按时间排序，推送最新发布的公告（非置顶）
        if items:
            try:
                # 按updated_at时间排序，取最新发布的公告
                sorted_items = sorted(items, key=lambda x: x.get("updated_at", ""), reverse=True)
                latest_item = sorted_items[0]  # 取最新发布的一条
                latest_title = str(latest_item.get("title") or "(无标题)").strip()
                latest_sev = str(latest_item.get("severity") or "info").lower()
                latest_icon = {"error": "❗", "warn": "⚠️", "success": "✅", "info": "ℹ️"}.get(latest_sev, "ℹ️")
                
                # 组装标题和内容
                title = f"{latest_icon} {latest_title}"
                content = str(latest_item.get("content") or "").strip()
                if content:
                    # 截断正文，避免过长（放宽到2000字，适配微信机器人上限）
                    content = content[:2000] + ("…" if len(content) > 2000 else "")
                else:
                    content = "公告内容为空"
            except Exception:
                title = f"{sev_icon} 社区公告"
                content = "有新的社区公告发布或更新"
        else:
            # 退化为摘要消息
            title = f"{sev_icon} 社区公告"
            content = f"有新的社区公告发布或更新"

        # 逐个用户分发
        tasks: List[asyncio.Task] = []
        for r in rows:
            try:
                if str(r.get("system_status_enabled") or "true").lower() != "true":
                    continue
                # 微信机器人
                if str(r.get("wechat_bot_enabled") or "false").lower() == "true" and r.get("wechat_webhook_url"):
                    tasks.append(asyncio.create_task(
                        NotificationService.send_wechat_bot_message(
                            r.get("wechat_webhook_url"),
                            f"{title}\n\n{content}",
                            "text"
                        )
                    ))
                # Server酱³
                if str(r.get("serverchan3_enabled") or "false").lower() == "true" and r.get("serverchan3_uid") and r.get("serverchan3_sendkey"):
                    tasks.append(asyncio.create_task(
                        NotificationService.send_serverchan3_message(
                            r.get("serverchan3_uid"),
                            r.get("serverchan3_sendkey"),
                            f"{title}",
                            content,
                            None
                        )
                    ))
                # Telegram 机器人
                if str(r.get("telegram_bot_enabled") or "false").lower() == "true" and r.get("telegram_chat_id"):
                    try:
                        from routers.telegram_bot import telegram_bot
                        chat_ids = [cid.strip() for cid in str(r.get("telegram_chat_id")).split(',') if cid.strip()]
                        tg_msg = f"*{title}*\n\n{content}"
                        for cid in chat_ids:
                            tasks.append(asyncio.create_task(
                                telegram_bot.send_message(cid, tg_msg)
                            ))
                    except Exception as e:
                        logger.debug(f"Telegram 通知准备失败: {e}")
            except Exception as e:
                logger.debug(f"用户平台通知准备失败: {e}")

        if tasks:
            # 并行等待，不抛出异常阻断主流程
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                # 统计成功和失败的任务数
                success_count = sum(1 for r in results if r is True)
                fail_count = len(results) - success_count
                
                # 只要有任务执行（无论成功失败），都更新已通知版本号，避免重复发送
                # 这样可以防止因为部分渠道失败导致的重复通知轰炸
                state["notified_version"] = version
                await db.execute_update(
                    """
                    INSERT INTO global_config(key, value, updated_at)
                    VALUES(:k, :v, NOW())
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                    {"k": "announcement_state", "v": json.dumps(state, ensure_ascii=False)}
                )
                if success_count > 0:
                    logger.info(f"公告通知发送完成: version={version}, 成功={success_count}, 失败={fail_count}, 已更新 notified_version")
                else:
                    logger.warning(f"公告通知全部发送失败: version={version}, 失败={fail_count}, 但仍更新 notified_version 避免重复")
            except Exception as e:
                logger.error(f"公告通知发送异常: {e}，但仍更新 notified_version 避免重复")
                # 即使异常也更新版本号，避免重复发送
                try:
                    state["notified_version"] = version
                    await db.execute_update(
                        """
                        INSERT INTO global_config(key, value, updated_at)
                        VALUES(:k, :v, NOW())
                        ON CONFLICT (key) DO UPDATE
                        SET value = EXCLUDED.value, updated_at = NOW()
                        """,
                        {"k": "announcement_state", "v": json.dumps(state, ensure_ascii=False)}
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"同步公告到平台失败: {e}")

@router.get("/announcements/sse-status")
async def get_sse_status():
    """获取SSE连接状态"""
    return {
        "sse_connected": _sse_connected,
        "sse_task_running": _sse_connection_task is not None and not _sse_connection_task.done(),
        "timestamp": datetime.now().isoformat()
    }

@local_router.get("/build-version")
async def get_build_version():
    """获取构建版本号"""
    try:
        version_file_path = os.path.join("data", "build-version.json")
        if os.path.exists(version_file_path):
            with open(version_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "version": data.get("version", "未知版本"),
                    "build_time": data.get("build_time", ""),
                    "timestamp": datetime.now().isoformat() + "Z"
                }
        else:
            return {
                "version": "开发版本",
                "build_time": "",
                "timestamp": datetime.now().isoformat() + "Z"
            }
    except Exception as e:
        logger.error(f"获取构建版本号失败: {e}")
        return {
            "version": "开发版本",
            "build_time": "",
            "timestamp": datetime.now().isoformat() + "Z"
        }
