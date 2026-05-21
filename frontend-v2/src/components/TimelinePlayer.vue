<template>
  <div class="timeline-player-container">
    <div
      class="player-viewport"
      ref="playerViewport"
      @mousemove="handleViewportMouseMove"
      @mouseleave="handleViewportMouseLeave"
      @touchstart="handleViewportTouchStart"
      @touchend="handleViewportTouchEnd"
      @touchcancel="handleViewportTouchEnd"
    >
      <div 
        v-if="isFullscreen && (subDisplayName || props.subPlatformName)" 
        class="streamer-meta"
        :class="{ 'is-visible': fullscreenControlsVisible }"
      >
        <img v-if="props.subAvatar" :src="props.subAvatar" class="streamer-avatar" referrerpolicy="no-referrer" />
        <div v-else class="streamer-avatar-placeholder">{{ subInitial }}</div>
        <div class="streamer-texts">
          <span v-if="props.subPlatformName" class="streamer-platform">{{ props.subPlatformName }}</span>
          <span class="streamer-name">{{ subDisplayName || '无缝时间轴回放' }}</span>
        </div>
      </div>
      <div class="player-content-layout" :class="{ 'triple-mode': tripleScreenMode > 0 }" :style="tripleLayoutStyle">
        <canvas v-if="showTripleScreen && tripleScreenMode === 4" ref="mirrorCanvasFarLeft" class="triple-mirror"></canvas>
        <canvas v-if="showTripleScreen" ref="mirrorCanvasLeft" class="triple-mirror"></canvas>
        <div class="video-stack">
          <video ref="video0" class="nvr-video" :class="{ 'active': activeVideo === 0 }" @ended="onVideoEnded" @timeupdate="onTimeUpdate" @play="onVideoPlay" @pause="onVideoPause" @loadedmetadata="onVideoLoadedMetadata"></video>
          <video ref="video1" class="nvr-video" :class="{ 'active': activeVideo === 1 }" @ended="onVideoEnded" @timeupdate="onTimeUpdate" @play="onVideoPlay" @pause="onVideoPause" @loadedmetadata="onVideoLoadedMetadata"></video>
        </div>
        <canvas v-if="showTripleScreen" ref="mirrorCanvasRight" class="triple-mirror"></canvas>
      </div>
      <div v-if="danmuMode === 'marquee' && marqueeItems.length" class="danmu-marquee-layer">
        <div
          v-for="item in marqueeItems"
          :key="item.id"
          class="danmu-marquee-item"
          :style="item.style"
        >
          <span class="danmu-text">{{ item.text }}</span>
        </div>
      </div>
      <div v-if="danmuMode === 'list'" class="danmu-list-panel">
        <button v-if="danmuListUserHold" class="danmu-list-jump" type="button" @click="jumpDanmuListToLatest">
          最新
        </button>
        <div
          class="danmu-list"
          ref="danmuListRef"
          @scroll="handleDanmuListScroll"
          @wheel.stop
          @touchmove.stop
        >
          <div v-for="item in danmuListItems" :key="item._id" class="danmu-list-item">
            <span class="danmu-text">{{ formatDanmuLine(item) }}</span>
          </div>
          <div v-if="!danmuListItems.length" class="danmu-list-empty">暂无弹幕</div>
        </div>
      </div>
      <div
        v-if="isFullscreen && isTouchDevice"
        class="fullscreen-touch-layer"
        @touchstart.prevent="handleFullscreenTouchLayer"
      ></div>
      <div v-if="loading" class="nvr-loading">
        <div class="loading-panel">
          <div class="loading-orbit">
            <span class="loading-dot"></span>
          </div>
          <div class="loading-title">{{ isTimelineSeeking ? '正在切换播放位置' : '正在加载片段' }}</div>
          <div class="loading-subtitle">请稍候，视频即将继续播放</div>
          <div class="loading-progress-track">
            <div class="loading-progress-bar"></div>
          </div>
        </div>
      </div>
    </div>
      <div v-if="!isFullscreen" class="timeline-controls">
        <div class="control-actions">
          <div class="control-main">
          <button class="btn btn-primary btn-sm" @click="togglePlay">
            <Icon :name="playing ? 'pause' : 'play'" :size="16" />
          </button>
          <button class="btn btn-outline btn-sm fullscreen-btn" @click="toggleFullscreen" :title="isFullscreen ? '退出全屏' : '全屏播放'">
            <Icon :name="isFullscreen ? 'minimize' : 'maximize'" :size="16" />
          </button>
          <button class="btn btn-outline btn-sm speed-btn" @click="togglePlaybackSpeed" :title="`播放倍速（当前 ${playbackSpeedLabel}）`">
            {{ playbackSpeedLabel }}
          </button>
          <button class="btn btn-outline btn-sm mute-btn" @click="toggleMute" :title="isMuted ? '取消静音' : '静音'">
            <Icon :name="isMuted ? 'volume-x' : 'volume-2'" :size="16" />
          </button>
          <button class="btn btn-outline btn-sm danmu-btn" @click="toggleDanmuMode" :title="danmuModeLabel">
            {{ danmuModeShort }}
          </button>
          <span class="danmu-status">{{ danmuStatusText }}</span>
          <button class="btn btn-outline btn-sm pip-btn" @click="togglePip" :title="isPipActive ? '退出小窗' : '小窗播放'">
            <Icon name="pip" :size="16" />
          </button>
          <button v-if="isVerticalVideo" class="btn btn-outline btn-sm triple-btn" :class="{ 'active': tripleScreenMode > 0 }" @click="cycleTripleScreenMode" :title="tripleScreenModeLabel">
            {{ tripleScreenModeShort }}
          </button>
          <span class="time-display">
            <span class="time-line time-line-current">{{ formatTime(playTimeOfDay) }}</span>
            <span class="time-line time-line-total">/ 24:00:00</span>
          </span>
            <div v-if="timelineNotice" class="runtime-hints runtime-hints--inline">
              <span class="runtime-hint runtime-hint--notice">
                {{ timelineNotice }}
              </span>
            </div>
        </div>
        <div class="timeline-runtime-row">
          <button class="btn btn-outline btn-sm quality-btn runtime-quality-btn" @click="cycleTimelineQuality" :title="`切换画质（当前 ${timelineQualityLabel}）`">
            {{ timelineQualityLabel }}
          </button>
          <GpuRuntimeInline
            class="timeline-gpu-inline"
            :gpu-stats="gpuStatusData"
            :is-loading="gpuStatusLoading"
            :error-text="gpuStatusError"
            :info="displayTranscodeLabel"
          />
        </div>
        <div class="date-picker-wrap">
          <div class="date-nav-row">
            <button
              type="button"
              class="btn btn-outline btn-xs date-nav-btn"
              :disabled="!prevAvailableDate"
              title="跳转到上一有录像日期"
              @click="jumpToAdjacentAvailableDate(-1)"
            >
              上一日
            </button>
            <input
              type="date"
              :value="currentDate"
              @change="onDateChange"
              class="form-input date-picker"
              :class="{ 'is-unavailable': !isCurrentDateAvailable && !availableDatesLoading }"
            />
            <button
              type="button"
              class="btn btn-outline btn-xs date-nav-btn"
              :disabled="!nextAvailableDate"
              title="跳转到下一有录像日期"
              @click="jumpToAdjacentAvailableDate(1)"
            >
              下一日
            </button>
          </div>
          <div class="date-quick-row">
            <button
              type="button"
              class="btn btn-outline btn-xs"
              :disabled="!availableDateItems.length"
              @click.stop="toggleAvailableDatePanel"
            >
              {{ showAvailableDatePanel ? '收起日历' : '有录像日历' }}
            </button>
            <button type="button" class="btn btn-outline btn-xs" @click="selectDate(todayDate)">今天</button>
            <button type="button" class="btn btn-outline btn-xs" @click="selectDate(yesterdayDate)">昨天</button>
            <button
              type="button"
              class="btn btn-outline btn-xs"
              :disabled="!latestAvailableDate"
              @click="jumpToLatestAvailableDate"
            >
              <span class="btn-text-desktop">最近有录像</span>
              <span class="btn-text-mobile">最近</span>
            </button>
            <span v-if="latestAvailableDate" class="date-panel-latest">
              最近：{{ latestAvailableDate }}
            </span>
          </div>
        </div>
      </div>
      <div v-if="availableDatesLoading" class="timeline-available-loading">正在加载可用日期...</div>
      <div v-else-if="availableDatesError" class="timeline-available-empty">{{ availableDatesError }}</div>
      <div v-else-if="!availableDateItems.length" class="timeline-available-empty">暂无可播放日期（当前仅支持 MP4/TS 时间轴片段）。</div>
      <div class="timeline-bar-container">
        <div
          class="timeline-bar-wrapper"
          :class="{ dragging: isDraggingTimeline }"
          ref="timelineWrapper"
          @wheel.prevent="onWheel"
          @touchstart="onTouchStart"
          @touchmove="onTouchMove"
          @touchend="onTouchEnd"
          @touchcancel="onTouchEnd"
          @scroll="onScroll"
          @mousedown="onDragStart"
        >
          <div class="timeline-bar-inner" :class="{ 'is-mobile': isMobile }">
            <div v-if="isMobile" class="timeline-track-spacer" :style="{ width: halfWrapWidth + 'px' }"></div>
            <!-- 背景横轴 24h -->
            <div
              class="timeline-track"
              ref="timelineTrack"
              :style="{ width: (timelineScale * 100) + '%' }"
              @mousemove="onTrackMouseMove"
              @mouseleave="onTrackMouseLeave"
              @click="onTrackClick"
            >
              <!-- 刻度线 -->
            <div v-for="(tick, idx) in computedTicks" :key="idx" class="timeline-tick" :class="{ 'major-tick': tick.isMajor }" :style="{ left: tick.leftPercent + '%' }">
              <span class="tick-label" v-if="tick.showLabel">{{ tick.labelText }}</span>
            </div>
              
              <!-- 录制片段 -->
              <div 
                v-for="(seg, idx) in normalizedSegments" 
                :key="idx" 
                class="timeline-segment"
                :class="[`timeline-segment--${seg.formatTag}`, `timeline-segment-status--${seg.statusTag}`]"
                :style="{ left: seg.left + '%', width: seg.width + '%' }"
                :title="seg.startTimeText + ' - ' + seg.endTimeText + ' [' + seg.formatText + ' | ' + seg.statusText + ']'"
              ></div>

              <div v-if="!isMobile" class="timeline-cursor playhead" :style="{ left: cursorLeft + '%' }"></div>
              <div
                v-if="!isMobile && hoverCursorVisible"
                class="timeline-cursor hover-cursor"
                :style="{ left: hoverCursorLeft + '%' }"
              ></div>
            </div>
            <div v-if="isMobile" class="timeline-track-spacer" :style="{ width: halfWrapWidth + 'px' }"></div>
          </div>
        </div>
        <div v-if="isMobile" class="timeline-cursor fixed-center"></div>
      </div>
    </div>
    <Teleport v-else-if="playerViewport" :to="playerViewport">
      <div
        class="timeline-controls timeline-controls--fullscreen"
        :class="{ 'is-visible': fullscreenControlsVisible }"
        ref="fullscreenControlsRef"
        @mousemove="showFullscreenControls"
        @mouseenter="handleFullscreenControlsEnter"
        @mouseleave="handleFullscreenControlsLeave"
        @touchstart="handleFullscreenControlsTouchStart"
        @touchend="handleFullscreenControlsTouchEnd"
        @touchcancel="handleFullscreenControlsTouchEnd"
      >
        <div
          class="fullscreen-controls-inner"
          ref="fullscreenControlsInnerRef"
          @mouseenter="handleFullscreenControlsEnter"
          @mouseleave="handleFullscreenControlsLeave"
        >
          <div class="control-actions">
            <div class="control-main">
              <button class="btn btn-primary btn-sm" @click="togglePlay">
                <Icon :name="playing ? 'pause' : 'play'" :size="16" />
              </button>
              <button class="btn btn-outline btn-sm fullscreen-btn" @click="toggleFullscreen" :title="isFullscreen ? '退出全屏' : '全屏播放'">
                <Icon :name="isFullscreen ? 'minimize' : 'maximize'" :size="16" />
              </button>
              <button v-if="isFullscreen && isTouchDevice" class="btn btn-outline btn-sm rotate-btn" @click="toggleForceLandscape" :title="isForceLandscape ? '取消强制横屏' : '强制横屏'">
                <Icon :name="isForceLandscape ? 'screen-off' : 'screen-rotation'" :size="16" />
              </button>
              <button class="btn btn-outline btn-sm speed-btn" @click="togglePlaybackSpeed" :title="`播放倍速（当前 ${playbackSpeedLabel}）`">
                {{ playbackSpeedLabel }}
              </button>
              <button class="btn btn-outline btn-sm quality-btn" @click="cycleTimelineQuality" :title="`切换画质（当前 ${timelineQualityLabel}）`">
                {{ timelineQualityLabel }}
              </button>
              <GpuRuntimeInline
                class="timeline-gpu-inline timeline-gpu-inline--fullscreen"
                :gpu-stats="gpuStatusData"
                :is-loading="gpuStatusLoading"
                :error-text="gpuStatusError"
                :info="displayTranscodeLabel"
              />
              <button class="btn btn-outline btn-sm mute-btn" @click="toggleMute" :title="isMuted ? '取消静音' : '静音'">
                <Icon :name="isMuted ? 'volume-x' : 'volume-2'" :size="16" />
              </button>
              <button class="btn btn-outline btn-sm danmu-btn" @click="toggleDanmuMode" :title="danmuModeLabel">
                {{ danmuModeShort }}
              </button>
              <button class="btn btn-outline btn-sm pip-btn" @click="togglePip" :title="isPipActive ? '退出小窗' : '小窗播放'">
                <Icon name="pip" :size="16" />
              </button>
              <button v-if="isVerticalVideo" class="btn btn-outline btn-sm triple-btn" :class="{ 'active': tripleScreenMode > 0 }" @click="cycleTripleScreenMode" :title="tripleScreenModeLabel">
                {{ tripleScreenModeShort }}
              </button>
              <span class="time-display">
                <span class="time-line time-line-current">{{ formatTime(playTimeOfDay) }}</span>
                <span class="time-line time-line-total">/ 24:00:00</span>
              </span>
            </div>
            <div class="date-picker-wrap date-picker-wrap--fullscreen">
              <div class="date-nav-row">
                <button
                  type="button"
                  class="btn btn-outline btn-xs date-nav-btn"
                  :disabled="!prevAvailableDate"
                  title="跳转到上一有录像日期"
                  @click="jumpToAdjacentAvailableDate(-1)"
                >
                  上一日
                </button>
                <input
                  type="date"
                  :value="currentDate"
                  @change="onDateChange"
                  class="form-input date-picker"
                  :class="{ 'is-unavailable': !isCurrentDateAvailable && !availableDatesLoading }"
                />
                <button
                  type="button"
                  class="btn btn-outline btn-xs date-nav-btn"
                  :disabled="!nextAvailableDate"
                  title="跳转到下一有录像日期"
                  @click="jumpToAdjacentAvailableDate(1)"
                >
                  下一日
                </button>
              </div>
              <div class="date-quick-row">
                <button
                  type="button"
                  class="btn btn-outline btn-xs"
                  :disabled="!availableDateItems.length"
                  @click.stop="toggleAvailableDatePanel"
                >
                  {{ showAvailableDatePanel ? '收起日历' : '有录像日历' }}
                </button>
                <button type="button" class="btn btn-outline btn-xs" @click="selectDate(todayDate)">今天</button>
                <button type="button" class="btn btn-outline btn-xs" @click="selectDate(yesterdayDate)">昨天</button>
                <button
                  type="button"
                  class="btn btn-outline btn-xs"
                  :disabled="!latestAvailableDate"
                  @click="jumpToLatestAvailableDate"
                >
                  最近有录像
                </button>
                <span v-if="latestAvailableDate" class="date-panel-latest">
                  最近：{{ latestAvailableDate }}
                </span>
              </div>
            </div>
          </div>
          <div class="timeline-bar-container">
            <div
              class="timeline-bar-wrapper"
              :class="{ dragging: isDraggingTimeline }"
              ref="timelineWrapper"
              @wheel.prevent="onWheel"
              @touchstart="onTouchStart"
              @touchmove="onTouchMove"
              @touchend="onTouchEnd"
              @touchcancel="onTouchEnd"
              @scroll="onScroll"
              @mousedown="onDragStart"
            >
              <div class="timeline-bar-inner" :class="{ 'is-mobile': isMobile }">
                <div v-if="isMobile" class="timeline-track-spacer" :style="{ width: halfWrapWidth + 'px' }"></div>
                <!-- 背景横轴 24h -->
                <div
                  class="timeline-track"
                  ref="timelineTrack"
                  :style="{ width: (timelineScale * 100) + '%' }"
                  @mousemove="onTrackMouseMove"
                  @mouseleave="onTrackMouseLeave"
                  @click="onTrackClick"
                >
                  <!-- 刻度线 -->
                <div v-for="(tick, idx) in computedTicks" :key="idx" class="timeline-tick" :class="{ 'major-tick': tick.isMajor }" :style="{ left: tick.leftPercent + '%' }">
                  <span class="tick-label" v-if="tick.showLabel">{{ tick.labelText }}</span>
                </div>
                  
                  <!-- 录制片段 -->
                  <div 
                    v-for="(seg, idx) in normalizedSegments" 
                    :key="idx" 
                    class="timeline-segment"
                    :class="[`timeline-segment--${seg.formatTag}`, `timeline-segment-status--${seg.statusTag}`]"
                    :style="{ left: seg.left + '%', width: seg.width + '%' }"
                    :title="seg.startTimeText + ' - ' + seg.endTimeText + ' [' + seg.formatText + ' | ' + seg.statusText + ']'"
                  ></div>

                  <div v-if="!isMobile" class="timeline-cursor playhead" :style="{ left: cursorLeft + '%' }"></div>
                  <div
                    v-if="!isMobile && hoverCursorVisible"
                    class="timeline-cursor hover-cursor"
                    :style="{ left: hoverCursorLeft + '%' }"
                  ></div>
                </div>
                <div v-if="isMobile" class="timeline-track-spacer" :style="{ width: halfWrapWidth + 'px' }"></div>
              </div>
            </div>
            <div v-if="isMobile" class="timeline-cursor fixed-center"></div>
          </div>
        </div>
      </div>
    </Teleport>
    <Teleport :to="availableDatePanelTarget">
      <div
        v-if="showAvailableDatePanel"
        class="available-date-modal-overlay"
        :class="{ 'available-date-modal-overlay--fullscreen': isFullscreen }"
        @click="closeAvailableDatePanel"
      >
        <div class="available-date-panel" role="dialog" aria-modal="true" @click.stop>
          <div class="available-date-panel-header">
            <div class="available-date-panel-title">有录像日历</div>
            <button type="button" class="btn btn-outline btn-xs" @click="closeAvailableDatePanel">关闭</button>
          </div>
          <div v-if="latestAvailableDate" class="available-date-panel-meta">
            最近有录像：{{ latestAvailableDate }}
          </div>
          <div class="available-month-tabs">
            <button
              v-for="month in availableMonthsDesc"
              :key="month"
              type="button"
              class="available-month-tab"
              :class="{ active: month === selectedAvailableMonth }"
              @click="selectedAvailableMonth = month"
            >
              {{ formatMonthLabel(month) }}
            </button>
          </div>
          <div v-if="selectedMonthDateItems.length" class="available-day-grid">
            <button
              v-for="item in selectedMonthDateItems"
              :key="item.date"
              type="button"
              class="available-day-item"
              :class="{ active: item.date === currentDate }"
              @click="pickAvailableDate(item.date)"
            >
              <span class="day">{{ item.date.slice(8, 10) }}</span>
              <span class="count">{{ item.count }}</span>
            </button>
          </div>
          <div v-else class="available-day-empty">该月份暂无可播放片段</div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, computed, nextTick, watch } from 'vue';
