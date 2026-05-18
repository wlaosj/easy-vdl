# -*- coding: utf-8 -*-
"""
Douyu弹幕录制 - Node.js进程管理封装
将Node.js独立进程作为子进程运行，Python只负责启动/停止/监控
"""
import subprocess
import os
import threading
import logging
import json
import time
from typing import Optional

logger = logging.getLogger(__name__)


class DouyuDanmuNodeProcess:
    """管理Douyu弹幕Node.js子进程的封装类"""

    def __init__(
        self,
        room_id: str,
        output_path: str,
        anchor_name: str = "",
        subscription_id: str = "",
        node_path: str = None,
        save_file: bool = True,
    ):
        self.room_id = str(room_id)
        self.output_path = output_path
        self.anchor_name = anchor_name or "unknown"
        self.subscription_id = subscription_id or ""
        self.save_file = save_file

        # 弹幕文件路径
        base = output_path.rsplit(".", 1)[0]
        self._danmu_path = f"{base}.danmu.jsonl"
        self._danmu_index_path = f"{base}.danmu.idx.jsonl"

        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        # Node.js路径
        self._node_path = node_path or "node"
        self._script_dir = os.path.dirname(os.path.abspath(__file__))
        self._script_path = os.path.join(self._script_dir, "douyu_danmu_collector.js")

    @property
    def danmu_path(self) -> str:
        return self._danmu_path

    @property
    def danmu_index_path(self) -> str:
        return self._danmu_index_path

    def start(self):
        """启动Node.js弹幕采集子进程"""
        if self._running:
            return

        # 确保输出目录存在
        if self.save_file:
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        # 构建命令
        cmd = [
            self._node_path,
            self._script_path,
            self.room_id,
            self.output_path,
            self.anchor_name,
            "true" if self.save_file else "false",
        ]

        logger.info(
            f"[DouyuDanmu] 启动Node.js弹幕进程: room={self.room_id}, output={self.output_path}"
        )

        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._running = True
            self._stop_event.clear()

            # 启动stdout读取线程
            self._thread = threading.Thread(
                target=self._read_stdout,
                name=f"douyu-danmu-{self.anchor_name}",
                daemon=True,
            )
            self._thread.start()

        except Exception as e:
            logger.error(f"[DouyuDanmu] 启动Node进程失败: {e}")
            self._running = False
            raise

    def _read_stdout(self):
        """读取Node.js进程的stdout，解析日志消息"""
        if not self._process or not self._process.stdout:
            return

        try:
            for line in self._process.stdout:
                if self._stop_event.is_set():
                    break

                if not line:
                    continue

                try:
                    msg = json.loads(line)
                    msg_type = msg.get("type", "")

                    if msg_type == "log":
                        logger.info(f"[DouyuDanmu] Room {msg.get('roomId')}: {msg.get('msg')}")
                    elif msg_type == "status":
                        logger.info(f"[DouyuDanmu] Status: {msg}")
                    elif msg_type == "danmu_event":
                        # 实时弹幕事件，推送到WebSocket
                        event = msg.get("event", {})
                        if event and self.subscription_id:
                            self._publish_danmu(event)
                except json.JSONDecodeError:
                    # 非JSON格式，直接输出
                    logger.debug(f"[DouyuDanmu] Node输出: {line.strip()}")

        except Exception as e:
            logger.warning(f"[DouyuDanmu] stdout读取异常: {e}")

    def _publish_danmu(self, event: dict):
        """推送弹幕事件到WebSocket"""
        if not self.subscription_id:
            return
        try:
            from routers.websocket import publish_live_danmu
            publish_live_danmu(self.subscription_id, [event])
        except Exception as e:
            logger.debug(f"[DouyuDanmu] 推送弹幕失败: {e}")

    def stop(self):
        """停止Node.js弹幕采集子进程"""
        if not self._running:
            return

        logger.info(f"[DouyuDanmu] 停止Node.js弹幕进程: room={self.room_id}")

        self._stop_event.set()

        try:
            # 发送stop命令到stdin
            if self._process and self._process.stdin:
                try:
                    self._process.stdin.write(json.dumps({"cmd": "stop"}) + "\n")
                    self._process.stdin.flush()
                except Exception:
                    pass

            # 等待进程结束
            if self._process:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"[DouyuDanmu] 停止Node进程时出错: {e}")

        self._running = False
        self._process = None

        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def is_running(self) -> bool:
        """检查进程是否运行中"""
        if not self._running or not self._process:
            return False

        # 检查进程是否还在运行
        if self._process.poll() is not None:
            self._running = False
            return False

        return True

    def send_command(self, cmd: str):
        """发送命令到stdin"""
        if not self._process or not self._process.stdin:
            return

        try:
            self._process.stdin.write(json.dumps({"cmd": cmd}) + "\n")
            self._process.stdin.flush()
        except Exception as e:
            logger.warning(f"[DouyuDanmu] 发送命令失败: {e}")

    def get_status(self):
        """获取弹幕进程状态"""
        return {
            "running": self.is_running(),
            "room_id": self.room_id,
            "anchor_name": self.anchor_name,
            "danmu_path": self.danmu_path,
        }
