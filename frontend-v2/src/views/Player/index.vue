<template>
  <div class="player-page">
    <!-- 播放器主体区域 -->
    <div class="main-layout">
      <!-- 左侧：显示区 -->
      <div class="primary-content" ref="primaryContentRef">
        <!-- 视频 / 音频容器 -->
        <div
          class="video-container"
          :class="{
            gallery: isGallery,
            'vertical-video': isVerticalVideo && !isAudio,
            'triple-screen': showTripleScreen,
            'mode-3': tripleScreenMode === 3,
            'mode-4': tripleScreenMode === 4
          }"
          :style="videoContainerStyle"
          @mouseleave="showControls = false"
          @mousemove="onMouseMove"
          @touchstart="handleTouchStartFromContainer"
          @wheel.prevent="handleWheelSwitch"
          @click="handleVideoContainerClick"
          ref="videoContainerRef"
        >
          <div class="video-slider-track" :style="sliderStyle">
            <!-- 上一集预览卡片（仅移动端显示） -->
            <div
              class="preview-card prev"
              v-if="prevVideoItem"
              :style="prevCardStyle"
            >
              <img :src="getThumbnailUrl(prevVideoItem)" class="preview-bg" />
              <div class="preview-overlay">
                <div class="preview-label mobile-only">上滑查看上一集</div>
                <div class="preview-label pc-only">滚轮上滑查看上一集</div>
                <div class="preview-title">{{ prevVideoItem.title }}</div>
              </div>
            </div>

            <!-- 当前视频容器 -->
            <div class="current-video-wrapper">
              <div
                class="video-wrapper"
                :class="{ 
                  'audio-mode': isAudio, 
                  'image-mode': isImage, 
                  'triple-screen-mode': showTripleScreen,
                  'mode-3': tripleScreenMode === 3,
                  'mode-4': tripleScreenMode === 4
                }"
                :style="{
                  '--multi-screen-count': tripleScreenMode
                }"
              >
                <!-- 移动端顶部标题 -->
                <div
                  class="video-top-info mobile-only"
                  :class="{ visible: showControls || isPaused }"
                >
                  <h1 class="mobile-video-title">
                    {{ currentVideo?.title || "正在播放..." }}
                  </h1>
                </div>
                <!-- 多连屏：最左侧镜像 (仅在 4 连模式下显示) -->
                <video
                  v-if="showTripleScreen && mirrorSrc && tripleScreenMode === 4"
                  class="triple-mirror left far"
                  :class="{ 'enhance-on': isEnhanced }"
                  :src="mirrorSrc"
                  :loop="playbackMode === 'single'"
                  muted
                  playsinline
                  ref="tripleLeftFarRef"
                  @loadeddata="syncTripleMirrors"
                  @play="syncTripleMirrors"
                ></video>
                <video
                  v-if="showTripleScreen && mirrorSrc"
                  class="triple-mirror left"
                  :class="{ 'enhance-on': isEnhanced }"
                  :src="mirrorSrc"
                  :loop="playbackMode === 'single'"
                  muted
                  playsinline
                  ref="tripleLeftRef"
                  @loadeddata="syncTripleMirrors"
                  @play="syncTripleMirrors"
                ></video>

                <video
                  :key="mediaElementKey"
                  v-if="!isGallery && !isImage"
                  ref="videoRef"
                  :src="currentSrc"
                  :loop="playbackMode === 'single'"
                  :style="{ transform: `rotate(${rotation}deg)` }"
                  @play="onPlay"
                  @pause="onPause"
                  @timeupdate="handleTimeUpdate"
                  @progress="handleProgress"
                  @loadedmetadata="handleLoadedMetadata"
                  @loadeddata="handleMediaReady"
                  @canplay="handleMediaReady"
                  @ended="handleEnded"
                  @enterpictureinpicture="onEnterPIP"
                  @leavepictureinpicture="onLeavePIP"
                  :class="{ 'enhance-on': isEnhanced, 'hidden-video': isAudio }"
                  autoplay
                  playsinline
                >
                  <track
                    v-for="track in subtitleTrackSources"
                    :key="track.id"
                    kind="subtitles"
                    :label="track.label"
                    :srclang="track.lang || 'und'"
                    :src="track.src"
                  />
                </video>

                <!-- 多连屏：右镜像 -->
                <video
                  v-if="showTripleScreen && mirrorSrc"
                  class="triple-mirror right"
                  :class="{ 'enhance-on': isEnhanced }"
                  :src="mirrorSrc"
                  :loop="playbackMode === 'single'"
                  muted
                  playsinline
                  ref="tripleRightRef"
                  @loadeddata="syncTripleMirrors"
                  @play="syncTripleMirrors"
                ></video>

                <img
                  v-if="isImage"
                  :key="mediaElementKey"
                  :src="currentImageSrc"
                  class="single-image-media"
                  :alt="currentVideo?.title || '图片'"
                  @load="onSingleImageLoad"
                  @error="handleThumbnailError"
                />

                <!-- 图集播放模式 -->
                <div v-if="isGallery" class="gallery-player">
                  <div class="gallery-content">
                    <transition name="fade" mode="out-in">
                      <div :key="galleryCurrentIndex" class="gallery-item">
                        <img
                          v-if="
                            galleryItems[galleryCurrentIndex]?.type === 'image'
                          "
                          :src="galleryItems[galleryCurrentIndex].url"
                          class="gallery-media"
                          @click="handleGalleryMediaClick"
                          @load="onGalleryMediaLoad"
                          @error="handleThumbnailError"
                        />
                        <video
                          v-else-if="
                            galleryItems[galleryCurrentIndex]?.type === 'video'
                          "
                          :src="galleryItems[galleryCurrentIndex].url"
                          class="gallery-media"
                          autoplay
                          loop
                          muted
                          playsinline
                          @click="handleGalleryMediaClick"
                          @loadedmetadata="onGalleryMediaLoad"
                          @error="handleThumbnailError"
                        ></video>
                      </div>
                    </transition>

                    <!-- 加载中状态 -->
                    <div v-if="galleryLoading" class="gallery-loading">
                      <div class="spinner"></div>
                    </div>

                    <!-- 左右切换箭头 (仅在非播放状态下显示更明显) -->
                    <button
                      class="gallery-nav prev"
                      @click="prevGalleryItem"
                      v-if="galleryItems.length > 1"
                    >
                      <Icon name="chevron-left" :size="36" />
                    </button>
                    <button
                      class="gallery-nav next"
                      @click="nextGalleryItem"
                      v-if="galleryItems.length > 1"
                    >
                      <Icon name="chevron-right" :size="36" />
                    </button>
                  </div>

                  <!-- 背景音乐 (BGM) -->
                  <audio
                    v-if="galleryBgm"
                    ref="galleryAudioRef"
                    :src="galleryBgm.url"
                    loop
                  ></audio>
                </div>

                <!-- 音频可视化模式 -->
                <LyricsVisualizer
                  v-if="isAudio"
                  :currentCoverUrl="currentCoverUrl"
                  :currentLyricsUrl="currentLyricsUrl"
                  :currentTime="currentTime"
                  :analyser="analyserRef"
                />

                <!-- 极简覆盖层 -->
                <!-- 交互层 (最高层级) -->
                <div
                  class="interactive-layer"
                  :class="{ 'touch-active': isTouchDevice }"
                  @pointerdown="handlePointerStart"
                  @pointermove="handlePointerMove"
                  @pointerup="handlePointerEnd"
                  @pointercancel="handlePointerEnd"
                  @touchstart="handleTouchStart"
                  @touchmove.prevent="handleTouchMove"
                  @touchend="handleTouchEnd"
                  @touchcancel="handleTouchCancel"
                >
                  <div
                    class="touch-zone left"
                    @click="handleTouchZone('prev')"
                  ></div>
                  <div
                    class="touch-zone center"
                    @click="handleTouchZone('center')"
                  ></div>
                  <div
                    class="touch-zone right"
                    @click="handleTouchZone('next')"
                  ></div>
                </div>

                <!-- 滑动切换提示 -->
                <div
                  v-if="swipeFeedback.show"
                  class="swipe-feedback"
                  :class="swipeFeedback.type"
                >
                  <Icon
                    :name="
                      swipeFeedback.type === 'next'
                        ? 'chevron-up'
                        : 'chevron-down'
                    "
                    :size="32"
                  />
                  <span>{{
                    swipeFeedback.type === "next" ? "下一集" : "上一集"
                  }}</span>
                </div>

                <!-- 极简覆盖层 -->
                <div class="stage-overlay" :class="{ hidden: !showControls }">
                  <div
                    class="center-play-btn"
                    v-if="showCenterPlayButton"
                    @click.stop="togglePlay"
                  >
                    <Icon name="play" :size="48" />
                  </div>
                </div>

                <!-- 双击提示动画 -->
                <div
                  v-if="seekFeedback.show"
                  class="seek-feedback"
                  :class="seekFeedback.type"
                >
                  <Icon
                    :name="
                      seekFeedback.type === 'forward'
                        ? 'chevron-right'
                        : 'chevron-left'
                    "
                    :size="32"
                  />
                  <span>{{
                    seekFeedback.type === "forward" ? "+10s" : "-10s"
                  }}</span>
                </div>

                <!-- 全屏模式下的统一控制栏 (PC/Mobile 通用) -->
                <div
                  v-if="isFullscreen"
                  class="fullscreen-controls"
                  :class="{
                    visible: showControls || isPaused || isDragging,
                    'is-touch': isTouchDevice,
                    'is-portrait-layout': isPortrait,
                  }"
                  @mouseenter="handleControlMouseEnter"
                  @mouseleave="handleControlMouseLeave"
                  @touchstart.passive="handleControlTouchStart"
                  @touchend="handleControlTouchEnd"
                  @touchcancel="handleControlTouchEnd"
                >
                  <!-- 第一行：进度条 -->
                  <div class="fullscreen-bar-section">
                    <PlayerProgressBar
                      root-class="progress-slot"
                      :current-time="formattedCurrentTime"
                      :duration="formattedDuration"
                      :buffer-percent="bufferPercent"
                      :progress-percent="progressPercent"
                      :time-layout="isPortrait ? 'stacked' : 'ends'"
                      @seekStart="startSeek"
                      @seekMove="doSeek"
                      @seekEnd="endSeek"
                    />
                  </div>

                  <!-- 第二行：操作按钮组 (支持换行以适配竖屏) -->
                  <div class="fullscreen-toolbar">
                    <!-- 基本控制组 -->
                    <div class="toolbar-group main-actions">
                      <button
                        class="fullscreen-action-btn"
                        @click="prevVideo"
                        title="上一个"
                      >
                        <Icon name="chevron-left" :size="18" />
                      </button>
                      <button
                        class="fullscreen-action-btn primary"
                        v-if="!isImage"
                        @click="togglePlay"
                        :title="isPaused ? '播放' : '暂停'"
                      >
                        <Icon :name="isPaused ? 'play' : 'pause'" :size="20" />
                      </button>
                      <button
                        class="fullscreen-action-btn"
                        @click="nextVideo"
                        title="下一个"
                      >
                        <Icon name="chevron-right" :size="18" />
                      </button>
                    </div>

                    <div class="toolbar-divider pc-only"></div>

                    <!-- 状态设置组 -->
                    <div class="toolbar-group settings-actions">
                      <button
                        class="fullscreen-action-btn pill"
                        @click="cyclePlaybackSpeed"
                        :title="`播放倍速: ${playbackSpeed}x`"
                      >
                        <span>{{ playbackSpeed }}x</span>
                      </button>
                      <button
                        class="fullscreen-action-btn pill"
                        @click="cycleQuality"
                        :title="`画质: ${qualityOptionsLabel}`"
                      >
                        <span>{{ qualityOptionsLabel }}</span>
                      </button>
                      <button
                        class="fullscreen-action-btn pill"
                        @click="cyclePlaybackMode"
                        :title="`循环模式: ${playbackModeLabel}`"
                      >
                        <Icon :name="playbackModeIcon" :size="16" />
                      </button>
                      <button
                        class="fullscreen-action-btn"
                        @click="toggleMute"
                        :title="isMuted ? '取消静音' : '静音'"
                      >
                        <Icon
                          :name="isMuted ? 'volume-x' : 'volume-2'"
                          :size="18"
                        />
                      </button>
                    </div>

                    <div class="toolbar-divider pc-only"></div>

                    <!-- GPU 与各种功能组 -->
                    <div class="toolbar-group extra-actions">
                      <GpuRuntimeInline
                        class="fullscreen-gpu pc-only"
                        :gpu-stats="gpuStatusData"
                        :is-loading="gpuStatusLoading"
                        :error-text="gpuStatusError"
                        :info="displaySideInfoLabel"
                      />
                      <!-- 移动端专有强制横屏按钮 -->
                      <button
                        v-if="isTouchDevice"
                        class="fullscreen-action-btn"
                        @click="toggleForceLandscape"
                        :title="isPortrait ? '旋转至横屏' : '锁定横屏'"
                      >
                        <Icon
                          :name="
                            isForceLandscape ? 'screen-off' : 'screen-rotation'
                          "
                          :size="18"
                        />
                      </button>
                      <button
                        class="fullscreen-action-btn exit-btn"
                        @click="toggleFullScreen"
                        :title="isTouchDevice ? '收起' : '退出全屏'"
                      >
                        <Icon name="minimize" :size="20" />
                      </button>
                    </div>
                  </div>
                </div>

                <!-- 移动端沉浸式进度条 (非全屏下显示) -->
                <div
                  v-if="!isFullscreen"
                  class="video-bottom-controls mobile-only"
                  :class="{ visible: showControls || isPaused || isDragging }"
                  @touchstart.passive="handleControlTouchStart"
                  @touchend="handleControlTouchEnd"
                  @touchcancel="handleControlTouchEnd"
                >
                  <div class="embedded-info">
                    <div class="embedded-time">
                      <span class="time-current">{{
                        formattedCurrentTime
                      }}</span>
                      <span class="time-divider"> / </span>
                      <span class="time-duration">{{ formattedDuration }}</span>
                    </div>
                  </div>
                  <div
                    class="embedded-progress-container"
                    @touchstart.prevent.stop="startSeek"
                    @touchmove.prevent.stop="doSeek"
                    @touchend.stop="endSeek"
                    @touchcancel.stop="endSeek"
                  >
                    <div class="progress-bg"></div>
                    <div
                      class="progress-buffer"
                      :style="{ width: bufferPercent + '%' }"
                    ></div>
                    <div
                      class="progress-current"
                      :style="{ width: progressPercent + '%' }"
                    ></div>
                    <div
                      class="progress-handle"
                      :style="{ left: progressPercent + '%' }"
                    ></div>
                  </div>
                </div>

                <!-- 极细底部进度条 (非全屏下显示) -->
                <div
                  v-if="!isFullscreen"
                  class="bottom-slim-progress mobile-only"
                  v-show="!showControls && !isPaused && !isDragging"
                >
                  <div
                    class="current"
                    :style="{ width: progressPercent + '%' }"
                  ></div>
                </div>
              </div>
              <!-- End of video-wrapper -->
            </div>
            <!-- End of current-video-wrapper -->

            <!-- 下一集预览卡片（仅移动端显示） -->
            <div
              class="preview-card next"
              v-if="nextVideoItem"
              :style="nextCardStyle"
            >
              <img :src="getThumbnailUrl(nextVideoItem)" class="preview-bg" />
              <div class="preview-overlay">
                <div class="preview-label mobile-only">下滑查看下一集</div>
                <div class="preview-label pc-only">滚轮下滑查看下一集</div>
                <div class="preview-title">{{ nextVideoItem.title }}</div>
              </div>
            </div>
          </div>
          <!-- End of video-slider-track -->
        </div>

        <!-- 视频标题与基本信息 (非剧场模式下在主列) -->
        <div class="video-info-section">
          <!-- PC端标题已合并入作者信息行 -->

          <VideoControls
            :isImage="isImage"
            :isPaused="isPaused"
            :isMuted="isMuted"
            v-model:playbackSpeed="playbackSpeed"
            v-model:currentQuality="currentQuality"
            :qualityOptions="qualityOptions"
            v-model:selectedSubtitleId="selectedSubtitleId"
            :subtitleOptions="subtitleOptions"
            :isAudio="isAudio"
            :isGallery="isGallery"
            :playbackModeIcon="playbackModeIcon"
            :playbackModeLabel="playbackModeLabel"
            v-model:autoPlayNext="autoPlayNext"
            v-model:enableBackgroundPlay="enableBackgroundPlay"
            v-model:isEnhanced="isEnhanced"
            v-model:tripleScreenMode="tripleScreenMode"
            :tripleScreenSliderStyle="tripleScreenSliderStyle"
            :formattedCurrentTime="formattedCurrentTime"
            :formattedDuration="formattedDuration"
            :bufferPercent="bufferPercent"
            :progressPercent="progressPercent"
            :gpuStatusData="gpuStatusData"
            :gpuStatusLoading="gpuStatusLoading"
            :gpuStatusError="gpuStatusError"
            :displaySideInfoLabel="displaySideInfoLabel"
            @prev-video="prevVideo"
            @toggle-play="togglePlay"
            @next-video="nextVideo"
            @toggle-mute="toggleMute"
            @toggle-pip="togglePIP"
            @toggle-fullscreen="toggleFullScreen"
            @show-playlist="showPlaylistDrawer = true"
            @show-settings="showSettingsDrawer = true"
            @cycle-playback-mode="cyclePlaybackMode"
            @seekStart="startSeek"
            @seekMove="doSeek"
            @seekEnd="endSeek"
          >
            <template #author-info>
              <AuthorInfoCard
                :currentVideo="currentVideo"
                :subscriptionId="subscriptionId"
                :subscriptionName="subscriptionName"
                @play-author-videos="playAuthorVideos"
                @clear-subscription-filter="clearSubscriptionFilter"
              />
            </template>
          </VideoControls>
        </div>
      </div>

      <!-- 移动端播放列表抽屉 -->
      <div
        class="bottom-drawer-overlay playlist-drawer"
        v-if="showPlaylistDrawer"
        @click="showPlaylistDrawer = false"
      >
        <div class="bottom-drawer" @click.stop>
          <div class="drawer-header">
            <div class="drawer-handle"></div>
            <h3>播放列表 ({{ filteredPlaylist.length }}/{{ playlist.length }})</h3>
            <button class="close-btn" @click="showPlaylistDrawer = false">
              <Icon name="x" :size="20" />
            </button>
          </div>
          <PlaylistPanel
            v-model:playlistFilterPlatform="playlistFilterPlatform"
            v-model:playlistFilterScope="playlistFilterScope"
            v-model:playlistFilterAuthor="playlistFilterAuthor"
            v-model:playlistFilterKeyword="playlistFilterKeyword"
            :isMobile="true"
            :filteredPlaylist="filteredPlaylist"
            :playlist="playlist"
            :currentVideoId="currentVideoId"
            :subscriptionId="subscriptionId"
            :subscriptionName="subscriptionName"
            :playlistAuthorOptions="playlistAuthorOptions"
            @play="playByVideoId"
            @refresh="refreshPlaylist"
            @clear-subscription-filter="clearSubscriptionFilter"
            @reset-filters="resetPlaylistFilters"
            @apply-filters="applyPlaylistFilters"
            :getThumbnailUrl="getThumbnailUrl"
            :handleThumbnailError="handleThumbnailError"
            :formatTime="formatTime"
          />
        </div>
      </div>

      <!-- 播放设置组件 -->
      <SettingsDrawer
        v-if="showSettingsDrawer"
        @close="showSettingsDrawer = false"
        v-model:playbackSpeed="playbackSpeed"
        v-model:currentQuality="currentQuality"
        v-model:selectedSubtitleId="selectedSubtitleId"
        v-model:playbackMode="playbackMode"
        v-model:autoPlayNext="autoPlayNext"
        v-model:enableBackgroundPlay="enableBackgroundPlay"
        v-model:isEnhanced="isEnhanced"
        v-model:tripleScreenMode="tripleScreenMode"
        :qualityOptions="qualityOptions"
        :subtitleOptions="subtitleOptions"
        :isAudio="isAudio"
        :isGallery="isGallery"
        :gpuStatusData="gpuStatusData"
        :gpuStatusLoading="gpuStatusLoading"
        :gpuStatusError="gpuStatusError"
        :displaySideInfoLabel="displaySideInfoLabel"
        :tripleScreenSliderStyle="tripleScreenSliderStyle"
      />

      <!-- 右侧：播放列表与推荐 (PC端) -->
      <div class="secondary-content">
        <PlaylistPanel
          v-model:playlistFilterPlatform="playlistFilterPlatform"
          v-model:playlistFilterScope="playlistFilterScope"
          v-model:playlistFilterAuthor="playlistFilterAuthor"
          v-model:playlistFilterKeyword="playlistFilterKeyword"
          :isMobile="false"
          :filteredPlaylist="filteredPlaylist"
          :playlist="playlist"
          :currentVideoId="currentVideoId"
          :subscriptionId="subscriptionId"
          :subscriptionName="subscriptionName"
          :playlistAuthorOptions="playlistAuthorOptions"
          @play="playByVideoId"
          @refresh="refreshPlaylist"
          @clear-subscription-filter="clearSubscriptionFilter"
          @reset-filters="resetPlaylistFilters"
          @apply-filters="applyPlaylistFilters"
          :getThumbnailUrl="getThumbnailUrl"
          :handleThumbnailError="handleThumbnailError"
          :formatTime="formatTime"
          :playlistContainerHeightStyle="playlistContainerHeightStyle"
          :currentIndex="currentIndex"
        />
      </div>
    </div>
    <!-- SVG 画质增强滤镜定义 (卷积锐化) -->
    <svg style="position: absolute; width: 0; height: 0;" aria-hidden="true">
      <filter id="video-sharpen">
        <feConvolveMatrix 
          order="3" 
          preserveAlpha="true" 
          kernelMatrix="0 -1 0 -1 5 -1 0 -1 0" 
        />
      </filter>
    </svg>
  </div>
