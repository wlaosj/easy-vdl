<template>
  <div class="audio-visualizer">
    <div class="audio-main-content">
      <!-- 左侧：封面与 Canvas 频谱 -->
      <div class="audio-left-section">
        <div class="audio-cover-wrapper">
          <img
            :src="currentCoverUrl"
            alt="封面"
            class="audio-cover"
            @error="handleThumbnailError"
          />
        </div>
        <div class="audio-bars">
          <canvas
            ref="canvasRef"
            width="300"
            height="80"
            class="audio-canvas"
          ></canvas>
        </div>
      </div>

      <!-- 右侧：歌词显示 -->
      <div class="audio-right-section">
        <div class="lyrics-panel">
          <LyricsDisplay
            :lyricsUrl="currentLyricsUrl"
            :currentTime="currentTime"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount, watch } from 'vue';
import LyricsDisplay from "@/components/business/LyricsDisplay.vue";

const props = defineProps({
  currentCoverUrl: {
    type: String,
    default: ''
  },
  currentLyricsUrl: {
    type: String,
    default: ''
  },
  currentTime: {
    type: Number,
    default: 0
  },
  analyser: {
    type: Object,
    default: null
  }
});

const canvasRef = ref(null);
let animationFrameId = null;
let dataArray = null;
let bufferLength = 0;

const handleThumbnailError = (e) => {
  if (!e.target.src.includes("default_thumbnail")) {
    e.target.src = "/static/default_thumbnail.png";
  }
};

const draw = () => {
  if (!props.analyser || !canvasRef.value) {
    animationFrameId = null;
    return;
  }

  const canvas = canvasRef.value;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    animationFrameId = requestAnimationFrame(draw);
    return;
  }

  // 获取频率数据
  props.analyser.getByteFrequencyData(dataArray);

  const dpr = window.devicePixelRatio || 1;
  // 保持高 DPI 设备上的清晰度，动态设置宽高
  if (canvas.width !== 300 * dpr || canvas.height !== 80 * dpr) {
    canvas.width = 300 * dpr;
    canvas.height = 80 * dpr;
    ctx.scale(dpr, dpr);
  }

  const width = 300;
  const height = 80;
  const barCount = 16;
  const gap = 4;
  const barWidth = 5;

  const totalBarsWidth = barCount * barWidth + (barCount - 1) * gap;
  const startX = (width - totalBarsWidth) / 2;

  ctx.clearRect(0, 0, width, height);

  // 将 FFT 数据点（通常为 32 或更多）映射到 16 个 bar
  const step = Math.floor(bufferLength / barCount) || 1;

  for (let i = 0; i < barCount; i++) {
    let sum = 0;
    for (let j = 0; j < step; j++) {
      sum += dataArray[i * step + j] || 0;
    }
    const average = sum / step;
    // 将 0-255 的值转换为 10-100% 的高度百分比，保证最小 10% 可见
    const rawHeight = Math.max(10, Math.min(100, (average / 255) * 90 + 10));
    const pixelHeight = (rawHeight / 100) * height;

    const x = startX + i * (barWidth + gap);
    const y = height - pixelHeight;

    // 设置圆角柱状图渐变色
    const grad = ctx.createLinearGradient(x, y, x, height);
    if (i % 2 === 0) {
      // 偶数柱子（橘红色渐变）
      grad.addColorStop(0, '#f97316');
      grad.addColorStop(1, '#ef4444');
    } else {
      // 奇数柱子（蓝色渐变）
      grad.addColorStop(0, '#60a5fa');
      grad.addColorStop(1, '#3b82f6');
    }

    ctx.fillStyle = grad;
    ctx.globalAlpha = 0.8;

    // 绘制圆角矩形，提供极致视觉动感
    ctx.beginPath();
    if (typeof ctx.roundRect === 'function') {
      ctx.roundRect(x, y, barWidth, pixelHeight, 999);
    } else {
      ctx.rect(x, y, barWidth, pixelHeight);
    }
    ctx.fill();
  }

  animationFrameId = requestAnimationFrame(draw);
};

const startVisualization = () => {
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }

  if (props.analyser) {
    bufferLength = props.analyser.frequencyBinCount;
    dataArray = new Uint8Array(bufferLength);
    draw();
  }
};

const stopVisualization = () => {
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }
};

watch(() => props.analyser, (newAnalyser) => {
  if (newAnalyser) {
    startVisualization();
  } else {
    stopVisualization();
  }
}, { immediate: true });

onBeforeUnmount(() => {
  stopVisualization();
});
</script>

<style scoped>
.audio-visualizer {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-secondary);
}

.audio-main-content {
  display: flex;
  width: 90%;
  max-width: 900px;
  height: 80%;
  align-items: center;
  gap: var(--spacing-xl);
}

.audio-left-section {
  flex: 0 0 300px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-lg);
}

.audio-cover-wrapper {
  width: 220px;
  height: 220px;
  border-radius: var(--border-radius-lg);
  overflow: hidden;
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.4);
  background: var(--color-bg-card);
  transition: transform 0.3s ease;
}

.audio-cover-wrapper:hover {
  transform: scale(1.03);
}

.audio-cover {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.audio-bars {
  width: 100%;
  max-width: 300px;
  height: 80px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.audio-canvas {
  width: 100%;
  height: 100%;
  display: block;
}

.audio-right-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
}

.lyrics-panel {
  flex: 1;
  height: 100%;
  min-height: 0;
}

@media (max-width: 768px) {
  .audio-main-content {
    flex-direction: column;
    justify-content: flex-start;
    gap: var(--spacing-lg);
    overflow-y: auto;
    padding-top: var(--spacing-md);
  }

  .audio-left-section {
    flex: 0 0 auto;
    gap: var(--spacing-sm);
  }

  .audio-cover-wrapper {
    width: 140px;
    height: 140px;
  }

  .audio-bars {
    height: 50px;
  }
}
</style>
