from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from typing import Dict, Optional, Set
import logging
import json
from datetime import datetime
import asyncio
import time
import uuid
import os
from sql.database_postgresql import get_session
from routers.auth import _resolve_user_from_token_str

router = APIRouter(prefix="/api")  # 添加API前缀
logger = logging.getLogger(__name__)

# 记录应用启动时间
APP_START_TIME = time.time()

# 缓存数据锁
_storage_cache_lock = asyncio.Lock()
_recent_activity_cache_lock = asyncio.Lock()
_gpu_cache_lock = asyncio.Lock()

# GPU 指标缓存（后台异步刷新，metrics 快照仅读取）
# 调整为 1 秒，降低仪表盘 GPU 指标感知延迟。
_GPU_CACHE_INTERVAL_SEC = 1
_GPU_CACHE = {
    "summary": {"gpu_count": 0, "has_gpu": False, "vendors": []},
    "gpus": [],
    "status": "success",
    "message": "GPU 数据准备中"
}
_GPU_LAST_TS = 0.0
_GPU_REFRESH_TASK = None

# 存储活跃的WebSocket连接
class ConnectionManager:
    def __init__(self):
        # subscription_id -> Set[WebSocket]
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.stop_fetch_signals: Set[str] = set()  # 添加停止信号集合
        
    async def connect(self, websocket: WebSocket, subscription_id: str):
        await websocket.accept()
        
        if subscription_id in self.active_connections:
            # 如果已经有连接，先断开旧连接
            # 注意：await close() 期间可能会触发 disconnect 从而删除 key
            existing_connections = list(self.active_connections[subscription_id])
            for old_connection in existing_connections:
                try:
                    await old_connection.close()
                except Exception:
                    pass
            
            # 关闭旧连接后，检查 key 是否还存在
            if subscription_id in self.active_connections:
                self.active_connections[subscription_id].clear()
            else:
                self.active_connections[subscription_id] = set()
        else:
            self.active_connections[subscription_id] = set()
            
        self.active_connections[subscription_id].add(websocket)
        # 清理可能存在的旧停止信号
        if subscription_id in self.stop_fetch_signals:
            self.stop_fetch_signals.remove(subscription_id)
        # WebSocket连接已建立
        try:
            await websocket.send_json({
                "type": "hello",
                "subscription": subscription_id,
                "timestamp": datetime.now().isoformat()
            })
        except Exception:
            pass
        
    def disconnect(self, websocket: WebSocket, subscription_id: str):
        if subscription_id in self.active_connections:
            self.active_connections[subscription_id].discard(websocket)
            if not self.active_connections[subscription_id]:
                del self.active_connections[subscription_id]
            # WebSocket连接已断开
        # 清理停止信号
        if subscription_id in self.stop_fetch_signals:
            self.stop_fetch_signals.remove(subscription_id)
            
    def is_connected(self, subscription_id: str) -> bool:
        """检查指定订阅是否有活跃的WebSocket连接"""
        return subscription_id in self.active_connections and bool(self.active_connections[subscription_id])
        
    async def broadcast_progress(self, subscription_id: str, data: dict):
        """广播进度更新到所有连接的客户端"""
        if subscription_id not in self.active_connections:
            return  # 没有连接，直接返回
        
        dead_connections = set()
        active_count = len(self.active_connections[subscription_id])
        success_count = 0
        
        # 优化：减少消息去重开销，简化去重逻辑
        message_id = f"{data.get('type', '')}-{data.get('progress', '')}"
        data['message_id'] = message_id
            
        # ✅ 优化：先过滤出有效的连接，避免向已关闭的连接发送
        valid_connections = []
        for connection in list(self.active_connections[subscription_id]):
            # 发送前检查连接状态（添加异常保护，确保健壮性）
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    valid_connections.append(connection)
                else:
                    dead_connections.add(connection)
            except Exception:
                # 如果检查状态时出错，保守处理：标记为失效连接
                dead_connections.add(connection)
        
            # 清理失效的连接
            for dead in dead_connections:
                self.active_connections[subscription_id].discard(dead)
                
        # 只向有效连接发送
        for connection in valid_connections:
            try:
                await connection.send_json(data)
                success_count += 1
            except Exception as e:
                # 改进错误信息显示
                error_msg = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
                logger.debug(f"发送进度更新失败: {error_msg}")  # 改为 DEBUG 级别
                dead_connections.add(connection)
                # 再次清理
                self.active_connections[subscription_id].discard(connection)
        
        if dead_connections:
            logger.debug(f"清理了 {len(dead_connections)} 个失效的WebSocket连接")
            
        if active_count > 0 and success_count == 0:
            logger.debug(f"没有成功发送进度更新（所有连接已失效）")

    async def broadcast_message(self, subscription_id: str, data: dict):
        """广播消息到所有连接的客户端"""
        if subscription_id not in self.active_connections:
            return  # 没有连接，直接返回
        
        dead_connections = set()
        active_count = len(self.active_connections[subscription_id])
        success_count = 0
        
        # 优化：减少时间戳生成开销，只在需要时添加
        if 'timestamp' not in data:
            data['timestamp'] = datetime.now().isoformat()
            
        # ✅ 优化：先过滤出有效的连接，避免向已关闭的连接发送
        valid_connections = []
        for connection in list(self.active_connections[subscription_id]):
            # 发送前检查连接状态（添加异常保护，确保健壮性）
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    valid_connections.append(connection)
                else:
                    dead_connections.add(connection)
            except Exception:
                # 如果检查状态时出错，保守处理：标记为失效连接
                dead_connections.add(connection)
            
            # 清理失效的连接
            for dead in dead_connections:
                self.active_connections[subscription_id].discard(dead)
                
        # 只向有效连接发送
        for connection in valid_connections:
            try:
                await connection.send_json(data)
                success_count += 1
            except Exception as e:
                # 改进错误信息显示
                error_msg = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
                logger.debug(f"发送消息失败: {error_msg}")  # 改为 DEBUG 级别
                dead_connections.add(connection)
                # 再次清理
                self.active_connections[subscription_id].discard(connection)
        
        if dead_connections:
            logger.debug(f"清理了 {len(dead_connections)} 个失效的WebSocket连接")
            
        if active_count > 0 and success_count == 0:
            logger.debug(f"没有成功发送消息（所有连接已失效）")

manager = ConnectionManager()

# 主事件循环（用于线程安全的 WebSocket 广播）
_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_main_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _MAIN_LOOP
    _MAIN_LOOP = loop


async def _broadcast_live_danmu(subscription_id: str, items: list) -> None:
    channel = f"danmu_live:{subscription_id}"
    await manager.broadcast_message(channel, {
        "type": "danmu",
        "data": items
    })


def publish_live_danmu(subscription_id: str, items: list) -> None:
    """线程安全的直播弹幕推送入口（供录制线程调用）"""
    if not subscription_id or not items:
        return
    try:
        if _MAIN_LOOP and _MAIN_LOOP.is_running():
            asyncio.run_coroutine_threadsafe(
                _broadcast_live_danmu(subscription_id, items),
                _MAIN_LOOP
            )
            return
    except Exception:
        pass
    # 兜底：无法获取主循环时不阻塞录制线程
    return


# 直播弹幕直连会话管理（用于未录制时的 IM 直连）
_LIVE_DANMU_SESSIONS: Dict[str, dict] = {}
_LIVE_DANMU_LOCK = asyncio.Lock()
_LIVE_DANMU_STOP_TASKS: Dict[str, asyncio.Task] = {}
_LIVE_DANMU_STOP_DELAY_SEC = 30


