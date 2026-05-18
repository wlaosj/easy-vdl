import { ref, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { playerApi } from '@/api/player'
import { tasksApi } from '@/api/tasks'

export function usePlaylist({
  // Video element ref (for minimal video ops in navigation decision logic)
  videoRef,
  // Shared refs (defined in index.vue, shared across composables)
  currentTime,
  streamOffset,
  isPaused,
  // Callbacks from usePlayerGestures
  cancelPendingSlideSwitch,
  isSwitchingMedia,
  // Callbacks from video playback layer (useVideoPlayback or index.vue)
  cleanupVideoConnection,
  markPIPForSourceSwitch,
  stopAudioVisualization,
  initAudioAnalyzer,
  // Called after route-watch updates currentIndex, for video/gallery init
  onRouteVideoSwitch,
}) {
  const route = useRoute()
  const router = useRouter()

  // =========================================================================
  // Constants
  // =========================================================================
  const PLAYER_STORAGE_KEYS = {
    quality: "random_player_quality",
    mode: "random_player_mode",
    speed: "random_player_speed",
    autoplay: "random_player_autoplay",
    backgroundPlay: "random_player_background_play",
    enhance: "random_player_enhance",
    muted: "random_player_muted",
    filterPlatform: "random_player_filter_platform",
    filterScope: "random_player_filter_scope",
    filterAuthor: "random_player_filter_author",
    filterKeyword: "random_player_filter_keyword",
    jumpContext: "random_player_jump_context",
    tripleScreen: "random_player_triple_screen",
  }

  const qualityOptions = [
    { value: "original", label: "原画" },
    { value: "1080p", label: "1080p" },
    { value: "720p", label: "720p" },
    { value: "480p", label: "480p" },
    { value: "360p", label: "360p" },
  ]

  // =========================================================================
  // State — Playlist data
  // =========================================================================
  const playlist = ref([])
  const currentIndex = ref(0)
  const isFetchingVideos = ref(false)
  const isUnmounting = ref(false)

  // Context
  const subscriptionId = ref(route.query.subscription_id || null)
  const subscriptionName = ref("")
  const taskId = ref(route.query.task_id || null)

  // Playback mode
  const playbackMode = ref(
    normalizePlaybackMode(localStorage.getItem(PLAYER_STORAGE_KEYS.mode))
  )
  const autoPlayNext = ref(
    localStorage.getItem(PLAYER_STORAGE_KEYS.autoplay) !== "false"
  )

  // Filters
  const initialFilterPlatform =
    localStorage.getItem(PLAYER_STORAGE_KEYS.filterPlatform) || "all"
  const supportedPlaylistFilterPlatforms = [
    "all",
    "douyin",
    "bilibili",
    "youtube",
    "xiaohongshu",
    "tiktok",
    "instagram",
    "x",
    "netease",
    "others",
  ]
  const playlistFilterPlatform = ref(
    supportedPlaylistFilterPlatforms.includes(initialFilterPlatform)
      ? initialFilterPlatform
      : "all"
  )
  const initialFilterScope =
    localStorage.getItem(PLAYER_STORAGE_KEYS.filterScope) || "all"
  const playlistFilterScope = ref(
    ["all", "manual", "subscription"].includes(initialFilterScope)
      ? initialFilterScope
      : "all"
  )
  const playlistFilterAuthor = ref(
    localStorage.getItem(PLAYER_STORAGE_KEYS.filterAuthor) || "all"
  )
  const playlistFilterKeyword = ref(
    localStorage.getItem(PLAYER_STORAGE_KEYS.filterKeyword) || ""
  )

  // Playback records
  const videoProgressMap = ref({})

  // Gallery thumbnail cache
  const galleryThumbnails = ref({})

  // Internal switch timers
  let switchSequence = 0
  let slideSwitchTimer = null

  // =========================================================================
  // Computed — Current video
  // =========================================================================
  const currentVideo = computed(() => playlist.value[currentIndex.value])
  const currentVideoId = computed(() => currentVideo.value?.id || null)

  // =========================================================================
  // Computed — Media type detection
  // =========================================================================
  const isGallery = computed(() => {
    const typeText = getTaskTypeText(currentVideo.value)
    return (
      typeText.includes("图集") ||
      (currentVideo.value?.filename && currentVideo.value.filename.endsWith("/"))
    )
  })

  const isAudio = computed(() => {
    if (isGallery.value) return false
    const fn = (currentVideo.value?.filename || "").toLowerCase()
    return !!fn.match(/\.(mp3|flac|m4a|wav|aac|ogg)$/)
  })

  const isImage = computed(() => {
    if (isGallery.value) return false
    const fn = (currentVideo.value?.filename || "").toLowerCase()
    return !!fn.match(/\.(jpg|jpeg|png|webp|gif|bmp|avif)$/)
  })

  // =========================================================================
  // Computed — Prev/Next items for preview cards
  // =========================================================================
  const prevVideoItem = computed(() => {
    if (playlist.value.length <= 1) return null
    let idx = currentIndex.value - 1
    if (idx < 0) idx = playlist.value.length - 1
    return playlist.value[idx]
  })

  const nextVideoItem = computed(() => {
    if (playlist.value.length <= 1) return null
    let idx = currentIndex.value + 1
    if (idx >= playlist.value.length) idx = 0
    return playlist.value[idx]
  })

  // =========================================================================
  // Computed — Playback mode meta
  // =========================================================================
  const playbackModeMeta = {
    order: { icon: "repeat", label: "顺序播放" },
    random: { icon: "shuffle", label: "随机播放" },
    single: { icon: "repeat-one", label: "单曲循环" },
  }

  const normalizedPlaybackMode = computed(() =>
    normalizePlaybackMode(playbackMode.value)
  )
  const playbackModeIcon = computed(
    () => playbackModeMeta[normalizedPlaybackMode.value]?.icon || playbackModeMeta.order.icon
  )
  const playbackModeLabel = computed(
    () => playbackModeMeta[normalizedPlaybackMode.value]?.label || playbackModeMeta.order.label
  )

  // =========================================================================
  // Computed — Filtered playlist
  // =========================================================================
  const playlistAuthorOptions = computed(() => {
    const authorSet = new Set()
    for (const video of playlist.value) {
      const author = getVideoAuthorName(video)
      if (author && author !== "未知作者") {
        authorSet.add(author)
      }
    }
    return Array.from(authorSet).sort((a, b) => a.localeCompare(b, "zh-CN"))
  })

  const filteredPlaylist = computed(() => {
    const keyword = (playlistFilterKeyword.value || "").trim().toLowerCase()

    return playlist.value.filter((video) => {
      const platform = getVideoPlatform(video)

      if (playlistFilterPlatform.value !== "all" && platform !== playlistFilterPlatform.value) {
        return false
      }

      if (playlistFilterScope.value === "manual" && !isManualTaskVideo(video)) {
        return false
      }
      if (playlistFilterScope.value === "subscription" && isManualTaskVideo(video)) {
        return false
      }

      if (playlistFilterAuthor.value !== "all") {
        const author = getVideoAuthorName(video)
        if (author !== playlistFilterAuthor.value) {
          return false
        }
      }

      if (keyword) {
        const title = String(video?.title || "").toLowerCase()
        const author = getVideoAuthorName(video).toLowerCase()
        if (!title.includes(keyword) && !author.includes(keyword)) {
          return false
        }
      }

      return true
    })
  })

  // =========================================================================
  // Helper functions
  // =========================================================================
  function getTaskTypeText(task) {
    if (!task) return "未知"
    if (task.task_type_display) {
      return task.task_type_display
    }
    const isSubscription =
      task.subscription_id ||
      (task.filename && task.filename.includes("subscriptions/"))
    const isGalleryType =
      task.url &&
      (task.url.includes("/note/") || task.url.includes("xhslink.com"))
    const authorInfo = task.author_info || {}
    const authorPlatform = (authorInfo.platform || "").toLowerCase()
    const youtubeTabType = (authorInfo.youtube_tab_type || "").toLowerCase()

    if (isSubscription) {
      if (isGalleryType) return "订阅图集"
      if (authorPlatform === "youtube") {
        if (youtubeTabType === "shorts") return "订阅油管短视频"
        return "订阅油管博主"
      }
      if (authorPlatform === "xiaohongshu") return "订阅图集"
      return "订阅任务"
    }

    if (isGalleryType) return "手动图集"
    return "视频下载"
  }

  function isImageFilename(filename) {
    return !!String(filename || "")
      .toLowerCase()
      .match(/\.(jpg|jpeg|png|webp|gif|bmp|avif)$/)
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

  function encodeDownloadPath(path) {
    if (!path) return ""
    return String(path)
      .split("/")
      .filter((p) => p)
      .map((part) => encodeURIComponent(part))
      .join("/")
  }

  function getThumbnailUrl(video) {
    if (!video) return "/static/default_thumbnail.png"

    // 优先使用异步加载的图集缩略图
    if (galleryThumbnails.value[video.id]) {
      return galleryThumbnails.value[video.id]
    }

    if (video.filename && isImageFilename(video.filename)) {
      return `/downloads/${encodeDownloadPath(video.filename)}`
    }

    if (!video.thumbnail) {
      if (video.filename) {
        const base = video.filename.substring(0, video.filename.lastIndexOf("."))
        const lower = (video.filename || "").toLowerCase()
        const isAudioFile = !!lower.match(/\.(mp3|flac|m4a|wav|aac|ogg|opus)$/)
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

    if (video.thumbnail.startsWith("http") || video.thumbnail.startsWith("data:")) {
      return video.thumbnail
    }

    let thumbPath = video.thumbnail
    if (!thumbPath.startsWith("/downloads/")) {
      thumbPath = `/downloads/${thumbPath}`
    }

    return thumbPath
      .split("/")
      .map((segment) => encodeURIComponent(segment))
      .join("/")
  }

  function formatTime(seconds) {
    if (!seconds || !isFinite(seconds) || seconds < 0) return "--:--"
    const totalSec = Math.floor(seconds)
    const h = Math.floor(totalSec / 3600)
    const m = Math.floor((totalSec % 3600) / 60)
    const s = totalSec % 60
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
    }
    return `${m}:${s.toString().padStart(2, "0")}`
  }

  function getVideoPlatform(video) {
    if (!video) return ""
    const source = String(video.source || video.platform || "").toLowerCase()
    const filename = String(video.filename || "").toLowerCase()
    const url = String(video.url || "").toLowerCase()

    if (isNeteaseMusicTask(video) || url.includes("music.163.com")) {
      return "netease"
    }

    if (source === "douyin_collection") {
      return "douyin"
    }
    if (source) {
      return source
    }

    const parts = filename.split("/").filter(Boolean)
    if (parts.length > 0) {
      const rawPlatform =
        parts[0] === "subscriptions" ? parts[1] || "" : parts[0]
      return rawPlatform === "douyin_collection" ? "douyin" : rawPlatform
    }

    return ""
  }

  function getVideoAuthorName(video) {
    return String(video?.author?.nickname || video?.author_name || "").trim()
  }

  function isNeteaseMusicTask(video) {
    if (!video) return false
    const source = String(video.source || video.platform || "").toLowerCase()
    const authorPlatform = String(video?.author_info?.platform || "").toLowerCase()
    const filename = String(video.filename || "").toLowerCase()
    const url = String(video.url || "").toLowerCase()
    const isAudioFile = /\.(mp3|flac|m4a|wav|aac|ogg|opus)$/.test(filename)
    return (
      (source === "netease" ||
        source.includes("netease") ||
        authorPlatform === "netease" ||
        filename.includes("/netease/") ||
        url.includes("music.163.com")) &&
      isAudioFile
    )
  }

  function isManualTaskVideo(video) {
    const subId = video?.subscription_id
    const filename = String(video?.filename || "").toLowerCase()
    if (subId) return false
    return !filename.startsWith("subscriptions/")
  }

  function normalizePlaybackMode(mode) {
    if (mode === "random" || mode === "single") return mode
    if (mode === "order" || mode === "asc" || mode === "desc") return "order"
    return "order"
  }

  function shuffleArray(items = []) {
    const arr = Array.isArray(items) ? [...items] : []
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[arr[i], arr[j]] = [arr[j], arr[i]]
    }
    return arr
  }

  // =========================================================================
  // Jump context (preserve navigation origin across page refreshes)
  // =========================================================================
  function saveJumpContext(taskIdVal, subscriptionIdVal) {
    try {
      localStorage.setItem(
        PLAYER_STORAGE_KEYS.jumpContext,
        JSON.stringify({
          task_id: taskIdVal || null,
          subscription_id: subscriptionIdVal || null,
          saved_at: Date.now(),
        })
      )
    } catch (e) {
      console.warn("保存播放跳转上下文失败:", e)
    }
  }

  function loadJumpContext() {
    try {
      const raw = localStorage.getItem(PLAYER_STORAGE_KEYS.jumpContext)
      if (!raw) return null
      const parsed = JSON.parse(raw)
      if (!parsed || typeof parsed !== "object") return null
      return {
        task_id: parsed.task_id || null,
        subscription_id: parsed.subscription_id || null,
      }
    } catch (e) {
      console.warn("读取播放跳转上下文失败:", e)
      return null
    }
  }

  function clearJumpContext() {
    try {
      localStorage.removeItem(PLAYER_STORAGE_KEYS.jumpContext)
    } catch (e) {
      console.warn("清理播放跳转上下文失败:", e)
    }
  }

  // =========================================================================
  // Filter helpers
  // =========================================================================
  function resetPlaylistFiltersState() {
    playlistFilterPlatform.value = "all"
    playlistFilterScope.value = "all"
    playlistFilterAuthor.value = "all"
    playlistFilterKeyword.value = ""
  }

  async function applyPlaylistFilters() {
    if (taskId.value || subscriptionId.value) return
    await fetchVideos()
    currentIndex.value = 0
  }

  async function resetPlaylistFilters() {
    resetPlaylistFiltersState()
    if (taskId.value || subscriptionId.value) {
      await clearSubscriptionFilter()
      return
    }
    await fetchVideos()
    currentIndex.value = 0
  }

  // =========================================================================
  // Core: fetchVideos
  // =========================================================================
  async function fetchVideos(overrideMode = null, forceShuffle = false) {
    isFetchingVideos.value = true
    try {
      playlist.value = []

      const mode = normalizePlaybackMode(overrideMode || playbackMode.value)
      const backendOrderBy = mode === "random" ? "random" : "asc"

      const isStandaloneFilterMode =
        !subscriptionId.value &&
        !taskId.value &&
        (playlistFilterPlatform.value !== "all" ||
          playlistFilterScope.value !== "all" ||
          playlistFilterAuthor.value !== "all")

      const limit = 1000

      const params = { order_by: backendOrderBy, limit }
      if (subscriptionId.value) {
        params.subscription_id = subscriptionId.value
      } else if (taskId.value) {
        params.task_id = taskId.value
      } else {
        if (playlistFilterPlatform.value !== "all") {
          params.platform = playlistFilterPlatform.value
        }
        if (playlistFilterScope.value === "manual") {
          params.manual_only = 1
        } else if (playlistFilterScope.value === "subscription") {
          params.subscription_only = 1
        }
        if (playlistFilterAuthor.value !== "all") {
          params.author_name = playlistFilterAuthor.value
        }
      }
      const res = await playerApi.getRandomVideos(params)
      let videos = res.videos || []

      if (taskId.value && !subscriptionId.value) {
        const targetVideo = videos.find((video) => String(video.id) === String(taskId.value))
        if (targetVideo) {
          const targetPlatform = getVideoPlatform(targetVideo)
          if (targetPlatform) {
            try {
              const platformRes = await playerApi.getRandomVideos({
                platform: targetPlatform,
                manual_only: 1,
                order_by: backendOrderBy,
                limit: 1000,
              })
              let manualPlatformVideos = (platformRes?.videos || []).filter(
                (video) => isManualTaskVideo(video)
              )
              if (targetPlatform === "netease") {
                manualPlatformVideos = manualPlatformVideos.filter((video) =>
                  isNeteaseMusicTask(video)
                )
              } else {
                manualPlatformVideos = manualPlatformVideos.filter(
                  (video) => getVideoPlatform(video) === targetPlatform
                )
              }
              const sourceList =
                manualPlatformVideos.length > 0
                  ? manualPlatformVideos
                  : [targetVideo]
              const shouldShuffle = forceShuffle || mode === "random"
              playlist.value = shouldShuffle
                ? shuffleArray(sourceList)
                : sourceList
            } catch (e) {
              console.warn(
                `获取平台播放列表失败(${targetPlatform})，降级为本地过滤:`,
                e
              )
              let manualPlatformVideos = videos.filter((video) =>
                isManualTaskVideo(video)
              )
              if (targetPlatform === "netease") {
                manualPlatformVideos = manualPlatformVideos.filter((video) =>
                  isNeteaseMusicTask(video)
                )
              } else {
                manualPlatformVideos = manualPlatformVideos.filter(
                  (video) => getVideoPlatform(video) === targetPlatform
                )
              }
              const sourceList =
                manualPlatformVideos.length > 0
                  ? manualPlatformVideos
                  : [targetVideo]
              const shouldShuffle = forceShuffle || mode === "random"
              playlist.value = shouldShuffle
                ? shuffleArray(sourceList)
                : sourceList
            }
          } else {
            playlist.value = [targetVideo]
          }
        } else {
          playlist.value = []
          console.error(
            `Task ${taskId.value} not found in video list (limit: ${limit})`
          )
        }
      } else {
        const shouldShuffle = forceShuffle || mode === "random"
        playlist.value = shouldShuffle ? shuffleArray(videos) : videos
      }

      setTimeout(() => {
        loadGalleryThumbnails(playlist.value)
      }, 200)

      if (subscriptionId.value && playlist.value.length > 0) {
        const firstVideo = playlist.value[0]
        subscriptionName.value =
          firstVideo?.author?.nickname || firstVideo?.author_name || "此博主"
      }
    } catch (e) {
      console.error("Fetch videos failed", e)
    } finally {
      isFetchingVideos.value = false
    }
  }

  // =========================================================================
  // Gallery thumbnail preloading
  // =========================================================================
  async function loadGalleryThumbnails(videos) {
    const pendingVideos = videos.slice(0, 50).filter((video) => {
      const isGalleryType =
        (video.task_type_display && video.task_type_display.includes("图集")) ||
        (video.filename && video.filename.endsWith("/"))
      return isGalleryType && !galleryThumbnails.value[video.id]
    })

    if (pendingVideos.length === 0) return

    const chunk = (arr, size) =>
      Array.from({ length: Math.ceil(arr.length / size) }, (v, i) =>
        arr.slice(i * size, i * size + size)
      )
    const BATCH_SIZE = 5
    const batches = chunk(pendingVideos, BATCH_SIZE)

    for (const batch of batches) {
      const tasks = batch.map(async (video) => {
        try {
          const parts = (video.filename || "").split("/").filter((p) => p)
          let platform = ""
          let folderPath = ""
          let isSubscription = false

          if (parts[0] === "subscriptions" && parts.length >= 3) {
            isSubscription = true
            platform = parts[1]
            folderPath = parts.slice(2).join("/")
          } else if (parts.length >= 2) {
            platform = parts[0]
            folderPath = parts.slice(1).join("/")
          } else {
            platform = video.author_info?.platform || video.source || "others"
            folderPath = (video.filename || "").replace(/\/$/, "")
          }

          const res = await tasksApi.getGalleryThumbnail({
            platform,
            folder_path: folderPath,
            subscription: isSubscription,
          })

          if (res.success && res.thumbnail_path) {
            galleryThumbnails.value[video.id] = `/downloads/${res.thumbnail_path}`
          }
        } catch (err) {
          // 忽略单个缩略图加载失败
        }
      })

      await Promise.allSettled(tasks)
      await new Promise((resolve) => setTimeout(resolve, 50))
    }
  }

  // =========================================================================
  // Refresh playlist (shuffle mode)
  // =========================================================================
  async function refreshPlaylist() {
    playbackMode.value = "random"
    await fetchVideos("random", true)
    currentIndex.value = 0
  }

  // =========================================================================
  // Subscription filter management
  // =========================================================================
  async function clearSubscriptionFilter() {
    clearJumpContext()
    taskId.value = null
    subscriptionId.value = null
    subscriptionName.value = ""

    playlist.value = []
    currentIndex.value = 0

    await router.replace({ path: "/player", query: {} })
    await fetchVideos()
    currentIndex.value = 0
  }

  // =========================================================================
  // Playback records
  // =========================================================================
  async function loadPlaybackRecord() {
    if (!subscriptionId.value) return null
    try {
      const record = await playerApi.getPlaybackRecord(subscriptionId.value)
      if (record) {
        if (record.playback_mode) {
          playbackMode.value = normalizePlaybackMode(record.playback_mode)
        }
        if (record.video_progress) {
          videoProgressMap.value = record.video_progress
        }
        return record
      }
    } catch (error) {
      console.warn("加载播放记录失败:", error)
    }
    return null
  }

  async function savePlaybackRecord() {
    if (!subscriptionId.value) return
    try {
      const current = currentVideo.value
      if (current && videoRef.value) {
        videoProgressMap.value[current.id] = videoRef.value.currentTime
      }
      const recordData = {
        current_index: currentIndex.value,
        playback_mode: playbackMode.value,
        video_progress: videoProgressMap.value,
      }
      await playerApi.savePlaybackRecord(subscriptionId.value, recordData)
    } catch (error) {
      console.warn("保存播放记录失败:", error)
    }
  }

  function restoreVideoProgress() {
    const current = currentVideo.value
    if (current && videoProgressMap.value[current.id] && videoRef.value) {
      const savedProgress = videoProgressMap.value[current.id]
      if (
        savedProgress > 5 &&
        videoRef.value.duration &&
        savedProgress < videoRef.value.duration - 10
      ) {
        videoRef.value.currentTime = savedProgress
      }
    }
  }

  // =========================================================================
  // Navigation: handleEnded (auto-advance decision)
  // =========================================================================
  function handleEnded() {
    if (isImage.value) return
    if (!autoPlayNext.value) return
    markPIPForSourceSwitch()

    if (playbackMode.value === "single") {
      if (!videoRef.value) return
      streamOffset.value = 0
      videoRef.value.currentTime = 0
      videoRef.value.play().catch(() => {
        isPaused.value = true
      })
      return
    }

    cleanupVideoConnection()
    streamOffset.value = 0

    if (playbackMode.value === "random" && playlist.value.length > 1) {
      let nextIndex = currentIndex.value
      while (nextIndex === currentIndex.value) {
        nextIndex = Math.floor(Math.random() * playlist.value.length)
      }
      currentIndex.value = nextIndex
      return
    }

    if (currentIndex.value < playlist.value.length - 1) {
      currentIndex.value++
    } else {
      currentIndex.value = 0
    }
  }

  // =========================================================================
  // Navigation: playIndex (external coordinator — stays thin)
  // =========================================================================
  // NOTE: playIndex, switchVideo, prevVideo, nextVideo remain in index.vue
  // because they are heavily interleaved with video element operations.
  // They call into this composable's state and functions.

  // =========================================================================
  // Playback mode
  // =========================================================================
  function cyclePlaybackMode() {
    const modeOrder = ["order", "random", "single"]
    const currentPos = modeOrder.indexOf(playbackMode.value)
    const nextPos = currentPos === -1 ? 0 : (currentPos + 1) % modeOrder.length
    playbackMode.value = modeOrder[nextPos]
    localStorage.setItem(PLAYER_STORAGE_KEYS.mode, playbackMode.value)
  }

  // =========================================================================
  // Play author videos
  // =========================================================================
  function playAuthorVideos() {
    const subId = currentVideo.value?.author?.id
    if (subId) {
      if (subscriptionId.value === subId) return
      router.replace({ query: { ...route.query, subscription_id: subId } })
    }
  }

  // =========================================================================
  // Route param watches
  // =========================================================================

  watch(
    () => route.query.task_id,
    async (newVal) => {
      if (route.path !== "/player") return

      if (taskId.value !== newVal) {
        taskId.value = newVal || null

        playlist.value = []
        currentIndex.value = 0

        const currentSubscriptionId = route.query.subscription_id || null
        if (subscriptionId.value !== currentSubscriptionId) {
          subscriptionId.value = currentSubscriptionId
        }

        if (taskId.value || subscriptionId.value) {
          resetPlaylistFiltersState()
          saveJumpContext(taskId.value, subscriptionId.value)
        }

        if (taskId.value) {
          await fetchVideos()
          const targetIndex = playlist.value.findIndex(
            (video) => String(video.id) === String(taskId.value)
          )
          if (targetIndex !== -1) {
            currentIndex.value = targetIndex
            nextTick(() => {
              if (videoRef.value) {
                videoRef.value.play().catch(() => {
                  isPaused.value = true
                })
              } else if (isGallery.value) {
                onRouteVideoSwitch?.()
              }
            })
          }
        } else if (subscriptionId.value) {
          await fetchVideos()
          let targetIndex = 0
          if (videoProgressMap.value) {
            const foundIndex = playlist.value.findIndex((video) => {
              const progress = videoProgressMap.value[video.id]
              return (
                progress > 5 &&
                (!video.duration || progress < video.duration - 10)
              )
            })
            if (foundIndex !== -1) targetIndex = foundIndex
          }
          currentIndex.value = targetIndex
          nextTick(() => {
            if (videoRef.value) {
              videoRef.value.play().catch(() => {
                isPaused.value = true
              })
            } else if (isGallery.value) {
              fetchGalleryFiles(currentVideo.value)
            }
          })
        }
      }
    }
  )

  watch(
    () => route.query.subscription_id,
    async (newVal) => {
      if (route.path !== "/player") return

      if (subscriptionId.value !== newVal) {
        subscriptionId.value = newVal || null

        if (!subscriptionId.value) {
          subscriptionName.value = ""
        }

        const currentTaskId = route.query.task_id || null
        if (taskId.value !== currentTaskId) {
          taskId.value = currentTaskId
        }

        if (taskId.value || subscriptionId.value) {
          resetPlaylistFiltersState()
          saveJumpContext(taskId.value, subscriptionId.value)
        }

        playlist.value = []
        currentIndex.value = 0

        let overrideMode = null
        if (route.query.reset_mode === "1") {
          playbackMode.value = "order"
          overrideMode = "order"
          const url = new URL(window.location.href)
          url.searchParams.delete("reset_mode")
          window.history.replaceState({}, "", url)
        }

        await fetchVideos(overrideMode)

        let targetIndex = 0
        if (overrideMode === "order" && videoProgressMap.value) {
          const foundIndex = playlist.value.findIndex((video) => {
            const progress = videoProgressMap.value[video.id]
            return (
              progress > 5 && (!video.duration || progress < video.duration - 10)
            )
          })
          if (foundIndex !== -1) targetIndex = foundIndex
        }
        currentIndex.value = targetIndex

        if (playlist.value.length > 0) {
          nextTick(() => {
            if (videoRef.value) {
              videoRef.value.play().catch(() => {
                isPaused.value = true
              })
            }
          })
        }
      }
    }
  )

  watch(playbackMode, (val) =>
    localStorage.setItem(PLAYER_STORAGE_KEYS.mode, val)
  )
  watch(autoPlayNext, (val) =>
    localStorage.setItem(PLAYER_STORAGE_KEYS.autoplay, val)
  )
  watch(playlistFilterPlatform, (val) =>
    localStorage.setItem(PLAYER_STORAGE_KEYS.filterPlatform, val)
  )
  watch(playlistFilterScope, (val) =>
    localStorage.setItem(PLAYER_STORAGE_KEYS.filterScope, val)
  )
  watch(playlistFilterAuthor, (val) =>
    localStorage.setItem(PLAYER_STORAGE_KEYS.filterAuthor, val)
  )
  watch(playlistFilterKeyword, (val) =>
    localStorage.setItem(PLAYER_STORAGE_KEYS.filterKeyword, val)
  )

  watch(playlistAuthorOptions, (options) => {
    if (isFetchingVideos.value) return
    if (!options || options.length === 0) return
    if (
      playlistFilterAuthor.value !== "all" &&
      !options.includes(playlistFilterAuthor.value)
    ) {
      playlistFilterAuthor.value = "all"
    }
  })

  // =========================================================================
  // Expose a helper for the slide-switch timer cleanup
  // =========================================================================
  function cancelSlideSwitch() {
    switchSequence++
    if (slideSwitchTimer) {
      clearTimeout(slideSwitchTimer)
      slideSwitchTimer = null
    }
  }

  // =========================================================================
  // Return
  // =========================================================================
  return {
    // Constants
    PLAYER_STORAGE_KEYS,
    qualityOptions,
    // State
    playlist,
    currentIndex,
    subscriptionId,
    subscriptionName,
    taskId,
    playbackMode,
    autoPlayNext,
    playlistFilterPlatform,
    playlistFilterScope,
    playlistFilterAuthor,
    playlistFilterKeyword,
    videoProgressMap,
    isFetchingVideos,
    isUnmounting,
    galleryThumbnails,
    // Computed
    currentVideo,
    currentVideoId,
    isGallery,
    isAudio,
    isImage,
    prevVideoItem,
    nextVideoItem,
    normalizedPlaybackMode,
    playbackModeIcon,
    playbackModeLabel,
    filteredPlaylist,
    playlistAuthorOptions,
    // Helpers
    getThumbnailUrl,
    getTaskTypeText,
    getVideoPlatform,
    getVideoAuthorName,
    isImageFilename,
    encodeDownloadPath,
    isManualTaskVideo,
    isNeteaseMusicTask,
    formatTime,
    normalizePlaybackMode,
    shuffleArray,
    resetPlaylistFiltersState,
    saveJumpContext,
    loadJumpContext,
    clearJumpContext,
    // Methods
    fetchVideos,
    refreshPlaylist,
    applyPlaylistFilters,
    resetPlaylistFilters,
    clearSubscriptionFilter,
    handleEnded,
    cyclePlaybackMode,
    playAuthorVideos,
    loadPlaybackRecord,
    savePlaybackRecord,
    restoreVideoProgress,
    cancelSlideSwitch,
  }
}