</template>

<script setup>
import {
  ref,
  computed,
  onMounted,
  onBeforeUnmount,
  onActivated,
  onDeactivated,
  watch,
  nextTick,
} from "vue";
import { useRoute, onBeforeRouteLeave } from "vue-router";
import { playerApi } from "@/api/player";
import { systemApi } from "@/api/system";
import { tasksApi } from "@/api/tasks";
import { buildAuthedWsUrl } from "@/utils/wsAuth";
import Icon from "@/components/common/Icon.vue";
import PlayerProgressBar from "@/components/common/PlayerProgressBar.vue";
import GpuRuntimeInline from "@/components/common/GpuRuntimeInline.vue";

// 引入重构后的 Composables 逻辑及子组件
import { usePlaylist } from "@/views/Player/composables/usePlaylist";
import { useVideoPlayback } from "@/views/Player/composables/useVideoPlayback";
import { useBackgroundBridge } from "@/views/Player/composables/useBackgroundBridge";
import { usePlayerGestures } from "@/views/Player/composables/usePlayerGestures";
import { useScrollLock } from "@/views/Player/composables/useScrollLock";
import { useTranscodingStatus } from "@/views/Player/composables/useTranscodingStatus";
import AuthorInfoCard from "@/views/Player/components/AuthorInfoCard.vue";
import VideoControls from "@/views/Player/components/VideoControls.vue";
import LyricsVisualizer from "@/views/Player/components/LyricsVisualizer.vue";
import PlaylistPanel from "@/views/Player/components/PlaylistPanel.vue";
import SettingsDrawer from "@/views/Player/components/SettingsDrawer.vue";

