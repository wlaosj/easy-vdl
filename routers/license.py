import os
import logging
import time
import asyncio
import aiohttp
import socket
import base64
import hashlib
import hmac
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from functools import wraps
from enum import Enum
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

# 配置日志
logger = logging.getLogger(__name__)

# 导入认证
from routers.auth import get_current_user
from sql.models import User

# 导入反调试检测
from routers.anti_debug import get_anti_debugger

# ==================== RSA公钥（用于验证服务端签名） ====================
# 此公钥与服务端私钥配对，用于验证授权响应的真实性
# 即使被提取，也无法伪造签名（只有服务端私钥才能签名）
_LICENSE_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAlFiLixXrW9hQf2jZXXnN
x9qw8WZ3SAoPNQxfa/aKtkKeO0LhFOBaPXpaEW+PujfNffVRdIh9gLhWb2YcfVX0
9WLg1gHPZOVIe4U0V/Ush4GwgGsipcJ8kR+Cj6x0sEQ/19cjSfL55e6rkad2S6sy
iA1m+s4iQZ1WpCqKrzCXcP+hOfvVUTkr4qQcujgGk5sRLLchaLnm83l2VgZwPm+U
sz8w1jtB8XibfMuA/hNN4LtE5RxKJ/TbtwHRIGzj9rspXY0DkSTT3JEg4e4YtFyr
7gwOgrbvTDL82RIolMhY/CJ+eFUPzlyyMhkcblrRZg5PjZTkr0aDvzPpZnS6OPhe
xQIDAQAB
-----END PUBLIC KEY-----"""

_LICENSE_PUBLIC_KEY = None

def _get_public_key():
    """获取RSA公钥（懒加载）"""
    global _LICENSE_PUBLIC_KEY
    if _LICENSE_PUBLIC_KEY is None:
        try:
            _LICENSE_PUBLIC_KEY = serialization.load_pem_public_key(
                _LICENSE_PUBLIC_KEY_PEM.encode(),
                backend=default_backend()
            )
        except Exception as e:
            logger.error(f"RSA公钥加载失败: {e}")
    return _LICENSE_PUBLIC_KEY

def verify_license_signature(valid: bool, days_remaining: int, timestamp: int, signature: str) -> bool:
    """验证授权响应的RSA签名（强制验证，不允许跳过）"""
    if not signature:
        # 签名为空 = 伪造的服务器（正版服务器必须返回签名）
        logger.warning("授权响应缺少签名，拒绝接受（可能是伪造服务器）")
        return False
    
    # 检查时间戳有效期（5分钟内），防止重放攻击
    if abs(time.time() - timestamp) > 300:
        logger.warning("授权响应时间戳过期（可能是重放攻击）")
        return False
    
    public_key = _get_public_key()
    if not public_key:
        logger.error("RSA公钥加载失败，无法验证签名")
        return False  # 公钥加载失败也拒绝
    
    # 构造待验证数据（必须与服务端签名时一致）
    data = f"{valid}|{days_remaining}|{timestamp}"
    try:
        signature_bytes = base64.b64decode(signature)
        public_key.verify(
            signature_bytes,
            data.encode(),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return True
    except Exception as e:
        logger.warning(f"签名验证失败（可能是伪造服务器）: {e}")
        return False

# 创建路由实例
router = APIRouter(prefix="/api/license", tags=["license"])

class LicenseStatus(str, Enum):
    """授权状态枚举"""
    VALID = "valid"      # 授权有效
    INVALID = "invalid"  # 授权无效
    EXPIRED = "expired"  # 授权已过期（终态，不再验证）

class LicenseManager:
    """高级版授权管理器"""
    def __init__(self):
        self.status = LicenseStatus.INVALID    # 当前状态
        self.permanently_expired = False          # 是否永久过期（服务端确认）
        self.license_key = None                # 授权密钥
        # 请求路径可用性窗口：最近一次成功后，12小时内 verify() 可直接放行（不请求远端）
        self.cache_duration = 43200
        # 后台主动复验节奏：每4小时触发一次远端校验（与请求路径缓存放行并行）
        self.verify_interval = 14400
        self.max_retries = 3                  # 最大重试次数
        self.retry_delay = 5                  # 重试间隔（秒）
        self.request_timeout = 10             # 请求超时时间（秒）
        self.last_success_time = 0             # 最后一次成功时间
        self.last_verify_time = 0              # 最后一次验证时间
        self.last_error = None                 # 最后一次错误信息
        self.remaining_days = 0                # 剩余天数
        self.kicked_off = False                # 是否被挤下线状态锁（防踩踏）
        self._background_task = None           # 后台定期验证任务
        self.verify_url = os.getenv(
            "SNIFFER_VERIFY_URL",
            "https://easy-vdl.921217.xyz/public/sniffer/verify-key",
        )
        self._verify_lock = asyncio.Lock()     # 验证锁，防止并发验证
        self._warned_missing_key = False       # 缺少密钥提示仅打印一次
        self._gate_log_last_at = {}            # 门禁拒绝日志节流
        # 反调试节流：避免高频 verify() 每次都执行重检测
        self.anti_debug_check_interval = max(
            1,
            int(os.getenv("SNIFFER_ANTI_DEBUG_CHECK_INTERVAL_SECONDS", "60"))
        )
        self._last_anti_debug_check_time = 0.0
        self._anti_debug_lock = asyncio.Lock()
        # IP 缓存
        self._cached_ip: Optional[str] = None
        self._cached_ip_at: float = 0.0
        self._ip_ttl_seconds: int = 3600

    @property
    def is_lifetime(self) -> bool:
        """判断是否为永久/终身授权 (基于剩余天数判断，-1 或大于 3650 天即视为永久)"""
        return self.status == LicenseStatus.VALID and (self.remaining_days == -1 or self.remaining_days > 3650)

    def clear_cache(self):
        """清除授权缓存，强制下次验证发起网络请求"""
        self.last_success_time = 0
        self.last_verify_time = 0
        # 强制刷新时，必须重置终态标记，否则 verify() 会直接拦截不发请求
        # 这允许被封禁/过期的客户端在管理员干预后（如解封）能自动恢复
        self.permanently_expired = False
        self.kicked_off = False                # 清除被挤下线状态锁
        
        if self.status == LicenseStatus.VALID:
             self.status = LicenseStatus.INVALID

    def _log_missing_key_once(self):
        """当缺少密钥时，输出一次性指引日志，帮助用户快速修复"""
        if self._warned_missing_key:
            return
        self._warned_missing_key = True
        logger.error("未检测到授权密钥: 环境变量 SNIFFER_LICENSE_KEY 未设置或为空")
        logger.warning("请设置环境变量 SNIFFER_LICENSE_KEY 后重启应用")

    def _log_verify_result(self, *, error_code: Optional[str], status: LicenseStatus, terminal: bool, message: str):
        """统一授权验证日志格式，便于 grep 与排障。"""
        log_msg = (
            "授权验证结果: "
            f"terminal={str(terminal).lower()} "
            f"error_code={error_code or '-'} "
            f"status={status} "
            f"message={message}"
        )
        if terminal:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    async def _maybe_run_anti_debug_check(self):
        """按时间窗口执行反调试检测，避免每次 verify() 都进行重检测。"""
        now = time.time()
        # 快路径：多数请求无需进入锁
        if now - self._last_anti_debug_check_time < self.anti_debug_check_interval:
            return

        async with self._anti_debug_lock:
            now = time.time()
            if now - self._last_anti_debug_check_time < self.anti_debug_check_interval:
                return

            # 真正执行检测（严格模式：命中时由 protect() 直接退出）
            anti_debugger = get_anti_debugger(strict_mode=True)
            anti_debugger.protect()
            self._last_anti_debug_check_time = now

    def get_real_container_id(self) -> str:
        """获取真实的容器ID（无法被用户修改）"""
        try:
            # 方法1: 从cgroup获取（推荐）
            try:
                with open("/proc/self/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            parts = line.strip().split("/")
                            for part in parts:
                                # 查找64位的完整容器ID
                                if len(part) == 64:
                                    container_id = part[:12]
                                    return container_id
                                # 或者直接查找12位ID
                                elif len(part) == 12 and all(c in '0123456789abcdef' for c in part):
                                    return part
            except Exception as e:
                pass
            
            # 方法2: 从mountinfo获取
            try:
                with open("/proc/self/mountinfo", "r") as f:
                    for line in f:
                        if "docker" in line:
                            parts = line.split()
                            for part in parts:
                                if "docker" in part and len(part) == 64:
                                    return part[:12]
            except Exception as e:
                pass
            
            # 如果都获取不到，使用HOSTNAME作为备选
            return os.getenv("HOSTNAME", "unknown")
            
        except Exception as e:
            return "unknown"

    async def _get_public_ip_http(self) -> Optional[str]:
        """通过外网服务获取出口公网IP（优先）"""
        try:
            timeout = aiohttp.ClientTimeout(total=3)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 首选 api.ipify.org
                try:
                    async with session.get("https://api.ipify.org?format=json") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            ip = data.get("ip")
                            if isinstance(ip, str) and ip:
                                return ip
                except Exception:
                    pass
                # 备选 ifconfig.me
                try:
                    async with session.get("https://ifconfig.me/ip") as resp:
                        if resp.status == 200:
                            text = (await resp.text()).strip()
                            if text:
                                return text
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def _get_local_ip(self) -> Optional[str]:
        """通过本地路由探测获取容器/主机的局域网IP（次选）"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            sock.close()
            return ip
        except Exception:
            return None

    async def get_host_ip(self) -> str:
        """获取客户端IP（带缓存）：优先公网IP，失败则返回局域网IP，最终返回空字符串"""
        now = time.time()
        if self._cached_ip and (now - self._cached_ip_at) < self._ip_ttl_seconds:
            return self._cached_ip
        # 1) 公网IP
        ip = await self._get_public_ip_http()
        source = "public_http" if ip else None
        # 2) 局域网IP
        if not ip:
            ip = self._get_local_ip()
            source = "local_route" if ip else None
        # 3) 兜底
        if not ip:
            ip = ""
            source = source or "none"
        self._cached_ip, self._cached_ip_at = ip, now
        return ip

    async def initialize(self) -> bool:
        """初始化授权管理器"""
        try:
            # 从环境变量获取密钥
            self.license_key = os.getenv("SNIFFER_LICENSE_KEY")
            if not self.license_key:
                self._log_missing_key_once()
                # 缺少密钥时不再触发远端验证，直接标记无效并设置下一次验证时间，避免频繁打点
                self.status = LicenseStatus.INVALID
                self.last_error = "缺少授权密钥(SNIFFER_LICENSE_KEY)"
                self.last_verify_time = time.time()
                return False

            logger.info("高级版授权初始化...")

            # 启动阶段：仅在初始化时进行有限重试（默认3次）
            success = await self._do_verify_with_retry()
            if success:
                logger.info("高级版授权验证成功")
            else:
                logger.error("高级版授权验证失败")

            # 初始化后即启动后台周期验证，保持验证节奏稳定
            self._start_background_verify()
            return success

        except Exception as e:
            logger.error(f"授权管理器初始化失败: {str(e)}")
            return False
    def _md5_hash(self, text: str) -> str:
        """MD5哈希辅助函数"""
        if not text:
            return ""
        return hashlib.md5(text.encode()).hexdigest()

    def _build_verify_request_canonical(self, key_hash: str, container_id: str, ts: int, nonce: str) -> str:
        """构造 v2 请求签名的规范字符串。"""
        return f"POST\n/public/sniffer/verify-key\n{key_hash}\n{container_id or ''}\n{ts}\n{nonce}"

    def _generate_verify_nonce(self) -> str:
        """生成一次性随机 nonce。"""
        return base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")

    def _sign_verify_request_v2(self, key_hash: str, container_id: str, ts: int, nonce: str) -> str:
        """使用密钥明文作为 HMAC secret 生成请求签名。"""
        canonical = self._build_verify_request_canonical(key_hash, container_id, ts, nonce)
        secret = (self.license_key or "").strip().encode("utf-8")
        digest = hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def _start_background_verify(self):
        """启动后台定期验证任务"""
        if self._background_task is None or self._background_task.done():
            self._background_task = asyncio.create_task(self._background_verify_loop())

    async def _background_verify_loop(self):
        """后台定期验证循环（每 verify_interval 主动复验一次）"""
        while True:
            try:
                await asyncio.sleep(self.verify_interval)
                # 后台复验：用于尽早发现授权状态变化，不直接改变请求路径的12小时缓存放行规则
                success = await self._do_verify_with_retry()  # 使用带重试的验证
                if success:
                    self.status = LicenseStatus.VALID
                    self.last_success_time = time.time()
                    self.last_verify_time = time.time()
                else:
                    if time.time() - self.last_success_time >= self.cache_duration:
                        self.status = LicenseStatus.INVALID
            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(5)  # 出错后等待5秒再继续

    async def verify(self) -> bool:
        """验证授权状态"""
        # 🔒 反调试检测（节流执行）：防止高频路径重复重检测
        try:
            await self._maybe_run_anti_debug_check()
        except Exception as e:
            logger.error(f"反调试检测失败: {e}")
        
        # 如果已被服务端确认过期，直接返回失败（终态，需重启服务）
        if self.permanently_expired:
            return False
            
        # 被挤下线锁：如果处于被挤下线状态，直接拦截自动验证的网络请求，防止踩踏套娃
        if getattr(self, "kicked_off", False):
            self.status = LicenseStatus.INVALID
            self.last_error = "授权名额已满，您的设备已被新激活的容器挤下线"
            return False
        
        now = time.time()
        # 确保每个进程都能读取到环境变量中的密钥（避免只在单例初始化的进程中加载）
        if not self.license_key:
            try:
                self.license_key = os.getenv("SNIFFER_LICENSE_KEY")
            except Exception:
                self.license_key = None
        # 本地前置校验：无密钥直接判定无效，且避免频繁重试
        if not self.license_key or not isinstance(self.license_key, str) or not self.license_key.strip():
            self.status = LicenseStatus.INVALID
            self.last_error = "缺少授权密钥(SNIFFER_LICENSE_KEY)"
            self._log_missing_key_once()
            # 间隔窗口内不重复验证，降低打点
            if now - self.last_verify_time < self.verify_interval:
                return False
            self.last_verify_time = now
            return False
        
        # 1. 请求路径放行窗口：
        # 最近一次成功在 cache_duration（默认12小时）内时，直接返回成功，不发远端请求。
        # 这是一种“可用性优先”的设计，避免授权服务短时波动影响业务。
        if now - self.last_success_time < self.cache_duration:
            return True
            
        # 2. 检查是否需要远端验证（仅在未命中12小时放行窗口时生效）
        # 策略分级：
        # - Valid (有效): 4小时节流一次（verify_interval）
        # - Invalid (临时失败): 5分钟节流一次（300s）以便快速自愈
        # - Fatal/终态: 直接拒绝或停止重试（见 permanently_expired）
        
        retry_interval = 300  # 临时失败重试间隔 (5分钟)
        
        # 决定当前使用的“远端请求节流窗口”（不是功能可用窗口）
        if self.status == LicenseStatus.VALID:
            current_interval = self.verify_interval
        elif self.permanently_expired: 
            return False # 终态直接拒绝
        else:
            # 非有效且非终态：按短窗口重试（默认5分钟），用于网络抖动后的快速恢复
            current_interval = retry_interval

        if now - self.last_verify_time < current_interval:
            # 如果上次验证失败，直接返回失败状态
            if self.status != LicenseStatus.VALID:
                return False
            return True
            
        # 3. 执行验证
        async with self._verify_lock:  # 使用锁防止并发验证
            return await self._do_verify()

    def _log_gate_denied(self, feature: str, reason: str, require_lifetime: bool):
        """记录授权门禁拒绝原因，按 feature/reason 节流避免后台任务刷屏。"""
        now = time.time()
        
        # 优化：折叠高频多实例子任务的 UUID，在授权失效时避免刷爆日志（折叠为大类全局 10 分钟限流）
        if "live.scheduler.monitor" in feature:
            log_key = f"live.scheduler.monitor.all|{reason}|{require_lifetime}"
            throttle_time = 600
        elif "subscribe" in feature or "scheduler" in feature:
            log_key = f"routers.subscribe.all|{reason}|{require_lifetime}"
            throttle_time = 600
        else:
            log_key = f"{feature}|{reason}|{require_lifetime}"
            throttle_time = 60
            
        if now - self._gate_log_last_at.get(log_key, 0) < throttle_time:
            return
        self._gate_log_last_at[log_key] = now
        logger.warning(
            "授权门禁拒绝: feature=%s reason=%s require_lifetime=%s status=%s permanently_expired=%s remaining_days=%s",
            feature,
            reason,
            str(require_lifetime).lower(),
            self.status,
            str(self.permanently_expired).lower(),
            self.remaining_days,
        )

    async def is_active_for(self, feature: str, require_lifetime: bool = False) -> bool:
        """非 HTTP 场景授权门禁：失败返回 False 并记录日志。"""
        feature = (feature or "unknown").strip() or "unknown"
        try:
            verified = await self.verify()
        except Exception as e:
            self.last_error = str(e)
            self._log_gate_denied(feature, f"verify_exception:{type(e).__name__}", require_lifetime)
            return False

        if not verified:
            self._log_gate_denied(feature, "verify_failed", require_lifetime)
            return False
        if self.status != LicenseStatus.VALID:
            self._log_gate_denied(feature, f"status_{self.status}", require_lifetime)
            return False
        if self.permanently_expired:
            self._log_gate_denied(feature, "permanently_expired", require_lifetime)
            return False
        if require_lifetime and not self.is_lifetime:
            self._log_gate_denied(feature, "lifetime_required", require_lifetime)
            return False

        return True

    async def ensure_active_or_403(self, feature: str, require_lifetime: bool = False):
        """HTTP API 授权门禁：失败抛出 403。"""
        if await self.is_active_for(feature=feature, require_lifetime=require_lifetime):
            return True

        detail = (
            "高光切片当前仅对永久高级版用户开放"
            if require_lifetime
            else "服务未授权或授权已过期，请联系管理员"
        )
        raise HTTPException(status_code=403, detail=detail)

    async def _do_verify(self) -> bool:
        """执行验证请求"""
        self.last_verify_time = time.time()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        
        # 前置校验：密钥为空时直接返回，避免发送无效请求导致 422 错误
        if not self.license_key or not isinstance(self.license_key, str) or not self.license_key.strip():
            self.status = LicenseStatus.INVALID
            self.last_error = "缺少授权密钥(SNIFFER_LICENSE_KEY)"
            self._log_missing_key_once()
            # 缺少密钥是配置错误，视为半永久错误，不自动重试直到重启或环境变量变更
            # 但为了简单，这里不设 permanently_expired，依靠 verify_interval 控制
            return False
        
        # 额外检查：防止用户误用示例文本作为密钥
        invalid_patterns = ["高级功能", "可选", "your_key", "example", "密钥"]
        key_lower = self.license_key.lower()
        for pattern in invalid_patterns:
            if pattern.lower() in key_lower:
                self.status = LicenseStatus.INVALID
                self.permanently_expired = True # 格式明显不对，永久放弃
                self.last_error = f"检测到无效密钥格式（包含'{pattern}'），请使用正确的授权密钥"
                logger.warning(f"检测到无效密钥格式: {self.license_key[:10]}...")
                return False
        
        try:
            # 获取真实的容器ID
            container_id = self.get_real_container_id()
            # 获取客户端IP（带缓存）
            host_ip = await self.get_host_ip()
            key_hash = self._md5_hash(self.license_key.strip())
            req_ts = int(time.time())
            req_nonce = self._generate_verify_nonce()
            req_sig = self._sign_verify_request_v2(key_hash, container_id, req_ts, req_nonce)
            
            verify_data = {
                # 公网安全增强：发送哈希后的身份指纹，避免泄露原始密钥
                "key_code": key_hash,
                "host_ip": host_ip,
                "container_id": container_id,
                "sig_ver": 2,
                "ts": req_ts,
                "nonce": req_nonce,
                "sig": req_sig,
            }
            headers = {"Content-Type": "application/json"}

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.verify_url, json=verify_data, headers=headers) as resp:
                    # 尝试解析响应 JSON
                    result = {}
                    try:
                        result = await resp.json()
                    except Exception:
                        pass
                    
                    if resp.status == 200 and result.get("valid", False):
                        # 强制验证签名（防伪造服务器）
                        signature = result.get("signature", "")
                        timestamp = result.get("ts", 0)
                        days_remaining = result.get("days_remaining", 0)
                        
                        # 签名验证是强制的，无签名或签名错误都拒绝
                        if not verify_license_signature(True, days_remaining, timestamp, signature):
                            self.status = LicenseStatus.INVALID
                            self.last_error = "授权响应签名无效（可能是伪造服务器）"
                            return False
                        
                        self.remaining_days = days_remaining
                        self.status = LicenseStatus.VALID
                        self.last_success_time = time.time()
                        self.last_error = None
                        return True
                    
                    # 验证失败：解析错误信息
                    error_msg = result.get("message", "授权验证失败")
                    error_code = result.get("error_code")
                    if not error_msg or error_msg == "授权验证失败":
                        # 尝试从 detail 获取更详细的错误
                        detail = result.get("detail", "")
                        if detail:
                            error_msg = str(detail) if not isinstance(detail, list) else "请求格式错误"
                    
                    self.last_error = error_msg
                    self.status = LicenseStatus.INVALID
                    
                    # 优先基于服务端稳定错误码判定终态，避免依赖文案关键词
                    # 说明：
                    # - KEY_STATUS_INVALID：服务端状态机异常/非法状态，重试意义不大，按终态处理
                    # - KEY_INVALID：兼容潜在服务端扩展错误码
                    fatal_error_codes = {
                        "KEY_EXPIRED",
                        "KEY_FROZEN",
                        "KEY_NOT_FOUND",
                        "KEY_INVALID",
                        "KEY_STATUS_INVALID",
                    }
                    if error_code in fatal_error_codes:
                        self.permanently_expired = True
                        self.status = LicenseStatus.EXPIRED if error_code == "KEY_EXPIRED" else LicenseStatus.INVALID
                        self._log_verify_result(
                            error_code=error_code,
                            status=self.status,
                            terminal=True,
                            message=error_msg,
                        )
                    else:
                        # 兼容旧服务端（未返回 error_code）：
                        # 仅对明确终态文案做兜底，避免把网络/签名/时钟等临时问题误判为终态
                        fatal_keywords_legacy = ["密钥已过期", "密钥已被冻结", "密钥不存在"]
                        if (not error_code) and any(k in error_msg for k in fatal_keywords_legacy):
                            self.permanently_expired = True  # 标记为终态，停止自动重试
                            self.status = LicenseStatus.EXPIRED if "过期" in error_msg else LicenseStatus.INVALID
                            self._log_verify_result(
                                error_code=None,
                                status=self.status,
                                terminal=True,
                                message=error_msg,
                            )
                        else:
                            # 其他未知错误，允许重试
                            self._log_verify_result(
                                error_code=error_code,
                                status=self.status,
                                terminal=False,
                                message=error_msg,
                            )

                    return False
                    
        except aiohttp.ClientError as e:
            self.status = LicenseStatus.INVALID
            self.last_error = f"网络连接失败: {type(e).__name__}"
            # 网络错误属于临时故障，不设置 permanently_expired，允许短间隔重试
            return False
        except Exception as e:
            self.status = LicenseStatus.INVALID
            self.last_error = str(e)
            return False

    async def _do_verify_with_retry(self) -> bool:
        """执行验证（带重试）"""
        # 如果已经是终态，直接跳过重试
        if self.permanently_expired:
            return False

        for attempt in range(self.max_retries):
            try:
                success = await self._do_verify()
                if success:
                    return True
                
                # 如果某次尝试变成了终态（例如第一次就返回"密钥不存在"），立即停止重试
                if self.permanently_expired:
                    return False

                if attempt < self.max_retries - 1:
                    # 指数退避 + 轻微随机抖动
                    backoff = self.retry_delay * (2 ** attempt)
                    jitter = 0.2 * backoff
                    sleep_sec = backoff + (jitter * (0.5))
                    await asyncio.sleep(sleep_sec)
                    
            except Exception as e:
                if attempt < self.max_retries - 1:
                    backoff = self.retry_delay * (2 ** attempt)
                    await asyncio.sleep(backoff)
                    continue
        
        return False

