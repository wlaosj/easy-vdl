import { readonly, ref } from 'vue'

const isRouteLoading = ref(false)
const pendingRoutePath = ref('')

let loadingStartedAt = 0
let finishTimer = null

const MIN_LOADING_VISIBLE_MS = 180

function clearFinishTimer() {
  if (finishTimer) {
    clearTimeout(finishTimer)
    finishTimer = null
  }
}

export function beginRouteLoading(path = '') {
  if (path) pendingRoutePath.value = path
  clearFinishTimer()
  loadingStartedAt = Date.now()
  isRouteLoading.value = true
}

export function endRouteLoading() {
  const elapsed = Date.now() - loadingStartedAt
  const waitMs = Math.max(0, MIN_LOADING_VISIBLE_MS - elapsed)
  clearFinishTimer()
  finishTimer = setTimeout(() => {
    isRouteLoading.value = false
    pendingRoutePath.value = ''
    finishTimer = null
  }, waitMs)
}

export function cancelRouteLoading() {
  clearFinishTimer()
  isRouteLoading.value = false
  pendingRoutePath.value = ''
}

export function setPendingRoutePath(path = '') {
  pendingRoutePath.value = path
}

export function useRouteLoadingState() {
  return {
    isRouteLoading: readonly(isRouteLoading),
    pendingRoutePath: readonly(pendingRoutePath)
  }
}
