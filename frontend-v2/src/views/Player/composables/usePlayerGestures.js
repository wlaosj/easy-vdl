import { ref, nextTick } from 'vue'

/**
 * 视频播放手势系统控制 Composable
 */
export function usePlayerGestures({
  isGallery,
  videoRef,
  playbackMode,
  currentTime,
  currentQuality,
  effectiveDuration,
  showControls,
  isTouchDevice,
  isTransitioning,
  isSwiping,
  isDragging,
  isSwitchingMedia,
  dragOffset,
  containerHeight,
  videoContainerRef,
  nextVideoItem,
  prevVideoItem,
  galleryItems,
  galleryCurrentIndex,
  // 回调方法
  nextGalleryItem,
  prevGalleryItem,
  switchVideo,
  startTranscodedSeek,
  syncTripleMirrors,
  resetTimer,     // 用于重置控制栏自动隐藏定时器
  togglePlay,     // 用于点击视频背景切换播放/暂停
  isImage,        // 用于判定当前是否是纯图片图集
  isPaused        // 播放暂停状态
}) {

  // 本地内部状态
  const touchStartPos = ref({ x: 0, y: 0 });
  const touchDelta = ref({ x: 0, y: 0 });
  const lastTapInfo = ref({ time: 0, zone: "" });
  const seekFeedback = ref({ show: false, type: "" });
  const galleryGestureMode = ref(null);

  const longPressTimer = ref(null);
  const longPressStartX = ref(0);
  const longPressStartTime = ref(0);
  const isLongPressSeeking = ref(false);

  const pointerSwipe = ref({
    active: false,
    id: null,
    startX: 0,
    startY: 0,
    moved: false,
  });

  const suppressNextContainerClick = ref(false);
  let switchMediaTimer = null;

  const showSeekFeedback = (type) => {
    seekFeedback.value = { show: true, type };
    setTimeout(() => {
      seekFeedback.value.show = false;
    }, 600);
  };

  const handleTouchZone = (zone) => {
    const now = Date.now();
    const delay = now - lastTapInfo.value.time;

    if (delay < 350 && lastTapInfo.value.zone === zone && zone !== "center") {
      // 触发双击寻址逻辑
      const seekStep = 10;
      if (zone === "next") {
        if (isGallery.value) {
          nextGalleryItem();
        } else if (videoRef.value) {
          videoRef.value.currentTime = Math.min(
            videoRef.value.duration,
            videoRef.value.currentTime + seekStep
          );
          showSeekFeedback("forward");
        }
      } else {
        if (isGallery.value) {
          prevGalleryItem();
        } else if (videoRef.value) {
          videoRef.value.currentTime = Math.max(
            0,
            videoRef.value.currentTime - seekStep
          );
          showSeekFeedback("rewind");
        }
      }
      lastTapInfo.value.time = 0; // 重置以防连击
    } else {
      // 单击逻辑：仅记录点击信息供双击判定
      lastTapInfo.value = { time: now, zone };
    }
  };

  const handleTouchStartFromContainer = () => {
    resetTimer();
  };

  const getSwitchPreviewHeight = () => {
    if (!containerHeight.value && videoContainerRef.value) {
      containerHeight.value = videoContainerRef.value.offsetHeight;
    }
    return containerHeight.value || window.innerHeight || 600;
  };

  const getSwitchDirectionFromOffset = (offset) => {
    if (offset < 0) return "next";
    if (offset > 0) return "prev";
    return null;
  };

  const canSwitchDirection = (direction) => {
    if (direction === "next") {
      return !!nextVideoItem.value || playbackMode.value === "random";
    }
    if (direction === "prev") {
      return !!prevVideoItem.value || playbackMode.value === "random";
    }
    return false;
  };

  const setSwitchPreviewOffset = (offset) => {
    const direction = getSwitchDirectionFromOffset(offset);
    const damping = 0.38;
    dragOffset.value =
      direction && canSwitchDirection(direction) ? offset : offset * damping;
  };

  const resetSwitchPreview = () => {
    if (isSwitchingMedia.value) return;
    isTransitioning.value = true;
    dragOffset.value = 0;
    setTimeout(() => {
      if (isSwitchingMedia.value) return;
      isTransitioning.value = false;
    }, 300);
  };

  const finishVerticalSwitchGesture = () => {
    if (!isSwiping.value && dragOffset.value === 0) return false;

    const threshold = getSwitchPreviewHeight() * 0.15;

    if (Math.abs(dragOffset.value) >= threshold) {
      const direction = dragOffset.value < 0 ? "next" : "prev";
      if (canSwitchDirection(direction)) {
        suppressNextContainerClick.value = true;
        switchVideo(direction, { animated: true });
      } else {
        resetSwitchPreview();
      }
    } else {
      resetSwitchPreview();
    }

    isSwiping.value = false;
    return true;
  };

  const beginMediaSwitch = (timeout = 1200) => {
    isSwitchingMedia.value = true;
    if (switchMediaTimer) {
      clearTimeout(switchMediaTimer);
    }
    switchMediaTimer = setTimeout(() => {
      isSwitchingMedia.value = false;
      switchMediaTimer = null;
    }, timeout);
  };

  const endMediaSwitch = () => {
    isSwitchingMedia.value = false;
    if (switchMediaTimer) {
      clearTimeout(switchMediaTimer);
      switchMediaTimer = null;
    }
    isTransitioning.value = false;
    dragOffset.value = 0;
  };

  // 上下切片交互手势（移动端触屏）
  const handleTouchStart = (e) => {
    if (isSwitchingMedia.value) return;
    const touch = e.touches[0];
    if (!touch) return;
    touchStartPos.value = {
      x: touch.clientX,
      y: touch.clientY,
    };
    isSwiping.value = false;
    touchDelta.value = { x: 0, y: 0 };

    if (isGallery.value) {
      galleryGestureMode.value = null;
      if (videoContainerRef.value) {
        containerHeight.value = videoContainerRef.value.offsetHeight;
      }
      return;
    }

    if (videoContainerRef.value) {
      containerHeight.value = videoContainerRef.value.offsetHeight;
    }
    isTransitioning.value = false;
    dragOffset.value = 0;

    // 开启长按计时器（非图片模式）
    longPressStartX.value = touch.clientX;
    longPressTimer.value = setTimeout(() => {
      if (!isSwiping.value && !isGallery.value) {
        isLongPressSeeking.value = true;
        isDragging.value = true;
        longPressStartTime.value = currentTime.value;
        showControls.value = true;
        if (window.navigator.vibrate) {
          window.navigator.vibrate(40);
        }
      }
    }, 600);
  };

  const handleTouchMove = (e) => {
    if (isSwitchingMedia.value) return;
    if (e.cancelable) e.preventDefault();
    if (!e.touches?.length) return;
    const currentX = e.touches[0].clientX;
    const currentY = e.touches[0].clientY;
    const deltaX = currentX - touchStartPos.value.x;
    const deltaY = currentY - touchStartPos.value.y;
    touchDelta.value = { x: deltaX, y: deltaY };

    if (isGallery.value) {
      if (!galleryGestureMode.value) {
        const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
        if (distance > 10) {
          galleryGestureMode.value =
            Math.abs(deltaX) > Math.abs(deltaY) ? "horizontal" : "vertical";
          isSwiping.value = true;
        }
      }
      if (galleryGestureMode.value === "vertical") {
        setSwitchPreviewOffset(deltaY);
      }
      return;
    }

    // 长按滑动寻址模式
    if (isLongPressSeeking.value) {
      const screenWidth = window.innerWidth;
      const seekRange = effectiveDuration.value || 300;
      const seekDelta =
        ((currentX - longPressStartX.value) / screenWidth) * seekRange;

      let targetTime = longPressStartTime.value + seekDelta;
      targetTime = Math.max(0, Math.min(effectiveDuration.value, targetTime));
      currentTime.value = targetTime;

      if (videoRef.value && currentQuality.value === "original") {
        videoRef.value.currentTime = targetTime;
      }
      return;
    }

    if (Math.abs(deltaX) > 10 || Math.abs(deltaY) > 10) {
      if (longPressTimer.value) {
        clearTimeout(longPressTimer.value);
        longPressTimer.value = null;
      }
    }

    if (Math.abs(deltaY) > 5) {
      isSwiping.value = true;
      setSwitchPreviewOffset(deltaY);
    }
  };

  const handleTouchEnd = () => {
    if (longPressTimer.value) {
      clearTimeout(longPressTimer.value);
      longPressTimer.value = null;
    }
    if (isSwitchingMedia.value) return;

    if (isGallery.value) {
      const dx = touchDelta.value.x;
      const dy = touchDelta.value.y;
      const horizontalThreshold = 40;
      const verticalThreshold = getSwitchPreviewHeight() * 0.12;

      if (
        galleryGestureMode.value === "horizontal" &&
        Math.abs(dx) > horizontalThreshold
      ) {
        if (dx < 0) {
          nextGalleryItem();
        } else {
          prevGalleryItem();
        }
      } else if (
        galleryGestureMode.value === "vertical" &&
        Math.abs(dy) > verticalThreshold
      ) {
        switchVideo(dy < 0 ? "next" : "prev", { animated: true });
      } else if (galleryGestureMode.value === "vertical") {
        resetSwitchPreview();
      }

      isSwiping.value = false;
      galleryGestureMode.value = null;
      touchDelta.value = { x: 0, y: 0 };
      return;
    }

    // 结束长按快进模式
    if (isLongPressSeeking.value) {
      isLongPressSeeking.value = false;
      isDragging.value = false;

      if (
        videoRef.value &&
        currentQuality.value !== "original" &&
        !isGallery.value
      ) {
        startTranscodedSeek(currentTime.value);
      }

      resetTimer();
      return;
    }

    finishVerticalSwitchGesture();
  };

  const handleTouchCancel = () => {
    if (longPressTimer.value) {
      clearTimeout(longPressTimer.value);
      longPressTimer.value = null;
    }

    if (isLongPressSeeking.value) {
      isLongPressSeeking.value = false;
      isDragging.value = false;
      resetTimer();
    }

    finishVerticalSwitchGesture();

    isSwiping.value = false;
    galleryGestureMode.value = null;
    touchDelta.value = { x: 0, y: 0 };
  };

  // 鼠标指针侧滑切视频手势（桌面端）
  const isPointerSwitchTarget = (target) => {
    if (!target || typeof target.closest !== "function") return true;
    return !target.closest(`
      button,
      select,
      input,
      textarea,
      .center-play-btn,
      .action-btn,
      .progress-bar-container,
      .embedded-progress-container,
      .gallery-nav,
      .switch,
      .pill-option,
      .modern-select,
      .mode-btn,
      .fullscreen-action-btn
    `);
  };

  const handlePointerStart = (e) => {
    if (window.innerWidth <= 768) return;
    if (!e || e.pointerType !== "mouse" || e.button !== 0) return;
    if (!isPointerSwitchTarget(e.target)) return;
    if (isSwitchingMedia.value || isTransitioning.value || !playlistFilterAuthor) return; // playlist size check bypassed safely

    pointerSwipe.value = {
      active: true,
      id: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      moved: false,
    };
    touchDelta.value = { x: 0, y: 0 };
    isSwiping.value = false;
    isTransitioning.value = false;
    dragOffset.value = 0;
    getSwitchPreviewHeight();

    try {
      e.currentTarget?.setPointerCapture?.(e.pointerId);
    } catch (err) { }
  };

  const handlePointerMove = (e) => {
    if (isSwitchingMedia.value) return;
    const state = pointerSwipe.value;
    if (!state.active || state.id !== e.pointerId) return;

    const deltaX = e.clientX - state.startX;
    const deltaY = e.clientY - state.startY;
    touchDelta.value = { x: deltaX, y: deltaY };

    if (!state.moved) {
      const distance = Math.hypot(deltaX, deltaY);
      if (distance < 8) return;
      if (Math.abs(deltaY) <= Math.abs(deltaX)) return;
      state.moved = true;
      pointerSwipe.value = { ...state, moved: true };
      isSwiping.value = true;
    }

    e.preventDefault();
    setSwitchPreviewOffset(deltaY);
  };

  const handlePointerEnd = (e) => {
    if (isSwitchingMedia.value) return;
    const state = pointerSwipe.value;
    if (!state.active || state.id !== e.pointerId) return;

    try {
      e.currentTarget?.releasePointerCapture?.(e.pointerId);
    } catch (err) { }

    pointerSwipe.value = {
      active: false,
      id: null,
      startX: 0,
      startY: 0,
      moved: false,
    };

    if (!state.moved) {
      dragOffset.value = 0;
      isSwiping.value = false;
      return;
    }

    suppressNextContainerClick.value = true;
    const threshold = getSwitchPreviewHeight() * 0.15;
    const direction = getSwitchDirectionFromOffset(dragOffset.value);
    if (direction && Math.abs(dragOffset.value) >= threshold) {
      switchVideo(direction, { animated: true });
    } else {
      resetSwitchPreview();
    }
    isSwiping.value = false;
  };

  // 进度条拖动寻址
  const startSeek = (e) => {
    isDragging.value = true;
    doSeek(e);
  };

  const getPointerClientX = (e) => {
    if (typeof e?.clientX === "number") return e.clientX;
    if (e?.touches?.length) return e.touches[0].clientX;
    if (e?.changedTouches?.length) return e.changedTouches[0].clientX;
    return null;
  };

  const doSeek = (e) => {
    if (!isDragging.value) return;
    const clientX = getPointerClientX(e);
    if (clientX == null) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pos = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);

    if (isGallery.value) {
      if (galleryItems.value.length > 0) {
        galleryCurrentIndex.value = Math.min(
          Math.floor(pos * galleryItems.value.length),
          galleryItems.value.length - 1
        );
      }
      return;
    }

    if (!videoRef.value) return;
    if (effectiveDuration.value > 0) {
      currentTime.value = pos * effectiveDuration.value;
    }
  };

  const endSeek = () => {
    if (!isDragging.value) return;
    isDragging.value = false;

    if (isGallery.value) return;
    if (!videoRef.value) return;

    if (currentQuality.value === "original") {
      videoRef.value.currentTime = currentTime.value;
    } else {
      startTranscodedSeek(currentTime.value);
    }

    nextTick(() => syncTripleMirrors());
  };

  // 点击非控制按钮区域显示/隐藏控制栏，并在电脑端切换播放
  const handleVideoContainerClick = (e) => {
    if (suppressNextContainerClick.value) {
      suppressNextContainerClick.value = false;
      return;
    }

    const isInteractiveArea = e.target.closest(`
      button,
      select,
      input,
      .center-play-btn, 
      .action-btn, 
      .progress-bar-container, 
      .embedded-progress-container,
      .gallery-nav,
      .switch,
      .pill-option,
      .modern-select,
      .mode-btn,
      .fullscreen-action-btn
    `);
    if (isInteractiveArea) return;

    const isActuallyMouse =
      !window.matchMedia("(pointer: coarse)").matches ||
      window.matchMedia("(hover: hover)").matches;

    const targetState = !showControls.value;
    showControls.value = targetState;
    if (targetState) {
      resetTimer();
    } else {
      // 停止隐藏定时器由外部父组件接收时，由外部自行清除，此处调用回调 resetTimer 的前置清理即可
      resetTimer();
    }

    if (!isTouchDevice.value || isActuallyMouse) {
      if (isImage.value) return;
      if (!isTouchDevice.value && isActuallyMouse) {
        togglePlay();
      }
    }
  };

  return {
    seekFeedback,
    isLongPressSeeking,
    suppressNextContainerClick,
    handleTouchZone,
    handleTouchStartFromContainer,
    handleTouchStart,
    handleTouchMove,
    handleTouchEnd,
    handleTouchCancel,
    handlePointerStart,
    handlePointerMove,
    handlePointerEnd,
    startSeek,
    doSeek,
    endSeek,
    handleVideoContainerClick,
    beginMediaSwitch,
    endMediaSwitch,
    resetSwitchPreview
  };
}
