import { nextTick } from 'vue'

const BG_MEDIA_KEY = "__EASY_VDL_BG_MEDIA__";
const BG_STATE_KEY = "__EASY_VDL_BG_MEDIA_STATE__";

/**
 * 后台音频播放桥接接管 Composable
 */
export function useBackgroundBridge({
  enableBackgroundPlay,
  autoPlayNext,
  playlist,
  currentIndex,
  playbackMode,
  playbackSpeed,
  currentSrc,
  isMuted,
  streamOffset,
  videoRef,
  isGallery,
  galleryAudioRef,
  galleryBgm,
  isPaused,
  currentTime,
  currentQuality,
  // 回调方法
  stopAutoRotate,
  startAutoRotate,
  startTranscodedSeek,
  syncTripleMirrors
}) {

  const getGlobalBgMedia = () => {
    try {
      return window[BG_MEDIA_KEY] || null;
    } catch (e) {
      return null;
    }
  };

  const setGlobalBgMedia = (media) => {
    try {
      window[BG_MEDIA_KEY] = media || null;
    } catch (e) {}
  };

  const getGlobalBgState = () => {
    try {
      return window[BG_STATE_KEY] || null;
    } catch (e) {
      return null;
    }
  };

  const setGlobalBgState = (state) => {
    try {
      window[BG_STATE_KEY] = state || null;
    } catch (e) {}
  };

  const getNextIndexByMode = () => {
    if (!Array.isArray(playlist.value) || playlist.value.length === 0) return -1;
    if (playbackMode.value === "random" && playlist.value.length > 1) {
      let nextIndex = currentIndex.value;
      while (nextIndex === currentIndex.value) {
        nextIndex = Math.floor(Math.random() * playlist.value.length);
      }
      return nextIndex;
    }
    if (currentIndex.value < playlist.value.length - 1) {
      return currentIndex.value + 1;
    }
    return 0;
  };

  const fadeMediaVolume = (media, from, to, duration = 140) => {
    if (!media || typeof media.volume !== "number") return Promise.resolve();
    if (duration <= 0 || from === to) {
      try {
        media.volume = to;
      } catch (e) {}
      return Promise.resolve();
    }

    const start = performance.now();
    return new Promise((resolve) => {
      const step = (now) => {
        const p = Math.min((now - start) / duration, 1);
        const v = from + (to - from) * p;
        try {
          media.volume = Math.max(0, Math.min(1, v));
        } catch (e) {}
        if (p < 1) requestAnimationFrame(step);
        else resolve();
      };
      requestAnimationFrame(step);
    });
  };

  const stopGlobalBgMedia = () => {
    const bg = getGlobalBgMedia();
    if (bg) {
      try {
        bg.pause();
      } catch (e) {}
      try {
        bg.src = "";
      } catch (e) {}
    }
    setGlobalBgMedia(null);
    setGlobalBgState(null);
  };

  const attachBackgroundVideoEndedHandler = (bg) => {
    if (!bg) return;
    bg.addEventListener("ended", async () => {
      if (getGlobalBgMedia() !== bg) return;
      if (!enableBackgroundPlay.value) {
        stopGlobalBgMedia();
        return;
      }
      if (!autoPlayNext.value) {
        stopGlobalBgMedia();
        return;
      }
      if (!playlist.value.length) {
        stopGlobalBgMedia();
        return;
      }

      const nextIndex = getNextIndexByMode();
      if (nextIndex < 0) {
        stopGlobalBgMedia();
        return;
      }

      currentIndex.value = nextIndex;
      streamOffset.value = 0;
      await nextTick();

      const nextSrc = currentSrc.value;
      if (!nextSrc) {
        stopGlobalBgMedia();
        return;
      }

      const nextBg = new Audio(nextSrc);
      const nextTargetVolume = isMuted.value ? 0 : 1;
      nextBg.loop = playbackMode.value === "single";
      nextBg.muted = false;
      nextBg.playbackRate = parseFloat(playbackSpeed.value || "1") || 1;
      try {
        nextBg.volume = 0;
      } catch (e) {}
      attachBackgroundVideoEndedHandler(nextBg);

      try {
        await nextBg.play();
        await Promise.all([
          fadeMediaVolume(nextBg, 0, nextTargetVolume, 140),
          fadeMediaVolume(
            bg,
            typeof bg.volume === "number" ? bg.volume : 1,
            0,
            140
          ),
        ]);
        try {
          bg.pause();
        } catch (e) {}
        try {
          bg.src = "";
        } catch (e) {}
        setGlobalBgMedia(nextBg);
        setGlobalBgState({ type: "video", wasPlaying: true });
      } catch (e) {
        stopGlobalBgMedia();
      }
    });
  };

  const smoothTakeoverToBackground = async (bg, foreground) => {
    const bgTarget = isMuted.value ? 0 : 1;
    try {
      bg.volume = 0;
    } catch (e) {}
    await bg.play();

    // 先让后台音频淡入，再停前台，避免硬切换爆音。
    await fadeMediaVolume(bg, 0, bgTarget, 120);
    if (foreground) {
      try {
        foreground.pause();
      } catch (e) {}
    }
  };

  const startBackgroundBridgePlayback = async () => {
    if (!enableBackgroundPlay.value) return;
    if (getGlobalBgMedia()) {
      // 已有后台桥接实例时，确保前台源不再继续发声，避免双声道叠加。
      if (isGallery.value) {
        stopAutoRotate();
        if (galleryAudioRef.value) {
          try {
            galleryAudioRef.value.pause();
          } catch (e) {}
        }
        isPaused.value = true;
      } else if (videoRef.value && !videoRef.value.paused) {
        try {
          videoRef.value.pause();
        } catch (e) {}
        isPaused.value = true;
      }
      return;
    }

    if (
      isGallery.value &&
      galleryAudioRef.value &&
      !galleryAudioRef.value.paused &&
      galleryBgm.value?.url
    ) {
      const bg = new Audio(galleryBgm.value.url);
      bg.loop = true;
      bg.muted = false;
      bg.playbackRate = parseFloat(playbackSpeed.value || "1") || 1;
      const t = galleryAudioRef.value.currentTime || 0;
      if (t > 0) {
        try {
          bg.currentTime = t;
        } catch (e) {}
      }
      try {
        await smoothTakeoverToBackground(bg, galleryAudioRef.value);
        setGlobalBgMedia(bg);
        setGlobalBgState({ type: "gallery", wasPlaying: true });
      } catch (e) {
        stopGlobalBgMedia();
      }
      return;
    }

    if (!videoRef.value || videoRef.value.paused || !currentSrc.value) return;

    const bg = new Audio(currentSrc.value);
    bg.loop = playbackMode.value === "single";
    bg.muted = false;
    bg.playbackRate = parseFloat(playbackSpeed.value || "1") || 1;
    attachBackgroundVideoEndedHandler(bg);
    const t = currentTime.value || 0;
    if (t > 0) {
      try {
        bg.currentTime = t;
      } catch (e) {}
    }
    try {
      await smoothTakeoverToBackground(bg, videoRef.value);
      setGlobalBgMedia(bg);
      setGlobalBgState({ type: "video", wasPlaying: true });
    } catch (e) {
      stopGlobalBgMedia();
    }
  };

  const restoreFromBackgroundBridge = async () => {
    const bg = getGlobalBgMedia();
    const state = getGlobalBgState();
    if (!bg || !state || !state.wasPlaying) return false;

    const t = Number(bg.currentTime || 0);

    if (state.type === "gallery") {
      if (isGallery.value && galleryAudioRef.value) {
        if (t > 0) {
          try {
            galleryAudioRef.value.currentTime = t;
          } catch (e) {}
        }
        isPaused.value = false;
        startAutoRotate();
        try {
          galleryAudioRef.value.volume = 0;
        } catch (e) {}
        await galleryAudioRef.value.play().catch(() => {});
        await Promise.all([
          fadeMediaVolume(galleryAudioRef.value, 0, 1, 120),
          fadeMediaVolume(
            bg,
            typeof bg.volume === "number" ? bg.volume : 1,
            0,
            120
          ),
        ]);
      }
      stopGlobalBgMedia();
      return true;
    }

    if (!isGallery.value && videoRef.value) {
      const targetVolume = isMuted.value ? 0 : 1;
      try {
        videoRef.value.muted = false;
        videoRef.value.volume = 0;
      } catch (e) {}

      if (currentQuality.value === "original") {
        try {
          videoRef.value.currentTime = t;
        } catch (e) {}
        await videoRef.value.play().catch(() => {});
        await Promise.all([
          fadeMediaVolume(videoRef.value, 0, targetVolume, 120),
          fadeMediaVolume(
            bg,
            typeof bg.volume === "number" ? bg.volume : 1,
            0,
            120
          ),
        ]);
      } else {
        currentTime.value = t;
        startTranscodedSeek(t);
        await new Promise((resolve) => nextTick(resolve));
        if (videoRef.value) {
          await videoRef.value.play().catch(() => {});
          await Promise.all([
            fadeMediaVolume(videoRef.value, 0, targetVolume, 140),
            fadeMediaVolume(
              bg,
              typeof bg.volume === "number" ? bg.volume : 1,
              0,
              140
            ),
          ]);
        }
      }
      try {
        videoRef.value.muted = isMuted.value;
        if (!isMuted.value && typeof videoRef.value.volume === "number") {
          videoRef.value.volume = 1;
        }
      } catch (e) {}
      stopGlobalBgMedia();
      return true;
    } else {
      stopGlobalBgMedia();
      return false;
    }
  };

  return {
    getGlobalBgMedia,
    setGlobalBgMedia,
    getGlobalBgState,
    setGlobalBgState,
    stopGlobalBgMedia,
    fadeMediaVolume,
    startBackgroundBridgePlayback,
    restoreFromBackgroundBridge,
  };
}