async def _ensure_live_danmu_session(sub_id: str) -> None:
    if not sub_id:
        return
    # 取消延迟停止任务（避免短暂断线导致 stop）
    task = _LIVE_DANMU_STOP_TASKS.pop(sub_id, None)
    if task and not task.done():
        task.cancel()
    async with _LIVE_DANMU_LOCK:
        if sub_id in _LIVE_DANMU_SESSIONS:
            return
    try:
        from sql.models import LiveSubscription
        from live.recorder import live_recorder
        from live import adapters
        from live.danmu import get_danmu_recorder

        # 如果正在录制且已有弹幕采集任务，则无需额外启动
        if sub_id in live_recorder.danmu_tasks:
            return

        db = get_session()
        try:
            sub = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
            if not sub or not sub.room_url:
                return
            platform = (sub.platform or "").lower()
            room_id = str(getattr(sub, "room_id", "") or "").strip()
            if not room_id:
                adapter = adapters.get_adapter_by_platform(platform)
                if adapter:
                    try:
                        room_info = await adapter.get_room_info(sub.room_url)
                        room_id = str((room_info or {}).get("room_id") or "").strip()
                        if room_id:
                            sub.room_id = room_id
                            db.commit()
                    except Exception as room_err:
                        logger.debug(f"[DanmuLive] 获取 room_id 失败，继续尝试直连: {sub_id}, {room_err}")

            recorder = get_danmu_recorder(
                platform,
                room_url=sub.room_url,
                output_path="",
                anchor_name=sub.anchor_name or "",
                subscription_id=sub_id,
                room_id=room_id,
                save_file=False,
            )
            if not recorder:
                return

            recorder.start()
            async with _LIVE_DANMU_LOCK:
                _LIVE_DANMU_SESSIONS[sub_id] = {
                    "recorder": recorder,
                    "platform": platform
                }
        finally:
            try:
                db.close()
            except Exception:
                pass
    except Exception:
        return


async def _stop_live_danmu_session(sub_id: str) -> bool:
    if not sub_id:
        return False
    # 已有延迟停止任务则不重复创建
    existing = _LIVE_DANMU_STOP_TASKS.get(sub_id)
    if existing and not existing.done():
        return False

    async def _delayed_stop():
        try:
            await asyncio.sleep(_LIVE_DANMU_STOP_DELAY_SEC)
        except asyncio.CancelledError:
            return
        # 到期后再次确认无人订阅
        try:
            if manager.is_connected(f"danmu_live:{sub_id}"):
                return
        except Exception:
            pass

        try:
            from live.recorder import live_recorder
            # 如果录制中已经有弹幕任务，不要停止
            if sub_id in live_recorder.danmu_tasks:
                return
        except Exception:
            pass

        async with _LIVE_DANMU_LOCK:
            session = _LIVE_DANMU_SESSIONS.pop(sub_id, None)
        if not session:
            return
        recorder = session.get("recorder")
        try:
            if recorder:
                recorder.stop()
        except Exception:
            pass

    _LIVE_DANMU_STOP_TASKS[sub_id] = asyncio.create_task(_delayed_stop())
    return True

# WebSocket 鉴权失败日志限频，避免客户端重连导致日志刷屏
_WS_AUTH_LOG_INTERVAL_SEC = 60
_WS_AUTH_LAST_LOG_TS: Dict[str, float] = {}
_WS_AUTH_SUPPRESSED_COUNT: Dict[str, int] = {}

def _log_ws_auth_failure(reason: str, channel: Optional[str]):
    safe_channel = (channel or "unknown").strip() or "unknown"
    key = f"{reason}:{safe_channel}"
    now = time.time()
    last = _WS_AUTH_LAST_LOG_TS.get(key, 0.0)

    if now - last >= _WS_AUTH_LOG_INTERVAL_SEC:
        suppressed = _WS_AUTH_SUPPRESSED_COUNT.pop(key, 0)
        suffix = f"，过去{_WS_AUTH_LOG_INTERVAL_SEC}s同类日志已抑制{suppressed}条" if suppressed > 0 else ""
        logger.warning(f"WebSocket鉴权失败: {reason}, channel={safe_channel}{suffix}")
        _WS_AUTH_LAST_LOG_TS[key] = now
    else:
        _WS_AUTH_SUPPRESSED_COUNT[key] = _WS_AUTH_SUPPRESSED_COUNT.get(key, 0) + 1
        logger.debug(f"WebSocket鉴权失败(已限频): {reason}, channel={safe_channel}")

def _extract_ws_token(websocket: WebSocket) -> Optional[str]:
    """从 WebSocket 握手中提取 token（兼容 query/header）。"""
    query_token = websocket.query_params.get("token")
    if query_token:
        return query_token.strip()

    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        bearer_token = auth_header[7:].strip()
        if bearer_token:
            return bearer_token

    api_token = websocket.headers.get("x-api-token")
    if api_token:
        return api_token.strip()

    return None

async def _require_ws_auth(websocket: WebSocket, channel: str) -> bool:
    """统一 WebSocket 鉴权，失败时直接拒绝握手。"""
    token_str = _extract_ws_token(websocket)
    if not token_str:
        _log_ws_auth_failure("缺少token", channel)
        try:
            await websocket.close(code=1008, reason="Unauthorized")
        except Exception:
            pass
        return False

    db = None
    try:
        db = get_session()
        user = await _resolve_user_from_token_str(token_str, db)
        if not user:
            _log_ws_auth_failure("无效token", channel)
            try:
                await websocket.close(code=1008, reason="Unauthorized")
            except Exception:
                pass
            return False
        return True
    except Exception as e:
        logger.error(f"WebSocket鉴权异常: channel={channel}, error={str(e)}")
        try:
            await websocket.close(code=1011, reason="Auth error")
        except Exception:
            pass
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

