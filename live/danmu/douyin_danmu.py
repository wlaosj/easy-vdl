# -*- coding: utf-8 -*-
"""Douyin danmu capture and file writer."""
import asyncio
import base64
import gzip
import hashlib
import json
import logging
import os
import random
import re
import threading
import time
from collections import OrderedDict
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import execjs
import requests
import websocket
from google.protobuf import json_format

from .base import BaseDanmuRecorder
from .proto.dy_pb2 import (
    PushFrame,
    Response,
    MatchAgainstScoreMessage,
    LikeMessage,
    MemberMessage,
    GiftMessage,
    ChatMessage,
    SocialMessage,
    RoomUserSeqMessage,
    UpdateFanTicketMessage,
    CommonTextMessage,
    ProductChangeMessage,
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_VERSION_CODE = 180800
DEFAULT_WEBCAST_SDK_VERSION = "1.0.14-beta.0"


class DouyinDanmuRecorder(BaseDanmuRecorder):
    """Capture douyin danmu and write to jsonl file."""

    _js_ctx_lock = threading.Lock()
    _js_ctx = None

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
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws = None
        self._file_handle = None
        self._idx_handle = None
        self._last_index_minute = None
        self._room_id = room_id or ""
        self._ttwid = ""
        self._last_room_info_ts = 0.0
        self._reconnect_failures = 0
        self._cooldown_until = 0.0
        self._last_error = ""
        self._last_close_code = None
        self._last_close_reason = ""

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
        self._thread = threading.Thread(target=self._run, name=f"douyin-danmu-{self.anchor_name}", daemon=True)
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
        reconnect_attempt = 0
        reconnecting = False
        base_delay = 2
        max_delay = 30

        while not self._stop_event.is_set():
            try:
                now = time.time()
                if self._cooldown_until and now < self._cooldown_until:
                    wait_left = max(0.0, self._cooldown_until - now)
                    logger.warning(
                        "[DouyinDanmu][reconnecting=true] 触发冷却中，%.1fs 后重试: sub_id=%s room_id=%s",
                        wait_left,
                        self.subscription_id or "-",
                        self._room_id or "-",
                    )
                    time.sleep(min(wait_left, 5))
                    continue
                if reconnecting:
                    logger.info(
                        "[DouyinDanmu][reconnecting=true] 尝试重新连接: sub_id=%s room_id=%s",
                        self.subscription_id or "-",
                        self._room_id or "-",
                    )
                room_info = None
                # 避免频繁请求触发风控：仅在必要/过期时刷新 room_id / ttwid
                refresh_ttwid = (now - self._last_room_info_ts) > 600
                if not self._room_id:
                    logger.info(
                        "[DouyinDanmu] 刷新房间信息: sub_id=%s room_id=unknown (首次)",
                        self.subscription_id or "-",
                    )
                    room_info = self._fetch_room_info()
                    self._last_room_info_ts = time.time()
                elif refresh_ttwid:
                    logger.info(
                        "[DouyinDanmu] 刷新 ttwid: sub_id=%s room_id=%s",
                        self.subscription_id or "-",
                        self._room_id or "-",
                    )
                    room_info = {"room_id": self._room_id, "ttwid": self._fetch_ttwid()}
                    self._last_room_info_ts = time.time()
                else:
                    room_info = {"room_id": self._room_id, "ttwid": self._ttwid}

                if not room_info:
                    logger.warning("[DouyinDanmu] 获取房间信息失败，准备重连")
                    raise RuntimeError("room_info_missing")

                fetched_room_id = room_info.get("room_id") or ""
                if fetched_room_id:
                    self._room_id = fetched_room_id
                self._ttwid = room_info.get("ttwid") or self._ttwid

                if not self._room_id:
                    logger.warning("[DouyinDanmu] 未能解析 room_id，准备重连")
                    raise RuntimeError("room_id_missing")

                wss_url = self._build_wss_url(self._room_id)
                if not wss_url:
                    logger.warning("[DouyinDanmu] 构建 WSS 地址失败，准备重连")
                    raise RuntimeError("wss_url_missing")

                self._open_file()

                headers = [
                    f"cookie: ttwid={self._ttwid}" if self._ttwid else "",
                    f"user-agent: {USER_AGENT}",
                ]
                headers = [h for h in headers if h]

                self._ws = websocket.WebSocketApp(
                    wss_url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                    header=headers,
                )

                self._ws.run_forever()

                # run_forever 返回后视为断开
                if self._stop_event.is_set():
                    break
                logger.warning(
                    "[DouyinDanmu][reconnecting=true] 连接已断开，准备重连: sub_id=%s room_id=%s",
                    self.subscription_id or "-",
                    self._room_id or "-",
                )
            except Exception as e:
                if self._stop_event.is_set():
                    break
                self._last_error = str(e)
                logger.warning(
                    "[DouyinDanmu][reconnecting=true] 采集线程异常，准备重连: sub_id=%s room_id=%s err=%s",
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

            reconnect_attempt += 1
            reconnecting = True
            self._reconnect_failures += 1
            # 风控/异常关键词触发冷却
            err_hint = (self._last_error or "") + " " + (self._last_close_reason or "")
            if any(k in err_hint.lower() for k in ["403", "captcha", "verify", "forbidden", "风控", "blocked"]):
                self._cooldown_until = time.time() + 300
                logger.warning(
                    "[DouyinDanmu][reconnecting=true] 触发风控冷却 300s: sub_id=%s room_id=%s hint=%s",
                    self.subscription_id or "-",
                    self._room_id or "-",
                    err_hint.strip()[:120],
                )
            delay = min(max_delay, base_delay * (2 ** (reconnect_attempt - 1)))
            if self._reconnect_failures >= 3:
                delay = max(delay, 15)
            jitter = random.uniform(0, 1.0)
            sleep_for = delay + jitter
            logger.info(
                "[DouyinDanmu][reconnecting=true] 将在 %.1fs 后重连 (attempt=%s): sub_id=%s room_id=%s",
                sleep_for,
                reconnect_attempt,
                self.subscription_id or "-",
                self._room_id or "-",
            )
            # 避免长时间 sleep 无法停止
            stop_at = time.time() + sleep_for
            while time.time() < stop_at:
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)

        reconnecting = False
        logger.info(
            "[DouyinDanmu][reconnecting=false] 已停止弹幕采集: sub_id=%s room_id=%s",
            self.subscription_id or "-",
            self._room_id or "-",
        )
        self._close_file()

    def _fetch_room_info(self) -> Optional[dict]:
        room_id = ""
        ttwid = ""
        try:
            headers = {
                "user-agent": USER_AGENT,
                "referer": "https://live.douyin.com/",
            }
            resp = requests.get(self.room_url, headers=headers, timeout=20)
            html = resp.text or ""
            ttwid = resp.cookies.get("ttwid") or ""
            room_id = self._extract_room_id_from_page(html, resp.url or "")
        except Exception as e:
            logger.debug(f"[DouyinDanmu] 页面解析 room_id 失败: {e}")

        if not room_id:
            room_id = self._fetch_room_id_from_adapter()

        return {
            "room_id": room_id,
            "ttwid": ttwid,
        }

    def _fetch_ttwid(self) -> str:
        """轻量获取 ttwid，避免解析页面内容。"""
        try:
            headers = {
                "user-agent": USER_AGENT,
                "referer": "https://live.douyin.com/",
            }
            resp = requests.get(self.room_url, headers=headers, timeout=10)
            return resp.cookies.get("ttwid") or ""
        except Exception as e:
            logger.debug(f"[DouyinDanmu] 获取 ttwid 失败: {e}")
            return ""

    def _extract_room_id_from_page(self, html: str, final_url: str) -> str:
        # 短链/中转页常会带 reflow 路径，优先尝试。
        try:
            reflow_match = re.search(r"/reflow/(\d+)", final_url or "")
            if reflow_match:
                return reflow_match.group(1)
        except Exception:
            pass

        if not html:
            return ""

        # 兼容抖音页面不同版本的字段形态。
        patterns = [
            r'roomId\\":\\"(\d+)\\"',
            r'"roomId":"(\d+)"',
            r'"room_id":"(\d+)"',
            r'"roomId":(\d+)',
            r'"room_id":(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
        return ""

    def _fetch_room_id_from_adapter(self) -> str:
        # 回退到与调度器一致的解析链路，避免页面返回验证码中间页时无法拿到 room_id。
        try:
            from live.adapters.douyin import DouyinAdapter

            async def _get_room_info():
                adapter = DouyinAdapter()
                return await adapter.get_room_info(self.room_url)

            room_info = asyncio.run(_get_room_info())
            room_id = str((room_info or {}).get("room_id") or "").strip()
            if room_id:
                logger.info("[DouyinDanmu] 使用适配器回退解析 room_id 成功: %s", room_id)
            return room_id
        except Exception as e:
            logger.debug(f"[DouyinDanmu] 适配器回退解析 room_id 失败: {e}")
            return ""

    def _build_wss_url(self, room_id: str) -> Optional[str]:
        user_unique_id = str(random.randint(7300000000000000000, 7999999999999999999))
        sig_params = OrderedDict(
            [
                ("live_id", "1"),
                ("aid", "6383"),
                ("version_code", DEFAULT_VERSION_CODE),
                ("webcast_sdk_version", DEFAULT_WEBCAST_SDK_VERSION),
                ("room_id", room_id),
                ("sub_room_id", ""),
                ("sub_channel_id", ""),
                ("did_rule", "3"),
                ("user_unique_id", user_unique_id),
                ("device_platform", "web"),
                ("device_type", ""),
                ("ac", ""),
                ("identity", "audience"),
            ]
        )
        x_ms_stub = self._get_x_ms_stub(sig_params)
        signature = self._get_signature(x_ms_stub)
        if not signature:
            return None

        params = {
            "room_id": room_id,
            "compress": "gzip",
            "version_code": DEFAULT_VERSION_CODE,
            "webcast_sdk_version": DEFAULT_WEBCAST_SDK_VERSION,
            "live_id": "1",
            "did_rule": "3",
            "user_unique_id": user_unique_id,
            "identity": "audience",
            "signature": signature,
        }
        wss_url = (
            "wss://webcast5-ws-web-lf.douyin.com/webcast/im/push/v2/?"
            + "&".join([f"{k}={v}" for k, v in params.items()])
        )
        return self._build_request_url(wss_url)

    def _build_request_url(self, url: str) -> str:
        parsed = urlparse(url)
        existing = parse_qs(parsed.query)
        existing["aid"] = ["6383"]
        existing["device_platform"] = ["web"]
        existing["browser_language"] = ["zh-CN"]
        existing["browser_platform"] = ["Win32"]
        browser_name = USER_AGENT.split("/")[0]
        browser_version = USER_AGENT.split(browser_name)[-1][1:]
        existing["browser_name"] = [browser_name]
        existing["browser_version"] = [browser_version]
        query = urlencode(existing, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))

    def _get_x_ms_stub(self, params: OrderedDict) -> str:
        sig_params = ",".join([f"{k}={v}" for k, v in params.items()])
        return hashlib.md5(sig_params.encode()).hexdigest()

    def _get_signature(self, x_ms_stub: str) -> Optional[str]:
        try:
            ctx = self._get_js_ctx()
            return ctx.call("get_sign", x_ms_stub)
        except Exception as e:
            logger.warning(f"[DouyinDanmu] 计算签名失败: {e}")
            return None

    def _get_js_ctx(self):
        if self.__class__._js_ctx is not None:
            return self.__class__._js_ctx
        with self.__class__._js_ctx_lock:
            if self.__class__._js_ctx is not None:
                return self.__class__._js_ctx
            js_path = os.path.join(os.path.dirname(__file__), "assets", "webmssdk.js")
            with open(js_path, "r", encoding="utf-8") as fh:
                js_code = fh.read()
            js_dom = (
                "document = {};\n"
                "window = {};\n"
                "navigator = {userAgent: '" + USER_AGENT + "'};\n"
            )
            self.__class__._js_ctx = execjs.compile(js_dom + js_code)
            return self.__class__._js_ctx

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
            logger.warning(f"[DouyinDanmu] 写入弹幕文件失败: {e}")

    def _on_open(self, ws):
        logger.info(
            "[DouyinDanmu] WebSocket 已连接: sub_id=%s room_id=%s",
            self.subscription_id or "-",
            self._room_id or "-",
        )
        threading.Thread(target=self._ping_loop, args=(ws,), daemon=True).start()

    def _on_message(self, ws, message: bytes):
        if self._stop_event.is_set():
            try:
                ws.close()
            except Exception:
                pass
            return
        try:
            frame = PushFrame()
            frame.ParseFromString(message)
            if frame.payload:
                payload = gzip.decompress(frame.payload)
            else:
                payload = b""
            resp = Response()
            resp.ParseFromString(payload)
            if resp.needAck:
                self._send_ack(ws, frame.logId, resp.internalExt)
            for msg in resp.messagesList:
                self._handle_message(msg)
        except Exception as e:
            logger.debug(f"[DouyinDanmu] 解析消息失败: {e}")

    def _send_ack(self, ws, log_id, internal_ext: str):
        try:
            obj = PushFrame()
            obj.payloadType = "ack"
            obj.logId = log_id
            # 兼容原实现：将 internal_ext 放入 payloadType 字段
            if internal_ext:
                obj.payloadType = internal_ext
            data = obj.SerializeToString()
            ws.send(data, websocket.ABNF.OPCODE_BINARY)
        except Exception:
            pass

    def _handle_message(self, msg):
        method = msg.method
        payload = msg.payload
        event = {
            "type": "danmu",
            "ts": time.time(),
            "method": method,
        }
        parser_map = {
            "WebcastMatchAgainstScoreMessage": MatchAgainstScoreMessage,
            "WebcastLikeMessage": LikeMessage,
            "WebcastMemberMessage": MemberMessage,
            "WebcastGiftMessage": GiftMessage,
            "WebcastChatMessage": ChatMessage,
            "WebcastSocialMessage": SocialMessage,
            "WebcastRoomUserSeqMessage": RoomUserSeqMessage,
            "WebcastUpdateFanTicketMessage": UpdateFanTicketMessage,
            "WebcastCommonTextMessage": CommonTextMessage,
            "WebcastProductChangeMessage": ProductChangeMessage,
        }
        parser_cls = parser_map.get(method)
        if parser_cls:
            obj = parser_cls()
            obj.ParseFromString(payload)
            data = json_format.MessageToDict(obj, preserving_proto_field_name=True)
        else:
            data = {
                "payload_base64": base64.b64encode(payload).decode("utf-8") if payload else "",
            }
        # Slim output: keep only fields needed for replay; raw payload can be stored later if needed.
        self._enrich_event(event, data)
        event_type = event.get("event_type")
        if event_type != "chat" and method != "WebcastChatMessage":
            return
        # Direct IM -> WS live push (avoid tailing files in live view)
        self._publish_live_danmu(event)
        self._write_line(event)

    def _enrich_event(self, event: dict, data: dict):
        data = data or {}
        method = event.get("method") or ""
        event_type = self._map_event_type(method)
        if event_type:
            event["event_type"] = event_type
        user_info = self._extract_user(data)
        if user_info:
            event["user"] = user_info
        content = self._extract_content(data)
        if content:
            event["content"] = content
        gift = self._extract_gift(data)
        if gift:
            event["gift"] = gift
        stats = self._extract_stats(data, event_type)
        if stats:
            event["stats"] = stats

    def _publish_live_danmu(self, event: dict):
        if not self.subscription_id:
            return
        try:
            from routers.websocket import publish_live_danmu
            publish_live_danmu(self.subscription_id, [event])
        except Exception:
            pass

    def _map_event_type(self, method: str) -> Optional[str]:
        mapping = {
            "WebcastChatMessage": "chat",
            "WebcastGiftMessage": "gift",
            "WebcastLikeMessage": "like",
            "WebcastMemberMessage": "member",
            "WebcastSocialMessage": "social",
            "WebcastRoomUserSeqMessage": "room_stat",
            "WebcastUpdateFanTicketMessage": "fan_ticket",
            "WebcastCommonTextMessage": "system",
            "WebcastProductChangeMessage": "product",
            "WebcastMatchAgainstScoreMessage": "match_score",
        }
        return mapping.get(method)

    def _extract_user(self, data: dict) -> Optional[dict]:
        if not isinstance(data, dict):
            return None
        candidates = []
        for key in ("user", "from_user", "user_info", "owner", "member", "sender", "audience"):
            value = data.get(key)
            if isinstance(value, dict):
                candidates.append(value)
        if not candidates:
            return None
        for user in candidates:
            nick = (
                user.get("nick_name")
                or user.get("nickname")
                or user.get("nickName")
                or user.get("display_id")
                or user.get("displayId")
                or user.get("short_id")
                or user.get("shortId")
                or user.get("unique_id")
                or user.get("uniqueId")
                or user.get("name")
            )
            user_id = (
                user.get("id")
                or user.get("id_str")
                or user.get("short_id")
                or user.get("shortId")
            )
            if nick or user_id:
                return {"id": user_id, "nickname": nick}
        return None

    def _extract_content(self, data: dict) -> Optional[str]:
        if not isinstance(data, dict):
            return None
        for key in ("content", "text", "msg", "message", "comment"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _extract_gift(self, data: dict) -> Optional[dict]:
        if not isinstance(data, dict):
            return None
        gift = data.get("gift")
        if not isinstance(gift, dict):
            return None
        gift_name = gift.get("name") or gift.get("describe")
        count = data.get("total_count") or data.get("totalCount")
        diamond = gift.get("diamondCount") or gift.get("diamond_count")
        if gift_name or count or diamond:
            return {"name": gift_name, "count": count, "diamond": diamond}
        return None

    def _extract_stats(self, data: dict, event_type: Optional[str]) -> Optional[dict]:
        if not isinstance(data, dict):
            return None
        if event_type == "like":
            total = data.get("total") or data.get("likeCount") or data.get("count")
            if total is not None:
                return {"like_total": total}
        if event_type == "member":
            member = data.get("memberCount") or data.get("member_count")
            if member is not None:
                return {"member_count": member}
        if event_type == "room_stat":
            total = data.get("total") or data.get("totalUser")
            popularity = data.get("popularity")
            stats = {}
            if total is not None:
                stats["total_user"] = total
            if popularity is not None:
                stats["popularity"] = popularity
            return stats or None
        return None

    def _on_error(self, ws, error):
        self._last_error = str(error)
        logger.warning(f"[DouyinDanmu] WebSocket error: {error}")

    def _on_close(self, ws, *args):
        try:
            if len(args) >= 2:
                self._last_close_code = args[0]
                self._last_close_reason = args[1] or ""
        except Exception:
            pass
        self._write_line({"type": "status", "ts": time.time(), "status": "closed"})
        logger.info(f"[DouyinDanmu] WebSocket closed: room_id={self._room_id}")

    def _ping_loop(self, ws):
        while not self._stop_event.is_set():
            try:
                obj = PushFrame()
                obj.payloadType = "hb"
                ws.send(obj.SerializeToString(), websocket.ABNF.OPCODE_BINARY)
            except Exception:
                break
            time.sleep(10)
