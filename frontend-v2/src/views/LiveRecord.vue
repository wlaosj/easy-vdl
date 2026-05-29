<template>
  <div class="live-record-page">

    <!-- 授权检测提示 -->
    <div v-if="!licenseValid" class="license-alert">
      <div class="license-icon">🔒</div>
      <h2>{{ checkingLicense ? '正在验证...' : '需要授权' }}</h2>
      <p v-if="!checkingLicense">该功能为高级功能，请前往发卡平台购买授权</p>
      
      <div class="license-features" v-if="!checkingLicense">
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>支持 抖音 / 斗鱼 / B站 / 虎牙 / 小红书 / YouTube / 咪咕 / 快手 / 网易CC / Twitch</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>自动检测开播 + 全自动开启录制</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>TG / 微信 / Server酱 开播消息通知</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>录制结束自动转码 MP4 + 智能分段</span>
        </div>
         <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>7x24小时无人值守全自动录制挂机</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>录制历史管理、在线播放与空间统计</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>直播录制支持的平台会陆续增加</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>支持弹幕录制（当前支持抖音 / B站 / 斗鱼）</span>
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
    <div class="top-row">
      <!-- 统计卡片 -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-content">
            <h3>{{ stats.total_subscriptions || 0 }}</h3>
            <p>监控中</p>
          </div>
        </div>

        <div class="stat-card live">
          <div class="stat-content">
            <h3>{{ stats.live_count || 0 }}</h3>
            <p>直播中</p>
          </div>
        </div>
        
        <div class="stat-card recording">
          <div class="stat-content">
            <h3>{{ stats.recording_count || 0 }}</h3>
            <p>录制中</p>
          </div>
        </div>
        
        <div class="stat-card">
          <div class="stat-content">
            <h3>{{ stats.today_records || 0 }}</h3>
            <p>今日录制</p>
          </div>
        </div>
        
        <div class="stat-card storage-card">
          <div class="stat-content">
            <h3 class="storage-size">
              <span class="storage-size-number">{{ storageSizeDisplay.value }}</span>
              <span class="storage-size-unit">{{ storageSizeDisplay.unit }}</span>
            </h3>
            <p>已使用</p>
          </div>
        </div>
      </div>

      <!-- 操作栏 -->
      <div class="action-bar">
        <!-- 第一行：搜索与主操作 -->
        <div class="action-row top">
          <div class="filter-group mobile-only mobile-primary-filters">
            <select v-model="filterPlatform" class="form-select filter-select">
              <option value="all">所有平台</option>
              <option value="douyin">抖音</option>
              <option value="douyu">斗鱼</option>
              <option value="bilibili">Bilibili</option>
              <option value="huya">虎牙</option>
              <option value="xhs">小红书</option>
              <option value="youtube">YouTube</option>
              <option value="migu">咪咕</option>
              <option value="kuaishou">快手</option>
              <option value="cc">网易CC</option>
              <option value="twitch">Twitch</option>
            </select>
            <select v-model="filterStatus" class="form-select filter-select">
              <option value="all">所有状态</option>
              <option value="live">直播中</option>
              <option value="recording">录制中</option>
              <option value="paused">暂停检测</option>
              <option value="offline">离线</option>
            </select>
            <select v-model="sortBy" class="form-select filter-select" @change="saveSortPreference">
              <option value="status">默认排序</option>
              <option value="newest">最新添加</option>
              <option value="oldest">最早添加</option>
              <option value="name">主播名称</option>
            </select>
          </div>
          <div class="search-container">
            <div class="search-input-wrapper">
              <Icon name="search" :size="16" class="search-icon" />
              <input 
                v-model="searchKeyword"
                type="text"
                class="search-input"
                placeholder="搜索主播名称..."
              />
              <button v-if="searchKeyword" class="clear-search" @click="searchKeyword = ''">
                <Icon name="close" :size="14" />
              </button>
            </div>
          </div>
          <div class="action-left">
            <button class="btn btn-primary" @click="showAddModal = true">添加<span class="mobile-hide">直播间</span></button>
            <button class="btn btn-outline" @click="refreshAll">刷新<span class="mobile-hide">状态</span></button>
            <button class="btn btn-outline" @click="openGlobalHistory">录制历史</button>
            <button class="btn btn-outline" @click="$router.push('/settings?tab=cookie')">
              <Icon name="settings" :size="14" style="vertical-align: middle; margin-right: 2px;" />
              Cookie
            </button>

            <!-- 直播订阅备份：导出 / 导入 -->
            <div class="live-backup-actions mobile-hide">
              <button class="btn btn-outline btn-sm" @click="exportLiveConfig" :disabled="subscriptions.length === 0">
                导出订阅
              </button>
              <button class="btn btn-outline btn-sm" @click="triggerLiveImport">
                导入订阅
              </button>
            </div>

            <button class="btn btn-outline mobile-only" @click="showToolsModal = true">
              更多工具
            </button>
          </div>
        </div>

        <!-- 第二行：批量操作与过滤器 -->
        <div class="action-row bottom mobile-hide">
          <div class="bulk-actions" v-if="filteredSubscriptions.length > 0">
            <button class="btn btn-xs btn-outline" @click="showBulkAutoRecordModal = true" :disabled="bulkLoading">录制开关</button>
            <button class="btn btn-xs btn-outline" @click="showBulkMonitorModal = true" :disabled="bulkLoading">检测开关</button>
            <button class="btn btn-xs btn-outline" @click="showBulkNotificationModal = true" :disabled="bulkLoading">通知开关</button>
            <button class="btn btn-xs btn-outline" @click="showBulkSubtitleModal = true" :disabled="bulkLoading">字幕开关</button>
            <button class="btn btn-xs btn-outline" @click="showBulkConvertModal = true" :disabled="bulkLoading">转码开关</button>
            <button class="btn btn-xs btn-outline" @click="showBulkSegmentModal = true" :disabled="bulkLoading">分段录制</button>
            <button class="btn btn-xs btn-outline" @click="showBulkQualityModal = true" :disabled="bulkLoading">修改画质</button>
            <button class="btn btn-xs btn-danger" @click="confirmBulkDelete" :disabled="bulkLoading">批量删除</button>
          </div>
          
          <div class="action-right">
            <!-- 备份按钮已移至上方主操作组 -->
            <div class="filter-group top-inline-filters">
              <select v-model="filterPlatform" class="form-select filter-select">
                <option value="all">所有平台</option>
                <option value="douyin">抖音</option>
                <option value="douyu">斗鱼</option>
                <option value="bilibili">Bilibili</option>
                <option value="huya">虎牙</option>
                <option value="xhs">小红书</option>
                <option value="youtube">YouTube</option>
                <option value="migu">咪咕</option>
                <option value="kuaishou">快手</option>
                <option value="cc">网易CC</option>
                <option value="twitch">Twitch</option>
              </select>
              <select v-model="filterStatus" class="form-select filter-select">
                <option value="all">所有状态</option>
                <option value="live">直播中</option>
                <option value="recording">录制中</option>
                <option value="paused">暂停检测</option>
                <option value="offline">离线</option>
              </select>
              <select v-model="sortBy" class="form-select filter-select" style="margin-left: 8px;" @change="saveSortPreference">
                <option value="status">默认排序</option>
                <option value="newest">最新添加</option>
                <option value="oldest">最早添加</option>
                <option value="name">主播名称</option>
              </select>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 直播订阅导入隐藏文件选择 -->
    <input
      ref="liveImportInput"
      type="file"
      accept=".json"
      style="display: none"
      @change="handleLiveImport"
    />

    <!-- 直播间列表 -->
    <div class="rooms-section">
      <Transition name="fade" mode="out-in">
        <SkeletonLoader 
          v-if="loading"
          :loading="true" 
          text="正在获取直播直播间列表..." 
          type="grid" 
          :count="10"
          itemHeight="240px"
          itemMinWidth="260px"
        />
        <div v-else class="rooms-grid">
        <div
          v-for="sub in subscriptionCards"
          :key="sub.id"
          class="room-card"
          :class="{ 'is-live': sub.is_live === 'true', 'is-recording': sub.is_recording === 'true' }"
        >


          <!-- 状态指示点 -->
          <div 
            class="status-dot" 
            :class="{
              'status-monitor-paused': sub.monitor_enabled === 'false',
              'status-auto-on': sub.monitor_enabled !== 'false' && sub.auto_record === 'true',
              'status-auto-off': sub.monitor_enabled !== 'false' && sub.auto_record !== 'true'
            }"
            :title="sub.monitor_enabled === 'false' ? '周期检测已暂停' : (sub.auto_record === 'true' ? '自动录制已开启' : '自动录制已关闭')"
          ></div>

          <!-- 右上角操作区域 -->
          <div class="card-top-actions">
            <button class="card-action-btn settings-btn" @click.stop="editSubscription(sub)" title="设置">
              <Icon name="settings" :size="16" />
            </button>
          </div>

          <div class="card-main-body">
            <!-- 侧边头像区域 -->
            <div class="avatar-side">
              <a :href="sub.room_url" target="_blank" rel="noopener noreferrer" class="avatar-link" :class="{ 'is-live': sub.is_live === 'true' }">
                <div v-if="sub.is_live === 'true'" class="live-ring"></div>
                <div class="avatar-container">
                  <img v-if="sub.avatar_url" :src="sub.avatar_url" :alt="sub.anchor_name" class="avatar" referrerpolicy="no-referrer" loading="lazy" />
                  <div v-else class="avatar-placeholder">{{ (sub.anchor_name || '未')[0] }}</div>
                </div>
                <div v-if="sub.is_live === 'true'" class="live-label">直播中</div>
              </a>
              <!-- 平台标识已移至名称前 -->
            </div>

            <!-- 信息区域 -->
            <div class="info-area">
              <div class="name-row">
                <span class="platform-badge" :class="`badge-${sub.platform}`">
                  {{ sub._platformName }}
                </span>
                <a :href="sub.room_url" target="_blank" rel="noopener noreferrer" class="name-link">
                  <h3
                    class="room-name"
                    :class="{ 'is-marquee': (sub._anchorName || '').length > 10 }"
                    :title="sub._anchorName"
                  >
                    <span class="room-name-track">
                      <span class="room-name-text">{{ sub._anchorName }}</span>
                      <span class="room-name-text room-name-clone" aria-hidden="true">{{ sub._anchorName }}</span>
                    </span>
                  </h3>
                </a>
              </div>
              
              <!-- 录制状态/画质信息 -->
              <div class="room-metrics">
                <div v-if="sub.is_recording === 'true' && sub.recording_status" class="recording-block highlight">
                  <div class="recording-row-main">
                    <span class="recording-text">录制中</span>
                    <span class="dot">·</span>
                    <span class="recording-duration">{{ sub._duration }}</span>
                    <span class="dot">·</span>
                    <span class="recording-size">{{ sub._fileSize }}</span>
                  </div>
                  <div class="recording-row-sub">
                    <template v-if="sub.recording_status.resolution || sub.recording_status.fps">
                      <span class="quality-label">画质：</span>
                      <span class="quality-value">
                        {{ sub.recording_status.resolution || '' }}
                        <span v-if="sub.recording_status.resolution && sub.recording_status.fps" style="margin: 0 4px;"></span>
                        {{ sub.recording_status.fps ? sub.recording_status.fps + 'fps' : '' }}
                      </span>
                    </template>
                    <span v-else class="getting-info">正在获取流信息...</span>
                    <template v-if="sub.compat_mode">
                      <span class="dot">·</span>
                      <span 
                        class="compat-badge-mini"
                        :class="{ 'is-recording': sub.is_recording === 'true' }"
                        title="已开启兼容模式（实时重编码）"
                      >
                        兼容
                      </span>
                    </template>
                    <template v-if="sub.danmu_enabled">
                      <span class="dot">·</span>
                      <span 
                        class="danmu-badge-mini"
                        :class="{ 'is-recording': sub.is_recording === 'true' }"
                        title="已开启弹幕录制"
                      >
                        弹幕
                      </span>
                    </template>
                  </div>
                </div>
                <div v-else class="metric-item">
                  <div class="status-badge-container">
                    <span v-if="sub.is_live === 'true'" class="live-status-text">直播中</span>
                    <span v-else-if="sub.monitor_enabled === 'false'" class="paused-status-text">已暂停检测</span>
                    <span v-else class="offline-status-text">未开播</span>
                  </div>
                  <span class="dot">·</span>
                  <span>{{ sub.quality }}</span>
                  <template v-if="sub.auto_record !== 'true' || sub.is_live === 'true'">
                    <span class="dot">·</span>
                    <span>{{ sub.auto_record === 'true' ? '自动录制' : '手动' }}</span>
                  </template>
                  <template v-if="sub.compat_mode">
                    <span class="dot">·</span>
                    <span 
                      class="compat-badge-mini"
                      :class="{ 'is-recording': sub.is_recording === 'true' }"
                      title="已开启兼容模式（实时重编码）"
                    >
                      兼容
                    </span>
                  </template>
                  <template v-if="sub.danmu_enabled">
                    <span class="dot">·</span>
                    <span 
                      class="danmu-badge-mini"
                      :class="{ 'is-recording': sub.is_recording === 'true' }"
                      title="已开启弹幕录制"
                    >
                      弹幕
                    </span>
                  </template>
                </div>
                <!-- 自动监控提示独立一行 -->
                <div v-if="sub.monitor_enabled === 'false'" class="monitoring-row">
                  <p class="monitoring-hint">
                    已暂停周期检测
                  </p>
                </div>
                <div v-else-if="sub.auto_record === 'true' && sub.is_live !== 'true'" class="monitoring-row">
                  <p class="monitoring-hint">
                    正在自动监控，开播即录
                  </p>
                </div>
              </div>
            </div>
          </div>

          <!-- 操作按钮栏 -->
          <div class="room-actions">
            <div v-if="sub.is_live === 'true'" class="room-action-row primary">
              <button 
                v-if="sub.is_recording !== 'true'"
                class="btn btn-primary btn-sm"
                @click="startRecording(sub)"
                :disabled="actionLoading[sub.id]"
              >
                开始录制
              </button>
              <button 
                v-else
                class="btn btn-danger btn-sm"
                @click="stopRecording(sub)"
                :disabled="actionLoading[sub.id]"
              >
                停止录制
              </button>
              
              <button 
                class="btn btn-success btn-sm"
                @click="playStream(sub)"
                :disabled="actionLoading[sub.id]"
              >
                {{ String(sub.platform || '').toLowerCase() === 'youtube' ? '跳转观看' : '查看直播' }}
              </button>
            </div>

            <div class="room-action-row secondary">
              <button 
                class="btn btn-secondary btn-sm"
                @click="refreshStatus(sub)"
                :disabled="actionLoading[sub.id]"
              >
                刷新状态
              </button>
              
              <button 
                class="btn btn-outline btn-sm"
                @click="showSubscriptionHistory(sub)"
              >
                录制历史
              </button>

              <button
                class="btn btn-outline btn-sm btn-timeline"
                @click="openTimelineForSub(sub)"
                :disabled="!isTimelineAvailable(sub.id)"
                :title="getTimelineButtonTitle(sub.id)"
              >
                时间轴
              </button>
            </div>
          </div>
        </div>
        </div>
      </Transition>
    </div>

  <template v-if="isLiveRecordRouteActive">
    <!-- 添加直播间模态框 -->
    <Modal v-model:show="showAddModal" title="添加直播间" @close="resetAddForm">
      <div class="add-form">
        <div class="form-group">
          <div class="mode-toggle">
            <button
              type="button"
              class="mode-btn"
              :class="{ active: addMode === 'single' }"
              @click="addMode = 'single'"
            >
              单个添加
            </button>
            <button
              type="button"
              class="mode-btn"
              :class="{ active: addMode === 'batch' }"
              @click="addMode = 'batch'"
            >
              批量添加
            </button>
          </div>
          <p class="form-hint">批量模式：每行一个链接，可混合平台，系统会自动识别。</p>
        </div>

        <div class="form-group">
          <label class="form-label" v-if="addMode === 'single'">直播间地址</label>
          <label class="form-label" v-else>直播间地址（每行一个）</label>
          <input
            v-if="addMode === 'single'"
            v-model="addForm.room_url"
            type="text"
            class="form-input"
            placeholder="请输入直播间地址"
          />
          <textarea
            v-else
            v-model="addBatchText"
            class="form-textarea"
            rows="6"
            placeholder="每行一个直播间链接"
          ></textarea>
          <div class="form-hint">
            目前支持 抖音 / 斗鱼 / B站 / 虎牙 / 小红书 / YouTube / 咪咕 / 快手 / 网易CC / Twitch 直播
            <a href="javascript:;" @click="showFormatHelp" style="margin-left:8px; color: var(--color-primary); text-decoration: none;">
              查看支持的链接格式
            </a>
          </div>
          <div class="form-hint" v-if="addMode === 'batch'">
            已识别 {{ batchStats.total }} 条，去重后 {{ batchStats.unique }} 条
            <span v-if="batchStats.duplicates > 0" style="margin-left:6px;">（已忽略 {{ batchStats.duplicates }} 条重复链接）</span>
          </div>
          <div class="form-hint" style="color:#dd6b20;">
            ⚠️ 小红书直播链接通常是临时链接，容易失效，暂不适合做长期自动监控。
          </div>
          <div class="form-hint" style="color:#dd6b20; margin-top: 4px;">
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">录制画质</label>
          <select v-model="addForm.quality" class="form-select">
            <option value="原画">原画</option>
            <option value="蓝光">蓝光</option>
            <option value="超清">超清</option>
            <option value="高清">高清</option>
          </select>
        </div>

        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="addForm.monitor_enabled" />
            <span>周期检测</span>
          </label>
          <p class="form-hint">关闭后将暂停检测开播状态，不会自动开始录制</p>
        </div>

        <div class="form-group">
          <label class="form-label">检测间隔 (秒)</label>
          <input 
            v-model.number="addForm.check_interval"
            type="number"
            :class="['form-input', { 'form-input-error': addIntervalError && addIntervalTouched }]"
            :disabled="!addForm.monitor_enabled"
            min="10"
            max="600"
            step="1"
            @blur="addIntervalTouched = true"
          />
          <p :class="addIntervalError && addIntervalTouched ? 'form-error' : 'form-hint'">
            {{ !addForm.monitor_enabled ? '开启周期检测后可设置检测间隔' : (addIntervalError && addIntervalTouched ? addIntervalError : getCheckIntervalHint('')) }}
          </p>
        </div>

        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="addForm.auto_record" />
            <span>开播自动录制</span>
          </label>
        </div>

        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="addForm.notification_enabled" />
            <span>开播/录制通知</span>
          </label>
          <p class="form-hint">需在系统设置中配置通知渠道 (微信/Telegram等)</p>
        </div>

        <div class="form-group" v-if="(addMode === 'batch') || addForm.room_url.includes('douyin.com') || addForm.room_url.includes('bilibili.com') || addForm.room_url.includes('b23.tv') || addForm.room_url.includes('douyu.com') || addForm.room_url.includes('huya.com') || addForm.room_url.includes('twitch.tv')">
          <label class="checkbox-label">
            <input type="checkbox" v-model="addForm.danmu_enabled" />
            <span>录制弹幕（抖音 / B站 / 斗鱼 / 虎牙 / Twitch）</span>
          </label>
          <p class="form-hint">默认关闭。当前支持抖音/B站/斗鱼/虎牙/Twitch，开启后会额外写入 .danmu.jsonl 文件</p>
        </div>
      </div>

      <template #footer>
        <button class="btn btn-secondary" @click="showAddModal = false">取消</button>
        <button class="btn btn-primary" @click="addSubscription" :disabled="addLoading || !!addIntervalError">
          <span v-if="addLoading" class="spinner spinner-sm"></span>
          {{ addMode === 'batch' ? '批量添加' : '确定' }}
        </button>
      </template>
    </Modal>

    <!-- 设置模态框 -->
    <Modal v-model:show="showEditModal" title="订阅设置">
      <div class="add-form" v-if="editingSubscription">
        <div class="form-group">
          <label class="form-label">主播</label>
          <p class="form-static">{{ editingSubscription.anchor_name }}</p>
        </div>

        <div class="form-group">
          <label class="form-label">录制画质</label>
          <select v-model="editForm.quality" class="form-select">
            <option value="原画">原画</option>
            <option value="蓝光">蓝光</option>
            <option value="超清">超清</option>
            <option value="高清">高清</option>
          </select>
        </div>

        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="editForm.monitor_enabled" />
            <span>周期检测</span>
          </label>
          <p class="form-hint">关闭后将暂停检测开播状态，不会自动开始录制</p>
        </div>

        <div class="form-group">
          <label class="form-label">检测间隔 (秒)</label>
          <input 
            v-model.number="editForm.check_interval"
            type="number"
            :class="['form-input', { 'form-input-error': editIntervalError && editIntervalTouched }]"
            :disabled="!editForm.monitor_enabled"
            min="10"
            max="600"
            step="1"
            @blur="editIntervalTouched = true"
          />
          <p :class="editIntervalError && editIntervalTouched ? 'form-error' : 'form-hint'">
            {{ !editForm.monitor_enabled ? '开启周期检测后可设置检测间隔' : (editIntervalError && editIntervalTouched ? editIntervalError : getCheckIntervalHint(editingSubscription?.platform)) }}
          </p>
        </div>

        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="editForm.auto_record" />
            <span>开播自动录制</span>
          </label>
        </div>

        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="editForm.notification_enabled" />
            <span>开播/录制通知</span>
          </label>
        </div>

        <!-- 高级配置分隔线 -->
        <div class="form-divider">
          <span>高级配置</span>
        </div>

        <!-- 分段录制 -->
        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="editForm.split_enabled" />
            <span>分段录制</span>
          </label>
          <p class="form-hint">按时长分割文件，防止意外中断文件损坏。若开启自动转码，结束后将自动合并。</p>
        </div>

        <div class="form-group" v-if="editForm.split_enabled">
          <label class="form-label">分段时长 (分钟)</label>
          <select v-model="editForm.split_duration" class="form-select">
            <option :value="600">10分钟</option>
            <option :value="1800">30分钟</option>
            <option :value="3600">1小时</option>
            <option :value="7200">2小时</option>
            <option :value="14400">4小时</option>
          </select>
        </div>

        <!-- 字幕生成 -->
        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="editForm.generate_subtitle" />
            <span>生成时间戳字幕</span>
          </label>
          <p class="form-hint">录制时自动生成SRT字幕文件,记录实时时间</p>
        </div>

        <div class="form-group" v-if="editingSubscription?.platform === 'douyin' || editingSubscription?.platform === 'bilibili' || editingSubscription?.platform === 'douyu' || editingSubscription?.platform === 'huya' || editingSubscription?.platform === 'twitch'">
          <label class="checkbox-label">
            <input type="checkbox" v-model="editForm.danmu_enabled" />
            <span>录制弹幕（抖音 / B站 / 斗鱼 / 虎牙 / Twitch）</span>
          </label>
          <p class="form-hint">开启后会额外写入 .danmu.jsonl 文件</p>
        </div>

        <!-- 兼容模式 -->
        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="editForm.compat_mode" />
            <span>兼容模式（实时重编码）</span>
          </label>
          <p class="form-hint">应对网络丢包导致的花屏问题。<strong>默认不建议开启</strong>，开启后会显著增加录制后的文件大小（录制容量增加）并增加 CPU 开销。</p>
        </div>

        <!-- 自动转码 -->
        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="editForm.auto_convert_mp4" />
            <span>录制结束自动转码为MP4</span>
          </label>
          <p class="form-hint">录制完成后自动将TS文件转换为MP4格式</p>
        </div>
      </div>

      <template #footer>
        <div style="flex: 1; display: flex; justify-content: flex-start;">
          <button class="btn btn-outline text-danger" @click="confirmDelete(editingSubscription)" :disabled="deleteLoading || editLoading">
            <span v-if="deleteLoading" class="spinner spinner-sm"></span>
            {{ deleteLoading ? '删除中...' : '删除订阅' }}
          </button>
        </div>
        <button class="btn btn-secondary" @click="showEditModal = false">取消</button>
        <button class="btn btn-primary" @click="saveSubscription" :disabled="editLoading || !!editIntervalError">
          <span v-if="editLoading" class="spinner spinner-sm"></span>
          保存
        </button>
      </template>
    </Modal>


    <!-- 录制历史模态框 -->
    <Modal v-model:show="showHistory" :title="historyTitle" width="1380px">
      <div class="history-container">
        <div class="history-toolbar" style="display: flex; justify-content: flex-end; margin-bottom: 12px;">
          <button
            v-if="historyTotal > 0"
            class="btn btn-secondary btn-sm"
            @click="batchConvertHistory"
            :disabled="historyLoading || batchDeleteLoading || batchConvertLoading || pendingConvertCountLoading || pendingConvertCount <= 0"
            style="margin-right: 8px;"
          >
            <span v-if="batchConvertLoading" class="spinner spinner-sm"></span>
            一键转码全部未转码 ({{ pendingConvertCount }})
          </button>
          <button
            v-if="selectedHistoryCount > 0"
            class="btn btn-danger btn-sm"
            @click="openBatchDeleteModal"
            :disabled="historyLoading || batchDeleteLoading"
            style="margin-right: 8px;"
          >
            批量删除 ({{ selectedHistoryCount }})
          </button>
          <button 
            v-if="historyFilterSubId && historyRecords.length > 0"
            class="btn btn-primary btn-sm"
            @click="openTimelinePlayer"
            style="margin-right: 8px;"
          >
            无缝时间轴回放
          </button>
          <button 
            v-if="historyRecords.length > 0"
            class="btn btn-outline text-danger btn-sm" 
            @click="clearHistory"
          >
            一键清空历史
          </button>
        </div>

        <div v-if="historyLoading && historyRecords.length === 0" class="loading-container">
          <span class="spinner"></span>
        </div>
        
        <div v-else-if="historyRecords.length === 0" class="empty-state">
          <p>暂无录制记录</p>
        </div>

        <div v-else class="history-content">
          <div v-if="historyLoading" class="history-loading-overlay">
            <span class="spinner spinner-sm"></span>
            <span>加载中...</span>
          </div>
          <!-- 电脑端表格 -->
          <div class="history-desktop">
            <table class="history-table">
              <thead>
                <tr>
                  <th style="width: 44px; text-align: center;">
                    <input
                      type="checkbox"
                      :checked="isAllHistorySelectedOnPage"
                      :disabled="selectableHistoryCountOnPage === 0"
                      @change="toggleSelectAllHistoryOnPage"
                    />
                  </th>
                  <th>主播</th>
                  <th>开始时间</th>
                  <th>时长</th>
                  <th>大小</th>
                  <th>状态</th>
                  <th>操作</th>
                  <th>备注</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="record in historyCardItems" :key="record.id">
                  <td style="text-align: center;">
                    <input
                      type="checkbox"
                      :checked="isHistorySelected(record.id)"
                      :disabled="record.status === 'recording'"
                      @change="toggleHistorySelection(record)"
                    />
                  </td>
                  <td>
                    <div
                      class="history-anchor-cell"
                      :class="{
                        'history-anchor-clickable': isRecordOwnerHistoryClickable(record),
                        'is-jumping': jumpAnimatingRecordId === String(record.id)
                      }"
                      :role="isRecordOwnerHistoryClickable(record) ? 'button' : undefined"
                      :tabindex="isRecordOwnerHistoryClickable(record) ? 0 : -1"
                      :aria-disabled="isRecordOwnerHistoryClickable(record) ? 'false' : 'true'"
                      @click="handleRecordOwnerHistoryClick(record)"
                      @keydown.enter.prevent="handleRecordOwnerHistoryClick(record)"
                      @keydown.space.prevent="handleRecordOwnerHistoryClick(record)"
                      :title="isRecordOwnerHistoryClickable(record) ? '查看该主播全部录制历史' : '当前已在该主播历史'"
                    >
                      <img v-if="record.avatar_url" :src="record.avatar_url" class="history-avatar" referrerpolicy="no-referrer" />
                      <div v-else class="history-avatar-placeholder">{{ (record.anchor_name || '未')[0] }}</div>
                      <span class="history-anchor-name" :title="record.anchor_name">{{ record._anchorName }}</span>
                    </div>
                  </td>
                  <td>{{ record._date }}</td>
                  <td>{{ record._duration }}</td>
                  <td>{{ record._size }}</td>
                  <td>
                    <div style="display: flex; align-items: center; gap: 4px;">
                      <span class="status-badge" :class="'status-' + record.status">
                        {{ record._statusText }}
                      </span>
                      <span v-if="record.converted === 'true'" class="badge badge-info">
                        已转码
                      </span>
                    </div>
                  </td>
                  <td class="actions-cell">
                    <!-- 转码按钮 -->
                    <button 
                      v-if="record.status === 'converting'"
                      class="btn btn-secondary btn-xs"
                      disabled
                    >
                      <span class="spinner spinner-xs"></span>
                      转码中...
                    </button>
                    <button 
                      v-else-if="record.converted === 'true'"
                      class="btn btn-secondary btn-xs"
                      disabled
                      style="opacity: 0.5; cursor: not-allowed;"
                    >
                      转码
                    </button>
                    <button 
                      v-else-if="['completed', 'stopped', 'failed'].includes(record.status) && record.file_path?.endsWith('.ts')"
                      class="btn btn-secondary btn-xs"
                      @click="convertRecord(record)"
                    >
                      转码
                    </button>
    
                    <!-- Play Button -->
                    <button 
                      class="btn btn-success btn-xs"
                      @click="playRecord(record)"
                      :disabled="!record.file_path && !record.converted_path"
                    >
                      播放
                    </button>
                    <button
                      v-if="['completed', 'stopped', 'failed'].includes(record.status) && record._fileUrl"
                      class="btn btn-primary btn-xs"
                      @click="downloadRecord(record)"
                      :disabled="!record._fileUrl"
                    >
                      下载
                    </button>
                    <button 
                      class="btn btn-outline text-danger btn-xs"
                      @click="deleteRecord(record)"
                      :disabled="record.status === 'recording'"
                    >
                      删除
                    </button>
                  </td>
                  <td>
                    <div class="remark-cell">
                      <span class="remark-text" :title="record._remark" :class="{ 'text-danger': !record.remark && record.error_message }">
                        {{ record._remark }}
                      </span>
                      <button class="btn btn-outline btn-xs" @click="openRemarkEditor(record)">备注</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 移动端列表 -->
          <div class="history-mobile">
            <div v-for="record in historyCardItems" :key="record.id" class="history-card">
              <div class="h-card-header">
                <div class="h-card-anchor">
                  <input
                    type="checkbox"
                    class="h-select-checkbox"
                    :checked="isHistorySelected(record.id)"
                    :disabled="record.status === 'recording'"
                    @change="toggleHistorySelection(record)"
                  />
                  <div
                    class="h-card-anchor-main"
                    :class="{
                      'h-anchor-clickable': isRecordOwnerHistoryClickable(record),
                      'is-jumping': jumpAnimatingRecordId === String(record.id)
                    }"
                    :role="isRecordOwnerHistoryClickable(record) ? 'button' : undefined"
                    :tabindex="isRecordOwnerHistoryClickable(record) ? 0 : -1"
                    :aria-disabled="isRecordOwnerHistoryClickable(record) ? 'false' : 'true'"
                    @click="handleRecordOwnerHistoryClick(record)"
                    @keydown.enter.prevent="handleRecordOwnerHistoryClick(record)"
                    @keydown.space.prevent="handleRecordOwnerHistoryClick(record)"
                    :title="isRecordOwnerHistoryClickable(record) ? '查看该主播全部录制历史' : '当前已在该主播历史'"
                  >
                    <img v-if="record.avatar_url" :src="record.avatar_url" class="h-card-avatar" referrerpolicy="no-referrer" />
                    <div v-else class="h-card-avatar-placeholder">{{ (record.anchor_name || '未')[0] }}</div>
                    <span class="h-card-name" :title="record.anchor_name">{{ record._anchorName }}</span>
                  </div>
                </div>
                <span class="status-badge" :class="'status-' + record.status">
                  {{ record._statusText }}
                </span>
              </div>
              <div class="h-card-body">
                <div class="h-info-row">
                  <span class="h-label">时间:</span>
                  <span class="h-value">{{ record._date }}</span>
                </div>
                <div class="h-info-row">
                  <span class="h-label">时长/大小:</span>
                  <span class="h-value">{{ record._duration }} / {{ record._size }}</span>
                </div>
                <div class="h-info-row">
                  <span class="h-label">备注:</span>
                  <span class="h-value h-value-remark" :title="record._remark" :class="{ 'text-danger': !record.remark && record.error_message }">{{ record._remark }}</span>
                </div>
              </div>
              <div class="h-card-footer">
                <span v-if="record.converted === 'true'" class="badge badge-info">已转码</span>
                <div class="h-card-actions">
                  <button
                    v-if="record.status === 'converting'"
                    class="btn btn-secondary btn-xs"
                    disabled
                  >
                    转码中...
                  </button>
                  <button
                    v-else-if="record.converted !== 'true' && ['completed', 'stopped', 'failed'].includes(record.status) && record.file_path?.endsWith('.ts')"
                    class="btn btn-secondary btn-xs"
                    @click="convertRecord(record)"
                  >
                    转码
                  </button>
                  <button
                    class="btn btn-success btn-xs"
                    @click="playRecord(record)"
                    :disabled="!record.file_path && !record.converted_path"
                  >
                    播放
                  </button>
                  <button class="btn btn-outline btn-xs" @click="openRemarkEditor(record)">备注</button>
                  <button
                    v-if="['completed', 'stopped', 'failed'].includes(record.status) && record._fileUrl"
                    class="btn btn-primary btn-xs"
                    @click="downloadRecord(record)"
                    :disabled="!record._fileUrl"
                  >
                    下载
                  </button>
                  <button 
                    class="btn btn-outline text-danger btn-xs"
                    @click="deleteRecord(record)"
                    :disabled="record.status === 'recording'"
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 分页 -->
        <div v-if="historyTotal > historyPageSize" class="pagination">
          <button 
            class="btn btn-outline btn-sm"
            :disabled="historyLoading || historyPage <= 1"
            @click="loadHistory(historyPage - 1)"
          >
            上一页
          </button>
          <span class="page-info">{{ historyPage }} / {{ Math.ceil(historyTotal / historyPageSize) }}</span>
          <button 
            class="btn btn-outline btn-sm"
            :disabled="historyLoading || historyPage >= Math.ceil(historyTotal / historyPageSize)"
            @click="loadHistory(historyPage + 1)"
          >
            下一页
          </button>
          <div class="pagination-jump">
            <span class="jump-label">跳转</span>
            <input
              v-model="historyJumpPage"
              type="number"
              min="1"
              :max="totalHistoryPages"
              class="form-input jump-input"
              :disabled="historyLoading"
              @keyup.enter="goToHistoryPage"
            />
            <button class="btn btn-outline btn-sm" :disabled="historyLoading" @click="goToHistoryPage">GO</button>
          </div>
        </div>
      </div>
    </Modal>

    <!-- 直播订阅备份/提示模态框（样式参考视频订阅页面） -->
    <Modal v-model:show="showTipModal" :title="tipTitle" :type="tipType">
      <div v-html="tipMessage"></div>
      <template #footer v-if="tipType === 'confirm'">
        <button class="btn btn-secondary" @click="handleTipCancel">取消</button>
        <button class="btn btn-primary" @click="handleTipConfirm">确定</button>
      </template>
    </Modal>

    <!-- 视频播放模态框 -->
    <Modal
      v-model:show="showPlayerModal"
      :title="''"
      :width="playerModalWidth"
      :container-height="playerModalHeight"
      @close="closePlayer"
      class="player-modal player-modal--fullscreen player-modal-light"
      :body-fill="true"
      :hide-close="true"
      persistent
    >
      <div
        class="player-layout player-fullscreen-root"
        ref="playerFullscreenRef"
        @mousemove="handlePlayerEdgeMove"
        @mouseleave="handlePlayerEdgeLeave"
      >
        <!-- 主播放区域 -->
        <div class="player-main">
          <div class="player-container" :class="{ 'triple-screen-active': showLiveTripleScreen && isLiveVerticalVideo }" ref="playerContainerRef">
            <canvas 
              v-show="showLiveTripleScreen && isLiveVerticalVideo" 
              ref="liveCanvasLeftRef" 
              class="live-triple-mirror left"
            ></canvas>
            <video 
              ref="videoPlayer" 
              :controls="videoControlsEnabled"
              autoplay 
              class="live-player"
              @loadedmetadata="onVideoMetadata"
              @dblclick.prevent="toggleLiveFullscreen"
              @play="startLiveTripleScreenLoop"
              @playing="startLiveTripleScreenLoop"
              @pause="stopLiveTripleScreenLoop"
              @ended="stopLiveTripleScreenLoop"
              controlsList="nofullscreen"
              disablepictureinpicture
            ></video>
            <canvas 
              v-show="showLiveTripleScreen && isLiveVerticalVideo" 
              ref="liveCanvasRightRef" 
              class="live-triple-mirror right"
            ></canvas>
            <div v-if="!liveDanmuUnsupported && liveDanmuMode === 'marquee' && liveMarqueeItems.length" class="live-danmu-layer danmu-marquee-layer">
              <div
                v-for="item in liveMarqueeItems"
                :key="item.id"
                class="danmu-marquee-item"
                :style="item.style"
              >
                <span class="danmu-text">{{ item.text }}</span>
              </div>
            </div>
            <div v-if="!liveDanmuUnsupported && liveDanmuMode === 'list' && isMobileViewport" class="live-danmu-panel danmu-list-panel">
              <button v-if="liveDanmuListUserHold" class="danmu-list-jump" type="button" @click="jumpLiveDanmuListToLatest">
                最新
              </button>
              <div
                class="danmu-list"
                ref="liveDanmuListRef"
                @scroll="handleLiveDanmuListScroll"
                @wheel.stop
                @touchmove.stop
              >
                <div v-for="item in liveDanmuListItems" :key="item._id" class="danmu-list-item">
                  <span class="danmu-text">{{ formatLiveDanmuLine(item) }}</span>
                </div>
                <div v-if="!liveDanmuListItems.length" class="danmu-list-empty">暂无弹幕</div>
              </div>
            </div>
            <div v-if="playerLoading" class="player-loading">
              <span class="spinner"></span>
              <span>加载直播流...</span>
            </div>
            <div v-if="playerError" class="player-error">
              <Icon name="alert-triangle" :size="24" />
              <p>{{ playerError }}</p>
              <button class="btn btn-primary btn-sm" @click="retryPlay">重试</button>
            </div>
          </div>
        </div>

        <!-- 纵向弹幕列：位于播放区与右侧列表之间 -->
        <div v-if="!liveDanmuUnsupported && liveDanmuMode === 'list' && !isMobileViewport" class="player-danmu-column">
          <div class="live-danmu-panel live-danmu-panel--column">
            <button v-if="liveDanmuListUserHold" class="danmu-list-jump" type="button" @click="jumpLiveDanmuListToLatest">
              最新
            </button>
            <div
              class="danmu-list"
              ref="liveDanmuListRef"
              @scroll="handleLiveDanmuListScroll"
              @wheel.stop
              @touchmove.stop
            >
              <div v-for="item in liveDanmuListItems" :key="item._id" class="danmu-list-item">
                <span class="danmu-text">{{ formatLiveDanmuLine(item) }}</span>
              </div>
              <div v-if="!liveDanmuListItems.length" class="danmu-list-empty">暂无弹幕</div>
            </div>
          </div>
        </div>

        <!-- 侧边切换列表 -->
        <div
          class="player-sidebar"
          v-if="liveSubList.length > 0 && (!isPlayerFullscreen || !isMobileViewport)"
          :class="{ 'is-hidden': isPlayerFullscreen && !isMobileViewport && !sidebarHoverVisible }"
          @mouseenter="showSidebarHover"
          @mouseleave="scheduleHideSidebar"
        >
          <div class="sidebar-header">
            <span class="live-status-dot"></span>
            <span>正在直播 ({{ liveSubList.length }})</span>
          </div>
          <div class="sidebar-list">
            <div 
              v-for="sub in liveSubList" 
              :key="sub.id"
              class="sidebar-item"
              :class="{ 'active': currentPlayerSub?.id === sub.id }"
              @click="handleSwitchStream(sub)"
            >
              <div class="item-avatar">
                <div class="playing-ring" v-if="currentPlayerSub?.id === sub.id"></div>
                <img v-if="sub.avatar_url" :src="sub.avatar_url" referrerpolicy="no-referrer" />
                <div v-else class="avatar-placeholder">{{ (sub.anchor_name || '未')[0] }}</div>
                <div class="playing-badge" v-if="currentPlayerSub?.id === sub.id">播放中</div>
              </div>
              <div class="item-info">
                <div class="item-name">{{ sub._anchorName }}</div>
                <div class="item-meta">
                  <span class="p-tag" :class="`tag-${sub.platform}`">{{ sub._platformName.replace('直播', '') }}</span>
                  <span class="q-tag">{{ sub.quality }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <div class="player-footer-bar">
          <div class="player-footer-controls">
            <button class="btn btn-primary live-fullscreen-btn player-action-btn player-action-btn-icon" @click="toggleLiveFullscreen" :title="isPlayerFullscreen ? '退出全屏' : '全屏播放'">
              <Icon :name="isPlayerFullscreen ? 'minimize' : 'maximize'" :size="14" />
            </button>
            <button
              v-if="!liveDanmuUnsupported"
              class="btn btn-primary danmu-btn player-action-btn player-action-btn-text"
              @click="toggleLiveDanmuMode"
              :title="liveDanmuModeLabel"
            >
              {{ liveDanmuStatusText }}
            </button>
            <button
              v-if="isLiveVerticalVideo"
              class="btn btn-primary triple-screen-btn player-action-btn player-action-btn-text"
              :class="{ active: showLiveTripleScreen }"
              @click="toggleLiveTripleScreen"
              title="三连屏预览"
            >
              三连屏：{{ showLiveTripleScreen ? '开' : '关' }}
            </button>
            <button class="btn btn-primary player-action-btn player-action-btn-confirm" @click="closePlayer">关闭</button>
          </div>
        </div>
      </template>
    </Modal>

    <!-- 删除确认专用模态框 -->
    <Modal v-model:show="showDeleteConfirmModal" title="确认删除" width="500px">
      <div v-if="recordToDelete" class="delete-confirm-content">
        <div class="confirm-message">
          确定要删除 <strong>{{ recordToDelete.anchor_name }}</strong> 的这条录制记录吗？
        </div>
        <div class="record-info-preview">
          <p>时间: {{ formatDate(recordToDelete.start_time) }}</p>
          <p>文件: {{ recordToDelete.file_name || '未知' }}</p>
        </div>
        
        <div class="delete-options-box">
          <label class="checkbox-label-modern dangerous-check">
            <input type="checkbox" v-model="deleteFileChecked" class="checkbox-modern" />
            <span class="checkbox-custom"></span>
            <div class="checkbox-text">
              <span class="checkbox-title">彻底删除录像文件</span>
              <span class="checkbox-desc text-danger">同时物理删除磁盘上的 TS/MP4/SRT/弹幕JSONL 及分段文件，无法恢复！</span>
            </div>
          </label>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showDeleteConfirmModal = false">取消</button>
        <button class="btn btn-danger" @click="executeDelete" :disabled="deleteLoading">
          <span v-if="deleteLoading" class="spinner spinner-sm"></span>
          确定删除
        </button>
      </template>
    </Modal>

    <!-- 清空历史确认模态框 -->
    <Modal v-model:show="showClearAllModal" :title="historyFilterSubId ? '确认清空主播历史' : '确认清空所有历史'" width="500px">
      <div class="delete-confirm-content">
        <div class="confirm-message">
          确定要清空 <strong class="text-danger">{{ historyFilterSubId ? historyFilterAnchorName + ' 的' : '所有' }}</strong> 录制历史记录吗？
        </div>
        <div class="record-info-preview error-bg" style="background: rgba(239, 68, 68, 0.05); border-color: rgba(239, 68, 68, 0.2);">
          <p class="text-danger" style="font-weight: 600;">⚠️ 此操作不可撤销！</p>
          <p>当前{{ historyFilterSubId ? '该主播' : '' }}记录总数: {{ historyTotal }} 条</p>
          <p v-if="historyRecordingCount > 0" class="text-success" style="margin-top: 4px; font-weight: 500;">
            <i class="icon-recording" style="display: inline-block; width: 8px; height: 8px; background: #22c55e; border-radius: 50%; margin-right: 4px;"></i>
            其中 {{ historyRecordingCount }} 条正在录制中（将保留）
          </p>
        </div>
        
        <div class="delete-options-box">
          <label class="checkbox-label-modern dangerous-check">
            <input type="checkbox" v-model="clearAllFileChecked" class="checkbox-modern" />
            <span class="checkbox-custom"></span>
            <div class="checkbox-text">
              <span class="checkbox-title">同时删除{{ historyFilterSubId ? '该主播的' : '所有' }}录像文件</span>
              <span class="checkbox-desc text-danger">物理删除磁盘上相关的 TS/MP4/SRT/弹幕JSONL 及分段文件</span>
            </div>
          </label>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showClearAllModal = false">取消</button>
        <button class="btn btn-danger" @click="executeClearAll" :disabled="clearAllLoading">
          <span v-if="clearAllLoading" class="spinner spinner-sm"></span>
          确认清空
        </button>
      </template>
    </Modal>

    <Modal v-model:show="showBatchDeleteModal" title="确认批量删除" width="500px">
      <div class="delete-confirm-content">
        <div class="confirm-message">
          确定要删除已选中的 <strong class="text-danger">{{ selectedHistoryCount }}</strong> 条录制记录吗？
        </div>

        <div class="delete-options-box">
          <label class="checkbox-label-modern dangerous-check">
            <input type="checkbox" v-model="batchDeleteFileChecked" class="checkbox-modern" />
            <span class="checkbox-custom"></span>
            <div class="checkbox-text">
              <span class="checkbox-title">同时删除录像文件</span>
              <span class="checkbox-desc text-danger">物理删除磁盘上相关的 TS/MP4/SRT/弹幕JSONL 及分段文件</span>
            </div>
          </label>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showBatchDeleteModal = false">取消</button>
        <button class="btn btn-danger" @click="executeBatchDelete" :disabled="batchDeleteLoading || selectedHistoryCount === 0">
          <span v-if="batchDeleteLoading" class="spinner spinner-sm"></span>
          确定删除
        </button>
      </template>
    </Modal>

    <Modal v-model:show="showRemarkModal" title="编辑备注" width="520px" @close="resetRemarkEditor">
      <div class="add-form">
        <div class="form-group">
          <label class="form-label">备注内容</label>
          <textarea
            v-model="remarkForm"
            class="form-input remark-textarea"
            maxlength="500"
            rows="4"
            placeholder="请输入备注（最多500字）"
          ></textarea>
          <p class="form-hint">{{ (remarkForm || '').length }}/500</p>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showRemarkModal = false">取消</button>
        <button class="btn btn-primary" @click="saveRemark" :disabled="remarkLoading">
          <span v-if="remarkLoading" class="spinner spinner-sm"></span>
          保存
        </button>
      </template>
    </Modal>

    <!-- 批量修改画质模态框 -->
    <Modal v-model:show="showBulkQualityModal" title="批量修改画质" width="400px">
      <div class="add-form">
        <div class="form-group">
          <label class="form-label">选择目标画质</label>
          <select v-model="bulkQualityTarget" class="form-select">
            <option value="原画">原画</option>
            <option value="蓝光">蓝光</option>
            <option value="超清">超清</option>
            <option value="高清">高清</option>
          </select>
          <p class="form-hint">将对当前筛选出的 {{ filteredSubscriptions.length }} 个订阅生效</p>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showBulkQualityModal = false">取消</button>
        <button class="btn btn-primary" @click="bulkSetQuality" :disabled="bulkLoading">
          <span v-if="bulkLoading" class="spinner spinner-sm"></span>
          确定修改
        </button>
      </template>
    </Modal>

    <!-- 批量录制开关二级操作 -->
    <Modal v-model:show="showBulkAutoRecordModal" title="批量录制开关" width="420px">
      <div class="bulk-toggle-content">
        <p class="bulk-toggle-desc">对当前筛选出的 {{ filteredSubscriptions.length }} 个直播间执行操作：</p>
        <div class="bulk-toggle-actions">
          <button class="btn btn-outline-success" @click="handleBulkAutoRecordChoice(true)" :disabled="bulkLoading">一键开启录制</button>
          <button class="btn btn-outline-danger" @click="handleBulkAutoRecordChoice(false)" :disabled="bulkLoading">一键关闭录制</button>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showBulkAutoRecordModal = false">取消</button>
      </template>
    </Modal>

    <!-- 批量检测开关二级操作 -->
    <Modal v-model:show="showBulkMonitorModal" title="批量检测开关" width="420px">
      <div class="bulk-toggle-content">
        <p class="bulk-toggle-desc">对当前筛选出的 {{ filteredSubscriptions.length }} 个直播间执行周期检测设置：</p>
        <div class="bulk-toggle-actions">
          <button class="btn btn-outline-success" @click="handleBulkMonitorChoice(true)" :disabled="bulkLoading">开启周期检测</button>
          <button class="btn btn-outline-danger" @click="handleBulkMonitorChoice(false)" :disabled="bulkLoading">暂停周期检测</button>
        </div>
        <p class="form-hint">暂停周期检测只停止后续开播状态轮询，不会停止当前正在录制的任务。</p>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showBulkMonitorModal = false">取消</button>
      </template>
    </Modal>

    <!-- 批量通知开关二级操作 -->
    <Modal v-model:show="showBulkNotificationModal" title="批量通知开关" width="420px">
      <div class="bulk-toggle-content">
        <p class="bulk-toggle-desc">对当前筛选出的 {{ filteredSubscriptions.length }} 个直播间执行通知设置：</p>
        <div class="bulk-toggle-actions">
          <button class="btn btn-outline-success" @click="handleBulkNotificationChoice(true)" :disabled="bulkLoading">开启开播录制通知</button>
          <button class="btn btn-outline-danger" @click="handleBulkNotificationChoice(false)" :disabled="bulkLoading">关闭开播录制通知</button>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showBulkNotificationModal = false">取消</button>
      </template>
    </Modal>

    <!-- 批量字幕开关二级操作 -->
    <Modal v-model:show="showBulkSubtitleModal" title="批量字幕开关" width="420px">
      <div class="bulk-toggle-content">
        <p class="bulk-toggle-desc">对当前筛选出的 {{ filteredSubscriptions.length }} 个直播间执行字幕设置：</p>
        <div class="bulk-toggle-actions">
          <button class="btn btn-outline-success" @click="handleBulkSubtitleChoice(true)" :disabled="bulkLoading">开启时间戳字幕</button>
          <button class="btn btn-outline-danger" @click="handleBulkSubtitleChoice(false)" :disabled="bulkLoading">关闭时间戳字幕</button>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showBulkSubtitleModal = false">取消</button>
      </template>
    </Modal>

    <!-- 批量转码开关二级操作 -->
    <Modal v-model:show="showBulkConvertModal" title="批量转码开关" width="420px">
      <div class="bulk-toggle-content">
        <p class="bulk-toggle-desc">对当前筛选出的 {{ filteredSubscriptions.length }} 个直播间执行转码设置：</p>
        <div class="bulk-toggle-actions">
          <button class="btn btn-outline-success" @click="handleBulkConvertChoice(true)" :disabled="bulkLoading">开启自动转码</button>
          <button class="btn btn-outline-danger" @click="handleBulkConvertChoice(false)" :disabled="bulkLoading">关闭自动转码</button>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showBulkConvertModal = false">取消</button>
      </template>
    </Modal>

    <!-- 批量分段录制设置 -->
    <Modal v-model:show="showBulkSegmentModal" title="批量分段录制" width="440px">
      <div class="bulk-toggle-content">
        <p class="bulk-toggle-desc">对当前筛选出的 {{ filteredSubscriptions.length }} 个直播间执行分段录制设置：</p>
        <div class="bulk-toggle-actions">
          <button class="btn btn-outline-success" @click="handleBulkSegmentChoice(true)" :disabled="bulkLoading">开启分段录制</button>
          <button class="btn btn-outline-danger" @click="handleBulkSegmentChoice(false)" :disabled="bulkLoading">关闭分段录制</button>
        </div>
        <div class="form-group" style="margin-top: 2px;">
          <label class="form-label">分段时长（分钟）</label>
          <select v-model.number="bulkSegmentDuration" class="form-select">
            <option :value="1800">30 分钟</option>
            <option :value="3600">60 分钟</option>
            <option :value="5400">90 分钟</option>
            <option :value="7200">120 分钟</option>
          </select>
          <p class="form-hint">仅在“开启分段录制”时生效</p>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showBulkSegmentModal = false">取消</button>
      </template>
    </Modal>
    
    <!-- 移动端更多操作模态框 -->
    <Modal v-model:show="showToolsModal" title="更多工具" width="450px">
      <div class="tools-modal-content">
        <!-- 批量操作 -->
        <div class="tool-section" v-if="filteredSubscriptions.length > 0">
          <h4 class="tool-section-title">批量操作 (针对当前筛选)</h4>
          <div class="tool-grid">
            <button class="btn btn-outline" @click="showBulkAutoRecordModal = true; showToolsModal = false" :disabled="bulkLoading">录制开关</button>
            <button class="btn btn-outline" @click="showBulkMonitorModal = true; showToolsModal = false" :disabled="bulkLoading">检测开关</button>
            <button class="btn btn-outline" @click="showBulkNotificationModal = true; showToolsModal = false" :disabled="bulkLoading">通知开关</button>
            <button class="btn btn-outline" @click="showBulkSubtitleModal = true; showToolsModal = false" :disabled="bulkLoading">字幕开关</button>
            <button class="btn btn-outline" @click="showBulkConvertModal = true; showToolsModal = false" :disabled="bulkLoading">转码开关</button>
            <button class="btn btn-outline" @click="showBulkSegmentModal = true; showToolsModal = false" :disabled="bulkLoading">分段录制</button>
            <button class="btn btn-outline" @click="showBulkQualityModal = true; showToolsModal = false" :disabled="bulkLoading">批量修改画质</button>
            <button class="btn btn-danger" @click="confirmBulkDelete(); showToolsModal = false" :disabled="bulkLoading">批量删除订阅</button>
          </div>
        </div>

        <!-- 备份与历史 -->
        <div class="tool-section">
          <h4 class="tool-section-title">数据管理</h4>
          <div class="tool-grid">
            <button class="btn btn-outline" @click="openGlobalHistory(); showToolsModal = false">
              <Icon name="history" :size="16" /> 查看全局历史
            </button>
            <button class="btn btn-outline" @click="exportLiveConfig(); showToolsModal = false" :disabled="subscriptions.length === 0">
              <Icon name="download" :size="16" /> 导出订阅配置
            </button>
            <button class="btn btn-outline" @click="triggerLiveImport(); showToolsModal = false">
              <Icon name="upload" :size="16" /> 导入订阅配置
            </button>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-secondary btn-block" @click="showToolsModal = false">关闭</button>
      </template>
    </Modal>
    </template>

    </div>
  </div>

  <!-- 现代简约滚动导航 -->
  <div class="modern-scroll-nav">
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

  <!-- 批量操作全屏处理中提示 -->
  <transition name="fade">
    <div v-if="bulkLoading" class="bulk-operation-overlay" role="status" aria-live="polite">
      <div class="bulk-operation-card">
        <span class="spinner bulk-spinner"></span>
        <h3>{{ bulkLoadingTitle }}</h3>
        <p>{{ bulkLoadingText }}</p>
        <p v-if="bulkLoadingHint" class="hint">{{ bulkLoadingHint }}</p>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref, onMounted, onUnmounted, onActivated, onDeactivated, computed, watch, nextTick } from 'vue'