defineOptions({ name: "Player" });

const route = useRoute();

// ── 桥接状态（在 usePlaylist ↔ useVideoPlayback 之间共享）──
const isPaused = ref(false);
const currentTime = ref(0);
const streamOffset = ref(0);
const videoRef = ref(null);
const isTouchDevice = ref(false);
const showControls = ref(true);
const isDragging = ref(false);
const isSwitchingMedia = ref(false);
const pendingRestorePIP = ref(false);
const primaryContentRef = ref(null);
const videoContainerRef = ref(null);
const galleryAudioRef = ref(null);

const showSettingsDrawer = ref(false);
const showPlaylistDrawer = ref(false);
const swipeFeedback = ref({ show: false, type: "next" });

// 手势共用响应式状态 (供 usePlayerGestures 双向共享)
const isSwiping = ref(false);
const dragOffset = ref(0);
const isTransitioning = ref(false);
const containerHeight = ref(0);
const showGestureGuide = ref(true);
let switchSequence = 0;
let slideSwitchTimer = null;

const isPortrait = ref(false);
const updateIsTouchDevice = () => {
  isTouchDevice.value = !!(
    navigator.maxTouchPoints ||
    (window.matchMedia && window.matchMedia("(pointer: coarse)").matches)
  );
  isPortrait.value = window.innerHeight > window.innerWidth;
};

