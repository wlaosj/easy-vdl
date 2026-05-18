# -*- coding: utf-8 -*-
"""Bilibili danmu capture and file writer."""

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import struct
import threading
import time
import urllib.parse
import zlib
from typing import Dict, List, Optional, Tuple

import requests
import websocket

from .base import BaseDanmuRecorder

try:
    import brotli  # type: ignore
except Exception:  # pragma: no cover
    brotli = None

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

WBI_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


class BilibiliDanmuRecorder(BaseDanmuRecorder):
    """Capture bilibili danmu and write to jsonl file."""

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
        self._room_id = str(room_id or "").strip()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws = None
        self._session = requests.Session()

        self._file_handle = None
        self._idx_handle = None
        self._last_index_minute = None

        self._reconnect_failures = 0
        self._last_error = ""
        self._cookie_map = self._load_bilibili_cookie_map()
        self._cookie_header = self._build_cookie_header(self._cookie_map)
        # 默认使用匿名模式以保护账号安全
        self._buvid3 = ""
        self._warned_brotli_missing = False

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
            name=f"bilibili-danmu-{self.anchor_name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=5)
        self._close_file()

    def _run(self):
        base_delay = 2
        max_delay = 30

        while not self._stop_event.is_set():
            try:
                room_id = self._resolve_room_id()
                if not room_id:
                    raise RuntimeError("room_id_missing")

                ws_url, token = self._get_ws_conf(room_id)
                if not ws_url or not token:
                    raise RuntimeError("ws_conf_missing")

                self._open_file()
                self._connect_and_loop(ws_url=ws_url, room_id=room_id, token=token)
                if self._stop_event.is_set():
                    break
                logger.warning(
                    "[BilibiliDanmu] 连接已断开，准备重连: sub_id=%s room_id=%s",
                    self.subscription_id or "-",
                    room_id,
                )
            except Exception as e:
                if self._stop_event.is_set():
                    break
                self._last_error = str(e)
                logger.warning(
                    "[BilibiliDanmu] 采集线程异常，准备重连: sub_id=%s room_id=%s err=%s",
                    self.subscription_id or "-",
                    self._room_id or "-",
                    e,
                )
            finally:
                try:
                    if self._ws:
                        self._ws.close()
                except Exception:
                    pass
                self._ws = None

            self._reconnect_failures += 1
            delay = min(max_delay, base_delay * (2 ** max(0, self._reconnect_failures - 1)))
            if self._reconnect_failures >= 3:
                delay = max(delay, 15)
            jitter = random.uniform(0, 1.0)
            sleep_for = delay + jitter
            logger.info(
                "[BilibiliDanmu] 将在 %.1fs 后重连: sub_id=%s room_id=%s",
                sleep_for,
                self.subscription_id or "-",
                self._room_id or "-",
            )
            stop_at = time.time() + sleep_for
            while time.time() < stop_at:
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)

        logger.info(
            "[BilibiliDanmu] 已停止弹幕采集: sub_id=%s room_id=%s",
            self.subscription_id or "-",
            self._room_id or "-",
        )
        self._close_file()

    def _connect_and_loop(self, ws_url: str, room_id: str, token: str):
        headers = [
            f"User-Agent: {USER_AGENT}",
            f"Referer: {self.room_url or 'https://live.bilibili.com/'}",
            "Origin: https://live.bilibili.com",
        ]
        self._ws = websocket.create_connection(ws_url, header=headers, timeout=10)
        self._ws.settimeout(5)

        if not self._buvid3:
            self._buvid3 = self._fetch_buvid3() or ""

        # 使用匿名 UID 以降低风险
        uid = 0

        auth_payload = {
            "uid": uid,
            "roomid": int(room_id),
            "protover": 3,
            "platform": "web",
            "type": 2,
            "key": token,
        }
        if self._buvid3:
            auth_payload["buvid"] = self._buvid3
        self._ws.send_binary(self._pack(op=7, body=json.dumps(auth_payload, separators=(",", ":")).encode("utf-8")))

        last_heartbeat = 0.0
        last_payload_ts = time.time()
        last_chat_ts = time.time()
        no_payload_timeout = 35
        no_chat_timeout = 90

        while not self._stop_event.is_set():
            now = time.time()
            if now - last_heartbeat >= 20:
                try:
                    # KeepLiveWS uses "{}" for heartbeat body.
                    self._ws.send_binary(self._pack(op=2, body=b"{}"))
                    last_heartbeat = now
                except Exception as e:
                    raise RuntimeError(f"heartbeat_send_failed: {e}")

            try:
                raw = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                continue

            if isinstance(raw, str):
                raw = raw.encode("utf-8", errors="ignore")

            for ver, op, _seq, body in self._unpack_packets(raw):
                if op == 8:
                    self._reconnect_failures = 0
                    logger.info(
                        "[BilibiliDanmu] 鉴权成功: sub_id=%s room_id=%s",
                        self.subscription_id or "-",
                        room_id,
                    )
                    continue
                if op == 3:
                    continue
                if op != 5:
                    continue

                last_payload_ts = time.time()
                for msg in self._parse_payload(ver, op, body):
                    event = self._convert_message(msg)
                    if not event:
                        continue
                    if event.get("event_type") != "chat":
                        continue
                    last_chat_ts = time.time()
                    self._publish_live_danmu(event)
                    self._write_line(event)

            # Some nodes occasionally only emit system events; reconnect and rotate node.
            now = time.time()
            if now - last_payload_ts > no_payload_timeout:
                raise RuntimeError("danmu_payload_timeout")
            if now - last_chat_ts > no_chat_timeout:
                raise RuntimeError("danmu_chat_timeout")

    def _resolve_room_id(self) -> str:
        # 如果已经有 room_id 且看起来像长号（> 10,000,000），则直接返回
        # 注意：B 站有些长号也比较短，但绝大多数短号都在 1-7 位之间。
        # 最稳妥的办法是：如果 room_id < 10,000,000，强制解析一次。
        if self._room_id and self._room_id.isdigit():
            if int(self._room_id) > 10000000:
                return self._room_id

        raw_id = self._room_id
        if not raw_id:
            try:
                match = re.search(r"live\.bilibili\.com/(\d+)", self.room_url or "")
                if match:
                    raw_id = match.group(1)
            except Exception:
                raw_id = ""

        if not raw_id:
            return ""

        headers = self._build_http_headers(raw_id)
        try:
            api = f"https://api.live.bilibili.com/room/v1/Room/room_init?id={raw_id}"
            resp = self._session.get(api, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    rid = str((data.get("data") or {}).get("room_id") or "").strip()
                    if rid.isdigit():
                        self._room_id = rid
                        logger.info("[BilibiliDanmu] Room ID resolved: %s -> %s", raw_id, rid)
                        return rid
        except Exception as e:
            logger.debug(f"[BilibiliDanmu] room_init 解析失败: {e}")

        try:
            from live.adapters.bilibili import BilibiliAdapter

            async def _get_room_info():
                adapter = BilibiliAdapter()
                return await adapter.get_room_info(self.room_url)

            room_info = asyncio.run(_get_room_info())
            rid = str((room_info or {}).get("room_id") or "").strip()
            if rid.isdigit():
                self._room_id = rid
                return rid
        except Exception as e:
            logger.debug(f"[BilibiliDanmu] 适配器回退解析 room_id 失败: {e}")

        return ""

    def _get_ws_conf(self, room_id: str) -> Tuple[str, str]:
        headers = self._build_http_headers(room_id)

        # 优先尝试带 WBI 签名的新接口（可规避 -352 风控），失败后再回退
        try:
            data = self._get_signed_danmu_info(room_id, headers)
            if data.get("code") == 0:
                ws_url, token = self._build_ws_endpoint(data.get("data") or {})
                if ws_url and token:
                    return ws_url, token
        except Exception as e:
            logger.debug(f"[BilibiliDanmu] WBI getDanmuInfo 失败，尝试回退: {e}")

        # 无签名直接请求（低优先级）
        try:
            api = (
                "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo"
                f"?id={room_id}&type=0"
            )
            resp = self._session.get(api, headers=headers, timeout=10)
            data = resp.json()
            if data.get("code") == 0:
                ws_url, token = self._build_ws_endpoint(data.get("data") or {})
                if ws_url and token:
                    return ws_url, token
        except Exception as e:
            logger.debug(f"[BilibiliDanmu] 无签名 getDanmuInfo 失败，尝试回退: {e}")

        api = (
            "https://api.live.bilibili.com/room/v1/Danmu/getConf"
            f"?room_id={room_id}&platform=pc&player=web"
        )
        resp = self._session.get(api, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"getConf_failed: {str(data)[:180]}")
        ws_url, token = self._build_ws_endpoint(data.get("data") or {})
        if not ws_url or not token:
            raise RuntimeError("invalid_danmu_conf")
        return ws_url, token

    def _build_ws_endpoint(self, data: Dict) -> Tuple[str, str]:
        token = str(data.get("token") or "")
        host_list = data.get("host_list") or data.get("host_server_list") or data.get("server_list") or []
        if not isinstance(host_list, list):
            host_list = []
        if not host_list:
            host = data.get("host")
            port = data.get("wss_port") or data.get("port") or 443
            if host:
                ws_url = f"wss://{host}:{int(port)}/sub"
                return ws_url, token
            return "", token

        # Rotate host by reconnect count to avoid getting stuck on a stale node.
        idx = self._reconnect_failures % len(host_list)
        host_info = host_list[idx]
        host = host_info.get("host")
        port = host_info.get("wss_port") or host_info.get("port") or 443
        if not host:
            return "", token
        return f"wss://{host}:{int(port)}/sub", token

    def _build_http_headers(self, room_id: str) -> Dict[str, str]:
        headers = {
            "user-agent": USER_AGENT,
            "referer": self.room_url or f"https://live.bilibili.com/{room_id}",
            "origin": "https://live.bilibili.com",
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }
        return headers

    def _load_bilibili_cookie_map(self) -> Dict[str, str]:
        cookie_paths = [
            "/app/database/cookie/bilibili_cookie.txt",
            os.path.join(os.getcwd(), "database", "cookie", "bilibili_cookie.txt"),
        ]
        for path in cookie_paths:
            try:
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                if not content:
                    continue
                parsed = self._parse_cookie_content(content)
                if parsed:
                    return parsed
            except Exception:
                continue
        return {}

    def _parse_cookie_content(self, cookie_str: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        text = (cookie_str or "").strip()
        if not text:
            return result

        # Netscape 格式（兼容 tab 与异常 '?' 分隔）
        if "\t" in text or text.startswith("#"):
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t") if "\t" in line else line.split("?")
                if len(parts) >= 7:
                    name = str(parts[5]).strip()
                    value = str(parts[6]).strip()
                    if name:
                        result[name] = value
            return result

        # 纯 Cookie Header 格式
        text = re.sub(r"^\s*cookie\s*:\s*", "", text, flags=re.IGNORECASE)
        for pair in text.replace("\r", "").replace("\n", "").split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            name = name.strip()
            if name:
                result[name] = value.strip()
        return result

    def _build_cookie_header(self, cookie_map: Dict[str, str]) -> str:
        if not cookie_map:
            return ""
        preferred_keys = [
            "SESSDATA",
            "bili_jct",
            "DedeUserID",
            "DedeUserID__ckMd5",
            "buvid3",
            "buvid4",
            "b_nut",
            "_uuid",
        ]
        pairs = []
        for k in preferred_keys:
            v = cookie_map.get(k)
            if v:
                pairs.append(f"{k}={v}")
        if pairs:
            return "; ".join(pairs)
        return "; ".join([f"{k}={v}" for k, v in cookie_map.items() if k])

    def _fetch_buvid3(self) -> str:
        try:
            resp = self._session.get(
                "https://api.bilibili.com/x/frontend/finger/spi",
                headers={"user-agent": USER_AGENT},
                timeout=10,
            )
            data = resp.json()
            return str(((data.get("data") or {}).get("b_3") or "")).strip()
        except Exception:
            return ""

    def _get_wbi_keys(self, headers: Dict[str, str]) -> Tuple[str, str]:
        resp = self._session.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=headers,
            timeout=10,
        )
        data = resp.json()
        wbi_img = (data.get("data") or {}).get("wbi_img") or {}
        img_url = str(wbi_img.get("img_url") or "")
        sub_url = str(wbi_img.get("sub_url") or "")
        if not img_url or not sub_url:
            raise RuntimeError("wbi_keys_missing")
        img_key = os.path.splitext(os.path.basename(urllib.parse.urlparse(img_url).path))[0]
        sub_key = os.path.splitext(os.path.basename(urllib.parse.urlparse(sub_url).path))[0]
        if not img_key or not sub_key:
            raise RuntimeError("invalid_wbi_keys")
        return img_key, sub_key

    def _get_wbi_mixin_key(self, orig: str) -> str:
        mixed = []
        for idx in WBI_MIXIN_KEY_ENC_TAB:
            if idx < len(orig):
                mixed.append(orig[idx])
        return "".join(mixed)[:32]

    def _sign_wbi_params(self, params: Dict[str, str], img_key: str, sub_key: str) -> Dict[str, str]:
        mixin_key = self._get_wbi_mixin_key(img_key + sub_key)
        signed = {k: str(v) for k, v in (params or {}).items()}
        signed["wts"] = str(int(time.time()))
        filtered: Dict[str, str] = {}
        for k in sorted(signed.keys()):
            filtered[k] = re.sub(r"[!'()*]", "", str(signed[k]))
        query = urllib.parse.urlencode([(k, filtered[k]) for k in sorted(filtered.keys())])
        filtered["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
        return filtered

    def _get_signed_danmu_info(self, room_id: str, headers: Dict[str, str]) -> Dict:
        img_key, sub_key = self._get_wbi_keys(headers)
        params = self._sign_wbi_params({"id": str(room_id), "type": "0"}, img_key, sub_key)
        api = "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo"
        resp = self._session.get(api, params=params, headers=headers, timeout=10)
        return resp.json()

    def _pack(self, op: int, body: bytes = b"", ver: int = 1, seq: int = 1) -> bytes:
        header_len = 16
        packet_len = header_len + len(body)
        return struct.pack(">IHHII", packet_len, header_len, ver, op, seq) + body

    def _unpack_packets(self, buf: bytes):
        offset = 0
        total = len(buf)
        while offset + 16 <= total:
            packet_len, header_len, ver, op, seq = struct.unpack(">IHHII", buf[offset : offset + 16])
            if packet_len < 16:
                break
            body = buf[offset + header_len : offset + packet_len]
            yield ver, op, seq, body
            offset += packet_len

    def _parse_payload(self, ver: int, op: int, body: bytes) -> List[dict]:
        messages: List[dict] = []
        if op != 5:
            return messages

        if ver in (0, 1):
            try:
                msg = json.loads(body.decode("utf-8", errors="ignore"))
                if isinstance(msg, dict):
                    messages.append(msg)
            except Exception:
                return messages
            return messages

        if ver == 2:
            try:
                decompressed = zlib.decompress(body)
            except Exception:
                return messages
            for sub_ver, sub_op, _sub_seq, sub_body in self._unpack_packets(decompressed):
                messages.extend(self._parse_payload(sub_ver, sub_op, sub_body))
            return messages

        if ver == 3 and brotli is not None:
            try:
                decompressed = brotli.decompress(body)
            except Exception:
                return messages
            for sub_ver, sub_op, _sub_seq, sub_body in self._unpack_packets(decompressed):
                messages.extend(self._parse_payload(sub_ver, sub_op, sub_body))
            return messages

        if ver == 3 and brotli is None and not self._warned_brotli_missing:
            self._warned_brotli_missing = True
            logger.warning("[BilibiliDanmu] brotli 未安装，ver=3 压缩弹幕包将被丢弃")

        return messages

    def _convert_message(self, msg: dict) -> Optional[dict]:
        if not isinstance(msg, dict):
            return None

        payload = msg
        if not payload.get("cmd") and isinstance(payload.get("msg"), dict):
            payload = payload.get("msg") or {}

        raw_cmd = str(payload.get("cmd") or "")
        cmd = raw_cmd.split(":", 1)[0]
        if not cmd:
            return None

        event = {
            "type": "danmu",
            "ts": time.time(),
            "method": cmd,
        }

        if cmd == "DANMU_MSG":
            info = payload.get("info") or []
            text = ""
            uid = ""
            uname = ""
            try:
                if isinstance(info, list) and len(info) > 1:
                    text = str(info[1] or "").strip()
                if isinstance(info, list) and len(info) > 2 and isinstance(info[2], list):
                    uid = str(info[2][0]) if len(info[2]) > 0 else ""
                    uname = str(info[2][1]) if len(info[2]) > 1 else ""
            except Exception:
                pass

            if not text:
                return None

            event["event_type"] = "chat"
            event["content"] = text
            event["user"] = {
                "id": uid,
                "name": uname,
            }
            return event

        if cmd == "SEND_GIFT":
            data = payload.get("data") or {}
            event["event_type"] = "gift"
            event["user"] = {
                "id": str(data.get("uid") or ""),
                "name": str(data.get("uname") or ""),
            }
            event["gift"] = {
                "name": str(data.get("giftName") or ""),
                "count": int(data.get("num") or 0),
                "price": float(data.get("total_coin") or 0) / 1000.0,
            }
            return event

        if cmd == "SUPER_CHAT_MESSAGE":
            data = payload.get("data") or {}
            event["event_type"] = "gift"
            event["content"] = str(data.get("message") or "")
            user_info = data.get("user_info") or {}
            event["user"] = {
                "id": str(user_info.get("uid") or ""),
                "name": str(user_info.get("uname") or ""),
            }
            event["gift"] = {
                "name": "super_chat",
                "count": 1,
                "price": float(data.get("price") or 0),
            }
            return event

        if cmd in ("LIKE_INFO_V3_CLICK", "LIKE_INFO_V3_UPDATE"):
            event["event_type"] = "like"
            return event

        if cmd in ("WATCHED_CHANGE", "ONLINE_RANK_COUNT", "ONLINE_RANK_V2"):
            event["event_type"] = "room_stat"
            return event

        if cmd in ("NOTICE_MSG", "COMMON_NOTICE_DANMAKU"):
            event["event_type"] = "system"
            return event

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
            logger.warning(f"[BilibiliDanmu] 写入弹幕文件失败: {e}")

    def _publish_live_danmu(self, event: dict):
        if not self.subscription_id:
            return
        try:
            from routers.websocket import publish_live_danmu

            publish_live_danmu(self.subscription_id, [event])
        except Exception:
            pass
