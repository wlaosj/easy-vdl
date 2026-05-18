# -*- coding: utf-8 -*-
"""高光分析 LLM 预设配置。"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class LLMPreset:
    name: str
    base_url: str
    default_model: str
    api_key_hint: str = ""


LLM_PRESETS: List[LLMPreset] = [
    LLMPreset(
        name="MiniMax",
        base_url="https://api.minimaxi.com/v1",
        default_model="MiniMax-Text-01",
        api_key_hint="https://platform.minimaxi.com/user-center/basic-information/interface-key",
    ),
    LLMPreset(name="OpenAI", base_url="https://api.openai.com/v1", default_model="gpt-4o-mini"),
    LLMPreset(name="Qwen", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", default_model="qwen-max"),
    LLMPreset(name="DeepSeek", base_url="https://api.deepseek.com", default_model="deepseek-chat"),
    LLMPreset(name="Moonshot", base_url="https://api.moonshot.cn/v1", default_model="moonshot-v1-8k"),
    LLMPreset(name="SiliconFlow", base_url="https://api.siliconflow.cn/v1", default_model="Qwen/Qwen2.5-7B-Instruct"),
    LLMPreset(name="OpenRouter", base_url="https://openrouter.ai/api/v1", default_model="openai/gpt-4o-mini"),
    LLMPreset(name="Zhipu", base_url="https://open.bigmodel.cn/api/paas/v4", default_model="glm-4-flash"),
    LLMPreset(name="Doubao", base_url="https://ark.cn-beijing.volces.com/api/v3", default_model="doubao-seed-1-6-250615"),
    LLMPreset(name="Hunyuan", base_url="https://api.hunyuan.cloud.tencent.com/v1", default_model="hunyuan-lite"),
    LLMPreset(name="Qianfan", base_url="https://qianfan.baidubce.com/v2", default_model="ernie-4.0-turbo-8k"),
    LLMPreset(name="Ollama", base_url="http://127.0.0.1:11434/v1", default_model="qwen2.5:7b"),
]


def get_preset(name: str) -> Optional[LLMPreset]:
    target = str(name or "").strip().lower()
    for item in LLM_PRESETS:
        if item.name.lower() == target:
            return item
    return None


def get_preset_dict(name: str) -> Dict[str, str]:
    preset = get_preset(name)
    if not preset:
        return {}
    return {
        "name": preset.name,
        "base_url": preset.base_url,
        "default_model": preset.default_model,
        "api_key_hint": preset.api_key_hint,
    }
