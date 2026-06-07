<template>
  <div class="content-view chat-view">
    <div class="chat-container">
      <!-- 顶部操作栏 -->
      <div class="chat-header">
        <div class="chat-header-left">
          <Icon name="zap" :size="20" />
          <h2>AI 助手</h2>
          <span v-if="modelInfo" class="model-badge" @click="showModelPicker = !showModelPicker" :title="modelInfo.title">
            {{ modelInfo.label }} ▾
          </span>
          <!-- 模型切换浮层 -->
          <div v-if="showModelPicker" class="model-picker" @click.stop>
            <div class="picker-header">切换模型</div>
            <div v-for="p in providerList" :key="p.key"
              class="picker-item"
              :class="{ active: p.key === currentProvider, disabled: !p.ready }"
              @click="switchProvider(p.key)">
              <span>{{ p.label }}</span>
              <span v-if="!p.ready" class="picker-status">未配置</span>
              <span v-if="p.key === currentProvider" class="picker-check">✓</span>
            </div>
            <div class="picker-footer" @click="goSettings">⚙️ 前往设置中心配置</div>
          </div>
        </div>
        <div class="chat-header-right">
          <button class="btn-header" @click="toggleHelp">
            <Icon name="info" :size="18" />
            <span>说明</span>
          </button>
          <button class="btn-header" @click="clearChat">
            <Icon name="trash" :size="18" />
            <span>清空</span>
          </button>
        </div>
      </div>

      <!-- 功能说明弹窗 -->
      <div v-if="showHelp" class="help-overlay" @click.self="showHelp = false">
        <div class="help-modal">
          <div class="help-modal-header">
            <span>📖 AI 助手功能说明</span>
            <button class="btn-icon btn-icon-sm" @click="showHelp = false">✕</button>
          </div>
          <div class="help-modal-body">
            <div class="help-group">
              <div class="help-group-title">📺 订阅管理</div>
              <div class="help-items">
                <span>• <b>添加订阅</b> 发博主链接，自动识别平台</span>
                <span>• <b>查看列表</b> 支持按平台筛选、翻页</span>
                <span>• <b>管理订阅</b> 暂停/恢复/删除</span>
                <span>• <b>检查更新</b> 立即检查新视频</span>
              </div>
              <div class="help-tags">抖音 YouTube B站 小红书 TikTok Instagram X 网易云</div>
            </div>
            <div class="help-group">
              <div class="help-group-title">⬇️ 视频下载</div>
              <div class="help-items">
                <span>• <b>下载视频</b> 发链接直接下载</span>
                <span>• <b>查看任务</b> 按状态筛选</span>
                <span>• <b>重试/删除</b> 失败重试、删除任务</span>
              </div>
            </div>
            <div class="help-group">
              <div class="help-group-title">🔴 直播监控</div>
              <div class="help-items">
                <span>• <b>添加监控</b> 开播自动录制</span>
                <span>• <b>查看列表</b> 谁在直播</span>
                <span>• <b>管理监控</b> 暂停/恢复/删除</span>
              </div>
              <div class="help-tags">抖音 B站 小红书 虎牙 斗鱼 快手 YouTube Twitch 咪咕 CC</div>
            </div>
            <div class="help-group">
              <div class="help-group-title">🎬 录制转码</div>
              <div class="help-items">
                <span>• <b>单条转码</b> 直播回放转 MP4</span>
                <span>• <b>批量转码</b> 一键转码所有未转码录制</span>
              </div>
            </div>
            <div class="help-group">
              <div class="help-group-title">📊 系统查询</div>
              <div class="help-items">
                <span>• <b>系统状态</b> CPU/内存/磁盘/统计</span>
                <span>• <b>任务统计</b> 下载队列数量</span>
                <span>• <b>授权信息</b> 有效期/剩余天数</span>
                <span>• <b>失败任务</b> 查看失败下载</span>
              </div>
            </div>
            <div class="help-group">
              <div class="help-group-title">💡 提示</div>
              <div class="help-items">
                <span>• 直接发链接，AI 自动识别处理</span>
                <span>• 支持自然语言：下载这个、谁在直播</span>
                <span>• 在「设置→AI 模型配置」中选择模型</span>
                <span>• 🤖 Telegram 和企业微信同样支持 AI 对话</span>
                <span>• 📱 TG 发链接自动弹出确认键盘</span>
                <span>• 💼 企微支持「查状态」「查订阅」等关键词命令</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 消息列表 -->
      <div class="chat-messages" ref="messagesRef">
        <!-- 欢迎消息 -->
        <div v-if="messages.length === 0" class="chat-welcome">
          <div class="welcome-icon">🤖</div>
          <h3>Easy-VDL AI 助手</h3>
          <p>用自然语言控制平台，试试这些：</p>
          <div class="welcome-suggestions">
            <button v-for="s in suggestions" :key="s" class="suggestion-chip" @click="sendSuggestion(s)">
              {{ s }}
            </button>
          </div>
        </div>

        <!-- 消息列表 -->
        <div
          v-for="(msg, i) in messages"
          :key="i"
          :class="['chat-message', msg.role]"
        >
          <div class="message-avatar">
            <span v-if="msg.role === 'user'">👤</span>
            <span v-else>🤖</span>
          </div>
          <div class="message-body">
            <div class="message-text" v-html="renderMarkdown(msg.text)"></div>
            <!-- 操作结果卡片 -->
            <div v-if="msg.actions && msg.actions.length > 0" class="message-actions">
              <div
                v-for="(action, j) in msg.actions"
                :key="j"
                :class="['action-card', action.result?.success ? 'success' : 'error']"
              >
                <span class="action-icon">{{ action.result?.success ? '✅' : '❌' }}</span>
                <span class="action-name">{{ getActionName(action.tool) }}</span>
                <span v-if="action.result?.name" class="action-detail">{{ action.result.name }}</span>
                <span v-else-if="action.result?.anchor_name" class="action-detail">{{ action.result.anchor_name }}</span>
                <span v-else-if="action.result?.error" class="action-detail error-text">{{ action.result.error }}</span>
              </div>
            </div>
            <div class="message-time">{{ formatTime(msg.time) }}</div>
          </div>
        </div>

        <!-- 加载中 -->
        <div v-if="loading" class="chat-message assistant">
          <div class="message-avatar">🤖</div>
          <div class="message-body">
            <div class="typing-indicator">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="chat-input-area">
        <div class="input-wrapper">
          <textarea
            ref="inputRef"
            v-model="inputText"
            @keydown.enter.exact.prevent="sendMessage"
            @input="autoResize"
            placeholder="输入消息或粘贴链接..."
            rows="1"
            :disabled="loading"
          ></textarea>
          <button
            class="send-btn"
            @click="sendMessage"
            :disabled="!inputText.trim() || loading"
          >
            <Icon name="chevron-up" :size="18" />
          </button>
        </div>
        <div class="input-hint">
          💡 直接发送视频/直播/博主链接，AI 会自动识别并处理
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, watch } from 'vue';
import { chatApi } from '../api/chat';
import { useRouter } from 'vue-router';
import Icon from '../components/common/Icon.vue';

