<template>
  <div class="tg-guide-page">
    <div class="guide-header">
      <button class="btn btn-outline" @click="goBack">
        <Icon name="chevron-left" :size="14" />
        返回通知设置
      </button>
    </div>

    <div class="guide-card">
      <div class="guide-title">
        <Icon name="info" :size="18" />
        Telegram Bot 功能介绍
      </div>

      <div class="guide-content">
        <p><strong>适用场景</strong></p>
        <ul>
          <li>在 Telegram 里远程触发下载、查看状态、管理订阅。</li>
          <li>接收下载完成/失败通知，并一键重试、删除或进入订阅管理。</li>
          <li>发送媒体到 Bot，支持本地转存（需满足授权与白名单要求）。</li>
        </ul>

        <p><strong>核心能力</strong></p>
        <ul>
          <li>远程命令：状态查看、订阅列表、直播列表、强制下载。</li>
          <li>菜单交互：分页、详情、设置、返回路径统一。</li>
          <li>失败闭环：失败通知内可重试任务、删除任务、进入订阅管理。</li>
          <li>任务中心：<code>/failed</code> 可查看失败任务并处理。</li>
          <li>媒体转存（LIFETIME）：向 Bot 发送视频/图片可转存到本地（永久高级授权专属能力）。</li>
        </ul>

        <p><strong>常用命令</strong></p>
        <pre class="code-block">/status     查看系统状态
/subs       视频订阅列表
/lives      直播订阅列表
/failed     失败任务列表（重试/删除）
/sub <链接> 强制添加订阅
/live <链接> 强制添加直播订阅
/dl <链接>   强制加入下载队列
/music <关键词> 搜索网易云并点选下载
/id         获取当前 Chat ID</pre>

        <p><strong>配置步骤</strong></p>
        <ol>
          <li>在 BotFather 创建机器人并获取 Token。</li>
          <li>在本页面开启 Telegram Bot，填写 Token。</li>
          <li>向你的 Bot 发送 <code>/id</code> 获取 Chat ID，并填入白名单。</li>
          <li>保存后点击“测试连接”，确认推送可达。</li>
        </ol>

        <p><strong>注意事项</strong></p>
        <ul>
          <li>启用 Bot 必须配置 Token 与 Chat ID 白名单。</li>
          <li>首次使用前建议先私聊 Bot 发送一条消息，确保会话已建立。</li>
          <li>通知按钮操作是异步执行，结果会在聊天中回显。</li>
          <li>媒体转存仅对 LIFETIME（永久高级授权）用户开放，且仅白名单 Chat ID 可用。</li>
          <li>转存路径为 <code>/app/downloads/telegram-inbox/&lt;chat_id&gt;/YYYYMMDD/</code>。</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import Icon from '@/components/common/Icon.vue'

const router = useRouter()

function goBack() {
  router.push({ path: '/settings', query: { tab: 'notifications' } })
}
</script>

<style scoped>
.tg-guide-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px;
}

.guide-header {
  margin-bottom: 16px;
}

.guide-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-secondary);
  padding: 20px;
}

.guide-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 14px;
  color: var(--color-text-primary);
}

.guide-content {
  color: var(--color-text-primary);
  line-height: 1.7;
}

.guide-content p {
  margin: 12px 0;
}

.guide-content ul,
.guide-content ol {
  margin: 8px 0 12px;
  padding-left: 20px;
}

.code-block {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 768px) {
  .tg-guide-page {
    padding: 12px;
  }
}
</style>
