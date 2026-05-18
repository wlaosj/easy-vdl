<template>
  <Modal
    v-model:show="show"
    title="⚠️ 免责声明"
    width="800px"
    :show-confirm="false"
    :persistent="true"
    :hide-close="true"
    class="disclaimer-modal"
  >
    <div class="disclaimer-content">
      <div class="alert alert-warning">
        <h4>📋 重要提醒</h4>
        <p>请仔细阅读以下免责声明，滚动到底部并点击"我已阅读并同意"按钮后方可使用本服务。</p>
        <p><strong>使用本服务可能触发平台风控、限流或账号封禁等风险，相关后果由用户自行承担。</strong></p>
      </div>

      <div class="section">
        <h4>🔒 服务性质声明</h4>
        <p>Easy-VDL 是一个视频下载工具平台，提供视频链接解析和下载服务。本平台仅作为技术工具，不涉及任何内容创作或版权归属。</p>
        <p>用户通过本平台下载的所有内容，其版权均归原作者或版权所有者所有。本平台不拥有、不控制、不传播任何视频内容。</p>
      </div>

      <div class="section info">
        <h4>📜 用户责任声明</h4>
        <p><strong>用户在使用本服务时必须遵守以下规定：</strong></p>
        <ul>
          <li>仅下载您拥有合法权限访问的内容</li>
          <li>遵守相关法律法规和平台服务条款</li>
          <li>不得用于商业用途或大规模传播</li>
          <li>尊重原作者和版权所有者的权益</li>
          <li>不得下载涉及违法、暴力、色情等不良内容</li>
          <li>自行管理账号与 Cookie 的安全与合规使用</li>
        </ul>
        <p>用户因使用本服务而产生的任何法律后果（包括但不限于账号限制、封禁、内容下架、纠纷或处罚），由用户自行承担。</p>
      </div>

      <div class="section danger">
        <h4>🚫 禁止行为</h4>
        <p><strong>严格禁止以下行为：</strong></p>
        <ul>
          <li>下载受版权保护的内容用于商业用途</li>
          <li>大规模批量下载或恶意爬取</li>
          <li>传播或分享下载的受版权保护内容</li>
          <li>利用本服务进行任何违法活动</li>
          <li>攻击或破坏本平台服务</li>
        </ul>
        <p>如发现违规行为，本平台有权立即停止服务并保留追究法律责任的权利。</p>
      </div>

      <div class="section success">
        <h4>✅ 平台承诺</h4>
        <p><strong>本平台承诺：</strong></p>
        <ul>
          <li>仅提供技术工具，不存储或传播任何视频内容</li>
          <li>保护用户隐私，不收集或泄露用户个人信息</li>
          <li>积极响应版权投诉，及时处理违规内容</li>
          <li>持续改进服务质量，提供安全可靠的技术支持</li>
        </ul>
        <p>我们致力于提供安全、便捷的技术工具，但不对第三方平台的限制、封禁或规则变动承担任何责任。</p>
      </div>

      <div class="section warning">
        <h4>⚖️ 法律声明</h4>
        <p>本免责声明受中华人民共和国法律管辖。如本声明的任何条款被认定为无效或不可执行，不影响其他条款的有效性。</p>
        <p>本平台保留随时修改本免责声明的权利，修改后的声明将在平台上公布。</p>
      </div>

      <div class="section contact">
        <h4>📞 联系我们</h4>
        <p>如果您对本免责声明有任何疑问，或发现平台上的违规内容，请通过以下方式联系我们：</p>
        <p>💬 电报群：<a href="https://t.me/+7jcTMePlNVwwZjg1" target="_blank">点击加入电报群</a></p>
      </div>

      <div class="footer-action">
        <p class="timer-tip" v-if="countdown > 0">⏰ 请仔细阅读以上声明，还剩 {{ countdown }} 秒后可同意</p>
        <button 
          class="btn btn-primary agree-btn" 
          :disabled="countdown > 0"
          @click="handleAgree"
        >
          <span v-if="countdown > 0">🔒 请阅读至结束</span>
          <span v-else>✅ 我已阅读并同意免责声明</span>
        </button>
      </div>
    </div>
  </Modal>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import Modal from './Modal.vue'

const show = ref(false)
const countdown = ref(10)
const isMandatory = ref(false)
let timer = null

const checkDisclaimer = () => {
  const isAgreed = localStorage.getItem('disclaimer_agreed')
  if (!isAgreed) {
    isMandatory.value = true
    show.value = true
    startTimer()
  }
}

const open = () => {
  isMandatory.value = false
  show.value = true
  const isAgreed = localStorage.getItem('disclaimer_agreed')
  if (isAgreed) {
    countdown.value = 0
  } else {
    startTimer()
  }
}

defineExpose({ open })

const startTimer = () => {
  if (timer) clearInterval(timer)
  countdown.value = 10
  timer = setInterval(() => {
    if (countdown.value > 0) {
      countdown.value--
    } else {
      clearInterval(timer)
    }
  }, 1000)
}

const handleAgree = () => {
  localStorage.setItem('disclaimer_agreed', 'true')
  show.value = false
}

onMounted(() => {
  // 延迟一点显示，确保页面完全加载
  setTimeout(checkDisclaimer, 1000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.disclaimer-content {
  text-align: left;
  line-height: 1.6;
}

.alert {
  padding: 15px;
  border-radius: 8px;
  margin-bottom: 20px;
}

.alert-warning {
  background: var(--color-warning-light);
  border: 1px solid var(--color-warning);
  color: var(--color-warning-dark, #856404);
}

.alert h4 {
  margin-top: 0;
  margin-bottom: 8px;
}

.section {
  padding: 15px;
  border-radius: 8px;
  margin-bottom: 15px;
  background: var(--color-bg-tertiary);
}

.section h4 {
  margin-top: 0;
  margin-bottom: 10px;
  color: var(--color-text-primary);
}

.section ul {
  padding-left: 20px;
  margin-bottom: 10px;
}

.section.info {
  background: rgba(12, 84, 96, 0.05);
}
.section.info h4 { color: #0c5460; }

.section.danger {
  background: var(--color-error-light);
}
.section.danger h4 { color: var(--color-error); }

.section.success {
  background: var(--color-success-light);
}
.section.success h4 { color: var(--color-success); }

.section.warning {
  background: var(--color-warning-light);
}
.section.warning h4 { color: var(--color-warning); }

.section.contact a {
  color: var(--color-primary);
  text-decoration: none;
}

.footer-action {
  margin-top: 30px;
  text-align: center;
  padding: 20px;
  background: var(--color-bg-tertiary);
  border-radius: 8px;
}

.timer-tip {
  margin-bottom: 15px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.agree-btn {
  padding: 12px 30px;
  font-size: 1.1rem;
  width: 100%;
}

.agree-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
