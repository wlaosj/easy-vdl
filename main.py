import os
import logging
import traceback
import sys
import subprocess
import shutil
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

# 导入各个模块的APIRouter
from routers import dyd, ytd, file_manager, ai_config, wnxt, version, subscribe, license, auth, setup, system, cookie_manager, notifications, backup, xiaohongshu, cache, telegram_media
from routers.wecom_bot import router as wecom_bot_router
from sql.database_postgresql import get_db  # 导入PostgreSQL数据库模块
from fastapi.staticfiles import StaticFiles
import time

# 在文件开头导入
from routers.douyin import douyin_api
from routers.youtube import youtube_api  # 添加YouTube API导入
from routers.scheduler import scheduler
from routers.downloader import download_manager
from routers.websocket import router as websocket_router  # 添加websocket导入

# 全局变量 (wnxt service)
wnxt.captured_media = {}  # 确保在主应用中是全局的

# 企业微信回调专用服务器
_wecom_callback_server = None

# 导入数据库和模型
from sql.database_postgresql import get_db
from sql import models

# --- 日志配置已统一交给supervisor管理 ---
# 使用标准的logging模块，避免与supervisor配置冲突
logger = logging.getLogger(__name__)

# --- FastAPI 应用初始化 ---
app = FastAPI(title="Easy-VDL Unified Service", description="统一的视频下载与文件管理服务")

# 注册路由
app.include_router(version.router)  # 社区公共API代理/公告相关
try:
    app.include_router(version.local_router)  # 本地直达端点，避免被反代到社区
except Exception:
    pass

# --- CORS 中间件配置 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 全局轻量后台内存回收（gc） ---
_global_gc_task = None
_image_cache_cleanup_task = None


async def _background_gc_loop():
    import gc
    while True:
        try:
            # 轻量周期性回收，避免打扰业务：空闲时也只做一次简单 gc
            await asyncio.sleep(3600)  # 调整为 60 分钟，降低频率
            collected = gc.collect()
            if collected > 0:
                logger.info(f"后台GC清理了 {collected} 个对象")
                # 将全局轻量GC的实际清理次数计入原看门狗计数文件
                try:
                    count_file = '/tmp/easy_vdl_watchdog_count'
                    current = 0
                    if os.path.exists(count_file):
                        try:
                            with open(count_file, 'r') as f:
                                current = int((f.read() or '0').strip() or '0')
                        except Exception:
                            current = 0
                    with open(count_file, 'w') as f:
                        f.write(str(current + 1))
                except Exception as e:
                    # 写计数失败不影响主流程
                    logger.warning(f"写入GC计数失败: {e}")

            # 在GC之后尝试让glibc归还未使用的堆内存
            try:
                import ctypes
                libc = ctypes.CDLL("libc.so.6")
                trim_result = int(libc.malloc_trim(0))  # 1=有归还，0=无可归还
                logger.info(f"后台malloc_trim(0)执行完成，result={trim_result}")
            except Exception as e:
                # 失败不影响主流程，只记录
                logger.info(f"后台malloc_trim(0)执行失败: {str(e)}")
        except asyncio.CancelledError:
            break
        except Exception:
            # 静默失败，不影响主流程
            pass


