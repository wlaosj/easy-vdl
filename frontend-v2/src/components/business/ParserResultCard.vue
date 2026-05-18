<template>
  <div class="result-card animate-slideUp">
    <!-- 视频基础信息头部 -->
    <div class="video-header">
      <div class="thumbnail-wrapper">
        <img :src="thumbnail" class="thumbnail" @error="handleImageError" />
        <!-- 失败后的占位 -->
        <div class="thumbnail-placeholder-error" style="display: none;">
           <Icon name="image" :size="32" />
           <span>封面加载失败</span>
        </div>
        <div class="duration-badge" v-if="duration">
          {{ formatDuration(duration) }}
        </div>
        <div class="play-overlay">
          <Icon name="play" :size="32" />
        </div>
      </div>
      
      <div class="video-meta">
        <div class="meta-top">
          <span class="platform-badge" v-if="platform">{{ platform.toUpperCase() }}</span>
          <span class="success-badge">✅ 解析成功</span>
        </div>
        
        <h2 class="video-title" :title="title">{{ title || '未命名视频' }}</h2>
        
        <div class="meta-bottom">
          <div class="author-info" v-if="author">
            <Icon name="user" :size="14" />
            <span>{{ author }}</span>
          </div>
          <div class="time-info" v-if="time">
            <Icon name="clock" :size="14" />
            <span>{{ time }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 主要内容槽位（如格式列表、下载选项等） -->
    <div class="result-body">
      <slot></slot>
    </div>

    <!-- 底部操作栏槽位 -->
    <div class="result-footer" v-if="$slots.footer">
      <slot name="footer"></slot>
    </div>
  </div>
</template>

<script setup>
import Icon from '@/components/common/Icon.vue'

const props = defineProps({
  title: String,
  author: String,
  thumbnail: String,
  duration: [Number, String],
  platform: String,
  time: String
})

const formatDuration = (val) => {
  if (typeof val === 'string' && val.includes(':')) return val
  const seconds = parseInt(val)
  if (isNaN(seconds)) return val
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  return h > 0 
    ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` 
    : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
}

const handleImageError = (e) => {
  const img = e.target
  const src = img.src

  // Youtube 质量降级逻辑
  if (src.includes('i.ytimg.com')) {
    const qualities = ['maxresdefault', 'hqdefault', 'mqdefault', 'sddefault', 'default']
    let currentIdx = -1
    for (let i = 0; i < qualities.length; i++) {
      if (src.includes(qualities[i])) {
        currentIdx = i
        break
      }
    }

    if (currentIdx >= 0 && currentIdx < qualities.length - 1) {
      const videoIdMatch = src.match(/\/vi\/([^/]+)\//)
      if (videoIdMatch) {
        const videoId = videoIdMatch[1]
        const nextQuality = qualities[currentIdx + 1]
        img.src = `https://i.ytimg.com/vi/${videoId}/${nextQuality}.jpg`
        return
      }
    }
  }

  // 最终失败逻辑
  img.style.display = 'none'
  const placeholder = img.nextElementSibling
  if (placeholder && placeholder.classList.contains('thumbnail-placeholder-error')) {
    placeholder.style.display = 'flex'
  }
}
</script>

<style scoped>
.result-card {
  margin-top: var(--spacing-xl);
  background: var(--color-bg-primary);
  border-radius: var(--radius-xl);
  border: 1px solid var(--color-border);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.video-header {
  padding: var(--spacing-lg);
  border-bottom: 1px solid var(--color-border);
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: var(--spacing-lg);
}

@media (max-width: 768px) {
  .video-header {
    grid-template-columns: 1fr;
    padding: var(--spacing-md);
    gap: var(--spacing-md);
  }

  .video-title {
    font-size: var(--font-size-md);
    margin-bottom: var(--spacing-sm);
  }

  .meta-top {
    margin-bottom: var(--spacing-xs);
  }

  .platform-badge {
    font-size: 0.65rem;
  }

  .success-badge {
    font-size: 0.8rem;
  }

  .author-info, .time-info {
    font-size: 0.8rem;
  }

  .result-body {
    padding: var(--spacing-md);
  }

  .result-footer {
    padding: var(--spacing-sm) var(--spacing-md);
  }
}

/* 超窄屏优化 */
@media (max-width: 400px) {
  .video-header {
    padding: var(--spacing-sm);
    gap: var(--spacing-sm);
  }

  .video-title {
    font-size: var(--font-size-sm);
  }

  .meta-bottom {
    flex-direction: column;
    gap: var(--spacing-xs);
  }

  .result-body {
    padding: var(--spacing-sm);
  }

  .result-footer {
    padding: var(--spacing-xs) var(--spacing-sm);
  }
}

.thumbnail-wrapper {
  position: relative;
  background: #000;
  border-radius: var(--radius-lg);
  overflow: hidden;
  aspect-ratio: 16/9;
  cursor: pointer;
}

.thumbnail {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.thumbnail-placeholder-error {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: var(--color-bg-tertiary);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--color-text-tertiary);
  gap: var(--spacing-sm);
  font-size: var(--font-size-sm);
}

.thumbnail-wrapper:hover .thumbnail {
  transform: scale(1.05);
}

.duration-badge {
  position: absolute;
  bottom: 8px;
  right: 8px;
  background: rgba(0, 0, 0, 0.8);
  color: white;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: 0.75rem;
  font-weight: 600;
  z-index: 2;
}

.play-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: white;
  opacity: 0;
  transition: opacity 0.3s ease;
  z-index: 1;
}

.thumbnail-wrapper:hover .play-overlay {
  opacity: 1;
}

.video-meta {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.meta-top {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-sm);
}

.platform-badge {
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 0.7rem;
  font-weight: 700;
}

.success-badge {
  color: var(--color-success);
  font-weight: 600;
  font-size: 0.85rem;
}

.video-title {
  font-size: var(--font-size-lg);
  font-weight: 700;
  line-height: 1.4;
  margin-bottom: var(--spacing-md);
  color: var(--color-text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.meta-bottom {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-md);
}

.author-info, .time-info {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  color: var(--color-text-tertiary);
  font-size: 0.85rem;
}

.result-body {
  padding: var(--spacing-lg);
}

.result-footer {
  padding: var(--spacing-md) var(--spacing-lg);
  background: var(--color-bg-tertiary);
  border-top: 1px solid var(--color-border);
}
</style>
