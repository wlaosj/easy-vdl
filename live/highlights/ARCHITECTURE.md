# AI 高光切片架构说明

本文档描述 `live/highlights` 当前切片链路、核心数据流、配置优先级与扩展约定。

## 1. 端到端流程

1. 前端提交 `AnalyzeRequest` 到 `router.py`。
2. `router._normalize_analyze_request` 规范化参数（`model_source/analysis_strategy/stream_type`）。
3. `router._analyze_and_save` 作为编排器执行离线分析主流程：
   - 检查录播文件与弹幕文件存在性。
   - `_build_rule_candidates`：`pipeline.build_segments_from_danmu_file` 生成规则候选片段。
   - `_run_llm_enhancement_pipeline`：可选执行 `L1` 与 `L2`。
   - `_save_analysis_outputs`：生成分段弹幕快照并保存分析结果。
4. 异步任务状态通过 websocket 广播，落盘到 `task_status.v1.json`。
5. 结果可进一步导出切片、剧情素材、资源包。

## 2. 模块职责边界

- `router.py`
  - 负责 API 协议、任务生命周期、状态广播、结果落盘编排。
  - 内部流程拆分为候选生成、LLM 增强、结果落盘三个阶段函数，便于扩展和测试。
  - 不承担模型细节与算法细节。

- `pipeline.py`
  - 负责规则候选生成（热度、突发、去噪、关键词、时间均衡抽样）。
  - 产出可供 LLM 二次增强的候选段。

- `llm.py`
  - 负责模型配置解析、调用、重试、JSON 抽取与结果融合。
  - 仅改写候选段中的语义字段和轻量时间偏移。

- `storage.py`
  - 负责分析产物与导出产物的路径解析与文件读写。

## 3. 配置优先级

以 L1/L2 自定义配置为例，解析顺序如下：

1. 用户请求体（`AIModelConfig`）提供的 `provider/model/base_url/api_key`。
2. 若请求缺失，回退到设置页全局配置（`GlobalConfig`）。
3. 对于已知 provider，应用 provider 级纠偏（例如 DeepSeek/Ollama 模型名纠偏）。
4. 最终通过 `_validate_chat_config` 做可执行性校验。

说明：
- `provider` 与 `source` 已统一映射，映射逻辑集中在 `_provider_to_source`。
- 非 Ollama provider 要求 API Key 非空。

## 4. 评分融合语义

- 规则层产出基础 `score/semantic_score/heat_score`。
- L1 仅对 `score` 做轻量融合，权重为 `0.6 * base + 0.4 * l1`，且强制 clamp 到 `[0,1]`。
- L2 产出语义判定后，通过 `_fuse_llm_scores` 进行融合：
  - 考虑 `confidence`、`is_highlight`、`scene_type` 对齐偏置。
  - 支持非高光惩罚与高置信加成。

## 5. JSON 抽取策略

- L2 使用语义丰富 JSON schema（`title/summary/keywords/story_text/...`）。
- L1 使用轻量 JSON schema（`score/reason/is_high_energy`）。
- 入口统一为 `_extract_json_from_text(..., schema=...)`，内部按 schema 分别走：
  - 平衡括号候选评分（L1/L2 分开评分函数）。
  - relaxed fallback（L1/L2 分开兜底抽取）。

## 6. 关键扩展点（推荐）

1. 新增 provider：
   - 在 `llm.py` 增加 provider loader。
   - 在 `_PROVIDER_SOURCE_MAP` 注册映射。
   - 复用 `_validate_chat_config` 保证输入完整性。

2. 新增分析策略：
   - 在 `schemas.py` 扩展 `analysis_strategy` Literal。
   - 在 `router._analyze_and_save` 增加分支，不破坏 `rule_only/llm_required` 语义。

3. 新增结果字段：
   - 先在 `llm.py` 或 `pipeline.py` 产出字段。
   - 再更新 `schemas.HighlightSegment` 与前端展示。

4. 替换 JSON 抽取器：
   - 保留 `L1/L2` 双 schema 入口（`_extract_json_from_text(..., schema=...)`）。
   - 不要合并回单一抽取器，以避免 schema 语义互相污染。

## 7. 当前设计约束

- `hybrid/rule_only` 仍是“规则优先 + LLM 增强”。
- `llm_required` 启用“AI 主导决策”：
  - 规则层只做轻量切窗召回，不做强阈值淘汰。
  - 召回池会按倍率扩大（上限 120），再交给 L1/L2 决策。
  - 最终结果按融合得分截断到 `max_candidates`。
- `llm_required` 下要求 LLM 真正参与；无可用样本或全量调用失败会报错而非静默降级。
- 时间偏移被限制在安全范围（`start_shift_sec: -8~8`、`end_shift_sec: -12~8`）并保持片段最小时长。
- 支持 `danmu_delay_compensation_seconds`（默认 `5`）：将弹幕时间整体前移后再参与候选分桶、片段评论采样与弹幕快照匹配，用于补偿“画面发生 -> 弹幕反应”天然延迟。

## 8. 重构约定

后续重构请遵循：

- 不在 `router` 中塞入 provider 特殊逻辑；统一进入 `llm.py`。
- 不在 `llm.py` 中直接做文件 I/O；文件写入统一由 `router/storage` 处理。
- 新增配置项时，必须同时更新：
  - 默认值定义
  - 读取逻辑
  - 有效性校验
  - 日志字段