// 移动端防滚动穿透锁
const { lock: lockPageScrollOnMobile, unlock: forceUnlockPageScroll } = useScrollLock();

// 模板直引用的本地值与函数
const sliderStyle = computed(() => ({}));
const cardHeight = computed(() =>
  containerHeight.value ||
  videoContainerRef.value?.offsetHeight ||
  window.innerHeight ||
  600
);
const cardPercentOffset = computed(() => (dragOffset.value / cardHeight.value) * 100);
const cardTransitionStyle = computed(() =>
  isTransitioning.value
    ? "transform 0.3s ease-out, opacity 0.3s ease-out"
    : "none"
);
const cardBaseOpacity = computed(() =>
  Math.min(Math.abs(dragOffset.value) / (cardHeight.value * 0.16), 1)
);

const prevCardStyle = computed(() => ({
  transform: `translate3d(0, ${-100 + cardPercentOffset.value}%, 0)`,
  opacity: cardBaseOpacity.value,
  transition: cardTransitionStyle.value,
}));
const nextCardStyle = computed(() => ({
  transform: `translate3d(0, ${100 + cardPercentOffset.value}%, 0)`,
  opacity: cardBaseOpacity.value,
  transition: cardTransitionStyle.value,
}));

const getSwitchPreviewHeight = () => {
  if (!containerHeight.value && videoContainerRef.value) {
    containerHeight.value = videoContainerRef.value.offsetHeight;
  }
  return containerHeight.value || window.innerHeight || 600;
};

const getSwitchDirectionFromOffset = (offset) => {
  if (offset < 0) return "next";
  if (offset > 0) return "prev";
  return null;
};

const canSwitchDirection = (direction) => {
  if (playlist.value.length <= 1 && playbackMode.value !== "random") {
    return false;
  }
  if (direction === "next") {
    return !!nextVideoItem.value || playbackMode.value === "random";
  }
  if (direction === "prev") {
    return !!prevVideoItem.value || playbackMode.value === "random";
  }
  return false;
};

const setSwitchPreviewOffset = (offset) => {
  const direction = getSwitchDirectionFromOffset(offset);
  const damping = 0.38;
  dragOffset.value =
    direction && canSwitchDirection(direction) ? offset : offset * damping;
};

const cancelPendingSlideSwitch = () => {
  switchSequence++;
  if (slideSwitchTimer) {
    clearTimeout(slideSwitchTimer);
    slideSwitchTimer = null;
  }
};

// ── placeholder 引用，供 usePlaylist 在回调尚未定义时安全访问 ──
let _cleanupVideoConnection = null;
let _markPIPForSourceSwitch = null;
let _stopAudioVisualization = null;
let _initAudioAnalyzer = null;

