<template>
  <Modal 
    v-model:show="show" 
    :title="state.title" 
    :type="state.type" 
    :show-confirm="false"
    width="400px"
    persistent
    z-index="30000"
  >
    <div class="dialog-content">
      <p v-html="state.message"></p>
    </div>
    
    <template #footer>
      <button 
        v-if="state.isConfirm" 
        class="btn btn-secondary" 
        @click="handleCancel"
      >
        {{ state.cancelText }}
      </button>
      <button 
        class="btn" 
        :class="confirmBtnClass"
        @click="handleConfirm"
      >
        {{ state.confirmText }}
      </button>
    </template>
  </Modal>
</template>

<script setup>
import { ref, computed } from 'vue'
import Modal from './Modal.vue'

const show = ref(false)
const resolvePromise = ref(null)

const state = ref({
  title: '',
  message: '',
  type: 'info',
  confirmText: '确定',
  cancelText: '取消',
  isConfirm: false
})

const confirmBtnClass = computed(() => {
  if (state.value.type === 'error' || state.value.type === 'warning') {
    return 'btn-danger'
  }
  return 'btn-primary'
})

const open = (options) => {
  state.value = {
    title: options.title || '提示',
    message: options.message || '',
    type: options.type || 'info',
    confirmText: options.confirmText || '确定',
    cancelText: options.cancelText || '取消',
    isConfirm: options.isConfirm || false
  }
  show.value = true
  
  return new Promise((resolve) => {
    resolvePromise.value = resolve
  })
}

const handleConfirm = () => {
  show.value = false
  if (resolvePromise.value) resolvePromise.value(true)
}

const handleCancel = () => {
  show.value = false
  if (resolvePromise.value) resolvePromise.value(false)
}

// 暴露方法给 useDialog
defineExpose({
  confirm: (options) => open({ ...options, isConfirm: true }),
  alert: (options) => open({ ...options, isConfirm: false })
})
</script>

<style scoped>
.dialog-content {
  padding: 8px 0;
}
.dialog-content p {
  margin: 0;
  color: var(--color-text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