@router.websocket("/ws/subscribe/{subscription_id}/progress")
async def websocket_endpoint(websocket: WebSocket, subscription_id: str):
    """WebSocket连接端点"""
    # 验证 subscription_id 参数
    if not subscription_id or subscription_id.strip() == "":
        logger.error("WebSocket连接失败: subscription_id 为空")
        try:
            await websocket.close(code=1008, reason="Invalid subscription_id")
        except Exception:
            pass
        return

    if not await _require_ws_auth(websocket, f"{subscription_id}/progress"):
        return
    
    try:
        await manager.connect(websocket, subscription_id)
    except KeyError as e:
        logger.error(f"WebSocket连接参数错误: {str(e)}, subscription_id={subscription_id}")
        try:
            await websocket.close(code=1008, reason=f"Parameter error: {str(e)}")
        except Exception:
            pass
        return
    except Exception as e:
        logger.error(f"WebSocket连接建立失败: {str(e)}, subscription_id={subscription_id}")
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
        return
    
    # 若是 metrics 订阅，建立连接后立即推送一次当前快照
    if subscription_id == "metrics":
        try:
            snapshot = await _collect_metrics_snapshot()
            await websocket.send_json({
                "type": "metrics",
                "seq": 0,
                "payload": snapshot,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            # 连接已关闭是正常情况，不记录为WARNING级别
            if websocket.client_state == WebSocketState.CONNECTED:
                logger.warning(f"初次推送指标失败: {str(e)}")
            else:
                logger.debug(f"初次推送指标失败（连接已关闭）: {str(e)}")

        # 为该连接单独启动一个周期性推送任务，确保持续有帧
        async def _per_connection_metrics_pump(ws: WebSocket):
            seq = 0
            while True:
                try:
                    await asyncio.sleep(1) # 改为1秒刷新一次，提供更流畅的CPU/网络实时曲线
                    seq += 1
                    payload = await _collect_metrics_snapshot()
                    # 检查连接状态，避免向已关闭的连接发送消息
                    if ws.client_state == WebSocketState.CONNECTED:
                        await ws.send_json({
                            "type": "metrics",
                            "seq": seq,
                            "payload": payload,
                            "timestamp": datetime.now().isoformat()
                        })
                    else:
                        # 连接已关闭，退出循环
                        break
                except Exception:
                    # 任何异常（包括连接关闭）直接退出循环
                    break
        metrics_task = asyncio.create_task(_per_connection_metrics_pump(websocket))
    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
                    # 心跳响应已发送，不记录日志避免刷屏
                elif data == "stop_fetch":
                    # 处理停止获取信号
                    manager.stop_fetch_signals.add(subscription_id)
                    logger.info(f"收到停止获取信号: {subscription_id}")
                    await websocket.send_json({"type": "fetch_status", "status": "stopping"})
            except WebSocketDisconnect:
                break
            except Exception as e:
                # 连接已关闭的错误不记录为ERROR，避免日志噪音
                if "not connected" in str(e).lower() or "close message" in str(e).lower():
                    logger.debug(f"处理WebSocket消息时连接已关闭: {str(e)}")
                else:
                    logger.error(f"处理WebSocket消息时出错: {str(e)}")
                break
    finally:
        manager.disconnect(websocket, subscription_id)
        # WebSocket连接已关闭
        try:
            if subscription_id == "metrics" and 'metrics_task' in locals():
                metrics_task.cancel()
        except Exception:
            pass

@router.websocket("/ws/subscribe/downloads/progress")
async def downloads_progress_endpoint(websocket: WebSocket):
    """下载进度WebSocket连接端点"""
    if not await _require_ws_auth(websocket, "downloads/progress"):
        return
    await manager.connect(websocket, "downloads")
    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
                    # 心跳响应已发送，不记录日志避免刷屏
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"处理下载进度WebSocket消息时出错: {str(e)}")
                break
    finally:
        manager.disconnect(websocket, "downloads")
        # 下载进度WebSocket连接已关闭

@router.websocket("/ws/subscribe/batch_tasks/progress")
async def batch_tasks_progress_endpoint(websocket: WebSocket):
    """批量任务进度WebSocket连接端点"""
    if not await _require_ws_auth(websocket, "batch_tasks/progress"):
        return
    await manager.connect(websocket, "batch_tasks")
    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
                    # 心跳响应已发送，不记录日志避免刷屏
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"处理批量任务WebSocket消息时出错: {str(e)}")
                break
    finally:
        manager.disconnect(websocket, "batch_tasks")
        # 批量任务WebSocket连接已关闭

@router.websocket("/ws/subscribe/transcode")
async def transcode_status_endpoint(websocket: WebSocket):
    """实时转码状态 WebSocket 连接端点"""
    if not await _require_ws_auth(websocket, "transcode"):
        return
    await manager.connect(websocket, "transcode")
    # 建立连接后推送一次当前快照
    try:
        from routers import file_manager
        snapshot = file_manager._get_last_transcoder()
        await websocket.send_json({
            "type": "transcode_update",
            "payload": snapshot,
            "timestamp": datetime.now().isoformat()
        })
    except Exception:
        pass
    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
                    # 心跳响应已发送，不记录日志避免刷屏
            except WebSocketDisconnect:
                break
            except Exception as e:
                # 某些情况下（前端未完成握手、连接已被关闭）底层会抛出
                # "WebSocket is not connected. Need to call \"accept\" first." 等异常，
                # 这类属于正常场景，无需 ERROR 级别刷屏日志，这里直接静默退出循环。
                msg = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
                if "WebSocket is not connected" in msg or "Need to call \"accept\" first" in msg:
                    break
                logger.error(f"处理转码状态 WebSocket 消息时出错: {msg}")
                break
    finally:
        manager.disconnect(websocket, "transcode")
        # 转码状态 WebSocket 连接已关闭


# 弹幕实时推送
@router.websocket("/ws/subscribe/danmu/{sub_id}")
async def danmu_stream_endpoint(websocket: WebSocket, sub_id: str):
    """弹幕 WebSocket 连接端点（前端按时间窗口同步）"""
    if not await _require_ws_auth(websocket, f"danmu/{sub_id}"):
        return
    if not sub_id or sub_id.strip() == "":
        try:
            await websocket.close(code=1008, reason="Invalid subscription_id")
        except Exception:
            pass
        return

    subscription_key = f"danmu:{sub_id}"
    await manager.connect(websocket, subscription_key)

    async def _fetch_danmu_range(start_ts: float, end_ts: float, limit: int):
        if end_ts <= start_ts:
            await websocket.send_json({
                "type": "error",
                "message": "end_ts 必须大于 start_ts"
            })
            return
        from sql.models import LiveSubscription, LiveRecord
        from live.routers import (
            _resolve_record_end_time,
            _align_datetime_pair,
            _resolve_danmu_path,
            _read_danmu_range
        )

        db = None
        try:
            db = get_session()
            subscription = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
            if not subscription:
                await websocket.send_json({
                    "type": "error",
                    "message": "订阅不存在"
                })
                return

            timeline_statuses = ["recording", "completed", "stopped", "converting", "failed"]
            records = db.query(LiveRecord).filter(
                LiveRecord.subscription_id == sub_id,
                LiveRecord.status.in_(timeline_statuses),
                LiveRecord.start_time.isnot(None)
            ).order_by(LiveRecord.start_time.asc()).all()

            window_start = datetime.fromtimestamp(start_ts)
            window_end = datetime.fromtimestamp(end_ts)
            danmu_files = []
            for r in records:
                record_start = r.start_time
                if not record_start:
                    continue
                record_end = _resolve_record_end_time(r)
                if not record_end:
                    continue
                comp_end, comp_start = _align_datetime_pair(record_end, record_start)
                if comp_end < comp_start:
                    record_end = record_start

                comp_record_start, comp_window_end = _align_datetime_pair(record_start, window_end)
                comp_record_end, comp_window_start = _align_datetime_pair(record_end, window_start)
                if comp_record_start >= comp_window_end or comp_record_end <= comp_window_start:
                    continue

                danmu_path = _resolve_danmu_path(r.file_path)
                if danmu_path and os.path.exists(danmu_path):
                    danmu_files.append(danmu_path)

            danmu_files = list(dict.fromkeys(danmu_files))
            events = []
            remaining = max(1, min(5000, int(limit)))
            for danmu_path in danmu_files:
                if remaining <= 0:
                    break
                items = _read_danmu_range(danmu_path, start_ts, end_ts, limit=remaining)
                events.extend(items)
                remaining = max(0, remaining - len(items))

            events.sort(key=lambda item: item.get("ts") or 0)

            return {
                "events": events,
                "files_checked": len(danmu_files),
                "start_ts": start_ts,
                "end_ts": end_ts
            }
        except Exception as e:
            logger.error(f"弹幕同步失败: {e}")
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": "弹幕同步失败"
                })
            except Exception:
                pass
            return None
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    cursor_ts: Optional[float] = None
    target_ts: Optional[float] = None
    stream_task = None
    async def _stream_loop():
        nonlocal cursor_ts, target_ts
        window = 30
        idle_sleep = 0.8
        while True:
            await asyncio.sleep(0)
            if cursor_ts is None or target_ts is None:
                await asyncio.sleep(idle_sleep)
                continue
            if cursor_ts > target_ts + 1:
                await asyncio.sleep(idle_sleep)
                continue
            range_end = min(cursor_ts + window, target_ts + 2)
            payload = await _fetch_danmu_range(cursor_ts, range_end, limit=2000)
            if not payload:
                await asyncio.sleep(idle_sleep)
                continue
            events = payload.get("events") or []
            if events:
                try:
                    await websocket.send_json({
                        "type": "danmu",
                        "data": events,
                        "meta": {
                            "files_checked": payload.get("files_checked", 0),
                            "count": len(events),
                            "start_ts": payload.get("start_ts"),
                            "end_ts": payload.get("end_ts")
                        }
                    })
                except Exception:
                    pass
                try:
                    last_ts = float(events[-1].get("ts", cursor_ts))
                    cursor_ts = last_ts + 0.001
                except Exception:
                    cursor_ts = cursor_ts + 1
            else:
                try:
                    cursor_ts = float(payload.get("end_ts") or range_end)
                except Exception:
                    cursor_ts = range_end
                await asyncio.sleep(idle_sleep)

    try:
        stream_task = asyncio.create_task(_stream_loop())
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
                    continue
                payload = json.loads(data)
                msg_type = payload.get("type")
                if msg_type not in ("reset", "sync", "tick"):
                    continue
                if msg_type == "tick":
                    ts = float(payload.get("ts", 0))
                    if ts > 0:
                        target_ts = ts
                    continue
                start_ts = float(payload.get("start_ts", 0))
                if start_ts <= 0:
                    continue
                cursor_ts = start_ts
                target_ts = float(payload.get("end_ts", start_ts + 2))
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"处理弹幕WebSocket消息时出错: {str(e)}")
                break
    finally:
        manager.disconnect(websocket, subscription_key)
        if stream_task:
            stream_task.cancel()


