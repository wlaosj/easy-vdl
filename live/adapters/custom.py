# -*- coding: utf-8 -*-
"""
自定义视频流适配器

支持录制任意视频流（RTMP、RTSP、HLS/m3u8、HTTP-FLV 等），
通过 FFprobe / HTTP 探测来判断流是否在线。
"""
import hashlib
import json
import logging
from urllib.parse import urlparse
from typing import Dict, Any, Optional

import httpx

from .base import BaseAdapter

logger = logging.getLogger(__name__)

# 流协议 / 格式识别常量
HLS_EXTENSIONS = (".m3u8",)
FLV_EXTENSIONS = (".flv",)
STREAM_PROTOCOLS = ("rtmp://", "rtmps://", "rtsp://")


class CustomAdapter(BaseAdapter):
    """自定义视频流适配器"""

    @property
    def platform_name(self) -> str:
        return "custom"

    def is_match(self, url: str) -> bool:
        """识别任意视频流 URL

        CustomAdapter 在适配器列表末尾，仅当无平台适配器匹配时才会触发。
        因此 is_match 可放宽匹配条件而不影响已有平台。
        """
        lower = url.strip().lower()
        # 已知流协议
        if any(lower.startswith(p) for p in STREAM_PROTOCOLS):
            return True
        # 已知流文件后缀
        if any(ext in lower for ext in HLS_EXTENSIONS + FLV_EXTENSIONS):
            return True
        # 通用 HTTP(S) URL（无平台适配器匹配时兜底）
        if lower.startswith("http://") or lower.startswith("https://"):
            return True
        return False

    # ----------------------------------------------------------------
    # 流探测（核心）
    # ----------------------------------------------------------------

    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        """探测流地址是否在线，返回标准化信息"""
        anchor_name = kwargs.get("anchor_name", "") or self._generate_name(url)
        probe_result = await self._probe_stream(url)
        return {
            "anchor_name": anchor_name,
            "room_id": self._url_to_id(url),
            "avatar_url": None,
            "is_live": probe_result["is_live"],
            "probe_success": True,
            "raw_data": {
                "format": probe_result.get("format", "unknown"),
                "probe_error": probe_result.get("error"),
            },
        }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        """自定义流的 URL 本身就是流地址，无需额外解析"""
        probe = await self._probe_stream(url)
        fmt = probe.get("format", "unknown")
        return {
            "url": url,
            "format": fmt,
            "is_live": probe["is_live"],
            "anchor_name": kwargs.get("anchor_name", ""),
        }

    # ----------------------------------------------------------------
    # 内部工具方法
    # ----------------------------------------------------------------

    @staticmethod
    def _detect_format(url: str) -> str:
        """根据 URL 识别流格式"""
        lower = url.strip().lower()
        if any(ext in lower for ext in HLS_EXTENSIONS):
            return "hls"
        if any(ext in lower for ext in FLV_EXTENSIONS):
            return "http_flv"
        if lower.startswith("rtmp://"):
            return "rtmp"
        if lower.startswith("rtmps://"):
            return "rtmps"
        if lower.startswith("rtsp://"):
            return "rtsp"
        if lower.startswith("http://") or lower.startswith("https://"):
            return "http_stream"
        return "unknown"

    @staticmethod
    def _url_to_id(url: str) -> str:
        """将 URL 哈希为稳定的房间 ID"""
        return hashlib.md5(url.encode()).hexdigest()[:12]

    @staticmethod
    def _generate_name(url: str) -> str:
        """从 URL 自动生成流名称"""
        try:
            parsed = urlparse(url)
            if parsed.hostname:
                return f"自定义流 - {parsed.hostname}"
        except Exception:
            pass
        return "自定义流"

    # ----------------------------------------------------------------
    # 三层探测策略
    # ----------------------------------------------------------------

    async def _probe_stream(self, url: str) -> dict:
        """按 URL 格式分发到对应的探测方法"""
        fmt = self._detect_format(url)
        try:
            if fmt == "hls":
                result = await self._probe_hls(url)
            elif fmt == "http_flv":
                result = await self._probe_http_flv(url)
            elif fmt in ("rtmp", "rtmps"):
                result = await self._probe_ffprobe(url, timeout=12)
            elif fmt == "rtsp":
                result = await self._probe_ffprobe(url, timeout=10)
            else:
                # HTTP 流及其他：先用 ffprobe 通用探测
                result = await self._probe_ffprobe(url, timeout=10)
        except Exception as e:
            logger.warning(f"[CustomAdapter] 探测流异常: {url}, {e}")
            result = {"is_live": False, "error": str(e)}
        result["format"] = fmt
        return result

    # ----- HLS 探测 -----

    async def _probe_hls(self, url: str) -> dict:
        """HLS (m3u8) 流探测：
        - 获取 playlist 内容
        - 有 #EXTINF 分段标记 且 无 #EXT-X-ENDLIST → 直播在线
        """
        try:
            async with httpx.AsyncClient(
                timeout=8, follow_redirects=True
            ) as client:
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/131.0.0.0 Safari/537.36"
                        )
                    },
                )
                if resp.status_code != 200:
                    return {
                        "is_live": False,
                        "error": f"HTTP {resp.status_code}",
                    }
                body = resp.text
                has_inf = "#EXTINF:" in body
                has_endlist = "#EXT-X-ENDLIST" in body
                # 直播流：有分段标记且未结束
                is_live = has_inf and not has_endlist
                return {"is_live": is_live, "error": None}
        except httpx.TimeoutException:
            return {"is_live": False, "error": "timeout"}
        except Exception as e:
            return {"is_live": False, "error": str(e)}

    # ----- HTTP-FLV 探测 -----

    async def _probe_http_flv(self, url: str) -> dict:
        """HTTP-FLV 流探测：
        先 HEAD 检查可达性，再用 ffprobe 确认是否有音视频流
        """
        # 快速 HTTP 可达性检查
        try:
            async with httpx.AsyncClient(
                timeout=5, follow_redirects=True
            ) as client:
                resp = await client.head(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/131.0.0.0 Safari/537.36"
                        ),
                    },
                )
                if resp.status_code >= 400:
                    logger.debug(
                        f"[CustomAdapter] HTTP-FLV HEAD {resp.status_code} for {url[:80]}"
                    )
        except Exception as e:
            # HEAD 失败不一定代表流不可用（某些源站不支持 HEAD）
            logger.debug(
                f"[CustomAdapter] HTTP-FLV HEAD 失败，继续 ffprobe: {e}"
            )

        # ffprobe 确认（传 User-Agent）
        return await self._probe_ffprobe(url, timeout=8)

    # ----- FFprobe 通用探测 -----

    async def _probe_ffprobe(self, url: str, timeout: int = 10) -> dict:
        """使用 ffprobe 探测流地址：
        读取流元数据，检查是否有 video / audio 流
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_entries", "stream=codec_type",
            "-user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "-timeout", f"{max(timeout - 2, 3) * 1000000}",
            "-rw_timeout", f"{max(timeout - 2, 3) * 1000000}",
            url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout + 3
            )
            if proc.returncode != 0:
                err_text = (stderr or b"").decode("utf-8", errors="ignore")[:200]
                return {"is_live": False, "error": err_text or f"exit={proc.returncode}"}
            data = json.loads(stdout)
            streams = data.get("streams", [])
            has_video = any(
                s.get("codec_type") == "video" for s in streams
            )
            has_audio = any(
                s.get("codec_type") == "audio" for s in streams
            )
            is_live = has_video or has_audio
            return {"is_live": is_live, "error": None}
        except asyncio.TimeoutError:
            return {"is_live": False, "error": "timeout"}
        except Exception as e:
            return {"is_live": False, "error": str(e)}


# 在文件末尾引入 asyncio（ffprobe 需要）
import asyncio
