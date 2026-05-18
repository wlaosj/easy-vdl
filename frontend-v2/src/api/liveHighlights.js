/**
 * AI 高光切片 API
 */
import client from './client'

export default {
  analyze(recordId, payload = {}) {
    return client.post(`/live/highlights/analyze/${recordId}`, payload)
  },

  analyzeAsync(recordId, payload = {}) {
    return client.post(`/live/highlights/analyze-async/${recordId}`, payload)
  },

  getAnalyzeTask(taskId) {
    return client.get(`/live/highlights/analyze-task/${taskId}`)
  },

  getAnalyzeLatest(recordId) {
    return client.get(`/live/highlights/analyze-task/latest/${recordId}`)
  },

  cancelAnalyze(recordId) {
    return client.post(`/live/highlights/analyze-task/cancel/${recordId}`)
  },

  getResult(recordId) {
    return client.get(`/live/highlights/${recordId}`)
  },

  getDanmuRange(recordId, startSec, endSec, maxEvents = 200) {
    return client.get(`/live/highlights/${recordId}/danmu-range`, {
      params: { start_sec: startSec, end_sec: endSec, max_events: maxEvents }
    })
  },

  getSegmentDanmu(recordId, segmentId) {
    return client.get(`/live/highlights/${recordId}/segment-danmu/${segmentId}`)
  },

  export(recordId, payload = {}) {
    return client.post(`/live/highlights/export/${recordId}`, payload)
  },

  downloadBundle(recordId, payload = {}) {
    return client.post(`/live/highlights/bundle/${recordId}`, payload, {
      responseType: 'blob'
    })
  },

  cleanup(recordId) {
    return client.delete(`/live/highlights/cleanup/${recordId}`)
  },

  cleanupByStreamer(subscriptionId) {
    return client.delete(`/live/highlights/cleanup-streamer/${subscriptionId}`)
  },

  getEligibleStreamers() {
    return client.get('/live/highlights/eligible-streamers')
  },

  getStreamerEligibleRecords(subscriptionId) {
    return client.get(`/live/highlights/eligible-records/${subscriptionId}`)
  },

  manualExport(payload = {}) {
    return client.post('/live/highlights/manual-export', payload)
  },

  manualExportByPath(payload = {}) {
    return client.post('/live/highlights/manual-export-by-path', payload)
  },

  getManualClipsByPath(filePath) {
    return client.post('/live/highlights/manual-clips-by-path', { file_path: filePath })
  },

  deleteManualClipByPath(filePath, clipName) {
    return client.delete(`/live/highlights/manual-clips-by-path/file/${encodeURIComponent(clipName)}`, {
      data: { file_path: filePath }
    })
  },

  cleanupManualClipsByPath(filePath) {
    return client.delete('/live/highlights/manual-clips-by-path', {
      data: { file_path: filePath }
    })
  },

  downloadManualClipByPath(filePath, clipName) {
    return client.post(`/live/highlights/manual-clips-by-path/file/${encodeURIComponent(clipName)}/download`, { file_path: filePath }, {
      responseType: 'blob'
    })
  },

  downloadManualClipsBundleByPath(filePath, clipNames = []) {
    return client.post('/live/highlights/manual-clips-by-path/bundle', {
      file_path: filePath,
      clip_names: clipNames,
    }, {
      responseType: 'blob'
    })
  },

  getManualClips(recordId) {
    return client.get(`/live/highlights/manual-clips/${recordId}`)
  },

  cleanupManualClips(recordId) {
    return client.delete(`/live/highlights/manual-clips/${recordId}`)
  },

  deleteManualClip(recordId, clipName) {
    return client.delete(`/live/highlights/manual-clips/${recordId}/file/${encodeURIComponent(clipName)}`)
  },

  downloadManualClip(recordId, clipName) {
    return client.get(`/live/highlights/manual-clips/${recordId}/file/${encodeURIComponent(clipName)}/download`, {
      responseType: 'blob'
    })
  },

  downloadManualClipsBundle(recordId, payload = {}) {
    return client.post(`/live/highlights/manual-clips/${recordId}/bundle`, payload, {
      responseType: 'blob'
    })
  },

  cleanupStreamerManualClips(subscriptionId) {
    return client.delete(`/live/highlights/manual-clips-streamer/${subscriptionId}`)
  }
}
