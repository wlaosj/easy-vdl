import logging
from typing import Dict, Any
from .base import BaseAdapter
from ..core import spider
from ..core.http_clients.async_http import get_response_status

logger = logging.getLogger(__name__)

class HuyaAdapter(BaseAdapter):
    """虎牙直播适配器"""
    
    @property
    def platform_name(self) -> str:
        return "huya"
        
    def is_match(self, url: str) -> bool:
        return "huya.com" in url

    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        """获取直播间信息"""
        try:
            # 虎牙的抓取函数同时也返回了流信息，非常全面
            data = await spider.get_huya_app_stream_url(url)
            
            return {
                "anchor_name": data.get("anchor_name", ""),
                "room_id": self._extract_room_id(url),
                # spider.get_huya_app_stream_url 现已返回 avatar_url，这里直接透传；
                # 若接口无头像字段则保持为空字符串，前端自然显示为默认头像。
                "avatar_url": data.get("avatar_url", "") or "",
                "is_live": data.get("is_live", False),
                "title": data.get("title", ""),
                "raw_data": data
            }
        except Exception as e:
            logger.error(f"[HuyaAdapter] 获取信息失败: {e}")
            return {
                "anchor_name": "",
                "room_id": self._extract_room_id(url),
                "avatar_url": "",
                "is_live": False,
                "raw_data": {}
            }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        try:
            # 重新获取最新状态
            data = await spider.get_huya_app_stream_url(url)
            
            if not data.get("is_live", False):
                return {"is_live": False, "url": None}
            
            # 止血策略：
            # 1) 先按 CDN 优先级尝试 FLV，再尝试同 CDN 的 m3u8
            # 2) 通过轻量探测选择可用链路，降低“开录秒退”
            # 3) 如果探测全部失败，回退到原先优先链路，确保不比旧逻辑更差
            priority_order = ["TX", "HW", "HS", "AL"]
            reconnect_round = int(kwargs.get("reconnect_round") or 0)
            restart_try = int(kwargs.get("restart_try") or 0)
            rotate_offset = (max(0, reconnect_round - 1) + max(0, restart_try)) % len(priority_order)
            ordered_cdns = priority_order[rotate_offset:] + priority_order[:rotate_offset]
            cdn_rank = {name: idx for idx, name in enumerate(ordered_cdns)}

            prefer_m3u8_first = ((reconnect_round + restart_try) % 2 == 1)
            excluded_routes = kwargs.get("excluded_routes") or []
            excluded_route_set = {str(route) for route in excluded_routes if route}

            raw_list = data.get("play_url_list") or []
            play_url_list = [item for item in raw_list if isinstance(item, dict)]
            play_url_list.sort(key=lambda item: cdn_rank.get(item.get("cdn_type"), 999))

            candidates = []
            for item in play_url_list:
                cdn_type = item.get("cdn_type", "UNKNOWN")
                flv_url = item.get("flv_url")
                m3u8_url = item.get("m3u8_url")
                if prefer_m3u8_first:
                    if m3u8_url:
                        candidates.append(("m3u8", m3u8_url, cdn_type))
                    if flv_url:
                        candidates.append(("flv", flv_url, cdn_type))
                else:
                    if flv_url:
                        candidates.append(("flv", flv_url, cdn_type))
                    if m3u8_url:
                        candidates.append(("m3u8", m3u8_url, cdn_type))

            # 兼容旧字段兜底
            fallback_items = [
                ("flv", data.get("record_url"), "fallback"),
                ("flv", data.get("flv_url"), "fallback"),
                ("m3u8", data.get("m3u8_url"), "fallback"),
            ]
            for fmt, url_item, cdn in fallback_items:
                if url_item:
                    candidates.append((fmt, url_item, cdn))

            dedup_candidates = []
            seen_urls = set()
            for fmt, url_item, cdn in candidates:
                if not url_item or url_item in seen_urls:
                    continue
                route_tag = f"{cdn}:{fmt}"
                if route_tag in excluded_route_set:
                    continue
                seen_urls.add(url_item)
                dedup_candidates.append((fmt, url_item, cdn))

            selected_format = "flv"
            selected_url = None
            selected_cdn = "fallback"
            for fmt, candidate_url, cdn in dedup_candidates:
                try:
                    ok = await get_response_status(
                        url=candidate_url,
                        proxy_addr=kwargs.get("proxy"),
                        timeout=5,
                        http2=False
                    )
                    if ok:
                        selected_format = fmt
                        selected_url = candidate_url
                        selected_cdn = cdn
                        break
                except Exception:
                    pass

            if not selected_url:
                # 探测失败时保持旧行为兜底，避免探测误判导致不可用
                fallback_candidates = [
                    ("flv", data.get("record_url"), "fallback"),
                    ("flv", data.get("flv_url"), "fallback"),
                    ("m3u8", data.get("m3u8_url"), "fallback"),
                ]
                if prefer_m3u8_first:
                    fallback_candidates = [fallback_candidates[2], fallback_candidates[0], fallback_candidates[1]]

                for fmt, candidate_url, cdn in fallback_candidates:
                    if not candidate_url:
                        continue
                    route_tag = f"{cdn}:{fmt}"
                    if route_tag in excluded_route_set:
                        continue
                    selected_url = candidate_url
                    selected_format = fmt
                    selected_cdn = cdn
                    break

                logger.warning(
                    f"[HuyaAdapter] 可用性探测全部失败，回退到兜底流。"
                    f"excluded={sorted(excluded_route_set)}, rotate={ordered_cdns}, prefer_m3u8={prefer_m3u8_first}"
                )
            else:
                logger.info(
                    f"[HuyaAdapter] 选中可用流: cdn={selected_cdn}, format={selected_format}, "
                    f"excluded={sorted(excluded_route_set)}, rotate={ordered_cdns}, prefer_m3u8={prefer_m3u8_first}"
                )

            return {
                "url": selected_url,
                "format": selected_format,
                "is_live": True,
                "anchor_name": data.get("anchor_name", ""),
                "source_cdn": selected_cdn
            }
        except Exception as e:
            logger.error(f"[HuyaAdapter] 获取流失败: {e}")
            raise

    def _extract_room_id(self, url: str) -> str:
        try:
            return url.split("/")[-1].split("?")[0]
        except:
            return ""
