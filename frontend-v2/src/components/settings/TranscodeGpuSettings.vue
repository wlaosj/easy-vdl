<template>
  <div class="transcode-settings">
    <div class="setting-group">
      <div class="group-title">
        <Icon name="monitor" :size="18" />
        GPU 转码设置
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">转码策略模式</span>
          <p class="desc">自动选择、手动指定某个硬件 profile，或强制 CPU 转码。</p>
        </div>
        <div class="setting-control">
          <select v-model="settings.mode" class="form-select" :disabled="loading || saving">
            <option value="auto">自动（按探测优先级）</option>
            <option value="manual">手动（选择指定 GPU）</option>
            <option value="cpu_only">仅 CPU</option>
          </select>
        </div>
      </div>

      <div v-if="settings.mode === 'manual'" class="setting-item">
        <div class="setting-label">
          <span class="title">手动选择硬件 Profile</span>
          <p class="desc" v-if="hasAdvancedProfiles">默认已折叠同卡重复项（优先 render 节点），可开启高级候选查看完整列表。</p>
          <p class="desc" v-else>默认展示优选的 render 节点候选。</p>
        </div>
        <div class="setting-control">
          <select v-model="settings.selected_profile_id" class="form-select" :disabled="loading || saving">
            <option value="">请选择</option>
            <option v-for="profile in selectableProfiles" :key="profile.profile_id" :value="profile.profile_id">
              {{ profile.display_name || profile.profile_id }}
            </option>
          </select>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">回退策略</span>
          <p class="desc">控制当前硬件失败时是否允许切到其他硬件或 CPU。</p>
        </div>
        <div class="setting-control checkbox-group">
          <label class="checkbox-item">
            <input v-model="settings.allow_fallback_to_other_hardware" type="checkbox" :disabled="loading || saving" />
            <span>允许回退到其他硬件</span>
          </label>
          <label class="checkbox-item">
            <input v-model="settings.allow_fallback_to_cpu" type="checkbox" :disabled="loading || saving" />
            <span>允许回退到 CPU</span>
          </label>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">输出视频编码</span>
          <p class="desc">按目标编码优先选择对应硬件编码器，不支持时自动回退软件编码器。</p>
        </div>
        <div class="setting-control">
          <select v-model="settings.output_video_codec" class="form-select" :disabled="loading || saving">
            <option value="auto">自动（跟随源视频）</option>
            <option value="h264">H.264（兼容优先）</option>
            <option value="hevc">HEVC / H.265（压缩率优先）</option>
            <option value="av1">AV1（新编码，CPU负载更高）</option>
          </select>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">Intel QSV 硬件提帧</span>
          <p class="desc">仅在 Intel QSV 转码链路下生效；不会回退到 CPU 软件插帧。</p>
        </div>
        <div class="setting-control">
          <select v-model="settings.intel_qsv_frame_interpolation_mode" class="form-select" :disabled="loading || saving">
            <option value="off">关闭</option>
            <option value="30to60">30 -> 60（稳定）</option>
            <option value="60to120">60 -> 120（实验）</option>
          </select>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">解码与编码高级项</span>
          <p class="desc">用于无缝播放场景下的硬解/低功耗编码策略。</p>
        </div>
        <div class="setting-control checkbox-group">
          <label class="checkbox-item">
            <input v-model="settings.enable_hw_decode" type="checkbox" :disabled="loading || saving" />
            <span>启用硬件解码（默认关闭）</span>
          </label>
          <label class="checkbox-item">
            <input v-model="settings.prefer_native_hw_decoder" type="checkbox" :disabled="loading || saving" />
            <span>QSV 优先原生硬解（Linux 常为 VAAPI）</span>
          </label>
          <label class="checkbox-item">
            <input v-model="settings.enable_intel_low_power_h264" type="checkbox" :disabled="loading || saving" />
            <span>Intel H264 低功耗编码</span>
          </label>
          <label class="checkbox-item">
            <input v-model="settings.enable_intel_low_power_hevc" type="checkbox" :disabled="loading || saving" />
            <span>Intel HEVC 低功耗编码</span>
          </label>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">操作</span>
          <p class="desc">保存设置后立即生效；可手动重探测硬件能力。</p>
        </div>
        <div class="setting-control action-buttons">
          <button class="btn btn-primary" :disabled="saving || loading" @click="saveSettings">
            <Icon name="check" :size="16" />
            {{ saving ? '保存中...' : '保存设置' }}
          </button>
          <button class="btn btn-outline" :disabled="reprobing || loading" @click="reprobeProfiles">
            <Icon :name="reprobing ? 'refresh' : 'monitor'" :size="16" :class="{ spin: reprobing }" />
            {{ reprobing ? '探测中...' : '重新探测 GPU' }}
          </button>
          <button class="btn btn-outline" :disabled="loading" @click="loadAll">
            <Icon name="refresh" :size="16" />
            刷新
          </button>
        </div>
      </div>

      <div class="policy-card">
        <div class="policy-title">当前生效转码策略</div>
        <div class="policy-main">{{ effectiveStrategySummary }}</div>
        <div class="policy-detail">{{ effectiveStrategyDetail }}</div>
        <div class="policy-chips">
          <span
            v-for="profile in effectiveProfiles"
            :key="`effective-${profile.profile_id}`"
            class="policy-chip policy-chip-hw"
          >
            {{ profile.display_name || `${String(profile.hwaccel || '').toUpperCase()} · ${profile.gpu_name || profile.device || 'auto'}` }}
          </span>
          <span v-if="showCpuFallbackChip" class="policy-chip policy-chip-cpu">
            CPU 回退 · {{ cpuFallbackEncoderLabel }}
          </span>
          <span
            v-if="!effectiveProfiles.length && settings.mode !== 'cpu_only' && !settings.allow_fallback_to_cpu"
            class="policy-chip policy-chip-risk"
          >
            无可用回退路径
          </span>
        </div>
      </div>

      <div class="profiles-card">
        <div class="profiles-header">
          <div class="profiles-title">
            探测到的转码 Profile（{{ visibleProfiles.length }}<template v-if="collapsedProfileCount > 0"> / {{ profiles.length }}</template>）
          </div>
          <label v-if="hasAdvancedProfiles" class="advanced-toggle">
            <input v-model="showAdvancedProfiles" type="checkbox" />
            <span>显示高级候选（+{{ collapsedProfileCount }}）</span>
          </label>
        </div>
        <div v-if="visibleProfiles.length === 0" class="empty">暂无可用硬件 profile，将走 CPU 转码。</div>
        <table v-else class="profiles-table">
          <thead>
            <tr>
              <th>状态</th>
              <th>后端</th>
              <th>厂商</th>
              <th>设备</th>
              <th>profile_id</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="profile in visibleProfiles" :key="profile.profile_id">
              <td>
                <span class="badge" :class="effectiveProfileIdSet.has(profile.profile_id) ? 'badge-active' : 'badge-idle'">
                  {{ effectiveProfileIdSet.has(profile.profile_id) ? '生效中' : '候选' }}
                </span>
              </td>
              <td>{{ profile.hwaccel }}</td>
              <td>{{ profile.vendor }}</td>
              <td>{{ profile.gpu_name || profile.device || '-' }}</td>
              <td class="mono">{{ profile.profile_id }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { systemApi } from '@/api/system'
import { useToast } from '@/composables/useToast'
import Icon from '@/components/common/Icon.vue'

const toast = useToast()
const loading = ref(false)
const saving = ref(false)
const reprobing = ref(false)
const showAdvancedProfiles = ref(false)
const profiles = ref([])
const effectiveProfiles = ref([])

const settings = reactive({
  mode: 'auto',
  selected_profile_id: '',
  selected_hwaccel: '',
  selected_vendor: '',
  output_video_codec: 'h264',
  allow_fallback_to_other_hardware: true,
  allow_fallback_to_cpu: true,
  enable_hw_decode: false,
  prefer_native_hw_decoder: true,
  enable_intel_low_power_h264: false,
  enable_intel_low_power_hevc: false,
  intel_qsv_frame_interpolation_mode: 'off'
})

const effectiveProfileIdSet = computed(() => {
  return new Set((effectiveProfiles.value || []).map((item) => item.profile_id))
})

const showCpuFallbackChip = computed(() => {
  if (settings.mode === 'cpu_only') return true
  return Boolean(settings.allow_fallback_to_cpu)
})

const outputCodecLabel = computed(() => {
  const value = String(settings.output_video_codec || 'h264').toLowerCase()
  if (value === 'auto') return '自动'
  if (value === 'hevc') return 'HEVC'
  if (value === 'av1') return 'AV1'
  return 'H.264'
})

const cpuFallbackEncoderLabel = computed(() => {
  const value = String(settings.output_video_codec || 'h264').toLowerCase()
  if (value === 'hevc') return 'libx265'
  if (value === 'av1') return 'libsvtav1'
  if (value === 'auto') return 'libx264/libx265/libsvtav1（按源）'
  return 'libx264'
})

const qsvInterpolationLabel = computed(() => {
  const mode = String(settings.intel_qsv_frame_interpolation_mode || 'off').toLowerCase()
  if (mode === '30to60') return 'QSV 提帧 30->60'
  if (mode === '60to120') return 'QSV 提帧 60->120（实验）'
  return 'QSV 提帧关闭'
})

const effectiveStrategySummary = computed(() => {
  if (settings.mode === 'cpu_only') {
    return `仅 CPU 转码（${outputCodecLabel.value}，${qsvInterpolationLabel.value}）`
  }
  if (settings.mode === 'manual') {
    if (effectiveProfiles.value.length > 0) {
      const primary = effectiveProfiles.value[0]
      return `手动策略生效：${primary.display_name || primary.profile_id}（${outputCodecLabel.value}，${qsvInterpolationLabel.value}）`
    }
    return settings.allow_fallback_to_cpu
      ? `手动策略未命中硬件，当前将回退 CPU（${outputCodecLabel.value}，${qsvInterpolationLabel.value}）`
      : '手动策略未命中硬件'
  }
  if (effectiveProfiles.value.length > 0) {
    const primary = effectiveProfiles.value[0]
    return `自动策略生效：${primary.display_name || primary.profile_id}（${outputCodecLabel.value}，${qsvInterpolationLabel.value}）`
  }
  return settings.allow_fallback_to_cpu
    ? `自动策略未探测到可用硬件，当前将回退 CPU（${outputCodecLabel.value}，${qsvInterpolationLabel.value}）`
    : '自动策略未探测到可用硬件'
})

const effectiveStrategyDetail = computed(() => {
  if (settings.mode === 'cpu_only') {
    return `已禁用全部硬件后端，转码链路固定为 CPU；${qsvInterpolationLabel.value}。`
  }
  if (effectiveProfiles.value.length > 0) {
    return settings.allow_fallback_to_cpu
      ? `当前优先使用上方硬件候选，失败时允许自动回退到 CPU；${qsvInterpolationLabel.value}。`
      : `当前仅允许硬件候选链路，不允许回退到 CPU；${qsvInterpolationLabel.value}。`
  }
  return settings.allow_fallback_to_cpu
    ? `当前没有硬件候选，系统会直接使用 CPU，属于预期行为；${qsvInterpolationLabel.value}。`
    : `当前没有硬件候选且已禁用 CPU 回退，可能导致转码失败；${qsvInterpolationLabel.value}。`
})

function normalizeDriDeviceKey(device) {
  const raw = String(device || '')
  const renderMatch = raw.match(/\/dev\/dri\/renderD(\d+)/)
  if (renderMatch) {
    const renderIndex = Number(renderMatch[1])
    if (Number.isFinite(renderIndex) && renderIndex >= 128) {
      return `drm-card-${renderIndex - 128}`
    }
    return `drm-render-${renderMatch[1]}`
  }
  const cardMatch = raw.match(/\/dev\/dri\/card(\d+)/)
  if (cardMatch) {
    return `drm-card-${cardMatch[1]}`
  }
  return raw || 'unknown-device'
}

function profileDedupKey(profile) {
  const hwaccel = String(profile?.hwaccel || '').toLowerCase()
  const vendor = String(profile?.vendor || '').toLowerCase()
  const encoder = String(profile?.encoder || '').toLowerCase()
  const initMode = String(profile?.init_mode || '').toLowerCase()
  const deviceKey = normalizeDriDeviceKey(profile?.device)
  return `${hwaccel}|${vendor}|${encoder}|${initMode}|${deviceKey}`
}

function isRenderDevice(profile) {
  const device = String(profile?.device || '')
  return device.includes('/dev/dri/renderD')
}

const dedupedProfiles = computed(() => {
  const grouped = new Map()
  const source = profiles.value || []
  for (const profile of source) {
    const key = profileDedupKey(profile)
    const existing = grouped.get(key)
    if (!existing) {
      grouped.set(key, profile)
      continue
    }

    const currentRender = isRenderDevice(profile)
    const existingRender = isRenderDevice(existing)
    if (currentRender && !existingRender) {
      grouped.set(key, profile)
      continue
    }
    if (currentRender === existingRender) {
      const currentRank = Number(profile?.rank || 0)
      const existingRank = Number(existing?.rank || 0)
      if (currentRank > existingRank) {
        grouped.set(key, profile)
      }
    }
  }
  return Array.from(grouped.values())
})

const collapsedProfileCount = computed(() => {
  const rawCount = (profiles.value || []).length
  const dedupedCount = dedupedProfiles.value.length
  return Math.max(0, rawCount - dedupedCount)
})

const hasAdvancedProfiles = computed(() => {
  return collapsedProfileCount.value > 0
})

const visibleProfiles = computed(() => {
  if (showAdvancedProfiles.value) {
    return profiles.value || []
  }
  return dedupedProfiles.value
})

const selectableProfiles = computed(() => {
  return [...visibleProfiles.value]
})

function mapToCanonicalProfileId(profileId) {
  const currentId = String(profileId || '')
  if (!currentId) {
    return currentId
  }
  const selected = (profiles.value || []).find((item) => item.profile_id === currentId)
  if (!selected) {
    return currentId
  }
  const selectedKey = profileDedupKey(selected)
  const canonical = (dedupedProfiles.value || []).find((item) => profileDedupKey(item) === selectedKey)
  return canonical?.profile_id || currentId
}

function reconcileSelectedProfile() {
  if (showAdvancedProfiles.value) {
    return
  }
  const currentId = String(settings.selected_profile_id || '')
  if (!currentId) {
    return
  }
  const canonicalId = mapToCanonicalProfileId(currentId)
  if (canonicalId && canonicalId !== currentId) {
    settings.selected_profile_id = canonicalId
  }
}

function applySettings(payload) {
  if (!payload || typeof payload !== 'object') return
  settings.mode = payload.mode || 'auto'
  settings.selected_profile_id = payload.selected_profile_id || ''
  settings.selected_hwaccel = payload.selected_hwaccel || ''
  settings.selected_vendor = payload.selected_vendor || ''
  settings.output_video_codec = payload.output_video_codec || 'h264'
  if (payload.allow_fallback_to_other_hardware !== undefined) {
    settings.allow_fallback_to_other_hardware = Boolean(payload.allow_fallback_to_other_hardware)
  }
  if (payload.allow_fallback_to_cpu !== undefined) {
    settings.allow_fallback_to_cpu = Boolean(payload.allow_fallback_to_cpu)
  }
  if (payload.enable_hw_decode !== undefined) {
    settings.enable_hw_decode = Boolean(payload.enable_hw_decode)
  }
  if (payload.prefer_native_hw_decoder !== undefined) {
    settings.prefer_native_hw_decoder = Boolean(payload.prefer_native_hw_decoder)
  }
  if (payload.enable_intel_low_power_h264 !== undefined) {
    settings.enable_intel_low_power_h264 = Boolean(payload.enable_intel_low_power_h264)
  }
  if (payload.enable_intel_low_power_hevc !== undefined) {
    settings.enable_intel_low_power_hevc = Boolean(payload.enable_intel_low_power_hevc)
  }
  if (payload.intel_qsv_frame_interpolation_mode !== undefined) {
    const mode = String(payload.intel_qsv_frame_interpolation_mode || 'off').toLowerCase()
    settings.intel_qsv_frame_interpolation_mode = ['off', '30to60', '60to120'].includes(mode) ? mode : 'off'
  }
}

async function loadSettings() {
  const data = await systemApi.getTranscodeSettings()
  applySettings(data.settings)
  profiles.value = data.detected_profiles || []
  effectiveProfiles.value = data.effective_profiles || []
  reconcileSelectedProfile()
}

async function loadAll() {
  loading.value = true
  try {
    await loadSettings()
  } catch (err) {
    toast.error(`加载转码设置失败: ${err.message}`)
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  if (settings.mode === 'manual' && !settings.selected_profile_id) {
    toast.warning('手动模式下请先选择一个硬件 profile')
    return
  }

  saving.value = true
  try {
    const payload = {
      mode: settings.mode,
      selected_profile_id: settings.selected_profile_id,
      output_video_codec: settings.output_video_codec,
      allow_fallback_to_other_hardware: settings.allow_fallback_to_other_hardware,
      allow_fallback_to_cpu: settings.allow_fallback_to_cpu,
      enable_hw_decode: settings.enable_hw_decode,
      prefer_native_hw_decoder: settings.prefer_native_hw_decoder,
      enable_intel_low_power_h264: settings.enable_intel_low_power_h264,
      enable_intel_low_power_hevc: settings.enable_intel_low_power_hevc,
      intel_qsv_frame_interpolation_mode: settings.intel_qsv_frame_interpolation_mode
    }
    const data = await systemApi.updateTranscodeSettings(payload)
    applySettings(data.settings)
    profiles.value = data.detected_profiles || profiles.value
    effectiveProfiles.value = data.effective_profiles || effectiveProfiles.value
    reconcileSelectedProfile()
    if (data.selected_profile_exists === false) {
      toast.warning('保存成功，但当前手动 profile 不存在于本次探测结果中')
    } else {
      toast.success('转码设置已保存并生效')
    }
  } catch (err) {
    toast.error(`保存失败: ${err.message}`)
  } finally {
    saving.value = false
  }
}

async function reprobeProfiles() {
  reprobing.value = true
  try {
    const data = await systemApi.reprobeTranscodeProfiles()
    applySettings(data.settings)
    profiles.value = data.profiles || []
    effectiveProfiles.value = data.effective_profiles || []
    reconcileSelectedProfile()
    toast.success('已完成硬件能力重探测')
  } catch (err) {
    toast.error(`重探测失败: ${err.message}`)
  } finally {
    reprobing.value = false
  }
}

onMounted(() => {
  loadAll()
})

watch(showAdvancedProfiles, (enabled) => {
  if (!enabled) {
    reconcileSelectedProfile()
  }
})

watch(hasAdvancedProfiles, (enabled) => {
  if (!enabled && showAdvancedProfiles.value) {
    showAdvancedProfiles.value = false
  }
})
</script>

<style scoped>
.transcode-settings {
  width: 100%;
}

.setting-group {
  margin-bottom: 32px;
}

.group-title {
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--color-primary);
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.setting-item {
  display: grid;
  grid-template-columns: minmax(240px, 320px) 1fr;
  gap: 40px;
  padding: 20px 0;
  border-bottom: 1px solid var(--color-border);
  align-items: flex-start;
}

.setting-label .title {
  display: block;
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 6px;
}

.setting-label .desc {
  font-size: 13px;
  color: var(--color-text-tertiary);
  line-height: 1.6;
}

.setting-control {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.checkbox-group {
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.checkbox-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.form-select {
  min-width: 300px;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 14px;
  background: var(--color-bg);
  color: var(--color-text-primary);
}

.action-buttons {
  gap: 10px;
}

.profiles-card {
  margin-top: 18px;
  padding: 14px 16px;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-bg-secondary);
}

.profiles-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 10px;
}

.policy-card {
  margin-top: 18px;
  padding: 14px 16px;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-bg-secondary);
}

.policy-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 6px;
}

.policy-main {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 6px;
}

.policy-detail {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
}

.policy-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.policy-chip {
  padding: 4px 8px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  font-size: 12px;
}

.policy-chip-hw {
  background: rgba(59, 130, 246, 0.12);
  color: #1d4ed8;
}

.policy-chip-cpu {
  background: rgba(107, 114, 128, 0.12);
  color: #4b5563;
}

.policy-chip-risk {
  background: rgba(239, 68, 68, 0.12);
  color: #b91c1c;
}

.profiles-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.profiles-header .profiles-title {
  margin-bottom: 0;
}

.advanced-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.profiles-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.profiles-table th,
.profiles-table td {
  padding: 8px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.badge-active {
  color: #047857;
  background: rgba(16, 185, 129, 0.15);
}

.badge-idle {
  color: #6b7280;
  background: rgba(107, 114, 128, 0.12);
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.empty {
  font-size: 13px;
  color: var(--color-text-tertiary);
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
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .form-select {
    min-width: 0;
    width: 100%;
  }

  .profiles-table {
    display: block;
    overflow-x: auto;
    white-space: nowrap;
  }
}
</style>
