# -*- coding: utf-8 -*-
"""AI 高光切片 V1：弹幕预处理 + 候选片段生成。"""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
import random
import heapq
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple, Optional


# 纯噪声（会被彻底丢弃，不计入热度）
NOISE_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^[^\w\s]+$"),  # 仅包含特殊符号（不含字母数字下划线词）
]

# 情绪/热度信号（计入热度，但在关键词提取时会过滤）
EMOTION_PATTERNS = [
    re.compile(r"^(哈|啊|哦|嗯|6|1|!|\?|。|，|、|~|～|草|q|o|x|z|w){2,}$", re.IGNORECASE),
    re.compile(r"^[0-9]+$", re.IGNORECASE), # 纯数字，如 666, 111
]

HIGHLIGHT_HINTS = {
    "high_energy": [
        # 游戏/竞技类
        "卧槽", "奈斯", "牛逼", "nice", "666", "杀穿", "暴杀", "游龙", "炸裂", "绝杀",
        "逆天", "封神", "太强", "秒", "赢了", "名场面", "神操作", "帅", "硬核", "拿下",
        "吃鸡", "灭队", "1v4", "五杀", "暴走", "大杀特杀", "MVP", "团灭", "连胜",
        # 唱歌/音乐类
        "开口跪", "听哭", "绝了", "太稳了", "神仙嗓音", "高音", "破音", "音色", "太好听了",
        "循环播放", "单曲循环", "耳朵怀孕", "神曲", "天籁", "开口脆",
        # 带货/商品类
        "上链接", "拼手速", "抢", "秒没", "加库存", "炸价格", "性价比", "冲", "抢到",
        "限量", "抢光", "炸场", "卖爆", "返场", "错过拍大腿",
        # 户外/美景类
        "壮观", "美哭了", "风景如画", "壁纸级别", "绝了", "这风景", "太美", "绝了绝了",
        "打卡", "分享", "震撼", "第一视角",
        # 棋牌/桌游类
        "通杀", "翻盘", "绝杀", "神抽", "天胡", "王炸", "炸弹", "春天", "倍杀",
        # 情感/互动类
        "甜", "齁", "磕到了", "上头", "好甜", "撒糖", "CP", "锁死", "在一起",
        # 学习/知识类
        "干货", "必考", "考点", "记笔记", "学到了", "收藏", "666", "牛",
    ],
    "funny": [
        # 游戏类
        "笑死", "哈哈", "绷不住", "乐", "抽象", "节目效果", "离谱", "下饭", "真菜",
        "拉了", "出餐", "大厨", "肉蛋葱鸡", "国宴", "诗人", "逛街", "舒服了",
        "太舒服辣", "逗逗你的", "人机", "描边", "马枪", "马老师", "下饭操作",
        # 美食类
        "看饿了", "想吃", "太香了", "深夜放毒", "馋", "流口水", "饿了", "好香",
        "干饭", "干饭人", "吃播", "吃相",
        # 整活/户外类
        "整活", "翻车", "社死", "尴尬", "整蛊", "离谱", "笑喷", "笑抽", "笑不活",
        "整活了", "新活", "老梗", "玩梗", "整烂活",
        # 带货/搞笑类
        "炸裂", "砍价", "搞笑", "整活", "才艺", "表演", "模仿", "配音",
        # 棋牌娱乐
        "好家伙", "这也行", "离谱", "迷惑", "绝活", "骚操作", "花活",
    ],
    "controversy": [
        # 竞技争议
        "争议", "对线", "节奏", "喷", "吵", "黑", "破防", "不想看", "换一个",
        "退钱", "过分了", "变了", "取关", "反转", "买分", "开挂", "作弊", "演员",
        "脚本", "外星人", "开哥", "外挂",
        # 话题争议
        "这也能吵", "迷惑", "离谱", "服了", "无语", "吐槽", "喷子", "键盘侠",
        "节奏大师", "引战", "嘴臭", "口嗨",
        # 带货争议
        "坑", "骗", "假货", "翻车", "投诉", "维权", "质量", "翻车",
    ],
    "teaching": [
        # 游戏教学
        "教学", "思路", "技巧", "细节", "复盘", "为什么", "怎么", "讲解",
        "原理", "学到了", "笔记", "原来如此", "讲师", "DPI", "灵敏度", "垂直",
        "设置", "教程", "入门", "进阶", "必杀", "连招", "出装", "符文", "天赋",
        # 学习知识
        "知识点", "考点", "必考", "重点", "笔记", "抄笔记", "截图", "保存",
        "干货", "硬核", "硬核教学", "良心", "详细", "通俗易懂",
        # 带货讲解
        "科普", "成分", "解析", "测评", "对比", "实验", "验证",
    ],
    "emotion": [
        # 感动类
        "泪目", "感动", "心疼", "难受", "唉", "温暖", "哭", "破防",
        "爷青回", "支撑住", "加油", "这就是爱", "催泪", "看哭", "绷不住",
        "破防了", "眼眶湿", "泪崩", "感动哭了", "太戳了", "戳心",
        # 温暖治愈
        "治愈", "暖", "温馨", "甜", "治愈系", "好暖", "戳中", "心窝",
        "太甜了", "齁甜", "甜哭了", "好磕", "CP感", "配一脸",
        # 共鸣类
        "扎心", "说心声", "代入感", "太真实", "我本人", "破防了", "就是我",
        "说出了心声", "这不就是我", "人间真实", "太懂了",
        # 励志类
        "燃", "热血", "炸", "太强了", "励志", "逆袭", "翻盘", "冲", "干就完了",
    ],
}

SCORE_WEIGHTS = {
    "high_energy": (0.55, 0.30, 0.15),
    "funny": (0.52, 0.30, 0.18),
    "controversy": (0.50, 0.34, 0.16),
    "teaching": (0.42, 0.48, 0.10),
    "emotion": (0.48, 0.37, 0.15),
}

# 当前弹幕录制仅稳定产出 chat/status，gift/like 在大多数场景为空。
# 为避免无效噪声影响热度解释，这里暂时关闭其打分权重；
# 字段仍保留，便于未来恢复礼物/点赞采集后直接启用。
HEAT_GIFT_WEIGHT = 0.0
HEAT_LIKE_WEIGHT = 0.0

# 活动口号/模板刷屏识别参数
SPAM_TEXT_MIN_COUNT = 60
SPAM_TEXT_MIN_RATIO = 0.006
MAX_TOKEN_TRACK = 80

