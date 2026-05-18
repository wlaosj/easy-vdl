<template>
  <aside 
    class="sidebar" 
    :class="{ 
      collapsed: isCollapsed && !systemStore.isMobile,
      'mobile-open': systemStore.sidebarOpen && systemStore.isMobile,
      'is-mobile': systemStore.isMobile
    }"
  >
    <!-- Logo -->
    <div class="sidebar-header">
      <div class="logo" @click="handleLogoClick" title="点击折叠/展开侧边栏">
        <div class="logo-container">
          <BrandLogo class="logo-svg" :rotating="systemStore.metrics.downloads.downloading > 0" />
        </div>
        <div class="logo-text-group" v-show="!isCollapsed || systemStore.isMobile">
          <span class="logo-text">Easy-VDL</span>
        </div>
      </div>
    </div>


    <!-- 导航菜单 -->
    <nav class="sidebar-nav">
      <router-link 
        v-for="item in menuItems" 
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: isActive(item.path), pending: isPending(item.path), analyzing: item.path === '/live-highlights' && systemStore.highlightsAnalyzing }"
        @click="handleNavClick(item.path)"
      >
        <div class="nav-icon-wrapper">
          <!-- Custom SVG Icon -->
          <svg 
            v-if="item.svgPath"
            viewBox="0 0 24 24" 
            width="20" 
            height="20"
            class="nav-icon-svg"
          >
            <path :d="item.svgPath" fill="currentColor" />
          </svg>
          <!-- Standard Icon -->
          <Icon v-else :name="item.icon" :size="20" />
        </div>
        
        <span class="nav-text" v-show="!isCollapsed || systemStore.isMobile">{{ item.label }}</span>
        <span
          class="nav-tag"
          :class="item.tagType === 'lifetime' ? 'lifetime-tag' : 'premium-tag'"
          v-if="(item.tagLabel || item.isPremium) && (!isCollapsed || systemStore.isMobile)"
        >
          {{ item.tagLabel || 'PRO' }}
        </span>
        <span class="nav-badge" v-if="getBadge(item) && (!isCollapsed || systemStore.isMobile)">{{ getBadge(item) }}</span>
      </router-link>
    </nav>

    <!-- 底部许可证状态 -->
    <div class="sidebar-footer" v-show="!isCollapsed || systemStore.isMobile">
      <LicenseCardShell
        class="license-card" 
        :class="[licenseStatus, { 'loading': systemStore.license.isLoading }]" 
        :is-licensed="systemStore.license.is_licensed"
        :remaining-days="systemStore.license.remaining_days"
        :loading="systemStore.license.isLoading"
        @click="goToLicenseSettings"
      >
        <template v-if="systemStore.license.isLoading">
          <div class="sidebar-license-skeleton">
            <div class="skeleton-dot"></div>
            <div class="skeleton-text"></div>
          </div>
        </template>
        <template v-else>
          <div class="license-header-compact">
            <!-- 皇冠图标 -->
            <div class="license-crown">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="currentColor">
                <path d="M5 16L3 5l5.5 5L12 4l3.5 6L21 5l-2 11H5z"/>
                <path d="M5 19h14v2H5z" opacity="0.8"/>
              </svg>
            </div>
            <!-- 授权信息 -->
            <div class="license-main">
              <span class="license-label">{{ systemStore.license.is_licensed ? '高级版' : '基础版' }}</span>
            </div>
          </div>
          <!-- 用量信息 -->
          <div class="license-usage">
            <div class="usage-info-row">
              <span class="usage-text">{{ systemStore.license.is_licensed ? expirationText : '' }}</span>
              <button
                v-if="systemStore.license.is_licensed"
                class="sidebar-feedback-btn"
                type="button"
                @click.stop="handleFeedbackClick"
                title="高级版用户专属优先反馈通道"
              >
                <Icon name="message-square" :size="13" />
                高级专享反馈
              </button>
            </div>
            <div class="usage-bar">
              <div class="usage-fill" :style="{ width: usagePercent + '%' }"></div>
            </div>
          </div>
        </template>
      </LicenseCardShell>
    </div>


  </aside>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDownloadsStore } from '@/stores/downloads'
