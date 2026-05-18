"""
订阅模块共享配置和基础依赖
"""
import logging
import asyncio

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 平台并发配置 - 控制批量检测更新时的并发数
PLATFORM_CONCURRENT_LIMITS = {
    # YouTube系列 - API稳定，可以并发
    "youtube": 2,              # YouTube频道：API稳定，保守并发=2，避免占满全局信号量
                               # 包含：频道视频(youtube_tab_type='videos')和Shorts(youtube_tab_type='shorts')
    "youtube_playlist": 2,     # YouTube播放列表：独立平台类型，保守并发=2
    
    # TikTok系列 - 使用yt-dlp，相对稳定
    "tiktok": 2,               # TikTok用户：保守并发=2，留足余量给其他平台
    "netease": 2,              # 网易云歌单：yt-dlp 拉取，保守并发=2
    "x": 2,                    # X 点赞：GraphQL 接口，保守并发=2
    
    # 抖音系列 - 依赖浏览器，反爬虫严格，必须串行
    "douyin": 1,               # 抖音博主：代码强制串行（修改此值无效）
                               # 包含：博主视频(subscription_type='user')和点赞(subscription_type='favorite')
    "douyin_collection": 1,    # 抖音合集：代码强制串行（修改此值无效）
    
    # Instagram - 使用instagrapi API，保守串行
    "instagram": 1,

    # 小红书 - 同样依赖浏览器和签名API，建议串行
    "xiaohongshu": 1,
    
    # B站系列
    "bilibili": 1,             # B站UP主：代码强制串行（修改此值无效）
    "bilibili_collection": 1,  # B站合集：代码强制串行（修改此值无效）
    
    # 默认值：未配置的平台默认为1（串行）
}

# 平台反风控参数配置 - 控制批量下载时的延迟参数
# 注意：所有平台的最高并发数（batch_size）都是5，区别在于延迟时间
PLATFORM_ANTI_CRAWL_CONFIG = {
    # 抖音系列 - 使用浏览器解析，严格反风控
    "douyin": {
        "stagger_delay": (0.5, 1.0),   # 错峰延迟范围（秒）：回调到0.5-1.0秒（与其他平台一致）
        "batch_interval": 2,            # 批次间隔（秒）：回调到2秒
    },
    "douyin_collection": {
        "stagger_delay": (0.5, 1.0),
        "batch_interval": 2,
    },
    # 小红书 - 使用浏览器+API，采用与抖音相同的保守节奏
    "xiaohongshu": {
        "stagger_delay": (0.5, 1.0),
        "batch_interval": 2,
    },
    # 其他平台 - 使用yt-dlp，不需要严格反风控
    "default": {
        "stagger_delay": (0.5, 1.0),   # 错峰延迟范围（秒）
        "batch_interval": 2,           # 批次间隔（秒）
    },
}

# 抖音平台浏览器活跃任务数上限（所有抖音播主共享，避免浏览器资源过载）
MAX_DOUYIN_BROWSER_ACTIVE_TASKS = 5

def get_platform_anti_crawl_config(platform: str) -> dict:
    """获取平台的反风控配置"""
    platform = platform.lower()
    return PLATFORM_ANTI_CRAWL_CONFIG.get(platform, PLATFORM_ANTI_CRAWL_CONFIG["default"])

# 添加一个全局集合来存储取消的任务ID
cancelled_batch_downloads = set()

# 任务完成事件字典：{task_id: asyncio.Event()}
task_completion_events = {}
task_completion_lock = asyncio.Lock()
