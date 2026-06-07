# -*- coding: utf-8 -*-
"""
直播录制管理器
使用FFmpeg进行直播流录制
支持: 视频转码、分段录制、字幕生成
"""
import subprocess
import asyncio
import os
import logging
import signal
import threading
import time
import re
import glob
from datetime import datetime
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


class LiveRecorder:
    """直播录制管理器"""
    
    def __init__(self):
        self.recording_tasks: Dict[str, dict] = {}  # subscription_id -> task_info
        self.subtitle_threads: Dict[str, threading.Thread] = {}  # subscription_id -> thread
        self.subtitle_stop_flags: Dict[str, bool] = {}  # subscription_id -> stop_flag
        self.exit_contexts: Dict[str, dict] = {}  # subscription_id -> {'reason': str, 'detail': str, 'updated_at': datetime}
        self.danmu_tasks: Dict[str, dict] = {}  # subscription_id -> {'recorder': obj, 'path': str}
        
        # [新增] 转码队列管理
        self.transcode_queue = asyncio.Queue()
        self.transcode_workers = []          # 工作者列表
        self.max_transcode_concurrency = 2   # 并发限制
        self.active_transcode_tasks: Dict[str, dict] = {} # sub_id -> task_info (当前正在转码的任务)
        self._queued_transcode_task_keys = set()  # 待处理任务去重键
        self._active_transcode_task_keys = set()  # 执行中任务去重键
        self._transcode_task_lock = threading.Lock()
        # 录制状态文件大小缓存，降低每秒状态推送时的磁盘扫描开销
        self._status_size_cache: Dict[str, dict] = {}
        self._status_size_cache_ttl_seconds = 5.0
    
    async def start_recording(
        self,
        subscription_id: str,
        stream_url: str,
        output_path: str,
        quality: str = "原画",
        format: str = "mpegts",  # FFmpeg 格式名称
        segment_time: int = 0,   # 分段时间(秒), 0表示不分段
        generate_subtitle: bool = False,  # 是否生成字幕
        compat_mode: bool = False,  # 兼容模式（实时重编码），应对网络丢包导致的花屏
        on_exit_callback: Optional[callable] = None,
        platform: Optional[str] = None,
        source_url: Optional[str] = None,
        room_url: Optional[str] = None,
        anchor_name: Optional[str] = None,
        room_id: Optional[str] = None
    ) -> subprocess.Popen:
        """
        启动录制

        Args:
            subscription_id: 订阅ID
            stream_url: 直播流URL
            output_path: 输出文件路径
            quality: 录制画质
            format: 输出格式 (ts/mp4/flv)
            segment_time: 分段时间(秒), 0表示不分段
            generate_subtitle: 是否生成时间戳字幕
            compat_mode: 兼容模式，开启后使用 -c:v libx264 -preset ultrafast 实时重编码，
                        可应对网络丢包导致的 H.264 码流损坏花屏问题，但会增加 CPU 开销和文件大小
            on_exit_callback: 进程意外退出时的回调函数(subscription_id)
            platform: 平台名称（用于设置更稳健的网络参数）

        Returns:
            subprocess.Popen: FFmpeg进程
        """
        # 确保目录存在
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        self.exit_contexts.pop(subscription_id, None)
        
        # 构建录制命令 (参数顺序很重要!)
        normalized_platform = (platform or "").lower()
        is_ytdlp_engine = normalized_platform in ["youtube", "twitch"]
        process_name = "YT-DLP" if is_ytdlp_engine else "FFmpeg"
        reconnect_delay_max = "10"
        rw_timeout = "10000000"
        if normalized_platform == "douyin":
            reconnect_delay_max = "20"
            rw_timeout = "20000000"
        elif normalized_platform == "huya":
            reconnect_delay_max = "12"
            rw_timeout = "15000000"

        # B站部分直播流（尤其 gotcha CDN 的 FLV）会校验 Referer/Origin。
        # 缺少这些头时会出现 403，导致“部分直播间无法录制”。
        input_headers_opts = []
        if normalized_platform == "bilibili":
            referer = (source_url or room_url or "https://live.bilibili.com/").strip()
            if referer:
                referer = referer.split("#", 1)[0]
            bilibili_headers = (
                f"Referer: {referer}\r\n"
                "Origin: https://live.bilibili.com\r\n"
            )
            input_headers_opts = ["-headers", bilibili_headers]
        elif normalized_platform == "huya":
            # 虎牙FLV流CDN校验Origin头，缺失可能导致403
            # 参考pure_live项目的 ffmpeg_header_factory.dart
            huya_headers = "Origin: https://www.huya.com\r\n"
            input_headers_opts = ["-headers", huya_headers]

        # 平台自适应 User-Agent：虎牙用SDK标识模拟官方客户端，其他平台用标准Chrome
        if normalized_platform == "huya":
            user_agent = "HYSDK(Windows,30000002)_APP(pc_exe&7090000&official)_SDK(trans&2.35.0.5996)"
        else:
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

        if is_ytdlp_engine:
            source = source_url or room_url or stream_url
            if not source:
                raise ValueError(f"{platform} 录制缺少可用 source_url")
            cookie_file = f"/app/database/cookie/{normalized_platform}_cookie.txt"
            command = [
                'yt-dlp',
                '--no-warnings',
                '--force-overwrites',
                '--hls-use-mpegts',
                '--no-part',
                '--remote-components',
                'ejs:github',
                '-o', output_path,
            ]
            if os.path.exists(cookie_file) and os.path.getsize(cookie_file) > 0:
                command.extend(['--cookies', cookie_file])
            command.append(source)
        else:
            # [优化] HLS(m3u8)流的 -reconnect 参数无效，仅对 HTTP 直连流(FLV等)启用
            is_hls = stream_url and '.m3u8' in stream_url.split('?')[0].lower()
            # RTSP / RTMP 协议不支持 reconnect 和 user_agent 参数
            stream_url_lower = (stream_url or '').lower()
            is_rtsp = stream_url_lower.startswith('rtsp://')
            is_rtmp = stream_url_lower.startswith(('rtmp://', 'rtmps://'))
            is_http_or_hls = not is_rtsp and not is_rtmp
            reconnect_opts = []
            if is_http_or_hls and not is_hls:
                reconnect_opts = [
                    '-reconnect', '1',
                    '-reconnect_streamed', '1',
                    '-reconnect_delay_max', reconnect_delay_max,
                ]
                if normalized_platform == "huya":
                    # 虎牙直播流偶发短暂断流，reconnect_at_eof 让ffmpeg在流结束时主动重连
                    # 参考pure_live项目 ffmpeg_command_builder.dart
                    reconnect_opts.extend(['-reconnect_at_eof', '1'])
            # 视频编码参数：兼容模式用实时重编码，否则直接复制流
            if compat_mode:
                video_codec_opts = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23']
            else:
                video_codec_opts = ['-c:v', 'copy']

            if segment_time > 0:
                # 分段录制模式
                segment_output = output_path.rsplit('.', 1)[0] + '_%03d.' + output_path.rsplit('.', 1)[1]
                command = [
                    'ffmpeg',
                    # 全局选项
                    '-loglevel', 'info',
                    '-y',
                    # 输入选项 (reconnect 仅对非 HLS 流有效)
                    *reconnect_opts,
                    *([] if is_rtsp or is_rtmp else ['-rw_timeout', rw_timeout]),
                    *([] if is_rtsp or is_rtmp else ['-user_agent', user_agent]),
                    *input_headers_opts,
                    '-fflags', '+discardcorrupt',
                    # 输入文件
                    '-i', stream_url,
                    # 输出选项
                    *video_codec_opts,
                    '-c:a', 'copy',
                    '-max_muxing_queue_size', '1024',
                    '-map', '0:v?',
                    '-map', '0:a?',
                    '-f', 'segment',
                    '-segment_time', str(segment_time),
                    '-segment_format', 'mpegts',
                    '-reset_timestamps', '1',
                    # 输出文件
                    segment_output
                ]
                logger.info(f"分段录制模式: 每 {segment_time} 秒分段")
            else:
                # 普通录制模式
                command = [
                    'ffmpeg',
                    # 全局选项
                    '-loglevel', 'info',
                    '-y',
                    # 输入选项 (reconnect 仅对非 HLS 流有效)
                    *reconnect_opts,
                    *([] if is_rtsp or is_rtmp else ['-rw_timeout', rw_timeout]),  # 平台自适应IO超时（抖音更宽松）
                    *([] if is_rtsp or is_rtmp else ['-user_agent', user_agent]),
                    *input_headers_opts,
                    '-fflags', '+discardcorrupt',
                    # 输入文件
                    '-i', stream_url,
                    # 输出选项
                    *video_codec_opts,
                    '-c:a', 'copy',
                    '-max_muxing_queue_size', '1024',
                    '-f', format,
                    # 输出文件
                    output_path
                ]

        input_url_for_log = (source_url or room_url or stream_url) if is_ytdlp_engine else stream_url
        input_url_path = str(input_url_for_log or "").split("?", 1)[0]
        lower_input_url_path = input_url_path.lower()
        if ".m3u8" in lower_input_url_path:
            input_format = "m3u8"
        elif ".flv" in lower_input_url_path:
            input_format = "flv"
        else:
            input_format = "unknown"

        logger.info(
            f"开始录制: sub={subscription_id}, platform={normalized_platform or 'unknown'}, "
            f"quality={quality}, input_format={input_format}, input_url={input_url_path}"
        )
        logger.debug(f"开始录制: {subscription_id}, 输出: {output_path}")
        logger.debug(f"流URL: {stream_url[:100]}...")
        logger.debug(f"{process_name}命令: {' '.join(command[:10])}...")
        
        # 启动FFmpeg进程
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid  # [优化] 创建新进程组，防止孤儿进程
        )
        
        # 在后台线程中监控 stderr
        def log_stderr():
            try:
                # 预定义匹配正则
                # Stream #0:0: Video: h264 (High), yuv420p(progressive), 1920x1080, 2419 kb/s, 30 fps
                res_pattern = re.compile(r'Video:.*?,.*?, (\d{3,5}x\d{3,5})')
                fps_pattern = re.compile(r'(\d+(?:\.\d+)?)\s+fps')
                keepalive_warn_count = 0
                
                for line in process.stderr:
                    line_str = line.decode('utf-8', errors='ignore').strip()
                    if line_str:
                        # 尝试提取视频元数据
                        if "Video:" in line_str:
                            res_match = res_pattern.search(line_str)
                            fps_match = fps_pattern.search(line_str)
                            
                            task = self.recording_tasks.get(subscription_id)
                            if task:
                                if res_match:
                                    task['resolution'] = res_match.group(1)
                                if fps_match:
                                    task['fps'] = fps_match.group(1)
                                    
                                # 如果抓到了分辨率，打印一条详细日志
                                if res_match:
                                    logger.debug(f"[LiveRecorder] 识别到流质量: {task.get('resolution')} @ {task.get('fps', '?')} fps")
                        
                        # 过滤掉高频的 progress 日志，只保留关键信息
                        if "frame=" in line_str or "size=" in line_str or "time=" in line_str:
                            # 这些是进度信息，不需要记录到日志文件
                            continue
                        
                        # 过滤掉 FFmpeg 内部频繁的网络/协议调试信息
                        if any(x in line_str for x in ["[hls @", "[http @", "[tcp @", "[tls @", "[https @"]):
                            if "Error" not in line_str and "failed" not in line_str.lower():
                                continue

                        lower_line = line_str.lower()
                        # YouTube HLS 常见可恢复噪音：连接复用失败后会自动重连，不需要每条都 warning。
                        if (
                            "keepalive request failed" in lower_line
                            and "retrying with new connection" in lower_line
                        ):
                            keepalive_warn_count += 1
                            if keepalive_warn_count == 1 or keepalive_warn_count % 20 == 0:
                                logger.warning(
                                    f"[FFmpeg {subscription_id}] keepalive request failed（可恢复）已出现 "
                                    f"{keepalive_warn_count} 次，FFmpeg 将自动重连"
                                )
                            continue

                        transient_network_markers = [
                            "keepalive request failed",
                            "connection timed out",
                            "connection reset by peer",
                            "broken pipe",
                            "network is unreachable",
                            "connection refused",
                            "connection aborted",
                            "resource temporarily unavailable",
                            "server returned 5",
                            "http error 5",
                            "error in the pull function",
                        ]
                        transient_network_excludes = [
                            "no space left on device",
                            "permission denied",
                        ]

                        # 只有包含 Error 或致命错误时才记录为 error
                        if (
                            any(marker in lower_line for marker in transient_network_markers)
                            and not any(ex in lower_line for ex in transient_network_excludes)
                        ):
                            self._set_exit_context(subscription_id, "transient_hls", line_str)
                            # 网络波动导致的重试，降级为 warning（FFmpeg 内部仍会按参数自动重连）
                            logger.warning(f"[FFmpeg {subscription_id}] {line_str}")
                        # HLS 播放列表无法继续刷新，通常意味着直播接近结束 / 源站中断，调度器会接管处理
                        # 这类情况属于“可预期的异常流程”，不再作为 ERROR 打印，避免误报
                        elif "Failed to reload playlist 0" in line_str:
                            self._set_exit_context(subscription_id, "transient_hls", line_str)
                            logger.warning(f"[FFmpeg {subscription_id}] {line_str}")
                        elif "Failed to open segment" in line_str or "404 Not Found" in line_str:
                            self._set_exit_context(subscription_id, "transient_hls", line_str)
                            logger.warning(f"[FFmpeg {subscription_id}] {line_str}")
                        elif "403 forbidden" in lower_line or "access denied" in lower_line:
                            # 上游明确拒绝（常见于抖音部分 FLV CDN），继续重连通常只会触发重试风暴
                            self._set_exit_context(subscription_id, "upstream_forbidden", line_str)
                            logger.error(f"[FFmpeg {subscription_id}] {line_str}")
                        elif "Invalid data found when processing input" in line_str or "Conversion failed!" in line_str:
                            self._set_exit_context(subscription_id, "stream_data_error", line_str)
                            logger.error(f"[FFmpeg {subscription_id}] {line_str}")
                        elif "Error" in line_str or "failed" in lower_line:
                            self._set_exit_context(subscription_id, "ffmpeg_error", line_str)
                            logger.error(f"[FFmpeg {subscription_id}] {line_str}")
                        elif any(x in line_str for x in ["Video:", "Audio:", "Metadata:", "Duration:", "Stream #"]):
                            # 正常的初始化信息或元数据信息
                            logger.debug(f"[FFmpeg {subscription_id}] {line_str}")
            except Exception as e:
                logger.error(f"读取{process_name} stderr失败: {e}")
        
        stderr_thread = threading.Thread(target=log_stderr, daemon=True)
        stderr_thread.start()

        # [新增] 进程监控线程：主动检测由于直播结束导致的进程退出
        def monitor_process():
            try:
                process.wait()  # 阻塞等待进程结束
                
                # 检查是否为 unexpected exit
                # 如果状态仍为 'recording'，说明不是由 stop_recording 触发的（手动停止会先设为 stopping）
                task = self.recording_tasks.get(subscription_id)
                if task and task.get('status') == 'recording':
                    # 启动时会预写入 unknown 上下文；这里只在仍为 unknown 时补齐真实退出码，
                    # 避免覆盖 stderr 线程已判定的更具体错误原因。
                    ctx = self.exit_contexts.get(subscription_id) or {}
                    if ctx.get("reason", "unknown") == "unknown":
                        self._set_exit_context(subscription_id, "unknown", f"ffmpeg_exit_code={process.returncode}")
                    logger.info(f"检测到录制进程自动退出 (直播结束或异常): {subscription_id}, code={process.returncode}")
                    
                    # 立即停止字幕生成
                    self._stop_subtitle_generation(subscription_id)

                    # 立即停止弹幕录制
                    self._stop_danmu(subscription_id)
                    
                    # 触发回调
                    if on_exit_callback:
                        try:
                            # 注意：这将在辅助线程中执行，如果回调涉及asyncio，需要用 run_coroutine_threadsafe
                            on_exit_callback(subscription_id)
                        except Exception as e:
                            logger.error(f"执行退出回调失败: {e}")
                            
            except Exception as e:
                logger.error(f"进程监控线程异常: {e}")

        monitor_thread = threading.Thread(target=monitor_process, daemon=True, name=f"monitor_{subscription_id}")
        monitor_thread.start()
        
        # 记录任务信息
        self.recording_tasks[subscription_id] = {
            'process': process,
            'start_time': datetime.now(),
            'output_path': output_path,
            'quality': quality,
            'format': format,
            'stream_url': stream_url,
            'status': 'recording',
            'segment_time': segment_time,
            'engine': 'yt-dlp' if is_ytdlp_engine else 'ffmpeg'
        }
        self._status_size_cache.pop(subscription_id, None)
        self.exit_contexts.setdefault(subscription_id, {
            'reason': 'unknown',
            'detail': '',
            'updated_at': datetime.now()
        })
        
        # 启动字幕生成
        if generate_subtitle:
            self._start_subtitle_generation(subscription_id, output_path)

        # 启动弹幕录制（按平台注册）
        if room_url and platform:
            try:
                self._start_danmu(
                    subscription_id,
                    platform,
                    room_url,
                    output_path,
                    anchor_name or "",
                    room_id=room_id or "",
                )
            except Exception as e:
                logger.warning(f"[Danmu] 启动弹幕录制失败: {subscription_id}, {platform}, {e}")
        
        logger.debug(f"录制已启动: {subscription_id}, PID: {process.pid}")

        # 广播录制开始状态
        try:
            from routers.websocket import broadcast_live_status_update
            await broadcast_live_status_update({
                "id": subscription_id,
                "is_recording": True,
                "recording_status": {
                    'duration': 0,
                    'file_size': 0,
                    'quality': quality,
                    'start_time': self.recording_tasks[subscription_id]['start_time'].isoformat()
                }
            })
        except Exception as e:
            logger.error(f"广播录制开始状态失败: {e}")
        
        return process
    
    def _start_subtitle_generation(self, subscription_id: str, output_path: str):
        """启动字幕生成线程"""
        subtitle_path = output_path.rsplit('.', 1)[0]
        self.subtitle_stop_flags[subscription_id] = False
        
        def generate_subtitles():
            """生成时间戳字幕文件 (SRT格式)"""
            index_time = 0
            logger.info(f"开始生成字幕: {subscription_id}")
            
            while not self.subtitle_stop_flags.get(subscription_id, True):
                try:
                    index_time += 1
                    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    # 计算时间码
                    h, remainder = divmod(index_time, 3600)
                    m, s = divmod(remainder, 60)
                    time_start = f"{h:02d}:{m:02d}:{s:02d},000"
                    
                    h2, remainder2 = divmod(index_time + 1, 3600)
                    m2, s2 = divmod(remainder2, 60)
                    time_end = f"{h2:02d}:{m2:02d}:{s2:02d},000"
                    
                    # SRT格式
                    srt_content = f"{index_time}\n{time_start} --> {time_end}\n{current_time}\n\n"
                    
                    with open(f"{subtitle_path}.srt", 'a', encoding='utf-8') as f:
                        f.write(srt_content)
                    
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"字幕生成错误: {e}")
                    break
            
            logger.info(f"字幕生成结束: {subscription_id}, 共 {index_time} 条")
        
        thread = threading.Thread(target=generate_subtitles, daemon=True)
        thread.start()
        self.subtitle_threads[subscription_id] = thread
        logger.info(f"字幕生成线程已启动: {subscription_id}")
    
    def _stop_subtitle_generation(self, subscription_id: str):
        """停止字幕生成"""
        if subscription_id in self.subtitle_stop_flags:
            self.subtitle_stop_flags[subscription_id] = True
            logger.info(f"字幕生成已停止: {subscription_id}")

    def _start_danmu(
        self,
        subscription_id: str,
        platform: str,
        room_url: str,
        output_path: str,
        anchor_name: str,
        room_id: str = "",
    ):
        if subscription_id in self.danmu_tasks:
            return
        from .danmu import get_danmu_recorder

        recorder = get_danmu_recorder(
            platform,
            room_url=room_url,
            output_path=output_path,
            anchor_name=anchor_name,
            subscription_id=subscription_id,
            room_id=room_id or "",
        )
        if not recorder:
            return
        recorder.start()
        self.danmu_tasks[subscription_id] = {
            "recorder": recorder,
            "path": recorder.danmu_path,
            "platform": platform,
        }
        logger.info(f"[Danmu] {platform}弹幕录制已启动: {subscription_id} -> {recorder.danmu_path}")

    def _stop_danmu(self, subscription_id: str):
        task = self.danmu_tasks.pop(subscription_id, None)
        if not task:
            return
        recorder = task.get("recorder")
        platform = task.get("platform") or "unknown"
        try:
            if recorder:
                recorder.stop()
        except Exception as e:
            logger.warning(f"[Danmu] 停止{platform}弹幕录制失败: {subscription_id}, {e}")
        logger.info(f"[Danmu] {platform}弹幕录制已停止: {subscription_id}")
    
    async def stop_recording(
        self, 
        subscription_id: str,
        convert_to_mp4: bool = False,
        delete_original: bool = True,
        on_convert_complete: Optional[callable] = None
    ) -> dict:
        """
        停止录制
        
        Args:
            subscription_id: 订阅ID
            convert_to_mp4: 是否转码为MP4
            delete_original: 转码后是否删除原文件
        
        Returns:
            dict: 录制结果信息
        """
        task = self.recording_tasks.get(subscription_id)
        if not task:
            return {'success': False, 'message': '录制任务不存在'}
        
        # 标记为正在停止，防止监控线程误判
        task['status'] = 'stopping'
        process = task['process']
        engine = task.get('engine', 'ffmpeg')
        process_name = "YT-DLP" if engine == 'yt-dlp' else "FFmpeg"
        
        logger.info(f"正在停止录制: {subscription_id}")
        
        # 停止字幕生成
        self._stop_subtitle_generation(subscription_id)

        # 停止弹幕录制
        self._stop_danmu(subscription_id)
        
        # 优雅退出录制进程
        try:
            if process.poll() is not None:
                logger.info(f"{process_name}进程已退出，无需发送停止命令: {subscription_id}, code={process.returncode}")
            elif engine == 'ffmpeg' and process.stdin:
                process.stdin.write(b'q')
                process.stdin.flush()
                process.stdin.close()
            else:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGINT)
                except (ProcessLookupError, PermissionError):
                    process.terminate()
        except Exception as e:
            logger.warning(f"发送退出命令失败: {e}")
        
        # 等待进程结束
        try:
            await asyncio.to_thread(process.wait, 10)
            logger.info(f"{process_name}进程已正常退出: {subscription_id}")
        except subprocess.TimeoutExpired:
            logger.warning(f"{process_name}进程超时,强制终止: {subscription_id}")
            try:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    process.kill()  # 进程组不存在时回退
                await asyncio.to_thread(process.wait, 5)
            except Exception as e:
                logger.error(f"强制终止失败: {e}")
        
        # 计算录制信息
        end_time = datetime.now()
        start_time = task['start_time']
        duration = int((end_time - start_time).total_seconds())
        
        # 获取文件大小 (支持分段统计)
        output_path = task['output_path']
        segment_time = task.get('segment_time', 0)
        file_size = self._get_recording_file_size(
            subscription_id=subscription_id,
            task=task,
            force_refresh=True
        )
        
        result = {
            'success': True,
            'duration': duration,
            'file_size': file_size,
            'file_path': output_path,
            'start_time': start_time,
            'end_time': end_time
        }
        
        # 清理任务
        del self.recording_tasks[subscription_id]
        self._status_size_cache.pop(subscription_id, None)
        self.exit_contexts.pop(subscription_id, None)
        
        logger.info(f"录制已停止: {subscription_id}, 时长: {duration}秒, 大小: {file_size}字节")

        # 广播录制停止状态
        try:
            from routers.websocket import broadcast_live_status_update
            await broadcast_live_status_update({
                "id": subscription_id,
                "is_recording": False,
                "recording_status": None
            })
        except Exception as e:
            logger.error(f"广播录制停止状态失败: {e}")
        
        # 异步转码为MP4
        if convert_to_mp4 and output_path.endswith('.ts'):
            segment_time = task.get('segment_time', 0)
            
            # 构造转码任务信息
            transcode_task = {
                'subscription_id': subscription_id,
                'output_path': output_path,
                'delete_original': delete_original,
                'on_complete': on_convert_complete,
                'segment_time': segment_time,
                'type': 'merge' if segment_time > 0 else 'convert',
                'enqueued_at': datetime.now()
            }
            
            # 加入队列
            await self._enqueue_transcode_task(transcode_task)
            result['converting'] = True
            result['message'] = '已加入转码队列'
        
        return result

    def _build_transcode_task_key(self, task: dict) -> str:
        """构建任务去重键，用于避免重复入队"""
        custom_key = task.get('task_key')
        if custom_key:
            return str(custom_key)
        output_path = task.get('output_path') or ''
        task_type = task.get('type') or 'convert'
        sub_id = task.get('subscription_id') or 'unknown'
        return f"{sub_id}:{task_type}:{output_path}"

    async def _enqueue_transcode_task(self, task: dict) -> bool:
        """将转码任务加入队列（带去重）"""
        task_key = self._build_transcode_task_key(task)
        with self._transcode_task_lock:
            if task_key in self._queued_transcode_task_keys or task_key in self._active_transcode_task_keys:
                logger.info(f"转码任务已存在，跳过重复入队: {task_key}")
                return False
            self._queued_transcode_task_keys.add(task_key)
        task['task_key'] = task_key
        await self.transcode_queue.put(task)
        logger.info(f"转码任务已入队: {task['subscription_id']} ({task['type']}), 队列长度: {self.transcode_queue.qsize()}")
        
        # 确保有足够的工作者在运行
        while len(self.transcode_workers) < self.max_transcode_concurrency:
            worker = asyncio.create_task(self._transcode_worker(len(self.transcode_workers)))
            self.transcode_workers.append(worker)

    async def _transcode_worker(self, worker_id: int):
        """转码后台工作者 (并发处理队列)"""
        logger.info(f"📡 直播转码工作者 #{worker_id} 已启动")
        while True:
            try:
                # 获取下一个任务
                task = await self.transcode_queue.get()
                sub_id = task['subscription_id']
                task_key = self._build_transcode_task_key(task)
                with self._transcode_task_lock:
                    self._queued_transcode_task_keys.discard(task_key)
                    self._active_transcode_task_keys.add(task_key)
                self.active_transcode_tasks[sub_id] = task
                
                task_type = task['type']
                logger.info(f"🛠️ 工作者 #{worker_id} 开始处理: {sub_id} ({task_type})")
                
                try:
                    if task_type == 'merge':
                        # 合并分段并转码
                        output_dir = os.path.dirname(task['output_path'])
                        prefix = os.path.basename(task['output_path']).rsplit('.', 1)[0]
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(
                            None, 
                            self._do_merge_segments, 
                            output_dir, prefix, task['delete_original'], task['on_complete']
                        )
                    else:
                        # 单文件转码
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(
                            None,
                            self._convert_to_mp4,
                            task['output_path'], task['delete_original'], task['on_complete']
                        )
                except Exception as e:
                    logger.error(f"转码任务执行失败: {sub_id}, 错误: {e}")
                finally:
                    self.transcode_queue.task_done()
                    if sub_id in self.active_transcode_tasks:
                        del self.active_transcode_tasks[sub_id]
                    with self._transcode_task_lock:
                        self._active_transcode_task_keys.discard(task_key)
                    logger.info(f"✅ 工作者 #{worker_id} 完成任务: {sub_id}, 仍有 {self.transcode_queue.qsize()} 个在排队")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"转码Worker #{worker_id} 异常: {e}")
                await asyncio.sleep(5)
    
    def _convert_to_mp4(self, ts_path: str, delete_original: bool = True, on_complete: Optional[callable] = None):
        """
        将TS文件转码为MP4 (后台执行)
        
        Args:
            ts_path: TS文件路径
            delete_original: 是否删除原文件
            on_complete: 完成后的回调函数 (接收 success: bool, mp4_path: str 作为参数)
        """
        success = False
        mp4_path = ts_path.rsplit('.', 1)[0] + '.mp4'
        try:
            if not os.path.exists(ts_path) or os.path.getsize(ts_path) == 0:
                logger.warning(f"文件不存在或为空: {ts_path}")
                if on_complete:
                    on_complete(False, None)
                return
            
            logger.info(f"开始转码: {ts_path} -> {mp4_path}")
            
            # 使用流复制,不重新编码,速度最快
            ffmpeg_command = [
                'ffmpeg',
                '-y',
                '-i', ts_path,
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-movflags', '+faststart',  # 优化MP4在线播放
                '-f', 'mp4',
                mp4_path
            ]
            
            result = subprocess.run(
                ffmpeg_command,
                capture_output=True,
                timeout=3600  # 1小时超时
            )
            
            if result.returncode != 0:
                logger.warning(
                    f"流复制转码失败（返回值={result.returncode}），可能是非标准音频流。尝试重新编码音频兜底: {ts_path}"
                )
                ffmpeg_command_fallback = [
                    'ffmpeg',
                    '-y',
                    '-i', ts_path,
                    '-c:v', 'copy',
                    '-c:a', 'aac',
                    '-b:a', '128k',
                    '-movflags', '+faststart',
                    '-f', 'mp4',
                    mp4_path
                ]
                result = subprocess.run(
                    ffmpeg_command_fallback,
                    capture_output=True,
                    timeout=3600
                )
                
                if result.returncode != 0:
                    logger.warning(
                        f"重新编码音频转码失败（返回值={result.returncode}），可能是物理损坏的音频轨。尝试丢弃音频兜底: {ts_path}"
                    )
                    ffmpeg_command_fallback_an = [
                        'ffmpeg',
                        '-y',
                        '-i', ts_path,
                        '-c:v', 'copy',
                        '-an',
                        '-movflags', '+faststart',
                        '-f', 'mp4',
                        mp4_path
                    ]
                    result = subprocess.run(
                        ffmpeg_command_fallback_an,
                        capture_output=True,
                        timeout=3600
                    )
            
            if result.returncode == 0:
                logger.info(f"转码成功: {mp4_path}")
                success = True
                
                # 删除原文件
                if delete_original and os.path.exists(mp4_path):
                    time.sleep(1)
                    os.remove(ts_path)
                    logger.info(f"已删除原文件: {ts_path}")
            else:
                logger.error(f"转码失败: {result.stderr.decode(errors='ignore')}")
                
        except subprocess.TimeoutExpired:
            logger.error(f"转码超时: {ts_path}")
        except Exception as e:
            logger.error(f"转码错误: {e}")
        finally:
            if on_complete:
                try:
                    on_complete(success, mp4_path if success else None)
                except Exception as cb_err:
                    logger.error(f"执行转码回调失败: {cb_err}")
    
    def convert_segment_files(self, output_dir: str, prefix: str, delete_original: bool = True, on_complete: Optional[callable] = None):
        """
        [过时] 请使用队列系统。
        为了兼容性保留，但内部现在只是做简单的合并。
        """
        self._do_merge_segments(output_dir, prefix, delete_original, on_complete)

    def _do_merge_segments(self, output_dir: str, prefix: str, delete_original: bool = True, on_complete: Optional[callable] = None):
        """执行实际的文件合并与转码操作"""
        import glob
        
        # 1. 寻找所有分段文件并排序
        pattern = os.path.join(output_dir, f"{prefix}_*.ts")
        ts_files = sorted(glob.glob(pattern))
        
        if not ts_files:
            logger.warning(f"未找到匹配前缀的分段文件: {prefix}")
            if on_complete: on_complete(False, None)
            return

        final_mp4_path = os.path.join(output_dir, f"{prefix}.mp4")
        concat_file = os.path.join(output_dir, f"{prefix}_concat.txt")
        success = False
        
        try:
            logger.info(f"开始合并分段文件 ({len(ts_files)} 个) -> {final_mp4_path}")
            
            # 2. 创建 concat 列表文件
            with open(concat_file, 'w', encoding='utf-8') as f:
                for ts_path in ts_files:
                    # 使用绝对路径，并转义单引号
                    safe_path = os.path.abspath(ts_path).replace("'", "'\\''")
                    f.write(f"file '{safe_path}'\n")
            
            # 3. 执行 FFmpeg 合并转码 (copy 模式快且保真)
            ffmpeg_command = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file,
                '-c', 'copy',
                '-movflags', '+faststart',
                final_mp4_path
            ]
            
            result = subprocess.run(ffmpeg_command, capture_output=True, timeout=7200) # 给 2 小时
            
            if result.returncode != 0:
                logger.warning(
                    f"合并分段流复制失败（返回值={result.returncode}），可能是非标准音频流。尝试重新编码音频兜底: {final_mp4_path}"
                )
                ffmpeg_command_fallback = [
                    'ffmpeg', '-y',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_file,
                    '-c:v', 'copy',
                    '-c:a', 'aac',
                    '-b:a', '128k',
                    '-movflags', '+faststart',
                    final_mp4_path
                ]
                result = subprocess.run(ffmpeg_command_fallback, capture_output=True, timeout=7200)
                
                if result.returncode != 0:
                    logger.warning(
                        f"合并分段重新编码音频失败（返回值={result.returncode}），可能是物理损坏的音频轨。尝试丢弃音频兜底: {final_mp4_path}"
                    )
                    ffmpeg_command_fallback_an = [
                        'ffmpeg', '-y',
                        '-f', 'concat',
                        '-safe', '0',
                        '-i', concat_file,
                        '-c:v', 'copy',
                        '-an',
                        '-movflags', '+faststart',
                        final_mp4_path
                    ]
                    result = subprocess.run(ffmpeg_command_fallback_an, capture_output=True, timeout=7200)
            
            if result.returncode == 0:
                logger.info(f"分段合并转码成功: {final_mp4_path}")
                success = True
                
                # 4. 删除原文件及临时列表
                if delete_original:
                    for ts_path in ts_files:
                        try:
                            os.remove(ts_path)
                        except: pass
                    logger.info(f"已清理 {len(ts_files)} 个原始分段文件")
            else:
                logger.error(f"分段合并失败: {result.stderr.decode(errors='ignore')}")
                
        except Exception as e:
            logger.error(f"合并分段过程出错: {e}")
        finally:
            # 清理列表文件
            if os.path.exists(concat_file):
                try: os.remove(concat_file)
                except: pass
            
            if on_complete:
                try:
                    on_complete(success, final_mp4_path if success else None)
                except Exception as cb_err:
                    logger.error(f"合并转码回调失败: {cb_err}")
    
    def get_recording_status(self, subscription_id: str) -> Optional[dict]:
        """获取录制状态"""
        task = self.recording_tasks.get(subscription_id)
        if not task:
            return None
        
        process = task['process']
        
        if process.poll() is not None:
            return {
                'status': 'stopped',
                'return_code': process.returncode,
                'message': 'FFmpeg进程已退出'
            }
        
        duration = int((datetime.now() - task['start_time']).total_seconds())
        output_path = task.get('output_path')
        segment_time = task.get('segment_time', 0)
        file_size = self._get_recording_file_size(subscription_id=subscription_id, task=task)
        
        return {
            'status': 'recording',
            'duration': duration,
            'file_size': file_size,
            'quality': task['quality'],
            'resolution': task.get('resolution'), # [新增] 真实分辨率
            'fps': task.get('fps'),               # [新增] 真实帧率
            'output_path': output_path,
            'start_time': task['start_time'].isoformat(),
            'segment_time': segment_time
        }

    def _scan_recording_file_size(self, task: dict) -> int:
        """实际扫描录制文件大小（可能触发磁盘 IO）。"""
        file_size = 0
        output_path = task.get('output_path')
        if not output_path:
            return 0

        segment_time = task.get('segment_time', 0)
        try:
            if segment_time > 0:
                base_path = output_path.rsplit('.', 1)[0]
                ext = output_path.rsplit('.', 1)[1]
                pattern = f"{base_path}_[0-9]*[0-9].{ext}"
                for f in glob.glob(pattern):
                    try:
                        file_size += os.path.getsize(f)
                    except OSError:
                        continue
            elif os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
        except Exception as e:
            logger.debug(f"扫描录制文件大小失败: {e}")
            file_size = 0
        return int(file_size)

    def _get_recording_file_size(self, subscription_id: str, task: dict, force_refresh: bool = False) -> int:
        """
        获取录制文件大小：
        - 默认使用短时缓存，降低高频状态推送造成的磁盘压力；
        - 停止录制等关键节点可强制刷新。
        """
        now = time.time()
        cache = self._status_size_cache.get(subscription_id)
        if (not force_refresh) and cache:
            age = now - float(cache.get('ts', 0))
            if age < self._status_size_cache_ttl_seconds:
                return int(cache.get('file_size', 0))

        size = self._scan_recording_file_size(task)
        self._status_size_cache[subscription_id] = {
            'ts': now,
            'file_size': size
        }
        return size

    def _set_exit_context(self, subscription_id: str, reason: str, detail: str = ""):
        """记录最近一次 FFmpeg 异常上下文，供调度器决定重连策略。"""
        self.exit_contexts[subscription_id] = {
            'reason': reason,
            'detail': (detail or "")[:300],
            'updated_at': datetime.now()
        }

    def get_exit_context(self, subscription_id: str) -> dict:
        """获取最近一次退出原因上下文。"""
        return self.exit_contexts.get(subscription_id, {
            'reason': 'unknown',
            'detail': '',
            'updated_at': None
        })

    def clear_exit_context(self, subscription_id: str):
        """清理退出原因上下文。"""
        self.exit_contexts.pop(subscription_id, None)
    
    def is_recording(self, subscription_id: str) -> bool:
        """检查是否正在录制"""
        task = self.recording_tasks.get(subscription_id)
        if not task:
            return False
        
        process = task['process']
        return process.poll() is None
    
    def get_all_recording_ids(self) -> list:
        """获取所有正在录制的订阅ID"""
        return list(self.recording_tasks.keys())

    def collect_recording_snapshot(self) -> tuple[Set[str], Dict[str, dict]]:
        """一次遍历收集所有活跃录制的 ID 集合和状态（替代多次独立调用）"""
        now = datetime.now()
        active_ids: Set[str] = set()
        statuses: Dict[str, dict] = {}
        for sub_id, task in self.recording_tasks.items():
            if task['process'].poll() is None:
                active_ids.add(sub_id)
                statuses[sub_id] = {
                    'status': 'recording',
                    'duration': int((now - task['start_time']).total_seconds()),
                    'file_size': self._get_recording_file_size(subscription_id=sub_id, task=task),
                    'quality': task['quality'],
                    'start_time': task['start_time'].isoformat()
                }
        return active_ids, statuses
    
    async def stop_all_recordings(self, convert_to_mp4: bool = False):
        """停止所有录制"""
        subscription_ids = list(self.recording_tasks.keys())
        for subscription_id in subscription_ids:
            try:
                await self.stop_recording(subscription_id, convert_to_mp4=convert_to_mp4)
            except Exception as e:
                logger.error(f"停止录制失败: {subscription_id}, 错误: {e}")


# 全局实例
live_recorder = LiveRecorder()
