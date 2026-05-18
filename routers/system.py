from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
import httpx
import os
import shutil
import subprocess
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import glob
import io
import zipfile
import logging
import asyncio
import time
import threading
from collections import deque
from pydantic import BaseModel  # 新增导入
from sql.models import User
from routers.auth import get_current_user
import platform

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/time")
def get_container_time():
    """返回容器当前时间（含时区信息）"""
    now = datetime.now().astimezone()
    return {
        "timestamp_ms": int(now.timestamp() * 1000),
        "iso": now.isoformat(),
        "timezone": str(now.tzinfo),
        "local": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

# 存储使用统计缓存（参考直播模式：后台任务定期计算）
_storage_cache = {
    "directory_size_bytes": 0,
    "total_gb": 0,
    "used_gb": 0,
    "free_gb": 0,
    "usage_percentage": 0,
    "last_update_ts": 0
}
_storage_cache_lock = asyncio.Lock()
# 最近活动缓存（最近6条已完成任务）
_recent_activity_cache = []
_recent_activity_cache_lock = asyncio.Lock()
_storage_calculation_task = None  # 后台存储计算任务
_recent_activity_task = None     # 后台活动更新任务

# GPU 指标缓存（避免页面频繁刷新时重复执行慢命令）
_gpu_stats_cache = {
    "payload": None,
    "last_update_ts": 0.0
}
_gpu_stats_cache_lock = asyncio.Lock()

_qsv_probe_cache: Dict[str, Any] = {
    "payload": None,
    "ts": 0.0
}
_qsv_probe_cache_lock = threading.Lock()
# GPU 固定采样周期（秒）：后台单任务定时刷新，接口只读缓存。
_GPU_MONITOR_INTERVAL_SECONDS = 2.0
_gpu_monitor_task = None


def _invalidate_gpu_stats_cache() -> None:
    """设置变更后立即清空 GPU 监控缓存，确保前端拿到最新策略状态。"""
    _gpu_stats_cache["payload"] = None
    _gpu_stats_cache["last_update_ts"] = 0.0


def _run_command_quiet(cmd: List[str], timeout: float = 2.5) -> tuple[int, str, str]:
    """运行系统命令并返回 (returncode, stdout, stderr)。"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def _truncate_text(text: str, max_chars: int = 4000) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


def _command_snapshot(cmd: List[str], timeout: float = 4.0, max_chars: int = 4000) -> Dict:
    code, stdout, stderr = _run_command_quiet(cmd, timeout=timeout)
    return {
        "cmd": " ".join(cmd),
        "returncode": code,
        "stdout": _truncate_text(stdout, max_chars=max_chars),
        "stderr": _truncate_text(stderr, max_chars=max_chars)
    }


def _qsv_probe_cache_ttl_seconds() -> int:
    raw = os.getenv("EASY_VDL_QSV_PROBE_CACHE_SECONDS", "600")
    try:
        value = int(str(raw).strip())
    except Exception:
        value = 600
    return max(60, value)


def _pick_dri_device() -> Optional[str]:
    dri_dir = "/dev/dri"
    if not os.path.isdir(dri_dir):
        return None
    try:
        entries = sorted(os.listdir(dri_dir))
    except Exception:
        return None
    render_nodes = [os.path.join(dri_dir, e) for e in entries if e.startswith("renderD")]
    card_nodes = [os.path.join(dri_dir, e) for e in entries if e.startswith("card")]
    for candidate in render_nodes + card_nodes:
        if os.path.exists(candidate):
            return candidate
    return None


def _run_qsv_probe_snapshot() -> Dict[str, Any]:
    device = _pick_dri_device()
    if not device:
        return {
            "cmd": "",
            "returncode": 127,
            "stdout": "",
            "stderr": "未找到 /dev/dri 设备节点"
        }
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-init_hw_device", f"qsv=hw:{device}",
        "-filter_hw_device", "hw",
        "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.5",
        "-vf", "hwupload=extra_hw_frames=32,vpp_qsv=w=160:h=90:format=nv12",
        "-c:v", "h264_qsv",
        "-frames:v", "1",
        "-f", "null", "-"
    ]
    return _command_snapshot(cmd, timeout=6.0)


def _get_cached_qsv_probe(force_refresh: bool = False) -> Dict[str, Any]:
    ttl = _qsv_probe_cache_ttl_seconds()
    now = time.time()
    with _qsv_probe_cache_lock:
        cached = _qsv_probe_cache.get("payload")
        cached_ts = float(_qsv_probe_cache.get("ts") or 0.0)
        if not force_refresh and cached and (now - cached_ts) < ttl:
            return dict(cached)
        payload = _run_qsv_probe_snapshot()
        _qsv_probe_cache["payload"] = payload
        _qsv_probe_cache["ts"] = now
        return dict(payload)


def _safe_float(value: str) -> Optional[float]:
    """把字符串解析为 float，失败返回 None。"""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _detect_pci_gpu_vendors() -> set[str]:
    """通过 lspci 尽力识别当前机器存在的 GPU 厂商。"""
    vendors: set[str] = set()
    try:
        code, stdout, _ = _run_command_quiet(["lspci", "-Dnn"], timeout=2.5)
        if code != 0 or not stdout:
            return vendors
        for line in stdout.splitlines():
            lower = line.lower()
            if "8086:" in lower and ("vga" in lower or "display" in lower or "3d" in lower):
                vendors.add("intel")
            if ("1002:" in lower or "1022:" in lower) and ("vga" in lower or "display" in lower or "3d" in lower):
                vendors.add("amd")
            if "10de:" in lower and ("vga" in lower or "display" in lower or "3d" in lower):
                vendors.add("nvidia")
    except Exception:
        pass
    return vendors


def _has_dri_nodes() -> bool:
    """判断容器内是否存在可用 /dev/dri 节点。"""
    try:
        dri_path = Path("/dev/dri")
        if not dri_path.exists() or not dri_path.is_dir():
            return False
        # 至少需要 card* 或 renderD* 任一设备节点
        has_card = any(dri_path.glob("card*"))
        has_render = any(dri_path.glob("renderD*"))
        return has_card or has_render
    except Exception:
        return False


def _parse_intel_gpu_top_util(stdout: str) -> Optional[float]:
    """从 intel_gpu_top -J 输出中提取一个总体利用率（尽力而为）。"""
    if not stdout:
        return None
    try:
        normalized = stdout.strip().replace("\n", "").replace("\t", "")
        normalized = normalized.replace("}{", "},{")
        # timeout 截断时可能缺少结尾 ']'，尽量补全
        if normalized.startswith("[") and not normalized.endswith("]") and "}" in normalized:
            normalized = normalized + "]"
        if not normalized.startswith("["):
            normalized = f"[{normalized}]"
        try:
            data = json.loads(normalized)
        except Exception:
            # 容错：提取第一个完整对象再解析
            start = normalized.find("{")
            end = normalized.rfind("}")
            if start >= 0 and end > start:
                data = json.loads(f"[{normalized[start:end+1]}]")
            else:
                return None
        if not isinstance(data, list):
            return None
        # 第二帧通常比第一帧更稳定
        sample = data[1] if len(data) > 1 else data[0]
        engines = sample.get("engines", {}) if isinstance(sample, dict) else {}
        util_candidates = []
        for key, value in engines.items():
            if not isinstance(value, dict):
                continue
            busy = value.get("busy")
            busy_num = _safe_float(busy)
            if busy_num is not None:
                util_candidates.append(busy_num)
        if util_candidates:
            return round(max(util_candidates), 1)
    except Exception:
        return None
    return None


def _collect_nvidia_gpu_stats() -> List[Dict]:
    """采集 NVIDIA 显卡指标。"""
    if not shutil.which("nvidia-smi"):
        pci_vendors = _detect_pci_gpu_vendors()
        if "nvidia" in pci_vendors:
            return [{
                "vendor": "nvidia",
                "name": "NVIDIA GPU",
                "status": "degraded",
                "error": "检测到 NVIDIA GPU，但容器内未找到 nvidia-smi（请检查 --gpus all 与 nvidia-container-toolkit）",
            }]
        return []

    query_fields = ",".join([
        "index",
        "name",
        "utilization.gpu",
        "temperature.gpu",
        "memory.total",
        "memory.used",
        "power.draw",
        "power.limit",
    ])
    cmd = [
        "nvidia-smi",
        f"--query-gpu={query_fields}",
        "--format=csv,noheader,nounits",
    ]
    code, stdout, stderr = _run_command_quiet(cmd, timeout=2.5)
    if code != 0 or not stdout:
        return [{
            "vendor": "nvidia",
            "name": "NVIDIA",
            "status": "error",
            "error": stderr or "nvidia-smi 执行失败",
        }]

    gpus: List[Dict] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        gpus.append({
            "vendor": "nvidia",
            "index": parts[0],
            "name": parts[1],
            "util_percent": _safe_float(parts[2]),
            "temperature_c": _safe_float(parts[3]),
            "memory_total_mb": _safe_float(parts[4]),
            "memory_used_mb": _safe_float(parts[5]),
            "power_w": _safe_float(parts[6]),
            "power_limit_w": _safe_float(parts[7]),
            "status": "ok",
        })
    return gpus


def _collect_intel_gpu_stats() -> List[Dict]:
    """采集 Intel 显卡基础指标（尽力而为）。"""
    if not _has_dri_nodes():
        return []

    pci_vendors = _detect_pci_gpu_vendors()
    has_intel_pci = "intel" in pci_vendors

    has_intel_cmd = shutil.which("intel_gpu_top") is not None
    if not has_intel_cmd:
        if has_intel_pci:
            return [{
                "vendor": "intel",
                "name": "Intel GPU",
                "status": "degraded",
                "error": "检测到 Intel GPU，但未找到 intel_gpu_top（请安装 intel-gpu-tools）",
            }]
        return []

    # 若系统里没有 Intel 显卡，则不返回伪数据
    try:
        if not has_intel_pci:
            return []
    except Exception:
        pass

    # intel_gpu_top 在某些环境可能需要更高权限，因此容错返回
    # 旧版本 intel_gpu_top 不支持 -n 参数，改为 timeout 截断采样。
    # 这里采用稳健组合：timeout 2.0 + -s 500，保证至少两帧输出。
    code, stdout, stderr = _run_command_quiet(
        ["timeout", "2.0", "intel_gpu_top", "-J", "-s", "500"],
        timeout=2.8
    )
    # timeout 返回码 124 也可能携带有效输出
    if code not in (0, 124):
        err_msg = stderr or "intel_gpu_top 执行失败"
        if "Failed to initialize PMU" in err_msg:
            err_msg = "intel_gpu_top 无权限访问 PMU（需放宽 perf_event_paranoid 或提升容器权限）"
        return [{
            "vendor": "intel",
            "name": "Intel GPU",
            "status": "degraded",
            "error": err_msg,
        }]

    util = _parse_intel_gpu_top_util(stdout)
    err_msg = None
    if util is None:
        err_msg = "无法从 intel_gpu_top 解析利用率"
        if stderr and "Failed to initialize PMU" in stderr:
            err_msg = "intel_gpu_top 无权限访问 PMU（需放宽 perf_event_paranoid 或提升容器权限）"
    return [{
        "vendor": "intel",
        "name": "Intel GPU",
        "util_percent": util,
        "status": "ok" if util is not None else "degraded",
        "error": err_msg,
    }]


def _parse_amd_radeontop_util(stdout: str) -> Optional[float]:
    """从 radeontop 输出解析 GPU 利用率。"""
    if not stdout:
        return None
    try:
        # 常见格式: gpu 12.34%, ...
        match = re.search(r"\bgpu\s+([0-9]+(?:\.[0-9]+)?)%", stdout, re.IGNORECASE)
        if match:
            return round(float(match.group(1)), 1)
    except Exception:
        return None
    return None


def _read_text_file(path: Path) -> Optional[str]:
    """读取文本文件并去除空白，失败返回 None。"""
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None


def _map_pci_vendor(vendor_hex: str) -> str:
    """将 PCI vendor id 映射为可读厂商名。"""
    normalized = (vendor_hex or "").strip().lower()
    mapping = {
        "0x10de": "nvidia",
        "0x8086": "intel",
        "0x1002": "amd",
        "0x1022": "amd",
    }
    return mapping.get(normalized, "unknown")


def _collect_dri_gpu_stats() -> List[Dict]:
    """通过 DRM sysfs 兜底识别 GPU（命令不可用时仍可识别设备）。"""
    if not _has_dri_nodes():
        return []

    cards: List[Dict] = []
    for card_path in sorted(Path("/sys/class/drm").glob("card*")):
        card_name = card_path.name
        # 跳过连接器节点（例如 card0-DP-1）
        if not re.fullmatch(r"card\d+", card_name):
            continue

        device_path = card_path / "device"
        if not device_path.exists():
            continue

        vendor_id = _read_text_file(device_path / "vendor")
        device_id = _read_text_file(device_path / "device")
        uevent = _read_text_file(device_path / "uevent") or ""

        vendor = _map_pci_vendor(vendor_id or "")
        driver = None
        for line in uevent.splitlines():
            if line.startswith("DRIVER="):
                driver = line.split("=", 1)[1].strip()
                break

        # 尽力读取利用率（不同驱动路径不同）
        util_percent = None
        for candidate in [
            device_path / "gpu_busy_percent",
            card_path / "gt_busy_percent",
            device_path / "gt_busy_percent",
        ]:
            value = _read_text_file(candidate)
            if value is not None:
                util_percent = _safe_float(value)
                if util_percent is not None:
                    break

        # 尽力读取温度
        temperature_c = None
        for temp_file in device_path.glob("hwmon/*/temp1_input"):
            raw = _read_text_file(temp_file)
            num = _safe_float(raw) if raw is not None else None
            if num is not None:
                # 常见单位为毫摄氏度
                temperature_c = round(num / 1000.0, 1) if num > 1000 else round(num, 1)
                break

        display_vendor = vendor.upper() if vendor != "unknown" else "GPU"
        display_name = f"{display_vendor} ({card_name})"

        cards.append({
            "vendor": vendor,
            "name": display_name,
            "card": card_name,
            "device_id": device_id,
            "pci_vendor_id": vendor_id,
            "driver": driver,
            "util_percent": util_percent,
            "temperature_c": temperature_c,
            "status": "ok" if util_percent is not None else "degraded",
            "source": "drm_sysfs",
            "error": None if util_percent is not None else "仅识别到设备，未读取到实时利用率",
        })

    return cards


def _collect_amd_gpu_stats() -> List[Dict]:
    """采集 AMD 显卡基础指标（尽力而为）。"""
    if not _has_dri_nodes():
        return []

    pci_vendors = _detect_pci_gpu_vendors()
    has_amd_pci = "amd" in pci_vendors

    has_amd_cmd = shutil.which("radeontop") is not None
    if not has_amd_cmd:
        if has_amd_pci:
            return [{
                "vendor": "amd",
                "name": "AMD GPU",
                "status": "degraded",
                "error": "检测到 AMD GPU，但未找到 radeontop（请安装 radeontop）",
            }]
        return []

    # 若系统里没有 AMD 显卡，则不返回伪数据
    try:
        if not has_amd_pci:
            return []
    except Exception:
        pass

    code, stdout, stderr = _run_command_quiet(
        ["radeontop", "-d", "-", "-l", "1"],
        timeout=3.0
    )
    if code != 0:
        return [{
            "vendor": "amd",
            "name": "AMD GPU",
            "status": "degraded",
            "error": stderr or "radeontop 执行失败",
        }]

    util = _parse_amd_radeontop_util(stdout)
    return [{
        "vendor": "amd",
        "name": "AMD GPU",
        "util_percent": util,
        "status": "ok" if util is not None else "degraded",
        "error": None if util is not None else "无法从 radeontop 解析利用率",
    }]


class TranscodeSettingsUpdateRequest(BaseModel):
    mode: Optional[str] = None
    selected_profile_id: Optional[str] = None
    selected_hwaccel: Optional[str] = None
    selected_vendor: Optional[str] = None
    output_video_codec: Optional[str] = None
    allow_fallback_to_other_hardware: Optional[bool] = None
    allow_fallback_to_cpu: Optional[bool] = None
    enable_hw_decode: Optional[bool] = None
    hardware_decoding_codecs: Optional[List[str]] = None
    prefer_native_hw_decoder: Optional[bool] = None
    enable_intel_low_power_h264: Optional[bool] = None
    enable_intel_low_power_hevc: Optional[bool] = None
    intel_qsv_frame_interpolation_mode: Optional[str] = None


@router.get("/transcode/settings")
async def get_transcode_settings(current_user: User = Depends(get_current_user)):
    try:
        from routers import file_manager
        settings = await asyncio.to_thread(file_manager.get_transcode_settings, False)
        detected_profiles = await asyncio.to_thread(
            file_manager.get_detected_hardware_acceleration_profiles,
            False
        )
        effective_profiles = await asyncio.to_thread(file_manager.get_hardware_acceleration_profiles)
        last_transcoder = file_manager._get_last_transcoder(include_label=True)
        return {
            "success": True,
            "settings": settings,
            "detected_profiles": detected_profiles,
            "effective_profiles": effective_profiles,
            "last_transcoder": last_transcoder
        }
    except Exception as e:
        logger.error(f"获取转码设置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取转码设置失败: {str(e)}")


@router.put("/transcode/settings")
async def update_transcode_settings(
    payload: TranscodeSettingsUpdateRequest,
    current_user: User = Depends(get_current_user)
):
    try:
        updates = payload.dict(exclude_none=True)
        mode = str(updates.get("mode") or "").strip().lower()
        if mode and mode not in {"auto", "manual", "cpu_only"}:
            raise HTTPException(status_code=400, detail="mode 仅支持 auto/manual/cpu_only")
        interpolation_mode = str(updates.get("intel_qsv_frame_interpolation_mode") or "").strip().lower()
        if interpolation_mode and interpolation_mode not in {"off", "30to60", "60to120"}:
            raise HTTPException(status_code=400, detail="intel_qsv_frame_interpolation_mode 仅支持 off/30to60/60to120")

        from routers import file_manager
        settings = await asyncio.to_thread(file_manager.save_transcode_settings, updates)
        _invalidate_gpu_stats_cache()
        detected_profiles = await asyncio.to_thread(
            file_manager.get_detected_hardware_acceleration_profiles,
            False
        )
        effective_profiles = await asyncio.to_thread(file_manager.get_hardware_acceleration_profiles)
        selected_profile_id = str(settings.get("selected_profile_id") or "").strip()
        selected_profile_exists = (not selected_profile_id) or any(
            p.get("profile_id") == selected_profile_id for p in detected_profiles
        )
        return {
            "success": True,
            "settings": settings,
            "detected_profiles": detected_profiles,
            "effective_profiles": effective_profiles,
            "selected_profile_exists": selected_profile_exists
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存转码设置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存转码设置失败: {str(e)}")


@router.get("/transcode/profiles")
async def get_transcode_profiles(
    force_refresh: bool = False,
    current_user: User = Depends(get_current_user)
):
    try:
        from routers import file_manager
        detected_profiles = await asyncio.to_thread(
            file_manager.get_detected_hardware_acceleration_profiles,
            force_refresh
        )
        effective_profiles = await asyncio.to_thread(file_manager.get_hardware_acceleration_profiles)
        settings = await asyncio.to_thread(file_manager.get_transcode_settings, False)
        last_transcoder = file_manager._get_last_transcoder(include_label=True)
        return {
            "success": True,
            "settings": settings,
            "profiles": detected_profiles,
            "effective_profiles": effective_profiles,
            "last_transcoder": last_transcoder
        }
    except Exception as e:
        logger.error(f"获取转码 profile 失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取转码 profile 失败: {str(e)}")


@router.post("/transcode/reprobe")
async def reprobe_transcode_profiles(current_user: User = Depends(get_current_user)):
    try:
        from routers import file_manager
        effective_profiles = await asyncio.to_thread(file_manager.refresh_hardware_acceleration_profiles)
        _invalidate_gpu_stats_cache()
        detected_profiles = await asyncio.to_thread(
            file_manager.get_detected_hardware_acceleration_profiles,
            False
        )
        settings = await asyncio.to_thread(file_manager.get_transcode_settings, False)
        last_transcoder = file_manager._get_last_transcoder(include_label=True)
        return {
            "success": True,
            "message": "已重新探测转码能力",
            "settings": settings,
            "profiles": detected_profiles,
            "effective_profiles": effective_profiles,
            "last_transcoder": last_transcoder
        }
    except Exception as e:
        logger.error(f"重探测转码 profile 失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重探测转码 profile 失败: {str(e)}")


def _build_gpu_stats_payload_sync() -> Dict:
    """同步构建 GPU 监控数据快照。"""
    try:
        gpus: List[Dict] = []
        gpus.extend(_collect_nvidia_gpu_stats())
        gpus.extend(_collect_intel_gpu_stats())
        gpus.extend(_collect_amd_gpu_stats())
        if not gpus:
            gpus.extend(_collect_dri_gpu_stats())

        # 叠加转码后端可用性：
        # - detected_profiles: 宿主机探测能力
        # - effective_profiles: 设置中心策略生效后的可用能力
        detected_profiles: List[Dict] = []
        effective_profiles: List[Dict] = []
        transcode_settings: Dict = {}
        last_transcoder: Dict = {}
        try:
            from routers import file_manager
            detected_profiles = file_manager.get_detected_hardware_acceleration_profiles() or []
            effective_profiles = file_manager.get_hardware_acceleration_profiles() or []
            transcode_settings = file_manager.get_transcode_settings() or {}
            last_transcoder = file_manager._get_last_transcoder(include_label=True) or {}
        except Exception:
            detected_profiles = []
            effective_profiles = []
            transcode_settings = {}
            last_transcoder = {}

        backend_by_vendor_detected: Dict[str, List[str]] = {}
        for p in detected_profiles:
            vendor = str(p.get("vendor") or "").lower()
            hw = str(p.get("hwaccel") or "").lower()
            if not vendor or not hw:
                continue
            backend_by_vendor_detected.setdefault(vendor, [])
            if hw not in backend_by_vendor_detected[vendor]:
                backend_by_vendor_detected[vendor].append(hw)

        backend_by_vendor_effective: Dict[str, List[str]] = {}
        for p in effective_profiles:
            vendor = str(p.get("vendor") or "").lower()
            hw = str(p.get("hwaccel") or "").lower()
            if not vendor or not hw:
                continue
            backend_by_vendor_effective.setdefault(vendor, [])
            if hw not in backend_by_vendor_effective[vendor]:
                backend_by_vendor_effective[vendor].append(hw)

        # 兼容 qsv/vaapi 共属于 Intel 路径（detected）
        if "intel" not in backend_by_vendor_detected:
            intel_hw = [p.get("hwaccel") for p in detected_profiles if p.get("hwaccel") in {"qsv", "vaapi"}]
            if intel_hw:
                backend_by_vendor_detected["intel"] = sorted(list({str(x) for x in intel_hw}))

        # 兼容 qsv/vaapi 共属于 Intel 路径（effective）
        if "intel" not in backend_by_vendor_effective:
            intel_hw = [p.get("hwaccel") for p in effective_profiles if p.get("hwaccel") in {"qsv", "vaapi"}]
            if intel_hw:
                backend_by_vendor_effective["intel"] = sorted(list({str(x) for x in intel_hw}))

        for gpu in gpus:
            vendor = str(gpu.get("vendor") or "").lower()
            detected_backends = backend_by_vendor_detected.get(vendor, [])
            effective_backends = backend_by_vendor_effective.get(vendor, [])
            # 兼容现有前端字段：transcode_backends 现在表示“生效后端”
            gpu["transcode_backends"] = effective_backends
            gpu["transcode_backends_detected"] = detected_backends
            gpu["transcode_supported"] = len(detected_backends) > 0
            gpu["transcode_enabled"] = len(effective_backends) > 0

        vendors = sorted(list({str(g.get("vendor")) for g in gpus if g.get("vendor")}))
        has_gpu = len(gpus) > 0 and any(g.get("status") != "error" for g in gpus)
        detected_backends_all = sorted(
            list({b for gpu in gpus for b in (gpu.get("transcode_backends_detected") or [])})
        )
        effective_backends_all = sorted(
            list({b for gpu in gpus for b in (gpu.get("transcode_backends") or [])})
        )
        qsv_probe: Optional[Dict[str, Any]] = None
        if "intel" in vendors and "qsv" not in detected_backends_all:
            try:
                qsv_probe = _get_cached_qsv_probe()
            except Exception as e:
                qsv_probe = {
                    "cmd": "",
                    "returncode": 1,
                    "stdout": "",
                    "stderr": f"QSV 探针执行失败: {str(e)}"
                }
        transcode_mode = str(transcode_settings.get("mode") or "auto").lower()
        transcode_enabled = len(effective_backends_all) > 0
        active_hwaccel = str(last_transcoder.get("hardware") or "").strip().lower()
        active_vendor = str(last_transcoder.get("vendor") or "").strip().lower()
        active_profile_id = str(last_transcoder.get("profile_id") or "").strip()
        active_gpu_index_raw = last_transcoder.get("gpu_index")
        active_gpu_index: Optional[int] = None
        try:
            if active_gpu_index_raw is not None and str(active_gpu_index_raw).strip() != "":
                active_gpu_index = int(active_gpu_index_raw)
        except Exception:
            active_gpu_index = None

        if not active_vendor:
            if active_hwaccel == "qsv":
                active_vendor = "intel"
            elif active_hwaccel == "nvenc":
                active_vendor = "nvidia"

        active_profile_usable = False
        if active_hwaccel and active_hwaccel != "cpu":
            for profile in effective_profiles:
                profile_hw = str(profile.get("hwaccel") or "").strip().lower()
                if profile_hw != active_hwaccel:
                    continue
                profile_vendor = str(profile.get("vendor") or "").strip().lower()
                profile_id = str(profile.get("profile_id") or "").strip()
                if active_profile_id and profile_id and profile_id != active_profile_id:
                    continue
                if active_vendor and profile_vendor and profile_vendor != active_vendor:
                    continue
                active_profile_usable = True
                break
            if not active_profile_usable:
                active_hwaccel = ""
                active_vendor = ""
                active_profile_id = ""
                active_gpu_index = None

        for gpu in gpus:
            gpu_vendor = str(gpu.get("vendor") or "").strip().lower()
            is_active = False
            if active_hwaccel and active_hwaccel != "cpu":
                if active_vendor and gpu_vendor == active_vendor:
                    is_active = True
                    if active_vendor == "nvidia" and active_gpu_index is not None:
                        try:
                            is_active = int(str(gpu.get("index")).strip()) == active_gpu_index
                        except Exception:
                            is_active = False
            if is_active:
                gpu_status = str(gpu.get("status") or "").strip().lower()
                gpu_transcode_enabled = bool(gpu.get("transcode_enabled"))
                if gpu_status == "error" or not gpu_transcode_enabled:
                    is_active = False
            gpu["is_active"] = bool(is_active)

        if active_hwaccel and active_hwaccel != "cpu" and not any(bool(g.get("is_active")) for g in gpus):
            if active_vendor:
                for gpu in gpus:
                    if str(gpu.get("vendor") or "").strip().lower() == active_vendor:
                        gpu["is_active"] = True
                        break

        return {
            "timestamp": datetime.now().isoformat(),
            "status": "success",
            "summary": {
                "gpu_count": len(gpus),
                "has_gpu": has_gpu,
                "vendors": vendors,
                "transcode_mode": transcode_mode,
                "transcode_enabled": transcode_enabled,
                "transcode_backends_detected": detected_backends_all,
                "transcode_backends": effective_backends_all,
                "qsv_probe": qsv_probe,
                "active_hwaccel": active_hwaccel or None,
                "active_vendor": active_vendor or None,
                "active_profile_id": active_profile_id or None,
                "active_gpu_index": active_gpu_index,
                "active_transcoder": last_transcoder or {},
            },
            "gpus": gpus,
            "message": "GPU 监控数据获取成功" if gpus else "未检测到可用 GPU 指标源",
        }
    except Exception as e:
        logger.error(f"获取 GPU 监控数据失败: {str(e)}")
        return {
            "timestamp": datetime.now().isoformat(),
            "status": "error",
            "summary": {
                "gpu_count": 0,
                "has_gpu": False,
                "vendors": [],
                "transcode_mode": "auto",
                "transcode_enabled": False,
                "transcode_backends_detected": [],
                "transcode_backends": [],
                "active_hwaccel": None,
                "active_vendor": None,
                "active_profile_id": None,
                "active_gpu_index": None,
                "active_transcoder": {},
            },
            "gpus": [],
            "message": f"获取 GPU 监控数据失败: {str(e)}",
        }


async def _refresh_gpu_stats_cache_once() -> None:
    """刷新 GPU 缓存（由后台任务调用）。"""
    payload = await asyncio.to_thread(_build_gpu_stats_payload_sync)
    async with _gpu_stats_cache_lock:
        _gpu_stats_cache["payload"] = payload
        _gpu_stats_cache["last_update_ts"] = time.time()


async def _update_gpu_stats_task():
    """后台异步任务：固定周期采样 GPU，接口只读缓存。"""
    logger.info("已启动 GPU 后台采样任务（每 %.1f 秒）", _GPU_MONITOR_INTERVAL_SECONDS)
    while True:
        try:
            await _refresh_gpu_stats_cache_once()
        except Exception as e:
            logger.error(f"后台更新 GPU 监控数据失败: {e}")
        await asyncio.sleep(_GPU_MONITOR_INTERVAL_SECONDS)


@router.get("/gpu-stats")
async def get_gpu_stats(force_refresh: bool = False):
    """获取 GPU 监控数据（只读缓存，不在请求路径触发采样）。"""
    if force_refresh:
        # 管理端主动刷新仍保留，但不在普通请求路径触发。
        await _refresh_gpu_stats_cache_once()

    async with _gpu_stats_cache_lock:
        cached_payload = _gpu_stats_cache.get("payload")
        cached_ts = float(_gpu_stats_cache.get("last_update_ts") or 0.0)

    if cached_payload is not None:
        return cached_payload

    return {
        "timestamp": datetime.now().isoformat(),
        "status": "pending",
        "summary": {
            "gpu_count": 0,
            "has_gpu": False,
            "vendors": [],
            "transcode_mode": "auto",
            "transcode_enabled": False,
            "transcode_backends_detected": [],
            "transcode_backends": [],
            "active_hwaccel": None,
            "active_vendor": None,
            "active_profile_id": None,
            "active_gpu_index": None,
            "active_transcoder": {},
            "cache_age_seconds": int(max(0.0, time.time() - cached_ts)) if cached_ts > 0 else None,
        },
        "gpus": [],
        "message": "GPU 监控缓存尚未就绪，请稍后重试",
    }


@router.get("/gpu-debug-report")
async def get_gpu_debug_report(current_user: User = Depends(get_current_user)):
    """获取 GPU 调试报告，用于用户反馈时定位硬件转码与监控问题。"""
    try:
        gpu_stats = await get_gpu_stats()

        transcode_profiles: List[Dict] = []
        effective_profiles: List[Dict] = []
        transcode_settings: Dict = {}
        last_transcoder: Dict = {}
        try:
            from routers import file_manager
            transcode_profiles = file_manager.get_detected_hardware_acceleration_profiles() or []
            effective_profiles = file_manager.get_hardware_acceleration_profiles() or []
            transcode_settings = file_manager.get_transcode_settings() or {}
            last_transcoder = file_manager._get_last_transcoder(include_label=True)
        except Exception as e:
            last_transcoder = {"status": "error", "error": f"读取转码信息失败: {str(e)}"}

        env_keys = [
            "EASY_VDL_ENABLE_HW_DECODE",
            "EASY_VDL_PREFER_NATIVE_HW_DECODER",
            "EASY_VDL_INTEL_LOW_POWER_H264",
            "NVIDIA_VISIBLE_DEVICES",
            "NVIDIA_DRIVER_CAPABILITIES"
        ]
        env_snapshot = {k: os.getenv(k) for k in env_keys if os.getenv(k) is not None}

        probe_commands = {
            "ffmpeg_version": _command_snapshot(["ffmpeg", "-hide_banner", "-version"], timeout=5.0),
            "ffmpeg_hwaccels": _command_snapshot(["ffmpeg", "-hide_banner", "-hwaccels"], timeout=5.0),
            "ffmpeg_encoders": _command_snapshot(["ffmpeg", "-hide_banner", "-encoders"], timeout=5.0),
            "ffmpeg_filters": _command_snapshot(["ffmpeg", "-hide_banner", "-filters"], timeout=5.0),
            "ffmpeg_qsv_probe": _run_qsv_probe_snapshot(),
            "vainfo": _command_snapshot(["vainfo"], timeout=6.0),
            "nvidia_smi": _command_snapshot(["nvidia-smi"], timeout=5.0),
            "lspci": _command_snapshot(["lspci", "-Dnn"], timeout=5.0),
            "ls_dev_dri": _command_snapshot(["ls", "-la", "/dev/dri"], timeout=3.0),
        }

        report = {
            "timestamp": datetime.now().isoformat(),
            "status": "success",
            "user": {
                "id": str(getattr(current_user, "id", "")),
                "username": getattr(current_user, "username", "")
            },
            "host": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "kernel": platform.release(),
                "machine": platform.machine()
            },
            "environment": env_snapshot,
            "gpu_stats": gpu_stats,
            "transcode": {
                "last": last_transcoder,
                "profiles": transcode_profiles,
                "effective_profiles": effective_profiles,
                "settings": transcode_settings
            },
            "probes": probe_commands
        }
        return report
    except Exception as e:
        logger.error(f"获取 GPU 调试报告失败: {str(e)}")
        return {
            "timestamp": datetime.now().isoformat(),
            "status": "error",
            "message": f"获取 GPU 调试报告失败: {str(e)}"
        }


@router.get("/health")
async def health_check():
    """系统健康检查（公开接口，用于登录页状态检测）
    检查核心服务: 主程序(easy-vdl-unified-service) 和 数据库(postgresql)
    策略：
    1. 数据库：优先尝试真实 SQL 连接，成功则视为 RUNNING；失败则参考 supervisor 状态
    2. 主程序：获取 supervisor 状态
    """
    health_status = {
        "status": "ok",
        "services": {},
        "message": "System is running"
    }
    
    # 1. 获取 Supervisor 进程状态
    supervisor_status = {}
    try:
        import subprocess
        target_services = ['easy-vdl-unified-service', 'postgresql']
        
        result = await asyncio.to_thread(
            subprocess.run,
            ['supervisorctl', 'status'] + target_services,
            capture_output=True, 
            text=True, 
            timeout=3
        )
        
        for line in result.stdout.split('\n'):
            line = line.strip()
            if not line: continue
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                state = parts[1]
                supervisor_status[name] = state
                
        # 补全可能未输出的服务
        for svc in target_services:
            if svc not in supervisor_status:
                supervisor_status[svc] = "UNKNOWN"
    except Exception:
        # 如果获取 supervisor 失败，默认 UNKNOWN
        supervisor_status = {s: "UNKNOWN" for s in ['easy-vdl-unified-service', 'postgresql']}

    # 2. 真实数据库连接检查 (覆盖 Supervisor 状态)
    from sql.database_postgresql import get_session
    from sqlalchemy import text
    
    db_connected = False
    try:
        # 使用短超时
        status_db = get_session()
        try:
            # 执行最简单的查询
            status_db.execute(text("SELECT 1"))
            db_connected = True
        finally:
            status_db.close()
    except Exception:
        pass
        
    # 3. 合并状态
    # 填充主程序状态
    health_status["services"]["easy-vdl-unified-service"] = supervisor_status.get("easy-vdl-unified-service", "UNKNOWN")
    
    # 填充数据库状态：如果真的连上了，无视 Supervisor 说什么，直接 RUNNING
    if db_connected:
        health_status["services"]["postgresql"] = "RUNNING"
    else:
        # 连不上，则显示 supervisor 的状态（可能是 STARTING, BACKOFF, FATAL 等）
        health_status["services"]["postgresql"] = supervisor_status.get("postgresql", "error")

    # 4. 判断总体健康度
    all_ok = True
    for name, state in health_status["services"].items():
        if state != "RUNNING":
            all_ok = False
            
    if not all_ok:
        health_status["status"] = "warning"
        health_status["message"] = "部分核心服务未就绪"
        
    return health_status


@router.get("/community-key")
async def get_community_key():
    """获取并验证社区API密钥"""
    import httpx
    
    try:
        key = os.getenv("COMMUNITY_API_KEY")
        if not key:
            return {
                "status": "not_set",
                "key_code": None,
                "is_valid": False,
                "message": "社区密钥未设置"
            }
        
        # 验证密钥是否有效 - 调用社区API的stats端点
        is_valid = False
        error_message = None
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 调用社区stats API验证密钥
                response = await client.get(
                    "https://easy-vdl.921217.xyz/client/stats",
                    headers={"X-API-Key": key}
                )
                
                if response.status_code == 200:
                    is_valid = True
                elif response.status_code == 401 or response.status_code == 403:
                    error_message = "密钥无效或已过期"
                else:
                    error_message = f"验证失败: HTTP {response.status_code}"
        except httpx.TimeoutException:
            error_message = "验证超时,请检查网络连接"
        except Exception as e:
            error_message = f"验证异常: {str(e)}"
            logger.warning(f"社区密钥验证异常: {e}")
        
        # 脱敏处理：只显示前12位
        masked_key = key[:12] + "****" if len(key) > 12 else key
        
        return {
            "status": "success" if is_valid else ("invalid" if error_message else "unknown"),
            "key_code": masked_key,
            "is_valid": is_valid,
            "message": "社区密钥有效" if is_valid else (error_message or "密钥状态未知")
        }
    except Exception as e:
        logger.error(f"获取社区密钥失败: {str(e)}")
        return {
            "status": "error",
            "key_code": None,
            "is_valid": False,
            "message": f"获取失败: {str(e)}"
        }



# ===== 下载核心版本（yt-dlp）缓存 =====
_core_version_cache = {
    "data": None,            # 缓存的数据
    "expires_at": None       # 过期时间（datetime）
}


def _get_current_core_version() -> str:
    """获取当前安装的下载核心（yt-dlp）版本。

    优先尝试 `yt-dlp --version`，失败时回退 `python -m yt_dlp --version`。
    返回值为版本字符串；失败则返回空字符串。
    """
    import subprocess
    commands = [
        ["yt-dlp", "--version"],
        ["python3", "-m", "yt_dlp", "--version"],
        ["python", "-m", "yt_dlp", "--version"],
    ]
    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                version = (result.stdout or result.stderr).strip()
                if version:
                    return version
        except Exception:
            continue
    return ""


def _fetch_latest_core_version() -> tuple[str | None, str]:
    """获取最新的下载核心版本号。

    优先从 PyPI 获取，失败则回退到 GitHub Releases。
    返回 (latest_version, source)；若都失败，返回 (None, "none")。
    """
    import json
    from urllib.request import urlopen, Request
    from urllib.error import URLError, HTTPError

    # 1) PyPI
    try:
        req = Request("https://pypi.org/pypi/yt-dlp/json", headers={"User-Agent": "easy-vdl/1.0"})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            version = data.get("info", {}).get("version")
            if version:
                return version, "pypi"
    except (URLError, HTTPError, TimeoutError, Exception):
        pass

    # 2) GitHub Releases
    try:
        req = Request("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest", headers={"User-Agent": "easy-vdl/1.0"})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            tag = data.get("tag_name") or data.get("name")
            if tag:
                # 常见格式为 "2025.09.15" 或 "v2025.09.15"
                latest = tag.lstrip("vV").strip()
                if latest:
                    return latest, "github"
    except (URLError, HTTPError, TimeoutError, Exception):
        pass

    return None, "none"


def _get_core_version_with_cache() -> dict:
    """带4小时缓存地返回核心版本信息。"""
    now = datetime.utcnow()
    cache = _core_version_cache

    if cache["data"] is not None and cache["expires_at"] is not None and now < cache["expires_at"]:
        payload = dict(cache["data"])  # 复制一份，补充剩余缓存时间
        remaining = int((cache["expires_at"] - now).total_seconds())
        payload["cache_expires_in"] = max(remaining, 0)
        return payload

    current_version = _get_current_core_version()
    latest_version, source = _fetch_latest_core_version()

    # 版本比较：按数字段比较，避免 2025.09.23 与 2025.9.23 误判
    def _parse_version_numbers(v: str) -> list[int]:
        import re
        if not v:
            return []
        try:
            return [int(x) for x in re.findall(r"\d+", v)]
        except Exception:
            return []

    def _is_latest_newer(latest: str, current: str) -> bool:
        la = _parse_version_numbers((latest or "").strip())
        cu = _parse_version_numbers((current or "").strip())
        if not la or not cu:
            # 缺少任一方，保守为无更新
            return False
        # 对齐长度后逐段比较
        max_len = max(len(la), len(cu))
        la += [0] * (max_len - len(la))
        cu += [0] * (max_len - len(cu))
        return la > cu

    has_update = _is_latest_newer(latest_version, current_version) if (current_version and latest_version) else False

    payload = {
        "status": "success" if current_version else "partial",
        "message": "检测成功" if current_version else "仅获取到当前版本",
        "current_version": current_version or None,
        "latest_version": latest_version,
        "has_update": has_update,
        "source": source,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "cache_expires_in": int(timedelta(hours=4).total_seconds())
    }

    _core_version_cache["data"] = payload
    _core_version_cache["expires_at"] = now + timedelta(hours=4)
    return payload


@router.get("/core-version")
async def get_core_version(fast: Optional[bool] = False):
    """获取下载核心版本信息（含最新版本检测与4小时缓存）。

    返回字段：
    - current_version: 当前安装版本
    - latest_version: 最新版本（可能为 null）
    - has_update: 是否有更新
    - checked_at: 检测时间（UTC）
    - cache_expires_in: 缓存剩余秒数
    - source: 最新版本来源（pypi/github/none）
    - status/message: 状态与描述
    """
    try:
        if fast:
            # 快速模式：仅返回本地当前版本，跳过联网查询；后台异步刷新缓存
            current_version = _get_current_core_version()
            # 后台刷新缓存（不影响当前响应速度）
            try:
                asyncio.create_task(asyncio.to_thread(_get_core_version_with_cache))
            except Exception:
                pass
            return {
                "status": "success" if current_version else "partial",
                "message": "快速返回当前版本" if current_version else "未获取到当前版本",
                "current_version": current_version or None,
                "latest_version": None,
                "has_update": False,
                "source": "none",
                "checked_at": datetime.utcnow().isoformat() + "Z",
                "cache_expires_in": 0
            }
        # 非快速模式：完整带缓存逻辑，放入线程池并设置总体超时，避免阻塞事件循环
        try:
            result = await asyncio.wait_for(asyncio.to_thread(_get_core_version_with_cache), timeout=8)
            return result
        except asyncio.TimeoutError:
            # 超时则回退到仅返回当前版本，避免前端卡住
            current_version = _get_current_core_version()
            return {
                "status": "partial",
                "message": "检测超时，已返回当前版本",
                "current_version": current_version or None,
                "latest_version": None,
                "has_update": False,
                "source": "timeout",
                "checked_at": datetime.utcnow().isoformat() + "Z",
                "cache_expires_in": 0
            }
    except Exception as e:
        logger.error(f"获取下载核心版本失败: {str(e)}")
        return {
            "status": "error",
            "message": f"获取下载核心版本失败: {str(e)}",
            "current_version": None,
            "latest_version": None,
            "has_update": False,
            "source": "none",
            "checked_at": datetime.utcnow().isoformat() + "Z",
            "cache_expires_in": 0
        }

async def _update_storage_size_task():
    """后台异步任务：定期使用系统命令获取订阅目录大小（参考直播模式）
    
    每900秒（15分钟）更新一次，最大程度降低对磁盘 I/O 的干扰
    """
    import subprocess
    downloads_path = "/app/downloads"
    subscriptions_path = os.path.join(downloads_path, "subscriptions")
    
    logger.info("已启动订阅目录大小后台监控任务")
    while True:
        try:
            # 1. 获取磁盘使用情况 (shutil.disk_usage 通常很快)
            if os.path.exists(downloads_path):
                total, used, free = shutil.disk_usage(downloads_path)
                DIVISOR = 1000 ** 3
                
                async with _storage_cache_lock:
                    _storage_cache["total_gb"] = round(total / DIVISOR, 2)
                    _storage_cache["used_gb"] = round(used / DIVISOR, 2)
                    _storage_cache["free_gb"] = round(free / DIVISOR, 2)
                    _storage_cache["usage_percentage"] = round((used / total) * 100, 1) if total > 0 else 0

            # 2. 获取订阅目录占用 (du 命令)
            if os.path.exists(subscriptions_path):
                process = await asyncio.create_subprocess_exec(
                    'du', '-sb', subscriptions_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    output = stdout.decode().strip()
                    if output:
                        size_str = output.split()[0]
                        async with _storage_cache_lock:
                            _storage_cache["directory_size_bytes"] = int(size_str)
                            _storage_cache["last_update_ts"] = time.time()
                        logger.debug(f"后台统计更新成功: {size_str} 字节")
            
        except Exception as e:
            logger.error(f"后台更新存储统计出错: {e}")
            
        await asyncio.sleep(900)


async def _update_recent_activity_task():
    """后台异步任务：定期获取最近活动列表（最近6条已完成任务）
    每15秒更新一次，确保仪表盘数据的准实时性，同时避免在推送线程中执行数据库查询
    """
    from sql.database_postgresql import get_db
    from sql.models import Task, Subscription
    import uuid

    logger.info("已启动最近活动后台监控任务")
    while True:
        try:
            # 使用同步的 get_db() 生成器
            db_gen = get_db()
            db_session = next(db_gen)
            try:
                # 在线程池中执行同步查询
                def _fetch():
                    tasks = db_session.query(Task).filter(
                        Task.status == 'COMPLETED'
                    ).order_by(Task.updated_at.desc()).limit(6).all()
                    
                    activity_list = []
                    for task in tasks:
                        try:
                            author_info = None
                            if task.subscription_id:
                                subscription = db_session.query(Subscription).filter(
                                    Subscription.id == task.subscription_id
                                ).first()
                                if subscription:
                                    author_info = {"nickname": subscription.nickname or "未知博主"}
                            
                            activity_list.append({
                                "id": task.id if task.id else str(uuid.uuid4()),
                                "source": task.source if task.source else 'others',
                                "filename": task.filename or task.url or "",
                                "url": task.url or "",
                                "original_url": getattr(task, 'original_url', None),
                                "status": str(task.status),
                                "subscription_id": getattr(task, 'subscription_id', None),
                                "author_info": author_info,
                                "updated_at": task.updated_at.isoformat() if task.updated_at else datetime.now().isoformat()
                            })
                        except Exception:
                            continue
                    return activity_list

                loop = asyncio.get_running_loop()
                results = await loop.run_in_executor(None, _fetch)
                
                if results is not None:
                    global _recent_activity_cache
                    async with _recent_activity_cache_lock:
                        _recent_activity_cache = results
            finally:
                db_session.close()
                
        except Exception as e:
            logger.error(f"后台更新最近活动出错: {e}")
            
        await asyncio.sleep(15)


@router.get("/storage-usage")
async def get_storage_usage():
    """获取存储使用情况（基于 /app/downloads 分区）
    
    优化说明（参考直播模式）：
    1. 后台任务定期计算目录大小（每5分钟），不阻塞API
    2. API直接从内存缓存读取，响应时间 < 1ms
    3. 磁盘使用情况实时获取（很快，不需要缓存）
    """
    try:
        downloads_path = "/app/downloads"

        if not os.path.exists(downloads_path):
            return {
                "total_bytes": 0,
                "used_bytes": 0,
                "free_bytes": 0,
                "usage_percentage": 0,
                "total_gb": 0,
                "used_gb": 0,
                "free_gb": 0,
                "path": downloads_path,
                "status": "error",
                "message": "下载目录不存在"
            }

        # 获取磁盘使用情况（这个很快，实时获取）
        total, used, free = await asyncio.to_thread(shutil.disk_usage, downloads_path)

        # 目录大小直接从内存缓存返回（后台任务定期更新，响应时间 < 1ms）
        async with _storage_cache_lock:
            directory_size = _storage_cache.get("directory_size_bytes", 0)
            last_update_ts = _storage_cache.get("last_update_ts", 0)

        # 适配 NAS 显示习惯：使用 1000 进制 (GB) 而非 1024 进制 (GiB)
        # 1 GB = 1000 * 1000 * 1000 bytes
        DIVISOR = 1000 ** 3
        
        usage_percentage = round((used / total) * 100, 1) if total > 0 else 0
        total_gb = round(total / DIVISOR, 2)
        used_gb = round(used / DIVISOR, 2)
        free_gb = round(free / DIVISOR, 2)
        directory_size_gb = round(directory_size / DIVISOR, 2)

        return {
            "timestamp": datetime.now().isoformat(),
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "directory_size_bytes": directory_size,
            "directory_size_gb": directory_size_gb,
            "usage_percentage": usage_percentage,
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "path": downloads_path,
            "status": "success",
            "message": "存储信息获取成功",
            "info": {
                "last_update_ts": last_update_ts,
                "update_age_seconds": int(time.time() - last_update_ts) if last_update_ts > 0 else None
            }
        }
    except Exception as e:
        logger.error(f"获取存储使用情况失败: {str(e)}")
        return {
            "timestamp": datetime.now().isoformat(),
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "usage_percentage": 0,
            "total_gb": 0,
            "used_gb": 0,
            "free_gb": 0,
            "path": "/app/downloads",
            "message": f"获取存储信息失败: {str(e)}"
        }


# ===== 后台任务启动 =====

@router.on_event("startup")
async def startup_system_monitors():
    """启动系统各项后台监控任务（参考直播模式）"""
    global _storage_calculation_task, _recent_activity_task, _gpu_monitor_task
    try:
        # 1. 存储监控任务
        if _storage_calculation_task is None or _storage_calculation_task.done():
            _storage_calculation_task = asyncio.create_task(_update_storage_size_task())
            logger.info("✅ 订阅目录大小后台监控任务已启动")
            
        # 2. 最近活动监控任务
        if _recent_activity_task is None or _recent_activity_task.done():
            _recent_activity_task = asyncio.create_task(_update_recent_activity_task())
            logger.info("✅ 最近活动后台监控任务已启动")

        # 3. GPU 固定采样任务
        if _gpu_monitor_task is None or _gpu_monitor_task.done():
            _gpu_monitor_task = asyncio.create_task(_update_gpu_stats_task())
            logger.info("✅ GPU 后台采样任务已启动")
    except Exception as e:
        logger.error(f"启动系统后台任务失败: {e}")


@router.on_event("shutdown")
async def shutdown_system_monitors():
    """关闭系统后台监控任务。"""
    global _storage_calculation_task, _recent_activity_task, _gpu_monitor_task
    tasks = [
        ("storage", _storage_calculation_task),
        ("recent_activity", _recent_activity_task),
        ("gpu_monitor", _gpu_monitor_task),
    ]
    for name, task in tasks:
        try:
            if task and not task.done():
                task.cancel()
        except Exception as e:
            logger.debug(f"取消后台任务失败 ({name}): {e}")
    _storage_calculation_task = None
    _recent_activity_task = None
    _gpu_monitor_task = None


# ===== 日志相关接口（需管理员） =====

@router.get("/logs")
async def get_log_files(current_user: User = Depends(get_current_user)):
    """获取日志文件列表"""
    if current_user.is_admin != "true":
        raise HTTPException(status_code=403, detail="❌ 权限不足\n\n需要管理员权限")

    logs_dir = "/app/logs"
    if not os.path.exists(logs_dir):
        raise HTTPException(status_code=404, detail="日志目录不存在")

    log_files = []
    for file_path in glob.glob(os.path.join(logs_dir, "*.log")):
        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            file_mtime = os.path.getmtime(file_path)
            log_files.append({
                "name": file_name,
                "size": file_size,
                "modified": datetime.fromtimestamp(file_mtime).isoformat(),
                "path": file_path
            })
        except Exception:
            continue

    log_files.sort(key=lambda x: x["modified"], reverse=True)
    return {"success": True, "files": log_files}


@router.get("/logs/{log_file}")
async def get_log_content(
    log_file: str,
    lines: Optional[int] = 100,
    current_user: User = Depends(get_current_user)
):
    """获取指定日志文件内容"""
    if current_user.is_admin != "true":
        raise HTTPException(status_code=403, detail="❌ 权限不足\n\n需要管理员权限")

    if ".." in log_file or "/" in log_file or "\\" in log_file:
        raise HTTPException(status_code=400, detail="❌ 无效的日志文件名")

    log_path = os.path.join("/app/logs", log_file)
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail=f"❌ 日志文件不存在: {log_file}")

    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
        content_lines = all_lines[-lines:] if lines and lines > 0 else all_lines
        return {
            "success": True,
            "file": log_file,
            "content": ''.join(content_lines),
            "total_lines": len(all_lines),
            "returned_lines": len(content_lines)
        }
    except Exception as e:
        logger.error(f"读取日志文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"❌ 读取日志文件失败\n\n错误详情：{str(e)}")


@router.delete("/logs/{log_file}")
async def clear_log_file(
    log_file: str,
    current_user: User = Depends(get_current_user)
):
    """清空指定日志文件"""
    if current_user.is_admin != "true":
        raise HTTPException(status_code=403, detail="❌ 权限不足\n\n需要管理员权限")

    if ".." in log_file or "/" in log_file or "\\" in log_file:
        raise HTTPException(status_code=400, detail="❌ 无效的日志文件名")

    log_path = os.path.join("/app/logs", log_file)
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail=f"❌ 日志文件不存在: {log_file}")

    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("")
        logger.info(f"管理员 {current_user.username} 清空了日志文件: {log_file}")
        return {"success": True, "message": f"✅ 日志文件 {log_file} 已清空"}
    except Exception as e:
        logger.error(f"清空日志文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"❌ 清空日志文件失败\n\n错误详情：{str(e)}")


@router.delete("/logs")
async def clear_all_logs(current_user: User = Depends(get_current_user)):
    """清空所有日志文件"""
    if current_user.is_admin != "true":
        raise HTTPException(status_code=403, detail="❌ 权限不足\n\n需要管理员权限")

    logs_dir = "/app/logs"
    if not os.path.exists(logs_dir):
        raise HTTPException(status_code=404, detail="日志目录不存在")

    cleared_files, failed_files = [], []
    for file_path in glob.glob(os.path.join(logs_dir, "*.log")):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("")
            cleared_files.append(os.path.basename(file_path))
        except Exception as e:
            failed_files.append(f"{os.path.basename(file_path)}: {str(e)}")

    logger.info(f"管理员 {current_user.username} 清空了所有日志文件，成功: {len(cleared_files)}, 失败: {len(failed_files)}")
    message = f"✅ 已清空 {len(cleared_files)} 个日志文件"
    if failed_files:
        message += f"\n❌ 清空失败: {', '.join(failed_files)}"
    return {"success": True, "message": message, "cleared_files": cleared_files, "failed_files": failed_files}


@router.post("/logs/export")
async def export_logs(current_user: User = Depends(get_current_user)):
    """导出所有日志文件为ZIP压缩包"""
    if current_user.is_admin != "true":
        raise HTTPException(status_code=403, detail="❌ 权限不足\n\n需要管理员权限")

    logs_dir = "/app/logs"
    if not os.path.exists(logs_dir):
        raise HTTPException(status_code=404, detail="日志目录不存在")

    log_files = glob.glob(os.path.join(logs_dir, "*.log"))
    if not log_files:
        raise HTTPException(status_code=404, detail="没有找到日志文件")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for log_file in log_files:
            file_name = os.path.basename(log_file)
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                zip_file.writestr(file_name, content)
            except Exception as e:
                logger.warning(f"无法读取日志文件 {file_name}: {str(e)}")
                continue

        system_info = f"""系统信息\n导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n导出用户: {current_user.username}\n日志文件数量: {len(log_files)}\n"""
        zip_file.writestr("system_info.txt", system_info)

    zip_buffer.seek(0)
    filename = f"easy-vdl-logs-{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        zip_buffer,  # BytesIO本身可迭代
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(zip_buffer.getbuffer().nbytes)
        }
    )


# ===== 内存监控相关功能 =====

# 内存数据缓存（最近6小时，每15秒采集一次）
_memory_history = deque(maxlen=1440)  # 6小时 * 60分钟 * 60秒 / 15秒 = 1440 条
_memory_collection_task = None


async def _get_memory_snapshot(include_processes: bool = False) -> Dict:
    """获取当前内存快照（包含数据库连接池状态）"""
    try:
        # 读取 memory.current
        with open('/sys/fs/cgroup/memory.current', 'r') as f:
            memory_current = int(f.read().strip())
        
        # 读取 memory.stat
        memory_stats = {}
        memory_limit = 0
        try:
            with open('/sys/fs/cgroup/memory.stat', 'r') as f:
                for line in f:
                    if ' ' in line:
                        key, value = line.strip().split(' ', 1)
                        memory_stats[key] = int(value)
        except Exception:
            pass

        # 读取内存限制 (cgroup v2: memory.max, cgroup v1: memory.limit_in_bytes)
        try:
            if os.path.exists('/sys/fs/cgroup/memory.max'):
                with open('/sys/fs/cgroup/memory.max', 'r') as f:
                    val = f.read().strip()
                    if val != 'max':
                        memory_limit = int(val)
            elif os.path.exists('/sys/fs/cgroup/memory/memory.limit_in_bytes'):
                with open('/sys/fs/cgroup/memory/memory.limit_in_bytes', 'r') as f:
                    memory_limit = int(f.read().strip())
            
            # 如果未设置限制或数值异常大，读取宿主机总内存
            if memory_limit <= 0 or memory_limit > 1024**5:
                try:
                    with open('/proc/meminfo', 'r') as f:
                        for line in f:
                            if line.startswith('MemTotal:'):
                                memory_limit = int(line.split()[1]) * 1024
                                break
                except:
                    pass
        except Exception:
            memory_limit = 0
        
        # 获取数据库连接池状态
        db_pool_usage = 0.0
        db_checked_out = 0
        try:
            from sql.database_postgresql import db
            pool_status = db.get_pool_status()
            db_pool_usage = pool_status["usage_rate"]
            db_checked_out = pool_status["checked_out"]
        except Exception:
            pass  # 静默失败，不影响内存采集
        
        processes = []
        if include_processes:
            # 按需获取进程RSS排行（前30），避免在后台采集中阻塞事件循环
            import asyncio
            try:
                # 使用异步子进程执行 ps 命令，避免阻塞主线程
                process = await asyncio.create_subprocess_exec(
                    'ps', '-eo', 'pid,ppid,rss,pmem,comm,args', '--no-headers', '--sort=-rss',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
                
                if process.returncode == 0:
                    output = stdout.decode().strip()
                    lines = output.split('\n')[:30]
                    for line in lines:
                        parts = line.split(None, 5)
                        if len(parts) >= 6:
                            try:
                                processes.append({
                                    'pid': parts[0],
                                    'ppid': parts[1],
                                    'rss_kb': int(parts[2]),
                                    'rss_mb': round(int(parts[2]) / 1024, 1),
                                    'pmem': parts[3],
                                    'comm': parts[4],
                                    'args': parts[5][:100] + '...' if len(parts[5]) > 100 else parts[5]
                                })
                            except (ValueError, IndexError):
                                continue
            except asyncio.TimeoutError:
                logger.warning("获取进程信息超时")
            except Exception as e:
                logger.warning(f"获取进程信息失败: {str(e)}")
        
        return {
            'memory_current': memory_current,
            'memory_current_mb': round(memory_current / 1024 / 1024, 1),
            'memory_limit': memory_limit,
            'memory_limit_mb': round(memory_limit / 1024 / 1024, 1) if memory_limit > 0 else 0,
            'memory_stats': memory_stats,
            'processes': processes,
            'db_pool_usage': round(db_pool_usage, 1),
            'db_checked_out': db_checked_out,
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取内存快照失败: {str(e)}")
        return {
            'memory_current': 0,
            'memory_current_mb': 0,
            'memory_stats': {},
            'processes': [],
            'db_pool_usage': 0.0,
            'db_checked_out': 0,
            'timestamp': datetime.now().isoformat(),
            'error': str(e)
        }


async def _collect_memory_data():
    """每5秒采集一次内存数据（优化后，提高峰值捕获精度）"""
    logger.info("内存数据采集任务已启动")
    while True:
        try:
            memory_data = await _get_memory_snapshot(False)
            _memory_history.append(memory_data)
            logger.debug(f"内存数据采集完成: {memory_data['memory_current_mb']}MB")
        except Exception as e:
            logger.error(f"内存数据采集失败: {str(e)}")
        
        await asyncio.sleep(5)  # 每5秒采集一次（优化后，可捕获短暂峰值）


def start_memory_collection():
    """启动内存数据采集任务"""
    global _memory_collection_task
    if _memory_collection_task is None or _memory_collection_task.done():
        _memory_collection_task = asyncio.create_task(_collect_memory_data())
        logger.info("内存数据采集任务已启动")


def stop_memory_collection():
    """停止内存数据采集任务"""
    global _memory_collection_task
    if _memory_collection_task and not _memory_collection_task.done():
        _memory_collection_task.cancel()
        logger.info("内存数据采集任务已停止")


@router.get("/memory/current")
async def get_memory_current(current_user: User = Depends(get_current_user)):
    """获取当前内存使用情况"""
    try:
        memory_data = await _get_memory_snapshot(False)
        return {
            "status": "success",
            "data": memory_data,
            "message": "内存信息获取成功"
        }
    except Exception as e:
        logger.error(f"获取当前内存信息失败: {str(e)}")
        return {
            "status": "error",
            "data": None,
            "message": f"获取内存信息失败: {str(e)}"
        }


@router.get("/memory/history")
async def get_memory_history(current_user: User = Depends(get_current_user)):
    """获取内存使用历史数据（最近6小时）"""
    try:
        history_data = list(_memory_history)
        return {
            "status": "success",
            "data": history_data,
            "count": len(history_data),
            "message": f"获取到 {len(history_data)} 条历史数据"
        }
    except Exception as e:
        logger.error(f"获取内存历史数据失败: {str(e)}")
        return {
            "status": "error",
            "data": [],
            "count": 0,
            "message": f"获取历史数据失败: {str(e)}"
        }


@router.get("/memory/processes")
async def get_memory_processes(current_user: User = Depends(get_current_user)):
    """获取进程内存使用排行"""
    try:
        memory_data = await _get_memory_snapshot(True)
        return {
            "status": "success",
            "data": memory_data.get('processes', []),
            "message": "进程内存信息获取成功"
        }
    except Exception as e:
        logger.error(f"获取进程内存信息失败: {str(e)}")
        return {
            "status": "error",
            "data": [],
            "message": f"获取进程信息失败: {str(e)}"
        }


@router.post("/memory/start-collection")
async def start_memory_collection_api(current_user: User = Depends(get_current_user)):
    """启动内存数据采集（管理员权限）"""
    if current_user.is_admin != "true":
        raise HTTPException(status_code=403, detail="❌ 权限不足\n\n需要管理员权限")
    
    try:
        start_memory_collection()
        return {
            "status": "success",
            "message": "内存数据采集已启动"
        }
    except Exception as e:
        logger.error(f"启动内存数据采集失败: {str(e)}")
        return {
            "status": "error",
            "message": f"启动采集失败: {str(e)}"
        }


@router.post("/memory/stop-collection")
async def stop_memory_collection_api(current_user: User = Depends(get_current_user)):
    """停止内存数据采集（管理员权限）"""
    if current_user.is_admin != "true":
        raise HTTPException(status_code=403, detail="❌ 权限不足\n\n需要管理员权限")
    
    try:
        stop_memory_collection()
        return {
            "status": "success",
            "message": "内存数据采集已停止"
        }
    except Exception as e:
        logger.error(f"停止内存数据采集失败: {str(e)}")
        return {
            "status": "error",
            "message": f"停止采集失败: {str(e)}"
        }


@router.get("/database/pool-status")
async def get_database_pool_status(current_user: User = Depends(get_current_user)):
    """获取数据库连接池状态"""
    try:
        from sql.database_postgresql import db
        
        # 使用统一的方法获取连接池状态
        pool_info = db.get_pool_status()
        
        # 获取数据库实际连接数
        
        # 获取数据库实际连接数
        db_info = {
            "total_connections": 0,
            "idle_connections": 0,
            "active_connections": 0
        }
        
        try:
            # 查询PostgreSQL实际连接状态
            from sql.database_postgresql import SessionLocal
            from sqlalchemy import text
            if SessionLocal:
                with SessionLocal() as session:
                    result = session.execute(text(
                        """
                        SELECT 
                            COUNT(*) as total,
                            COUNT(*) FILTER (WHERE state = 'idle') as idle,
                            COUNT(*) FILTER (WHERE state = 'active') as active
                        FROM pg_stat_activity 
                        WHERE datname = 'easy_vdl'
                        """
                    ))
                    row = result.fetchone()
                    if row:
                        db_info["total_connections"] = row[0]
                        db_info["idle_connections"] = row[1]
                        db_info["active_connections"] = row[2]
        except Exception as e:
            logger.warning(f"获取数据库实际连接数失败: {e}")
        
        return {
            "status": "success",
            "data": {
                "pool": pool_info,
                "database": db_info
            }
        }
    except Exception as e:
        logger.error(f"获取数据库连接池状态失败: {str(e)}")
        return {
            "status": "error",
            "message": f"获取连接池状态失败: {str(e)}",
            "data": {
                "pool": {"pool_size": 50, "max_overflow": 50, "checked_out": 0, "checked_in": 0, "overflow": 0},
                "database": {"total_connections": 0, "idle_connections": 0, "active_connections": 0}
            }
        }


@router.post("/memory/gc")
async def trigger_garbage_collection(current_user: User = Depends(get_current_user)):
    """手动触发垃圾回收和内存整理"""
    try:
        import gc
        import ctypes
        
        # 记录GC前的内存使用
        memory_before = 0
        try:
            with open('/sys/fs/cgroup/memory.current', 'r') as f:
                memory_before = int(f.read().strip()) / 1024 / 1024
        except:
            try:
                with open('/sys/fs/cgroup/memory/memory.usage_in_bytes', 'r') as f:
                    memory_before = int(f.read().strip()) / 1024 / 1024
            except:
                pass
        
        # 执行Python垃圾回收
        collected_objects = gc.collect()
        
        # 执行malloc_trim释放glibc缓存的内存
        malloc_trim_success = False
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
            malloc_trim_success = True
        except Exception as e:
            logger.warning(f"malloc_trim执行失败: {e}")
        
        # 记录GC后的内存使用
        memory_after = 0
        try:
            with open('/sys/fs/cgroup/memory.current', 'r') as f:
                memory_after = int(f.read().strip()) / 1024 / 1024
        except:
            try:
                with open('/sys/fs/cgroup/memory/memory.usage_in_bytes', 'r') as f:
                    memory_after = int(f.read().strip()) / 1024 / 1024
            except:
                pass
        
        memory_freed = memory_before - memory_after if memory_before > 0 and memory_after > 0 else 0
        
        logger.info(f"手动GC完成: 回收对象数={collected_objects}, malloc_trim={'成功' if malloc_trim_success else '失败'}, 释放内存={memory_freed:.1f}MB")
        
        return {
            "status": "success",
            "message": "垃圾回收完成",
            "data": {
                "collected_objects": collected_objects,
                "malloc_trim_executed": malloc_trim_success,
                "memory_before_mb": round(memory_before, 1) if memory_before > 0 else None,
                "memory_after_mb": round(memory_after, 1) if memory_after > 0 else None,
                "memory_freed_mb": round(memory_freed, 1) if memory_freed > 0 else 0
            }
        }
    except Exception as e:
        logger.error(f"执行垃圾回收失败: {str(e)}")
        return {
            "status": "error",
            "message": f"执行垃圾回收失败: {str(e)}"
        }



@router.get("/supervisor/status")
async def get_supervisor_status(current_user: User = Depends(get_current_user)):
    """获取Supervisord管理的所有进程状态"""
    if current_user.is_admin != "true":
        raise HTTPException(status_code=403, detail="❌ 权限不足\n\n需要管理员权限")
    
    try:
        import subprocess
        # 调用 supervisorctl status 命令
        result = await asyncio.to_thread(
            subprocess.run,
            ['supervisorctl', 'status'],
            capture_output=True, 
            text=True, 
            timeout=5
        )
        
        output = result.stdout
        services = []
        
        # 解析输出
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            parts = line.split()
            if len(parts) < 2:
                continue
                
            name = parts[0]
            state = parts[1]
            extra_info = ' '.join(parts[2:])
            
            # 尝试提取PID
            pid = None
            if state == 'RUNNING' and 'pid' in extra_info:
                try:
                    pid_part = extra_info.split(',')[0] # "pid 123"
                    if 'pid' in pid_part:
                        pid = int(pid_part.strip().split()[1])
                except:
                    pass
            
            services.append({
                "name": name,
                "state": state,
                "pid": pid,
                "info": extra_info
            })
            
        return {
            "status": "success",
            "data": services
        }
            
    except Exception as e:
        logger.error(f"获取Supervisord状态失败: {str(e)}")
        return {
            "status": "error",
            "message": f"获取状态失败: {str(e)}",
            "data": []
        }


@router.get("/network/check")
async def check_network_connectivity(current_user: User = Depends(get_current_user)):
    """检测网络连通性（YouTube和Bilibili）
    
    优化说明：
    1. 增加单个站点检测超时时间（5秒 -> 10秒）
    2. 添加整体API超时保护（15秒）
    3. 优化错误处理，避免403等状态码导致API失败
    """
    import httpx
    import time
    
    async def check_site(url: str, timeout: float = 10.0) -> dict:
        """检测单个站点的连通性（增加超时时间到10秒）"""
        try:
            start_time = time.time()
            # 使用更长的超时时间，并设置连接和读取超时
            timeout_config = httpx.Timeout(timeout, connect=5.0, read=timeout)
            async with httpx.AsyncClient(timeout=timeout_config, follow_redirects=True) as client:
                response = await client.get(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                latency_ms = int((time.time() - start_time) * 1000)
                
                # 即使返回403/429等状态码，也认为网络是通的（只是被限制）
                if response.status_code < 500:  # 4xx错误也认为网络是通的
                    return {
                        "status": "ok" if response.status_code < 400 else "limited",
                        "latency_ms": latency_ms,
                        "status_code": response.status_code,
                        "message": f"HTTP {response.status_code}" if response.status_code >= 400 else None
                    }
                else:
                    return {
                        "status": "error",
                        "latency_ms": latency_ms,
                        "status_code": response.status_code,
                        "message": f"HTTP {response.status_code}"
                    }
        except httpx.TimeoutException:
            return {
                "status": "timeout",
                "latency_ms": int(timeout * 1000),
                "message": "连接超时"
            }
        except httpx.ConnectError:
            return {
                "status": "failed",
                "latency_ms": 0,
                "message": "连接失败"
            }
        except Exception as e:
            return {
                "status": "failed",
                "latency_ms": 0,
                "message": str(e)[:100]  # 限制错误消息长度
            }
    
    try:
        # 并发检测两个站点，整体超时15秒
        youtube_task = check_site("https://www.youtube.com")
        bilibili_task = check_site("https://www.bilibili.com")
        
        youtube_result, bilibili_result = await asyncio.wait_for(
            asyncio.gather(
            youtube_task, bilibili_task, return_exceptions=True
            ),
            timeout=15.0
        )
        
        # 处理异常情况
        if isinstance(youtube_result, Exception):
            youtube_result = {"status": "failed", "latency_ms": 0, "message": str(youtube_result)[:100]}
        if isinstance(bilibili_result, Exception):
            bilibili_result = {"status": "failed", "latency_ms": 0, "message": str(bilibili_result)[:100]}
        
        return {
            "status": "success",
            "data": {
                "youtube": youtube_result,
                "bilibili": bilibili_result
            },
            "checked_at": datetime.now().isoformat()
        }
    except asyncio.TimeoutError:
        logger.warning(f"网络检测整体超时（15秒）")
        return {
            "status": "timeout",
            "message": "网络检测超时",
            "data": {
                "youtube": {"status": "timeout", "latency_ms": 0, "message": "检测超时"},
                "bilibili": {"status": "timeout", "latency_ms": 0, "message": "检测超时"}
            }
        }
    except Exception as e:
        logger.error(f"网络检测失败: {str(e)}")
        return {
            "status": "error",
            "message": f"检测失败: {str(e)[:100]}",
            "data": {
                "youtube": {"status": "failed", "latency_ms": 0, "message": "检测异常"},
                "bilibili": {"status": "failed", "latency_ms": 0, "message": "检测异常"}
            }
        }
# ===== 动态日志控制 =====

class LogLevelRequest(BaseModel):
    level: str  # DEBUG, INFO, WARNING, ERROR

@router.get("/log-level")
async def get_log_level(
    current_user: User = Depends(get_current_user)
):
    """获取当前运行时日志等级（内存态）。"""
    try:
        root_logger = logging.getLogger()
        effective_level = root_logger.getEffectiveLevel()
        level_name = logging.getLevelName(effective_level)
        if not isinstance(level_name, str):
            level_name = "INFO"

        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level_name not in valid_levels:
            level_name = "INFO"

        return {
            "success": True,
            "level": level_name
        }
    except Exception as e:
        logger.error(f"获取日志等级失败: {e}")
        return {
            "success": True,
            "level": "INFO"
        }

@router.post("/log-level")
async def set_log_level(
    request: LogLevelRequest,
    current_user: User = Depends(get_current_user)
):
    """
    动态设置系统运行时的日志等级 (In-Memory)
    
    注意：
    1. 仅在内存中生效，重启服务后失效（恢复配置文件默认值）。
    2. 仅管理员可用。
    3. 用于临时调试和问题排查。
    """
    if current_user.is_admin != "true":
        raise HTTPException(status_code=403, detail="❌ 权限不足\n\n需要管理员权限")

    level_name = request.level.upper()
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    
    if level_name not in valid_levels:
        raise HTTPException(status_code=400, detail=f"无效的日志等级，可选值: {', '.join(valid_levels)}")

    try:
        new_level = getattr(logging, level_name)
        
        # 定义嘈杂的第三方库（在 DEBUG 模式下需要强制压制）
        NOISY_LIBRARIES = [
            "uvicorn", "uvicorn.access", "uvicorn.error",
            "httpx", "httpcore", "hpack", "h2",
            "sqlalchemy", "sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.dialects", "sqlalchemy.orm",
            "aiohttp", "asyncio", "urllib3", "requests", "multipart", 
            "watchfiles", "fsevents", "websockets"
        ]
        
        # 1. 设置 Root Logger
        root_logger = logging.getLogger()
        root_logger.setLevel(new_level)
        
        # 2. 遍历所有已加载的 Logger 并精细化更新
        updated_loggers = []
        for name in logging.root.manager.loggerDict:
            try:
                logger_obj = logging.getLogger(name)
                
                # 判断是否是 noisy 库
                is_noisy = any(name == lib or name.startswith(lib + ".") for lib in NOISY_LIBRARIES)
                
                if is_noisy:
                    # 对于嘈杂的第三方库，至少保持 WARNING 级别
                    # 即：如果用户设为 DEBUG/INFO，这些库强制为 WARNING
                    # 如果用户设为 ERROR，则这些库也为 ERROR
                    if new_level < logging.WARNING:
                        logger_obj.setLevel(logging.WARNING)
                    else:
                        logger_obj.setLevel(new_level)
                else:
                    # 其他业务库 -> 完全跟随系统设置
                    logger_obj.setLevel(new_level)
                
                updated_loggers.append(name)
                
                # 同时更新 Handlers
                for handler in logger_obj.handlers:
                    handler.setLevel(new_level)
            except Exception:
                pass
                
        # 3. 强制更新 Root Logger 的 Handlers (Console, File)
        for handler in root_logger.handlers:
            handler.setLevel(new_level)

        logger.critical(f"🔔 系统日志等级已被管理员 {current_user.username} 动态修改为: {level_name}")
        
        return {
            "success": True,
            "message": f"日志等级已临时修改为 {level_name}",
            "affected_loggers": len(updated_loggers),
            "note": "重启后将恢复默认配置"
        }

    except Exception as e:
        logger.error(f"修改日志等级失败: {e}")
        raise HTTPException(status_code=500, detail=f"修改失败: {str(e)}")


@router.get("/avatar-proxy")
async def avatar_proxy(url: str = Query(..., description="图片URL")):
    """代理头像图片（解决Instagram等CDN跨域拦截问题）"""
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="无效的图片URL")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                }
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"获取图片失败，上游返回 {resp.status_code}")

            content_type = resp.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                content_type = "image/jpeg"

            return StreamingResponse(
                io.BytesIO(resp.content),
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Content-Disposition": "inline",
                }
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="获取图片超时")
    except httpx.RequestError as e:
        logger.error(f"头像代理请求失败: {url[:80]}... error={e}")
        raise HTTPException(status_code=502, detail=f"请求图片失败: {str(e)[:100]}")
