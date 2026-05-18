<template>
  <div class="lyrics-display" :class="{ 'has-lyrics': lyrics.length > 0, 'theme-light': isLightTheme }">
    <div v-if="loading" class="lyrics-loading">
      <div class="spinner-sm"></div>
      <span>加载歌词中...</span>
    </div>
    
    <div v-else-if="error" class="lyrics-error">
      <Icon name="alert-circle" :size="20" />
      <span>{{ error }}</span>
    </div>
    
    <div v-else-if="lyrics.length === 0" class="lyrics-empty">
      <Icon name="music" :size="32" />
      <p>暂无歌词</p>
    </div>
    
    <div v-else class="lyrics-content">
      <div
        v-for="line in visibleLyrics"
        :key="line.originalIndex"
        class="lyric-line"
        :class="{
          active: line.originalIndex === currentLineIndex,
          passed: line.originalIndex < currentLineIndex,
          near: line.distance <= 1 && line.originalIndex !== currentLineIndex,
          far: line.distance >= 3
        }"
        :data-index="line.originalIndex"
      >
        {{ line.text }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import Icon from '@/components/common/Icon.vue'
import { useSystemStore } from '@/stores/system'

const systemStore = useSystemStore()

const props = defineProps({
  lyricsUrl: {
    type: String,
    default: ''
  },
  currentTime: {
    type: Number,
    default: 0
  }
})

const lyrics = ref([])
const loading = ref(false)
const error = ref(null)
const currentLineIndex = ref(-1)
const isLightTheme = computed(() => systemStore.theme !== 'dark')

// 解析LRC歌词格式
const parseLRC = (lrcText) => {
  const lines = lrcText.split('\n')
  const parsedLyrics = []
  
  const timeRegex = /\[(\d{2}):(\d{2})\.(\d{2,3})\]/g
  
  for (const line of lines) {
    const matches = [...line.matchAll(timeRegex)]
    if (matches.length > 0) {
      const text = line.replace(timeRegex, '').trim()
      if (text) {
        for (const match of matches) {
          const minutes = parseInt(match[1])
          const seconds = parseInt(match[2])
          const milliseconds = parseInt(match[3].padEnd(3, '0'))
          const time = minutes * 60 + seconds + milliseconds / 1000
          
          parsedLyrics.push({ time, text })
        }
      }
    }
  }
  
  // 按时间排序
  return parsedLyrics.sort((a, b) => a.time - b.time)
}

// 加载歌词
const loadLyrics = async (url) => {
  if (!url) {
    lyrics.value = []
    error.value = null
    return
  }
  
  loading.value = true
  error.value = null
  
  try {
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error('歌词文件不存在')
    }
    
    const text = await response.text()
    lyrics.value = parseLRC(text)
    
    if (lyrics.value.length === 0) {
      error.value = '歌词格式错误'
    }
  } catch (e) {
    console.warn('加载歌词失败:', e)
    error.value = null // 不显示错误,只是没有歌词
    lyrics.value = []
  } finally {
    loading.value = false
  }
}

// 监听歌词URL变化
watch(() => props.lyricsUrl, (newUrl) => {
  loadLyrics(newUrl)
}, { immediate: true })

// 监听播放时间,更新当前歌词行
watch(() => props.currentTime, (time) => {
  if (lyrics.value.length === 0) return
  
  // 找到当前应该高亮的歌词行
  let index = -1
  for (let i = 0; i < lyrics.value.length; i++) {
    if (lyrics.value[i].time <= time) {
      index = i
    } else {
      break
    }
  }
  
  if (index !== currentLineIndex.value) {
    currentLineIndex.value = index
  }
})

// 多行歌词窗口：当前行上下各展示若干行，避免只看到单行。
const visibleLyrics = computed(() => {
  const items = lyrics.value || []
  const total = items.length
  if (total === 0) return []

  const windowSize = 9
  const half = Math.floor(windowSize / 2)
  const center = currentLineIndex.value >= 0 ? currentLineIndex.value : 0

  let start = Math.max(0, center - half)
  let end = Math.min(total, start + windowSize)
  if (end - start < windowSize) {
    start = Math.max(0, end - windowSize)
  }

  return items.slice(start, end).map((line, idx) => ({
    ...line,
    originalIndex: start + idx,
    distance: Math.abs(start + idx - center)
  }))
})
</script>

<style scoped>
.lyrics-display {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, 
    rgba(99, 102, 241, 0.12) 0%, 
    rgba(168, 85, 247, 0.1) 50%,
    rgba(236, 72, 153, 0.12) 100%
  );
  backdrop-filter: blur(24px);
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.15);
  box-shadow: 
    0 12px 40px rgba(0, 0, 0, 0.15),
    inset 0 1px 0 rgba(255, 255, 255, 0.15),
    inset 0 -1px 0 rgba(0, 0, 0, 0.1);
}

.lyrics-loading,
.lyrics-error,
.lyrics-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: rgba(255, 255, 255, 0.6);
  padding: 40px 32px;
}

