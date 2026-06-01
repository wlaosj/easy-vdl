<template>
  <!-- 移动端版本 -->
  <div v-if="isMobile" class="playlist-mobile-wrapper">
    <!-- 当前筛选状态条 -->
    <div class="filter-status-bar mobile-only" v-if="subscriptionId">
      <span class="filter-label">正在播放：{{ subscriptionName }} 的视频</span>
      <button
        class="filter-clear-btn"
        @click="$emit('clear-subscription-filter')"
        title="返回全部"
      >
        <Icon name="x" :size="14" />
      </button>
    </div>
    <div class="playlist-filter-panel mobile-only">
      <div class="playlist-filter-row">
        <select
          :value="playlistFilterPlatform"
          class="filter-select"
          @change="$emit('update:playlistFilterPlatform', $event.target.value); $emit('apply-filters')"
        >
          <option
            v-for="platform in platformFilterOptions"
            :key="platform.value"
            :value="platform.value"
          >
            {{ platform.label }}
          </option>
        </select>
        <select
          :value="playlistFilterScope"
          class="filter-select"
          @change="$emit('update:playlistFilterScope', $event.target.value); $emit('apply-filters')"
        >
          <option value="all">全部任务</option>
          <option value="manual">仅手动</option>
          <option value="subscription">仅订阅</option>
        </select>
        <select
          :value="playlistFilterAuthor"
          class="filter-select"
          @change="$emit('update:playlistFilterAuthor', $event.target.value); $emit('apply-filters')"
        >
          <option value="all">全部博主</option>
          <option
            v-for="author in playlistAuthorOptions"
            :key="author"
            :value="author"
          >
            {{ author }}
          </option>
        </select>
      </div>
      <div class="playlist-filter-row">
        <input
          :value="playlistFilterKeyword"
          class="filter-input"
          type="text"
          placeholder="筛选标题/作者"
          @input="$emit('update:playlistFilterKeyword', $event.target.value)"
        />
        <button class="filter-action-btn" @click="$emit('reset-filters')">
          重置
        </button>
      </div>
    </div>
    <div class="drawer-content playlist-drawer-list">
      <div
        v-for="(video, index) in filteredPlaylist"
        :key="video.id"
        class="playlist-item"
        :class="{ active: currentVideoId === video.id }"
        @click="$emit('play', video.id)"
      >
        <div class="item-index">{{ index + 1 }}</div>
        <div class="item-thumb">
          <img
            :src="getThumbnailUrl(video)"
            @error="handleThumbnailError"
            loading="lazy"
          />
          <div class="duration" v-if="video.duration">
            {{ formatTime(video.duration) }}
          </div>
          <div class="playing-bars" v-if="currentVideoId === video.id">
            <div class="bar"></div>
            <div class="bar"></div>
            <div class="bar"></div>
          </div>
        </div>
        <div class="item-detail">
          <div class="title" :title="video.title">{{ video.title }}</div>
          <div class="meta">
            <span class="platform-tag" v-if="video.platform">{{ getPlatformName(video.platform) }}</span>
            <span class="author-name">{{ video?.author?.nickname || video?.author_name || "未知作者" }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 桌面端版本 -->
  <div
    v-else
    class="playlist-container"
    :style="playlistContainerHeightStyle"
  >
    <div class="playlist-header">
      <h3>
        播放列表
        <span class="count">({{ filteredPlaylist.length }}/{{ playlist.length }})</span>
      </h3>
      <button class="icon-btn" @click="$emit('refresh')" title="刷新列表">
        <Icon name="refresh" :size="18" />
      </button>
    </div>
    <div class="playlist-filter-panel">
      <div class="playlist-filter-row">
        <select
          :value="playlistFilterPlatform"
          class="filter-select"
          @change="$emit('update:playlistFilterPlatform', $event.target.value); $emit('apply-filters')"
        >
          <option
            v-for="platform in platformFilterOptions"
            :key="platform.value"
            :value="platform.value"
          >
            {{ platform.label }}
          </option>
        </select>
        <select
          :value="playlistFilterScope"
          class="filter-select"
          @change="$emit('update:playlistFilterScope', $event.target.value); $emit('apply-filters')"
        >
          <option value="all">全部任务</option>
          <option value="manual">仅手动</option>
          <option value="subscription">仅订阅</option>
        </select>
        <select
          :value="playlistFilterAuthor"
          class="filter-select"
          @change="$emit('update:playlistFilterAuthor', $event.target.value); $emit('apply-filters')"
        >
          <option value="all">全部博主</option>
          <option
            v-for="author in playlistAuthorOptions"
            :key="author"
            :value="author"
          >
            {{ author }}
          </option>
        </select>
      </div>
      <div class="playlist-filter-row secondary-filter-row">
        <div class="search-input-wrapper">
          <input
            :value="playlistFilterKeyword"
            class="filter-input"
            type="text"
            placeholder="筛选标题/作者"
            @input="$emit('update:playlistFilterKeyword', $event.target.value)"
          />
        </div>
        <button class="filter-action-btn" @click="$emit('reset-filters')">
          重置
        </button>
      </div>
    </div>
    <!-- 当前筛选状态条 -->
    <div class="filter-status-bar" v-if="subscriptionId">
      <span class="filter-label">正在播放：{{ subscriptionName }} 的视频</span>
      <button
        class="filter-clear-btn"
        @click="$emit('clear-subscription-filter')"
        title="返回全部"
      >
        <Icon name="x" :size="14" />
      </button>
    </div>
    <div class="playlist-items custom-scrollbar">
      <div
        v-for="(video, index) in filteredPlaylist"
        :key="video.id"
        class="playlist-item"
        :class="{ active: currentVideoId === video.id }"
        @click="$emit('play', video.id)"
      >
        <div class="item-thumbnail">
          <img
            :src="getThumbnailUrl(video)"
            @error="handleThumbnailError"
            loading="lazy"
          />
          <div class="playing-indicator" v-if="index === currentIndex">
            <div class="bar"></div>
            <div class="bar"></div>
            <div class="bar"></div>
          </div>
          <span class="duration" v-if="video.duration">
            {{ formatTime(video.duration) }}
          </span>
        </div>
        <div class="item-detail">
          <div class="title" :title="video.title">{{ video.title }}</div>
          <div class="meta">
            {{ video?.author?.nickname || video?.author_name || "未知作者" }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import Icon from "@/components/common/Icon.vue";

const props = defineProps({
  isMobile: {
    type: Boolean,
    default: false
  },
  playlist: {
    type: Array,
    required: true
  },
  filteredPlaylist: {
    type: Array,
    required: true
  },
  currentVideoId: {
    type: [String, Number],
    default: ''
  },
  currentIndex: {
    type: Number,
    default: 0
  },
  playlistFilterPlatform: {
    type: String,
    required: true
  },
  playlistFilterScope: {
    type: String,
    required: true
  },
  playlistFilterAuthor: {
    type: String,
    required: true
  },
  playlistFilterKeyword: {
    type: String,
    required: true
  },
  playlistAuthorOptions: {
    type: Array,
    required: true
  },
  subscriptionId: {
    type: [String, Number],
    default: null
  },
  subscriptionName: {
    type: String,
    default: ''
  },
  playlistContainerHeightStyle: {
    type: Object,
    default: () => ({})
  },
  getThumbnailUrl: {
    type: Function,
    required: true
  },
  formatTime: {
    type: Function,
    required: true
  }
});

defineEmits([
  'update:playlistFilterPlatform',
  'update:playlistFilterScope',
  'update:playlistFilterAuthor',
  'update:playlistFilterKeyword',
  'apply-filters',
  'reset-filters',
  'clear-subscription-filter',
  'play',
  'refresh'
]);

const handleThumbnailError = (e) => {
  if (!e.target.src.includes("default_thumbnail")) {
    e.target.src = "/static/default_thumbnail.png";
  }
};

const platformFilterOptions = [
  { value: 'all', label: '全部平台' },
  { value: 'douyin', label: '抖音' },
  { value: 'bilibili', label: 'B站' },
  { value: 'youtube', label: 'YouTube' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'tiktok', label: 'TikTok' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'x', label: 'X' },
  { value: 'netease', label: '网易云' },
  { value: 'others', label: '其他' }
];

const getPlatformName = (platform) => {
  const map = {
    douyin: '抖音',
    douyin_collection: '抖音',
    bilibili: 'B站',
    youtube: 'YouTube',
    xiaohongshu: '小红书',
    tiktok: 'TikTok',
    instagram: 'Instagram',
    x: 'X',
    netease: '网易云',
    others: '其他'
  };
  return map[platform] || platform;
};
</script>

<style scoped>
/* 侧边播放列表 */
.playlist-container {
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  box-sizing: border-box;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.playlist-header {
  padding: 16px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.playlist-header h3 {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0;
}

.playlist-header .count {
  font-size: 0.9rem;
  color: var(--color-text-muted);
  font-weight: normal;
}

.playlist-filter-panel {
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-primary);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.playlist-filter-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-select {
  flex: 1;
  min-width: 80px;
  height: 34px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  padding: 0 10px;
  font-size: 0.84rem;
}

.filter-input {
  flex: 1;
  min-width: 120px;
  height: 34px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  padding: 0 10px;
  font-size: 0.84rem;
}

.filter-select:focus,
.filter-input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.filter-action-btn {
  flex-shrink: 0;
  min-width: 64px;
  height: 34px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  font-size: 0.82rem;
  cursor: pointer;
  white-space: nowrap;
}

.filter-action-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* 筛选状态条 */
.filter-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: linear-gradient(
    135deg,
    rgba(237, 137, 54, 0.1) 0%,
    rgba(221, 107, 32, 0.1) 100%
  );
  border-bottom: 1px solid rgba(237, 137, 54, 0.2);
}

.filter-label {
  font-size: 0.85rem;
  color: #dd6b20;
  font-weight: 500;
}

.filter-clear-btn {
  background: transparent;
  border: none;
  color: #dd6b20;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
}

.filter-clear-btn:hover {
  background: rgba(221, 107, 32, 0.15);
}

.playlist-items {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
}

.playlist-item {
  display: flex;
  gap: 12px;
  padding: 8px;
  border-radius: 12px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: all 0.2s;
  content-visibility: auto;
  contain-intrinsic-size: 80px;
}

.playlist-item:hover {
  background: var(--color-bg-tertiary);
}
.playlist-item.active {
  background: var(--color-primary-light);
}

.item-thumbnail {
  position: relative;
  width: 140px;
  aspect-ratio: 16 / 9;
  border-radius: 8px;
  overflow: hidden;
  background: #000;
  flex-shrink: 0;
}

.item-thumbnail img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.playing-indicator {
  position: absolute;
  bottom: 8px;
  left: 8px;
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 12px;
}

.playing-indicator .bar {
  width: 3px;
  background: var(--color-primary);
  animation: bar-dance 1s infinite alternate;
}

.playing-indicator .bar:nth-child(2) {
  animation-delay: 0.2s;
  height: 8px;
}
.playing-indicator .bar:nth-child(3) {
  animation-delay: 0.4s;
  height: 6px;
}

@keyframes bar-dance {
  from {
    height: 4px;
  }
  to {
    height: 12px;
  }
}

.duration {
  position: absolute;
  bottom: 4px;
  right: 4px;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  font-size: 0.7rem;
  padding: 1px 4px;
  border-radius: 4px;
}

.item-detail {
  flex: 1;
  min-width: 0;
}
.item-detail .title {
  font-size: 0.9rem;
  font-weight: 600;
  line-height: 1.3;
  color: var(--color-text-primary);
  display: -webkit-box;
  line-clamp: 2;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 4px;
}

.item-detail .meta {
  font-size: 0.75rem;
  color: var(--color-text-muted);
}

/* 自定义滚动条 */
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 10px;
}

/* 移动端版本 */
.playlist-mobile-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.playlist-mobile-wrapper .playlist-filter-panel {
  padding: 10px 16px;
  flex-shrink: 0;
}

.playlist-drawer-list {
  padding: 0 !important;
  flex: 1 !important;
  overflow-y: auto !important;
  min-height: 0 !important;
  -webkit-overflow-scrolling: touch; /* 增强 iOS 上的滑动流畅度 */
}

.playlist-drawer-list .playlist-item {
  padding: 10px 16px;
  border-bottom: 1px solid var(--color-border-subtle);
  border-radius: 0;
  margin: 0;
  cursor: pointer;
  gap: 12px;
}
.playlist-drawer-list .playlist-item.active {
  background: var(--color-primary-light);
}
.playlist-drawer-list .item-index {
  width: 20px;
  font-size: 0.8rem;
  color: var(--color-text-muted);
  text-align: center;
}
.playlist-drawer-list .item-thumb {
  width: 100px;
  height: 56px;
  border-radius: 6px;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
  background: #000;
}
.playlist-drawer-list .item-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.playlist-drawer-list .duration {
  font-size: 0.65rem;
  padding: 1px 3px;
  border-radius: 3px;
}
.playlist-drawer-list .item-detail .title {
  font-size: 0.85rem;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  margin-bottom: 2px;
}
.playlist-drawer-list .item-detail .meta {
  font-size: 0.7rem;
}
.playlist-drawer-list .playing-bars {
  position: absolute;
  bottom: 6px;
  left: 6px;
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 10px;
}
.playlist-drawer-list .playing-bars .bar {
  width: 2px;
  background: var(--color-primary);
  animation: bar-dance 1s infinite alternate;
}
.playlist-drawer-list .playing-bars .bar:nth-child(2) {
  animation-delay: 0.2s;
  height: 6px;
}
.playlist-drawer-list .playing-bars .bar:nth-child(3) {
  animation-delay: 0.4s;
  height: 5px;
}
</style>
