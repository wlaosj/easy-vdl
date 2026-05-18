<template>
  <div class="cookie-settings">
    <div class="cookie-top-tips">
      <!-- Security Notice -->
      <div class="security-tip">
        <div class="notice-icon security">
          <Icon name="shield" :size="20" />
        </div>
        <div class="notice-content">
          <span class="notice-title security">安全提示（重要）</span>
          <div class="notice-desc">
            <p class="security-desc">
              Cookie 等同于“登录凭证”。一旦泄露，可能导致账号被盗用、隐私暴露，甚至被平台判定异常登录。
            </p>
            <ul class="security-list">
              <li><b>不要把 Cookie 文件夹暴露在公网</b>（不要通过 Nginx/反代/文件服务对外开放下载目录或配置目录）。</li>
              <li><b>不要把 cookies.txt 发给任何人</b>，也不要上传到网盘/工单/截图分享；日志里也不要打印 Cookie 内容。</li>
              <li><b>最小权限</b>：Cookie 文件目录建议仅容器/应用用户可读写（例如 600/700）。</li>
              <li><b>建议用内网访问管理页面</b>；如必须公网访问，请开启强密码/鉴权/HTTPS/访问控制（白名单、基础认证等）。</li>
              <li><b>怀疑泄露请立刻处理</b>：平台退出所有设备/修改密码/重新登录并生成新的 Cookie，然后在此重新保存。</li>
            </ul>
          </div>
        </div>
      </div>

      <!-- Plugin Recommendation -->
      <div class="plugin-tip">
        <div class="notice-icon">
          <Icon name="link" :size="20" />
        </div>
        <div class="notice-content">
          <span class="notice-title">推荐工具</span>
          <p class="notice-desc">
            建议使用浏览器插件获取 Cookie: 
            <a href="https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc" target="_blank" class="plugin-link">
              Get cookies.txt LOCALLY
            </a>
          </p>
        </div>
      </div>
    </div>

    <!-- License Warning -->
    <div class="auth-warning" v-if="!systemStore.hasLicense && (settingsStore.cookieStatus.youtube.autoUpdate || settingsStore.cookieStatus.bilibili.autoUpdate || settingsStore.cookieStatus.xiaohongshu.autoUpdate)">
      <div class="warning-header">
        <Icon name="shield" :size="18" />
        <span class="warning-title">功能受限</span>
      </div>
      <p class="warning-desc">
        YouTube、B站和小红书 Cookie 自动更新功能需要有效授权。您可以手动保存但无法自动定期更新。
      </p>
    </div>

    <!-- YouTube Cookie -->
    <div class="card" :class="{ 'highlight-card': highlightPlatform === 'youtube' }">
      <div class="card-header">
        <div class="header-main">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="#FF0000">
            <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
          </svg>
          <span class="platform-name">YouTube Cookie</span>
          <span :class="['status-tag', settingsStore.cookieStatus.youtube.exists ? 'success' : 'error']">
            {{ settingsStore.cookieStatus.youtube.exists ? '已配置' : '未配置' }}
          </span>
        </div>
        <div class="header-stats" v-if="settingsStore.cookieStatus.youtube.exists">
          <div class="stat-pill"><span class="label">大小:</span> {{ settingsStore.cookieStatus.youtube.fileSize }}</div>
          <div class="stat-pill"><span class="label">最后更新:</span> {{ formatDate(settingsStore.cookieStatus.youtube.lastUpdate) }}</div>
          <div class="stat-pill next-update" v-if="settingsStore.cookieStatus.youtube.autoUpdate"><span class="label">下次更新:</span> {{ formatDate(settingsStore.cookieStatus.youtube.nextUpdate) }}</div>
        </div>
      </div>
      
      <div class="card-body">
        <div class="config-section">
          <div class="section-label">
            <span class="title">增强功能</span>
            <span class="desc">通过浏览器自动同步 Cookie</span>
          </div>
          <div class="section-controls">
            <button @click="updateCookieNow('youtube')" :disabled="!systemStore.hasLicense" class="btn btn-primary btn-xs">
              <Icon name="refresh" :size="14" />
              立即同步
            </button>
            <div class="auto-update">
              <span class="toggle-text">自动更新</span>
              <label class="switch" :class="{ disabled: !systemStore.hasLicense }">
                <input 
                  type="checkbox" 
                  :checked="settingsStore.cookieStatus.youtube.autoUpdate"
                  @change="toggleAutoUpdate('youtube')"
                  :disabled="!systemStore.hasLicense"
                >
                <span class="switch-slider"></span>
              </label>
              <select 
                v-if="settingsStore.cookieStatus.youtube.autoUpdate" 
                v-model="youtubeInterval" 
                @change="saveAutoUpdate('youtube')" 
                class="mini-select"
              >
                <option :value="10">10m</option>
                <option :value="30">30m</option>
                <option :value="60">1h</option>
                <option :value="120">2h</option>
                <option :value="1440">24h</option>
              </select>
            </div>
          </div>
        </div>

        <div class="manual-section">
          <div class="input-header">
            <span class="title">手动输入</span>
            <div class="input-actions">
              <button @click="saveYoutubeCookie" :disabled="settingsStore.saving" class="btn btn-primary btn-xs">保存</button>
              <button @click="openClearModal('youtube')" class="btn btn-danger btn-xs">清除</button>
            </div>
          </div>
          <textarea 
            v-model="youtubeCookie" 
            placeholder="粘贴 Netscape 格式的 Cookie..."
            class="form-textarea"
            style="min-height: 80px;"
          ></textarea>
        </div>
      </div>
    </div>

    <!-- Bilibili Cookie -->
    <div class="card" :class="{ 'highlight-card': highlightPlatform === 'bilibili' }">
      <div class="card-header">
        <div class="header-main">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="#00A1D6">
            <path d="M17.813 4.653h.854c1.51.054 2.769.578 3.773 1.574 1.004.995 1.524 2.249 1.56 3.76v7.36c-.036 1.51-.556 2.769-1.56 3.773s-2.262 1.524-3.773 1.56H5.333c-1.51-.036-2.769-.556-3.773-1.56S.036 18.858 0 17.347v-7.36c.036-1.511.556-2.765 1.56-3.76 1.004-.996 2.262-1.52 3.773-1.574h.774l-1.174-1.12a1.234 1.234 0 0 1-.373-.906c0-.356.124-.658.373-.907l.027-.027c.267-.249.573-.373.92-.373.347 0 .653.124.92.373L9.653 4.44c.071.071.134.142.187.213h4.267a.836.836 0 0 1 .16-.213l2.853-2.747c.267-.249.573-.373.92-.373.347 0 .662.151.929.4.267.249.391.551.391.907 0 .355-.124.657-.373.906zM5.333 7.24c-.746.018-1.373.276-1.88.773-.506.498-.769 1.13-.786 1.894v7.52c.017.764.28 1.395.786 1.893.507.498 1.134.756 1.88.773h13.334c.746-.017 1.373-.275 1.88-.773.506-.498.769-1.129.786-1.893v-7.52c-.017-.765-.28-1.396-.786-1.894-.507-.497-1.134-.755-1.88-.773zM8 11.107c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c0-.373.129-.689.386-.947.258-.257.574-.386.947-.386zm8 0c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c.017-.391.15-.711.4-.96.249-.249.56-.373.933-.373Z"/>
          </svg>
          <span class="platform-name">B站 Cookie</span>
          <span :class="['status-tag', settingsStore.cookieStatus.bilibili.exists ? 'success' : 'error']">
            {{ settingsStore.cookieStatus.bilibili.exists ? '已配置' : '未配置' }}
          </span>
        </div>
        <div class="header-stats" v-if="settingsStore.cookieStatus.bilibili.exists">
          <div class="stat-pill"><span class="label">大小:</span> {{ settingsStore.cookieStatus.bilibili.fileSize }}</div>
          <div class="stat-pill"><span class="label">最后更新:</span> {{ formatDate(settingsStore.cookieStatus.bilibili.lastUpdate) }}</div>
          <div class="stat-pill next-update" v-if="settingsStore.cookieStatus.bilibili.autoUpdate"><span class="label">下次更新:</span> {{ formatDate(settingsStore.cookieStatus.bilibili.nextUpdate) }}</div>
        </div>
      </div>
      
      <div class="card-body">
        <div class="config-section">
          <div class="section-label">
            <span class="title">增强功能</span>
            <span class="desc">通过浏览器自动同步 Cookie</span>
          </div>
          <div class="section-controls">
            <button @click="updateCookieNow('bilibili')" :disabled="!systemStore.hasLicense" class="btn btn-primary btn-xs">
              <Icon name="refresh" :size="14" />
              立即同步
            </button>
            <div class="auto-update">
              <span class="toggle-text">自动更新</span>
              <label class="switch" :class="{ disabled: !systemStore.hasLicense }">
                <input 
                  type="checkbox" 
                  :checked="settingsStore.cookieStatus.bilibili.autoUpdate"
                  @change="toggleAutoUpdate('bilibili')"
                  :disabled="!systemStore.hasLicense"
                >
                <span class="switch-slider"></span>
              </label>
              <select 
                v-if="settingsStore.cookieStatus.bilibili.autoUpdate" 
                v-model="bilibiliInterval" 
                @change="saveAutoUpdate('bilibili')" 
                class="mini-select"
              >
                <option :value="10">10m</option>
                <option :value="30">30m</option>
                <option :value="60">1h</option>
                <option :value="120">2h</option>
                <option :value="1440">24h</option>
              </select>
            </div>
          </div>
        </div>

        <div class="manual-section">
          <div class="input-header">
            <span class="title">手动输入</span>
            <div class="input-actions">
              <button @click="saveBilibiliCookie" :disabled="settingsStore.saving" class="btn btn-primary btn-xs">保存</button>
              <button @click="openClearModal('bilibili')" class="btn btn-danger btn-xs">清除</button>
            </div>
          </div>
          <textarea 
            v-model="bilibiliCookie" 
            placeholder="粘贴 Netscape 格式的 Cookie..."
            class="form-textarea"
            style="min-height: 80px;"
          ></textarea>
        </div>
      </div>
    </div>

    <!-- 小红书 Cookie -->
    <div class="card" :class="{ 'highlight-card': highlightPlatform === 'xiaohongshu' }">
      <div class="card-header">
        <div class="header-main">
          <svg width="24" height="24" viewBox="0 0 24 24" aria-label="xiaohongshu-logo">
            <rect x="1.5" y="1.5" width="21" height="21" rx="5" fill="#FF2442" />
            <text x="12" y="14.2" text-anchor="middle" font-size="7.2" font-weight="700" fill="#FFFFFF" font-family="Arial, sans-serif">XHS</text>
          </svg>
          <span class="platform-name">小红书 Cookie</span>
          <span :class="['status-tag', settingsStore.cookieStatus.xiaohongshu.exists ? 'success' : 'error']">
            {{ settingsStore.cookieStatus.xiaohongshu.exists ? '已配置' : '未配置' }}
          </span>
        </div>
        <div class="header-stats" v-if="settingsStore.cookieStatus.xiaohongshu.exists">
          <div class="stat-pill"><span class="label">大小:</span> {{ settingsStore.cookieStatus.xiaohongshu.fileSize }}</div>
          <div class="stat-pill"><span class="label">最后更新:</span> {{ formatDate(settingsStore.cookieStatus.xiaohongshu.lastUpdate) }}</div>
          <div class="stat-pill next-update" v-if="settingsStore.cookieStatus.xiaohongshu.autoUpdate"><span class="label">下次更新:</span> {{ formatDate(settingsStore.cookieStatus.xiaohongshu.nextUpdate) }}</div>
        </div>
      </div>
      
      <div class="card-body">
        <div class="config-section">
          <div class="section-label">
            <span class="title">增强功能</span>
            <span class="desc">通过浏览器自动同步 Cookie</span>
          </div>
          <div class="section-controls">
            <button @click="updateCookieNow('xiaohongshu')" :disabled="!systemStore.hasLicense" class="btn btn-primary btn-xs">
              <Icon name="refresh" :size="14" />
              立即同步
            </button>
            <div class="auto-update">
              <span class="toggle-text">自动更新</span>
              <label class="switch" :class="{ disabled: !systemStore.hasLicense }">
                <input 
                  type="checkbox" 
                  :checked="settingsStore.cookieStatus.xiaohongshu.autoUpdate"
                  @change="toggleAutoUpdate('xiaohongshu')"
                  :disabled="!systemStore.hasLicense"
                >
                <span class="switch-slider"></span>
              </label>
              <select 
                v-if="settingsStore.cookieStatus.xiaohongshu.autoUpdate" 
                v-model="xiaohongshuInterval" 
                @change="saveAutoUpdate('xiaohongshu')" 
                class="mini-select"
              >
                <option :value="10">10m</option>
                <option :value="30">30m</option>
                <option :value="60">1h</option>
                <option :value="120">2h</option>
                <option :value="1440">24h</option>
              </select>
            </div>
          </div>
        </div>

        <div class="manual-section">
          <div class="input-header">
            <span class="title">手动输入</span>
            <div class="input-actions">
              <button @click="saveXiaohongshuCookie" :disabled="settingsStore.saving" class="btn btn-primary btn-xs">保存</button>
              <button @click="openClearModal('xiaohongshu')" class="btn btn-danger btn-xs">清除</button>
            </div>
          </div>
          <textarea 
            v-model="xiaohongshuCookie" 
            placeholder="粘贴 Netscape 格式的 Cookie..."
            class="form-textarea"
            style="min-height: 80px;"
          ></textarea>
        </div>
      </div>
    </div>

    <!-- TikTok Cookie -->
    <div class="card" id="cookie-platform-tiktok" :class="{ 'highlight-card': highlightPlatform === 'tiktok' }">
      <div class="card-header">
        <div class="header-main">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="#FE2C55">
            <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.1z"/>
          </svg>
          <span class="platform-name">TikTok Cookie</span>
          <span :class="['status-tag', settingsStore.cookieStatus.tiktok.exists ? 'success' : 'error']">
            {{ settingsStore.cookieStatus.tiktok.exists ? '已配置' : '未配置' }}
          </span>
        </div>
        <div class="header-stats" v-if="settingsStore.cookieStatus.tiktok.exists">
          <div class="stat-pill"><span class="label">大小:</span> {{ settingsStore.cookieStatus.tiktok.fileSize }}</div>
          <div class="stat-pill"><span class="label">最后更新:</span> {{ formatDate(settingsStore.cookieStatus.tiktok.lastUpdate) }}</div>
        </div>
      </div>
      
      <div class="card-body">
        <div class="manual-section no-border">
          <div class="input-header">
            <span class="title">手动输入</span>
            <div class="input-actions">
              <button @click="saveTiktokCookie" :disabled="settingsStore.saving" class="btn btn-primary btn-xs">保存</button>
              <button @click="openClearModal('tiktok')" class="btn btn-danger btn-xs">清除</button>
            </div>
          </div>
          <textarea 
            v-model="tiktokCookie" 
            placeholder="粘贴 Netscape 格式的 Cookie..."
            class="form-textarea"
            style="min-height: 80px;"
          ></textarea>
        </div>
      </div>
    </div>

    <!-- Instagram 账号密码 -->
    <div class="card" id="cookie-platform-instagram" :class="{ 'highlight-card': highlightPlatform === 'instagram' }">
      <div class="card-header">
        <div class="header-main">
          <svg width="24" height="24" viewBox="0 0 24 24" aria-label="instagram-logo">
            <defs>
              <linearGradient id="instagram-cookie-gradient" x1="2" y1="22" x2="22" y2="2" gradientUnits="userSpaceOnUse">
                <stop offset="0" stop-color="#F58529" />
                <stop offset="0.45" stop-color="#DD2A7B" />
                <stop offset="1" stop-color="#515BD4" />
              </linearGradient>
            </defs>
            <rect x="2" y="2" width="20" height="20" rx="5" fill="url(#instagram-cookie-gradient)" />
            <circle cx="12" cy="12" r="4.2" fill="none" stroke="#fff" stroke-width="2" />
            <circle cx="17.2" cy="6.8" r="1.3" fill="#fff" />
          </svg>
          <span class="platform-name">Instagram 账号</span>
          <span :class="['status-tag', settingsStore.cookieStatus.instagram.exists ? 'success' : 'error']">
            {{ settingsStore.cookieStatus.instagram.exists ? '已配置' : '未配置' }}
          </span>
        </div>
        <div class="header-stats" v-if="settingsStore.cookieStatus.instagram.exists">
          <div class="stat-pill"><span class="label">账号:</span> {{ settingsStore.cookieStatus.instagram.username }}</div>
        </div>
      </div>

      <div class="card-body">
        <div class="manual-section no-border">
          <div class="input-header">
            <span class="title">账号密码登录（推荐使用小号，比 Cookie 更稳定）</span>
            <div class="input-actions">
              <button @click="saveInstagramCookie" :disabled="settingsStore.saving" class="btn btn-primary btn-xs">保存</button>
              <button @click="openClearModal('instagram')" class="btn btn-danger btn-xs">清除</button>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">用户名</label>
            <input
              v-model="instagramUsername"
              type="text"
              placeholder="Instagram 用户名"
              class="form-input"
            />
          </div>
          <div class="form-group">
            <label class="form-label">密码</label>
            <input
              v-model="instagramPassword"
              type="password"
              placeholder="Instagram 密码"
              class="form-input"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- X Cookie -->
    <div class="card" id="cookie-platform-x" :class="{ 'highlight-card': highlightPlatform === 'x' }">
      <div class="card-header">
        <div class="header-main">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="#111111">
            <path d="M18.25 2H21l-6.6 7.54L22 22h-6.16l-4.83-6.1L5.4 22H2.65l7.05-8.06L2 2h6.31l4.36 5.5L18.25 2z"/>
          </svg>
          <span class="platform-name">X Cookie</span>
          <span :class="['status-tag', settingsStore.cookieStatus.x.exists ? 'success' : 'error']">
            {{ settingsStore.cookieStatus.x.exists ? '已配置' : '未配置' }}
          </span>
        </div>
        <div class="header-stats" v-if="settingsStore.cookieStatus.x.exists">
          <div class="stat-pill"><span class="label">大小:</span> {{ settingsStore.cookieStatus.x.fileSize }}</div>
          <div class="stat-pill"><span class="label">最后更新:</span> {{ formatDate(settingsStore.cookieStatus.x.lastUpdate) }}</div>
        </div>
      </div>
      
      <div class="card-body">
        <div class="manual-section no-border">
          <div class="input-header">
            <span class="title">手动输入</span>
            <div class="input-actions">
              <button @click="saveXCookie" :disabled="settingsStore.saving" class="btn btn-primary btn-xs">保存</button>
              <button @click="openClearModal('x')" class="btn btn-danger btn-xs">清除</button>
            </div>
          </div>
          <textarea 
            v-model="xCookie" 
            placeholder="粘贴 Netscape 格式的 Cookie..."
            class="form-textarea"
            style="min-height: 80px;"
          ></textarea>
        </div>
      </div>
    </div>

    <!-- 网易云音乐 Cookie -->
    <div class="card" id="cookie-platform-netease" :class="{ 'highlight-card': highlightPlatform === 'netease' }">
      <div class="card-header">
        <div class="header-main">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="#E53E3E">
            <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
          </svg>
          <span class="platform-name">网易云音乐 Cookie</span>
          <span :class="['status-tag', settingsStore.cookieStatus.netease.exists ? 'success' : 'error']">
            {{ settingsStore.cookieStatus.netease.exists ? '已配置' : '未配置' }}
          </span>
        </div>
        <div class="header-stats" v-if="settingsStore.cookieStatus.netease.exists">
          <div class="stat-pill"><span class="label">大小:</span> {{ settingsStore.cookieStatus.netease.fileSize }}</div>
          <div class="stat-pill"><span class="label">最后更新:</span> {{ formatDate(settingsStore.cookieStatus.netease.lastUpdate) }}</div>
        </div>
      </div>
      
      <div class="card-body">
        <div class="manual-section no-border">
          <div class="input-header">
            <span class="title">手动输入</span>
            <div class="input-actions">
              <button @click="saveNeteaseCookie" :disabled="settingsStore.saving" class="btn btn-primary btn-xs">保存</button>
              <button @click="openClearModal('netease')" class="btn btn-danger btn-xs">清除</button>
            </div>
          </div>
          <textarea 
            v-model="neteaseCookie" 
            placeholder="粘贴 Netscape 格式的 Cookie..."
            class="form-textarea"
            style="min-height: 80px;"
          ></textarea>
        </div>
      </div>
    </div>

    <!-- 清除确认弹窗 -->
    <Modal
      v-model:show="showClearModal"
      :title="clearModalTitle"
      type="warning"
      width="400px"
      :show-confirm="false"
    >
      <div class="confirm-content">
        <p>确定要清除 {{ platformNames[pendingPlatform] }} 的 Cookie 吗？</p>
        <p class="sub-text">清除后需要重新保存 Cookie 才能正常使用相关功能。</p>
      </div>
      
      <template #footer>
        <button class="btn btn-secondary" @click="showClearModal = false">取消</button>
        <button class="btn btn-danger" @click="confirmClear">确定清除</button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'
