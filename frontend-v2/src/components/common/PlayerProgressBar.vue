<template>
  <div :class="rootClass">
    <slot name="toolbar" />
    <div class="progress-area" :class="{ 'time-ends': showTime && timeLayout === 'ends' }">
      <template v-if="showTime && timeLayout === 'ends'">
        <span class="time-end left">{{ currentTime }}</span>
        <div
          class="progress-bar-container"
          @mousedown="$emit('seekStart', $event)"
          @mousemove="$emit('seekMove', $event)"
          @mouseup="$emit('seekEnd', $event)"
        >
          <div class="progress-bg">
            <div class="progress-buffer" :style="{ width: bufferPercent + '%' }"></div>
            <div class="progress-current" :style="{ width: progressPercent + '%' }"></div>
            <div class="progress-handle" :style="{ left: progressPercent + '%' }"></div>
          </div>
        </div>
        <span class="time-end right">{{ duration }}</span>
      </template>
      <template v-else>
        <div v-if="showTime" class="time-info">
          <span>{{ currentTime }}</span>
          <span>{{ duration }}</span>
        </div>
        <div
          class="progress-bar-container"
          @mousedown="$emit('seekStart', $event)"
          @mousemove="$emit('seekMove', $event)"
          @mouseup="$emit('seekEnd', $event)"
        >
          <div class="progress-bg">
            <div class="progress-buffer" :style="{ width: bufferPercent + '%' }"></div>
            <div class="progress-current" :style="{ width: progressPercent + '%' }"></div>
            <div class="progress-handle" :style="{ left: progressPercent + '%' }"></div>
          </div>
        </div>
      </template>
    </div>
    <div v-if="showSide" class="progress-side">
      <slot name="side" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  rootClass: { type: String, default: 'progress-slot' },
  showTime: { type: Boolean, default: true },
  timeLayout: { type: String, default: 'stacked' },
  showSide: { type: Boolean, default: false },
  currentTime: { type: String, default: '0:00' },
  duration: { type: String, default: '0:00' },
  bufferPercent: { type: Number, default: 0 },
  progressPercent: { type: Number, default: 0 }
})

defineEmits(['seekStart', 'seekMove', 'seekEnd'])
</script>