# 时间均衡参数（自适应）
# 基础值：每 GROUP_BALANCE_MINUTES 分钟最多选 GROUP_BALANCE_MAX_PER_GROUP 个
GROUP_BALANCE_MINUTES = 15
GROUP_BALANCE_MAX_PER_GROUP_BASE = 1
MERGE_GAP_SECONDS = 8.0

# 弹幕密度自适应参数
DANMU_DENSITY_THRESHOLD_LOW = 5    # 低密度阈值（条/分钟）
DANMU_DENSITY_THRESHOLD_HIGH = 30   # 高密度阈值（条/分钟）

logger = logging.getLogger(__name__)


@dataclass
class DanmuEvent:
    ts: float
    uid: str
    text: str
    event_type: str


@dataclass
class BucketStat:
    idx: int
    start_ts: float
    end_ts: float
    chat_count: int = 0
    unique_users: int = 0
    gift_count: int = 0
    like_count: int = 0
    heat_score: float = 0.0
    burst_score: float = 0.0
    hint_hits: int = 0
    spam_hits: int = 0
    spam_ratio: float = 0.0
    text_diversity: float = 0.0
    novelty_score: float = 0.0
    score: float = 0.0
    sample_texts: List[str] = None
    token_set: set = None

    def __post_init__(self):
        if self.sample_texts is None:
            self.sample_texts = []
        if self.token_set is None:
            self.token_set = set()


def _extract_text(event: dict) -> str:
    content = event.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        for key in ("text", "content", "message", "msg"):
            val = content.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    for key in ("text", "message", "msg"):
        val = event.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_uid(event: dict) -> str:
    user = event.get("user")
    if isinstance(user, dict):
        for key in ("id", "uid", "sec_uid", "short_id", "nickname"):
            val = user.get(key)
            if val is not None:
                s = str(val).strip()
                if s:
                    return s
    return "anonymous"

def _is_noise(text: str) -> bool:
    """判断是否为极端噪声（如纯符号、空白），这些内容甚至不计入热度。"""
    if not text:
        return True
    for pattern in NOISE_PATTERNS:
        if pattern.match(text):
            return True
    return False


def _is_meaningless(text: str) -> bool:
    """判断是否为无实际含义的弹幕（如重复字符、纯数字等）。"""
    if not text:
        return True
    for pattern in EMOTION_PATTERNS:
        if pattern.match(text):
            return True
    # 长度过短的单字如果不是特殊关键词，通常也意义不大
    if len(text) < 2 and text not in ("牛", "好", "赞", "滚", "强"):
        return True
    return False


def _count_punctuation_burst(texts: List[str]) -> int:
    """统计包含多个问号或感叹号的弹幕数量（爆发性情绪信号）"""
    hit = 0
    if not texts:
        return 0
    for t in texts:
        if not t:
            continue
        # 统计中文或英文的连续问号/感叹号
        if t.count("?") >= 2 or t.count("？") >= 2 or t.count("!") >= 2 or t.count("！") >= 2:
            hit += 1
    return hit


def _count_quality_long_text(texts: List[str]) -> int:
    """统计高质量长文本弹幕（通常包含有效信息而非刷屏）"""
    hit = 0
    if not texts:
        return 0
    for t in texts:
        # 长度超过 15 字，通常意味着有具体的表达
        if len(t) > 15:
            hit += 1
    return hit