defineOptions({ name: 'ChatView' });

const CHAT_STORAGE_KEY = 'easy_vdl_chat_history';
const CLIENT_ID_KEY = 'easy_vdl_chat_client_id';
const MAX_STORED_MSGS = 50;

// 每个浏览器生成唯一 client_id，避免同一账号多设备共用 session
function getClientId() {
  let id = localStorage.getItem(CLIENT_ID_KEY);
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    localStorage.setItem(CLIENT_ID_KEY, id);
  }
  return id;
}
const sessionClientId = getClientId();

const showHelp = ref(false);
const showModelPicker = ref(false);
const modelInfo = ref(null);
const providerList = ref([]);
const currentProvider = ref('auto');
const router = useRouter();
const token = localStorage.getItem('token') || '';
const authHeader = { Authorization: 'Bearer ' + token };

const PROVIDER_META = {
  deepseek: { label: 'DeepSeek', cfgKey: 'llm_deepseek' },
  minimax: { label: 'MiniMax', cfgKey: 'llm_minimax' },
  compat: { label: '兼容平台', cfgKey: 'llm_compat' },
  ollama: { label: 'Ollama', cfgKey: 'llm_ollama' },
};

function toggleHelp() {
  showHelp.value = !showHelp.value;
}

function providerReady(cfg, key) {
  const meta = PROVIDER_META[key];
  if (!meta) return false;
  const baseUrl = cfg[meta.cfgKey + '_base_url'];
  const model = cfg[meta.cfgKey + '_model'];
  if (key === 'ollama') return !!(baseUrl && model);
  return !!(baseUrl && model && cfg[meta.cfgKey + '_api_key']);
}