def _run_image_cache_cleanup_once():
    """执行一次图片缓存清理（阈值触发 + 可选按文件年龄清理）。"""
    cache_path = os.getenv("IMAGE_CACHE_PATH", "/tmp/image_cache")
    if not os.path.isdir(cache_path):
        return

    try:
        max_mb = int(os.getenv("IMAGE_CACHE_MAX_MB", "500"))
    except Exception:
        max_mb = 500
    try:
        target_mb = int(os.getenv("IMAGE_CACHE_TARGET_MB", "200"))
    except Exception:
        target_mb = 200
    try:
        max_age_days = int(os.getenv("IMAGE_CACHE_MAX_AGE_DAYS", "14"))
    except Exception:
        max_age_days = 14

    max_mb = max(50, max_mb)
    target_mb = max(20, min(target_mb, max_mb))
    max_bytes = max_mb * 1024 * 1024
    target_bytes = target_mb * 1024 * 1024

    files = []
    total_size = 0
    now = time.time()
    removed_count = 0
    removed_size = 0

    for name in os.listdir(cache_path):
        file_path = os.path.join(cache_path, name)
        if not os.path.isfile(file_path):
            continue
        try:
            stat = os.stat(file_path)
        except Exception:
            continue
        size = stat.st_size
        mtime = stat.st_mtime
        total_size += size
        files.append((file_path, size, mtime))

    # 第一阶段：按文件年龄清理（默认 14 天）
    if max_age_days > 0:
        expire_before = now - (max_age_days * 24 * 3600)
        for file_path, size, mtime in files:
            if mtime >= expire_before:
                continue
            try:
                os.remove(file_path)
                total_size -= size
                removed_count += 1
                removed_size += size
            except Exception:
                continue
        # 重新收集，避免后续按大小阶段访问已删除文件
        files = []
        for name in os.listdir(cache_path):
            file_path = os.path.join(cache_path, name)
            if not os.path.isfile(file_path):
                continue
            try:
                stat = os.stat(file_path)
                files.append((file_path, stat.st_size, stat.st_mtime))
            except Exception:
                continue

    # 第二阶段：超过上限时，按最旧文件淘汰到目标水位
    if total_size > max_bytes:
        files.sort(key=lambda x: x[2])  # mtime 从旧到新
        for file_path, size, _mtime in files:
            if total_size <= target_bytes:
                break
            try:
                os.remove(file_path)
                total_size -= size
                removed_count += 1
                removed_size += size
            except Exception:
                continue

    if removed_count > 0:
        logger.info(
            f"图片缓存清理完成: 删除 {removed_count} 个文件, 释放 {removed_size // 1024 // 1024}MB, "
            f"当前约 {total_size // 1024 // 1024}MB"
        )


async def _image_cache_cleanup_loop():
    """后台图片缓存清理循环（独立于内存 GC）。"""
    try:
        interval = int(os.getenv("IMAGE_CACHE_CLEANUP_INTERVAL_SECONDS", "21600"))
    except Exception:
        interval = 21600
    interval = max(600, interval)
    logger.info(f"图片缓存清理任务已启动, interval={interval}s")

    while True:
        try:
            _run_image_cache_cleanup_once()
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"图片缓存清理任务异常: {str(e)}")
            await asyncio.sleep(interval)

# --- 全局异常处理 ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"全局错误处理: {str(exc)}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"参数校验失败: {exc.errors()}")
    try:
        body = await request.json()
        logger.error(f"请求体: {body}")
    except Exception:
        logger.error("无法解析请求体")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()}
    )

