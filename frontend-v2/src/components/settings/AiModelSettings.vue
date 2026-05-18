<template>
  <div class="ai-model-settings">
    <div class="model-tabs" role="tablist" aria-label="AI模型标签页">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'strategy' }"
        @click="switchTab('strategy')"
      >默认策略</button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'minimax' }"
        @click="switchTab('minimax')"
      >MiniMax</button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'deepseek' }"
        @click="switchTab('deepseek')"
      >DeepSeek</button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'compat' }"
        @click="switchTab('compat')"
      >兼容平台</button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'ollama' }"
        @click="switchTab('ollama')"
      >Ollama</button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'asr' }"
        @click="switchTab('asr')"
      >ASR 模型</button>
    </div>

    <div class="tab-panel strategy-panel" v-if="activeTab === 'strategy'">
      <div class="group-title">双级 AI 默认偏好</div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">L1 侦察兵 (初筛)</span>
          <p class="desc">全局默认：负责初步识别精彩时刻，建议用本地轻量模型。</p>
        </div>
        <div class="setting-control">
          <select v-model="settingsStore.aiModelSettings.l1ScoutProvider" class="form-input">
            <option value="none">关闭 (仅规则分析)</option>
            <option value="minimax">云端 MiniMax</option>
            <option value="deepseek">云端 DeepSeek</option>
            <option value="compat">兼容平台</option>
            <option value="ollama">本地 Ollama</option>
          </select>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">L2 剪辑师 (精修)</span>
          <p class="desc">全局默认：负责生成文案与剧情，建议用云端强力模型。</p>
        </div>
        <div class="setting-control">
          <select v-model="settingsStore.aiModelSettings.l2EditorProvider" class="form-input">
            <option value="none">关闭 (仅打分不写文案)</option>
            <option value="minimax">云端 MiniMax</option>
            <option value="deepseek">云端 DeepSeek</option>
            <option value="compat">兼容平台</option>
            <option value="ollama">本地 Ollama</option>
          </select>
        </div>
      </div>

      <div class="status-grid">
        <div class="status-card" :class="{ ok: minimaxReady }">
          <div class="status-name">MiniMax</div>
          <div class="status-value">{{ minimaxReady ? '已配置' : '待配置' }}</div>
        </div>
        <div class="status-card" :class="{ ok: deepseekReady }">
          <div class="status-name">DeepSeek</div>
          <div class="status-value">{{ deepseekReady ? '已配置' : '待配置' }}</div>
        </div>
        <div class="status-card" :class="{ ok: compatReady }">
          <div class="status-name">兼容平台</div>
          <div class="status-value">{{ compatReady ? '已配置' : '待配置' }}</div>
        </div>
        <div class="status-card" :class="{ ok: ollamaReady }">
          <div class="status-name">Ollama</div>
          <div class="status-value">{{ ollamaReady ? '已配置' : '待配置' }}</div>
        </div>
      </div>
    </div>

    <div class="tab-panel" v-else-if="activeTab === 'minimax'">
      <div class="group-title">MiniMax 配置</div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">Base URL</span>
          <p class="desc">默认值通常可直接使用；如你有专用接入地址可替换。</p>
        </div>
        <div class="setting-control">
          <input
            type="text"
            v-model="settingsStore.aiModelSettings.minimaxBaseUrl"
            placeholder="https://api.minimaxi.com/v1"
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">模型名</span>
          <p class="desc">填写你在 MiniMax 控制台可用的文本模型名称。</p>
        </div>
        <div class="setting-control">
          <input
            type="text"
            v-model="settingsStore.aiModelSettings.minimaxModel"
            placeholder="MiniMax-Text-01"
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">API Key</span>
          <p class="desc">仅保存在本地服务端数据库，不会展示给其他用户。</p>
        </div>
        <div class="setting-control">
          <input
            type="password"
            v-model="settingsStore.aiModelSettings.minimaxApiKey"
            placeholder="sk-..."
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">请求超时（秒）</span>
          <p class="desc">云端模型建议 60-120 秒；默认 90 秒，网络波动时更稳。</p>
        </div>
        <div class="setting-control">
          <input
            type="number"
            min="5"
            max="120"
            v-model.number="settingsStore.aiModelSettings.minimaxTimeoutSeconds"
            class="form-input"
          />
        </div>
      </div>

    </div>

    <div class="tab-panel" v-else-if="activeTab === 'deepseek'">
      <div class="group-title">DeepSeek 配置</div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">Base URL</span>
          <p class="desc">默认值通常可直接使用；如你有代理网关可替换。</p>
        </div>
        <div class="setting-control">
          <input
            type="text"
            v-model="settingsStore.aiModelSettings.deepseekBaseUrl"
            placeholder="https://api.deepseek.com"
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">模型名</span>
          <p class="desc">填写可用模型，例如 deepseek-chat / deepseek-reasoner。</p>
        </div>
        <div class="setting-control">
          <input
            type="text"
            v-model="settingsStore.aiModelSettings.deepseekModel"
            placeholder="deepseek-chat"
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">API Key</span>
          <p class="desc">仅保存在本地服务端数据库，不会展示给其他用户。</p>
        </div>
        <div class="setting-control">
          <input
            type="password"
            v-model="settingsStore.aiModelSettings.deepseekApiKey"
            placeholder="sk-..."
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">请求超时（秒）</span>
          <p class="desc">建议 30-120 秒；默认 90 秒。</p>
        </div>
        <div class="setting-control">
          <input
            type="number"
            min="5"
            max="120"
            v-model.number="settingsStore.aiModelSettings.deepseekTimeoutSeconds"
            class="form-input"
          />
        </div>
      </div>

    </div>

    <div class="tab-panel" v-else-if="activeTab === 'compat'">
      <div class="group-title">OpenAI 兼容平台配置</div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">平台预设</span>
          <p class="desc">选择常用平台会自动填入 Base URL 与推荐模型；也可以选自定义后手动填写。</p>
        </div>
        <div class="setting-control">
          <select
            v-model="settingsStore.aiModelSettings.compatProvider"
            class="form-input"
            @change="applyCompatPreset"
          >
            <option v-for="preset in compatPresets" :key="preset.name" :value="preset.name">
              {{ preset.label }}
            </option>
          </select>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">Base URL</span>
          <p class="desc">填写 OpenAI 兼容接口地址，通常以 /v1、/api/v3 或兼容路径结尾。</p>
        </div>
        <div class="setting-control">
          <input
            type="text"
            v-model="settingsStore.aiModelSettings.compatBaseUrl"
            placeholder="https://api.openai.com/v1"
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">模型名</span>
          <p class="desc">填写平台实际可用的模型 ID，例如 qwen-max / moonshot-v1-8k / glm-4-flash。</p>
        </div>
        <div class="setting-control">
          <input
            type="text"
            v-model="settingsStore.aiModelSettings.compatModel"
            placeholder="gpt-4o-mini"
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">API Key</span>
          <p class="desc">用于兼容平台鉴权，仅保存在本地服务端数据库。</p>
        </div>
        <div class="setting-control">
          <input
            type="password"
            v-model="settingsStore.aiModelSettings.compatApiKey"
            placeholder="sk-..."
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">额外参数（JSON）</span>
          <p class="desc">用于传递厂商扩展参数，例如 OpenRouter 的 provider 或 reasoning 配置。</p>
        </div>
        <div class="setting-control">
          <textarea
            v-model="settingsStore.aiModelSettings.compatExtraParams"
            rows="5"
            class="form-input"
            placeholder='{"top_p":0.9}'
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">请求超时（秒）</span>
          <p class="desc">兼容平台建议 30-120 秒；默认 90 秒。</p>
        </div>
        <div class="setting-control">
          <input
            type="number"
            min="5"
            max="120"
            v-model.number="settingsStore.aiModelSettings.compatTimeoutSeconds"
            class="form-input"
          />
        </div>
      </div>

    </div>

    <div class="tab-panel" v-else-if="activeTab === 'ollama'">
      <div class="group-title">Ollama 配置</div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">模式</span>
          <p class="desc">推荐使用原生模式（/api/chat），兼容模式保留用于旧网关。</p>
        </div>
        <div class="setting-control">
          <select v-model="settingsStore.aiModelSettings.ollamaMode" class="form-input">
            <option value="native">原生 Ollama（推荐）</option>
            <option value="openai_compat">OpenAI 兼容</option>
          </select>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">Base URL</span>
          <p class="desc">原生模式建议填到主机端口（如 http://127.0.0.1:11434），兼容模式可用 /v1。</p>
        </div>
        <div class="setting-control">
          <input
            type="text"
            v-model="settingsStore.aiModelSettings.ollamaBaseUrl"
            placeholder="http://127.0.0.1:11434"
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">模型名</span>
          <p class="desc">填写本地已拉取的模型名，例如 qwen2.5:7b。</p>
        </div>
        <div class="setting-control">
          <input
            type="text"
            v-model="settingsStore.aiModelSettings.ollamaModel"
            placeholder="qwen2.5:7b"
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">API Key（可选）</span>
          <p class="desc">本地 Ollama 通常不需要；若你前面有网关鉴权可填写。</p>
        </div>
        <div class="setting-control">
          <input
            type="password"
            v-model="settingsStore.aiModelSettings.ollamaApiKey"
            placeholder="可留空"
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">关闭思考模式</span>
          <p class="desc">原生模式下会传递 think=false，减少 reasoning/thinking 输出。</p>
        </div>
        <div class="setting-control">
          <label>
            <input
              type="checkbox"
              v-model="settingsStore.aiModelSettings.ollamaDisableThinking"
            />
            传递 think=false
          </label>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">额外参数（JSON）</span>
          <p class="desc">用于覆盖模型高级参数。原生模式优先放入 options；例如 {"num_ctx":8192}。</p>
        </div>
        <div class="setting-control">
          <textarea
            v-model="settingsStore.aiModelSettings.ollamaExtraParams"
            rows="6"
            class="form-input"
            placeholder='{"num_ctx":8192,"repeat_penalty":1.05}'
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">请求超时（秒）</span>
          <p class="desc">本地模型建议 60-180 秒；默认 180 秒，慢模型可提高到 600 秒。</p>
        </div>
        <div class="setting-control">
          <input
            type="number"
            min="10"
            max="600"
            v-model.number="settingsStore.aiModelSettings.ollamaTimeoutSeconds"
            class="form-input"
          />
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">能力信息（元数据）</span>
          <p class="desc">
            图像能力：{{ ollamaMetaStatusLabel }}
            <span v-if="settingsStore.aiModelSettings.ollamaMetaCheckedAt">
              （{{ formatCheckedAt(settingsStore.aiModelSettings.ollamaMetaCheckedAt) }}）
            </span>
          </p>
          <p class="desc" v-if="settingsStore.aiModelSettings.ollamaMetaCapabilities.length">
            能力列表：{{ settingsStore.aiModelSettings.ollamaMetaCapabilities.join(', ') }}
          </p>
          <div class="meta-cap-grid">
            <span class="meta-cap-chip" :class="capabilityClass(settingsStore.aiModelSettings.ollamaMetaSupportsVision)">图像：{{ capabilityLabel(settingsStore.aiModelSettings.ollamaMetaSupportsVision) }}</span>
            <span class="meta-cap-chip" :class="capabilityClass(settingsStore.aiModelSettings.ollamaMetaSupportsAudio)">音频：{{ capabilityLabel(settingsStore.aiModelSettings.ollamaMetaSupportsAudio) }}</span>
            <span class="meta-cap-chip" :class="capabilityClass(settingsStore.aiModelSettings.ollamaMetaSupportsTools)">工具：{{ capabilityLabel(settingsStore.aiModelSettings.ollamaMetaSupportsTools) }}</span>
            <span class="meta-cap-chip" :class="capabilityClass(settingsStore.aiModelSettings.ollamaMetaSupportsThinking)">思考：{{ capabilityLabel(settingsStore.aiModelSettings.ollamaMetaSupportsThinking) }}</span>
          </div>
          <p class="desc" v-if="ollamaMetaModelSummary">
            模型信息：{{ ollamaMetaModelSummary }}
          </p>
          <p class="desc" v-if="settingsStore.aiModelSettings.ollamaMetaModifiedAt">
            模型更新时间：{{ formatCheckedAt(settingsStore.aiModelSettings.ollamaMetaModifiedAt) }}
          </p>
          <p class="desc" v-if="settingsStore.aiModelSettings.ollamaMetaDetail">
            详情：{{ settingsStore.aiModelSettings.ollamaMetaDetail }}
          </p>
          <p class="desc">
            说明：元数据仅用于快速判断，最终以实际图像测试为准。
          </p>
        </div>
        <div class="setting-control">
          <button class="btn btn-outline" :disabled="metaLoading" @click="refreshOllamaCapabilities(true)">
            <Icon :name="metaLoading ? 'refresh' : 'database'" :size="16" :class="{ spin: metaLoading }" />
            {{ metaLoading ? '读取中...' : '刷新能力信息' }}
          </button>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">图像能力实测</span>
          <p class="desc">
            当前状态：{{ ollamaVisionStatusLabel }}
            <span v-if="settingsStore.aiModelSettings.ollamaVisionCheckedAt">
              （{{ formatCheckedAt(settingsStore.aiModelSettings.ollamaVisionCheckedAt) }}）
            </span>
          </p>
          <p class="desc" v-if="settingsStore.aiModelSettings.ollamaVisionDetail">
            详情：{{ settingsStore.aiModelSettings.ollamaVisionDetail }}
          </p>
          <p class="desc final-conclusion">{{ ollamaVisionConclusion }}</p>
          <p class="desc">说明：点击后会发起真实图像请求，结论优先级高于元数据。</p>
        </div>
        <div class="setting-control">
          <button class="btn btn-outline" :disabled="visionTesting" @click="detectOllamaVisionCapability">
            <Icon :name="visionTesting ? 'refresh' : 'image'" :size="16" :class="{ spin: visionTesting }" />
            {{ visionTesting ? '检测中...' : '检测图像能力' }}
          </button>
        </div>
      </div>
    </div>

    <div class="tab-panel" v-else-if="activeTab === 'asr'">
      <div class="group-title">ASR 模型管理</div>

      <div class="asr-summary">
        <div>
          <span class="summary-label">缓存目录</span>
          <span class="summary-value">{{ asrCacheDir || '-' }}</span>
        </div>
        <div>
          <span class="summary-label">已占用</span>
          <span class="summary-value">{{ formatBytes(asrTotalSize) }}</span>
        </div>
      </div>

      <div v-if="asrLoading" class="asr-empty">
        <Icon name="refresh" :size="16" class="spin" />
        正在读取 ASR 模型状态...
      </div>

      <div v-else class="asr-model-list">
        <div v-for="model in asrModels" :key="model.name" class="asr-model-card">
          <div class="asr-model-main">
            <div class="asr-model-title">
              <span>{{ model.label }}</span>
              <span class="status-chip" :class="{ ok: model.installed }">
                {{ model.installed ? '已安装' : '未安装' }}
              </span>
            </div>
            <div class="asr-model-desc">{{ model.description }}</div>
            <div class="asr-model-meta">
              <span>{{ model.repo_id }}</span>
              <span>{{ formatBytes(model.size_bytes) }}</span>
            </div>
          </div>
          <div class="asr-model-actions">
            <button
              class="btn btn-outline"
              :disabled="isAsrModelBusy(model.name)"
              @click="downloadAsrModel(model)"
            >
              <Icon :name="isAsrModelBusy(model.name) ? 'refresh' : 'download'" :size="16" :class="{ spin: isAsrModelBusy(model.name) }" />
              {{ isAsrModelBusy(model.name) ? '处理中...' : (model.installed ? '重新下载' : '下载') }}
            </button>
            <button
              class="btn btn-outline text-danger"
              :disabled="!model.installed || isAsrModelBusy(model.name)"
              @click="deleteAsrModel(model)"
            >
              <Icon name="trash" :size="16" />
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="testResult" class="test-result" :class="{ ok: testResult.success, fail: !testResult.success }">
      <div class="result-title">{{ testResult.success ? '连接测试成功' : '连接测试失败' }}</div>
      <div class="result-line">{{ testResult.message }}</div>
      <div class="result-line" v-if="testResult.model">模型：{{ testResult.model }}</div>
      <div class="result-line" v-if="testResult.latency_ms">耗时：{{ testResult.latency_ms }} ms</div>
      <div class="result-line" v-if="testResult.detail">详情：{{ testResult.detail }}</div>
    </div>

    <div class="global-actions" v-if="activeTab !== 'asr'">
      <button
        class="btn btn-outline"
        :disabled="testing || activeTab === 'strategy'"
        @click="testCurrentTab"
      >
        <Icon :name="testing ? 'refresh' : 'zap'" :size="16" :class="{ spin: testing }" />
        {{ testing ? '测试中...' : '测试' }}
      </button>
      <button @click="saveSettings" :disabled="settingsStore.saving" class="btn btn-primary">
        <Icon name="check" :size="16" />
        {{ settingsStore.saving ? '保存中...' : '保存' }}
      </button>
      <button @click="clearSettings" class="btn btn-outline text-danger">
        <Icon name="trash" :size="16" />
        清空
      </button>
    </div>
    <div class="global-actions" v-else>
      <button class="btn btn-outline" :disabled="asrLoading || Object.keys(asrBusyModels).length > 0" @click="loadAsrModels">
        <Icon :name="asrLoading ? 'refresh' : 'database'" :size="16" :class="{ spin: asrLoading }" />
        {{ asrLoading ? '刷新中...' : '刷新列表' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { aiConfigApi } from '@/api/settings'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import { useDialog } from '@/composables/useDialog'
import Icon from '@/components/common/Icon.vue'
import { wsService } from '@/utils/websocket'

const settingsStore = useSettingsStore()
const toast = useToast()
const dialog = useDialog()
const testing = ref(false)
const visionTesting = ref(false)
const metaLoading = ref(false)
const testResult = ref(null)
const activeTab = ref('strategy')
const asrLoading = ref(false)
// asrBusyModels: { [modelName]: { started_at, started_by } }
const asrBusyModels = ref({})
const asrModels = ref([])
const asrCacheDir = ref('')
const asrTotalSize = ref(0)
let capabilitiesTimer = null
let asrWsUnsubscribe = null

// 辅助函数：检查某模型是否正在下载
function isAsrModelBusy(modelName) {
  return modelName in asrBusyModels.value
}

const compatPresets = [
  { name: 'OpenAI', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  { name: 'Qwen', label: '通义千问 / 阿里云百炼', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-max' },
  { name: 'Moonshot', label: 'Moonshot / Kimi', baseUrl: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-8k' },
  { name: 'SiliconFlow', label: 'SiliconFlow', baseUrl: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-7B-Instruct' },
  { name: 'OpenRouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', model: 'openai/gpt-4o-mini' },
  { name: 'Zhipu', label: '智谱 GLM', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  { name: 'Doubao', label: '火山方舟 / 豆包', baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seed-1-6-250615' },
  { name: 'Hunyuan', label: '腾讯混元', baseUrl: 'https://api.hunyuan.cloud.tencent.com/v1', model: 'hunyuan-lite' },
  { name: 'Qianfan', label: '百度千帆', baseUrl: 'https://qianfan.baidubce.com/v2', model: 'ernie-4.0-turbo-8k' },
  { name: 'Custom', label: '自定义兼容接口', baseUrl: '', model: '' },
]

const minimaxReady = computed(() => {
  const cfg = settingsStore.aiModelSettings
  return !!String(cfg.minimaxBaseUrl || '').trim()
    && !!String(cfg.minimaxModel || '').trim()
    && !!String(cfg.minimaxApiKey || '').trim()
})

const deepseekReady = computed(() => {
  const cfg = settingsStore.aiModelSettings
  return !!String(cfg.deepseekBaseUrl || '').trim()
    && !!String(cfg.deepseekModel || '').trim()
    && !!String(cfg.deepseekApiKey || '').trim()
})

const compatReady = computed(() => {
  const cfg = settingsStore.aiModelSettings
  return !!String(cfg.compatBaseUrl || '').trim()
    && !!String(cfg.compatModel || '').trim()
    && !!String(cfg.compatApiKey || '').trim()
})

const ollamaReady = computed(() => {
  const cfg = settingsStore.aiModelSettings
  return !!String(cfg.ollamaBaseUrl || '').trim()
    && !!String(cfg.ollamaModel || '').trim()
})

const ollamaVisionStatusLabel = computed(() => {
  const status = String(settingsStore.aiModelSettings.ollamaVisionCapability || 'unknown').toLowerCase()
  if (status === 'supported') return '支持图像分析'
  if (status === 'unsupported') return '不支持图像分析'
  return '未检测'
})

const ollamaMetaStatusLabel = computed(() => {
  const status = String(settingsStore.aiModelSettings.ollamaMetaCapability || 'unknown').toLowerCase()
  if (status === 'supported') return '元数据提示支持'
  if (status === 'unsupported') return '元数据提示不支持'
  return '未知'
})

const ollamaMetaModelSummary = computed(() => {
  const cfg = settingsStore.aiModelSettings
  const parts = []
  if (cfg.ollamaMetaFamily) parts.push(`家族 ${cfg.ollamaMetaFamily}`)
  if (cfg.ollamaMetaParameterSize) parts.push(`规模 ${cfg.ollamaMetaParameterSize}`)
  if (cfg.ollamaMetaQuantizationLevel) parts.push(`量化 ${cfg.ollamaMetaQuantizationLevel}`)
  if (cfg.ollamaMetaFormat) parts.push(`格式 ${cfg.ollamaMetaFormat}`)
  if (cfg.ollamaMetaContextLength) parts.push(`上下文 ${Number(cfg.ollamaMetaContextLength).toLocaleString()}`)
  if (cfg.ollamaMetaArchitecture) parts.push(`架构 ${cfg.ollamaMetaArchitecture}`)
  if (cfg.ollamaMetaRequires) parts.push(`requires ${cfg.ollamaMetaRequires}`)
  return parts.join(' | ')
})

const ollamaVisionConclusion = computed(() => {
  const vision = String(settingsStore.aiModelSettings.ollamaVisionCapability || 'unknown').toLowerCase()
  const metaVision = settingsStore.aiModelSettings.ollamaMetaSupportsVision
  if (vision === 'supported') return '最终结论：图像实测通过，可直接用于图像分析。'
  if (vision === 'unsupported') return '最终结论：图像实测未通过，建议切换模型后重试。'
  if (metaVision === true) return '最终结论：元数据提示支持图像，建议点击“检测图像能力”做一次实测确认。'
  if (metaVision === false) return '最终结论：元数据提示不支持图像，建议更换视觉模型。'
  return '最终结论：能力信息不足，请先读取元数据并进行一次图像实测。'
})

const currentClearLabel = computed(() => {
  if (activeTab.value === 'strategy') return '默认策略'
  if (activeTab.value === 'minimax') return 'MiniMax'
  if (activeTab.value === 'deepseek') return 'DeepSeek'
  if (activeTab.value === 'compat') return '兼容平台'
  if (activeTab.value === 'ollama') return 'Ollama'
  return '当前页'
})

function capabilityLabel(flag) {
  if (flag === true) return '支持'
  if (flag === false) return '不支持'
  return '未知'
}

function capabilityClass(flag) {
  if (flag === true) return 'ok'
  if (flag === false) return 'fail'
  return 'unknown'
}

function switchTab(tab) {
  activeTab.value = tab
  testResult.value = null
  if (tab === 'ollama') scheduleCapabilitiesRefresh()
  if (tab === 'asr') loadAsrModels()
}

function applyCompatPreset() {
  const provider = String(settingsStore.aiModelSettings.compatProvider || '').trim()
  const preset = compatPresets.find((item) => item.name === provider)
  if (!preset || preset.name === 'Custom') return
  settingsStore.aiModelSettings.compatBaseUrl = preset.baseUrl
  settingsStore.aiModelSettings.compatModel = preset.model
}

async function saveSettings() {
  const result = await settingsStore.saveAiModelSettings()
  if (result.success) {
    toast.success('AI 模型配置已保存')
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

async function clearSettings() {
  const label = currentClearLabel.value
  const confirmed = await dialog.confirm({
    title: `清空${label}配置`,
    type: 'warning',
    confirmText: '确认清空',
    cancelText: '取消',
    message: `将清空当前标签页的配置。<br><br><strong>范围：</strong>${label}<br><strong>说明：</strong>其他 AI 平台配置不会受影响。`
  })
  if (!confirmed) return
  const result = await settingsStore.clearAiModelSettings(activeTab.value)
  if (result.success) {
    toast.success(`${label}配置已清空`)
    testResult.value = null
  } else {
    toast.error(`清空失败: ${result.error}`)
  }
}

async function testSettings(provider = 'minimax') {
  testing.value = true
  testResult.value = null
  const result = provider === 'ollama'
    ? await settingsStore.testOllamaSettings()
    : provider === 'compat'
      ? await settingsStore.testCompatSettings()
      : provider === 'deepseek'
        ? await settingsStore.testDeepseekSettings()
        : await settingsStore.testAiModelSettings()
  testing.value = false

  if (result.success) {
    testResult.value = result.data || { success: true, message: `${provider} 配置可用` }
    toast.success(
      provider === 'ollama'
        ? 'Ollama 测试成功'
        : provider === 'compat'
          ? '兼容平台测试成功'
          : provider === 'deepseek'
            ? 'DeepSeek 测试成功'
            : 'MiniMax 测试成功'
    )
  } else {
    const payload = result.data || {}
    testResult.value = {
      success: false,
      message: result.error || payload.message || '测试失败',
      detail: payload.detail || '',
      latency_ms: payload.latency_ms,
    }
    toast.error(`测试失败: ${testResult.value.message}`)
  }
}

async function testCurrentTab() {
  if (activeTab.value === 'strategy' || activeTab.value === 'asr') return
  await testSettings(activeTab.value)
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size >= 10 || unitIndex === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`
}

async function loadAsrModels() {
  asrLoading.value = true
  try {
    const result = await aiConfigApi.listAsrModels()
    asrModels.value = Array.isArray(result?.models) ? result.models : []
    asrCacheDir.value = String(result?.cache_dir || result?.hf_home || '').trim()
    asrTotalSize.value = Number(result?.total_size_bytes || 0)
    // 恢复下载状态（页面刷新后从后端同步）
    const downloading = result?.downloading || {}
    asrBusyModels.value = downloading
  } catch (err) {
    const msg = err?.response?.data?.detail || err?.response?.data?.message || err.message || '读取 ASR 模型状态失败'
    toast.error(msg)
  } finally {
    asrLoading.value = false
  }
}

async function downloadAsrModel(model) {
  const name = String(model?.name || '').trim()
  if (!name) return
  // 标记为下载中
  asrBusyModels.value = { ...asrBusyModels.value, [name]: { started_at: Date.now() } }
  try {
    await aiConfigApi.downloadAsrModel(name)
    // 下载成功/失败由 WebSocket 推送后端状态，前端不立即清除 busy 状态
    // toast.success(`ASR 模型 ${name} 已下载`)
    // await loadAsrModels()
  } catch (err) {
    const status = err?.response?.status
    if (status === 409) {
      // 正在下载中，不显示错误
      return
    }
    const msg = err?.response?.data?.detail || err?.response?.data?.message || err.message || '下载 ASR 模型失败'
    toast.error(msg)
    // 清除该模型的下载状态
    const newBusy = { ...asrBusyModels.value }
    delete newBusy[name]
    asrBusyModels.value = newBusy
  }
}

async function deleteAsrModel(model) {
  const name = String(model?.name || '').trim()
  if (!name || !model?.installed) return
  const confirmed = await dialog.confirm({
    title: `删除 ASR 模型 ${name}`,
    type: 'warning',
    confirmText: '确认删除',
    cancelText: '取消',
    message: `将删除本地缓存的 faster-whisper ${name} 模型。<br><br>下次使用该版本时需要重新下载。`
  })
  if (!confirmed) return
  // 标记为删除中
  asrBusyModels.value = { ...asrBusyModels.value, [name]: { started_at: Date.now(), deleting: true } }
  try {
    await aiConfigApi.deleteAsrModel(name)
    toast.success(`ASR 模型 ${name} 已删除`)
    await loadAsrModels()
  } catch (err) {
    const msg = err?.response?.data?.detail || err?.response?.data?.message || err.message || '删除 ASR 模型失败'
    toast.error(msg)
  } finally {
    // 清除该模型的 busy 状态
    const newBusy = { ...asrBusyModels.value }
    delete newBusy[name]
    asrBusyModels.value = newBusy
  }
}

function formatCheckedAt(value) {
  try {
    const d = new Date(value)
    if (Number.isNaN(d.getTime())) return value
    return d.toLocaleString()
  } catch {
    return value
  }
}

async function detectOllamaVisionCapability() {
  if (activeTab.value !== 'ollama') return
  visionTesting.value = true
  const result = await settingsStore.detectOllamaVision()
  visionTesting.value = false
  if (result.success) {
    const capability = String(result?.data?.capability || 'unknown').toLowerCase()
    if (capability === 'supported') {
      toast.success('模型支持图像分析')
    } else if (capability === 'unsupported') {
      toast.success('模型不支持图像分析')
    } else {
      toast.warning('暂时无法确定图像能力，请稍后重试')
    }
  } else {
    toast.error(`检测失败: ${result.error}`)
  }
}

async function refreshOllamaCapabilities(showToast = false) {
  if (activeTab.value !== 'ollama') return
  const baseUrl = String(settingsStore.aiModelSettings.ollamaBaseUrl || '').trim()
  const model = String(settingsStore.aiModelSettings.ollamaModel || '').trim()
  if (!baseUrl || !model) {
    settingsStore.aiModelSettings.ollamaMetaCapability = 'unknown'
    settingsStore.aiModelSettings.ollamaMetaCheckedAt = ''
    settingsStore.aiModelSettings.ollamaMetaDetail = '请先填写 Base URL 与模型名。'
    settingsStore.aiModelSettings.ollamaMetaCapabilities = []
    settingsStore.aiModelSettings.ollamaMetaSupportsVision = null
    settingsStore.aiModelSettings.ollamaMetaSupportsAudio = null
    settingsStore.aiModelSettings.ollamaMetaSupportsTools = null
    settingsStore.aiModelSettings.ollamaMetaSupportsThinking = null
    settingsStore.aiModelSettings.ollamaMetaFamily = ''
    settingsStore.aiModelSettings.ollamaMetaParameterSize = ''
    settingsStore.aiModelSettings.ollamaMetaQuantizationLevel = ''
    settingsStore.aiModelSettings.ollamaMetaFormat = ''
    settingsStore.aiModelSettings.ollamaMetaArchitecture = ''
    settingsStore.aiModelSettings.ollamaMetaContextLength = null
    settingsStore.aiModelSettings.ollamaMetaRequires = ''
    settingsStore.aiModelSettings.ollamaMetaModifiedAt = ''
    return
  }
  metaLoading.value = true
  const result = await settingsStore.fetchOllamaCapabilities()
  metaLoading.value = false
  if (showToast) {
    if (result.success) {
      const capability = String(result?.data?.capability || 'unknown').toLowerCase()
      if (capability === 'supported') {
        toast.success('元数据提示支持图像能力')
      } else if (capability === 'unsupported') {
        toast.warning('元数据提示不支持图像能力，建议再做实测确认')
      } else {
        toast.warning('暂未读取到明确能力信息，请以实测为准')
      }
    } else {
      toast.error(`读取能力信息失败: ${result.error}`)
    }
  }
}

function scheduleCapabilitiesRefresh() {
  if (capabilitiesTimer) clearTimeout(capabilitiesTimer)
  capabilitiesTimer = setTimeout(() => {
    refreshOllamaCapabilities(false)
  }, 600)
}

watch(
  () => [
    activeTab.value,
    settingsStore.aiModelSettings.ollamaBaseUrl,
    settingsStore.aiModelSettings.ollamaModel,
    settingsStore.aiModelSettings.ollamaMode,
    settingsStore.aiModelSettings.ollamaApiKey,
  ],
  () => {
    if (activeTab.value === 'ollama') {
      scheduleCapabilitiesRefresh()
    }
  }
)

onMounted(() => {
  settingsStore.loadAiModelSettings()
  // 初始化 ASR WebSocket 监听
  wsService.connect('asr_model')
  asrWsUnsubscribe = wsService.onMessage((channel, data) => {
    if (channel !== 'asr_model') return
    if (data.type === 'asr_download_start') {
      const modelName = data.model_name || ''
      if (modelName) {
        asrBusyModels.value = { ...asrBusyModels.value, [modelName]: data }
      }
    } else if (data.type === 'asr_download_complete') {
      const modelName = data.model_name || ''
      // 清除该模型的下载状态
      const newBusy = { ...asrBusyModels.value }
      delete newBusy[modelName]
      asrBusyModels.value = newBusy
      // 刷新模型列表
      loadAsrModels()
      toast.success(`ASR 模型 ${modelName} 已下载`)
    } else if (data.type === 'asr_download_error') {
      const modelName = data.model_name || ''
      // 清除该模型的下载状态
      const newBusy = { ...asrBusyModels.value }
      delete newBusy[modelName]
      asrBusyModels.value = newBusy
      toast.error(`ASR 模型 ${modelName} 下载失败: ${data.error || '未知错误'}`)
    }
  })
})

onBeforeUnmount(() => {
  if (capabilitiesTimer) {
    clearTimeout(capabilitiesTimer)
    capabilitiesTimer = null
  }
  if (asrWsUnsubscribe) {
    asrWsUnsubscribe()
    asrWsUnsubscribe = null
  }
  wsService.close('asr_model')
})
</script>

<style scoped>
.ai-model-settings {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.model-tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 2px;
}

.tab-btn {
  border: 1px solid var(--color-border-primary);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  border-radius: 999px;
  padding: 7px 14px;
  font-weight: 600;
  white-space: nowrap;
}

.tab-btn.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
}

.tab-panel {
  border: 1px solid var(--color-border-primary);
  border-radius: 12px;
  background: var(--color-bg-card);
  padding: 14px;
}

.group-title {
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  color: var(--color-primary);
  margin-bottom: 14px;
}

.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--color-border-primary);
}

.setting-item:last-child {
  border-bottom: 0;
  padding-bottom: 4px;
}

.setting-label {
  flex: 1;
  min-width: 0;
}

.setting-label .title {
  display: block;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.setting-label .desc {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.45;
}

.meta-cap-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0;
}

.meta-cap-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--color-border-primary);
  color: var(--color-text-secondary);
  background: var(--color-bg-secondary);
}

.meta-cap-chip.ok {
  border-color: rgba(22, 163, 74, 0.45);
  background: rgba(22, 163, 74, 0.1);
  color: #166534;
}

.meta-cap-chip.fail {
  border-color: rgba(239, 68, 68, 0.45);
  background: rgba(239, 68, 68, 0.08);
  color: #991b1b;
}

.meta-cap-chip.unknown {
  border-color: rgba(148, 163, 184, 0.55);
  background: rgba(148, 163, 184, 0.1);
  color: #334155;
}

.final-conclusion {
  margin-top: 6px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.setting-control {
  width: 420px;
  max-width: 100%;
}

.status-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.status-card {
  border: 1px solid var(--color-border-primary);
  border-radius: 10px;
  padding: 10px 12px;
  background: var(--color-bg-secondary);
}

.status-card.ok {
  border-color: rgba(22, 163, 74, 0.45);
  background: rgba(22, 163, 74, 0.08);
}

.status-name {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.status-value {
  margin-top: 4px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.asr-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--color-border-primary);
  border-radius: 8px;
  background: var(--color-bg-secondary);
  margin-bottom: 12px;
}

.summary-label {
  display: block;
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}

.summary-value {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  word-break: break-all;
}

.asr-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-secondary);
  padding: 18px 4px;
}

.asr-model-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.asr-model-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border: 1px solid var(--color-border-primary);
  border-radius: 8px;
  padding: 12px;
  background: var(--color-bg-card);
}

.asr-model-main {
  flex: 1;
  min-width: 0;
}

.asr-model-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.asr-model-desc {
  margin-top: 5px;
  font-size: 13px;
  line-height: 1.45;
  color: var(--color-text-secondary);
}

.asr-model-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-tertiary, var(--color-text-secondary));
}

.asr-model-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  background: rgba(148, 163, 184, 0.14);
  border: 1px solid rgba(148, 163, 184, 0.45);
}

.status-chip.ok {
  color: #166534;
  background: rgba(22, 163, 74, 0.1);
  border-color: rgba(22, 163, 74, 0.45);
}

.test-result {
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--color-border-primary);
}

.test-result.ok {
  border-color: #16a34a;
  background: rgba(22, 163, 74, 0.08);
}

.test-result.fail {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.08);
}

.result-title {
  font-weight: 700;
  margin-bottom: 6px;
}

.result-line {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}

.global-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  border: 1px solid var(--color-border-primary);
  border-radius: 12px;
  padding: 10px;
  background: var(--color-bg-card);
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@media (max-width: 900px) {
  .setting-item {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .setting-control {
    width: 100%;
  }

  .status-grid {
    grid-template-columns: 1fr;
  }

  .asr-summary {
    grid-template-columns: 1fr;
  }

  .asr-model-card {
    align-items: stretch;
    flex-direction: column;
  }

  .asr-model-actions {
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .model-tabs {
    position: sticky;
    top: 0;
    z-index: 5;
    padding: 8px 2px;
    margin: -2px -2px 0;
    background: var(--color-bg-primary);
  }

  .tab-btn {
    padding: 8px 12px;
    font-size: 13px;
  }

  .tab-panel {
    padding: 12px 10px;
  }

  .global-actions {
    position: sticky;
    bottom: 0;
    z-index: 6;
    background: rgba(255, 255, 255, 0.92);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    padding-bottom: calc(10px + env(safe-area-inset-bottom));
  }

  .global-actions .btn {
    flex: 1;
    min-width: 0;
    height: 42px;
  }
}
</style>
