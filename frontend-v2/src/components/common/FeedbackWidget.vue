<template>
  <div v-if="visible" class="feedback-widget">
    <button class="feedback-btn" @click="openTally" title="问题反馈">
      <div class="icon-wrapper">
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
      </div>
      <span class="btn-text">反馈建议</span>
    </button>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useSystemStore } from '@/stores/system'

const systemStore = useSystemStore()

// 这里的 ID 只是占位符，需要用户提供真实的 ID 替换
const props = defineProps({
  formId: {
    type: String,
    default: ''
  },
  headless: {
    type: Boolean,
    default: false
  }
})

const visible = ref(false)

const openTally = () => {
  if (!props.formId) return
  
  // 仅在 Tally 脚本已经加载完成时，通过弹窗在当前页面打开
  if (!window.Tally) {
    // 不再回退到新标签页，避免破坏「模拟框」体验
    // 让用户稍后再试（通常脚本很快就会加载完成）
    window.alert('反馈表单正在加载，请稍后再试～')
    return
  }

  window.Tally.openPopup(props.formId, {
    layout: 'modal',
    width: 700,

    hiddenFields: {
      url: window.location.href,
      userAgent: navigator.userAgent,
      userTier: props.headless ? 'Premium' : 'Standard',
      appVersion: systemStore.app.version || 'Unknown',
      licenseKey: systemStore.license.license_key || 'Unknown'
    }
  })
}

// 暴露给全局，方便其他组件调用
window.showFeedbackForm = openTally

onMounted(() => {
  if (!window.Tally) {
    const script = document.createElement('script')
    script.src = 'https://tally.so/widgets/embed.js'
    script.async = true
    document.head.appendChild(script)
  }
  
  if (props.formId && !props.headless) {
    visible.value = true
  }
})

defineExpose({ openTally })
</script>

<style scoped>
.feedback-widget {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 40000;
}

.feedback-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--color-bg-card, #ffffff);
  color: var(--color-text-primary, #333);
  border: 1px solid var(--color-border, #ddd);
  padding: 8px 16px;
  border-radius: 50px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  font-size: 14px;
  font-weight: 500;
}

.feedback-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.icon-wrapper {
  display: flex;
  align-items: center;
}

/* 深色模式适配 */
:global([data-theme="dark"]) .feedback-btn {
  background: #2d2d2d;
  color: #e0e0e0;
  border-color: #444;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

:global([data-theme="dark"]) .feedback-btn:hover {
  background: #333;
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* 移动端优化 */
@media (max-width: 768px) {
  .feedback-widget {
    bottom: 80px; /* 避开底部导航栏如果存在 */
    right: 16px;
  }
  
  .feedback-btn {
    padding: 10px;
    border-radius: 50%;
    width: 44px;
    height: 44px;
    justify-content: center;
  }
  
  .btn-text {
    display: none;
  }
}
</style>
