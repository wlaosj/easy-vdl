<template>
  <header class="header">
    <div class="header-left">
      <!-- 移动端汉堡菜单 -->
      <button 
        v-if="systemStore.isMobile" 
        class="header-btn mobile-menu-btn" 
        @click="systemStore.sidebarOpen = true"
      >
        <BrandLogo class="mobile-logo-svg" :rotating="systemStore.metrics.downloads.downloading > 0" :outerGlow="false" strokeWidth="3" />
      </button>
      <h1 class="page-title">{{ pageTitle }}</h1>
      <!-- 免责声明入口（一级位置，桌面端显示） -->
      <button class="header-btn disclaimer-btn desktop-only" @click="handleShowDisclaimer" title="免责声明">
        <Icon name="file-text" :size="18" />
      </button>
      <!-- 一级入口：电报群 / 购买授权 / 项目主页（桌面端显示） -->
      <a
        href="https://t.me/+7jcTMePlNVwwZjg1"
        target="_blank"
        class="header-btn tg-btn desktop-only"
        title="加入交流群组"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M21.435 2.582a1.933 1.933 0 0 0-1.93-.503L2.528 7.309a1.933 1.933 0 0 0-.21 3.574l4.66 2.09c.404.181.884.116 1.22-.166l8.032-6.732c.15-.125.342.083.21.21l-6.83 6.61a1.607 1.607 0 0 0-.462 1.134v3.52c0 .546.43.916.924.78l2.91-.803a1.2 1.2 0 0 1 .947.163l4.316 2.91a1.933 1.933 0 0 0 2.923-1.4l1.492-14.77a1.933 1.933 0 0 0-.805-1.748z" fill="currentColor"/>
        </svg>
      </a>

      <a
        href="https://c.fakamiao.top/shopDetail/6WNe26"
        target="_blank"
        class="header-btn afdian-btn desktop-only"
        title="购买高级版授权"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path>
          <line x1="3" y1="6" x2="21" y2="6"></line>
          <path d="M16 10a4 4 0 0 1-8 0"></path>
        </svg>
      </a>

      <a
        href="https://hub.docker.com/r/qq918652593/easy-vdl"
        target="_blank"
        class="header-btn docker-btn desktop-only"
        title="DockerHub 主页"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <line x1="2" y1="12" x2="22" y2="12"/>
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
        </svg>
      </a>

      <button
        class="header-btn theme-toggle-btn desktop-only"
        @click="handleThemeToggle"
        :title="systemStore.theme === 'light' ? '切换到深色模式' : '切换到浅色模式'"
      >
        <Icon :name="systemStore.theme === 'light' ? 'moon' : 'sun'" :size="20" />
      </button>
    </div>

    <!-- 右侧操作区 -->
    <div class="header-right">
      <!-- 移动端主题切换 -->
      <button
        class="header-btn theme-toggle-btn mobile-only"
        @click="handleThemeToggle"
        :title="systemStore.theme === 'light' ? '切换到深色模式' : '切换到浅色模式'"
      >
        <Icon :name="systemStore.theme === 'light' ? 'moon' : 'sun'" :size="20" />
      </button>

      <!-- 遮罩层 -->
      <div v-if="showUserMenu" class="menu-overlay" @click="showUserMenu = false"></div>

      <!-- 用户菜单 -->
      <div class="user-menu" @click="showUserMenu = !showUserMenu">
        <div class="user-avatar">
          <BrandLogo class="avatar-logo-svg" :rotating="systemStore.metrics.downloads.downloading > 0" :outerGlow="false" strokeWidth="3" />
        </div>

        <!-- 下拉菜单 -->
        <div class="dropdown-menu" v-show="showUserMenu" @click.stop>
          <div class="dropdown-header">
            <div class="user-avatar large">
              <BrandLogo class="avatar-logo-svg" :rotating="systemStore.metrics.downloads.downloading > 0" :outerGlow="false" strokeWidth="3" />
            </div>
            <div class="user-info">
              <span class="user-name">{{ userName }}</span>
            </div>
          </div>

          <!-- 移动端专属菜单项 -->
          <button class="dropdown-item mobile-only" @click="handleMobileDisclaimer">
            <Icon name="file-text" :size="16" />
            <span>免责声明</span>
          </button>
          <a
            href="https://t.me/+7jcTMePlNVwwZjg1"
            target="_blank"
            class="dropdown-item mobile-only"
            @click="showUserMenu = false"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
              <path d="M21.435 2.582a1.933 1.933 0 0 0-1.93-.503L2.528 7.309a1.933 1.933 0 0 0-.21 3.574l4.66 2.09c.404.181.884.116 1.22-.166l8.032-6.732c.15-.125.342.083.21.21l-6.83 6.61a1.607 1.607 0 0 0-.462 1.134v3.52c0 .546.43.916.924.78l2.91-.803a1.2 1.2 0 0 1 .947.163l4.316 2.91a1.933 1.933 0 0 0 2.923-1.4l1.492-14.77a1.933 1.933 0 0 0-.805-1.748z"/>
            </svg>
            <span>加入交流群</span>
          </a>
          <a
            href="https://c.fakamiao.top/shopDetail/6WNe26"
            target="_blank"
            class="dropdown-item mobile-only"
            @click="showUserMenu = false"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/>
            </svg>
            <span>购买授权</span>
          </a>
          <a
            href="https://hub.docker.com/r/qq918652593/easy-vdl"
            target="_blank"
            class="dropdown-item mobile-only"
            @click="showUserMenu = false"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
            <span>项目主页</span>
          </a>

          <div class="dropdown-divider mobile-only"></div>

          <a href="#" class="dropdown-item danger" @click.prevent="handleLogout">
            <Icon name="log-out" :size="16" />
            <span>退出登录</span>
          </a>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useSystemStore } from '@/stores/system'