import SkeletonLoader from '@/components/common/SkeletonLoader.vue'
import { useRoute, useRouter } from 'vue-router'
import Modal from '@/components/common/Modal.vue'
import Icon from '@/components/common/Icon.vue'
import liveApi from '@/api/live'
import { licenseApi } from '@/api/index'
import { useSystemStore } from '@/stores/system'
import { useDialog } from '@/composables/useDialog'
import { useToast } from '@/composables/useToast'
import { buildAuthedWsUrl } from '@/utils/wsAuth'
import { formatBytes } from '@/utils/dashboard'
import mpegts from 'mpegts.js'
import Hls from 'hls.js'

const systemStore = useSystemStore()
const route = useRoute()
const router = useRouter()
const isLiveRecordRouteActive = computed(() => route.path === '/live-record')

const dialog = useDialog()
const toast = useToast()


// 授权状态
const cachedLicense = localStorage.getItem('license_status')
const licenseValid = ref(cachedLicense === 'true')
const checkingLicense = ref(cachedLicense === null)

async function checkLicense(force = false) {
    if (cachedLicense === null) {
        checkingLicense.value = true
    }
    
    try {
        if (force) {
            try {
                await licenseApi.refresh()
            } catch (e) {
                console.warn('刷新授权失败，将使用缓存状态', e)
            }
        }
        
        const res = await licenseApi.getStatus()
        licenseValid.value = res.is_licensed
        localStorage.setItem('license_status', res.is_licensed)
        
        if (force && res.is_licensed) {
             toast.success('授权状态已刷新')
        }
    } catch (e) {
        if (cachedLicense === null) {
             licenseValid.value = false
        }
        console.error('License check failed:', e)
    } finally {
        checkingLicense.value = false
        // 如果授权通过，继续加载数据
        if (licenseValid.value) {
            loadData()
            initWebSocket()
        }
    }
}

