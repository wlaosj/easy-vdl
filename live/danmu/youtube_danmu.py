# -*- coding: utf-8 -*-
"""YouTube Live Chat (danmu) capture via InnerTube API.

Reverse-engineered from Playwright traffic capture.
Protocol: JSON API, no protobuf, no signing.
Polling: POST youtubei/v1/live_chat/get_live_chat?key=...
State: continuation token (refreshed each response).
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests

try:
    from .base import BaseDanmuRecorder
except ImportError:
    # Allow standalone import for testing
    from live.danmu.base import BaseDanmuRecorder

logger = logging.getLogger(__name__)

YT_BASE = "https://www.youtube.com/youtubei/v1"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
)
FALLBACK_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"


def _extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from various URL formats."""
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()

    # youtu.be/VIDEO_ID
    if "youtu.be" in host:
        path = (parsed.path or "").strip("/")
        if path and not path.startswith("@"):
            return path.split("/")[0]

    # youtube.com/live/VIDEO_ID  or  youtube.com/watch?v=VIDEO_ID
    if "youtube.com" in host or "yt.be" in host:
        # /live/VIDEO_ID
        path = (parsed.path or "").strip("/")
        if path.startswith("live/"):
            vid = path.split("/", 1)[1]
            if vid:
                return vid.split("/")[0]

        # watch?v=VIDEO_ID
        qs = parse_qs(parsed.query or "")
        if "v" in qs and qs["v"][0]:
            return qs["v"][0]

    return None


def _resolve_live_via_ytdlp(url: str) -> Optional[str]:
    """Use yt-dlp to find the current live video_id from a channel URL."""
    try:
        import subprocess
        result = subprocess.run(
            ["yt-dlp", "-j", "--no-download", "--no-warnings", url],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            vid = data.get("id") or ""
            live_status = data.get("live_status") or ""
            if vid and live_status in ("is_live", "is_upcoming", "was_live"):
                return vid
    except Exception as e:
        logger.debug(f"[YTDanmu] yt-dlp resolve failed: {e}")
    return None


def _extract_api_key(html: str) -> str:
    m = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
    return m.group(1) if m else FALLBACK_API_KEY


def _extract_client_version(html: str) -> str:
    m = re.search(r'"INNERTUBE_CONTEXT_CLIENT_VERSION"\s*:\s*"([^"]+)"', html)
    return m.group(1) if m else "2.20241203.10.00"


def _extract_initial_continuation(html: str) -> str:
    """Extract the first continuation token from ytInitialData."""
    idx = html.find("ytInitialData")
    if idx < 0:
        return ""

    start = html.find("{", idx)
    if start < 0:
        return ""

    depth = 0
    in_str = False
    escape = False
    end = start
    for i in range(start, len(html)):
        ch = html[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    try:
        data = json.loads(html[start:end])
    except json.JSONDecodeError:
        return ""

    # Navigate to liveChatRenderer.continuations
    try:
        top = data.get("contents", {}).get("twoColumnWatchNextResults", {})
        bar = top.get("conversationBar", {})
        # Can be conversationBar.liveChatRenderer or conversationBar.conversationBarRenderer.liveChatRenderer
        lcr = bar.get("liveChatRenderer")
        if not lcr:
            cbr = bar.get("conversationBarRenderer", {})
            lcr = cbr.get("liveChatRenderer")
        if not lcr:
            return ""
        conts = lcr.get("continuations", [])
    except (KeyError, TypeError):
        return ""

    for c in conts:
        for key in ("invalidationContinuationData", "timedContinuationData",
                     "reloadContinuationData", "liveChatContinuationData"):
            entry = c.get(key)
            if entry and entry.get("continuation"):
                return entry["continuation"]
    return ""


def _build_payload(api_key: str, client_version: str, continuation: str) -> dict:
    return {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": client_version,
                "acceptLanguage": "en-US",
                "deviceMake": "",
                "deviceModel": "",
                "userAgent": UA,
                "hl": "en-US",
                "gl": "US",
                "timeZone": "America/New_York",
            }
        },
        "continuation": continuation,
    }


def _build_headers(api_key: str, client_version: str) -> dict:
    return {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Origin": "https://www.youtube.com",
        "X-YouTube-Client-Name": "1",
        "X-YouTube-Client-Version": client_version,
    }


def _runs_to_text(runs: list[dict]) -> str:
    return "".join(r.get("text", "") for r in runs)


