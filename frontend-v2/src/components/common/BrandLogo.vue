<script setup>
import { useId } from 'vue'

defineProps({
  rotating: { type: Boolean, default: false },
  outerGlow: { type: Boolean, default: true },
  strokeWidth: { type: [String, Number], default: 2.5 }
})

const uid = useId()
const gradientId = `brand-logo-gradient-${uid}`
</script>

<template>
  <svg
    :class="{ 'is-rotating': rotating }"
    viewBox="0 0 40 40"
    xmlns="http://www.w3.org/2000/svg"
  >
    <defs>
      <linearGradient :id="gradientId" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#FF4D4D" stop-opacity="1" />
        <stop offset="100%" stop-color="#F9CB28" stop-opacity="1" />
      </linearGradient>
    </defs>
    <circle cx="20" cy="20" r="18" :fill="`url(#${gradientId})`" />
    <circle
      v-if="outerGlow"
      cx="20" cy="20" r="18" fill="none"
      stroke="rgba(255,255,255,0.2)" stroke-width="0.5"
    />
    <g transform="translate(20, 20)">
      <path d="M0 -11 L0 0" stroke="white" :stroke-width="strokeWidth" stroke-linecap="round" />
      <path d="M-9.5 5.5 L0 0" stroke="white" :stroke-width="strokeWidth" stroke-linecap="round" />
      <path d="M9.5 5.5 L0 0" stroke="white" :stroke-width="strokeWidth" stroke-linecap="round" />
    </g>
  </svg>
</template>
