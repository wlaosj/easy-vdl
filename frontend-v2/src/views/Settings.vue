<template>
  <div class="settings-view">
    <!-- 移动端设置中心九宫格门户 -->
    <div v-if="isMobile && !showMobileDetail" class="mobile-settings-portal">
      <div class="portal-header">
        <h2>设置中心</h2>
        <p>SYSTEM SETTINGS</p>
      </div>
      
      <div class="portal-grid">
        <div 
          v-for="item in navItems" 
          :key="item.id"
          class="portal-card"
          @click="selectPortalItem(item.id)"
        >
          <div class="portal-card-glow"></div>
          <div class="portal-card-icon-wrapper" :class="item.id">
            <Icon :name="item.icon" :size="20" />
          </div>
          <div class="portal-card-content">
            <h4>{{ item.label }}</h4>
            <p>{{ item.desc || '管理系统全局配置项' }}</p>
          </div>
          <div class="portal-card-arrow">
            <Icon name="arrow-right" :size="12" />
          </div>
        </div>
      </div>
    </div>

    <!-- 侧边导航 (PC端显示，移动端隐藏) -->
    <aside v-if="!isMobile" class="settings-sidebar">
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
    <main v-if="!isMobile || showMobileDetail" class="settings-main">
      <!-- 移动端面包屑导航 -->
      <div v-if="isMobile && showMobileDetail" class="mobile-breadcrumb-header">
        <button class="back-portal-btn" @click="backToPortal">
          <Icon name="chevron-left" :size="14" />
          <span>设置中心</span>
        </button>
        <span class="breadcrumb-divider">/</span>
        <span class="current-module-title">{{ currentNavItem?.label }}</span>
      </div>

      <div class="settings-container" :class="{ 'cookie-layout': activeTab === 'cookie' || activeTab === 'notifications' || activeTab === 'license' || activeTab === 'logs' || activeTab === 'api-tokens' || activeTab === 'download' || activeTab === 'transcode-gpu' || activeTab === 'ai-model' }">
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
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
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

const isMobile = ref(false)
const showMobileDetail = ref(false)

const navItems = [
  { id: 'proxy', label: '网络代理', icon: 'shield', desc: '配置全局网络代理，支持 HTTP、HTTPS 与 SOCKS5 代理' },
  { id: 'cookie', label: 'Cookie管理', icon: 'link', desc: '管理 YouTube、Bilibili、TikTok 等主流平台凭证' },
  { id: 'notifications', label: '通知设置', icon: 'notifications', desc: '配置微信机器人、Server酱与 Telegram 消息推送' },
  { id: 'download', label: '下载设置', icon: 'download', desc: '配置并发限制与速度上限，调控网络带宽总吞吐量' },
  { id: 'transcode-gpu', label: 'GPU转码', icon: 'monitor', desc: '自动检测硬件加速环境，调节多卡并联与解码回退' },
  { id: 'ai-model', label: 'AI模型', icon: 'activity', desc: '配置本地高光分析算法模型，调配切片识别灵敏度' },
  { id: 'media-library', label: '媒体库同步', icon: 'monitor', desc: '下载完成事件触发后，一键自动拉起 Jellyfin 刷新' },
  { id: 'api-tokens', label: 'API Token', icon: 'key', desc: '快速生成和回收 API Token 令牌，供第三方应用调用' },
  { id: 'logs', label: '日志查看', icon: 'logs', desc: '实时监控系统后端运行轨迹，导出并清理崩溃排查日志' },
  { id: 'license', label: '授权管理', icon: 'user', desc: '查看并激活系统高级商业功能授权，维护正版安全许可证' }
]

const currentNavItem = computed(() => navItems.find(i => i.id === activeTab.value))

function checkMobile() {
  isMobile.value = window.innerWidth <= 768
}

// 当点击导航时，更新 URL 参数 (PC端)
function setActiveTab(tabId, event) {
  activeTab.value = tabId
  router.replace({ query: { ...route.query, tab: tabId } })
  
  // 自动滚动到中间
  if (event && event.currentTarget) {
    event.currentTarget.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }
}

// 选择门户项目 (移动端)
function selectPortalItem(tabId) {
  activeTab.value = tabId
  router.replace({ query: { ...route.query, tab: tabId } })
  showMobileDetail.value = true
}

// 返回门户 (移动端)
function backToPortal() {
  showMobileDetail.value = false
  // 清除 tab 参数
  const query = { ...route.query }
  delete query.tab
  router.replace({ query })
}

// 自动滚动到激活项执行函数 (PC端)
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
  checkMobile()
  window.addEventListener('resize', checkMobile)

  const queryTab = route.query.tab
  if (queryTab && navItems.some(i => i.id === queryTab)) {
    activeTab.value = queryTab
    showMobileDetail.value = true
    // 延迟一点确保 DOM 渲染完成
    setTimeout(scrollToActiveTab, 100)
  } else {
    showMobileDetail.value = false
  }

  if (queryTab === 'cookie') {
    setTimeout(scrollToCookiePlatform, 120)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', checkMobile)
})