def _parse_poll_response(data: dict) -> tuple[list[dict], Optional[str], float]:
    """Parse API response into EDL-standard events + next continuation + timeout."""
    events: list[dict] = []
    ts = time.time()

    lcc = data.get("continuationContents", {}).get("liveChatContinuation", {})
    if not lcc:
        return events, None, 5.0

    # Extract next continuation
    next_cont: Optional[str] = None
    poll_timeout = 5.0
    for c in lcc.get("continuations", []):
        for key in ("invalidationContinuationData", "timedContinuationData"):
            entry = c.get(key)
            if entry and entry.get("continuation"):
                next_cont = entry["continuation"]
                poll_timeout = entry.get("timeoutMs", 5000) / 1000
                break
        if next_cont:
            break

    # Parse actions
    for action in lcc.get("actions", []):
        chat_item = action.get("addChatItemAction", {})
        if not chat_item:
            continue
        item = chat_item.get("item", {})

        # Ordinary chat message
        msg = item.get("liveChatTextMessageRenderer")
        if msg:
            author = (msg.get("authorName", {}).get("simpleText", "") or "").lstrip("@")
            text = _runs_to_text(msg.get("message", {}).get("runs", []))
            if text:
                events.append({
                    "type": "danmu",
                    "ts": ts,
                    "method": "liveChatTextMessageRenderer",
                    "event_type": "chat",
                    "content": text,
                    "user": {"name": author, "id": author},
                })
            continue

        # Super Chat (paid)
        paid = item.get("liveChatPaidMessageRenderer")
        if paid:
            author = (paid.get("authorName", {}).get("simpleText", "") or "").lstrip("@")
            text = _runs_to_text(paid.get("message", {}).get("runs", []))
            amount = paid.get("purchaseAmountText", {}).get("simpleText", "")
            events.append({
                "type": "danmu",
                "ts": ts,
                "method": "liveChatPaidMessageRenderer",
                "event_type": "chat",
                "content": text,
                "user": {"name": author, "id": author},
                "gift": {"name": "super_chat", "count": 1, "price": amount},
            })
            continue

        # Membership
        member = item.get("liveChatMembershipItemRenderer")
        if member:
            author = (member.get("authorName", {}).get("simpleText", "") or "").lstrip("@")
            text = member.get("headerSubtext", {}).get("simpleText", "") or "Joined as member"
            events.append({
                "type": "danmu",
                "ts": ts,
                "method": "liveChatMembershipItemRenderer",
                "event_type": "chat",
                "content": text,
                "user": {"name": author, "id": author},
            })
            continue

    return events, next_cont, poll_timeout


