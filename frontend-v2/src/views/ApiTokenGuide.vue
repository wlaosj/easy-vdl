<template>
  <div class="api-token-guide-page">
    <div class="guide-header">
      <button class="btn btn-outline" @click="goBack">
        <Icon name="chevron-left" :size="14" />
        返回 API Token 管理
      </button>
    </div>

    <div class="guide-card">
      <div class="guide-title">
        <Icon name="info" :size="18" />
        如何使用 API Token？
      </div>
      <div class="guide-content">
        <p><strong>1. 创建 Token</strong></p>
        <p>在设置页中创建 Token，建议为每个外部应用创建独立的 Token，便于管理和撤销。</p>

        <p><strong>2. 使用 Token 调用 API</strong></p>
        <p>在 HTTP 请求头中添加 Token：</p>
        <pre class="code-block"># 方式1：使用 X-API-Token 头（推荐）
X-API-Token: your_token_here

# 方式2：使用 Authorization Bearer
Authorization: Bearer your_token_here</pre>

        <div class="security-warning">
          <p><strong>安全警告：HTTP vs HTTPS</strong></p>
          <ul>
            <li><strong>HTTP 风险：</strong>Token 以明文传输，容易被中间人攻击窃取，存在安全风险</li>
            <li><strong>HTTPS 推荐：</strong>生产环境或公网访问时，强烈建议使用 HTTPS 加密传输</li>
            <li><strong>内网使用：</strong>仅在可信内网环境中使用 HTTP，并确保网络隔离</li>
          </ul>
        </div>

        <p><strong>3. 支持的 API 接口</strong></p>
        <p>以下接口支持使用 API Token 调用（示例中使用 <code>http://</code>，生产环境请使用 <code>https://</code>）：</p>
        <div class="auth-legend">
          <p><strong>权限说明：</strong></p>
          <ul>
            <li><span class="tag tag-free">免费可用</span> 仅需有效 Token（JWT / API Token）</li>
            <li><span class="tag tag-pro">需高级授权</span> 除 Token 外，还需系统高级授权有效</li>
          </ul>
        </div>

        <div class="api-examples">
          <div class="api-example">
            <p><strong>① 抖音视频下载</strong> <span class="tag tag-free">免费可用</span></p>
            <pre class="code-block">curl -X POST "http://your-server:port/api/dyd/download" \
  -H "X-API-Token: your_token_here" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.douyin.com/video/xxx",
    "generate_nfo": true
  }'</pre>
          </div>

          <div class="api-example">
            <p><strong>② 小红书视频下载</strong> <span class="tag tag-free">免费可用</span></p>
            <pre class="code-block">curl -X POST "http://your-server:port/api/xhs/download" \
  -H "X-API-Token: your_token_here" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.xiaohongshu.com/explore/xxx",
    "generate_nfo": true
  }'</pre>
          </div>

          <div class="api-example">
            <p><strong>③ YouTube 视频下载（自动最高画质）</strong> <span class="tag tag-free">免费可用</span></p>
            <pre class="code-block">curl -X POST "http://your-server:port/api/ytd/download" \
  -H "X-API-Token: your_token_here" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=xxx"
  }'</pre>
          </div>

          <div class="api-example">
            <p><strong>④ B站视频下载（自动最高画质）</strong> <span class="tag tag-free">免费可用</span></p>
            <pre class="code-block">curl -X POST "http://your-server:port/api/ytd/download" \
  -H "X-API-Token: your_token_here" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.bilibili.com/video/xxx"
  }'</pre>
            <p class="api-note">注意：YouTube 和 B站共用同一个接口，系统会根据 URL 自动识别平台。</p>
          </div>

          <div class="api-example">
            <p><strong>⑤ 获取直播订阅列表（用于 OpenClaw 等 AI 工具同步）</strong> <span class="tag tag-pro">需高级授权</span></p>
            <pre class="code-block">curl -X GET "http://your-server:port/api/live/subscriptions" \
  -H "X-API-Token: your_token_here"</pre>
          </div>

          <div class="api-example">
            <p><strong>⑥ 添加直播间订阅（用于 OpenClaw 等 AI 工具自动录制）</strong> <span class="tag tag-pro">需高级授权</span></p>
            <pre class="code-block">curl -X POST "http://your-server:port/api/live/subscriptions?room_url=https://live.douyin.com/123456&platform=douyin&quality=原画&auto_record=true&check_interval=60&notification_enabled=true" \
  -H "X-API-Token: your_token_here"</pre>
            <p class="api-note">说明：直播订阅接口仍受高级授权控制，需在系统已授权状态下调用。</p>
          </div>

          <div class="api-example">
            <p><strong>⑦ 刷新直播状态（触发即时探测）</strong> <span class="tag tag-pro">需高级授权</span></p>
            <pre class="code-block">curl -X POST "http://your-server:port/api/live/status/refresh/{sub_id}" \
  -H "X-API-Token: your_token_here"</pre>
          </div>

          <div class="api-example">
            <p><strong>⑧ 手动开始 / 停止录制</strong> <span class="tag tag-pro">需高级授权</span></p>
            <pre class="code-block"># 开始录制
