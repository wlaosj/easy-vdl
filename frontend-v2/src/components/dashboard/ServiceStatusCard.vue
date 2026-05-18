<template>
  <div class="card status-card service-horizontal">
    <div class="supervisor-list-horizontal">
      <div v-if="!services.length" class="text-xs text-gray-500 text-center py-2 w-full">
        暂无数据
      </div>
      <div v-for="svc in services" :key="svc.name" class="supervisor-chip" :class="svc.state.toLowerCase()">
        <div class="chip-dot" :class="svc.state.toLowerCase()"></div>
        <span class="chip-name">{{ getServiceName(svc.name) }}</span>
        <span class="chip-status" v-if="svc.state !== 'RUNNING'">{{ svc.state }}</span>
      </div>
      
      <div class="network-status-divider"></div>
      <div
        v-for="site in networkStatus"
        :key="site.name"
        class="network-chip"
        :class="getNetworkClass(site)"
        :title="getNetworkTooltip(site)"
      >
        <div class="network-icon">{{ site.icon }}</div>
        <span class="network-name">{{ site.label }}</span>
        <span class="network-latency" v-if="site.status === 'ok'">{{ site.latency_ms }}ms</span>
        <span class="network-status-text" v-else>{{ getNetworkStatusText(site.status) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  services: {
    type: Array,
    default: () => []
  },
  networkStatus: {
    type: Array,
    default: () => []
  }
})

function getServiceName(name) {
  const map = {
    'easy-vdl-unified-service': '主程序',
    'filebrowser': '文件管理',
    'fluxbox': '窗口管理',
    'nginx': 'Web服务',
    'postgresql': '数据库',
    'websockify': 'VNC代理',
    'x11vnc': '远程桌面',
    'xvfb': '虚拟显卡'
  }
  return map[name] || name.replace('easy-vdl-', '')
}

function getNetworkClass(site) {
  if (site.status === 'ok') {
    if (site.latency_ms < 200) return 'network-good'
    if (site.latency_ms < 1000) return 'network-slow'
    return 'network-very-slow'
  }
  if (site.status === 'checking') return 'network-checking'
  if (site.status === 'timeout') return 'network-timeout'
  return 'network-failed'
}

function getNetworkStatusText(status) {
  const map = {
    'checking': '检测中',
    'timeout': '超时',
    'failed': '失败',
    'error': '错误'
  }
  return map[status] || status
}

function getNetworkTooltip(site) {
  if (site.status === 'ok') {
    return `${site.label} 连接正常 (${site.latency_ms}ms)`
  }
  if (site.message) {
    return `${site.label}: ${site.message}`
  }
  return `${site.label}: ${getNetworkStatusText(site.status)}`
}
</script>

<style scoped>
.service-horizontal {
  padding: 12px 16px !important;
}

.supervisor-list-horizontal {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 5px;
}

.supervisor-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--color-bg-tertiary);
  border-radius: 20px;
  border: 1px solid var(--color-border);
  font-size: 12px;
  transition: all 0.2s;
}

.supervisor-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
}

.chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #bdc3c7;
}

.chip-name {
  color: var(--color-text-primary);
  font-weight: 500;
}

.chip-status {
  font-size: 10px;
  font-weight: bold;
  opacity: 0.8;
  margin-left: 2px;
}

.chip-dot.running {
  background: #27ae60;
  box-shadow: 0 0 4px #27ae60;
}

.chip-dot.fatal,
.chip-dot.stopped,
.chip-dot.backoff {
  background: #e74c3c;
  box-shadow: 0 0 4px #e74c3c;
}

.chip-dot.starting {
  background: #f39c12;
  box-shadow: 0 0 4px #f39c12;
}

.supervisor-chip.fatal,
.supervisor-chip.stopped,
.supervisor-chip.backoff {
  background: rgba(231, 76, 60, 0.1);
  border-color: rgba(231, 76, 60, 0.3);
}

.supervisor-chip.fatal .chip-name,
.supervisor-chip.stopped .chip-name {
  color: #c0392b;
}

.supervisor-chip.starting {
  background: rgba(243, 156, 18, 0.1);
  border-color: rgba(243, 156, 18, 0.3);
}

.network-status-divider {
  width: 1px;
  height: 24px;
  background: var(--color-border);
  margin: 0 4px;
}

.network-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--color-bg-tertiary);
  border-radius: 20px;
  border: 1px solid var(--color-border);
  font-size: 12px;
  transition: all 0.2s;
  cursor: help;
}

.network-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
}

.network-icon {
  font-size: 14px;
  line-height: 1;
}

.network-name {
  color: var(--color-text-primary);
  font-weight: 500;
}

.network-latency {
  font-size: 10px;
  font-weight: bold;
  font-family: monospace;
  opacity: 0.8;
}

.network-status-text {
  font-size: 10px;
  font-weight: bold;
  opacity: 0.8;
}

.network-chip.network-good {
  background: rgba(39, 174, 96, 0.1);
  border-color: rgba(39, 174, 96, 0.3);
}

.network-chip.network-good .network-icon {
  filter: drop-shadow(0 0 2px #27ae60);
}

.network-chip.network-good .network-latency {
  color: #27ae60;
}

.network-chip.network-slow {
  background: rgba(243, 156, 18, 0.1);
  border-color: rgba(243, 156, 18, 0.3);
}

.network-chip.network-slow .network-latency {
  color: #f39c12;
}

.network-chip.network-very-slow {
  background: rgba(230, 126, 34, 0.1);
  border-color: rgba(230, 126, 34, 0.3);
}

.network-chip.network-very-slow .network-latency {
  color: #e67e22;
}

.network-chip.network-failed,
.network-chip.network-timeout {
  background: rgba(231, 76, 60, 0.1);
  border-color: rgba(231, 76, 60, 0.3);
}

.network-chip.network-failed .network-status-text {
  color: #e74c3c;
}

.network-chip.network-checking {
  background: rgba(52, 152, 219, 0.1);
  border-color: rgba(52, 152, 219, 0.3);
  animation: network-pulse 1.5s ease-in-out infinite;
}

.network-chip.network-checking .network-status-text {
  color: #3498db;
}

@keyframes network-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.text-xs {
  font-size: 12px;
}

.text-gray-500 {
  color: var(--color-text-tertiary);
}
</style>