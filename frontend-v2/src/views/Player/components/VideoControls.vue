<template>
  <div class="video-controls-container">
    <div class="info-bar">
      <slot name="author-info"></slot>
      
      <div class="action-bar">
        <div class="action-group">
        <button class="action-btn" @click="$emit('prev-video')" title="上一集">
          <Icon name="chevron-left" :size="18" />
        </button>
        <button
          class="action-btn"
          v-if="!isImage"
          @click="$emit('toggle-play')"
          :title="isPaused ? '播放' : '暂停'"
        >
          <Icon :name="isPaused ? 'play' : 'pause'" :size="18" />
        </button>
        <button class="action-btn" @click="$emit('next-video')" title="下一集">
          <Icon name="chevron-right" :size="18" />
        </button>
        <div class="divider"></div>
        <button
          class="action-btn"
          @click="$emit('toggle-mute')"
          :title="isMuted ? '取消静音' : '音量'"
        >
          <Icon :name="isMuted ? 'volume-x' : 'volume-2'" :size="18" />
          <span class="btn-text">音量</span>
        </button>
        <div class="divider"></div>
        <button class="action-btn" @click="$emit('toggle-pip')" title="画中画">
          <Icon name="pip" :size="18" />
          <span class="btn-text">小窗</span>
        </button>
        <button
          class="action-btn"
          @click="$emit('toggle-fullscreen')"
          title="全屏"
        >
          <Icon name="maximize" :size="18" />
          <span class="btn-text">全屏</span>
        </button>
      </div>

      <button
        class="action-btn mobile-only"
        @click="$emit('show-playlist')"
        title="播放列表"
      >
        <Icon name="list" :size="18" />
        <span class="btn-text">列表</span>
      </button>

      <button
        class="action-btn mobile-only"
        @click="$emit('show-settings')"
      >
        <Icon name="settings" :size="18" />
        <span class="btn-text">设置</span>
      </button>
    </div>

    </div>

    <!-- 设置与进度控制 (桌面端) -->
    <div class="settings-card pc-only">
      <div class="control-row">
        <div class="control-group">
          <label>播放倍速</label>
          <select 
            :value="playbackSpeed" 
            @change="$emit('update:playbackSpeed', $event.target.value)" 
            class="modern-select"
          >
            <option value="0.5">0.5x</option>
            <option value="1">1.0x</option>
            <option value="1.25">1.25x</option>
            <option value="1.5">1.5x</option>
            <option value="2.0">2.0x</option>
          </select>
        </div>
        <div class="control-group">
          <label>画质选择</label>
          <select 
            :value="currentQuality"
            @change="$emit('update:currentQuality', $event.target.value)" 
            class="modern-select"
          >
            <option
              v-for="opt in qualityOptions"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </option>
          </select>
        </div>
        <div class="control-group">
          <label>字幕</label>
          <select
            :value="selectedSubtitleId"
            @change="$emit('update:selectedSubtitleId', $event.target.value)"
            class="modern-select"
            :disabled="!subtitleOptions.length || isAudio || isGallery"
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
        <div class="control-group">
          <label>列表模式</label>
          <button class="mode-btn" @click="$emit('cycle-playback-mode')">
            <Icon :name="playbackModeIcon" :size="16" />
            {{ playbackModeLabel }}
          </button>
        </div>
        <div class="control-group flex-row">
          <div class="switch-item">
            <label>自动连播</label>
            <div class="switch" @click="$emit('update:autoPlayNext', !autoPlayNext)">
              <input type="checkbox" :checked="autoPlayNext" />
              <span class="switch-slider"></span>
            </div>
          </div>
          <div class="switch-item">
            <label>后台播放</label>
            <div
              class="switch"
              @click="$emit('update:enableBackgroundPlay', !enableBackgroundPlay)"
            >
              <input type="checkbox" :checked="enableBackgroundPlay" />
              <span class="switch-slider"></span>
            </div>
          </div>
          <div class="switch-item">
            <label>画质增强</label>
            <div class="switch" @click="$emit('update:isEnhanced', !isEnhanced)">
              <input type="checkbox" :checked="isEnhanced" />
              <span class="switch-slider"></span>
            </div>
          </div>
          <div class="control-group">
            <label>多连屏模式</label>
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
        </div>

        <PlayerProgressBar
          :current-time="formattedCurrentTime"
          :duration="formattedDuration"
          :buffer-percent="bufferPercent"
          :progress-percent="progressPercent"
          :show-side="true"
          @seekStart="(val) => $emit('seekStart', val)"
          @seekMove="(val) => $emit('seekMove', val)"
          @seekEnd="(val) => $emit('seekEnd', val)"
        >
          <template #side>
            <GpuRuntimeInline
              class="pc-only player-gpu-inline"
              :gpu-stats="gpuStatusData"
              :is-loading="gpuStatusLoading"
              :error-text="gpuStatusError"
              :info="displaySideInfoLabel"
            />
          </template>
        </PlayerProgressBar>
      </div>
    </div>
  </div>
</template>

<script setup>
import Icon from "@/components/common/Icon.vue";
import PlayerProgressBar from "@/components/common/PlayerProgressBar.vue";
import GpuRuntimeInline from "@/components/common/GpuRuntimeInline.vue";

const props = defineProps({
  isImage: Boolean,
  isPaused: Boolean,
  isMuted: Boolean,
  playbackSpeed: [String, Number],
  currentQuality: String,
  qualityOptions: Array,
  selectedSubtitleId: String,
  subtitleOptions: Array,
  isAudio: Boolean,
  isGallery: Boolean,
  playbackModeIcon: String,
  playbackModeLabel: String,
  autoPlayNext: Boolean,
  enableBackgroundPlay: Boolean,
  isEnhanced: Boolean,
  tripleScreenMode: Number,
  tripleScreenSliderStyle: Object,
  formattedCurrentTime: String,
  formattedDuration: String,
  bufferPercent: Number,
  progressPercent: Number,
  gpuStatusData: Object,
  gpuStatusLoading: Boolean,
  gpuStatusError: String,
  displaySideInfoLabel: String
});

defineEmits([
  'prev-video',
  'toggle-play',
  'next-video',
  'toggle-mute',
  'toggle-pip',
  'toggle-fullscreen',
  'show-playlist',
  'show-settings',
  'update:playbackSpeed',
  'update:currentQuality',
  'update:selectedSubtitleId',
  'cycle-playback-mode',
  'update:autoPlayNext',
  'update:enableBackgroundPlay',
  'update:isEnhanced',
  'update:tripleScreenMode',
  'seekStart',
  'seekMove',
  'seekEnd'
]);
</script>