async function fetchModel() {
  try {
    const [modelRes, cfgRes] = await Promise.all([
      fetch('/api/chat/model', { headers: authHeader }),
      fetch('/api/ai-config/', { headers: authHeader }),
    ]);
    if (modelRes.ok) {
      const data = await modelRes.json();
      currentProvider.value = data.provider || 'auto';
      if (data.provider && data.provider !== 'none') {
        const labels = { deepseek: 'DeepSeek', minimax: 'MiniMax', compat: '兼容', ollama: 'Ollama' };
        const label = labels[data.provider] || data.provider;
        modelInfo.value = { label, title: `${label} · ${data.model}` };
      } else {
        modelInfo.value = null;
      }
    }
    if (cfgRes.ok) {
      const cfg = await cfgRes.json();
      providerList.value = [
        { key: 'auto', label: '自动（按优先级）', ready: true },
        ...Object.keys(PROVIDER_META).map(k => ({
          key: k,
          label: PROVIDER_META[k].label,
          ready: providerReady(cfg, k),
        })),
        { key: 'none', label: '关闭', ready: true },
      ];
    }
  } catch { /* ignore */ }
}

async function switchProvider(key) {
  showModelPicker.value = false;
  if (key === currentProvider.value) return;
  try {
    await fetch('/api/ai-config/', {
      method: 'POST',
      headers: { ...authHeader, 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm_chat_provider: key }),
    });
    currentProvider.value = key;
    if (key === 'none') {
      modelInfo.value = null;
    }
    // 重新获取模型详情
    const res = await fetch('/api/chat/model', { headers: authHeader });
    if (res.ok) {
      const data = await res.json();
      if (data.provider && data.provider !== 'none') {
        const labels = { deepseek: 'DeepSeek', minimax: 'MiniMax', compat: '兼容', ollama: 'Ollama' };
        const label = labels[data.provider] || data.provider;
        modelInfo.value = { label, title: `${label} · ${data.model}` };
      }
    }
  } catch { /* ignore */ }
}

function goSettings() {
  showModelPicker.value = false;
  router.push('/settings?tab=ai-model');
}

const messages = ref([]);
const inputText = ref('');
const loading = ref(false);
const messagesRef = ref(null);
const inputRef = ref(null);

const suggestions = [
  '查看系统状态',
  '我有哪些订阅？',
  '查看下载任务',
  '谁在直播？',
  '订阅抖音博主',
  '监控这个直播间',
  '订阅有异常的吗',
  '把录制转码成mp4',
  '授权还有多久到期',
  '自动识别这个链接',
];

const TOOL_NAMES = {
  add_subscription: '添加订阅',
  list_subscriptions: '查看订阅',
  pause_subscription: '暂停订阅',
  resume_subscription: '恢复订阅',
  delete_subscription: '删除订阅',
  check_subscription_update: '检查更新',
  download_video: '下载视频',
  list_downloads: '查看任务',
  retry_download: '重试下载',
  delete_download: '删除任务',
  add_live_subscription: '添加直播监控',
  list_live_subscriptions: '查看直播',
  pause_live_subscription: '暂停监控',
  resume_live_subscription: '恢复监控',
  delete_live_subscription: '删除监控',
  check_status: '系统状态',
  check_tasks: '任务统计',
  check_license: '授权信息',
  check_failed_tasks: '失败任务',
  smart_handle_url: '智能处理链接',
  chat_reply: '回复',
};

function getActionName(tool) {
  return TOOL_NAMES[tool] || tool;
}

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

// 从 localStorage 恢复历史
function loadChatHistory() {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      if (Array.isArray(saved)) {
        messages.value = saved.slice(-MAX_STORED_MSGS);
      }
    }
  } catch {
    // 静默失败，不影响正常使用
  }
}