// 状态
const loading = ref(true)
const subscriptions = ref([])
const stats = ref({})
const timelineAvailabilityMap = ref({})
const storageSizeDisplay = computed(() => {
  const [value = '0', unit = 'B'] = formatSize(stats.value.total_size || 0).split(' ')
  return { value, unit }
})
const actionLoading = ref({})
const bulkLoading = ref(false)
const bulkLoadingTitle = ref('正在处理批量操作')
const bulkLoadingText = ref('正在提交请求，请稍候...')
const bulkLoadingHint = ref('')
let bulkLoadingHintTimer = null
const liveImportInput = ref(null)
const searchKeyword = ref('')
const debouncedSearchKeyword = ref('')
const showToolsModal = ref(false)
const showBulkAutoRecordModal = ref(false)
const showBulkMonitorModal = ref(false)
const showBulkNotificationModal = ref(false)
const showBulkSubtitleModal = ref(false)
const showBulkConvertModal = ref(false)
const showBulkSegmentModal = ref(false)
const bulkSegmentDuration = ref(3600)
const showScrollTop = ref(false)
const showScrollBottom = ref(true)
let liveStatsRefreshTimer = null
let liveStatsRefreshInFlight = false
let liveStatsRefreshQueued = false
let searchDebounceTimer = null

// 直播订阅备份提示模态（参考视频订阅页面）
const showTipModal = ref(false)
const tipTitle = ref('')
const tipMessage = ref('')
const tipType = ref('info') // info / success / warning / error / confirm
let tipResolve = null

// 筛选状态
// 筛选状态 (从本地存储恢复或默认 'all')
const filterPlatform = ref(localStorage.getItem('live_record_filter_platform') || 'all')
const filterStatus = ref(localStorage.getItem('live_record_filter_status') || 'all')
const sortBy = ref(localStorage.getItem('live_record_sort_by') || 'status')

// 监听筛选状态变化并保存
watch(filterPlatform, (val) => {
  localStorage.setItem('live_record_filter_platform', val)
})
watch(filterStatus, (val) => {
  localStorage.setItem('live_record_filter_status', val)
})
watch(sortBy, (val) => {
  localStorage.setItem('live_record_sort_by', val)
})

function saveSortPreference() {
  localStorage.setItem('live_record_sort_by', sortBy.value)
}
watch(searchKeyword, (val) => {
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }
  searchDebounceTimer = setTimeout(() => {
    debouncedSearchKeyword.value = val
    searchDebounceTimer = null
  }, 180)
})

const filteredSubscriptions = computed(() => {
  const filtered = subscriptions.value.filter(sub => {
    // 平台筛选
    const platformMatch = filterPlatform.value === 'all' || sub.platform === filterPlatform.value
    
    // 状态筛选
    let statusMatch = true
    if (filterStatus.value === 'live') {
      statusMatch = sub.is_live === 'true'
    } else if (filterStatus.value === 'recording') {
      statusMatch = sub.is_recording === 'true'
    } else if (filterStatus.value === 'paused') {
      statusMatch = sub.monitor_enabled === 'false'
    } else if (filterStatus.value === 'offline') {
      statusMatch = sub.is_live !== 'true' && sub.is_recording !== 'true' && sub.monitor_enabled !== 'false'
    }

    // 关键字筛选
    const kw = debouncedSearchKeyword.value.trim().toLowerCase()
    const keywordMatch = !kw || (sub.anchor_name || '').toLowerCase().includes(kw)
    
    return platformMatch && statusMatch && keywordMatch
  })

  const getPriority = (sub) => {
    if (sub.is_recording === 'true') return 3
    if (sub.is_live === 'true') return 2
    return 1
  }

  const getCreatedAtTs = (sub) => {
    const ts = Date.parse(sub.created_at || '')
    return Number.isFinite(ts) ? ts : 0
  }

  // 排序：根据用户选择的策略进行多维度排序，并使用 ID 进行最终稳定性兜底
  return filtered.sort((a, b) => {
    if (sortBy.value === 'status') {
      const priorityDiff = getPriority(b) - getPriority(a)
      if (priorityDiff !== 0) return priorityDiff

      const createdAtDiff = getCreatedAtTs(b) - getCreatedAtTs(a)
      if (createdAtDiff !== 0) return createdAtDiff
    } else if (sortBy.value === 'newest') {
      const createdAtDiff = getCreatedAtTs(b) - getCreatedAtTs(a)
      if (createdAtDiff !== 0) return createdAtDiff
    } else if (sortBy.value === 'oldest') {
      const createdAtDiff = getCreatedAtTs(a) - getCreatedAtTs(b)
      if (createdAtDiff !== 0) return createdAtDiff
    } else if (sortBy.value === 'name') {
      const nameA = String(a.anchor_name || '')
      const nameB = String(b.anchor_name || '')
      const nameDiff = nameA.localeCompare(nameB, 'zh-CN')
      if (nameDiff !== 0) return nameDiff
    }

    return String(a.id || '').localeCompare(String(b.id || ''))
  })
})

// 订阅卡片数据（预计算展示字段，避免模板中反复调用函数）
const subscriptionCards = computed(() => {
  return filteredSubscriptions.value.map(sub => ({
    ...sub,
    _platformName: getPlatformName(sub.platform),
    _anchorName: sanitizeAnchorName(sub.anchor_name),
    _duration: sub.recording_status?.duration != null ? formatDuration(sub.recording_status.duration) : '',
    _fileSize: sub.recording_status?.file_size != null ? formatSize(sub.recording_status.file_size) : '',
  }))
})

// 正在直播的订阅列表 (用于播放器侧边栏切换)
const liveSubList = computed(() => {
  return subscriptions.value
    .filter(sub => sub.is_live === 'true')
    .map(sub => ({
      ...sub,
      _anchorName: sanitizeAnchorName(sub.anchor_name),
      _platformName: getPlatformName(sub.platform),
    }))
})

// 添加表单
const MIN_CHECK_INTERVAL_SECONDS = 10
const MAX_CHECK_INTERVAL_SECONDS = 600
const addIntervalTouched = ref(false)
const editIntervalTouched = ref(false)

function getCheckIntervalError(value) {
  if (value === '' || value === null || value === undefined) {
    return '请输入检测间隔'
  }
  const interval = Number(value)
  if (!Number.isFinite(interval)) {
    return '检测间隔必须是数字'
  }
  if (!Number.isInteger(interval)) {
    return '检测间隔必须为整数秒'
  }
  if (interval < MIN_CHECK_INTERVAL_SECONDS) {
    return `检测间隔不能小于 ${MIN_CHECK_INTERVAL_SECONDS} 秒`
  }
  if (interval > MAX_CHECK_INTERVAL_SECONDS) {
    return `检测间隔不能大于 ${MAX_CHECK_INTERVAL_SECONDS} 秒`
  }
  return ''
}

function getCheckIntervalHint(platform) {
  if (platform === 'kuaishou') {
    return '最小 10 秒。快手对检测频率较敏感，建议 300~600 秒'
  }
  if (platform === 'youtube') {
    return '最小 10 秒。建议 120 秒以上，过短的间隔可能触发人机验证'
  }
  return '最小 10 秒，建议 60 秒，过短的间隔可能触发平台风控限流'
}

const addIntervalError = computed(() => addForm.value.monitor_enabled ? getCheckIntervalError(addForm.value.check_interval) : '')
const editIntervalError = computed(() => editForm.value.monitor_enabled ? getCheckIntervalError(editForm.value.check_interval) : '')

const showAddModal = ref(false)
const addLoading = ref(false)
const addMode = ref('single')
const addForm = ref({
  room_url: '',
  quality: '原画',
  auto_record: false,
  monitor_enabled: true,
  check_interval: 60,
  notification_enabled: true,
  danmu_enabled: false
})
const addBatchText = ref('')

function parseBatchUrls(text) {
  const rawLines = String(text || '').split(/\r?\n/)
  const urls = []
  rawLines.forEach((line) => {
    const trimmed = line.trim()
    if (!trimmed) return
    const parts = trimmed.split(/[\s,]+/).filter(Boolean)
    urls.push(...parts)
  })
  const seen = new Set()
  const uniqueUrls = []
  let duplicates = 0
  urls.forEach((url) => {
    if (seen.has(url)) {
      duplicates += 1
    } else {
      seen.add(url)
      uniqueUrls.push(url)
    }
  })
  return {
    total: urls.length,
    unique: uniqueUrls.length,
    duplicates,
    uniqueUrls
  }
}

const batchStats = computed(() => parseBatchUrls(addBatchText.value))

// 显示格式帮助
function showFormatHelp() {
  dialog.alert({
    title: '支持的链接格式',
    message: `
      <div style="text-align: left; font-size: 13px; line-height: 1.5;">
        <div style="margin-bottom: 8px;">支持 <strong>抖音 / 斗鱼 / Bilibili / 虎牙 / 小红书 / YouTube / 咪咕 / 快手</strong> 平台，常见格式：</div>
        <table style="width: 100%; border-collapse: collapse;">
          <tr>
            <td style="padding: 2px 0; width: 70px; color: var(--color-text-secondary); vertical-align: top;">抖音:</td>
            <td style="padding: 2px 0;">live.douyin.com/123... 或 v.douyin.com/abc...</td>
          </tr>
          <tr>
            <td style="padding: 2px 0; color: var(--color-text-secondary); vertical-align: top;">Bilibili:</td>
            <td style="padding: 2px 0;">live.bilibili.com/123...</td>
          </tr>
          <tr>
            <td style="padding: 2px 0; color: var(--color-text-secondary); vertical-align: top;">斗鱼:</td>
            <td style="padding: 2px 0;">www.douyu.com/24422</td>
          </tr>
          <tr>
            <td style="padding: 2px 0; color: var(--color-text-secondary); vertical-align: top;">虎牙:</td>
            <td style="padding: 2px 0;">huya.com/123456</td>
          </tr>
          <tr>
            <td style="padding: 2px 0; color: var(--color-text-secondary); vertical-align: top;">小红书:</td>
            <td style="padding: 2px 0;">xhslink.com/... 或 www.xiaohongshu.com/user/profile/... （支持直链和短链）<br/>⚠️ 小红书直播链接多为临时地址，易失效，暂不建议用于长期监控。</td>
          </tr>
          <tr>
            <td style="padding: 2px 0; color: var(--color-text-secondary); vertical-align: top;">YouTube:</td>
            <td style="padding: 2px 0;">youtube.com/watch?v=... 或 youtube.com/live/... 或 youtu.be/...</td>
          </tr>
          <tr>
            <td style="padding: 2px 0; color: var(--color-text-secondary); vertical-align: top;">咪咕:</td>
            <td style="padding: 2px 0;">www.miguvideo.com/p/live/120000...</td>
          </tr>
          <tr>
            <td style="padding: 2px 0; color: var(--color-text-secondary); vertical-align: top;">快手:</td>
            <td style="padding: 2px 0;">
              live.kuaishou.com/u/... 或 v.kuaishou.com/... (支持短链)<br/>
            </td>
          </tr>
          <tr>
            <td style="padding: 2px 0; color: var(--color-text-secondary); vertical-align: top;">网易CC:</td>
            <td style="padding: 2px 0;">
              cc.163.com/123456
            </td>
          </tr>
          <tr>
            <td style="padding: 2px 0; color: var(--color-text-secondary); vertical-align: top;">Twitch:</td>
            <td style="padding: 2px 0;">
              twitch.tv/username 或 m.twitch.tv/username
            </td>
          </tr>
        </table>
      </div>
    `,
    confirmText: '知道了'
  })
}

// 编辑表单
const showEditModal = ref(false)
const editLoading = ref(false)
const editingSubscription = ref(null)
const editForm = ref({
  quality: '原画',
  auto_record: true,
  monitor_enabled: true,
  check_interval: 60,
  notification_enabled: true,
  // 新增高级配置
  split_enabled: false,
  split_duration: 3600,
  generate_subtitle: false,
  auto_convert_mp4: true,
  danmu_enabled: false,
  compat_mode: false
})

const deleteLoading = ref(false)
const deletingSubscription = ref(null)

// 历史记录
const showHistory = ref(false)
const historyLoading = ref(false)
const historyRecords = ref([])
// 历史记录展示数据（预计算展示字段）
const historyCardItems = computed(() => {
  return historyRecords.value.map(record => ({
    ...record,
    _anchorName: truncateHistoryAnchorName(record.anchor_name),
    _date: formatDate(record.start_time),
    _duration: formatDuration(record.duration),
    _size: formatSize(record.file_size),
    _statusText: getStatusText(record.status),
    _fileUrl: getRecordFileUrl(record),
    _remark: getRecordRemark(record),
  }))
})
const historyPage = ref(1)
const historyPageSize = ref(8)
const historyTotal = ref(0)
const historyRecordingCount = ref(0)
const historyFilterSubId = ref(null)
const historyJumpPage = ref('')
const jumpAnimatingRecordId = ref('')
let jumpAnimatingTimer = null
const totalHistoryPages = computed(() => Math.max(1, Math.ceil(historyTotal.value / historyPageSize.value)))
const selectedHistoryIds = ref([])
const showBatchDeleteModal = ref(false)
const batchDeleteLoading = ref(false)
const batchDeleteFileChecked = ref(false)
const selectableHistoryIdsOnPage = computed(() =>
  historyRecords.value.filter(r => r.status !== 'recording').map(r => r.id)
)
const selectableHistoryCountOnPage = computed(() => selectableHistoryIdsOnPage.value.length)
const isAllHistorySelectedOnPage = computed(() =>
  selectableHistoryCountOnPage.value > 0 &&
  selectableHistoryIdsOnPage.value.every(id => selectedHistoryIds.value.includes(id))
)
const selectedHistoryCount = computed(() => selectedHistoryIds.value.length)
const batchConvertLoading = ref(false)
const pendingConvertCount = ref(0)
const pendingConvertCountLoading = ref(false)

// 删除确认状态
const showDeleteConfirmModal = ref(false)
const recordToDelete = ref(null)
const deleteFileChecked = ref(false) // 默认为 false，防止手误
const historyFilterAnchorName = ref('')
const historyFilterPlatformName = ref('')
const historyFilterAvatarUrl = ref('')
const isMobileViewport = ref(false)
let viewportResizeHandler = null
const showClearAllModal = ref(false)
const clearAllLoading = ref(false)
const clearAllFileChecked = ref(false)
const showRemarkModal = ref(false)
const remarkLoading = ref(false)
const editingRemarkRecord = ref(null)
const remarkForm = ref('')
const historyTitle = computed(() => historyFilterSubId.value ? `录制历史 - ${historyFilterAnchorName.value}` : '录制历史')
const TIMELINE_DATE_STORAGE_KEY = 'live_record_timeline_date_by_sub_v1'
const TIMELINE_RESUME_STORE_KEY = 'timeline_player_resume_state_v3'
const timelineDateBySub = ref({})
const timelineSelectedDate = ref(getTodayDateString())

function getTodayDateString() {
  const now = new Date()
  const y = now.getFullYear()
  const m = `${now.getMonth() + 1}`.padStart(2, '0')
  const d = `${now.getDate()}`.padStart(2, '0')
  return `${y}-${m}-${d}`
}

function getTimelineDateForSub(subId) {
  const key = String(subId || '')
  if (!key) return getTodayDateString()
  const date = timelineDateBySub.value[key]
  return typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : getTodayDateString()
}

function getResumeDateForSub(subId) {
  const key = String(subId || '')
  if (!key) return ''
  try {
    const raw = localStorage.getItem(TIMELINE_RESUME_STORE_KEY)
    if (!raw) return ''
    const parsed = JSON.parse(raw)
    if (!parsed || Number(parsed.version) !== 3 || typeof parsed.items !== 'object') return ''
    const entry = parsed.items[`${key}|__latest__`]
    const extrasDate = entry?.extras?.date
    if (typeof extrasDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(extrasDate)) {
      return extrasDate
    }
  } catch (error) {
    console.warn('load resume date failed', error)
  }
  return ''
}

function getPreferredTimelineDateForSub(subId) {
  return getResumeDateForSub(subId) || getTimelineDateForSub(subId)
}

