<template>
  <div class="subscriptions-page">
    <!-- 授权检测提示 -->
    <div v-if="!licenseValid" class="license-alert">
      <div class="license-icon">🔒</div>
      <h2>{{ checkingLicense ? '正在验证...' : '需要授权' }}</h2>
      <p v-if="!checkingLicense">该功能为高级功能，请前往发卡平台购买授权</p>
      
      <div class="license-features" v-if="!checkingLicense">
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>支持油管/B站/抖音/TikTok/X/Instagram/网易云歌单</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>支持 X 点赞订阅</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>自动检测更新 + 自动批量下载</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>TG / 微信 / Server酱 消息通知</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>Emby / Jellyfin 自动刮削推送</span>
        </div>
         <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>7x24小时无人值守全自动挂机</span>
        </div>
         <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>订阅数据备份、导入与一键迁移</span>
        </div>
      </div>

      <p v-else>正在连接服务器验证授权状态...</p>
      <div class="license-actions" v-if="!checkingLicense">
        <a href="https://c.fakamiao.top/shopDetail/6WNe26" target="_blank" class="btn btn-primary">购买授权</a>
        <button @click="checkLicense(true)" class="btn btn-secondary">刷新状态</button>
      </div>
      <div class="license-actions" v-else>
          <span class="spinner" style="border-color: var(--color-primary); border-top-color: transparent;"></span>
      </div>
    </div>

    <div v-else class="page-content">


    <!-- 常驻筛选器和折叠控制 -->
    <div class="action-panel-container">
      <!-- 常驻筛选器 -->
      <div class="action-panel primary-panel">
        <!-- 新建操作 -->
        <div class="action-group">
          <div class="action-group-title">新增与任务</div>
          <div class="group-items">
            <button class="btn btn-primary btn-xs" @click="confirmOpenAddModal">
              <Icon name="plus" :size="12" />
              添加视频订阅
            </button>
            <button class="btn btn-outline btn-xs" @click="goToBatchDownloadTasks" title="查看订阅系统批量下载任务">
              <Icon name="download" :size="12" />
              订阅任务
            </button>
          </div>
        </div>

        <!-- 筛选器 (最左侧) -->
        <div class="action-group filter-action-group">
          <div class="action-group-title">筛选与搜索</div>
          <div class="group-items filter-horizontal">
            <!-- 平台多选筛选器 -->
            <div class="custom-multiselect" v-click-outside="() => showPlatformDropdown = false">
              <div class="multiselect-header" @click="showPlatformDropdown = !showPlatformDropdown">
                <span class="selected-text" :title="selectedPlatformsText">
                  {{ selectedPlatformsText || '全部平台' }}
                </span>
                <Icon name="chevron-down" :size="12" :class="{ 'rotate': showPlatformDropdown }" />
              </div>
              
              <!-- 全屏模糊遮罩层 -->
              <div class="platform-dropdown-overlay" v-if="showPlatformDropdown" @click.stop="showPlatformDropdown = false"></div>

              <div v-show="showPlatformDropdown" class="multiselect-dropdown">
                <div class="scroll-area">
                  <div class="dropdown-item all-platforms" @click="toggleAllPlatforms">
                    <input type="checkbox" :checked="selectedPlatforms.length === 0" readonly />
                    <span>全部平台</span>
                  </div>
                  
                  <div class="dropdown-group">
                    <div class="group-title">抖音</div>
                    <div class="dropdown-item" @click="togglePlatform('douyin')">
                      <input type="checkbox" :checked="isPlatformSelected('douyin')" />
                      <span>全部抖音</span>
                    </div>
                    <div class="dropdown-item sub-item" @click="togglePlatform('douyin_creator')">
                      <input type="checkbox" :checked="isPlatformSelected('douyin_creator')" />
                      <span>├ 抖音博主</span>
                    </div>
                    <div class="dropdown-item sub-item" @click="togglePlatform('douyin_collection')">
                      <input type="checkbox" :checked="isPlatformSelected('douyin_collection')" />
                      <span>├ 抖音合集</span>
                    </div>
                    <div class="dropdown-item sub-item" @click="togglePlatform('douyin_favorite')">
                      <input type="checkbox" :checked="isPlatformSelected('douyin_favorite')" />
                      <span>└ 抖音点赞</span>
                    </div>
                  </div>

                  <div class="dropdown-group">
                    <div class="group-title">TikTok</div>
                    <div class="dropdown-item" @click="togglePlatform('tiktok')">
                      <input type="checkbox" :checked="isPlatformSelected('tiktok')" />
                      <span>TikTok博主</span>
                    </div>
                  </div>

                  <div class="dropdown-group">
                    <div class="group-title">YouTube</div>
                    <div class="dropdown-item" @click="togglePlatform('youtube')">
                      <input type="checkbox" :checked="isPlatformSelected('youtube')" />
                      <span>全部YouTube</span>
                    </div>
                    <div class="dropdown-item sub-item" @click="togglePlatform('youtube_channel')">
                      <input type="checkbox" :checked="isPlatformSelected('youtube_channel')" />
                      <span>├ 油管博主</span>
                    </div>
                    <div class="dropdown-item sub-item" @click="togglePlatform('youtube_shorts')">
                      <input type="checkbox" :checked="isPlatformSelected('youtube_shorts')" />
                      <span>├ 油管短视频</span>
                    </div>
                    <div class="dropdown-item sub-item" @click="togglePlatform('youtube_playlist')">
                      <input type="checkbox" :checked="isPlatformSelected('youtube_playlist')" />
                      <span>└ 油管合集</span>
                    </div>
                  </div>

                  <div class="dropdown-group">
                    <div class="group-title">Instagram</div>
                    <div class="dropdown-item" @click="togglePlatform('instagram')">
                      <input type="checkbox" :checked="isPlatformSelected('instagram')" />
                      <span>Instagram博主</span>
                    </div>
                  </div>

                  <div class="dropdown-group">
                    <div class="group-title">小红书</div>
                    <div class="dropdown-item" @click="togglePlatform('xiaohongshu')">
                      <input type="checkbox" :checked="isPlatformSelected('xiaohongshu')" />
                      <span>小红书博主</span>
                    </div>
                  </div>

                  <div class="dropdown-group">
                    <div class="group-title">Bilibili</div>
                    <div class="dropdown-item" @click="togglePlatform('bilibili')">
                      <input type="checkbox" :checked="isPlatformSelected('bilibili')" />
                      <span>全部B站</span>
                    </div>
                    <div class="dropdown-item sub-item" @click="togglePlatform('bilibili_creator')">
                      <input type="checkbox" :checked="isPlatformSelected('bilibili_creator')" />
                      <span>├ B站博主</span>
                    </div>
                    <div class="dropdown-item sub-item" @click="togglePlatform('bilibili_collection')">
                      <input type="checkbox" :checked="isPlatformSelected('bilibili_collection')" />
                      <span>├ B站合集</span>
                    </div>
                    <div class="dropdown-item sub-item" @click="togglePlatform('bilibili_favorite')">
                      <input type="checkbox" :checked="isPlatformSelected('bilibili_favorite')" />
                      <span>└ B站收藏夹</span>
                    </div>
                  </div>

                  <div class="dropdown-group">
                    <div class="group-title">网易云</div>
                    <div class="dropdown-item" @click="togglePlatform('netease')">
                      <input type="checkbox" :checked="isPlatformSelected('netease')" />
                      <span>网易云歌单</span>
                    </div>
                  </div>

                  <div class="dropdown-group">
                    <div class="group-title">X</div>
                    <div class="dropdown-item" @click="togglePlatform('x_favorite')">
                      <input type="checkbox" :checked="isPlatformSelected('x_favorite')" />
                      <span>X点赞列表</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <!-- 状态筛选器 (自定义) -->
            <div class="custom-multiselect compact-select" v-click-outside="() => showStatusDropdown = false">
              <div class="multiselect-header" @click="showStatusDropdown = !showStatusDropdown">
                <span class="selected-text" :title="getStatusText(statusFilter)">
                  {{ getStatusText(statusFilter) }}
                </span>
                <Icon name="chevron-down" :size="12" :class="{ 'rotate': showStatusDropdown }" />
              </div>

              <!-- 全屏模糊遮罩层 -->
              <div class="platform-dropdown-overlay" v-if="showStatusDropdown" @click.stop="showStatusDropdown = false"></div>
              
              <div v-show="showStatusDropdown" class="multiselect-dropdown">
                <div class="scroll-area">
                  <div class="dropdown-item" @click="selectStatus('')">
                    <span :class="{ 'text-primary font-bold': statusFilter === '' }">全部状态</span>
                    <Icon name="check" :size="14" v-if="statusFilter === ''" class="text-primary ml-auto" />
                  </div>
                  <div class="dropdown-item" @click="selectStatus('active')">
                    <span :class="{ 'text-primary font-bold': statusFilter === 'active' }">正常</span>
                    <Icon name="check" :size="14" v-if="statusFilter === 'active'" class="text-primary ml-auto" />
                  </div>
                  <div class="dropdown-item" @click="selectStatus('paused')">
                    <span :class="{ 'text-primary font-bold': statusFilter === 'paused' }">暂停/未开自检</span>
                    <Icon name="check" :size="14" v-if="statusFilter === 'paused'" class="text-primary ml-auto" />
                  </div>
                  <div class="dropdown-item" @click="selectStatus('error')">
                    <span :class="{ 'text-primary font-bold': statusFilter === 'error' }">异常</span>
                    <Icon name="check" :size="14" v-if="statusFilter === 'error'" class="text-primary ml-auto" />
                  </div>
                  <div class="dropdown-item" @click="selectStatus('invalid')">
                    <span :class="{ 'text-primary font-bold': statusFilter === 'invalid' }">失效</span>
                    <Icon name="check" :size="14" v-if="statusFilter === 'invalid'" class="text-primary ml-auto" />
                  </div>
                  <div class="dropdown-item" @click="selectStatus('no_auto_download')">
                    <span :class="{ 'text-primary font-bold': statusFilter === 'no_auto_download' }">未开自下</span>
                    <Icon name="check" :size="14" v-if="statusFilter === 'no_auto_download'" class="text-primary ml-auto" />
                  </div>
                </div>
              </div>
            </div>
            <div class="search-input-wrapper">
              <Icon name="search" :size="12" class="search-icon" />
              <input 
                type="text" 
                class="form-input form-input-xs search-input" 
                v-model="searchQuery" 
                @input="filterSubscriptions" 
                placeholder="搜索..."
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 移动端功能区折叠按钮 (移到这里) -->
      <button class="mobile-panel-toggle" @click="actionPanelExpanded = !actionPanelExpanded">
        <Icon :name="actionPanelExpanded ? 'chevron-up' : 'chevron-down'" :size="16" />
        <span>{{ actionPanelExpanded ? '收起' : '展开' }}</span>
      </button>

      <!-- 折叠的更多功能 -->
      <div class="action-panel secondary-panel" :class="{ 'mobile-collapsed': !actionPanelExpanded }">
        <!-- 备份管理：仅导出/导入订阅列表 -->
        <div class="action-group">
          <div class="action-group-title">备份管理</div>
          <div class="group-items">
            <button class="btn btn-dark btn-xs" @click="exportConfig">
              备份
            </button>
            <button class="btn btn-dark btn-xs" @click="importConfig">
              导入
            </button>
          </div>
        </div>

        <!-- 账号登录 -->
        <div class="action-group">
          <div class="action-group-title">账号登录 <span class="action-group-hint-inline">强烈建议使用小号（cookie）登录</span></div>
          <div class="group-items">
            <button class="btn btn-dark btn-xs" @click="handleDouyinLogin">抖音</button>
            <button class="btn btn-dark btn-xs" @click="handleYoutubeLogin">油管</button>
            <button class="btn btn-dark btn-xs" @click="handleBilibiliLogin">B站</button>
            <button class="btn btn-dark btn-xs" @click="handleXiaohongshuLogin">小红书</button>
            <button class="btn btn-dark btn-xs" @click="handleXCookieSettings">X</button>
            <button class="btn btn-dark btn-xs" @click="handleNeteaseCookieSettings">网易云</button>
            <button class="btn btn-dark btn-xs" @click="handleTkCookieSettings">TK</button>
            <button class="btn btn-dark btn-xs" @click="handleInsCookieSettings">Ins</button>
          </div>
        </div>

        <!-- 系统维护 -->
        <div class="action-group">
          <div class="action-group-title">系统维护</div>
          <div class="group-items">
            <button class="btn btn-dark btn-xs" @click="handleResetBrowser">
              重置
            </button>
            <button class="btn btn-dark btn-xs" @click="handleClearCache">
              清缓存
            </button>
          </div>
        </div>

        <!-- 批量管理 -->
        <div class="action-group">
          <div class="action-group-title">批量管理</div>
          <div class="group-items">
            <button class="btn btn-dark btn-xs" @click="showBatchSetInterval">
              周期
            </button>
            <button class="btn btn-dark btn-xs" @click="showBatchSetAutoDownload">
              自载
            </button>
            <button class="btn btn-dark btn-xs" @click="showBatchAddDouyin">
              批加
            </button>
            <button class="btn btn-dark btn-xs" @click="batchCheckUpdate">
              检测
            </button>
            <button class="btn btn-dark btn-xs" @click="batchSyncVideos">
              同步
            </button>
          </div>
        </div>
      </div>
    </div>



    <!-- 订阅列表 -->
    <div class="subscriptions-main-container">
      <Transition name="fade" mode="out-in">
        <SkeletonLoader 
          v-if="loading"
          :loading="loading" 
          text="正在获取您的视频订阅..." 
          type="grid" 
          :count="8"
          itemHeight="160px"
          itemMinWidth="380px"
          gap="24px"
        />

      <div v-else class="subscriptions-content-wrapper">
      <div class="subscriptions-grid" v-if="filteredSubscriptions.length > 0">
      <div 
        v-for="sub in filteredSubscriptions" 
        :key="sub.id"
        class="subscription-card"
      >

        <!-- 左侧橙色强调条 -->

        


        <!-- 状态指示点 - 逻辑简化：全开启为绿，否则为黄 -->
        <div 
          class="status-dot" 
          :class="{
            'status-error': sub.status === 'error',
            'status-invalid': sub.status === 'invalid',
            'status-active': sub.status === 'active' && sub.update_interval > 0 && (sub.auto_download === true || sub.auto_download === 'true') && sub.status !== 'error' && sub.status !== 'invalid',
            'status-paused': (sub.status !== 'active' || sub.update_interval === 0 || sub.auto_download === false || sub.auto_download === 'false') && !(sub.is_checking || sub.is_syncing) && sub.status !== 'error' && sub.status !== 'invalid',
            'status-checking': sub.is_checking || sub.is_syncing,
            'status-blinking': sub.progressState?.visible && ['downloading', 'syncing', 'cancelling'].includes(sub.progressState?.status)
          }"
        ></div>

        <!-- 头像区域（包含下方平台和视频数） -->
        <div class="avatar-side">
          <div class="avatar-container">
            <img 
              :src="proxyImage(sub.avatar_url)" 
              :alt="sub.nickname"
              class="avatar"
              @click.stop="openProfile(sub)"
              @error="handleImageError"
              loading="lazy"
            />
          </div>
          <div class="avatar-meta desktop-only">
            <span class="platform-badge" :class="`badge-${sub.platform}`">
              {{ getPlatformName(sub.platform, sub.subscription_type, sub.youtube_tab_type) }}
            </span>
            <span class="video-count-inline" v-if="sub.video_count">
              {{ sub.video_count }} 视频
            </span>
          </div>
        </div>

        <!-- 信息区域 -->
        <div class="info-area">
          <div class="name-row">
            <span class="platform-badge mobile-only" :class="`badge-${sub.platform}`">
              {{ getPlatformName(sub.platform, sub.subscription_type, sub.youtube_tab_type) }}
            </span>
            <h3
              class="creator-name"
              :class="{ 'is-marquee': (sub.nickname || '').length > 10 }"
              :title="sub.nickname"
            >
              <span class="creator-name-track">
                <span class="creator-name-text">{{ sub.nickname }}</span>
                <span class="creator-name-text creator-name-clone" aria-hidden="true">{{ sub.nickname }}</span>
              </span>
            </h3>
            <span class="video-count-inline mobile-only" v-if="sub.video_count">
              {{ sub.video_count }}
            </span>
          </div>
          <div
            v-if="sub.status === 'error' && getSubscriptionErrorSummary(sub)"
            class="subscription-error-hint"
            :title="getSubscriptionErrorDetail(sub)"
          >
            <Icon name="alert-triangle" :size="12" class="error-hint-icon" />
            <span class="marquee-wrap"><span class="marquee-text">{{ getSubscriptionErrorSummary(sub) }}</span></span>
            <button
              v-if="sub.platform === 'instagram'"
              class="btn btn-xs btn-outline"
              style="margin-left:6px; flex-shrink:0; height:20px; line-height:18px; padding:0 6px; color:var(--color-error); border-color:var(--color-error);"
              :disabled="sub._clearingRisk"
              @click.stop="handleClearInstagramRisk(sub)"
            >{{ sub._clearingRisk ? '解除中...' : '解除' }}</button>
          </div>

          <!-- 快捷操作栏 (现在是第二行) -->
          <div class="quick-actions-toolbar">
            <button 
              class="toolbar-btn" 
              @click.stop="checkUpdate(sub)" 
              :disabled="sub.is_checking"
            >
              <span class="desktop-text">{{ sub.is_checking ? '检测中' : '更新' }}</span>
              <span class="mobile-text">{{ sub.is_checking ? '检测' : '更新' }}</span>
            </button>
            <button 
              class="toolbar-btn" 
              @click.stop="viewVideos(sub)"
            >
              <span class="desktop-text">列表</span>
              <span class="mobile-text">列表</span>
            </button>
            <button 
              class="toolbar-btn" 
              @click.stop="playSubscriptionVideos(sub)"
            >
              <span class="desktop-text">播放</span>
              <span class="mobile-text">播放</span>
            </button>
            <button 
              class="toolbar-btn" 
              @click.stop="syncVideos(sub)" 
              :disabled="sub.is_syncing"
            >
              <span class="desktop-text">{{ sub.is_syncing ? '同步中' : '同步' }}</span>
              <span class="mobile-text">{{ sub.is_syncing ? '同步' : '同步' }}</span>
            </button>
            <!-- 进度条通知栏 (常驻预留位置，空闲时显示下次更新时间) -->
            <div 
              class="progress-notification"
              :class="{ 'show-cancel-btn': sub.progressState && ['downloading', 'completed', 'partial_completed', 'error', 'cancelled'].includes(sub.progressState.status) && sub.progressState.type === 'batch_download_progress' }"
            >
              <!-- 任务进行中：显示进度条 -->
              <div class="progress-active-content" :class="{ 'visible': sub.progressState && sub.progressState.visible }">
                <template v-if="sub.progressState">
                  <div class="progress-info">
                    <span class="progress-text" :class="sub.progressState.statusClass">
                      {{ sub.progressState.message }}
                    </span>
                  </div>
                  
                  <div class="progress-status-row">
                    <!-- 批量下载：支持进度恢复和统一管理 -->
                    <div 
                      class="progress-track-wrapper"
                      v-if="sub.progressState.status === 'downloading' && sub.progressState.type === 'batch_download_progress'"
                    >
                      <div class="progress-track">
                        <div 
                          class="progress-fill" 
                          :class="[sub.progressState.statusClass, { 'indeterminate': sub.progressState.indeterminate }]"
                          :style="{ width: sub.progressState.percent + '%' }"
                        ></div>
                      </div>
                    </div>
                    <!-- 非批量下载的进度条 -->
                    <div 
                      v-else
                      class="progress-track"
                    >
                      <div 
                        class="progress-fill" 
                        :class="[sub.progressState.statusClass, { 'indeterminate': sub.progressState.indeterminate }]"
                        :style="{ width: sub.progressState.percent + '%' }"
                      ></div>
                    </div>

                    <!-- 数值显示在进度条右侧 -->
                    <span class="progress-count" v-if="sub.progressState.total > 0">
                      {{ sub.progressState.current }}/{{ sub.progressState.total }}
                    </span>

                    <!-- 常驻取消按钮：移动到数值右侧 -->
                    <button 
                      v-if="sub.progressState.status === 'downloading' && sub.progressState.type === 'batch_download_progress'"
                      class="cancel-download-btn-inline"
                      @click.stop="cancelBatchDownload(sub)"
                      :disabled="sub.progressState.status === 'cancelling'"
                      :title="sub.progressState.status === 'cancelling' ? '正在取消...' : '取消下载'"
                    >
                      {{ sub.progressState.status === 'cancelling' ? '取消中' : '✕' }}
                    </button>
                    <!-- 手动关闭按钮：适用于完成或异常状态 -->
                    <button 
                      v-else-if="['completed', 'partial_completed', 'error', 'cancelled'].includes(sub.progressState.status) && sub.progressState.type === 'batch_download_progress'"
                      class="cancel-download-btn-inline"
                      @click.stop="removeTask(sub.id)"
                      title="关闭"
                    >
                      ✕
                    </button>
                  </div>
                </template>
              </div>

              <!-- 空闲状态：显示下次更新时间 -->
              <div class="progress-idle-content" :class="{ 'visible': !sub.progressState || !sub.progressState.visible }">
                <span class="next-update-label">
                  <Icon name="clock" :size="12" />
                  <span v-if="sub.status === 'active' && (sub.check_interval > 0 || sub.update_interval > 0)">
                    下次自动检测: {{ calculateNextUpdate(sub) }}
                  </span>
                  <span v-else-if="sub.status === 'error'">
                    检测异常（详情见上方提示）
                  </span>
                  <span v-else-if="sub.status === 'invalid'">
                    订阅链接已失效
                  </span>
                  <span v-else>
                    {{ sub.status === 'paused' ? '自动检测已暂停' : '自动检测已关闭' }}
                  </span>
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 右上角详情设置按钮 -->
        <button class="card-settings-btn" @click.stop="openDetailDrawer(sub)" title="查看详情">
          <Icon name="settings" :size="16" />
        </button>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <Transition name="drawer-fade">
    <div class="drawer-overlay" v-if="showDetailDrawer" @click="closeDetailDrawer">
        <Transition name="drawer-slide">
          <div class="drawer-panel" v-if="showDetailDrawer && currentSubscription" @click.stop>
        <!-- 抽屉头部 (横向紧凑化重构) -->
        <div class="drawer-header-compact">
          <div class="header-main-info">
            <img 
              :src="proxyImage(currentSubscription?.avatar_url)" 
              :alt="currentSubscription?.nickname"
              class="compact-avatar"
              @error="handleImageError"
            />
            <div class="compact-text-content">
              <div class="compact-title-row">
                <h2
                  class="compact-title"
                  :class="{ 'is-marquee': (currentSubscription?.nickname || '').length > 12 }"
                  :title="currentSubscription?.nickname"
                >
                  <span class="compact-title-track">
                    <span class="compact-title-text">{{ currentSubscription?.nickname }}</span>
                    <span class="compact-title-text compact-title-clone" aria-hidden="true">{{ currentSubscription?.nickname }}</span>
                  </span>
                </h2>
                <div class="detail-header-info">
                  <span class="platform-badge" :class="`badge-${currentSubscription?.platform}`">
                    {{ getPlatformName(currentSubscription?.platform, currentSubscription?.subscription_type, currentSubscription?.youtube_tab_type) }}
                  </span>
                  <span class="status-badge-mini" :class="{
                    'active': currentSubscription?.status === 'active',
                    'paused': currentSubscription?.status === 'paused',
                    'error': currentSubscription?.status === 'error',
                    'invalid': currentSubscription?.status === 'invalid'
                  }">
                    {{ 
                      currentSubscription?.status === 'active' ? '运行中' : 
                      currentSubscription?.status === 'invalid' ? '已失效' : 
                      currentSubscription?.status === 'error' ? '异常' : 
                      '已休眠' 
                    }}
                  </span>
                </div>
              </div>
              <p class="compact-subtitle" v-if="currentSubscription?.signature" :title="currentSubscription?.signature">
                {{ currentSubscription?.signature }}
              </p>
            </div>
          </div>
          <button class="close-btn-mini" @click="closeDetailDrawer">
            <Icon name="x" :size="20" />
          </button>
        </div>

        <!-- 抽屉内容 -->
        <div class="drawer-content">

          <!-- 核心统计栏 (紧凑型) -->
          <div class="stats-ribbon">
            <div class="ribbon-item">
              <span class="ribbon-value">{{ currentSubscription?.video_count || 0 }}</span>
              <span class="ribbon-label">视频数</span>
            </div>
            <div class="ribbon-divider"></div>
            <div class="ribbon-item" v-if="currentSubscription?.follower_count">
              <span class="ribbon-value">{{ formatCount(currentSubscription?.follower_count) }}</span>
              <span class="ribbon-label">粉丝</span>
            </div>
            <div class="ribbon-divider" v-if="currentSubscription?.follower_count"></div>
            <div class="ribbon-item" v-if="currentSubscription?.like_count">
              <span class="ribbon-value">{{ formatCount(currentSubscription?.like_count) }}</span>
              <span class="ribbon-label">获赞</span>
            </div>
          </div>

          <div
            v-if="currentSubscription?.status === 'error' && getSubscriptionErrorSummary(currentSubscription)"
            class="drawer-error-panel"
          >
            <div class="drawer-error-title">
              <Icon name="alert-triangle" :size="14" />
              <span>{{ getSubscriptionErrorSummary(currentSubscription) }}</span>
            </div>
            <div class="drawer-error-detail">
              {{ getSubscriptionErrorDetail(currentSubscription) }}
            </div>
          </div>

          <!-- 时间轴数据 (行式紧凑布局) -->
          <div class="time-metrics-list">
            <div class="time-metric-row">
              <div class="metric-info">
                <Icon name="plus" :size="12" class="metric-icon neon-blue" />
                <span class="metric-label">初次订阅</span>
              </div>
              <span class="metric-value">{{ currentSubscription?.created_at ? formatTime(currentSubscription.created_at) : '未知' }}</span>
            </div>
            <div class="time-metric-row">
              <div class="metric-info">
                <Icon name="activity" :size="12" class="metric-icon neon-green" />
                <span class="metric-label">最近检查</span>
              </div>
              <span class="metric-value">{{ (currentSubscription?.last_check_time || currentSubscription?.last_check) ? formatTime(currentSubscription.last_check_time || currentSubscription.last_check) : '未检测' }}</span>
            </div>
            <div class="time-metric-row highlight">
              <div class="metric-info">
                <Icon name="refresh" :size="12" class="metric-icon neon-orange" />
                <span class="metric-label">下次更新周期</span>
              </div>
              <span class="metric-value">{{ calculateNextUpdate(currentSubscription) }}</span>
            </div>
          </div>

          <!-- 设置区域 (精美列表 - 还原旧版逻辑) -->
          <div class="settings-list">
            <div class="setting-row-item">
              <div class="row-info">
                <Icon name="clock" :size="16" class="row-icon neon-orange-bg" />
                <div class="row-text">
                  <div class="row-title">自动检测周期</div>
                  <div class="row-desc">设置系统自动检索新视频的频率</div>
                  <div class="row-hint" style="margin-top: 4px; font-size: 12px; color: var(--color-warning);">
                    💡 建议设置 1 小时以上，避免频繁请求触发平台风控机制
                  </div>
                </div>
              </div>
              <select 
                class="form-select select-modern" 
                v-model.number="currentSubscription.check_interval"
                @change="updateCurrentSubscription"
              >
                <option :value="0">不自动检测</option>
                <option :value="1800">30分钟</option>
                <option :value="3600">1小时</option>
                <option :value="7200">2小时</option>
                <option :value="14400">4小时</option>
                <option :value="21600">6小时</option>
                <option :value="43200">12小时</option>
                <option :value="86400">24小时</option>
              </select>
            </div>

            <div class="setting-row-item">
              <div class="row-info">
                <Icon name="download" :size="16" class="row-icon neon-orange-bg" />
                <div class="row-text">
                  <div class="row-title">自动下载新视频</div>
                  <div class="row-desc">开启后系统将自动下载检测到的新内容</div>
                </div>
              </div>
              <label class="switch-modern">
                <input 
                  type="checkbox" 
                  v-model="currentSubscription.auto_download"
                  @change="updateCurrentSubscription"
                />
                <span class="slider-modern"></span>
              </label>
            </div>

            <!-- 新增：跳过B站充电视频 (仅B站博主和合集显示) -->
            <div class="setting-row-item" v-if="currentSubscription?.platform?.startsWith('bilibili') && currentSubscription?.subscription_type !== 'favorite'">
              <div class="row-info">
                <Icon name="slash" :size="16" class="row-icon neon-orange-bg" />
                <div class="row-text">
                  <div class="row-title">跳过 B 站充电专属视频</div>
                  <div class="row-desc">
                    开启后将阻止新的充电内容入库。执行“同步视频”可清理库中现有的充电记录。
                    <span class="desc-hint" style="color: var(--color-warning); font-size: 11px; display: block; margin-top: 2px;">
                      (提示：已下载的视频将始终保留，不会被删除)
                    </span>
                  </div>
                </div>
              </div>
              <label class="switch-modern">
                <input 
                  type="checkbox" 
                  v-model="currentSubscription.skip_bilibili_upower"
                  @change="updateCurrentSubscription"
                />
                <span class="slider-modern"></span>
              </label>
            </div>
          </div>

          <!-- 功能操作区 (按钮组 - 纯文字极简版) -->
          <div class="drawer-actions-grid-five">
            <button 
              class="btn btn-secondary grid-pure-text-btn" 
              @click="checkUpdate(currentSubscription)"
              :disabled="currentSubscription.is_checking"
            >
              {{ currentSubscription.is_checking ? '检测中' : '更新' }}
            </button>

            <button class="btn btn-secondary grid-pure-text-btn" @click="viewVideosFromDrawer">
              列表
            </button>

            <button class="btn btn-secondary grid-pure-text-btn" @click="playSubscriptionVideos(currentSubscription)">
              播放
            </button>

            <button 
              class="btn btn-secondary grid-pure-text-btn" 
              @click="syncVideos(currentSubscription)" 
              :disabled="currentSubscription.is_syncing"
            >
              {{ currentSubscription.is_syncing ? '同步中' : '同步' }}
            </button>

            <button
              v-if="isRenamableBilibiliCollection(currentSubscription)"
              class="btn btn-secondary grid-pure-text-btn"
              @click="renameCurrentSubscription"
            >
              重命名
            </button>

            <button class="btn btn-secondary grid-pure-text-btn delete-text" @click="deleteCurrentSubscription">
              删除订阅
            </button>
          </div>
        </div>
      </div>
      </Transition>
    </div>
    </Transition>


    <!-- 空状态 (真正无数据) -->
    <div class="empty-state" v-if="hasLoadedOnce && !loading && (subscriptions.length === 0)">
      <div class="empty-icon">📭</div>
      <h3 class="empty-title">暂无视频订阅</h3>
      <p class="empty-desc">先点击账号登录工具栏登录对应的平台，再点击右上角"添加视频订阅"按钮开始订阅您喜欢的博主</p>
      <button class="btn btn-primary" @click="confirmOpenAddModal">
        <Icon name="plus" :size="16" />
        添加视频订阅
      </button>
    </div>

    <!-- 搜索/筛选无结果 -->
    <div class="empty-state" v-else-if="hasLoadedOnce && !loading && filteredSubscriptions.length === 0">
      <div class="empty-icon">🔍</div>
      <h3 class="empty-title">没有找到匹配的订阅</h3>
      <p class="empty-desc">请尝试调整筛选条件或搜索关键词</p>
      <button class="btn btn-outline" @click="resetFilters">
        重置筛选条件
      </button>
    </div>
    </div>
  </Transition>
