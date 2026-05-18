/**
 * Shared utility functions for the dashboard components.
 */

/**
 * Format bytes into human-readable string (decimal, k=1000).
 */
export function formatBytes(bytes, decimals = 2) {
  if (bytes === 0) return '0 B'
  const k = 1000
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i]
}

/**
 * Format bytes with configurable binary/decimal unit mode.
 */
export function formatBytesWithMode(bytes, unitMode, decimals = 2) {
  if (bytes === 0) return '0 B'
  const k = unitMode === 'binary' ? 1024 : 1000
  const dm = decimals < 0 ? 0 : decimals
  const sizes = unitMode === 'binary'
    ? ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB']
    : ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i]
}

/**
 * Format uptime seconds into human-readable string.
 */
export function formatUptime(seconds) {
  if (!seconds || seconds === 0) return '0分钟'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const parts = []
  if (days > 0) parts.push(`${days}天`)
  if (hours > 0) parts.push(`${hours}小时`)
  if (minutes > 0 || parts.length === 0) parts.push(`${minutes}分钟`)
  return parts.join('')
}

/**
 * Format bps speed into human-readable string.
 */
export function formatSpeed(bps) {
  if (!bps || isNaN(bps) || bps === null || bps === undefined) return '0 B/s'
  if (bps === 0) return '0 B/s'
  if (bps < 1024) return bps.toFixed(0) + ' B/s'
  if (bps < 1024 * 1024) return (bps / 1024).toFixed(1) + ' KB/s'
  return (bps / (1024 * 1024)).toFixed(2) + ' MB/s'
}

/**
 * Returns a CSS class name based on usage percentage.
 */
export function getUsageClass(usage) {
  if (usage > 90) return 'usage-critical'
  if (usage > 75) return 'usage-warning'
  if (usage > 60) return 'usage-caution'
  return 'usage-normal'
}

/**
 * Get database pool capacity display string.
 */
export function getPoolCapacity(db) {
  if (!db) return '加载中...'
  const current = (db.checked_out || 0) + (db.checked_in || 0)
  if (db.pool_size !== undefined && db.max_overflow !== undefined) {
    const max = db.pool_size + db.max_overflow
    return `${current}/${max}`
  }
  return `${current}/?`
}

/**
 * Get database pool info text.
 */
export function getPoolInfoText(db) {
  if (!db) return '等待数据加载...'
  const current = (db.checked_out || 0) + (db.checked_in || 0)
  const parts = []
  parts.push(`实际创建连接: ${current}`)
  if (db.pool_size !== undefined && db.max_overflow !== undefined) {
    parts.push(`池配置: ${db.pool_size}+${db.max_overflow}`)
  }
  if (db.total_connections !== undefined && db.total_connections > 0) {
    const diff = current - db.total_connections
    if (diff > 0) {
      parts.push(`已回收: ${diff}个连接`)
    }
  }
  return parts.join(' | ')
}

/**
 * Get memory usage percentage.
 */
export function getMemoryUsagePercent(memoryMB, memoryLimitMB) {
  const mem = memoryMB || 0
  const total = memoryLimitMB || 2048
  return Math.round((mem / total) * 100)
}
