# -*- coding: utf-8 -*-
"""AI 高光分析提示词模板。"""

from typing import List, Optional


def build_highlight_system_prompt() -> str:
    return (
        "你是短视频高光编辑助手。"
        "必须且只能输出一个合法的 JSON 对象，格式为 "
        '{"title":"", "summary":"", "keywords":["","",""], "story_text":"", '
        '"scene_type":"high_energy|funny|controversy|teaching|emotion", '
        '"is_highlight":true, "confidence":0.0, '
        '"negative_reason":"none|tech_issue|shopping_query|greeting|spam|off_topic|low_signal", '
        '"start_shift_sec":0, "end_shift_sec":0}。'
        "严禁输出任何 <think> 标签、分析过程、Markdown 代码块或解释性文字。"
        "字段约束：title 不超过 32 个中文字符；summary 不超过 90 个中文字符；"
        "keywords 为 3~6 个短词；story_text 不超过 80 个中文字符，且为 1~2 句。"
        "scene_type 必须是给定枚举之一；is_highlight 为布尔值；"
        "confidence 为 0~1 浮点数；negative_reason 在真高光时必须为 none，非高光时选择最主要原因；"
        "start_shift_sec 为 -8~8，end_shift_sec 为 -12~8 的整数。"
        "is_highlight 与 confidence 会直接参与候选排序，请按真实高光程度返回。"
        "请输出单行 JSON，避免被截断。"
    )


def build_l1_scout_system_prompt() -> str:
    return (
        "你是高光片段初筛侦察兵。"
        "必须且只能输出一个合法的 JSON 对象，格式为 "
        '{"score":0.0,"reason":"","is_high_energy":false}。'
        "严禁输出任何 <think> 标签、分析过程、Markdown 代码块或解释性文字。"
        "字段约束：score 为 0~1 浮点数；reason 不超过 60 个中文字符；is_high_energy 为布尔值。"
        "请输出单行 JSON，避免被截断。"
    )


def build_highlight_user_prompt(
    *,
    highlight_type: str,
    stream_type: Optional[str],
    title: str,
    summary: str,
    comments: List[str],
    story_enabled: bool,
    speech_text: Optional[str] = None,
) -> str:
    task_line = (
        "请返回更好的标题与摘要，并给出 3~6 个关键词。"
        if not story_enabled
        else "请返回更好的标题与摘要，并给出 3~6 个关键词。同时给出可直接上屏的剧情文案（1-2句）。"
    )
    return (
        f"高光类型: {highlight_type}\n"
        + (f"直播类型: {stream_type}\n" if (stream_type or "").strip() else "")
        + f"原始标题: {title}\n"
        + f"原始摘要: {summary}\n"
        + (f"主播语音转写:\n{speech_text}\n" if (speech_text or "").strip() else "")
        + "请结合弹幕语义判断该片段是否真高光，并给出场景类型复核结果。\n"
        + "is_highlight 与 confidence 会直接影响最终候选排序，请谨慎给分。\n"
        + "如果不是高光，请给出 negative_reason：tech_issue=卡顿没声等技术问题；shopping_query=价格链接库存咨询；"
        + "greeting=开播问候签到；spam=活动口号/复读刷屏；off_topic=跑题闲聊；low_signal=信息不足。\n"
        + "时间点仅允许微调，start_shift_sec 范围 -8 到 8 秒，end_shift_sec 范围 -12 到 8 秒。\n"
        + f"弹幕样本(共{len(comments)}条):\n- "
        + "\n- ".join(comments)
        + "\n\n"
        + task_line
        + "\n请仅输出单行 JSON 对象，不要输出任何解释文字。"
    )
