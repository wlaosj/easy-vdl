<template>
  <div
    class="author-area"
    @click="$emit('play-author-videos')"
    title="播放该博主的所有视频"
  >
    <img
      v-if="
        currentVideo?.author?.avatar ||
        currentVideo?.author?.avatar_url
      "
      :src="
        proxyImage(
          currentVideo?.author?.avatar ||
            currentVideo?.author?.avatar_url
        )
      "
      class="author-avatar"
      style="object-fit: cover"
      @error="handleImageError"
    />
    <div v-else class="author-avatar">
      {{ (currentVideo?.author_name || "U").charAt(0) }}
    </div>
    <div class="author-meta">
      <div class="author-name-row">
        <span class="author-name">{{
          currentVideo?.author?.nickname ||
          currentVideo?.author_name ||
          "手动任务"
        }}</span>
        <span
          class="author-play-hint"
          v-if="currentVideo?.subscription_id"
        >
          <Icon name="play" :size="9" />
          <span class="hint-text">播放全部</span>
        </span>
        <div v-if="currentVideo?.title" class="video-title-container pc-only" ref="titleContainerRef">
          <div
            class="video-title-inner"
            :class="{ 'is-scrolling': isTitleScrolling }"
            ref="titleInnerRef"
            :style="titleMarqueeStyle"
            :title="currentVideo?.title"
          >
            <span class="title-content">{{ currentVideo?.title }}</span>
            <span class="title-content" aria-hidden="true">{{ currentVideo?.title }}</span>
          </div>
        </div>
      </div>
      <span class="video-date" v-if="currentVideo?.created_at">{{
        currentVideo.created_at
      }}</span>
    </div>
    <span
      class="subscription-filter-badge"
      v-if="subscriptionId"
      @click.stop
    >
      <span class="filter-label-small">
        正在播放：{{ subscriptionName }} 的视频
      </span>
      <button
        class="filter-clear-btn-small"
        @click.stop="$emit('clear-subscription-filter')"
        title="返回全部"
      >
        <Icon name="x" :size="14" />
      </button>
    </span>
  </div>
</template>

<script setup>
import { nextTick, ref, watch, onMounted, onBeforeUnmount } from "vue";
import Icon from "@/components/common/Icon.vue";
import { subscriptionsApi } from "@/api/subscriptions";

const props = defineProps({
  currentVideo: {
    type: Object,
    default: () => ({})
  },
  subscriptionId: {
    type: [String, Number],
    default: null
  },
  subscriptionName: {
    type: String,
    default: ""
  }
});

defineEmits(['play-author-videos', 'clear-subscription-filter']);

const DEFAULT_AVATAR =
  'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"%3E%3Ccircle cx="50" cy="50" r="50" fill="%23e2e8f0"/%3E%3Ccircle cx="50" cy="40" r="18" fill="%23a0aec0"/%3E%3Cpath d="M 25 85 Q 25 60 50 60 T 75 85" fill="%23a0aec0"/%3E%3C/svg%3E';

const proxyImage = (url) => {
  if (!url) return DEFAULT_AVATAR;
  if (
    url.includes("hdslb.com") ||
    url.includes("bilibili.com") ||
    url.includes("douyinpic.com") ||
    url.includes("byteimg.com") ||
    url.includes("douyinstatic.com")
  ) {
    return subscriptionsApi.proxyImage(url);
  }
  return url;
};

const handleImageError = (e) => {
  if (e.target.src !== DEFAULT_AVATAR) {
    e.target.src = DEFAULT_AVATAR;
  }
};

const titleContainerRef = ref(null);
const titleInnerRef = ref(null);
const resizeKey = ref(0);
const isTitleScrolling = ref(false);
const titleMarqueeStyle = ref({});
const TITLE_SCROLL_GAP = 32;
const TITLE_SCROLL_SPEED = 48; // px/s
let titleResizeObserver = null;
let titleMeasureRaf = null;
let marqueeRaf = null;

const handleResize = () => {
  resizeKey.value++;
  scheduleTitleMeasure();
};

const stopTitleMarquee = (reset = true) => {
  if (marqueeRaf) {
    cancelAnimationFrame(marqueeRaf);
    marqueeRaf = null;
  }
  if (reset && titleInnerRef.value) {
    titleInnerRef.value.style.transform = '';
  }
};

const startTitleMarquee = (distance) => {
  stopTitleMarquee(false);

  let pos = 0;
  let lastTime = 0;

  const step = (time) => {
    const inner = titleInnerRef.value;
    if (!inner) {
      stopTitleMarquee(false);
      return;
    }

    if (!lastTime) lastTime = time;
    const delta = time - lastTime;
    lastTime = time;
    pos -= (delta / 1000) * TITLE_SCROLL_SPEED;

    if (Math.abs(pos) >= distance) pos = 0;
    inner.style.transform = `translateX(${pos}px)`;
    marqueeRaf = requestAnimationFrame(step);
  };

  marqueeRaf = requestAnimationFrame(step);
};

const measureTitleOverflow = async () => {
  const container = titleContainerRef.value;
  const inner = titleInnerRef.value;
  stopTitleMarquee();

  if (!container || !inner) {
    isTitleScrolling.value = false;
    titleMarqueeStyle.value = {};
    return;
  }

  const first = inner.querySelector('.title-content');
  if (!first) {
    isTitleScrolling.value = false;
    titleMarqueeStyle.value = {};
    return;
  }

  const contentW = Math.ceil(first.getBoundingClientRect().width || first.scrollWidth);
  const containerW = container.clientWidth;
  const overflowing = contentW > containerW && containerW > 0;
  const distance = contentW + TITLE_SCROLL_GAP;

  isTitleScrolling.value = overflowing;
  titleMarqueeStyle.value = {};

  if (overflowing) {
    await nextTick();
    startTitleMarquee(distance);
  }
};

const scheduleTitleMeasure = async () => {
  await nextTick();
  if (titleMeasureRaf) cancelAnimationFrame(titleMeasureRaf);
  titleMeasureRaf = requestAnimationFrame(() => {
    titleMeasureRaf = null;
    measureTitleOverflow();
  });
};

watch(
  () => props.currentVideo?.title,
  () => {
    isTitleScrolling.value = false;
    titleMarqueeStyle.value = {};
    scheduleTitleMeasure();
  },
  { immediate: true }
);

watch(resizeKey, scheduleTitleMeasure);

onMounted(() => {
  window.addEventListener('resize', handleResize);

  if (typeof ResizeObserver !== 'undefined') {
    titleResizeObserver = new ResizeObserver(scheduleTitleMeasure);
    if (titleContainerRef.value) titleResizeObserver.observe(titleContainerRef.value);
  }

  scheduleTitleMeasure();
});

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize);
  if (titleResizeObserver) {
    titleResizeObserver.disconnect();
    titleResizeObserver = null;
  }
  if (titleMeasureRaf) {
    cancelAnimationFrame(titleMeasureRaf);
    titleMeasureRaf = null;
  }
  stopTitleMarquee();
});
</script>