import Icon from '@/components/common/Icon.vue';
import GpuRuntimeInline from '@/components/common/GpuRuntimeInline.vue';
import mpegts from 'mpegts.js';
import { playerApi } from '@/api/player';
import { systemApi } from '@/api/system';
import { useTimelineResume } from '@/composables/useTimelineResume';

const props = defineProps({
  subId: String,
  subName: String,
  subAvatar: String,
  subPlatformName: String,
  date: String,
  resumeAt: [String, Number],
});

const emit = defineEmits(['date-change']);

// 视频组件 ref
const video0 = ref(null);
const video1 = ref(null);
const playerViewport = ref(null);
const timelineWrapper = ref(null);
const timelineTrack = ref(null);
const fullscreenControlsRef = ref(null);
const fullscreenControlsInnerRef = ref(null);

// 状态
const loading = ref(false);
const playing = ref(false);
const activeVideo = ref(0);
const segments = ref([]);
const playTimeOfDay = ref(0); // 0 到 86400 (当天秒数)
const currentDate = ref(props.date || getLocalDateString());
const availableDateItems = ref([]);
const availableDatesLoading = ref(false);
const availableDatesError = ref('');
const showAvailableDatePanel = ref(false);
const selectedAvailableMonth = ref('');
const currentSegmentIndex = ref(-1); // 当前播放的片段索引
const timelineScale = ref(1); // 时间轴缩放倍率，默认 1
const isMobile = ref(false);
const currentSegmentOffset = ref(0);
const currentSegmentMediaTimeBase = ref(0);
const isDraggingTimeline = ref(false);
const isTimelineSeeking = ref(false);
const timelineNotice = ref('');
const RESUME_SAVE_INTERVAL_MS = 15 * 1000;
const RESUME_VISIBILITY_MAX_INPLACE_MS = 60 * 60 * 1000;
let resumeSaveInterval = null;
const RESUME_BROADCAST_CHANNEL = 'timeline-resume-updated';
const autoJumpedDate = ref('');
const pendingAutoJumpNotice = ref({ date: '', message: '' });
const hoverCursorLeft = ref(0);
const hoverCursorVisible = ref(false);
const desktopDragMoved = ref(false);
const isDesktopManualBrowse = ref(false);
const isTouchDevice = ref(false);
const TIMELINE_QUALITY_KEY = 'timeline_player_quality';
const TIMELINE_MUTED_KEY = 'timeline_player_muted';
const TIMELINE_SPEED_KEY = 'timeline_player_speed';
const PLAYBACK_SPEED_OPTIONS = [0.75, 1, 1.25, 1.5, 2];
const timelineQualityOptions = [
  { value: 'original', label: '原画' },
  { value: '1080p', label: '1080p' },
  { value: '720p', label: '720p' },
  { value: '480p', label: '480p' },
  { value: '360p', label: '360p' }
];
const TS_AUTO_TRANSCODE_QUALITY = '1080p';
const DANMU_MODE_KEY = 'timeline_danmu_mode';
const danmuMode = ref('marquee');
const danmuItems = ref([]);
const danmuAvailable = ref(true);
const danmuKeySet = new Set();
let danmuSocket = null;
let danmuSocketReconnectTimer = null;
let danmuTickTimer = null;
const DANMU_PREFETCH_SECONDS = 30;
const DANMU_RECONNECT_DELAY_MS = 2000;

const danmuVisible = computed(() => danmuMode.value !== 'off');

const danmuModeLabel = computed(() => {
  if (danmuMode.value === 'marquee') return '弹幕: 横向滚动';
  if (danmuMode.value === 'list') return '弹幕: 纵向列表';
  return '弹幕: 关闭';
});

const danmuModeShort = computed(() => {
  if (danmuMode.value === 'marquee') return '横';
  if (danmuMode.value === 'list') return '纵';
  return '关';
});

const toggleDanmuMode = () => {
  const order = ['marquee', 'list', 'off'];
  const idx = order.indexOf(danmuMode.value);
  const next = order[(idx + 1) % order.length] || 'marquee';
  danmuMode.value = next;
  localStorage.setItem(DANMU_MODE_KEY, next);
};

const danmuStatusText = computed(() => {
  const nowTs = getCurrentTs();
  if (!danmuVisible.value) return '弹幕: 关闭';
  if (!nowTs) return '弹幕: 未就绪';
  if (danmuMode.value === 'marquee') return '弹幕: 横向';
  if (danmuMode.value === 'list') return '弹幕: 纵向';
  return '弹幕: 关闭';
});

function normalizeTimelineQuality(value) {
  const allowed = new Set(timelineQualityOptions.map((item) => item.value));
  return allowed.has(value) ? value : 'original';
}

const timelineQuality = ref(normalizeTimelineQuality(localStorage.getItem(TIMELINE_QUALITY_KEY) || 'original'));
const timelineQualityLabel = computed(() => {
  const found = timelineQualityOptions.find((item) => item.value === timelineQuality.value);
  return found?.label || '原画';
});

const getDateBaseTs = (dateStr) => {
  if (!dateStr) return null;
  const date = new Date(`${dateStr}T00:00:00`);
  const ts = date.getTime();
  if (Number.isNaN(ts)) return null;
  return Math.floor(ts / 1000);
};

const getCurrentTs = () => {
  const base = getDateBaseTs(currentDate.value);
  if (base === null) return null;
  return base + Math.max(0, Number(playTimeOfDay.value) || 0);
};


const formatDanmuLine = (item) => {
  const nickname = item?.user?.nickname || item?.user?.name || '用户';
  const content = String(item?.content || '').trim();
  return `${nickname}：${content}`;
};
const isFullscreen = ref(false);
const isMuted = ref(localStorage.getItem(TIMELINE_MUTED_KEY) === 'true');
const isPipActive = ref(false);
const tripleScreenMode = ref(Number(localStorage.getItem('timeline_triple_screen') || '0'));
if (![0, 3, 4].includes(tripleScreenMode.value)) tripleScreenMode.value = 0;
const isVerticalVideo = ref(false);
const videoAspectRatio = ref(0);
const mirrorCanvasLeft = ref(null);
const mirrorCanvasRight = ref(null);
const mirrorCanvasFarLeft = ref(null);
let tripleScreenRAF = null;
const fullscreenControlsVisible = ref(false);
const fullscreenControlsHovering = ref(false);
const fullscreenControlsTouching = ref(false);
const lastInputType = ref('mouse');
let fullscreenHideTimer = null;
const availableDatePanelTarget = computed(() => (
  isFullscreen.value && playerViewport.value ? playerViewport.value : 'body'
));

const scheduleHideFullscreenControls = () => {
  if (!isFullscreen.value) return;
  if (fullscreenControlsHovering.value) return;
  if (isTouchDevice.value && fullscreenControlsTouching.value) return;
  if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
  fullscreenHideTimer = setTimeout(() => {
    if (!fullscreenControlsHovering.value && !(isTouchDevice.value && fullscreenControlsTouching.value)) {
      fullscreenControlsVisible.value = false;
    }
  }, 1800);
};

const showFullscreenControls = () => {
  if (!isFullscreen.value) return;
  lastInputType.value = 'mouse';
  fullscreenControlsVisible.value = true;
  scheduleHideFullscreenControls();
};

const handleViewportMouseMove = () => {
  lastInputType.value = 'mouse';
};

const handleViewportMouseLeave = () => {
  if (!isFullscreen.value) return;
  if (lastInputType.value === 'mouse') {
    fullscreenControlsVisible.value = false;
    if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
    return;
  }
  scheduleHideFullscreenControls();
};

const handleViewportTouchStart = (event) => {
  if (!isFullscreen.value || !isTouchDevice.value) return;
  lastInputType.value = 'touch';
  const target = event?.target;
  const controlsEl = fullscreenControlsRef.value;
  if (controlsEl && target && controlsEl.contains(target)) {
    fullscreenControlsTouching.value = true;
    fullscreenControlsVisible.value = true;
    if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
  }
};

const handleFullscreenTouchLayer = (event) => {
  if (!isFullscreen.value || !isTouchDevice.value) return;
  lastInputType.value = 'touch';
  if (fullscreenControlsVisible.value) {
    fullscreenControlsTouching.value = false;
    fullscreenControlsVisible.value = false;
  } else {
    fullscreenControlsTouching.value = true;
    fullscreenControlsVisible.value = true;
    // 第一个 touch 点亮屏幕时，防止穿透触发按钮
    if (event?.preventDefault) event.preventDefault();
  }
  if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
};

const handleViewportTouchEnd = () => {
  if (!isFullscreen.value || !isTouchDevice.value) return;
  fullscreenControlsTouching.value = false;
  scheduleHideFullscreenControls();
};

const handleFullscreenControlsEnter = () => {
  if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
  lastInputType.value = 'mouse';
  fullscreenControlsHovering.value = true;
  fullscreenControlsVisible.value = true;
};

const handleFullscreenControlsLeave = () => {
  fullscreenControlsHovering.value = false;
  if (lastInputType.value === 'mouse') {
    fullscreenControlsVisible.value = false;
    if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
    return;
  }
  scheduleHideFullscreenControls();
};

const handleFullscreenControlsTouchStart = (event) => {
  if (!isFullscreen.value || !isTouchDevice.value) return;
  lastInputType.value = 'touch';
  fullscreenControlsTouching.value = true;
  
  if (!fullscreenControlsVisible.value) {
    fullscreenControlsVisible.value = true;
    // 第一个 touch 点亮屏幕时，防止直接点击到里面的按钮
    if (event?.preventDefault) event.preventDefault();
  }
  
  if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
};

const handleFullscreenControlsTouchEnd = () => {
  if (!isFullscreen.value || !isTouchDevice.value) return;
  fullscreenControlsTouching.value = false;
  scheduleHideFullscreenControls();
};

const handleGlobalTouchEnd = () => {
  if (!isFullscreen.value || !isTouchDevice.value) return;
  fullscreenControlsTouching.value = false;
  scheduleHideFullscreenControls();
};

const handleGlobalMouseMove = (event) => {
  if (!isFullscreen.value) return;
  // 如果是触摸设备且当前正处于触摸操作中，不应响应全局鼠标移动带来的显隐切换
  if (isTouchDevice.value && lastInputType.value === 'touch') return;
  const target = event?.target;
  const innerEl = fullscreenControlsInnerRef.value;
  if (innerEl && target && innerEl.contains(target)) {
    if (!fullscreenControlsVisible.value) {
      fullscreenControlsVisible.value = true;
      if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
    }
    return;
  }
  if (fullscreenControlsVisible.value) {
    fullscreenControlsVisible.value = false;
    if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
  }
};

function normalizePlaybackSpeed(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  const matched = PLAYBACK_SPEED_OPTIONS.find((v) => Math.abs(v - parsed) < 0.001);
  return matched || 1;
}

const playbackSpeed = ref(normalizePlaybackSpeed(localStorage.getItem(TIMELINE_SPEED_KEY) || '1'));
const playbackSpeedLabel = computed(() => (
  Number.isInteger(playbackSpeed.value) ? `${playbackSpeed.value}x` : `${playbackSpeed.value.toFixed(2).replace(/0$/, '')}x`
));

function withTsAutoNotice(baseNotice = '') {
  const cleaned = String(baseNotice || '')
    .replace(/\s*TS 片段在“原画”下默认使用[^。]*。?/g, '')
    .trim();
  const hasTsSegment = segments.value.some((seg) => String(seg?.format || '').toLowerCase() === 'ts');
  if (!(hasTsSegment && timelineQuality.value === 'original')) {
    return cleaned;
  }
  const notice = `TS 原画默认 ${TS_AUTO_TRANSCODE_QUALITY} 转码播放，提升起播稳定性。`;
  return cleaned ? `${cleaned} ${notice}` : notice;
}

const subDisplayName = computed(() => String(props.subName || '').trim());
const subInitial = computed(() => {
  const first = Array.from(subDisplayName.value || '播')[0];
  return first || '播';
});
const todayDate = computed(() => getLocalDateString());
const yesterdayDate = computed(() => getDateOffsetString(-1));
const showTripleScreen = computed(() => tripleScreenMode.value > 0 && isVerticalVideo.value);
const tripleScreenModeShort = computed(() => {
  if (tripleScreenMode.value === 3) return '三连';
  if (tripleScreenMode.value === 4) return '四连';
  return '多屏：关';
});
const tripleScreenModeLabel = computed(() => {
  if (tripleScreenMode.value === 3) return '三连屏模式';
  if (tripleScreenMode.value === 4) return '四连屏模式';
  return '关闭多连屏';
});
const tripleLayoutStyle = computed(() => {
  if (!showTripleScreen.value) return {};
  const ar = videoAspectRatio.value > 0 ? videoAspectRatio.value : 0.5625;
  return { '--video-aspect-ratio': String(ar) };
});
const latestAvailableDate = computed(() => {
  if (!availableDateItems.value.length) return '';
  return availableDateItems.value[availableDateItems.value.length - 1].date;
});
const availableDateSet = computed(() => new Set(availableDateItems.value.map((item) => item.date)));
const isCurrentDateAvailable = computed(() => availableDateSet.value.has(currentDate.value));
const prevAvailableDate = computed(() => findAdjacentAvailableDate(currentDate.value, -1));
const nextAvailableDate = computed(() => findAdjacentAvailableDate(currentDate.value, 1));
const availableMonthMap = computed(() => {
  const monthMap = new Map();
  availableDateItems.value.forEach((item) => {
    const monthKey = String(item?.date || '').slice(0, 7);
    if (!monthKey) return;
    if (!monthMap.has(monthKey)) monthMap.set(monthKey, []);
    monthMap.get(monthKey).push(item);
  });
  return monthMap;
});
const availableMonthsDesc = computed(() => (
  Array.from(availableMonthMap.value.keys()).sort((a, b) => b.localeCompare(a))
));
const selectedMonthDateItems = computed(() => {
  if (!selectedAvailableMonth.value) return [];
  return availableMonthMap.value.get(selectedAvailableMonth.value) || [];
});

