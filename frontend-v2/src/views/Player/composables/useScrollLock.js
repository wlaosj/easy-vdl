/**
 * 移动端全屏防滚动穿透 Composable
 * 用于在移动端进入播放页时，锁死 main-content 及外层 DOM 容器的物理滚动
 * 放行底栏组件（如播放列表、设置抽屉）内部滚动，且在退出时完美还原原生位置，杜绝 iOS WebView 橡皮筋穿透 Bug。
 */
export function useScrollLock() {
  let unlockPageScroll = null;
  let removeTouchMoveGuard = null;

  /**
   * 强制解除锁定（兜底与复位）
   */
  const forceUnlockPageScroll = () => {
    try {
      if (unlockPageScroll) {
        unlockPageScroll();
      }
    } catch (e) {
      console.error("[useScrollLock] Failed to unlock scroll:", e);
    }
    unlockPageScroll = null;

    try {
      if (removeTouchMoveGuard) {
        removeTouchMoveGuard();
      }
    } catch (e) {}
    removeTouchMoveGuard = null;

    try {
      document.body.classList.remove("route-player-lock");
    } catch (e) {}
  };

  /**
   * 开启移动端防滚动穿透锁定
   */
  const lockPageScrollOnMobile = () => {
    // 只在移动端处理
    if (window.innerWidth > 768) {
      return () => {};
    }

    const docEl = document.documentElement;
    const body = document.body;
    const mainContent = document.querySelector(".main-content");

    // 1) 标记当前在播放页，用于全局样式精确禁用布局滚动容器
    try {
      body.classList.add("route-player-lock");
    } catch (e) {}

    // 2) 拦截全局 touchmove，防止 iOS/WebView 橡皮筋回弹导致外层滚动
    // 放行底部抽屉内容区（允许播放列表、设置面板内部滚动）
    const touchMoveGuard = (evt) => {
      try {
        const target = evt.target;
        if (target && typeof target.closest === "function") {
          if (target.closest(".bottom-drawer") || target.closest(".mobile-action-dock")) {
            return;
          }
        }
        evt.preventDefault();
      } catch (e) {
        try {
          evt.preventDefault();
        } catch (e2) {}
      }
    };

    document.addEventListener("touchmove", touchMoveGuard, { passive: false });
    removeTouchMoveGuard = () => {
      try {
        document.removeEventListener("touchmove", touchMoveGuard);
      } catch (e) {}
    };

    // 3) 记录并固定当前滚动位置，避开 iOS 滚动拉伸导致的顶层空隙
    const scrollY = window.scrollY || docEl.scrollTop || 0;

    const prev = {
      htmlOverflow: docEl.style.overflow,
      bodyOverflow: body.style.overflow,
      bodyPosition: body.style.position,
      bodyTop: body.style.top,
      bodyWidth: body.style.width,
      mainOverflow: mainContent ? mainContent.style.overflow : null,
      mainOverscroll: mainContent ? mainContent.style.overscrollBehavior : null,
      mainWebkitScroll: mainContent
        ? mainContent.style.webkitOverflowScrolling
        : null,
    };

    docEl.style.overflow = "hidden";
    body.style.overflow = "hidden";
    body.style.position = "fixed";
    body.style.top = `-${scrollY}px`;
    body.style.width = "100%";
    
    if (mainContent) {
      mainContent.style.overflow = "hidden";
      mainContent.style.overscrollBehavior = "none";
      // @ts-ignore
      mainContent.style.webkitOverflowScrolling = "auto";
    }

    // 返回精心包装的“解锁函数”，还原全部状态
    return () => {
      try {
        body.classList.remove("route-player-lock");
        
        try {
          if (removeTouchMoveGuard) {
            removeTouchMoveGuard();
          }
        } catch (e) {}
        removeTouchMoveGuard = null;

        docEl.style.overflow = prev.htmlOverflow;
        body.style.overflow = prev.bodyOverflow;
        body.style.position = prev.bodyPosition;
        body.style.top = prev.bodyTop;
        body.style.width = prev.bodyWidth;

        if (mainContent) {
          mainContent.style.overflow = prev.mainOverflow;
          mainContent.style.overscrollBehavior = prev.mainOverscroll;
          // @ts-ignore
          mainContent.style.webkitOverflowScrolling = prev.mainWebkitScroll;
        }

        window.scrollTo(0, scrollY);
      } catch (e) {
        console.error("[useScrollLock] Failed to restore scroll states:", e);
      }
    };
  };

  const lock = () => {
    forceUnlockPageScroll();
    unlockPageScroll = lockPageScrollOnMobile();
  };

  return {
    lock,
    unlock: forceUnlockPageScroll
  };
}
