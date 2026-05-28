# -*- coding: utf-8 -*-
"""Twitch danmu capture and file writer using standard IRC protocol."""

import json
import logging
import os
import random
import re
import socket
import threading
import time
from typing import Dict, Optional
from urllib.parse import urlparse

from .base import BaseDanmuRecorder

logger = logging.getLogger(__name__)


class TwitchDanmuRecorder(BaseDanmuRecorder):
    """Capture Twitch live chat (danmu) via anonymous IRC and write to jsonl file."""

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
        self._sock: Optional[socket.socket] = None

        self._file_handle = None
        self._idx_handle = None
        self._last_index_minute = None

        self._reconnect_failures = 0
        self._last_error = ""

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
            name=f"twitch-danmu-{self.anchor_name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        try:
            if self._sock:
                self._sock.shutdown(socket.SHUT_RDWR)
                self._sock.close()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=5)
        self._close_file()

    def _extract_channel_name(self) -> str:
        """Extract Twitch channel name (lowercase) from room url or room_id."""
        if self._room_id and not self._room_id.isdigit():
            # If room_id is already the channel username
            return self._room_id.strip().lower()

        if not self.room_url:
            return ""
        try:
            parsed = urlparse(self.room_url)
            path = (parsed.path or "").strip("/")
            if path:
                # handles twitch.tv/username or twitch.tv/username/
                return path.split("/", 1)[0].lower()
        except Exception as e:
            logger.debug(f"[TwitchDanmu] Failed to extract channel name: {e}")
        return ""

    def _run(self):
        base_delay = 2
        max_delay = 30

        while not self._stop_event.is_set():
            try:
                channel = self._extract_channel_name()
                if not channel:
                    raise RuntimeError("twitch_channel_name_missing")

                self._open_file()
                self._connect_and_loop(channel)
                if self._stop_event.is_set():
                    break
                logger.warning(
                    "[TwitchDanmu] 连接已断开，准备重连: sub_id=%s channel=%s",
                    self.subscription_id or "-",
                    channel,
                )
            except Exception as e:
                if self._stop_event.is_set():
                    break
                self._last_error = str(e)
                logger.warning(
                    "[TwitchDanmu] 采集线程异常，准备重连: sub_id=%s err=%s",
                    self.subscription_id or "-",
                    e,
                )
            finally:
                try:
                    if self._sock:
                        self._sock.close()
                except Exception:
                    pass
                self._sock = None

            self._reconnect_failures += 1
            delay = min(max_delay, base_delay * (2 ** max(0, self._reconnect_failures - 1)))
            if self._reconnect_failures >= 3:
                delay = max(delay, 15)
            jitter = random.uniform(0, 1.0)
            sleep_for = delay + jitter
            logger.info(
                "[TwitchDanmu] 将在 %.1fs 后重连: sub_id=%s",
                sleep_for,
                self.subscription_id or "-",
            )
            stop_at = time.time() + sleep_for
            while time.time() < stop_at:
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)

        logger.info(
            "[TwitchDanmu] 已停止弹幕采集: sub_id=%s",
            self.subscription_id or "-",
        )
        self._close_file()

    def _connect_and_loop(self, channel: str):
        server = "irc.chat.twitch.tv"
        port = 6667
        
        # Generate random anonymous nickname
        rand_num = random.randint(100000000, 999999999)
        nick = f"justinfan{rand_num}"

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(10.0)
        self._sock.connect((server, port))

        # Send anonymous login credentials
        self._sock.send(f"NICK {nick}\r\n".encode("utf-8"))
        self._sock.send(f"JOIN #{channel}\r\n".encode("utf-8"))

        self._reconnect_failures = 0
        logger.info(
            "[TwitchDanmu] 成功连接并加入频道: sub_id=%s channel=%s",
            self.subscription_id or "-",
            channel,
        )

        buffer = ""
        last_heartbeat_response = time.time()
        timeout_limit = 120.0  # Twitch server should ping us or send messages

        while not self._stop_event.is_set():
            try:
                data = self._sock.recv(4096)
                if not data:
                    raise RuntimeError("socket_closed_by_remote")
                
                buffer += data.decode("utf-8", errors="ignore")
            except socket.timeout:
                # Check for absolute quietness
                if time.time() - last_heartbeat_response > timeout_limit:
                    raise RuntimeError("irc_ping_timeout")
                continue
            except Exception as e:
                raise RuntimeError(f"socket_recv_error: {e}")

            # Process completed lines
            while "\r\n" in buffer:
                line, buffer = buffer.split("\r\n", 1)
                if not line:
                    continue

                # Respond to Twitch server ping to prevent disconnection
                if line.startswith("PING"):
                    try:
                        self._sock.send("PONG :tmi.twitch.tv\r\n".encode("utf-8"))
                        last_heartbeat_response = time.time()
                    except Exception as e:
                        raise RuntimeError(f"pong_send_failed: {e}")
                    continue

                # Parse IRC PRIVMSG
                # Format: :user!user@user.tmi.twitch.tv PRIVMSG #channel :message
                if " PRIVMSG #" in line:
                    event = self._parse_irc_line(line)
                    if event:
                        self._publish_live_danmu(event)
                        self._write_line(event)
                        last_heartbeat_response = time.time()

    def _parse_irc_line(self, line: str) -> Optional[dict]:
        try:
            # Match IRC PRIVMSG line
            match = re.match(r"^:([^!]+)![^ ]+ PRIVMSG #[^ ]+ :(.+)$", line)
            if not match:
                return None

            user_nick = match.group(1)
            content = match.group(2)

            return {
                "type": "danmu",
                "ts": time.time(),
                "method": "PRIVMSG",
                "event_type": "chat",
                "content": content,
                "user": {
                    "id": user_nick,
                    "name": user_nick,
                },
            }
        except Exception as e:
            logger.debug(f"[TwitchDanmu] Failed to parse IRC line: {e}")
            return None

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
            logger.warning(f"[TwitchDanmu] 写入弹幕文件失败: {e}")

    def _publish_live_danmu(self, event: dict):
        if not self.subscription_id:
            return
        try:
            from routers.websocket import publish_live_danmu

            publish_live_danmu(self.subscription_id, [event])
        except Exception:
            pass