# --- 启动/关闭事件 ---
async def _init_license_async():
    """后台异步初始化授权服务"""
    try:
        success = await license.initialize_license_service()
        if not success:
            logger.warning("授权服务初始化失败，部分功能可能不可用")
    except Exception as e:
        logger.error(f"授权服务初始化异常: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info("Easy-VDL Unified Service 启动中...")
    logger.info("VNC安全策略: /websockify 已启用 JWT 鉴权闸门（需先登录UI）")
    try:
        from routers import websocket as ws
        ws.set_main_event_loop(asyncio.get_running_loop())
    except Exception:
        pass
    
    # 给PostgreSQL一些启动时间，避免时序竞争
    initial_wait_seconds = 2
    logger.info(f"等待 {initial_wait_seconds} 秒让PostgreSQL完成启动...")
    await asyncio.sleep(initial_wait_seconds)
    
    # 等待PostgreSQL就绪，最多等待60秒
    max_retries = 60
    postgresql_initialized = False
    
    for attempt in range(max_retries):
        try:
            logger.info(f"正在尝试连接PostgreSQL... (第{attempt + 1}次)")
            from sql.database_postgresql import init_database
            await init_database()
            logger.info("PostgreSQL数据库初始化完成")
            postgresql_initialized = True
            break
        except Exception as e:
            if attempt < max_retries - 1:
                # 第一次重试等待时间较短，后续重试等待时间较长
                wait_time = 1 if attempt == 0 else 2
                logger.warning(f"PostgreSQL连接失败，等待{wait_time}秒后重试: {str(e)}")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"PostgreSQL数据库连接失败，已达到最大重试次数: {str(e)}")
                raise Exception("PostgreSQL数据库连接失败，无法启动服务")
    
    if not postgresql_initialized:
        logger.error("PostgreSQL数据库初始化失败，服务无法启动")
        raise Exception("PostgreSQL数据库初始化失败")
    
    # 检查并创建环境变量用户（如果设置了环境变量且数据库中没有用户）
    try:
        from sql.models import User
        from routers.auth import apply_env_override_to_database
        from sql.database_postgresql import get_db
        
        # 检查数据库中是否有用户
        db = next(get_db())
        try:
            user_count = db.query(User).count()
            
            # 如果数据库中没有用户且设置了环境变量，则创建用户
            if user_count == 0:
                env_username = os.getenv("EASY_VDL_ADMIN_USERNAME")
                env_password = os.getenv("EASY_VDL_ADMIN_PASSWORD")
                
                if env_username and env_password:
                    logger.info(f"检测到环境变量用户配置，正在创建管理员用户: {env_username}")
                    success = apply_env_override_to_database(db)
                    if success:
                        logger.info("✅ 环境变量用户创建成功")
                    else:
                        logger.warning("⚠️ 环境变量用户创建失败")
                else:
                    logger.info("未设置环境变量用户，系统将等待首次注册")
            else:
                logger.info(f"数据库中已有 {user_count} 个用户，跳过环境变量用户创建")
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"环境变量用户创建检查失败: {str(e)}")
    
    # 清理卡住的同步、批量下载状态和下载任务
    try:
        from sql.models import Subscription, Task, SubscriptionVideo, TaskStatus
        from sql.database_postgresql import get_db
        from sqlalchemy import or_, func
        
        logger.info("正在清理卡住的同步、批量下载状态和下载任务...")
        db = next(get_db())
        
        # 清理卡住的同步状态
        stuck_sync_subs = db.query(Subscription).filter(
            Subscription.sync_status == "syncing"
        ).all()
        
        for sub in stuck_sync_subs:
            logger.info(f"清理订阅 {sub.nickname} 的卡住的同步状态")
            sub.sync_status = None
            sub.sync_progress = 0
        
        # 清理所有进行中的下载任务（标记为失败，不删除记录）
        active_tasks = db.query(Task).filter(
            Task.status.in_([
                TaskStatus.PENDING.value,
                TaskStatus.DOWNLOADING.value,
                TaskStatus.PROCESSING.value
            ])
        ).all()
        
        task_count = len(active_tasks)
        failed_task_ids = []
        for task in active_tasks:
            task.status = TaskStatus.ERROR.value
            task.error_message = "Docker重启导致任务中断"
            task.updated_at = func.now()
            failed_task_ids.append(task.id)
        
        # 只重置关联到中断任务的订阅视频下载状态
        # 注意：保留download_task_id，这样重试时可以复用原task_id
        downloading_videos = db.query(SubscriptionVideo).filter(
            or_(
                SubscriptionVideo.download_task_id.in_(failed_task_ids),
                SubscriptionVideo.downloaded == 'downloading'
            )
        ).all()
        
        video_count = len(downloading_videos)
        for video in downloading_videos:
            # 不清除download_task_id，保留与Task的关联，便于重试时复用
            video.downloaded = 'false'
            video.error_message = "Docker重启导致下载中断，可重新下载"
        
        # 清理卡住的批量下载状态（包括 "downloading" 和 "cancelling"）
        stuck_download_subs = db.query(Subscription).filter(
            Subscription.batch_download_status.in_(["downloading", "cancelling"])
        ).all()
        
        for sub in stuck_download_subs:
            logger.info(f"清理订阅 {sub.nickname} 的卡住的批量下载状态")
            sub.batch_download_status = None
            sub.batch_download_progress = 0
            sub.batch_download_total = 0
            sub.batch_download_completed = 0
            sub.batch_download_failed = 0
            sub.batch_download_start_time = None
        
        # 提交所有更改
        if stuck_sync_subs or active_tasks or downloading_videos or stuck_download_subs:
            db.commit()
            logger.info(f"🔄 Docker重启系统清理完成："
                       f"标记中断任务为失败 {task_count} 个，"
                       f"重置视频下载状态 {video_count} 个，"
                       f"清理同步状态 {len(stuck_sync_subs)} 个，"
                       f"清理批量下载 {len(stuck_download_subs)} 个")
        else:
            logger.info("✅ 没有卡住的状态需要清理")
        
        db.close()
    except Exception as e:
        logger.error(f"清理卡住的状态失败: {str(e)}")
    
    # 清理残留的Chrome进程（保留，因为临时目录策略只解决锁文件问题，进程清理仍有必要）
    try:
        # 清理Chrome进程
        chrome_process_commands = [
            ['pkill', '-f', 'chrome'],
            ['pkill', '-f', 'chromium'],
            ['pkill', '-f', 'google-chrome'],
            ['pkill', '-f', 'chromium-browser']
        ]
        
        for cmd in chrome_process_commands:
            try:
                subprocess.run(cmd, check=False, capture_output=True, text=True)
            except Exception:
                pass  # 静默处理清理命令失败
        
        logger.debug("Chrome进程清理完成")
    except Exception as e:
        logger.error(f"清理Chrome进程失败: {str(e)}")
    
    # 确保Chrome数据目录存在（统一浏览器架构）
    try:
        chrome_dir = "/app/database/chrome"
        unified_dir = os.path.join(chrome_dir, "unified")
        os.makedirs(chrome_dir, exist_ok=True)
        os.makedirs(unified_dir, exist_ok=True)
        os.chmod(chrome_dir, 0o755)
        os.chmod(unified_dir, 0o755)
        logger.debug("Chrome数据目录已确保存在（统一浏览器架构）")
    except Exception as e:
        logger.error(f"创建Chrome数据目录失败: {str(e)}")

    # 确保必要的目录存在
    directories = [
        "/app/downloads",
        "/app/downloads/douyin",
        "/app/downloads/xiaohongshu",
        "/app/downloads/youtube",
        "/app/downloads/others",
        "/app/logs",
        "/app/sockets",
        "/app/database",
        "/app/cache"
    ]
    
    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
        except Exception as e:
            logger.error(f"创建目录失败 {directory}: {str(e)}")
    
    logger.debug("应用目录结构已确保存在")

    # 初始化YTD服务
    try:
        # logger.info("正在初始化YTD服务...")
        success = await ytd.initialize_ytd_service()
        if success:
            logger.debug("YTD服务初始化成功")
        else:
            logger.warning("YTD服务初始化失败")
    except Exception as e:
        logger.error(f"YTD服务初始化异常: {str(e)}")

    # 初始化授权服务（阻塞等待完成，避免调度器启动时误判授权失效）
    try:
        await _init_license_async()
    except Exception as e:
        logger.error(f"授权服务初始化异常: {str(e)}")
    
    # 启动订阅调度器
    try:
        logger.debug("正在启动订阅调度器...")
        await scheduler.start()
        logger.info("订阅调度器启动成功")
    except Exception as e:
        logger.error(f"订阅调度器启动失败: {str(e)}")
        
    # 启动下载管理器
    try:
        logger.debug("正在启动下载管理器...")
        await download_manager.start()
        logger.info("下载管理器启动成功")
    except Exception as e:
        logger.error(f"下载管理器启动失败: {str(e)}")
    
    # 启动各API的worker任务（确保只启动一次）
    try:
        logger.debug("正在启动各API的worker任务...")
        # 启动抖音API worker
        await douyin_api.start_worker()
        logger.info("抖音API worker已启动")
        
        # 启动YouTube API worker
        await youtube_api.start_worker()
        logger.info("YouTube API worker已启动")
        
        # 启动B站API worker
        from routers.bilibili import bilibili_api
        await bilibili_api.start_worker()
        logger.info("B站API worker已启动")
        
        logger.info("所有API worker启动完成")
    except Exception as e:
        logger.error(f"启动API worker失败: {str(e)}")
    
    # 启动全局轻量 gc 循环（静默后台，不影响业务）
    try:
        global _global_gc_task
        if _global_gc_task is None or _global_gc_task.done():
            _global_gc_task = asyncio.create_task(_background_gc_loop())
    except Exception:
        pass

    # 启动图片缓存清理循环（与内存GC解耦）
    try:
        cleanup_enabled = os.getenv("IMAGE_CACHE_CLEANUP_ENABLED", "true").lower() in ("1", "true", "yes", "on")
        if cleanup_enabled:
            global _image_cache_cleanup_task
            if _image_cache_cleanup_task is None or _image_cache_cleanup_task.done():
                _image_cache_cleanup_task = asyncio.create_task(_image_cache_cleanup_loop())
        else:
            logger.info("图片缓存清理任务已禁用 (IMAGE_CACHE_CLEANUP_ENABLED=false)")
    except Exception as e:
        logger.warning(f"启动图片缓存清理任务失败: {str(e)}")