import { useSystemStore } from '@/stores/system'
import { setPendingRoutePath, useRouteLoadingState } from '@/composables/useRouteLoading'
import Icon from '@/components/common/Icon.vue'
import LicenseCardShell from '@/components/common/LicenseCardShell.vue'
import BrandLogo from '@/components/common/BrandLogo.vue'

const route = useRoute()
const router = useRouter()
const downloadsStore = useDownloadsStore()
const systemStore = useSystemStore()
const { isRouteLoading, pendingRoutePath } = useRouteLoadingState()

const isCollapsed = ref(localStorage.getItem('sidebarCollapsed') === 'true')

// Platform Icons (SVG Paths)
const ICONS = {
  YOUTUBE: 'M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z',
  TIKTOK: 'M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.1z',
  NETEASE: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 14.5c-2.49 0-4.5-2.01-4.5-4.5S9.51 7.5 12 7.5s4.5 2.01 4.5 4.5-2.01 4.5-4.5 4.5zm0-5.5c-.55 0-1 .45-1 1s.45 1 1 1 1-.45 1-1-.45-1-1-1z'
}

const menuItems = [
  { path: '/', label: '仪表盘', icon: 'dashboard' },
  { path: '/subscriptions', label: '视频订阅', icon: 'film', isPremium: true },
  { path: '/live-record', label: '直播订阅', icon: 'video-camera', isPremium: true },
  
  // 核心工具组
  { path: '/youtube-bili', label: '油管B站', svgPath: ICONS.YOUTUBE },
  { path: '/short-video', label: '某音某书', svgPath: ICONS.TIKTOK },
  { path: '/netease', label: '某云音乐', svgPath: ICONS.NETEASE },
  { path: '/universal', label: '通用提取', icon: 'link', isPremium: true },
  { path: '/player', label: '视频播放', icon: 'play' },
  { path: '/live-timeline', label: '直播回放', icon: 'history', isPremium: true },
  { path: '/live-highlights', label: '高光切片', icon: 'activity', isPremium: true, tagLabel: 'LIFETIME', tagType: 'lifetime' },
  
  // 管理组
  // 下面这个 badge 改为通过 getBadge 动态获取，避免响应式更新导致整个菜单重绘
  { path: '/downloads', label: '下载中心', icon: 'download' },

  
  // 系统组
  { path: '/settings', label: '系统设置', icon: 'settings' }
]

function getBadge(item) {
  if (item.path === '/downloads') {
    return systemStore.metrics.downloads.downloading || null
  }
  if (item.path === '/live-record') {
    return systemStore.metrics.live_stats?.recording_count || null
  }
  return item.badge || null
}

onMounted(() => {
  systemStore.fetchLicenseStatus()
})

// 许可证状态
const licenseStatus = computed(() => {
  // 与全局口径一致：当前授权可用即视为 active
  if (systemStore.license.is_licensed) return 'active'
  if (systemStore.license.status === 'expired') return 'expired'
  return 'trial'
})

const licenseType = computed(() => {
  if (systemStore.license.is_licensed) return '高级版'
  return '免费版'
})

const licenseText = computed(() => {
  if (licenseStatus.value === 'active') return '已激活'
  if (licenseStatus.value === 'expired') return '已过期'
  return '未授权'
})

const expirationText = computed(() => {
  if (!systemStore.license.is_licensed) return '功能受限'
  const days = systemStore.license.remaining_days
  // 支持 -1 和大数字两种方式表示永久
  if (days === -1 || days > 3650) return '永久有效'
  return `有效期剩余 ${days} 天`
})

const usagePercent = computed(() => {
  // 保持进度条视觉效果：永久授权满格，否则按365天计算比例
  const days = systemStore.license.remaining_days || 0
  // 永久密钥满格
  if (days === -1 || days > 365) return 100
  return Math.max(0, Math.min(100, (days / 365) * 100))
})

function handleLogoClick() {
  if (systemStore.isMobile) {
    systemStore.sidebarOpen = false
  } else {
    isCollapsed.value = !isCollapsed.value
    // 持久化保存状态
    localStorage.setItem('sidebarCollapsed', isCollapsed.value)
  }
}

function handleNavClick(path) {
  if (!isActive(path)) {
    setPendingRoutePath(path)
  }
  if (systemStore.isMobile) {
    systemStore.sidebarOpen = false
  }
}

function isPending(path) {
  return isRouteLoading.value && pendingRoutePath.value === path && !isActive(path)
}