# 直播弹幕实时推送（直连 IM -> WS）
@router.websocket("/ws/subscribe/danmu-live/{sub_id}")
async def danmu_live_stream_endpoint(websocket: WebSocket, sub_id: str):
    """直播弹幕 WebSocket 连接端点（等待 IM 推送）"""
    if not await _require_ws_auth(websocket, f"danmu_live/{sub_id}"):
        return
    if not sub_id or sub_id.strip() == "":
        try:
            await websocket.close(code=1008, reason="Invalid subscription_id")
        except Exception:
            pass
        return

    subscription_key = f"danmu_live:{sub_id}"
    await manager.connect(websocket, subscription_key)
    await _ensure_live_danmu_session(sub_id)
    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
            except Exception as e:
                msg = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
                if "WebSocket is not connected" in msg or "Need to call \"accept\" first" in msg:
                    break
                logger.error(f"处理直播弹幕WebSocket消息时出错: {msg}")
                break
    finally:
        manager.disconnect(websocket, subscription_key)
        if not manager.is_connected(subscription_key):
            scheduled = await _stop_live_danmu_session(sub_id)
            if scheduled:
                logger.info(
                    "[DanmuLive] WS 连接断开，准备延迟停止弹幕采集: sub_id=%s delay=%ss",
                    sub_id,
                    _LIVE_DANMU_STOP_DELAY_SEC,
                )


# 直播状态推送后台任务引用
_live_status_task = None

async def _live_status_loop():
    """后台任务：定期广播正在录制的任务状态"""
    while True:
        try:
            await asyncio.sleep(1) # 1秒刷新一次，保证录制时长显示的秒数跳动流畅 (原3秒会有卡顿感)
            # 只有当有人订阅 live_status 频道时才广播，节省资源
            if not manager.is_connected("live_status"):
                 continue

            from live.recorder import live_recorder
            recording_ids = live_recorder.get_all_recording_ids()
            
            # 如果没有正在录制的任务，不需要推送
            if not recording_ids:
                 continue

            for sub_id in recording_ids:
                status = live_recorder.get_recording_status(sub_id)
                if status:
                    update_data = {
                        "id": sub_id,
                        "is_recording": True, 
                        "recording_status": status
                    }
                    await broadcast_live_status_update(update_data)
                    
        except Exception as e:
            logger.error(f"直播状态循环推送异常: {e}")
            await asyncio.sleep(5)

@router.websocket("/ws/subscribe/live_status")
async def live_status_endpoint(websocket: WebSocket):
    """直播录制状态 WebSocket 连接端点"""
    if not await _require_ws_auth(websocket, "live_status"):
        return
    await manager.connect(websocket, "live_status")
    
    # 启动后台推送任务 (如果尚未运行)
    global _live_status_task
    if _live_status_task is None or _live_status_task.done():
        _live_status_task = asyncio.create_task(_live_status_loop())
        logger.info("已启动直播状态实时推送任务")
    
    # 建立连接后推送一次当前快照
    try:
        from sql.database_postgresql import get_session
        
        # 获取数据库会话
        db = get_session()
        try:
            # 获取统计数据
            # 这里的逻辑需要调整，因为 live.routers 重构了，原来可能有 get_live_stats 但现在没有了。
            # 直播统计数据现在应该直接从数据库查询，而不是依赖 live.routers 内部函数
            # 之前的 live.routers.py 现在被 adapter 逻辑替换了，可能丢失了 get_live_stats
            
            # 手动实现统计逻辑，不再尝试导入不存在的函数
            from sql.models import LiveSubscription, LiveRecord
            from live.recorder import live_recorder
            from datetime import date, datetime
            
            # 1. 简化的统计信息
            total_subscriptions = db.query(LiveSubscription).count()
            recording_ids = live_recorder.get_all_recording_ids()
            recording_count = len(recording_ids)
            today_start = datetime.combine(date.today(), datetime.min.time())
            today_records = db.query(LiveRecord).filter(LiveRecord.start_time >= today_start).count()
            
            # 监控状态统计
            disabled_all = db.query(LiveSubscription).filter(
                LiveSubscription.monitor_enabled == "false"
            ).count()
            invalid_count = db.query(LiveSubscription).filter(
                LiveSubscription.monitor_enabled == "false",
                cast(LiveSubscription.extra_data, String).like('%auto_disabled%')
            ).count()
            paused_count = disabled_all - invalid_count
            
            stats_snapshot = {
                "total_subscriptions": total_subscriptions,
                "paused_count": paused_count,
                "invalid_count": invalid_count,
                "recording_count": recording_count,
                "today_records": today_records,
                # total_size 计算太慢，初始推送暂时省略，或者由前端保留上次的值
                "total_size": 0 
            }
            
            # 2. 状态列表 (仅提取关键状态)
            live_status_list = []
            subscriptions = db.query(LiveSubscription).all()
            for sub in subscriptions:
                is_recording = live_recorder.is_recording(sub.id)
                live_status_list.append({
                    "id": sub.id,
                    "is_live": sub.is_live == "true",
                    "is_recording": is_recording,
                    "recording_status": live_recorder.get_recording_status(sub.id) if is_recording else None
                })
            
            # 推送初始数据
            await websocket.send_json({
                "type": "live_status_initial",
                "stats": stats_snapshot,
                "data": live_status_list,
                "timestamp": datetime.now().isoformat()
            })
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"直播状态 WebSocket 初始推送失败: {e}")
        
    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"处理直播状态 WebSocket 消息时出错: {str(e)}")
                break
    finally:
        manager.disconnect(websocket, "live_status")


