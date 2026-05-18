import { ref } from 'vue';

const RESUME_STATE_KEY = 'timeline_player_resume_state_v3';
const RESUME_STATE_VERSION = 3;

export function useTimelineResume({
  getStorageKey,
  getFallbackKey,
  maxAgeMs = 7 * 24 * 60 * 60 * 1000
}) {
  const wasPlayingBeforeHidden = ref(false);
  const hiddenPlayTimeOfDay = ref(0);
  const hiddenSegmentIndex = ref(-1);
  const hiddenSegmentOffset = ref(0);
  const pendingResumeTimeOfDay = ref(0);
  const pendingResumeWasPlaying = ref(false);
  const pendingResumeSegmentIndex = ref(-1);
  const pendingResumeSegmentOffset = ref(0);
  const pendingResumeExtras = ref({});

  const readStore = () => {
    try {
      const raw = localStorage.getItem(RESUME_STATE_KEY);
      if (!raw) return { version: RESUME_STATE_VERSION, items: {} };
      const parsed = JSON.parse(raw);
      if (!parsed || Number(parsed.version) !== RESUME_STATE_VERSION || typeof parsed.items !== 'object') {
        return { version: RESUME_STATE_VERSION, items: {} };
      }
      return parsed;
    } catch (error) {
      console.warn('read resume store failed', error);
      return { version: RESUME_STATE_VERSION, items: {} };
    }
  };

  const writeStore = (store) => {
    try {
      localStorage.setItem(RESUME_STATE_KEY, JSON.stringify(store));
    } catch (error) {
      console.warn('write resume store failed', error);
    }
  };

  const pruneStore = (store) => {
    if (!store || typeof store.items !== 'object') return store;
    const now = Date.now();
    const entries = Object.entries(store.items || {});
    let changed = false;
    entries.forEach(([key, value]) => {
      const updatedAt = Number(value?.updatedAt || 0);
      if (!updatedAt || now - updatedAt > maxAgeMs) {
        delete store.items[key];
        changed = true;
      }
    });
    if (changed) writeStore(store);
    return store;
  };

  const clearHiddenResumeState = () => {
    hiddenPlayTimeOfDay.value = 0;
    hiddenSegmentIndex.value = -1;
    hiddenSegmentOffset.value = 0;
    wasPlayingBeforeHidden.value = false;
  };

  const setHiddenResumeState = ({ absoluteTime = 0, segmentIndex = -1, segmentOffset = 0, wasPlaying = false }) => {
    hiddenPlayTimeOfDay.value = Math.max(0, Math.min(86400, Number(absoluteTime) || 0));
    hiddenSegmentIndex.value = Number.isInteger(segmentIndex) ? segmentIndex : -1;
    hiddenSegmentOffset.value = Math.max(0, Number(segmentOffset) || 0);
    wasPlayingBeforeHidden.value = !!wasPlaying;
  };

  const saveResumeState = ({
    timeOfDay = 0,
    segmentIndex = -1,
    segmentOffset = 0,
    wasPlaying = false,
    extras = {}
  }) => {
    try {
      const key = String(getStorageKey?.() || '');
      if (!key) return;
      const fallbackKey = String(getFallbackKey?.() || '');
      const payload = {
        timeOfDay: Math.max(0, Math.min(86400, Number(timeOfDay) || 0)),
        segmentIndex: Number.isInteger(segmentIndex) ? segmentIndex : -1,
        segmentOffset: Math.max(0, Number(segmentOffset) || 0),
        wasPlaying: !!wasPlaying,
        extras: extras && typeof extras === 'object' ? extras : {},
        updatedAt: Date.now()
      };
      const store = pruneStore(readStore());
      store.items[key] = payload;
      if (fallbackKey && fallbackKey !== key) {
        store.items[fallbackKey] = payload;
      }
      writeStore(store);
    } catch (error) {
      console.warn('save resume state failed', error);
    }
  };

  const loadResumeState = () => {
    try {
      const key = String(getStorageKey?.() || '');
      if (!key) return;
      const fallbackKey = String(getFallbackKey?.() || '');
      const store = pruneStore(readStore());
      const primary = store.items[key];
      const fallback = fallbackKey ? store.items[fallbackKey] : null;
      const target = primary || fallback;
      if (!target) return;
      pendingResumeTimeOfDay.value = Math.max(0, Math.min(86400, Number(target.timeOfDay) || 0));
      pendingResumeWasPlaying.value = !!target.wasPlaying;
      pendingResumeSegmentIndex.value = Number.isInteger(target.segmentIndex) ? target.segmentIndex : -1;
      pendingResumeSegmentOffset.value = Math.max(0, Number(target.segmentOffset) || 0);
      pendingResumeExtras.value = target.extras && typeof target.extras === 'object' ? target.extras : {};
    } catch (error) {
      console.warn('load resume state failed', error);
    }
  };

  const consumePendingResume = () => {
    const payload = {
      timeOfDay: pendingResumeTimeOfDay.value,
      wasPlaying: pendingResumeWasPlaying.value,
      segmentIndex: pendingResumeSegmentIndex.value,
      segmentOffset: pendingResumeSegmentOffset.value,
      extras: pendingResumeExtras.value || {}
    };
    pendingResumeTimeOfDay.value = 0;
    pendingResumeWasPlaying.value = false;
    pendingResumeSegmentIndex.value = -1;
    pendingResumeSegmentOffset.value = 0;
    pendingResumeExtras.value = {};
    return payload;
  };

  return {
    wasPlayingBeforeHidden,
    hiddenPlayTimeOfDay,
    hiddenSegmentIndex,
    hiddenSegmentOffset,
    setHiddenResumeState,
    clearHiddenResumeState,
    saveResumeState,
    loadResumeState,
    consumePendingResume
  };
}