// 监听 URL 变化并同步（用于浏览器前进后退）
watch(() => route.query.tab, (newTab) => {
  if (newTab && navItems.some(i => i.id === newTab)) {
    activeTab.value = newTab
    showMobileDetail.value = true
    setTimeout(scrollToActiveTab, 50)
  } else {
    showMobileDetail.value = false
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
@media (max-width: 768px) {
  .settings-view {
    flex-direction: column;
    min-height: 100%;
    height: auto;
    overflow: visible;
    background: var(--color-bg-primary);
  }
  
  .settings-sidebar {
    display: none !important; /* 彻底移除移动端滚动的胶囊导航栏，使用精美卡片仪表盘 */
  }

  /* 移动端设置中心九宫格门户 */
  .mobile-settings-portal {
    width: 100%;
    padding: 16px 12px 30px 12px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: 20px;
    animation: slideIn var(--transition-normal);
  }

  .portal-header {
    padding: 0 4px;
    margin-bottom: 4px;
  }

  .portal-header h2 {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--color-text-primary);
    letter-spacing: -0.5px;
  }

  .portal-header p {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--color-primary);
    margin-top: 4px;
    font-weight: 700;
  }

  .portal-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
    width: 100%;
    box-sizing: border-box;
  }

  .portal-card {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
    padding: 16px 14px;
    background: var(--color-bg-secondary);
    border: 1px solid var(--color-border);
    border-radius: 16px;
    cursor: pointer;
    overflow: hidden;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
    min-width: 0;
    box-sizing: border-box;
  }

  .portal-card:active {
    transform: scale(0.97);
    background: var(--color-bg-hover);
    border-color: var(--color-primary);
  }

  .portal-card-glow {
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(circle, rgba(var(--color-primary-rgb), 0.03) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
  }

  .portal-card-icon-wrapper {
    position: relative;
    z-index: 1;
    width: 38px;
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 12px;
    flex-shrink: 0;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
  }

  /* 炫彩渐变图标颜色背景对齐 */
  .portal-card-icon-wrapper.proxy { background: linear-gradient(135deg, #3b82f6, #1d4ed8); color: white; }
  .portal-card-icon-wrapper.cookie { background: linear-gradient(135deg, #f97316, #ea580c); color: white; }
  .portal-card-icon-wrapper.notifications { background: linear-gradient(135deg, #ec4899, #db2777); color: white; }
  .portal-card-icon-wrapper.download { background: linear-gradient(135deg, #10b981, #059669); color: white; }
  .portal-card-icon-wrapper.transcode-gpu { background: linear-gradient(135deg, #8b5cf6, #7c3aed); color: white; }
  .portal-card-icon-wrapper.ai-model { background: linear-gradient(135deg, #6366f1, #4f46e5); color: white; }
  .portal-card-icon-wrapper.media-library { background: linear-gradient(135deg, #06b6d4, #0891b2); color: white; }
  .portal-card-icon-wrapper.api-tokens { background: linear-gradient(135deg, #f59e0b, #d97706); color: white; }
  .portal-card-icon-wrapper.logs { background: linear-gradient(135deg, #6b7280, #4b5563); color: white; }
  .portal-card-icon-wrapper.license { background: linear-gradient(135deg, #14b8a6, #0d9488); color: white; }

  .portal-card-content {
    position: relative;
    z-index: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
    width: 100%;
    min-width: 0;
  }

  .portal-card-content h4 {
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--color-text-primary);
    margin: 0;
  }

  .portal-card-content p {
    font-size: 0.7rem;
    color: var(--color-text-muted);
    line-height: 1.3;
    margin: 0;
    /* 双行截断，保持高度一致 */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    height: 2.6em; 
  }

  .portal-card-arrow {
    position: absolute;
    top: 16px;
    right: 14px;
    color: var(--color-text-muted);
    opacity: 0.5;
    z-index: 1;
  }

  /* 移动端面包屑导航 */
  .mobile-breadcrumb-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 14px;
    background: var(--color-bg-secondary);
    border-bottom: 1px solid var(--color-border);
    margin: 0 0 12px 0;
    width: 100%;
    box-sizing: border-box;
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
  }

  .back-portal-btn {
    display: flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: none;
    color: var(--color-primary);
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    padding: 2px 4px;
    border-radius: 4px;
    transition: background-color 0.2s;
  }

  .back-portal-btn:active {
    background-color: var(--color-bg-hover);
  }

  .breadcrumb-divider {
    color: var(--color-text-muted);
    font-size: 0.78rem;
    opacity: 0.5;
  }

  .current-module-title {
    font-size: 0.82rem;
    font-weight: 500;
    color: var(--color-text-primary);
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
