# -*- coding: utf-8 -*-
"""Danmu capture modules."""
import os
import sys
from typing import Callable, Dict, Optional, Type

from .base import BaseDanmuRecorder
from .bilibili_danmu import BilibiliDanmuRecorder
from .douyin_danmu import DouyinDanmuRecorder
from .twitch_danmu import TwitchDanmuRecorder
from .youtube_danmu import YoutubeDanmuRecorder

# 斗鱼弹幕使用 Node.js 版本 (Python 版本因 SSL 问题无法连接斗鱼服务器)
_douyu_node_recorder = None
if os.environ.get("EASY_VDL_USE_NODE_DOUMU", "true").lower() != "false":
    try:
        from ..douyu_danmu.douyu_wrapper import DouyuDanmuNodeProcess

        class DouyuDanmuNodeRecorder(BaseDanmuRecorder):
            """基于Node.js的斗鱼弹幕录制器"""

            def __init__(
                self,
                room_url: str,
                output_path: str,
                anchor_name: str = "",
                subscription_id: str = "",
                room_id: str = "",
                save_file: bool = True,
            ):
                self._node = DouyuDanmuNodeProcess(
                    room_id=room_id or "",
                    output_path=output_path,
                    anchor_name=anchor_name,
                    subscription_id=subscription_id,
                    save_file=save_file,
                )

            @property
            def danmu_path(self) -> str:
                return self._node.danmu_path

            @property
            def danmu_index_path(self) -> str:
                return self._node.danmu_index_path

            def start(self):
                self._node.start()

            def stop(self):
                self._node.stop()

        _douyu_node_recorder = DouyuDanmuNodeRecorder

    except ImportError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"[Danmu] 无法导入Node.js斗鱼弹幕模块: {e}")

# 虎牙弹幕使用 Node.js 版本
_huya_node_recorder = None
try:
    from ..huya_danmu.huya_wrapper import HuyaDanmuNodeProcess

    class HuyaDanmuNodeRecorder(BaseDanmuRecorder):
        """基于Node.js的虎牙弹幕录制器"""

        def __init__(
            self,
            room_url: str,
            output_path: str,
            anchor_name: str = "",
            subscription_id: str = "",
            room_id: str = "",
            save_file: bool = True,
        ):
            self._node = HuyaDanmuNodeProcess(
                room_id=room_id or "",
                output_path=output_path,
                anchor_name=anchor_name,
                subscription_id=subscription_id,
                save_file=save_file,
            )

        @property
        def danmu_path(self) -> str:
            return self._node.danmu_path

        @property
        def danmu_index_path(self) -> str:
            return self._node.danmu_index_path

        def start(self):
            self._node.start()

        def stop(self):
            self._node.stop()

    _huya_node_recorder = HuyaDanmuNodeRecorder

except ImportError as e:
    import logging

    logger = logging.getLogger(__name__)
    logger.error(f"[Danmu] 无法导入Node.js虎牙弹幕模块: {e}")

_DANMU_REGISTRY: Dict[str, Type[BaseDanmuRecorder]] = {
    "bilibili": BilibiliDanmuRecorder,
    "douyin": DouyinDanmuRecorder,
    "douyu": _douyu_node_recorder,  # Node.js only
    "huya": _huya_node_recorder,  # Node.js only
    "twitch": TwitchDanmuRecorder,
    "youtube": YoutubeDanmuRecorder,
}


def register_danmu(platform: str, recorder_cls: Type[BaseDanmuRecorder]) -> None:
    """Register a platform danmu recorder for future extension."""
    if not platform or not recorder_cls:
        return
    _DANMU_REGISTRY[platform.lower()] = recorder_cls


def is_danmu_supported(platform: str) -> bool:
    """Check whether the given platform has a registered danmaku recorder."""
    if not platform:
        return False
    return platform.lower() in _DANMU_REGISTRY


def get_danmu_recorder(
    platform: str,
    *,
    room_url: str,
    output_path: str,
    anchor_name: str = "",
    subscription_id: str = "",
    room_id: str = "",
    save_file: bool = True,
) -> Optional[BaseDanmuRecorder]:
    """Create danmu recorder instance by platform."""
    if not platform:
        return None
    recorder_cls = _DANMU_REGISTRY.get(platform.lower())
    if not recorder_cls:
        return None
    return recorder_cls(
        room_url=room_url,
        output_path=output_path,
        anchor_name=anchor_name,
        subscription_id=subscription_id,
        room_id=room_id,
        save_file=save_file,
    )