const encoderLabel = ref('');
const transcodeStatus = ref({});
let encoderRefreshInterval = null;
const gpuStatusLoading = ref(true);
const gpuStatusError = ref('');
const gpuStatusData = ref({ summary: { has_gpu: false, transcode_enabled: false }, gpus: [] });
let gpuRefreshInterval = null;

// Touch zoom variables
let initialPinchDist = 0;
let initialScale = 1;

let flvPlayer0 = null;
let flvPlayer1 = null;
let lastProgrammaticScrollLeft = -1;
let ignoreMobileScrollUntil = 0;
let isTouchTimelineInteracting = false;
let scrollTimeout = null;
let mobileTouchEndListening = false;
const isUserScrolling = ref(false);
const halfWrapWidth = ref(0);
let dragStartX = 0;
let dragStartScrollLeft = 0;
let resizeHandler = null;
let suppressTrackClickOnce = false;
let visibilityResumeTimer = null;
let localSeekRetryTimers = [];
let tsNudgeTimer = null;
let lastTsNudgeAt = 0;
let hiddenAtMs = 0;
let timelineLiveRefreshInterval = null;
let timelineLiveRefreshing = false;
const timelineLiveRefreshMs = 4000;

const setTimelineLiveRefreshEnabled = (enabled) => {
  if (!enabled) {
    if (timelineLiveRefreshInterval) {
      clearInterval(timelineLiveRefreshInterval);
      timelineLiveRefreshInterval = null;
    }
    return;
  }
  if (timelineLiveRefreshInterval) return;
  timelineLiveRefreshInterval = setInterval(() => {
    refreshTimelineIncremental();
  }, timelineLiveRefreshMs);
};

const updateHalfWidth = () => {
  if (timelineWrapper.value) {
    halfWrapWidth.value = timelineWrapper.value.clientWidth / 2;
  }
};

function getLocalDateString() {
  const now = new Date();
  const y = now.getFullYear();
  const m = `${now.getMonth() + 1}`.padStart(2, '0');
  const d = `${now.getDate()}`.padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function normalizeDateString(value) {
  const normalized = String(value || '').trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(normalized) ? normalized : '';
}

function normalizeResumeAt(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return 0;
  return Math.max(0, Math.min(86400, parsed));
}

function getDateOffsetString(offsetDays = 0) {
  const now = new Date();
  now.setDate(now.getDate() + Number(offsetDays || 0));
  const y = now.getFullYear();
  const m = `${now.getMonth() + 1}`.padStart(2, '0');
  const d = `${now.getDate()}`.padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function sortDateItems(items = []) {
  return [...items].sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

function formatMonthLabel(monthKey) {
  if (!/^\d{4}-\d{2}$/.test(String(monthKey || ''))) return monthKey || '';
  const [year, month] = String(monthKey).split('-');
  return `${year}年${month}月`;
}

function findAdjacentAvailableDate(baseDate, direction = 1) {
  const normalizedBase = normalizeDateString(baseDate);
  if (!normalizedBase || !availableDateItems.value.length) return '';
  const allDates = availableDateItems.value.map((item) => item.date);
  if (direction < 0) {
    for (let i = allDates.length - 1; i >= 0; i -= 1) {
      if (allDates[i] < normalizedBase) return allDates[i];
    }
    return '';
  }
  for (let i = 0; i < allDates.length; i += 1) {
    if (allDates[i] > normalizedBase) return allDates[i];
  }
  return '';
}

const loadAvailableDates = async () => {
  if (!props.subId) return;
  availableDatesLoading.value = true;
  availableDatesError.value = '';
  try {
    const res = await fetch(`/api/live/timeline/${props.subId}/dates`, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      }
    });
    const data = await res.json();
    if (!data?.success) {
      availableDateItems.value = [];
      availableDatesError.value = '可用日期加载失败';
      return;
    }

    const parsed = Array.isArray(data.data) ? data.data : [];
    const validItems = parsed
      .map((item) => {
        const date = normalizeDateString(item?.date);
        const count = Math.max(0, Number(item?.count || 0));
        return date ? { date, count } : null;
      })
      .filter(Boolean);

    availableDateItems.value = sortDateItems(validItems);
  } catch (error) {
    console.warn('load timeline available dates failed', error);
    availableDateItems.value = [];
    availableDatesError.value = '可用日期加载失败';
  } finally {
    availableDatesLoading.value = false;
  }
};

const {
  wasPlayingBeforeHidden,
  hiddenPlayTimeOfDay,
  hiddenSegmentIndex,
  hiddenSegmentOffset,
  setHiddenResumeState,
  clearHiddenResumeState,
  saveResumeState,
  loadResumeState,
  consumePendingResume
} = useTimelineResume({
  getStorageKey: () => `${props.subId || ''}|${currentDate.value || ''}`,
  getFallbackKey: () => `${props.subId || ''}|__latest__`
});

// 从 API 加载录像片段
const loadTimelineEvents = async (dateStr) => {
  loading.value = true;
  timelineNotice.value = '';
  let handedOffToPlayerLoading = false;
  try {
    const res = await fetch(`/api/live/timeline/${props.subId}?date=${dateStr}`, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      }
    });
    const data = await res.json();
    if (data.success) {
      segments.value = data.data;
      const skippedNonPlayable = Number(
        data?.meta?.skipped_non_playable ?? data?.meta?.skipped_non_mp4 ?? 0
      );
      const normalizedDate = normalizeDateString(dateStr);
      if (segments.value.length > 0) {
        if (normalizedDate && !availableDateSet.value.has(normalizedDate)) {
          availableDateItems.value = sortDateItems([
            ...availableDateItems.value,
            { date: normalizedDate, count: segments.value.length }
          ]);
        }
        if (skippedNonPlayable > 0) {
          timelineNotice.value = `已忽略 ${skippedNonPlayable} 条非 MP4/TS 录制。TS 片段采用兼容模式，定位可能有轻微偏差。`;
        }
        const recordingCount = Number(data?.meta?.status_counts?.recording || 0);
        if (recordingCount > 0 && !timelineNotice.value) {
          timelineNotice.value = `当前有 ${recordingCount} 条“录制中”片段，定位和时长会实时变化。`;
        }
        timelineNotice.value = withTsAutoNotice(timelineNotice.value);
        if (pendingAutoJumpNotice.value.message && pendingAutoJumpNotice.value.date === normalizedDate) {
          timelineNotice.value = timelineNotice.value
            ? `${pendingAutoJumpNotice.value.message} ${timelineNotice.value}`
            : pendingAutoJumpNotice.value.message;
          pendingAutoJumpNotice.value = { date: '', message: '' };
        }
        setTimelineLiveRefreshEnabled(recordingCount > 0);
        autoJumpedDate.value = '';
        // 优先恢复到最近一次会话位置；否则从第一个片段开始。
        const pendingResume = consumePendingResume();
        const resumeTarget = Math.max(0, Math.min(86400, Number(pendingResume.timeOfDay) || 0));
        const resumeSegmentIndex = Number.isInteger(pendingResume.segmentIndex) ? pendingResume.segmentIndex : -1;
        const resumeSegmentOffset = Math.max(0, Number(pendingResume.segmentOffset) || 0);
        const resumeOverride = normalizeResumeAt(props.resumeAt);
        const finalResumeTarget = resumeTarget > 0 ? resumeTarget : resumeOverride;
        const shouldResume = finalResumeTarget > 0;
        const resumeExtras = pendingResume.extras || {};
        if (resumeExtras.timelineQuality) {
          timelineQuality.value = normalizeTimelineQuality(resumeExtras.timelineQuality);
          localStorage.setItem(TIMELINE_QUALITY_KEY, timelineQuality.value);
        }
        if (resumeExtras.playbackSpeed) {
          playbackSpeed.value = normalizePlaybackSpeed(resumeExtras.playbackSpeed);
          localStorage.setItem(TIMELINE_SPEED_KEY, String(playbackSpeed.value));
          applyPlaybackPreferences();
        }
        if (shouldResume) {
          const resumeSeg = segments.value[resumeSegmentIndex];
          if (resumeSeg) {
            const segStart = getSegmentStartOffset(resumeSeg);
            const segDuration = Math.max(0, Number(resumeSeg.duration) || 0);
            const safeOffset = Math.max(0, Math.min(segDuration, resumeSegmentOffset));
            playTimeOfDay.value = segStart + safeOffset;
            isTimelineSeeking.value = true;
            playing.value = true;
            handedOffToPlayerLoading = true;
            playSegment(resumeSegmentIndex, safeOffset);
          } else {
            playTimeOfDay.value = finalResumeTarget;
            handedOffToPlayerLoading = playFromTime(finalResumeTarget);
          }
          if (!handedOffToPlayerLoading) {
            const firstSegStart = getSegmentStartOffset(segments.value[0]);
            playTimeOfDay.value = firstSegStart;
            playSegment(0, 0);
            handedOffToPlayerLoading = true;
          }
          // 恢复播放时一律尝试自动起播；失败则保持暂停
          nextTick(() => {
            const currentV = activeVideo.value === 0 ? video0.value : video1.value;
            if (!currentV) return;
            currentV.play().then(() => {
              playing.value = true;
            }).catch(() => {
              playing.value = false;
            });
          });
        } else {
          const firstSegStart = getSegmentStartOffset(segments.value[0]);
          playTimeOfDay.value = firstSegStart;
          playSegment(0, 0);
          handedOffToPlayerLoading = true;
        }

        // 自动将时间轴滚动到对应的播放位置，使其居中
        nextTick(() => {
          centerTimelineOn(playTimeOfDay.value);
        });
      } else {
        stopAll();
        loading.value = false;
        setTimelineLiveRefreshEnabled(false);
        const latestDate = latestAvailableDate.value;
        if (latestDate && latestDate !== normalizedDate && autoJumpedDate.value !== normalizedDate) {
          autoJumpedDate.value = normalizedDate;
          pendingAutoJumpNotice.value = {
            date: latestDate,
            message: `当前日期暂无可播放片段，已为你跳转到最近有录像日期 ${latestDate}。`
          };
          selectDate(latestDate);
          return;
        }
        timelineNotice.value = skippedNonPlayable > 0
          ? `当前日期没有可播放的 MP4/TS 片段（已忽略 ${skippedNonPlayable} 条不支持格式录制）。`
          : '当前日期暂无可播放片段。';
      }
    } else {
      loading.value = false;
      setTimelineLiveRefreshEnabled(false);
    }
  } catch (err) {
    console.error("加载时间轴失败", err);
    loading.value = false;
    setTimelineLiveRefreshEnabled(false);
    timelineNotice.value = '时间轴加载失败，请稍后重试。';
  } finally {
    if (!handedOffToPlayerLoading) {
      loading.value = false;
    }
  }
};

const resetDanmuBuffer = () => {
  danmuItems.value = [];
  danmuKeySet.clear();
  danmuAvailable.value = true;
};

const danmuListRef = ref(null);
const danmuListStickToBottom = ref(true);
const danmuListUserHold = ref(false);

const handleDanmuListScroll = () => {
  const el = danmuListRef.value;
  if (!el) return;
  const threshold = 16;
  const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - threshold;
  danmuListStickToBottom.value = atBottom;
  danmuListUserHold.value = !atBottom;
};

const scrollDanmuListToBottom = () => {
  const el = danmuListRef.value;
  if (!el) return;
  el.scrollTop = el.scrollHeight;
};

const jumpDanmuListToLatest = () => {
  danmuListUserHold.value = false;
  danmuListStickToBottom.value = true;
  nextTick(scrollDanmuListToBottom);
};

const danmuListItems = computed(() => {
  return danmuItems.value
    .filter((item) => {
      if (!item?.content) return false;
      const method = item?.method || '';
      const eventType = item?.event_type || '';
      if (eventType && eventType !== 'chat') return false;
      if (!eventType && method && method !== 'WebcastChatMessage') return false;
      return true;
    })
    .slice(-200);
});

const DANMU_MARQUEE_LANES = 7;
const DANMU_MARQUEE_GAP_MS = 450;
const DANMU_MARQUEE_MAX_ACTIVE = 60;
const marqueeItems = ref([]);
const marqueeLaneNextAt = Array.from({ length: DANMU_MARQUEE_LANES }, () => 0);

const calcMarqueeDuration = (text) => {
  const len = String(text || '').length;
  const base = 12;
  const extra = Math.min(22, len * 0.3);
  return Math.max(12, Math.min(32, base + extra));
};

const enqueueMarquee = (item) => {
  if (danmuMode.value !== 'marquee') return;
  if (marqueeItems.value.length >= DANMU_MARQUEE_MAX_ACTIVE) return;
  const text = formatDanmuLine(item);
  if (!text) return;
  const now = Date.now();
  let lane = 0;
  let earliest = marqueeLaneNextAt[0];
  for (let i = 1; i < marqueeLaneNextAt.length; i += 1) {
    if (marqueeLaneNextAt[i] < earliest) {
      earliest = marqueeLaneNextAt[i];
      lane = i;
    }
  }
  const duration = calcMarqueeDuration(text);
  const startAt = Math.max(now, earliest);
  marqueeLaneNextAt[lane] = startAt + duration * 1000 + DANMU_MARQUEE_GAP_MS;

  const laneStep = DANMU_MARQUEE_LANES > 1 ? 70 / (DANMU_MARQUEE_LANES - 1) : 0;
  const topPercent = 10 + lane * laneStep;

  const createItem = () => {
    if (danmuMode.value !== 'marquee') return;
    const id = `${item._id || ''}-${startAt}`;
    const style = {
      top: `${topPercent}%`,
      animationDuration: `${duration}s`
    };
    marqueeItems.value.push({ id, text, style });
    const cleanupDelay = duration * 1000 + 80;
    setTimeout(() => {
      marqueeItems.value = marqueeItems.value.filter((m) => m.id !== id);
    }, cleanupDelay);
  };

  const delayMs = Math.max(0, startAt - now);
  if (delayMs > 0) {
    setTimeout(createItem, delayMs);
  } else {
    createItem();
  }
};

const appendDanmuItems = (items) => {
  items.forEach((item) => {
    const ts = Number(item.ts) || 0;
    const content = String(item.content || '');
    const userId = item?.user?.id || '';
    const key = `${ts}-${userId}-${content}`;
    if (danmuKeySet.has(key)) return;
    danmuKeySet.add(key);
    item._id = key;
    danmuItems.value.push(item);
    enqueueMarquee(item);
  });
  const maxItems = 200;
  if (danmuItems.value.length > maxItems) {
    danmuItems.value.splice(0, danmuItems.value.length - maxItems);
  }
  if (danmuMode.value === 'list' && danmuListStickToBottom.value && !danmuListUserHold.value) {
    nextTick(scrollDanmuListToBottom);
  }
};

const buildDanmuWsUrl = () => {
  const token = localStorage.getItem('token') || '';
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const base = `${proto}://${window.location.host}/api/ws/subscribe/danmu/${props.subId}`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
};

const closeDanmuSocket = () => {
  if (danmuSocketReconnectTimer) {
    clearTimeout(danmuSocketReconnectTimer);
    danmuSocketReconnectTimer = null;
  }
  if (danmuTickTimer) {
    clearInterval(danmuTickTimer);
    danmuTickTimer = null;
  }
  if (danmuSocket) {
    try {
      danmuSocket.close();
    } catch (error) {
      // ignore
    }
    danmuSocket = null;
  }
};

const scheduleDanmuReconnect = () => {
  if (danmuSocketReconnectTimer) return;
  danmuSocketReconnectTimer = setTimeout(() => {
    danmuSocketReconnectTimer = null;
    openDanmuSocket();
  }, DANMU_RECONNECT_DELAY_MS);
};

const handleDanmuMessage = (payload) => {
  if (!payload || typeof payload !== 'object') return;
  if (payload.type !== 'danmu') return;
  if (Array.isArray(payload.data)) {
    appendDanmuItems(payload.data);
  }
  if (payload.meta) {
    if ((payload?.meta?.files_checked || 0) > 0) {
      danmuAvailable.value = true;
    }
  }
};

const sendDanmuReset = () => {
  if (!danmuVisible.value || !props.subId || !danmuAvailable.value) return;
  if (!danmuSocket || danmuSocket.readyState !== 1) return;
  const nowTs = getCurrentTs();
  if (!nowTs) return;
  const startTs = Math.max(0, nowTs - 5);
  const endTs = startTs + DANMU_PREFETCH_SECONDS;
  const payload = {
    type: 'reset',
    start_ts: startTs,
    end_ts: endTs,
    limit: 2000
  };
  danmuSocket.send(JSON.stringify(payload));
};

const sendDanmuTick = () => {
  if (!danmuVisible.value || !props.subId || !danmuAvailable.value) return;
  if (!danmuSocket || danmuSocket.readyState !== 1) return;
  const nowTs = getCurrentTs();
  if (!nowTs) return;
  danmuSocket.send(JSON.stringify({ type: 'tick', ts: nowTs }));
};