# （已移除：指标采集与WS广播在 routers.websocket 中实现）

# 注：WS 推送改为在 routers.websocket 中按连接推送，这里不再全局广播

    # 启动社区公告SSE连接
    try:
        from routers.version import start_sse_connection
        await start_sse_connection()
        logger.debug("社区公告SSE连接任务已创建")
    except Exception as e:
        logger.error(f"启动社区公告SSE连接失败: {e}")

    # （已移除）智能内存清理看门狗启动
    
    # 启动内存数据采集
    # try:
    #     from routers.system import start_memory_collection
    #     start_memory_collection()
    #     logger.info("内存数据采集已启动")
    # except Exception as e:
    #     logger.warning(f"启动内存数据采集失败: {str(e)}")
    
    # 进度缓存刷新任务已移除，无需处理

    # 初始化统一浏览器管理器（懒加载模式）
    try:
        from routers.unified_browser_manager import unified_browser
        # 懒加载说明仅在调试时关注
        logger.debug("统一浏览器管理器采用懒加载模式（首次使用时自动初始化）")
        # 不在启动时初始化浏览器，首次使用时自动初始化
        # await unified_browser.init_browser()
        
        # 启动自动清理任务
        await unified_browser.start_cleanup_task()
        logger.info("✅ 统一浏览器自动清理任务已启动")
    except Exception as e:
        logger.error(f"统一浏览器管理器初始化异常: {str(e)}")
    
    # 初始化DYD浏览器管理器的后台清理任务
    try:
        from routers.dyd import browser_manager as dyd_browser_manager
        await dyd_browser_manager.start_cleanup_task()
        logger.info("✅ DYD浏览器自动清理任务已启动")
    except Exception as e:
        logger.error(f"DYD浏览器管理器初始化异常: {str(e)}")
    
    # 启动 Telegram 机器人
    try:
        from routers.telegram_bot import telegram_bot
        await telegram_bot.start()
    except Exception as e:
        logger.error(f"Telegram 机器人启动失败: {e}")

    # 启动企业微信应用Bot
    try:
        from routers.wecom_bot import wecom_bot
        await wecom_bot.start()
        # 启动企业微信回调专用端口（无论是否启用，等待回调验证时需要）
        wecom_callback_port = int(os.environ.get("WECOM_CALLBACK_PORT", "8001"))
        import uvicorn as _uvicorn
        from fastapi import FastAPI as _FastAPI
        wecom_app = _FastAPI()
        wecom_app.include_router(wecom_bot_router)
        _wecom_callback_server = _uvicorn.Server(_uvicorn.Config(wecom_app, host="0.0.0.0", port=wecom_callback_port, log_level="warning"))
        asyncio.create_task(_wecom_callback_server.serve())
        logger.info(f"企业微信回调专用端口已启动: {wecom_callback_port}")
    except Exception as e:
        logger.error(f"企业微信Bot启动失败: {e}")

    # 启动直播录制调度器
    try:
        from live.scheduler import live_scheduler
        from sql.database_postgresql import get_session
        live_scheduler.set_db_session_factory(get_session)
        await live_scheduler.start()
        logger.info("直播录制调度器已启动")
    except Exception as e:
        logger.error(f"直播录制调度器启动失败: {e}")
    
    logger.info("Easy-VDL Unified Service 启动完成")
    


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    # 停止订阅调度器
    try:
        logger.info("正在停止订阅调度器...")
        await scheduler.stop()
        logger.info("订阅调度器已停止")
    except Exception as e:
        logger.error(f"停止订阅调度器失败: {str(e)}")
    
    # 停止下载管理器
    try:
        logger.info("正在停止下载管理器...")
        await download_manager.stop()
        logger.info("下载管理器已停止")
    except Exception as e:
        logger.error(f"停止下载管理器失败: {str(e)}")
    
    # 停止各API的worker任务
    try:
        logger.info("正在停止各API的worker任务...")
        await douyin_api.stop_worker()
        await youtube_api.stop_worker()
        
        from routers.bilibili import bilibili_api
        await bilibili_api.stop_worker()
        logger.info("所有API worker已停止")
    except Exception as e:
        logger.error(f"停止API worker失败: {str(e)}")

    # 关闭统一浏览器管理器
    try:
        from routers.unified_browser_manager import unified_browser
        logger.info("正在关闭统一浏览器管理器...")
        await unified_browser.stop_cleanup_task()
        await unified_browser.close_browser()
        logger.info("✅ 统一浏览器管理器已关闭")
    except Exception as e:
        logger.error(f"关闭统一浏览器管理器失败: {str(e)}")
    
    # 关闭DYD浏览器管理器
    try:
        from routers.dyd import browser_manager as dyd_browser_manager
        logger.info("正在关闭DYD浏览器管理器...")
        await dyd_browser_manager.stop_cleanup_task()
        await dyd_browser_manager.close()
        logger.info("✅ DYD浏览器管理器已关闭")
    except Exception as e:
        logger.error(f"关闭DYD浏览器管理器失败: {str(e)}")
    
    # 停止直播录制调度器
    try:
        from live.scheduler import live_scheduler
        logger.info("正在停止直播录制调度器...")
        await live_scheduler.stop()
        logger.info("直播录制调度器已停止")
    except Exception as e:
        logger.error(f"停止直播录制调度器失败: {e}")
    
    # 关闭 Telegram 机器人
    try:
        from routers.telegram_bot import telegram_bot
        await telegram_bot.stop()
    except Exception as e:
        logger.error(f"关闭 Telegram 机器人失败: {e}")

    # 关闭企业微信应用Bot
    try:
        from routers.wecom_bot import wecom_bot
        await wecom_bot.stop()
        # 关闭企业微信回调专用端口
        if _wecom_callback_server is not None:
            _wecom_callback_server.should_exit = True
            logger.info("企业微信回调专用端口已停止")
    except Exception as e:
        logger.error(f"关闭企业微信Bot失败: {e}")
    
    # 清理数据库连接池
    try:
        from sql.database_postgresql import db
        if db.engine:
            db.engine.dispose()
            logger.info("数据库连接池已清理")
    except Exception as e:
        logger.error(f"清理数据库连接池失败: {str(e)}")
    
    # 强制垃圾回收
    import gc
    gc.collect()
    # 停止全局 gc 循环
    try:
        global _global_gc_task
        if _global_gc_task:
            _global_gc_task.cancel()
            _global_gc_task = None
    except Exception:
        pass

    # 停止图片缓存清理循环
    try:
        global _image_cache_cleanup_task
        if _image_cache_cleanup_task:
            _image_cache_cleanup_task.cancel()
            _image_cache_cleanup_task = None
    except Exception:
        pass
    
    # 停止进度缓存刷新任务
    try:
        if hasattr(app.state, 'progress_flush_task') and app.state.progress_flush_task:
            app.state.progress_flush_task.cancel()
            app.state.progress_flush_task = None
    except Exception:
        pass
    
    # 停止内存数据采集
    try:
        from routers.system import stop_memory_collection
        stop_memory_collection()
        logger.info("内存数据采集已停止")
    except Exception as e:
        logger.warning(f"停止内存数据采集失败: {str(e)}")
    
    # YTD进程池由操作系统管理，随容器销毁自动回收，无需显式关闭
    
    logger.info("内存清理完成")