function loadTimelineDateCache() {
  try {
    const raw = localStorage.getItem(TIMELINE_DATE_STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return

    const restored = {}
    Object.entries(parsed).forEach(([subId, date]) => {
      const key = String(subId || '').trim()
      const normalizedDate = String(date || '').trim()
      if (key && /^\d{4}-\d{2}-\d{2}$/.test(normalizedDate)) {
        restored[key] = normalizedDate
      }
    })
    timelineDateBySub.value = restored
  } catch (error) {
    console.warn('load timeline date cache failed', error)
  }
}

function saveTimelineDateCache() {
  try {
    localStorage.setItem(TIMELINE_DATE_STORAGE_KEY, JSON.stringify(timelineDateBySub.value || {}))
  } catch (error) {
    console.warn('save timeline date cache failed', error)
  }
}

function handleTimelineDateChange(newDate) {
  const normalized = String(newDate || '').trim()
  if (!/^\d{4}-\d{2}-\d{2}$/.test(normalized)) return
  timelineSelectedDate.value = normalized
  const subKey = String(historyFilterSubId.value || '')
  if (subKey) {
    timelineDateBySub.value[subKey] = normalized
    saveTimelineDateCache()
  }
}

function normalizeQueryValue(value) {
  if (Array.isArray(value)) return String(value[0] || '').trim()
  return String(value || '').trim()
}

function syncHistoryQuery(subId = '', anchorName = '', platformName = '') {
  const query = { ...route.query, action: 'history' }
  const normalizedSubId = String(subId || '').trim()
  const normalizedAnchorName = String(anchorName || '').trim()
  const normalizedPlatformName = String(platformName || '').trim()

  if (normalizedSubId) {
    query.subscription_id = normalizedSubId
  } else {
    delete query.subscription_id
  }

  if (normalizedAnchorName) {
    query.anchor_name = normalizedAnchorName
  } else {
    delete query.anchor_name
  }

  if (normalizedPlatformName) {
    query.platform_name = normalizedPlatformName
  } else {
    delete query.platform_name
  }

  router.replace({ path: route.path, query }).catch(() => {})
}

function clearHistoryQuery() {
  const query = { ...route.query }
  delete query.action
  delete query.subscription_id
  delete query.anchor_name
  delete query.platform_name
  router.replace({ path: route.path, query }).catch(() => {})
}

function openGlobalHistory(options = {}) {
  const { syncRoute = true, reload = false } = options
  historyFilterSubId.value = null
  historyFilterAnchorName.value = ''
  historyFilterPlatformName.value = ''
  historyFilterAvatarUrl.value = ''
  historyPage.value = 1
  showHistory.value = true
  if (syncRoute) syncHistoryQuery()
  if (reload) loadHistory(1)
}

function showSubscriptionHistory(sub, options = {}) {
  const { syncRoute = true, reload = false } = options
  historyFilterSubId.value = sub.id
  historyFilterAnchorName.value = sub.anchor_name
  const platformName = getPlatformName(sub.platform)
  historyFilterPlatformName.value = platformName
  historyFilterAvatarUrl.value = sub.avatar_url || ''
  historyPage.value = 1
  showHistory.value = true
  if (syncRoute) syncHistoryQuery(sub.id, sub.anchor_name, platformName)
  if (reload) loadHistory(1)
}

function triggerRecordJumpAnimation(recordId) {
  const normalizedId = String(recordId || '').trim()
  if (!normalizedId) return
  jumpAnimatingRecordId.value = normalizedId
  if (jumpAnimatingTimer) {
    clearTimeout(jumpAnimatingTimer)
    jumpAnimatingTimer = null
  }
  jumpAnimatingTimer = setTimeout(() => {
    jumpAnimatingRecordId.value = ''
    jumpAnimatingTimer = null
  }, 420)
}

function isRecordOwnerHistoryClickable(record) {
  const subId = String(record?.subscription_id || '').trim()
  if (!subId) return false
  const activeSubId = String(historyFilterSubId.value || '').trim()
  if (!activeSubId) return true
  return subId !== activeSubId
}

function handleRecordOwnerHistoryClick(record) {
  if (!isRecordOwnerHistoryClickable(record)) return
  openRecordOwnerHistory(record)
}

async function openRecordOwnerHistory(record) {
  const subId = String(record?.subscription_id || '').trim()
  if (!subId) {
    toast.error('该记录缺少订阅ID，无法筛选该主播历史')
    return
  }

  triggerRecordJumpAnimation(record?.id)
  const anchorName = String(record?.anchor_name || '').trim()
  historyFilterSubId.value = subId
  historyFilterAnchorName.value = anchorName
  historyFilterPlatformName.value = ''
  historyFilterAvatarUrl.value = String(record?.avatar_url || '').trim()
  historyPage.value = 1
  showHistory.value = true
  syncHistoryQuery(subId, anchorName, '')
  await new Promise(resolve => setTimeout(resolve, 140))
  loadHistory(1)
}

function openTimelinePlayer() {
  const query = {
    name: historyFilterAnchorName.value,
    avatar: historyFilterAvatarUrl.value,
    platform_name: historyFilterPlatformName.value,
    date: getPreferredTimelineDateForSub(historyFilterSubId.value)
  }
  router.push({
    name: 'live-timeline',
    params: { subId: historyFilterSubId.value },
    query
  })
}

function openTimelineForSub(sub) {
  const query = {
    name: sub.anchor_name,
    avatar: sub.avatar_url,
    platform_name: getPlatformName(sub.platform),
    date: getPreferredTimelineDateForSub(sub.id)
  }
  router.push({
    name: 'live-timeline',
    params: { subId: sub.id },
    query
  })
}

function truncateHistoryAnchorName(name, maxChars = 6) {
  const raw = String(name || '')
  const chars = Array.from(raw)
  if (chars.length <= maxChars) return raw
  return `${chars.slice(0, maxChars).join('')}...`
}

function getRecordRemark(record) {
  const remark = String(record?.remark || '').trim()
  if (remark) return remark
  const error = String(record?.error_message || '').trim()
  return error || '-'
}

function openRemarkEditor(record) {
  editingRemarkRecord.value = record
  remarkForm.value = String(record?.remark || '')
  showRemarkModal.value = true
}

function resetRemarkEditor() {
  editingRemarkRecord.value = null
  remarkForm.value = ''
}

// 播放器状态
const showPlayerModal = ref(false)
const playingTitle = ref('')
const playerLoading = ref(false)
const playerError = ref('')
const videoPlayer = ref(null)
const videoMetadata = ref({ width: 0, height: 0 })
const currentPlayerSub = ref(null)
const playerContainerRef = ref(null)

// 直播预览三连屏相关状态
const showLiveTripleScreen = ref(localStorage.getItem('easyvdl_live_triple_screen') === 'true')
const liveCanvasLeftRef = ref(null)
const liveCanvasRightRef = ref(null)
let liveTripleScreenRAF = null

const isLiveVerticalVideo = computed(() => {
  return videoMetadata.value.width > 0 && videoMetadata.value.height > videoMetadata.value.width
})

function startLiveTripleScreenLoop() {
  stopLiveTripleScreenLoop()
  if (!showLiveTripleScreen.value || !isLiveVerticalVideo.value) return

  const drawFrame = () => {
    const video = videoPlayer.value
    if (!video || video.paused || video.ended) {
      liveTripleScreenRAF = requestAnimationFrame(drawFrame)
      return
    }

    const canvasLeft = liveCanvasLeftRef.value
    const canvasRight = liveCanvasRightRef.value

    if (canvasLeft) {
      const ctxLeft = canvasLeft.getContext('2d')
      if (ctxLeft) {
        if (canvasLeft.width !== video.videoWidth || canvasLeft.height !== video.videoHeight) {
          canvasLeft.width = video.videoWidth
          canvasLeft.height = video.videoHeight
        }
        ctxLeft.drawImage(video, 0, 0, canvasLeft.width, canvasLeft.height)
      }
    }

    if (canvasRight) {
      const ctxRight = canvasRight.getContext('2d')
      if (ctxRight) {
        if (canvasRight.width !== video.videoWidth || canvasRight.height !== video.videoHeight) {
          canvasRight.width = video.videoWidth
          canvasRight.height = video.videoHeight
        }
        ctxRight.drawImage(video, 0, 0, canvasRight.width, canvasRight.height)
      }
    }

    liveTripleScreenRAF = requestAnimationFrame(drawFrame)
  }

  liveTripleScreenRAF = requestAnimationFrame(drawFrame)
}

function stopLiveTripleScreenLoop() {
  if (liveTripleScreenRAF) {
    cancelAnimationFrame(liveTripleScreenRAF)
    liveTripleScreenRAF = null
  }
}

function toggleLiveTripleScreen() {
  showLiveTripleScreen.value = !showLiveTripleScreen.value
  localStorage.setItem('easyvdl_live_triple_screen', String(showLiveTripleScreen.value))
}

// 监听三连屏开启状态和是否为竖屏视频，自动启停 loop
watch([showLiveTripleScreen, isLiveVerticalVideo], ([show, isVertical]) => {
  if (show && isVertical) {
    nextTick(() => {
      startLiveTripleScreenLoop()
    })
  } else {
    stopLiveTripleScreenLoop()
  }
})
const playerFullscreenRef = ref(null)
const isPlayerFullscreen = ref(false)
const videoControlsEnabled = computed(() => !isPlayerFullscreen.value)
const sidebarHoverVisible = ref(false)
let sidebarHideTimer = null
const SIDEBAR_EDGE_TRIGGER_PX = 24
const SIDEBAR_HIDE_DELAY_MS = 1200

const clearSidebarHideTimer = () => {
  if (sidebarHideTimer) {
    clearTimeout(sidebarHideTimer)
    sidebarHideTimer = null
  }
}

const showSidebarHover = () => {
  clearSidebarHideTimer()
  sidebarHoverVisible.value = true
}

const scheduleHideSidebar = (delay = SIDEBAR_HIDE_DELAY_MS) => {
  clearSidebarHideTimer()
  if (!isPlayerFullscreen.value) {
    sidebarHoverVisible.value = false
    return
  }
  sidebarHideTimer = setTimeout(() => {
    sidebarHoverVisible.value = false
  }, delay)
}

const handlePlayerEdgeMove = (event) => {
  if (!isPlayerFullscreen.value || isMobileViewport.value) return
  const root = playerFullscreenRef.value
  if (!root) return
  const rect = root.getBoundingClientRect()
  if (event.clientX >= rect.right - SIDEBAR_EDGE_TRIGGER_PX) {
    showSidebarHover()
  } else if (sidebarHoverVisible.value) {
    scheduleHideSidebar()
  }
}

const handlePlayerEdgeLeave = () => {
  if (!isPlayerFullscreen.value || isMobileViewport.value) return
  scheduleHideSidebar(300)
}

// 直播弹幕（实时）
const LIVE_DANMU_MODE_KEY = 'live_danmu_mode'
const liveDanmuMode = ref('marquee')
const liveDanmuItems = ref([])
const liveDanmuAvailable = ref(true)
const liveDanmuKeySet = new Set()
let liveDanmuSocket = null
let liveDanmuSocketReconnectTimer = null
let liveDanmuReconnectAttempt = 0
const LIVE_DANMU_RECONNECT_BASE_MS = 1500
const LIVE_DANMU_RECONNECT_MAX_MS = 30000
const LIVE_DANMU_RECONNECT_JITTER = 0.2
const LIVE_DANMU_SUPPORTED_PLATFORMS = new Set(['douyin', 'bilibili', 'douyu', 'huya', 'twitch'])

const liveDanmuVisible = computed(() => liveDanmuMode.value !== 'off')
const liveDanmuUnsupported = computed(() => {
  const platform = String(currentPlayerSub.value?.platform || '').toLowerCase()
  return platform ? !LIVE_DANMU_SUPPORTED_PLATFORMS.has(platform) : false
})
const liveDanmuModeLabel = computed(() => {
  if (liveDanmuMode.value === 'marquee') return '弹幕: 横向滚动'
  if (liveDanmuMode.value === 'list') return '弹幕: 纵向列表'
  return '弹幕: 关闭'
})
const liveDanmuStatusText = computed(() => {
  if (liveDanmuUnsupported.value) return '弹幕: 暂不支持'
  if (!liveDanmuVisible.value) return '弹幕: 关闭'
  if (!liveDanmuAvailable.value) return '弹幕: 未就绪'
  if (liveDanmuMode.value === 'marquee') return '弹幕: 横向'
  if (liveDanmuMode.value === 'list') return '弹幕: 纵向'
  return '弹幕'
})

const updatePlayerFullscreenState = () => {
  const fsEl = document.fullscreenElement
  const target = playerFullscreenRef.value
  isPlayerFullscreen.value = !!fsEl && !!target && fsEl === target
}

watch(isPlayerFullscreen, (val) => {
  clearSidebarHideTimer()
  if (val) {
    sidebarHoverVisible.value = false
  } else {
    sidebarHoverVisible.value = false
  }
})

const toggleLiveFullscreen = async () => {
  const target = playerFullscreenRef.value
  if (!target) return
  if (document.fullscreenElement) {
    if (document.exitFullscreen) {
      document.exitFullscreen().catch(() => {})
    }
    return
  }
  if (target.requestFullscreen) {
    try {
      await target.requestFullscreen()
    } catch (e) {
      // ignore
    }
  }
}

const savedLiveDanmuMode = localStorage.getItem(LIVE_DANMU_MODE_KEY)
if (savedLiveDanmuMode) {
  liveDanmuMode.value = savedLiveDanmuMode
}

watch(liveDanmuMode, (val) => {
  localStorage.setItem(LIVE_DANMU_MODE_KEY, val)
  if (val === 'off') {
    closeLiveDanmuSocket()
  } else if (showPlayerModal.value && currentPlayerSub.value?.id) {
    openLiveDanmuSocket(false)
  }
})

watch(
  [showPlayerModal, () => currentPlayerSub.value?.id],
  ([show, subId]) => {
    if (show && subId && liveDanmuVisible.value) {
      openLiveDanmuSocket(true)
    } else {
      closeLiveDanmuSocket()
    }
  }
)

const toggleLiveDanmuMode = () => {
  if (liveDanmuUnsupported.value) return
  const order = ['marquee', 'list', 'off']
  const idx = order.indexOf(liveDanmuMode.value)
  liveDanmuMode.value = order[(idx + 1) % order.length]
}

const resetLiveDanmuBuffer = () => {
  liveDanmuItems.value = []
  liveDanmuKeySet.clear()
  liveDanmuAvailable.value = true
  liveMarqueeItems.value = []
}

const liveDanmuListRef = ref(null)
const liveDanmuListStickToBottom = ref(true)
const liveDanmuListUserHold = ref(false)

const handleLiveDanmuListScroll = () => {
  const el = liveDanmuListRef.value
  if (!el) return
  const threshold = 16
  const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - threshold
  liveDanmuListStickToBottom.value = atBottom
  liveDanmuListUserHold.value = !atBottom
}

const scrollLiveDanmuListToBottom = () => {
  const el = liveDanmuListRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

const jumpLiveDanmuListToLatest = () => {
  liveDanmuListUserHold.value = false
  liveDanmuListStickToBottom.value = true
  nextTick(scrollLiveDanmuListToBottom)
}

const liveDanmuListItems = computed(() => {
  return liveDanmuItems.value
    .filter((item) => {
      if (!item?.content) return false
      const method = item?.method || ''
      const eventType = item?.event_type || ''
      if (eventType && eventType !== 'chat') return false
      if (!eventType && method && method !== 'WebcastChatMessage') return false
      return true
    })
    .slice(-200)
})

const LIVE_DANMU_MARQUEE_LANES = 6
const LIVE_DANMU_MARQUEE_GAP_MS = 450
const LIVE_DANMU_MARQUEE_MAX_ACTIVE = 50
const liveMarqueeItems = ref([])
const liveMarqueeLaneNextAt = Array.from({ length: LIVE_DANMU_MARQUEE_LANES }, () => 0)

const calcLiveMarqueeDuration = (text) => {
  const len = String(text || '').length
  const base = 12
  const extra = Math.min(22, len * 0.3)
  return Math.max(12, Math.min(32, base + extra))
}

const formatLiveDanmuLine = (item) => {
  if (!item) return ''
  const user = item?.user?.nickname || item?.user?.name || ''
  const content = String(item?.content || '').trim()
  if (!content) return ''
  if (user) return `${user}: ${content}`
  return content
}

const enqueueLiveMarquee = (item) => {
  if (liveDanmuMode.value !== 'marquee') return
  if (liveMarqueeItems.value.length >= LIVE_DANMU_MARQUEE_MAX_ACTIVE) return
  const text = formatLiveDanmuLine(item)
  if (!text) return
  const now = Date.now()
  let lane = 0
  let earliest = liveMarqueeLaneNextAt[0]
  for (let i = 1; i < liveMarqueeLaneNextAt.length; i += 1) {
    if (liveMarqueeLaneNextAt[i] < earliest) {
      earliest = liveMarqueeLaneNextAt[i]
      lane = i
    }
  }
  const duration = calcLiveMarqueeDuration(text)
  const startAt = Math.max(now, earliest)
  liveMarqueeLaneNextAt[lane] = startAt + duration * 1000 + LIVE_DANMU_MARQUEE_GAP_MS

  const laneStep = LIVE_DANMU_MARQUEE_LANES > 1 ? 70 / (LIVE_DANMU_MARQUEE_LANES - 1) : 0
  const topPercent = 10 + lane * laneStep

  const createItem = () => {
    if (liveDanmuMode.value !== 'marquee') return
    const id = `${item._id || ''}-${startAt}`
    const style = {
      top: `${topPercent}%`,
      animationDuration: `${duration}s`
    }
    liveMarqueeItems.value.push({ id, text, style })
    const cleanupDelay = duration * 1000 + 80
    setTimeout(() => {
      liveMarqueeItems.value = liveMarqueeItems.value.filter((m) => m.id !== id)
    }, cleanupDelay)
  }

  const delayMs = Math.max(0, startAt - now)
  if (delayMs > 0) {
    setTimeout(createItem, delayMs)
  } else {
    createItem()
  }
}

const appendLiveDanmuItems = (items) => {
  items.forEach((item) => {
    const ts = Number(item.ts) || 0
    const content = String(item.content || '')
    const userId = item?.user?.id || ''
    const key = `${ts}-${userId}-${content}`
    if (liveDanmuKeySet.has(key)) return
    liveDanmuKeySet.add(key)
    item._id = key
    liveDanmuItems.value.push(item)
    enqueueLiveMarquee(item)
  })
  const maxItems = 200
  if (liveDanmuItems.value.length > maxItems) {
    liveDanmuItems.value.splice(0, liveDanmuItems.value.length - maxItems)
  }
  if (liveDanmuMode.value === 'list' && liveDanmuListStickToBottom.value && !liveDanmuListUserHold.value) {
    nextTick(scrollLiveDanmuListToBottom)
  }
}

const buildLiveDanmuWsUrl = () => {
  if (!currentPlayerSub.value?.id) return ''
  return buildAuthedWsUrl(`/api/ws/subscribe/danmu-live/${currentPlayerSub.value.id}`)
}

const closeLiveDanmuSocket = () => {
  if (liveDanmuSocketReconnectTimer) {
    clearTimeout(liveDanmuSocketReconnectTimer)
    liveDanmuSocketReconnectTimer = null
  }
  liveDanmuReconnectAttempt = 0
  if (liveDanmuSocket) {
    try {
      liveDanmuSocket.close()
    } catch (error) {
      // ignore
    }
    liveDanmuSocket = null
  }
}

const scheduleLiveDanmuReconnect = () => {
  if (liveDanmuSocketReconnectTimer) return
  if (!liveDanmuVisible.value || liveDanmuUnsupported.value) return
  const expDelay = Math.min(
    LIVE_DANMU_RECONNECT_MAX_MS,
    LIVE_DANMU_RECONNECT_BASE_MS * Math.pow(2, liveDanmuReconnectAttempt)
  )
  const jitterRange = expDelay * LIVE_DANMU_RECONNECT_JITTER
  const delay = Math.max(500, expDelay - jitterRange + Math.random() * jitterRange * 2)
  liveDanmuReconnectAttempt += 1
  liveDanmuSocketReconnectTimer = setTimeout(() => {
    liveDanmuSocketReconnectTimer = null
    openLiveDanmuSocket()
  }, delay)
}

const openLiveDanmuSocket = (resetBuffer = false) => {
  if (!currentPlayerSub.value?.id || !liveDanmuVisible.value) return
  if (liveDanmuUnsupported.value) {
    liveDanmuAvailable.value = false
    return
  }
  closeLiveDanmuSocket()
  if (resetBuffer) resetLiveDanmuBuffer()
  liveDanmuAvailable.value = true
  const wsUrl = buildLiveDanmuWsUrl()
  if (!wsUrl) return
  try {
    liveDanmuSocket = new WebSocket(wsUrl)
  } catch (error) {
    scheduleLiveDanmuReconnect()
    return
  }
  liveDanmuSocket.onopen = () => {
    liveDanmuAvailable.value = true
    liveDanmuReconnectAttempt = 0
  }
  liveDanmuSocket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      if (payload?.type === 'danmu' && Array.isArray(payload.data)) {
        liveDanmuAvailable.value = true
        appendLiveDanmuItems(payload.data)
      }
    } catch (error) {
      // ignore malformed payloads
    }
  }
  liveDanmuSocket.onerror = () => {
    scheduleLiveDanmuReconnect()
  }
  liveDanmuSocket.onclose = () => {
    scheduleLiveDanmuReconnect()
  }
}

// 计算播放器模态框宽度
const playerModalWidth = computed(() => '100%')
const playerModalHeight = computed(() => '100%')

function onVideoMetadata(e) {
  videoMetadata.value = {
    width: e.target.videoWidth,
    height: e.target.videoHeight
  }
}
let flvPlayer = null
let hlsPlayer = null

function getRecordRawPath(record) {
  let rawPath = record.file_path

  if (record.converted === 'true' && record.converted_path) {
    rawPath = record.converted_path
  } else if (!rawPath && record.converted_path) {
    rawPath = record.converted_path
  }

  if (!rawPath || typeof rawPath !== 'string') return ''

  const prefixes = ['/app/downloads/', '/app/data/', '/downloads/']
  for (const prefix of prefixes) {
    if (rawPath.startsWith(prefix)) {
      rawPath = rawPath.substring(prefix.length)
      break
    }
  }

  if (rawPath.includes('/live/') && !rawPath.startsWith('live/')) {
    const idx = rawPath.indexOf('live/')
    rawPath = rawPath.substring(idx)
  }

  return rawPath
}

function getRecordFileUrl(record) {
  const rawPath = getRecordRawPath(record)
  if (!rawPath) return ''

  const encodedPath = rawPath.split('/').map(p => encodeURIComponent(p)).join('/')
  return `${window.location.origin}/downloads/${encodedPath}`
}

function getRecordDownloadName(record) {
  const rawPath = getRecordRawPath(record)
  const fallback = `record_${record.id || Date.now()}.mp4`
  if (!rawPath) return fallback

  const fileName = rawPath.split('/').pop() || fallback
  return fileName
}