def load_danmu_events(danmu_path: str) -> List[DanmuEvent]:
    events: List[DanmuEvent] = []
    with open(danmu_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            ts = obj.get("ts")
            if ts is None:
                continue
            try:
                ts_val = float(ts)
            except Exception:
                continue

            event_type = str(obj.get("event_type") or obj.get("type") or "chat")
            text = _extract_text(obj)
            uid = _extract_uid(obj)

            if event_type == "chat":
                # 只过滤极端噪声（如纯空白或纯符号），保留情绪信号用于热度统计
                if _is_noise(text):
                    continue

            events.append(DanmuEvent(ts=ts_val, uid=uid, text=text, event_type=event_type))

    events.sort(key=lambda x: x.ts)
    return events


def preprocess_events(events: List[DanmuEvent], dedup_window_seconds: int = 8) -> List[DanmuEvent]:
    """简单去重：同 uid 同 text 在短时间窗口内只保留一次（仅对聊天生效）。"""
    if not events:
        return []

    recent_seen: Dict[Tuple[str, str], float] = {}
    cleaned: List[DanmuEvent] = []

    for ev in events:
        if ev.event_type != "chat":
            # 非聊天事件不做去重，保留原始明细（当前默认不参与热度权重）。
            cleaned.append(ev)
            continue

        key = (ev.uid, ev.text)
        prev_ts = recent_seen.get(key)
        if prev_ts is not None and (ev.ts - prev_ts) <= dedup_window_seconds:
            continue
        recent_seen[key] = ev.ts
        cleaned.append(ev)

    return cleaned


def _normalize_for_spam(text: str) -> str:
    if not text:
        return ""
    norm = re.sub(r"\s+", "", str(text).strip().lower())
    # 仅保留中英数，统一口号文案形态
    norm = "".join(ch for ch in norm if ch.isalnum() or (0x4E00 <= ord(ch) <= 0x9FFF))
    return norm[:48]


def _collect_spam_texts(events: List[DanmuEvent]) -> set:
    chat_texts = []
    for ev in events:
        if ev.event_type != "chat":
            continue
        norm = _normalize_for_spam(ev.text)
        if len(norm) < 2:
            continue
        chat_texts.append(norm)

    total = len(chat_texts)
    if total <= 0:
        return set()

    counter = Counter(chat_texts)
    spam_texts = set()
    for text, count in counter.items():
        if count < SPAM_TEXT_MIN_COUNT:
            continue
        if (count / total) < SPAM_TEXT_MIN_RATIO:
            continue
        spam_texts.add(text)
    return spam_texts


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = len(a | b)
    if union <= 0:
        return 0.0
    return len(a & b) / union


def _rebalance_segments_by_time(
    segments: List[dict],
    *,
    group_minutes: int,
    max_per_group_base: int,
    danmu_density: float = 10.0,  # 弹幕密度（条/分钟）
    total_duration_minutes: float = 0.0,  # 直播总时长（分钟）
) -> List[dict]:
    """自适应时间均衡：根据弹幕密度和直播时长动态调整每组最大片段数。"""
    if len(segments) <= 1:
        return segments

    # 动态计算每组最大片段数
    # 低密度直播：减少每组限制，避免选不满
    # 高密度直播：增加每组限制，避免漏掉高光
    density_factor = 1.0
    if danmu_density <= DANMU_DENSITY_THRESHOLD_LOW:
        # 低密度：放宽限制，同时降低时间粒度（更细致地捕获稀薄高光）
        density_factor = 0.5  # 放宽 50%
        effective_group_minutes = max(5, group_minutes // 2)  # 时间窗口缩小一半
    elif danmu_density >= DANMU_DENSITY_THRESHOLD_HIGH:
        # 高密度：收紧限制，避免片段扎堆
        density_factor = 1.5  # 收紧 50%
        effective_group_minutes = group_minutes
    else:
        effective_group_minutes = group_minutes
        density_factor = 1.0

    # 根据直播总时长调整：短直播更宽松，长直播更严格
    duration_factor = 1.0
    if total_duration_minutes > 0:
        if total_duration_minutes <= 30:
            # 短直播（<=30分钟）：放宽限制
            duration_factor = 1.5
        elif total_duration_minutes >= 180:
            # 长直播（>=3小时）：收紧限制，避免候选过多
            duration_factor = 0.7

    max_per_group = max(1, int(max_per_group_base * density_factor * duration_factor))

    group_sec = max(60, int(effective_group_minutes) * 60)
    groups: Dict[int, List[dict]] = defaultdict(list)
    deferred: List[dict] = []

    for seg in segments:
        start_sec = float(seg.get("start_sec") or 0.0)
        gid = int(start_sec // group_sec)
        groups[gid].append(seg)

    # 先选每个组分数最高的片段
    selected: List[dict] = []
    for gid in sorted(groups.keys()):
        group_segs = groups[gid]
        # 按分数降序排序，每组取最多 max_per_group 个
        group_segs.sort(key=lambda x: (x.get("score", 0), x.get("heat_score", 0)), reverse=True)
        selected.extend(group_segs[:max_per_group])
        # 多余的放入待处理池
        if len(group_segs) > max_per_group:
            deferred.extend(group_segs[max_per_group:])

    # 如果选中数量不足，从备用池补充（仍按分数排序）
    if len(selected) < len(segments) and deferred:
        deferred.sort(key=lambda x: (x.get("score", 0), x.get("heat_score", 0)), reverse=True)
        remaining_slots = len(segments) - len(selected)
        if remaining_slots > 0:
            # 计算剩余组数，计算平均每组还能放多少
            all_gids = set(g for g in groups.keys()) | set(g for g in [int(s.get("start_sec", 0) // group_sec) for s in deferred])
            max_extra_per_gid = max(1, (remaining_slots // max(len(all_gids), 1)) // 2)

            # 重新按组分配备用片段
            deferred_groups: Dict[int, List[dict]] = defaultdict(list)
            for seg in deferred:
                gid = int(seg.get("start_sec", 0) // group_sec)
                deferred_groups[gid].append(seg)

            for gid in sorted(deferred_groups.keys()):
                g_deferred = deferred_groups[gid]
                g_deferred.sort(key=lambda x: (x.get("score", 0), x.get("heat_score", 0)), reverse=True)
                extra_count = min(len(g_deferred), max_extra_per_gid)
                selected.extend(g_deferred[:extra_count])

    return selected[:len(segments)]


def _keyword_extract(texts: List[str], top_k: int = 6) -> List[str]:
    words: List[str] = []
    # 增加更多业务无关词
    internal_stop = {"这个", "那个", "就是", "然后", "主播", "真的", "感觉", "看到", "应该"}
    
    for text in texts:
        # 过滤情绪信号和无意义短语
        if _is_meaningless(text):
            continue
            
        # 混合中英分词的轻量方案：中英文/数字串
        for token in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", text.lower()):
            if token in internal_stop:
                continue
            words.append(token)
    if not words:
        return []
    return [w for w, _ in Counter(words).most_common(top_k)]


def _count_hint_hits(texts: List[str], hints: List[str]) -> int:
    if not texts or not hints:
        return 0
    hit = 0
    for text in texts:
        low = text.lower()
        for hint in hints:
            if hint and hint in low:
                hit += 1
    return hit


def _text_diversity(texts: List[str]) -> float:
    if not texts:
        return 0.0
    uniq = len(set(texts))
    return min(1.0, uniq / max(1, len(texts)))


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    rank = max(0.0, min(1.0, p)) * (len(sorted_vals) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = rank - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def build_segments(
    events: List[DanmuEvent],
    *,
    timeline_base_ts: Optional[float],
    highlight_type: str,
    window_seconds: int,
    max_candidates: int,
    danmu_delay_compensation_seconds: int = 0,
    pre_padding_seconds: int,
    post_padding_seconds: int,
    seed: int = -1,
    randomness: int = 0,
) -> List[dict]:
    if not events:
        return []

    # 初始化随机数生成器
    if seed == -1:
        prng = random.Random()
    else:
        # 使用确定的偏移量计算方式（不再用重启会变的 hash()）
        h_offset = sum(ord(c) for c in highlight_type)
        prng = random.Random(seed + h_offset)

    base_ts = float(timeline_base_ts) if timeline_base_ts is not None else events[0].ts
    delay = float(max(0, int(danmu_delay_compensation_seconds or 0)))
    spam_texts = _collect_spam_texts(events)
    bucket_map: Dict[int, BucketStat] = {}
    bucket_users: Dict[int, set] = defaultdict(set)

    for ev in events:
        effective_ts = float(ev.ts) - delay
        idx = int((effective_ts - base_ts) // window_seconds)
        bucket_start = base_ts + idx * window_seconds
        bucket_end = bucket_start + window_seconds
        bucket = bucket_map.get(idx)
        if bucket is None:
            bucket = BucketStat(idx=idx, start_ts=bucket_start, end_ts=bucket_end)
            bucket_map[idx] = bucket

        if ev.event_type == "chat":
            bucket.chat_count += 1
            bucket_users[idx].add(ev.uid)
            if ev.text and len(bucket.sample_texts) < 25:
                bucket.sample_texts.append(ev.text)
            norm = _normalize_for_spam(ev.text)
            if norm and norm in spam_texts:
                bucket.spam_hits += 1
            if ev.text and len(bucket.token_set) < MAX_TOKEN_TRACK:
                for token in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", ev.text.lower()):
                    bucket.token_set.add(token)
        elif ev.event_type == "gift":
            bucket.gift_count += 1
        elif ev.event_type == "like":
            bucket.like_count += 1

    sorted_idx = sorted(bucket_map.keys())
    buckets = [bucket_map[i] for i in sorted_idx]
    hints = [h.lower() for h in HIGHLIGHT_HINTS.get(highlight_type, [])]
    for b in buckets:
        b.unique_users = len(bucket_users.get(b.idx, set()))
        b.hint_hits = _count_hint_hits(b.sample_texts, hints)
        b.text_diversity = _text_diversity(b.sample_texts)
        b.spam_ratio = min(1.0, b.spam_hits / max(1, b.chat_count))
        # [新增] 计算语气爆发点和高质量文本点
        punc_hits = _count_punctuation_burst(b.sample_texts)
        quality_hits = _count_quality_long_text(b.sample_texts)

        user_ratio = b.unique_users / max(1, b.chat_count)
        anti_spam_factor = max(0.55, min(1.15, 0.6 + user_ratio * 0.9))
        # [终极优化] 语义热度 = 基础热度 + 语义能量奖励
        base_heat = b.chat_count + b.unique_users * 1.15
        
        semantic_energy = (
            b.hint_hits * 1.6            # 核心梗/黑话权重
            + punc_hits * 2.0            # 情绪爆发点权重 (???, !!!)
            + quality_hits * 2.2         # 高质量长文本奖励
            + (b.gift_count * 5.0 if HEAT_GIFT_WEIGHT > 0 else 0)
        )

        # [终极优化] 动态噪音惩罚 (技术故障 + 活动乞求/配置咨询)
        # 注意：仅当弹幕中包含这些词且占比高时才惩罚，避免误杀
        # 技术故障类（惩罚力度大）
        tech_keywords = ["卡了", "回声", "没声", "音画", "少人", "暂停", "断了", "掉线", "闪退", "bug"]
        # 设置咨询类（中等惩罚）
        config_keywords = ["dpi", "灵敏度", "找他", "组局", "设置", "键位", "按键", "操作设置", "怎么设置"]
        # 带货咨询类（低惩罚）
        shopping_keywords = ["几号链接", "多少钱", "怎么买", "在哪", "链接", "价格", "优惠", "劵", "券"]
        # 聊天/日常类（非高光噪音）
        daily_keywords = ["早到", "道歉", "迟到", "主播在吗", "有人吗", "打招呼", "签到"]

        noise_hits = sum(1 for t in b.sample_texts if any(w in t.lower() for w in tech_keywords + config_keywords))
        tech_hits = sum(1 for t in b.sample_texts if any(w in t.lower() for w in tech_keywords))
        config_hits = sum(1 for t in b.sample_texts if any(w in t.lower() for w in config_keywords))
        shopping_hits = sum(1 for t in b.sample_texts if any(w in t.lower() for w in shopping_keywords))
        daily_hits = sum(1 for t in b.sample_texts if any(w in t.lower() for w in daily_keywords))

        total_hits = noise_hits + shopping_hits + daily_hits
        noise_ratio = total_hits / max(1, b.chat_count)
        tech_ratio = tech_hits / max(1, b.chat_count)
        config_ratio = config_hits / max(1, b.chat_count)
        shopping_ratio = shopping_hits / max(1, b.chat_count)

        # 综合噪音惩罚：技术问题占主导（0.6系数），配置咨询次之（0.4系数），带货噪音较低（0.25系数）
        noise_penalty = max(0.45, 1.0 - tech_ratio * 0.6 - config_ratio * 0.4 - shopping_ratio * 0.25)

        # 针对开播前几分钟的强力压制，仅在噪音比例确实很高时触发
        if b.idx < 6 and noise_ratio > 0.5 and tech_ratio > 0.35:
            noise_penalty *= 0.7

        spam_penalty = max(0.6, 1.0 - b.spam_ratio * 0.6)
        # 终极热度得分 = (基础 + 能量) * 用户真实度因子 * 垃圾过滤因子 * 噪音压制因子
        b.heat_score = (base_heat + semantic_energy) * anti_spam_factor * spam_penalty * noise_penalty

    for i, b in enumerate(buckets):
        prev_heat = buckets[i - 1].heat_score if i > 0 else b.heat_score
        next_heat = buckets[i + 1].heat_score if i < len(buckets) - 1 else b.heat_score
        local_base = max(1.0, (prev_heat + next_heat) / 2.0)
        b.burst_score = max(0.0, (b.heat_score - local_base) / local_base)
        prev_tokens = buckets[i - 1].token_set if i > 0 else set()
        next_tokens = buckets[i + 1].token_set if i < len(buckets) - 1 else set()
        b.novelty_score = max(0.0, 1.0 - ((_jaccard(b.token_set, prev_tokens) + _jaccard(b.token_set, next_tokens)) / 2.0))

    if not buckets:
        return []

    heat_values = [b.heat_score for b in buckets]
    avg = sum(heat_values) / len(heat_values)
    variance = sum((x - avg) ** 2 for x in heat_values) / max(1, len(heat_values))
    std = math.sqrt(variance)
    p75 = _percentile(sorted(heat_values), 0.75)
    threshold = max(avg + std * 0.9, p75 * 0.95, 4.0)

    # 开启随机性时，动态放宽入门门票，让候选池变大
    if randomness > 0:
        threshold *= (1.0 - (randomness / 100.0) * 0.5)

    candidate_buckets = [b for b in buckets if b.heat_score >= threshold]
    candidate_buckets.extend(
        [
            b
            for b in buckets
            if b.burst_score >= 0.45 and b.chat_count >= 3 and b not in candidate_buckets
        ]
    )
    if not candidate_buckets:
        candidate_buckets = sorted(buckets, key=lambda x: x.heat_score, reverse=True)[:max(1, min(3, len(buckets)))]

    # 候选池适度放大，再做最终排序与均衡抽样，避免结果扎堆
    candidate_pool_limit = max(max_candidates, min(len(buckets), max_candidates * 4))
    
    # 注入“强力”随机性：对热度分进行基于全局最大热度的扰动排序
    max_h = max(heat_values) if heat_values else 1.0
    def get_sort_score(bucket: BucketStat) -> float:
        score = bucket.heat_score
        if randomness > 0:
            # 扰动范围基于全局最高分和随机强度
            disturb = (prng.random() - 0.5) * 2 * (randomness / 100.0) * max_h
            score += disturb
        return score

    candidate_buckets = sorted(candidate_buckets, key=get_sort_score, reverse=True)[:candidate_pool_limit]

    # 生成候选片段并合并重叠
    raw_segments = []
    for b in candidate_buckets:
        # 时间抖动：单片段长短和位置的微调
        start_jitter = 0
        end_jitter = 0
        if randomness > 0:
            # 加强抖动感，最大抖动 +/- 12秒
            max_j = (randomness / 100.0) * 12.0
            start_jitter = (prng.random() - 0.5) * 2 * max_j
            end_jitter = (prng.random() - 0.5) * 2 * max_j

        start_ts = max(base_ts, b.start_ts - pre_padding_seconds + start_jitter)
        end_ts = b.end_ts + post_padding_seconds + end_jitter
        raw_segments.append((start_ts, end_ts, b))

    raw_segments.sort(key=lambda x: x[0])
    merged = []
    for seg in raw_segments:
        if not merged:
            merged.append(seg)
            continue
        last_start, last_end, last_bucket = merged[-1]
        cur_start, cur_end, cur_bucket = seg
        if cur_start <= (last_end + MERGE_GAP_SECONDS):
            # 重叠或间隔较小就合并，保留热度更高的 bucket 作为主描述
            merged_bucket = last_bucket if last_bucket.heat_score >= cur_bucket.heat_score else cur_bucket
            merged[-1] = (last_start, max(last_end, cur_end), merged_bucket)
        else:
            merged.append(seg)

    result = []
    for start_ts, end_ts, bucket in merged:
        duration = max(0.0, end_ts - start_ts)
        if duration < 12:
            continue
        if duration > 150:
            end_ts = start_ts + 150
            duration = 150

        keywords = _keyword_extract(bucket.sample_texts)
        title_prefix = {
            "high_energy": "高能时刻",
            "funny": "搞笑片段",
            "controversy": "争议片段",
            "teaching": "教学重点",
            "emotion": "情绪高潮",
        }.get(highlight_type, "高光片段")

        summary = (
            f"该片段弹幕热度显著上升，聊天 {bucket.chat_count} 条，"
            f"活跃用户 {bucket.unique_users} 人。"
        )
        if keywords:
            summary += f" 关键词：{', '.join(keywords[:4])}。"

        heat_score = float(bucket.heat_score)
        keyword_richness = min(1.0, len(keywords) / 6.0)
        hint_component = min(1.0, bucket.hint_hits / 4.0)
        semantic_score = min(
            1.0,
            max(
                0.2,
                0.22
                + keyword_richness * 0.30
                + bucket.text_diversity * 0.18
                + hint_component * 0.18
                + bucket.novelty_score * 0.22,
            ),
        )
        heat_norm = min(1.0, heat_score / max(threshold * 1.4, 1.0))
        burst_norm = min(1.0, bucket.burst_score / 1.2)
        w_heat, w_sem, w_burst = SCORE_WEIGHTS.get(highlight_type, (0.55, 0.30, 0.15))
        total_score = min(1.0, heat_norm * w_heat + semantic_score * w_sem + burst_norm * w_burst)

        result.append({
            "id": str(uuid.uuid4()),
            "start_sec": round(start_ts - base_ts, 3),
            "end_sec": round(end_ts - base_ts, 3),
            "duration_sec": round(duration, 3),
            "score": round(total_score, 4),
            "heat_score": round(heat_score, 4),
            "burst_score": round(float(bucket.burst_score), 4),
            "semantic_score": round(semantic_score, 4),
            "highlight_type": highlight_type,
            "title": f"{title_prefix} · {int(start_ts - base_ts)}s",
            "summary": summary,
            "keywords": keywords,
            "chat_count": bucket.chat_count,
            "unique_users": bucket.unique_users,
            "gift_count": bucket.gift_count,
            "like_count": bucket.like_count,
            "clip_path": None,
        })

    result.sort(key=lambda x: (x["score"], x["heat_score"]), reverse=True)

    # 计算弹幕密度和直播总时长，用于自适应时间均衡
    total_duration_sec = events[-1].ts - events[0].ts if len(events) > 1 else 0
    total_duration_minutes = total_duration_sec / 60.0 if total_duration_sec > 0 else 0.0
    total_danmu_count = sum(b.chat_count for b in buckets)
    danmu_density = total_danmu_count / total_duration_minutes if total_duration_minutes > 0 else 0.0

    # 自适应时间窗口：根据直播时长和目标候选数动态调整
    adaptive_minutes = max(5, min(30, total_duration_minutes / max(1, max_candidates * 3)))
    rebalanced = _rebalance_segments_by_time(
        result,
        group_minutes=adaptive_minutes,
        max_per_group_base=GROUP_BALANCE_MAX_PER_GROUP_BASE,
        danmu_density=danmu_density,
        total_duration_minutes=total_duration_minutes,
    )
    return rebalanced[:max_candidates]


def _iter_danmu_events_stream(danmu_path: str):
    """按行流式读取弹幕事件，避免一次性加载整文件。"""
    with open(danmu_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            ts = obj.get("ts")
            if ts is None:
                continue
            try:
                ts_val = float(ts)
            except Exception:
                continue

            event_type = str(obj.get("event_type") or obj.get("type") or "chat")
            text = _extract_text(obj)
            uid = _extract_uid(obj)

            if event_type == "chat" and _is_noise(text):
                continue

            yield DanmuEvent(ts=ts_val, uid=uid, text=text, event_type=event_type)


def _iter_danmu_events_stream_ordered(
    danmu_path: str,
    *,
    reorder_window_seconds: float = 2.0,
    max_buffer_size: int = 400,
    emit_ordering_stats: bool = False,
):
    """在小窗口内重排乱序弹幕，降低时序抖动对分桶/采样的影响。"""
    heap: List[Tuple[float, int, DanmuEvent]] = []
    seq = 0
    max_seen_ts: Optional[float] = None
    out_of_order_count = 0
    severe_out_of_order_count = 0
    max_backtrack_seconds = 0.0

    for ev in _iter_danmu_events_stream(danmu_path):
        ts_val = float(ev.ts)
        if max_seen_ts is not None and ts_val + 1e-6 < max_seen_ts:
            out_of_order_count += 1
            backtrack = max_seen_ts - ts_val
            if backtrack > max_backtrack_seconds:
                max_backtrack_seconds = backtrack
            if backtrack > reorder_window_seconds:
                severe_out_of_order_count += 1
        max_seen_ts = ts_val if max_seen_ts is None else max(max_seen_ts, ts_val)

        heapq.heappush(heap, (ts_val, seq, ev))
        seq += 1

        watermark = max_seen_ts - reorder_window_seconds
        while heap and (heap[0][0] <= watermark or len(heap) > max_buffer_size):
            yield heapq.heappop(heap)[2]

    while heap:
        yield heapq.heappop(heap)[2]

    if emit_ordering_stats and out_of_order_count > 0:
        log_fn = logger.warning if severe_out_of_order_count > 0 else logger.info
        log_fn(
            "danmu.stream.out_of_order file=%s count=%s severe=%s max_backtrack_sec=%.3f reorder_window_sec=%.1f",
            danmu_path,
            out_of_order_count,
            severe_out_of_order_count,
            max_backtrack_seconds,
            reorder_window_seconds,
        )


def iter_danmu_events_stream(danmu_path: str):
    """导出给路由层的流式事件迭代器。"""
    return _iter_danmu_events_stream_ordered(danmu_path)


def probe_first_event_ts(danmu_path: str) -> Optional[float]:
    for ev in _iter_danmu_events_stream_ordered(danmu_path):
        return float(ev.ts)
    return None


def _iter_preprocessed_danmu_events_stream(danmu_path: str, dedup_window_seconds: int = 8):
    """流式去重：同 uid 同 text 在短窗口内仅保留一次。"""
    recent_seen: Dict[Tuple[str, str], float] = {}
    for ev in _iter_danmu_events_stream_ordered(danmu_path):
        if ev.event_type != "chat":
            yield ev
            continue
        key = (ev.uid, ev.text)
        prev_ts = recent_seen.get(key)
        if prev_ts is not None and (ev.ts - prev_ts) <= dedup_window_seconds:
            continue
        recent_seen[key] = ev.ts
        yield ev


def _scan_stream_for_spam_and_counts(danmu_path: str, dedup_window_seconds: int = 8) -> Dict[str, object]:
    """首轮流式扫描：统计 raw/cleaned 数量 + 全局刷屏文本。"""
    raw_count = 0
    cleaned_count = 0
    first_ts: Optional[float] = None
    spam_total = 0
    counter: Counter = Counter()
    recent_seen: Dict[Tuple[str, str], float] = {}

    for ev in _iter_danmu_events_stream_ordered(danmu_path, emit_ordering_stats=True):
        raw_count += 1
        if first_ts is None:
            first_ts = float(ev.ts)

        if ev.event_type == "chat":
            key = (ev.uid, ev.text)
            prev_ts = recent_seen.get(key)
            if prev_ts is not None and (ev.ts - prev_ts) <= dedup_window_seconds:
                continue
            recent_seen[key] = ev.ts

        cleaned_count += 1
        if ev.event_type != "chat":
            continue
        norm = _normalize_for_spam(ev.text)
        if len(norm) < 2:
            continue
        counter[norm] += 1
        spam_total += 1

        # 避免极端场景下 Counter 无限膨胀（轻量淘汰一次性噪声）。
        if len(counter) > 300000 and (cleaned_count % 50000 == 0):
            for k, v in list(counter.items()):
                if v <= 1:
                    counter.pop(k, None)

    spam_texts = set()
    if spam_total > 0:
        for text, count in counter.items():
            if count < SPAM_TEXT_MIN_COUNT:
                continue
            if (count / spam_total) < SPAM_TEXT_MIN_RATIO:
                continue
            spam_texts.add(text)

    return {
        "raw_events": int(raw_count),
        "cleaned_events": int(cleaned_count),
        "first_ts": first_ts,
        "spam_texts": spam_texts,
    }


def build_segments_from_danmu_file(
    danmu_path: str,
    *,
    timeline_base_ts: Optional[float],
    highlight_type: str,
    window_seconds: int,
    max_candidates: int,
    danmu_delay_compensation_seconds: int = 0,
    pre_padding_seconds: int,
    post_padding_seconds: int,
    seed: int = -1,
    randomness: int = 0,
    dedup_window_seconds: int = 8,
    ai_decision_mode: bool = False,
) -> Dict[str, object]:
    """全链路流式版候选生成：不保留全量事件列表。"""
    scan = _scan_stream_for_spam_and_counts(danmu_path, dedup_window_seconds=dedup_window_seconds)
    spam_texts = scan.get("spam_texts") or set()
    first_ts = scan.get("first_ts")
    if first_ts is None and timeline_base_ts is None:
        return {
            "segments": [],
            "raw_events": int(scan.get("raw_events") or 0),
            "cleaned_events": int(scan.get("cleaned_events") or 0),
        }

    # 初始化随机数生成器
    if seed == -1:
        prng = random.Random()
    else:
        h_offset = sum(ord(c) for c in highlight_type)
        prng = random.Random(seed + h_offset)

    base_ts = float(timeline_base_ts) if timeline_base_ts is not None else float(first_ts)
    delay = float(max(0, int(danmu_delay_compensation_seconds or 0)))
    bucket_map: Dict[int, BucketStat] = {}
    bucket_users: Dict[int, set] = defaultdict(set)

    for ev in _iter_preprocessed_danmu_events_stream(danmu_path, dedup_window_seconds=dedup_window_seconds):
        effective_ts = float(ev.ts) - delay
        idx = int((effective_ts - base_ts) // window_seconds)
        bucket_start = base_ts + idx * window_seconds
        bucket_end = bucket_start + window_seconds
        bucket = bucket_map.get(idx)
        if bucket is None:
            bucket = BucketStat(idx=idx, start_ts=bucket_start, end_ts=bucket_end)
            bucket_map[idx] = bucket

        if ev.event_type == "chat":
            bucket.chat_count += 1
            bucket_users[idx].add(ev.uid)
            if ev.text and len(bucket.sample_texts) < 25:
                bucket.sample_texts.append(ev.text)
            norm = _normalize_for_spam(ev.text)
            if norm and norm in spam_texts:
                bucket.spam_hits += 1
            if ev.text and len(bucket.token_set) < MAX_TOKEN_TRACK:
                for token in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", ev.text.lower()):
                    bucket.token_set.add(token)
        elif ev.event_type == "gift":
            bucket.gift_count += 1
        elif ev.event_type == "like":
            bucket.like_count += 1

    sorted_idx = sorted(bucket_map.keys())
    buckets = [bucket_map[i] for i in sorted_idx]
    hints = [h.lower() for h in HIGHLIGHT_HINTS.get(highlight_type, [])]
    for b in buckets:
        b.unique_users = len(bucket_users.get(b.idx, set()))
        b.hint_hits = _count_hint_hits(b.sample_texts, hints)
        b.text_diversity = _text_diversity(b.sample_texts)
        b.spam_ratio = min(1.0, b.spam_hits / max(1, b.chat_count))
        # [新增] 计算语气爆发点和高质量文本点
        punc_hits = _count_punctuation_burst(b.sample_texts)
        quality_hits = _count_quality_long_text(b.sample_texts)

        user_ratio = b.unique_users / max(1, b.chat_count)
        anti_spam_factor = max(0.55, min(1.15, 0.6 + user_ratio * 0.9))
        # [终极优化] 语义热度 = 基础热度 + 语义能量奖励
        base_heat = b.chat_count + b.unique_users * 1.15
        
        semantic_energy = (
            b.hint_hits * 1.6            # 核心梗/黑话权重
            + punc_hits * 2.0            # 情绪爆发点权重 (???, !!!)
            + quality_hits * 2.2         # 高质量长文本奖励
            + (b.gift_count * 5.0 if HEAT_GIFT_WEIGHT > 0 else 0)
        )

        # [终极优化] 动态噪音惩罚 (技术故障 + 活动乞求/配置咨询)
        # 注意：仅当弹幕中包含这些词且占比高时才惩罚，避免误杀
        # 技术故障类（惩罚力度大）
        tech_keywords = ["卡了", "回声", "没声", "音画", "少人", "暂停", "断了", "掉线", "闪退", "bug"]
        # 设置咨询类（中等惩罚）
        config_keywords = ["dpi", "灵敏度", "找他", "组局", "设置", "键位", "按键", "操作设置", "怎么设置"]
        # 带货咨询类（低惩罚）
        shopping_keywords = ["几号链接", "多少钱", "怎么买", "在哪", "链接", "价格", "优惠", "劵", "券"]
        # 聊天/日常类（非高光噪音）
        daily_keywords = ["早到", "道歉", "迟到", "主播在吗", "有人吗", "打招呼", "签到"]

        noise_hits = sum(1 for t in b.sample_texts if any(w in t.lower() for w in tech_keywords + config_keywords))
        tech_hits = sum(1 for t in b.sample_texts if any(w in t.lower() for w in tech_keywords))
        config_hits = sum(1 for t in b.sample_texts if any(w in t.lower() for w in config_keywords))
        shopping_hits = sum(1 for t in b.sample_texts if any(w in t.lower() for w in shopping_keywords))
        daily_hits = sum(1 for t in b.sample_texts if any(w in t.lower() for w in daily_keywords))

        total_hits = noise_hits + shopping_hits + daily_hits
        noise_ratio = total_hits / max(1, b.chat_count)
        tech_ratio = tech_hits / max(1, b.chat_count)
        config_ratio = config_hits / max(1, b.chat_count)
        shopping_ratio = shopping_hits / max(1, b.chat_count)

        # 综合噪音惩罚：技术问题占主导（0.6系数），配置咨询次之（0.4系数），带货噪音较低（0.25系数）
        noise_penalty = max(0.45, 1.0 - tech_ratio * 0.6 - config_ratio * 0.4 - shopping_ratio * 0.25)

        # 针对开播前几分钟的强力压制，仅在噪音比例确实很高时触发
        if b.idx < 6 and noise_ratio > 0.5 and tech_ratio > 0.35:
            noise_penalty *= 0.7

        spam_penalty = max(0.6, 1.0 - b.spam_ratio * 0.6)
        # 终极热度得分 = (基础 + 能量) * 用户真实度因子 * 垃圾过滤因子 * 噪音压制因子
        b.heat_score = (base_heat + semantic_energy) * anti_spam_factor * spam_penalty * noise_penalty

    for i, b in enumerate(buckets):
        prev_heat = buckets[i - 1].heat_score if i > 0 else b.heat_score
        next_heat = buckets[i + 1].heat_score if i < len(buckets) - 1 else b.heat_score
        local_base = max(1.0, (prev_heat + next_heat) / 2.0)
        b.burst_score = max(0.0, (b.heat_score - local_base) / local_base)
        prev_tokens = buckets[i - 1].token_set if i > 0 else set()
        next_tokens = buckets[i + 1].token_set if i < len(buckets) - 1 else set()
        b.novelty_score = max(0.0, 1.0 - ((_jaccard(b.token_set, prev_tokens) + _jaccard(b.token_set, next_tokens)) / 2.0))

    if not buckets:
        return {
            "segments": [],
            "raw_events": int(scan.get("raw_events") or 0),
            "cleaned_events": int(scan.get("cleaned_events") or 0),
        }

    heat_values = [b.heat_score for b in buckets]
    avg = sum(heat_values) / len(heat_values)
    variance = sum((x - avg) ** 2 for x in heat_values) / max(1, len(heat_values))
    std = math.sqrt(variance)
    p75 = _percentile(sorted(heat_values), 0.75)
    threshold = max(avg + std * 0.9, p75 * 0.95, 4.0)
    if randomness > 0:
        threshold *= (1.0 - (randomness / 100.0) * 0.5)

    if ai_decision_mode:
        # AI 主导决策模式：规则层仅做轻量召回，不在这里强阈值淘汰。
        candidate_buckets = [b for b in buckets if b.chat_count >= 2]
        if not candidate_buckets:
            candidate_buckets = [b for b in buckets if b.chat_count >= 1]
    else:
        candidate_buckets = [b for b in buckets if b.heat_score >= threshold]
        candidate_buckets.extend(
            [
                b
                for b in buckets
                if b.burst_score >= 0.45 and b.chat_count >= 3 and b not in candidate_buckets
            ]
        )
        if not candidate_buckets:
            candidate_buckets = sorted(buckets, key=lambda x: x.heat_score, reverse=True)[:max(1, min(3, len(buckets)))]

    candidate_pool_limit = max(max_candidates, min(len(buckets), max_candidates * 4))
    max_h = max(heat_values) if heat_values else 1.0

    def get_sort_score(bucket: BucketStat) -> float:
        score = bucket.heat_score
        if randomness > 0:
            disturb = (prng.random() - 0.5) * 2 * (randomness / 100.0) * max_h
            score += disturb
        return score

    candidate_buckets = sorted(candidate_buckets, key=get_sort_score, reverse=True)[:candidate_pool_limit]

    raw_segments = []
    for b in candidate_buckets:
        start_jitter = 0.0
        end_jitter = 0.0
        if randomness > 0:
            max_j = (randomness / 100.0) * 12.0
            start_jitter = (prng.random() - 0.5) * 2 * max_j
            end_jitter = (prng.random() - 0.5) * 2 * max_j
        start_ts = max(base_ts, b.start_ts - pre_padding_seconds + start_jitter)
        end_ts = b.end_ts + post_padding_seconds + end_jitter
        raw_segments.append((start_ts, end_ts, b))

    raw_segments.sort(key=lambda x: x[0])
    merged = []
    # 粘性合并阈值：间隔较小的相邻候选视为同一段内容延续，避免高光被切碎。
    for seg in raw_segments:
        if not merged:
            merged.append(seg)
            continue
        last_start, last_end, last_bucket = merged[-1]
        cur_start, cur_end, cur_bucket = seg
        
        if cur_start <= (last_end + MERGE_GAP_SECONDS):
            # 保留热度更高的一方的 Bucket 信息作为主要参考
            merged_bucket = last_bucket if last_bucket.heat_score >= cur_bucket.heat_score else cur_bucket
            merged[-1] = (last_start, max(last_end, cur_end), merged_bucket)
        else:
            merged.append(seg)

    result = []
    for start_ts, end_ts, bucket in merged:
        duration = max(0.0, end_ts - start_ts)
        if duration < 12:
            continue
        if duration > 150:
            end_ts = start_ts + 150
            duration = 150

        keywords = _keyword_extract(bucket.sample_texts)
        title_prefix = {
            "high_energy": "高能时刻",
            "funny": "搞笑片段",
            "controversy": "争议片段",
            "teaching": "教学重点",
            "emotion": "情绪高潮",
        }.get(highlight_type, "高光片段")

        summary = (
            f"该片段弹幕热度显著上升，聊天 {bucket.chat_count} 条，"
            f"活跃用户 {bucket.unique_users} 人。"
        )
        if keywords:
            summary += f" 关键词：{', '.join(keywords[:4])}。"

        heat_score = float(bucket.heat_score)
        keyword_richness = min(1.0, len(keywords) / 6.0)
        hint_component = min(1.0, bucket.hint_hits / 4.0)
        semantic_score = min(
            1.0,
            max(
                0.2,
                0.22
                + keyword_richness * 0.30
                + bucket.text_diversity * 0.18
                + hint_component * 0.18
                + bucket.novelty_score * 0.22,
            ),
        )
        heat_norm = min(1.0, heat_score / max(threshold * 1.4, 1.0))
        burst_norm = min(1.0, bucket.burst_score / 1.2)
        w_heat, w_sem, w_burst = SCORE_WEIGHTS.get(highlight_type, (0.55, 0.30, 0.15))
        total_score = min(1.0, heat_norm * w_heat + semantic_score * w_sem + burst_norm * w_burst)

        result.append({
            "id": str(uuid.uuid4()),
            "start_sec": round(start_ts - base_ts, 3),
            "end_sec": round(end_ts - base_ts, 3),
            "duration_sec": round(duration, 3),
            "score": round(total_score, 4),
            "heat_score": round(heat_score, 4),
            "burst_score": round(float(bucket.burst_score), 4),
            "semantic_score": round(semantic_score, 4),
            "highlight_type": highlight_type,
            "title": f"{title_prefix} · {int(start_ts - base_ts)}s",
            "summary": summary,
            "keywords": keywords,
            "chat_count": bucket.chat_count,
            "unique_users": bucket.unique_users,
            "gift_count": bucket.gift_count,
            "like_count": bucket.like_count,
            "clip_path": None,
        })

    result.sort(key=lambda x: (x["score"], x["heat_score"]), reverse=True)

    # 计算弹幕密度和直播总时长，用于自适应时间均衡
    bucket_times = [(b.start_ts, b.end_ts) for b in buckets]
    total_duration_sec = max(b.end_ts for b in buckets) - min(b.start_ts for b in buckets) if buckets else 0
    total_duration_minutes = total_duration_sec / 60.0 if total_duration_sec > 0 else 0.0
    total_danmu_count = sum(b.chat_count for b in buckets)
    danmu_density = total_danmu_count / total_duration_minutes if total_duration_minutes > 0 else 0.0

    # 自适应时间窗口：根据直播时长和目标候选数动态调整
    adaptive_minutes = max(5, min(30, total_duration_minutes / max(1, max_candidates * 3)))
    rebalanced = _rebalance_segments_by_time(
        result,
        group_minutes=adaptive_minutes,
        max_per_group_base=GROUP_BALANCE_MAX_PER_GROUP_BASE,
        danmu_density=danmu_density,
        total_duration_minutes=total_duration_minutes,
    )

    return {
        "segments": rebalanced[:max_candidates],
        "raw_events": int(scan.get("raw_events") or 0),
        "cleaned_events": int(scan.get("cleaned_events") or 0),
    }


def collect_segment_comments_from_danmu_file(
    danmu_path: str,
    *,
    segments: List[dict],
    timeline_base_ts: Optional[float],
    danmu_delay_compensation_seconds: int = 0,
    dedup_window_seconds: int = 8,
    max_comments_per_segment: int = 240,
    progress_hook: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, List[str]]:
    """流式采样各片段评论，用于 LLM 增强。"""
    if not segments:
        return {}

    base_ts = float(timeline_base_ts) if timeline_base_ts is not None else probe_first_event_ts(danmu_path)
    if base_ts is None:
        return {str(seg.get("id") or ""): [] for seg in segments}

    windows = []
    for seg in segments:
        seg_id = str(seg.get("id") or "")
        if not seg_id:
            continue
        start_sec = float(seg.get("start_sec") or 0.0)
        end_sec = float(seg.get("end_sec") or 0.0)
        if end_sec < start_sec:
            start_sec, end_sec = end_sec, start_sec
        windows.append({
            "segment_id": seg_id,
            "abs_start": base_ts + start_sec,
            "abs_end": base_ts + end_sec,
        })
    windows.sort(key=lambda x: x["abs_start"])

    if not windows:
        return {}

    total_windows = len(windows)
    holder: Dict[str, Dict[str, object]] = {
        w["segment_id"]: {"comments": [], "seen": set()}
        for w in windows
    }
    delay = float(max(0, int(danmu_delay_compensation_seconds or 0)))
    active: List[int] = []
    ptr = 0
    completed_ids: set[str] = set()

    def _report_progress() -> None:
        if not progress_hook:
            return
        progress_hook(len(completed_ids), total_windows, "弹幕采样")

    _report_progress()

    for ev in _iter_preprocessed_danmu_events_stream(danmu_path, dedup_window_seconds=dedup_window_seconds):
        if ev.event_type != "chat":
            continue
        ts = float(ev.ts)
        effective_ts = ts - delay

        while ptr < len(windows) and windows[ptr]["abs_start"] <= effective_ts:
            active.append(ptr)
            ptr += 1

        if not active:
            continue

        text = re.sub(r"\s+", " ", str(ev.text or "").strip())[:56].strip()
        if not text:
            continue

        next_active: List[int] = []
        for idx in active:
            w = windows[idx]
            if effective_ts > w["abs_end"]:
                completed_ids.add(str(w["segment_id"]))
                continue
            next_active.append(idx)
            if effective_ts < w["abs_start"]:
                continue
            slot = holder[w["segment_id"]]
            comments = slot["comments"]
            if len(comments) >= max_comments_per_segment:
                continue
            seen = slot["seen"]
            if text in seen:
                continue
            seen.add(text)
            comments.append(text)
        active = next_active
        _report_progress()

        if ptr >= len(windows) and not active:
            break

    for w in windows:
        completed_ids.add(str(w["segment_id"]))
    _report_progress()

    return {
        seg_id: list(payload.get("comments") or [])
        for seg_id, payload in holder.items()
    }
