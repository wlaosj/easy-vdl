"""
网易云音乐专用解析和下载路由
使用 yt-dlp 进行网易云音乐的解析和下载
"""
import os
import asyncio
import logging
import yt_dlp
import json
import uuid
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sql.database_postgresql import get_db
from sql.models import User, Task, TaskStatus, SubscriptionVideo
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/netease", tags=["netease"])


class NeteaseParseRequest(BaseModel):
    url: str


class NeteaseDownloadRequest(BaseModel):
    url: str
    format_id: str
    song_id: Optional[str] = None  # 歌单中的歌曲ID（如果是歌单下载）


class NeteaseSongInfo(BaseModel):
    """批量下载中的单个歌曲信息"""
    url: str
    format_id: str
    song_id: str
    title: Optional[str] = None


class NeteaseBatchDownloadRequest(BaseModel):
    """批量下载请求"""
    songs: List[NeteaseSongInfo]


class NeteaseSearchRequest(BaseModel):
    """网易云搜索请求模型"""
    keyword: str
    limit: int = 20
    offset: int = 0


class NeteaseSearchSong(BaseModel):
    id: str
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: Optional[float] = None
    cover: Optional[str] = None


class NeteaseSearchResponse(BaseModel):
    songs: List[NeteaseSearchSong]
    has_more: bool = False
    total: int = 0