</div>

    <!-- 添加订阅模态框 -->
    <Modal v-model:show="showAddModal" title="添加视频订阅" width="600px">
      <div class="add-subscription-form">
        <!-- 静态提示 -->
        <div class="static-hint-card">
          <Icon name="info" :size="16" class="hint-icon" />
          <span class="hint-text">添加订阅前，请确保已在工具栏 <span class="highlight">"账号登录"</span>（含网易云/TK Cookie）中完成对应平台的登录或cookie配置，否则可能无法获取数据。</span>
        </div>
        <div class="static-hint-card warning">
          <Icon name="alert-triangle" :size="16" class="hint-icon" />
          <span class="hint-text"><strong>建议使用小号或专用 Cookie</strong> 登录对应平台，避免主账号因频繁访问触发风控限制。</span>
        </div>
        <!-- 平台选择 -->
        <div class="form-group">
          <label class="form-label">
            <Icon name="globe" :size="14" />
            <span>平台类型</span>
          </label>
          <select class="form-select form-select-modern" v-model="newSubscription.platform">
            <option value="douyin">抖音博主</option>
            <option value="douyin_collection">抖音合集</option>
            <option value="douyin_favorite">抖音点赞列表</option>
            <option value="tiktok">TikTok博主</option>
            <option value="instagram">Instagram博主</option>
            <option value="youtube_videos">YouTube博主</option>
            <option value="youtube_shorts">YouTube短视频</option>
            <option value="youtube_playlist">YouTube合集</option>
            <option value="bilibili">B站博主</option>
            <option value="bilibili_collection">B站合集</option>
            <option value="bilibili_favorite">B站收藏夹</option>
            <option value="xiaohongshu">小红书博主</option>
            <option value="netease_playlist">网易云歌单</option>
            <option value="x_favorite">X点赞列表</option>
          </select>
        </div>

        <!-- 链接输入（非抖音点赞） -->
        <div class="form-group" v-if="newSubscription.platform !== 'douyin_favorite'">
          <label class="form-label">
            <Icon name="link" :size="14" />
            <span>{{ getLinkLabel() }}</span>
          </label>
          <input 
            type="text" 
            class="form-input form-input-modern" 
            v-model="newSubscription.profile_url"
            :placeholder="getLinkPlaceholder()"
          />
          <div class="form-hint" v-if="getLinkHint()">
            {{ getLinkHint() }}
          </div>
        </div>

        <!-- 自定义博主名称（可选） -->
        <div class="form-group" v-if="newSubscription.platform === 'douyin'">
          <label class="form-label">
            <Icon name="user" :size="14" />
            <span>自定义博主名称（可选）</span>
          </label>
          <input
            type="text"
            class="form-input form-input-modern"
            v-model="newSubscription.nickname"
            placeholder="留空则使用平台昵称；填写后将锁定为自定义名称"
          />
          <div class="form-hint">
            用于订阅显示和目录名固化（创建时生效）
          </div>
          <div class="form-hint" style="color: var(--color-warning); margin-top: 2px;">
            💡 若博主昵称是纯 emoji（如 🏄 / 🏝️），建议填写自定义名称，避免下载目录名异常或冲突
          </div>
        </div>

        <!-- 平台特定提示 -->
        <div v-if="newSubscription.platform === 'douyin_favorite'" class="form-group">
          <div class="platform-hint platform-hint-info">
            <div class="hint-header">
              <Icon name="info" :size="16" />
              <span>抖音点赞列表订阅</span>
            </div>
            <div class="hint-content">
              <p>• 将订阅当前登录抖音账号的点赞列表</p>
              <p>• 系统会自动检测您点赞的新视频</p>
              <p class="hint-warning">⚠️ 请确保已登录抖音账号（点击工具栏"账号登录"）</p>
              <p class="hint-warning">⚠️ 如在浏览器中切换了抖音账号，请先删除本点赞订阅并重新添加，以避免账号不一致导致的数据异常</p>
            </div>
          </div>
        </div>

        <div v-if="newSubscription.platform === 'bilibili_favorite'" class="form-group">
          <div class="platform-hint platform-hint-info">
            <div class="hint-header">
              <Icon name="info" :size="16" />
              <span>B站收藏夹订阅</span>
            </div>
            <div class="hint-content">
              <p><strong>支持以下格式：</strong></p>
              <ul class="hint-list">
                <li>收藏夹URL：<code>https://www.bilibili.com/medialist/play/ml473071500</code></li>
                <li>收藏夹URL：<code>https://space.bilibili.com/416291500/favlist?fid=473071500</code></li>
                <li>直接输入收藏夹ID：<code>473071500</code></li>
              </ul>
              <p class="hint-warning">⚠️ 如需访问需要登录的收藏夹，请确保已配置B站Cookie</p>
            </div>
          </div>
        </div>

        <div v-if="newSubscription.platform === 'x_favorite'" class="form-group">
          <div class="platform-hint platform-hint-info">
            <div class="hint-header">
              <Icon name="info" :size="16" />
              <span>X点赞列表订阅</span>
            </div>
            <div class="hint-content">
              <p>• 将订阅指定用户的点赞视频列表</p>
              <p>• 输入主页链接或用户名（如：<code>https://x.com/bigbigvvv</code> 或 <code>@bigbigvvv</code>）</p>
              <p class="hint-warning">⚠️ 请确保已配置有效的 X cookie（auth_token + ct0）</p>
            </div>
          </div>
        </div>

        <!-- 更新周期 -->
        <div class="form-group">
          <label class="form-label">
            <Icon name="clock" :size="14" />
            <span>自动检测周期</span>
          </label>
          <select class="form-select form-select-modern" v-model="newSubscription.check_interval">
            <option :value="0">不自动检测</option>
            <option :value="1800">30分钟</option>
            <option :value="3600">1小时</option>
            <option :value="7200">2小时</option>
            <option :value="14400">4小时</option>
            <option :value="28800">8小时</option>
            <option :value="43200">12小时</option>
            <option :value="86400">24小时</option>
          </select>
          <div class="form-hint">系统将按此周期自动检测新视频</div>
          <div class="form-hint" style="color: var(--color-warning); margin-top: 4px;">
            💡 建议设置 1 小时以上，避免频繁请求触发平台风控机制
          </div>
        </div>

        <!-- 自动下载 -->
        <div class="form-group form-group-checkbox">
          <label class="checkbox-label-modern">
            <input type="checkbox" v-model="newSubscription.auto_download" class="checkbox-modern" />
            <span class="checkbox-custom"></span>
            <div class="checkbox-text">
              <span class="checkbox-title">自动下载新视频</span>
              <span class="checkbox-desc">检测到新视频后自动开始下载</span>
            </div>
          </label>
        </div>
      </div>

      <template #footer>
        <button class="btn btn-secondary" @click="showAddModal = false" :disabled="addingSubscription">取消</button>
        <button class="btn btn-primary" @click="addSubscription" :disabled="addingSubscription">
          <span v-if="addingSubscription" class="btn-loading">
            <span class="spinner-small"></span>
            添加中...
          </span>
          <span v-else>确定</span>
        </button>
      </template>
    </Modal>

    <!-- 备份/提示模态框 -->
    <Modal v-model:show="showTipModal" :title="tipTitle" :type="tipType">
      <div v-html="tipMessage"></div>
      <!-- 输入框（用于 prompt 类型） -->
      <input 
        v-if="tipType === 'prompt'" 
        v-model="tipInputValue"
        type="text"
        :placeholder="tipPlaceholder"
        :maxlength="tipMaxlength"
        class="tip-input"
        name="dev_sub_secret"
        autocomplete="one-time-code"
        autocapitalize="off"
        autocorrect="off"
        spellcheck="false"
        inputmode="numeric"
        maxlength="8"
        @keyup.enter="handleTipConfirm"
      />
      <template #footer v-if="tipType === 'confirm' || tipType === 'prompt'">
        <button class="btn btn-secondary" @click="handleTipCancel">取消</button>
        <button class="btn btn-primary" @click="handleTipConfirm">确定</button>
      </template>
    </Modal>

    <!-- 视频列表模态框 -->
    <VideoListModal 
      v-model:show="showVideosModal"
      :subscriptionId="currentSubscription?.id"
      :platform="currentSubscription?.platform"
      :youtubeTabType="currentSubscription?.youtube_tab_type"
      :subscriptionType="currentSubscription?.subscription_type"
      :currentQuality="currentSubscription?.quality"
      :nickname="currentSubscription?.nickname"
      :isDownloading="currentSubscription?.progressState?.status === 'downloading' && currentSubscription?.progressState?.type === 'batch_download_progress'"
      @qualityUpdated="handleQualityUpdated"
      @batchDownloadStarted="handleBatchDownloadStarted"
    />

    <!-- VNC登录模态框 -->
    <VncLoginModal 
      v-model:show="showVncModal"
      :platform="vncPlatform"
    />

    <!-- 批量设置全屏加载遮罩 -->
    <Transition name="drawer-fade">
      <div v-if="batchSettingLoading" class="batch-loading-overlay">
        <div class="batch-loading-content">
          <div class="loading-spinner-wrapper">
            <span class="batch-spinner"></span>
            <div class="loading-pulse"></div>
          </div>
          <h3 class="batch-loading-title">正在批量应用设置</h3>
          <p class="batch-loading-desc">请稍候，系统正在为您同步所有订阅项...</p>
        </div>
      </div>
    </Transition>

    <!-- 文件上传输入(隐藏) -->
    <input 
      type="file" 
      ref="fileInput" 
      @change="handleFileImport" 
      accept=".json"
      style="display: none;"
    />
    </div>
  </div>

  <!-- 现代简约滚动导航 -->
  <div class="modern-scroll-nav" :class="{ 'hide-when-video-list-open': showVideosModal }">
    <button 
      class="nav-item top" 
      :class="{ 'visible': showScrollTop }"
      @click.stop="scrollToTop"
      title="回到顶部"
    >
      <Icon name="chevron-up" :size="20" />
    </button>
    <div class="nav-divider" :class="{ 'visible': showScrollTop && showScrollBottom }"></div>
    <button 
      class="nav-item bottom" 
      :class="{ 'visible': showScrollBottom }"
      @click.stop="scrollToBottom"
      title="滚到底部"
    >
      <Icon name="chevron-down" :size="20" />
    </button>
  </div>
</template>

<style scoped>
/* 授权提示 */
.license-alert {
  text-align: center;
  background: var(--color-bg-card);
  border: 2px dashed var(--color-error);
  border-radius: var(--radius-xl);
  padding: 3rem 4rem;
  margin: 2rem auto;
  max-width: 800px;
}

.license-icon {
  font-size: 3rem;
  margin-bottom: var(--spacing-lg);
}

.license-actions {
  margin-top: var(--spacing-xl);
  display: flex;
  justify-content: center;
  gap: var(--spacing-lg);
}

@media (max-width: 768px) {
  .license-alert {
    padding: 24px 18px;
    margin: 20px 16px;
    border-radius: 18px;
    max-width: calc(100% - 32px);
    box-sizing: border-box;
  }

  .license-icon {
    font-size: 2.4rem;
  }

  .license-alert h2 {
    font-size: 22px;
  }

  .license-alert p {
    font-size: 14px;
  }

  .license-features {
    grid-template-columns: 1fr !important;
    gap: 10px 0;
    margin: 20px 0;
  }

  .feature-item {
    font-size: 13px;
    white-space: normal;
  }

  .license-actions {
    flex-direction: column;
    gap: 10px;
  }

  .license-actions .btn {
    width: 100%;
    padding: 10px 0;
    font-size: 14px;
  }
}

@media (max-width: 480px) {
  .license-alert {
    margin: 16px 12px;
    padding: 20px 14px;
  }

  .license-features {
    gap: 8px 0;
  }

  .feature-item {
    font-size: 12.5px;
  }
}

.action-group-hint-inline {
  margin-left: 6px;
  font-size: 11px;
  color: var(--color-warning);
  font-weight: 600;
  white-space: nowrap;
}

.license-features {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px 40px;
  margin: 32px 0;
  text-align: left;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--color-text-secondary);
  font-size: 15px;
  overflow-wrap: break-word;
  word-break: break-word;
}

.feature-item .icon {
  color: var(--color-success);
}

