/**
 * Shared GPU utility functions for dashboard and system components.
 */

export function normalizeGpuVendor(value) {
  const text = String(value || '').trim().toLowerCase()
  if (!text) return ''
  if (text.includes('intel')) return 'intel'
  if (text.includes('nvidia')) return 'nvidia'
  if (text.includes('amd')) return 'amd'
  return text
}

export function parseGpuIndex(value) {
  if (value === undefined || value === null || value === '') return null
  const parsed = Number.parseInt(String(value).trim(), 10)
  return Number.isFinite(parsed) ? parsed : null
}

function pickPreferred(list) {
  if (!Array.isArray(list) || list.length === 0) return null
  const ok = list.find((gpu) => String(gpu?.status || '').toLowerCase() === 'ok')
  if (ok) return ok
  const degradedUsable = list.find((gpu) => {
    const status = String(gpu?.status || '').toLowerCase()
    return status === 'degraded' && Boolean(gpu?.transcode_enabled)
  })
  if (degradedUsable) return degradedUsable
  const nonError = list.find((gpu) => String(gpu?.status || '').toLowerCase() !== 'error')
  return nonError || list[0] || null
}

export function pickPrimaryGpu(gpuStatsPayload) {
  const gpuList = Array.isArray(gpuStatsPayload?.gpus) ? gpuStatsPayload.gpus : []
  if (!gpuList.length) return null

  const explicitActive = gpuList.find((gpu) => Boolean(gpu?.is_active))
  if (explicitActive) return explicitActive

  const summary = gpuStatsPayload?.summary || {}
  const activeTranscoder = summary.active_transcoder || {}
  const activeVendor = normalizeGpuVendor(summary.active_vendor || activeTranscoder.vendor)
  const activeHwaccel = String(summary.active_hwaccel || activeTranscoder.hardware || '').trim().toLowerCase()
  const activeGpuIndex = parseGpuIndex(summary.active_gpu_index ?? activeTranscoder.gpu_index)

  if (activeVendor) {
    const sameVendor = gpuList.filter((gpu) => normalizeGpuVendor(gpu?.vendor) === activeVendor)
    if (sameVendor.length > 0) {
      if (activeVendor === 'nvidia' && activeGpuIndex !== null) {
        const exact = sameVendor.find((gpu) => parseGpuIndex(gpu?.index) === activeGpuIndex)
        if (exact) return exact
      }
      return pickPreferred(sameVendor)
    }
  }

  if (activeHwaccel === 'vaapi') {
    const vaapiCapable = gpuList.filter((gpu) => {
      const backends = Array.isArray(gpu?.transcode_backends) ? gpu.transcode_backends : []
      return backends.map((item) => String(item || '').toLowerCase()).includes('vaapi')
    })
    if (vaapiCapable.length > 0) return pickPreferred(vaapiCapable)
  }

  return pickPreferred(gpuList)
}