async def send_progress_update(subscription_id: str, progress_data: dict):
    """发送进度更新"""
    try:
        # 根据消息类型构造不同的数据结构
        if isinstance(progress_data, dict) and "type" in progress_data:
            # 如果已经包含type字段，直接使用
            data = {
                "timestamp": datetime.now().isoformat(),
                **progress_data
            }
        else:
            # 否则按照原有格式处理
            data = {
                "type": "progress_update",
                "timestamp": datetime.now().isoformat(),
                "data": progress_data
            }
        
        # 1. 确保数据中包含 subscription_id，以便公共频道识别归属
        if "subscription_id" not in data:
            data["subscription_id"] = subscription_id
            
        has_active_receiver = False
        
        # 2. 检查并发送给特定订阅 ID 的频道
        if manager.is_connected(subscription_id):
            has_active_receiver = True
            # 检查当前事件循环状态，避免冲突
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    asyncio.create_task(manager.broadcast_progress(subscription_id, data))
                else:
                    await manager.broadcast_progress(subscription_id, data)
            except RuntimeError:
                await manager.broadcast_progress(subscription_id, data)
        
        # 3. [新增] 如果是批量下载进度，同时也发送给全局 batch_tasks 频道
        # 这样任务列表页（监听 batch_tasks）也能收到个别任务的更新
        if data.get("type") == "batch_download_progress" and manager.is_connected("batch_tasks"):
            has_active_receiver = True
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    asyncio.create_task(manager.broadcast_progress("batch_tasks", data))
                else:
                    await manager.broadcast_progress("batch_tasks", data)
            except RuntimeError:
                await manager.broadcast_progress("batch_tasks", data)

        # 4. 如果两个频道都没有活跃连接，才记录日志
        if not has_active_receiver:
            # 批量操作时，很多订阅可能没有建立WebSocket连接，这是正常的
            # 降低日志级别，避免日志刷屏
            if data.get("type") == "batch_download_progress":
                # 批量下载进度：使用 DEBUG 级别（批量操作时很常见）
                logger.debug(f"尝试发送批量下载进度但没有活跃连接: {subscription_id}")
            elif data.get("type") == "sync_progress" or data.get("type") == "check_result":
                # 同步/检测进度：使用 DEBUG 级别（用户可能不在页面）
                logger.debug(f"尝试发送进度更新但没有活跃连接: {subscription_id}, 类型: {data.get('type')}")
            else:
                # 其他类型：使用 INFO 级别（可能表示问题）
                logger.info(f"尝试发送进度更新但没有活跃连接: {subscription_id}, 类型: {data.get('type')}")
            return
            
    except Exception as e:
        logger.error(f"发送进度更新时出错: {str(e)}")
        # 不抛出异常，避免影响下载流程

async def broadcast_message(subscription_id: str, data: dict):
    """广播消息到指定订阅的所有客户端"""
    await manager.broadcast_message(subscription_id, data) 

async def broadcast_transcode_update(data: dict):
    await manager.broadcast_message("transcode", {
        "type": "transcode_update",
        "payload": data,
        "timestamp": datetime.now().isoformat()
    })

async def broadcast_live_status_update(data: dict):
    """广播直播状态更新"""
    # 构造标准消息格式
    message = {
        "type": "live_status_update",
        "timestamp": datetime.now().isoformat(),
        # 支持两种更新模式：
        # 1. 'stats': 仅更新顶部统计
        # 2. 'subscription': 更新单个订阅的状态
        # 3. 'full': 全量更新 (不推荐，尽量用增量)
        **data 
    }
    await manager.broadcast_message("live_status", message)


async def _refresh_gpu_cache_nonblocking(force: bool = False):
    """后台刷新 GPU 缓存（非阻塞）。

    - 快照路径不等待该任务完成，避免阻塞 metrics 推送。
    - 同一时刻只允许一个刷新任务在跑。
    """
    global _GPU_REFRESH_TASK, _GPU_LAST_TS, _GPU_CACHE

    now = time.time()
    if not force and (now - _GPU_LAST_TS) < _GPU_CACHE_INTERVAL_SEC:
        return

    if _GPU_REFRESH_TASK is not None and not _GPU_REFRESH_TASK.done():
        return

    async def _runner():
        global _GPU_LAST_TS, _GPU_CACHE
        try:
            from routers.system import get_gpu_stats
            fresh_gpu = await asyncio.wait_for(get_gpu_stats(), timeout=6)
            if isinstance(fresh_gpu, dict):
                gpu_data = {
                    "summary": fresh_gpu.get("summary", {"gpu_count": 0, "has_gpu": False, "vendors": []}),
                    "gpus": fresh_gpu.get("gpus", []),
                    "status": fresh_gpu.get("status", "success"),
                    "message": fresh_gpu.get("message", "")
                }
                async with _gpu_cache_lock:
                    _GPU_CACHE = gpu_data
                    _GPU_LAST_TS = time.time()
        except Exception:
            # 失败时保留旧缓存
            pass

    _GPU_REFRESH_TASK = asyncio.create_task(_runner())