curl -X POST "http://your-server:port/api/live/record/start/{sub_id}" \
  -H "X-API-Token: your_token_here"

# 停止录制
curl -X POST "http://your-server:port/api/live/record/stop/{sub_id}" \
  -H "X-API-Token: your_token_here"</pre>
          </div>

          <div class="api-example">
            <p><strong>⑨ 查询录制状态 / 全局直播状态</strong> <span class="tag tag-pro">需高级授权</span></p>
            <pre class="code-block"># 单个订阅录制状态
curl -X GET "http://your-server:port/api/live/record/status/{sub_id}" \
  -H "X-API-Token: your_token_here"

# 全局直播状态列表
curl -X GET "http://your-server:port/api/live/status" \
  -H "X-API-Token: your_token_here"</pre>
          </div>
        </div>

        <p><strong>4. 常见错误排查</strong></p>
        <div class="troubleshooting">
          <ul>
            <li><strong>务必显式带头：</strong>每次请求都要显式传 <code>X-API-Token</code>，不要依赖工具自动继承上下文。</li>
            <li><strong>环境变量先加载：</strong>如果通过环境变量注入 token（例如 OpenClaw），请确保在同一条命令上下文先加载 secrets，再发起 curl 请求。</li>
            <li><strong>错误文案对照：</strong><code>无效的认证凭据</code> 通常是请求头未带上 token；<code>无效的 API Token</code> 通常是 token 值错误、失效或被禁用。</li>
          </ul>
        </div>

        <p><strong>5. 使用场景示例</strong></p>
        <div class="use-cases">
          <div class="use-case">
            <p><strong>iOS 快捷指令（Shortcuts）</strong></p>
            <p>在快捷指令中使用“获取 URL 内容”操作：</p>
            <ol>
              <li>方法选择：POST</li>
              <li>URL：<code>http://your-server:port/api/dyd/download</code></li>
              <li>请求头：添加 <code>X-API-Token</code>，值为你的 Token</li>
              <li>请求体：JSON，内容为 <code>{"url":"视频链接","generate_nfo":true}</code></li>
            </ol>
          </div>

          <div class="use-case">
            <p><strong>浏览器插件</strong></p>
            <p>在插件中使用 <code>fetch</code> API：</p>
            <pre class="code-block">fetch('http://your-server:port/api/dyd/download', {
  method: 'POST',
  headers: {
    'X-API-Token': 'your_token_here',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    url: videoUrl,
    generate_nfo: true
  })
})</pre>
          </div>
        </div>

        <p><strong>6. 安全建议</strong></p>
        <ul>
          <li><strong>使用 HTTPS：</strong>生产环境或公网访问时，必须使用 HTTPS 加密传输</li>
          <li><strong>Token 保管：</strong>不要泄露，不要提交到代码仓库</li>
          <li><strong>设置过期：</strong>建议设置合理过期时间并定期轮换</li>
          <li><strong>及时撤销：</strong>Token 泄露或不再使用时立即删除</li>
          <li><strong>最小权限：</strong>为不同应用创建独立 Token</li>
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
  router.push({ path: '/settings', query: { tab: 'api-tokens' } })
}
</script>

<style scoped>
.api-token-guide-page {
  max-width: 980px;
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

.security-warning {
  background: #fff3cd;
  border-left: 4px solid #ffc107;
  border-radius: 4px;
  padding: 12px;
  margin: 16px 0;
  color: #856404;
}

.auth-legend {
  margin: 12px 0 14px;
  padding: 10px 12px;
  background: var(--color-bg-tertiary);
  border: 1px solid var(--color-border);
  border-radius: 8px;
}

.troubleshooting {
  margin: 12px 0 16px;
  padding: 10px 12px;
  background: #fff8e1;
  border: 1px solid #ffe082;
  border-radius: 8px;
}

.tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 20px;
  font-weight: 600;
  margin-left: 4px;
  vertical-align: middle;
}

.tag-free {
  color: #0f5132;
  background: #d1e7dd;
  border: 1px solid #badbcc;
}

.tag-pro {
  color: #664d03;
  background: #fff3cd;
  border: 1px solid #ffecb5;
}

.api-note {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.use-case {
  margin-bottom: 16px;
}

@media (max-width: 768px) {
  .api-token-guide-page {
    padding: 12px;
  }
}
</style>