import { useToast } from '@/composables/useToast'
import Icon from '@/components/common/Icon.vue'
import Modal from '@/components/common/Modal.vue'

const settingsStore = useSettingsStore()
const systemStore = useSystemStore()
const toast = useToast()
const route = useRoute()

const youtubeCookie = ref('')
const bilibiliCookie = ref('')
const tiktokCookie = ref('')
const instagramUsername = ref('')
const instagramPassword = ref('')
const xCookie = ref('')
const neteaseCookie = ref('')
const xiaohongshuCookie = ref('')

const youtubeInterval = ref(10)
const bilibiliInterval = ref(10)
const xiaohongshuInterval = ref(10)

const highlightPlatform = computed(() => {
  const p = route.query.platform
  return typeof p === 'string' ? p : ''
})

// Modal State
const showClearModal = ref(false)
const pendingPlatform = ref('')
const platformNames = {
  youtube: 'YouTube',
  bilibili: 'Bilibili',
  tiktok: 'TikTok',
  instagram: 'Instagram',
  x: 'X',
  netease: '网易云音乐',
  xiaohongshu: '小红书'
}

const clearModalTitle = computed(() => {
  const name = platformNames[pendingPlatform.value]
  return `清除 ${name} Cookie`
})

// 格式化日期
function formatDate(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

// 打开清除确认弹窗
function openClearModal(platform) {
  pendingPlatform.value = platform
  showClearModal.value = true
}

// 确认清除
async function confirmClear() {
  if (!pendingPlatform.value) return
  
  const platform = pendingPlatform.value
  const name = platformNames[platform]
  
  const result = await settingsStore.clearCookie(platform)
  
  if (result.success) {
    toast.success(`${name} Cookie 已清除`)
  } else {
    toast.error(`清除失败: ${result.error}`)
  }
  
  showClearModal.value = false
  pendingPlatform.value = ''
}

// 保存 YouTube Cookie
async function saveYoutubeCookie() {
  if (!youtubeCookie.value.trim()) {
    toast.warning('请输入 Cookie 内容')
    return
  }
  const result = await settingsStore.saveYoutubeCookie(youtubeCookie.value)
  if (result.success) {
    toast.success('YouTube Cookie 已保存')
    youtubeCookie.value = ''
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

// 保存 Bilibili Cookie
async function saveBilibiliCookie() {
  if (!bilibiliCookie.value.trim()) {
    toast.warning('请输入 Cookie 内容')
    return
  }
  const result = await settingsStore.saveBilibiliCookie(bilibiliCookie.value)
  if (result.success) {
    toast.success('Bilibili Cookie 已保存')
    bilibiliCookie.value = ''
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

// 保存 TikTok Cookie
async function saveTiktokCookie() {
  if (!tiktokCookie.value.trim()) {
    toast.warning('请输入 Cookie 内容')
    return
  }
  const result = await settingsStore.saveTiktokCookie(tiktokCookie.value)
  if (result.success) {
    toast.success('TikTok Cookie 已保存')
    tiktokCookie.value = ''
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

// 保存 Instagram 账号密码
async function saveInstagramCookie() {
  if (!instagramUsername.value.trim()) {
    toast.warning('请输入 Instagram 用户名')
    return
  }
  if (!instagramPassword.value) {
    toast.warning('请输入 Instagram 密码')
    return
  }
  const result = await settingsStore.saveInstagramCookie({
    username: instagramUsername.value.trim(),
    password: instagramPassword.value
  })
  if (result.success) {
    toast.success('Instagram 账号已保存')
    instagramUsername.value = ''
    instagramPassword.value = ''
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

// 保存 X Cookie
async function saveXCookie() {
  if (!xCookie.value.trim()) {
    toast.warning('请输入 Cookie 内容')
    return
  }
  const result = await settingsStore.saveXCookie(xCookie.value)
  if (result.success) {
    toast.success('X Cookie 已保存')
    xCookie.value = ''
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

// 保存网易云音乐 Cookie
async function saveNeteaseCookie() {
  if (!neteaseCookie.value.trim()) {
    toast.warning('请输入 Cookie 内容')
    return
  }
  const result = await settingsStore.saveNeteaseCookie(neteaseCookie.value)
  if (result.success) {
    toast.success('网易云音乐 Cookie 已保存')
    neteaseCookie.value = ''
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

// 保存小红书 Cookie
async function saveXiaohongshuCookie() {
  if (!xiaohongshuCookie.value.trim()) {
    toast.warning('请输入 Cookie 内容')
    return
  }
  const result = await settingsStore.saveXiaohongshuCookie(xiaohongshuCookie.value)
  if (result.success) {
    toast.success('小红书 Cookie 已保存')
    xiaohongshuCookie.value = ''
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

// 自动更新逻辑
async function toggleAutoUpdate(platform) {
  if (!systemStore.hasLicense) return
  
  const current = settingsStore.cookieStatus[platform].autoUpdate
  let interval = 10
  if (platform === 'youtube') interval = youtubeInterval.value
  else if (platform === 'bilibili') interval = bilibiliInterval.value
  else if (platform === 'xiaohongshu') interval = xiaohongshuInterval.value
  
  const result = await settingsStore.setAutoUpdate(platform, !current, interval)
  if (result.success) {
    let name = platform === 'youtube' ? 'YouTube' : (platform === 'bilibili' ? 'B站' : '小红书')
    toast.success(`${name} 自动更新已${!current ? '开启' : '关闭'}`)
  } else {
    toast.error(`操作失败: ${result.error}`)
  }
}

async function saveAutoUpdate(platform) {
  if (!systemStore.hasLicense) return
  let interval = 10
  if (platform === 'youtube') interval = youtubeInterval.value
  else if (platform === 'bilibili') interval = bilibiliInterval.value
  else if (platform === 'xiaohongshu') interval = xiaohongshuInterval.value
  
  const result = await settingsStore.setAutoUpdate(platform, true, interval)
  if (result.success) {
    toast.success('更新间隔已保存')
  }
}

// 立即更新
async function updateCookieNow(platform) {
  if (!systemStore.hasLicense) {
    toast.error('此功能需要有效授权')
    return
  }
  const result = await settingsStore.updateCookieNow(platform)
  if (result.success) {
    let name = platform === 'youtube' ? 'YouTube' : (platform === 'bilibili' ? 'B站' : '小红书')
    toast.success(`${name} 更新任务已启动`)
    // 延迟一会儿刷新状态
    setTimeout(() => settingsStore.loadCookieStatus(), 2000)
  } else {
    toast.error(`更新启动失败: ${result.error}`)
  }
}

// 同步初始值
watch(() => settingsStore.cookieStatus.youtube.autoUpdateInterval, (val) => {
  if (val) youtubeInterval.value = val
}, { immediate: true })

watch(() => settingsStore.cookieStatus.bilibili.autoUpdateInterval, (val) => {
  if (val) bilibiliInterval.value = val
}, { immediate: true })

watch(() => settingsStore.cookieStatus.xiaohongshu.autoUpdateInterval, (val) => {
  if (val) xiaohongshuInterval.value = val
}, { immediate: true })

onMounted(async () => {
  await settingsStore.loadCookieStatus()
  // 必须确保加载最新的授权状态
  await systemStore.fetchLicenseStatus()
})
</script>

<style scoped>
.cookie-settings {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(480px, 1fr));
  gap: 20px;
}

@media (max-width: 1300px) {
  .cookie-settings {
    grid-template-columns: 1fr;
  }
}

.cookie-top-tips {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.security-tip {
  display: flex;
  gap: 16px;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 12px;
  padding: 16px 20px;
  align-items: flex-start;
}

[data-theme="dark"] .security-tip {
  background: rgba(245, 158, 11, 0.07);
  border-color: rgba(245, 158, 11, 0.25);
}

.notice-icon.security {
  color: #f59e0b;
}

.notice-title.security {
  color: #f59e0b;
}

.security-desc {
  margin: 0 0 8px 0;
}

.security-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
}

.security-list li {
  line-height: 1.55;
}

.plugin-tip {
  display: flex;
  gap: 16px;
  background: rgba(37, 99, 235, 0.1);
  border: 1px solid rgba(37, 99, 235, 0.3);
  border-radius: 12px;
  padding: 16px 20px;
  align-items: flex-start;
}

[data-theme="dark"] .plugin-tip {
  background: rgba(37, 99, 235, 0.05);
  border-color: rgba(37, 99, 235, 0.2);
}

.notice-icon {
  color: var(--color-primary);
  display: flex;
  padding-top: 2px;
}

.notice-content {
  flex: 1;
}

.notice-title {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-primary);
  margin-bottom: 4px;
}

.notice-desc {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  margin: 0;
  word-break: break-word;
  overflow-wrap: break-word;
}

.plugin-link {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 600;
  margin-left: 4px;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.plugin-link:hover {
  border-bottom-color: var(--color-primary);
}

.auth-warning {
  grid-column: 1 / -1;
  background: var(--color-warning-light);
  border: 1px solid var(--color-warning);
  border-radius: 10px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.highlight-card {
  border: 2px solid rgba(59, 130, 246, 0.9);
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.15), 0 8px 24px rgba(59, 130, 246, 0.2);
  animation: cookieHighlightPulse 1.6s ease-in-out 2;
}

[data-theme="dark"] .highlight-card {
  border-color: rgba(96, 165, 250, 0.9);
  box-shadow: 0 0 0 4px rgba(96, 165, 250, 0.18), 0 10px 26px rgba(96, 165, 250, 0.25);
}

@keyframes cookieHighlightPulse {
  0% {
    transform: translateY(0);
    box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.15), 0 8px 24px rgba(59, 130, 246, 0.2);
  }
  50% {
    transform: translateY(-2px);
    box-shadow: 0 0 0 6px rgba(59, 130, 246, 0.28), 0 12px 28px rgba(59, 130, 246, 0.28);
  }
  100% {
    transform: translateY(0);
    box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.15), 0 8px 24px rgba(59, 130, 246, 0.2);
  }
}

.warning-header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-warning);
}

.warning-title {
  font-weight: 600;
  font-size: 0.9rem;
}

.warning-desc {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  margin: 0;
}

/* Compact Card Design */
.card-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-primary);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.header-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.platform-name {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.status-tag {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}

.status-tag.success {
  background: var(--color-success-light);
  color: var(--color-success);
}

.status-tag.error {
  background: var(--color-error-light);
  color: var(--color-error);
}

.header-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.stat-pill {
  font-size: 0.75rem;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  padding: 2px 10px;
  border-radius: 20px;
  color: var(--color-text-secondary);
}

[data-theme="dark"] .stat-pill {
  background: var(--color-bg-tertiary);
  border-color: var(--color-border);
  color: var(--color-text-secondary);
}

[data-theme="dark"] .cookie-settings .btn-danger {
  background: rgba(248, 113, 113, 0.16);
  color: #fecaca;
  border: 1px solid rgba(252, 165, 165, 0.45);
  box-shadow: none;
}

[data-theme="dark"] .cookie-settings .btn-danger:hover:not(:disabled) {
  background: rgba(248, 113, 113, 0.24);
  color: #fee2e2;
  border-color: rgba(252, 165, 165, 0.62);
}

.stat-pill .label {
  color: var(--color-text-muted);
  font-weight: 500;
  margin-right: 4px;
}

/* Card Body */
.card-body {
  padding: 0 20px;
}

.config-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 0;
  border-bottom: 1px solid var(--color-border-light);
  gap: 16px;
}

.section-label {
  flex-shrink: 0;
  min-width: 0;
}

.section-label .title {
  display: block;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
}

.section-label .desc {
  font-size: 0.8rem;
  color: var(--color-text-tertiary);
  white-space: nowrap;
}

.section-controls {
  display: flex;
  align-items: center;
  gap: 20px;
}

.auto-update {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--color-bg-primary);
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
}

.toggle-text {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--color-text-secondary);
}

.mini-select {
  background: transparent;
  border: none;
  font-size: 0.8rem;
  color: var(--color-primary);
  font-weight: 600;
  cursor: pointer;
  padding: 0 4px;
}

.mini-select:focus {
  outline: none;
}

/* Manual Section */
.manual-section {
  padding: 16px 0;
}

.input-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}

.input-header .title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
}

.input-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

@media (max-width: 1024px) {
  .cookie-settings {
    grid-template-columns: 1fr;
  }

  .cookie-top-tips {
    grid-template-columns: 1fr;
  }

  .card-header {
    padding: 12px 16px;
  }

  .card-body {
    padding: 0 16px;
  }

  .config-section {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
    padding: 16px 0;
  }

  .section-controls {
    width: 100%;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
  }

  .section-controls > .btn {
    flex: 1;
    min-width: 120px;
    justify-content: center;
  }

  .auto-update {
    flex: 2;
    min-width: 200px;
    justify-content: space-between;
    padding: 8px 12px;
  }

  .section-label .title,
  .section-label .desc {
    white-space: normal;
  }

  .input-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .input-actions {
    width: 100%;
    display: flex;
    gap: 8px;
  }

  .input-actions .btn {
    flex: 1;
    justify-content: center;
  }
}

@media (max-width: 768px) {
  .cookie-settings {
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .plugin-tip {
    padding: 12px 16px;
    gap: 12px;
  }

  .card-header {
    padding: var(--spacing-sm);
    gap: 10px;
  }

  .card-body {
    padding: 0 var(--spacing-sm);
  }

  .header-main {
    flex-wrap: wrap;
    gap: 8px;
  }

  .platform-name {
    font-size: 1rem;
  }

  .header-stats {
    gap: 6px;
  }

  .stat-pill {
    font-size: 0.7rem;
    padding: 2px 8px;
  }

  .config-section {
    padding: 12px 0;
    gap: 12px;
  }

  .section-controls {
    gap: 10px;
  }

  .auto-update {
    flex-wrap: wrap;
    gap: 8px;
    padding: 8px 10px;
  }

  .toggle-text {
    font-size: 0.8rem;
  }

  .mini-select {
    font-size: 0.75rem;
  }

  .manual-section {
    padding: 12px 0;
  }

  .input-header {
    gap: 10px;
  }

  .input-actions {
    gap: 6px;
  }

  .input-header .title {
    font-size: 0.9rem;
  }
}

.confirm-content {
  text-align: center;
  padding: 10px 0;
}

.confirm-content p {
  margin: 0 0 8px 0;
  font-size: 1rem;
  color: var(--color-text-primary);
}

.confirm-content .sub-text {
  font-size: 0.85rem;
  color: var(--color-text-tertiary);
}
</style>