import Icon from '@/components/common/Icon.vue'
import BrandLogo from '@/components/common/BrandLogo.vue'
import { useToast } from '@/composables/useToast'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const systemStore = useSystemStore()
const toast = useToast()

const showUserMenu = ref(false)

onMounted(() => {
    if (authStore.isAuthenticated && !authStore.user) {
        authStore.fetchUserInfo()
    }
})

const userName = computed(() => authStore.user?.username || 'Admin')
const pageTitle = computed(() => route.meta.title || 'Easy-VDL')

function handleShowDisclaimer() {
  if (typeof window.showDisclaimer === 'function') {
    window.showDisclaimer()
  }
}

function handleMobileDisclaimer() {
  showUserMenu.value = false
  handleShowDisclaimer()
}

function handleThemeToggle(event) {
  const target = event?.currentTarget
  if (target && typeof window !== 'undefined') {
    const rect = target.getBoundingClientRect()
    window.dispatchEvent(new CustomEvent('theme-toggle-with-origin', {
      detail: {
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2
      }
    }))
    return
  }
  systemStore.toggleTheme()
}

function handleLogout() {
  authStore.logout()
  toast.success('已退出登录')
  router.push('/login')
}
</script>

<style scoped>
.header {
  height: 60px; /* 显式设置为 60px 以匹配 Sidebar */
  background: linear-gradient(135deg, #e74c3c 0%, #f39c12 100%);
  border-bottom: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--spacing-lg);
  transition: background 0.3s ease;
  position: relative;
  z-index: 100;
}

[data-theme="dark"] .header {
  background: linear-gradient(135deg, #8e2e25 0%, #a66a0c 100%);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

@media (max-width: 768px) {
  .header {
    padding: 0 var(--spacing-sm);
  }
}

/* Left */
.header-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.mobile-menu-btn {
  margin-left: -4px;
  background: transparent;
  border: none;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mobile-logo-img {
  width: 32px;
  height: 32px;
  object-fit: contain;
  background: rgba(255, 255, 255, 0.95);
  border-radius: var(--radius-md);
  padding: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transition: transform var(--transition-fast);
}

.mobile-logo-img:active {
  transform: scale(0.9);
}

.mobile-logo-svg {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform var(--transition-fast);
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.15));
  flex-shrink: 0;
  border: none;
}

.is-rotating {
  animation: logo-rotate 3s linear infinite;
}

@keyframes logo-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

[data-theme="dark"] .mobile-logo-svg {
  filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.3));
}

