<template>
  <div class="layout" :class="{ 'is-mobile': systemStore.isMobile }">
    <!-- 移动端遮罩层 -->
    <div 
      v-if="systemStore.isMobile && systemStore.sidebarOpen" 
      class="sidebar-overlay"
      @click="systemStore.sidebarOpen = false"
    ></div>
    
    <Sidebar />
    <div class="main-wrapper">
      <Header />
      <div class="route-loading-bar" :class="{ visible: isRouteLoading }"></div>
      <main class="main-content" :class="{ 'no-padding': $route.meta.noPadding }">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useSystemStore } from '@/stores/system'
import { useRouteLoadingState } from '@/composables/useRouteLoading'
import Sidebar from './Sidebar.vue'
import Header from './Header.vue'

const systemStore = useSystemStore()
const { isRouteLoading } = useRouteLoadingState()

const checkMobile = () => {
  systemStore.isMobile = window.innerWidth <= 768
  if (!systemStore.isMobile) {
    systemStore.sidebarOpen = false
  }
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})
</script>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  position: relative;
}

.sidebar-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(2px);
  z-index: 9999;
}

.main-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
}

.route-loading-bar {
  position: absolute;
  left: 0;
  right: 0;
  top: 60px;
  height: 2px;
  z-index: 20;
  opacity: 0;
  pointer-events: none;
  background: linear-gradient(90deg, #e74c3c 0%, #f39c12 30%, #f9cb28 60%, #e74c3c 100%);
  background-size: 180% 100%;
  transform: scaleX(0.2);
  transform-origin: 0 50%;
  transition: opacity 0.15s ease;
}

.route-loading-bar.visible {
  opacity: 1;
  animation: route-loading-slide 1.05s ease-in-out infinite;
}

@keyframes route-loading-slide {
  0% { transform: scaleX(0.2); background-position: 140% 0; }
  50% { transform: scaleX(0.7); background-position: 45% 0; }
  100% { transform: scaleX(1); background-position: -20% 0; }
}

.main-content {
  flex: 1;
  padding: var(--spacing-lg);
  overflow-y: auto;
  background: var(--color-bg-primary);
}

.main-content.no-padding {
  padding: 0;
}

@media (max-width: 768px) {
  .layout {
    height: 100vh;
    height: 100dvh;
  }
  .main-content {
    padding: var(--spacing-sm);
    overflow-y: auto;
    height: 100%;
    -webkit-overflow-scrolling: touch;
  }
}

</style>