// 保存历史到 localStorage（限制条数）
function saveChatHistory() {
  try {
    const toStore = messages.value.slice(-MAX_STORED_MSGS);
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(toStore));
  } catch {
    // localStorage 可能满，静默忽略
  }
}

function renderMarkdown(text) {
  if (!text) return '';
  // 简单 Markdown 渲染
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // 代码块
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    // 行内代码
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // 粗体
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // 链接 — href 中过滤引号和 <> 防止 XSS，同时保留完整 URL 作为显示文本
    .replace(/(https?:\/\/[^\s<>"']+)/g, function(match) {
      var safeUrl = match.replace(/["']/g, '%27');
      return '<a href="' + safeUrl + '" target="_blank" rel="noopener">' + match + '</a>';
    })
    // 换行
    .replace(/\n/g, '<br>');
  return html;
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight;
    }
  });
}

function autoResize() {
  const el = inputRef.value;
  if (!el) return;
  el.style.height = '';
  // 内容不为空时才展开，为空时保持 rows=1
  if (el.value && el.scrollHeight > el.clientHeight) {
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }
}

async function sendMessage() {
  const text = inputText.value.trim();
  if (!text || loading.value) return;

  // 添加用户消息
  messages.value.push({
    role: 'user',
    text,
    time: Date.now(),
  });
  saveChatHistory();
  inputText.value = '';
  // 立即重置输入框高度，不等待 DOM 更新
  if (inputRef.value) inputRef.value.style.height = '';
  scrollToBottom();
  loading.value = true;

  try {
    const result = await chatApi.send(text, sessionClientId);
    messages.value.push({
      role: 'assistant',
      text: result.reply || '🤔 无法理解，请尝试其他表述',
      actions: result.actions || [],
      time: Date.now(),
    });
    saveChatHistory();
  } catch (err) {
    messages.value.push({
      role: 'assistant',
      text: '❌ 请求失败，请稍后重试',
      actions: [],
      time: Date.now(),
    });
  } finally {
    loading.value = false;
    scrollToBottom();
  }
}

function sendSuggestion(text) {
  inputText.value = text;
  sendMessage();
}

async function clearChat() {
  try {
    await chatApi.clear(sessionClientId);
    messages.value = [];
  } catch {
    messages.value = [];
  }
  localStorage.removeItem(CHAT_STORAGE_KEY);
}

function onClickOutside(e) {
  if (showModelPicker.value) {
    const picker = e.target.closest('.model-picker, .model-badge');
    if (!picker) showModelPicker.value = false;
  }
}

onMounted(() => {
  loadChatHistory();
  fetchModel();
  nextTick(() => scrollToBottom());
  inputRef.value?.focus();
  document.addEventListener('click', onClickOutside);
});
</script>

<style scoped>
.chat-view {
  position: relative;
  height: 100%;
  box-sizing: border-box;
  overflow: hidden;
}

.chat-container {
  position: relative;
  width: 100%;
  max-width: 800px;
  height: 100%;
  margin: 0 auto;
  background: var(--color-card-bg, #fff);
  border-radius: var(--radius-lg, 12px);
  box-shadow: var(--shadow-md, 0 2px 8px rgba(0,0,0,0.08));
  overflow: hidden;
}

/* Header — 固定在顶部 */
.chat-header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--color-border, #e5e7eb);
  background: var(--color-card-bg, #fff);
}

.chat-header-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  position: relative;
}

.chat-header-left h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}