// ── 初始化 usePlaylist (核心数据层) ──
const {
  playlist,
  currentIndex,
  subscriptionId,
  subscriptionName,
  taskId,
  playbackMode,
  autoPlayNext,
  playlistFilterPlatform,
  playlistFilterScope,
  playlistFilterAuthor,
  playlistFilterKeyword,
  videoProgressMap,
  isFetchingVideos,
  isUnmounting,
  galleryThumbnails,
  currentVideo,
  currentVideoId,
  isGallery,
  isAudio,
  isImage,
  prevVideoItem,
  nextVideoItem,
  normalizedPlaybackMode,
  playbackModeIcon,
  playbackModeLabel,
  filteredPlaylist,
  playlistAuthorOptions,
  qualityOptions,
  getThumbnailUrl,
  getTaskTypeText,
  getVideoPlatform,
  getVideoAuthorName,
  isImageFilename,
  encodeDownloadPath,
  isManualTaskVideo,
  isNeteaseMusicTask,
  formatTime,
  normalizePlaybackMode,
  shuffleArray,
  resetPlaylistFiltersState,
  saveJumpContext,
  loadJumpContext,
  clearJumpContext,
  fetchVideos,
  refreshPlaylist,
  applyPlaylistFilters,
  resetPlaylistFilters,
  clearSubscriptionFilter,
  handleEnded,
  cyclePlaybackMode,
  playAuthorVideos,
  loadPlaybackRecord,
  savePlaybackRecord,
  restoreVideoProgress,
  cancelSlideSwitch,
} = usePlaylist({
  videoRef,
  currentTime,
  streamOffset,
  isPaused,
  cancelPendingSlideSwitch,
  isSwitchingMedia,
  cleanupVideoConnection: () => _cleanupVideoConnection?.(),
  markPIPForSourceSwitch: () => _markPIPForSourceSwitch?.(),
  stopAudioVisualization: () => _stopAudioVisualization?.(),
  initAudioAnalyzer: () => _initAudioAnalyzer?.(),
  onRouteVideoSwitch: () => {
    if (videoRef.value) {
      videoRef.value.play().catch(() => { isPaused.value = true });
    } else if (isGallery.value) {
      fetchGalleryFiles(currentVideo.value);
    }
  },
});

// ── 初始化 useVideoPlayback (播放器核心控制层) ──
const {
  isPIP, isFullscreen, rotation, isVerticalVideo, videoAspectRatio,
  duration, originalDuration, originalVideoInfo, videoMetadataCache,
  bufferPercent, playbackSpeed, currentQuality, isEnhanced, isMuted,
  mirrorSrc,
  tripleScreenMode, tripleLeftRef, tripleLeftFarRef, tripleRightRef,
  galleryItems, galleryCurrentIndex, galleryBgm,
  autoRotateTimer, galleryLoading, galleryInterval,
  analyserRef,
  subtitleOptions, selectedSubtitleId,
  isControlHovered, isControlTouched, isForceLandscape,
  effectiveDuration, playlistContainerHeightStyle, videoContainerStyle,
  showTripleScreen, showCenterPlayButton, tripleScreenSliderStyle,
  mediaElementKey, currentCoverUrl, currentLyricsUrl, currentImageSrc,
  subtitleTrackSources, currentSrc,
  qualityOptionsLabel,
  formattedCurrentTime, formattedDuration, progressPercent,
  togglePlay, toggleMute, togglePIP, toggleFullScreen,
  cycleQuality, cyclePlaybackSpeed, toggleForceLandscape,
  shouldForceMediaReload,
  onPlay, onPause, handleTimeUpdate, handleProgress, handleLoadedMetadata,
  handleMediaReady, onEnterPIP, onLeavePIP,
  onSingleImageLoad, onGalleryMediaLoad,
  fetchGalleryFiles, startAutoRotate, stopAutoRotate,
  nextGalleryItem, prevGalleryItem, handleGalleryMediaClick,
  stopAudioVisualization, initAudioAnalyzer, cleanupAudioAnalyzer, resetAudioAnalyzer, ensureAudioAnalyzer,
  fetchCurrentVideoSubtitles, applySubtitleSelection,
  syncTripleMirrors, startTripleScreenLoop, stopTripleScreenLoop,
  fetchCurrentVideoMetadata,
  startTranscodedSeek, cleanupVideoConnection,
  onMouseMove, handleControlMouseEnter, handleControlMouseLeave,
  handleControlTouchStart, handleControlTouchEnd, resetTimer,
  syncFullscreenState, markPIPForSourceSwitch, nudgeFullscreenVideoLayer, isVideoInPIP,
  syncPlaylistContainerHeight,
  setupResizeObserver, cleanupResizeObserver,
  cleanupAllVideoResources, cleanup,
} = useVideoPlayback({
  isPaused, currentTime, streamOffset, videoRef,
  isTouchDevice, showControls, isDragging, isSwitchingMedia,
  currentVideo, currentVideoId, isGallery, isAudio, isImage,
  playbackMode, autoPlayNext, playlist, currentIndex, getVideoPlatform,
  videoContainerRef, primaryContentRef, galleryAudioRef,
  onEnded: handleEnded,
  onNextVideo: () => nextVideo(),
  onPrevVideo: () => prevVideo(),
  onMediaSwitchEnd: () => endMediaSwitch(),
  onRestoreVideoProgress: restoreVideoProgress,
  pendingRestorePIP,
});

// 将 useVideoPlayback 的回调函数赋值给 usePlaylist 的占位符
_cleanupVideoConnection = cleanupVideoConnection;
_markPIPForSourceSwitch = markPIPForSourceSwitch;
_stopAudioVisualization = stopAudioVisualization;
_initAudioAnalyzer = initAudioAnalyzer;

// ── 保留在本层的本地状态 / 桥接声明 ──
const enableBackgroundPlay = ref(localStorage.getItem("random_player_background_play") === "true");

const handleThumbnailError = (e) => {
  if (!e.target.src.includes("default_thumbnail")) {
    e.target.src = "/static/default_thumbnail.png";
  }
};
let saveProgressTimer = null;
let wasPlayingBeforeDeactivate = false;
let wasGalleryPlayingBeforeDeactivate = false;
const BG_MEDIA_KEY = "__EASY_VDL_BG_MEDIA__";
const BG_STATE_KEY = "__EASY_VDL_BG_MEDIA_STATE__";

const {
  gpuStatusData,
  gpuStatusLoading,
  gpuStatusError,
  encoderLabel,
  transcodeStatus,
  stableSideInfoLabel,
  showTranscodeInfo,
  displaySideInfoLabel,
  refreshQualitySuffix,
  startGpuStatusPolling,
  stopGpuStatusPolling,
  setupEncoderSocket,
  cleanupEncoderSocket
} = useTranscodingStatus({
  currentQuality,
  isAudio,
  isImage,
  isGallery,
  originalVideoInfo
});

watch(currentVideoId, (value) => {
  if (!value) {
    stableSideInfoLabel.value = "";
  }
});

let refreshInterval = null;

watch(enableBackgroundPlay, (val) =>
  localStorage.setItem("random_player_background_play", String(val))
);

// 开始音频可视化

// 播放控制