const openDanmuSocket = (resetBuffer = false) => {
  if (!props.subId) return;
  closeDanmuSocket();
  if (resetBuffer) resetDanmuBuffer();
  danmuAvailable.value = true;
  try {
    danmuSocket = new WebSocket(buildDanmuWsUrl());
  } catch (error) {
    scheduleDanmuReconnect();
    return;
  }
  danmuSocket.onopen = () => {
    sendDanmuReset();
    if (danmuTickTimer) clearInterval(danmuTickTimer);
    danmuTickTimer = setInterval(() => {
      sendDanmuTick();
    }, 1000);
  };
  danmuSocket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      handleDanmuMessage(payload);
    } catch (error) {
      // ignore malformed payloads
    }
  };
  danmuSocket.onerror = () => {
    scheduleDanmuReconnect();
  };
  danmuSocket.onclose = () => {
    scheduleDanmuReconnect();
  };
};

const refreshTimelineIncremental = async () => {
  if (timelineLiveRefreshing || !props.subId) return;
  timelineLiveRefreshing = true;
  try {
    const res = await fetch(`/api/live/timeline/${props.subId}?date=${currentDate.value}`, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      }
    });
    const data = await res.json();
    if (!data?.success || !Array.isArray(data?.data)) return;

    const prevSeg = segments.value[currentSegmentIndex.value];
    const prevPlayUrl = String(prevSeg?.play_url || '');
    segments.value = data.data;

    const skippedNonPlayable = Number(
      data?.meta?.skipped_non_playable ?? data?.meta?.skipped_non_mp4 ?? 0
    );
    const recordingCount = Number(data?.meta?.status_counts?.recording || 0);
    if (skippedNonPlayable > 0) {
      timelineNotice.value = `已忽略 ${skippedNonPlayable} 条非 MP4/TS 录制。TS 片段采用兼容模式，定位可能有轻微偏差。`;
    } else if (recordingCount > 0) {
      timelineNotice.value = `当前有 ${recordingCount} 条“录制中”片段，定位和时长会实时变化。`;
    } else {
      timelineNotice.value = '';
    }
    timelineNotice.value = withTsAutoNotice(timelineNotice.value);

    if (prevPlayUrl) {
      const nextIdx = segments.value.findIndex((item) => String(item?.play_url || '') === prevPlayUrl);
      if (nextIdx >= 0) {
        currentSegmentIndex.value = nextIdx;
      }
    }
    setTimelineLiveRefreshEnabled(recordingCount > 0);
  } catch (err) {
    console.warn('timeline incremental refresh failed', err);
  } finally {
    timelineLiveRefreshing = false;
  }
};

const getSegmentStartOffset = (seg) => {
  if (!seg?.start_time) return 0;
  const dt = new Date(seg.start_time);
  if (Number.isNaN(dt.getTime())) return 0;

  const normalizedDate = normalizeDateString(currentDate.value);
  if (normalizedDate) {
    const [y, m, d] = normalizedDate.split('-').map((item) => Number(item));
    const dayStart = new Date(y, (m || 1) - 1, d || 1, 0, 0, 0, 0);
    const offset = Math.floor((dt.getTime() - dayStart.getTime()) / 1000);
    return Math.max(0, Math.min(86400, offset));
  }

  return dt.getHours() * 3600 + dt.getMinutes() * 60 + dt.getSeconds();
};

const getSegmentEndOffset = (seg) => {
  return Math.max(0, Math.min(86400, getSegmentStartOffset(seg) + Number(seg?.duration || 0)));
};

// 预处理用于渲染的片段信息
const normalizedSegments = computed(() => {
  return segments.value.map(seg => {
    const startSec = getSegmentStartOffset(seg);
    const dt = new Date(seg.start_time);
    const endDt = new Date(dt.getTime() + seg.duration * 1000);
    return {
      left: (startSec / 86400) * 100,
      width: (seg.duration / 86400) * 100,
      startTimeText: `${dt.getHours().toString().padStart(2,'0')}:${dt.getMinutes().toString().padStart(2,'0')}:${dt.getSeconds().toString().padStart(2,'0')}`,
      endTimeText: `${endDt.getHours().toString().padStart(2,'0')}:${endDt.getMinutes().toString().padStart(2,'0')}:${endDt.getSeconds().toString().padStart(2,'0')}`,
      formatTag: String(seg?.format || '').trim().toLowerCase() || 'unknown',
      formatText: String(seg?.format || 'unknown').toUpperCase(),
      statusTag: String(seg?.status || '').trim().toLowerCase() || 'unknown',
      statusText: String(seg?.status || 'unknown').toUpperCase(),
      original: seg
    };
  });
});

const cursorLeft = computed(() => {
  return (playTimeOfDay.value / 86400) * 100;
});

