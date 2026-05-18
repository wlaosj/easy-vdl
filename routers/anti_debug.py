"""
反调试检测模块
用于检测和防止调试器附加到程序
"""

import sys
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AntiDebugger:
    """反调试检测器"""
    
    def __init__(self, strict_mode: bool = True):
        """
        初始化反调试检测器
        
        Args:
            strict_mode: 严格模式，检测到调试器时立即退出程序
        """
        self.strict_mode = strict_mode
        self._warned = False
    
    def check_trace_function(self) -> bool:
        """
        检测 sys.settrace（Python 调试器的核心机制）
        
        Returns:
            True: 检测到调试器
            False: 未检测到调试器
        """
        if sys.gettrace() is not None:
            logger.error("🚨 安全警告: 检测到 sys.settrace 调试器")
            return True
        return False
    
    def check_debugger_modules(self) -> Optional[str]:
        """
        检测已加载的调试器模块
        
        Returns:
            检测到的调试器模块名称，未检测到则返回 None
        """
        # 常见的调试器模块
        debugger_modules = [
            'pdb',           # Python 内置调试器
            'debugpy',       # VS Code 调试器
            'pydevd',        # PyCharm 调试器
            'ipdb',          # IPython 调试器
            'pudb',          # 终端调试器
            'bdb',           # 调试器基类
        ]
        
        for module_name in debugger_modules:
            if module_name in sys.modules:
                logger.error(f"🚨 安全警告: 检测到调试器模块 '{module_name}'")
                return module_name
        
        return None
    
    def check_profiler(self) -> bool:
        """
        检测性能分析器（也可用于调试）
        
        Returns:
            True: 检测到性能分析器
            False: 未检测到
        """
        if sys.getprofile() is not None:
            logger.error("🚨 安全警告: 检测到 sys.setprofile 性能分析器")
            return True
        return False
    
    def check_environment(self) -> Optional[str]:
        """
        检测环境变量中的调试标志
        
        Returns:
            检测到的环境变量名称，未检测到则返回 None
        """
        # 常见的调试环境变量
        debug_env_vars = [
            'PYTHONDEBUG',
            'PYDEBUG',
            'DEBUG',
            'DEBUGPY_RUNNING',
        ]
        
        for env_var in debug_env_vars:
            if os.getenv(env_var):
                logger.error(f"🚨 安全警告: 检测到调试环境变量 '{env_var}'")
                return env_var
        
        return None
    
    def check_all(self) -> bool:
        """
        执行所有反调试检测
        
        Returns:
            True: 检测到调试器
            False: 未检测到调试器
        """
        detected = False
        
        # 检测 trace 函数
        if self.check_trace_function():
            detected = True
        
        # 检测调试器模块
        if self.check_debugger_modules():
            detected = True
        
        # 检测性能分析器
        if self.check_profiler():
            detected = True
        
        # 检测环境变量
        if self.check_environment():
            detected = True
        
        return detected
    
    def protect(self, exit_on_detect: bool = None) -> bool:
        """
        执行保护检测，如果检测到调试器则采取行动
        
        Args:
            exit_on_detect: 是否在检测到调试器时退出程序
                           None 时使用 strict_mode 设置
        
        Returns:
            True: 检测到调试器
            False: 未检测到调试器
        """
        if exit_on_detect is None:
            exit_on_detect = self.strict_mode
        
        detected = self.check_all()
        
        if detected:
            if exit_on_detect:
                logger.critical("🚨 检测到调试器，程序将立即退出以保护安全")
                # 使用 os._exit 而不是 sys.exit，无法被捕获
                os._exit(1)
            else:
                if not self._warned:
                    logger.warning("⚠️ 检测到调试器，但允许继续运行（非严格模式）")
                    self._warned = True
        
        return detected


# 全局单例
_anti_debugger = None


def get_anti_debugger(strict_mode: bool = True) -> AntiDebugger:
    """
    获取反调试检测器单例
    
    Args:
        strict_mode: 严格模式
    
    Returns:
        AntiDebugger 实例
    """
    global _anti_debugger
    if _anti_debugger is None:
        _anti_debugger = AntiDebugger(strict_mode=strict_mode)
    return _anti_debugger


def quick_check() -> bool:
    """
    快速检测（不退出程序）
    
    Returns:
        True: 检测到调试器
        False: 未检测到调试器
    """
    detector = get_anti_debugger(strict_mode=False)
    return detector.check_all()


def protect_function(func):
    """
    装饰器：保护函数不被调试
    
    使用方法:
        @protect_function
        def sensitive_function():
            # 敏感代码
            pass
    """
    def wrapper(*args, **kwargs):
        # 每次调用函数时都检测
        detector = get_anti_debugger(strict_mode=True)
        detector.protect()
        return func(*args, **kwargs)
    
    return wrapper