function isActive(path) {
  if (path === '/') {
    return route.path === '/'
  }
  return route.path.startsWith(path)
}

function goToLicenseSettings() {
  router.push('/settings?tab=license')
  // 移动端点击后关闭侧边栏
  if (systemStore.isMobile) {
    systemStore.sidebarOpen = false
  }
}

function handleFeedbackClick() {
  if (typeof window.showFeedbackForm === 'function') {
    window.showFeedbackForm()
  } else {
    window.alert('反馈表单正在初始化，请稍后再试一次～')
  }
}
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--color-bg-secondary);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  transition: transform var(--transition-normal), width var(--transition-normal);
  overflow: hidden;
  z-index: 10000;
}

.sidebar.collapsed {
  width: var(--sidebar-collapsed-width);
}

/* Mobile styles */
.sidebar.is-mobile {
  position: fixed;
  top: 0;
  left: 0;
  transform: translateX(-100%);
  width: 280px; /* 移动端固定宽度 */
}

.sidebar.is-mobile.mobile-open {
  transform: translateX(0);
  box-shadow: 10px 0 30px rgba(0, 0, 0, 0.25);
}

/* Header */
.sidebar-header {
  height: 60px; /* 减小高度以匹配 Header */
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--spacing-lg);
  border-bottom: 1px solid var(--color-border);
}

.logo {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  cursor: pointer;
  user-select: none;
  transition: transform var(--transition-fast);
}

.logo:hover {
  transform: scale(1.02);
}

.logo:active {
  transform: scale(0.98);
}


.logo-container {
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform var(--transition-normal);
}

.logo-svg.is-rotating {
  animation: logo-rotate 3s linear infinite;
}

@keyframes logo-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.logo-svg {
  width: 36px;
  height: 36px;
  filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.2));
  transition: transform var(--transition-fast);
}

.logo:hover .logo-container {
  transform: scale(1.1);
}

.logo-text-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.logo-text {
  font-size: 20px;
  font-weight: 850;
  letter-spacing: -0.8px;
  background: linear-gradient(135deg, #FF4D4D, #F9CB28);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  white-space: nowrap;
  font-family: 'Outfit', 'Inter', sans-serif;
  line-height: 1;
}





.collapse-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  color: var(--color-text-tertiary);
  transition: all var(--transition-fast);
}

.collapse-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

/* Navigation */
.sidebar-nav {
  flex: 1;
  padding: var(--spacing-md);
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  padding: 6px 12px;
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  transition: all var(--transition-fast);
  text-decoration: none;
  white-space: nowrap;
}

.nav-item:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

.nav-item:hover .nav-icon-wrapper {
  background: rgba(230, 126, 34, 0.05);
}

/* 图标包裹容器 */
.nav-icon-wrapper {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

/* 左侧激活指示线 */
.nav-item::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 50%;
  width: 3px;
  height: 20px;
  border-radius: 0 2px 2px 0;
  background: var(--gradient-header);
  transform: translateY(-50%) scaleY(0);
  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  pointer-events: none;
}

.nav-item.active::before,
.nav-item.router-link-active::before {
  transform: translateY(-50%) scaleY(1);
}

/* 确保 active 状态优先级高于 hover */
.nav-item.active,
.nav-item.router-link-active {
  background: rgba(230, 126, 34, 0.05) !important;
  color: var(--color-text-primary) !important;
}

.nav-item.active .nav-icon-wrapper,
.nav-item.router-link-active .nav-icon-wrapper {
  background: var(--gradient-header) !important;
  color: white !important;
  box-shadow: 0 4px 12px rgba(231, 76, 60, 0.25);
}

.nav-item.pending {
  background: rgba(230, 126, 34, 0.08);
  color: var(--color-text-primary);
}

.nav-item.pending .nav-icon-wrapper {
  background: rgba(230, 126, 34, 0.18);
  animation: pending-pulse 0.9s ease-in-out infinite;
}

@keyframes pending-pulse {
  0% { transform: scale(1); }
  50% { transform: scale(1.06); }
  100% { transform: scale(1); }
}

.nav-item.analyzing {
  background: rgba(239, 68, 68, 0.08);
}