const playIndex = (index, { force = false } = {}) => {
  if (isSwitchingMedia.value && !force) return;
  cancelPendingSlideSwitch();
  if (force) {
    endMediaSwitch();
  }
  const targetVideo = playlist.value[index];
  if (!targetVideo) return;

  if (index === currentIndex.value) {
    if (videoRef.value && videoRef.value.paused && !isImage.value) {
      videoRef.value.play().catch(() => { isPaused.value = true; });
    }
    return;
  }

  beginMediaSwitch();

  // 先清理旧的视频连接（断开转码进程）
  cleanupVideoConnection();

  // 停止可视化（但不断开连接，因为 video 元素可能被重用）
  if (isAudio.value) {
    resetAudioAnalyzer();
  }

  const targetFilename = String(targetVideo.filename || "").toLowerCase();
  const isTargetAudio = !!targetFilename.match(/\.(mp3|flac|m4a|wav|aac|ogg|opus)$/);
  const isTargetImage = isImageFilename(targetFilename);
  if (isTargetAudio || isTargetImage) {
    isVerticalVideo.value = false;
    videoAspectRatio.value = null;
  }

  currentIndex.value = index;
  currentTime.value = 0;
  streamOffset.value = 0;
  isPaused.value = isTargetImage;

  // 重置图集状态
  galleryItems.value = [];
  galleryCurrentIndex.value = 0;
  stopAutoRotate();

  // 等待 DOM 更新和视频源变化
  nextTick(() => {
    if (videoRef.value) {
      // 确保 video 元素重新加载（如果 src 改变了）
      if (isAudio.value) {
        // 强制重新加载，确保新音频源被加载
        videoRef.value.load();
      }

      // 等待音频加载完成后再播放
      const tryPlay = async () => {
        try {
          if (
            isAudio.value &&
            audioContext &&
            audioContext.state === "suspended"
          ) {
            await audioContext.resume();
          }
          await videoRef.value.play();
        } catch (err) {
          console.warn("播放失败", err);
        }
      };

      // 如果已经加载，立即尝试播放
      if (videoRef.value.readyState >= 2) {
        tryPlay();
      } else {
        // 等待加载完成
        const handler = () => {
          tryPlay();
          videoRef.value?.removeEventListener("loadedmetadata", handler);
        };
        videoRef.value.addEventListener("loadedmetadata", handler);
        // 也监听 canplay 事件，确保可以播放
        const canPlayHandler = () => {
          tryPlay();
          videoRef.value?.removeEventListener("canplay", canPlayHandler);
        };
        videoRef.value.addEventListener("canplay", canPlayHandler);
      }
    } else if (isImage.value) {
      isPaused.value = true;
      endMediaSwitch();
    } else if (isGallery.value) {
      fetchGalleryFiles(currentVideo.value);
      endMediaSwitch();
    }
  });
};

const playByVideoId = (videoId) => {
  const index = playlist.value.findIndex((video) => String(video.id) === String(videoId));
  if (index >= 0) {
    showPlaylistDrawer.value = false;
    playIndex(index, { force: true });
  }
};


// ── 核心切换逻辑（提取自 prevVideo/nextVideo）──
const applyVideoSwitch = (direction) => {
  markPIPForSourceSwitch();
  cleanupVideoConnection();

  // 停止可视化（但不断开连接）
  if (isAudio.value) {
    resetAudioAnalyzer();
  }

  if (direction === "next") {
    if (currentIndex.value < playlist.value.length - 1) {
      currentIndex.value++;
    } else {
      currentIndex.value = 0;
    }
  } else {
    if (currentIndex.value > 0) {
      currentIndex.value--;
    } else {
      currentIndex.value = playlist.value.length - 1;
    }
  }
  isPaused.value = false;
  currentTime.value = 0;
  streamOffset.value = 0;

  // 等待新音频加载后自动播放
  nextTick(() => {
    if (videoRef.value) {
      // 移动端全屏切换时强制重载，避免浏览器全屏视频层停留在旧帧。
      if (shouldForceMediaReload()) {
        videoRef.value.load();
      }

      const tryPlay = async () => {
        if (isAudio.value) {
          ensureAudioAnalyzer();
          await new Promise((resolve) => setTimeout(resolve, 50));
        }

        try {
          await videoRef.value?.play();
        } catch (err) {
          console.warn("Autoplay failed", err);
        }
      };

      if (videoRef.value.readyState >= 2) {
        tryPlay();
      } else {
        const handler = () => {
          tryPlay();
          videoRef.value?.removeEventListener("loadedmetadata", handler);
        };
        videoRef.value.addEventListener("loadedmetadata", handler);
        const canPlayHandler = () => {
          tryPlay();
          videoRef.value?.removeEventListener("canplay", canPlayHandler);
        };
        videoRef.value.addEventListener("canplay", canPlayHandler);
      }
    }
  });
};

// ── 统一切换入口：所有用户触发的切换都经过这里 ──
const switchVideo = (direction, { animated = false } = {}) => {
  if (isSwitchingMedia.value) return;

  if (animated) {
    if (!canSwitchDirection(direction)) {
      resetSwitchPreview();
      return;
    }
    const token = ++switchSequence;
    if (slideSwitchTimer) {
      clearTimeout(slideSwitchTimer);
      slideSwitchTimer = null;
    }
    beginMediaSwitch();
    isTransitioning.value = true;
    const height = getSwitchPreviewHeight();
    dragOffset.value = direction === "next" ? -height : height;

    slideSwitchTimer = setTimeout(() => {
      slideSwitchTimer = null;
      if (token !== switchSequence) return;
      isTransitioning.value = false;
      dragOffset.value = 0;
      // 延迟 120ms 启动新视频的加载，彻底避开动画未完全归位时硬件解码重置的开销重合
      setTimeout(() => {
        if (token === switchSequence) {
          applyVideoSwitch(direction);
        }
      }, 120);
    }, 300);
  } else {
    cancelPendingSlideSwitch();
    beginMediaSwitch();
    applyVideoSwitch(direction);
  }
};

const prevVideo = () => switchVideo("prev");
const nextVideo = () => switchVideo("next");

// 路由离开守卫
onBeforeRouteLeave(() => {
  isUnmounting.value = true;
  forceUnlockPageScroll();
});

// 图集媒体加载完成后，判断是否为竖屏
// =========================================================================
// 模块化重构：引入手势系统与后台播放接管桥 Composable
// =========================================================================

// 1. 初始化后台播放桥接 Composable
const {
  getGlobalBgMedia,
  setGlobalBgMedia,
  getGlobalBgState,
  setGlobalBgState,
  stopGlobalBgMedia,
  fadeMediaVolume,
  startBackgroundBridgePlayback,
  restoreFromBackgroundBridge,
} = useBackgroundBridge({
  enableBackgroundPlay,
  autoPlayNext,
  playlist,
  currentIndex,
  playbackMode,
  playbackSpeed,
  currentSrc,
  isMuted,
  streamOffset,
  videoRef,
  isGallery,
  galleryAudioRef,
  galleryBgm,
  isPaused,
  currentTime,
  currentQuality,
  stopAutoRotate,
  startAutoRotate,
  startTranscodedSeek,
  syncTripleMirrors,
});

// 2. 初始化手势控制 Composable
const {
  seekFeedback,
  isLongPressSeeking,
  suppressNextContainerClick,
  handleTouchZone,
  handleTouchStartFromContainer,
  handleTouchStart,
  handleTouchMove,
  handleTouchEnd,
  handleTouchCancel,
  handlePointerStart,
  handlePointerMove,
  handlePointerEnd,
  startSeek,
  doSeek,
  endSeek,
  handleVideoContainerClick,
  beginMediaSwitch,
  endMediaSwitch,
  resetSwitchPreview,
} = usePlayerGestures({
  isGallery,
  videoRef,
  playbackMode,
  currentTime,
  currentQuality,
  effectiveDuration,
  showControls,
  isTouchDevice,
  isTransitioning,
  isSwiping,
  isDragging,
  isSwitchingMedia,
  dragOffset,
  containerHeight,
  videoContainerRef,
  nextVideoItem,
  prevVideoItem,
  galleryItems,
  galleryCurrentIndex,
  // 传入回调函数
  nextGalleryItem,
  prevGalleryItem,
  switchVideo,
  startTranscodedSeek,
  syncTripleMirrors,
  resetTimer,
  togglePlay,
  isImage,
  isPaused,
});










