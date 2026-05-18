import { ref, computed, watch, nextTick } from 'vue'
import { playerApi } from '@/api/player'
import { tasksApi } from '@/api/tasks'

export function useVideoPlayback({
  // ── Shared refs (defined in index.vue) ──
  isPaused,
  currentTime,
  streamOffset,
  videoRef,
  isTouchDevice,
  showControls,
  isDragging,
  isSwitchingMedia,
  // ── From usePlaylist ──
  currentVideo,
  currentVideoId,
  isGallery,
  isAudio,
  isImage,
  playbackMode,
  autoPlayNext,
  playlist,
  currentIndex,
  getVideoPlatform,
  // ── Template refs ──
  videoContainerRef,
  primaryContentRef,
  galleryAudioRef,
  // ── Callbacks / integration ──
  onEnded,
  onNextVideo,
  onPrevVideo,
  onMediaSwitchEnd,
  onRestoreVideoProgress,
  // ── For PiP restore after source switch ──
  pendingRestorePIP,
}) {
  // =========================================================================
  // State — Playback / UI
  // =========================================================================
  const isPIP = ref(false)
  const isFullscreen = ref(false)
  const rotation = ref(0)

  // 镜像视频源：仅在主视频播放后才赋值，避免镜像各自触发独立转码
  const mirrorSrc = ref('')

  const isVerticalVideo = ref(false)
  const videoAspectRatio = ref(null)
  const duration = ref(0)
  const originalDuration = ref(0)
  const originalVideoInfo = ref({ width: null, height: null, videoBitrate: null, formatBitrate: null })
  const videoMetadataCache = ref({})
  const bufferPercent = ref(0)
  const playbackSpeed = ref(localStorage.getItem("random_player_speed") || "1")
  const currentQuality = ref(localStorage.getItem("random_player_quality") || "720p")
  const isEnhanced = ref(localStorage.getItem("random_player_enhance") === "true")
  const isMuted = ref(localStorage.getItem("random_player_muted") === "true")

  // Triple-screen
  const savedTripleScreenMode =
    localStorage.getItem("random_player_triple_screen") ||
    localStorage.getItem("random_player_triple_screen_mode")
  const tripleScreenMode = ref(parseInt(savedTripleScreenMode ?? "0"))
  if (![0, 3, 4].includes(tripleScreenMode.value)) {
    tripleScreenMode.value = 0
  }
  const tripleLeftRef = ref(null)
  const tripleLeftFarRef = ref(null)
  const tripleRightRef = ref(null)
  let tripleScreenRAF = null

  // Gallery
  const galleryItems = ref([])
  const galleryCurrentIndex = ref(0)
  const galleryBgm = ref(null)
  const autoRotateTimer = ref(null)
  const galleryLoading = ref(false)
  const galleryInterval = computed(() => {
    const speed = parseFloat(playbackSpeed.value) || 1
    return 3000 / speed
  })

  // Audio visualization
  const analyserRef = ref(null)
  let audioContext = null
  let analyser = null
  let sourceNode = null
  let sourceMediaElement = null
  let isAnalyzerInitialized = false

  // Subtitle
  const subtitleOptions = ref([])
  const selectedSubtitleId = ref("off")
  let subtitleFetchToken = 0

  // Control bar visibility timer
  const isControlHovered = ref(false)
  const isControlTouched = ref(false)
  let controlBarTimer = null

  // Force landscape (mobile)
  const isForceLandscape = ref(false)

  // Playlist container height
  const primaryContentHeight = ref(0)
  let primaryContentResizeObserver = null

  // Refresh interval (for encoder status polling)
  let refreshInterval = null

  // =========================================================================
  // Computed — Media source & formatting
  // =========================================================================
  const effectiveDuration = computed(() => {
    if (originalDuration.value && isFinite(originalDuration.value) && originalDuration.value > 0) {
      return originalDuration.value
    }
    if (duration.value && isFinite(duration.value) && duration.value > 0) {
      return duration.value
    }
    return 0
  })

  const playlistContainerHeightStyle = computed(() => {
    if (window.innerWidth <= 1300) return null
    const h = Math.max(0, Math.floor(primaryContentHeight.value || 0))
    return h > 0 ? { height: `${h}px`, maxHeight: `${h}px` } : null
  })

  const videoContainerStyle = computed(() => {
    if (isAudio.value || isGallery.value || isImage.value) return {}
    if (!isVerticalVideo.value) return {}
    const ratio = Number(videoAspectRatio.value)
    if (!isFinite(ratio) || ratio <= 0) return {}
    return { '--video-aspect-ratio': ratio.toString() }
  })

  const showTripleScreen = computed(() => {
    return tripleScreenMode.value > 0 && isVerticalVideo.value && !isAudio.value && !isGallery.value && !isImage.value
  })

  const showCenterPlayButton = computed(
    () => isPaused.value && !isImage.value && !isSwitchingMedia
  )

  const tripleScreenSliderStyle = computed(() => ({
    left: tripleScreenMode.value === 0
      ? "2px"
      : tripleScreenMode.value === 3
        ? "calc(33.33% + 2px)"
        : "calc(66.66% + 2px)",
    width: "calc(33.33% - 4px)",
  }))

  const mediaElementKey = computed(() => {
    const type = isImage.value ? "image" : isAudio.value ? "audio" : "video"
    const video = currentVideo.value || {}
    const mediaId = video.id || video.filename || video.path || `index-${currentIndex.value}`
    const qualityKey = type === "video" ? currentQuality.value : "source"
    const offsetKey = type === "video" && streamOffset.value > 0 ? streamOffset.value.toFixed(3) : "0"
    return `${type}:${mediaId}:${qualityKey}:${offsetKey}`
  })

  const currentCoverUrl = computed(() => {
    if (!currentVideo.value) return "/static/default_thumbnail.png"
    if (isGallery.value && galleryItems.value.length > 0) {
      return galleryItems.value[0].url
    }
    return getThumbnailUrl(currentVideo.value)
  })

  const currentLyricsUrl = computed(() => {
    if (!currentVideo.value || !isAudio.value) return ""
    const rawFilename = currentVideo.value.filename || ""
    if (!rawFilename) return ""
    const lyricsFilename = rawFilename.replace(/\.(mp3|flac|m4a|wav|aac|ogg)$/i, ".lyrics.lrc")
    return `/downloads/${encodeDownloadPath(lyricsFilename)}`
  })

  const currentImageSrc = computed(() => {
    if (!currentVideo.value || !isImage.value) return ""
    return `/downloads/${encodeDownloadPath(currentVideo.value.filename || "")}`
  })

  const subtitleTrackSources = computed(() => {
    const token = localStorage.getItem("token")
    return (subtitleOptions.value || []).map((track) => {
      const encodedPath = encodeURIComponent(track.path || "")
      let src = `/api/video/subtitle/stream?path=${encodedPath}`
      if (token) src += `&token=${encodeURIComponent(token)}`
      return { ...track, src }
    })
  })

  const currentSrc = computed(() => {
    if (!currentVideo.value) return ""
    const rawFilename = currentVideo.value.filename || ""
    const encodedFilename = encodeDownloadPath(rawFilename)

    if (isImage.value) return ""
    if (isAudio.value) return `/downloads/${encodedFilename}`

    let url = `/api/video/stream?filename=${encodedFilename}&quality=${currentQuality.value}`
    const token = localStorage.getItem("token")
    if (token) url += `&token=${token}`
    if (streamOffset.value > 0) url += `&start=${streamOffset.value.toFixed(3)}`
    return url
  })

  const qualityOptionsLabel = computed(() => {
    const found = qualityOptions.find((opt) => opt.value === currentQuality.value)
    return found ? found.label : "画质"
  })

  const formattedCurrentTime = computed(() => {
    if (isGallery.value) return `${galleryCurrentIndex.value + 1}`
    return formatTime(currentTime.value)
  })

  const formattedDuration = computed(() => {
    if (isGallery.value) return `${galleryItems.value.length}`
    return formatTime(effectiveDuration.value)
  })

  const progressPercent = computed(() => {
    if (isGallery.value) {
      if (galleryItems.value.length <= 1) return 0
      return (galleryCurrentIndex.value / (galleryItems.value.length - 1)) * 100
    }
    if (effectiveDuration.value <= 0) return 0
    return Math.min(Math.max((currentTime.value / effectiveDuration.value) * 100, 0), 100)
  })

  const qualityOptions = [
    { value: "original", label: "原画" },
    { value: "1080p", label: "1080p" },
    { value: "720p", label: "720p" },
    { value: "480p", label: "480p" },
    { value: "360p", label: "360p" },
  ]

  // =========================================================================
  // Helpers — local
  // =========================================================================
  function formatTime(seconds) {
    if (!seconds || !isFinite(seconds) || seconds < 0) return "--:--"
    const totalSec = Math.floor(seconds)
    const h = Math.floor(totalSec / 3600)
    const m = Math.floor((totalSec % 3600) / 60)
    const s = totalSec % 60
    if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
    return `${m}:${s.toString().padStart(2, "0")}`
  }

  function encodeDownloadPath(path) {
    if (!path) return ""
    return String(path).split("/").filter((p) => p).map((part) => encodeURIComponent(part)).join("/")
  }

  function isInstagramTask(video) {
    const source = String(video?.source || video?.platform || "").toLowerCase()
    const filename = String(video?.filename || "").toLowerCase()
    return source === "instagram" || filename.includes("subscriptions/instagram/")
  }

  function getParentDownloadPath(filename) {
    const parts = String(filename || "").split("/").filter((p) => p)
    parts.pop()
    return parts.join("/")
  }

  function getThumbnailUrl(video) {
    if (!video) return "/static/default_thumbnail.png"
    if (video.filename && /\.(jpg|jpeg|png|webp|gif|bmp|avif)$/i.test(video.filename)) {
      return `/downloads/${encodeDownloadPath(video.filename)}`
    }
    if (!video.thumbnail) {
      if (video.filename) {
        const base = video.filename.substring(0, video.filename.lastIndexOf("."))
        const isAudioFile = /\.(mp3|flac|m4a|wav|aac|ogg|opus)$/i.test(video.filename)
        if (isInstagramTask(video)) {
          const parentPath = getParentDownloadPath(video.filename)
          if (parentPath) {
            return `/downloads/${encodeDownloadPath(`${parentPath}/poster.jpg`)}`
          }
        }
        const guess = isAudioFile ? `${base}.jpg` : `${base}-poster.jpg`
        return `/downloads/${encodeDownloadPath(guess)}`
      }
      return "/static/default_thumbnail.png"
    }
    if (video.thumbnail.startsWith("http") || video.thumbnail.startsWith("data:")) return video.thumbnail
    let thumbPath = video.thumbnail
    if (!thumbPath.startsWith("/downloads/")) thumbPath = `/downloads/${thumbPath}`
    return thumbPath.split("/").map((s) => encodeURIComponent(s)).join("/")
  }

  // =========================================================================
  // Quality & speed controls
  // =========================================================================
  function cycleQuality() {
    const index = qualityOptions.findIndex((opt) => opt.value === currentQuality.value)
    const nextIndex = (index + 1) % qualityOptions.length
    currentQuality.value = qualityOptions[nextIndex].value
  }

  function cyclePlaybackSpeed() {
    const speeds = ["0.5", "1", "1.25", "1.5", "2.0"]
    const index = speeds.indexOf(playbackSpeed.value)
    const nextIndex = (index + 1) % speeds.length
    playbackSpeed.value = speeds[nextIndex]
  }

  // =========================================================================
  // Force landscape (mobile fullscreen)
  // =========================================================================
  async function toggleForceLandscape() {
    if (!isFullscreen.value) return
    try {
      if (isForceLandscape.value) {
        if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock()
        isForceLandscape.value = false
      } else {
        if (screen.orientation && screen.orientation.lock) {
          await screen.orientation.lock("landscape").catch((err) => console.warn("Orientation lock rejected", err))
          isForceLandscape.value = true
        }
      }
    } catch (err) { console.error("Orientation toggle error:", err) }
  }

  // =========================================================================
  // Video aspect ratio
  // =========================================================================
  function applyVideoAspectBySize(width, height) {
    const vw = Number(width); const vh = Number(height)
    if (!isFinite(vw) || !isFinite(vh) || vw <= 0 || vh <= 0) return false
    isVerticalVideo.value = vh > vw * 1.05
    videoAspectRatio.value = vw / vh
    return true
  }

  function applyVideoAspectFromMeta(meta) {
    if (!meta) return false
    return applyVideoAspectBySize(meta.width, meta.height)
  }

  // =========================================================================
  // Playback controls
  // =========================================================================
  function togglePlay() {
    if (isImage.value) { isPaused.value = true; return }
    if (isGallery.value) {
      isPaused.value = !isPaused.value
      if (!isPaused.value) {
        startAutoRotate()
        nextTick(() => { if (galleryBgm.value && galleryAudioRef.value) galleryAudioRef.value.play().catch(() => {}) })
      } else {
        stopAutoRotate()
        if (galleryBgm.value && galleryAudioRef.value) galleryAudioRef.value.pause()
      }
      return
    }
    if (!videoRef.value) return
    if (videoRef.value.paused) {
      if (isAudio.value) {
        if (!isAnalyzerInitialized) initAudioAnalyzer()
        if (audioContext && audioContext.state === "suspended") {
          audioContext.resume().then(() => { videoRef.value?.play().then(() => { isPaused.value = false }).catch(() => {}) }).catch(() => { videoRef.value?.play().then(() => { isPaused.value = false }).catch(() => {}) })
          return
        }
      }
      videoRef.value.play().then(() => { isPaused.value = false }).catch((err) => console.warn("Play failed", err))
    } else {
      videoRef.value.pause()
      isPaused.value = true
    }
  }

  function toggleMute() {
    isMuted.value = !isMuted.value
    localStorage.setItem("random_player_muted", isMuted.value)
    if (videoRef.value) videoRef.value.muted = isMuted.value
  }

  async function togglePIP() {
    if (!videoRef.value) return
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture()
        isPIP.value = false
        pendingRestorePIP.value = false
      } else {
        await videoRef.value.requestPictureInPicture()
        isPIP.value = true
      }
    } catch (e) { console.error("PiP failed", e) }
  }

  async function toggleFullScreen() {
    const container = videoContainerRef.value
    if (!container) return
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen()
        isFullscreen.value = false
        return
      }
      if (container.requestFullscreen) {
        await container.requestFullscreen()
        isFullscreen.value = true
      }
    } catch (e) { console.error("Fullscreen failed", e) }
  }

  function isVideoInPIP() {
    try {
      return !!(videoRef.value && document.pictureInPictureElement && document.pictureInPictureElement === videoRef.value)
    } catch (e) { return !!isPIP.value }
  }

  function syncFullscreenState() {
    try { isFullscreen.value = !!(document.fullscreenElement || document.webkitFullscreenElement) }
    catch (e) { isFullscreen.value = false }
  }

  function markPIPForSourceSwitch() {
    try {
      pendingRestorePIP.value = !!(videoRef.value && document.pictureInPictureElement && document.pictureInPictureElement === videoRef.value)
    } catch (e) { pendingRestorePIP.value = false }
  }

  function onEnterPIP() { isPIP.value = true }
  function onLeavePIP() { isPIP.value = false; pendingRestorePIP.value = false }

  function nudgeFullscreenVideoLayer() {
    if (!isTouchDevice.value || !isFullscreen.value || !videoContainerRef.value) return
    const el = videoContainerRef.value
    const prev = el.style.transform
    el.style.transform = "translateZ(0.001px)"
    requestAnimationFrame(() => { el.style.transform = prev })
  }

  function handleMediaReady() {
    nudgeFullscreenVideoLayer()
    onMediaSwitchEnd?.()
  }

  // =========================================================================
  // Video event handlers
  // =========================================================================
  const onPlay = () => {
    if (!isFullscreen.value || !isTouchDevice.value) onMediaSwitchEnd?.()
    isPaused.value = false
    if (isAudio.value && audioContext && audioContext.state === "suspended") {
      audioContext.resume().catch((err) => console.warn("恢复 AudioContext 失败:", err))
    }
    if (showTripleScreen.value) {
      // 主视频开始播放后才给镜像赋值 src，避免镜像各自独立触发转码
      if (!mirrorSrc.value) mirrorSrc.value = currentSrc.value
      syncTripleMirrors()
      startTripleScreenLoop()
    }
  }

  const onPause = () => {
    if (isSwitchingMedia.value) return
    isPaused.value = true
    syncTripleMirrors()
    stopTripleScreenLoop()
  }

  const handleTimeUpdate = () => {
    if (!isDragging.value && videoRef.value) {
      currentTime.value = streamOffset.value + videoRef.value.currentTime
    }
  }

  const handleProgress = () => {
    if (videoRef.value && videoRef.value.buffered.length > 0 && effectiveDuration.value > 0) {
      const end = videoRef.value.buffered.end(videoRef.value.buffered.length - 1)
      bufferPercent.value = Math.min(Math.max((end / effectiveDuration.value) * 100, 0), 100)
    }
  }

  const handleLoadedMetadata = async () => {
    if (!videoRef.value) return
    duration.value = videoRef.value.duration
    if (isAudio.value) { isVerticalVideo.value = false; videoAspectRatio.value = null }
    try {
      const vw = videoRef.value.videoWidth; const vh = videoRef.value.videoHeight
      if (vw > 0 && vh > 0) { isVerticalVideo.value = vh > vw * 1.05; videoAspectRatio.value = vw / vh }
      else { videoAspectRatio.value = null }
    } catch (e) { isVerticalVideo.value = false; videoAspectRatio.value = null }
    videoRef.value.playbackRate = parseFloat(playbackSpeed.value)
    videoRef.value.muted = isMuted.value
    if (isEnhanced.value) videoRef.value.classList.add("enhance-on")
    if (isAudio.value) {
      nextTick(() => {
        initAudioAnalyzer()
      })
    }
    if (!isAudio.value) {
      await fetchCurrentVideoMetadata()
      if (currentQuality.value === "original") originalDuration.value = 0
    } else {
      originalDuration.value = 0
      originalVideoInfo.value = { width: null, height: null, videoBitrate: null, formatBitrate: null }
    }
    restoreVideoProgress()
    applySubtitleSelection()
    if (pendingRestorePIP.value && !isAudio.value && !isGallery.value && !document.pictureInPictureElement && videoRef.value) {
      try { await videoRef.value.requestPictureInPicture(); isPIP.value = true } catch (e) { console.debug("恢复小窗播放失败:", e) }
    }
    pendingRestorePIP.value = false
    refreshQualitySuffix()
  }

  // =========================================================================
  // Video metadata
  // =========================================================================
  async function fetchCurrentVideoMetadata() {
    const current = currentVideo.value
    if (!current || !current.filename || isImage.value) return null
    try {
      const cacheKey = current.filename
      let res = videoMetadataCache.value[cacheKey]
      if (!res) { res = await playerApi.getVideoMetadata(cacheKey); if (res) videoMetadataCache.value[cacheKey] = res }
      if (res) {
        const width = Number(res.width); const height = Number(res.height)
        const videoBitrate = Number(res.video_bitrate); const formatBitrate = Number(res.format_bitrate)
        originalVideoInfo.value = {
          width: isFinite(width) && width > 0 ? Math.round(width) : null,
          height: isFinite(height) && height > 0 ? Math.round(height) : null,
          videoBitrate: isFinite(videoBitrate) && videoBitrate > 0 ? Math.round(videoBitrate) : null,
          formatBitrate: isFinite(formatBitrate) && formatBitrate > 0 ? Math.round(formatBitrate) : null,
        }
        if (currentQuality.value !== "original" && res.success && typeof res.duration === "number" && isFinite(res.duration) && res.duration > 0) {
          originalDuration.value = res.duration
        }
      }
      return res
    } catch (error) {
      console.warn("获取视频元数据失败:", error)
      originalVideoInfo.value = { width: null, height: null, videoBitrate: null, formatBitrate: null }
      return null
    }
  }

  function restoreVideoProgress() {
    onRestoreVideoProgress?.()
  }

  // =========================================================================
  // Subtitle
  // =========================================================================
  function applySubtitleSelection() {
    if (!videoRef.value || !videoRef.value.textTracks) return
    const tracks = videoRef.value.textTracks
    const targetId = selectedSubtitleId.value
    for (let i = 0; i < tracks.length; i++) {
      const textTrack = tracks[i]
      const meta = subtitleTrackSources.value[i]
      const shouldShow = targetId !== "off" && meta && String(meta.id) === String(targetId)
      textTrack.mode = shouldShow ? "showing" : "disabled"
    }
  }

  async function fetchCurrentVideoSubtitles() {
    const fetchToken = ++subtitleFetchToken
    const current = currentVideo.value
    if (!current || !current.filename || isAudio.value || isImage.value || isGallery.value) {
      subtitleOptions.value = []; selectedSubtitleId.value = "off"; return
    }
    try {
      const res = await playerApi.getVideoSubtitles(current.filename)
      if (fetchToken !== subtitleFetchToken) return
      const options = (res?.subtitles || []).filter((item) => item && item.path)
      subtitleOptions.value = options
      if (!options.length) { selectedSubtitleId.value = "off"; return }
      const hasCurrent = options.some((item) => String(item.id) === String(selectedSubtitleId.value))
      if (!hasCurrent) {
        const defaultOpt = options.find((item) => item.is_default) || options[0]
        selectedSubtitleId.value = defaultOpt ? String(defaultOpt.id) : "off"
      }
      await nextTick(); applySubtitleSelection()
    } catch (error) {
      if (fetchToken !== subtitleFetchToken) return
      subtitleOptions.value = []; selectedSubtitleId.value = "off"
    }
  }

  // =========================================================================
  // Gallery
  // =========================================================================
  async function fetchGalleryFiles(task) {
    if (!task) return
    galleryLoading.value = true
    galleryItems.value = []; galleryCurrentIndex.value = 0; galleryBgm.value = null
    try {
      const parts = (task.filename || "").split("/").filter((p) => p)
      let platform = ""; let folderPath = ""; let isSubscription = false
      if (parts[0] === "subscriptions" && parts.length >= 3) {
        isSubscription = true; platform = parts[1]; folderPath = parts.slice(2).join("/")
      } else if (parts.length >= 2) {
        platform = parts[0]; folderPath = parts.slice(1).join("/")
      } else {
        platform = task.author_info?.platform || task.source || "others"
        folderPath = (task.filename || "").replace(/\/$/, "")
      }
      const res = await tasksApi.getGalleryFiles({ platform, folder_path: folderPath, subscription: isSubscription })
      if (res.success) {
        galleryItems.value = (res.media_items || []).map((item) => ({ name: item.name, url: item.url, type: item.type }))
        galleryCurrentIndex.value = 0; galleryBgm.value = res.bgm || null
        if (!isPaused.value) {
          startAutoRotate()
          nextTick(() => { if (galleryBgm.value && galleryAudioRef.value) galleryAudioRef.value.play().catch(() => {}) })
        }
      }
    } catch (error) { console.error("获取图集文件失败:", error) }
    finally { galleryLoading.value = false }
  }

  function startAutoRotate() {
    stopAutoRotate()
    if (galleryItems.value.length <= 1) return
    autoRotateTimer.value = setInterval(() => { nextGalleryItem() }, galleryInterval.value)
  }

  function stopAutoRotate() {
    if (autoRotateTimer.value) { clearInterval(autoRotateTimer.value); autoRotateTimer.value = null }
  }

  function nextGalleryItem() {
    if (galleryItems.value.length <= 1) return
    if (galleryCurrentIndex.value < galleryItems.value.length - 1) { galleryCurrentIndex.value++ }
    else { if (autoPlayNext.value) onNextVideo?.(); else galleryCurrentIndex.value = 0 }
  }

  function prevGalleryItem() {
    if (galleryItems.value.length <= 1) return
    if (galleryCurrentIndex.value > 0) { galleryCurrentIndex.value-- }
    else { galleryCurrentIndex.value = galleryItems.value.length - 1 }
  }

  function handleGalleryMediaClick(e) {
    if (window.innerWidth <= 768) return
    nextGalleryItem()
  }

  const onGalleryMediaLoad = (e) => {
    try {
      let vw = 0; let vh = 0
      if (e.target.tagName === "IMG") { vw = e.target.naturalWidth; vh = e.target.naturalHeight }
      else if (e.target.tagName === "VIDEO") { vw = e.target.videoWidth; vh = e.target.videoHeight }
      if (vw > 0 && vh > 0) { isVerticalVideo.value = vh > vw * 1.05; videoAspectRatio.value = vw / vh }
      else { videoAspectRatio.value = null }
    } catch (err) { console.warn("Detect gallery media ratio failed:", err) }
  }

  const onSingleImageLoad = (e) => {
    try {
      const img = e?.target
      applyVideoAspectBySize(img?.naturalWidth, img?.naturalHeight)
    } catch (e2) { isVerticalVideo.value = false; videoAspectRatio.value = null }
    duration.value = 0; currentTime.value = 0; bufferPercent.value = 100; isPaused.value = true
    onMediaSwitchEnd?.()
  }

  // =========================================================================
  // Audio visualization
  // =========================================================================
  function startAudioVisualization() { if (analyser) analyserRef.value = analyser }

  function stopAudioVisualization() {
    if (sourceNode && analyser) { try { sourceNode.disconnect(analyser) } catch (e) {} }
    if (analyser) { try { analyser.disconnect() } catch (e) {}; analyser = null }
    analyserRef.value = null
  }

  function cleanupAudioAnalyzer() { stopAudioVisualization(); isAnalyzerInitialized = false }

  function resetAudioAnalyzer() {
    stopAudioVisualization()
    isAnalyzerInitialized = false
  }

  function ensureAudioAnalyzer() {
    if (!isAnalyzerInitialized) initAudioAnalyzer()
  }

  function initAudioAnalyzer() {
    if (!videoRef.value || !isAudio.value) return
    if (isAnalyzerInitialized && analyser && audioContext && audioContext.state !== "closed") {
      startAudioVisualization(); return
    }
    try {
      stopAudioVisualization()
      if (!audioContext || audioContext.state === "closed") audioContext = new (window.AudioContext || window.webkitAudioContext)()
      if (sourceMediaElement && sourceMediaElement !== videoRef.value) {
        try { sourceNode?.disconnect() } catch (e) {}; sourceNode = null; sourceMediaElement = null
      }
      if (!sourceNode) {
        try { sourceNode = audioContext.createMediaElementSource(videoRef.value); sourceMediaElement = videoRef.value }
        catch (error) { console.warn("MediaElementSource 创建失败:", error) }
      }
      if (!analyser) { analyser = audioContext.createAnalyser(); analyser.fftSize = 64; analyser.smoothingTimeConstant = 0.8 }
      if (sourceNode && analyser) {
        try {
          try { sourceNode.disconnect() } catch (e) {}
          try { analyser.disconnect() } catch (e) {}
          sourceNode.connect(analyser); analyser.connect(audioContext.destination)
        } catch (e) {
          try { sourceNode.connect(audioContext.destination) } catch (e2) {}
        }
      }
      if (audioContext.state === "suspended") audioContext.resume().catch(() => {})
      isAnalyzerInitialized = true
      startAudioVisualization()
    } catch (error) {
      console.warn("初始化音频分析器失败:", error); isAnalyzerInitialized = false; stopAudioVisualization()
    }
  }

  // =========================================================================
  // Triple screen
  // =========================================================================
  function syncTripleMirrors() {
    if (!showTripleScreen.value) return
    const main = videoRef.value; const left = tripleLeftRef.value; const right = tripleRightRef.value
    if (!main) return
    const mirrors = [tripleLeftFarRef.value, left, right].filter(Boolean)
    for (const m of mirrors) {
      if (m.playbackRate !== main.playbackRate) m.playbackRate = main.playbackRate
      if (Math.abs(m.currentTime - main.currentTime) > 0.15) m.currentTime = main.currentTime
      if (!main.paused && m.paused) m.play().catch(() => {})
      if (main.paused && !m.paused) m.pause()
    }
  }

  function startTripleScreenLoop() {
    if (tripleScreenRAF) return
    const loop = () => { syncTripleMirrors(); tripleScreenRAF = requestAnimationFrame(loop) }
    tripleScreenRAF = requestAnimationFrame(loop)
  }

  function stopTripleScreenLoop() {
    if (tripleScreenRAF) { cancelAnimationFrame(tripleScreenRAF); tripleScreenRAF = null }
  }

  // =========================================================================
  // Control bar visibility
  // =========================================================================
  function resetTimer() {
    if (controlBarTimer) clearTimeout(controlBarTimer)
    controlBarTimer = setTimeout(() => {
      if (!isPaused.value && !isControlHovered.value && !isControlTouched.value) showControls.value = false
    }, 3000)
  }

  const onMouseMove = (e) => {
    if (!window.matchMedia("(hover: hover)").matches) return
    if (isFullscreen.value && e?.clientY !== undefined) {
      const height = videoContainerRef.value?.offsetHeight || window.innerHeight
      if (e.clientY > height - 140) { showControls.value = true; resetTimer() }
      else { if (!isPaused.value && !isControlHovered.value) showControls.value = false }
      return
    }
    if (!isFullscreen.value) { showControls.value = true; resetTimer() }
  }

  const handleControlMouseEnter = () => {
    if (!window.matchMedia("(hover: hover)").matches) return
    isControlHovered.value = true; showControls.value = true
    if (controlBarTimer) clearTimeout(controlBarTimer)
  }

  const handleControlMouseLeave = () => {
    isControlHovered.value = false
    if (isFullscreen.value && !isTouchDevice.value) showControls.value = false
    else resetTimer()
  }

  const handleControlTouchStart = () => {
    isControlTouched.value = true; showControls.value = true
    if (controlBarTimer) clearTimeout(controlBarTimer)
  }

  const handleControlTouchEnd = () => {
    isControlTouched.value = false; resetTimer()
  }

  // =========================================================================
  // Transcoded seek
  // =========================================================================
  function startTranscodedSeek(targetTime) {
    const current = currentVideo.value
    if (!current || !current.filename || !videoRef.value) return
    const wasPlaying = !videoRef.value.paused
    streamOffset.value = Math.max(targetTime, 0)
    bufferPercent.value = 0
    nextTick(() => {
      if (!videoRef.value) return
      videoRef.value.load()
      if (wasPlaying) videoRef.value.play().catch(() => {})
    })
  }

  // =========================================================================
  // Cleanup video connection (disconnect transcoding process)
  // =========================================================================
  function cleanupVideoConnection() {
    if (videoRef.value && (currentQuality.value !== "original" || isAudio.value)) {
      try {
        videoRef.value.pause()
        if (videoRef.value.src) videoRef.value.src = ""
      } catch (e) { console.debug("清理视频连接时出错:", e) }
    }
    if (isAudio.value) { stopAudioVisualization(); isAnalyzerInitialized = false }
  }

  // =========================================================================
  // Layout
  // =========================================================================
  function syncPlaylistContainerHeight() {
    const el = primaryContentRef.value
    if (!el) return
    primaryContentHeight.value = el.offsetHeight || 0
  }

  // =========================================================================
  // Refresh quality suffix (encoder status polling helper)
  // =========================================================================
  async function refreshQualitySuffix() {
    try {
      const res = await playerApi.getEncoderStatus()
      return res || {}
    } catch (error) { return {} }
  }

  // =========================================================================
  // Watches
  // =========================================================================
  // Save playback settings to localStorage
  watch(currentQuality, (val) => localStorage.setItem("random_player_quality", val))
  watch(playbackSpeed, (val) => {
    localStorage.setItem("random_player_speed", val)
    if (videoRef.value) {
      videoRef.value.playbackRate = parseFloat(val)
    }
  })
  watch(isEnhanced, (val) => localStorage.setItem("random_player_enhance", val))
  watch(tripleScreenMode, (val) => localStorage.setItem("random_player_triple_screen", String(val)))

  // Triple-screen on/off
  watch(showTripleScreen, (active) => {
    if (active) { nextTick(() => { syncTripleMirrors(); if (!isPaused.value) startTripleScreenLoop() }) }
    else stopTripleScreenLoop()
  })

  // Audio mode → init/cleanup audio analyzer
  watch(isAudio, (audioMode) => {
    if (audioMode) {
      isVerticalVideo.value = false; videoAspectRatio.value = null
      cleanupAudioAnalyzer()
      nextTick(() => {
        if (videoRef.value && videoRef.value.readyState >= 2) initAudioAnalyzer()
        else {
          const handler = () => { initAudioAnalyzer(); videoRef.value?.removeEventListener("loadedmetadata", handler) }
          videoRef.value?.addEventListener("loadedmetadata", handler)
        }
      })
    } else {
      cleanupAudioAnalyzer(); sourceMediaElement = null; sourceNode = null
    }
  }, { immediate: true })

  // Source change → re-init audio analyzer
  watch(() => currentSrc.value, () => {
    if (isAudio.value) {
      stopAudioVisualization(); isAnalyzerInitialized = false
      nextTick(() => { if (videoRef.value) initAudioAnalyzer() })
    } else { cleanupAudioAnalyzer() }
  })

  // Current video change → reset video-level state
  watch(() => currentVideo.value, (newVideo, oldVideo) => {
    mirrorSrc.value = ''
    originalVideoInfo.value = { width: null, height: null, videoBitrate: null, formatBitrate: null }
    if (!newVideo) {
      isVerticalVideo.value = false; videoAspectRatio.value = null
      subtitleOptions.value = []; selectedSubtitleId.value = "off"
    } else if (isAudio.value || isImage.value) {
      isVerticalVideo.value = false; videoAspectRatio.value = null
      subtitleOptions.value = []; selectedSubtitleId.value = "off"
    } else if (!isGallery.value) {
      const cacheKey = newVideo.filename || ""
      const cachedMeta = cacheKey ? videoMetadataCache.value[cacheKey] : null
      if (!applyVideoAspectFromMeta(cachedMeta)) applyVideoAspectFromMeta(newVideo)
      fetchCurrentVideoSubtitles()
    } else {
      subtitleOptions.value = []; selectedSubtitleId.value = "off"
    }
    if (!oldVideo) return
    if (newVideo && isGallery.value) fetchGalleryFiles(newVideo)
    else { galleryItems.value = []; galleryCurrentIndex.value = 0; stopAutoRotate() }
  })

  // Fullscreen → clear force-landscape
  watch(isFullscreen, (val) => {
    if (!val && isForceLandscape.value) {
      if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock()
      isForceLandscape.value = false
    }
  })

  // Subtitle selection → apply
  watch(selectedSubtitleId, () => { nextTick(() => applySubtitleSelection()) })
  watch(() => subtitleTrackSources.value.map((item) => `${item.id}:${item.src}`).join("|"), () => { nextTick(() => applySubtitleSelection()) })

  // Sync container height when media changes
  watch([currentVideoId, isAudio, isImage, isGallery], () => { nextTick(syncPlaylistContainerHeight) }, { flush: "post" })

  // =========================================================================
  // Lifecycle helpers (called from index.vue)
  // =========================================================================
  function setupResizeObserver() {
    window.addEventListener("resize", syncPlaylistContainerHeight)
    nextTick(syncPlaylistContainerHeight)
    if (primaryContentRef.value && typeof ResizeObserver !== "undefined") {
      primaryContentResizeObserver = new ResizeObserver(() => { syncPlaylistContainerHeight() })
      primaryContentResizeObserver.observe(primaryContentRef.value)
    }
  }

  function cleanupResizeObserver() {
    window.removeEventListener("resize", syncPlaylistContainerHeight)
    if (primaryContentResizeObserver) { primaryContentResizeObserver.disconnect(); primaryContentResizeObserver = null }
  }

  function cleanupAllVideoResources(keepPlayingByPIP) {
    if (videoRef.value && !keepPlayingByPIP) {
      try { videoRef.value.pause(); videoRef.value.src = ""; videoRef.value.load() } catch (e) { console.debug("清理视频资源时出错:", e) }
    }
    if (!keepPlayingByPIP && document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {})
  }

  function cleanup() {
    stopTripleScreenLoop()
    cleanupAudioAnalyzer()
    cleanupResizeObserver()
  }

  // =========================================================================
  // Return
  // =========================================================================
  return {
    // State
    isPIP, isFullscreen, rotation, isVerticalVideo, videoAspectRatio,
    duration, originalDuration, originalVideoInfo, videoMetadataCache,
    bufferPercent, playbackSpeed, currentQuality, isEnhanced, isMuted,
    mirrorSrc,
    tripleScreenMode, tripleLeftRef, tripleLeftFarRef, tripleRightRef,
    galleryItems, galleryCurrentIndex, galleryBgm, galleryAudioRef,
    autoRotateTimer, galleryLoading, galleryInterval,
    analyserRef,
    subtitleOptions, selectedSubtitleId,
    isControlHovered, isControlTouched,
    isForceLandscape,
    primaryContentHeight,
    // Computed
    effectiveDuration, playlistContainerHeightStyle, videoContainerStyle,
    showTripleScreen, showCenterPlayButton, tripleScreenSliderStyle,
    mediaElementKey, currentCoverUrl, currentLyricsUrl, currentImageSrc,
    subtitleTrackSources, currentSrc,
    qualityOptions, qualityOptionsLabel,
    formattedCurrentTime, formattedDuration, progressPercent,
    // Methods — playback
    togglePlay, toggleMute, togglePIP, toggleFullScreen,
    cycleQuality, cyclePlaybackSpeed, toggleForceLandscape,
    shouldForceMediaReload: () => isAudio.value || (isTouchDevice.value && isFullscreen.value),
    // Methods — video events
    onPlay, onPause, handleTimeUpdate, handleProgress, handleLoadedMetadata,
    handleMediaReady, onEnterPIP, onLeavePIP,
    onSingleImageLoad, onGalleryMediaLoad,
    // Methods — gallery
    fetchGalleryFiles, startAutoRotate, stopAutoRotate,
    nextGalleryItem, prevGalleryItem, handleGalleryMediaClick,
    // Methods — audio visualization
    startAudioVisualization, stopAudioVisualization,
    cleanupAudioAnalyzer, initAudioAnalyzer, resetAudioAnalyzer, ensureAudioAnalyzer,
    // Methods — subtitle
    fetchCurrentVideoSubtitles, applySubtitleSelection,
    // Methods — triple screen
    syncTripleMirrors, startTripleScreenLoop, stopTripleScreenLoop,
    // Methods — metadata
    fetchCurrentVideoMetadata,
    // Methods — seek & connection
    startTranscodedSeek, cleanupVideoConnection,
    // Methods — control bar
    onMouseMove, handleControlMouseEnter, handleControlMouseLeave,
    handleControlTouchStart, handleControlTouchEnd, resetTimer,
    // Methods — fullscreen / PIP
    syncFullscreenState, markPIPForSourceSwitch, nudgeFullscreenVideoLayer, isVideoInPIP,
    // Methods — layout
    syncPlaylistContainerHeight,
    // Methods — encoder status
    refreshQualitySuffix,
    // Lifecycle helpers
    setupResizeObserver, cleanupResizeObserver,
    cleanupAllVideoResources, cleanup,
    // Internal helpers (needed externally)
    applyVideoAspectBySize,
  }
}