# --- 添加路由 ---
# 认证和系统设置路由（无需认证）
app.include_router(auth.router)
app.include_router(setup.router)
app.include_router(system.router)  # 添加系统管理路由

# 其他业务路由
app.include_router(dyd.router)
app.include_router(xiaohongshu.router)  # 添加小红书路由
app.include_router(ytd.router)
app.include_router(file_manager.router)
app.include_router(ai_config.router)
app.include_router(wnxt.router, tags=["wnxt"])  # 移除prefix，因为router已经定义了前缀
app.include_router(subscribe.router)  # 添加订阅路由
app.include_router(websocket_router)  # 添加WebSocket路由
app.include_router(license.router)  # 添加授权路由
# app.include_router(background.router)  # 添加背景图片管理路由 (已删除)
app.include_router(cookie_manager.router)  # 添加cookie管理路由
app.include_router(notifications.router)  # 添加通知系统路由
app.include_router(telegram_media.router)  # Telegram 媒体入站独立路由
app.include_router(wecom_bot_router)  # 企业微信应用Bot回调路由
app.include_router(backup.router)  # 添加数据备份路由
app.include_router(cache.router)  # 添加缓存管理路由

# 在其他路由注册后添加
from routers import douyin, youtube, bilibili, tiktok, netease, xhsapi
app.include_router(douyin.router)
app.include_router(youtube.router)  # 添加YouTube路由
app.include_router(bilibili.router)  # 添加B站路由
app.include_router(tiktok.router)  # 添加TikTok路由
app.include_router(xhsapi.router)  # 添加小红书API路由
app.include_router(netease.router)  # 添加网易云路由

