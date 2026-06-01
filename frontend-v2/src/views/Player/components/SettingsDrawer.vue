<template>
  <!-- 播放设置遮罩 -->
  <div
    class="mobile-actions-backdrop active"
    @click="$emit('close')"
  ></div>

  <!-- 播放设置抽屉 -->
  <div class="mobile-action-dock drawer-active">
    <!-- 移动端抽屉控制头部 -->
    <div class="drawer-header-mobile">
      <div class="drawer-handle"></div>
      <div class="drawer-title-row">
        <h3>播放设置</h3>
        <button class="drawer-close-btn" @click="$emit('close')">✕</button>
      </div>
    </div>
    <div class="drawer-content">
        <div class="settings-list">
          <!-- 播放倍速 -->
          <div class="setting-item flex-between">
            <div class="label">播放倍速</div>
            <select
              :value="playbackSpeed"
              class="modern-select settings-select"
              @change="$emit('update:playbackSpeed', $event.target.value)"
            >
              <option v-for="s in ['0.5', '1', '1.25', '1.5', '2']" :key="s" :value="s">{{ s }}x</option>
            </select>
          </div>

          <!-- 画质选择 -->
          <div class="setting-item flex-between">
            <div class="label">画质选择</div>
            <select
              :value="currentQuality"
              class="modern-select settings-select"
              @change="$emit('update:currentQuality', $event.target.value)"
            >
              <option v-for="opt in qualityOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <!-- 字幕 -->
          <div class="setting-item flex-between">
            <div class="label">字幕选择</div>
            <select
              :value="selectedSubtitleId"
              class="modern-select settings-select"
              :disabled="!subtitleOptions.length || isAudio || isGallery"
              @change="$emit('update:selectedSubtitleId', $event.target.value)"
            >
              <option value="off">关闭字幕</option>
              <option
                v-for="opt in subtitleOptions"
                :key="opt.id"
                :value="opt.id"
              >
                {{ opt.label }}
              </option>
            </select>
          </div>

          <!-- 播放模式 -->
          <div class="setting-item flex-between">
            <div class="label">播放模式</div>
            <select
              :value="playbackMode"
              class="modern-select settings-select"
              @change="$emit('update:playbackMode', $event.target.value)"
            >
              <option value="order">顺序播放</option>
              <option value="random">随机播放</option>
              <option value="single">单曲循环</option>
            </select>
          </div>

          <!-- 自动连播 -->
          <div class="setting-item flex-between">
            <div class="label">自动连播</div>
            <div class="switch" @click="$emit('update:autoPlayNext', !autoPlayNext)">
              <input type="checkbox" :checked="autoPlayNext" @change.stop />
              <span class="switch-slider"></span>
            </div>
          </div>

          <!-- 后台播放 -->
          <div class="setting-item flex-between">
            <div class="label">后台播放</div>
            <div class="switch" @click="$emit('update:enableBackgroundPlay', !enableBackgroundPlay)">
              <input type="checkbox" :checked="enableBackgroundPlay" @change.stop />
              <span class="switch-slider"></span>
            </div>
          </div>

          <!-- 画质增强 -->
          <div class="setting-item flex-between">
            <div class="label">画质增强</div>
            <div class="switch" @click="$emit('update:isEnhanced', !isEnhanced)">
              <input type="checkbox" :checked="isEnhanced" @change.stop />
              <span class="switch-slider"></span>
            </div>
          </div>

          <!-- 多连屏模式 -->
          <div class="setting-item flex-between">
            <div class="label">多连屏模式</div>
            <select
              :value="tripleScreenMode"
              class="modern-select settings-select"
              @change="$emit('update:tripleScreenMode', parseInt($event.target.value))"
            >
              <option :value="0">关闭</option>
              <option :value="3">三连屏</option>
              <option :value="4">四连屏</option>
            </select>
          </div>

          <!-- GPU 状态 -->
          <div class="setting-item full-width">
            <div class="label">GPU 状态</div>
            <GpuRuntimeInline
              class="player-gpu-mobile"
              :gpu-stats="gpuStatusData"
              :is-loading="gpuStatusLoading"
              :error-text="gpuStatusError"
              :info="displaySideInfoLabel"
            />
          </div>
        </div>
      </div>
    </div>
  </template>

<script setup>
import { computed } from 'vue';
import Icon from "@/components/common/Icon.vue";
import GpuRuntimeInline from "@/components/common/GpuRuntimeInline.vue";