// 供模板层直接调用的悬停监听
let lastWheelSwitchAt = 0;
const WHEEL_SWITCH_DELTA_THRESHOLD = 6;
const WHEEL_SWITCH_THRESHOLD_RATIO = 0.12;
const WHEEL_SWITCH_COOLDOWN_MS = 360;

const handleWheelSwitch = (e) => {
  // 仅桌面端启用滚轮切换，移动端保持触控手势行为
  if (window.innerWidth <= 768) return;
  if (!e || isSwitchingMedia.value || isTransitioning.value || playlist.value.length <= 1) return;

  const deltaY = Number(e.deltaY || 0);
  const deltaX = Number(e.deltaX || 0);

  // 忽略横向滚动和微小抖动
  if (Math.abs(deltaY) < WHEEL_SWITCH_DELTA_THRESHOLD) return;
  if (Math.abs(deltaY) < Math.abs(deltaX)) return;

  const now = Date.now();
  if (now - lastWheelSwitchAt < WHEEL_SWITCH_COOLDOWN_MS) return;

  const height = getSwitchPreviewHeight();
  const direction = deltaY > 0 ? "prev" : "next";
  if (!canSwitchDirection(direction)) {
    setSwitchPreviewOffset(deltaY * 0.35);
    resetSwitchPreview();
    return;
  }

  dragOffset.value =
    direction === "next"
      ? -height * WHEEL_SWITCH_THRESHOLD_RATIO
      : height * WHEEL_SWITCH_THRESHOLD_RATIO;
  resetTimer();
  lastWheelSwitchAt = now;
  requestAnimationFrame(() => switchVideo(direction, { animated: true }));
};

// 键盘快捷键处理
const handleKeydown = (e) => {
  // 如果当前焦点在输入框或 select 中，不触发切集
  if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;

  switch (e.key) {
    case "ArrowLeft":
    case "ArrowUp":
      e.preventDefault();
      prevVideo();
      break;
    case "ArrowRight":
    case "ArrowDown":
      e.preventDefault();
      nextVideo();
      break;
  }
};

onMounted(async () => {
  setupResizeObserver();
  updateIsTouchDevice();
  window.addEventListener("resize", updateIsTouchDevice);

  // 防止极端情况下残留锁（例如热更新/异常中断）
  forceUnlockPageScroll();
  // 移动端进入播放页时锁定页面滚动，避免主布局 main-content 被拖动
  lockPageScrollOnMobile();
  // 重置卸载标志（组件可能被复用）
  isUnmounting.value = false;
  // 同步全屏状态（用于全屏控制栏显示）
  syncFullscreenState();
  document.addEventListener("fullscreenchange", syncFullscreenState);
  document.addEventListener("webkitfullscreenchange", syncFullscreenState);

  // 处理跳转上下文：
  // 1) 如果 URL 带 task/subscription，视为外部跳转，清空播放中心本地筛选并保存上下文
  // 2) 如果 URL 没带，尝试恢复上一次保存的跳转上下文
  const routeTaskId = route.query.task_id || null;
  const routeSubscriptionId = route.query.subscription_id || null;
  if (routeTaskId || routeSubscriptionId) {
    taskId.value = routeTaskId;
    subscriptionId.value = routeSubscriptionId;
    resetPlaylistFiltersState();
    saveJumpContext(taskId.value, subscriptionId.value);
  } else {
    const savedContext = loadJumpContext();
    if (
      savedContext &&
      (savedContext.task_id || savedContext.subscription_id)
    ) {
      taskId.value = savedContext.task_id;
      subscriptionId.value = savedContext.subscription_id;
      resetPlaylistFiltersState();
    }
  }

  // 并行加载数据以提升速度
  const fetchPromises = [];

  // 1. 加载播放记录任务
  let recordPromise = Promise.resolve(null);
  if (subscriptionId.value) {
    recordPromise = loadPlaybackRecord();
  }

  // 2. 加载视频列表任务
  // 如果是从订阅列表新点进来的（带有 reset_mode=1），强制使用 order 模式
  let initialMode = playbackMode.value;
  if (route.query.reset_mode === "1") {
    initialMode = "order";
    playbackMode.value = "order"; // 立即更新UI状态
  }
  const videosPromise = fetchVideos(initialMode);

  // 并发执行
  const [playbackRecord] = await Promise.all([recordPromise, videosPromise]);

  // 处理播放记录恢复 (此时视频列表已加载完成)
  if (playbackRecord) {
    // 如果不是重置模式，且记录中的模式与当前不一致，更新状态
    // 注意：虽然列表是按 initialMode 加载的，但我们更新界面状态以匹配记录
    if (route.query.reset_mode !== "1" && playbackRecord.playback_mode) {
      playbackMode.value = normalizePlaybackMode(playbackRecord.playback_mode);
    }
  }

  // 视频加载完成后，静默清除 reset_mode 参数，不触发路由更新
  let isResetMode = false;
  if (route.query.reset_mode === "1") {
    isResetMode = true;
    const url = new URL(window.location.href);
    url.searchParams.delete("reset_mode");
    window.history.replaceState({}, "", url);
  }

  // 恢复播放位置
  if (playlist.value.length > 0) {
    // 默认从第0个开始
    let targetIndex = 0;

    // 如果 URL 中有 task_id，优先使用它
    if (taskId.value) {
      const foundIndex = playlist.value.findIndex(
        (video) => String(video.id) === String(taskId.value)
      );
      if (foundIndex !== -1) {
        targetIndex = foundIndex;
        // 清除 task_id 参数
        const url = new URL(window.location.href);
        url.searchParams.delete("task_id");
        window.history.replaceState({}, "", url);
        taskId.value = null;
      }
    } else if (isResetMode && videoProgressMap.value) {
      // 如果是重置模式（强制顺序播放），则旧的 current_index 已经失效
      // 我们尝试在列表中寻找第一个"看了一半"的视频
      const foundIndex = playlist.value.findIndex((video) => {
        const progress = videoProgressMap.value[video.id];
        // 进度大于5秒 且 (没有总时长 或 进度小于总时长-10秒)
        return (
          progress > 5 && (!video.duration || progress < video.duration - 10)
        );
      });

      if (foundIndex !== -1) {
        targetIndex = foundIndex;
        console.log("Found resume video at index:", targetIndex);
      }
    } else if (playbackRecord && playbackRecord.current_index !== undefined) {
      // 只有在非重置模式下，才使用记录中的索引
      targetIndex = Math.min(
        playbackRecord.current_index,
        playlist.value.length - 1
      );
    }

    currentIndex.value = Math.max(0, targetIndex);
  }

  // 初始加载尝试播放
  if (playlist.value.length > 0) {
    if (isImage.value) {
      isPaused.value = true;
    } else if (isGallery.value) {
      fetchGalleryFiles(currentVideo.value);
    } else if (videoRef.value) {
      videoRef.value.play().catch(() => {
        isPaused.value = videoRef.value.paused;
      });
    }
  }

  window.addEventListener("mousemove", onMouseMove);
  window.addEventListener("keydown", handleKeydown);
  resetTimer();

  // 启动转码状态监听
  setupEncoderSocket();
  // 定时轮询兗底
  refreshInterval = setInterval(refreshQualitySuffix, 1000);
  refreshQualitySuffix();
  startGpuStatusPolling();

  // 启动播放进度保存定时器（每2秒保存一次，仅当有subscriptionId时）
  if (subscriptionId.value) {
    saveProgressTimer = setInterval(() => {
      if (videoRef.value && !videoRef.value.paused) {
        savePlaybackRecord();
      }
    }, 2000);
  }
});

