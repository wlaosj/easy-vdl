import { ref } from 'vue'

const dialogInstance = ref(null)

export function useDialog() {
    function setDialogInstance(instance) {
        dialogInstance.value = instance
    }

    /**
     * 显示确认对话框
     * @param {Object} options 
     * @param {String} options.title 标题
     * @param {String} options.message 内容
     * @param {String} options.type 类型: success, error, warning, info
     * @param {String} options.confirmText 确认按钮文字
     * @param {String} options.cancelText 取消按钮文字
     * @returns {Promise<Boolean>}
     */
    function confirm({ title = '确认', message = '', type = 'warning', confirmText = '确定', cancelText = '取消', width }) {
        if (!dialogInstance.value) {
            console.warn('Dialog instance not initialized')
            // 如果没初始化，Fallback 到系统原生 confirm
            return Promise.resolve(window.confirm(message))
        }
        return dialogInstance.value.confirm({ title, message, type, confirmText, cancelText, width })
    }

    /**
     * 显示提示对话框
     * @param {Object} options 
     */
    function alert({ title = '提示', message = '', type = 'info', confirmText = '确定', width }) {
        if (!dialogInstance.value) {
            console.warn('Dialog instance not initialized')
            window.alert(message)
            return Promise.resolve()
        }
        return dialogInstance.value.alert({ title, message, type, confirmText, width })
    }

    return {
        setDialogInstance,
        confirm,
        alert
    }
}