@router.post("/search", response_model=NeteaseSearchResponse)
async def search_netease(request: NeteaseSearchRequest, current_user: User = Depends(get_current_user)):
    """
    搜索网易云音乐歌曲（直接调用网易云官方接口）
    
    - 不再依赖外部部署的 NeteaseCloudMusicApi
    - 复用已配置的网易云 Cookie（/app/database/cookie/netease_cookie.txt），提高搜索稳定性
    - 使用官方接口 `https://music.163.com/api/search/get`
    """
    import httpx

    keyword = request.keyword.strip()
    if not keyword:
        return NeteaseSearchResponse(songs=[], has_more=False, total=0)

    params = {
        "s": keyword,
        "type": 1,  # 单曲
        "limit": max(1, min(request.limit, 50)),
        "offset": max(0, request.offset),
        "csrf_token": ""
    }

    # 注意：解析模块使用的是 Netscape 格式的 yt-dlp Cookie 文件，
    # 无法直接作为 HTTP Header 发送（会触发 "Illegal header value" 错误）。
    # 搜索接口这里暂不附加 Cookie，使用匿名搜索，避免 header 非法错误。
    headers = {
        "Referer": "https://music.163.com",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://music.163.com/api/search/get", params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        result = data.get("result") or {}
        raw_songs = result.get("songs") or []
        total = int(result.get("songCount") or len(raw_songs))

        songs: List[NeteaseSearchSong] = []
        for s in raw_songs:
            try:
                song_id = str(s.get("id"))
                name = s.get("name") or ""
                artists = s.get("ar") or s.get("artists") or []
                artist_name = ""
                if isinstance(artists, list) and artists:
                    first = artists[0]
                    if isinstance(first, dict):
                        artist_name = first.get("name", "")
                    else:
                        artist_name = str(first)
                album = ""
                al = s.get("al") or s.get("album") or {}
                if isinstance(al, dict):
                    album = al.get("name", "")
                duration_ms = s.get("dt") or s.get("duration") or 0
                duration = float(duration_ms) / 1000.0 if duration_ms else None
                cover = None
                if isinstance(al, dict):
                    cover = al.get("picUrl") or al.get("picurl")

                songs.append(NeteaseSearchSong(
                    id=song_id,
                    title=name,
                    artist=artist_name or None,
                    album=album or None,
                    duration=duration,
                    cover=cover
                ))
            except Exception as e:
                logger.warning(f"[netease_search] 跳过异常歌曲项: {e}")
                continue

    except httpx.HTTPError as e:
        logger.error(f"[netease_search] 官方接口请求失败: {e}")
        raise HTTPException(status_code=502, detail=f"网易云搜索接口不可用: {e}")
    except Exception as e:
        logger.error(f"[netease_search] 搜索出错: {e}")
        raise HTTPException(status_code=500, detail=f"网易云搜索出错: {e}")

    has_more = (request.offset + len(songs)) < total
    return NeteaseSearchResponse(songs=songs, has_more=has_more, total=total)


class NeteaseSongFormat(BaseModel):
    format_id: str
    ext: str
    resolution: str
    filesize: Optional[int] = None
    filesize_str: Optional[str] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    abr: Optional[float] = None  # 音频码率
    fps: Optional[float] = None


class NeteaseSong(BaseModel):
    id: str
    title: str
    artist: Optional[str] = None
    duration: Optional[float] = None
    thumbnail: Optional[str] = None
    webpage_url: str
    formats: List[NeteaseSongFormat]


class NeteaseParseResponse(BaseModel):
    is_playlist: bool
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    songs: Optional[List[NeteaseSong]] = None  # 歌单时的歌曲列表
    formats: Optional[List[NeteaseSongFormat]] = None  # 单曲时的格式列表
    error: Optional[str] = None


def extract_formats_from_info(info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从yt-dlp信息中提取格式列表（针对音频）"""
    formats = []
    all_formats = info.get('formats', [])
    
    if not all_formats:
        # 如果没有formats，尝试从info本身构造
        if info.get('url') and info.get('ext'):
            formats.append({
                'format_id': info.get('format_id', '0'),
                'ext': info.get('ext', 'mp3'),
                'resolution': 'audio',
                'filesize': info.get('filesize'),
                'filesize_str': info.get('filesize_str'),
                'vcodec': 'none',
                'acodec': info.get('acodec', 'unknown'),
                'abr': info.get('abr'),
                'fps': None
            })
        return formats
    
    for f in all_formats:
        has_video = f.get('vcodec') != 'none'
        has_audio = f.get('acodec') != 'none'
        
        # 跳过DRM保护的格式
        if f.get('drm') or f.get('has_drm'):
            continue
        
        # 跳过没有URL的格式
        if not f.get('url'):
            continue
        
        # 跳过fragment格式（通常不稳定）
        if f.get('fragments') or 'hls' in str(f.get('protocol', '')).lower():
            continue
        
        if has_audio and not has_video:
            # 纯音频格式
            ext = f.get('ext', 'mp3')
            abr = f.get('abr', 0)
            resolution = 'audio'
            if abr:
                resolution = f'音频 · {ext.upper()} · {int(abr)}kbps'
            
            format_item = {
                'format_id': f.get('format_id', '0'),
                'ext': ext,
                'resolution': resolution,
                'filesize': f.get('filesize'),
                'filesize_str': f.get('filesize_str'),
                'vcodec': 'none',
                'acodec': f.get('acodec', 'unknown'),
                'abr': abr,
                'fps': None
            }
            formats.append(format_item)
    
    return formats


@router.post("/parse", response_model=NeteaseParseResponse)
async def parse_netease(request: NeteaseParseRequest, current_user: User = Depends(get_current_user)):
    """解析网易云音乐链接（支持单曲和歌单）"""
    try:
        url = request.url.strip()
        
        if not url:
            raise ValueError("缺少必要的URL参数")
        
        # 检查是否为网易云链接
        if 'music.163.com' not in url:
            raise ValueError("仅支持网易云音乐链接 (music.163.com)")
        
        # 判断是否为歌单链接
        is_playlist_url = 'playlist' in url or '/#/my/m/music/' in url
        
        # yt-dlp配置
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',
            'no_cache_dir': True,
            'ignoreerrors': True,  # 对于歌单，忽略失败的条目
            'socket_timeout': 300,  # 设置300秒超时，支持大歌单解析
        }
        
        # 读取网易云音乐 Cookie（如果存在）
        try:
            netease_cookie_path = '/app/database/cookie/netease_cookie.txt'
            if os.path.exists(netease_cookie_path):
                with open(netease_cookie_path, 'r', encoding='utf-8') as f:
                    netease_cookie = f.read().strip()
                    if netease_cookie:
                        ydl_opts['cookiefile'] = netease_cookie_path
                        logger.info("网易云音乐 Cookie 已加载用于解析")
        except Exception as e:
            logger.warning(f"读取网易云音乐 Cookie 失败: {str(e)}")
            # Cookie 读取失败不影响主流程
        
        # 使用yt-dlp解析，增加重试机制
        info = None
        max_retries = 8
        last_error = None
        
        # 导入随机和异步库（如果未导入）
        import random
        import asyncio
        
        for attempt in range(max_retries):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # 使用 run_in_executor 避免阻塞主线程
                    loop = asyncio.get_event_loop()
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                
                if info:
                    break
                else:
                    # Info 为 None，视为失败，抛出异常以便进入重试逻辑
                    raise ValueError("未获取到歌曲信息 (Info is None)")

            except Exception as e:
                last_error = e
                error_str = str(e)
                logger.warning(f"[parse_netease] 解析尝试 {attempt+1}/{max_retries} 失败: {error_str}")
                
                # 检查是否为频率限制错误
                if "405" in error_str or "406" in error_str or "操作频繁" in error_str:
                    if attempt < max_retries - 1:
                        wait_time = random.uniform(3, 8)
                        logger.info(f"[parse_netease] 触发频率限制，等待 {wait_time:.1f} 秒后重试...")
                        await asyncio.sleep(wait_time)
                        continue
                
                # 其他错误（包括 info 为 None）稍作等待也重试一下
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
        
        # 如果重试多次后 info 仍为 None，且有异常，则抛出异常
        if info is None:
            if last_error:
                # 重新抛出最后一次的异常，以便后续 except 捕获处理
                raise last_error
            else:
                 # 如果没有异常但 info 为空
                 raise HTTPException(status_code=400, detail="解析失败：未获取到歌曲信息")

        # 判断是否为播放列表
        is_playlist = info.get('_type') == 'playlist' or 'entries' in info
        
        if is_playlist:
            # 处理歌单
            entries = info.get('entries', [])
            songs = []
            
            for idx, entry in enumerate(entries):
                if not entry:
                    continue
                
                try:
                    # 提取歌曲信息
                    song_id = entry.get('id') or str(idx)
                    title = entry.get('title', f'歌曲 {idx + 1}')
                    artist = entry.get('uploader') or entry.get('artist') or entry.get('creator')
                    duration = entry.get('duration')
                    thumbnail = entry.get('thumbnail')
                    webpage_url = entry.get('webpage_url') or entry.get('url') or url
                    
                    # 提取格式
                    formats = extract_formats_from_info(entry)
                    
                    if not formats:
                        # 对于 flat extraction，可能没有 formats，构造一个默认的
                        formats.append({
                            'format_id': 'best',
                            'ext': 'mp3',
                            'resolution': '自动选择最佳音质',
                            'filesize': None,
                            'filesize_str': None,
                            'vcodec': 'none',
                            'acodec': 'unknown',
                            'abr': None,
                            'fps': None
                        })
                    
                    if formats:
                        songs.append({
                            'id': song_id,
                            'title': title,
                            'artist': artist,
                            'duration': duration,
                            'thumbnail': thumbnail,
                            'webpage_url': webpage_url,
                            'formats': formats
                        })
                except Exception as e:
                    logger.warning(f"[parse_netease] 跳过失败的歌曲条目 {idx}: {str(e)}")
                    continue
            
            return NeteaseParseResponse(
                is_playlist=True,
                title=info.get('title', '网易云歌单'),
                thumbnail=info.get('thumbnail'),
                songs=songs
            )
        else:
            # 处理单曲
            formats = extract_formats_from_info(info)
            
            return NeteaseParseResponse(
                is_playlist=False,
                title=info.get('title'),
                thumbnail=info.get('thumbnail'),
                formats=formats
            )
    
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        logger.error(f"[parse_netease] yt-dlp解析失败: {error_msg}")
        raise HTTPException(status_code=400, detail=f"解析失败: {error_msg}")
    except AttributeError as e:
        error_msg = "解析失败: 可能是VIP歌曲、版权限制或Cookie失效"
        logger.error(f"[parse_netease] {error_msg}, 详情: {str(e)}")
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[parse_netease] 解析出错: {error_msg}")
        raise HTTPException(status_code=500, detail=f"解析出错: {error_msg}")


@router.post("/download")
async def download_netease(request: NeteaseDownloadRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """下载网易云音乐"""
    try:
        url = request.url.strip()
        format_id = request.format_id
        
        if not url or not format_id:
            raise ValueError("缺少必要的参数")
        
        logger.info(f"[download_netease] 收到下载请求: url={url}, format_id={format_id}")
        
        # 创建下载任务
        task_id = str(uuid.uuid4())
        try:
            task = Task(
                id=task_id,
                url=url,
                source="netease",
                status=TaskStatus.PENDING.value,
                progress=0.0,
                headers=None,
                cookie=None,  # Cookie从文件读取
                format_id=format_id,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db.add(task)
            db.commit()
            
            # 添加到下载队列
            import routers.downloader
            await routers.downloader.download_manager.add_download_task(task_id)
            
            return {
                "success": True,
                "message": "已添加到下载队列",
                "task_id": task_id
            }
            
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[download_netease] 添加下载任务失败: {error_msg}")
        raise HTTPException(status_code=500, detail=f"添加下载任务失败: {error_msg}")


@router.post("/batch-download")
async def batch_download_netease(request: NeteaseBatchDownloadRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """批量下载网易云音乐
    
    接收多个歌曲信息，后端统一创建任务并加入队列
    即使前端刷新或关闭，后端也会继续处理
    """
    try:
        if not request.songs:
            raise ValueError("歌曲列表不能为空")
        
        logger.info(f"[batch_download_netease] 收到批量下载请求: {len(request.songs)} 首歌曲")
        
        task_ids = []
        tasks_to_add = []
        success_count = 0
        fail_count = 0
        
        # 第一步: 批量创建所有Task对象(不提交数据库)
        for song in request.songs:
            try:
                task_id = str(uuid.uuid4())
                task = Task(
                    id=task_id,
                    url=song.url.strip(),
                    source="netease",
                    status=TaskStatus.PENDING.value,
                    progress=0.0,
                    headers=None,
                    cookie=None,
                    format_id=song.format_id,
                    title=song.title or f"网易云歌曲 {song.song_id}",
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                db.add(task)
                tasks_to_add.append(task_id)
                task_ids.append(task_id)
                
            except Exception as e:
                logger.error(f"[batch_download_netease] 创建任务对象失败: {song.url}, 错误: {str(e)}")
                fail_count += 1
                continue
        
        # 第二步: 一次性提交所有任务到数据库
        try:
            db.commit()
            logger.info(f"[batch_download_netease] 已批量创建 {len(tasks_to_add)} 个任务到数据库")
        except Exception as e:
            logger.error(f"[batch_download_netease] 批量提交数据库失败: {str(e)}")
            db.rollback()
            raise HTTPException(status_code=500, detail=f"批量创建任务失败: {str(e)}")
        
        # 第三步: 将任务添加到下载队列(带小延迟避免队列压力)
        import routers.downloader
        for task_id in tasks_to_add:
            try:
                await routers.downloader.download_manager.add_download_task(task_id)
                success_count += 1
                # 减少延迟时间,从0.5秒降低到0.05秒
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"[batch_download_netease] 添加任务到队列失败: {task_id}, 错误: {str(e)}")
                fail_count += 1
                continue
        
        db.close()
        
        return {
            "success": True,
            "message": f"已添加 {success_count} 个下载任务到队列" + (f"，{fail_count} 个失败" if fail_count > 0 else ""),
            "task_ids": task_ids,
            "success_count": success_count,
            "fail_count": fail_count
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[batch_download_netease] 批量下载失败: {error_msg}")
        raise HTTPException(status_code=500, detail=f"批量下载失败: {error_msg}")


async def netease_download_logic(
    task_id: str,
    url: str,
    format_id: str = None,
    download_dir: Optional[str] = None,
    subscription_id: Optional[str] = None
) -> bool:
    """网易云音乐下载逻辑（使用 yt-dlp）"""
    import asyncio
    import aiohttp
    import threading
    import random
    import time
    
    db = next(get_db())
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.error(f"[netease_download] 任务不存在: {task_id}")
            return False
        
        try:
            import yt_dlp
        except ImportError:
            logger.error("[netease_download] yt-dlp 未安装")
            task.status = TaskStatus.ERROR.value
            task.error_message = "yt-dlp 未安装"
            task.updated_at = datetime.now()
            db.commit()
            return False
        
        # 确定下载目录
        if download_dir:
            base_dir = download_dir
        elif subscription_id:
            # 订阅下载：构建订阅目录
            from routers.subscribe import get_subscription_download_dir
            db_session = next(get_db())
            try:
                task_obj = db_session.query(Task).filter(Task.id == task_id).first()
                title = task_obj.title if task_obj else "未知歌曲"
                base_dir = get_subscription_download_dir(subscription_id, title)
                if not base_dir:
                    base_dir = '/app/downloads/netease'
            finally:
                try:
                    db_session.rollback()
                except Exception:
                    pass
                db_session.close()
        else:
            # 手动下载：使用默认目录
            base_dir = '/app/downloads/netease'
        
        # 确保目录存在
        os.makedirs(base_dir, exist_ok=True)
        
        # 获取格式ID
        final_format_id = format_id or task.format_id or 'best'
        
        # 输出文件模板
        outtmpl = f'{base_dir}/{task_id}.%(ext)s'
        
        # 添加随机延迟，避免并发请求触发网易云 405/406 频率限制
        import random
        delay = random.uniform(2.0, 5.0)
        logger.debug(f"[netease_download] 延迟 {delay:.2f} 秒后开始下载，避免频率限制")
        await asyncio.sleep(delay)
        
        # 更新任务状态
        task.status = TaskStatus.DOWNLOADING.value
        task.progress = 0.0
        task.updated_at = datetime.now()
        db.commit()
        
        # 获取主事件循环，用于跨线程发送 WebSocket 消息
        try:
            main_loop = asyncio.get_running_loop()
        except RuntimeError:
            main_loop = None

        # 进度回调
        def progress_hook(d):
            if d['status'] == 'downloading':
                try:
                    if '_percent_str' in d:
                        progress_str = d['_percent_str']
                        progress = float(progress_str.replace('%', '').strip())
                    elif 'downloaded_bytes' in d and 'total_bytes' in d:
                        progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
                    elif 'downloaded_bytes' in d and 'total_bytes_estimate' in d:
                        progress = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
                    else:
                        progress = 0.0
                    
                    progress = round(max(0.0, min(100.0, progress)), 1)
                    
                    # 时间节流：每300ms更新一次
                    import time
                    current_time = time.time()
                    if not hasattr(progress_hook, 'last_update_time') or (current_time - progress_hook.last_update_time) >= 0.3 or progress >= 99.9:
                        # 1. 更新数据库（同步，阻塞当前线程，但没关系）
                        from routers.ytd import update_task_progress
                        try:
                            # 注意：update_task_progress 内部的 WS 发送在子线程可能会失败，所以我们在下面手动发送
                            update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=progress, subscription_id=subscription_id)
                        except Exception as e:
                            logger.warning(f"[netease_download] 更新数据库进度失败: {str(e)}")
                        
                        # 2. 发送 WebSocket 消息（调度回主线程）
                        if main_loop and not main_loop.is_closed():
                            from routers.websocket import broadcast_message
                            
                            async def send_ws():
                                try:
                                    # 构造只包含必要字段的消息
                                    progress_data = {
                                        'type': 'progress_update',
                                        'task': {
                                            'id': task_id,
                                            'progress': progress,
                                            'status': TaskStatus.DOWNLOADING.value,
                                            'subscription_id': subscription_id,
                                            'source': 'netease',
                                            'updated_at': datetime.now().isoformat()
                                        }
                                    }
                                    await broadcast_message('downloads', progress_data)
                                except Exception as e:
                                    logger.warning(f"[netease_download] WS发送失败: {str(e)}")

                            asyncio.run_coroutine_threadsafe(send_ws(), main_loop)
                        
                        progress_hook.last_update_time = current_time
                except (ValueError, TypeError, ZeroDivisionError):
                    pass
            elif d['status'] == 'finished':
                # finished 状态更新进度
                from routers.ytd import update_task_progress
                try:
                    update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=99.9, subscription_id=subscription_id)
                except Exception as e:
                    logger.warning(f"[netease_download] 更新完成进度失败: {str(e)}")
                
                # 手动发送 100% 进度
                if main_loop and not main_loop.is_closed():
                    from routers.websocket import broadcast_message
                    async def send_finish_ws():
                        try:
                            progress_data = {
                                'type': 'progress_update',
                                'task': {
                                    'id': task_id,
                                    'progress': 99.9,
                                    'status': TaskStatus.DOWNLOADING.value,
                                    'subscription_id': subscription_id,
                                    'source': 'netease',
                                    'updated_at': datetime.now().isoformat()
                                }
                            }
                            await broadcast_message('downloads', progress_data)
                        except Exception as e:
                            logger.warning(f"[netease_download] 完成WS发送失败: {str(e)}")
                    asyncio.run_coroutine_threadsafe(send_finish_ws(), main_loop)
        
        # yt-dlp 配置
        ydl_opts = {
            'format': final_format_id,
            'outtmpl': outtmpl,
            'progress_hooks': [progress_hook],
            'noprogress': True,
            'noplaylist': True,
            'overwrites': True,
            'no-mtime': True,
            'no_cache_dir': True,
            'retries': 3,
            'fragment_retries': 3,
            'socket_timeout': 300,  # 300秒超时
            'quiet': True,
            'no_warnings': True,
            'writethumbnail': True,  # 下载封面
            'writesubtitles': True,  # 下载歌词/字幕
            'writeautomaticsub': True, # 下载自动生成的字幕（如果有）
            'subtitleslangs': ['all'], # 下载所有语言
        }
        
        # 读取网易云音乐 Cookie（如果存在）
        try:
            netease_cookie_path = '/app/database/cookie/netease_cookie.txt'
            if os.path.exists(netease_cookie_path):
                with open(netease_cookie_path, 'r', encoding='utf-8') as f:
                    netease_cookie = f.read().strip()
                    if netease_cookie:
                        ydl_opts['cookiefile'] = netease_cookie_path
                        logger.info("网易云音乐 Cookie 已加载用于下载")
        except Exception as e:
            logger.warning(f"读取网易云音乐 Cookie 失败: {str(e)}")
            # Cookie 读取失败不影响主流程
        
        try:
            logger.info(f"[netease_download] 开始下载: task_id={task_id}, url={url}, format_id={final_format_id}")
            
            # 先提取信息以获取歌曲标题和艺术家
            song_title = None
            song_artist = None
            try:
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                    loop = asyncio.get_event_loop()
                    info = await loop.run_in_executor(None, ydl.extract_info, url, False)
                    song_title = info.get('title', '未知歌曲')
                    song_artist = info.get('uploader') or info.get('artist') or info.get('creator') or '未知艺术家'
            except Exception as e:
                logger.warning(f"[netease_download] 获取歌曲信息失败: {str(e)}")
                # 使用任务标题作为备选
                song_title = task.title or '未知歌曲'
                song_artist = '未知艺术家'
            
            # 使用 yt-dlp 下载，增加重试机制
            error_messages = []
            
            def error_hook(d):
                """捕获错误信息"""
                if d.get('status') == 'error':
                    error_messages.append(d.get('error', 'Unknown error'))
            
            ydl_opts['progress_hooks'].append(error_hook)
            
            max_retries = 8  # 增加重试次数
            for attempt in range(max_retries):
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        # 在线程池中执行下载，避免阻塞
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, ydl.download, [url])
                    # 如果下载成功（没有跑出异常），则跳出循环
                    break
                except Exception as download_error:
                    error_str = str(download_error)
                    logger.warning(f"[netease_download] yt-dlp 下载异常 (尝试 {attempt+1}/{max_retries}): {error_str}")
                    
                    # 检查是否为频率限制错误 (405 Method Not Allowed 或 406 Not Acceptable)
                    if "405" in error_str or "406" in error_str or "操作频繁" in error_str:
                        if attempt < max_retries - 1:
                            # 延长等待时间：固定 5-10 秒随机
                            wait_time = random.uniform(5, 10)
                            logger.info(f"[netease_download] 触发频率限制，等待 {wait_time:.1f} 秒后重试...")
                            await asyncio.sleep(wait_time)
                            continue
                    
                    # 如果是最后一次尝试，或者非频率错误，则记录错误并继续
                    if attempt == max_retries - 1:
                        logger.error(f"[netease_download] 最终下载失败: {error_str}")
            
            # 下载完成，查找下载的文件
            downloaded_file = None
            thumbnail_file = None
            lyric_files = [] # 存储歌词文件
            
            # 重新扫描目录查找匹配文件
            for file in os.listdir(base_dir):
                if file.startswith(task_id):
                    file_path = os.path.join(base_dir, file)
                    file_lower = file.lower()
                    if file_lower.endswith(('.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg', '.opus')):
                        downloaded_file = file_path
                    elif file_lower.endswith(('.webp', '.jpg', '.jpeg', '.png', '.image')):
                        thumbnail_file = file_path
                    elif file_lower.endswith(('.lrc', '.srt', '.vtt', '.ttml', '.smi', '.json', '.xml')):
                        # 收集歌词文件
                        lyric_files.append(file_path)
            
            if downloaded_file:
                # 使用 sanitize_filename 清理文件名
                from routers.dyd import sanitize_filename
                safe_title = sanitize_filename(song_title)
                safe_artist = sanitize_filename(song_artist)
                
                # 按艺术家分类：创建艺术家文件夹
                artist_folder = os.path.join(base_dir, safe_artist)
                os.makedirs(artist_folder, exist_ok=True)
                
                # 构造新文件名：艺术家 - 标题.ext
                file_ext = os.path.splitext(downloaded_file)[1]
                new_filename = f"{safe_artist} - {safe_title}{file_ext}"
                new_filepath = os.path.join(artist_folder, new_filename)
                
                # 重命名文件
                if os.path.exists(downloaded_file):
                    # 如果目标文件已存在，添加序号
                    counter = 1
                    original_new_filepath = new_filepath
                    while os.path.exists(new_filepath):
                        new_filename = f"{safe_artist} - {safe_title} ({counter}){file_ext}"
                        new_filepath = os.path.join(artist_folder, new_filename)
                        counter += 1
                    
                    # 确定最终的文件名（不含扩展名），用于同步命名歌词和封面
                    final_base_name = os.path.splitext(new_filename)[0]
                    
                    os.rename(downloaded_file, new_filepath)
                    logger.info(f"[netease_download] 文件已重命名: {os.path.basename(downloaded_file)} -> {safe_artist}/{new_filename}")
                    
                    # 重命名缩略图文件（放在艺术家文件夹中，与音频同名）
                    if thumbnail_file and os.path.exists(thumbnail_file):
                        thumb_ext = os.path.splitext(thumbnail_file)[1]
                        new_thumb_filename = f"{final_base_name}{thumb_ext}"
                        new_thumb_filepath = os.path.join(artist_folder, new_thumb_filename)
                        # 如果目标缩略图已存在，删除旧的
                        if os.path.exists(new_thumb_filepath):
                            os.remove(thumbnail_file)
                        else:
                            os.rename(thumbnail_file, new_thumb_filepath)
                            
                    # 重命名歌词文件（放在艺术家文件夹中，与音频同名）
                    for lrc_file in lyric_files:
                        if os.path.exists(lrc_file):
                            # lrc_file 可能是 task_id.zh-Hans.lrc，我们只取扩展名和可能的语言后缀吗？
                            # 通常为了简单，如果是 .lrc 直接命名为 {final_base_name}.lrc
                            # 如果有语言后缀，可能需要保留。
                            # yt-dlp 命名通常是 {outtmpl}.{lang}.{ext}
                            
                            # 获取文件名部分（去掉路径）
                            lrc_basename = os.path.basename(lrc_file)
                            # 移除开头的 task_id 部分
                            suffix = lrc_basename[len(task_id):] # e.g. ".zh-Hans.lrc" or ".lrc"
                            
                            new_lrc_filename = f"{final_base_name}{suffix}"
                            new_lrc_filepath = os.path.join(artist_folder, new_lrc_filename)
                            
                            if os.path.exists(new_lrc_filepath):
                                os.remove(lrc_file)
                            else:
                                os.rename(lrc_file, new_lrc_filepath)
                            logger.info(f"[netease_download] 歌词文件已重命名: {lrc_basename} -> {safe_artist}/{new_lrc_filename}")
                
                # 更新任务状态
                update_db = next(get_db())
                try:
                    update_task = update_db.query(Task).filter(Task.id == task_id).first()
                    if update_task:
                        # 计算相对路径
                        filename = new_filepath.replace('/app/downloads/', '')
                        # 更新任务标题（如果还没有）
                        if not update_task.title or update_task.title == url:
                            update_task.title = f"{song_artist} - {song_title}"
                        
                        # 再次过滤标题中的特殊字符（针对 TG 通知）
                        n_display_title = update_task.title.replace('<', '《').replace('>', '》')
                        
                        update_task.status = TaskStatus.COMPLETED.value
                        update_task.progress = 100.0
                        update_task.filename = filename
                        update_task.updated_at = datetime.now()

                        # 订阅下载：同步回写 SubscriptionVideo 下载状态
                        subscription_video = update_db.query(SubscriptionVideo).filter(
                            SubscriptionVideo.download_task_id == task_id
                        ).first()
                        if subscription_video:
                            subscription_video.downloaded = "true"
                            subscription_video.error_message = None

                        update_db.commit()
                        
                        logger.info(f"[netease_download] 下载完成: task_id={task_id}, file={filename}")
                        
                        # 广播完成消息
                        try:
                            import routers.websocket
                            await routers.websocket.broadcast_message('downloads', {
                                'type': 'progress_update',
                                'task': {
                                    'id': task_id,
                                    'status': TaskStatus.COMPLETED.value,
                                    'progress': 100.0,
                                    'filename': filename,
                                    'updated_at': datetime.now().isoformat(),
                                    'source': update_task.source,
                                    'title': update_task.title,
                                    'url': update_task.url
                                }
                            })
                        except Exception as e:
                            logger.warning(f"[netease_download] WebSocket消息发送失败: {str(e)}")
                finally:
                    try:
                        update_db.rollback()
                    except Exception:
                        pass
                    update_db.close()
                
                # 发送通知逻辑
                try:
                    import aiohttp
                    import asyncio
                    import threading
                    
                    platform_name = "网易云音乐"
                    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    # 手动下载情况下，author_name 统一标记
                    author_name = f"艺术家: {song_artist}" if song_artist else "手动下载"
                    
                    # 1. 准备封面图
                    extra_data = {}
                    try:
                        # 查找已经被重命名到艺术家文件夹下的封面图
                        found_poster_path = None
                        for ext in ['.jpg', '.jpeg', '.png', '.webp', '.image']:
                            test_path = os.path.join(artist_folder, f"{final_base_name}{ext}")
                            if os.path.exists(test_path):
                                found_poster_path = test_path
                                break
                        
                        if found_poster_path:
                            # 转换为相对路径
                            relative_poster_path = f"/downloads/{os.path.relpath(found_poster_path, '/app/downloads/')}"
                            extra_data["cover"] = relative_poster_path
                            logger.info(f"网易云通知将包含封面: {relative_poster_path}")
                    except Exception as _e:
                        logger.warning(f"网易云查找封面失败: {str(_e)}")

                    if subscription_id:
                        extra_data["subscription_id"] = subscription_id

                    # 2. 准备通知数据
                    notification_data = {
                        "title": f"🎉 下载完成 ({platform_name})",
                        "content": f"内容《{n_display_title}》下载完成！\n\n🏷️ 来源: {platform_name}\n👤 {author_name}\n⏰ 完成时间: {current_time}",
                        "user_id": "default",
                        "extra_data": extra_data
                    }
                    
                    def send_notification_thread():
                        try:
                            async def send_notification():
                                try:
                                    connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                                    async with aiohttp.ClientSession(connector=connector) as session:
                                        async with session.post("http://localhost/api/notifications/download-completed", json=notification_data) as response:
                                            if response.status == 200:
                                                logger.info(f"网易云下载完成通知发送成功: {song_title}")
                                            else:
                                                logger.warning(f"网易云下载完成通知发送失败: {response.status}")
                                except Exception as e:
                                    logger.warning(f"发送网易云通知异常: {str(e)}")
                            
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(send_notification())
                            finally:
                                loop.close()
                        except Exception as e:
                            logger.warning(f"发送网易云通知线程执行失败: {str(e)}")
                    
                    thread = threading.Thread(target=send_notification_thread)
                    thread.daemon = True
                    thread.start()
                except Exception as e:
                    logger.warning(f"启动网易云通知线程失败: {str(e)}")

                return True
            else:
                logger.error(f"[netease_download] 未找到下载文件: task_id={task_id}, url={url}")
                logger.error(f"[netease_download] 可能原因: 1) VIP歌曲需要会员 2) 版权限制 3) Cookie失效 4) 歌曲已下架")
                
                # 发送失败通知
                try:
                    import aiohttp
                    import asyncio
                    import threading
                    
                    notification_data = {
                        "title": f"❌ 下载失败 (网易云音乐)",
                        "content": f"歌曲《{song_title}》下载失败！\n\n🏷️ 来源: 网易云音乐\n👤 艺术家: {song_artist}\n🚫 错误信息: 未找到下载文件\n⏰ 失败时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        "user_id": "default",
                        "extra_data": {
                            "task_id": task_id,
                            "url": url,
                            "subscription_id": subscription_id
                        }
                    }
                    
                    def send_error_thread():
                        try:
                            async def send_notification():
                                connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                                async with aiohttp.ClientSession(connector=connector) as session:
                                    await session.post("http://localhost/api/notifications/download-error", json=notification_data)
                            
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            loop.run_until_complete(send_notification())
                            loop.close()
                        except: pass
                    
                    threading.Thread(target=send_error_thread, daemon=True).start()
                except: pass

                # 列出目录中的文件，帮助调试
                try:
                    files_in_dir = os.listdir(base_dir)
                    logger.debug(f"[netease_download] 目录 {base_dir} 中的文件: {files_in_dir}")
                except Exception as list_err:
                    logger.debug(f"[netease_download] 无法列出目录: {str(list_err)}")
                
                update_db = next(get_db())
                try:
                    update_task = update_db.query(Task).filter(Task.id == task_id).first()
                    if update_task:
                        error_detail = "下载失败: 可能是VIP歌曲、版权限制或Cookie失效"
                        if error_messages:
                            error_detail += f" ({'; '.join(error_messages)})"
                        
                        update_task.status = TaskStatus.ERROR.value
                        update_task.error_message = error_detail
                        update_task.updated_at = datetime.now()

                        # 订阅下载：同步回写 SubscriptionVideo 下载失败状态
                        subscription_video = update_db.query(SubscriptionVideo).filter(
                            SubscriptionVideo.download_task_id == task_id
                        ).first()
                        if subscription_video:
                            subscription_video.downloaded = "false"
                            subscription_video.error_message = error_detail

                        update_db.commit()
                        
                        # 广播错误消息
                        try:
                            import routers.websocket
                            # 使用 asyncio.run_coroutine_threadsafe 或直接在异步上下文中调用
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                asyncio.create_task(routers.websocket.broadcast_message('downloads', {
                                    'type': 'progress_update',
                                    'task': {
                                        'id': task_id,
                                        'status': TaskStatus.ERROR.value,
                                        'error_message': "下载完成但未找到文件",
                                        'updated_at': datetime.now().isoformat()
                                    }
                                }))
                        except Exception as ws_err:
                            logger.warning(f"[netease_download] WebSocket错误消息发送失败: {str(ws_err)}")
                finally:
                    try:
                        update_db.rollback()
                    except Exception:
                        pass
                    update_db.close()
                return False
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[netease_download] 下载失败: {error_msg}")

            # 发送失败通知
            try:
                import aiohttp
                import asyncio
                import threading
                
                notification_data = {
                    "title": f"❌ 下载失败 (网易云音乐)",
                    "content": f"歌曲《{song_title or '未知歌曲'}》下载失败！\n\n🏷️ 来源: 网易云音乐\n👤 艺术家: {song_artist or '未知'}\n🚫 错误信息: {error_msg[:100]}\n⏰ 失败时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    "user_id": "default",
                    "extra_data": {
                        "task_id": task_id,
                        "url": url,
                        "subscription_id": subscription_id
                    }
                }
                
                def send_error_thread_exc():
                    try:
                        async def send_notification():
                            connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                            async with aiohttp.ClientSession(connector=connector) as session:
                                await session.post("http://localhost/api/notifications/download-error", json=notification_data)
                        
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(send_notification())
                        loop.close()
                    except: pass
                
                threading.Thread(target=send_error_thread_exc, daemon=True).start()
            except: pass

            update_db = next(get_db())
            try:
                update_task = update_db.query(Task).filter(Task.id == task_id).first()
                if update_task:
                    update_task.status = TaskStatus.ERROR.value
                    update_task.error_message = error_msg
                    update_task.updated_at = datetime.now()

                    # 订阅下载：同步回写 SubscriptionVideo 下载失败状态
                    subscription_video = update_db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.download_task_id == task_id
                    ).first()
                    if subscription_video:
                        subscription_video.downloaded = "false"
                        subscription_video.error_message = error_msg

                    update_db.commit()
                    
                    # 广播错误消息
                    try:
                        import routers.websocket
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(routers.websocket.broadcast_message('downloads', {
                                'type': 'progress_update',
                                'task': {
                                    'id': task_id,
                                    'status': TaskStatus.ERROR.value,
                                    'error_message': error_msg,
                                    'updated_at': datetime.now().isoformat()
                                }
                            }))
                    except Exception as ws_err:
                        logger.warning(f"[netease_download] WebSocket错误消息发送失败: {str(ws_err)}")
            finally:
                try:
                    update_db.rollback()
                except Exception:
                    pass
                update_db.close()
            return False
            
    except Exception as e:
        logger.error(f"[netease_download] 处理任务失败: {str(e)}")
        try:
            update_db = next(get_db())
            try:
                update_task = update_db.query(Task).filter(Task.id == task_id).first()
                if update_task:
                    update_task.status = TaskStatus.ERROR.value
                    update_task.error_message = str(e)
                    update_task.updated_at = datetime.now()

                    # 订阅下载：同步回写 SubscriptionVideo 下载失败状态
                    subscription_video = update_db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.download_task_id == task_id
                    ).first()
                    if subscription_video:
                        subscription_video.downloaded = "false"
                        subscription_video.error_message = str(e)

                    update_db.commit()
                    
                    # 广播错误消息
                    try:
                        import routers.websocket
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(routers.websocket.broadcast_message('downloads', {
                                'type': 'progress_update',
                                'task': {
                                    'id': task_id,
                                    'status': TaskStatus.ERROR.value,
                                    'error_message': str(e),
                                    'updated_at': datetime.now().isoformat()
                                }
                            }))
                    except Exception as ws_err:
                        logger.warning(f"[netease_download] WebSocket错误消息发送失败: {str(ws_err)}")
            finally:
                try:
                    update_db.rollback()
                except Exception:
                    pass
                update_db.close()
        except Exception:
            pass
        return False
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()
