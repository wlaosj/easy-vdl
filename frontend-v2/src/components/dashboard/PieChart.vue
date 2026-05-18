<template>
  <div class="pie-chart-container">
    <svg viewBox="0 0 100 100" class="pie-chart">
      <!-- 渐变定义 -->
      <defs>
        <linearGradient
          v-for="grad in gradients"
          :key="grad.id"
          :id="`grad-${grad.id}`"
          x1="0%"
          y1="0%"
          x2="100%"
          y2="100%"
        >
          <stop offset="0%" :stop-color="grad.startColor" />
          <stop offset="100%" :stop-color="grad.endColor" />
        </linearGradient>
      </defs>

      <!-- 空状态 -->
      <circle
        v-if="segments.length === 0"
        cx="50"
        cy="50"
        r="40"
        fill="none"
        stroke="#eee"
        stroke-width="20"
        class="pie-empty-ring"
      />

      <circle
        v-for="(segment, idx) in segments"
        :key="segment.platform"
        cx="50"
        cy="50"
        r="40"
        fill="none"
        :stroke="`url(#grad-${segment.colorId})`"
        stroke-width="20"
        :stroke-dasharray="`${segment.dashArray} ${circumference - segment.dashArray}`"
        :stroke-dashoffset="segment.dashOffset"
        :class="['pie-segment', `pie-segment-${segment.platform}`]"
        :style="{ '--segment-delay': `${idx * 70}ms` }"
        @click="handleSegmentClick(segment)"
        @mouseenter="hoveredSegment = segment"
        @mouseleave="hoveredSegment = null"
      >
        <title>{{ segment.name }}: {{ segment.count }} ({{ segment.percent }}%)</title>
      </circle>
    </svg>
    <div class="pie-center-text">
      <template v-if="hoveredSegment">
        <div class="pie-hover-name">{{ hoveredSegment.name }}</div>
        <div class="pie-hover-data">{{ hoveredSegment.percent }}%</div>
      </template>
      <template v-else>
        <div class="pie-total">{{ total }}</div>
        <div class="pie-label">{{ label }}</div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  segments: {
    type: Array,
    required: true,
    default: () => []
  },
  total: {
    type: Number,
    default: 0
  },
  label: {
    type: String,
    default: '总计'
  },
  gradients: {
    type: Array,
    required: true,
    default: () => []
  },
  circumference: {
    type: Number,
    default: 2 * Math.PI * 40 // 2 * PI * 40
  }
})

const emit = defineEmits(['segment-click'])

const hoveredSegment = ref(null)

function handleSegmentClick(segment) {
  emit('segment-click', segment)
}
</script>

<style scoped>
.pie-chart-container {
  --pie-empty-ring-stroke: rgba(100, 116, 139, 0.45);
  --pie-center-bg: rgba(255, 255, 255, 0.62);
  --pie-center-border: rgba(255, 255, 255, 0.22);
  --pie-center-shadow: 0 8px 20px rgba(0, 0, 0, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.6);
  --pie-total-color: var(--color-text-primary);
  --pie-label-color: var(--color-text-secondary);
  --pie-hover-name-color: var(--color-text-primary);
  --pie-hover-data-color: var(--color-text-primary);
  position: relative;
  width: 100%;
  max-width: 164px;
  max-height: 164px;
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto;
  overflow: visible;
}

.pie-chart {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
  overflow: visible;
  filter: drop-shadow(0 8px 14px rgba(0, 0, 0, 0.12));
}

.pie-empty-ring {
  stroke: var(--pie-empty-ring-stroke);
  opacity: 0.3;
}

.pie-segment-douyin,
.pie-segment-tiktok,
.pie-segment-netease,
.pie-segment-youtube,
.pie-segment-bilibili,
.pie-segment-redbook,
.pie-segment-x,
.pie-segment-instagram,
.pie-segment-huya,
.pie-segment-douyu,
.pie-segment-migu,
.pie-segment-other {
  cursor: pointer;
  transition: filter 0.22s ease;
  stroke-linecap: butt;
  opacity: 0;
  animation: segment-in 0.55s ease forwards;
  animation-delay: var(--segment-delay, 0ms);
}

.pie-segment-douyin:hover,
.pie-segment-tiktok:hover,
.pie-segment-netease:hover,
.pie-segment-youtube:hover,
.pie-segment-bilibili:hover,
.pie-segment-redbook:hover,
.pie-segment-x:hover,
.pie-segment-instagram:hover,
.pie-segment-huya:hover,
.pie-segment-douyu:hover,
.pie-segment-migu:hover,
.pie-segment-other:hover {
  filter: brightness(1.08);
}

.pie-center-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  min-width: 76px;
  min-height: 76px;
  padding: 10px;
  border-radius: 999px;
  border: 1px solid var(--pie-center-border);
  background: var(--pie-center-bg);
  box-shadow: var(--pie-center-shadow);
  backdrop-filter: blur(3px);
  text-align: center;
  pointer-events: none;
  z-index: 10;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  animation: center-fade 0.3s ease;
}

.pie-total {
  font-size: 22px;
  font-weight: bold;
  color: var(--pie-total-color);
  line-height: 1.2;
}

.pie-label {
  font-size: 12px;
  color: var(--pie-label-color);
  margin-top: 4px;
}

.pie-hover-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--pie-hover-name-color);
  line-height: 1.2;
}

.pie-hover-data {
  font-size: 18px;
  font-weight: bold;
  color: var(--pie-hover-data-color);
  margin-top: 4px;
}


@keyframes segment-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes center-fade {
  from {
    opacity: 0.5;
    transform: translate(-50%, -50%) scale(0.97);
  }
  to {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1);
  }
}
</style>

<style>
:root[data-theme="dark"] .pie-chart-container {
  --pie-empty-ring-stroke: rgba(148, 163, 184, 0.45);
  --pie-center-bg: rgba(22, 27, 34, 0.92);
  --pie-center-border: rgba(148, 163, 184, 0.35);
  --pie-center-shadow: 0 12px 28px rgba(0, 0, 0, 0.48), inset 0 1px 0 rgba(255, 255, 255, 0.06);
  --pie-total-color: #f8fafc;
  --pie-label-color: rgba(226, 232, 240, 0.78);
  --pie-hover-name-color: #f8fafc;
  --pie-hover-data-color: #ffffff;
}

:root[data-theme="dark"] .pie-chart-container .pie-center-text {
  background: rgba(22, 27, 34, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.35) !important;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.48), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

:root[data-theme="dark"] .pie-chart-container .pie-total,
:root[data-theme="dark"] .pie-chart-container .pie-hover-name,
:root[data-theme="dark"] .pie-chart-container .pie-hover-data {
  color: #f8fafc !important;
}

:root[data-theme="dark"] .pie-chart-container .pie-label {
  color: rgba(226, 232, 240, 0.78) !important;
}
</style>
