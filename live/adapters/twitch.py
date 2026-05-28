import logging
import json
import subprocess
import asyncio
import os
import time
from typing import Dict, Any, Optional
from pathlib import Path
from urllib.parse import urlparse

from .base import BaseAdapter

logger = logging.getLogger(__name__)


class TwitchAdapter(BaseAdapter):
    """Twitch 直播适配器"""

    @property
    def platform_name(self) -> str:
        return "twitch"

    def is_match(self, url: str) -> bool:
        u = (url or "").lower()
        return "twitch.tv" in u

    def _resolve_cookie_file(self, cookie_file: Optional[str] = None) -> Optional[str]:
        """解析可用的 Twitch cookie 文件路径。"""
        candidates = []
        if cookie_file:
            candidates.append(cookie_file)
        candidates.append("/app/database/cookie/twitch_cookie.txt")
        candidates.append(str(Path(__file__).resolve().parents[2] / "database" / "cookie" / "twitch_cookie.txt"))

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
                        is_live = bool(data.get("is_live")) or live_status == "is_live"
                        anchor_name = data.get("uploader") or data.get("channel") or ""
                        cover_url = data.get("thumbnail") or ""
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
                "is offline",
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
            is_auth_required = any(marker in lower_err for marker in auth_markers)
            is_timeout = any(marker in lower_err for marker in timeout_markers)

            if is_known_offline:
                logger.debug(f"[TwitchAdapter] 直播不可用/已结束（按离线处理）: {err_text}")
            elif is_auth_required:
                logger.warning(
                    "[TwitchAdapter] Twitch 触发身份验证，建议配置 Twitch Cookie（设置页->Cookie管理）"
                )
            elif is_timeout:
                logger.warning(
                    f"[TwitchAdapter] yt-dlp 状态探测超时: {err_text}"
                )
            else:
                logger.error(f"[TwitchAdapter] yt-dlp 获取直播间信息失败: {err_text}")

            return {
                "anchor_name": "",
                "room_id": self._extract_room_id(url) or "",
                "avatar_url": "",
                "is_live": False,
                "live_status": None,
                "probe_success": is_known_offline,
                "raw_data": {
                    "probe_error": err_text,
                    "probe_error_type": (
                        "auth_required"
                        if is_auth_required
                        else ("offline" if is_known_offline else ("timeout" if is_timeout else "unknown"))
                    ),
                },
            }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        try:
            data = await self._probe_with_ytdlp(url, **kwargs)
        except Exception as e:
            logger.error(f"[TwitchAdapter] yt-dlp 获取流地址失败: {e}")
            raise

        if not isinstance(data, dict) or not data.get("is_live"):
            return {"is_live": False, "url": None}

        # Twitch 实际录制由 recorder 中 yt-dlp 执行，这里返回页面 URL 作为录制入口。
        return {
            "url": url,
            "format": "twitch",
            "play_url": url,
            "play_format": "twitch",
            "is_live": True,
            "anchor_name": data.get("anchor_name", ""),
        }

    def _extract_room_id(self, url: str) -> Optional[str]:
        if not url:
            return None
        try:
            parsed = urlparse(url)
            path = (parsed.path or "").strip("/")
            # 支持 m.twitch.tv/username 或 twitch.tv/username
            if path:
                return path.split("/", 1)[0]
        except Exception:
            return None
        return None