.nav-item.analyzing .nav-icon-wrapper {
  background: rgba(239, 68, 68, 0.2);
  animation: analyze-pulse 1.2s ease-in-out infinite;
  box-shadow: 0 0 10px rgba(239, 68, 68, 0.15);
}

@keyframes analyze-pulse {
  0%, 100% { transform: scale(1); box-shadow: 0 0 10px rgba(239, 68, 68, 0.15); }
  50% { transform: scale(1.1); box-shadow: 0 0 20px rgba(239, 68, 68, 0.35); }
}

/* Collapsed State */
.sidebar.collapsed .sidebar-header {
  padding: 0 var(--spacing-sm);
  justify-content: center;
}

.sidebar.collapsed .sidebar-nav {
  padding: var(--spacing-sm);
}

.sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 8px;
}


.nav-text {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
}

.nav-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #ff4d4d;
  color: white;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 800;
  margin-left: auto;
  box-shadow: 0 2px 8px rgba(255, 77, 77, 0.4);
  line-height: 1;
  animation: badge-pulse 2s infinite;
}

@keyframes badge-pulse {
  0% { transform: scale(1); }
  50% { transform: scale(1.05); }
  100% { transform: scale(1); }
}

[data-theme="dark"] .nav-badge {
  background: #e74c3c;
  box-shadow: 0 2px 10px rgba(231, 76, 60, 0.5);
}

.nav-tag {
  font-size: 9px;
  font-weight: 800;
  padding: 1px 4px;
  border-radius: 4px;
  margin-left: 4px;
  line-height: 1;
  letter-spacing: 0.2px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  flex-shrink: 0;
}

.premium-tag {
  background: linear-gradient(135deg, #FFD700, #FFA500);
  color: #5c3a00;
}

.lifetime-tag {
  background: linear-gradient(135deg, #ff7a18, #ff4d4d);
  color: #fff;
  letter-spacing: 0.3px;
}

[data-theme="dark"] .premium-tag {
  background: linear-gradient(135deg, #f1c40f, #e67e22);
  color: #2c1e00;
}

[data-theme="dark"] .lifetime-tag {
  background: linear-gradient(135deg, #ff8a1f, #ff5a3d);
  color: #fff4e8;
}

/* Footer - License Card (Unraid Style) */
.sidebar-footer {
  padding: var(--spacing-md);
}

.sidebar-license-skeleton {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.skeleton-dot {
  width: 24px;
  height: 24px;
  background: var(--color-bg-tertiary);
  border-radius: 50%;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

.skeleton-text {
  flex: 1;
  height: 12px;
  background: var(--color-bg-tertiary);
  border-radius: 4px;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

@keyframes skeleton-pulse {
  0% { opacity: 0.6; }
  50% { opacity: 0.3; }
  100% { opacity: 0.6; }
}

.license-card {
  padding: 16px;
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: padding var(--transition-fast);
}

.license-card .license-label {
  font-size: 18px;
  white-space: nowrap;
  line-height: 1.1;
}

.license-card .usage-info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.license-card .sidebar-feedback-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  border: 1px solid rgba(230, 126, 34, 0.35);
  border-radius: 6px;
  background: rgba(230, 126, 34, 0.12);
  color: var(--color-text-primary);
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  padding: 3px 8px;
  white-space: nowrap;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.license-card .sidebar-feedback-btn:hover {
  background: rgba(230, 126, 34, 0.18);
  border-color: rgba(230, 126, 34, 0.5);
}

.license-card.is-lifetime .license-header-compact {
  padding-right: 74px;
}

/* 移动端适配 - 上移授权卡片避免被遮挡 */
@media (max-width: 768px) {
  .sidebar-footer {
    padding: var(--spacing-md) var(--spacing-md) calc(var(--spacing-md) + 60px);
    /* 增加底部padding，让卡片上移，避免被系统导航栏遮挡 */
  }

  .license-card {
    padding: 12px;
  }

  .license-card .license-label {
    font-size: 16px;
  }

  .license-card .sidebar-feedback-btn {
    font-size: 9px;
    padding: 2px 6px;
  }

}

/* 超小屏幕进一步优化 */
@media (max-width: 480px) {
  .sidebar-footer {
    padding: var(--spacing-sm) var(--spacing-sm) calc(var(--spacing-sm) + 80px);
    /* 超小屏幕进一步增加底部padding */
  }

  .license-card {
    padding: 10px;
  }
}


</style>