const props = defineProps({
  playbackSpeed: {
    type: String,
    required: true
  },
  qualityOptions: {
    type: Array,
    required: true
  },
  currentQuality: {
    type: String,
    required: true
  },
  selectedSubtitleId: {
    type: String,
    required: true
  },
  subtitleOptions: {
    type: Array,
    required: true
  },
  isAudio: {
    type: Boolean,
    default: false
  },
  isGallery: {
    type: Boolean,
    default: false
  },
  playbackMode: {
    type: String,
    required: true
  },
  autoPlayNext: {
    type: Boolean,
    required: true
  },
  enableBackgroundPlay: {
    type: Boolean,
    required: true
  },
  isEnhanced: {
    type: Boolean,
    required: true
  },
  tripleScreenMode: {
    type: Number,
    required: true
  },
  gpuStatusData: {
    type: Object,
    default: null
  },
  gpuStatusLoading: {
    type: Boolean,
    default: false
  },
  gpuStatusError: {
    type: String,
    default: ''
  },
  displaySideInfoLabel: {
    type: String,
    default: ''
  }
});

defineEmits([
  'close',
  'update:playbackSpeed',
  'update:currentQuality',
  'update:selectedSubtitleId',
  'update:playbackMode',
  'update:autoPlayNext',
  'update:enableBackgroundPlay',
  'update:isEnhanced',
  'update:tripleScreenMode'
]);

const tripleScreenSliderStyle = computed(() => ({
  left:
    props.tripleScreenMode === 0
      ? "2px"
      : props.tripleScreenMode === 3
        ? "calc(33.33% + 2px)"
        : "calc(66.66% + 2px)",
  width: "calc(33.33% - 4px)",
}));
</script>

<style scoped>


.drawer-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px 0 14px 0;
  width: 100%;
  box-sizing: border-box;
}

.settings-list {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  padding-bottom: 20px;
  width: 100%;
  box-sizing: border-box;
}
.setting-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  box-sizing: border-box;
}
.setting-item.flex-between {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 8px;
  min-height: 50px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  width: 100%;
}
.setting-item.full-width {
  grid-column: span 2;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  width: 100%;
  overflow: hidden;
}
.setting-item .label {
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
  flex: 1;
  min-width: 0;
}
.setting-item.full-width .label {
  font-size: 0.84rem;
  font-weight: 600;
}
.options-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.subtitle-select {
  width: 100%;
  min-width: 0;
}
.options-row.scrollable {
  flex-wrap: nowrap;
  overflow-x: auto;
  padding-bottom: 4px;
  margin: 0 -4px;
  padding-left: 4px;
}

/* 药丸选项样式 */
.pill-option {
  padding: 5px 12px;
  border-radius: 10px;
  background: var(--color-bg-tertiary);
  border: 1px solid transparent;
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  min-width: 60px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}
.pill-option.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
  border-color: var(--color-primary);
}

/* 下拉框样式 */
.modern-select {
  width: 100%;
  height: 38px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  padding: 0 10px;
  font-size: 0.86rem;
  outline: none;
}
.modern-select:focus {
  border-color: var(--color-primary);
}

.settings-select {
  width: 72px !important;
  height: 30px !important;
  font-size: 0.78rem !important;
  border-radius: 6px !important;
  padding: 0 4px !important;
  background: var(--color-bg-tertiary) !important;
  border-color: var(--color-border) !important;
  text-align: right;
  flex-shrink: 0;
}

/* 开关（Switch）样式 */
.switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
  cursor: pointer;
  flex-shrink: 0;
}
.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}
.switch-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: var(--color-bg-tertiary);
  transition: 0.3s;
  border-radius: 22px;
  border: 1px solid var(--color-border);
}
.switch-slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 2px;
  bottom: 2px;
  background-color: white;
  transition: 0.3s;
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0,0,0,0.15);
}
input:checked + .switch-slider {
  background-color: var(--color-primary);
  border-color: var(--color-primary);
}
input:checked + .switch-slider:before {
  transform: translateX(20px);
}

/* 分段控制器 */
.segment-control {
  position: relative;
  display: flex;
  background: var(--color-bg-tertiary);
  border-radius: 10px;
  padding: 2px;
  border: 1px solid var(--color-border);
  width: 100%;
}
.segment-item {
  flex: 1;
  text-align: center;
  font-size: 0.8rem;
  padding: 6px 0;
  cursor: pointer;
  z-index: 2;
  color: var(--color-text-secondary);
  transition: color 0.3s;
  font-weight: 500;
}
.segment-item.active {
  color: var(--color-primary);
}
.segment-slider {
  position: absolute;
  top: 2px;
  bottom: 2px;
  background: var(--color-bg-secondary);
  border-radius: 8px;
  z-index: 1;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.player-gpu-mobile {
  width: 100%;
}
</style>