.btn-header {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  padding: 0.375rem 0.75rem;
  border: 1px solid var(--color-border, #e5e7eb);
  border-radius: var(--radius-sm, 8px);
  background: var(--color-card-bg, #fff);
  color: var(--color-text-secondary, #6b7280);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-header:hover {
  background: var(--color-hover-bg, #f3f4f6);
  color: var(--color-text, #1f2937);
  border-color: var(--color-border-hover, #d1d5db);
}

.chat-header-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* Messages — 在 header 和 input 之间滚动 */
.chat-messages {
  position: absolute;
  top: 56px;
  bottom: 72px;
  left: 0;
  right: 0;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* Welcome */
.chat-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  text-align: center;
  gap: 0.75rem;
}

.welcome-icon {
  font-size: 3rem;
}

.chat-welcome h3 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}

.chat-welcome p {
  margin: 0;
  color: var(--color-text-secondary, #6b7280);
  font-size: 0.875rem;
}

.welcome-suggestions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
  margin-top: 0.5rem;
  max-width: 400px;
}

.suggestion-chip {
  padding: 0.5rem 1rem;
  border: 1px solid var(--color-border, #e5e7eb);
  border-radius: 999px;
  background: var(--color-card-bg, #fff);
  color: var(--color-text, #1f2937);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 0.2s;
}

.suggestion-chip:hover {
  border-color: var(--color-primary, #f39c12);
  background: var(--color-primary-light, #fef3c7);
}

/* Message bubble */
.chat-message {
  display: flex;
  gap: 0.625rem;
  max-width: 85%;
}

.chat-message.user {
  align-self: flex-end;
  flex-direction: row-reverse;
  user-select: text;
}

.chat-message.assistant {
  align-self: flex-start;
}

.message-avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.125rem;
  background: var(--color-bg, #f9fafb);
}

.message-body {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.message-text {
  padding: 0.625rem 0.875rem;
  border-radius: var(--radius-md, 10px);
  font-size: 0.875rem;
  line-height: 1.6;
  word-break: break-word;
}

.chat-message.user .message-text {
  background: var(--color-primary, #f39c12);
  color: #fff;
  border-bottom-right-radius: 4px;
  user-select: text;
}

.chat-message.assistant .message-text {
  background: var(--color-bg, #f3f4f6);
  color: var(--color-text, #1f2937);
  border-bottom-left-radius: 4px;
}

.message-text :deep(a) {
  color: inherit;
  text-decoration: underline;
}

.message-text :deep(code) {
  padding: 0.125rem 0.375rem;
  border-radius: 4px;
  background: rgba(0,0,0,0.08);
  font-size: 0.8125rem;
}

.message-text :deep(pre) {
  margin: 0.5rem 0;
  padding: 0.75rem;
  border-radius: var(--radius-sm, 6px);
  background: rgba(0,0,0,0.06);
  overflow-x: auto;
}

.message-text :deep(pre code) {
  padding: 0;
  background: none;
}

.message-time {
  font-size: 0.6875rem;
  color: var(--color-text-secondary, #9ca3af);
  padding: 0 0.25rem;
}

.chat-message.user .message-time {
  text-align: right;
}

/* Model badge */
.model-badge {
  position: relative;
  font-size: 0.6875rem;
  padding: 0.125rem 0.5rem;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.1);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.3);
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
}

.model-badge:hover {
  background: rgba(16, 185, 129, 0.18);
}

/* Model picker dropdown */
.model-picker {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  min-width: 220px;
  background: var(--color-card-bg, #fff);
  border: 1px solid var(--color-border, #e5e7eb);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  z-index: 100;
  overflow: hidden;
}

.picker-header {
  padding: 0.5rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7280);
  border-bottom: 1px solid var(--color-border, #e5e7eb);
}

.picker-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  font-size: 0.8125rem;
  cursor: pointer;
  transition: background 0.15s;
}

.picker-item:hover:not(.disabled) {
  background: var(--color-hover-bg, #f3f4f6);
}

.picker-item.active {
  color: var(--color-primary, #f39c12);
  font-weight: 500;
}

.picker-item.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.picker-status {
  font-size: 0.6875rem;
  color: var(--color-text-tertiary, #9ca3af);
}

.picker-check {
  font-size: 0.75rem;
  color: var(--color-primary, #f39c12);
}

.picker-footer {
  padding: 0.5rem 0.75rem;
  font-size: 0.75rem;
  color: var(--color-text-secondary, #6b7280);
  border-top: 1px solid var(--color-border, #e5e7eb);
  cursor: pointer;
  text-align: center;
}

.picker-footer:hover {
  background: var(--color-hover-bg, #f3f4f6);
}

/* Help modal */
.help-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.help-modal {
  background: var(--color-card-bg, #fff);
  border-radius: 14px;
  width: 100%;
  max-width: 520px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
}

.help-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.875rem 1rem;
  font-size: 0.9rem;
  font-weight: 600;
  border-bottom: 1px solid var(--color-border, #e5e7eb);
}

.btn-icon-sm {
  width: 28px;
  height: 28px;
  font-size: 0.875rem;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--color-text-secondary, #9ca3af);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon-sm:hover {
  background: var(--color-hover-bg, #f3f4f6);
  color: var(--color-text, #1f2937);
}

.help-modal-body {
  padding: 0.75rem 1rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.help-group-title {
  font-size: 0.8125rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
}

.help-items {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  font-size: 0.75rem;
  color: var(--color-text-secondary, #6b7280);
  line-height: 1.6;
}

.help-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-top: 0.25rem;
  font-size: 0.6875rem;
  color: var(--color-text-tertiary, #9ca3af);
}

/* Action cards */
.message-actions {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  margin-top: 0.375rem;
}

.action-card {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.625rem;
  border-radius: var(--radius-sm, 6px);
  font-size: 0.8125rem;
}

.action-card.success {
  background: rgba(16, 185, 129, 0.08);
  color: #059669;
}

.action-card.error {
  background: rgba(239, 68, 68, 0.08);
  color: #dc2626;
}

.action-name {
  font-weight: 500;
}

.action-detail {
  color: var(--color-text-secondary, #6b7280);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}

.error-text {
  color: #dc2626;
}

/* Typing indicator */
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 0.75rem 1rem;
  background: var(--color-bg, #f3f4f6);
  border-radius: var(--radius-md, 10px);
  border-bottom-left-radius: 4px;
}

.typing-indicator span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-text-secondary, #9ca3af);
  animation: typing 1.4s infinite;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
  30% { opacity: 1; transform: scale(1); }
}

/* Input area */
.chat-input-area {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 10;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--color-border, #e5e7eb);
  background: var(--color-card-bg, #fff);
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  padding: 0.5rem;
  border: 1px solid var(--color-border, #e5e7eb);
  border-radius: var(--radius-lg, 12px);
  background: var(--color-bg, #f9fafb);
  transition: border-color 0.2s;
}

.input-wrapper:focus-within {
  border-color: var(--color-primary, #f39c12);
}

.input-wrapper textarea {
  flex: 1;
  border: none;
  background: transparent;
  resize: none;
  outline: none;
  font-size: 0.875rem;
  line-height: 1.5;
  padding: 0.25rem 0.5rem;
  max-height: 120px;
  font-family: inherit;
  color: var(--color-text, #1f2937);
}

.input-wrapper textarea::placeholder {
  color: var(--color-text-secondary, #9ca3af);
}

.send-btn {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: var(--color-primary, #f39c12);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
}

.send-btn:hover:not(:disabled) {
  background: var(--color-primary-dark, #e67e22);
  transform: scale(1.05);
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.input-hint {
  font-size: 0.75rem;
  color: var(--color-text-secondary, #9ca3af);
  text-align: center;
  margin-top: 0.5rem;
}

/* Mobile */
@media (max-width: 768px) {
  .chat-view {
    height: 100%;
    padding: 0;
    overflow: hidden;
  }

  .chat-container {
    border-radius: 0;
    max-width: 100%;
  }

  .chat-messages {
    top: 52px;
    bottom: 68px;
  }

  .chat-message {
    max-width: 90%;
  }

  .welcome-suggestions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
    align-items: stretch;
  }

  .suggestion-chip {
    text-align: center;
    white-space: normal;
    font-size: 0.75rem;
    padding: 0.5rem 0.75rem;
  }
}

/* Dark theme */
[data-theme="dark"] .chat-message.assistant .message-text {
  background: var(--color-bg, #1f2937);
}

[data-theme="dark"] .typing-indicator {
  background: var(--color-bg, #1f2937);
}

[data-theme="dark"] .input-wrapper {
  background: var(--color-bg, #1f2937);
}

[data-theme="dark"] .message-text :deep(code) {
  background: rgba(255,255,255,0.1);
}

[data-theme="dark"] .message-text :deep(pre) {
  background: rgba(255,255,255,0.06);
}
</style>
