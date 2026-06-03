"""
统一浏览器管理器
单浏览器实例 + 单Context + 多标签页方案
支持抖音、B站、YouTube等多平台并发，通过域名隔离实现Cookie独立
"""
import os
import asyncio
import logging
import time
from typing import Optional, Dict
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)


class UnifiedBrowserManager:
    """统一浏览器管理器 - 单实例方案"""
    
    _instance = None
    _initialized = False  # 类变量，用于跟踪是否已初始化
    _lock = asyncio.Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化管理器"""
        # 使用类变量来检查是否已初始化，避免重复初始化
        if UnifiedBrowserManager._initialized:
            return
        
        UnifiedBrowserManager._initialized = True
        self._playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self._pages: Dict[str, Page] = {}  # {platform: page}
        self._page_locks: Dict[str, asyncio.Lock] = {}  # 每个平台的页面锁
        
        # 🔧 标签页管理（统一管理所有页面，包括频道专用页面）
        self._max_total_pages = 20  # 全局标签页上限（提高到20，支持更多并发检测和YouTube频道订阅）
        self._page_last_used: Dict[str, float] = {}  # {page_key: timestamp} 页面最后使用时间
        self._page_created_at: Dict[str, float] = {}  # {page_key: timestamp} 页面创建时间
        self._closing_pages: set = set()  # 正在关闭的页面集合，防止重复关闭
        
        # 临时目录和持久化目录
        self.user_data_dir = "/app/database/chrome/unified"
        self._temp_user_data_dir = None
        
        # 空闲超时管理
        self._idle_timeout = 120  # 2分钟空闲超时（与更短的平台清理冷却配合）
        self._force_cleanup_timeout = 1800  # 30分钟强制回收（处理任务计数卡死）
        self._last_activity = None  # 懒加载模式：初始为None，首次使用时才设置
        self._activity_lock = asyncio.Lock()
        self._cleanup_task = None
        
        # 任务计数管理（上下文管理器）
        self._active_tasks = 0  # 当前活跃任务数
        self._task_lock = asyncio.Lock()  # 任务计数锁
        self._task_names = {}  # {task_id: task_name} 用于调试
        
        # 浏览器锁（防并发初始化）
        self._browser_lock = asyncio.Lock()
        self._is_initializing = False
        self._init_event: Optional[asyncio.Event] = None  # 初始化完成事件（替代轮询）
        
        logger.info("统一浏览器管理器已创建（标签页上限: %d）", self._max_total_pages)
    
    async def _update_activity(self):
        """更新最后活动时间"""
        async with self._activity_lock:
            self._last_activity = time.time()

    async def touch_activity(self, source: str = "") -> bool:
        """外部调用的活动刷新接口（仅浏览器存在时生效）"""
        if not self.context:
            return False
        await self._update_activity()
        if source:
            logger.debug(f"浏览器活动已刷新，source={source}")
        return True
    
    async def _is_browser_healthy(self) -> bool:
        """检查浏览器是否健康（未被手动关闭）"""
        if not self.context:
            return False
        
        try:
            # 🔧 增强健康检查：不仅检查 pages 属性，还尝试执行简单操作
            pages = self.context.pages
            
            # 如果有页面，尝试在其中一个页面执行简单操作验证连接
            if pages:
                try:
                    # 使用较短超时，避免卡住
                    await asyncio.wait_for(
                        pages[0].evaluate("1"),
                        timeout=2.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("浏览器健康检查超时，可能已断开连接")
                    return False
                except Exception:
                    # 页面可能已关闭，但 context 可能仍健康
                    pass
            
            return True
                
        except Exception as e:
            logger.warning(f"浏览器健康检查失败（可能被手动关闭）: {str(e)}")
            return False
    
    async def _check_and_cleanup_now(self):
        """立即检查并清理（任务结束时调用）"""
        try:
            # 检查任务计数
            async with self._task_lock:
                if self._active_tasks > 0:
                    logger.debug(f"仍有 {self._active_tasks} 个活跃任务，跳过立即关闭")
                    return
            
            # 检查空闲时间
            async with self._activity_lock:
                if self._last_activity:
                    idle_time = time.time() - self._last_activity
                    if idle_time >= self._idle_timeout:
                        logger.info(f"任务完成且空闲{idle_time:.1f}秒，立即关闭浏览器")
                        await self.close_browser()
                        self._last_activity = None
                    else:
                        remaining = self._idle_timeout - idle_time
                        logger.debug(f"任务完成但空闲时间不足({idle_time:.1f}秒 < {self._idle_timeout}秒)，还需等待{remaining:.1f}秒")
        except Exception as e:
            logger.error(f"立即检查清理出错: {str(e)}")
    
    def _on_context_closed(self):
        """浏览器 Context 关闭事件回调（用户手动关闭或崩溃）"""
        logger.debug("浏览器 Context 已关闭（可能是空闲自动回收或连接断开）")
        # 清空状态，下次使用时会自动重新初始化
        self.context = None
        self._pages.clear()
        self._page_last_used.clear()
        self._page_created_at.clear()
        
        # 🔧 修复：异步清理Playwright实例，避免driver进程残留
        playwright_to_stop = self._playwright
        self._playwright = None
        if playwright_to_stop:
            # 创建后台任务清理Playwright，避免阻塞
            asyncio.create_task(self._cleanup_playwright_async(playwright_to_stop))
        
        logger.debug("浏览器状态已清空，等待下次自动重新初始化")
    
    async def _cleanup_playwright_async(self, playwright):
        """异步清理Playwright实例"""
        try:
            await playwright.stop()
            logger.debug("Playwright driver进程已清理")
        except Exception as e:
            logger.warning(f"清理Playwright driver进程时出错: {e}")
    
    @asynccontextmanager
    async def task_context(self, platform: str, task_name: str = ""):
        """
        任务上下文管理器：自动管理任务生命周期
        
        Args:
            platform: 平台名称（douyin/bilibili/youtube）
            task_name: 任务名称（用于日志）
        
        Usage:
            async with unified_browser.task_context("douyin", "sync"):
                # 执行任务
                pass
        """
        import uuid
        task_id = str(uuid.uuid4())[:8]
        full_name = f"{platform}_{task_name}" if task_name else platform
        
        # 开始任务
        async with self._task_lock:
            self._active_tasks += 1
            self._task_names[task_id] = full_name
            task_count = self._active_tasks
        
        await self._update_activity()
        logger.info(f"📥 任务开始 [{full_name}] (ID:{task_id}, 活跃任务数:{task_count})")
        
        try:
            # 让出控制权给 with 代码块
            yield
            
        finally:
            # 结束任务
            async with self._task_lock:
                self._active_tasks = max(0, self._active_tasks - 1)
                self._task_names.pop(task_id, None)
                task_count = self._active_tasks
            
            await self._update_activity()
            logger.info(f"📤 任务结束 [{full_name}] (ID:{task_id}, 活跃任务数:{task_count})")
            
            # 如果所有任务都完成了，立即检查是否可以关闭浏览器
            if task_count == 0:
                logger.debug("所有任务已完成，触发立即检查")
                await self._check_and_cleanup_now()
    
    def _get_temp_work_dir(self) -> str:
        """获取临时工作目录路径"""
        return "/app/database/chrome/tmp/unified_work"
    
    async def _setup_symlink(self):
        """设置符号链接（临时目录 -> 持久化目录）"""
        import shutil
        
        temp_user_data_dir = self._get_temp_work_dir()
        os.makedirs(temp_user_data_dir, exist_ok=True)
        
        temp_default_dir = os.path.join(temp_user_data_dir, "Default")
        persistent_default_dir = os.path.join(self.user_data_dir, "Default")
        
        # 确保持久化目录存在
        os.makedirs(persistent_default_dir, exist_ok=True)
        
        # 检查符号链接是否存在且正确
        if os.path.exists(temp_default_dir) and not os.path.islink(temp_default_dir):
            logger.warning("Default不是符号链接，正在重新创建...")
            shutil.rmtree(temp_default_dir)
            os.symlink(persistent_default_dir, temp_default_dir)
            logger.info("符号链接重新创建成功")
        elif not os.path.exists(temp_default_dir):
            os.symlink(persistent_default_dir, temp_default_dir)
            logger.info("符号链接创建成功")
        
        return temp_user_data_dir
    
    async def _cleanup_singleton_locks(self, temp_dir: str):
        """清理Chrome单例锁文件及损坏的会话恢复文件"""
        lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie", "DevToolsActivePort"]
        for lock_name in lock_files:
            lock_path = os.path.join(temp_dir, lock_name)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                    logger.debug(f"已删除锁文件: {lock_name}")
                except Exception:
                    pass

        # 清理会话恢复文件，防止SIGKILL损坏的session文件导致启动卡死
        default_dir = os.path.join(temp_dir, "Default")
        if os.path.isdir(default_dir):
            session_files = ["Current Session", "Current Tabs", "Last Session", "Last Tabs"]
            for fname in session_files:
                fpath = os.path.join(default_dir, fname)
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                        logger.debug(f"已清理会话恢复文件: {fname}")
                    except Exception:
                        pass
    
    def _get_browser_args(self) -> list:
        """获取浏览器启动参数"""
        return [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-zygote',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--display=:99',
            '--start-maximized',
            '--disable-blink-features=AutomationControlled',
            '--disable-process-singleton',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-background-networking',
            '--disable-background-downloads',
            '--disable-client-side-phishing-detection',
            '--disable-component-extensions-with-background-pages',
            '--disable-default-apps',
            '--disable-domain-reliability',
            '--disable-extensions',
            '--disable-features=TranslateUI',
            '--disable-hang-monitor',
            '--disable-ipc-flooding-protection',
            '--disable-popup-blocking',
            '--disable-prompt-on-repost',
            '--disable-sync',
            '--disable-translate',
            '--metrics-recording-only',
            '--no-first-run',
            '--no-default-browser-check',
            '--password-store=basic',
            '--use-mock-keychain',
            '--no-service-autorun',
            '--export-tagged-pdf',
            '--disable-search-engine-choice-screen',
            '--force-color-profile=srgb',
            '--disable-field-trial-config',
            '--disable-breakpad',
            '--remote-debugging-port=9222',  # 添加CDP调试端口，用于查询真实标签页数
            '--disable-component-update',
            '--disable-features=ImprovedCookieControls,LazyFrameLoading,GlobalMediaControls,DestroyProfileOnBrowserClose,MediaRouter,DialMediaRouteProvider,AcceptCHFrame,AutoExpandDetailsElement,CertificateTransparencyComponentUpdater,AvoidUnnecessaryBeforeUnloadCheckSync,Translate,HttpsUpgrades,PaintHolding',
            '--allow-pre-commit-input',
            # 缓存优化：限制缓存大小，减少磁盘和内存占用（1.3GB -> ~150MB）
            '--disk-cache-size=104857600',   # 限制磁盘缓存为 100MB
            '--media-cache-size=52428800',   # 限制媒体缓存为 50MB
            # 🔧 额外内存优化参数
            '--aggressive-cache-discard',    # 更激进的缓存丢弃策略
            '--disable-background-media-playback',  # 禁用后台媒体播放
            '--disable-low-res-tiling',      # 禁用低分辨率平铺（减少GPU内存）
            '--disable-software-rasterizer', # 禁用软件光栅化（如果GPU可用）
        ]
    
    async def init_browser(self) -> bool:
        """初始化浏览器（全局只初始化一次）"""
        # 防并发初始化
        if self.context:
            return True
        
        if self._is_initializing:
            # 🔧 优化：使用 Event 替代轮询等待初始化完成
            logger.info("检测到其他协程正在初始化浏览器，等待完成...")
            wait_start = time.time()
            
            # 确保事件已创建
            if self._init_event is None:
                self._init_event = asyncio.Event()
            
            try:
                # 使用事件等待，最多等待60秒（与浏览器启动超时一致）
                await asyncio.wait_for(self._init_event.wait(), timeout=60.0)
                # 初始化完成，检查结果
                if self.context:
                    logger.info(f"等待初始化完成成功，耗时{time.time() - wait_start:.2f}秒")
                    return True
                else:
                    logger.warning("等待完成但 context 仍为空，初始化可能失败")
                    return False
            except asyncio.TimeoutError:
                # 等待超时，记录详细信息
                logger.error(f"❌ 等待浏览器初始化超时（60秒），_is_initializing={self._is_initializing}, context={self.context is not None}")
                # 🔧 关键修复：强制重置初始化标志，防止永久死锁
                if self._is_initializing and not self.context:
                    logger.warning("强制重置 _is_initializing 标志，允许其他协程尝试初始化")
                    self._is_initializing = False
                    if self._init_event:
                        self._init_event.clear()
                return False
        
        self._is_initializing = True
        # 🔧 创建或重置初始化事件
        if self._init_event is None:
            self._init_event = asyncio.Event()
        else:
            self._init_event.clear()
        
        init_success = False  # 跟踪初始化是否成功
        try:
            await self._update_activity()
            
            async with self._browser_lock:
                if self.context:
                    init_success = True
                    return True
                
                # 确保目录存在
                os.makedirs(self.user_data_dir, exist_ok=True)
                
                # 设置符号链接
                temp_user_data_dir = await self._setup_symlink()
                self._temp_user_data_dir = temp_user_data_dir
                
                # 清理锁文件
                await self._cleanup_singleton_locks(temp_user_data_dir)
                
                # 定义内部检查函数（避免污染全局空间）
                async def _check_display_server() -> bool:
                    try:
                        import socket
                        display = os.environ.get('DISPLAY', ':99')
                        # 解析端口，如 :99 -> 99
                        display_num = int(display.split(':')[-1].split('.')[0])
                        socket_path = f"/tmp/.X11-unix/X{display_num}"
                        
                        if not os.path.exists(socket_path):
                            logger.error(f"❌ X Server Socket不存在: {socket_path}。原因是Xvfb服务未启动或已崩溃。请检查supervisor状态。")
                            return False

                        # 尝试连接Socket
                        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        sock.settimeout(1.0)
                        sock.connect(socket_path)
                        sock.close()
                        return True
                    except (ValueError, IndexError):
                        logger.warning(f"无法解析DISPLAY环境变量: {display}，跳过检查")
                        return True
                    except ConnectionRefusedError:
                        logger.error(f"❌ X Server Socket拒绝连接: {socket_path}。可能是Xvfb服务死锁或残留了锁文件。尝试重启容器。")
                        return False
                    except Exception as e:
                        logger.warning(f"X Server检查时发生忽略的异常: {str(e)}")
                        return True

                # 🚀 启动前检查 X Server 状态（快速失败机制）
                if not await _check_display_server():
                    logger.critical("🛑 检测到显示服务(Xvfb)异常，终止浏览器启动。")
                    init_success = False
                    return False
                
                # 启动Playwright（带超时保护）
                if not self._playwright:
                    try:
                        self._playwright = await asyncio.wait_for(
                            async_playwright().start(),
                            timeout=30.0
                        )
                        logger.info("Playwright已启动")
                    except asyncio.TimeoutError:
                        logger.error("❌ Playwright 启动超时（30秒）")
                        init_success = False
                        return False
                
                # 启动浏览器（持久化Context，带超时保护）
                try:
                    self.context = await asyncio.wait_for(
                        self._playwright.chromium.launch_persistent_context(
                            user_data_dir=temp_user_data_dir,
                            headless=False,
                            channel="chrome",
                            viewport={"width": 1280, "height": 720},
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
                            args=self._get_browser_args(),
                            ignore_https_errors=True,
                        ),
                        timeout=60.0
                    )
                except asyncio.TimeoutError:
                    logger.error("❌ 浏览器启动超时（60秒）")
                    # 清理已启动的 Playwright
                    if self._playwright:
                        try:
                            await self._playwright.stop()
                        except Exception:
                            pass
                        self._playwright = None
                    init_success = False
                    return False
                
                # 🔧 注册浏览器关闭事件监听
                self.context.on('close', self._on_context_closed)
                
                # 注入JavaScript脚本隐藏自动化特征
                await self.context.add_init_script("""
                    // 1. 覆盖navigator.webdriver
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    
                    // 2. 增强chrome对象，模拟真实Chrome环境
                    window.chrome = {
                        runtime: {
                            onConnect: undefined,
                            onMessage: undefined
                        },
                        app: {
                            isInstalled: false,
                            InstallState: {
                                DISABLED: 'disabled',
                                INSTALLED: 'installed',
                                NOT_INSTALLED: 'not_installed'
                            },
                            RunningState: {
                                CANNOT_RUN: 'cannot_run',
                                READY_TO_RUN: 'ready_to_run',
                                RUNNING: 'running'
                            }
                        }
                    };
                    
                    // 3. 覆盖permissions
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                    
                    // 4. 真实的plugins列表
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => ({
                            0: {
                                name: "Chrome PDF Plugin",
                                filename: "internal-pdf-viewer",
                                description: "Portable Document Format",
                                length: 1
                            },
                            1: {
                                name: "Chrome PDF Viewer",
                                filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai",
                                description: "",
                                length: 1
                            },
                            2: {
                                name: "Native Client",
                                filename: "internal-nacl-plugin",
                                description: "",
                                length: 2
                            },
                            length: 3,
                            item: function(index) { return this[index] || null; },
                            namedItem: function(name) {
                                for (let i = 0; i < this.length; i++) {
                                    if (this[i].name === name) return this[i];
                                }
                                return null;
                            }
                        })
                    });
                    
                    // 5. 覆盖languages
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['zh-CN', 'zh', 'en-US', 'en']
                    });
                    
                    // 6. 硬件信息伪造
                    Object.defineProperty(navigator, 'hardwareConcurrency', {
                        get: () => 8
                    });
                    
                    Object.defineProperty(navigator, 'deviceMemory', {
                        get: () => 8
                    });
                    
                    // 7. 修复窗口尺寸一致性
                    Object.defineProperty(window, 'outerHeight', {
                        get: () => 824  // 720 + 104 (浏览器UI高度)
                    });
                    
                    Object.defineProperty(window, 'outerWidth', {
                        get: () => 1280
                    });
                    
                    // 8. 屏幕信息伪造
                    Object.defineProperty(screen, 'width', {
                        get: () => 1920
                    });
                    
                    Object.defineProperty(screen, 'height', {
                        get: () => 1080
                    });
                    
                    Object.defineProperty(screen, 'availWidth', {
                        get: () => 1920
                    });
                    
                    Object.defineProperty(screen, 'availHeight', {
                        get: () => 1040  // 减去任务栏高度
                    });
                    
                    Object.defineProperty(screen, 'colorDepth', {
                        get: () => 24
                    });
                    
                    Object.defineProperty(screen, 'pixelDepth', {
                        get: () => 24
                    });
                    
                    // 9. 网络连接信息伪造
                    Object.defineProperty(navigator, 'connection', {
                        get: () => ({
                            effectiveType: '4g',
                            rtt: 100,
                            downlink: 10,
                            saveData: false
                        })
                    });
                    
                    // 10. 平台信息优化
                    Object.defineProperty(navigator, 'platform', {
                        get: () => 'Win32'
                    });
                    
                    // 11. 移除自动化痕迹
                    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
                    
                    // 12. WebGL指纹伪造
                    const getParameter = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(parameter) {
                        if (parameter === 37445) {
                            return 'Intel Inc.';
                        }
                        if (parameter === 37446) {
                            return 'Intel(R) HD Graphics 630';
                        }
                        return getParameter.call(this, parameter);
                    };
                    
                    // 13. Canvas指纹 (移除随机化，保持稳定性)
                    // 保持原生行为，避免指纹变动导致掉登录
                    
                    // 14. 时间精度降低（防止高精度时间指纹）
                    const originalNow = Date.now;
                    Date.now = function() {
                        return Math.floor(originalNow() / 100) * 100;
                    };
                    
                    // 15. 伪造Battery API
                    Object.defineProperty(navigator, 'getBattery', {
                        get: () => () => Promise.resolve({
                            charging: true,
                            chargingTime: 0,
                            dischargingTime: Infinity,
                            level: 1
                        })
                    });
                    
                    console.log('🔒 反检测脚本已加载');
                """)
                
                # 设置初始活动时间
                self._last_activity = time.time()
                
                logger.info("✅ 统一浏览器初始化成功")
                logger.debug(f"   数据目录: {self.user_data_dir}")
                logger.debug(f"   临时目录: {temp_user_data_dir}")
                
                init_success = True
                return True
                
        except Exception as e:
            logger.error(f"❌ 浏览器初始化失败: {type(e).__name__}: {str(e)}")
            import traceback
            full_traceback = traceback.format_exc()
            logger.error(f"完整堆栈:\n{full_traceback}")
            # 记录更多上下文信息
            logger.error(f"初始化上下文: playwright={self._playwright is not None}, context={self.context is not None}, temp_dir={getattr(self, '_temp_user_data_dir', 'N/A')}")
            
            # 🔧 优化：清理资源（Playwright 可能已部分初始化）
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            
            init_success = False
            return False
        finally:
            # 🔧 统一通知等待的协程初始化完成（无论成功或失败）
            if self._init_event:
                self._init_event.set()
            self._is_initializing = False
    
    async def get_page(self, page_key: str, auto_create: bool = True) -> Optional[Page]:
        """
        获取或创建页面（支持平台和频道页面）
        
        Args:
            page_key: 页面标识，支持以下格式：
                - "platform" - 平台基础页面 (如 "douyin", "bilibili", "youtube")
                - "platform:identifier" - 平台专用页面 (如 "youtube:UCX6OQ3DkcsbYNE6H8uQQuVA")
            auto_create: 如果不存在是否自动创建
        
        Returns:
            Page对象，如果失败返回None
        """
        # 解析 page_key 获取平台名称（用于日志）
        platform = page_key.split(':')[0] if ':' in page_key else page_key
        # 检查浏览器是否健康（可能被用户手动关闭）
        if not await self._is_browser_healthy():
            logger.info(f"[{platform}] 浏览器未初始化或已被关闭，需要重新初始化")
            
            # 🔧 关键修复：使用锁保护清空和初始化操作，防止并发冲突
            async with self._browser_lock:
                # 双重检查：获取锁后再次检查健康状态（可能已被其他协程初始化）
                if await self._is_browser_healthy():
                    logger.debug(f"[{platform}] 浏览器已被其他协程恢复，无需重新初始化")
                    # 不清空，继续使用
                else:
                    logger.info(f"[{platform}] 确认浏览器不健康，清空并标记需要重新初始化")
                    # 只清空状态，不在这里初始化（避免嵌套锁）
                    self.context = None
                    self._pages.clear()
            
            # 在锁外调用 init_browser（它内部有自己的锁）
            if not await self.init_browser():
                logger.error(f"[{platform}] 浏览器重新初始化失败")
                return None
            logger.info(f"[{platform}] 浏览器重新初始化成功")
        
        # 为每个页面创建独立的锁
        if page_key not in self._page_locks:
            self._page_locks[page_key] = asyncio.Lock()
        
        # 🔧 修复：将LRU清理也纳入全局锁保护，避免并发计数错误
        async with self._browser_lock:
            async with self._page_locks[page_key]:
                # 检查是否已有页面
                if page_key in self._pages:
                    page = self._pages[page_key]
                    try:
                        # 检查页面是否仍然有效
                        await page.evaluate("1")
                        await self._update_activity()
                        # 更新页面使用时间
                        self._page_last_used[page_key] = time.time()
                        return page
                    except Exception as e:
                        logger.warning(f"[{page_key}] 页面无效，将重新创建: {str(e)}")
                        del self._pages[page_key]
                        if page_key in self._page_last_used:
                            del self._page_last_used[page_key]
                        if page_key in self._page_created_at:
                            del self._page_created_at[page_key]
                
                # 🔧 检查标签页总数是否达到上限
                if len(self._pages) >= self._max_total_pages:
                    logger.warning(f"标签页已达上限({self._max_total_pages})，清理最少使用的页面")
                    await self._cleanup_least_used_page()
                
                # 创建新页面
                if auto_create:
                    try:
                        # 统一创建新标签页
                        page = await self.context.new_page()
                        
                        page.set_default_timeout(30000)
                        self._pages[page_key] = page
                        # 记录页面创建和使用时间
                        now = time.time()
                        self._page_created_at[page_key] = now
                        self._page_last_used[page_key] = now
                        await self._update_activity()
                        logger.debug(f"✅ [{page_key}] 标签页已创建（当前总数: {len(self._pages)}/{self._max_total_pages}）")
                        return page
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"❌ 创建{platform}标签页失败: {error_msg}")
                        
                        # 如果错误是 "Target page, context or browser has been closed"
                        # 说明浏览器在健康检查之后被关闭了，需要清空并重试
                        if "closed" in error_msg.lower() or "target" in error_msg.lower():
                            logger.warning("检测到浏览器已关闭，清空状态并标记需要重新初始化")
                            self.context = None
                            self._pages.clear()
                            self._playwright = None
                            # 🔧 不在锁内调用 init_browser()，设置标记让外层处理
                            # 返回 None，让调用方重试
                            return None
                        
                        return None
                
                return None
    
    async def close_page(self, page_key: str):
        """关闭指定页面"""
        # 防止重复关闭
        if page_key in self._closing_pages:
            logger.debug(f"[{page_key}] 标签页正在关闭中，跳过重复操作")
            return
        
        # 检查页面是否存在
        if page_key not in self._pages:
            logger.debug(f"[{page_key}] 标签页不存在，无需关闭")
            return
        
        # 标记为正在关闭
        self._closing_pages.add(page_key)
        
        try:
            page_obj = self._pages.get(page_key)
            if page_obj is None:
                logger.debug(f"[{page_key}] 页面对象为空，直接清理记录")
                self._cleanup_page_records(page_key)
                return
            
            try:
                # 检查页面是否已经关闭
                if hasattr(page_obj, 'is_closed') and page_obj.is_closed():
                    logger.debug(f"[{page_key}] 页面已关闭，直接清理记录")
                else:
                    # 尝试关闭页面
                    await page_obj.close()
                    logger.debug(f"[{page_key}] 标签页已关闭（当前总数: {len(self._pages)-1}/{self._max_total_pages}）")
            except Exception as e:
                # 记录详细的错误信息，但降低日志级别
                error_type = type(e).__name__
                logger.warning(f"关闭 [{page_key}] 标签页时出现异常: {error_type}: {str(e)}")
            finally:
                # 无论是否成功关闭，都要清理内存中的记录，避免内存泄漏
                self._cleanup_page_records(page_key)
        finally:
            # 移除关闭标记
            self._closing_pages.discard(page_key)
    
    def _cleanup_page_records(self, page_key: str):
        """清理页面相关的所有记录"""
        # 清理页面对象
        if page_key in self._pages:
            del self._pages[page_key]
        # 清理相关记录
        if page_key in self._page_last_used:
            del self._page_last_used[page_key]
        if page_key in self._page_created_at:
            del self._page_created_at[page_key]
        if page_key in self._page_locks:
            del self._page_locks[page_key]
    
    async def _cleanup_least_used_page(self):
        """清理最少使用的页面（全局LRU策略）"""
        if not self._pages:
            return
        
        # 找到最久未使用的页面（不区分平台，全局LRU）
        least_used_key = min(
            self._page_last_used.items(),
            key=lambda x: x[1]
        )[0]
        
        idle_time = time.time() - self._page_last_used[least_used_key]
        logger.info(f"🗑️ 清理最少使用的页面: [{least_used_key}] (空闲: {idle_time:.1f}秒)")
        await self.close_page(least_used_key)
    
    async def close_browser(self):
        """关闭浏览器"""
        logger.debug("正在关闭统一浏览器...")
        
        try:
            # 关闭所有页面
            for page_key in list(self._pages.keys()):
                await self.close_page(page_key)
            
            # 清理所有记录
            self._page_last_used.clear()
            self._page_created_at.clear()
            self._closing_pages.clear()
            
            # 关闭Context（如果还未被_on_context_closed回调清理）
            context_to_close = self.context
            if context_to_close:
                try:
                    await context_to_close.close()
                    logger.info("BrowserContext已关闭")
                except Exception as e:
                    # Context可能已被关闭（触发了_on_context_closed回调），这是正常的
                    if "closed" in str(e).lower() or "has been closed" in str(e).lower():
                        logger.debug(f"Context已通过回调关闭: {str(e)}")
                    else:
                        logger.warning(f"关闭Context时出现异常: {str(e)}")
                finally:
                    self.context = None
            
            # 停止Playwright（如果还未被_on_context_closed回调清理）
            playwright_to_stop = self._playwright
            if playwright_to_stop:
                try:
                    await playwright_to_stop.stop()
                    logger.info("Playwright已停止")
                except Exception as e:
                    # Playwright可能已被异步清理，这是正常的
                    if "closed" in str(e).lower() or "has been closed" in str(e).lower():
                        logger.debug(f"Playwright已通过回调清理: {str(e)}")
                    else:
                        logger.warning(f"停止Playwright时出现异常: {str(e)}")
                finally:
                    self._playwright = None
            
            logger.debug("✅ 统一浏览器已关闭")
            
        except Exception as e:
            # 捕获其他可能的异常（通常不应该发生）
            error_msg = str(e).lower()
            if "closed" in error_msg or "has been closed" in error_msg:
                # Context/Playwright已被关闭，这是正常情况（可能通过回调清理）
                logger.debug(f"浏览器已通过回调关闭: {str(e)}")
            else:
                logger.error(f"❌ 关闭浏览器失败: {str(e)}")
            # 即使出错也要清空状态，防止下次无法初始化
            self.context = None
            self._playwright = None
            self._pages.clear()
    
    async def start_cleanup_task(self):
        """启动自动清理任务"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._auto_cleanup())
            logger.debug("统一浏览器自动清理任务已启动")
    
    async def stop_cleanup_task(self):
        """停止自动清理任务"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("统一浏览器自动清理任务已停止")
    
    async def _auto_cleanup(self):
        """自动清理空闲浏览器"""
        logger.debug("统一浏览器自动清理任务开始运行（懒加载模式）")
        while True:
            await asyncio.sleep(10)  # 每10秒检查一次
            try:
                # 如果浏览器未初始化，跳过检查
                if not self.context:
                    # logger.debug("浏览器未初始化，跳过空闲检查")
                    continue
                
                # 先检查是否有活跃任务
                async with self._task_lock:
                    task_count = self._active_tasks
                    active_task_names = list(self._task_names.values())
                if task_count > 0:
                    # 正常情况下有任务就不清理，但如果长期无活动，说明计数可能卡死，执行兜底回收
                    async with self._activity_lock:
                        idle_time = (time.time() - self._last_activity) if self._last_activity else 0
                    if idle_time >= self._force_cleanup_timeout:
                        logger.warning(
                            f"检测到任务计数疑似卡死：active_tasks={task_count}, "
                            f"idle_time={idle_time:.1f}s, tasks={active_task_names}，执行强制回收"
                        )
                        async with self._task_lock:
                            self._active_tasks = 0
                            self._task_names.clear()
                        await self.close_browser()
                        async with self._activity_lock:
                            self._last_activity = None
                        logger.warning("强制回收完成：已重置任务计数并关闭浏览器")
                    else:
                        logger.debug(f"有 {task_count} 个活跃任务，跳过空闲检查: {active_task_names}")
                    continue
                
                # 再检查空闲时间
                async with self._activity_lock:
                    if self._last_activity and (time.time() - self._last_activity) > self._idle_timeout:
                        logger.debug(f"浏览器空闲超过{self._idle_timeout}秒，准备关闭")
                        await self.close_browser()
                        self._last_activity = None
                        logger.info(f"浏览器空闲回收已执行：空闲超过{self._idle_timeout}秒，浏览器已关闭")
            except Exception as e:
                logger.error(f"自动清理任务出错: {str(e)}")
    
    def get_status(self) -> dict:
        """获取浏览器状态（用于调试和监控）"""
        return {
            "initialized": self.context is not None,
            "active_pages": list(self._pages.keys()),
            "page_count": len(self._pages),  # 管理的页面数
            "active_tasks": self._active_tasks,  # 活跃任务数
            "task_names": list(self._task_names.values()),  # 任务名称列表
            "last_activity": self._last_activity,
            "idle_timeout": self._idle_timeout,
            "force_cleanup_timeout": self._force_cleanup_timeout,
            "data_directory": self.user_data_dir,
        }


# 全局单例实例
unified_browser = UnifiedBrowserManager()


def get_browser_manager() -> UnifiedBrowserManager:
    """获取统一浏览器管理器实例（供其他模块使用）"""
    return unified_browser