const showTranscodeInfo = computed(() => timelineQuality.value !== 'original' && !!encoderLabel.value);
const gpuPrimaryVendorLabel = computed(() => {
  const gpuList = Array.isArray(gpuStatusData.value?.gpus) ? gpuStatusData.value.gpus : [];
  const normalizeVendor = (value) => {
    const text = String(value || '').trim().toLowerCase();
    if (!text) return '';
    if (text.includes('intel')) return 'intel';
    if (text.includes('nvidia')) return 'nvidia';
    if (text.includes('amd')) return 'amd';
    return text;
  };
  const parseGpuIndex = (value) => {
    if (value === undefined || value === null || value === '') return null;
    const parsed = Number.parseInt(String(value).trim(), 10);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const pickPreferred = (list) => {
    if (!Array.isArray(list) || list.length === 0) return null
    const ok = list.find((gpu) => String(gpu?.status || '').toLowerCase() === 'ok')
    if (ok) return ok
    const degradedUsable = list.find((gpu) => {
      const status = String(gpu?.status || '').toLowerCase()
      return status === 'degraded' && Boolean(gpu?.transcode_enabled)
    })
    if (degradedUsable) return degradedUsable
    const nonError = list.find((gpu) => String(gpu?.status || '').toLowerCase() !== 'error')
    return nonError || list[0] || null
  };
  const summary = gpuStatusData.value?.summary || {};
  const activeTranscoder = summary.active_transcoder || {};
  const activeVendor = normalizeVendor(summary.active_vendor || activeTranscoder.vendor);
  const activeHwaccel = String(summary.active_hwaccel || activeTranscoder.hardware || '').trim().toLowerCase();
  const activeGpuIndex = parseGpuIndex(summary.active_gpu_index ?? activeTranscoder.gpu_index);
  const explicitActive = gpuList.find((gpu) => Boolean(gpu?.is_active));
  let primaryGpu = explicitActive || null;
  if (!primaryGpu && activeVendor) {
    const sameVendor = gpuList.filter((gpu) => normalizeVendor(gpu?.vendor) === activeVendor);
    if (sameVendor.length > 0) {
      if (activeVendor === 'nvidia' && activeGpuIndex !== null) {
        primaryGpu = sameVendor.find((gpu) => parseGpuIndex(gpu?.index) === activeGpuIndex) || null;
      }
      if (!primaryGpu) primaryGpu = pickPreferred(sameVendor);
    }
  }
  if (!primaryGpu && activeHwaccel === 'vaapi') {
    const vaapiCapable = gpuList.filter((gpu) => {
      const backends = Array.isArray(gpu?.transcode_backends) ? gpu.transcode_backends : [];
      return backends.map((item) => String(item || '').toLowerCase()).includes('vaapi');
    });
    if (vaapiCapable.length > 0) primaryGpu = pickPreferred(vaapiCapable);
  }
  if (!primaryGpu) primaryGpu = pickPreferred(gpuList);
  const rawVendor = String(primaryGpu?.vendor || '').toLowerCase().trim();
  if (!rawVendor) return '';
  if (rawVendor.includes('intel')) return 'Intel';
  if (rawVendor.includes('nvidia')) return 'NVIDIA';
  if (rawVendor.includes('amd')) return 'AMD';
  return rawVendor.toUpperCase();
});

const transcodeHardwareLabel = computed(() => {
  const text = String(encoderLabel.value || '').toLowerCase();
  if (!text) return '';
  if (text.includes('nvenc') || text.includes('cuda')) return 'NVIDIA';
  if (text.includes('qsv')) return 'Intel';
  if (text.includes('amf')) return 'AMD';
  if (text.includes('vaapi')) return gpuPrimaryVendorLabel.value || 'GPU';
  if (text.includes('libx') || text.includes('svt') || text.includes('cpu')) return 'CPU';
  return gpuPrimaryVendorLabel.value || '';
});

const transcodeFrameInterpolationLabel = computed(() => {
  const payload = transcodeStatus.value || {};
  const active = Boolean(payload.frame_interpolation_active);
  if (!active) return '插帧×';
  const mode = String(payload.frame_interpolation_mode || '').toLowerCase();
  if (mode === '30to60') return '插帧30→60√';
  if (mode === '60to120') return '插帧60→120√';
  const target = Number(payload.frame_interpolation_target_fps);
  if (Number.isFinite(target) && target > 0) return `插帧→${Math.round(target)}√`;
  return '插帧√';
});

const displayTranscodeLabel = computed(() => {
  if (!showTranscodeInfo.value) return '';
  const hw = transcodeHardwareLabel.value;
  const base = hw ? `转码(${hw}): ${encoderLabel.value}` : `转码: ${encoderLabel.value}`;
  return `${base} · ${transcodeFrameInterpolationLabel.value}`;
});

const computedTicks = computed(() => {
  const ticks = [];
  const scale = timelineScale.value;
  let intervalSecs = 3600; // 默认大刻度（缩小时候）：1小时一个线
  let labelInterval = 2; // 默认每隔两条线显示一个文字（即每2小时标数字）
  
  if (scale >= 20) {
    intervalSecs = 60; // 1分钟一根线
    labelInterval = 5; // 5分钟标一次数字
  } else if (scale >= 12) {
    intervalSecs = 300; // 5分钟一根线
    labelInterval = 3; // 15分钟标一次数字
  } else if (scale >= 6) {
    intervalSecs = 900; // 15分钟一根线
    labelInterval = 4; // 1小时标一次数字
  } else if (scale >= 3) {
    intervalSecs = 1800; // 30分钟一根线
    labelInterval = 2; // 1小时标一次数字
  } else if (scale >= 1.5) {
    intervalSecs = 3600; // 1小时一根线
    labelInterval = 1; // 1小时标一次数字
  } else {
    intervalSecs = 3600; // 1小时一根线
    labelInterval = 2; // 2小时标一次数字
  }
  
  const totalTicks = Math.floor(86400 / intervalSecs);
  for (let i = 0; i <= totalTicks; i++) {
    const sec = i * intervalSecs;
    if (sec > 86400) break;
    
    // 是否显示这根线上的时刻文字
    const showLabel = i % labelInterval === 0;
    
    let labelText = '';
    if (showLabel) {
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      labelText = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
    }
    
    ticks.push({
      leftPercent: (sec / 86400) * 100,
      showLabel,
      labelText,
      isMajor: showLabel
    });
  }
  return ticks;
});

const formatTime = (seconds) => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h.toString().padStart(2,'0')}:${m.toString().padStart(2,'0')}:${s.toString().padStart(2,'0')}`;
};

// 清理所有播放器
const stopAll = () => {
  if (tsNudgeTimer) {
    clearTimeout(tsNudgeTimer);
    tsNudgeTimer = null;
  }
  lastTsNudgeAt = 0;
  const resetVideoElement = (el) => {
    if (!el) return;
    try {
      el.pause();
    } catch (err) {
      // noop
    }
    try {
      // 主动移除事件句柄，避免卸载阶段再次触发回调
      el.onloadeddata = null;
      el.onloadedmetadata = null;
      el.oncanplay = null;
      el.onerror = null;
      el.onended = null;
      el.ontimeupdate = null;
      el.onprogress = null;
      el.onwaiting = null;
      el.onstalled = null;
    } catch (err) {
      // noop
    }
    try {
      el.srcObject = null;
    } catch (err) {
      // noop
    }
    try {
      el.removeAttribute('src');
      el.src = '';
      // 触发浏览器立即中止当前媒体网络请求
      el.load();
    } catch (err) {
      // noop
    }
  };

  if (flvPlayer0) {
    flvPlayer0.destroy();
    flvPlayer0 = null;
  }
  if (flvPlayer1) {
    flvPlayer1.destroy();
    flvPlayer1 = null;
  }
  resetVideoElement(video0.value);
  resetVideoElement(video1.value);
  playing.value = false;
  isTimelineSeeking.value = false;
  currentSegmentMediaTimeBase.value = 0;
  stopTripleScreenLoop();
};

const getAllVideoElements = () => [video0.value, video1.value].filter(Boolean);

const applyPlaybackPreferences = (target = null) => {
  const targets = target ? [target] : getAllVideoElements();
  targets.forEach((video) => {
    try {
      video.playbackRate = playbackSpeed.value;
      video.muted = isMuted.value;
      video.defaultMuted = isMuted.value;
    } catch (err) {
      // noop
    }
  });
};

const updatePipState = () => {
  const pipElement = document.pictureInPictureElement;
  if (!pipElement) {
    isPipActive.value = false;
    return;
  }
  isPipActive.value = pipElement === video0.value || pipElement === video1.value;
};

// 播放指定的片段
const playSegment = (index, offsetSeconds) => {
  if (index < 0 || index >= segments.value.length) {
    playing.value = false;
    isTimelineSeeking.value = false;
    return;
  }
  loading.value = true;
  currentSegmentIndex.value = index;
  const seg = segments.value[index];
  
  const videoEl = activeVideo.value === 0 ? video1.value : video0.value;
  const nextVideoIdx = activeVideo.value === 0 ? 1 : 0;
  
  // 销毁旧的对应 player
  if (nextVideoIdx === 0 && flvPlayer0) {
    flvPlayer0.destroy();
    flvPlayer0 = null;
  } else if (nextVideoIdx === 1 && flvPlayer1) {
    flvPlayer1.destroy();
    flvPlayer1 = null;
  }

  videoEl.pause();
  videoEl.removeAttribute('src');
  videoEl.load();
  localSeekRetryTimers.forEach((id) => clearTimeout(id));
  localSeekRetryTimers = [];
  if (tsNudgeTimer) {
    clearTimeout(tsNudgeTimer);
    tsNudgeTimer = null;
  }
  lastTsNudgeAt = 0;
  
  const requestedOffset = Math.max(0, Number(offsetSeconds) || 0);
  const segmentFormat = String(seg?.format || '').toLowerCase();
  const isTsSegment = segmentFormat === 'ts';
  const isTsOrFlv = segmentFormat === 'ts' || segmentFormat === 'flv';
  const requestedQuality = normalizeTimelineQuality(timelineQuality.value);
  const autoTsTranscode = isTsSegment && requestedQuality === 'original';
  const selectedQuality = autoTsTranscode ? TS_AUTO_TRANSCODE_QUALITY : requestedQuality;
  const usingTranscode = selectedQuality !== 'original';
  const useTsRemuxPlayback = isTsSegment && !usingTranscode;
  const useMpegtsPlayback = !useTsRemuxPlayback && isTsOrFlv && mpegts.isSupported() && !usingTranscode;

  // token for url
  const mediaUrl = new URL(seg.play_url, window.location.origin);
  const token = localStorage.getItem('token');
  if (token && mediaUrl.pathname.includes('/api/')) {
    mediaUrl.searchParams.set('token', token);
  }

  mediaUrl.searchParams.set('quality', selectedQuality);
  if (useTsRemuxPlayback) {
    mediaUrl.searchParams.set('container', 'mp4');
  } else {
    mediaUrl.searchParams.delete('container');
  }
  const segStartOffset = Math.max(0, Number(seg?.start_offset) || 0);
  const urlStartOffset = Math.max(0, Number(mediaUrl.searchParams.get('start')) || 0);
  const baseStartOffset = Math.max(segStartOffset, urlStartOffset);
  const combinedStartOffset = baseStartOffset + requestedOffset;
  const useServerSideSeek = !useMpegtsPlayback && combinedStartOffset > 0;
  const localSeekTarget = useMpegtsPlayback ? combinedStartOffset : 0;
  const timelineSeekOffset = requestedOffset;
  const mediaTimeBaseAtSeek = useMpegtsPlayback ? localSeekTarget : 0;
  const requiresStartupBuffer = useTsRemuxPlayback;

  // 只要 URL 走 /api/video/stream 且可用，就统一让后端按 start 起播，避免前端 local seek 回零。
  // 如果 seg.play_url 已含基础 start（跨天切片场景），需要叠加 requestedOffset。
  if (useServerSideSeek) {
    mediaUrl.searchParams.set('start', `${combinedStartOffset}`);
  } else {
    mediaUrl.searchParams.delete('start');
  }

  const url = `${mediaUrl.pathname}${mediaUrl.search}`;
  currentSegmentOffset.value = timelineSeekOffset;
  currentSegmentMediaTimeBase.value = mediaTimeBaseAtSeek;
  videoEl.preload = 'auto';
  applyPlaybackPreferences(videoEl);

  if (useMpegtsPlayback) {
    let tsRecoveredOnce = false;
    const player = mpegts.createPlayer({
      type: 'mpegts',
      isLive: false,
      url: url
    }, {
      // TS 回放优先兼容性：使用保守参数，避免设备差异导致的解码错误
      enableWorker: false,
      enableStashBuffer: true,
      stashInitialSize: 768 * 1024,
      // 文件回放关闭懒加载，降低缓冲边界反复停取导致的抖动
      lazyLoad: false,
      fixAudioTimestampGap: true
    });
    player.attachMediaElement(videoEl);
    player.load();
    if (nextVideoIdx === 0) flvPlayer0 = player;
    else flvPlayer1 = player;
    
    player.on(mpegts.Events.ERROR, (type, detail, info) => {
      console.warn('mpegts player error', type, detail, info);
      if (!tsRecoveredOnce) {
        tsRecoveredOnce = true;
        try {
          player.unload();
          player.load();
          if (playing.value) {
            videoEl.play().catch(() => {});
          }
          return;
        } catch (recoverErr) {
          console.warn('mpegts recovery failed', recoverErr);
        }
      }
      console.log('mpegts player fatal error, jumping to next segment');
      isTimelineSeeking.value = false;
      onVideoEnded();
    });

    const nudgePlayback = () => {
      if (!playing.value) return;
      const nowTs = Date.now();
      if (nowTs - lastTsNudgeAt < 260) return;
      lastTsNudgeAt = nowTs;
      try {
        const now = Number(videoEl.currentTime || 0);
        if (localSeekTarget > 0 && now + 0.8 < localSeekTarget) {
          if (typeof videoEl.fastSeek === 'function') videoEl.fastSeek(localSeekTarget);
          else videoEl.currentTime = localSeekTarget;
          currentSegmentOffset.value = localSeekTarget;
        }
        if (videoEl.paused && videoEl.readyState >= 2) {
          videoEl.play().catch(() => {});
        }
      } catch (_) {}
      if (tsNudgeTimer) clearTimeout(tsNudgeTimer);
      tsNudgeTimer = setTimeout(() => {
        if (!playing.value) return;
        try {
          if (videoEl.paused && videoEl.readyState >= 2) {
            videoEl.play().catch(() => {});
          }
        } catch (_) {}
      }, 220);
    };
    videoEl.onwaiting = nudgePlayback;
    videoEl.onstalled = nudgePlayback;
  } else {
    videoEl.src = url;
    videoEl.load();
    videoEl.onwaiting = null;
    videoEl.onstalled = null;
  }
  
  const applyOffsetSeek = () => {
    if (localSeekTarget <= 0 && !useServerSideSeek) {
      currentSegmentOffset.value = timelineSeekOffset;
      currentSegmentMediaTimeBase.value = 0;
      return;
    }
    if (useServerSideSeek) {
      currentSegmentOffset.value = timelineSeekOffset;
      currentSegmentMediaTimeBase.value = 0;
      return;
    }
    try {
      videoEl.currentTime = localSeekTarget;
      currentSegmentOffset.value = timelineSeekOffset;
      currentSegmentMediaTimeBase.value = localSeekTarget;
    } catch (err) {
      currentSegmentOffset.value = 0;
      currentSegmentMediaTimeBase.value = 0;
      console.warn('seek offset failed', err);
    }
  };

  const ensureLocalSeek = () => {
    if (localSeekTarget <= 0) return;
    const now = Number(videoEl.currentTime || 0);
    if (Math.abs(now - localSeekTarget) <= 0.8) {
      currentSegmentOffset.value = timelineSeekOffset;
      currentSegmentMediaTimeBase.value = localSeekTarget;
      return;
    }
    try {
      if (typeof videoEl.fastSeek === 'function') {
        videoEl.fastSeek(localSeekTarget);
      } else {
        videoEl.currentTime = localSeekTarget;
      }
      currentSegmentOffset.value = timelineSeekOffset;
      currentSegmentMediaTimeBase.value = localSeekTarget;
    } catch (err) {
      console.warn('ensure local seek failed', err);
    }
  };

  const getBufferedAheadSeconds = () => {
    try {
      const ct = Number(videoEl.currentTime || 0);
      const buffered = videoEl.buffered;
      if (!buffered || buffered.length <= 0) return 0;
      for (let i = 0; i < buffered.length; i++) {
        const start = Number(buffered.start(i));
        const end = Number(buffered.end(i));
        if (ct >= start && ct <= end) {
          return Math.max(0, end - ct);
        }
      }
      // 当前点不在缓冲区，保守返回 0
      return 0;
    } catch (_) {
      return 0;
    }
  };

  const tryStartPlayback = () => {
    if (!(playing.value || index === 0 || isTimelineSeeking.value)) return;
    if (requiresStartupBuffer) {
      // 放宽 TS remux 起播门槛，避免长时间等待导致看起来“卡住”
      const bufferedAhead = getBufferedAheadSeconds();
      if (videoEl.readyState < 2 || bufferedAhead < 0.2) {
        return;
      }
    }
    videoEl.play().then(() => {
      ensureLocalSeek();
      localSeekRetryTimers.push(setTimeout(ensureLocalSeek, 120));
      localSeekRetryTimers.push(setTimeout(ensureLocalSeek, 320));
      playing.value = true;
    }).catch(e => {
      console.log("Play interrupted", e);
      playing.value = false;
    });
  };

  // The moment the video is loaded, we mark loading finished and switch visibility
  videoEl.onloadeddata = () => {
    loading.value = false;
    activeVideo.value = nextVideoIdx;
    ensureLocalSeek();

    if (!requiresStartupBuffer) {
      // 非 TS remux 的片段仍保持即时起播
      tryStartPlayback();
    }
    
    // 把另一个对应的视频停止
    const prevVideoIdx = nextVideoIdx === 0 ? 1 : 0;
    const prevVideoEl = prevVideoIdx === 0 ? video0.value : video1.value;
    prevVideoEl.pause();
    isTimelineSeeking.value = false;
  };
  videoEl.onloadedmetadata = () => {
    applyPlaybackPreferences(videoEl);
    applyOffsetSeek();
    ensureLocalSeek();
    localSeekRetryTimers.push(setTimeout(ensureLocalSeek, 80));
    localSeekRetryTimers.push(setTimeout(ensureLocalSeek, 220));
  };
  videoEl.oncanplay = () => {
    ensureLocalSeek();
    if (requiresStartupBuffer) {
      tryStartPlayback();
    }
  };
  videoEl.onprogress = () => {
    if (requiresStartupBuffer) {
      tryStartPlayback();
    }
  };
};

const togglePlay = () => {
  const currentV = activeVideo.value === 0 ? video0.value : video1.value;
  if (!currentV || !currentV.src && (!flvPlayer0 && !flvPlayer1)) return;
  
  if (playing.value) {
    currentV.pause();
    playing.value = false;
  } else {
    currentV.play().then(() => {
      playing.value = true;
    });
  }
};

const togglePlaybackSpeed = () => {
  const currentIndex = PLAYBACK_SPEED_OPTIONS.findIndex((v) => Math.abs(v - playbackSpeed.value) < 0.001);
  const nextIndex = currentIndex >= 0 ? (currentIndex + 1) % PLAYBACK_SPEED_OPTIONS.length : 1;
  playbackSpeed.value = PLAYBACK_SPEED_OPTIONS[nextIndex];
  localStorage.setItem(TIMELINE_SPEED_KEY, String(playbackSpeed.value));
  applyPlaybackPreferences();
};

const toggleMute = () => {
  isMuted.value = !isMuted.value;
  localStorage.setItem(TIMELINE_MUTED_KEY, String(isMuted.value));
  applyPlaybackPreferences();
};

const togglePip = async () => {
  const currentV = activeVideo.value === 0 ? video0.value : video1.value;
  if (!currentV) return;
  if (!document.pictureInPictureEnabled || currentV.disablePictureInPicture) return;
  try {
    if (document.pictureInPictureElement) {
      await document.exitPictureInPicture();
    } else {
      await currentV.requestPictureInPicture();
    }
  } catch (error) {
    console.warn('toggle picture-in-picture failed', error);
  } finally {
    updatePipState();
  }
};

const onVideoEnded = () => {
  // 无缝切换到下一个片段
  if (currentSegmentIndex.value + 1 < segments.value.length) {
    const nextIdx = currentSegmentIndex.value + 1;
    currentSegmentOffset.value = 0;
    currentSegmentMediaTimeBase.value = 0;
    playTimeOfDay.value = getSegmentStartOffset(segments.value[nextIdx]);
    isTimelineSeeking.value = true;
    playing.value = true;
    playSegment(nextIdx, 0);
  } else {
    playing.value = false;
    isTimelineSeeking.value = false;
  }
};

const syncPlayingFromMedia = () => {
  const v0 = video0.value;
  const v1 = video1.value;
  const isPlaying = [v0, v1].some((v) => v && !v.paused && !v.ended && v.readyState >= 2);
  playing.value = isPlaying;
};

const onVideoPlay = (e) => {
  syncPlayingFromMedia();
};

const onVideoPause = (e) => {
  syncPlayingFromMedia();
};

const onVideoLoadedMetadata = (e) => {
  const vw = e.target.videoWidth;
  const vh = e.target.videoHeight;
  if (vw > 0 && vh > 0) {
    isVerticalVideo.value = vh > vw * 1.05;
    videoAspectRatio.value = vw / vh;
  }
};

function getActiveVideoEl() {
  return activeVideo.value === 0 ? video0.value : video1.value;
}

function startTripleScreenLoop() {
  if (tripleScreenRAF) return;
  const doFrame = () => {
    if (tripleScreenMode.value === 0) { stopTripleScreenLoop(); return; }
    const video = getActiveVideoEl();
    // 每帧检测竖屏（不依赖事件，兼容 mpegts）
    if (video && !isVerticalVideo.value) {
      const vw = video.videoWidth;
      const vh = video.videoHeight;
      if (vw > 0 && vh > 0) {
        isVerticalVideo.value = vh > vw * 1.05;
        videoAspectRatio.value = vw / vh;
      }
    }
    if (!showTripleScreen.value) { tripleScreenRAF = requestAnimationFrame(doFrame); return; }
    if (!video) { tripleScreenRAF = requestAnimationFrame(doFrame); return; }
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    const videoAspect = vw > 0 && vh > 0 ? vw / vh : (videoAspectRatio.value || 0.5625);
    const canvases = [mirrorCanvasFarLeft.value, mirrorCanvasLeft.value, mirrorCanvasRight.value].filter(Boolean);
    for (const cvs of canvases) {
      if (!cvs || !cvs.parentNode) continue;
      // 同步 canvas 缓冲区与 CSS 尺寸
      const cw = Math.round(cvs.clientWidth);
      const ch = Math.round(cvs.clientHeight);
      if (cw > 0 && ch > 0 && (cvs.width !== cw || cvs.height !== ch)) {
        cvs.width = cw;
        cvs.height = ch;
      }
      if (cvs.width < 1 || cvs.height < 1) continue;
      const ctx = cvs.getContext('2d');
      if (!ctx) continue;
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, cvs.width, cvs.height);
      try {
        let drawW, drawH, ox, oy;
        if (cvs.width / cvs.height > videoAspect) {
          drawH = cvs.height;
          drawW = drawH * videoAspect;
          ox = (cvs.width - drawW) / 2;
          oy = 0;
        } else {
          drawW = cvs.width;
          drawH = drawW / videoAspect;
          ox = 0;
          oy = (cvs.height - drawH) / 2;
        }
        ctx.drawImage(video, ox, oy, drawW, drawH);
      } catch (_) {}
    }
    tripleScreenRAF = requestAnimationFrame(doFrame);
  };
  tripleScreenRAF = requestAnimationFrame(doFrame);
}

function stopTripleScreenLoop() {
  if (tripleScreenRAF) {
    cancelAnimationFrame(tripleScreenRAF);
    tripleScreenRAF = null;
  }
  [mirrorCanvasLeft.value, mirrorCanvasRight.value, mirrorCanvasFarLeft.value].filter(Boolean).forEach((cvs) => {
    if (cvs.width > 0 && cvs.height > 0) {
      const ctx = cvs.getContext('2d');
      if (ctx) {
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, cvs.width, cvs.height);
      }
    }
  });
}

function cycleTripleScreenMode() {
  tripleScreenMode.value = tripleScreenMode.value === 0 ? 3 : (tripleScreenMode.value === 3 ? 4 : 0);
  localStorage.setItem('timeline_triple_screen', String(tripleScreenMode.value));
}

const onTimeUpdate = (e) => {
  if (isTimelineSeeking.value) return;
  const vid = e.target;
  // 仅激活的 video 触发的时间线更新才有效
  const isActive = (activeVideo.value === 0 && vid === video0.value) || 
                   (activeVideo.value === 1 && vid === video1.value);
  if (!isActive) return;
  // 按真实播放状态同步按钮显示
  syncPlayingFromMedia();

  const seg = segments.value[currentSegmentIndex.value];
  if (!seg) return;

  const timelineDelta = Math.max(
    0,
    Number(vid.currentTime || 0) - Number(currentSegmentMediaTimeBase.value || 0)
  );
  playTimeOfDay.value = getSegmentStartOffset(seg) + currentSegmentOffset.value + timelineDelta;
  if (!isDraggingTimeline.value && !(isDesktopManualBrowse.value && !isMobile.value)) {
    syncTimelineToTime(playTimeOfDay.value);
  }
};

const resolveSegmentAtTime = (timeSeconds) => {
  let targetIndex = -1;
  let offsetSeconds = 0;
  
  for (let i = 0; i < segments.value.length; i++) {
    const sStart = getSegmentStartOffset(segments.value[i]);
    const sEnd = getSegmentEndOffset(segments.value[i]);
    
    if (timeSeconds >= sStart && timeSeconds <= sEnd) {
      targetIndex = i;
      offsetSeconds = timeSeconds - sStart;
      break;
    }
  }
  
  if (targetIndex === -1) {
    // 没点中任何片段，查找点之后最近的片段
    for (let i = 0; i < segments.value.length; i++) {
      const sStart = getSegmentStartOffset(segments.value[i]);
      if (sStart > timeSeconds) {
        targetIndex = i;
        offsetSeconds = 0;
        break;
      }
    }
  }

  return { targetIndex, offsetSeconds };
};

const playFromTime = (timeSeconds) => {
  const { targetIndex, offsetSeconds } = resolveSegmentAtTime(timeSeconds);
  if (targetIndex !== -1) {
    const targetSegStart = getSegmentStartOffset(segments.value[targetIndex]);
    isTimelineSeeking.value = true;
    playing.value = true;
    playTimeOfDay.value = targetSegStart + offsetSeconds;
    playSegment(targetIndex, offsetSeconds);
    persistResumeSnapshot(collectResumeSnapshot());
    return true;
  }
  return false;
};

const onScroll = () => {
  if (!isMobile.value) return;
  if (!timelineTrack.value || !timelineWrapper.value) return;
  if (!isTouchTimelineInteracting && Date.now() < ignoreMobileScrollUntil) return;
  if (!isTouchTimelineInteracting && Math.abs(timelineWrapper.value.scrollLeft - lastProgrammaticScrollLeft) <= 1.5) {
    return; // System scroll
  }
  
  isUserScrolling.value = true;
  
  // Preview the time while scrolling (center alignment)
  const trackWidth = timelineTrack.value.clientWidth;
  if (!trackWidth) return;
  const ratio = timelineWrapper.value.scrollLeft / trackWidth;
  playTimeOfDay.value = Math.max(0, Math.min(86400, ratio * 86400));

  // 移动端单指拖动期间只做预览，等 touchend 再提交跳转。
  if (isTouchTimelineInteracting) {
    return;
  }

  if (scrollTimeout) clearTimeout(scrollTimeout);
  scrollTimeout = setTimeout(() => {
    scrollTimeout = null;
    if (isTouchTimelineInteracting || !timelineTrack.value || !timelineWrapper.value) return;
    const trackWidth = timelineTrack.value.clientWidth;
    if (trackWidth > 0) {
      const ratio = timelineWrapper.value.scrollLeft / trackWidth;
      playTimeOfDay.value = Math.max(0, Math.min(86400, ratio * 86400));
    }
    isUserScrolling.value = false;
    playFromTime(playTimeOfDay.value);
  }, 140);
};

const onDragMove = (e) => {
  if (!isDraggingTimeline.value || !timelineWrapper.value) return;
  e.preventDefault();
  const dx = e.clientX - dragStartX;
  if (!desktopDragMoved.value && Math.abs(dx) > 3) {
    desktopDragMoved.value = true;
  }
  timelineWrapper.value.scrollLeft = dragStartScrollLeft - dx;
};

const onDragEnd = () => {
  if (!isDraggingTimeline.value) return;
  isDraggingTimeline.value = false;
  document.removeEventListener('mousemove', onDragMove);
  document.removeEventListener('mouseup', onDragEnd);
  if (!isMobile.value && desktopDragMoved.value) {
    suppressTrackClickOnce = true;
    isDesktopManualBrowse.value = true;
  }
  if (scrollTimeout) {
    clearTimeout(scrollTimeout);
    scrollTimeout = null;
  }
  if (isMobile.value) {
    isUserScrolling.value = false;
    playFromTime(playTimeOfDay.value);
  }
  desktopDragMoved.value = false;
};

const onDragStart = (e) => {
  if (e.button !== 0 || !timelineWrapper.value) return;
  if (scrollTimeout) {
    clearTimeout(scrollTimeout);
    scrollTimeout = null;
  }
  isDraggingTimeline.value = true;
  desktopDragMoved.value = false;
  dragStartX = e.clientX;
  dragStartScrollLeft = timelineWrapper.value.scrollLeft;
  document.addEventListener('mousemove', onDragMove);
  document.addEventListener('mouseup', onDragEnd);
};

const onTrackMouseMove = (e) => {
  if (isMobile.value || !timelineTrack.value) return;
  const rect = timelineTrack.value.getBoundingClientRect();
  const x = Math.min(Math.max(e.clientX - rect.left, 0), rect.width);
  hoverCursorLeft.value = (x / rect.width) * 100;
  hoverCursorVisible.value = true;
};

const onTrackMouseLeave = () => {
  if (isMobile.value) return;
  hoverCursorVisible.value = false;
};

const onTrackClick = (e) => {
  if (isMobile.value || !timelineTrack.value) return;
  if (suppressTrackClickOnce) {
    suppressTrackClickOnce = false;
    return;
  }
  const rect = timelineTrack.value.getBoundingClientRect();
  const x = Math.min(Math.max(e.clientX - rect.left, 0), rect.width);
  const clickedTime = (x / rect.width) * 86400;
  hoverCursorLeft.value = (x / rect.width) * 100;
  hoverCursorVisible.value = true;
  isDesktopManualBrowse.value = false;
  playFromTime(clickedTime);
  centerTimelineOn(clickedTime);
};

const syncTimelineToTime = (timeSeconds) => {
  if (!timelineWrapper.value || !timelineTrack.value || isUserScrolling.value) return;
  const ratio = timeSeconds / 86400;
  const trackWidth = timelineTrack.value.clientWidth;
  const wrapWidth = timelineWrapper.value.clientWidth;
  const playX = trackWidth * ratio;
  const desiredScroll = isMobile.value ? playX : (playX - wrapWidth / 2);
  const maxScrollLeft = Math.max(0, timelineWrapper.value.scrollWidth - wrapWidth);
  const targetScroll = Math.max(0, Math.min(maxScrollLeft, desiredScroll));
  
  if (Math.abs(timelineWrapper.value.scrollLeft - targetScroll) < 1.5) return;
  lastProgrammaticScrollLeft = targetScroll;
  if (isMobile.value) {
    ignoreMobileScrollUntil = Date.now() + 160;
  }
  timelineWrapper.value.scrollTo({ left: targetScroll, behavior: 'auto' });
};

const centerTimelineOn = (timeSeconds) => {
  if (timelineWrapper.value && timelineTrack.value) {
    const ratio = timeSeconds / 86400;
    const trackWidth = timelineTrack.value.clientWidth;
    const wrapWidth = timelineWrapper.value.clientWidth;
    const playX = trackWidth * ratio;
    const desiredScroll = isMobile.value ? playX : (playX - wrapWidth / 2);
    const maxScrollLeft = Math.max(0, timelineWrapper.value.scrollWidth - wrapWidth);
    const scrollTarget = Math.max(0, Math.min(maxScrollLeft, desiredScroll));
    
    lastProgrammaticScrollLeft = scrollTarget;
    if (isMobile.value) {
      // 移动端避免平滑滚动触发 onScroll 的二次跳转
      ignoreMobileScrollUntil = Date.now() + 800;
    }
    timelineWrapper.value.scrollTo({
      left: Math.max(0, scrollTarget),
      behavior: isMobile.value ? 'auto' : 'smooth'
    });
  }
};

const handleZoom = (newScale) => {
  if (!timelineWrapper.value || !timelineTrack.value) return;
  
  const clampScale = Math.max(1, Math.min(24, newScale));
  if (clampScale === timelineScale.value) return;
  const playRatio = Math.max(0, Math.min(1, playTimeOfDay.value / 86400));
  
  timelineScale.value = clampScale;
  
  nextTick(() => {
    if (!timelineTrack.value || !timelineWrapper.value) return;
    const newTrackWidth = timelineTrack.value.clientWidth;
    const wrapWidth = timelineWrapper.value.clientWidth;
    const newPlayX = newTrackWidth * playRatio;
    const desiredScroll = isMobile.value ? newPlayX : (newPlayX - wrapWidth / 2);
    const maxScrollLeft = Math.max(0, timelineWrapper.value.scrollWidth - wrapWidth);
    const targetScrollLeft = Math.max(0, Math.min(maxScrollLeft, desiredScroll));

    lastProgrammaticScrollLeft = targetScrollLeft;
    if (isMobile.value) {
      ignoreMobileScrollUntil = Date.now() + 180;
    }
    timelineWrapper.value.scrollLeft = targetScrollLeft;
  });
};

const onWheel = (e) => {
  const delta = e.deltaY > 0 ? -0.15 : 0.15; // scroll up to zoom in
  const newScale = timelineScale.value * (1 + delta);
  handleZoom(newScale);
};

const onTouchStart = (e) => {
  if (isMobile.value && e.touches.length === 1) {
    isTouchTimelineInteracting = true;
    isUserScrolling.value = true;
    ignoreMobileScrollUntil = 0;
    if (!mobileTouchEndListening) {
      window.addEventListener('touchend', onTouchEnd, true);
      window.addEventListener('touchcancel', onTouchEnd, true);
      mobileTouchEndListening = true;
    }
    if (scrollTimeout) {
      clearTimeout(scrollTimeout);
      scrollTimeout = null;
    }
    return;
  }
  if (e.touches.length === 2) {
    e.preventDefault();
    initialPinchDist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
    initialScale = timelineScale.value;
  }
};

const onTouchMove = (e) => {
  if (isMobile.value && isTouchTimelineInteracting && e.touches.length === 1) {
    if (!timelineTrack.value || !timelineWrapper.value) return;
    const trackWidth = timelineTrack.value.clientWidth;
    if (!trackWidth) return;
    const ratio = timelineWrapper.value.scrollLeft / trackWidth;
    playTimeOfDay.value = Math.max(0, Math.min(86400, ratio * 86400));
    return;
  }
  if (e.touches.length === 2) {
    e.preventDefault();
    const currentDist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
    const scaling = currentDist / initialPinchDist;
    const newScale = initialScale * scaling;
    handleZoom(newScale);
  }
};

const onTouchEnd = (e) => {
  if (!isMobile.value) return;
  if (e.touches && e.touches.length > 0) return;
  if (!isTouchTimelineInteracting) return;
  isTouchTimelineInteracting = false;
  if (mobileTouchEndListening) {
    window.removeEventListener('touchend', onTouchEnd, true);
    window.removeEventListener('touchcancel', onTouchEnd, true);
    mobileTouchEndListening = false;
  }
  if (scrollTimeout) clearTimeout(scrollTimeout);
  scrollTimeout = setTimeout(() => {
    scrollTimeout = null;
    if (!timelineTrack.value || !timelineWrapper.value) {
      isUserScrolling.value = false;
      return;
    }
    const trackWidth = timelineTrack.value.clientWidth;
    if (trackWidth > 0) {
      const ratio = timelineWrapper.value.scrollLeft / trackWidth;
      playTimeOfDay.value = Math.max(0, Math.min(86400, ratio * 86400));
    }
    isUserScrolling.value = false;
    playFromTime(playTimeOfDay.value);
  }, 120);
};

const selectDate = (targetDate) => {
  const normalized = normalizeDateString(targetDate);
  if (!normalized) return;
  if (normalized === currentDate.value) return;
  currentDate.value = normalized;
  setTimelineLiveRefreshEnabled(false);
  stopAll();
  loadTimelineEvents(normalized);
  emit('date-change', normalized);
};

const onDateChange = (e) => {
  selectDate(e?.target?.value);
};

const pickAvailableDate = (targetDate) => {
  closeAvailableDatePanel();
  selectDate(targetDate);
};

const isForceLandscape = ref(false);

const toggleForceLandscape = async () => {
  if (!isFullscreen.value) return;
  
  try {
    if (isForceLandscape.value) {
      if (screen.orientation && screen.orientation.unlock) {
        screen.orientation.unlock();
      }
      isForceLandscape.value = false;
    } else {
      if (screen.orientation && screen.orientation.lock) {
        await screen.orientation.lock('landscape').catch(err => {
          console.warn('Orientation lock rejected', err);
        });
        isForceLandscape.value = true;
      }
    }
  } catch (err) {
    console.error('Orientation toggle error:', err);
  }
};

const closeAvailableDatePanel = () => {
  showAvailableDatePanel.value = false;
};

const toggleAvailableDatePanel = () => {
  if (!availableDateItems.value.length) return;
  const nextVisible = !showAvailableDatePanel.value;
  showAvailableDatePanel.value = nextVisible;
  if (!nextVisible) return;
  const currentMonth = String(currentDate.value || '').slice(0, 7);
  if (availableMonthMap.value.has(currentMonth)) {
    selectedAvailableMonth.value = currentMonth;
    return;
  }
  if (!availableMonthsDesc.value.includes(selectedAvailableMonth.value)) {
    selectedAvailableMonth.value = availableMonthsDesc.value[0] || '';
  }
};

const jumpToAdjacentAvailableDate = (direction = 1) => {
  const target = direction < 0 ? prevAvailableDate.value : nextAvailableDate.value;
  if (target) selectDate(target);
};

const jumpToLatestAvailableDate = () => {
  if (latestAvailableDate.value) {
    selectDate(latestAvailableDate.value);
  }
};

const onKeydown = (event) => {
  if (event?.key === 'Escape' && showAvailableDatePanel.value) {
    closeAvailableDatePanel();
  }
};

const onTimelineQualityChange = () => {
  timelineQuality.value = normalizeTimelineQuality(timelineQuality.value);
  localStorage.setItem(TIMELINE_QUALITY_KEY, timelineQuality.value);
  timelineNotice.value = withTsAutoNotice(timelineNotice.value);
  refreshQualitySuffix();

  if (currentSegmentIndex.value < 0) return;
  playFromTime(playTimeOfDay.value);
};

const cycleTimelineQuality = () => {
  const currentIndex = timelineQualityOptions.findIndex((item) => item.value === timelineQuality.value);
  const nextIndex = currentIndex >= 0
    ? (currentIndex + 1) % timelineQualityOptions.length
    : 0;
  timelineQuality.value = timelineQualityOptions[nextIndex].value;
  onTimelineQualityChange();
};

const getFullscreenElement = () => (
  document.fullscreenElement ||
  document.webkitFullscreenElement ||
  null
);

const updateFullscreenState = () => {
  const fullEl = getFullscreenElement();
  isFullscreen.value = !!(fullEl && playerViewport.value && (fullEl === playerViewport.value || playerViewport.value.contains(fullEl)));
  
  if (!isFullscreen.value && isForceLandscape.value) {
    if (screen.orientation && screen.orientation.unlock) {
      screen.orientation.unlock();
    }
    isForceLandscape.value = false;
  }
};

const toggleFullscreen = async () => {
  if (!playerViewport.value) return;
  try {
    if (getFullscreenElement()) {
      if (document.exitFullscreen) await document.exitFullscreen();
      else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
    } else if (playerViewport.value.requestFullscreen) {
      await playerViewport.value.requestFullscreen();
    } else if (playerViewport.value.webkitRequestFullscreen) {
      playerViewport.value.webkitRequestFullscreen();
    }
  } catch (error) {
    console.warn('toggle fullscreen failed', error);
  } finally {
    updateFullscreenState();
  }
};

const collectResumeSnapshot = () => {
  const seg = segments.value[currentSegmentIndex.value];
  const currentV = activeVideo.value === 0 ? video0.value : video1.value;
  if (!seg || !currentV) {
    return {
      timeOfDay: Math.max(0, Math.min(86400, playTimeOfDay.value)),
      segmentIndex: currentSegmentIndex.value,
      segmentOffset: Math.max(0, Number(currentSegmentOffset.value) || 0),
      wasPlaying: playing.value,
      extras: {
        timelineQuality: timelineQuality.value,
        playbackSpeed: playbackSpeed.value,
        date: currentDate.value
      }
    };
  }
  const segStart = getSegmentStartOffset(seg);
  const duration = Math.max(0, Number(seg.duration) || 0);
  const timelineDelta = Math.max(
    0,
    Number(currentV.currentTime || 0) - Number(currentSegmentMediaTimeBase.value || 0)
  );
  const absoluteTime = Math.max(
    0,
    Math.min(86400, segStart + currentSegmentOffset.value + timelineDelta)
  );
  return {
    timeOfDay: absoluteTime,
    segmentIndex: currentSegmentIndex.value,
    segmentOffset: Math.max(0, Math.min(duration, absoluteTime - segStart)),
    wasPlaying: playing.value,
    extras: {
      timelineQuality: timelineQuality.value,
      playbackSpeed: playbackSpeed.value,
      date: currentDate.value
    }
  };
};

const notifyResumeUpdated = () => {
  try {
    if (typeof BroadcastChannel !== 'undefined') {
      const channel = new BroadcastChannel(RESUME_BROADCAST_CHANNEL);
      channel.postMessage({ type: 'resume-updated' });
      channel.close();
    }
  } catch (e) {}
  try {
    window.dispatchEvent(new CustomEvent('timeline-resume-updated'));
  } catch (e) {}
};

const persistResumeSnapshot = (snapshot) => {
  saveResumeState(snapshot);
  notifyResumeUpdated();
};

const handleVisibilityChange = () => {
  if (document.hidden) {
    hiddenAtMs = Date.now();
    const snapshot = collectResumeSnapshot();
    setHiddenResumeState({
      absoluteTime: snapshot.timeOfDay,
      segmentIndex: snapshot.segmentIndex,
      segmentOffset: snapshot.segmentOffset,
      wasPlaying: snapshot.wasPlaying
    });
    persistResumeSnapshot(snapshot);
    return;
  }

  if (visibilityResumeTimer) clearTimeout(visibilityResumeTimer);
  visibilityResumeTimer = setTimeout(async () => {
    updateHalfWidth();
    const currentV = activeVideo.value === 0 ? video0.value : video1.value;
    const seg = segments.value[currentSegmentIndex.value];
    const resumeTarget = hiddenPlayTimeOfDay.value || playTimeOfDay.value;
    const hiddenDurationMs = hiddenAtMs > 0 ? Date.now() - hiddenAtMs : 0;

    if (wasPlayingBeforeHidden.value && resumeTarget > 0 && hiddenDurationMs <= RESUME_VISIBILITY_MAX_INPLACE_MS) {
      // 先尝试原位续播，避免每次切后台/切回都触发重载动画。
      const sameSegment = hiddenSegmentIndex.value >= 0 && hiddenSegmentIndex.value === currentSegmentIndex.value;
      if (currentV && seg && sameSegment) {
        try {
          const segStart = getSegmentStartOffset(seg);
          await currentV.play();
          const currentTime = Math.max(
            0,
            Number(currentV.currentTime || 0) - Number(currentSegmentMediaTimeBase.value || 0)
          );
          playTimeOfDay.value = Math.max(
            0,
            Math.min(86400, segStart + currentSegmentOffset.value + currentTime)
          );
          playing.value = true;
          isTimelineSeeking.value = false;
          syncTimelineToTime(playTimeOfDay.value);
          clearHiddenResumeState();
          return;
        } catch (error) {
          console.warn('in-place resume failed, fallback to segment reload', error);
        }
      }

      // 原位恢复失败时，再按隐藏前的片段索引+片段内偏移恢复，避免绝对时间映射误差导致回到开头。
      const resumeSeg = segments.value[hiddenSegmentIndex.value];
      if (resumeSeg) {
        const segStart = getSegmentStartOffset(resumeSeg);
        const segDuration = Math.max(0, Number(resumeSeg.duration) || 0);
        const safeOffset = Math.max(0, Math.min(segDuration, Number(hiddenSegmentOffset.value) || 0));
        isTimelineSeeking.value = true;
        playing.value = true;
        playTimeOfDay.value = segStart + safeOffset;
        playSegment(hiddenSegmentIndex.value, safeOffset);
      } else if (hiddenDurationMs > 0) {
        // 回退到按绝对秒定位
        playFromTime(resumeTarget);
      }
      syncTimelineToTime(resumeTarget);
      clearHiddenResumeState();
      return;
    }

    if (resumeTarget > 0 && hiddenDurationMs > RESUME_VISIBILITY_MAX_INPLACE_MS) {
      playFromTime(resumeTarget);
      syncTimelineToTime(resumeTarget);
      clearHiddenResumeState();
      return;
    }

    if (currentV && seg) {
      const baseTime = getSegmentStartOffset(seg) + currentSegmentOffset.value;
      const currentTime = Math.max(
        0,
        Number(currentV.currentTime || 0) - Number(currentSegmentMediaTimeBase.value || 0)
      );
      playTimeOfDay.value = Math.max(0, Math.min(86400, baseTime + currentTime));
      syncTimelineToTime(playTimeOfDay.value);
    } else if (playTimeOfDay.value > 0) {
      syncTimelineToTime(playTimeOfDay.value);
    }

    if (wasPlayingBeforeHidden.value && currentV && currentV.paused) {
      try {
        await currentV.play();
        playing.value = true;
      } catch (error) {
        console.warn('resume after hidden failed', error);
      }
    }
    clearHiddenResumeState();
  }, 120);
};

const refreshQualitySuffix = async () => {
  try {
    const res = await playerApi.getEncoderStatus();
    encoderLabel.value = res.label || '';
    transcodeStatus.value = res || {};
  } catch (error) {
    encoderLabel.value = '';
    transcodeStatus.value = {};
  }
};

const refreshGpuStatus = async () => {
  try {
    const data = await systemApi.getGpuStats();
    gpuStatusData.value = data || { summary: { has_gpu: false, transcode_enabled: false }, gpus: [] };
    gpuStatusError.value = '';
  } catch (error) {
    gpuStatusError.value = error?.message || 'gpu_status_failed';
  } finally {
    gpuStatusLoading.value = false;
  }
};

const startStatusPolling = () => {
  if (encoderRefreshInterval) clearInterval(encoderRefreshInterval);
  refreshQualitySuffix();
  encoderRefreshInterval = setInterval(refreshQualitySuffix, 1000);

  if (gpuRefreshInterval) clearInterval(gpuRefreshInterval);
  refreshGpuStatus();
  gpuRefreshInterval = setInterval(refreshGpuStatus, 1000);
};

const stopStatusPolling = () => {
  if (encoderRefreshInterval) {
    clearInterval(encoderRefreshInterval);
    encoderRefreshInterval = null;
  }
  if (gpuRefreshInterval) {
    clearInterval(gpuRefreshInterval);
    gpuRefreshInterval = null;
  }
};

onMounted(() => {
  mpegts.LoggingControl.enableAll = false;
  const savedMode = localStorage.getItem(DANMU_MODE_KEY);
  if (savedMode === 'marquee' || savedMode === 'list' || savedMode === 'off') {
    danmuMode.value = savedMode;
  } else {
    danmuMode.value = 'marquee';
  }

  isMobile.value = window.innerWidth <= 768;
  isTouchDevice.value = !!(navigator.maxTouchPoints || (window.matchMedia && window.matchMedia('(pointer: coarse)').matches));
  if (isMobile.value) {
    timelineScale.value = 2.5; // default scale for mobile
  }

  resizeHandler = () => {
    isMobile.value = window.innerWidth <= 768;
    isTouchDevice.value = !!(navigator.maxTouchPoints || (window.matchMedia && window.matchMedia('(pointer: coarse)').matches));
    updateHalfWidth();
  };
  window.addEventListener('resize', resizeHandler);
  setTimeout(updateHalfWidth, 50);

  loadAvailableDates();
  loadResumeState();
  loadTimelineEvents(currentDate.value);
  startStatusPolling();
  if (danmuMode.value !== 'off') {
    openDanmuSocket(true);
    lastDanmuResetTs.value = null;
  }
  nextTick(() => {
    applyPlaybackPreferences();
    updatePipState();
  });
  if (resumeSaveInterval) clearInterval(resumeSaveInterval);
  resumeSaveInterval = setInterval(() => {
    if (!segments.value.length) return;
    const snapshot = collectResumeSnapshot();
    if (snapshot.timeOfDay > 0) {
      persistResumeSnapshot(snapshot);
    }
  }, RESUME_SAVE_INTERVAL_MS);
  document.addEventListener('fullscreenchange', updateFullscreenState);
  document.addEventListener('webkitfullscreenchange', updateFullscreenState);
  window.addEventListener('mousemove', handleGlobalMouseMove, true);
  window.addEventListener('touchend', handleGlobalTouchEnd, { passive: true });
  window.addEventListener('touchcancel', handleGlobalTouchEnd, { passive: true });
  document.addEventListener('enterpictureinpicture', updatePipState);
  document.addEventListener('leavepictureinpicture', updatePipState);
  document.addEventListener('visibilitychange', handleVisibilityChange);
  document.addEventListener('keydown', onKeydown);
});

onBeforeUnmount(() => {
  persistResumeSnapshot(collectResumeSnapshot());
  if (resumeSaveInterval) {
    clearInterval(resumeSaveInterval);
    resumeSaveInterval = null;
  }
  closeDanmuSocket();
  if (resizeHandler) window.removeEventListener('resize', resizeHandler);
  if (mobileTouchEndListening) {
    window.removeEventListener('touchend', onTouchEnd, true);
    window.removeEventListener('touchcancel', onTouchEnd, true);
    mobileTouchEndListening = false;
  }
  if (scrollTimeout) clearTimeout(scrollTimeout);
  if (visibilityResumeTimer) clearTimeout(visibilityResumeTimer);
  if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
  setTimelineLiveRefreshEnabled(false);
  localSeekRetryTimers.forEach((id) => clearTimeout(id));
  localSeekRetryTimers = [];
  stopStatusPolling();
  document.removeEventListener('fullscreenchange', updateFullscreenState);
  document.removeEventListener('webkitfullscreenchange', updateFullscreenState);
  window.removeEventListener('mousemove', handleGlobalMouseMove, true);
  window.removeEventListener('touchend', handleGlobalTouchEnd);
  window.removeEventListener('touchcancel', handleGlobalTouchEnd);
  document.removeEventListener('enterpictureinpicture', updatePipState);
  document.removeEventListener('leavepictureinpicture', updatePipState);
  document.removeEventListener('visibilitychange', handleVisibilityChange);
  document.removeEventListener('keydown', onKeydown);
  document.body.style.removeProperty('overflow');
  onDragEnd();
  stopAll();
});

watch(tripleScreenMode, (val) => {
  if (val > 0) startTripleScreenLoop();
  else stopTripleScreenLoop();
}, { immediate: true });

watch(isFullscreen, (value) => {
  if (value) {
    fullscreenControlsVisible.value = true;
    fullscreenControlsHovering.value = false;
    fullscreenControlsTouching.value = false;
    scheduleHideFullscreenControls();
  } else {
    fullscreenControlsVisible.value = false;
    fullscreenControlsHovering.value = false;
    fullscreenControlsTouching.value = false;
    if (fullscreenHideTimer) clearTimeout(fullscreenHideTimer);
  }
});

watch(
  () => props.subId,
  () => {
    if (danmuMode.value !== 'off') {
      openDanmuSocket(true);
      lastDanmuResetTs.value = null;
    }
  }
);

watch(
  () => currentDate.value,
  () => {
    resetDanmuBuffer();
    sendDanmuReset();
  }
);

const lastDanmuResetTs = ref(null);

watch(
  () => playTimeOfDay.value,
  (value, prev) => {
    if (!danmuVisible.value) return;
    const nowTs = getCurrentTs();
    if (!nowTs) return;
    if (lastDanmuResetTs.value === null) {
      lastDanmuResetTs.value = nowTs;
      return;
    }
    const delta = Math.abs(nowTs - lastDanmuResetTs.value);
    if (delta >= 20 && Math.abs((value || 0) - (prev || 0)) > 5) {
      lastDanmuResetTs.value = nowTs;
      sendDanmuReset();
    }
  }
);

watch(
  () => danmuMode.value,
  (mode) => {
    if (mode === 'off') {
      closeDanmuSocket();
      marqueeItems.value = [];
      for (let i = 0; i < marqueeLaneNextAt.length; i += 1) {
        marqueeLaneNextAt[i] = 0;
      }
      lastDanmuResetTs.value = null;
    } else {
      openDanmuSocket(true);
      lastDanmuResetTs.value = null;
      if (mode !== 'marquee') {
        marqueeItems.value = [];
        for (let i = 0; i < marqueeLaneNextAt.length; i += 1) {
          marqueeLaneNextAt[i] = 0;
        }
        danmuListUserHold.value = false;
        danmuListStickToBottom.value = true;
        nextTick(scrollDanmuListToBottom);
      }
    }
  }
);

watch(availableMonthsDesc, (months) => {
  if (!Array.isArray(months) || !months.length) {
    selectedAvailableMonth.value = '';
    showAvailableDatePanel.value = false;
    return;
  }
  if (!months.includes(selectedAvailableMonth.value)) {
    selectedAvailableMonth.value = months[0];
  }
}, { immediate: true });

watch(showAvailableDatePanel, (visible) => {
  if (visible) {
    document.body.style.overflow = 'hidden';
  } else {
    document.body.style.removeProperty('overflow');
  }
});
</script>

<style scoped>
.timeline-player-container {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 360px;
  background: var(--bg-surface);
  border-radius: 8px;
  overflow: hidden;
}

.player-viewport {
  flex: 1 1 auto;
  position: relative;
  background: #000;
  min-height: 280px;
  overflow: hidden;
}

.danmu-marquee-layer {
  position: absolute;
  left: 0;
  right: 0;
  top: 12px;
  bottom: 80px;
  z-index: 4;
  pointer-events: none;
  overflow: hidden;
  padding-right: 8px;
}

.danmu-marquee-item {
  position: absolute;
  left: 100%;
  transform: translateX(0);
  display: inline-block;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.55);
  color: #f8fafc;
  font-size: 15px;
  line-height: 1.25;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
  animation-name: danmu-marquee-move;
  animation-timing-function: linear;
  animation-fill-mode: both;
  will-change: transform;
  width: max-content;
  min-width: 140px;
  max-width: min(70vw, 520px);
  white-space: normal;
  word-break: break-word;
}

.danmu-list-panel {
  position: absolute;
  left: 16px;
  bottom: 20px;
  width: min(32%, 360px);
  height: clamp(120px, 36%, 240px);
  z-index: 4;
  pointer-events: auto;
  background: rgba(15, 23, 42, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  box-sizing: border-box;
  padding: 8px;
  contain: layout paint;
  transform: translateZ(0);
  backface-visibility: hidden;
}

@media (max-width: 768px) {
  .danmu-marquee-layer {
    top: 8px;
    bottom: 64px;
  }
  .danmu-marquee-item {
    font-size: 10px;
    max-width: 80vw;
    padding: 3px 8px;
  }
  .danmu-list-panel {
    left: 0;
    right: auto;
    bottom: 0;
    width: min(32vw, 150px);
    height: min(16vh, 120px);
    padding: 3px;
  }
  .danmu-list-item {
    font-size: 7px;
    padding: 1px 3px;
  }
  .danmu-list-jump {
    right: 3px;
    bottom: 3px;
    font-size: 8px;
    padding: 1px 3px;
  }
}

@media (max-width: 768px) and (orientation: portrait) {
  .danmu-list-panel {
    width: min(50vw, 220px);
  }
}

@media (max-width: 1024px) and (max-height: 600px) {
  .danmu-marquee-item {
    font-size: 10px;
  }
  .danmu-list-panel .danmu-list-item {
    font-size: 10px !important;
    padding: 2px 5px !important;
  }
}

.danmu-list-jump {
  position: absolute;
  right: 6px;
  top: 6px;
  z-index: 2;
  padding: 4px 8px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(15, 23, 42, 0.55);
  color: rgba(248, 250, 252, 0.9);
  font-size: 12px;
  cursor: pointer;
  backdrop-filter: blur(2px);
}

.danmu-list-jump:hover {
  background: rgba(15, 23, 42, 0.9);
}

.danmu-list {
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.55) transparent;
}

.danmu-list::-webkit-scrollbar {
  width: 6px;
}

.danmu-list::-webkit-scrollbar-track {
  background: transparent;
}

.danmu-list::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.55);
  border-radius: 999px;
}

.danmu-list::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.75);
}

.danmu-list-empty {
  color: rgba(226, 232, 240, 0.6);
  font-size: 12px;
  padding: 6px 8px;
}

.danmu-list-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.55);
  color: #f8fafc;
  font-size: 15px;
  line-height: 1.2;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
}

.danmu-text {
  font-weight: 600;
  color: #f8fafc;
  letter-spacing: 0.2px;
}

@keyframes danmu-marquee-move {
  0% { transform: translateX(0); opacity: 1; }
  100% { transform: translateX(-140vw); opacity: 1; }
}

@media (max-width: 768px) {
  .danmu-list-panel .danmu-list-item {
    font-size: 10px !important;
    padding: 2px 5px !important;
  }
}

.danmu-btn {
  font-size: 12px;
  padding: 4px 8px;
}

.danmu-status {
  font-size: 12px;
  color: rgba(248, 250, 252, 0.8);
  margin-left: 8px;
}

.fullscreen-touch-layer {
  position: absolute;
  inset: 0;
  z-index: 6;
  background: transparent;
}

.streamer-meta {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: min(72%, 460px);
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.58);
  border: 1px solid rgba(255, 255, 255, 0.22);
  backdrop-filter: blur(3px);
  
  /* 默认隐藏，跟随全屏控制逻辑 */
  opacity: 0;
  pointer-events: none;
  transform: translateY(-12px);
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.streamer-meta.is-visible {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0);
}

.streamer-avatar,
.streamer-avatar-placeholder {
  width: 34px;
  height: 34px;
  border-radius: 999px;
  flex: 0 0 34px;
}

.streamer-avatar {
  object-fit: cover;
}

.streamer-avatar-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  background: linear-gradient(135deg, #fb923c, #f97316);
}

.streamer-texts {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.streamer-platform {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.86);
  background: rgba(255, 255, 255, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 999px;
  padding: 2px 8px;
  white-space: nowrap;
}

.streamer-name {
  min-width: 0;
  font-size: 14px;
  color: #fff;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nvr-video {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  opacity: 0;
  z-index: 1;
  transition: opacity 0.3s;
}

.nvr-video.active {
  opacity: 1;
  z-index: 2;
}

.player-content-layout {
  width: 100%;
  height: 100%;
  position: relative;
}

.player-content-layout.triple-mode {
  display: flex;
  flex-direction: row;
  justify-content: center;
  gap: 4px;
  height: 100%;
}

.player-content-layout.triple-mode .video-stack {
  height: 100%;
  aspect-ratio: var(--video-aspect-ratio, 0.5625);
  flex: 0 0 auto;
  position: relative;
}

.player-content-layout.triple-mode .video-stack .nvr-video {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}

.player-content-layout.triple-mode > canvas.triple-mirror {
  height: 100%;
  aspect-ratio: var(--video-aspect-ratio, 0.5625);
  flex: 0 0 auto;
  pointer-events: none;
  user-select: none;
}

.nvr-loading {
  position: absolute;
  inset: 0;
  z-index: 3;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.42);
  backdrop-filter: blur(1.5px);
}

.loading-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 220px;
  padding: 16px 18px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.66);
  border: 1px solid rgba(255, 255, 255, 0.2);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
}

.loading-orbit {
  position: relative;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.28);
  border-top-color: #ffffff;
  animation: loading-spin 0.95s linear infinite;
  margin-bottom: 10px;
}

.loading-dot {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #fff;
  transform: translate(-50%, -50%);
  animation: loading-pulse 1.1s ease-in-out infinite;
}

.loading-title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.2px;
}

.loading-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.82);
}

.loading-progress-track {
  width: 100%;
  height: 5px;
  margin-top: 12px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.2);
}

.loading-progress-bar {
  width: 45%;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.18), #fff, rgba(255, 255, 255, 0.18));
  animation: loading-slide 1.25s ease-in-out infinite;
}

.loading-text {
  font-size: 14px;
}

@keyframes loading-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes loading-pulse {
  0% { transform: translate(-50%, -50%) scale(0.8); opacity: 0.8; }
  50% { transform: translate(-50%, -50%) scale(1.25); opacity: 1; }
  100% { transform: translate(-50%, -50%) scale(0.8); opacity: 0.8; }
}

@keyframes loading-slide {
  0% { transform: translateX(-120%); }
  100% { transform: translateX(280%); }
}

.timeline-controls {
  flex-shrink: 0;
  padding: 16px;
  background: var(--bg-surface-light);
  border-top: 1px solid var(--border-color);
}


.timeline-controls--fullscreen {
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: 16px;
  z-index: 8;
  padding: 12px 14px 14px;
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.75), rgba(15, 23, 42, 0.9));
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(10px);
  opacity: 0;
  pointer-events: none;
  transform: translateY(12px);
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.timeline-controls--fullscreen.is-visible {
  opacity: 1;
  pointer-events: none;
  transform: translateY(0);
}

.timeline-controls--fullscreen .fullscreen-controls-inner {
  pointer-events: auto;
  width: 100%;
}

.timeline-controls--fullscreen .control-actions {
  margin-bottom: 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.timeline-controls--fullscreen .control-main {
  gap: 10px;
  flex-wrap: wrap;
  justify-content: center;
}

.timeline-controls--fullscreen .date-picker-wrap--fullscreen {
  width: min(88vw, 860px);
  margin: 0;
  align-items: center;
}

.timeline-controls--fullscreen .date-picker-wrap--fullscreen .date-nav-row,
.timeline-controls--fullscreen .date-picker-wrap--fullscreen .date-quick-row {
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}

.timeline-controls--fullscreen .date-picker-wrap--fullscreen .date-panel-latest {
  color: rgba(255, 255, 255, 0.75);
}

.timeline-controls--fullscreen .date-picker-wrap--fullscreen .date-picker {
  background: rgba(2, 6, 23, 0.6);
  border-color: rgba(251, 146, 60, 0.55);
  color: #e2e8f0;
}

.timeline-controls--fullscreen .time-display {
  color: #f8fafc;
}

.timeline-controls--fullscreen .timeline-bar-container {
  margin-top: 12px;
}

.timeline-controls--fullscreen .tick-label {
  color: rgba(255, 255, 255, 0.92);
  background: rgba(2, 6, 23, 0.55);
  padding: 2px 6px;
  border-radius: 999px;
  text-shadow: 0 2px 6px rgba(0, 0, 0, 0.7);
}

.timeline-controls--fullscreen :deep(.timeline-gpu-inline) {
  background: rgba(15, 23, 42, 0.85);
  border-color: rgba(255, 255, 255, 0.18);
  color: #e2e8f0;
}

.timeline-controls--fullscreen :deep(.timeline-gpu-inline .gpu-bar) {
  background: rgba(255, 255, 255, 0.08);
}

.control-actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    "main date"
    "runtime date";
  align-items: start;
  column-gap: 16px;
  row-gap: 8px;
  margin-bottom: 12px;
}

.control-main {
  grid-area: main;
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex-wrap: wrap;
}

.time-display {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: monospace;
  font-size: 14px;
  color: var(--text-primary);
  min-width: 168px;
  white-space: nowrap;
}

.time-line {
  display: inline-block;
}

.date-picker-wrap {
  grid-area: date;
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 360px;
  max-width: 460px;
  width: min(34vw, 460px);
  margin-left: 0;
}

.date-picker {
  padding: 4px 6px;
  border-radius: 10px;
  font-size: 14px;
  min-height: 30px;
  flex: 1;
  border: 1px solid rgba(249, 115, 22, 0.42);
  background: var(--bg-element);
  color: var(--text-primary);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}

.date-picker:hover {
  border-color: rgba(249, 115, 22, 0.62);
}

.date-picker:focus {
  outline: none;
  border-color: #ea580c;
  box-shadow: 0 0 0 2px rgba(251, 146, 60, 0.2);
}

.date-picker.is-unavailable {
  border-color: rgba(230, 126, 34, 0.55);
  box-shadow: inset 0 0 0 1px rgba(230, 126, 34, 0.25);
}

.date-nav-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.date-nav-btn {
  min-width: 56px;
  white-space: nowrap;
}

.date-quick-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex-wrap: wrap;
}

.date-panel-latest {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.available-date-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  background: rgba(2, 6, 23, 0.62);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
}

.available-date-modal-overlay--fullscreen {
  position: absolute;
  z-index: 14;
}

.available-date-panel {
  width: min(620px, calc(100vw - 36px));
  max-height: min(76vh, 560px);
  overflow: auto;
  margin: 0;
  border: 1px solid rgba(148, 163, 184, 0.45);
  border-radius: 10px;
  background: #ffffff;
  color: #111827;
  box-shadow: 0 16px 38px rgba(2, 6, 23, 0.28);
  padding: 10px;
}

[data-theme="dark"] .available-date-panel {
  border-color: rgba(148, 163, 184, 0.35);
  background: #111827;
  color: #e5e7eb;
  box-shadow: 0 16px 38px rgba(0, 0, 0, 0.45);
}

.available-date-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.available-date-panel-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.available-date-panel-meta {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.available-month-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 4px;
  margin-bottom: 8px;
}

.available-month-tab {
  border: 1px solid var(--border-color);
  background: var(--bg-element);
  color: var(--text-secondary);
  border-radius: 999px;
  font-size: 11px;
  line-height: 1.2;
  padding: 4px 10px;
  white-space: nowrap;
  cursor: pointer;
}

.available-month-tab:hover {
  color: var(--text-primary);
  border-color: var(--color-primary);
}

.available-month-tab.active {
  color: #2563eb;
  border-color: rgba(59, 130, 246, 0.45);
  background: rgba(59, 130, 246, 0.1);
  font-weight: 600;
}

.available-day-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(54px, 1fr));
  gap: 6px;
}

.available-day-item {
  border: 1px solid var(--border-color);
  background: var(--bg-element);
  color: var(--text-secondary);
  border-radius: 8px;
  padding: 6px 4px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  cursor: pointer;
}

.available-day-item:hover {
  border-color: var(--color-primary);
  color: var(--text-primary);
}

.available-day-item.active {
  border-color: rgba(59, 130, 246, 0.5);
  background: rgba(59, 130, 246, 0.14);
  color: #2563eb;
}

.available-day-item .day {
  font-size: 14px;
  font-weight: 700;
  line-height: 1;
}

.available-day-item .count {
  font-size: 10px;
  opacity: 0.75;
}

.available-day-empty {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 4px 2px;
}

.timeline-available-loading,
.timeline-available-empty {
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--text-secondary);
}

.timeline-available-summary {
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--text-secondary);
}

.available-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.available-date-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.available-date-chip {
  border: 1px solid var(--border-color);
  background: var(--bg-element);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 11px;
  line-height: 1.2;
  cursor: pointer;
}

.available-date-chip:hover {
  border-color: var(--color-primary);
  color: var(--text-primary);
}

.available-date-chip.active {
  background: rgba(59, 130, 246, 0.14);
  border-color: rgba(59, 130, 246, 0.5);
  color: #2563eb;
  font-weight: 600;
}

.chip-count {
  margin-left: 3px;
  opacity: 0.72;
}

.quality-btn {
  width: 102px;
  min-width: 102px;
  max-width: 102px;
  flex: 0 0 102px;
  min-height: 34px;
  height: 34px;
  font-size: 15px;
  padding: 0 10px;
  line-height: 34px;
  border-radius: 10px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.speed-btn {
  min-width: 56px;
  font-variant-numeric: tabular-nums;
}

.triple-btn {
  min-width: 64px;
  font-size: 13px;
}

.triple-btn.active {
  background: var(--color-primary);
  color: #fff;
  border-color: var(--color-primary);
}

.runtime-quality-btn {
  flex: 0 0 auto;
}

.timeline-runtime-row {
  grid-area: runtime;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 10px;
  min-width: 0;
  width: 100%;
}

/* 移除冗余样式 */

.runtime-hints {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1 1 auto;
  flex-wrap: wrap;
  row-gap: 2px;
}

.runtime-hints--inline {
  flex: 1 1 auto;
}

.runtime-hint {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.runtime-hint--notice {
  color: #a16207;
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
}



.timeline-gpu-inline {
  min-width: 240px;
  max-width: 460px;
  flex: 0 1 auto;
}

@media (max-width: 1200px) and (min-width: 769px) {
  .control-actions {
    grid-template-columns: 1fr;
    grid-template-areas:
      "main"
      "runtime"
      "date";
    row-gap: 10px;
  }

  .date-picker-wrap {
    min-width: 0;
    width: 100%;
    max-width: 100%;
  }

  .date-quick-row {
    justify-content: flex-start;
  }
}

.timeline-bar-container {
  position: relative;
  width: 100%;
}

.timeline-notice {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 12px;
  color: #a16207;
  background: rgba(250, 204, 21, 0.12);
  border: 1px solid rgba(250, 204, 21, 0.35);
}

.timeline-bar-wrapper {
  height: 72px;
  background: var(--bg-element);
  border-radius: 4px;
  position: relative;
  overflow-x: hidden;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  cursor: default;
}

.timeline-bar-wrapper.dragging {
  cursor: grabbing;
}

.timeline-bar-inner {
  height: 100%;
}

.timeline-bar-inner.is-mobile {
  display: flex;
}

.timeline-track-spacer {
  flex-shrink: 0;
  height: 100%;
}

.timeline-track {
  position: relative;
  height: 100%;
  min-width: 100%;
  flex-shrink: 0;
  transform-origin: left top;
}

.timeline-tick {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(255,255,255,0.05);
}

.timeline-tick.major-tick {
  background: rgba(255,255,255,0.2);
}

.tick-label {
  position: absolute;
  top: 4px;
  left: 6px;
  font-size: 11px;
  color: var(--color-text-secondary);
  font-weight: 600;
  letter-spacing: 0.2px;
  user-select: none;
  z-index: 2;
  text-shadow: 0 1px 2px rgba(255, 255, 255, 0.8);
  transition: color 0.3s ease;
}

[data-theme="dark"] .tick-label {
  color: rgba(255, 255, 255, 0.65);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
}

.timeline-segment {
  position: absolute;
  bottom: 8px; /* Stick closer to bottom */
  height: 32px;
  background: var(--color-primary);
  opacity: 0.8;
  border-radius: 4px;
  transition: opacity 0.2s;
}

.timeline-segment:hover {
  opacity: 1;
}

.timeline-segment--mp4 {
  background: var(--color-primary);
}

.timeline-segment--ts {
  background: #f59e0b;
}

.timeline-segment-status--recording {
  box-shadow: 0 0 0 1px rgba(255, 59, 48, 0.65) inset, 0 0 8px rgba(255, 59, 48, 0.35);
}

.timeline-segment-status--stopped {
  filter: saturate(0.9);
}

.timeline-segment-status--converting {
  background-image: repeating-linear-gradient(
    135deg,
    rgba(255, 255, 255, 0.18) 0,
    rgba(255, 255, 255, 0.18) 6px,
    rgba(255, 255, 255, 0.02) 6px,
    rgba(255, 255, 255, 0.02) 12px
  );
}

.timeline-segment-status--failed {
  opacity: 0.45;
  filter: grayscale(0.45);
}

.timeline-cursor {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #ff4757;
  z-index: 4;
  pointer-events: none;
}
.timeline-cursor::after {
  content: '';
  position: absolute;
  top: 0;
  left: -4px;
  width: 10px;
  height: 10px;
  background: #ff4757;
  border-radius: 50%;
}
.timeline-cursor.fixed-center {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 2px;
  background: #ff4757;
  z-index: 10;
  pointer-events: none;
  transform: translateX(-50%);
}
.timeline-cursor.fixed-center::after {
  content: '';
  position: absolute;
  top: 0;
  left: -4px;
  width: 10px;
  height: 10px;
  background: #ff4757;
  border-radius: 50%;
}

.timeline-cursor.hover-cursor {
  background: #22d3ee;
  z-index: 9;
}

.timeline-cursor.hover-cursor::after {
  background: #22d3ee;
}

.btn-text-mobile {
  display: none;
}

@media (max-width: 768px) {
  .timeline-player-container {
    min-height: 0;
  }
  .timeline-controls {
    padding: 8px 10px calc(24px + env(safe-area-inset-bottom, 0px));
  }
  .player-viewport {
    min-height: 180px;
    max-height: 38vh;
  }
  .streamer-meta {
    display: none;
  }
  .streamer-avatar,
  .streamer-avatar-placeholder {
    width: 30px;
    height: 30px;
    flex-basis: 30px;
  }
  .streamer-platform {
    font-size: 10px;
    padding: 2px 7px;
  }
  .streamer-name {
    font-size: 13px;
  }
  .control-actions {
    display: grid;
    grid-template-columns: 1fr;
    grid-template-areas:
      "main"
      "date"
      "runtime";
    gap: 8px;
    margin-bottom: 8px;
    align-items: stretch;
  }
  .control-main {
    grid-area: main;
    width: 100%;
    gap: 6px;
    flex-wrap: wrap;
    min-width: 0;
  }
  .control-main :deep(.btn.btn-sm) {
    min-width: 44px;
    height: 40px;
    padding: 0 10px;
    border-radius: 12px;
  }
  .time-display {
    font-size: 12px;
    display: flex;
    flex: 0 0 auto;
    width: auto;
    min-width: 120px;
    max-width: 140px;
    flex-direction: row;
    align-items: center;
    gap: 4px;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    order: 6;
  }
  .time-hint-inline {
    order: 99;
    width: 100%;
    justify-content: flex-end;
  }
  .time-line-current {
    font-size: 12px;
  }
  .time-line-total {
    font-size: 11px;
    opacity: 0.8;
  }
  .fullscreen-btn {
    order: 2;
  }
  .speed-btn {
    order: 3;
    min-width: 52px;
    height: 40px;
  }
  .mute-btn {
    order: 4;
  }
  .pip-btn {
    order: 5;
  }
  .triple-btn {
    order: 6;
    min-width: 52px;
    height: 40px;
    font-size: 12px;
  }
  .date-picker-wrap {
    grid-area: date;
    width: 100%;
    min-width: 0;
    margin-top: 0;
    margin-left: 0;
    max-width: 100%;
  }
  .date-nav-row {
    width: 100%;
    min-width: 0;
  }
  .date-nav-btn {
    min-width: 48px;
    padding: 0 6px;
    height: 36px;
    min-height: 36px;
    line-height: 36px;
    border-radius: 10px;
  }
  .date-picker {
    width: auto;
    min-width: 0;
    min-height: 36px;
    flex: 1;
  }
  .date-quick-row {
    justify-content: flex-start;
    gap: 5px;
    flex-wrap: nowrap;
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 2px;
  }
  .date-quick-row .btn {
    flex: 0 0 auto;
  }
  .btn-text-desktop {
    display: none;
  }
  .btn-text-mobile {
    display: inline;
  }
  .date-panel-latest {
    font-size: 10px;
    flex: 0 0 auto;
  }
  .available-date-modal-overlay {
    padding: 12px;
    align-items: flex-end;
  }
  .available-date-panel {
    width: min(680px, calc(100vw - 24px));
    max-height: min(72vh, 480px);
    padding: 8px;
    border-radius: 8px;
  }
  .available-date-panel-title {
    font-size: 13px;
  }
  .available-date-panel-meta {
    font-size: 11px;
    margin-bottom: 6px;
  }
  .available-month-tab {
    font-size: 10px;
    padding: 3px 8px;
  }
  .available-day-grid {
    grid-template-columns: repeat(auto-fill, minmax(50px, 1fr));
    gap: 5px;
  }
  .available-day-item {
    border-radius: 7px;
    padding: 5px 4px;
  }
  .available-day-item .day {
    font-size: 13px;
  }
  .available-day-item .count {
    font-size: 9px;
  }
  .quality-btn {
    width: 86px;
    min-width: 86px;
    max-width: 86px;
    flex: 0 0 86px;
    min-height: 40px;
    height: 40px;
    font-size: 14px;
    padding: 0 10px;
    line-height: 40px;
    border-radius: 12px;
    opacity: 1;
  }
  .timeline-runtime-row {
    grid-area: runtime;
    flex-direction: row;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
    min-width: 0;
  }
  .runtime-hints {
    display: none !important;
  }
  /* 移除冗余样式 */
  .runtime-hints {
    order: 4;
    width: 100%;
    flex: 1 1 100%;
    gap: 6px;
  }
  .runtime-quality-btn {
    order: 1;
    align-self: center;
    width: auto;
    min-width: 74px;
    max-width: 96px;
    flex: 0 0 auto;
    height: 36px;
    min-height: 36px;
    line-height: 36px;
    padding: 0 12px;
    border-radius: 10px;
    font-size: 13px;
  }
  .runtime-hint {
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .timeline-gpu-inline {
    order: 2;
    min-width: 0;
    width: auto;
    flex: 1 1 auto;
    max-width: 100%;
    height: 36px;
    min-height: 36px;
  }
  .timeline-gpu-inline :deep(.gpu-runtime-inline) {
    height: 36px;
    min-height: 36px;
  }
  .timeline-gpu-inline :deep(.gpu-runtime-bottom) {
    height: 100%;
    align-items: center;
  }
  .timeline-notice,
  .timeline-available-loading,
  .timeline-available-empty {
    display: none !important;
  }
  .available-label {
    font-size: 11px;
    margin-bottom: 5px;
  }
  .available-date-chip {
    font-size: 10px;
    padding: 3px 8px;
  }
  .timeline-bar-wrapper {
    height: 60px; /* Make it easier to tap on mobile */
    margin-top: 8px;
    overflow-x: auto;
    overflow-y: hidden;
    touch-action: pan-x;
    cursor: grab;
  }
  .timeline-track {
    min-width: 800px;
  }
  .timeline-segment {
    height: 32px;
  }
  .tick-label {
    top: 2px;
    left: 2px;
    font-size: 9px;
    transform-origin: left top;
    transform: scale(0.9);
  }
}

</style>
