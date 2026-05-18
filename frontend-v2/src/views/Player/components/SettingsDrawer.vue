<template>
  <div
    class="bottom-drawer-overlay"
    @click="$emit('close')"
  >
    <div class="bottom-drawer" @click.stop>
      <div class="drawer-header">
        <div class="drawer-handle"></div>
        <h4>播放设置</h4>
        <button class="close-btn" @click="$emit('close')">
          <Icon name="x" :size="20" />
        </button>
      </div>
      <div class="drawer-content">
        <div class="settings-list">
          <!-- 播放倍速 -->
          <div class="setting-item">
            <div class="label">播放倍速</div>
            <div class="options-row">
              <button
                v-for="s in [0.5, 1, 1.25, 1.5, 2]"
                :key="s"
                class="pill-option"
                :class="{ active: parseFloat(playbackSpeed) === s }"
                @click="$emit('update:playbackSpeed', s.toString())"
              >
                {{ s }}x
              </button>
            </div>
          </div>

          <!-- 画质选择 -->
          <div class="setting-item">
            <div class="label">画质选择</div>
            <div class="options-row scrollable">
              <button
                v-for="opt in qualityOptions"
                :key="opt.value"
                class="pill-option"
                :class="{ active: currentQuality === opt.value }"
                @click="$emit('update:currentQuality', opt.value)"
              >
                {{ opt.label }}
              </button>
            </div>
          </div>

          <!-- 字幕 -->
          <div class="setting-item">
            <div class="label">字幕</div>
            <select
              :value="selectedSubtitleId"
              class="modern-select subtitle-select"
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
          <div class="setting-item">
            <div class="label">播放模式</div>
            <div class="options-row">
              <button
                class="pill-option"
                :class="{ active: playbackMode === 'order' }"
                @click="$emit('update:playbackMode', 'order')"
              >
                顺序播放
              </button>
              <button
                class="pill-option"
                :class="{ active: playbackMode === 'random' }"
                @click="$emit('update:playbackMode', 'random')"
              >
                随机播放
              </button>
              <button
                class="pill-option"
                :class="{ active: playbackMode === 'single' }"
                @click="$emit('update:playbackMode', 'single')"
              >
                单曲循环
              </button>
            </div>
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
            <div class="label">画质增强 (锐化)</div>
            <div class="switch" @click="$emit('update:isEnhanced', !isEnhanced)">
              <input type="checkbox" :checked="isEnhanced" @change.stop />
              <span class="switch-slider"></span>
            </div>
          </div>

          <!-- 多连屏模式 -->
          <div class="setting-item">
            <div class="label">多连屏模式</div>
            <div class="segment-control multi-screen-segments">
              <div
                class="segment-item"
                :class="{ active: tripleScreenMode === 0 }"
                @click="$emit('update:tripleScreenMode', 0)"
              >关闭</div>
              <div
                class="segment-item"
                :class="{ active: tripleScreenMode === 3 }"
                @click="$emit('update:tripleScreenMode', 3)"
              >三连</div>
              <div
                class="segment-item"
                :class="{ active: tripleScreenMode === 4 }"
                @click="$emit('update:tripleScreenMode', 4)"
              >四连</div>
              <div
                class="segment-slider"
                :style="tripleScreenSliderStyle"
              ></div>
            </div>
          </div>

          <!-- GPU 状态 -->
          <div class="setting-item">
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
/* 底部抽屉样式 - 移动端全屏半透明遮罩 */
.bottom-drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5); /* 加回遮罩半透明背景，防视效穿透 */
  z-index: 1000;
  display: flex;
  align-items: flex-end;
}
.bottom-drawer {
  width: 100%;
  background: var(--color-bg-secondary);
  border-radius: 16px 16px 0 0;
  max-height: 75vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.2);
}
.drawer-header {
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--color-border);
  position: relative;
}
.drawer-handle {
  position: absolute;
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
  width: 36px;
  height: 4px;
  background: var(--color-border);
  border-radius: 2px;
}
.drawer-header h4 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
}
.close-btn {
  background: transparent;
  border: none;
  color: var(--color-text-primary);
  padding: 4px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.drawer-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.settings-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 24px;
}
.setting-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.setting-item.flex-between {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}
.setting-item .label {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text-primary);
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

/* 开关（Switch）样式 */
.switch {
  position: relative;
  display: inline-block;
  width: 44px;
  height: 24px;
  cursor: pointer;
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
  border-radius: 24px;
  border: 1px solid var(--color-border);
}
.switch-slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
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
