import logging
import json
import subprocess
import asyncio
import os
import time
from typing import Dict, Any, Optional
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .base import BaseAdapter

logger = logging.getLogger(__name__)


def is_watch_video_url(url: str) -> bool:
    """判断是否为 YouTube 单场视频链接（watch?v= 或 youtu.be），而非频道直播页"""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if "youtube.com" in host:
            query = parse_qs(parsed.query or "")
            if "v" in query and query["v"]:
                return True
        if "youtu.be" in host:
            path = (parsed.path or "").strip("/")
            return bool(path)
    except Exception:
        pass
    return False


async def resolve_channel_live_url(url: str) -> Optional[str]:
    """通过 yt-dlp 将单场视频链接解析为频道永久直播页 URL (@handle/live)

    返回转换后的 URL，如果解析失败则返回 None，保持原链接不变。
    """
    def _resolve() -> Optional[str]:
        try:
            result = subprocess.run(
                ["yt-dlp", "-j", "--no-download", "--no-warnings", url],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                uploader_url = data.get("uploader_url") or data.get("channel_url", "")
                if uploader_url:
                    return uploader_url.rstrip("/") + "/live"
        except Exception:
            pass
        return None

    resolved = await asyncio.to_thread(_resolve)
    if resolved:
        logger.info(f"[YouTube] 已解析频道直播页: {url} -> {resolved}")
    else:
        logger.warning(f"[YouTube] 解析频道直播页失败，保持原链接: {url}")
    return resolved


class YoutubeAdapter(BaseAdapter):
    """YouTube 直播适配器"""

    @property
    def platform_name(self) -> str:
        return "youtube"

    def is_match(self, url: str) -> bool:
        u = (url or "").lower()
        return "youtube.com" in u or "youtu.be" in u

    def _resolve_cookie_file(self, cookie_file: Optional[str] = None) -> Optional[str]:
        """解析可用的 YouTube cookie 文件路径。"""
        candidates = []
        if cookie_file:
            candidates.append(cookie_file)
        candidates.append("/app/database/cookie/youtube_cookie.txt")
        candidates.append(str(Path(__file__).resolve().parents[2] / "database" / "cookie" / "youtube_cookie.txt"))

        for path in candidates:
            if not path:
                continue
            try:
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    return path
            except Exception:
                continue
        return None

    async def _probe_with_ytdlp(self, url: str, **kwargs) -> Dict[str, Any]:
        def _run() -> Dict[str, Any]:
            try:
                probe_timeout = int(kwargs.get("probe_timeout") or 45)
            except Exception:
                probe_timeout = 45
            probe_timeout = max(10, min(120, probe_timeout))
            # 默认再重试 1 轮（共 2 轮），缓解 YouTube 间歇性探测超时。
            try:
                retry_rounds = int(kwargs.get("probe_retry_rounds") or 1)
            except Exception:
                retry_rounds = 1
            retry_rounds = max(0, min(3, retry_rounds))
            total_rounds = 1 + retry_rounds
            retry_backoff_seconds = 2.0

            base_cmd = [
                "yt-dlp",
                "--dump-single-json",
                "--no-warnings",
                "--skip-download",
                "--remote-components",
                "ejs:github",
            ]
            cookie_file = self._resolve_cookie_file(kwargs.get("cookie_file"))

            attempt_cmds = []
            if cookie_file:
                attempt_cmds.append(("with_cookie", [*base_cmd, "--cookies", cookie_file, url]))
            attempt_cmds.append(("no_cookie", [*base_cmd, url]))

            errors = []
            for round_index in range(total_rounds):
                for tag, cmd in attempt_cmds:
                    try:
                        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=probe_timeout)
                    except subprocess.TimeoutExpired:
                        errors.append(
                            f"round={round_index + 1}/{total_rounds} {tag}: timed out after {probe_timeout} seconds"
                        )
                        continue

                    if proc.returncode == 0 and (proc.stdout or "").strip():
                        data = json.loads(proc.stdout)
                        live_status = data.get("live_status")
                        # is_upcoming 表示预约/待开播，不应当按“已在线”处理。
                        is_live = bool(data.get("is_live")) or live_status == "is_live"
                        anchor_name = data.get("uploader") or data.get("channel") or ""
                        cover_url = self._extract_cover_url(data)
                        return {
                            "is_live": is_live,
                            "live_status": live_status,
                            "anchor_name": anchor_name,
                            "avatar_url": cover_url,
                            "raw_data": data,
                        }

                    err = (proc.stderr or proc.stdout or "yt-dlp probe failed").strip()
                    errors.append(f"round={round_index + 1}/{total_rounds} {tag}: {err[:260]}")

                if round_index + 1 < total_rounds:
                    time.sleep(retry_backoff_seconds)

            raise RuntimeError(" | ".join(errors)[:600])

        return await asyncio.to_thread(_run)

    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        try:
            data = await self._probe_with_ytdlp(url, **kwargs)
            return {
                "anchor_name": data.get("anchor_name", ""),
                "room_id": self._extract_room_id(url) or "",
                "avatar_url": data.get("avatar_url", ""),
                "is_live": bool(data.get("is_live")),
                "live_status": data.get("live_status"),
                "probe_success": True,
                "raw_data": data.get("raw_data", {}),
            }
        except Exception as e:
            err_text = str(e or "")
            lower_err = err_text.lower()
            offline_markers = (
                "this live event has ended",
                "this live stream recording is not available",
                "not currently live",
            )
            permanent_offline_markers = (
                "video unavailable",
            )
            auth_markers = (
                "sign in to confirm you're not a bot",
                "cookies-from-browser or --cookies",
            )
            timeout_markers = (
                "timed out after",
                "timeout expired",
                "subprocess.timeoutexpired",
            )
            is_known_offline = any(marker in lower_err for marker in offline_markers)
            is_permanent_offline = any(marker in lower_err for marker in permanent_offline_markers)
            is_auth_required = any(marker in lower_err for marker in auth_markers)
            is_timeout = any(marker in lower_err for marker in timeout_markers)
            if is_known_offline:
                logger.debug(f"[YoutubeAdapter] 直播不可用/已结束（按离线处理）: {err_text}")
            elif is_permanent_offline:
                logger.warning(
                    f"[YoutubeAdapter] 视频已永久不可用（Video unavailable），将触发自动停止检测: {err_text}"
                )
            elif is_auth_required:
                logger.warning(
                    "[YoutubeAdapter] YouTube 触发人机验证，建议更新 YouTube Cookie（设置页->Cookie管理）"
                )
            elif is_timeout:
                logger.warning(
                    f"[YoutubeAdapter] yt-dlp 状态探测超时（非录制中断）: {err_text}"
                )
            else:
                logger.error(f"[YoutubeAdapter] yt-dlp 获取直播间信息失败: {err_text}")
            return {
                "anchor_name": "",
                "room_id": self._extract_room_id(url) or "",
                "avatar_url": "",
                "is_live": False,
                "live_status": None,
                # Video unavailable 是永久失效，标记 probe_success=False 让调度层走自动停止
                "probe_success": is_known_offline,
                "permanent_offline": is_permanent_offline,
                "raw_data": {
                    "probe_error": err_text,
                    "probe_error_type": (
                        "auth_required"
                        if is_auth_required
                        else ("permanent_offline"
                              if is_permanent_offline
                              else ("offline" if is_known_offline else ("timeout" if is_timeout else "unknown")))
                    ),
                },
            }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        try:
            data = await self._probe_with_ytdlp(url, **kwargs)
        except Exception as e:
            logger.error(f"[YoutubeAdapter] yt-dlp 获取流地址失败: {e}")
            raise

        if not isinstance(data, dict) or not data.get("is_live"):
            return {"is_live": False, "url": None}

        # YouTube 实际录制由 recorder 中 yt-dlp 执行，这里返回页面 URL 作为录制入口。
        return {
            "url": url,
            "format": "youtube",
            "play_url": url,
            "play_format": "youtube",
            "is_live": True,
            "anchor_name": data.get("anchor_name", ""),
        }

    def _extract_room_id(self, url: str) -> Optional[str]:
        if not url:
            return None
        try:
            parsed = urlparse(url)
            host = (parsed.netloc or "").lower()
            query = parse_qs(parsed.query or "")
            if "v" in query and query["v"]:
                return query["v"][0]
            if "youtu.be" in host:
                path = (parsed.path or "").strip("/")
                return path or None
            path = (parsed.path or "").strip("/")
            if path.startswith("live/"):
                return path.split("/", 1)[1] or None
        except Exception:
            return None
        return None

    def _extract_cover_url(self, data: Dict[str, Any]) -> str:
        if not isinstance(data, dict):
            return ""

        thumbnail = data.get("thumbnail")
        if isinstance(thumbnail, str) and thumbnail:
            return thumbnail

        thumbnails = data.get("thumbnails") or []
        if not isinstance(thumbnails, list):
            return ""

        best_url = ""
        best_score = -1
        for item in thumbnails:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str) or not url:
                continue
            width = item.get("width")
            height = item.get("height")
            score = 0
            if isinstance(width, int) and isinstance(height, int):
                score = width * height
            if score >= best_score:
                best_score = score
                best_url = url

        return best_url