# 添加直播录制路由
from live.routers import router as live_router
app.include_router(live_router, prefix="/api/live", tags=["live"])
from live.highlights.router import router as live_highlights_router
app.include_router(live_highlights_router, prefix="/api/live/highlights", tags=["live-highlights"])

# --- 根路径 ---
@app.get("/api/")
async def root():
    return {"message": "Welcome to Easy-VDL Unified Service!"}

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "easy-vdl-unified-service"}

@app.get("/api/memory")
async def memory_status():
    """获取内存使用状态"""
    import psutil
    import gc
    
    # 获取当前进程信息
    process = psutil.Process()
    memory_info = process.memory_info()
    
    # 获取系统内存信息
    system_memory = psutil.virtual_memory()
    
    # 获取数据库连接信息
    db_connections = 0
    try:
        from sql.database_postgresql import db
        if db.engine:
            db_connections = db.engine.pool.size()
    except:
        pass
    
    # 获取统一浏览器管理器状态
    browser_info = {}
    try:
        from routers.unified_browser_manager import unified_browser
        browser_info = unified_browser.get_status()
    except Exception as e:
        logger.debug(f"获取浏览器状态失败: {str(e)}")
    
    return {
        "process_memory": {
            "rss": f"{memory_info.rss / 1024 / 1024:.1f} MB",
            "vms": f"{memory_info.vms / 1024 / 1024:.1f} MB",
            "percent": f"{process.memory_percent():.1f}%"
        },
        "system_memory": {
            "total": f"{system_memory.total / 1024 / 1024 / 1024:.1f} GB",
            "available": f"{system_memory.available / 1024 / 1024 / 1024:.1f} GB",
            "percent": f"{system_memory.percent:.1f}%"
        },
        "database": {
            "connections": db_connections
        },
        "browser": browser_info,
        "gc_stats": {
            "collections": gc.get_stats()
        }
    }


## （已移除：/api/metrics/mini 端点，指标仅通过WS推送）

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