function downloadRecord(record) {
  const fileUrl = getRecordFileUrl(record)
  if (!fileUrl) {
    toast.error('下载地址无效')
    return
  }

  const link = document.createElement('a')
  link.href = fileUrl
  link.download = getRecordDownloadName(record)
  link.rel = 'noopener noreferrer'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

// Play record file
function playRecord(record) {
  if (!record.file_path && !record.converted_path) {
    toast.error('文件路径无效')
    return
  }
  
  // Clean up existing player
  destroyPlayer()
  
  playingTitle.value = `${record.anchor_name} - ${formatDate(record.start_time)}`
  showPlayerModal.value = true
  playerLoading.value = true
  playerError.value = ''
  videoMetadata.value = { width: 0, height: 0 }
  
  nextTick(() => {
     const videoElement = videoPlayer.value
     if (!videoElement) return
     
     // 构造文件 URL
     // record.file_path 通常是绝对路径，例如 /app/downloads/live/douyin/...
     // 或者是 /mnt/user/appdata/...
     // 前端 /downloads/ 代理映射到下载根目录
     
     const rawPath = getRecordRawPath(record)
     if (!rawPath) {
        playerLoading.value = false
        playerError.value = '文件路径无效'
        return
     }

     const fileUrl = getRecordFileUrl(record)
     
     const isTs = rawPath.toLowerCase().endsWith('.ts')
     
     if (isTs) {
         if (mpegts.getFeatureList().mseLivePlayback) {
             // 关闭 mpegts 的详细日志输出
             mpegts.LoggingControl.enableAll = false;
             
             flvPlayer = mpegts.createPlayer({
                 type: 'mpegts', 
                 url: fileUrl,
                 isLive: false,
                 filesize: record.file_size
             }, {
                 enableWorker: true,
                 lazyLoad: true,
                 lazyLoadMaxDuration: 3 * 60,
                 seekType: 'range'
             })
             
             flvPlayer.attachMediaElement(videoElement)
             flvPlayer.load()
             flvPlayer.play().then(() => {
                 playerLoading.value = false
             }).catch(err => {
                 console.error('播放失败:', err)
                 playerLoading.value = false
                 playerError.value = `播放失败: ${err.message}`
             })
             
             flvPlayer.on(mpegts.Events.ERROR, (e) => {
                 console.error('Mpegts Error:', e)
                 playerLoading.value = false
                 playerError.value = '视频加载出错，可能是格式不支持或文件已损坏'
             })
         } else {
             playerError.value = '您的浏览器不支持 MSE，无法播放 TS 文件'
             playerLoading.value = false
         }
     } else {
         // Native support for MP4, etc.
         videoElement.src = fileUrl
         videoElement.load()
         videoElement.play().then(() => {
             playerLoading.value = false
         }).catch(err => {
             console.error('播放失败:', err)
             playerLoading.value = false
             playerError.value = `播放失败: ${err.message}`
         })
         
         videoElement.onerror = () => {
             playerLoading.value = false
             playerError.value = '视频加载失败'
         }
         
         videoElement.onloadeddata = () => {
             playerLoading.value = false
         }
     }
  })
}

// Close Play Player




const wsService = ref(null)
let liveStatusWsShouldReconnect = true
let liveStatusReconnectTimer = null

function closeLiveStatusWebSocket(allowReconnect = false) {
  liveStatusWsShouldReconnect = allowReconnect
  if (!allowReconnect && liveStatusReconnectTimer) {
    clearTimeout(liveStatusReconnectTimer)
    liveStatusReconnectTimer = null
  }
  if (wsService.value) {
    const ws = wsService.value
    wsService.value = null
    ws.close()
  }
}

const handlePageScroll = (event) => {
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

// 初始化
onMounted(async () => {
  isMobileViewport.value = window.innerWidth <= 768
  loadTimelineDateCache()
  viewportResizeHandler = () => {
    isMobileViewport.value = window.innerWidth <= 768
  }
  window.addEventListener('resize', viewportResizeHandler)
  document.addEventListener('fullscreenchange', updatePlayerFullscreenState)

  // 初始处理查询参数中的筛选条件
  handleRouteQuery()

  // 获取存储信息
  systemStore.fetchStorageUsage()
  
  await checkLicense()

  const scrollContainer = document.querySelector('.main-content')
  if (scrollContainer) {
    scrollContainer.addEventListener('scroll', handlePageScroll)
    handlePageScroll({ target: scrollContainer })
  }
})

watch(() => route.query, () => {
  handleRouteQuery()
})

function handleRouteQuery() {
  // 必须确保当前确实处于直播录制页面，才处理此类通用筛选参数
  if (route.path !== '/live-record') return

  if (route.query.status) {
    filterStatus.value = route.query.status
  }
  if (route.query.platform) {
    filterPlatform.value = route.query.platform
  }
  if (route.query.action === 'history') {
    const subId = normalizeQueryValue(route.query.subscription_id)
    const anchorName = normalizeQueryValue(route.query.anchor_name)
    const platformName = normalizeQueryValue(route.query.platform_name)
    if (subId) {
      historyFilterSubId.value = subId
      historyFilterAnchorName.value = anchorName
      historyFilterPlatformName.value = platformName
      historyFilterAvatarUrl.value = ''
      historyPage.value = 1
      showHistory.value = true
    } else {
      openGlobalHistory({ syncRoute: false })
    }
  }
}

// 初始化WebSocket
function initWebSocket() {
  if (!liveStatusWsShouldReconnect) return
  if (wsService.value) return 

  const wsUrl = buildAuthedWsUrl('/api/ws/subscribe/live_status')
  
  const ws = new WebSocket(wsUrl)
  
  ws.onopen = () => {
    console.log('Live status WebSocket connected')
  }
  
  ws.onmessage = (event) => {
    try {
      if (event.data === 'pong') return
      const message = JSON.parse(event.data)
      
      if (message.type === 'live_status_initial') {
        // 初始全量数据
        if (message.stats) {
          // 只合并非零值，避免覆盖已加载的更详细数据 (如 total_size 为 0 时不覆盖)
          if (message.stats.total_size > 0) {
            stats.value = message.stats
          } else {
             // 仅合并其他字段
             const { total_size, ...others } = message.stats
             stats.value = { ...stats.value, ...others }
          }
        }
        
        // 更新列表状态 (不完全覆盖，仅合并状态字段，保留UI状态)
        if (message.data && subscriptions.value.length > 0) {
           const statusMap = new Map(message.data.map(item => [item.id, item]))
           subscriptions.value.forEach(sub => {
             const newStatus = statusMap.get(sub.id)
             if (newStatus) {
               sub.is_live = newStatus.is_live ? 'true' : 'false'
               sub.is_recording = newStatus.is_recording ? 'true' : 'false'
               if (newStatus.recording_status) {
                 sub.recording_status = newStatus.recording_status
               }
             }
           })
        }
      } else if (message.type === 'live_status_update') {
        // 增量更新
        if (message.id) {
           const sub = subscriptions.value.find(s => s.id === message.id)
           if (sub) {
             if (message.is_live !== undefined) sub.is_live = message.is_live ? 'true' : 'false'
             if (message.is_recording !== undefined) sub.is_recording = message.is_recording ? 'true' : 'false'
             if (message.anchor_name) sub.anchor_name = message.anchor_name
             if (message.recording_status !== undefined) sub.recording_status = message.recording_status
             // 录制开始或停止时，刷新一下统计数据
              if (message.is_recording !== undefined) {
               // 聚合短时间内的多次录制状态变更，避免频繁请求 /live/stats
               scheduleLiveStatsRefresh(700)
             }
           }
           
           // 同步更新历史记录中的正在录制项
           if (showHistory.value && historyRecords.value.length > 0 && message.recording_status) {
             // 找到属于该订阅且状态为"recording"的记录
             // 注意: 历史接口返回的记录中 subscription_id 字段由后端决定，假设有。如果没有，只能通过 anchor_name 或其他方式猜测，
             // 但最稳妥是后端 history 接口返回 subscription_id。
             // 暂时尝试匹配 active 状态的记录。
             const activeRecord = historyRecords.value.find(r => r.status === 'recording' && r.subscription_id === message.id)
             if (activeRecord) {
               activeRecord.duration = message.recording_status.duration
               activeRecord.file_size = message.recording_status.file_size
             }
           }
        }
      } else if (message.type === 'record_update') {
           // 处理录制记录更新 (例如转码完成)
           if (showHistory.value && historyRecords.value.length > 0) {
               const targetRecord = historyRecords.value.find(r => r.id === message.id)
               if (targetRecord) {
                   if (message.status) targetRecord.status = message.status
                   if (message.converted) targetRecord.converted = message.converted
                   if (message.converted_path) targetRecord.converted_path = message.converted_path
               }
           }
        }
    } catch (e) {
      console.error('WebSocket message error:', e)
    }
  }
  
  ws.onclose = () => {
    console.log('Live status WebSocket closed')
    if (wsService.value === ws) {
      wsService.value = null
    }
    if (!liveStatusWsShouldReconnect) return
    // 简单的重连机制
    liveStatusReconnectTimer = setTimeout(() => {
       liveStatusReconnectTimer = null
       if (liveStatusWsShouldReconnect && licenseValid.value) initWebSocket()
    }, 3000)
  }
  
  wsService.value = ws
}

onUnmounted(() => {
  closeLiveStatusWebSocket(false)
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
    searchDebounceTimer = null
  }
  stopBulkLoadingState()
  if (jumpAnimatingTimer) {
    clearTimeout(jumpAnimatingTimer)
    jumpAnimatingTimer = null
  }
  if (liveStatsRefreshTimer) {
    clearTimeout(liveStatsRefreshTimer)
    liveStatsRefreshTimer = null
  }
  clearSidebarHideTimer()
  closeLiveDanmuSocket()

  const scrollContainer = document.querySelector('.main-content')
  if (scrollContainer) {
    scrollContainer.removeEventListener('scroll', handlePageScroll)
  }
  if (viewportResizeHandler) {
    window.removeEventListener('resize', viewportResizeHandler)
    viewportResizeHandler = null
  }
  document.removeEventListener('fullscreenchange', updatePlayerFullscreenState)
})

function scheduleLiveStatsRefresh(delay = 700) {
  if (liveStatsRefreshInFlight) {
    liveStatsRefreshQueued = true
    return
  }
  if (liveStatsRefreshTimer) {
    clearTimeout(liveStatsRefreshTimer)
  }
  liveStatsRefreshTimer = setTimeout(async () => {
    liveStatsRefreshTimer = null
    if (liveStatsRefreshInFlight) {
      liveStatsRefreshQueued = true
      return
    }
    liveStatsRefreshInFlight = true
    try {
      const res = await liveApi.getLiveStats()
      if (res.success) {
        stats.value = res.data
      }
    } catch (e) {
      console.warn('刷新直播统计失败:', e)
    } finally {
      liveStatsRefreshInFlight = false
      if (liveStatsRefreshQueued) {
        liveStatsRefreshQueued = false
        scheduleLiveStatsRefresh(900)
      }
    }
  }, delay)
}

// 加载数据
async function loadData() {
  try {
    const [subsRes, statsRes] = await Promise.all([
      liveApi.getLiveSubscriptions(),
      liveApi.getLiveStats()
    ])
    
    // 注意：响应拦截器已经返回了 response.data，所以直接使用 res 而不是 res.data
    if (subsRes.success) {
      subscriptions.value = subsRes.data
      const ids = subscriptions.value.map(item => item.id).filter(Boolean)
      await refreshTimelineAvailability(ids)
    } else {
      timelineAvailabilityMap.value = {}
    }
    
    if (statsRes.success) {
      stats.value = statsRes.data
    }
  } catch (error) {
    console.error('加载数据失败:', error)
  } finally {
    loading.value = false
  }
}

async function refreshTimelineAvailability(ids = []) {
  if (!ids.length) {
    timelineAvailabilityMap.value = {}
    return
  }
  try {
    const res = await liveApi.getTimelineAvailability(ids)
    if (res.success && res.data) {
      timelineAvailabilityMap.value = res.data
    }
  } catch (error) {
    console.warn('加载时间轴可用性失败:', error)
    timelineAvailabilityMap.value = {}
  }
}

function isTimelineAvailable(subId) {
  return !!timelineAvailabilityMap.value?.[subId]?.available
}

function getTimelineButtonTitle(subId) {
  const item = timelineAvailabilityMap.value?.[subId]
  if (item && item.available) {
    return `可回放片段：${item.count || 0}`
  }
  return '暂无可回放的 MP4 录制'
}

// 刷新所有状态
async function refreshAll() {
  loading.value = true
  await loadData()
}

// 刷新单个状态
async function refreshStatus(sub) {
  actionLoading.value[sub.id] = true
  try {
    await liveApi.refreshLiveStatus(sub.id)
    await loadData()
    toast.success('状态已更新')
  } catch (error) {
    dialog.alert({
      title: '刷新失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    actionLoading.value[sub.id] = false
  }
}

// 开始录制
async function startRecording(sub) {
  actionLoading.value[sub.id] = true
  try {
    const res = await liveApi.startRecording(sub.id)
    if (res.success) {
      await loadData()
      toast.success('录制任务已启动，且已开启开播自动录制')
    } else {
      dialog.alert({ message: res.message || '开始录制失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '操作失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    actionLoading.value[sub.id] = false
  }
}

// 停止录制
async function stopRecording(sub) {
  actionLoading.value[sub.id] = true
  try {
    const res = await liveApi.stopRecording(sub.id)
    if (res.success) {
      await loadData()
      toast.success('已停止录制，且已关闭开播自动录制')
    } else {
      dialog.alert({ message: res.message || '停止录制失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '操作失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    actionLoading.value[sub.id] = false
  }
}

// 批量设置自动录制
function startBulkLoadingState({ title, text, delayedHint = '' }) {
  bulkLoadingTitle.value = title || '正在处理批量操作'
  bulkLoadingText.value = text || '正在提交请求，请稍候...'
  bulkLoadingHint.value = ''

  if (bulkLoadingHintTimer) {
    clearTimeout(bulkLoadingHintTimer)
    bulkLoadingHintTimer = null
  }

  if (delayedHint) {
    bulkLoadingHintTimer = setTimeout(() => {
      if (bulkLoading.value) {
        bulkLoadingHint.value = delayedHint
      }
    }, 8000)
  }
}

function stopBulkLoadingState() {
  if (bulkLoadingHintTimer) {
    clearTimeout(bulkLoadingHintTimer)
    bulkLoadingHintTimer = null
  }
  bulkLoadingHint.value = ''
}

async function bulkSetAutoRecord(enabled) {
  if (filteredSubscriptions.value.length === 0) return
  
  const actionText = enabled ? '开启' : '关闭'
  const targetCount = filteredSubscriptions.value.length
  const confirmed = await dialog.confirm({
    title: `批量${actionText}自动录制`,
    message: `确定要批量<strong>${actionText}</strong>当前筛选出的 ${targetCount} 个直播间的自动录制吗？`,
    type: enabled ? 'success' : 'warning'
  })
  
  if (!confirmed) return

  startBulkLoadingState({
    title: enabled ? '正在批量开启自动录制' : '正在批量关闭自动录制',
    text: enabled
      ? `正在检查 ${targetCount} 个直播间，已开播的会立即尝试开录...`
      : `正在停止 ${targetCount} 个直播间的录制任务，请稍候...`,
    delayedHint: enabled
      ? '若当前网络较慢，立即检查可能需要更长时间，请勿关闭页面。'
      : '部分录制任务需要等待 FFmpeg 正常退出，可能持续几十秒。'
  })
  
  bulkLoading.value = true
  try {
    const ids = filteredSubscriptions.value.map(sub => sub.id)
    const res = await liveApi.bulkUpdateSubscriptionConfig(ids, {
      auto_record: enabled ? 'true' : 'false'
    })
    
    if (res.success) {
      const immediateStarted = Number(res.immediate_started || 0)
      const immediateStopped = Number(res.immediate_stopped || 0)
      const immediateChecked = Number(res.immediate_checked || 0)

      const detail = enabled
        ? `（立即检查 ${immediateChecked} 个，已立即开录 ${immediateStarted} 个）`
        : `（已立即停录 ${immediateStopped} 个）`

      toast.success((res.message || `成功批量${actionText}`) + detail)
      await loadData()
    } else {
      dialog.alert({ message: res.message || '操作失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '批量操作失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    bulkLoading.value = false
    stopBulkLoadingState()
  }
}

async function handleBulkAutoRecordChoice(enabled) {
  showBulkAutoRecordModal.value = false
  await nextTick()
  await bulkSetAutoRecord(enabled)
}

// 批量设置周期检测开关
async function bulkSetMonitor(enabled) {
  if (filteredSubscriptions.value.length === 0) return

  const actionText = enabled ? '开启' : '暂停'
  const targetCount = filteredSubscriptions.value.length
  const confirmed = await dialog.confirm({
    title: `批量${actionText}周期检测`,
    message: enabled
      ? `确定要批量<strong>开启</strong>当前筛选出的 ${targetCount} 个直播间的周期检测吗？`
      : `确定要批量<strong>暂停</strong>当前筛选出的 ${targetCount} 个直播间的周期检测吗？<br><br>这只会停止后续开播状态轮询，不会停止当前正在录制的任务。`,
    type: enabled ? 'success' : 'warning'
  })

  if (!confirmed) return

  startBulkLoadingState({
    title: enabled ? '正在批量开启周期检测' : '正在批量暂停周期检测',
    text: enabled
      ? `正在恢复 ${targetCount} 个直播间的开播状态检测...`
      : `正在暂停 ${targetCount} 个直播间的开播状态检测...`,
    delayedHint: enabled
      ? '恢复周期检测后，已开启自动录制的订阅会继续按检测间隔工作。'
      : ''
  })

  bulkLoading.value = true
  try {
    const ids = filteredSubscriptions.value.map(sub => sub.id)
    const res = await liveApi.bulkUpdateSubscriptionConfig(ids, {
      monitor_enabled: enabled ? 'true' : 'false'
    })

    if (res.success) {
      const pausedCount = Number(res.monitor_paused || 0)
      const detail = enabled ? '' : `（已暂停 ${pausedCount} 个检测任务）`
      toast.success((res.message || `成功批量${actionText}周期检测`) + detail)
      await loadData()
    } else {
      dialog.alert({ message: res.message || '操作失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '批量操作失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    bulkLoading.value = false
    stopBulkLoadingState()
  }
}

async function handleBulkMonitorChoice(enabled) {
  showBulkMonitorModal.value = false
  await nextTick()
  await bulkSetMonitor(enabled)
}

// 批量设置通知开关
async function bulkSetNotification(enabled) {
  if (filteredSubscriptions.value.length === 0) return

  const actionText = enabled ? '开启' : '关闭'
  const confirmed = await dialog.confirm({
    title: `批量${actionText}开播录制通知`,
    message: `确定要批量<strong>${actionText}</strong>当前筛选出的 ${filteredSubscriptions.value.length} 个直播间的开播录制通知吗？`,
    type: enabled ? 'success' : 'warning'
  })

  if (!confirmed) return

  bulkLoading.value = true
  try {
    const ids = filteredSubscriptions.value.map(sub => sub.id)
    const res = await liveApi.bulkUpdateSubscriptionConfig(ids, {
      notification_enabled: enabled ? 'true' : 'false'
    })

    if (res.success) {
      toast.success(res.message || `成功批量${actionText}通知`)
      await loadData()
    } else {
      dialog.alert({ message: res.message || '操作失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '批量操作失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    bulkLoading.value = false
  }
}

async function handleBulkNotificationChoice(enabled) {
  await bulkSetNotification(enabled)
  showBulkNotificationModal.value = false
}

// 批量设置时间戳字幕开关
async function bulkSetSubtitle(enabled) {
  if (filteredSubscriptions.value.length === 0) return

  const actionText = enabled ? '开启' : '关闭'
  const confirmed = await dialog.confirm({
    title: `批量${actionText}时间戳字幕`,
    message: `确定要批量<strong>${actionText}</strong>当前筛选出的 ${filteredSubscriptions.value.length} 个直播间的时间戳字幕吗？`,
    type: enabled ? 'success' : 'warning'
  })

  if (!confirmed) return

  bulkLoading.value = true
  try {
    const ids = filteredSubscriptions.value.map(sub => sub.id)
    const res = await liveApi.bulkUpdateSubscriptionConfig(ids, {
      generate_subtitle: enabled ? 'true' : 'false'
    })

    if (res.success) {
      toast.success(res.message || `成功批量${actionText}时间戳字幕`)
      await loadData()
    } else {
      dialog.alert({ message: res.message || '操作失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '批量操作失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    bulkLoading.value = false
  }
}

async function handleBulkSubtitleChoice(enabled) {
  await bulkSetSubtitle(enabled)
  showBulkSubtitleModal.value = false
}

// 批量设置自动转码开关
async function bulkSetAutoConvert(enabled) {
  if (filteredSubscriptions.value.length === 0) return

  const actionText = enabled ? '开启' : '关闭'
  const confirmed = await dialog.confirm({
    title: `批量${actionText}自动转码`,
    message: `确定要批量<strong>${actionText}</strong>当前筛选出的 ${filteredSubscriptions.value.length} 个直播间的“录制结束自动转码为 MP4”吗？`,
    type: enabled ? 'success' : 'warning'
  })

  if (!confirmed) return

  bulkLoading.value = true
  try {
    const ids = filteredSubscriptions.value.map(sub => sub.id)
    const res = await liveApi.bulkUpdateSubscriptionConfig(ids, {
      auto_convert_mp4: enabled ? 'true' : 'false'
    })

    if (res.success) {
      toast.success(res.message || `成功批量${actionText}自动转码`)
      await loadData()
    } else {
      dialog.alert({ message: res.message || '操作失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '批量操作失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    bulkLoading.value = false
  }
}

async function handleBulkConvertChoice(enabled) {
  await bulkSetAutoConvert(enabled)
  showBulkConvertModal.value = false
}

// 批量设置分段录制
async function bulkSetSegment(enabled) {
  if (filteredSubscriptions.value.length === 0) return

  const actionText = enabled ? '开启' : '关闭'
  const confirmed = await dialog.confirm({
    title: `批量${actionText}分段录制`,
    message: enabled
      ? `确定要批量<strong>开启</strong>当前筛选出的 ${filteredSubscriptions.value.length} 个直播间的分段录制吗？<br><br>分段时长将统一设置为 <strong>${Math.round(bulkSegmentDuration.value / 60)} 分钟</strong>。`
      : `确定要批量<strong>关闭</strong>当前筛选出的 ${filteredSubscriptions.value.length} 个直播间的分段录制吗？`,
    type: enabled ? 'success' : 'warning'
  })

  if (!confirmed) return

  bulkLoading.value = true
  try {
    const ids = filteredSubscriptions.value.map(sub => sub.id)
    const payload = {
      split_enabled: enabled ? 'true' : 'false'
    }
    if (enabled) {
      payload.split_duration = bulkSegmentDuration.value
    }
    const res = await liveApi.bulkUpdateSubscriptionConfig(ids, payload)

    if (res.success) {
      toast.success(res.message || `成功批量${actionText}分段录制`)
      await loadData()
    } else {
      dialog.alert({ message: res.message || '操作失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '批量操作失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    bulkLoading.value = false
  }
}

async function handleBulkSegmentChoice(enabled) {
  await bulkSetSegment(enabled)
  showBulkSegmentModal.value = false
}

// 批量修改画质
const showBulkQualityModal = ref(false)
const bulkQualityTarget = ref('原画')

async function bulkSetQuality() {
  if (filteredSubscriptions.value.length === 0) return
  
  bulkLoading.value = true
  try {
    const ids = filteredSubscriptions.value.map(sub => sub.id)
    const res = await liveApi.bulkUpdateSubscriptionConfig(ids, {
      quality: bulkQualityTarget.value
    })
    
    if (res.success) {
      toast.success(res.message || `成功批量修改画质`)
      showBulkQualityModal.value = false
      await loadData()
    } else {
      dialog.alert({ message: res.message || '操作失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '批量操作失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    bulkLoading.value = false
  }
}

// 批量删除
async function confirmBulkDelete() {
  if (filteredSubscriptions.value.length === 0) return
  
  const confirmed = await dialog.confirm({
    title: '批量删除订阅',
    message: `确定要<strong class="text-danger">删除</strong>当前筛选出的 ${filteredSubscriptions.value.length} 个直播订阅吗？<br><br><span class="text-danger">注意：这将停止正在进行的录制并移除监控。历史录像文件将保留。</span>`,
    type: 'error',
    confirmText: '确认删除',
    confirmButtonClass: 'btn-danger'
  })
  
  if (!confirmed) return
  
  bulkLoading.value = true
  try {
    const ids = filteredSubscriptions.value.map(sub => sub.id)
    const res = await liveApi.bulkDeleteSubscriptions(ids)
    
    if (res.success) {
      toast.success(res.message || `成功批量删除`)
      await loadData()
    } else {
      dialog.alert({ message: res.message || '操作失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '批量删除失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    bulkLoading.value = false
  }
}

// 导出直播订阅配置
async function exportLiveConfig() {
  const confirmed = await customConfirm(
    '确认导出直播订阅列表',
    `
      <div style="text-align:left;line-height:1.6;font-size:13px;">
        <p>将导出当前所有直播订阅，仅包含订阅列表本身：</p>
        <ul style="margin:8px 0;padding-left:20px;">
          <li>平台、直播间链接</li>
          <li>画质、检测间隔、是否自动录制</li>
          <li>通知开关等基础配置</li>
        </ul>
        <p style="font-size:12px;color:var(--color-text-tertiary);margin-top:4px;">
          温馨提示：此备份<strong>不会</strong>包含历史录制记录或录像文件，仅用于快速迁移直播订阅列表。
        </p>
      </div>
    `
  )
  if (!confirmed) return

  try {
    const res = await liveApi.exportLiveBackup()
    if (!res || !Array.isArray(res.subscriptions) || res.subscriptions.length === 0) {
      await customAlert(
        '导出失败',
        `<div style="text-align:left;line-height:1.6;font-size:13px;">当前没有任何直播订阅可供备份。</div>`,
        'warning'
      )
      return
    }

    const json = JSON.stringify(res, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)

    const link = document.createElement('a')
    link.href = url
    link.download = `live_subscriptions_${new Date().toISOString().slice(0, 10)}.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)

    const total = res.total_subscriptions || res.subscriptions.length
    await customAlert(
      '导出成功',
      `
        <div style="text-align:center;line-height:1.6;font-size:13px;">
          <p style="margin-bottom:10px;">配置文件已准备就绪。</p>
          <div style="background:rgba(0,0,0,0.03);padding:12px;border-radius:8px;text-align:left;">
            • 共导出 ${total} 条直播订阅配置
          </div>
        </div>
      `,
      'success'
    )
  } catch (e) {
    console.error('导出直播订阅失败:', e)
    await customAlert(
      '导出失败',
      `<div style="text-align:left;line-height:1.6;font-size:13px;">导出直播订阅列表时发生错误：${e.message || '未知错误'}</div>`,
      'error'
    )
  }
}

// 触发导入文件选择
function triggerLiveImport() {
  if (liveImportInput.value) {
    liveImportInput.value.value = ''
    liveImportInput.value.click()
  }
}

// 处理直播订阅导入
async function handleLiveImport(event) {
  const file = event.target.files && event.target.files[0]
  if (!file) return

  if (!file.name.endsWith('.json')) {
    await customAlert(
      '格式错误',
      `<div style="text-align:left;line-height:1.6;font-size:13px;">请选择有效的 JSON 格式直播订阅备份文件。</div>`,
      'error'
    )
    event.target.value = ''
    return
  }

  try {
    const content = await new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = e => resolve(e.target.result)
      reader.onerror = err => reject(err)
      reader.readAsText(file)
    })

    let data
    try {
      data = JSON.parse(content)
    } catch (e) {
      throw new Error('备份文件内容不是合法的 JSON')
    }

    const res = await liveApi.importLiveBackup(data)

    await loadData()

    const errors = Array.isArray(res.errors) ? res.errors : []
    const hasErrors = errors.length > 0
    const errorHtml = hasErrors
      ? `
        <div style="margin-top:10px;">
          <p style="margin:0 0 4px;font-size:12px;color:var(--color-error);">部分条目已跳过/失败：</p>
          <div style="max-height:120px;overflow:auto;border-radius:6px;border:1px solid rgba(248,113,113,0.4);padding:6px 8px;background:rgba(248,113,113,0.06);font-size:12px;line-height:1.5;">
            ${errors.slice(0, 10).map(msg => `<div style="margin-bottom:2px;">• ${msg}</div>`).join('')}
            ${errors.length > 10 ? `<div style="margin-top:4px;opacity:0.7;">…… 共 ${errors.length} 条，更多详情请查看后台日志</div>` : ''}
          </div>
        </div>
      `
      : ''

    await customAlert(
      '导入完成',
      `
        <div style="text-align:left;line-height:1.6;font-size:13px;">
          <p style="margin-bottom:8px;">直播订阅导入已完成：</p>
          <div style="background:rgba(0,0,0,0.03);padding:12px;border-radius:8px;font-size:13px;">
            <div><strong>总计:</strong> ${res.total || 0} 条</div>
            <div><strong>新增:</strong> ${res.success || 0} 条</div>
            <div><strong>跳过/失败:</strong> ${res.failed || 0} 条</div>
          </div>
          ${errorHtml}
          <p style="margin-top:10px;color:var(--color-text-tertiary);font-size:12px;">
            提示：导入只会新增订阅，不会删除或修改现有订阅，也不会影响历史录制记录。
          </p>
        </div>
      `,
      hasErrors ? 'warning' : 'success'
    )
  } catch (error) {
    console.error('导入直播订阅失败:', error)
    await customAlert(
      '导入失败',
      `<div style="text-align:left;line-height:1.6;font-size:13px;">${error.message || '读取或解析备份文件失败'}</div>`,
      'error'
    )
  } finally {
    event.target.value = ''
  }
}

// ===== 备份提示模态逻辑（复用订阅页样式） =====
function customAlert(title, message, type = 'info') {
  return new Promise((resolve) => {
    tipTitle.value = title
    tipMessage.value = message
    tipType.value = type
    showTipModal.value = true
    tipResolve = (result) => resolve(result)
  })
}

function customConfirm(title, message, type = 'confirm') {
  return new Promise((resolve) => {
    tipTitle.value = title
    tipMessage.value = message
    tipType.value = type
    showTipModal.value = true
    tipResolve = (result) => resolve(result)
  })
}

function handleTipConfirm() {
  showTipModal.value = false
  if (tipResolve) {
    const resolve = tipResolve
    tipResolve = null
    resolve(true)
  }
}

function handleTipCancel() {
  showTipModal.value = false
  if (tipResolve) {
    const resolve = tipResolve
    tipResolve = null
    resolve(false)
  }
}

watch(showTipModal, (visible) => {
  if (!visible && tipResolve) {
    const resolve = tipResolve
    tipResolve = null
    resolve(false)
  }
})

// 添加订阅
async function addSubscription() {
  if (addMode.value === 'batch') {
    await addBatchSubscriptions()
    return
  }

  if (!addForm.value.room_url) {
    toast.warning('请输入直播间地址')
    return
  }
  addIntervalTouched.value = true
  if (addForm.value.monitor_enabled && addIntervalError.value) {
    toast.warning(addIntervalError.value)
    return
  }

  addLoading.value = true
  try {
    const res = await liveApi.addLiveSubscription(addForm.value)
    // 注意：响应拦截器已经返回了 response.data，所以直接使用 res 而不是 res.data
    if (res.success) {
      toast.success(res.message || '添加成功')
      showAddModal.value = false
      resetAddForm()
      addLoading.value = false
      await loadData()
    } else {
      dialog.alert({ title: '添加失败', message: res.message || '未知错误', type: 'error' })
    }
  } catch (error) {
    console.error('添加订阅失败:', error)
    dialog.alert({
      title: '系统错误',
      message: error.response?.data?.detail || error.message || '未知错误',
      type: 'error'
    })
  } finally {
    addLoading.value = false
  }
}

async function addBatchSubscriptions() {
  const stats = batchStats.value
  if (!stats.uniqueUrls.length) {
    toast.warning('请至少输入一个直播间链接')
    return
  }
  if (stats.uniqueUrls.length > 300) {
    toast.warning('一次最多添加300个直播间，请分批提交')
    return
  }
  addIntervalTouched.value = true
  if (addIntervalError.value) {
    toast.warning(addIntervalError.value)
    return
  }

  const payload = {
      subscriptions: stats.uniqueUrls.map(url => ({
        room_url: url,
        quality: addForm.value.quality,
        auto_record: addForm.value.auto_record,
        monitor_enabled: addForm.value.monitor_enabled,
        check_interval: addForm.value.check_interval,
        notification_enabled: addForm.value.notification_enabled,
        danmu_enabled: addForm.value.danmu_enabled
      }))
    }

  addLoading.value = true
  try {
    const res = await liveApi.batchAddLiveSubscriptions(payload)
    const total = res.total ?? stats.uniqueUrls.length
    const successCount = res.success_count ?? (res.successes || []).length
    const errorCount = res.error_count ?? (res.errors || []).length
    const errors = Array.isArray(res.errors) ? res.errors : []
    const errorHtml = errors.length
      ? `
        <div style="margin-top:10px;">
          <p style="margin:0 0 4px;font-size:12px;color:var(--color-error);">以下链接添加失败或被跳过：</p>
          <div style="max-height:140px;overflow:auto;border-radius:6px;border:1px solid rgba(248,113,113,0.4);padding:6px 8px;background:rgba(248,113,113,0.06);font-size:12px;line-height:1.5;">
            ${errors.slice(0, 12).map(item => `<div style="margin-bottom:2px;">• ${item.room_url || '未知链接'}：${item.message || '失败'}</div>`).join('')}
            ${errors.length > 12 ? `<div style="margin-top:4px;opacity:0.7;">…… 共 ${errors.length} 条</div>` : ''}
          </div>
        </div>
      `
      : ''

    // 先关闭弹窗，再刷新列表与展示结果提示
    showAddModal.value = false
    resetAddForm()
    addLoading.value = false

    if (successCount > 0) {
      await loadData()
    }

    await customAlert(
      '批量添加完成',
      `
        <div style="text-align:left;line-height:1.6;font-size:13px;">
          <p style="margin-bottom:8px;">批量添加已完成：</p>
          <div style="background:rgba(0,0,0,0.03);padding:12px;border-radius:8px;font-size:13px;">
            <div><strong>总计:</strong> ${total} 条</div>
            <div><strong>成功:</strong> ${successCount} 条</div>
            <div><strong>失败/跳过:</strong> ${errorCount} 条</div>
          </div>
          ${errorHtml}
          <p style="margin-top:10px;color:var(--color-text-tertiary);font-size:12px;">
            提示：批量添加支持混合平台，系统会根据链接自动识别平台。
          </p>
        </div>
      `,
      errorCount > 0 ? 'warning' : 'success'
    )
  } catch (error) {
    console.error('批量添加订阅失败:', error)
    dialog.alert({
      title: '系统错误',
      message: error.response?.data?.detail || error.message || '未知错误',
      type: 'error'
    })
  } finally {
    addLoading.value = false
  }
}

// 重置添加表单
function resetAddForm() {
  addMode.value = 'single'
  addIntervalTouched.value = false
  addForm.value = {
    room_url: '',
    quality: '原画',
    auto_record: false,
    monitor_enabled: true,
    check_interval: 60,
    notification_enabled: true,
    danmu_enabled: false
  }
  addBatchText.value = ''
}

// 编辑订阅
async function editSubscription(sub) {
  editingSubscription.value = sub
  editIntervalTouched.value = false
  
  // 先设置基础配置
    editForm.value = {
      quality: sub.quality,
      auto_record: sub.auto_record === 'true',
      monitor_enabled: sub.monitor_enabled !== 'false',
      check_interval: sub.check_interval,
      // 默认高级配置
      split_enabled: false,
      split_duration: 3600,
      generate_subtitle: false,
      auto_convert_mp4: true,
      danmu_enabled: false,
      compat_mode: false
    }

  // 尝试加载完整配置
  try {
    const res = await liveApi.getSubscriptionConfig(sub.id)
    if (res.success && res.data) {
      editForm.value = {
        quality: res.data.quality || '原画',
        auto_record: res.data.auto_record === 'true',
        monitor_enabled: res.data.monitor_enabled !== 'false',
        check_interval: res.data.check_interval || 60,
        notification_enabled: res.data.notification_enabled === 'true',
        split_enabled: res.data.split_enabled === 'true',
        split_duration: res.data.split_duration || 3600,
        generate_subtitle: res.data.generate_subtitle || false,
        auto_convert_mp4: res.data.auto_convert_mp4 !== false,
        danmu_enabled: res.data.danmu_enabled === true || res.data.danmu_enabled === 'true',
        compat_mode: res.data.compat_mode === true || res.data.compat_mode === 'true'
      }
    } else {
       // 如果获取高级配置失败，至少回填基础信息中的 notification_enabled
       // sub 对象本身也有 notification_enabled
       editForm.value.notification_enabled = sub.notification_enabled === 'true'
    }
  } catch (e) {
    console.warn('加载高级配置失败:', e)
  }
  
  showEditModal.value = true
}

// 保存订阅
async function saveSubscription() {
  editIntervalTouched.value = true
  if (editForm.value.monitor_enabled && editIntervalError.value) {
    toast.warning(editIntervalError.value)
    return
  }
  editLoading.value = true
  try {
    // 使用新的配置API
    const config = {
      quality: editForm.value.quality,
      auto_record: editForm.value.auto_record ? 'true' : 'false',
      monitor_enabled: editForm.value.monitor_enabled ? 'true' : 'false',
      check_interval: editForm.value.check_interval,
      notification_enabled: editForm.value.notification_enabled ? 'true' : 'false',
      split_enabled: editForm.value.split_enabled ? 'true' : 'false',
      split_duration: editForm.value.split_duration,
      generate_subtitle: editForm.value.generate_subtitle ? 'true' : 'false',
      auto_convert_mp4: editForm.value.auto_convert_mp4 ? 'true' : 'false',
      danmu_enabled: editForm.value.danmu_enabled ? 'true' : 'false',
      compat_mode: editForm.value.compat_mode ? 'true' : 'false'
    }
    
    const res = await liveApi.updateSubscriptionConfig(editingSubscription.value.id, config)
    if (res.success) {
      if (editingSubscription.value.is_recording === 'true') {
        toast.success('保存成功。注意：新的配置将在下次录制时生效。')
      } else {
        toast.success(res.message || '保存成功')
      }
      showEditModal.value = false
      await loadData()
    } else {
      dialog.alert({ message: res.message || '保存失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '保存失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    editLoading.value = false
  }
}

// 确认删除
async function confirmDelete(sub) {
  const confirmed = await dialog.confirm({
    title: '确认删除',
    message: `确定要删除对 <strong>${sub.anchor_name || '该主播'}</strong> 的直播间订阅吗?<br><span style="color: var(--color-text-tertiary); font-size: 0.9em;">如果正在录制，将会停止录制。</span>`,
    type: 'error',
    confirmText: '删除',
    cancelText: '取消'
  })
  
  if (confirmed) {
    deletingSubscription.value = sub
    await deleteSubscription()
    // 如果是从编辑模态框触发的，关闭模态框
    if (showEditModal.value) {
      showEditModal.value = false
    }
  }
}

// 删除订阅
async function deleteSubscription() {
  deleteLoading.value = true
  try {
    const res = await liveApi.deleteLiveSubscription(deletingSubscription.value.id)
    if (res.success) {
      toast.success(res.message || '删除成功')
      await loadData()
    } else {
      dialog.alert({ message: res.message || '删除失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '删除失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    deleteLoading.value = false
  }
}

// 加载录制历史
async function loadHistory(page = 1) {
  historyLoading.value = true
  historyPage.value = page
  
  try {
    const res = await liveApi.getRecordHistory({
      page,
      page_size: historyPageSize.value,
      subscription_id: historyFilterSubId.value
    })
    
    if (res.success) {
      historyRecords.value = res.data
      historyTotal.value = res.total
      historyRecordingCount.value = res.recording_count || 0
      historyJumpPage.value = String(historyPage.value)
      await refreshPendingConvertCount()
    }
  } catch (error) {
    console.error('加载历史失败:', error)
  } finally {
    historyLoading.value = false
  }
}

async function refreshPendingConvertCount() {
  pendingConvertCountLoading.value = true
  try {
    const res = await liveApi.getUnconvertedCount(historyFilterSubId.value)
    if (res.success && res.data) {
      pendingConvertCount.value = Number(res.data.count || 0)
    }
  } catch (error) {
    console.error('获取待转码数量失败:', error)
  } finally {
    pendingConvertCountLoading.value = false
  }
}

function goToHistoryPage() {
  const page = Number(historyJumpPage.value)
  if (!Number.isInteger(page)) {
    toast.error('请输入有效页码')
    return
  }
  if (page < 1 || page > totalHistoryPages.value) {
    toast.error(`页码范围 1-${totalHistoryPages.value}`)
    return
  }
  if (page === historyPage.value) return
  loadHistory(page)
}

function isHistorySelected(recordId) {
  return selectedHistoryIds.value.includes(recordId)
}

function toggleHistorySelection(record) {
  if (!record || record.status === 'recording') return
  const idx = selectedHistoryIds.value.indexOf(record.id)
  if (idx >= 0) {
    selectedHistoryIds.value.splice(idx, 1)
  } else {
    selectedHistoryIds.value.push(record.id)
  }
}

function toggleSelectAllHistoryOnPage() {
  const ids = selectableHistoryIdsOnPage.value
  if (ids.length === 0) return

  if (isAllHistorySelectedOnPage.value) {
    selectedHistoryIds.value = selectedHistoryIds.value.filter(id => !ids.includes(id))
  } else {
    const merged = new Set([...selectedHistoryIds.value, ...ids])
    selectedHistoryIds.value = Array.from(merged)
  }
}

function openBatchDeleteModal() {
  if (selectedHistoryCount.value === 0) return
  batchDeleteFileChecked.value = false
  showBatchDeleteModal.value = true
}

async function executeBatchDelete() {
  if (selectedHistoryCount.value === 0) return
  batchDeleteLoading.value = true
  try {
    const ids = [...selectedHistoryIds.value]
    const results = await Promise.allSettled(
      ids.map(id => liveApi.deleteRecord(id, batchDeleteFileChecked.value))
    )

    let successCount = 0
    let failedCount = 0
    for (const item of results) {
      if (item.status === 'fulfilled' && item.value?.success) {
        successCount += 1
      } else {
        failedCount += 1
      }
    }

    if (successCount > 0) {
      toast.success(`已删除 ${successCount} 条记录`)
    }
    if (failedCount > 0) {
      toast.error(`${failedCount} 条删除失败`)
    }

    selectedHistoryIds.value = []
    showBatchDeleteModal.value = false
    await loadHistory(historyPage.value)
    if (batchDeleteFileChecked.value) {
      await loadData()
    }
  } catch (error) {
    dialog.alert({
      title: '批量删除失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    batchDeleteLoading.value = false
  }
}

// 监听弹窗显示，自动加载
watch(showHistory, (val) => {
  if (val) {
    loadHistory(historyPage.value)
  } else {
    if (route.query.action === 'history') {
      clearHistoryQuery()
    }
    selectedHistoryIds.value = []
    showBatchDeleteModal.value = false
    pendingConvertCount.value = 0
  }
})

onActivated(() => {
  liveStatusWsShouldReconnect = true
  if (licenseValid.value && isLiveRecordRouteActive.value) {
    initWebSocket()
  }
})

onDeactivated(() => {
  stopBulkLoadingState()
  closeLiveStatusWebSocket(false)
  if (liveStatsRefreshTimer) {
    clearTimeout(liveStatsRefreshTimer)
    liveStatsRefreshTimer = null
  }
  // keep-alive 离开页面时关闭播放器，避免直播流在后台继续占用资源
  if (showPlayerModal.value) {
    closePlayer()
  }
})

async function saveRemark() {
  if (!editingRemarkRecord.value) return

  const normalized = String(remarkForm.value || '').trim()
  if (normalized.length > 500) {
    toast.error('备注最多500个字符')
    return
  }

  try {
    remarkLoading.value = true
    const res = await liveApi.updateRecordRemark(editingRemarkRecord.value.id, normalized)
    if (res.success) {
      editingRemarkRecord.value.remark = normalized || null
      toast.success(res.message || '备注已更新')
      showRemarkModal.value = false
      resetRemarkEditor()
    } else {
      dialog.alert({ message: res.message || '备注保存失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '备注保存失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    remarkLoading.value = false
  }
}

// 删除录制记录
function deleteRecord(record) {
  recordToDelete.value = record
  deleteFileChecked.value = false // 每次重置为不勾选
  showDeleteConfirmModal.value = true
}

// 执行删除
async function executeDelete() {
  if (!recordToDelete.value) return
  
  try {
    deleteLoading.value = true
    const res = await liveApi.deleteRecord(recordToDelete.value.id, deleteFileChecked.value)
    
    if (res.success) {
      toast.success(res.message || '删除成功')
      selectedHistoryIds.value = selectedHistoryIds.value.filter(id => id !== recordToDelete.value.id)
      // 刷新列表
      await loadHistory(historyPage.value)
      // 如果开启了删除文件，那可能需要刷新空间统计
      if (deleteFileChecked.value) {
        await loadData() 
      }
      showDeleteConfirmModal.value = false
    } else {
      dialog.alert({ message: res.message || '删除失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '删除失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    deleteLoading.value = false
  }
}

// 一键清空历史记录
// 一键清空历史记录 (打开弹窗)
function clearHistory() {
  clearAllFileChecked.value = false
  showClearAllModal.value = true
}

// 执行清空
async function executeClearAll() {
  clearAllLoading.value = true
  try {
    const res = await liveApi.clearAllRecords(clearAllFileChecked.value, historyFilterSubId.value)
    if (res.success) {
      toast.success(res.message || '历史记录已清空')
      showClearAllModal.value = false
      await loadHistory(1)
      await loadData() // 刷新统计信息
    } else {
      dialog.alert({ message: res.message || '清空失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '操作失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    clearAllLoading.value = false
  }
}

// 转码录制文件为MP4
async function convertRecord(record) {
  const confirmed = await dialog.confirm({
    title: '确认转码',
    message: '确定将此录制转码为MP4格式吗？这可能需要一些时间。',
    type: 'info'
  })
  if (!confirmed) return
  
  try {
    const res = await liveApi.convertToMp4(record.id, true)
    if (res.success) {
      toast.success('转码任务已启动, 请稍后刷新查看')
      await loadHistory(historyPage.value)
    } else {
      dialog.alert({ message: res.message || '转码失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '转码失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  }
}

async function batchConvertHistory() {
  await refreshPendingConvertCount()
  if (pendingConvertCount.value <= 0) {
    toast.error('没有待转码记录')
    return
  }

  const scopeText = historyFilterSubId.value ? '当前主播的全部历史未转码记录' : '全部历史未转码记录'
  const confirmed = await dialog.confirm({
    title: '确认批量转码',
    message: `检测到 ${pendingConvertCount.value} 条待转码记录，确定发起${scopeText}的一键转码吗？`,
    type: 'info'
  })
  if (!confirmed) return

  batchConvertLoading.value = true
  try {
    const res = await liveApi.convertUnconvertedToMp4(historyFilterSubId.value, true)
    if (res.success) {
      toast.success(res.message || '批量转码任务已提交')
      await loadHistory(historyPage.value)
      await refreshPendingConvertCount()
    } else {
      dialog.alert({ message: res.message || '批量转码失败', type: 'error' })
    }
  } catch (error) {
    dialog.alert({
      title: '批量转码失败',
      message: error.response?.data?.detail || error.message,
      type: 'error'
    })
  } finally {
    batchConvertLoading.value = false
  }
}

// 播放直播流
async function playStream(sub) {
  if (['youtube', 'twitch'].includes(String(sub?.platform || '').toLowerCase())) {
    const targetUrl = sub?.room_url || ''
    if (!targetUrl) {
      toast.error(`未找到 ${sub.platform === 'youtube' ? 'YouTube' : 'Twitch'} 直播间地址`)
      return
    }
    window.open(targetUrl, '_blank', 'noopener,noreferrer')
    return
  }

  currentPlayerSub.value = sub
  playingTitle.value = `正在播放: ${sub.anchor_name}`
  showPlayerModal.value = true
  playerLoading.value = true
  playerError.value = ''
  videoMetadata.value = { width: 0, height: 0 }
  
  try {
    const res = await liveApi.getPlayUrl(sub.id)
    if (res.success && res.data) {
      initPlayer(
        res.data.url,
        res.data.format,
        res.data.fallback_url,
        res.data.fallback_format
      )
    } else {
      playerError.value = res.message || '无法获取播放地址'
      playerLoading.value = false
    }
  } catch (error) {
    playerError.value = '请求失败: ' + (error.response?.data?.detail || error.message)
    playerLoading.value = false
  }
}

// 切换直播流
function handleSwitchStream(sub) {
  if (currentPlayerSub.value?.id === sub.id) return
  
  // 先销毁旧播放器
  destroyPlayer()
  
  // 重新加载新直播
  playStream(sub)
}

function initPlayer(url, format, fallbackUrl = '', fallbackFormat = '') {
  destroyPlayer()
  let switchedToFallback = false
  const safeFallbackUrl = fallbackUrl && fallbackUrl !== url ? fallbackUrl : ''
  const safeFallbackFormat = fallbackFormat || (String(safeFallbackUrl).toLowerCase().includes('.m3u8') ? 'm3u8' : 'flv')

  const useFallback = (reason = '') => {
    if (!safeFallbackUrl || switchedToFallback) {
      if (reason && !playerError.value) {
        playerError.value = reason
      }
      playerLoading.value = false
      return false
    }
    switchedToFallback = true
    console.warn(`[LivePreview] FLV 播放失败，切换 m3u8 兜底: ${reason || 'unknown'}`)
    destroyPlayer()
    startPlayback(safeFallbackUrl, safeFallbackFormat, true)
    return true
  }

  // 确保 DOM 已更新
  setTimeout(() => {
    if (!videoPlayer.value) return

    startPlayback(url, format, false)
  }, 100)

  function startPlayback(targetUrl, targetFormat, isFallback) {
    if (!videoPlayer.value) return
    const normalizedFormat = String(targetFormat || '').toLowerCase()

    if (normalizedFormat === 'flv' && mpegts.isSupported()) {
      flvPlayer = mpegts.createPlayer({
        type: 'flv',
        isLive: true,
        url: targetUrl,
        cors: true
      })
      flvPlayer.attachMediaElement(videoPlayer.value)
      flvPlayer.load()
      flvPlayer.play().catch(e => {
        const switched = !isFallback && useFallback(`FLV 预览失败: ${e?.message || e}`)
        if (!switched) {
          playerLoading.value = false
          playerError.value = `播放失败: ${e?.message || e}`
        }
      })

      flvPlayer.on(mpegts.Events.ERROR, (e) => {
        console.error('播放器错误:', e)
        const switched = !isFallback && useFallback(`FLV 预览失败: ${e}`)
        if (!switched) {
          playerLoading.value = false
          if (e === 'NetworkError') {
            playerError.value = '直播流连接断开'
          } else {
            playerError.value = '直播流播放失败'
          }
        }
      })

      flvPlayer.on(mpegts.Events.LOADING_COMPLETE, () => {
        playerLoading.value = false
      })

      // 监听首帧解码，取消 loading
      flvPlayer.on(mpegts.Events.STATISTICS_INFO, () => {
        if (playerLoading.value) playerLoading.value = false
      })
      return
    }
    if (normalizedFormat === 'flv' && !mpegts.isSupported()) {
      const switched = !isFallback && useFallback('当前浏览器不支持 FLV 播放')
      if (!switched) {
        playerLoading.value = false
        playerError.value = '当前浏览器不支持 FLV 播放'
      }
      return
    }

    if (normalizedFormat === 'm3u8') {
      if (Hls.isSupported()) {
        hlsPlayer = new Hls({
          enableWorker: true,
          lowLatencyMode: true,
        })
        hlsPlayer.loadSource(targetUrl)
        hlsPlayer.attachMedia(videoPlayer.value)
        hlsPlayer.on(Hls.Events.MANIFEST_PARSED, () => {
          videoPlayer.value.play().catch((e) => {
            console.warn('自动播放被阻止:', e)
          })
          playerLoading.value = false
        })
        hlsPlayer.on(Hls.Events.ERROR, (_event, data) => {
          if (!data?.fatal) return
          console.error('HLS 播放器错误:', data)
          playerLoading.value = false
          playerError.value = `HLS 播放失败: ${data?.details || '未知错误'}`
        })
        return
      }

      if (videoPlayer.value.canPlayType('application/vnd.apple.mpegurl')) {
        videoPlayer.value.src = targetUrl
        videoPlayer.value.play().catch((e) => {
          console.warn('自动播放被阻止:', e)
        })
        playerLoading.value = false
        return
      }

      playerLoading.value = false
      playerError.value = '当前浏览器不支持 m3u8 播放'
      return
    }

    videoPlayer.value.src = targetUrl
    videoPlayer.value.play().catch((e) => {
      console.warn('自动播放被阻止:', e)
    })
    playerLoading.value = false
  }
}

function closePlayer() {
  if (document.fullscreenElement && document.exitFullscreen) {
    document.exitFullscreen().catch(() => {})
  }
  showPlayerModal.value = false
  stopLiveTripleScreenLoop()
  closeLiveDanmuSocket()
  resetLiveDanmuBuffer()
  destroyPlayer()
  currentPlayerSub.value = null
}

function destroyPlayer() {
  stopLiveTripleScreenLoop()
  if (flvPlayer) {
    try {
      flvPlayer.pause()
      flvPlayer.unload()
      flvPlayer.detachMediaElement()
      flvPlayer.destroy()
    } catch (e) {
      console.warn(e)
    }
    flvPlayer = null
  }
  if (hlsPlayer) {
    try {
      hlsPlayer.destroy()
    } catch (e) {
      console.warn(e)
    }
    hlsPlayer = null
  }
  if (videoPlayer.value) {
    try {
      videoPlayer.value.pause()
    } catch (e) {
      console.warn(e)
    }
    videoPlayer.value.src = ''
  }
}

function retryPlay() {
  if (currentPlayerSub.value) {
    playStream(currentPlayerSub.value)
  }
}

function formatSize(bytes) {
  return formatBytes(bytes, 2)
}

function formatDuration(seconds) {
  if (!seconds) return '--'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

function formatDate(dateStr) {
  if (!dateStr) return '--'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function getPlatformName(platform) {
  const names = {
    'douyin': '抖音直播',
    'douyu': '斗鱼直播',
    'bilibili': 'B站直播',
    'huya': '虎牙直播',
    'xhs': '小红书直播',
    'youtube': 'YouTube直播',
    'migu': '咪咕直播',
    'kuaishou': '快手直播',
    'cc': '网易CC直播',
    'twitch': 'Twitch直播'
  }
  return names[platform] || platform
}

function sanitizeAnchorName(name) {
  const text = String(name || '未知')
  return text.replace(/\s+/g, ' ').trim() || '未知'
}

function getStatusText(status) {
  const texts = {
    'recording': '录制中',
    'completed': '已完成',
    'failed': '失败',
    'stopped': '已停止'
  }
  return texts[status] || status
}
</script>

<style scoped>
.live-record-page {
  padding: var(--spacing-lg);
  overflow-x: hidden;
}

/* 播放器侧边栏切换布局 */
:global(.player-modal:not(.player-modal-light)) .modal-body {
  padding: 0;
  overflow: hidden;
  background: var(--color-bg-card) !important;
  max-height: none; /* 移除 Modal 组件默认的 70vh 限制 */
}

:global(.player-modal:not(.player-modal-light)) .modal-container {
  background: var(--color-bg-card) !important;
}

:global(.player-modal:not(.player-modal-light)) .modal-header {
  background: var(--color-bg-card) !important;
  border-bottom: 1px solid var(--color-border) !important;
  color: var(--color-text-primary) !important;
}

:global(.player-modal:not(.player-modal-light)) .modal-header .header-content h3 {
  color: var(--color-text-primary) !important;
}

:global(.player-modal:not(.player-modal-light)) .close-btn {
  color: var(--color-text-tertiary) !important;
}

:global(.player-modal:not(.player-modal-light)) .close-btn:hover {
  color: var(--color-text-primary) !important;
  background: var(--color-bg-hover) !important;
}

:global(.player-modal:not(.player-modal-light)) .modal-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--color-border) !important;
  background: var(--color-bg-secondary) !important;
}

/* 查看直播全屏布局：移动端全屏，桌面端不遮左侧栏 */
:global(.player-modal--fullscreen.modal-overlay) {
  padding: 0 !important;
  align-items: stretch !important;
  justify-content: stretch !important;
  background: transparent !important;
  top: var(--header-height) !important;
  left: var(--sidebar-width) !important;
  right: auto !important;
  width: calc(100vw - var(--sidebar-width)) !important;
  height: calc(100vh - var(--header-height)) !important;
}

:global(.player-modal--fullscreen .modal-container) {
  width: 100% !important;
  height: 100% !important;
  max-width: 100% !important;
  max-height: 100% !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  background: var(--color-bg-card);
  display: flex;
  flex-direction: column;
}

:global(.player-modal--fullscreen .modal-header) {
  display: none !important;
}

:global(.player-modal--fullscreen .modal-body) {
  flex: 1 1 auto !important;
  height: auto !important;
  max-height: none !important;
  background: var(--color-bg-secondary) !important;
  min-height: 0;
}

:global(.player-modal--fullscreen .modal-body.modal-body-fill) {
  display: flex;
  flex-direction: column;
}

@media (max-width: 768px) {
  :global(.player-modal--fullscreen.modal-overlay) {
    top: var(--header-height) !important;
    left: 0 !important;
    width: 100vw !important;
    height: calc(100dvh - var(--header-height)) !important;
  }

  :global(.player-modal--fullscreen .modal-container) {
    height: calc(100dvh - var(--header-height)) !important;
    max-height: calc(100dvh - var(--header-height)) !important;
  }

  :global(.player-modal--fullscreen .modal-footer) {
    padding: 8px 10px calc(8px + env(safe-area-inset-bottom, 0px)) !important;
    min-height: 54px;
  }
}

.player-layout {
  display: flex;
  position: relative;
  height: 60vh;
  min-height: 480px;
  background: var(--color-bg-secondary);
  align-items: stretch;
}

:global(.player-modal--fullscreen .player-layout) {
  height: 100% !important;
  min-height: 0 !important;
  width: 100% !important;
  flex: 1 1 auto !important;
}

.player-main {
  flex: 1;
  position: relative;
  background: var(--color-bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.player-danmu-column {
  width: 260px;
  background: var(--color-bg-card);
  border-left: 1px solid var(--color-border);
  border-right: none;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.player-sidebar {
  width: 220px;
  background: var(--color-bg-card);
  border-left: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  z-index: 10;
  height: 100%;
  transition: transform 0.22s ease, opacity 0.22s ease;
  transform: translateX(0);
  opacity: 1;
  will-change: transform, opacity;
}

:global(.player-fullscreen-root:fullscreen .player-sidebar) {
  position: absolute;
  right: 0;
  top: 0;
  height: 100%;
}

.player-sidebar.is-hidden {
  transform: translateX(100%);
  opacity: 0;
  pointer-events: none;
}

@media (max-width: 1200px) {
  .player-danmu-column {
    width: 220px;
  }

  .player-sidebar {
    width: 200px;
  }
}

.sidebar-header {
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  gap: 10px;
}

.live-status-dot {
  width: 8px;
  height: 8px;
  background-color: #ef4444;
  border-radius: 50%;
  position: relative;
  display: inline-block;
}

.live-status-dot::after {
  content: '';
  position: absolute;
  top: -2px;
  left: -2px;
  right: -2px;
  bottom: -2px;
  border: 1px solid #ef4444;
  border-radius: 50%;
  animation: live-dot-pulse 2s infinite;
}

@keyframes live-dot-pulse {
  0% { transform: scale(1); opacity: 0.8; }
  100% { transform: scale(2.2); opacity: 0; }
}

.sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

/* 自定义滚动条 */
.sidebar-list::-webkit-scrollbar {
  width: 4px;
}
.sidebar-list::-webkit-scrollbar-track {
  background: transparent;
}
.sidebar-list::-webkit-scrollbar-thumb {
  background: #444;
  border-radius: 2px;
}

.sidebar-item {
  display: flex;
  align-items: center;
  padding: 10px 16px;
  gap: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

.sidebar-item:hover {
  background: var(--color-bg-hover);
}

.sidebar-item.active {
  background: var(--color-bg-tertiary);
}

.item-avatar {
  position: relative;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
}

.item-avatar img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  border: 1.5px solid var(--color-border);
}

.sidebar-item.active img {
  border-color: transparent;
}

.item-avatar .avatar-placeholder {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: var(--color-bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  color: var(--color-text-tertiary);
}

.playing-ring {
  position: absolute;
  top: -3px;
  left: -3px;
  right: -3px;
  bottom: -3px;
  border: 2px solid #fe2c55;
  border-radius: 50%;
  animation: live-breath 1.5s infinite ease-in-out;
  z-index: 1;
}

.playing-badge {
  position: absolute;
  bottom: -4px;
  left: 50%;
  transform: translateX(-50%);
  background: linear-gradient(to right, #fe2c55, #ff4d7d);
  color: white;
  font-size: 9px;
  padding: 0px 4px;
  border-radius: 4px;
  font-weight: 700;
  white-space: nowrap;
  z-index: 5;
  border: 1px solid #1a1a1a;
  line-height: 1.4;
}

.item-info {
  flex: 1;
  min-width: 0;
}

.item-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.sidebar-item.active .item-name {
  color: var(--color-text-primary);
}

.item-meta {
  display: flex;
  gap: 6px;
  align-items: center;
}

.p-tag {
  font-size: 10px;
  padding: 0px 4px;
  border-radius: 3px;
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.tag-douyin { color: #fe2c55; background: rgba(254, 44, 85, 0.1); }
.tag-douyu { color: #ff6a00; background: rgba(255, 106, 0, 0.12); }
.tag-bilibili { color: #00aeec; background: rgba(0, 174, 236, 0.1); }
.tag-huya { color: #ff8c00; background: rgba(255, 140, 0, 0.1); }
.tag-xhs { color: #ff2442; background: rgba(255, 36, 66, 0.1); }
.tag-youtube { color: #ff0000; background: rgba(255, 0, 0, 0.1); }
.tag-migu { color: #1d8ef7; background: rgba(29, 142, 247, 0.12); }
.tag-kuaishou { color: #ff6600; background: rgba(255, 102, 0, 0.12); }
.tag-cc { color: #0d91e9; background: rgba(13, 145, 233, 0.1); }

.q-tag {
  font-size: 10px;
  color: var(--color-text-tertiary);
}

/* 响应式适配 */
@media (max-width: 768px) {
  .player-layout {
    flex-direction: column;
    height: min(56dvh, 440px) !important;
    min-height: 280px;
  }
  
  .player-main {
    flex: 1;
    min-height: 0;
    max-height: 100%;
    background: #000;
  }
  
  .player-danmu-column {
    width: 100%;
    height: 160px;
    border-left: none;
    border-right: none;
    border-top: 1px solid #1f2937;
    border-bottom: 1px solid #1f2937;
  }
  
  .player-sidebar {
    width: 100%;
    border-left: none;
    border-top: 1px solid #333;
    height: 112px;
    flex-shrink: 0;
  }

  .sidebar-header {
    display: none; /* 移动端隐藏标题栏以节省空间 */
  }
  
  .sidebar-list {
    display: flex;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 8px 10px;
    gap: 8px;
    align-items: flex-start; /* 防止子项拉伸高度 */
  }
  
  .sidebar-item {
    flex-direction: column;
    width: 64px;
    padding: 0;
    flex-shrink: 0;
    text-align: center;
    align-items: center;
    gap: 6px;
    background: transparent !important; /* 移除移动端背景块 */
    border: none !important;
  }
  
  .sidebar-item:hover {
    background: transparent;
  }
  
  .item-avatar {
    width: 42px;
    height: 42px;
    margin: 0 auto;
  }
  
  .item-info {
    width: 100%;
    min-width: 0;
  }

  .item-meta {
    display: flex;
    justify-content: center;
    width: 100%;
    margin-top: -2px;
  }

  .item-name {
    font-size: 10px;
    width: 100%;
    max-width: 100%;
    display: block;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.2;
    margin-bottom: 1px;
  }

  .item-meta .q-tag {
    display: none;
  }

  .item-meta .p-tag {
    font-size: 9px;
    line-height: 1;
    padding: 2px 5px;
    border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.18);
    background: rgba(17, 24, 39, 0.6);
    color: rgba(255, 255, 255, 0.9);
  }

  .sidebar-list::-webkit-scrollbar {
    height: 3px;
  }
}

@media (max-width: 375px) {
  .sidebar-item {
    width: 68px;
  }
}

.stats-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  margin-bottom: 24px;
}

@media (max-width: 1024px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}

.stat-card {
  min-width: 120px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
}

.stat-card.recording {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.08), rgba(220, 38, 38, 0.04));
  border-color: rgba(239, 68, 68, 0.3);
}

.stat-card.live {
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.08), rgba(22, 163, 74, 0.04));
  border-color: rgba(34, 197, 94, 0.28);
}

.stat-icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

.stat-icon.pulse {
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.stat-content h3 {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-text-primary);
  margin: 0;
  line-height: 1.2;
}

.storage-size {
  display: inline-flex;
  align-items: baseline;
  justify-content: center;
  gap: 4px;
  max-width: 100%;
}

.storage-size-number {
  min-width: 0;
}

.storage-size-unit {
  font-size: 0.62em;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--color-text-secondary);
}



.stat-main {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.stat-total {
  font-size: 14px;
  color: var(--color-text-tertiary);
  font-weight: 500;
}

.stat-card.storage-card.battery-card-style {
  position: relative;
  border: 2px solid var(--color-border);
  border-radius: 12px;
  overflow: visible; /* Show battery tip */
  background: var(--color-bg-card);
  padding: 0; /* padding handled by content */
  transition: all 0.3s ease;
}

.stat-card.storage-card.battery-card-style::after {
  content: '';
  position: absolute;
  top: 50%;
  right: -7px;
  transform: translateY(-50%);
  width: 5px;
  height: 24px;
  background: var(--color-border);
  border-radius: 0 4px 4px 0;
  transition: background-color 0.3s ease;
}

/* Hover effect highlights border and tip */
.stat-card.storage-card.battery-card-style:hover {
  border-color: var(--color-text-secondary);
}
.stat-card.storage-card.battery-card-style:hover::after {
  background: var(--color-text-secondary);
}

.battery-bg-fill {
  position: absolute;
  top: 3px;
  left: 3px;
  bottom: 3px;
  border-radius: 9px;
  transition: width 0.3s ease;
  z-index: 0;
  max-width: calc(100% - 6px);
}

.battery-bg-fill.normal { background: rgba(39, 174, 96, 0.15); }
.battery-bg-fill.caution { background: rgba(241, 196, 15, 0.15); }
.battery-bg-fill.warning { background: rgba(230, 126, 34, 0.15); }
.battery-bg-fill.critical { background: rgba(231, 76, 60, 0.15); }

.stat-content.relative-z {
  position: relative;
  z-index: 1;
  padding: 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.stat-footer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 4px;
}

.stat-percent-large {
  font-weight: 700;
  font-size: 14px;
}

.stat-percent-large.normal { color: #27ae60; }
.stat-percent-large.caution { color: #f1c40f; }
.stat-percent-large.warning { color: #e67e22; }
.stat-percent-large.critical { color: #e74c3c; }

.stat-percent {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-tertiary);
  min-width: 30px;
  text-align: right;
}

.stat-content p {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin: 4px 0 0 0;
}

/* 操作栏 */
.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  gap: 16px;
  flex-wrap: wrap;
}

.action-left, .action-right {
  display: flex;
  gap: 12px;
  align-items: center;
}

.filter-group {
  display: flex;
  gap: 8px;
}

.form-select.filter-select {
  padding: 0 32px 0 12px;
  height: 36px;
  line-height: 36px;
  font-size: 13px;
  min-width: 110px;
  border-radius: var(--radius-md);
  border-color: var(--color-border);
  background-color: var(--color-bg-secondary);
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
}

.action-left .btn {
  gap: 0;
}

/* 直播间列表 */
.rooms-section {
  background: transparent;
  border: none;
  padding: 0;
}

.loading-container {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px 0;
  color: var(--color-text-secondary);
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--color-text-secondary);
}

.empty-state h3 {
  margin: 16px 0 8px;
  color: var(--color-text-primary);
}

/* 直播间网格 */
.rooms-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--spacing-md);
}

@media (min-width: 1400px) {
  .rooms-grid {
    grid-template-columns: repeat(5, 1fr);
  }
}

@media (max-width: 1399px) and (min-width: 1200px) {
  .rooms-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 1199px) and (min-width: 900px) {
  .rooms-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 899px) and (min-width: 600px) {
  .rooms-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 直播间卡片基础样式 */
.room-card {
  position: relative;
  background: var(--color-bg-card);
  border-radius: var(--radius-xl);
  border: 1px solid var(--color-border);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  padding: 16px 16px 16px 28px;
  gap: 12px;
  min-height: 180px; /* 保持紧凑基线高度 */
  height: auto; /* 内容增多时自动扩展，避免按钮被遮挡 */
  content-visibility: auto; /* 浏览器渲染优化 */
  contain-intrinsic-size: 220px; /* 预估高度 */
}

.room-card:hover {
  border-color: var(--color-primary-light);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

/* 移除了性能开销巨大的 filter: blur 动态光晕，改用高效的 CSS Box Shadow */
.room-card.is-live {
  border-color: rgba(34, 197, 94, 0.4);
  box-shadow: 0 0 15px rgba(34, 197, 94, 0.12);
}

.room-card.is-recording {
  border-color: rgba(239, 68, 68, 0.4);
  box-shadow: 0 0 15px rgba(239, 68, 68, 0.12);
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

.status-dot.status-auto-on {
  background: #22c55e;
  box-shadow: 0 0 5px rgba(34, 197, 94, 0.4);
}

.status-dot.status-auto-off {
  background: #f59e0b;
}

.status-dot.status-monitor-paused {
  background: #ef4444;
  box-shadow: 0 0 5px rgba(239, 68, 68, 0.42);
}

/* 卡片主内容区 */
.card-main-body {
  position: relative;
  z-index: 1;
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.info-area {
  flex: 1;
  min-width: 0;
}

/* 侧边头像布局 */
.avatar-side {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  width: 64px;
}

.avatar-link {
  text-decoration: none;
  display: block;
  outline: none;
  position: relative;
}

.avatar-link.is-live {
  padding: 4px;
  margin: -4px;
}

.avatar-container {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  overflow: hidden;
  background: var(--color-bg-tertiary);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease;
  position: relative;
  z-index: 2;
  border: 2px solid transparent;
}

/* 呼吸光圈效果 */
.is-live .live-ring {
  position: absolute;
  top: -3px;
  left: -3px;
  right: -3px;
  bottom: -3px;
  border: 2px solid #fe2c55;
  border-radius: 50%;
  animation: live-breath 1.5s infinite ease-in-out;
  z-index: 1;
}

@keyframes live-breath {
  0% {
    transform: scale(0.98);
    opacity: 0.8;
    box-shadow: 0 0 0 0 rgba(254, 44, 85, 0.7);
  }
  50% {
    transform: scale(1.02);
    opacity: 1;
    box-shadow: 0 0 0 6px rgba(254, 44, 85, 0);
  }
  100% {
    transform: scale(0.98);
    opacity: 0.8;
    box-shadow: 0 0 0 0 rgba(254, 44, 85, 0);
  }
}

.live-label {
  position: absolute;
  bottom: -6px;
  left: 50%;
  transform: translateX(-50%);
  background: linear-gradient(to right, #fe2c55, #ff4d7d);
  color: white;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 700;
  white-space: nowrap;
  z-index: 5;
  border: 1.5px solid #fff;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.avatar-link:hover .avatar-container {
  transform: scale(1.04);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
}

.avatar {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text-secondary);
}

.name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  min-width: 0;
  padding-right: 44px; /* 为右上角绝对定位的按钮预留空间 */
}

.name-link {
  flex: 1;
  min-width: 0;
  display: block;
}

.name-link .room-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text-primary);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  transition: color 0.2s ease;
  max-width: 100%;
  mask-image: linear-gradient(to right, #000 0%, #000 88%, transparent 100%);
  -webkit-mask-image: linear-gradient(to right, #000 0%, #000 88%, transparent 100%);
}

.room-name-track {
  display: inline-flex;
  align-items: center;
  min-width: 100%;
}

.room-name-text {
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.room-name-clone {
  display: none;
}

.name-link .room-name.is-marquee .room-name-track {
  min-width: max-content;
  animation: live-room-name-marquee 9s linear infinite;
}

.name-link .room-name.is-marquee:hover .room-name-track {
  animation-play-state: paused;
}

.name-link .room-name.is-marquee .room-name-text {
  overflow: visible;
  text-overflow: clip;
  max-width: none;
  flex-shrink: 0;
}

.name-link .room-name.is-marquee .room-name-clone {
  display: inline-block;
  padding-left: 32px;
}

@keyframes live-room-name-marquee {
  0%, 12% {
    transform: translateX(0);
  }
  88%, 100% {
    transform: translateX(calc(-50% - 16px));
  }
}

.platform-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 6px;
  font-weight: 600;
  background: rgba(0, 0, 0, 0.05);
  color: var(--color-text-secondary);
  flex-shrink: 0;
}

.name-link:hover .room-name {
  color: var(--color-primary);
}

.room-metrics {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 8px; /* 降低为8px，因为设置按钮在title行，title行已有44px右边距 */
}

.metric-item {
  font-size: 13px;
  color: var(--color-text-tertiary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.metric-item.highlight {
  color: #ef4444;
  font-weight: 600;
}

.liv.recording-text {
  color: #ff4d4f;
  font-weight: 600;
  animation: pulse 2s infinite;
}

.recording-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
  width: 100%;
}

.recording-row-main {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  color: #ff4d4f;
  font-weight: 600;
  white-space: nowrap;
}

.recording-duration {
  font-family: Consolas, Monaco, "Courier New", Courier, monospace;
  font-variant-numeric: tabular-nums;
  display: inline-block;
  min-width: 60px;
  text-align: center;
}

.recording-size {
  font-family: Consolas, Monaco, "Courier New", Courier, monospace;
  font-variant-numeric: tabular-nums;
  display: inline-block;
  min-width: 45px;
  text-align: left;
}

.recording-row-sub {
  display: flex;
  align-items: center;
  gap: 3px; /* 降低间距，防止文字和标签溢出卡片 */
  font-size: 11px;
  color: var(--color-text-tertiary);
  opacity: 0.8;
  white-space: nowrap;
}

.quality-label {
  opacity: 0.7;
}

.quality-value {
  color: #ff4d4f;
  font-weight: 500;
  background: rgba(255, 77, 79, 0.08);
  padding: 1px 4px; /* 缩减左右边距 */
  border-radius: 4px;
  border: 1px solid rgba(255, 77, 79, 0.15);
}

.getting-info {
  font-size: 10px;
  opacity: 0.6;
  font-style: italic;
}

.recording-text {
  animation: pulse 2s infinite;
}

.danmu-badge-mini {
  font-size: 10px;
  color: #0ea5e9;
  background: rgba(14, 165, 233, 0.08);
  padding: 1.5px 4px; /* 缩减边距 */
  border-radius: 4px;
  border: 1px solid rgba(14, 165, 233, 0.25);
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  line-height: 1;
  transition: all 0.3s ease;
}

.danmu-badge-mini.is-recording {
  background: rgba(14, 165, 233, 0.15);
  border-color: rgba(14, 165, 233, 0.45);
  animation: pulse-danmu 2s infinite;
}

@keyframes pulse-danmu {
  0% {
    box-shadow: 0 0 0 0 rgba(14, 165, 233, 0.2);
    opacity: 1;
  }
  50% {
    box-shadow: 0 0 0 4px rgba(14, 165, 233, 0);
    opacity: 0.7;
  }
  100% {
    box-shadow: 0 0 0 0 rgba(14, 165, 233, 0.2);
    opacity: 1;
  }
}

.compat-badge-mini {
  font-size: 10px;
  color: #e96a2e;
  background: rgba(233, 106, 46, 0.08);
  padding: 1.5px 4px; /* 缩减边距 */
  border-radius: 4px;
  border: 1px solid rgba(233, 106, 46, 0.25);
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  line-height: 1;
  transition: all 0.3s ease;
}

.compat-badge-mini.is-recording {
  background: rgba(233, 106, 46, 0.15);
  border-color: rgba(233, 106, 46, 0.45);
  animation: pulse-compat 2s infinite;
}

@keyframes pulse-compat {
  0% {
    box-shadow: 0 0 0 0 rgba(233, 106, 46, 0.2);
    opacity: 1;
  }
  50% {
    box-shadow: 0 0 0 4px rgba(233, 106, 46, 0);
    opacity: 0.7;
  }
  100% {
    box-shadow: 0 0 0 0 rgba(233, 106, 46, 0.2);
    opacity: 1;
  }
}

.live-status-text {
  color: #22c55e;
  font-weight: 600;
}

.dot {
  opacity: 0.5;
}

/* 操作按钮 */
.room-actions {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--color-border);
  overflow: visible;
}

.room-action-row {
  display: grid;
  gap: 6px;
}

.room-action-row.primary {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.room-action-row.secondary {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.room-action-row .btn {
  min-width: 0;
  width: 100%;
  white-space: nowrap;
  padding: 0 10px;
}

[data-theme="dark"] .room-actions {
  border-top-color: rgba(255, 255, 255, 0.05);
}

[data-theme="dark"] .room-actions .btn-danger {
  background: rgba(248, 113, 113, 0.16);
  color: #fecaca;
  border: 1px solid rgba(252, 165, 165, 0.45);
}

[data-theme="dark"] .room-actions .btn-danger:hover:not(:disabled) {
  background: rgba(248, 113, 113, 0.24);
  color: #fee2e2;
  border-color: rgba(252, 165, 165, 0.62);
}

[data-theme="dark"] .room-actions .btn-success {
  background: rgba(74, 222, 128, 0.16);
  color: #bbf7d0;
  border: 1px solid rgba(134, 239, 172, 0.45);
}

[data-theme="dark"] .room-actions .btn-success:hover:not(:disabled) {
  background: rgba(74, 222, 128, 0.24);
  color: #dcfce7;
  border-color: rgba(134, 239, 172, 0.62);
}

[data-theme="dark"] .room-actions .btn-primary {
  background: rgba(251, 146, 60, 0.18);
  color: #fed7aa;
  border: 1px solid rgba(253, 186, 116, 0.52);
}

[data-theme="dark"] .room-actions .btn-primary:hover:not(:disabled) {
  background: rgba(251, 146, 60, 0.26);
  color: #ffedd5;
  border-color: rgba(253, 186, 116, 0.68);
}

[data-theme="dark"] .room-actions .btn-secondary {
  background: rgba(148, 163, 184, 0.14);
  color: #e2e8f0;
  border: 1px solid rgba(148, 163, 184, 0.4);
}

[data-theme="dark"] .room-actions .btn-secondary:hover:not(:disabled) {
  background: rgba(148, 163, 184, 0.22);
  color: #f1f5f9;
  border-color: rgba(148, 163, 184, 0.58);
}

[data-theme="dark"] .room-actions .btn-outline {
  background: rgba(251, 191, 36, 0.1);
  color: #fde68a;
  border: 1px solid rgba(252, 211, 77, 0.5);
}

[data-theme="dark"] .room-actions .btn-outline:hover:not(:disabled) {
  background: rgba(251, 191, 36, 0.18);
  color: #fef3c7;
  border-color: rgba(252, 211, 77, 0.72);
}

[data-theme="dark"] .bulk-actions .btn-danger,
[data-theme="dark"] .tool-grid .btn-danger {
  background: rgba(248, 113, 113, 0.16);
  color: #fecaca;
  border: 1px solid rgba(252, 165, 165, 0.45);
  box-shadow: none;
}

[data-theme="dark"] .bulk-actions .btn-danger:hover:not(:disabled),
[data-theme="dark"] .tool-grid .btn-danger:hover:not(:disabled) {
  background: rgba(248, 113, 113, 0.24);
  color: #fee2e2;
  border-color: rgba(252, 165, 165, 0.62);
}

[data-theme="dark"] .platform-badge {
  background: rgba(255, 255, 255, 0.1);
}

/* 状态标签 */
.status-badges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.badge {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 100px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.badge-live {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}

.badge-offline {
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
}

.badge-recording {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.live-dot {
  width: 6px;
  height: 6px;
  background: currentColor;
  border-radius: 50%;
  animation: pulse 1s ease-in-out infinite;
}

.recording-icon {
  animation: pulse 1s ease-in-out infinite;
}

/* 主播信息 */
.bulk-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.bulk-actions .btn {
  padding: 4px 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  border-radius: 8px;
  transition: all 0.2s ease;
  white-space: nowrap; /* 核心：防止文字垂直 */
}

/* 一键开启 - 优雅绿 */
.btn-outline-success {
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.3);
  background: rgba(16, 185, 129, 0.05);
}

.btn-outline-success:hover {
  background: #10b981;
  color: white;
  border-color: #10b981;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
}

/* 一键关闭 - 警示红 */
.btn-outline-danger {
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.2);
  background: rgba(239, 68, 68, 0.05);
}

.btn-outline-danger:hover {
  background: #ef4444;
  color: white;
  border-color: #ef4444;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.3);
}

.bulk-toggle-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.bulk-toggle-desc {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.bulk-toggle-actions {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

/* 移动端特殊优化 */
@media (max-width: 768px) {
  .live-record-page {
    padding: 0;
  }

  .action-bar {
    flex-direction: column;
    gap: 8px;
    margin-bottom: 12px;
    align-items: stretch;
  }

  /* Row 1 */
  .action-left {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 8px;
    width: 100%;
  }

  .action-left .btn {
    width: 100%;
    justify-content: center;
    padding: 8px 0;
    font-size: 14px;
    height: 38px;
  }

  /* Container for Row 2 & 3 */
  .action-right {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    width: 100%;
  }

  /* Row 2: Bulk Actions (Span 1) + Backup Actions (Span 1) */
  .bulk-actions {
    grid-row: 1;
    grid-column: 1;
    background: var(--color-bg-tertiary);
    padding: 2px 6px;
    border-radius: 8px;
    display: flex;
    gap: 4px;
    margin: 0;
    border: none;
    align-items: center;
    height: 32px;
  }

  .bulk-actions .btn {
    flex: 1;
    font-size: 12px;
    padding: 0;
    height: 26px;
    white-space: nowrap;
  }

  .live-backup-actions {
    grid-row: 1;
    grid-column: 2;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px;
  }

  .live-backup-actions .btn {
    width: 100%;
    justify-content: center;
    font-size: 12px;
    padding: 0;
    height: 32px;
    white-space: nowrap;
  }

  /* Row 3: Filter Group (Full Width) */
  .filter-group {
    grid-row: 2;
    grid-column: 1 / span 2;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    width: 100%;
  }

  .form-select.filter-select {
    width: 100% !important;
    min-width: 0 !important;
    height: 36px;
    font-size: 13px;
  }
}

.room-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.room-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  overflow: hidden;
  background: var(--color-bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar-placeholder {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.room-details {
  min-width: 0;
}

.room-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0;
}

.room-platform {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin: 2px 0 0 0;
}

/* 录制信息 */
.recording-info {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.08);
  border-radius: var(--radius-sm);
}

.info-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* 设置信息 */
.room-settings {
  display: flex;
  gap: 12px;
}

.setting-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--color-text-tertiary);
  padding: 4px 8px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-sm);
}

.setting-item.auto-enabled {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}

.offline-status-text {
  color: var(--color-text-tertiary);
  font-weight: 600;
}

.paused-status-text {
  color: #f59e0b;
  font-weight: 600;
}

.monitoring-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-primary);
  opacity: 0.9;
  margin: 2px 0 0 0;
  font-weight: 500;
}

.monitoring-row {
  display: flex;
  width: 100%;
}

.spin-slow {
  animation: spin 3s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.status-badge-container {
  display: flex;
  align-items: center;
}

/* 桌面端卡片布局微调：提升信息区可读性与按钮区对齐 */
@media (min-width: 769px) {
  .rooms-grid {
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  }

  .room-card {
    padding: 14px 14px 14px 20px;
    gap: 10px;
    min-height: 196px;
  }

  .status-dot {
    top: 10px;
    left: 10px;
  }

  .card-top-actions {
    top: 8px;
    right: 8px;
  }

  .card-main-body {
    gap: 12px;
  }

  .avatar-side {
    width: 60px;
    gap: 6px;
  }

  .avatar-container {
    width: 60px;
    height: 60px;
  }

  .name-row {
    margin-bottom: 6px;
    padding-right: 36px;
  }

  .platform-badge {
    font-size: 10px;
    padding: 2px 5px;
  }

  .room-name {
    font-size: 15px;
  }

  .room-metrics {
    gap: 6px;
    padding-right: 0;
    min-width: 0;
  }

  .metric-item {
    font-size: 12px;
    min-width: 0;
    flex-wrap: nowrap;
  }

  .metric-item > span {
    white-space: nowrap;
  }

  .status-badge-container {
    flex-shrink: 0;
    min-width: max-content;
  }

  .live-status-text,
  .offline-status-text {
    white-space: nowrap;
    writing-mode: horizontal-tb;
  }

  .recording-row-main,
  .recording-row-sub {
    white-space: nowrap;
  }

  .room-actions {
    gap: 8px;
    padding-top: 9px;
  }

  .room-action-row {
    gap: 8px;
  }

  .room-action-row .btn {
    height: 34px;
    padding: 0 10px;
    line-height: 1;
  }
}

/* 表单 */
.add-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
}

.form-input, .form-select {
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  font-size: 14px;
}

.form-textarea {
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  font-size: 14px;
  resize: vertical;
  min-height: 120px;
}

.form-input:focus, .form-select:focus {
  outline: none;
  border-color: var(--color-primary);
}
.form-input-error {
  border-color: var(--color-error) !important;
}

.form-textarea:focus {
  outline: none;
  border-color: var(--color-primary);
}

.form-hint {
  font-size: 12px;
  color: var(--color-text-tertiary);
  margin: 0;
}
.form-error {
  font-size: 12px;
  color: var(--color-error);
  margin: 0;
}

.form-static {
  font-size: 14px;
  color: var(--color-text-primary);
  margin: 0;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 14px;
}

.checkbox-label input {
  width: 16px;
  height: 16px;
}

.mode-toggle {
  display: flex;
  gap: 6px;
  padding: 4px;
  border-radius: 10px;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
}

.mode-btn {
  flex: 1;
  padding: 6px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 13px;
  cursor: pointer;
}

.mode-btn.active {
  background: var(--color-primary);
  color: #fff;
}

/* 表单分隔线 */
.form-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 8px 0;
  color: var(--color-text-tertiary);
  font-size: 12px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.form-divider::before,
.form-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--color-border);
}

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
  white-space: nowrap;
}

.feature-item .icon {
  color: var(--color-success);
}

@media (max-width: 768px) {
  .license-alert {
    padding: 24px 18px;
    margin: 20px 16px;
    border-radius: 18px;
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
    grid-template-columns: 1fr;
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

.page-content {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
}

/* 历史记录 */
.history-container {
  min-height: 300px;
}

.history-content {
  position: relative;
}

.history-loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.55);
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 13px;
  color: var(--color-text-secondary);
  pointer-events: none;
}

.history-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 1320px;
  table-layout: auto;
}

.history-table th,
.history-table td {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px solid var(--color-border);
  font-size: 14px;
}

.history-table th {
  font-weight: 600;
  color: var(--color-text-secondary);
  background: var(--color-bg-secondary);
}

.history-table th:nth-child(8),
.history-table td:nth-child(8) {
  width: 340px;
  overflow: hidden;
}

.actions-cell {
  display: flex;
  gap: 6px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.history-table td:nth-child(6) {
  white-space: nowrap;
}

.h-select-checkbox {
  margin-right: 2px;
}

.remark-cell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.remark-cell .btn {
  flex-shrink: 0;
  width: 52px;
  text-align: center;
}

.remark-text {
  flex: 1;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.9em;
}

.remark-textarea {
  resize: vertical;
  min-height: 96px;
}

.history-desktop {
  overflow-x: auto;
}

.badge-info {
  font-size: 10px;
  padding: 2px 6px;
  background: var(--color-info, #3b82f6);
  color: white;
  border-radius: 4px;
}

.status-badge {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 100px;
  white-space: nowrap;
}

/* 历史记录移动端卡片 */
.history-mobile {
  display: none;
  flex-direction: column;
  gap: 12px;
}

.history-card {
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  padding: 12px;
  border: 1px solid var(--color-border);
}

.h-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 8px;
  gap: 8px;
}

.h-card-anchor {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.h-card-anchor-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.h-anchor-clickable {
  position: relative;
  cursor: pointer;
  border-radius: 8px;
  transition: background-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}

.h-anchor-clickable:hover {
  background: rgba(59, 130, 246, 0.12);
  transform: translateX(2px);
}

.h-anchor-clickable::after {
  content: '↗';
  margin-left: 4px;
  color: var(--color-primary);
  opacity: 0;
  transform: translateX(-4px);
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.h-anchor-clickable:hover::after,
.h-anchor-clickable:focus-visible::after,
.h-anchor-clickable.is-jumping::after {
  opacity: 1;
  transform: translateX(0);
}

.h-anchor-clickable:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
  border-radius: 6px;
}

.h-anchor-clickable.is-jumping {
  animation: anchor-jump-feedback 0.42s ease-out;
}

.h-card-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid var(--color-border);
  flex-shrink: 0;
}

.h-card-avatar-placeholder {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-bg-tertiary);
  color: var(--color-text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: bold;
  border: 1px solid var(--color-border);
  flex-shrink: 0;
}

.h-card-name {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  font-size: 14px;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.h-card-header .status-badge {
  flex-shrink: 0;
}

.h-card-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.h-info-row {
  display: flex;
  font-size: 12px;
  line-height: 1.4;
}

.h-label {
  color: var(--color-text-tertiary);
  width: 65px;
  flex-shrink: 0;
}

.h-value {
  color: var(--color-text-secondary);
  word-break: break-all;
}

.h-value-remark {
  word-break: normal;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.h-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.h-card-actions {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

@media (max-width: 768px) {
  .history-desktop {
    display: none;
  }
  .history-mobile {
    display: flex;
  }
  
  .history-toolbar {
    margin-bottom: 8px !important;
  }
}

.status-completed {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}

.status-recording {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.status-failed {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-top: 20px;
  flex-wrap: wrap;
}

.page-info {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.pagination-jump {
  display: flex;
  align-items: center;
  gap: 8px;
}

.jump-label {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.jump-input {
  width: 72px;
  padding: 6px 8px;
  text-align: center;
}

/* 按钮样式 */
/* Spinner */
.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.spinner-sm {
  width: 12px;
  height: 12px;
  border-width: 1.5px;
}

.bulk-operation-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 12000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.bulk-operation-card {
  min-width: 280px;
  max-width: 520px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: var(--shadow-lg);
  text-align: center;
}

.bulk-operation-card h3 {
  margin: 0 0 8px;
  font-size: 16px;
  color: var(--color-text-primary);
}

.bulk-operation-card p {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.bulk-operation-card .hint {
  margin-top: 8px;
  color: #f59e0b;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.text-secondary {
  color: var(--color-text-secondary);
  font-size: 13px;
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

  .top-row {
    display: flex;
    align-items: stretch;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 16px; /* 从 24px 减小 */
    background: var(--color-bg-card);
    padding: 6px 12px; /* 进一步压缩横向占用 */
    border-radius: var(--radius-xl);
    border: 1px solid var(--color-border);
  }

  .stats-grid {
    display: flex;
    flex: 0 1 auto;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 0;
    min-width: min(100%, 520px);
    padding-right: 10px;
    border-right: 1px solid var(--color-border);
    align-content: stretch;
  }

  .stat-card {
    flex: 0 0 104px;
    min-width: 104px;
    padding: 10px 8px;
    background: var(--color-bg-card);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    flex-direction: column;
    gap: 8px;
  }

  .stat-content h3 {
    font-size: 18px;
    line-height: 1.2;
    margin-bottom: 2px;
  }

  .stat-content p {
    font-size: 12px;
    color: var(--color-text-tertiary);
    margin: 0;
  }

  .action-bar {
    display: flex;
    flex-direction: column;
    gap: 12px; /* 从 16px 减小 */
    flex: 1;
    flex-basis: 520px;
    min-width: 0;
    border: none;
    padding: 0;
    margin: 0; /* 核心修复：显式重置所有方向的 margin */
    background: transparent;
  }

  .action-row {
    display: flex;
    align-items: center;
    width: 100%;
    gap: 16px;
    flex-wrap: wrap;
    margin: 0; /* 显式重置 margin */
  }

  .search-container {
    width: auto;
    min-width: 0;
    flex: 1 1 180px;
    max-width: 240px;
    order: 2;
    margin-left: auto; /* Pushes the search box to the right */
  }

  .search-input-wrapper {
    position: relative;
    display: flex;
    align-items: center;
  }

  .search-icon {
    position: absolute;
    left: 12px;
    color: var(--color-text-tertiary);
    pointer-events: none;
  }

  .search-input {
    width: 100%;
    padding: 8px 36px;
    background: var(--color-bg-secondary);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    color: var(--color-text-primary);
    font-size: 14px;
    transition: all 0.2s ease;
  }

  .search-input:focus {
    outline: none;
    border-color: var(--color-primary);
    background: var(--color-bg-card);
    box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.1);
  }

  .clear-search {
    position: absolute;
    right: 8px;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--color-text-tertiary);
    cursor: pointer;
    border-radius: 50%;
  }

  .clear-search:hover {
    background: var(--color-bg-tertiary);
    color: var(--color-text-primary);
  }

  .action-left {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    min-width: 0;
    margin-left: 0;
    order: 1;
  }

  .live-backup-actions {
    display: flex;
    gap: 8px;
  }

  .action-row.bottom {
    align-items: center;
    flex-wrap: wrap;
  }

  .bulk-actions {
    display: flex;
    gap: 8px;
    flex: 1 1 auto;
    min-width: 0;
    width: auto;
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .action-right {
    display: flex;
    align-items: center;
    gap: 12px;
    flex: 0 0 auto;
    margin-left: auto;
  }

  .filter-group {
    display: flex;
    gap: 8px;
  }

  .top-inline-filters {
    flex-shrink: 1;
    min-width: 0;
  }

  .form-select.filter-select {
    min-width: 88px;
    width: 95px;
  }

  .filter-divider {
    width: 1px;
    height: 20px;
    background: var(--color-border);
    margin: 0 4px;
  }

  .live-backup-actions {
    display: flex;
    flex-direction: row; /* 改回横向 */
    gap: 8px;
    margin-left: auto;
  }
  
  .live-backup-actions .btn {
    padding: 6px 12px;
    font-size: 13px;
    white-space: nowrap;
  }
  
  /* 响应式适配 */
  @media (max-width: 1024px) {
    .top-row {
      flex-direction: column;
      align-items: stretch;
      justify-content: flex-start;
      padding: 0;
      background: transparent;
      border: none;
      gap: 16px;
    }

    .stats-grid {
      flex: none;
      width: 100%;
      min-width: 0;
      border-right: none;
      padding-right: 0;
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 10px;
    }

    .stat-card {
      padding: 12px 8px;
      gap: 4px;
    }

    .action-bar {
      flex: none;
      flex-basis: auto;
      width: 100%;
    }
  }

  @media (max-width: 768px) {
    .live-record-page {
      padding: 12px;
    }

    .modern-scroll-nav {
      right: 16px;
      bottom: 24px;
    }
    
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 8px;
      margin-bottom: 0;
    }
    
    .stat-card {
      padding: 8px 4px;
      min-width: 0;
      gap: 2px;
      border-radius: var(--radius-md);
      text-align: center;
      flex-direction: column;
      justify-content: center;
    }

    .stat-content h3 {
      font-size: 15px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      width: 100%;
    }

    .stat-content p {
      font-size: 11px;
      margin-top: 1px;
      white-space: nowrap;
    }

  .stat-card.storage-card {
    grid-column: auto;
    padding: 8px 4px 7px;
    text-align: center;
    justify-content: center;
  }

  .stat-card.storage-card .storage-size {
    flex-direction: column;
    align-items: center;
    gap: 1px;
    line-height: 1;
  }

  .stat-card.storage-card .storage-size-number {
    font-size: 0.96em;
    font-weight: 700;
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
  }

  .stat-card.storage-card .storage-size-unit {
    font-size: 0.46em;
    line-height: 1;
    letter-spacing: 0.02em;
    opacity: 0.9;
  }

    .action-bar {
      flex-direction: column;
      align-items: stretch;
      justify-content: flex-start;
      gap: 12px;
      margin-bottom: 0;
      margin-top: 12px;
    }

    .action-row {
      flex-direction: column;
      gap: 12px;
    }
    
  .search-container {
    width: 100%;
    flex: none;
    order: 2; /* 搜索框在第一行内部沉到底部 */
  }

  .mobile-primary-filters {
    width: 100%;
    order: 2;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .mobile-primary-filters .filter-select {
    width: 100%;
    min-width: 0;
  }

  .action-left {
    display: flex;
    gap: 8px;
    order: 1; /* 按钮在第一行内部置顶 */
    width: 100%;
      margin-left: 0;
    }

    .action-left .btn {
      flex: 1;
      padding: 6px 4px;
      font-size: 13px;
      white-space: nowrap;
    }

    .search-container {
      flex: none;
      order: 3;
    }

    .tools-modal-content {
      display: flex;
      flex-direction: column;
      gap: 24px;
      padding: 8px 0;
    }

    .tool-section {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .tool-section-title {
      font-size: 14px;
      font-weight: 600;
      color: var(--color-text-secondary);
      margin: 0;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--color-border);
    }

    .tool-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
    }

    .tool-grid .btn, .tool-grid .form-select {
      width: 100%;
      margin: 0;
    }

    .mobile-hide {
      display: none !important;
    }

    .mobile-only {
      display: flex !important;
    }
  }

/* 基础辅助类 */
.mobile-only {
  display: none;
}

/* 播放器样式 */
/* 播放器基础样式优化 */
.player-container {
  width: 100%;
  height: 100%;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-secondary);
}

.live-player {
  width: 100%;
  height: 100%;
  object-fit: contain;
  outline: none;
  display: block;
}

.player-container.triple-screen-active {
  display: flex !important;
  flex-direction: row !important;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 0 12px;
  background: #0a0a0c;
}

.player-container.triple-screen-active .live-player,
.player-container.triple-screen-active .live-triple-mirror {
  max-width: calc(33.33% - 8px) !important;
  width: auto !important;
  height: 100% !important;
  object-fit: contain;
  flex: 1 1 auto;
}

.live-triple-mirror {
  display: block;
  pointer-events: none;
  border-radius: 4px;
  opacity: 1;
}

/* 引导使用自定义全屏，避免原生全屏导致弹幕层被隐藏 */
.live-player::-webkit-media-controls-fullscreen-button {
  display: none;
}

/* 全屏时保证容器铺满并保持弹幕层可见 */
.player-fullscreen-root:fullscreen {
  width: 100vw;
  height: 100vh;
  background: #000;
}

.player-fullscreen-root:fullscreen .player-main,
.player-fullscreen-root:fullscreen .player-danmu-column,
.player-fullscreen-root:fullscreen .player-container,
.player-fullscreen-root:fullscreen .live-player {
  height: 100%;
}

.player-loading, .player-error {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  z-index: 10;
  gap: 12px;
}

.player-error {
  color: #ef4444; 
}

/* 直播弹幕层 */
.live-danmu-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 6;
}

.danmu-marquee-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 6;
}

.danmu-marquee-item {
  position: absolute;
  left: 100%;
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.88);
  color: #111827;
  font-weight: 600;
  font-size: 14px;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.25);
  white-space: nowrap;
  max-width: min(70vw, 520px);
  overflow: hidden;
  text-overflow: ellipsis;
  animation-name: live-danmu-marquee-move;
  animation-timing-function: linear;
  animation-fill-mode: forwards;
}

.danmu-text {
  display: inline-block;
  line-height: 1.2;
}

@keyframes live-danmu-marquee-move {
  from {
    transform: translateX(0);
  }
  to {
    transform: translateX(-140vw);
  }
}

.live-danmu-panel {
  position: absolute;
  left: 12px;
  bottom: 12px;
  width: min(40vw, 360px);
  max-height: 38%;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.18);
  z-index: 7;
}

.live-danmu-panel--column {
  position: relative;
  left: auto;
  bottom: auto;
  width: 100%;
  max-height: none;
  height: 100%;
  border-radius: 0;
  background: var(--color-bg-card);
  box-shadow: none;
  padding: 12px 10px;
}

/* 全屏时上移，避免遮挡控制条 */
.player-container:fullscreen .live-danmu-panel {
  bottom: 64px;
}

.danmu-list-jump {
  align-self: flex-end;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  font-size: 12px;
  cursor: pointer;
}

.danmu-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 4px 0;
}

.danmu-list::-webkit-scrollbar {
  width: 4px;
}
.danmu-list::-webkit-scrollbar-track {
  background: transparent;
}
.danmu-list::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 999px;
}

.danmu-list-item {
  padding: 5px 12px;
  background: transparent;
  color: var(--color-text-primary);
  font-size: 13px;
  line-height: 1.4;
  transition: all 0.2s ease;
  cursor: default;
}

.danmu-list-item:hover {
  background: var(--color-bg-hover);
}

.danmu-list-empty {
  color: var(--color-text-tertiary);
  font-size: 12px;
}

.player-footer-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  width: 100%;
}

.player-footer-controls {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px;
  border-radius: 999px;
  background: rgba(var(--color-primary-rgb), 0.08);
  border: 1px solid rgba(var(--color-primary-rgb), 0.25);
  color: var(--color-text-primary);
  box-shadow: 0 6px 16px rgba(var(--color-primary-rgb), 0.12);
}

.player-footer-controls .player-action-btn {
  height: 34px;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, #e96a2e 0%, #f39c12 100%);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
  box-shadow: 0 3px 10px rgba(233, 106, 46, 0.28);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.player-footer-controls .player-action-btn:hover {
  filter: brightness(1.05);
}

.player-footer-controls .player-action-btn:active {
  transform: translateY(1px);
}

.player-footer-controls .player-action-btn-icon {
  width: 90px;
  min-width: 90px;
  padding: 0 14px;
}

.player-footer-controls .player-action-btn-text {
  min-width: 110px;
  padding: 0 16px;
  white-space: nowrap;
}

.player-footer-controls .triple-screen-btn {
  background: linear-gradient(135deg, #707070 0%, #505050 100%);
  box-shadow: 0 3px 10px rgba(80, 80, 80, 0.2);
  transition: all 0.3s ease;
}

.player-footer-controls .triple-screen-btn:hover {
  background: linear-gradient(135deg, #808080 0%, #606060 100%);
}

.player-footer-controls .triple-screen-btn.active {
  background: linear-gradient(135deg, #e96a2e 0%, #f39c12 100%);
  box-shadow: 0 3px 10px rgba(233, 106, 46, 0.28);
}

.player-footer-controls .player-action-btn-confirm {
  min-width: 92px;
  padding: 0 20px;
}

.player-footer-controls .danmu-btn {
  border-radius: 999px;
  white-space: nowrap;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .modal-body {
  background: #000;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .modal-container {
  background: #000 !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .modal-header {
  background: #0b0f16;
  border-bottom: 1px solid #1f2937;
  color: #f8fafc;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .modal-header .header-content h3 {
  color: #f8fafc !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .close-btn {
  color: #94a3b8 !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .close-btn:hover {
  color: #f8fafc !important;
  background: rgba(148, 163, 184, 0.12) !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .modal-footer {
  border-top: 1px solid #1f2937;
  background: #0b0f16;
}

[data-theme="dark"] :global(.player-modal--fullscreen:not(.player-modal-light) .modal-container) {
  background: #000;
}

[data-theme="dark"] :global(.player-modal--fullscreen:not(.player-modal-light) .modal-body) {
  background: #000;
}

[data-theme="dark"] .player-layout {
  background: #000;
}

[data-theme="dark"] .player-danmu-column {
  background: #1a1a1a;
  border-left-color: #333;
  border-right: none;
}

[data-theme="dark"] .player-sidebar {
  background: #1a1a1a;
  border-left-color: #333;
}

[data-theme="dark"] .sidebar-header {
  color: #eee;
  border-bottom-color: #333;
}

[data-theme="dark"] .sidebar-item:hover {
  background: #2a2a2a;
}

[data-theme="dark"] .sidebar-item.active {
  background: #333;
}

[data-theme="dark"] .item-avatar img {
  border-color: #444;
}

[data-theme="dark"] .item-avatar .avatar-placeholder {
  background: #333;
  color: #999;
}

[data-theme="dark"] .item-name {
  color: #ddd;
}

[data-theme="dark"] .sidebar-item.active .item-name {
  color: #fff;
}

[data-theme="dark"] .p-tag {
  background: #333;
  color: #888;
  border-color: transparent;
}

[data-theme="dark"] .q-tag {
  color: #666;
}

@media (max-width: 768px) {
  [data-theme="dark"] .item-meta .p-tag {
    border-color: rgba(255, 255, 255, 0.22);
    background: rgba(15, 23, 42, 0.78);
    color: #f8fafc;
  }
}

[data-theme="dark"] .danmu-marquee-item {
  background: rgba(15, 23, 42, 0.68);
  border: 1px solid rgba(148, 163, 184, 0.35);
  color: #f8fafc;
  box-shadow: 0 8px 18px rgba(2, 6, 23, 0.45);
}

[data-theme="dark"] .live-danmu-panel {
  background: linear-gradient(160deg, rgba(15, 23, 42, 0.82), rgba(30, 41, 59, 0.78));
  border: 1px solid rgba(148, 163, 184, 0.36);
  box-shadow: 0 14px 28px rgba(2, 6, 23, 0.42);
}

[data-theme="dark"] .live-danmu-panel--column {
  background: rgba(10, 15, 25, 0.9);
}

[data-theme="dark"] .danmu-list-jump {
  border-color: rgba(148, 163, 184, 0.4);
  background: rgba(30, 41, 59, 0.74);
  color: #f8fafc;
}

[data-theme="dark"] .danmu-list::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.5);
}

[data-theme="dark"] .danmu-list-item {
  background: transparent;
  border: none;
  color: #f8fafc;
}

[data-theme="dark"] .danmu-list-item:hover {
  background: rgba(148, 163, 184, 0.1);
}

[data-theme="dark"] .danmu-list-empty {
  color: rgba(148, 163, 184, 0.9);
}

[data-theme="dark"] .player-footer-controls {
  background: rgba(230, 126, 34, 0.12);
  border: 1px solid rgba(230, 126, 34, 0.4);
  color: #f8fafc;
  box-shadow: 0 6px 16px rgba(230, 126, 34, 0.18);
}

:global(html:not([data-theme="dark"]) .player-modal-light .player-layout) {
  background: var(--color-bg-primary) !important;
}

[data-theme="light"] :global(.player-modal-light) .player-main {
  background: #eef2f7 !important;
}

[data-theme="light"] :global(.player-modal-light) .player-container {
  background: #e5e7eb !important;
}

[data-theme="dark"] :global(.player-modal-light) .player-main,
[data-theme="dark"] :global(.player-modal-light) .player-container {
  background: #000 !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .player-danmu-column) {
  background: #f8fafc !important;
  border-left-color: #d1d5db !important;
  border-right: none !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .player-sidebar) {
  background: #f8fafc !important;
  border-left-color: #d1d5db !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .sidebar-header) {
  color: #334155 !important;
  border-bottom-color: #d1d5db !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .sidebar-item:hover) {
  background: #eef2f7 !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .sidebar-item.active) {
  background: #e8eef7 !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .item-avatar img) {
  border-color: #d1d5db !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .item-avatar .avatar-placeholder) {
  background: #f1f5f9 !important;
  color: #64748b !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .item-name),
:global(html:not([data-theme="dark"]) .player-modal-light .sidebar-item.active .item-name) {
  color: #1f2937 !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .p-tag) {
  background: #ffffff !important;
  color: #334155 !important;
  border: 1px solid #cbd5e1 !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .q-tag) {
  color: #64748b !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .danmu-marquee-item) {
  background: rgba(255, 255, 255, 0.92) !important;
  border: 1px solid rgba(148, 163, 184, 0.42) !important;
  color: #0f172a !important;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.16) !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .live-danmu-panel) {
  background: rgba(255, 255, 255, 0.55) !important;
  border: 1px solid rgba(255, 255, 255, 0.3) !important;
  box-shadow: 0 8px 32px rgba(15, 23, 42, 0.08) !important;
  backdrop-filter: blur(12px) saturate(180%);
}

:global(html:not([data-theme="dark"]) .player-modal-light .live-danmu-panel--column) {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .danmu-list-jump) {
  border-color: #cbd5e1 !important;
  background: #ffffff !important;
  color: #334155 !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .danmu-list::-webkit-scrollbar-thumb) {
  background: rgba(100, 116, 139, 0.45) !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .danmu-list-item) {
  background: transparent !important;
  border: none !important;
  color: #0f172a !important;
  box-shadow: none !important;
  border-radius: 0 !important;
  padding: 5px 16px !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .danmu-list-item:hover) {
  background: #eef2f7 !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .danmu-list-empty) {
  color: #64748b !important;
}

:global(html:not([data-theme="dark"]) .player-modal-light .danmu-text),
:global(html:not([data-theme="dark"]) .player-modal-light .sidebar-header),
:global(html:not([data-theme="dark"]) .player-modal-light .item-name),
:global(html:not([data-theme="dark"]) .player-modal-light .player-footer-controls .player-action-btn) {
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

/* 浅色主题下播放器外圈与侧栏改为浅色（Teleported Modal 需要全局选择器） */
:global([data-theme="light"] .player-modal-light .player-layout) {
  background: #f3f4f6 !important;
}

:global([data-theme="light"] .player-modal-light .player-main) {
  background: #e5e7eb !important;
}

:global([data-theme="light"] .player-modal-light .player-container) {
  background: #dfe3e8 !important;
}

:global([data-theme="light"] .player-modal-light .player-danmu-column) {
  background: #f8fafc !important;
  border-left-color: #d1d5db !important;
  border-right-color: #d1d5db !important;
}

:global([data-theme="light"] .player-modal-light .player-sidebar) {
  background: #f8fafc !important;
  border-left-color: #d1d5db !important;
}

:global([data-theme="light"] .player-modal-light .modal-footer) {
  background: #f3f4f6 !important;
  border-top-color: #d1d5db !important;
}

/* 关键覆盖：修正 Modal.vue 中 .player-modal-light .modal-body 的黑色 !important */
:global([data-theme="light"] .player-modal-light.modal-overlay .modal-container) {
  background: #f3f4f6 !important;
}

:global([data-theme="light"] .player-modal-light.modal-overlay .modal-body) {
  background: #eef2f7 !important;
}

:global([data-theme="dark"] .player-modal-light.modal-overlay .modal-container),
:global([data-theme="dark"] .player-modal-light.modal-overlay .modal-body) {
  background: #000 !important;
}

@media (max-width: 768px) {
  .live-danmu-panel {
    width: min(58vw, 220px);
    max-height: 28%;
    left: auto;
    right: 8px;
    bottom: 8px;
    padding: 8px;
  }
  .danmu-marquee-item {
    font-size: 11px;
  }
  .danmu-list-item {
    font-size: 10px;
  }
  .player-footer-controls {
    padding: 4px;
    gap: 6px;
    flex-wrap: nowrap;
    border-radius: 12px;
    min-width: 0;
  }
  .player-footer-controls .btn {
    height: 30px;
  }
  .player-footer-bar {
    flex-direction: row;
    align-items: center;
    justify-content: center;
    gap: 0;
  }
  .player-footer-controls {
    width: min(100%, 360px);
    justify-content: space-between;
    gap: 6px;
    margin: 0 auto;
  }
  .player-footer-controls .player-action-btn {
    flex: 1 1 0;
    min-width: 0;
    padding: 0 8px;
    font-size: 12px;
  }
  .player-footer-controls .player-action-btn-icon {
    flex: 0 0 64px;
  }
  .player-footer-controls .player-action-btn-text {
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

/* 移动端浅色主题适配：修正 player-modal-light 在浅色模式仍偏暗的问题 */
@media (max-width: 768px) {
  [data-theme="light"] :global(.player-modal-light) .player-sidebar {
    background: #f8fafc !important;
    border-top-color: #e5e7eb !important;
    border-left-color: #e5e7eb !important;
  }

  [data-theme="light"] :global(.player-modal-light) .sidebar-item:hover {
    background: #eef2f7 !important;
  }

  [data-theme="light"] :global(.player-modal-light) .sidebar-item.active {
    background: #e8eef7 !important;
  }

  [data-theme="light"] :global(.player-modal-light) .item-avatar img {
    border-color: #d1d5db !important;
  }

  [data-theme="light"] :global(.player-modal-light) .item-avatar .avatar-placeholder {
    background: #f1f5f9 !important;
    color: #64748b !important;
  }

  [data-theme="light"] :global(.player-modal-light) .item-name,
  [data-theme="light"] :global(.player-modal-light) .sidebar-item.active .item-name {
    color: #1f2937 !important;
  }

  [data-theme="light"] :global(.player-modal-light) .p-tag {
    background: #ffffff !important;
    color: #334155 !important;
    border: 1px solid #cbd5e1 !important;
  }

  [data-theme="light"] .player-footer-controls {
    background: rgba(255, 255, 255, 0.96);
    border: 1px solid rgba(233, 106, 46, 0.35);
    box-shadow: 0 8px 18px rgba(15, 23, 42, 0.14);
  }
}

/* 浅色模式最终兜底：
   systemStore 在浅色时会 removeAttribute('data-theme')，因此不能依赖 [data-theme="light"] */
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .modal-container) {
  background: #f3f4f6 !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .modal-body) {
  background: #eef2f7 !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-layout) {
  background: #f3f4f6 !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-main) {
  background: #e5e7eb !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-container) {
  background: #dfe3e8 !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-danmu-column) {
  background: #f8fafc !important;
  border-left-color: #d1d5db !important;
  border-right-color: #d1d5db !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-sidebar) {
  background: #f8fafc !important;
  border-left-color: #d1d5db !important;
}

/* 浅色主题统一色阶：降低割裂感 */
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light) {
  --live-surface-base: #eef1f5;
  --live-surface-card: #f6f8fb;
  --live-surface-item: #ffffff;
  --live-border-soft: #d5dce6;
  --live-text-main: #1f2937;
  --live-text-sub: #475569;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .modal-container),
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .modal-body),
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .modal-footer),
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-layout),
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-main),
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-container),
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-danmu-column),
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-sidebar) {
  background: var(--live-surface-base) !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .modal-footer),
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-danmu-column),
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-sidebar) {
  border-color: var(--live-border-soft) !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .player-danmu-column) {
  border-left-color: rgba(148, 163, 184, 0.26) !important;
  border-right: none !important; /* 避免与右侧 sidebar 的 left border 形成双线 */
  box-shadow: none;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .sidebar-header) {
  color: var(--live-text-sub) !important;
  border-bottom-color: var(--live-border-soft) !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .sidebar-item:hover) {
  background: #e8edf3 !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .sidebar-item.active) {
  background: #e3e9f1 !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .item-name),
:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .sidebar-item.active .item-name) {
  color: var(--live-text-main) !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .p-tag) {
  background: var(--live-surface-item) !important;
  color: var(--live-text-sub) !important;
  border: 1px solid var(--live-border-soft) !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .danmu-marquee-item) {
  background: rgba(255, 255, 255, 0.9) !important;
  border: 1px solid var(--live-border-soft) !important;
  color: #0f172a !important;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.12) !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .live-danmu-panel) {
  background: rgba(255, 255, 255, 0.55) !important;
  border: 1px solid rgba(255, 255, 255, 0.3) !important;
  box-shadow: 0 8px 32px rgba(15, 23, 42, 0.08) !important;
  backdrop-filter: blur(12px) saturate(180%);
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .live-danmu-panel--column) {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  border-radius: 0 !important;
  margin: 0;
  height: 100%;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .danmu-list-jump) {
  border-color: var(--live-border-soft) !important;
  background: var(--live-surface-item) !important;
  color: var(--live-text-sub) !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .danmu-list-item) {
  background: transparent !important;
  border: none !important;
  color: #0f172a !important;
  box-shadow: none !important;
  border-radius: 0 !important;
  padding: 5px 16px !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .danmu-list-item:hover) {
  background: #eef2f7 !important;
}

:global(html:not([data-theme="dark"]) .modal-overlay.player-modal-light .danmu-list-empty) {
  color: #64748b !important;
}

.btn-success {
  background-color: #22c55e;
  color: white;
  border: none;
}
.btn-success:hover {
  background-color: #16a34a;
}

/* 右上角操作区域 */
.card-top-actions {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  gap: 6px;
  z-index: 10;
}

.card-action-btn {
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
  backdrop-filter: blur(4px);
}

[data-theme="dark"] .card-action-btn {
  background: rgba(30, 30, 30, 0.8);
  border-color: rgba(255, 255, 255, 0.1);
  color: var(--color-text-secondary);
}

.card-action-btn:hover {
  background: var(--color-primary);
  color: white;
  border-color: var(--color-primary);
  transform: scale(1.05);
}

.card-action-btn:hover :deep(svg) {
  animation: none;
}

/* 设置按钮特定的旋转动画 */
.settings-btn:hover {
  transform: rotate(45deg) scale(1.05);
}

/* 删除确认弹窗样式 */
.delete-confirm-content {
  padding: 10px 0;
}

.confirm-message {
  font-size: 15px;
  color: var(--color-text-primary);
  margin-bottom: 16px;
}

.record-info-preview {
  background: var(--color-bg-tertiary);
  padding: 12px;
  border-radius: var(--radius-md);
  margin-bottom: 20px;
  font-size: 13px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.record-info-preview p {
  margin: 4px 0;
}

.delete-options-box {
  background: rgba(239, 68, 68, 0.05);
  border: 1px dashed rgba(239, 68, 68, 0.2);
  padding: 16px;
  border-radius: var(--radius-md);
}

.checkbox-label-modern.dangerous-check {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  cursor: pointer;
  width: 100%;
  position: relative;
}

/* Hide the default checkbox */
.checkbox-label-modern.dangerous-check .checkbox-modern {
  position: absolute;
  opacity: 0;
  cursor: pointer;
  height: 0;
  width: 0;
}

.checkbox-label-modern.dangerous-check .checkbox-text {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.checkbox-label-modern.dangerous-check .checkbox-title {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-error);
  margin-bottom: 4px;
}

.checkbox-label-modern.dangerous-check .checkbox-desc {
  display: block;
  font-size: 12px;
  opacity: 0.8;
  line-height: 1.4;
}

.checkbox-label-modern.dangerous-check .checkbox-custom {
  margin-top: 2px; /* Visual alignment with title */
  width: 18px;
  height: 18px;
  border: 2px solid var(--color-border);
  border-radius: 4px;
  position: relative;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.checkbox-label-modern.dangerous-check .checkbox-modern:checked + .checkbox-custom {
  background-color: var(--color-error);
  border-color: var(--color-error);
}

.checkbox-label-modern.dangerous-check .checkbox-modern:checked + .checkbox-custom::after {
  content: '';
  position: absolute;
  left: 5px;
  top: 1px;
  width: 5px;
  height: 10px;
  border: solid white;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}

/* 历史记录表格头像单元格 */
.history-anchor-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 220px;
  min-width: 0;
}

.history-anchor-clickable {
  position: relative;
  cursor: pointer;
  border-radius: 8px;
  padding: 2px 6px 2px 0;
  transition: background-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}

.history-anchor-clickable:hover {
  background: rgba(59, 130, 246, 0.12);
  transform: translateX(2px);
}

.history-anchor-clickable::after {
  content: '↗';
  margin-left: 4px;
  color: var(--color-primary);
  opacity: 0;
  transform: translateX(-4px);
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.history-anchor-clickable:hover::after,
.history-anchor-clickable:focus-visible::after,
.history-anchor-clickable.is-jumping::after {
  opacity: 1;
  transform: translateX(0);
}

.history-anchor-clickable:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
  border-radius: 6px;
}

.history-anchor-clickable.is-jumping {
  animation: anchor-jump-feedback 0.42s ease-out;
}

.history-anchor-clickable:hover .history-anchor-name,
.h-anchor-clickable:hover .h-card-name {
  color: var(--color-primary);
}

@keyframes anchor-jump-feedback {
  0% {
    transform: translateX(0) scale(1);
    box-shadow: 0 0 0 0 rgba(59, 130, 246, 0);
  }
  40% {
    transform: translateX(3px) scale(1.015);
    box-shadow: 0 0 0 6px rgba(59, 130, 246, 0.18);
  }
  100% {
    transform: translateX(0) scale(1);
    box-shadow: 0 0 0 0 rgba(59, 130, 246, 0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .history-anchor-clickable,
  .h-anchor-clickable {
    transition: none;
  }
  .history-anchor-clickable.is-jumping,
  .h-anchor-clickable.is-jumping {
    animation: none;
  }
}

.history-anchor-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid var(--color-border);
  flex-shrink: 0;
}

.history-avatar-placeholder {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-bg-tertiary);
  color: var(--color-text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: bold;
  border: 1px solid var(--color-border);
  flex-shrink: 0;
}

/* 批量操作动画可见性增强 */
.bulk-operation-overlay {
  background: rgba(0, 0, 0, 0.52);
  backdrop-filter: blur(2px);
}

.bulk-operation-card {
  min-width: 300px;
  max-width: 560px;
  background: linear-gradient(180deg, var(--color-bg-card), var(--color-bg-secondary));
  padding: 20px 22px;
  animation: bulk-card-pulse 1.2s ease-in-out infinite;
}

.bulk-spinner {
  width: 24px;
  height: 24px;
  border-width: 2.5px;
  margin: 0 auto 10px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.22s ease;
}

.fade-enter-from .bulk-operation-card,
.fade-leave-to .bulk-operation-card {
  transform: translateY(8px) scale(0.985);
}
@keyframes bulk-card-pulse {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-2px);
  }
}
/* 批量处理中动效兜底修复 */
.spinner {
  display: inline-block;
  box-sizing: border-box;
}

.bulk-spinner {
  display: block;
  border-color: rgba(148, 163, 184, 0.35);
  border-top-color: var(--color-primary, #16a34a);
  animation: spin 0.65s linear infinite;
}

.bulk-operation-card {
  position: relative;
  overflow: hidden;
}

.bulk-operation-card::after {
  content: "";
  display: block;
  height: 3px;
  margin-top: 12px;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(22, 163, 74, 0.08), rgba(22, 163, 74, 0.9), rgba(22, 163, 74, 0.08));
  background-size: 220% 100%;
  animation: bulk-progress 1.1s linear infinite;
}

@keyframes bulk-progress {
  from {
    background-position: 200% 0;
  }
  to {
    background-position: 0 0;
  }
}

/* 最终覆盖：纵向弹幕列与“正在直播”侧栏同一套底色/分隔，避免任何前序规则冲突 */
:global(html:not([data-theme="dark"]) .player-modal--fullscreen) {
  --live-side-bg-final: #eef1f5;
  --live-side-border-final: #d5dce6;
}

:global([data-theme="dark"] .player-modal--fullscreen) {
  --live-side-bg-final: #1a1a1a;
  --live-side-border-final: #333;
}

:global(.player-modal--fullscreen .player-danmu-column),
:global(.player-modal--fullscreen .player-sidebar) {
  background: var(--live-side-bg-final, var(--color-bg-card)) !important;
}

:global(.player-modal--fullscreen .player-danmu-column) {
  border-left: 1px solid var(--live-side-border-final, var(--color-border)) !important;
  border-right: none !important;
  box-shadow: none !important;
}

:global(.player-modal--fullscreen .player-sidebar) {
  border-left: 1px solid var(--live-side-border-final, var(--color-border)) !important;
}

:global(.player-modal--fullscreen .live-danmu-panel--column) {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

@media (max-width: 768px) {
  :deep(.timeline-modal .modal-body.modal-body-fill) {
    overflow-y: auto;
    overscroll-behavior: contain;
    padding-bottom: calc(8px + env(safe-area-inset-bottom, 0px));
  }

  :deep(.timeline-modal .modal-header) {
    padding: 12px 14px;
  }

  :deep(.timeline-modal .header-content) {
    min-width: 0;
    flex: 1;
  }

  :deep(.timeline-modal .header-content h3) {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.2;
  }

  :deep(.timeline-modal .header-actions) {
    flex-shrink: 0;
  }
}

</style>
