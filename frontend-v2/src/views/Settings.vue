<template>
  <div class="settings-view">
    <!-- 侧边导航 -->
    <aside class="settings-sidebar">

      <div class="nav-list">
        <button 
          v-for="item in navItems" 
          :key="item.id"
          class="nav-item"
          :class="{ active: activeTab === item.id }"
          @click="setActiveTab(item.id, $event)"
        >
          <div class="nav-icon"><Icon :name="item.icon" :size="18" /></div>
          <span>{{ item.label }}</span>
        </button>
      </div>
    </aside>

    <!-- 主配置区 -->
    <main class="settings-main">
      <div class="settings-container" :class="{ 'cookie-layout': activeTab === 'cookie' || activeTab === 'notifications' || activeTab === 'license' || activeTab === 'logs' || activeTab === 'api-tokens' || activeTab === 'download' || activeTab === 'transcode-gpu' || activeTab === 'ai-model' }">
        <!-- 头部导航说明 -->


        <!-- 配置项内容 -->
        <div class="settings-body">
          <!-- 代理设置 -->
          <template v-if="activeTab === 'proxy'">
            <ProxySettings />
          </template>

          <!-- Cookie管理 -->
          <template v-else-if="activeTab === 'cookie'">
            <CookieSettings />
          </template>

          <!-- 通知设置 -->
          <template v-else-if="activeTab === 'notifications'">
            <NotificationSettings />
          </template>


          <!-- 媒体库同步 -->
          <template v-else-if="activeTab === 'media-library'">
            <MediaLibrarySettings />
          </template>

          <!-- API Token 管理 -->
          <template v-else-if="activeTab === 'api-tokens'">
            <ApiTokenSettings />
          </template>

          <!-- 日志查看 -->
          <template v-else-if="activeTab === 'logs'">
            <LogViewer />
          </template>

          <!-- 授权管理 -->
          <template v-else-if="activeTab === 'license'">
            <LicenseSettings />
          </template>

          <!-- 下载设置 -->
          <template v-else-if="activeTab === 'download'">
            <DownloadSettings />
          </template>

          <!-- GPU转码设置 -->
          <template v-else-if="activeTab === 'transcode-gpu'">
            <TranscodeGpuSettings />
          </template>

          <!-- AI模型设置 -->
          <template v-else-if="activeTab === 'ai-model'">
            <AiModelSettings />
          </template>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import ProxySettings from '@/components/settings/ProxySettings.vue'
import CookieSettings from '@/components/settings/CookieSettings.vue'
import NotificationSettings from '@/components/settings/NotificationSettings.vue'
import MediaLibrarySettings from '@/components/settings/MediaLibrarySettings.vue'
import LogViewer from '@/components/settings/LogViewer.vue'
import LicenseSettings from '@/components/settings/LicenseSettings.vue'
import ApiTokenSettings from '@/components/settings/ApiTokenSettings.vue'
import DownloadSettings from '@/components/settings/DownloadSettings.vue'
import TranscodeGpuSettings from '@/components/settings/TranscodeGpuSettings.vue'
import AiModelSettings from '@/components/settings/AiModelSettings.vue'

const route = useRoute()
const router = useRouter()
const activeTab = ref('proxy')

const navItems = [
  { id: 'proxy', label: '网络代理', icon: 'shield', desc: '配置全局网络代理,支持HTTP、HTTPS和SOCKS5协议' },
  { id: 'cookie', label: 'Cookie管理', icon: 'link', desc: '管理YouTube、Bilibili、TikTok等平台的Cookie凭证' },
  { id: 'notifications', label: '通知设置', icon: 'notifications', desc: '配置微信机器人、Server酱等消息推送服务' },
  { id: 'download', label: '下载设置', icon: 'download', desc: '配置系统全局并发上限，控制所有下载任务的总并发数' },
  { id: 'transcode-gpu', label: 'GPU转码', icon: 'monitor', desc: '识别硬件转码能力，支持多显卡手动选择与回退策略' },
  { id: 'ai-model', label: 'AI模型', icon: 'activity', desc: '配置高光分析模型，用于高光切片语义增强' },
  { id: 'media-library', label: '媒体库同步', icon: 'monitor', desc: '下载完成后自动刷新 Jellyfin/Emby 媒体库' },
  { id: 'api-tokens', label: 'API Token', icon: 'key', desc: '创建和管理 API Token，用于外部应用调用 API' },
  { id: 'logs', label: '日志查看', icon: 'logs', desc: '查看和管理系统运行日志' },
  { id: 'license', label: '授权管理', icon: 'user', desc: '管理系统授权许可证和高级功能' }
]

const currentNavItem = computed(() => navItems.find(i => i.id === activeTab.value))

// 当点击导航时，更新 URL 参数
function setActiveTab(tabId, event) {
  activeTab.value = tabId
  router.replace({ query: { ...route.query, tab: tabId } })
  
  // 移动端：点击后自动滚动到中间
  if (event && event.currentTarget) {
    event.currentTarget.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }
}

// 自动滚动到激活项执行函数
function scrollToActiveTab() {
  const activeEl = document.querySelector('.nav-item.active')
  if (activeEl) {
    activeEl.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }
}

