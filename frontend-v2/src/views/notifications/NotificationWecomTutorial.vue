<template>
  <div class="tutorial-page">
    <div class="page-header">
      <router-link class="back-link" to="/settings/notifications/wecom">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M15 18l-6-6 6-6" stroke="currentColor" stroke-width="2" fill="none"/>
        </svg>
        返回企业微信设置
      </router-link>
      <h2>🖥️ VPS 中继搭建</h2>
      <p class="page-desc">让本地 Easy-VDL 企业微信机器人能正常收发微信消息（无公网 IP 时使用）。</p>
    </div>

    <div class="section">
      <h3>原理</h3>
      <div class="principle">
        <div class="principle-item">
          <span class="label">📤 出站 API</span>
          <span class="arrow">→</span>
          <span class="value highlight">HTTP 代理 (tinyproxy)</span>
          <span class="arrow">→</span>
          <span class="value">本地 EDL</span>
        </div>
        <div class="principle-item">
          <span class="label">📥 入站回调</span>
          <span class="arrow">→</span>
          <span class="value highlight">VPS:8001 (frps)</span>
          <span class="arrow">→</span>
          <span class="value highlight">frp 隧道</span>
          <span class="arrow">→</span>
          <span class="value">本地 EDL:8001</span>
        </div>
      </div>
    </div>

    <div class="section">
      <h3>1. VPS 安装 Docker</h3>
      <pre class="code-block">curl -fsSL https://get.docker.com | sh</pre>
    </div>

    <div class="section">
      <h3>2. 创建配置目录</h3>
      <pre class="code-block">mkdir -p ~/docker/frps ~/docker/tinyproxy</pre>
    </div>

    <div class="section">
      <h3>3. frps 配置</h3>
      <p class="field-hint">创建 <code>~/docker/frps/frps.toml</code>：</p>
      <pre class="code-block">bindPort = 7100
auth.token = "改成你的密钥"

webServer.addr = "0.0.0.0"
webServer.port = 7101
webServer.user = "admin"
webServer.password = "改成你的密码"</pre>
    </div>

    <div class="section">
      <h3>4. tinyproxy 配置</h3>
      <p class="field-hint">创建 <code>~/docker/tinyproxy/tinyproxy.conf</code>：</p>
      <pre class="code-block">Port 8888
Timeout 600
Allow 你的EDL机器IP</pre>
    </div>

    <div class="section">
      <h3>5. docker-compose.yml</h3>
      <p class="field-hint">创建 <code>~/docker/docker-compose.yml</code>：</p>
      <pre class="code-block">version: "3.8"

services:
  frps:
    image: snowdreamtech/frps:latest
    container_name: frps
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./frps/frps.toml:/etc/frp/frps.toml:ro

  tinyproxy:
    image: andyshinn/tinyproxy:latest
    container_name: tinyproxy
    restart: unless-stopped
    ports:
      - "1080:8888"
    volumes:
      - ./tinyproxy/tinyproxy.conf:/etc/tinyproxy/tinyproxy.conf:ro</pre>
    </div>

    <div class="section">
      <h3>6. 启动</h3>
      <pre class="code-block">cd ~/docker && docker compose up -d</pre>
    </div>

    <div class="section">
      <h3>7. VPS 防火墙放行端口</h3>
      <ul class="port-list">
        <li><code>7100</code> — frp 隧道端口</li>
        <li><code>8001</code> — 微信回调端口</li>
        <li><code>1080</code> — HTTP 代理端口</li>
      </ul>
    </div>

    <div class="section">
      <h3>8. 本地 EDL 机器配置 frpc</h3>
      <p class="field-hint">创建 <code>frpc.toml</code>：</p>
      <pre class="code-block">serverAddr = "你的VPS公网IP"
serverPort = 7100
auth.token = "与frps.toml一致"

[[proxies]]
name = "wecom-bot"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8001
remotePort = 8001</pre>
      <p class="field-hint">启动：<code>frpc -c frpc.toml</code></p>
    </div>

    <div class="section">
      <h3>9. 企业微信后台配置</h3>
      <ul class="port-list">
        <li><strong>可信 IP</strong> — 填入 VPS 公网 IP</li>
        <li><strong>回调 URL</strong> — <code>http://VPS公网IP:8001/api/wecom/callback</code></li>
        <li><strong>API 代理</strong> — 在配置页填 <code>http://VPS公网IP:1080</code></li>
      </ul>
    </div>

    <div class="page-footer">
      <router-link class="btn btn-outline" to="/settings/notifications/wecom">← 返回企业微信设置</router-link>
    </div>
  </div>
</template>

<script setup>
</script>

<style scoped>
.tutorial-page {
  max-width: 860px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.page-header h2 {
  margin: 0;
  font-size: 1.2rem;
  color: var(--color-text-primary);
}

.page-desc {
  margin: 0;
  font-size: 0.9rem;
  color: var(--color-text-tertiary);
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.85rem;
  color: var(--color-primary, #07C160);
  text-decoration: none;
  width: fit-content;
}

.back-link:hover {
  text-decoration: underline;
}

.section {
  background: var(--color-bg-secondary);
  border-radius: 14px;
  padding: 20px 24px;
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-sm);
}

.section h3 {
  margin: 0 0 10px;
  font-size: 1rem;
  color: var(--color-text-primary);
}

.field-hint {
  font-size: 0.85rem;
  color: var(--color-text-tertiary);
  margin: 4px 0;
}

.field-hint code {
  background: var(--color-bg-tertiary, rgba(128,128,128,0.15));
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.8rem;
}

.code-block {
  background: var(--color-bg-tertiary, rgba(0,0,0,0.3));
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 14px 18px;
  font-size: 0.82rem;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre;
  color: var(--color-text-primary);
  margin: 8px 0 0;
}

.port-list {
  margin: 4px 0;
  padding-left: 20px;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}

.port-list li {
  margin: 5px 0;
}

.port-list code {
  background: var(--color-bg-tertiary, rgba(128,128,128,0.15));
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.8rem;
}

.principle {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.principle-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.85rem;
  padding: 8px 12px;
  background: var(--color-bg-tertiary, rgba(128,128,128,0.08));
  border-radius: 8px;
}

.principle-item .label {
  font-weight: 600;
  color: var(--color-text-primary);
  min-width: 80px;
}

.principle-item .value {
  color: var(--color-text-secondary);
}

.principle-item .highlight {
  color: var(--color-primary, #07C160);
  font-weight: 600;
}

.principle-item .arrow {
  color: var(--color-text-tertiary);
}

.page-footer {
  display: flex;
  justify-content: center;
  padding: 12px 0 24px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 24px;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  text-decoration: none;
  transition: background 0.2s;
}

.btn:hover {
  background: var(--color-bg-tertiary);
}
</style>