.lyrics-loading {
  color: rgba(255, 255, 255, 0.5);
}

.lyrics-loading .spinner-sm {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.1);
  border-top-color: rgba(99, 102, 241, 0.8);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.lyrics-error {
  color: rgba(239, 68, 68, 0.9);
}

.lyrics-empty {
  color: rgba(255, 255, 255, 0.6);
}

.lyrics-empty p {
  font-size: 1rem;
  font-weight: 500;
  letter-spacing: 0.5px;
  margin: 0;
}

.lyrics-content {
  flex: 1;
  overflow: hidden;
  padding: 24px 24px;
  text-align: center;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  position: relative;
}

.lyric-line {
  padding: 6px 12px;
  margin: 0;
  font-size: 1rem;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.74);
  transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: default;
  user-select: none;
  font-weight: 500;
  letter-spacing: 0.4px;
  min-height: 1.45em;
  white-space: normal;
  overflow-wrap: anywhere;
}

.lyric-line.active {
  font-size: 1.28rem;
  font-weight: 700;
  color: #fff;
  transform: scale(1.02);
  text-shadow: 
    0 0 20px rgba(255, 255, 255, 0.5),
    0 0 40px rgba(168, 85, 247, 0.4);
  letter-spacing: 0.8px;
  background: linear-gradient(135deg, #818cf8, #c084fc, #f472b6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: lyricPulse 0.5s cubic-bezier(0.4, 0, 0.2, 1);
  filter: drop-shadow(0 0 8px rgba(168, 85, 247, 0.4));
  margin: 2px 0;
  padding: 8px 12px;
}

@keyframes lyricPulse {
  0% {
    transform: scale(1);
    opacity: 0.8;
  }
  50% {
    transform: scale(1.1);
    opacity: 1;
  }
  100% {
    transform: scale(1.05);
    opacity: 1;
  }
}

.lyric-line.passed {
  color: rgba(255, 255, 255, 0.82);
  font-weight: 500;
  font-size: 0.98rem;
  opacity: 0.8;
}

.lyric-line.near {
  opacity: 0.8;
}

.lyric-line.far {
  opacity: 0.5;
}

.lyric-line:not(.active):not(.passed) {
  opacity: 0.62;
  filter: none;
  font-size: 0.98rem;
}

/* 响应式 */
@media (max-width: 768px) {
  .lyrics-display {
    border-radius: 16px;
  }

  .lyrics-content {
    padding: 20px 14px;
  }
  
  .lyric-line {
    font-size: 0.9rem;
    padding: 5px 8px;
    line-height: 1.4;
  }
  
  .lyric-line.active {
    font-size: 1.12rem;
    padding: 6px 10px;
    margin: 2px 0;
  }

  .lyric-line.passed {
    font-size: 0.9rem;
  }

  .lyric-line:not(.active):not(.passed) {
    font-size: 0.88rem;
  }

  .lyrics-loading,
  .lyrics-error,
  .lyrics-empty {
    padding: 32px 24px;
    gap: 12px;
  }
}

.lyrics-display.theme-light {
  background: linear-gradient(135deg,
    rgba(99, 102, 241, 0.18) 0%,
    rgba(168, 85, 247, 0.14) 50%,
    rgba(236, 72, 153, 0.16) 100%
  );
}

.lyrics-display.theme-light .lyrics-loading,
.lyrics-display.theme-light .lyrics-error,
.lyrics-display.theme-light .lyrics-empty {
  color: rgba(55, 65, 81, 0.72);
}

.lyrics-display.theme-light .lyrics-loading {
  color: rgba(55, 65, 81, 0.64);
}

.lyrics-display.theme-light .lyrics-loading .spinner-sm {
  border-color: rgba(99, 102, 241, 0.16);
  border-top-color: rgba(99, 102, 241, 0.82);
}

.lyrics-display.theme-light .lyrics-error {
  color: rgba(239, 68, 68, 0.9);
}

.lyrics-display.theme-light .lyrics-empty {
  color: rgba(55, 65, 81, 0.62);
}

.lyrics-display.theme-light .lyric-line {
  color: rgba(31, 41, 55, 0.84);
}

.lyrics-display.theme-light .lyric-line.active {
  color: #312e81;
  text-shadow:
    0 1px 0 rgba(255, 255, 255, 0.7),
    0 6px 18px rgba(99, 102, 241, 0.18);
  background: none;
  -webkit-background-clip: initial;
  -webkit-text-fill-color: currentColor;
  background-clip: initial;
  filter: drop-shadow(0 2px 6px rgba(49, 46, 129, 0.14));
}

.lyrics-display.theme-light .lyric-line.passed {
  color: rgba(17, 24, 39, 0.84);
  opacity: 0.9;
}

.lyrics-display.theme-light .lyric-line.near {
  opacity: 0.82;
}

.lyrics-display.theme-light .lyric-line.far {
  opacity: 0.56;
}

.lyrics-display.theme-light .lyric-line:not(.active):not(.passed) {
  opacity: 0.76;
}
</style>