.mobile-menu-btn:active .mobile-logo-svg {
  transform: scale(0.9);
}

.page-title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: #ffffff;
  margin: 0;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

[data-theme="dark"] .page-title {
  color: rgba(255, 255, 255, 0.95);
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}

@media (max-width: 768px) {
  .page-title {
    font-size: var(--font-size-lg);
  }
}


/* Right */
.header-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

/* Header Button */
.header-btn {
  position: relative;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  color: rgba(255, 255, 255, 0.85);
  transition: all var(--transition-fast);
}

.header-btn:hover {
  color: #ffffff;
}

.disclaimer-btn {
  width: 36px;
  height: 36px;
  background: rgba(255, 255, 255, 0.12);
}

.disclaimer-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.tg-btn:hover {
  color: #24A1DE !important;
  background: transparent !important;
}

.afdian-btn:hover {
  color: #946ce6 !important;
  background: transparent !important;
}

.docker-btn:hover {
  color: #0db7ed !important;
  background: transparent !important;
}

.theme-toggle-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 0;
  color: rgba(255, 255, 255, 0.9);
}

.theme-toggle-btn:hover {
  transform: translateY(-1px);
}

.theme-toggle-btn:active {
  transform: translateY(0) scale(0.92);
}

.theme-toggle-btn :deep(.icon) {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.theme-toggle-btn:hover :deep(.icon) {
  transform: scale(1.1);
}

[data-theme="dark"] .theme-toggle-btn {
  color: #f39c12;
}


.header-btn .badge {
  position: absolute;
  top: 6px;
  right: 6px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  font-size: 10px;
  font-weight: var(--font-weight-bold);
  background: var(--color-error);
  color: white;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
}

/* User Menu */
.user-menu {
  position: relative;
  cursor: pointer;
}

.user-avatar {
  width: 36px;
  height: 36px;
  background: linear-gradient(135deg, #e74c3c, #f39c12);
  color: white;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-bold);
  overflow: hidden;
  transition: all var(--transition-fast);
}

.user-avatar:hover {
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.user-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-logo-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.user-avatar.large {
  width: 48px;
  height: 48px;
  font-size: var(--font-size-lg);
}

/* Dropdown */
.dropdown-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 240px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  padding: var(--spacing-sm);
  z-index: 200;
  animation: dropdownSlideIn 0.2s ease;
}

@keyframes dropdownSlideIn {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.dropdown-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-md);
}

.user-info {
  display: flex;
  flex-direction: column;
}

.user-info .user-name {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.user-info .user-email {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
  text-decoration: none;
}

.dropdown-item:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

.dropdown-item.danger {
  color: var(--color-error);
}

.dropdown-item.danger:hover {
  background: var(--color-error-light);
}

.dropdown-divider {
  height: 1px;
  background: var(--color-border);
  margin: var(--spacing-xs) 0;
}

/* 遮罩层 */
.menu-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(2px);
  z-index: 190;
  animation: overlayFadeIn 0.2s ease;
}

@keyframes overlayFadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

/* 移动端：按钮集中在右上角 */
@media (max-width: 768px) {
  .desktop-only {
    display: none !important;
  }

  .header-right {
    gap: 2px;
  }

  .dropdown-menu {
    position: fixed;
    top: auto;
    bottom: 0;
    left: 0;
    right: 0;
    min-width: unset;
    max-height: 70vh;
    overflow-y: auto;
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    animation: dropdownSlideUp 0.25s ease;
  }

  @keyframes dropdownSlideUp {
    from { transform: translateY(100%); }
    to { transform: translateY(0); }
  }
}

@media (min-width: 769px) {
  .mobile-only {
    display: none !important;
  }
}
</style>