// keep-alive 下：从其他页面切回来不会触发 onMounted，只会 onActivated
onActivated(async () => {
  isUnmounting.value = false;
  // 再次进入播放页时确保锁滚动生效
  forceUnlockPageScroll();
  lockPageScrollOnMobile();

  // 先尝试从后台桥接恢复，避免先拉起前台再回切导致的短时双声道重叠。
  const restoredFromBackground = await restoreFromBackgroundBridge();

  if (
    !restoredFromBackground &&
    enableBackgroundPlay.value &&
    wasPlayingBeforeDeactivate &&
    videoRef.value?.paused
  ) {
    videoRef.value.play().catch(() => {});
  }
  if (
    !restoredFromBackground &&
    enableBackgroundPlay.value &&
    wasGalleryPlayingBeforeDeactivate &&
    isGallery.value &&
    isPaused.value
  ) {
    isPaused.value = false;
    startAutoRotate();
    if (galleryAudioRef.value) {
      galleryAudioRef.value.play().catch(() => {});
    }
  }
  wasPlayingBeforeDeactivate = false;
  wasGalleryPlayingBeforeDeactivate = false;

  // 检查路由参数是否有变化，如果有变化需要重新加载
  const currentTaskId = route.query.task_id || null;
  const currentSubscriptionId = route.query.subscription_id || null;
  let effectiveTaskId = currentTaskId;
  let effectiveSubscriptionId = currentSubscriptionId;
  if (!effectiveTaskId && !effectiveSubscriptionId) {
    const savedContext = loadJumpContext();
    if (
      savedContext &&
      (savedContext.task_id || savedContext.subscription_id)
    ) {
      effectiveTaskId = savedContext.task_id;
      effectiveSubscriptionId = savedContext.subscription_id;
    }
  }

  // 如果 task_id 或 subscription_id 发生变化，清空旧列表并重新加载
  if (
    effectiveTaskId !== taskId.value ||
    effectiveSubscriptionId !== subscriptionId.value
  ) {
    // 更新状态（确保两个状态都同步）
    taskId.value = effectiveTaskId;
    subscriptionId.value = effectiveSubscriptionId;

    // 如果清理了订阅，清空名称
    if (!effectiveSubscriptionId) {
      subscriptionName.value = "";
    }

    // 清空旧列表
    playlist.value = [];
    currentIndex.value = 0;

    // 重新加载视频（只要有 task_id 或 subscription_id 就加载）
    if (effectiveTaskId || effectiveSubscriptionId) {
      await fetchVideos();

      // 如果有 task_id，定位到对应的视频
      if (effectiveTaskId && playlist.value.length > 0) {
        const targetIndex = playlist.value.findIndex(
          (video) => String(video.id) === String(effectiveTaskId)
        );
        if (targetIndex !== -1) {
          currentIndex.value = targetIndex;
          nextTick(() => {
            if (videoRef.value) {
              videoRef.value.play().catch(() => {
                isPaused.value = true;
              });
            } else if (isGallery.value) {
              fetchGalleryFiles(currentVideo.value);
            }
          });
        }
      } else if (effectiveSubscriptionId && playlist.value.length > 0) {
        // 如果只有 subscription_id，智能恢复播放位置
        let targetIndex = 0;
        if (videoProgressMap.value) {
          const foundIndex = playlist.value.findIndex((video) => {
            const progress = videoProgressMap.value[video.id];
            return (
              progress > 5 &&
              (!video.duration || progress < video.duration - 10)
            );
          });
          if (foundIndex !== -1) targetIndex = foundIndex;
        }
        currentIndex.value = targetIndex;
        nextTick(() => {
          if (videoRef.value) {
            videoRef.value.play().catch(() => {
              isPaused.value = true;
            });
          } else if (isGallery.value) {
            fetchGalleryFiles(currentVideo.value);
          }
        });
      }
    }
  }

  startGpuStatusPolling();
});

// keep-alive 下：离开播放页通常是 deactivated 而不是 unmount
onDeactivated(() => {
  wasPlayingBeforeDeactivate = !!videoRef.value && !videoRef.value.paused;
  wasGalleryPlayingBeforeDeactivate = isGallery.value && !isPaused.value;
  const keepPlayingByPIP = isVideoInPIP();
  if (enableBackgroundPlay.value && !keepPlayingByPIP) {
    startBackgroundBridgePlayback();
  } else if (!keepPlayingByPIP) {
    stopGlobalBgMedia();
    if (isGallery.value) {
      stopAutoRotate();
      if (galleryAudioRef.value) {
        galleryAudioRef.value.pause();
      }
    }
    if (videoRef.value && !videoRef.value.paused) {
      videoRef.value.pause();
    }
    isPaused.value = true;
  }
  forceUnlockPageScroll();
  stopGpuStatusPolling();
});

onBeforeUnmount(() => {
  cleanupResizeObserver();
  isUnmounting.value = true;
  cleanup();
  window.removeEventListener("resize", updateIsTouchDevice);

  // 解除移动端滚动锁定（兜底）
  forceUnlockPageScroll();

  const keepPlayingByPIP = isVideoInPIP();
  if (enableBackgroundPlay.value && !keepPlayingByPIP) {
    startBackgroundBridgePlayback();
  } else if (!keepPlayingByPIP) {
    stopGlobalBgMedia();
  }

  window.removeEventListener("mousemove", onMouseMove);
  window.removeEventListener("keydown", handleKeydown);
  document.removeEventListener("fullscreenchange", syncFullscreenState);
  document.removeEventListener("webkitfullscreenchange", syncFullscreenState);

  // 完全清理音频分析器
  cleanupAudioAnalyzer();

  // 退出前保存播放记录
  if (subscriptionId.value) {
    savePlaybackRecord();
  }

  // 清除播放进度定时器
  if (saveProgressTimer) {
    clearInterval(saveProgressTimer);
    saveProgressTimer = null;
  }

  // 清理视频资源，断开转码连接（这会导致后端转码进程自动终止）
  if (videoRef.value && !keepPlayingByPIP) {
    try {
      videoRef.value.pause();
      // 清空源地址会断开 HTTP 连接，后端转码进程会因管道断开而终止
      videoRef.value.src = "";
      videoRef.value.load();
    } catch (e) {
      console.debug("清理视频资源时出错:", e);
    }
  }

  // 退出页面时自动关闭画中画
  if (!keepPlayingByPIP && document.pictureInPictureElement) {
    document.exitPictureInPicture().catch(() => {});
  }

  cleanupEncoderSocket();
  if (refreshInterval) clearInterval(refreshInterval);
  stopGpuStatusPolling();
});
</script>

<style src="./index.css"></style>
