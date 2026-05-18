import { ref } from 'vue'

// 全局Toast实例引用
const toastInstance = ref(null)

export function useToast() {
    // 设置Toast实例
    function setToastInstance(instance) {
        toastInstance.value = instance
    }

    // Toast方法
    function success(message, title = '') {
        if (toastInstance.value) {
            toastInstance.value.success(message, title)
        } else {
            console.warn('Toast instance not initialized')
        }
    }

    function error(message, title = '') {
        if (toastInstance.value) {
            toastInstance.value.error(message, title)
        } else {
            console.warn('Toast instance not initialized')
        }
    }

    function warning(message, title = '') {
        if (toastInstance.value) {
            toastInstance.value.warning(message, title)
        } else {
            console.warn('Toast instance not initialized')
        }
    }

    function info(message, title = '') {
        if (toastInstance.value) {
            toastInstance.value.info(message, title)
        } else {
            console.warn('Toast instance not initialized')
        }
    }

    function clear() {
        if (toastInstance.value) {
            toastInstance.value.clear()
        }
    }

    return {
        setToastInstance,
        success,
        error,
        warning,
        info,
        clear
    }
}