def _fetch_initial_context(video_id: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Fetch YouTube live page and return (continuation, api_key, client_version)."""
    url = f"https://www.youtube.com/live/{video_id}"
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        resp.raise_for_status()
        html = resp.text
        cont = _extract_initial_continuation(html)
        api_key = _extract_api_key(html)
        client_ver = _extract_client_version(html)
        return cont, api_key, client_ver
    except Exception as e:
        logger.warning(f"[YTDanmu] Failed to fetch page: {e}")
        return None, None, None


class YoutubeDanmuRecorder(BaseDanmuRecorder):
    """Capture YouTube live chat via InnerTube HTTP polling and write to jsonl."""

    def __init__(
        self,
        room_url: str,
        output_path: str,
        anchor_name: str = "",
        subscription_id: str = "",
        save_file: bool = True,
        room_id: str = "",
    ):
        self.room_url = room_url
        self.output_path = output_path
        self.anchor_name = anchor_name or "unknown"
        self.subscription_id = subscription_id or ""
        self.save_file = save_file
        self._room_id = room_id or ""

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._file_handle = None
        self._idx_handle = None
        self._last_index_minute = None

        self._video_id: Optional[str] = None
        self._api_key: Optional[str] = None
        self._client_version: Optional[str] = None

    @property
    def danmu_path(self) -> str:
        if not self.output_path:
            return ""
        base = self.output_path.rsplit(".", 1)[0]
        return f"{base}.danmu.jsonl"

    @property
    def danmu_index_path(self) -> str:
        if not self.output_path:
            return ""
        base = self.output_path.rsplit(".", 1)[0]
        return f"{base}.danmu.idx.jsonl"

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name=f"yt-danmu-{self.anchor_name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._close_file()

    def _resolve_video_id(self) -> Optional[str]:
        """Resolve the current live video_id from room_url."""
        # Try direct extraction first
        vid = _extract_video_id(self.room_url)
        if vid:
            return vid

        # Fallback: try yt-dlp on the channel URL
        logger.info(
            "[YTDanmu] No direct video_id in URL, resolving via yt-dlp: sub_id=%s",
            self.subscription_id or "-",
        )
        vid = _resolve_live_via_ytdlp(self.room_url)
        return vid

    def _run(self):
        if self._stop_event.is_set():
            return

        # 1. Resolve video_id
        video_id = self._resolve_video_id()
        if not video_id:
            logger.warning(
                "[YTDanmu] Could not resolve video_id, will retry: sub_id=%s url=%s",
                self.subscription_id or "-",
                self.room_url,
            )
            # Retry with backoff
            for attempt in range(5):
                if self._stop_event.is_set():
                    return
                time.sleep(5 * (attempt + 1))
                video_id = self._resolve_video_id()
                if video_id:
                    break

        if not video_id:
            logger.error(
                "[YTDanmu] Failed to resolve video_id after retries: sub_id=%s",
                self.subscription_id or "-",
            )
            return

        self._video_id = video_id
        logger.info(
            "[YTDanmu] Resolved video_id=%s for sub_id=%s",
            video_id, self.subscription_id or "-",
        )

        # 2. Fetch initial page context
        cont, api_key, client_ver = _fetch_initial_context(video_id)
        if not cont:
            logger.warning(
                "[YTDanmu] No continuation found (chat may be disabled): sub_id=%s video=%s",
                self.subscription_id or "-",
                video_id,
            )
            return

        self._api_key = api_key
        self._client_version = client_ver

        # 3. Open output files
        self._open_file()

        # 4. Polling loop
        self._poll_loop(cont)

        self._close_file()
        logger.info(
            "[YTDanmu] Stopped: sub_id=%s",
            self.subscription_id or "-",
        )

    def _poll_loop(self, initial_continuation: str):
        """Main poll loop: runs until stopped or unrecoverable error."""
        cont = initial_continuation
        consecutive_errors = 0
        empty_polls = 0

        while not self._stop_event.is_set():
            try:
                events, next_cont, timeout = self._poll_once(cont)
            except Exception as e:
                consecutive_errors += 1
                logger.warning(
                    "[YTDanmu] Poll error (%d/%d): sub_id=%s err=%s",
                    consecutive_errors, 5, self.subscription_id or "-", e,
                )
                if consecutive_errors >= 5:
                    logger.error(
                        "[YTDanmu] Too many poll errors, stopping: sub_id=%s",
                        self.subscription_id or "-",
                    )
                    break
                time.sleep(min(15, 2 ** consecutive_errors))
                continue

            consecutive_errors = 0

            if not events:
                empty_polls += 1
            else:
                empty_polls = 0
                for event in events:
                    self._publish_live_danmu(event)
                    self._write_line(event)

            # If continuation is the same and we got no events for many polls,
            # the stream may have ended
            if empty_polls > 60:  # ~10 mins of empty polls
                logger.info(
                    "[YTDanmu] Stream appears ended (empty polls): sub_id=%s",
                    self.subscription_id or "-",
                )
                break

            cont = next_cont or cont
            timeout = max(1.0, min(timeout, 30.0))

            # Sleep with stop_event check
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)

    def _poll_once(self, continuation: str) -> tuple[list[dict], Optional[str], float]:
        """Single poll cycle. Returns (events, next_continuation, timeout)."""
        url = f"{YT_BASE}/live_chat/get_live_chat?key={self._api_key}&prettyPrint=false"
        resp = requests.post(
            url,
            headers=_build_headers(self._api_key, self._client_version),
            json=_build_payload(self._api_key, self._client_version, continuation),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return _parse_poll_response(data)

    # ── File I/O ───────────────────────────────────────────────

    def _open_file(self):
        if not self.save_file or not self.output_path:
            return
        os.makedirs(os.path.dirname(self.danmu_path), exist_ok=True)
        self._file_handle = open(self.danmu_path, "a", encoding="utf-8")
        self._idx_handle = open(self.danmu_index_path, "a", encoding="utf-8")

    def _close_file(self):
        if self._file_handle:
            try:
                self._file_handle.flush()
                self._file_handle.close()
            except Exception:
                pass
            self._file_handle = None
        if self._idx_handle:
            try:
                self._idx_handle.flush()
                self._idx_handle.close()
            except Exception:
                pass
            self._idx_handle = None

    def _write_line(self, data: dict):
        if not self.save_file:
            return
        if not self._file_handle:
            return
        try:
            ts = data.get("ts")
            if ts is None:
                ts = time.time()
                data["ts"] = ts
            minute_bucket = int(float(ts) // 60)
            if self._idx_handle and minute_bucket != self._last_index_minute:
                try:
                    offset = self._file_handle.tell()
                    idx_line = {
                        "minute_ts": minute_bucket * 60,
                        "offset": offset,
                    }
                    self._idx_handle.write(json.dumps(idx_line, ensure_ascii=False) + "\n")
                    self._idx_handle.flush()
                    self._last_index_minute = minute_bucket
                except Exception:
                    pass
            self._file_handle.write(json.dumps(data, ensure_ascii=False) + "\n")
            self._file_handle.flush()
        except Exception as e:
            logger.warning(f"[YTDanmu] 写入弹幕文件失败: {e}")

    def _publish_live_danmu(self, event: dict):
        if not self.subscription_id:
            return
        try:
            from routers.websocket import publish_live_danmu
            publish_live_danmu(self.subscription_id, [event])
        except Exception:
            pass