function scrollToCookiePlatform() {
  const platform = route.query.platform
  if (!platform) return
  const target = document.querySelector(`#cookie-platform-${platform}`)
  if (target) {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

// 初始化时从 URL 读取 tab
onMounted(() => {
  const queryTab = route.query.tab
  if (queryTab && navItems.some(i => i.id === queryTab)) {
    activeTab.value = queryTab
    // 延迟一点确保 DOM 渲染完成
    setTimeout(scrollToActiveTab, 100)
  }

  if (queryTab === 'cookie') {
    setTimeout(scrollToCookiePlatform, 120)
  }
})

// 监听 URL 变化并同步（用于浏览器前进后退）
watch(() => route.query.tab, (newTab) => {
  if (newTab && navItems.some(i => i.id === newTab)) {
    activeTab.value = newTab
    setTimeout(scrollToActiveTab, 50)
  }
})

watch(() => route.query.platform, () => {
  if (activeTab.value === 'cookie') {
    setTimeout(scrollToCookiePlatform, 50)
  }
})
</script>

<style scoped>
.settings-view {
  display: flex;
  height: 100%;
  background: var(--color-bg-primary);
  overflow: hidden;
}

/* 侧边导航 */
.settings-sidebar {
  width: 260px;
  background: var(--color-bg-secondary);
  border-right: 1px solid var(--color-border);
  padding: var(--spacing-xl) 0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 0 var(--spacing-xl);
  margin-bottom: var(--spacing-xl);
}

.sidebar-header h2 {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  letter-spacing: -0.5px;
}

.sidebar-header p {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--color-text-muted);
  margin-top: var(--spacing-xs);
  font-weight: var(--font-weight-semibold);
}

.nav-list {
  display: flex;
  flex-direction: column;
  padding: 0 var(--spacing-md);
  gap: var(--spacing-xs);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-lg);
  color: var(--color-text-secondary);
  transition: all var(--transition-fast);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
}

.nav-item:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
  transform: translateX(4px);
}

.nav-item.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
}

.nav-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--color-bg-tertiary);
  transition: all var(--transition-fast);
}

.nav-item.active .nav-icon {
  background: var(--color-primary);
  color: white;
  box-shadow: 0 4px 8px var(--color-primary-light);
}

/* 主内容区 */
.settings-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow-y: auto;
  scroll-behavior: smooth;
}

.settings-container {
  width: 100%;
  margin: 0;
  padding: var(--spacing-2xl) var(--spacing-xl);
}

.settings-container.cookie-layout {
  max-width: 100%;
}

@media (min-width: 1600px) {
  .settings-container {
    max-width: 1000px;
  }
  .settings-container.cookie-layout {
    max-width: 1400px;
  }
}





.settings-body {
  min-height: 500px;
  animation: slideIn var(--transition-normal);
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 针对移动端或窄屏的适配 */
/* 针对移动端或窄屏的适配 */
@media (max-width: 768px) {
  .settings-view {
    flex-direction: column;
    min-height: 100%;
    height: auto;
    overflow: visible;
    background: var(--color-bg-primary);
  }
  
  .settings-sidebar {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid var(--color-border);
    padding: 10px 0; /* 移除左右内边距，让滚动区域到边 */
    background: var(--color-bg-secondary);
    flex-shrink: 0;
    z-index: 10;
  }
  
  /* 移动端隐藏侧边栏大标题 */
  .sidebar-header {
     display: none;
  }

  .nav-list {
    flex-direction: row;
    overflow-x: auto;
    padding: 0 var(--spacing-sm); /* 正好 8px 左边距 */
    gap: 8px;
    /* 隐藏滚动条 */
    scrollbar-width: none;
    -ms-overflow-style: none;
    -webkit-overflow-scrolling: touch;
  }
  .nav-list::-webkit-scrollbar {
    display: none;
  }
  
  .nav-item {
    flex-shrink: 0;
    padding: 6px 16px 6px 12px;
    border-radius: 100px; /* 胶囊状 */
    background: var(--color-bg-tertiary); /* 使用主题色 */
    margin: 0;
    font-size: 13px;
    gap: 6px;
  }
  
  .nav-item:hover {
      transform: none; 
      background: var(--color-bg-tertiary);
  }
  
  .nav-item.active {
    background: var(--color-primary);
    color: white;
  }
  
  .nav-icon {
    width: 20px;
    height: 20px;
    background: transparent !important; /* 移动端胶囊模式下图标背景透明更自然 */
    color: inherit;
    box-shadow: none !important;
  }
  
  .nav-icon :deep(.icon) {
      width: 14px !important;
      height: 14px !important;
  }

  .settings-main {
    padding: 0;
    background: var(--color-bg-primary);
    overflow-y: visible; /* 移除滚动，让父级 .main-content 负责滚动 */
    flex: none; /* 移除 flex: 1，让内容自然展开 */
  }

  .settings-container {
    padding: var(--spacing-sm);
    max-width: 100%;
  }
  

  
  /* 强制覆盖子组件中的 Grid 布局，转为移动端垂直堆叠 */
  :deep(.setting-item) {
      grid-template-columns: 1fr !important;
      gap: 12px !important;
      padding: 20px 0 !important;
  }
  
  :deep(.setting-control) {
      width: 100%;
      padding-top: 0 !important;
      flex-wrap: wrap; /* 允许按钮换行 */
  }

  /* 统一输入框和下拉框宽度 */
  :deep(.form-input), :deep(.form-select) {
      width: 100% !important;
      max-width: none !important;
  }

  /* 按钮适配 */
  :deep(.btn) {
      flex: 1; /* 多个按钮时均分 */
      min-width: 100px; /* 防止太小 */
      justify-content: center;
  }
  
  /* 针对 form-group-row 的特定修复 (如果存在) */
  :deep(.form-group-row) {
      flex-direction: column !important;
      align-items: flex-start !important;
      gap: 8px !important;
  }
  
  :deep(.form-label) {
      width: 100% !important;
      margin-bottom: 4px !important;
  }
}
</style>