.spinner {
  width: 20px;
  height: 20px;
  border: 3px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 按钮加载状态 */
.btn-loading {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.spinner-small {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

.btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* 进度条通知栏样式 */
.progress-notification {
  margin-top: 6px;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 8px;
  width: 100%;
  height: 42px; /* 增加高度，给两行文字留足空间 */
  position: relative;
  overflow: hidden;
}

.progress-active-content,
.progress-idle-content {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  padding: 6px 10px; /* 增加内边距 */
  display: flex;
  flex-direction: column;
  justify-content: center;
  transition: all 0.3s ease;
  opacity: 0;
  pointer-events: none;
}

.progress-active-content.visible,
.progress-idle-content.visible {
  opacity: 1;
  pointer-events: auto;
}

.progress-idle-content {
  color: var(--color-text-tertiary);
  font-size: 0.75rem;
}

.next-update-label {
  display: flex;
  align-items: center;
  gap: 6px;
}

.progress-info {
  display: flex;
  margin-bottom: 4px; /* 增加文字和进度条之间的间距 */
  font-size: 0.75rem;
}

.progress-text {
  font-weight: 500;
  width: 100%; /* 占满第一行 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.progress-count {
  color: #666;
  font-family: monospace;
  font-size: 0.75rem;
  margin-left: 8px;
  white-space: nowrap;
  flex-shrink: 0;
}

.progress-status-row {
  display: flex;
  align-items: center;
  width: 100%;
}

/* 进度条容器（支持hover显示取消按钮） */
.progress-track-wrapper {
  position: relative;
  flex: 1; /* 占据剩余空间 */
}

/* 进度条基础样式 */
.progress-track {
  width: 100%;
  height: 4px;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 2px;
  overflow: hidden;
  position: relative;
  flex: 1; /* 如果不在 wrapper 里也应该自适应 */
}

/* 按钮已改为常驻并在数值右侧 */

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #e74c3c 0%, #f39c12 100%);
  border-radius: 2px;
  transition: width 0.3s ease, background-color 0.3s ease;
}

/* 状态颜色 */
.text-success, .bg-success { color: #48bb78; }
.progress-fill.bg-success { background-color: #48bb78; }

.text-warning, .bg-warning { color: #ed8936; }
.progress-fill.bg-warning { background-color: #ed8936; }

.text-danger, .bg-danger { color: #f56565; }
.progress-fill.bg-danger { background-color: #f56565; }

.text-primary { color: #e67e22; }

/* 失败详情 */
.progress-error-detail {
  margin-top: 4px;
  font-size: 0.75rem;
  color: #f56565;
  display: flex;
  justify-content: flex-end;
}

/* 不确定进度动画 (Indeterminate) */
.progress-fill.indeterminate {
  width: 100% !important;
  background: linear-gradient(90deg, transparent, #e74c3c, #f39c12, transparent);
  background-size: 200% 100%;
  animation: loading 1.5s infinite;
}

@keyframes loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* 取消下载按钮（行内常驻显示，放在数值右侧） */
.cancel-download-btn-inline {
  margin-left: 8px;
  width: 18px;
  height: 18px;
  border-radius: 4px; /* 改为圆角矩形，更符合行内按钮风格 */
  border: 1px solid #f56565;
  background: white;
  color: #f56565;
  cursor: pointer;
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  flex-shrink: 0;
  padding: 0;
  line-height: 1;
}

.cancel-download-btn-inline:hover:not(:disabled) {
  background: #f56565;
  color: #fff;
  transform: scale(1.1);
}

.cancel-download-btn-inline:active:not(:disabled) {
  transform: scale(0.9);
}

.cancel-download-btn-inline:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  color: #ed8936;
  border-color: #ed8936;
}

/* 状态灯闪烁动画 */
.status-blinking {
  animation: status-blink 1s infinite;
  background-color: #ffc107 !important; /* 黄色闪烁 */
  box-shadow: 0 0 8px rgba(255, 193, 7, 0.6);
}

@keyframes status-blink {
  0%, 100% { opacity: 1; box-shadow: 0 0 5px rgba(255, 193, 7, 0.6); }
  50% { opacity: 0.5; box-shadow: 0 0 12px rgba(255, 193, 7, 0.9); }
}

/* 快捷操作栏样式 */
.quick-actions-toolbar {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.subscription-error-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  margin-top: 4px;
  color: var(--color-error);
  font-size: 12px;
  line-height: 1.35;
  overflow: hidden;
  position: relative;
}

.subscription-error-hint .error-hint-icon {
  flex-shrink: 0;
}

.subscription-error-hint .marquee-wrap {
  overflow: hidden;
  flex: 1;
  min-width: 0;
  mask-image: linear-gradient(to right, transparent 0%, #000 8%, #000 92%, transparent 100%);
  -webkit-mask-image: linear-gradient(to right, transparent 0%, #000 8%, #000 92%, transparent 100%);
}

.subscription-error-hint .marquee-text {
  display: inline-block;
  white-space: nowrap;
  padding-left: 100%;
  animation: marquee-scroll 12s linear infinite;
}

@keyframes marquee-scroll {
  0% { transform: translateX(0); }
  100% { transform: translateX(-100%); }
}

.drawer-error-panel {
  margin: 10px 0 12px;
  padding: 10px 12px;
  border: 1px solid rgba(239, 68, 68, 0.28);
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.08);
}

.drawer-error-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--color-error);
  font-size: 13px;
  font-weight: 600;
}

.drawer-error-detail {
  margin-top: 6px;
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.5;
  word-break: break-word;
}

.toolbar-btn {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  border: none;
  cursor: pointer;
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  transition: all 0.2s ease;
  white-space: nowrap;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  transform: translateY(0);
  box-shadow: 0 0 0 rgba(0, 0, 0, 0);
}

[data-theme="dark"] .toolbar-btn {
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
}

.toolbar-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
  transform: translateY(-1px) scale(1.02);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

[data-theme="dark"] .toolbar-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.toolbar-btn:active {
  transform: translateY(0) scale(0.98);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
}

/* 统一按钮样式 - 已移除播放按钮的特殊样式 */


/* 文字切换逻辑 */
.mobile-only { display: none !important; }
.desktop-only { display: block; }
.mobile-text { display: none; }
.desktop-text { display: inline; }

@media (max-width: 768px) {
  .mobile-only { display: inline-flex !important; }
  .desktop-only { display: none !important; }
  .mobile-text { display: inline; }
  .desktop-text { display: none; }
}

.toolbar-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background: var(--color-bg-tertiary);
}

[data-theme="dark"] .toolbar-btn:disabled {
  background: var(--color-bg-tertiary);
}

/* 现代简约滚动导航样式 */
.modern-scroll-nav {
  position: fixed;
  right: 24px;
  bottom: 32px;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(10px);
  z-index: 1000;
  overflow: hidden;
  transition: all 0.3s ease;
}

[data-theme="dark"] .modern-scroll-nav {
  background: rgba(30, 30, 30, 0.8);
  border-color: rgba(255, 255, 255, 0.1);
}

.nav-item {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  background: transparent;
  border: none;
  color: var(--color-text-secondary);
  transition: all 0.2s ease;
  padding: 0;
}

.nav-item:hover {
  color: var(--color-primary);
  background: var(--color-bg-hover);
}

/* 动态隐藏逻辑：平滑缩放 */
.nav-item.top, .nav-item.bottom {
  height: 0;
  opacity: 0;
  overflow: hidden;
  pointer-events: none;
}

.nav-item.visible {
  height: 44px;
  opacity: 1;
  pointer-events: auto;
}

.nav-divider {
  height: 0;
  width: 24px;
  margin: 0 auto;
  background: var(--color-border);
  opacity: 0;
  transition: all 0.3s ease;
}

.nav-divider.visible {
  height: 1px;
  opacity: 0.5;
}

@media (max-width: 768px) {
  .modern-scroll-nav {
    right: 16px;
    bottom: 24px;
  }
  
  /* 移动端下，当视频列表打开时隐藏快捷滚动组件 */
  .modern-scroll-nav.hide-when-video-list-open {
    display: none;
  }
}
</style>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, reactive, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import Modal from '@/components/common/Modal.vue'
import SkeletonLoader from '@/components/common/SkeletonLoader.vue'
import VideoListModal from '@/components/business/VideoListModal.vue'
import VncLoginModal from '@/components/business/VncLoginModal.vue'
import { subscriptionsApi, resolveAvatarUrl, handleImageError as sharedHandleImageError } from '@/api/subscriptions'
import { systemApi, licenseApi, cookieApi } from '@/api/index'
import { wsService } from '@/utils/websocket'
import { buildAuthedWsUrl } from '@/utils/wsAuth'
import { useBatchDownloadProgress } from '@/composables/useBatchDownloadProgress'
import { useToast } from '@/composables/useToast'


const router = useRouter()
const route = useRoute()
const toast = useToast()

// 授权状态 - 优先读取本地缓存，避免闪烁
const cachedLicense = localStorage.getItem('license_status')
const licenseValid = ref(cachedLicense === 'true')
// 用 ref 跟踪是否有缓存，避免并发调用时 const 值不变的问题
const hasCachedLicense = ref(cachedLicense !== null)
// 如果有缓存，初始不显示loading；如果无缓存，显示loading
const checkingLicense = ref(cachedLicense === null)

async function checkLicense(force = false) {
    // 只有在没有缓存时才显示loading状态，否则静默更新
    if (!hasCachedLicense.value) {
        checkingLicense.value = true
    }

    try {
        // 只有在手动强制刷新时，才请求后端去授权服务器验证
        if (force) {
            try {
                await licenseApi.refresh()
            } catch (e) {
                console.warn('刷新授权失败，将使用缓存状态', e)
            }
        }

        const res = await licenseApi.getStatus()
        licenseValid.value = res.is_licensed
        hasCachedLicense.value = true
        // 更新本地缓存
        localStorage.setItem('license_status', res.is_licensed)

        if (force && res.is_licensed) {
             customAlert('提示', '授权状态已刷新', 'success')
        }
    } catch (e) {
        // 仅在明确失败时才置为false
        if (!hasCachedLicense.value) {
             licenseValid.value = false
        }
        console.error('License check failed:', e)
    } finally {
        checkingLicense.value = false
    }
}

// 数据状态
const loading = ref(true)
const hasLoadedOnce = ref(false)
const subscriptions = ref([])
const filteredSubscriptions = ref([])

// 使用统一的批量下载进度管理 Composable
const {
  progressStates,
  updateTrigger,
  getProgressState,
  addTask,
  removeTask,
  restoreProgressStates,
  startWebSocketListener,
  startPolling,
  cleanup
} = useBatchDownloadProgress()


// 抽屉状态
const showDetailDrawer = ref(false)
const currentSubscription = ref(null)

// 筛选器
const platformFilter = ref('') // 保持为字符串以兼容 Dashboard 跳转，但自定义下拉框会处理成数组形式进行多选展示
const selectedPlatforms = ref([]) // 实际选中的平台列表
const showPlatformDropdown = ref(false)
const statusFilter = ref('')
const showStatusDropdown = ref(false)

function getStatusText(status) {
  const map = {
    '': '全部状态',
    'active': '正常',
    'paused': '暂停/未开自检',
    'error': '异常',
    'invalid': '失效',
    'no_auto_download': '未开自下'
  }
  return map[status] || '全部状态'
}

function getSubscriptionErrorDetail(sub) {
  const message = sub?.error_message || sub?.progressState?.message || ''
  return String(message || '').trim()
}

function getSubscriptionErrorSummary(sub) {
  const detail = getSubscriptionErrorDetail(sub)
  if (!detail) return ''
  const text = detail.toLowerCase()
  if (text.includes('instagram 处于风控冷却期') || text.includes('风控冷却')) {
    return 'Instagram 风控冷却中，请在 APP 完成验证后点击解除'
  }
  if (text.includes('exceeded 30 redirects')) {
    return 'Instagram 登录态或访问环境异常'
  }
  if (text.includes('session 登录失败') || text.includes('login required') || text.includes('login_required')) {
    return 'Instagram 登录态失效，请重新保存账号密码'
  }
  if (text.includes('challenge') || text.includes('checkpoint')) {
    return 'Instagram 触发验证，请在 APP 完成验证后点击解除'
  }
  if (text.includes('429') || text.includes('too many')) {
    return 'Instagram 请求过于频繁，稍后自动恢复或点击解除'
  }
  if (text.includes('403')) {
    return 'Instagram 拒绝访问，检查网络环境或重新保存账号密码'
  }
  if (sub?.platform === 'instagram') {
    return `Instagram 检测失败：${detail.slice(0, 36)}`
  }
  const platformNames = {
    douyin: '抖音', douyin_collection: '抖音合集',
    youtube: 'YouTube', youtube_playlist: 'YouTube播放列表',
    bilibili: 'B站', bilibili_collection: 'B站合集',
    tiktok: 'TikTok',
    x: 'X',
    netease: '网易云',
    xiaohongshu: '小红书'
  }
  const name = (sub?.platform && platformNames[sub.platform]) || sub?.platform || '订阅'
  return `${name}检测异常，请检查登录状态和Cookie是否有效`
}

function selectStatus(status) {
  statusFilter.value = status
  showStatusDropdown.value = false
  filterSubscriptions()
}
const searchQuery = ref('')
const showVideosModal = ref(false)
const videos = ref([])

// 模态框
const showAddModal = ref(false)
const showTipModal = ref(false)
const tipTitle = ref('')
const tipMessage = ref('')
const tipType = ref('info') // info, success, warning, error, confirm, prompt
const tipInputValue = ref('')
const tipPlaceholder = ref('请输入内容')
const tipMaxlength = ref(200)
let tipResolve = null

// VNC登录模态框
const showVncModal = ref(false)
const vncPlatform = ref('douyin')

// 新订阅表单
const newSubscription = ref({
  platform: 'douyin',
  profile_url: '',
  nickname: '',
  check_interval: 14400,
  auto_download: true
})
const skipXhsWarningOnce = ref(false)

// 添加订阅加载状态
const addingSubscription = ref(false)

// 文件上传
const fileInput = ref(null)

// 批量设置加载状态
const batchSettingLoading = ref(false)

// 移动端功能区折叠状态
const actionPanelExpanded = ref(false)

// 滚动逻辑
const showScrollTop = ref(false)
const showScrollBottom = ref(true)

const handleScroll = (event) => {
  // 如果没有传入 event（手动调用），则直接查找容器
  const container = event?.target || document.querySelector('.main-content')
  if (!container || !container.classList?.contains('main-content')) return

  const scrollY = container.scrollTop
  const windowHeight = container.clientHeight
  const fullHeight = container.scrollHeight
  
  showScrollTop.value = scrollY > 400
  showScrollBottom.value = (fullHeight - scrollY - windowHeight) > 200
}

const scrollToTop = () => {
  const container = document.querySelector('.main-content')
  if (container) {
    container.scrollTo({ top: 0, behavior: 'smooth' })
  } else {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

const scrollToBottom = () => {
  const container = document.querySelector('.main-content')
  if (container) {
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
  } else {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' })
  }
}

// 加载订阅列表
async function loadSubscriptions() {
  loading.value = true
  try {
    const data = await subscriptionsApi.getList()
    // 后端直接返回数组
    subscriptions.value = Array.isArray(data) ? data : []
    
    // 使用 Composable 恢复批量下载进度状态
    await restoreProgressStates(subscriptions.value)
    
    // 初始应用路由参数（如果有）
    handleRouteQuery()
    
    // 如果路由参数为空，则从 localStorage 恢复筛选状态
    if (!route.query.status && !route.query.platform) {
      applyFiltersFromStorage()
    } else {
      // 如果有路由参数，使用路由参数筛选
      filterSubscriptions()
    }
    
    // 加载完成后初始化WebSocket监听（用于同步进度等其他功能）
    initStoreWebSockets()
    
    // 数据加载后，高度发生变化，重新计算按钮状态
    nextTick(() => {
      handleScroll()
    })
  } catch (error) {
    console.error('加载订阅失败:', error)
  } finally {
    loading.value = false
    hasLoadedOnce.value = true
  }
}

// 打开添加订阅前的风险确认
async function confirmOpenAddModal() {
  const confirmed = await customConfirm(
    '风险提示',
    `
      <div style="text-align: left; line-height: 1.7;">
        <p><strong>⚠️ 订阅功能可能触发平台风控/封禁风险</strong></p>
        <p>频繁检测、自动化访问等行为可能导致账号被限制或封禁。</p>
        <p style="color: var(--color-warning);"><strong>建议使用小号登录。</strong></p>
        <p style="margin-top: 8px;">是否继续添加订阅？</p>
      </div>
    `
  )
  if (confirmed) {
    showAddModal.value = true
  }
}

// 处理路由参数
function handleRouteQuery() {
  if (route.path !== '/subscriptions') return
  const { status, platform } = route.query
  
  // 总是根据 URL 参数重置筛选状态，确保从仪表盘跳转时的准确性
  
  // 1. 处理状态筛选
  if (status) {
    // 如果是 'all'，也重置为空字符串
    statusFilter.value = status === 'all' ? '' : status
  } else {
    // URL不包含状态参数时，重置为空（显示全部）
    statusFilter.value = ''
  }
  
  // 2. 处理平台筛选
  if (platform) {
    // 平台筛选如果是多选，这里简化处理，如果传了单个值就置为单选
    // 如果是 all，则清空
    if (platform === 'all') {
      selectedPlatforms.value = []
    } else {
      selectedPlatforms.value = [platform]
    }
  } else {
    // URL不包含平台参数时，重置为空（显示全部）
    selectedPlatforms.value = []
  }
  
  // 执行筛选
  filterSubscriptions()

  // 3. 处理订阅 ID (跳转后自动打开视频列表)
  const { sub_id } = route.query
  if (sub_id && subscriptions.value.length > 0) {
    nextTick(() => {
      const sub = subscriptions.value.find(s => s.id === sub_id)
      if (sub) {
        viewVideos(sub)
      }
    })
  }
}

// 监听路由变化
watch(() => route.query, () => {
  handleRouteQuery()
}, { deep: true })

// 为订阅附加进度状态（computed 属性，自动响应 progressStates 变化）
const subscriptionsWithProgress = computed(() => {
  // 访问 updateTrigger 以确保响应式更新
  updateTrigger.value
  
  return subscriptions.value.map(sub => {
    const downloadProgressState = getProgressState(sub.id)
    // 优先使用下载进度，其次使用本地保存的进度（同步/检测），最后使用默认空状态
    // 修复：之前逻辑会强制覆盖 handleSyncProgress 等方法设置的 sub.progressState
    const progressState = downloadProgressState || sub.progressState || {
      visible: false,
      message: '',
      current: 0,
      total: 0,
      percent: 0,
      status: '',
      statusClass: 'text-primary',
      indeterminate: false,
      type: ''
    }

    return {
      ...sub,
      progressState
    }
  })
})


// WebSocket 管理
const wsConnections = new Map() // subId -> WebSocket
let unregisterBatchTasks = null

// 记录当前批量检测任务，用于在卡片上提示/收尾
const currentBatchCheck = reactive({
  active: false,
  taskId: '',
  subIds: []
})

// 记录当前批量添加任务（抖音博主）
const currentBatchAdd = reactive({
  active: false,
  taskId: '',
  total: 0,
  processed: 0,
  success: 0,
  failed: 0,
  skipped: 0
})

function initStoreWebSockets() {
  // 为所有订阅建立连接（或根据可见性优化，这里先全量建立以保证实时性）
  subscriptions.value.forEach(sub => {
    connectWebSocket(sub.id)
  })
}

function connectWebSocket(subId) {
  if (wsConnections.has(subId)) {
    const ws = wsConnections.get(subId)
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
      return
    }
  }

  try {
    const url = buildAuthedWsUrl(`/api/ws/subscribe/${subId}/progress`)
    
    const ws = new WebSocket(url)
    
    // 心跳定时期
    let pingInterval
    
    ws.onopen = () => {
      // console.log(`WebSocket connected for subscription ${subId}`)
      // 每30秒发送一次心跳
      pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping')
        }
      }, 30000)
    }
    
    ws.onmessage = (event) => {
      if (event.data === 'pong') return
      try {
        const data = JSON.parse(event.data)
        handleWsMessage(subId, data)
      } catch (e) {
        console.error('WebSocket message parse error:', e)
      }
    }
    
    ws.onerror = (err) => {
      // console.error(`WebSocket error for ${subId}:`, err)
    }
    
    ws.onclose = () => {
      wsConnections.delete(subId)
      if (pingInterval) clearInterval(pingInterval)
    }
    
    wsConnections.set(subId, ws)
  } catch (e) {
    console.error(`Failed to connect WebSocket for ${subId}:`, e)
  }
}

function handleWsMessage(subId, data) {
  const sub = subscriptions.value.find(s => s.id === subId)
  if (!sub) return

  // 批量下载进度由 Composable 统一处理，这里只处理同步进度和检测结果
  if (data.type === 'batch_download_progress') {
    // 批量下载进度已由 useBatchDownloadProgress Composable 处理
    // 这里不需要额外处理
    return
  } else if (data.type === 'sync_progress') {
    handleSyncProgress(sub, data)
  } else if (data.type === 'check_result') {
    handleCheckResult(sub, data)
  }
}

function handleCheckResult(sub, data) {
  const state = sub.progressState
  state.visible = true
  state.indeterminate = false
  const hasUpdate = !!data.has_update
  const count = data.new_videos_count || 0
  if (hasUpdate && count > 0) {
    state.message = `检测完成，发现 ${count} 个新视频`
    state.statusClass = 'text-success'
    state.percent = 100
  } else {
    state.message = '检测完成，暂无更新'
    state.statusClass = 'text-gray'
    state.percent = 100
  }
  setTimeout(() => { state.visible = false }, 3000)
}

// 批量检测（进度汇总）WebSocket
function handleBatchTaskMessage(id, data) {
  if (id !== 'batch_tasks') return
  if (data.type === 'batch_check_progress') {
    // 仅处理当前前端发起的批量检测任务
    if (!currentBatchCheck.active || data.task_id !== currentBatchCheck.taskId) return

    const isFinished = data.status === 'completed' || data.status === 'error'

    // 如果还有任务未结束，保持卡片“检测中”状态
    if (!isFinished) return

    // 结束：更新提示后清理卡片状态
    currentBatchCheck.subIds.forEach(subId => {
      const sub = subscriptions.value.find(s => s.id === subId)
      if (!sub) return
      if (!sub.progressState) {
        sub.progressState = { visible: false, message: '', current: 0, total: 0, percent: 0, statusClass: 'text-primary' }
      }
      sub.is_checking = false
      sub.progressState.visible = true
      if (data.status === 'completed') {
        sub.progressState.message = '批量检测完成（请查看更新结果）'
        sub.progressState.statusClass = 'text-success'
      } else {
        sub.progressState.message = '批量检测结束（可能有失败，请查看日志）'
        sub.progressState.statusClass = 'text-warning'
      }
      setTimeout(() => {
        sub.progressState.visible = false
      }, 3000)
    })

    currentBatchCheck.active = false
    currentBatchCheck.taskId = ''
    currentBatchCheck.subIds = []
    return
  }

  if (data.type === 'batch_add_progress') {
    if (!currentBatchAdd.active || data.task_id !== currentBatchAdd.taskId) return

    currentBatchAdd.total = data.total ?? currentBatchAdd.total
    currentBatchAdd.processed = data.processed ?? currentBatchAdd.processed
    currentBatchAdd.success = data.success ?? currentBatchAdd.success
    currentBatchAdd.failed = data.failed ?? currentBatchAdd.failed
    currentBatchAdd.skipped = data.skipped ?? currentBatchAdd.skipped

    const isFinished = data.status === 'completed' || data.status === 'error'
    if (!isFinished) return

    const errors = Array.isArray(data.errors) ? data.errors : []
    const errorHtml = errors.length > 0
      ? `<div style="margin-top: 10px; max-height: 180px; overflow: auto; background: rgba(0,0,0,0.03); padding: 10px; border-radius: 6px; font-size: 12px;">${errors.map(err => `<div style="margin-bottom: 6px;">• ${err}</div>`).join('')}</div>`
      : ''

    customAlert(
      data.failed > 0 ? '批量添加完成（部分失败）' : '批量添加完成',
      `
        <div style="text-align: left;">
          <div><strong>总计：</strong>${data.total || currentBatchAdd.total || 0}</div>
          <div><strong>成功：</strong>${data.success || 0}</div>
          <div><strong>跳过：</strong>${data.skipped || 0}</div>
          <div><strong>失败：</strong>${data.failed || 0}</div>
          ${errorHtml}
        </div>
      `,
      data.failed > 0 ? 'warning' : 'success'
    )

    currentBatchAdd.active = false
    currentBatchAdd.taskId = ''
    currentBatchAdd.total = 0
    currentBatchAdd.processed = 0
    currentBatchAdd.success = 0
    currentBatchAdd.failed = 0
    currentBatchAdd.skipped = 0

    loadSubscriptions()
  }
}

function handleSyncProgress(sub, data) {
  // 确保 progressState 存在（同步进度不使用 Composable）
  if (!sub.progressState) {
    sub.progressState = {
      visible: false,
      message: '',
      current: 0,
      total: 0,
      percent: 0,
      status: '',
      statusClass: 'text-primary',
      failed: 0,
      indeterminate: false,
      type: ''
    }
  }
  
  const state = sub.progressState
  state.visible = true
  // 同步状态也记录 status
  state.status = data.status
  state.type = 'sync_progress' // 标记为同步进度，不显示取消按钮
  const totalVideos = sub.video_count || 100 // 估算或使用现有值
  
  if (data.status === 'syncing') {
    state.current = data.count || 0
    state.total = totalVideos 
    
    if (state.total > 0) {
      state.percent = (state.current / state.total) * 100
    }
    
    // 优先使用后端发送的消息
    if (data.message) {
      let msg = data.message
      // 进一步优化：去除平台名和“媒体”字样，极致节省空间
      msg = msg.replace(/(Instagram|YouTube|Bilibili|TikTok|小红书|抖音|X|媒体)/gi, '')
      msg = msg.replace(/\s+/g, ' ').trim()
      state.message = msg
      state.indeterminate = state.current === 0 
    } else if (state.current === 0) {
      state.indeterminate = true
      state.message = '准备中...'
    } else {
      state.indeterminate = false
      state.message = `同步 ${data.count} 条`
    }
    state.statusClass = 'text-primary'
    
  } else if (data.status === 'completed') {
    state.indeterminate = false
    state.message = `同步完成 (共${data.count}个)`
    state.statusClass = 'bg-success'
    state.percent = 100
    setTimeout(() => { if(state.message.includes('同步完成')) state.visible = false }, 3000)
  } else if (data.status === 'error') {
    state.indeterminate = false
    state.message = data.error || '同步失败'
    state.statusClass = 'bg-danger'
  } else if (data.status === 'skipped') {
    state.indeterminate = false
    state.message = '已跳过同步'
    state.statusClass = 'text-gray'
    setTimeout(() => { state.visible = false }, 3000)
  }
}

// 组件卸载时关闭连接
onUnmounted(() => {
  wsConnections.forEach(ws => ws.close())
  wsConnections.clear()
  if (unregisterBatchTasks) unregisterBatchTasks()
  wsService.close('batch_tasks')
})

// 筛选订阅
function filterSubscriptions() {
  let result = subscriptionsWithProgress.value

  // 平台多选筛选
  if (selectedPlatforms.value.length > 0) {
    result = result.filter(sub => {
      return selectedPlatforms.value.some(filter => {
        // ===== 抖音系列 =====
        if (filter === 'douyin') {
          return sub.platform === 'douyin' || sub.platform === 'douyin_collection'
        }
        if (filter === 'douyin_creator') {
          return sub.platform === 'douyin' && sub.subscription_type !== 'favorite' && sub.subscription_type !== 'collection'
        }
        if (filter === 'douyin_collection') {
          return sub.platform === 'douyin_collection' || (sub.platform === 'douyin' && sub.subscription_type === 'collection')
        }
        if (filter === 'douyin_favorite') {
          return sub.platform === 'douyin' && sub.subscription_type === 'favorite'
        }
        
        // ===== TikTok =====
        if (filter === 'tiktok') {
          return sub.platform === 'tiktok'
        }
        
        // ===== YouTube 系列 =====
        if (filter === 'youtube') {
          return sub.platform === 'youtube' || sub.platform === 'youtube_playlist'
        }
        if (filter === 'youtube_channel') {
          return sub.platform === 'youtube' && (!sub.youtube_tab_type || sub.youtube_tab_type === 'videos')
        }
        if (filter === 'youtube_shorts') {
          return sub.platform === 'youtube' && sub.youtube_tab_type === 'shorts'
        }
        if (filter === 'youtube_playlist') {
          return sub.platform === 'youtube_playlist'
        }
        
        // ===== Bilibili 系列 =====
        if (filter === 'bilibili') {
          return sub.platform === 'bilibili' || sub.platform === 'bilibili_collection'
        }
        if (filter === 'bilibili_creator') {
          return sub.platform === 'bilibili' && sub.subscription_type !== 'favorite' && sub.subscription_type !== 'collection'
        }
        if (filter === 'bilibili_collection') {
          return sub.platform === 'bilibili_collection' || (sub.platform === 'bilibili' && sub.subscription_type === 'collection')
        }
        if (filter === 'bilibili_favorite') {
          return sub.platform === 'bilibili' && sub.subscription_type === 'favorite'
        }

        // ===== Instagram =====
        if (filter === 'instagram') {
          return sub.platform === 'instagram'
        }

        // ===== 小红书 =====
        if (filter === 'xiaohongshu') {
          return sub.platform === 'xiaohongshu'
        }

        // ===== X 点赞 =====
        if (filter === 'x_favorite') {
          return sub.platform === 'x' && sub.subscription_type === 'favorite'
        }
        
        return sub.platform === filter
      })
    })
  }

  // 状态筛选
  if (statusFilter.value) {
    const filter = statusFilter.value
    result = result.filter(sub => {
      const interval = sub.check_interval || sub.update_interval || 0
      const isAutoDownload = sub.auto_download === true || sub.auto_download === 'true'
      
      if (filter === 'active') {
        return sub.status === 'active' && interval > 0
      }
      if (filter === 'paused') {
        return sub.status === 'paused' || interval === 0
      }
      if (filter === 'no_auto_download') {
        return !isAutoDownload
      }
      if (filter === 'error') {
        return sub.status === 'error'
      }
      if (filter === 'invalid') {
        return sub.status === 'invalid'
      }
      return true
    })
  }

  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(sub => 
      sub.nickname?.toLowerCase().includes(query) || 
      sub.signature?.toLowerCase().includes(query)
    )
  }


  filteredSubscriptions.value = result
}

function resetFilters() {
  selectedPlatforms.value = []
  statusFilter.value = ''
  searchQuery.value = ''
  filterSubscriptions()
}

// 监听筛选条件变化，保存到 localStorage
watch([selectedPlatforms, statusFilter, searchQuery], ([newPlatforms, newStatus, newSearchQuery]) => {
  localStorage.setItem('subscription_platform_filter', newPlatforms.join(','))
  localStorage.setItem('subscription_status_filter', newStatus)
  localStorage.setItem('subscription_search_query', newSearchQuery || '')
}, { deep: true });

const platformNamesMap = {
  'douyin': '全部抖音',
  'douyin_creator': '抖音博主',
  'douyin_collection': '抖音合集',
  'douyin_favorite': '抖音点赞',
  'tiktok': 'TikTok博主',
  'instagram': 'Instagram博主',
  'youtube': '全部YouTube',
  'youtube_channel': '油管博主',
  'youtube_shorts': '油管短视频',
  'youtube_playlist': '油管合集',
  'bilibili': '全部B站',
  'bilibili_creator': 'B站博主',
  'bilibili_collection': 'B站合集',
  'bilibili_favorite': 'B站收藏夹',
  'xiaohongshu': '小红书',
  'netease': '网易云歌单',
  'x_favorite': 'X点赞'
};

const selectedPlatformsText = computed(() => {
  if (selectedPlatforms.value.length === 0) return '全部平台';
  if (selectedPlatforms.value.length === 1) return platformNamesMap[selectedPlatforms.value[0]] || selectedPlatforms.value[0];
  return `已选 ${selectedPlatforms.value.length} 个平台`;
});

// 定义平台关系
const platformRelations = {
  'douyin': ['douyin_creator', 'douyin_collection', 'douyin_favorite'],
  'youtube': ['youtube_channel', 'youtube_shorts', 'youtube_playlist'],
  'bilibili': ['bilibili_creator', 'bilibili_collection', 'bilibili_favorite']
};

// 工具函数：获取子项所属的父项
const getParentPlatform = (child) => {
  for (const [parent, children] of Object.entries(platformRelations)) {
    if (children.includes(child)) return parent;
  }
  return null;
};

// 判断平台是否被选中（支持父子联动视觉显示）
function isPlatformSelected(platform) {
  // 如果当前项被直接选中
  if (selectedPlatforms.value.includes(platform)) return true;
  
  // 如果父项被选中，所有子项视觉上也是选中状态
  const parent = getParentPlatform(platform);
  if (parent && selectedPlatforms.value.includes(parent)) return true;
  
  return false;
}

function togglePlatform(platform) {
  const isParent = platformRelations[platform] !== undefined;
  const children = platformRelations[platform] || [];
  const parent = getParentPlatform(platform);
  
  if (isParent) {
    // 点击的是父项（如全部抖音）
    const index = selectedPlatforms.value.indexOf(platform);
    if (index === -1) {
      // 选中父项时，移除所有已经选中的子项，保持数组简洁
      selectedPlatforms.value = selectedPlatforms.value.filter(p => !children.includes(p));
      selectedPlatforms.value.push(platform);
    } else {
      selectedPlatforms.value.splice(index, 1);
    }
  } else {
    // 点击的是子项（如抖音博主）
    const index = selectedPlatforms.value.indexOf(platform);
    const parentIndex = parent ? selectedPlatforms.value.indexOf(parent) : -1;
    
    if (parentIndex !== -1) {
      // 如果父项已选中，点击子项意味着想“取消全选并仅取消这一子项”
      // 逻辑上转换为：选中除了当前点击子项外的所有其他子项
      const otherChildren = platformRelations[parent].filter(c => c !== platform);
      selectedPlatforms.value.splice(parentIndex, 1);
      selectedPlatforms.value.push(...otherChildren);
    } else {
      // 正常切换子项状态
      if (index === -1) {
        selectedPlatforms.value.push(platform);
        // 检查是否所有子项都已选中，如果是，则自动转换为父项
        if (parent) {
          const allChildrenSelected = platformRelations[parent].every(c => selectedPlatforms.value.includes(c));
          if (allChildrenSelected) {
            selectedPlatforms.value = selectedPlatforms.value.filter(p => !platformRelations[parent].includes(p));
            selectedPlatforms.value.push(parent);
          }
        }
      } else {
        selectedPlatforms.value.splice(index, 1);
      }
    }
  }
  filterSubscriptions();
}

function toggleAllPlatforms() {
  selectedPlatforms.value = [];
  filterSubscriptions();
}

// 监听 platformFilter 变化 (Dashboard 跳转)
watch(platformFilter, (newVal) => {
  if (newVal) {
    selectedPlatforms.value = [newVal]
    filterSubscriptions()
  }
})

// 监听数据源变化（包括进度更新），自动刷新列表
watch(subscriptionsWithProgress, () => {
  filterSubscriptions()
})

// 添加订阅
async function addSubscription() {
  if (addingSubscription.value) return // 防止重复提交
  
  try {
    addingSubscription.value = true
    
    if (newSubscription.value.platform === 'douyin_favorite') {
      // 抖音点赞列表不需要 profile_url，后端会使用浏览器中登录的抖音账号
      await subscriptionsApi.addDouyinFavorite({
        auto_download: String(newSubscription.value.auto_download).toLowerCase()
      })
    } else {
      // 验证必填字段
      if (!newSubscription.value.profile_url || !newSubscription.value.profile_url.trim()) {
        customAlert('添加订阅失败', '请输入主页链接', 'error')
        addingSubscription.value = false
        return
      }

      // 根据平台类型构建订阅数据
      let subscriptionData = {
        profile_url: newSubscription.value.profile_url.trim(),
        update_interval: newSubscription.value.check_interval,
        auto_download: String(newSubscription.value.auto_download).toLowerCase()
      }
      const platform = newSubscription.value.platform
      const customNickname = (newSubscription.value.nickname || '').trim()
      if (platform === 'douyin' && customNickname) {
        subscriptionData.nickname = customNickname
      }

      // 处理不同的平台类型
      if (platform === 'youtube_videos') {
        // 油管博主
        subscriptionData.platform = 'youtube'
        subscriptionData.youtube_tab_type = 'videos'
      } else if (platform === 'youtube_shorts') {
        // 油管短视频
        subscriptionData.platform = 'youtube'
        subscriptionData.youtube_tab_type = 'shorts'
      } else if (platform === 'youtube_playlist') {
        // 油管合集：从播放列表链接提取playlist_id，或直接使用输入的播放列表ID
        let playlistId = null
        const profileUrl = newSubscription.value.profile_url || ''
        
        // 尝试从URL中提取播放列表ID
        const playlistMatch = profileUrl.match(/[?&]list=([^&]+)/)
        if (playlistMatch) {
          playlistId = playlistMatch[1]
        } else if (profileUrl && !profileUrl.startsWith('http')) {
          // 如果输入不是URL，可能是直接输入的播放列表ID
          // YouTube播放列表ID通常以PL开头
          if (profileUrl.startsWith('PL') && profileUrl.length >= 10) {
            playlistId = profileUrl
          } else {
            // 尝试从输入中提取播放列表ID
            const idMatch = profileUrl.match(/(PL[a-zA-Z0-9_-]+)/)
            if (idMatch) {
              playlistId = idMatch[1]
            }
          }
        }
        
        if (!playlistId) {
          customAlert('添加订阅失败', '无法识别播放列表ID，请使用：1) 播放列表链接（如：https://www.youtube.com/playlist?list=PLxxxxx）2) 播放列表ID（如：PLxxxxx）', 'error')
          addingSubscription.value = false
          return
        }
        
        subscriptionData.platform = 'youtube_playlist'
        subscriptionData.user_id = playlistId
      } else if (platform === 'bilibili_favorite') {
        // B站收藏夹订阅
        subscriptionData.platform = 'bilibili'
        subscriptionData.subscription_type = 'favorite'
      } else if (platform === 'netease_playlist') {
        // 网易云歌单订阅
        subscriptionData.platform = 'netease'
        subscriptionData.subscription_type = 'playlist'
      } else if (platform === 'x_favorite') {
        // X 点赞订阅
        subscriptionData.platform = 'x'
        subscriptionData.subscription_type = 'favorite'
      } else if (platform === 'instagram') {
        subscriptionData.platform = 'instagram'
      } else {
        // 抖音博主、抖音合集、TikTok、B站博主、B站合集、小红书
        subscriptionData.platform = platform
      }

      await subscriptionsApi.add(subscriptionData)
    }
    
    // 成功后关闭模态框并重置表单
    showAddModal.value = false
    newSubscription.value = {
      platform: 'douyin',
      profile_url: '',
      nickname: '',
      check_interval: 3600,
      auto_download: true
    }
    
    // 显示成功提示
    customAlert('添加成功', '订阅已成功添加，正在刷新列表...<br><br><span style="color: var(--color-warning);">💡 建议手动点击“同步”按钮，拉取博主历史所有视频（首次添加默认仅检测前几页）</span>', 'success')
    
    // 刷新订阅列表
    await loadSubscriptions()
  } catch (error) {
    console.error('添加订阅失败:', error)
    customAlert('添加订阅失败', error.response?.data?.detail || '添加订阅失败', 'error')
  } finally {
    addingSubscription.value = false
  }
}

// 更新订阅
async function updateSubscription(sub) {
  try {
    await subscriptionsApi.update(sub.id, {
      update_interval: sub.check_interval,  // 后端字段名是update_interval
      auto_download: String(sub.auto_download).toLowerCase(),  // 转换为字符串
      status: sub.status
    })
  } catch (error) {
    console.error('更新订阅失败:', error)
    customAlert('更新失败', error.response?.data?.detail || error.message, 'error')
  }
}

// 切换状态
async function toggleStatus(sub) {
  sub.status = sub.status === 'active' ? 'paused' : 'active'
  await updateSubscription(sub)
}

// 检测更新
async function checkUpdate(sub) {
  if (!sub.progressState) {
    sub.progressState = { visible: false, message: '', current: 0, total: 0, percent: 0, statusClass: 'text-primary' }
  }
  
  const state = sub.progressState
  state.visible = true
  state.message = '正在检查更新...'
  state.percent = 100
  state.indeterminate = true
  state.statusClass = 'text-primary'
  
  sub.is_checking = true
  try {
    const data = await subscriptionsApi.checkUpdate(sub.id)
    state.indeterminate = false

    // 更新订阅状态（如风控解除后清除错误标记）
    if (data.status !== undefined) sub.status = data.status
    if (data.error_message !== undefined) sub.error_message = data.error_message
    
    if (data.has_update) {
      state.message = `发现 ${data.new_videos_count || 0} 个新视频！`
      state.statusClass = 'text-success'
      // 更新本地视频计数
      if (data.video_count !== undefined) sub.video_count = data.video_count
    } else {
      state.message = '暂无更新'
      state.statusClass = 'text-gray'
    }
    
    // 3秒后隐藏
    setTimeout(() => {
      if (state.visible) state.visible = false
    }, 3000)
  } catch (error) {
    console.error('检测更新失败:', error)
    state.indeterminate = false
    state.message = '检测更新失败'
    state.statusClass = 'text-danger'
    setTimeout(() => { state.visible = false }, 3000)
  } finally {
    sub.is_checking = false
  }
}

// 同步视频
async function syncVideos(sub) {
  sub.is_syncing = true
  try {
    await subscriptionsApi.syncVideos(sub.id)
    // 移除 loadSubscriptions()，由 WebSocket 负责更新状态
  } catch (error) {
    console.error('同步视频失败:', error)
  } finally {
    sub.is_syncing = false
  }
}

// 取消批量下载
async function cancelBatchDownload(sub) {
  const confirmed = await customConfirm('确认取消', '确定要取消剩余的下载任务吗？')
  if (!confirmed) {
    return
  }
  
  try {
    // 更新本地状态为取消中
    if (sub.progressState) {
      sub.progressState.status = 'cancelling'
      sub.progressState.message = '正在取消...'
    }
    
    await subscriptionsApi.cancelBatchDownload(sub.id)
    // WebSocket会推送取消状态更新，这里不需要手动更新UI
  } catch (error) {
    console.error('取消批量下载失败:', error)
    customAlert('取消下载失败', error.response?.data?.detail || error.message || '未知错误', 'error')
    
    // 恢复状态
    if (sub.progressState && sub.progressState.status === 'cancelling') {
      sub.progressState.status = 'downloading'
      sub.progressState.message = '正在下载...'
    }
  }
}

// 查看视频
async function viewVideos(sub) {
  currentSubscription.value = sub
  showVideosModal.value = true
}

// 画质更新回调
function handleQualityUpdated(quality) {
  if (currentSubscription.value) {
    currentSubscription.value.quality = quality
  }
}

// 处理批量下载开始事件（立即显示进度）
function handleBatchDownloadStarted(data) {
  const sub = subscriptions.value.find(s => s.id === data.subscriptionId)
  
  if (sub) {
    // 调用 Composable 的 addTask 方法立即显示进度
    addTask(data.subscriptionId, {
      completed: 0,
      total: data.total || 0,
      failed: 0,
      status: 'downloading',
      nickname: sub.nickname,
      platform: sub.platform,
      avatar_url: sub.avatar_url
    })
    
    // 手动触发重新筛选，强制更新 UI
    filterSubscriptions()
  }
}

// 删除订阅
async function deleteSubscription(sub) {
  const confirmed = await customConfirm('确认删除', `确定要删除订阅"${sub.nickname}"吗?`)
  if (!confirmed) return
  
  try {
    await subscriptionsApi.delete(sub.id)
    await loadSubscriptions()
  } catch (error) {
    console.error('删除订阅失败:', error)
    customAlert('删除失败', error.response?.data?.detail || error.message || '删除订阅失败', 'error')
  }
}

// 打开详情抽屉
async function openDetailDrawer(sub) {
  // 注意：后端返回的是 update_interval，前端抽屉模板中使用的是 check_interval
  // 映射时间字段确保显示正确
  
  // 逻辑增强：如果状态是 paused，则将选择框显示为"不自动检测"(0)
  // 否则使用真实的 update_interval
  let displayInterval = sub.update_interval !== undefined ? sub.update_interval : 0
  if (sub.status === 'paused') {
    displayInterval = 0
  } else if (displayInterval > 0 && displayInterval < 1800) {
    // 前端最低30分钟：老数据若小于30分钟，打开抽屉时自动归一显示
    displayInterval = 1800
  }

  // 先设置数据
  currentSubscription.value = { 
    ...sub,
    check_interval: displayInterval,
    auto_download: sub.auto_download === true || sub.auto_download === 'true',
    skip_bilibili_upower: sub.skip_bilibili_upower === true || sub.skip_bilibili_upower === 'true',
    // 确保时间字段存在，后端可能返回 last_check 或 last_check_time
    last_check_time: sub.last_check_time || sub.last_check,
    created_at: sub.created_at
  }
  
  // 等待 DOM 更新完成后再显示，避免闪烁
  await nextTick()
  showDetailDrawer.value = true
}

// 关闭详情抽屉
function closeDetailDrawer() {
  showDetailDrawer.value = false
  setTimeout(() => {
    currentSubscription.value = null
  }, 300)
}

// 更新当前订阅
async function updateCurrentSubscription() {
  if (!currentSubscription.value) return
  
  try {
    // 前端最低30分钟：仅保留"不自动检测(0)"和>=1800秒
    if (currentSubscription.value.check_interval > 0 && currentSubscription.value.check_interval < 1800) {
      currentSubscription.value.check_interval = 1800
    }

    // 逻辑修正：如果周期设为 0（不自动检测），则将状态设为 paused，否则设为 active
    const newStatus = currentSubscription.value.check_interval === 0 ? 'paused' : 'active'
    
    await subscriptionsApi.update(currentSubscription.value.id, {
      update_interval: currentSubscription.value.check_interval, // 注意:后端字段名是update_interval
      auto_download: String(currentSubscription.value.auto_download).toLowerCase(), // 转换为字符串
      skip_bilibili_upower: String(currentSubscription.value.skip_bilibili_upower).toLowerCase(), // 转换为字符串
      status: newStatus
    })
    
    // 同步更新本地状态
    currentSubscription.value.status = newStatus
    currentSubscription.value.update_interval = currentSubscription.value.check_interval
    
    // 同步更新列表中的数据
    const index = subscriptions.value.findIndex(s => s.id === currentSubscription.value.id)
    if (index > -1) {
      subscriptions.value[index] = { ...currentSubscription.value }
      filterSubscriptions()
    }
  } catch (error) {
    console.error('更新订阅失败:', error)
    customAlert('更新失败', error.response?.data?.detail || error.message, 'error')
  }
}

function isRenamableBilibiliCollection(sub) {
  return sub && (
    sub.platform === 'bilibili_collection' ||
    (sub.platform === 'bilibili' && sub.subscription_type === 'collection')
  )
}

async function renameCurrentSubscription() {
  if (!currentSubscription.value || !isRenamableBilibiliCollection(currentSubscription.value)) return

  const currentName = currentSubscription.value.nickname || ''
  const input = await customPrompt(
    '重命名合集',
    `
      <div style="text-align: left; line-height: 1.7;">
        <p><strong>仅用于 B站合集试点</strong></p>
        <p style="color: var(--color-warning);">重命名会同步迁移历史下载文件夹并更新数据库路径。</p>
        <p>建议先关闭该订阅的自动更新/自动下载，并确认当前没有下载任务正在运行。</p>
        <p style="margin-top: 8px;">请输入新的合集名称：</p>
      </div>
    `,
    currentName || '请输入新名称',
    200
  )
  if (!input) return

  const nickname = String(input).trim()
  if (!nickname) return

  const confirmed = await customConfirm(
    '确认迁移',
    `
      <div style="text-align: left; line-height: 1.7;">
        <p>将合集从 <strong>${currentName || '未命名'}</strong> 重命名为 <strong>${nickname}</strong>。</p>
        <p style="color: var(--color-warning);">这会移动历史文件夹并更新该订阅的任务路径。</p>
        <p>迁移期间不要手动操作对应下载目录。</p>
      </div>
    `
  )
  if (!confirmed) return

  try {
    const result = await subscriptionsApi.rename(currentSubscription.value.id, nickname)
    currentSubscription.value.nickname = result.nickname || nickname
    currentSubscription.value.storage_name = result.storage_name
    currentSubscription.value.nickname_locked = 'true'
    const index = subscriptions.value.findIndex(s => s.id === currentSubscription.value.id)
    if (index > -1) {
      subscriptions.value[index] = { ...subscriptions.value[index], ...currentSubscription.value }
      filterSubscriptions()
    }
    customAlert('重命名成功', `已完成迁移，更新了 ${result.updated_tasks || 0} 条任务路径。`, 'success')
    await loadSubscriptions()
    const refreshed = subscriptions.value.find(s => s.id === currentSubscription.value.id)
    if (refreshed) {
      await openDetailDrawer(refreshed)
    }
  } catch (error) {
    console.error('重命名失败:', error)
    customAlert('重命名失败', error.response?.data?.detail || error.message || '重命名失败', 'error')
  }
}

// 切换当前订阅状态
async function toggleCurrentStatus() {
  if (!currentSubscription.value) return
  currentSubscription.value.status = currentSubscription.value.status === 'active' ? 'paused' : 'active'
  await updateCurrentSubscription()
}

// 从抽屉查看视频
function viewVideosFromDrawer() {
  if (currentSubscription.value) {
    closeDetailDrawer()
    viewVideos(currentSubscription.value)
  }
}

// 删除当前订阅
async function deleteCurrentSubscription() {
  if (!currentSubscription.value) return
  
  const confirmed = await customConfirm('确认删除', `确定要删除订阅"${currentSubscription.value.nickname}"吗?`)
  if (!confirmed) return
  
  try {
    await subscriptionsApi.delete(currentSubscription.value.id)
    closeDetailDrawer()
    await loadSubscriptions()
  } catch (error) {
    console.error('删除订阅失败:', error)
    customAlert('删除失败', error.response?.data?.detail || error.message || '删除订阅失败', 'error')
  }
}

// 展开/折叠全部
// 批量检测更新
async function batchCheckUpdate() {
  const visibleCount = filteredSubscriptions.value.length
  const now = new Date()
  const todayPassword = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
  
  if (visibleCount === 0) {
    customAlert('提示', '当前筛选没有可操作的订阅', 'warning')
    return
  }

  const password = await customPrompt('开发者工具', `
    <div style="text-align: left;">
      <p style="margin-bottom: 15px;">批量检测当前筛选的 <strong style="color: var(--color-primary);">${visibleCount}</strong> 个订阅的更新</p>
      <p style="color: #666; font-size: 0.9em; margin-bottom: 8px;">此为开发者工具，请输入开发者密码：</p>
      <p style="color: #666; font-size: 0.9em; margin-bottom: 15px;">密码为当天日期（YYYYMMDD），例如：<strong>${todayPassword}</strong></p>
    </div>
  `, '请输入开发者密码', 8)
  if (!password) return
  
  try {
    const subscriptionIds = filteredSubscriptions.value.map(sub => sub.id)
    const data = await subscriptionsApi.batchCheckFiltered(subscriptionIds, password)
    
    // 前端本地标记：让卡片立即显示“检测中”
    if (data.task_id) {
      currentBatchCheck.active = true
      currentBatchCheck.taskId = data.task_id
      currentBatchCheck.subIds = [...subscriptionIds]
      subscriptionIds.forEach(id => {
        const sub = subscriptions.value.find(s => s.id === id)
        if (!sub) return
        if (!sub.progressState) {
          sub.progressState = { visible: false, message: '', current: 0, total: 0, percent: 0, statusClass: 'text-primary' }
        }
        sub.is_checking = true
        sub.progressState.visible = true
        sub.progressState.message = '批量检测中...'
        sub.progressState.indeterminate = true
        sub.progressState.statusClass = 'text-primary'
      })
    }
    
    const platformsInfo = Object.entries(data.platforms || {})
      .map(([p, count]) => `${p}(${count}个)`)
      .join('、')
    
    customAlert('批量检测已发起', `
      <div style="text-align: left;">
        <p>已发起批量检测 <strong>${data.total}</strong> 个订阅的更新（${platformsInfo}）</p>
        <p style="color: #666; font-size: 0.9em; margin-top: 10px;">
          任务将在后台执行，可关闭页面。<br>
          此为开发者工具，请在日志中查看进度。
        </p>
      </div>
    `, 'success')
    
    console.log('批量检测已发起:', data)
  } catch (error) {
    if (error.response?.status === 403) {
      customAlert('密码错误', '开发者口令错误，无法执行批量检测', 'error')
    } else {
      customAlert('操作失败', `批量检测失败: ${error.message || '未知错误'}`, 'error')
    }
  }
}

// 批量同步视频
async function batchSyncVideos() {
  const visibleCount = filteredSubscriptions.value.length
  const now = new Date()
  const todayPassword = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
  
  if (visibleCount === 0) {
    customAlert('提示', '当前筛选没有可操作的订阅', 'warning')
    return
  }

  const password = await customPrompt('开发者工具', `
    <div style="text-align: left;">
      <p style="margin-bottom: 15px;">批量同步当前筛选的 <strong style="color: var(--color-primary);">${visibleCount}</strong> 个订阅的视频</p>
      <p style="color: #666; font-size: 0.9em; margin-bottom: 8px;">此为开发者工具，请输入开发者密码：</p>
      <p style="color: #666; font-size: 0.9em; margin-bottom: 15px;">密码为当天日期（YYYYMMDD），例如：<strong>${todayPassword}</strong></p>
    </div>
  `, '请输入开发者密码', 8)
  if (!password) return
  
  try {
    const subscriptionIds = filteredSubscriptions.value.map(sub => sub.id)
    const data = await subscriptionsApi.batchSyncFiltered(subscriptionIds, password)
    
    const platformsInfo = Object.entries(data.platforms || {})
      .map(([p, count]) => `${p}(${count}个)`)
      .join('、')
    
    customAlert('批量同步已发起', `
      <div style="text-align: left;">
        <p>已发起批量同步 <strong>${data.total}</strong> 个订阅的视频（${platformsInfo}）</p>
        <p style="color: #666; font-size: 0.9em; margin-top: 10px;">
          任务将在后台执行，可关闭页面。<br>
          此为开发者工具，请在日志中查看进度。
        </p>
      </div>
    `, 'success')
    
    console.log('批量同步已发起:', data)
  } catch (error) {
    if (error.response?.status === 403) {
      customAlert('密码错误', '开发者口令错误，无法执行批量同步', 'error')
    } else {
      customAlert('操作失败', `批量同步失败: ${error.message || '未知错误'}`, 'error')
    }
  }
}

// 批量添加抖音博主
async function showBatchAddDouyin() {
  const MAX_BATCH_DOUYIN_URLS = 15
  const confirmed = await customConfirm('批量添加抖音博主', `
    <div style="text-align: left;">
      <p style="margin-bottom: 10px;">
        每行一个抖音主页链接或短链接（<code>v.douyin.com</code>），单次最多 <strong>${MAX_BATCH_DOUYIN_URLS}</strong> 个。
      </p>
      <textarea
        id="batchDouyinUrls"
        style="width: 100%; min-height: 170px; resize: vertical; padding: 10px; border: 1px solid var(--color-border); border-radius: 6px; font-size: 13px; line-height: 1.5;"
        placeholder="https://www.douyin.com/user/MS4wLjABAAAA...\nhttps://v.douyin.com/xxxxxx/"
      ></textarea>
      <div style="margin-top: 12px;">
        <label style="display: block; margin-bottom: 6px; font-weight: 500;">自动检测周期：</label>
        <select id="batchDouyinInterval" style="width: 100%; padding: 8px; border: 1px solid var(--color-border); border-radius: 6px;">
          <option value="1800">30分钟</option>
          <option value="3600" selected>1小时</option>
          <option value="7200">2小时</option>
          <option value="14400">4小时</option>
          <option value="28800">8小时</option>
          <option value="43200">12小时</option>
          <option value="86400">24小时</option>
        </select>
      </div>
      <div style="margin-top: 12px;">
        <label style="display: block; margin-bottom: 6px; font-weight: 500;">自动下载新视频：</label>
        <select id="batchDouyinAutoDownload" style="width: 100%; padding: 8px; border: 1px solid var(--color-border); border-radius: 6px;">
          <option value="true" selected>开启</option>
          <option value="false">关闭</option>
        </select>
      </div>
      <div style="margin-top: 10px; color: var(--color-warning); font-size: 12px;">
        提示：抖音风控较严，系统会自动串行处理并限速；超过 ${MAX_BATCH_DOUYIN_URLS} 个请分批提交。
      </div>
    </div>
  `)

  if (!confirmed) return

  const rawInput = document.getElementById('batchDouyinUrls')?.value || ''
  const updateInterval = Number(document.getElementById('batchDouyinInterval')?.value || 3600)
  const autoDownload = String(document.getElementById('batchDouyinAutoDownload')?.value || 'true')

  const parsedUrls = rawInput
    .split(/\r?\n|,/)
    .map(item => item.trim())
    .filter(Boolean)

  const dedupedUrls = [...new Set(parsedUrls)]

  if (dedupedUrls.length === 0) {
    customAlert('输入无效', '请至少输入一个抖音主页链接', 'warning')
    return
  }

  if (dedupedUrls.length > MAX_BATCH_DOUYIN_URLS) {
    customAlert('数量超限', `当前共 ${dedupedUrls.length} 个链接，单次最多支持 ${MAX_BATCH_DOUYIN_URLS} 个，请分批提交`, 'warning')
    return
  }

  try {
    const res = await subscriptionsApi.batchAddDouyin({
      profile_urls: dedupedUrls,
      update_interval: updateInterval,
      auto_download: autoDownload
    })

    currentBatchAdd.active = true
    currentBatchAdd.taskId = res.task_id
    currentBatchAdd.total = res.total || dedupedUrls.length
    currentBatchAdd.processed = 0
    currentBatchAdd.success = 0
    currentBatchAdd.failed = 0
    currentBatchAdd.skipped = 0

    customAlert('批量添加已启动', `
      <div style="text-align: left;">
        <div>任务ID：<code>${res.task_id}</code></div>
        <div style="margin-top: 8px;">已提交 <strong>${res.queued || dedupedUrls.length}</strong> 个抖音博主，任务将在后台执行。</div>
      </div>
    `, 'success')
  } catch (error) {
    customAlert('批量添加失败', error.response?.data?.detail || error.message || '请求失败', 'error')
  }
}

// 批量设置周期
// 批量设置更新周期
async function runBatchSubscriptionUpdates(subscriptions, buildPayload, concurrency = 8) {
  let successCount = 0
  let failCount = 0
  const queue = [...subscriptions]
  const workerCount = Math.min(concurrency, queue.length)

  const worker = async () => {
    while (queue.length > 0) {
      const sub = queue.shift()
      if (!sub) break
      try {
        await subscriptionsApi.update(sub.id, buildPayload(sub))
        successCount++
      } catch (error) {
        failCount++
        console.error(`更新订阅 ${sub.id} 失败:`, error)
      }
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()))
  return { successCount, failCount }
}

async function showBatchSetInterval() {
  const visibleCount = filteredSubscriptions.value.length
  
  if (visibleCount === 0) {
    customAlert('提示', '当前筛选没有可操作的订阅', 'warning')
    return
  }

  const confirmed = await customConfirm('批量设置更新周期', `
    <div style="text-align: left;">
      <p style="margin-bottom: 15px;">将对当前筛选的 <strong style="color: var(--color-primary);">${visibleCount}</strong> 个订阅进行批量设置</p>
      <label style="display: block; margin-bottom: 10px; font-weight: 500;">选择更新周期：</label>
      <select id="intervalSelect" style="width: 100%; padding: 10px; border: 1px solid var(--color-border); border-radius: 6px; font-size: 1rem;">
        <option value="0">暂停</option>
        <option value="0.5">30 分钟</option>
        <option value="1">1 小时</option>
        <option value="2" selected>2 小时</option>
        <option value="4">4 小时</option>
        <option value="6">6 小时</option>
        <option value="12">12 小时</option>
      </select>
    </div>
  `)
  
  if (!confirmed) return
  
  const intervalHours = parseFloat(document.getElementById('intervalSelect').value)
  const intervalSeconds = intervalHours * 3600
  
  batchSettingLoading.value = true
  const { successCount, failCount } = await runBatchSubscriptionUpdates(
    filteredSubscriptions.value,
    () => ({
      update_interval: intervalSeconds,
      status: intervalHours === 0 ? 'paused' : 'active'
    })
  )
  
  const intervalText = intervalHours === 0 ? '暂停' : (intervalHours < 1 ? `${intervalHours * 60}分钟` : `${intervalHours}小时`)
  
  if (failCount === 0) {
    customAlert('设置成功', `成功设置 ${successCount} 个订阅的更新周期为 ${intervalText}`, 'success')
  } else {
    customAlert('设置完成', `成功 ${successCount} 个，失败 ${failCount} 个`, 'warning')
  }
  
  batchSettingLoading.value = false
  await loadSubscriptions()
}

// 批量设置自动下载
async function showBatchSetAutoDownload() {
  const visibleCount = filteredSubscriptions.value.length
  
  if (visibleCount === 0) {
    customAlert('提示', '当前筛选没有可操作的订阅', 'warning')
    return
  }

  const confirmed = await customConfirm('批量设置自动下载', `
    <div style="text-align: left;">
      <p style="margin-bottom: 15px;">将对当前筛选的 <strong style="color: var(--color-primary);">${visibleCount}</strong> 个订阅进行批量设置</p>
      <label style="display: block; margin-bottom: 10px; font-weight: 500;">选择自动下载状态：</label>
      <select id="autoDownloadSelect" style="width: 100%; padding: 10px; border: 1px solid var(--color-border); border-radius: 6px; font-size: 1rem;">
        <option value="true">✅ 开启自动下载</option>
        <option value="false">❌ 关闭自动下载</option>
      </select>
    </div>
  `)
  
  if (!confirmed) return
  
  const autoDownload = document.getElementById('autoDownloadSelect').value
  
  batchSettingLoading.value = true
  const { successCount, failCount } = await runBatchSubscriptionUpdates(
    filteredSubscriptions.value,
    () => ({
      auto_download: autoDownload
    })
  )
  
  const statusText = autoDownload === 'true' ? '开启' : '关闭'
  
  if (failCount === 0) {
    customAlert('设置成功', `成功${statusText} ${successCount} 个订阅的自动下载`, 'success')
  } else {
    customAlert('设置完成', `成功 ${successCount} 个，失败 ${failCount} 个`, 'warning')
  }
  
  batchSettingLoading.value = false
  await loadSubscriptions()
}

// 模拟确认框
function customConfirm(title, message) {
  return new Promise((resolve) => {
    tipTitle.value = title
    tipMessage.value = message
    tipType.value = 'confirm'
    showTipModal.value = true
    tipResolve = resolve
  })
}

// 模拟警告框
function customAlert(title, message, type = 'info') {
  tipTitle.value = title
  tipMessage.value = message
  tipType.value = type
  showTipModal.value = true
}

// 模拟输入框（用于密码输入）
function customPrompt(title, message, placeholder = '请输入内容', maxlength = 200) {
  return new Promise((resolve) => {
    tipTitle.value = title
    tipMessage.value = message
    tipType.value = 'prompt'
    tipInputValue.value = ''
    tipPlaceholder.value = placeholder
    tipMaxlength.value = maxlength
    showTipModal.value = true
    tipResolve = resolve
  })
}

function handleTipConfirm() {
  showTipModal.value = false
  if (tipResolve) {
    // 如果是 prompt 类型，返回输入值；否则返回 true
    const result = tipType.value === 'prompt' ? tipInputValue.value : true
    tipResolve(result)
  }
}

function handleTipCancel() {
  showTipModal.value = false
  if (tipResolve) {
    // 取消时返回 null（prompt）或 false（confirm）
    const result = tipType.value === 'prompt' ? null : false
    tipResolve(result)
  }
}

// 小红书订阅风险提示：切换到小红书时强制弹窗确认
watch(
  () => newSubscription.value.platform,
  async (next, prev) => {
    if (skipXhsWarningOnce.value) {
      skipXhsWarningOnce.value = false
      return
    }
    if (next === 'xiaohongshu' && prev !== 'xiaohongshu') {
      const phrase = '我已确认风险并自行承担后果'
      const input = await customPrompt(
        '风险提示',
        `
          <div style="text-align: left; line-height: 1.7;">
            <p><strong>⚠️ 小红书订阅存在较高的风控/封号风险</strong></p>
            <p>平台可能会根据自动化访问、频繁请求等行为触发限制或封禁。</p>
            <p style="color: var(--color-warning);"><strong>强烈不建议使用主账号。</strong></p>
            <p>如仍需使用，请尽量使用<strong>小号</strong>并降低更新频率。</p>
            <p style="margin-top: 8px;">请输入以下文字以继续：</p>
            <p style="margin: 6px 0; padding: 6px 8px; background: var(--color-bg-card); border-radius: 6px; font-weight: 600;">${phrase}</p>
          </div>
        `,
        `请输入：${phrase}`,
        phrase.length
      )
      if (input !== phrase) {
        customAlert('已取消', '未确认风险内容，已取消选择“小红书博主”。', 'warning')
        skipXhsWarningOnce.value = true
        newSubscription.value.platform = prev || 'douyin'
      }
    }
  }
)

// 自动检测周期：从“关闭”切到“开启”时提醒风险

// 导出配置 (订阅备份)
async function exportConfig() {
  const confirmed = await customConfirm('确认导出订阅配置', `
    <div style="text-align: left; line-height: 1.6;">
      <p>将导出所有博主的订阅设置，包含：</p>
      <ul style="margin: 8px 0; padding-left: 20px;">
        <li>博主昵称与平台信息</li>
        <li>自动检测周期设置</li>
        <li>自动下载开启状态</li>
      </ul>
      <p style="font-size: 0.9em; color: var(--color-text-tertiary);">温馨提示：此备份不包含视频下载历史及账号Cookie。</p>
    </div>
  `)
  if (!confirmed) return

  try {
    const data = await subscriptionsApi.exportConfig()

    if (!data.subscriptions || data.subscriptions.length === 0) {
      customAlert('导出失败', '当前没有订阅数据可供备份', 'warning')
      return
    }

    const configJson = JSON.stringify(data, null, 2)
    const blob = new Blob([configJson], { type: 'application/json' })
    const url = URL.createObjectURL(blob)

    const link = document.createElement('a')
    link.href = url
    link.download = `subscription_config_${new Date().toISOString().slice(0, 10)}.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)

    customAlert('导出成功', `
      <div style="text-align: center;">
        <p style="margin-bottom: 10px;">配置文件已准备就绪</p>
        <div style="background: rgba(0,0,0,0.03); padding: 12px; border-radius: 8px; text-align: left; font-size: 0.9em;">
          • ${data.total_subscriptions} 个订阅配置已保存
        </div>
      </div>
    `, 'success')
  } catch (error) {
    console.error('导出订阅备份失败:', error)
    customAlert('错误', '导出配置文件失败: ' + (error.message || '未知错误'), 'error')
  }
}

// 导入配置
function importConfig() {
  fileInput.value?.click()
}

// 处理文件导入
async function handleFileImport(event) {
  const file = event.target.files[0]
  if (!file) return

  if (!file.name.endsWith('.json')) {
    customAlert('格式错误', '请选择有效的 JSON 格式配置文件', 'error')
    return
  }
  
  try {
    const importResult = await subscriptionsApi.importConfig(file)
    
    const htmlContent = `
      <div style="text-align: left;">
        <p style="margin-bottom: 8px;">订阅配置已成功导入。</p>
        <div style="background: rgba(0,0,0,0.03); padding: 12px; border-radius: 8px; font-size: 0.9em;">
          <strong>总订阅数:</strong> ${importResult.total || 0}<br>
          <strong>新增:</strong> ${importResult.success || 0}<br>
          <strong>跳过(已存在):</strong> ${importResult.failed || 0}
        </div>
      </div>
    `
    
    customAlert('导入成功', htmlContent, 'success')
    await loadSubscriptions()
  } catch (error) {
    console.error('导入失败:', error)
    customAlert('导入失败', '备份文件内容非法或服务器解析异常', 'error')
  }
  
  event.target.value = ''
}

// 重置浏览器
async function handleResetBrowser() {
  const confirmed = await customConfirm('重置确认', `
    <div style="text-align: center;">
      <p style="margin-bottom: 15px;">确定要重置所有浏览器吗？</p>
      <p style="color: #666; font-size: 0.9em; margin-bottom: 20px;">
        这将删除抖音、YouTube和B站的所有浏览器文件，包括登录信息、缓存等。若遇到浏览器问题，可以尝试此操作。
      </p>
    </div>
  `)
  if (!confirmed) return
  
  try {
    const response = await subscriptionsApi.resetBrowser()
    
    customAlert('重置完成', `
      <div style="text-align: center;">
        <h3 style="color: var(--color-success); margin-bottom: 15px;">✅ 重置成功</h3>
        <p style="margin-bottom: 10px;">浏览器数据已成功重置</p>
        <div style="background: #f8f9fa; padding: 10px; border-radius: 6px; margin: 15px 0;">
          <p style="margin: 0; font-size: 0.9em; color: #666;">
            <strong>重置内容包括：</strong><br>
            • 所有浏览器缓存和会话数据<br>
            • 登录状态和Cookie信息<br>
            • 浏览器配置和扩展数据<br>
            • 临时文件和日志数据
          </p>
        </div>
        <p style="font-size: 0.9em; color: #666;">
          下次使用时需要重新登录相关平台
        </p>
      </div>
    `, 'success')
  } catch (error) {
    console.error('重置浏览器失败:', error)
    const errorMessage = error.message || '重置失败'
    
    customAlert('重置失败', `
      <div style="text-align: center;">
        <h3 style="color: var(--color-error); margin-bottom: 15px;">❌ 重置失败</h3>
        <p style="margin-bottom: 10px;">浏览器重置过程中遇到问题</p>
        <div style="background: #fff5f5; padding: 10px; border-radius: 6px; margin: 15px 0; border: 1px solid #fed7d7;">
          <p style="margin: 0; font-size: 0.9em; color: #c53030;">
            <strong>错误详情：</strong><br>
            ${errorMessage}
          </p>
        </div>
        <div style="background: #f8f9fa; padding: 10px; border-radius: 6px; margin: 15px 0;">
          <p style="margin: 0; font-size: 0.9em; color: #666;">
            <strong>可能的解决方案：</strong><br>
            • 确保没有浏览器正在运行<br>
            • 等待几分钟后重试<br>
            • 检查系统权限设置<br>
            • 联系技术支持
          </p>
        </div>
      </div>
    `, 'error')
  }
}

// 清理缓存
async function handleClearCache() {
  const confirmed = await customConfirm('确认清理', `
    <div style="text-align: center;">
      <p style="margin-bottom: 10px;">确定要清理所有平台的API参数缓存吗？</p>
      <p style="color: #666; font-size: 0.9em;">
        清理后下次获取参数时会重新请求。
      </p>
    </div>
  `)
  if (!confirmed) return
  
  try {
    const result = await subscriptionsApi.clearCache()
    customAlert('清理成功', '缓存清理成功！' + (result.message || ''), 'success')
  } catch (error) {
    console.error('清理缓存失败:', error)
    customAlert('清理失败', error.message || '清理缓存失败，请稍后重试', 'error')
  }
}

// 抖音登录
async function handleDouyinLogin() {
  try {
    // 立即显示VNC模态框
    vncPlatform.value = 'douyin'
    showVncModal.value = true
    
    // 异步启动浏览器
    const response = await subscriptionsApi.douyinLogin()
    
    if (!response || response.error) {
      // 如果启动失败，关闭VNC模态框
      showVncModal.value = false
      throw new Error(response?.error || '启动浏览器失败')
    }
  } catch (error) {
    console.error('抖音登录失败:', error)
    showVncModal.value = false
    customAlert('登录失败', '启动浏览器失败: ' + (error.message || '未知错误'), 'error')
  }
}

// YouTube登录
async function handleYoutubeLogin() {
  try {
    // 立即显示VNC模态框
    vncPlatform.value = 'youtube'
    showVncModal.value = true
    
    // 异步启动浏览器
    const response = await subscriptionsApi.youtubeLogin()
    
    if (!response || response.error) {
      showVncModal.value = false
      throw new Error(response?.error || '启动浏览器失败')
    }
  } catch (error) {
    console.error('YouTube登录失败:', error)
    showVncModal.value = false
    customAlert('登录失败', '启动浏览器失败: ' + (error.message || '未知错误'), 'error')
  }
}

// B站登录
async function handleBilibiliLogin() {
  try {
    // 立即显示VNC模态框
    vncPlatform.value = 'bilibili'
    showVncModal.value = true
    
    // 异步启动浏览器
    const response = await subscriptionsApi.bilibiliLogin()
    
    if (!response || response.error) {
      showVncModal.value = false
      throw new Error(response?.error || '启动浏览器失败')
    }
  } catch (error) {
    console.error('B站登录失败:', error)
    showVncModal.value = false
    customAlert('登录失败', '启动浏览器失败: ' + (error.message || '未知错误'), 'error')
  }
}

// 小红书登录
async function handleXiaohongshuLogin() {
  try {
    // 立即显示VNC模态框
    vncPlatform.value = 'xiaohongshu'
    showVncModal.value = true
    
    // 异步启动浏览器
    const response = await subscriptionsApi.xiaohongshuLogin()
    
    if (!response || response.error) {
      showVncModal.value = false
      throw new Error(response?.error || '启动浏览器失败')
    }
  } catch (error) {
    console.error('小红书登录失败:', error)
    showVncModal.value = false
    customAlert('登录失败', '启动浏览器失败: ' + (error.message || '未知错误'), 'error')
  }
}

// 跳转到TK Cookie设置
function handleTkCookieSettings() {
  router.push({ path: '/settings', query: { tab: 'cookie', platform: 'tiktok' } })
}

function handleNeteaseCookieSettings() {
  router.push({ path: '/settings', query: { tab: 'cookie', platform: 'netease' } })
}

function handleXCookieSettings() {
  router.push({ path: '/settings', query: { tab: 'cookie', platform: 'x' } })
}

function handleInsCookieSettings() {
  router.push({ path: '/settings', query: { tab: 'cookie', platform: 'instagram' } })
}

async function handleClearInstagramRisk(sub) {
  try {
    sub._clearingRisk = true
    await cookieApi.clearInstagramRisk()
    sub.status = 'active'
    sub.error_message = ''
    toast.success('风控状态已清除，点击检测更新或等待自动检测')
  } catch (error) {
    toast.error('清除失败: ' + (error.message || '未知错误'))
  } finally {
    sub._clearingRisk = false
  }
}

// 打开主页
function openProfile(sub) {
  if (sub.profile_url) {
    window.open(sub.profile_url, '_blank')
  }
}

// 默认头像(SVG)
// 代理图片（委托共享工具）
function proxyImage(url) {
  return resolveAvatarUrl(url)
}

// 图片加载失败处理（委托共享工具）
function handleImageError(event) {
  sharedHandleImageError(event)
}

// 获取链接标签
function getLinkLabel() {
  const platform = newSubscription.value.platform
  if (platform === 'bilibili_favorite') return '收藏夹链接或ID'
  if (platform === 'youtube_playlist') return '播放列表链接或ID'
  if (platform === 'netease_playlist') return '歌单链接或ID'
  if (platform === 'x_favorite') return '用户主页或用户名'
  if (platform === 'douyin_collection' || platform === 'bilibili_collection') return '合集链接'
  if (platform === 'instagram') return '主页链接或用户名'
  if (platform === 'xiaohongshu') return '主页链接'
  return '主页链接'
}

// 获取链接占位符
function getLinkPlaceholder() {
  const platform = newSubscription.value.platform
  if (platform === 'bilibili_favorite') return '请输入收藏夹URL或收藏夹ID（如：473071500）'
  if (platform === 'youtube_playlist') return '请输入YouTube播放列表链接或播放列表ID（如：PLxxxxx）'
  if (platform === 'netease_playlist') return '请输入网易云歌单链接或歌单ID（如：https://music.163.com/playlist?id=123456 或 123456）'
  if (platform === 'douyin_collection') return '请输入抖音合集链接、短链接或合集ID（如：7407257750834513958）'
  if (platform === 'bilibili_collection') return '请输入B站合集链接或BV号（如：BVxxxxx）'
  if (platform === 'youtube_videos' || platform === 'youtube_shorts') return '请输入YouTube频道链接、频道ID（如：UCxxxxx）或频道handle（如：@channelname）'
  if (platform === 'bilibili') return '请输入B站UP主主页链接或UID（如：123456）'
  if (platform === 'tiktok') return '请输入TikTok用户主页链接或用户名（如：@username 或 username）'
  if (platform === 'instagram') return '请输入Instagram用户主页链接或用户名（如：https://www.instagram.com/username/ 或 @username）'
  if (platform === 'douyin') return '请输入抖音主页链接或短链接（推荐）'
  if (platform === 'xiaohongshu') return '请输入小红书用户主页链接'
  if (platform === 'x_favorite') return '请输入X主页链接或用户名（如：https://x.com/bigbigvvv 或 @bigbigvvv）'
  return '请输入博主主页链接或ID'
}

// 获取链接提示
function getLinkHint() {
  const platform = newSubscription.value.platform
  if (platform === 'youtube_playlist') return '支持：播放列表链接（https://www.youtube.com/playlist?list=PLxxxxx）或直接输入播放列表ID（PLxxxxx）'
  if (platform === 'netease_playlist') return '支持：歌单链接（https://music.163.com/playlist?id=123456）或直接输入歌单ID（123456）'
  if (platform === 'douyin_collection') return '支持：合集链接、短链接（v.douyin.com）或合集ID'
  if (platform === 'bilibili_collection') return '支持：合集链接（https://www.bilibili.com/video/BVxxxxx）或直接输入BV号（BVxxxxx）'
  if (platform === 'bilibili') return '支持：UP主主页链接（https://space.bilibili.com/123456）或直接输入UID（123456）'
  if (platform === 'bilibili_favorite') return '支持：收藏夹链接或直接输入收藏夹ID（如：473071500）'
  if (platform === 'douyin') return '💡 推荐使用主页链接或短链接（v.douyin.com），不支持抖音号'
  if (platform === 'tiktok') return '支持：用户主页链接（https://www.tiktok.com/@username）或直接输入用户名（@username 或 username）'
  if (platform === 'instagram') return '支持：Instagram主页链接（https://www.instagram.com/username/）或直接输入用户名（@username 或 username）。图片、视频和轮播媒体会按子媒体分别入库和下载。'
  if (platform === 'x_favorite') return '支持：X主页链接（https://x.com/username）或直接输入用户名（@username 或 username）'
  if (platform === 'youtube_videos' || platform === 'youtube_shorts') return '支持：频道链接（https://www.youtube.com/@channelname）、频道ID（UCxxxxx）或频道handle（@channelname 或 channelname）'
  if (platform === 'xiaohongshu') {
    return '支持：小红书用户主页链接（https://www.xiaohongshu.com/user/profile/xxxxx）。⚠️ 当前小红书订阅功能仍在测试中，平台风控较严，建议适当拉长自动检测周期并避免频繁手动同步，如遇部分笔记同步/下载失败属正常现象，可稍后重试。'
  }
  return null
}

// 获取平台名称
function getPlatformName(platform, subscription_type = null, youtube_tab_type = null) {
  // 如果是B站收藏夹
  if (platform === 'bilibili' && subscription_type === 'favorite') {
    return 'B站收藏'
  }
  // 如果是B站合集
  if (platform === 'bilibili' && subscription_type === 'collection') {
    return 'B站合集'
  }
  // 如果是B站UP主
  if (platform === 'bilibili' && (!subscription_type || subscription_type === 'user')) {
    return 'B站'
  }
  
  // 如果是YouTube频道，根据tab_type显示不同名称
  if (platform === 'youtube' && youtube_tab_type) {
    if (youtube_tab_type === 'shorts') {
      return '油管短视频'
    }
    if (youtube_tab_type === 'videos') {
      return '油管'
    }
  }
  
  const map = {
    'douyin': '抖音',
    'douyin_collection': '抖音合集',
    'douyin_favorite': '抖音点赞',
    'tiktok': 'TikTok',
    'instagram': 'Instagram',
    'youtube': '油管',
    'youtube_channel': '油管',
    'youtube_shorts': '油管短视频',
    'youtube_playlist': '油管合集',
    'bilibili': 'B站',
    'bilibili_collection': 'B站合集',
    'bilibili_favorite': 'B站收藏',
    'xiaohongshu': '小红书',
    'netease': '网易云',
    'x': 'X',
    'x_favorite': 'X点赞'
  }
  return map[platform] || platform
}

// 格式化数字（支持万/亿）
function formatCount(count) {
  if (!count) return '0'
  if (count < 10000) return count.toString()
  if (count < 100000000) {
    return (count / 10000).toFixed(1) + '万'
  }
  return (count / 100000000).toFixed(1) + '亿'
}

// 格式化时间
function formatTime(time) {
  if (!time) return ''
  const date = new Date(time)
  const Y = date.getFullYear()
  const M = (date.getMonth() + 1).toString().padStart(2, '0')
  const D = date.getDate().toString().padStart(2, '0')
  const h = date.getHours().toString().padStart(2, '0')
  const m = date.getMinutes().toString().padStart(2, '0')
  return `${Y}-${M}-${D} ${h}:${m}`
}

// 格式化相对时间
function formatTimeAgo(time) {
  if (!time) return ''
  const now = new Date()
  const past = new Date(time)
  const diff = Math.floor((now - past) / 1000) // 秒

  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 2592000) return `${Math.floor(diff / 86400)}天前`
  return formatTime(time)
}

// 获取更新周期文本
function getIntervalText(seconds) {
  if (!seconds || seconds === 0) return '不自动检测'
  const hours = seconds / 3600
  if (hours < 1) return `${seconds / 60}分钟`
  if (hours < 24) return `${hours}小时`
  return `${hours / 24}天`
}

// 计算下次更新时间
function calculateNextUpdate(sub) {
  const interval = sub.check_interval || sub.update_interval || 0
  if (!sub || interval === 0) {
    return '已停止自动检测'
  }
  if (sub.status === 'error') {
    return '检测异常，自动重试中'
  }
  if (sub.status === 'invalid') {
    return '订阅已失效'
  }
  if (sub.status === 'paused') {
    return '自动检测已暂停'
  }
  if (sub.status !== 'active') {
    return '自动检测已停止'
  }

  // 使用 last_check_time (后端返回的值)
  const lastCheck = sub.last_check_time || sub.last_check
  if (!lastCheck) return '等待初次检测'
  
  const lastDate = new Date(lastCheck)
  const nextDate = new Date(lastDate.getTime() + interval * 1000)
  
  
  const now = new Date()
  if (nextDate < now) {
    return '即将开始...'
  }
  
  // 如果是今天，只显示时间
  if (nextDate.toDateString() === now.toDateString()) {
    const h = nextDate.getHours().toString().padStart(2, '0')
    const m = nextDate.getMinutes().toString().padStart(2, '0')
    return `${h}:${m}`
  }
  
  return formatTime(nextDate).split(' ')[0].split('-').slice(1).join('-') + ' ' + formatTime(nextDate).split(' ')[1]
}

// 编辑订阅(暂未实现)
function editSubscription(sub) {
  customAlert('提示', '编辑功能开发中...', 'info')
}

// 播放博主视频
function playSubscriptionVideos(sub) {
  if (!sub) return
  // 添加 reset_mode=1 参数，告诉播放器重置播放模式为顺序播放
  router.push({ path: '/player', query: { subscription_id: sub.id, reset_mode: '1' } }).then(() => {
    // 跳转到播放中心后，主动把主内容滚动容器拉到最顶，避免被顶部导航遮挡
    nextTick(() => {
      try {
        const container = document.querySelector('.main-content')
        if (container && typeof container.scrollTo === 'function') {
          container.scrollTo({ top: 0, behavior: 'auto' })
        } else {
          window.scrollTo({ top: 0, behavior: 'auto' })
        }
      } catch (e) {}
    })
  })
}

// 跳转到批量下载任务页面
function goToBatchDownloadTasks() {
  router.push('/batch-download-tasks')
}

// 应用筛选条件（从 localStorage 读取）
function applyFiltersFromStorage() {
  const savedPlatform = localStorage.getItem('subscription_platform_filter')
  const savedStatus = localStorage.getItem('subscription_status_filter')
  const savedSearchQuery = localStorage.getItem('subscription_search_query')
  
  if (savedPlatform) {
    selectedPlatforms.value = savedPlatform.split(',').filter(p => p !== '')
    // 如果只有一个值，也同步给 platformFilter 以保持兼容
    if (selectedPlatforms.value.length === 1) {
      platformFilter.value = selectedPlatforms.value[0]
    }
  }
  if (savedStatus) {
    statusFilter.value = savedStatus
  }
  if (savedSearchQuery) {
    searchQuery.value = savedSearchQuery
  }
  
  // 应用筛选后需要触发筛选函数
  if (savedPlatform || savedStatus || savedSearchQuery) {
    filterSubscriptions()
  }
}

onMounted(() => {
  checkLicense(false)
  // 先恢复筛选状态（在加载数据之前）
  applyFiltersFromStorage()
  // 然后加载订阅列表（loadSubscriptions 内部会再次应用筛选以确保数据加载后筛选生效）
  loadSubscriptions()

  // 批量任务进度 WebSocket（用于批量检测更新提示）
  wsService.connect('batch_tasks')
  unregisterBatchTasks = wsService.onMessage((id, data) => handleBatchTaskMessage(id, data))
  
  // 启动批量下载进度管理
  startWebSocketListener()
  startPolling()

  // 核心修复：监听 Layout 中的滚动容器
  const scrollContainer = document.querySelector('.main-content')
  if (scrollContainer) {
    scrollContainer.addEventListener('scroll', handleScroll)
    // 初始计算
    const scrollY = scrollContainer.scrollTop
    const windowHeight = scrollContainer.clientHeight
    const fullHeight = scrollContainer.scrollHeight
    showScrollTop.value = scrollY > 400
    showScrollBottom.value = (fullHeight - scrollY - windowHeight) > 200
  }
})

// 监听路由变化，当从其他页面跳转回来时重新应用筛选
watch(() => router.currentRoute.value.fullPath, (newPath, oldPath) => {
  // 只在跳转到订阅页面时应用筛选
  if (newPath === '/subscriptions' && oldPath && oldPath !== '/subscriptions') {
    applyFiltersFromStorage()
  }
})

onUnmounted(() => {
  // 清理批量下载进度管理资源
  cleanup()
  const scrollContainer = document.querySelector('.main-content')
  if (scrollContainer) {
    scrollContainer.removeEventListener('scroll', handleScroll)
  }
})
</script>

<style scoped>
.subscriptions-page {
  padding: var(--spacing-lg);
}

.page-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-xl);
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  margin: 0;
}

.page-subtitle {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin: var(--spacing-xs) 0 0;
}



.filters-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-md);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-lg);
  margin-bottom: var(--spacing-lg);
}

.filter-group {
  display: flex;
  gap: var(--spacing-sm);
}

.filter-actions {
  display: flex;
  gap: var(--spacing-sm);
}

.subscriptions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: var(--spacing-md);
}

/* 订阅卡片基础样式 */
.subscription-card {
  position: relative;
  background: var(--color-bg-card);
  border-radius: var(--radius-xl);
  border: 1px solid var(--color-border);
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  content-visibility: auto; /* 浏览器渲染优化 */
  contain-intrinsic-size: 150px; /* 预估卡片高度，避免滚动抖动 */
}

.subscription-card:hover {
  border-color: var(--color-primary-light);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.subscription-card.expanded {
  cursor: default;
  box-shadow: var(--shadow-lg);
}

/* 精简视图 */
.card-compact-view {
  display: flex;
  align-items: center;
  padding: var(--spacing-md);
  gap: var(--spacing-md);
  min-height: 80px;
  position: relative;
}

/* 左侧强调条 */
.card-accent {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--color-border);
  transition: all 0.3s ease;
}

.card-accent.active {
  background: linear-gradient(180deg, #e67e22 0%, #d35400 100%);
  width: 5px;
}

/* 状态指示点 */
.status-dot {
  position: absolute;
  top: 12px;
  left: 12px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-text-tertiary);
  z-index: 2;
  box-shadow: 0 0 0 2px var(--color-bg-card);
}

.status-dot.status-active {
  background: var(--color-success);
}

.status-dot.status-paused {
  background: var(--color-warning);
}

.status-dot.status-checking {
  background: var(--color-warning);
  animation: pulse-dot 1.5s ease-in-out infinite;
}

.status-dot.status-error {
  background: var(--color-error);
}

.status-dot.status-invalid {
  background: #7f8c8d;
}

@keyframes pulse-dot {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.6;
    transform: scale(1.2);
  }
}



/* 信息区域 */
.info-area {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.name-row {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  flex-wrap: nowrap;
  width: 100%;
  padding-right: 40px; /* 预留空间给右上角齿轮，防止重叠 */
}

.video-count-inline {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  white-space: nowrap;
}

.inline-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  padding-left: 5px;
}

.creator-name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.platform-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: var(--font-weight-semibold);
  background: var(--color-primary-light);
  color: var(--color-primary);
  flex-shrink: 0;
}

/* 平台标识颜色 - 抖音系列 */
.platform-badge.badge-douyin,
.platform-badge.badge-douyin_collection,
.platform-badge.badge-douyin_favorite {
  background: linear-gradient(135deg, #FF0050, #FF6B00);
  color: #ffffff;
}

/* 平台标识颜色 - TikTok */
.platform-badge.badge-tiktok {
  background: linear-gradient(135deg, #000000, #25F4EE);
  color: #ffffff;
}

.platform-badge.badge-instagram {
  background: linear-gradient(135deg, #f58529 0%, #dd2a7b 55%, #515bd4 100%);
  color: #ffffff;
}

/* 平台标识颜色 - YouTube系列 */
.platform-badge.badge-youtube,
.platform-badge.badge-youtube_channel,
.platform-badge.badge-youtube_shorts,
.platform-badge.badge-youtube_playlist {
  background: linear-gradient(135deg, #FF0000, #CC0000);
  color: #ffffff;
}

/* 平台标识颜色 - B站系列 */
.platform-badge.badge-bilibili,
.platform-badge.badge-bilibili_collection {
  background: linear-gradient(135deg, #FB7299, #FF6699);
  color: #ffffff;
}

/* 平台标识颜色 - 网易云 */
.platform-badge.badge-netease {
  background: linear-gradient(135deg, #d81e06, #ff4d4f);
  color: #ffffff;
}

/* 平台标识颜色 - X */
.platform-badge.badge-x {
  background: linear-gradient(135deg, #111111, #2f2f2f);
  color: #ffffff;
}

.stats-row {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 右上角详情设置按钮 */
.card-settings-btn {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
  z-index: 10;
  /* backdrop-filter: blur(4px); -- 移除以优化性能 */
}

[data-theme="dark"] .card-settings-btn {
  background: rgba(37, 37, 37, 0.9);
  border-color: var(--color-border);
}

.card-settings-btn:hover {
  background: var(--color-primary);
  color: white;
  border-color: var(--color-primary);
  transform: rotate(45deg); /* 悬浮时旋转齿轮 */
}

/* 详情图标已移除 */

/* 展开指示器 */
.expand-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  flex-shrink: 0;
  transition: all 0.3s ease;
}

.subscription-card:hover .expand-icon {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.subscription-card.expanded .expand-icon {
  background: var(--color-primary);
  color: white;
}

/* 展开详情视图 */
.card-expanded-view {
  padding: 0 var(--spacing-lg) var(--spacing-lg);
  animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 签名 */
.signature {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin: 0 0 var(--spacing-md);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* 统计数据网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-lg);
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--spacing-md);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  gap: var(--spacing-xs);
  transition: all 0.3s ease;
}

.stat-card:hover {
  background: var(--color-bg-hover);
  transform: translateY(-2px);
}

.stat-card svg {
  color: var(--color-primary);
}

.stat-value {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  text-align: center;
  word-break: break-all;
}

.stat-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  text-align: center;
}

/* 设置区域 */
.settings-area {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  padding: var(--spacing-md);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  margin-bottom: var(--spacing-md);
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
}

.setting-label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.form-select.compact {
  flex: 1;
  max-width: 200px;
  padding: 6px 10px;
  font-size: var(--font-size-sm);
}

.switch.compact {
  margin: 0;
}

/* 移动端功能区折叠按钮 */
.mobile-panel-toggle {
  display: none; /* PC端隐藏 */
  width: 100%;
  padding: var(--spacing-sm);
  margin-bottom: var(--spacing-sm);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-fast);
  gap: var(--spacing-xs);
  align-items: center;
  justify-content: center;
}

.mobile-panel-toggle:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.mobile-panel-toggle:active {
  transform: scale(0.98);
}

/* 操作面板 */
.action-panel {
  display: flex;
  gap: var(--spacing-xl);
  margin-bottom: var(--spacing-lg);
  padding: var(--spacing-md) var(--spacing-lg);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-lg);
  flex-wrap: wrap; /* 允许换行 */
  overflow-x: visible;
  align-items: flex-start;
}

.action-group {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  flex-shrink: 0; /* 禁止缩小 */
}

.action-group-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-tertiary);
  line-height: 1;
  margin-bottom: 2px;
  letter-spacing: 0.2px;
}

.filter-action-group {
  padding-left: 0;
  border-left: none;
}

.filter-horizontal {
  display: flex !important;
  flex-direction: row !important;
  align-items: center;
  gap: 6px !important;
}

.compact-select {
  width: 99px;
}

/* 自定义多选下拉框 */
.custom-multiselect {
  position: relative;
  width: 122px;
  user-select: none;
}

.multiselect-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0.68rem;
  height: 28px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.multiselect-header:hover {
  border-color: var(--color-primary);
}

.selected-text {
  font-size: 13px;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 80px;
}

.multiselect-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  width: 200px;
  max-height: 400px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  z-index: 1000;
  overflow: hidden;
  animation: slideUp var(--transition-fast);
}

.scroll-area {
  max-height: 380px;
  overflow-y: auto;
  padding: 4px;
  overscroll-behavior: contain; /* 防止滚动穿透 */
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.2s;
}

.dropdown-item:hover {
  background: var(--color-bg-hover);
}

.dropdown-item input[type="checkbox"] {
  width: 14px;
  height: 14px;
  cursor: pointer;
  accent-color: var(--color-primary);
}

.dropdown-item span {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}

.dropdown-item.sub-item {
  padding-left: 20px;
  font-size: 0.9em;
  color: var(--color-text-secondary);
}

.dropdown-group {
  margin-top: 4px;
  border-top: 1px solid var(--color-border-light);
  padding-top: 4px;
}

.group-title {
  padding: 4px 8px;
  font-size: var(--font-size-xs);
  font-weight: bold;
  color: var(--color-text-tertiary);
  text-transform: uppercase;
}

.all-platforms {
  font-weight: bold;
  border-bottom: 1px solid var(--color-border-light);
  margin-bottom: 4px;
  padding-bottom: 8px;
}

.multiselect-header .chevron-down {
  transition: transform 0.2s;
}

.rotate {
  transform: rotate(180deg);
}

[data-theme="dark"] .multiselect-dropdown {
  background: #2a2a2a;
}

.form-select-xs {
  height: 30px; /* 增加高度 */
  padding: 0 6px;
  font-size: 13px; /* 增加字体 */
  border-radius: 6px;
  background-color: var(--color-bg-card);
  border: 1px solid var(--color-border);
}

.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 8px;
  color: var(--color-text-tertiary);
  pointer-events: none;
}

.search-input {
  padding-left: 28px !important;
  width: 101px;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}

.search-input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(230, 126, 34, 0.1);
}

.form-input-xs {
  height: 30px; /* 增加高度 */
  padding: 0 8px;
  font-size: 13px; /* 增加字体 */
  border-radius: 6px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-card);
}


.label-icon {
  opacity: 0.8;
}

.neon-blue { color: #3498db; }
.neon-orange { color: #e67e22; }
.neon-purple { color: #9b59b6; }
.neon-green { color: #2ecc71; }
.neon-gray { color: #95a5a6; }
.neon-teal { color: #1abc9c; }

.group-items {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
}

/* 覆盖全局 btn-xs 样式，仅在此页面生效 */
.btn-xs {
  font-size: 13px;
  padding: 4px 10px;
  height: 30px; 
}

.action-panel .btn-dark:hover:not(:disabled),
.action-panel .btn-dark:focus-visible:not(:disabled) {
  background: var(--color-primary);
  color: #ffffff;
  border-color: var(--color-primary);
  box-shadow: 0 4px 10px var(--color-primary-light);
}

.action-panel .btn-dark:active:not(:disabled) {
  background: var(--color-primary-hover);
  border-color: var(--color-primary-hover);
}

/* 卡片设计 - 优化版 */
.subscriptions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.subscription-card {
  position: relative;
  background: var(--color-bg-card);
  border-radius: 24px;
  border: 1px solid var(--color-border);
  padding: 20px;
  display: flex;
  align-items: flex-start; /* 顶部对齐，防止高度变化导致头像跳动 */
  gap: 16px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  min-height: 120px;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  /* 性能优化：限制重排和重绘范围，对大量卡片列表极为有效 */
  content-visibility: auto;
  contain-intrinsic-size: auto 120px;
}

[data-theme="dark"] .subscription-card {
  background: var(--color-bg-card);
  border-color: var(--color-border);
  box-shadow: var(--shadow-md);
}

/* 移除了性能开销巨大的 filter: blur 动态光晕，改用高效的 CSS Box Shadow */
.subscription-card:hover {
  border-color: var(--color-primary);
  transform: translateY(-4px) scale(1.01);
  box-shadow: 0 12px 30px rgba(230, 126, 34, 0.15); /* 替代原本的模糊图层 */
}


[data-theme="dark"] .subscription-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-xl);
}

/* 确保内部元素在光晕之上 */
.status-dot,
.avatar-container,
.info-area,
.quick-actions {
  position: relative;
  z-index: 1;
}

/* 左侧头像和元数据组合 */
.avatar-side {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  width: 72px; /* 略微拓宽以适应Badge */
  margin-top: 8px; /* 整体下移 */
}

/* 头像容器 - 调整为较舒缓的 4:5 比例 */
.avatar-container {
  position: relative;
  width: 60px;
  height: 75px; /* 4:5 比例：60 * 5 / 4 */
  flex-shrink: 0;
}

.avatar-meta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  width: 100%;
}

.platform-badge {
  padding: 2px 6px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 500;
  white-space: nowrap;
  text-align: center;
  width: auto;
  max-width: 100%;
}

.video-count-inline {
  font-size: 11px;
  color: var(--color-text-secondary);
  white-space: nowrap;
  font-weight: 500;
  margin-top: 2px;
}

.subscription-card .avatar {
  width: 100%;
  height: 100%;
  border-radius: 12px; /* 圆角矩形 */
  object-fit: cover;
  border: 1px solid var(--color-border);
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  transition: transform 0.3s ease;
}

.subscription-card:hover .avatar {
  transform: scale(1.05);
  border-color: var(--color-primary-opacity);
}

[data-theme="dark"] .subscription-card .avatar {
  border-color: var(--color-border);
}

/* 状态指示点 */
.status-dot {
  position: absolute;
  top: 16px; 
  left: 16px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  z-index: 2;
  background: var(--color-text-tertiary);
  box-shadow: 0 0 0 2px var(--color-bg-card);
}

.status-dot.status-active { background: var(--color-success); }
.status-dot.status-paused { background: var(--color-warning); }
.status-dot.status-checking { background: var(--color-primary); animation: pulse-dot 1.5s infinite; }
.status-dot.status-error { background: var(--color-error); }
.status-dot.status-invalid { background: #7f8c8d; }

/* 信息区域 */
.info-area {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px; /* 增加与上方名称的间距 */
  padding-top: 4px;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 8px; /* 增加Badge和名称间的间距 */
  margin-bottom: 0;
  padding-right: 32px; 
}

/* 原 meta-row 样式移除，已合并到 avatar-meta */

/* 快捷操作区 - Grid 网格布局 */
.quick-actions-toolbar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px; /* 紧凑间距 */
  width: 100%;
}

/* 让进度条通知栏占满整行 */
.progress-notification {
  grid-column: 1 / -1;
  margin-top: 4px;
}

.toolbar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 2px;
  border-radius: 8px;
  border: 1.5px solid var(--color-primary);
  background: transparent;
  color: var(--color-primary);
  font-size: 13px; /* 从12px增加 */
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  height: 34px; /* 从32px增加 */
  line-height: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  box-sizing: border-box;
}

/* 深色模式适配 */
[data-theme="dark"] .toolbar-btn {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: transparent;
}

.toolbar-btn:hover {
  background: var(--color-primary);
  color: #ffffff;
  border-color: var(--color-primary);
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(230, 126, 34, 0.25);
}

.toolbar-btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 4px rgba(230, 126, 34, 0.2);
}

.creator-name {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text-primary);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  flex: 1;
  min-width: 0;
  line-height: 1.2;
  max-width: 100%;
  mask-image: linear-gradient(to right, #000 0%, #000 88%, transparent 100%);
  -webkit-mask-image: linear-gradient(to right, #000 0%, #000 88%, transparent 100%);
}

.creator-name-track {
  display: inline-flex;
  align-items: center;
  min-width: 100%;
}

.creator-name-text {
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.creator-name-clone {
  display: none;
}

.creator-name.is-marquee .creator-name-track {
  min-width: max-content;
  animation: creator-name-marquee 9s linear infinite;
}

.creator-name.is-marquee:hover .creator-name-track {
  animation-play-state: paused;
}

.creator-name.is-marquee .creator-name-text {
  overflow: visible;
  text-overflow: clip;
  max-width: none;
  flex-shrink: 0;
}

.creator-name.is-marquee .creator-name-clone {
  display: inline-block;
  padding-left: 32px;
}

@keyframes creator-name-marquee {
  0%, 12% {
    transform: translateX(0);
  }
  88%, 100% {
    transform: translateX(calc(-50% - 16px));
  }
}

[data-theme="dark"] .creator-name {
  color: var(--color-text-primary);
}

/* 平台标识颜色 - 品牌色优化 */
/* 平台标识颜色 - 手机App图标版优化 (拉大差异) */
/* 抖音：采用更具品牌 Logo 特色的红青撞色渐变 */
.platform-badge.badge-douyin,
.platform-badge.badge-douyin_collection,
.platform-badge.badge-douyin_favorite {
  background: linear-gradient(135deg, #25F4EE 0%, #FE2C55 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 1px 1px 0px rgba(37, 244, 238, 0.5), -1px -1px 0px rgba(254, 44, 85, 0.5);
}

/* TikTok：以App图标的黑底为主，强调青色边缘 */
.platform-badge.badge-tiktok {
  background: #121212;
  border: 1.5px solid #25F4EE;
  color: #25F4EE;
  font-weight: 700;
}

.platform-badge.badge-instagram {
  background: linear-gradient(135deg, #f58529 0%, #dd2a7b 55%, #515bd4 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 0 1px 1px rgba(0,0,0,0.15);
}

.platform-badge.badge-youtube,
.platform-badge.badge-youtube_channel,
.platform-badge.badge-youtube_shorts,
.platform-badge.badge-youtube_playlist {
  background: linear-gradient(135deg, #FF0000 0%, #E60000 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 0 1px 1px rgba(0,0,0,0.2);
}

.platform-badge.badge-bilibili,
.platform-badge.badge-bilibili_collection,
.platform-badge.badge-bilibili_favorite {
  background: linear-gradient(135deg, #00A1D6 0%, #0079A1 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 0 1px 2px rgba(0,0,0,0.1);
}

/* 小红书：经典正红渐变，简约而醒目 */
.platform-badge.badge-xiaohongshu {
  background: linear-gradient(135deg, #FF2442 0%, #FF8999 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 0 1px 1px rgba(0,0,0,0.1);
}

.stats-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--color-text-tertiary);
}

[data-theme="dark"] .stats-row {
  color: var(--color-text-tertiary);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 快捷操作区 - 右侧灰色方块按钮 */
.quick-actions {
  display: flex;
  gap: 12px;
  flex-shrink: 0;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 72px;
  height: 48px;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 600;
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  cursor: pointer;
  transition: all 0.2s ease;
}

[data-theme="dark"] .action-btn {
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border-color: var(--color-border);
}

.action-btn:hover:not(:disabled) {
  background: var(--color-primary);
  color: #ffffff;
  border-color: var(--color-primary);
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(230, 126, 34, 0.2);
}

.action-btn:active:not(:disabled) {
  transform: translateY(0);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: var(--color-bg-tertiary);
}

[data-theme="dark"] .action-btn:disabled {
  background: var(--color-bg-tertiary);
}

.detail-icon {
  display: none; /* 移除冗余的箭头图标 */
}

/* 模态框遮罩 */
.drawer-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 24px;
}

/* 详情面板 (居中浮窗，高度适中) */
.drawer-panel {
  width: 100%;
  max-width: 600px;
  background: #ffffff;
  border-radius: 24px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  height: auto;
  max-height: 85vh;
  margin: auto;
  overflow: hidden;
}

[data-theme="dark"] .drawer-panel {
  background: var(--color-bg-card);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
}

/* Transition 动画 - 遮罩层淡入淡出 */
.drawer-fade-enter-active,
.drawer-fade-leave-active {
  transition: opacity 0.2s ease;
}

.drawer-fade-enter-from,
.drawer-fade-leave-to {
    opacity: 0;
}

/* Transition 动画 - 面板滑入滑出 */
.drawer-slide-enter-active {
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.drawer-slide-leave-active {
  transition: all 0.2s ease-in;
}

.drawer-slide-enter-from {
  opacity: 0;
  transform: scale(0.95) translateY(-10px);
  }

.drawer-slide-leave-to {
  opacity: 0;
  transform: scale(0.98);
}

.drawer-header {
  padding: 32px 24px 24px;
  border-bottom: none;
  background: linear-gradient(to bottom, #fcfcfc, #ffffff);
}

.drawer-title-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 16px;
}

.drawer-avatar {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  border: 4px solid #fff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.drawer-title {
  font-size: 22px;
  font-weight: 800;
  color: #1a1a1a;
  margin: 0;
}

.drawer-subtitle {
  font-size: 13px;
  color: #888;
  max-width: 300px;
  margin: 8px auto 0;
  line-height: 1.6;
}

/* 紧凑型头部重构 */
.drawer-header-compact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  background: linear-gradient(to bottom, var(--color-bg-card), var(--color-bg-primary));
  border-bottom: 1px solid var(--color-border);
}

[data-theme="dark"] .drawer-header-compact {
  background: linear-gradient(to bottom, var(--color-bg-card), var(--color-bg-secondary));
  border-bottom-color: var(--color-border);
}

.header-main-info {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
  min-width: 0;
}

.compact-avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: 2px solid var(--color-bg-card);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  object-fit: cover;
}

[data-theme="dark"] .compact-avatar {
  border-color: var(--color-bg-card);
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}

.compact-text-content {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.compact-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
  min-width: 0;
  flex: 1;
}

.compact-title {
  font-size: 18px;
  font-weight: 800;
  color: var(--color-text-primary);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  flex: 1;
  min-width: 0;
  max-width: 100%;
  mask-image: linear-gradient(to right, #000 0%, #000 90%, transparent 100%);
  -webkit-mask-image: linear-gradient(to right, #000 0%, #000 90%, transparent 100%);
}

.compact-title-track {
  display: inline-flex;
  align-items: center;
  min-width: 100%;
}

.compact-title-text {
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.compact-title-clone {
  display: none;
}

.compact-title.is-marquee .compact-title-track {
  min-width: max-content;
  animation: compact-title-marquee 10s linear infinite;
}

.compact-title.is-marquee:hover .compact-title-track {
  animation-play-state: paused;
}

.compact-title.is-marquee .compact-title-text {
  overflow: visible;
  text-overflow: clip;
  max-width: none;
  flex-shrink: 0;
}

.compact-title.is-marquee .compact-title-clone {
  display: inline-block;
  padding-left: 36px;
}

@keyframes compact-title-marquee {
  0%, 12% {
    transform: translateX(0);
  }
  88%, 100% {
    transform: translateX(calc(-50% - 18px));
  }
}

[data-theme="dark"] .compact-title {
  color: var(--color-text-primary);
}

.detail-header-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.platform-badge-mini, .status-badge-mini {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.platform-badge-mini { 
  background: var(--color-bg-tertiary); 
  color: var(--color-text-secondary); 
}

[data-theme="dark"] .platform-badge-mini {
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
}

/* 平台标识颜色 - 迷你版 - 抖音系列 */
.platform-badge-mini.badge-douyin,
.platform-badge-mini.badge-douyin_collection,
.platform-badge-mini.badge-douyin_favorite {
  background: linear-gradient(135deg, #FF0050, #FF6B00);
  color: #ffffff;
}

/* 平台标识颜色 - 迷你版 - TikTok */
.platform-badge-mini.badge-tiktok {
  background: linear-gradient(135deg, #000000, #25F4EE);
  color: #ffffff;
}

/* 平台标识颜色 - 迷你版 - YouTube系列 */
.platform-badge-mini.badge-youtube,
.platform-badge-mini.badge-youtube_channel,
.platform-badge-mini.badge-youtube_shorts,
.platform-badge-mini.badge-youtube_playlist {
  background: linear-gradient(135deg, #FF0000, #CC0000);
  color: #ffffff;
}

/* 平台标识颜色 - 迷你版 - B站系列 */
.platform-badge-mini.badge-bilibili,
.platform-badge-mini.badge-bilibili_collection {
  background: linear-gradient(135deg, #FB7299, #FF6699);
  color: #ffffff;
}

/* 平台标识颜色 - 迷你版 - X */
.platform-badge-mini.badge-x {
  background: linear-gradient(135deg, #111111, #2f2f2f);
  color: #ffffff;
}
.status-badge-mini.active { 
  background: var(--color-success-light); 
  color: var(--color-success); 
}

[data-theme="dark"] .status-badge-mini.active {
  background: var(--color-success-light);
  color: var(--color-success);
}

.status-badge-mini.paused { 
  background: var(--color-error-light); 
  color: var(--color-error); 
}

[data-theme="dark"] .status-badge-mini.paused {
  background: var(--color-error-light);
  color: var(--color-error);
}

.status-badge-mini.error { 
  background: var(--color-error-light); 
  color: var(--color-error); 
}

[data-theme="dark"] .status-badge-mini.error {
  background: var(--color-error-light);
  color: var(--color-error);
}

.status-badge-mini.invalid { 
  background: rgba(127, 140, 141, 0.15); 
  color: #7f8c8d; 
}

[data-theme="dark"] .status-badge-mini.invalid {
  background: rgba(127, 140, 141, 0.25);
  color: #b2bec3;
}

.compact-subtitle {
  font-size: 12px;
  color: var(--color-text-tertiary);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

[data-theme="dark"] .compact-subtitle {
  color: var(--color-text-tertiary);
}

.close-btn-mini {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: var(--color-bg-tertiary);
  color: var(--color-text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  margin-left: 12px;
}

[data-theme="dark"] .close-btn-mini {
  background: var(--color-bg-tertiary);
  color: var(--color-text-tertiary);
}

.close-btn-mini:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

[data-theme="dark"] .close-btn-mini:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

/* 抽屉内容 */
.drawer-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px 32px; /* 减小了顶部内边距 */
}

/* 统计概览 (极简盒式) */
/* 核心统计栏 (横向丝滑布局) */
.stats-ribbon {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8f9fa;
  border-radius: 12px;
  padding: 12px;
  margin-bottom: 16px;
}

[data-theme="dark"] .stats-ribbon {
  background: var(--color-bg-tertiary);
}

.ribbon-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
}

.ribbon-divider {
  width: 1px;
  height: 20px;
  background: #e9ecef;
  margin: 0 10px;
}

[data-theme="dark"] .ribbon-divider {
  background: var(--color-border);
}

.ribbon-value {
  font-size: 16px;
  font-weight: 700;
  color: #333;
}

[data-theme="dark"] .ribbon-value {
  color: var(--color-text-primary);
}

.ribbon-label {
  font-size: 11px;
  color: #888;
  margin-top: 2px;
}

[data-theme="dark"] .ribbon-label {
  color: var(--color-text-tertiary);
}

/* 时间指标列表 (紧凑行式) */
.time-metrics-list {
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 14px;
  padding: 4px 16px;
  margin-bottom: 24px;
}

[data-theme="dark"] .time-metrics-list {
  background: var(--color-bg-secondary);
  border-color: var(--color-border);
}

/* 时间轴数据 */
.time-metrics-list {
  margin-bottom: 24px;
}

.time-metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--color-border);
}

.time-metric-row:last-child {
  border-bottom: none;
}

.metric-info {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-tertiary);
}

.metric-icon {
  width: 14px; /* 固定图标容器宽度 */
  display: flex;
  justify-content: center;
}

.metric-label {
  font-size: 13px;
}

.metric-value {
  font-size: 13px;
  color: var(--color-text-secondary);
  font-weight: 500;
  font-family: 'JetBrains Mono', 'Fira Code', 'Roboto Mono', monospace; /* 使用等宽字体 */
  font-variant-numeric: tabular-nums; /* 启用表格数字，确保数字宽度一致 */
}

.time-metric-row.highlight .metric-label,
.time-metric-row.highlight .metric-value {
  color: var(--color-primary);
  font-weight: 600;
}

.neon-blue { color: #3498db; }
.neon-green { color: #2ecc71; }
.neon-orange { color: #e67e22; }

.row-icon.neon-orange-bg {
  color: #e67e22;
}

.status-indicator {
  font-size: 14px;
  font-weight: 700;
  padding: 2px 0;
}

.status-indicator.on { 
  color: var(--color-success); 
}

[data-theme="dark"] .status-indicator.on {
  color: var(--color-success);
}

.status-indicator.off { 
  color: var(--color-warning); 
}

[data-theme="dark"] .status-indicator.off {
  color: var(--color-warning);
}

/* 设置列表 */
.settings-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 24px;
}

.setting-row-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 14px;
  transition: all 0.2s;
}

[data-theme="dark"] .setting-row-item {
  background: var(--color-bg-secondary);
  border-color: var(--color-border);
}

.setting-row-item:hover {
  border-color: #e0e0e0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.02);
}

/* 批量设置全屏加载 */
.batch-loading-overlay {
  position: fixed;
  inset: 0;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(10px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
}

[data-theme="dark"] .batch-loading-overlay {
  background: rgba(15, 15, 15, 0.85);
}

.batch-loading-content {
  text-align: center;
}

.loading-spinner-wrapper {
  position: relative;
  width: 80px;
  height: 80px;
  margin: 0 auto 24px;
}

.batch-spinner {
  position: absolute;
  inset: 0;
  border: 4px solid var(--color-primary-light);
  border-top: 4px solid var(--color-primary);
  border-radius: 50%;
  animation: spin 1s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

.loading-pulse {
  position: absolute;
  inset: 10px;
  background: var(--color-primary);
  border-radius: 50%;
  opacity: 0.15;
  animation: pulse 1.5s ease-in-out infinite;
}

.batch-loading-title {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 8px;
  color: var(--color-text-primary);
}

.batch-loading-desc {
  font-size: 14px;
  color: var(--color-text-tertiary);
}

[data-theme="dark"] .setting-row-item:hover {
  border-color: var(--color-border-light);
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}

.row-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.row-icon {
  color: #e67e22;
  opacity: 0.8;
}

.row-text {
  display: flex;
  flex-direction: column;
}

.row-title {
  font-size: 14px;
  font-weight: 600;
  color: #333;
}

[data-theme="dark"] .row-title {
  color: var(--color-text-primary);
}

.row-desc {
  font-size: 12px;
  color: #888;
  line-height: 1.5;
  margin-top: 2px;
}

[data-theme="dark"] .row-desc {
  color: var(--color-text-tertiary);
}

/* 现代开关与下拉 */
.select-modern {
  width: 130px;
  height: 36px;
  padding: 0 12px;
  border-radius: 10px;
  font-size: 13px;
  background-color: #f5f5f5;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s;
  color: #333;
}

[data-theme="dark"] .select-modern {
  background-color: var(--color-bg-tertiary);
  color: var(--color-text-primary);
  border-color: var(--color-border);
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23cccccc' viewBox='0 0 16 16'%3E%3Cpath d='M7.247 11.14 2.451 5.658C2.185 5.355 2.403 5 2.808 5h9.384c.405 0 .623.355.358.658l-4.796 5.482a.503.503 0 0 1-.707 0L7.247 11.14z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: calc(100% - 10px) center;
}

.select-modern:hover {
  background-color: var(--color-bg-hover);
}

[data-theme="dark"] .select-modern:hover {
  background-color: var(--color-bg-hover);
}

.select-modern:focus {
  outline: none;
  border-color: var(--color-primary);
  background-color: var(--color-bg-card);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

[data-theme="dark"] .select-modern:focus {
  background-color: var(--color-bg-secondary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.switch-modern {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
  flex-shrink: 0;
  margin-left: 12px;
}

.switch-modern input { opacity: 0; width: 0; height: 0; }

.slider-modern {
  position: absolute;
  cursor: pointer;
  top: 0; left: 0; right: 0; bottom: 0;
  background-color: #e0e0e0;
  transition: .3s;
  border-radius: 22px;
}

[data-theme="dark"] .slider-modern {
  background-color: #333;
}

.slider-modern:before {
  position: absolute;
  content: "";
  height: 16px; width: 16px;
  left: 3px; bottom: 3px;
  background-color: white;
  transition: .3s;
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

input:checked + .slider-modern { background-color: #e67e22; }
input:checked + .slider-modern:before { transform: translateX(18px); }

/* 功能按钮区 */
/* 极简文字按钮网格 */
.drawer-actions-grid-five {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 6px;
  background: var(--color-bg-secondary);
  padding: 8px;
  border-radius: 12px;
  border: 1px solid var(--color-border);
}

.grid-pure-text-btn {
  height: 48px !important;
  padding: 0 !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  border-radius: 10px !important;
  border: 1.5px solid var(--color-primary) !important;
  background: transparent !important;
  color: var(--color-primary) !important;
  white-space: nowrap;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  line-height: 1;
  box-sizing: border-box;
}

.grid-pure-text-btn:hover:not(:disabled) {
  background: var(--color-primary) !important;
  color: #ffffff !important;
  border-color: var(--color-primary) !important;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(230, 126, 34, 0.3);
}

[data-theme="dark"] .grid-pure-text-btn:hover:not(:disabled) {
  box-shadow: 0 4px 12px rgba(230, 126, 34, 0.4);
}

.grid-pure-text-btn:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 6px rgba(230, 126, 34, 0.2);
}

.grid-pure-text-btn.delete-text {
  border-color: #ff4d4f !important;
  color: #ff4d4f !important;
}

.grid-pure-text-btn.delete-text:hover {
  background: #ff4d4f !important;
  color: #ffffff !important;
  border-color: #ff4d4f !important;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(255, 77, 79, 0.3);
}

.action-grid-two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

/* 动效 */
.spin { animation: fa-spin 2s infinite linear; }
.pulse { animation: pulse 1.5s infinite ease-in-out; }

@keyframes pulse {
  0% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.1); opacity: 0.7; }
  100% { transform: scale(1); opacity: 1; }
}

@keyframes fa-spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(359deg); }
}

/* 响应式 */


  /* 操作面板容器 - PC端整体背景 */
  .action-panel-container {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      column-gap: 0; /* 改用 padding 产生间距 */
      row-gap: 4px;
      margin-bottom: 24px;
      
      background: var(--color-bg-secondary);
      border-radius: 12px;
      padding: 0; /* 内部 padding 由 action-group 决定 */
      border: 1px solid var(--color-border);
      position: relative;
      overflow: visible;
      box-shadow: var(--shadow-sm);
  }
  
  .action-panel-container .primary-panel,
  .action-panel-container .secondary-panel {
      display: contents; 
      gap: 0;
      margin: 0;
      padding: 0;
      background: transparent;
      border-radius: 0;
      overflow: visible;
      flex-wrap: initial;
      align-items: initial;
  }

  .action-panel-container .action-group {
    display: flex;
    flex-direction: column;
    align-items: center; /* 垂直居中 */
    gap: var(--spacing-sm);
    padding: 8px 12px;
    position: relative;
    min-width: max-content;
    flex-shrink: 0;
  }

  /* 桌面端工具栏紧凑化，尽量避免 1080p 换行 */
  .action-panel-container .action-group-title {
    font-size: 11px;
  }

  .action-panel-container .group-items {
    gap: 6px;
  }

  .action-panel-container .btn-xs {
    height: 30px;
    font-size: 12px;
    padding: 3px 10px;
  }

  .action-panel-container .multiselect-header,
  .action-panel-container .form-input-xs {
    height: 28px;
    font-size: 12px;
  }

  /* 添加分隔线 */
  .action-panel-container .action-group:not(:last-child)::after {
    content: '';
    position: absolute;
    right: 0;
    top: 8px;
    bottom: 8px;
    height: auto;
    width: 1px;
    background: var(--color-border);
    opacity: 0.6;
  }

  /* 筛选组特别处理，宽度稍大 */
  .filter-action-group {
    flex-grow: 0;
  }

  .mobile-panel-toggle {
      display: none;
  }


/* 移动端适配 (覆盖上面的 PC 样式) */
@media (max-width: 768px) {
  .subscriptions-page {
      padding: 0;
      max-width: 100%;
      box-sizing: border-box;
  }

  .action-panel-container {
      display: block;
      background: transparent;
      border: none;
      padding: 0;
      max-width: 100%;
      overflow: visible;
      box-sizing: border-box;
  }

  /* 恢复 panel 的实体容器属性 */
  .action-panel-container .primary-panel, .action-panel-container .secondary-panel {
      display: flex;
      flex-direction: column;
      width: 100%;
      max-width: 100%;
      gap: 6px;
      box-sizing: border-box;
  }
  
  .action-panel-container .primary-panel {
      background: #fff;
      padding: 10px 8px;
      border-radius: 8px;
      margin-bottom: 8px;
      max-width: 100%;
      position: relative;
      z-index: 101;
      overflow: visible !important;
      box-sizing: border-box;
  }

  [data-theme="dark"] .action-panel-container .primary-panel {
      background: var(--color-bg-card);
      border: 1px solid var(--color-border);
  }

  .action-panel-container .secondary-panel {
      background: var(--color-bg-tertiary);
      padding: 4px 8px;
      border-radius: 0 0 12px 12px;
      margin-top: -8px;
      border: 1px solid var(--color-border);
      border-top: none;
      max-width: 100%;
      overflow: hidden;
      transition: max-height 0.3s ease, opacity 0.3s ease;
      max-height: 1000px;
      opacity: 1;
      box-sizing: border-box;
  }

  .action-panel-container .secondary-panel.mobile-collapsed {
      max-height: 0;
      opacity: 0;
      margin: 0;
      padding-top: 0;
      padding-bottom: 0;
      border: none;
  }
  
  .action-group {
      width: 100%;
      max-width: 100%;
      min-width: 0;
      padding: 4px 0;
      position: relative;
      box-sizing: border-box;
  }

  .action-group-title {
    font-size: 10px;
    margin-bottom: 0;
    opacity: 0.85;
  }

  /* 分隔线：替代已删除的副标题 */
  .secondary-panel .action-group:not(:last-child)::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 10%;
    right: 10%;
    height: 1px;
    background: var(--color-border);
    opacity: 0.4;
    display: block !important;
  }

  .action-group::after {
    display: none !important; /* 隐藏 PC 端的分隔线 */
  }
  
  .mobile-panel-toggle {
      display: flex;
      width: 100%;
      margin: 12px 0;
      justify-content: center;
      align-items: center;
      gap: 6px;
      padding: 10px;
      font-size: 14px;
      color: var(--color-primary);
      background: var(--color-bg-tertiary);
      border: 1px solid var(--color-border);
      border-radius: 8px;
      transition: all 0.2s ease;
  }

  [data-theme="dark"] .mobile-panel-toggle {
      background: rgba(255,255,255,0.05);
      color: var(--color-text-tertiary);
  }


  
  .group-items {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 6px; /* 从 10px 降到 6px */
    width: 100%;
  }

  /* 让按钮铺满格子 */
  .group-items .btn {
    width: 100%;
    justify-content: center;
    box-shadow: none;
    border: 1px solid var(--color-border);
  }

  /* 筛选器: 两行，筛选器占满一行，搜索框换行 */
  .filter-horizontal {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    gap: 4px !important;
    width: 100% !important;
  }

  .compact-select, .custom-multiselect {
    min-width: 0 !important;
    width: 100% !important;
  }

  .search-input-wrapper {
      width: 100% !important;
      min-width: 0 !important;
      margin: 0 !important;
      grid-column: 1 / -1 !important;
  }

  .search-input {
    width: 100% !important;
    min-width: 0 !important;
    height: 30px !important;
    padding-left: 22px !important;
    font-size: 12px !important;
  }

  /* 订阅卡片网格:单列 */
  .subscriptions-grid {
    grid-template-columns: 1fr;
    gap: var(--spacing-sm);
    max-width: 100%;
    box-sizing: border-box;
  }

  /* 卡片:紧凑布局 */
  .subscription-card {
    padding: 10px;
    gap: 10px;
    min-height: 80px;
    align-items: center;
    max-width: 100%;
    box-sizing: border-box;
  }

  /* 头像保持较大尺寸并对齐电脑端比例 */
  .avatar-side {
    width: 74px; /* 增加宽度 */
    margin-top: 0;
  }

  .avatar-container {
    width: 64px !important;
    height: 114px !important; /* 9:16 ratio */
  }

  .name-row {
    padding-right: 32px;
    gap: 8px;
    align-items: center;
  }

  .name-row .platform-badge {
    padding: 2px 6px;
    font-size: 11px;
    border-radius: 4px;
    line-height: 1.2;
  }

  .name-row .video-count-inline {
    font-size: 12px;
    color: var(--color-text-tertiary);
    background: var(--color-bg-tertiary);
    padding: 1px 6px;
    border-radius: 4px;
    font-weight: 500;
  }

  /* 信息区:压缩间距 */
  .creator-name {
    font-size: 17px;
    max-width: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .platform-badge {
    font-size: 10px;
    padding: 1px 6px;
  }

  .stats-row {
    font-size: 12px;
  }

  /* 隐藏右侧快捷操作(点击卡片进入详情) */
  .quick-actions {
    display: none;
  }

  /* 快捷操作工具栏:移动端显示为横向滚动 */
  .quick-actions-toolbar {
    display: flex;
    flex-wrap: wrap; /* 允许换行，但让按钮组不换行 */
    gap: 8px;
    padding-bottom: 2px;
    margin-top: 10px;
  }
  
  /* 强制按钮不换行 */
  .toolbar-btn {
    flex: 1; 
    min-width: 0; /* 允许压缩 */
    font-size: 13px;
    padding: 8px 4px;
    white-space: nowrap;
    justify-content: center;
    order: 0;
  }
  
  /* 进度条/时间提示强制换行并占满宽度 */
  .progress-notification {
    flex-basis: 100%;
    width: 100%;
    order: 1;
    margin-top: 4px;
  }

  /* 详情抽屉:全屏显示 */
  .drawer-overlay {
    padding: 0;
    align-items: flex-start; /* 顶部对齐，避免居中导致顶部被遮挡 */
    justify-content: flex-start; /* 移除居中 */
  }

  .drawer-panel {
    width: 100%;
    max-width: 100%;
    max-height: 100vh;
    height: 100vh;
    border-radius: 0;
    margin: 0;
    box-sizing: border-box;
  }

  /* 移动端优化：使用从底部滑入的动画，更自然 */
  .drawer-slide-enter-active {
    transition: all 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
  }

  .drawer-slide-leave-active {
    transition: all 0.25s cubic-bezier(0.55, 0.06, 0.68, 0.19);
  }

  .drawer-slide-enter-from {
    opacity: 0;
    transform: translateY(20px);
  }

  .drawer-slide-leave-to {
    opacity: 0;
    transform: translateY(10px);
  }

  /* 紧凑头部 */
  .drawer-header-compact {
    padding: var(--spacing-sm) var(--spacing-md);
    /* 添加安全区域适配，确保在有刘海的设备上头部不被遮挡 */
    padding-top: calc(var(--spacing-sm) + env(safe-area-inset-top, 0px));
  }

  .compact-avatar {
    width: 44px;
    height: 44px;
  }

  .compact-title {
    font-size: 16px;
  }

  .compact-subtitle {
    font-size: 11px;
  }

  /* 内容区 */
  .drawer-content {
    padding: var(--spacing-sm) var(--spacing-md);
    /* 添加底部安全区域适配，确保底部内容不被手势导航栏遮挡 */
    padding-bottom: calc(var(--spacing-sm) + env(safe-area-inset-bottom, 0px));
  }

  /* 统计带:垂直堆叠 */
  .stats-ribbon {
    flex-wrap: wrap;
    gap: var(--spacing-sm);
  }

  .ribbon-item {
    min-width: 80px;
  }

  .ribbon-divider {
    display: none;
  }

  /* 时间指标 */
  .time-metrics-list {
    padding: 4px 12px;
  }

  .time-metric-row {
    padding: 8px 0;
  }

  .metric-label,
  .metric-value {
    font-size: 12px;
  }

  /* 设置行 */
  .setting-row-item {
    padding: 10px 12px;
  }

  .row-title {
    font-size: 13px;
  }

  .select-modern {
    width: 110px;
    height: 32px;
    font-size: 12px;
  }

  /* 操作按钮网格:3列 */
  .drawer-actions-grid-five {
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
    padding: 6px;
  }

  .grid-pure-text-btn {
    height: 42px !important;
    font-size: 11px !important;
  }

  /* 状态点 */
  .status-dot {
    top: 8px;
    left: 8px;
    width: 8px;
    height: 8px;
  }
}

/* 超窄屏适配 (400px以下) */
@media (max-width: 400px) {
  .action-panel {
    padding: var(--spacing-xs);
  }

  .subscription-card {
    padding: 10px;
    gap: 10px;
  }

  .avatar-container {
    width: 56px !important; 
    height: 100px !important; /* 9:16 ratio */
  }

  .creator-name {
    font-size: 14px;
    flex: 1; /* 让名字占据剩余空间 */
    min-width: 0; /* 允许截断 */
  }

  .platform-badge {
    display: inline-block; /* 强制显示 */
    flex-shrink: 0; /* 防止被挤压 */
    font-size: 9px;
    padding: 1px 4px;
    margin-left: 4px;
  }

  .stats-row {
    font-size: 11px;
  }

  .drawer-actions-grid-five {
    grid-template-columns: repeat(2, 1fr);
  }

  .compact-select {
    min-width: 70px;
  }
}

/* 提示框输入框样式 */
.tip-input {
  width: 100%;
  padding: 10px 12px;
  margin-top: 15px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 1rem;
  transition: border-color 0.2s ease;
}

.tip-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(230, 126, 34, 0.1);
}

/* 添加订阅表单样式 */
.add-subscription-form {
  display: flex;
  flex-direction: column;
  gap: 16px; /* 减小间距 */
  padding: 4px 0;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

/* 筛选器遮罩层 */
.platform-dropdown-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  z-index: 999;
  cursor: default;
}

[data-theme="dark"] .platform-dropdown-overlay {
  background: rgba(0, 0, 0, 0.5);
}

/* 提升下拉框层级，确保在遮罩之上 */
.multiselect-dropdown {
  z-index: 1000 !important;
}

.form-label .icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

/* Utility Classes */
.text-primary { color: var(--color-primary); }
.font-bold { font-weight: 600; }
.ml-auto { margin-left: auto; }

/* 现代化输入框 */
.form-input-modern,
.form-select-modern {
  width: 100%;
  padding: 10px 14px;
  font-size: 14px;
  border: 1.5px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  transition: all 0.2s ease;
  outline: none;
}

.form-input-modern:focus,
.form-select-modern:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(230, 126, 34, 0.1);
  background: var(--color-bg-primary);
}

[data-theme="dark"] .form-input-modern,
[data-theme="dark"] .form-select-modern {
  background: var(--color-bg-secondary);
  border-color: var(--color-border);
}

[data-theme="dark"] .form-input-modern:focus,
[data-theme="dark"] .form-select-modern:focus {
  background: var(--color-bg-card);
}

.form-select-modern {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23666' viewBox='0 0 16 16'%3E%3Cpath d='M7.247 11.14 2.451 5.658C2.185 5.355 2.403 5 2.808 5h9.384c.405 0 .623.355.358.658l-4.796 5.482a.503.503 0 0 1-.707 0L7.247 11.14z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 36px;
}

[data-theme="dark"] .form-select-modern {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23ccc' viewBox='0 0 16 16'%3E%3Cpath d='M7.247 11.14 2.451 5.658C2.185 5.355 2.403 5 2.808 5h9.384c.405 0 .623.355.358.658l-4.796 5.482a.503.503 0 0 1-.707 0L7.247 11.14z'/%3E%3C/svg%3E");
}

/* 表单提示 */
.form-hint {
  font-size: 12px;
  color: var(--color-text-tertiary);
  margin-top: -4px;
  line-height: 1.4;
}

/* 平台提示框 */
.platform-hint {
  padding: 16px;
  border-radius: 10px;
  border: 1.5px solid;
  background: var(--color-bg-secondary);
}

.platform-hint-info {
  border-color: var(--color-primary-light);
  background: linear-gradient(135deg, rgba(230, 126, 34, 0.05), rgba(230, 126, 34, 0.02));
}

[data-theme="dark"] .platform-hint-info {
  background: rgba(230, 126, 34, 0.1);
  border-color: rgba(230, 126, 34, 0.3);
}

.hint-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-primary);
  margin-bottom: 12px;
}

.hint-header .icon {
  flex-shrink: 0;
}

.hint-content {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.hint-content p {
  margin: 6px 0;
}

.hint-content p:first-child {
  margin-top: 0;
}

.hint-content p:last-child {
  margin-bottom: 0;
}

.hint-content strong {
  color: var(--color-text-primary);
  font-weight: 600;
}

.hint-list {
  margin: 8px 0;
  padding-left: 20px;
  list-style: none;
}

.hint-list li {
  margin: 6px 0;
  position: relative;
  padding-left: 16px;
}

.hint-list li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: var(--color-primary);
  font-weight: bold;
}

.hint-list code {
  background: var(--color-bg-tertiary);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  color: var(--color-primary);
  border: 1px solid var(--color-border);
  word-break: break-all;
}

[data-theme="dark"] .hint-list code {
  background: rgba(0, 0, 0, 0.3);
  border-color: var(--color-border);
}

.hint-warning {
  color: var(--color-warning) !important;
  font-weight: 500;
  margin-top: 10px !important;
  padding-top: 10px;
  border-top: 1px solid var(--color-border);
}

/* 复选框样式 */
.form-group-checkbox {
  padding: 12px;
  background: var(--color-bg-secondary);
  border-radius: 10px;
  border: 1.5px solid var(--color-border);
}

.checkbox-label-modern {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  cursor: pointer;
  user-select: none;
}

.checkbox-modern {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.checkbox-custom {
  width: 20px;
  height: 20px;
  border: 2px solid var(--color-border);
  border-radius: 5px;
  background: var(--color-bg-card);
  flex-shrink: 0;
  margin-top: 2px;
  position: relative;
  transition: all 0.2s ease;
}

.checkbox-modern:checked + .checkbox-custom {
  background: var(--color-primary);
  border-color: var(--color-primary);
}

.checkbox-modern:checked + .checkbox-custom::after {
  content: '';
  position: absolute;
  left: 6px;
  top: 2px;
  width: 5px;
  height: 10px;
  border: solid white;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}

.checkbox-modern:focus + .checkbox-custom {
  box-shadow: 0 0 0 3px rgba(230, 126, 34, 0.1);
}

.checkbox-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}

.checkbox-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.checkbox-desc {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

/* 静态提示卡片 */
.static-hint-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: #e6f7ff;
  border: 1px solid #91d5ff;
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 20px;
}

.hint-icon {
  color: #1890ff;
  flex-shrink: 0;
  margin-top: 2px;
}

.hint-text {
  font-size: 13px;
  color: #1890ff;
  line-height: 1.5;
}

.hint-text .highlight {
  font-weight: 700;
  background: rgba(24, 144, 255, 0.1);
  padding: 0 4px;
  border-radius: 4px;
}

/* 空状态样式 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
  background: var(--color-bg-card);
  border-radius: 20px;
  border: 1px dashed var(--color-border);
  margin: 24px 0;
  box-shadow: var(--shadow-sm);
}

.empty-icon {
  font-size: 56px;
  margin-bottom: 20px;
  filter: drop-shadow(0 4px 12px rgba(0,0,0,0.1));
}

.empty-title {
  font-size: 22px;
  font-weight: 800;
  color: var(--color-text-primary);
  margin-bottom: 12px;
}

.empty-desc {
  font-size: 15px;
  color: var(--color-text-tertiary);
  max-width: 440px;
  margin-bottom: 28px;
  line-height: 1.6;
}

/* 统一加载过渡动画 */
.subscriptions-main-container {
  min-height: 500px;
  position: relative;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