# ---- metrics snapshot helper (避免循环依赖，精简实现) ----
async def _collect_metrics_snapshot() -> dict:
    """采集一次指标快照（同步函数，供后台线程调用）"""
    
    # 1) 容器运行时长（应用启动时间）
    uptime_seconds = int(time.time() - APP_START_TIME)
    
    # 2) 内存

    memory_mb = 0.0
    memory_limit_mb = 0.0
    try:
        import os
        with open('/sys/fs/cgroup/memory.current', 'r') as f:
            current_bytes = int(f.read().strip())
        with open('/sys/fs/cgroup/memory.stat', 'r') as f:
            lines = f.readlines()
        memory_stats = {}
        for line in lines:
            if ' ' in line:
                key, value = line.strip().split(' ', 1)
                memory_stats[key] = int(value)
        inactive_file = memory_stats.get('inactive_file', 0)
        memory_bytes = max(0, current_bytes - inactive_file)
        memory_mb = memory_bytes / 1024 / 1024

        limit_bytes = 0
        if os.path.exists('/sys/fs/cgroup/memory.max'):
            with open('/sys/fs/cgroup/memory.max', 'r') as f:
                val = f.read().strip()
                if val != 'max': limit_bytes = int(val)
        elif os.path.exists('/sys/fs/cgroup/memory/memory.limit_in_bytes'):
            with open('/sys/fs/cgroup/memory/memory.limit_in_bytes', 'r') as f:
                limit_bytes = int(f.read().strip())
        
        # 如果 limit_bytes 太大（例如 cgroup v1 下的 9223372036854771712）或为 0，代表未限制
        # 此时读取宿主机 /proc/meminfo 获取总内存
        if limit_bytes <= 0 or limit_bytes > 1024**5: # 1TB 作为一个阈值判断，通常容器限制不会这么大
            try:
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if line.startswith('MemTotal:'):
                            # 格式: MemTotal:       32744744 kB
                            limit_bytes = int(line.split()[1]) * 1024
                            break
            except:
                pass

        if limit_bytes > 0:
            memory_limit_mb = limit_bytes / 1024 / 1024
    except Exception:
        pass

    # 2) 下载任务统计（包含所有类型：订阅下载、手动下载）
    downloading = 0
    queued = 0
    completed = 0
    failed = 0
    try:
        # 统计订阅下载任务（内存操作，无需 wrapper）
        from routers.downloader import download_manager as _dm
        subscription_tasks = 0
        try:
            subscription_tasks = len([t for t in (_dm.tasks or {}).values() if not t.done()])
        except Exception:
            subscription_tasks = 0
        try:
            queued = len(_dm.download_queue)
        except Exception:
            queued = 0
        
        global _TASK_COUNTS_CACHE, _TASK_COUNTS_LAST_TS
        try:
            _TASK_COUNTS_CACHE
        except NameError:
            _TASK_COUNTS_CACHE = {"completed": 0, "failed": 0}
            _TASK_COUNTS_LAST_TS = 0

        # 是否需要更新缓存的完成/失败计数
        need_update_history = (time.time() - _TASK_COUNTS_LAST_TS > 10)

        def _fetch_download_stats_db_sync(check_history: bool):
            _d = 0
            _c = None
            _f = None
            _sub_count = 0
            try:
                from sql.database_postgresql import get_db
                from sql.models import Task, TaskStatus
                from sqlalchemy import cast, String, func
                db = next(get_db())
                try:
                    # 1. Active tasks (手动任务)
                    active_statuses = [TaskStatus.PENDING.value, TaskStatus.DOWNLOADING.value, TaskStatus.PROCESSING.value]
                    _d = db.query(Task).filter(Task.status.in_(active_statuses)).count()
                    
                    # [新增] 统计正在下载的订阅博主数量 (去重)
                    _sub_count = db.query(func.count(func.distinct(Task.subscription_id))).filter(
                        Task.status.in_(active_statuses),
                        Task.subscription_id.isnot(None)
                    ).scalar()
                    
                    # 2. Completed/Failed tasks (only if needed)
                    if check_history:
                        _c = db.query(Task).filter(Task.status == TaskStatus.COMPLETED.value).count()
                        _f = db.query(Task).filter(Task.status == TaskStatus.ERROR.value).count()
                finally:
                    try:
                        db.close()
                    except Exception:
                        pass
            except Exception:
                pass
            return _d, _c, _f, _sub_count

        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, lambda: _fetch_download_stats_db_sync(need_update_history))
        
        active_subscription_count = 0
        if res:
             manual_tasks, db_completed, db_failed, sub_count = res
             downloading = manual_tasks
             active_subscription_count = sub_count
             
             if need_update_history and db_completed is not None:
                 _TASK_COUNTS_CACHE = {"completed": db_completed, "failed": db_failed}
                 _TASK_COUNTS_LAST_TS = time.time()
                 completed = db_completed
                 failed = db_failed
             else:
                 completed = _TASK_COUNTS_CACHE.get("completed", 0)
                 failed = _TASK_COUNTS_CACHE.get("failed", 0)
        else:
             completed = _TASK_COUNTS_CACHE.get("completed", 0)
             failed = _TASK_COUNTS_CACHE.get("failed", 0)

    except Exception:
        downloading, queued, completed, failed = 0, 0, 0, 0

    # 3) 容器内网络速率（rx下行 + tx上行）
    # 采用滑动差分：读取网卡rx_bytes/tx_bytes并与上次快照比较，速率=Δbytes/Δt
    net = {"rx_bps": 0, "tx_bps": 0}
    try:
        import os
        # 模块级缓存
        global _NET_RX_PREV_BYTES, _NET_RX_PREV_TS, _NET_TX_PREV_BYTES, _NET_IFACE
        try:
            _NET_RX_PREV_BYTES
        except NameError:
            _NET_RX_PREV_BYTES = None
            _NET_RX_PREV_TS = None
            _NET_TX_PREV_BYTES = None
            _NET_IFACE = None

        def _detect_iface() -> str | None:
            # 优先 eth0；否则挑选第一个非lo、状态为up的接口
            try:
                if os.path.exists('/sys/class/net/eth0/statistics/rx_bytes'):
                    return 'eth0'
                for name in os.listdir('/sys/class/net'):
                    if name == 'lo':
                        continue
                    path = f'/sys/class/net/{name}/operstate'
                    state = None
                    try:
                        with open(path, 'r') as f:
                            state = f.read().strip()
                    except Exception:
                        state = None
                    if os.path.exists(f'/sys/class/net/{name}/statistics/rx_bytes') and (state in (None, 'up')):
                        return name
            except Exception as e:
                import traceback
                # Assuming the user meant to add this logging to the general exception for _detect_iface
                # and that "Storage sync error" is a placeholder for a more general metrics collection error.
                # The original instruction mentioned `_fetch_storage_sync` which is not present.
                # This is the most syntactically correct and faithful interpretation of the intent
                # given the provided "Code Edit" snippet's content and its placement attempt.
                logger.error(f"Metrics collection error in _detect_iface: {e}\n{traceback.format_exc()}")
                return None
            return None

        if _NET_IFACE is None:
            _NET_IFACE = _detect_iface()

        def _read_rx_bytes() -> int | None:
            if not _NET_IFACE:
                return None
            p = f'/sys/class/net/{_NET_IFACE}/statistics/rx_bytes'
            try:
                with open(p, 'r') as f:
                    return int(f.read().strip())
            except Exception:
                return None

        def _read_tx_bytes() -> int | None:
            if not _NET_IFACE:
                return None
            p = f'/sys/class/net/{_NET_IFACE}/statistics/tx_bytes'
            try:
                with open(p, 'r') as f:
                    return int(f.read().strip())
            except Exception:
                return None

        now = time.time()
        cur_rx = _read_rx_bytes()
        cur_tx = _read_tx_bytes()
        
        # 只有当两个指标的先前数据都存在时才计算，避免初次采样跳变
        if cur_rx is not None and _NET_RX_PREV_BYTES is not None and _NET_RX_PREV_TS is not None:
            dt = max(0.001, now - _NET_RX_PREV_TS)
            db_rx = max(0, cur_rx - _NET_RX_PREV_BYTES)
            rx_bps = int(db_rx / dt)
            # 安全阈值：单网卡 1GB/s 以上通常视为采样错误或回环异常
            if rx_bps < 1024 * 1024 * 1024:
                net["rx_bps"] = rx_bps
        
        if cur_tx is not None and _NET_TX_PREV_BYTES is not None and _NET_RX_PREV_TS is not None:
            dt = max(0.001, now - _NET_RX_PREV_TS)
            db_tx = max(0, cur_tx - _NET_TX_PREV_BYTES)
            tx_bps = int(db_tx / dt)
            if tx_bps < 1024 * 1024 * 1024:
                net["tx_bps"] = tx_bps

        # 更新全局缓存
        _NET_RX_PREV_BYTES = cur_rx
        _NET_TX_PREV_BYTES = cur_tx
        _NET_RX_PREV_TS = now
    except Exception:
        pass

    # 4) 浏览器标签页统计
    browsers = {
        "total_pages": 0,  # 标签页总数（包括所有平台）
    }
    
    try:
        def _fetch_browsers_sync():
            # 通过Chrome DevTools Protocol (CDP) 获取真实标签页数
            import json
            import urllib.request
            
            _total = 0
            # 1. 统一浏览器（douyin/bilibili/youtube）- 端口9222
            try:
                with urllib.request.urlopen('http://localhost:9222/json', timeout=1) as response:
                    targets = json.loads(response.read().decode())
                    _total += len([t for t in targets if t.get('type') == 'page'])
            except Exception:
                pass
            
            # 2. DYD浏览器（独立实例）- 端口9223
            try:
                with urllib.request.urlopen('http://localhost:9223/json', timeout=1) as response:
                    targets = json.loads(response.read().decode())
                    _total += len([t for t in targets if t.get('type') == 'page'])
            except Exception:
                pass
            return _total

        loop = asyncio.get_running_loop()
        total_pages = await loop.run_in_executor(None, _fetch_browsers_sync)
        browsers["total_pages"] = total_pages
    except Exception:
        browsers["total_pages"] = 0

    # 5) 看门狗清理次数（/tmp 持久跨重启）
    watchdog_count = 0
    try:
        import os
        p = '/tmp/easy_vdl_watchdog_count'
        if os.path.exists(p):
            with open(p, 'r') as f:
                watchdog_count = int((f.read() or '0').strip() or '0')
    except Exception:
        watchdog_count = 0

    # 6) CPU 使用率（通过 /proc/stat 计算）
    cpu_percent = 0.0
    try:
        # 模块级缓存
        global _CPU_PREV_TOTAL, _CPU_PREV_IDLE, _CPU_PREV_TS
        try:
            _CPU_PREV_TOTAL
        except NameError:
            _CPU_PREV_TOTAL = None
            _CPU_PREV_IDLE = None
            _CPU_PREV_TS = None

        def _read_cpu_stats():
            with open('/proc/stat', 'r') as f:
                line = f.readline()  # 第一行是总CPU统计
            fields = line.split()
            if fields[0] == 'cpu':
                # user, nice, system, idle, iowait, irq, softirq, ...
                user = int(fields[1])
                nice = int(fields[2])
                system = int(fields[3])
                idle = int(fields[4])
                iowait = int(fields[5]) if len(fields) > 5 else 0
                irq = int(fields[6]) if len(fields) > 6 else 0
                softirq = int(fields[7]) if len(fields) > 7 else 0
                
                total = user + nice + system + idle + iowait + irq + softirq
                return total, idle
            return None, None

        now = time.time()
        cur_total, cur_idle = _read_cpu_stats()
        
        if cur_total is not None and cur_idle is not None:
            if _CPU_PREV_TOTAL is not None and _CPU_PREV_IDLE is not None and _CPU_PREV_TS is not None:
                dt = max(0.001, now - _CPU_PREV_TS)
                total_delta = cur_total - _CPU_PREV_TOTAL
                idle_delta = cur_idle - _CPU_PREV_IDLE
                
                if total_delta > 0:
                    cpu_percent = ((total_delta - idle_delta) / total_delta) * 100.0
                    cpu_percent = max(0.0, min(100.0, cpu_percent))  # 限制在 0-100
            
            _CPU_PREV_TOTAL = cur_total
            _CPU_PREV_IDLE = cur_idle
            _CPU_PREV_TS = now
    except Exception:
        cpu_percent = 0.0

    # 7) 数据库连接池状态 (轻量级，每次获取)
    db_status = {}
    try:
        from sql.database_postgresql import db
        # 统一使用 get_pool_status 获取状态
        status = db.get_pool_status()
        
        db_status = {
            "pool_usage": status["usage_rate"],
            "checked_out": status["checked_out"],
            "checked_in": status["checked_in"],
            "pool_size": status["pool_size"],
            "max_overflow": status["max_overflow"],
            "overflow": status["overflow"],
            # 前端可能还需要 total_connections 来比对，如果有的话也可以从API加，
            # 但这里是 metrics snapshot，保持轻量级，只返回 dict
        }
    except Exception:
        pass

    # 8) Supervisor 状态 (带缓存，5秒刷新一次)
    global _SUPERVISOR_CACHE, _SUPERVISOR_LAST_TS
    try:
        _SUPERVISOR_CACHE
    except NameError:
        _SUPERVISOR_CACHE = []
        _SUPERVISOR_LAST_TS = 0
    
    supervisor_data = _SUPERVISOR_CACHE
    if time.time() - _SUPERVISOR_LAST_TS > 5:
        try:
            import subprocess

            def _fetch_supervisor_status_sync():
                try:
                    result = subprocess.run(
                        ['supervisorctl', 'status'],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode != 0:
                        return None
                    new_services = []
                    for line in result.stdout.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split()
                        if len(parts) < 2:
                            continue
                        new_services.append({
                            "name": parts[0],
                            "state": parts[1]
                        })
                    return new_services
                except Exception:
                    return None

            loop = asyncio.get_running_loop()
            new_services = await loop.run_in_executor(None, _fetch_supervisor_status_sync)
            if new_services is not None:
                _SUPERVISOR_CACHE = new_services
                supervisor_data = new_services
                _SUPERVISOR_LAST_TS = time.time()
        except Exception:
            pass

    # 9) 直播统计 (带缓存，10秒刷新一次)
    global _LIVE_STATS_CACHE, _LIVE_STATS_LAST_TS
    try:
        _LIVE_STATS_CACHE
    except NameError:
        # 初始化时尝试获取 total_size
        initial_total_size = 0
        try:
            from live import routers as live_routers
            initial_total_size = live_routers._stats_data.get("total_size", 0)
        except Exception:
            pass
        _LIVE_STATS_CACHE = {
            "total_subscriptions": 0, "paused_count": 0, "invalid_count": 0, "live_count": 0, "recording_count": 0, "today_records": 0, "total_size": initial_total_size
        }
        _LIVE_STATS_LAST_TS = 0
        
    live_stats_data = _LIVE_STATS_CACHE
    
    # 检查授权状态：如果未授权，强制返回0，也不更新缓存
    from routers.license import license_manager
    is_licensed = await license_manager.verify()
    
    if not is_licensed:
        live_stats_data = {
            "total_subscriptions": 0, "paused_count": 0, "invalid_count": 0, "live_count": 0, "recording_count": 0, "today_records": 0, "total_size": 0
        }
    elif time.time() - _LIVE_STATS_LAST_TS > 10:
        try:
            def _fetch_live_stats_sync():
                try:
                    from sql.database_postgresql import get_db
                    from sql.models import LiveSubscription, LiveRecord
                    from live.recorder import live_recorder
                    from datetime import date, datetime as dt_class
                    
                    db_session = next(get_db())
                    try:
                        total_subs = db_session.query(LiveSubscription).count()
                        live_count = db_session.query(LiveSubscription).filter(LiveSubscription.is_live == "true").count()
                        
                        recording_ids = live_recorder.get_all_recording_ids()
                        rec_count = len(recording_ids)
                        
                        today_start = dt_class.combine(date.today(), dt_class.min.time())
                        today_recs = db_session.query(LiveRecord).filter(LiveRecord.start_time >= today_start).count()
                        
                        # 从 live.routers 获取 total_size
                        t_size = 0
                        try:
                            from live import routers as live_routers
                            t_size = live_routers._stats_data.get("total_size", 0)
                        except Exception:
                            pass

                        # 监控状态统计
                        disabled_all = db_session.query(LiveSubscription).filter(
                            LiveSubscription.monitor_enabled == "false"
                        ).count()
                        invalid_count = db_session.query(LiveSubscription).filter(
                            LiveSubscription.monitor_enabled == "false",
                            cast(LiveSubscription.extra_data, String).like('%auto_disabled%')
                        ).count()
                        paused_count = disabled_all - invalid_count

                        return {
                            "total_subscriptions": total_subs,
                            "paused_count": paused_count,
                            "invalid_count": invalid_count,
                            "live_count": live_count,
                            "recording_count": rec_count,
                            "today_records": today_recs,
                            "total_size": t_size
                        }
                    finally:
                         db_session.close()
                except Exception:
                    return None
            
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, _fetch_live_stats_sync)
            if res:
                _LIVE_STATS_CACHE = res
                live_stats_data = res
                _LIVE_STATS_LAST_TS = time.time()
        except Exception:
            pass

    # 10) 存储使用情况 (使用 routers.system 预热好的缓存)
    try:
        from routers.system import _storage_cache as system_storage
        storage_data = {
            "total_gb": system_storage.get("total_gb", 0),
            "used_gb": system_storage.get("used_gb", 0),
            "free_gb": system_storage.get("free_gb", 0),
            "usage_percentage": system_storage.get("usage_percentage", 0),
            "directory_size_bytes": system_storage.get("directory_size_bytes", 0)
        }
    except Exception:
        storage_data = {
            "total_gb": 0, "used_gb": 0, "free_gb": 0, "usage_percentage": 0, "directory_size_bytes": 0
        }

    # 11) 授权信息 (从 license_manager 获取，轻量级读取)
    license_data = {}
    try:
        from routers.license import license_manager, LicenseStatus
        license_data = {
            "is_licensed": license_manager.status == LicenseStatus.VALID,
            "status": license_manager.status,
            "remaining_days": license_manager.remaining_days
        }
    except Exception:
        pass  # 如果获取失败，使用空对象

    # 12) 网络连通性检测 (带缓存，30秒刷新一次，避免频繁HTTP请求)
    global _NETWORK_CACHE, _NETWORK_LAST_TS
    try:
        _NETWORK_CACHE
    except NameError:
        _NETWORK_CACHE = {
            "youtube": {"status": "checking", "latency_ms": 0},
            "bilibili": {"status": "checking", "latency_ms": 0}
        }
        _NETWORK_LAST_TS = 0
    
    network_data = _NETWORK_CACHE
    # 如果缓存未初始化（_NETWORK_LAST_TS == 0）或超过30秒，则执行检测
    if _NETWORK_LAST_TS == 0 or time.time() - _NETWORK_LAST_TS > 30:
        try:
            import httpx
            
            async def check_site(url: str, timeout: float = 5.0) -> dict:
                """检测单个站点的连通性"""
                try:
                    start_time = time.time()
                    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                        response = await client.get(url, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        })
                        latency_ms = int((time.time() - start_time) * 1000)
                        
                        if response.status_code < 400:
                            return {
                                "status": "ok",
                                "latency_ms": latency_ms,
                                "status_code": response.status_code
                            }
                        else:
                            return {
                                "status": "error",
                                "latency_ms": latency_ms,
                                "status_code": response.status_code,
                                "message": f"HTTP {response.status_code}"
                            }
                except httpx.TimeoutException:
                    return {
                        "status": "timeout",
                        "latency_ms": int(timeout * 1000),
                        "message": "连接超时"
                    }
                except Exception as e:
                    return {
                        "status": "failed",
                        "latency_ms": 0,
                        "message": str(e)
                    }
            
            # 并发检测两个站点
            youtube_task = check_site("https://www.youtube.com")
            bilibili_task = check_site("https://www.bilibili.com")
            
            youtube_result, bilibili_result = await asyncio.gather(
                youtube_task, bilibili_task, return_exceptions=True
            )
            
            # 处理异常情况
            if isinstance(youtube_result, Exception):
                youtube_result = {"status": "failed", "latency_ms": 0, "message": str(youtube_result)}
            if isinstance(bilibili_result, Exception):
                bilibili_result = {"status": "failed", "latency_ms": 0, "message": str(bilibili_result)}
            
            network_data = {
                "youtube": youtube_result,
                "bilibili": bilibili_result
            }
            _NETWORK_CACHE = network_data
            _NETWORK_LAST_TS = time.time()
        except Exception:
            pass  # 如果检测失败，使用缓存数据

    # 13) 最近活动（使用 routers.system 预热好的缓存）
    try:
        from routers.system import _recent_activity_cache as system_recent_activity
        recent_activity_data = system_recent_activity
    except Exception:
        recent_activity_data = []

    # 14) 公告状态和版本信息 (带缓存，60秒刷新一次，避免频繁HTTP请求)
    global _ANNOUNCEMENT_CACHE, _ANNOUNCEMENT_LAST_TS
    try:
        _ANNOUNCEMENT_CACHE
    except NameError:
        _ANNOUNCEMENT_CACHE = {
            "has_unread_notice": False,
            "pending": False,
            "latest_version": 0,
            "ack_version": 0,
            "current_version": "Unknown",
            "latest_app_version": None,
            "has_app_update": False
        }
        _ANNOUNCEMENT_LAST_TS = 0
    
    announcement_data = _ANNOUNCEMENT_CACHE
    if time.time() - _ANNOUNCEMENT_LAST_TS > 60:
        try:
            from sql.database_postgresql import db
            import re
            import os
            import json as json_lib
            
            # 1. 获取公告状态（从 global_config）
            try:
                rows = await db.execute_query(
                    "SELECT value FROM global_config WHERE key = :k",
                    {"k": "announcement_state"}
                )
                state = {}
                if rows:
                    try:
                        state = json_lib.loads(rows[0].get("value") or "{}")
                    except Exception:
                        pass
                
                latest_version = int(state.get("latest_version") or 0)
                ack_version = int(state.get("ack_version") or 0)
                pending = latest_version > ack_version
                
                announcement_data["pending"] = pending
                announcement_data["has_unread_notice"] = pending
                announcement_data["latest_version"] = latest_version
                announcement_data["ack_version"] = ack_version
            except Exception:
                pass
            
            # 2. 获取当前应用版本（从 build-version.json）
            try:
                version_file_path = os.path.join("data", "build-version.json")
                if os.path.exists(version_file_path):
                    with open(version_file_path, "r", encoding="utf-8") as f:
                        data = json_lib.load(f)
                        announcement_data["current_version"] = data.get("version", "Unknown")
            except Exception:
                pass
            
            # 3. 获取最新公告并解析版本号（从社区服务器）
            try:
                import httpx
                remote_url = "https://easy-vdl.921217.xyz/public/announcements"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(remote_url, params={"limit": 1})
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("items", [])
                        if items and len(items) > 0:
                            first_ann = items[0]
                            content = first_ann.get("content", "")
                            # 解析版本号：匹配 "版本号：v20250915.192920"
                            version_match = re.search(r'版本号[：:]\s*(v[\d.]+)', content, re.IGNORECASE)
                            if version_match:
                                remote_version = version_match.group(1)
                                announcement_data["latest_app_version"] = remote_version
                                current_ver = announcement_data["current_version"]
                                if current_ver and current_ver != "Unknown":
                                    announcement_data["has_app_update"] = current_ver != remote_version
            except Exception:
                pass  # 如果获取失败，使用缓存数据
            
            _ANNOUNCEMENT_CACHE = announcement_data
            _ANNOUNCEMENT_LAST_TS = time.time()
        except Exception:
            pass  # 如果获取失败，使用缓存数据

    # 15) GPU 监控（后台异步刷新，快照仅读缓存不阻塞）
    await _refresh_gpu_cache_nonblocking()
    async with _gpu_cache_lock:
        gpu_data = _GPU_CACHE

    return {
        "uptime_seconds": uptime_seconds,
        "memory_mb": round(memory_mb, 1),
        "memory_limit_mb": round(memory_limit_mb, 1),
        "downloads": {
            "downloading": int(downloading),
            "queued": int(queued),
            "completed": int(completed),
            "failed": int(failed),
            "active_subscriptions": int(active_subscription_count)
        },
        "net": net,
        "cpu_percent": round(cpu_percent, 1),
        "watchdog": {"cleanup_count": int(watchdog_count)},
        "browsers": browsers,
        "database": db_status,
        "supervisor": supervisor_data,
        "live_stats": live_stats_data,
        "storage": storage_data,
        "license": license_data,
        "network": network_data,
        "recent_activity": recent_activity_data,
        "announcement": announcement_data,
        "gpu_stats": gpu_data
    }