# 创建全局授权管理器实例
license_manager = LicenseManager()

def require_license(func):
    """要求有效授权的装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        await license_manager.ensure_active_or_403(feature=f"{func.__module__}.{func.__name__}")
        return await func(*args, **kwargs)
    return wrapper

@router.get("/env-key")
async def get_env_key(current_user: User = Depends(get_current_user)):
    """获取环境变量中的密钥（仅返回脱敏值）"""
    is_admin = str(getattr(current_user, "is_admin", "")).lower() == "true"
    if not is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可查看授权密钥信息")

    key = os.getenv("SNIFFER_LICENSE_KEY")
    if not key:
        raise HTTPException(status_code=404, detail="环境变量中未找到密钥")

    key = str(key)
    if len(key) <= 10:
        masked = f"{key[:2]}****" if len(key) > 2 else "****"
    else:
        masked = f"{key[:6]}****{key[-4:]}"

    return {
        "key_code": masked,
        "masked": True,
    }

def _mask_license_key(key: Optional[str]) -> Optional[str]:
    """统一授权密钥脱敏规则：前6后4。"""
    if not key:
        return None
    key = str(key)
    if len(key) <= 10:
        return f"{key[:2]}****" if len(key) > 2 else "****"
    return f"{key[:6]}****{key[-4:]}"

@router.get("/status")
async def get_license_status(current_user: User = Depends(get_current_user)):
    """获取授权状态"""
    try:
        is_licensed = await license_manager.verify()
        
        # 计算剩余时间
        now = time.time()
        cache_remaining = max(0, license_manager.cache_duration - 
            (now - license_manager.last_success_time)) if license_manager.status == LicenseStatus.VALID else 0
            
        next_verify = max(0, license_manager.verify_interval - 
            (now - license_manager.last_verify_time)) if license_manager.last_verify_time > 0 else 0
            
        return {
            "is_licensed": is_licensed,
            "is_lifetime": bool(getattr(license_manager, "is_lifetime", False)),
            "status": license_manager.status,
            "remaining_days": license_manager.remaining_days,
            "last_success_time": license_manager.last_success_time,
            "cache_remaining": int(cache_remaining),
            "next_verify": int(next_verify),
            "error": license_manager.last_error,
            "license_key": _mask_license_key(license_manager.license_key),
            "message": "服务已授权" if is_licensed else (
                f"授权验证失败: {license_manager.last_error}" if license_manager.last_error else "授权无效"
            )
        }
    except Exception as e:
        return {
            "is_licensed": False,
            "is_lifetime": False,
            "status": LicenseStatus.INVALID,
            "error": str(e),
            "message": "获取授权状态失败"
        }

@router.post("/refresh")
async def refresh_license(current_user: User = Depends(get_current_user)):
    """手动刷新授权状态"""
    try:
        # 强制重新验证
        license_manager.last_success_time = 0
        license_manager.last_verify_time = 0
        license_manager.permanently_expired = False
        license_manager.kicked_off = False  # 手动刷新时重置被挤下线状态锁，允许发起网络验证请求
        success = await license_manager.verify()
        
        return {
            "success": success,
            "status": license_manager.status,
            "error": license_manager.last_error if not success else None,
            "message": "授权刷新成功" if success else f"授权刷新失败: {license_manager.last_error}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "刷新授权失败"
        }

async def initialize_license_service():
    """初始化授权服务"""
    try:
        logger.debug("正在初始化授权服务...")
        success = await license_manager.initialize()
        if success:
            logger.debug("授权服务初始化成功")
        else:
            logger.warning("授权服务初始化失败")
        return success
    except Exception as e:
        return False 
