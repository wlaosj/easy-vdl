import os
import asyncio
import logging
import time
import json
import tempfile
import threading
from datetime import datetime

import yt_dlp
from sql.database_postgresql import get_db
from sql.models import Task, TaskStatus

# 独立的 X 下载逻辑（基于 yt-dlp），避免走“通用解析”路径
logger = logging.getLogger(__name__)


async def x_download_task(
    task_id: str,
    url: str,
    format_id: str = None,
    headers: dict = None,
    download_dir: str = None
):
    """X 专用下载实现（使用 X Cookie + 独立目录）"""
    import aiohttp

    db = next(get_db())
    temp_dir = None
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise Exception("任务不存在")

        temp_dir = tempfile.mkdtemp()

        final_format_id = task.format_id or format_id or 'bestvideo+bestaudio'
        logger.info(f"[x-download] 使用格式: {final_format_id} (数据库: {task.format_id}, 参数: {format_id})")

        if final_format_id and final_format_id != 'bestvideo+bestaudio':
            if final_format_id.isdigit():
                final_format_id = f"{final_format_id}+bestaudio"
            elif 'bestvideo' in final_format_id and 'bestaudio' not in final_format_id:
                final_format_id = f"{final_format_id}+bestaudio"
            elif 'bestaudio' in final_format_id and 'bestvideo' not in final_format_id:
                final_format_id = f"bestvideo+{final_format_id}"
            elif '+' not in final_format_id:
                final_format_id = f"{final_format_id}+bestaudio"

        ydl_opts = {
            'format': final_format_id,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'no_cache_dir': True,
            'writethumbnail': True,
            'postprocessors': [
                {'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'},
                {'key': 'FFmpegVideoRemuxer', 'preferedformat': 'mp4'}
            ],
            'audioformat': 'best',
            'audioquality': '0',
            'extractaudio': False,
            'keepvideo': False,
            'prefer_ffmpeg': True,
            'merge_output_format': 'mp4',
            'postprocessor_args': {
                'ffmpeg': ['-c:v', 'copy', '-c:a', 'copy', '-strict', 'experimental']
            }
        }

        request_headers = {}
        if headers:
            if isinstance(headers, str):
                try:
                    headers = json.loads(headers)
                except Exception:
                    headers = {}
            request_headers = headers
        if not request_headers.get('User-Agent'):
            request_headers['User-Agent'] = (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        ydl_opts['http_headers'] = request_headers

        x_cookie_path = '/app/database/cookie/x.txt'
        if os.path.exists(x_cookie_path):
            ydl_opts['cookiefile'] = x_cookie_path
            logger.debug(f"[x-download] 使用 X Cookie 文件: {x_cookie_path}")

        # 对齐 ytd.py：先用 task_id 作为临时文件名，下载完成后再重命名为标题
        base_filename = task_id
        if download_dir:
            output_dir = download_dir
        else:
            output_dir = "/app/downloads/x"
        os.makedirs(output_dir, exist_ok=True)
        ydl_opts['outtmpl'] = {
            'default': f'{output_dir}/{base_filename}.%(ext)s',
            'thumbnail': f'{output_dir}/{base_filename}.%(ext)s'
        }

        filename_rel = f"x/{base_filename}.%(ext)s"
        if output_dir.startswith("/app/downloads/"):
            rel_dir = output_dir[len("/app/downloads/"):]
            filename_rel = f"{rel_dir}/{base_filename}.%(ext)s"

        db.query(Task).filter(Task.id == task_id).update({
            'status': TaskStatus.DOWNLOADING.value,
            'progress': 0.0,
            'filename': filename_rel,
            'updated_at': datetime.now()
        })
        db.commit()

        last_progress_time = time.time()
        progress_queue = asyncio.Queue()

        def progress_hook(d):
            nonlocal last_progress_time
            try:
                if d.get('status') == 'downloading':
                    now = time.time()
                    if now - last_progress_time < 0.3:
                        return
                    last_progress_time = now
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes') or 0
                    progress = 0.0
                    if total > 0:
                        progress = min(99.0, max(0.0, downloaded / total * 100))
                    progress_queue.put_nowait(progress)
            except Exception:
                pass

        ydl_opts['progress_hooks'] = [progress_hook]

        def _download(opts):
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=True)

        loop = asyncio.get_running_loop()
        try:
            info = await loop.run_in_executor(None, _download, ydl_opts)
        except Exception as e:
            logger.warning(f"[x-download] 第一次下载失败，尝试使用更宽松的格式: {str(e)}")
            try:
                ydl_opts_fallback = ydl_opts.copy()
                # 智能重试策略：根据错误类型选择不同的格式
                if "format is not available" in str(e) or "Requested format" in str(e):
                    ydl_opts_fallback['format'] = 'best'
                    logger.info(f"[x-download] 检测到格式不可用，重试使用 'best' 格式")
                elif "bestvideo+bestaudio" in final_format_id:
                    ydl_opts_fallback['format'] = 'best'
                    logger.info(f"[x-download] 检测到bestvideo+bestaudio失败，重试使用 'best' 格式")
                else:
                    ydl_opts_fallback['format'] = 'bestvideo+bestaudio'
                    logger.info(f"[x-download] 重试使用 'bestvideo+bestaudio' 格式")

                ydl_opts_fallback['ignoreerrors'] = True
                ydl_opts_fallback['no_check_certificate'] = True
                info = await loop.run_in_executor(None, _download, ydl_opts_fallback)
            except Exception as e2:
                logger.error(f"[x-download] 重试下载也失败: {str(e2)}")
                raise e2

        # 对齐 ytd.py：重命名为可读标题，并生成 NFO
        resolved_filename_rel = None
        try:
            # 先判断实际扩展名
            file_ext = None
            preferred_exts = [".mp4", ".mkv", ".webm", ".mov", ".flv"]
            for ext in preferred_exts:
                if os.path.exists(os.path.join(output_dir, f"{base_filename}{ext}")):
                    file_ext = ext
                    break

            from routers.ytd import rename_files_for_emby, generate_nfo
            if isinstance(info, dict):
                info.setdefault('webpage_url', url)
                if not info.get('uploader'):
                    info['uploader'] = info.get('uploader_id') or info.get('uploader') or ''

            filename_base = rename_files_for_emby(task_id, info or {}, output_dir, file_ext or ".mp4")

            try:
                generate_nfo(info or {}, os.path.join(output_dir, filename_base), filename_base)
            except Exception as nfo_err:
                logger.warning(f"[x-download] 生成NFO失败: {nfo_err}")

            # 定位重命名后的真实文件路径
            for ext in preferred_exts:
                candidate = os.path.join(output_dir, filename_base, f"{filename_base}{ext}")
                if os.path.exists(candidate):
                    if candidate.startswith("/app/downloads/"):
                        resolved_filename_rel = candidate[len("/app/downloads/"):]
                    else:
                        resolved_filename_rel = candidate
                    break
        except Exception as rename_err:
            logger.warning(f"[x-download] 重命名失败，保留原文件名: {rename_err}")
            # 兜底定位原文件
            try:
                for ext in ["mp4", "mkv", "webm", "mov", "flv"]:
                    candidate = os.path.join(output_dir, f"{base_filename}.{ext}")
                    if os.path.exists(candidate):
                        if candidate.startswith("/app/downloads/"):
                            resolved_filename_rel = candidate[len("/app/downloads/"):]
                        else:
                            resolved_filename_rel = candidate
                        break
            except Exception:
                pass

        # 更新完成状态（如能解析真实文件名则写入）
        update_fields = {
            'status': TaskStatus.COMPLETED.value,
            'progress': 100.0,
            'updated_at': datetime.now()
        }
        if resolved_filename_rel:
            update_fields['filename'] = resolved_filename_rel
        db.query(Task).filter(Task.id == task_id).update(update_fields)
        db.commit()

        # 同步订阅视频下载状态（避免下载完成过快导致订阅列表仍显示“下载”）
        try:
            from sql.models import SubscriptionVideo
            updated_rows = db.query(SubscriptionVideo).filter(
                SubscriptionVideo.download_task_id == task_id
            ).update({
                'downloaded': "true",
                'error_message': None
            })
            if updated_rows:
                db.commit()
        except Exception:
            db.rollback()

        # 广播完成状态（延迟导入避免循环依赖）
        import routers.websocket
        await routers.websocket.broadcast_message('downloads', {
            'type': 'progress_update',
            'task': {
                'id': task_id,
                'progress': 100.0,
                'status': TaskStatus.COMPLETED.value,
                'updated_at': datetime.now().isoformat(),
                'filename': resolved_filename_rel or filename_rel
            }
        })

        # 下载完成发送通知
        try:
            n_video_title = info.get('title') if info else base_filename
            if n_video_title:
                n_video_title = str(n_video_title).replace('<', '《').replace('>', '》')
            n_platform_name = "X"
            n_current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # 判断来源：订阅 or 手动
            source_text = "手动添加"
            try:
                task_for_notice = db.query(Task).filter(Task.id == task_id).first()
                if task_for_notice and task_for_notice.subscription_id:
                    from sql.models import Subscription
                    sub = db.query(Subscription).filter(Subscription.id == task_for_notice.subscription_id).first()
                    if sub and sub.nickname:
                        source_text = f"订阅 - {sub.nickname}"
                    else:
                        source_text = "订阅"
            except Exception:
                pass

            extra_data = {}
            try:
                if resolved_filename_rel:
                    # resolved_filename_rel: e.g. subscriptions/x/author/标题 (2026)/标题 (2026).mp4
                    folder_rel = os.path.dirname(resolved_filename_rel)
                    filename_base = os.path.splitext(os.path.basename(resolved_filename_rel))[0]
                    poster_rel = f"{folder_rel}/{filename_base}-poster.jpg"
                    poster_path = f"/app/downloads/{poster_rel}"
                    if os.path.exists(poster_path):
                        extra_data["cover"] = f"/downloads/{poster_rel}"
            except Exception:
                pass

            notification_data = {
                "title": f"🎉 下载完成 ({n_platform_name})",
                "content": f"内容《{n_video_title}》下载完成！\n\n🏷️ 来源: {n_platform_name}\n👤 {source_text}\n⏰ 完成时间: {n_current_time}",
                "user_id": "default",
                "extra_data": extra_data
            }

            def send_notification_thread():
                try:
                    async def send_notification():
                        connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                        async with aiohttp.ClientSession(connector=connector) as session:
                            await session.post("http://localhost/api/notifications/download-completed", json=notification_data)
                    loop2 = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop2)
                    try:
                        loop2.run_until_complete(send_notification())
                    finally:
                        loop2.close()
                except Exception:
                    pass

            threading.Thread(target=send_notification_thread, daemon=True).start()
        except Exception as e:
            logger.warning(f"[x-download] 通知处理异常: {e}")

        return info

    except Exception as e:
        # 发送失败通知
        try:
            def send_fail_notify():
                try:
                    async def send():
                        connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                        async with aiohttp.ClientSession(connector=connector) as session:
                            await session.post("http://localhost/api/notifications/download-error", json={
                                "title": "❌ 下载失败 (X)",
                                "content": f"X 下载出错\n🚫 错误: {str(e)[:200]}\n🆔 任务: {task_id}",
                                "user_id": "default"
                            })
                    loop2 = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop2)
                    try:
                        loop2.run_until_complete(send())
                    finally:
                        loop2.close()
                except Exception:
                    pass
            threading.Thread(target=send_fail_notify, daemon=True).start()
        except Exception:
            pass

        db.query(Task).filter(Task.id == task_id).update({
            'status': TaskStatus.ERROR.value,
            'error_message': str(e),
            'updated_at': datetime.now()
        })
        db.commit()
        raise
    finally:
        try:
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            db.rollback()
        except Exception:
            pass
        db.close()
