<template>
  <div class="downloads-page">
    <!-- 顶部操作栏 -->
    <div class="page-toolbar">
      <div class="toolbar-left">
        <div class="filter-tabs">
          <button 
            class="filter-tab" 
            :class="{ active: downloadsStore.currentFilter === 'all' }"
            @click="downloadsStore.setFilter('all')"
          >
            全部
          </button>
          <button 
            class="filter-tab" 
            :class="{ active: downloadsStore.currentFilter === 'active' }"
            @click="downloadsStore.setFilter('active')"
          >
            进行
          </button>
          <button 
            class="filter-tab" 
            :class="{ active: downloadsStore.currentFilter === 'completed' }"
            @click="downloadsStore.setFilter('completed')"
          >
            完成
          </button>
          <button 
            class="filter-tab" 
            :class="{ active: downloadsStore.currentFilter === 'error' }"
            @click="downloadsStore.setFilter('error')"
          >
            失败
          </button>
          <button 
            class="filter-tab" 
            :class="{ active: downloadsStore.currentFilter === 'cancelled' }"
            @click="downloadsStore.setFilter('cancelled')"
          >
            已取消
          </button>
          <!-- 移动端清空按钮 -->
          <button 
            class="filter-tab filter-tab-clear-mobile btn-clear-action" 
            @click="clearFilteredTasks"
          >
            <Icon name="trash" :size="14" />
            {{ getClearButtonText() }}
          </button>
        </div>
        
        <!-- 订阅系统任务入口容器 -->
        <div class="batch-tasks-container">
          <button 
            class="btn btn-outline btn-batch-tasks"
            @click="goToBatchDownloadTasks"
            title="查看订阅系统批量下载任务"
          >
            <Icon name="download" :size="16" />
            <span class="btn-text">订阅系统任务</span>
          </button>
        </div>
      </div>
      
      <div class="toolbar-right">
        <div class="search-box">
          <Icon name="search" :size="16" />
          <input 
            type="text" 
            v-model="searchInput" 
            @keyup.enter="handleSearch"
            placeholder="搜索任务..." 
          />
        </div>
      </div>
    </div>

    <!-- 高级筛选栏 -->
    <div class="advanced-filters">
        <!-- 移动端搜索框 -->
        <div class="search-box search-box-mobile">
          <Icon name="search" :size="16" />
          <input 
            type="text" 
            v-model="searchInput" 
            @keyup.enter="handleSearch"
            placeholder="搜索任务..." 
          />
        </div>
        
        <!-- 博主选择器 -->
        <div class="filter-group author-select-container" v-click-outside="closeAuthorDropdown">
            <!-- 移动端遮罩层 -->
            <div 
                class="author-dropdown-overlay" 
                v-show="showAuthorDropdown" 
                @click.stop="closeAuthorDropdown"
            ></div>

            <div class="author-selector" :class="{ active: showAuthorDropdown }" @click="toggleAuthorDropdown">
                <span class="author-placeholder" :class="{ 'has-value': currentAuthorName }">
                    {{ currentAuthorName ? `👤 ${currentAuthorName}` : '👤 选择博主...' }}
                </span>
                <Icon name="chevron-down" :size="12" class="dropdown-arrow" />
            </div>
            
            <div class="author-dropdown" v-show="showAuthorDropdown">
                <div class="author-search-input">
                    <input 
                        type="text" 
                        v-model="authorSearch" 
                        placeholder="搜索博主..." 
                        @click.stop
                    />
                </div>
                <div class="author-list">
                    <div v-if="filteredAuthorsGroups.length === 0" class="no-authors">
                        没有找到匹配的博主
                    </div>
                    <div v-for="group in filteredAuthorsGroups" :key="group.platform" class="platform-group">
                        <div class="platform-header">
                            <span class="platform-badge-mini" :class="`badge-${group.platform}`">
                                {{ group.platformName }}
                            </span>
                            <span class="platform-subtitle">共 {{ group.authors.length }} 位博主</span>
                        </div>
                        <div 
                            v-for="author in group.authors" 
                            :key="author.subscription_id"
                            class="author-item"
                            :class="{ selected: downloadsStore.currentAuthorFilter === author.subscription_id }"
                            @click="selectAuthor(author)"
                        >
                            <span class="author-item-name">
                                {{ author.nickname }}
                                <span v-if="author.platform" class="author-platform-tag">
                                    {{ getPlatformDisplayName(author.platform) }}
                                </span>
                            </span>
                            <span class="author-item-count">{{ author.task_count }} 个任务</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 平台筛选 -->
        <select class="form-select" :style="{ width: '160px' }" :value="downloadsStore.currentPlatformFilter" @change="e => downloadsStore.setPlatformFilter(e.target.value)">
            <option value="all">全部平台</option>
            <option value="douyin">抖音</option>
            <option value="xiaohongshu">小红书</option>
            <option value="tiktok">TikTok</option>
            <option value="instagram">Instagram</option>
            <option value="youtube">YouTube</option>
            <option value="bilibili">Bilibili</option>
            <option value="netease">网易云音乐</option>
            <option value="x">X</option>
            <option value="unknown">未知平台</option>
            <option value="others">其他</option>
        </select>

        <!-- 复选框组 -->
        <div class="checkbox-group">
            <label class="filter-checkbox">
                <input 
                    type="checkbox" 
                    :checked="downloadsStore.currentManualOnly" 
                    @change="e => downloadsStore.setManualOnly(e.target.checked)"
                >
                仅手动
            </label>

            <label class="filter-checkbox" title="仅显示文件已删除但任务仍在的记录">
                <input 
                    type="checkbox" 
                    :checked="downloadsStore.currentOrphanOnly" 
                    @change="e => downloadsStore.setOrphanOnly(e.target.checked)"
                >
                仅孤儿
            </label>
            
            <!-- 移动端清空按钮 -->
            <button 
                class="filter-tab filter-tab-clear-mobile btn-clear-action btn-clear-in-checkbox" 
                @click="clearFilteredTasks"
            >
                <Icon name="trash" :size="14" />
                {{ getClearButtonText() }}
            </button>
        </div>

        <!-- 操作按钮组 -->
        <div class="action-buttons-group">
            <!-- 分页控件 -->
            <div class="pagination-bar inline-pagination" v-if="downloadsStore.totalTasks > 0">
                <button 
                    class="page-btn" 
                    :disabled="downloadsStore.currentPage === 1"
                    @click="downloadsStore.goToPage(downloadsStore.currentPage - 1)"
                >
                    <Icon name="chevron-left" :size="14" />
                </button>
                
                <div class="page-numbers">
                    <button 
                        v-for="page in displayedPages" 
                        :key="page"
                        class="page-number"
                        :class="{ active: downloadsStore.currentPage === page, ellipsis: page === '...' }"
                        :disabled="page === '...'"
                        @click="typeof page === 'number' && downloadsStore.goToPage(page)"
                    >
                        {{ page }}
                    </button>
                </div>

                <button 
                    class="page-btn" 
                    :disabled="downloadsStore.currentPage === downloadsStore.totalPages"
                    @click="downloadsStore.goToPage(downloadsStore.currentPage + 1)"
                >
                    <Icon name="chevron-right" :size="14" />
                </button>

                <span class="page-info">
                    {{ downloadsStore.currentPage }} / {{ downloadsStore.totalPages }} ({{ downloadsStore.totalTasks }})
                </span>
                
                <!-- 页码选择下拉框 -->
                <select 
                    class="page-select" 
                    :value="downloadsStore.currentPage"
                    @change="handlePageSelect($event)"
                >
                    <option v-for="page in downloadsStore.totalPages" :key="page" :value="page">
                        第 {{ page }} 页
                    </option>
                </select>
            </div>
            
            <!-- 清除筛选 -->
            <button 
                v-if="downloadsStore.hasActiveFilters"
                class="btn btn-outline text-danger btn-filter-action" 
                @click="resetAllFilters"
            >
                <Icon name="x" :size="14" />
                清除筛选
            </button>
            
            <!-- 智能清空任务 -->
            <button class="btn btn-danger btn-clear-action btn-clear-action-desktop" @click="clearFilteredTasks">
                <Icon name="trash" :size="16" />
                {{ getClearButtonText() }}
            </button>
        </div>
    </div>

    <!-- 任务列表 -->
    <div class="task-list">
      <Transition name="fade" mode="out-in">
        <SkeletonLoader 
          v-if="downloadsStore.loading"
          :loading="true"
          text="正在加载任务..."
          type="list"
          :count="5"
          itemHeight="120px"
        />
        
        <div v-else class="task-content-wrapper">
          <div 
            class="card task-card" 
            v-for="task in downloadsStore.tasks" 
            :key="task.id"
            :class="{ 
                'task-active': ['DOWNLOADING', 'PROCESSING'].includes(task.status), 
                'task-error': task.status === 'ERROR' 
            }"
            :data-task-id="task.id"
            @mouseenter="handleMouseEnter(task)"
            @mouseleave="handleMouseLeave"
          >


            <!-- 视频缩略图 (左侧) -->
            <div 
              class="task-thumbnail"
              :class="{ 'clickable-thumbnail': task.status === 'COMPLETED' }"
              @click="task.status === 'COMPLETED' && playTask(task)"
            >
              <img 
                :src="thumbnailCache[task.id] || PLACEHOLDER_IMAGE" 
                class="thumbnail-img" 
                @error="handleThumbnailError(task)"
                :style="{ display: (thumbnailCache[task.id]) ? 'block' : 'none' }"
              />
              <!-- 占位符/备用图标 -->
              <div v-if="!thumbnailCache[task.id]" class="thumbnail-placeholder">
                <Icon :name="getPlatformIcon(task.source)" :size="24" />
              </div>
              <!-- 悬停视频静音自动播放预览 -->
              <video
                v-if="hoveredTaskId === task.id && isVideoTask(task) && getPlayableUrl(task)"
                :src="getPlayableUrl(task)"
                class="thumbnail-video-preview"
                :class="{ 'is-playing': isPreviewPlaying }"
                @playing="isPreviewPlaying = true"
                autoplay
                muted
                loop
                playsinline
              ></video>
            </div>

            <!-- 任务信息 (右侧) -->
            <div class="task-content">
              <div class="task-header">
                <div class="task-title-row">
                  <span class="badge platform-badge-mini" :class="task.source">
                    {{ getPlatformDisplayName(task.source) }}
                  </span>
                  <a v-if="task.url || task.original_url" 
                     :href="task.original_url || task.url" 
                     target="_blank" 
                     class="task-title-link"
                     :title="getTaskTitle(task)">
                    <h4 class="task-title">{{ getTaskTitle(task) }}</h4>
                  </a>
                  <h4 v-else class="task-title" :title="getTaskTitle(task)">{{ getTaskTitle(task) }}</h4>
                </div>
              </div>

              <!-- 标签区 -->
              <div class="task-badges">
                <span 
                  v-if="task.author_info" 
                  class="badge author-badge clickable-author" 
                  :title="`点击查看博主【${task.author_info.nickname}】的订阅详情`"
                  @click.stop="goToSubscriptionDetail(task.author_info.subscription_id)"
                >
                  👤 {{ task.author_info.nickname?.length > 5 ? task.author_info.nickname.slice(0, 5) + '...' : (task.author_info.nickname || '未知博主') }}
                </span>
                <span class="badge type-badge" :class="getTaskTypeClass(task)">
                  {{ getTaskTypeText(task) }}
                </span>
                <span v-if="task.status === 'COMPLETED'" class="badge status-badge completed">已完成</span>
                <template v-else-if="task.status === 'ERROR'">
                  <span class="badge status-badge error">失败</span>
                  <div 
                    class="error-inline-scroller" 
                    :title="task.error_message || '点击复制错误日志'"
                    @click.stop="copyToClipboard(task.error_message || '未知错误')"
                  >
                    <div class="error-scroller-text">
                      <span>⚠️ {{ task.error_message || '未知错误' }}</span>
                      <span class="marquee-spacer" style="margin: 0 16px; opacity: 0.5;">|</span>
                      <span>⚠️ {{ task.error_message || '未知错误' }}</span>
                      <span class="marquee-spacer" style="margin: 0 16px; opacity: 0.5;">|</span>
                    </div>
                  </div>
                </template>
              </div>


              <!-- 进度条 -->
              <div class="task-progress" v-if="['DOWNLOADING', 'PROCESSING'].includes(task.status)">
                <div class="progress-bar" :class="getProgressClass(task.status)">
                    <div class="progress-fill" :style="{ width: (task.progress || 0) + '%' }"></div>
                </div>
                <div class="progress-text">
                    <span>{{ task.status === 'PROCESSING' ? '处理中' : '下载中' }} {{ (task.progress || 0).toFixed(1) }}%</span>
                    <span v-if="task.speed" class="speed-text">{{ task.speed }}</span>
                </div>
              </div>





              <!-- 操作按钮 -->
              <div class="task-actions">
                  <div class="btns-group-wrapper">
                    <div class="btns-group">
                      <template v-if="['DOWNLOADING', 'PROCESSING', 'PENDING'].includes(task.status)">
                        <button 
                          class="btn btn-secondary btn-sm" 
                          :class="{ 'btn-loading': cancelingTaskIds.has(task.id) }"
                          :disabled="cancelingTaskIds.has(task.id)"
                          @click="cancelTask(task.id)"
                        >
                          <span v-if="cancelingTaskIds.has(task.id)">取消中...</span>
                          <span v-else>取消</span>
                        </button>
                      </template>
                      <template v-else-if="task.status === 'COMPLETED'">
                        <button 
                          class="btn btn-outline btn-sm" 
                          :class="{ 'btn-loading': downloadingGalleryId === task.id }"
                          :disabled="downloadingGalleryId === task.id"
                          @click="downloadFile(task)"
                        >
                          <span v-if="downloadingGalleryId === task.id">打包中...</span>
                          <span v-else>下载</span>
                        </button>
                         <button class="btn btn-primary btn-sm" @click="playTask(task)">播放</button>
                        <button v-if="task.filename" class="btn btn-outline btn-sm" @click="openSliceManager(task)">切片</button>
                        <button class="btn btn-outline btn-sm text-danger" @click="deleteTask(task.id)">删除</button>
                      </template>
                      <template v-else>
                        <button class="btn btn-success btn-sm" @click="retryTask(task.id)">重试</button>
                        <button class="btn btn-outline btn-sm text-danger" @click="deleteTask(task.id)">删除</button>
                      </template>
                    </div>
                    <!-- 失败任务的时间组件，在重试/操作按钮下方显示 -->
                    <div class="task-time-inline error-time" v-if="task.status === 'ERROR' && task.created_at">
                      {{ formatDateTime(task.created_at) }}
                    </div>
                  </div>

                  <!-- 新增：订阅任务失败时的操作按钮旁友好滚动提示 -->
                  <div 
                    v-if="task.status === 'ERROR' && task.author_info" 
                    class="error-inline-tip"
                  >
                    <div class="error-inline-tip-text">
                      <span>💡 提示：点击博主 <strong class="highlight-author" @click.stop="goToSubscriptionDetail(task.author_info.subscription_id)">【{{ task.author_info.nickname }}】</strong> 可批量重试</span>
                      <span class="marquee-spacer" style="margin: 0 24px; opacity: 0.4;">✦</span>
                      <span>💡 提示：点击博主 <strong class="highlight-author" @click.stop="goToSubscriptionDetail(task.author_info.subscription_id)">【{{ task.author_info.nickname }}】</strong> 可批量重试</span>
                      <span class="marquee-spacer" style="margin: 0 24px; opacity: 0.4;">✦</span>
                    </div>
                  </div>
                  
                  <!-- 时间 (下载中或失败任务隐藏以节省高度/避免重复) -->
                  <div class="task-time-inline" v-if="task.created_at && !['DOWNLOADING', 'PROCESSING', 'PENDING', 'ERROR'].includes(task.status)">
                    {{ formatDateTime(task.created_at) }}
                  </div>
              </div>
            </div>

            <!-- 操作按钮 -->
          </div>
        </div>
      </Transition>
    </div>

    <!-- 空状态 -->
    <div class="empty-state" v-if="!downloadsStore.loading && downloadsStore.tasks.length === 0">
      <div class="empty-icon">
        <svg viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="60" cy="60" r="55" fill="url(#gradient)" fill-opacity="0.1"/>
          <circle cx="60" cy="60" r="40" stroke="url(#gradient)" stroke-width="2" stroke-dasharray="6 4"/>
          <path d="M60 35V75M60 75L45 60M60 75L75 60" stroke="url(#gradient)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
          <defs>
            <linearGradient id="gradient" x1="0" y1="0" x2="120" y2="120">
              <stop offset="0%" stop-color="#e74c3c"/>
              <stop offset="100%" stop-color="#f39c12"/>
            </linearGradient>
          </defs>
        </svg>
      </div>
      <h3 class="empty-title">暂无符合条件的任务</h3>
      <p class="empty-desc">当前筛选条件下没有任务，请调整筛选条件</p>
      <button class="btn btn-primary" @click="resetAllFilters" v-if="downloadsStore.hasActiveFilters">
        清除筛选条件
      </button>
    </div>
    
    <!-- 播放模态框：视频 / 音频 -->
    <div v-if="showVideoModal" class="modal-overlay" @click.self="closeVideoModal">
        <div class="video-modal" :class="{ 'audio-mode': isAudioPlayback }">
          <div class="modal-header">
            <h3>{{ currentVideoTitle }}</h3>
            <button class="close-btn" @click="closeVideoModal">×</button>
          </div>
          <div class="modal-body" v-if="!isAudioPlayback">
            <video 
              v-if="currentVideoUrl" 
              :src="currentVideoUrl" 
              controls 
              autoplay
              style="width: 100%; height: 100%; max-height: 80vh;"
            ></video>
          </div>
          <div class="modal-body audio-body" v-else>
            <div class="audio-visualizer">
              <div class="audio-main-content">
                <!-- 左侧：封面 -->
                <div class="audio-left-section">
                  <div class="audio-cover-wrapper">
                    <img :src="currentCoverUrl" alt="封面" class="audio-cover" />
                  </div>
                  <div class="audio-bars">
                    <span 
                      v-for="(height, index) in audioBarHeights" 
                      :key="index" 
                      class="bar"
                      :style="{ height: height + '%' }"
                    ></span>
                  </div>
                </div>
                
                <!-- 右侧：歌词显示 -->
                <div class="audio-right-section">
                  <div class="lyrics-panel">
                    <LyricsDisplay :lyricsUrl="currentLyricsUrl" :currentTime="currentAudioTime" />
                  </div>
                </div>
              </div>
              
              <audio
                v-if="currentVideoUrl"
                ref="audioRef"
                :src="currentVideoUrl"
                controls
                autoplay
                class="audio-element"
                @timeupdate="handleAudioTimeUpdate"
                @loadedmetadata="initAudioAnalyzer"
              ></audio>
            </div>
          </div>
        </div>
    </div>

    <!-- 图集预览模态框 (Gallery Viewer) -->
    <div v-if="showGalleryModal" class="modal-overlay gallery-viewer-overlay" @click.self="closeGalleryModal">
      <div class="gallery-modal">
        <div class="gallery-header">
          <div class="gallery-title-info">
            <span class="gallery-badge">图集</span>
            <h3 class="gallery-main-title">{{ currentGalleryTitle }}</h3>
          </div>
          <div class="gallery-controls">
            <span class="gallery-counter">{{ galleryCurrentIndex + 1 }} / {{ galleryItems.length }}</span>
            <button class="close-btn" @click="closeGalleryModal">×</button>
          </div>
        </div>
        
        <div class="gallery-body">
          <!-- 左右切换按钮 -->
          <button class="gallery-nav-btn prev" @click="prevGalleryItem" v-if="galleryItems.length > 1">
            <Icon name="chevron-left" :size="32" />
          </button>
          
          <div class="gallery-content-wrapper">
             <transition name="fade" mode="out-in">
               <div :key="galleryCurrentIndex" class="gallery-item-container">
                 <!-- 图片类型 -->
                 <img 
                   v-if="currentGalleryItem?.type === 'image'" 
                   :src="currentGalleryItem.url" 
                   class="gallery-media gallery-image" 
                   @click="nextGalleryItem"
                 />
                 <!-- 视频类型 -->
                 <video 
                   v-else-if="currentGalleryItem?.type === 'video'" 
                   :src="currentGalleryItem.url" 
                   class="gallery-media gallery-video" 
                   autoplay 
                   loop 
                   playsinline
                   controls
                 ></video>
               </div>
             </transition>
          </div>

          <button class="gallery-nav-btn next" @click="nextGalleryItem" v-if="galleryItems.length > 1">
            <Icon name="chevron-right" :size="32" />
          </button>
        </div>

        <!-- 背景音乐 -->
        <!-- 背景音乐 (隐藏播放) -->
        <audio v-if="galleryBgm" :src="galleryBgm.url" autoplay loop ref="galleryAudioRef" style="display: none;"></audio>
      </div>
    </div>
    <template v-if="isDownloadsRouteActive">
    <!-- 密码验证模态框 -->
    <div v-if="showPasswordModal" class="modal-overlay" @click.self="closePasswordModal">
        <div class="password-modal">
            <div class="modal-header">
                <h3>🔒 身份验证</h3>
                <button class="close-btn" @click="closePasswordModal">&times;</button>
            </div>
            <div class="password-modal-body">
                <p class="password-hint">此操作为敏感操作，请验证您的登录密码：</p>
                <div class="form-group">
                    <input 
                        type="password" 
                        v-model="passwordInput" 
                        @keyup.enter="handleVerifyPassword"
                        placeholder="请输入登录密码" 
                        class="password-input"
                        ref="passwordInputRef"
                        autofocus
                        autocomplete="new-password"
                    />
                    <div class="error-msg" v-if="passwordError">{{ passwordError }}</div>
                </div>
                <div class="modal-actions">
                    <button class="btn btn-secondary" @click="closePasswordModal">取消</button>
                    <button class="btn btn-danger" @click="handleVerifyPassword">确认清空</button>
                </div>
            </div>
        </div>
    </div>
    
    <!-- 确认清空弹窗 -->
    <Modal
        v-model:show="showConfirmModal"
        class="download-confirm-modal"
        :title="confirmTitle"
        type="warning"
        width="450px"
        :z-index="32000"
        :show-confirm="false"
    >
        <div v-html="confirmContent"></div>
        <template #footer>
            <button class="btn btn-secondary" @click="showConfirmModal = false" :disabled="isDeletingTask">取消</button>
            <button 
                class="btn btn-primary" 
                @click="handleConfirmClear" 
                style="margin-left: 12px;"
                :class="{ 'btn-loading': isDeletingTask }"
                :disabled="isDeletingTask"
            >
                <span v-if="isDeletingTask">删除中...</span>
                <span v-else>确定</span>
            </button>
        </template>
    </Modal>
    
    <!-- 自定义提示弹窗 -->
    <Modal v-model:show="showTipModal" :title="tipTitle" :type="tipType" :z-index="32000">
        <div v-html="tipMessage"></div>
        <!-- 输入框（用于 prompt 类型） -->
        <input 
            v-if="tipType === 'prompt'" 
            v-model="tipInputValue"
            type="text"
            placeholder="请输入开发者密码"
            class="tip-input"
            name="dev_clear_secret"
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
        <template #footer v-else>
            <button class="btn btn-primary" @click="handleTipConfirm">确定</button>
        </template>
    </Modal>

    <Modal
      v-model:show="sliceManagerVisible"
      title="手动切片"
      width="760px"
      :show-confirm="false"
    >
      <div class="slice-manager">
        <div class="slice-manager-head">
          <div class="slice-source-name">{{ sliceVideoTitle || '手动切片' }}</div>
          <div class="slice-manager-actions">
            <button class="btn btn-primary btn-sm" @click="openSliceEditorFromManager">新建切片</button>
            <button class="btn btn-outline btn-sm" @click="loadDownloadManualClips" :disabled="sliceClipsLoading">刷新</button>
            <button class="btn btn-outline btn-sm" @click="downloadDownloadClipsBundle" :disabled="sliceClips.length === 0 || sliceClipsLoading || sliceBundling">
              {{ sliceBundling ? '打包中...' : `批量导出(${sliceClips.length})` }}
            </button>
            <button class="btn btn-outline btn-sm text-danger" @click="cleanupDownloadClips" :disabled="sliceClips.length === 0 || sliceClipsLoading || sliceBundling">清空本视频</button>
          </div>
        </div>

        <div v-if="sliceClipsLoading" class="slice-empty">加载中...</div>
        <div v-else-if="sliceClips.length === 0" class="slice-empty">暂无手动切片</div>
        <div v-else class="slice-clip-list">
          <div v-for="clip in sliceClips" :key="clip.name" class="slice-clip-item">
            <div class="slice-clip-main">
              <div class="slice-clip-name">{{ clip.name }}</div>
              <div class="slice-clip-meta">
                {{ secToClock(clip.start_sec) }} → {{ secToClock(clip.end_sec) }}
                <span>·</span>
                {{ formatBytesLocal(clip.size_bytes) }}
                <span>·</span>
                {{ formatDateTime(clip.created_at) }}
              </div>
            </div>
            <div class="slice-clip-actions">
              <button class="btn btn-outline btn-sm" @click="playDownloadClip(clip)">播放</button>
              <button class="btn btn-outline btn-sm" @click="downloadDownloadClip(clip)" :disabled="sliceBundling">下载</button>
              <button class="btn btn-outline btn-sm text-danger" @click="deleteDownloadClip(clip)">删除</button>
            </div>
          </div>
        </div>
      </div>
    </Modal>
    </template>

    <!-- 视频列表模态框 -->
    <VideoListModal 
      v-model:show="showVideosModal"
      :subscriptionId="currentSubscription?.id"
      :platform="currentSubscription?.platform"
      :youtubeTabType="currentSubscription?.youtube_tab_type"
      :subscriptionType="currentSubscription?.subscription_type"
      :currentQuality="currentSubscription?.quality"
      :nickname="currentSubscription?.nickname"
      @qualityUpdated="handleQualityUpdated"
      @batchDownloadStarted="handleBatchDownloadStarted"
    />
  </div>

  <!-- 手动切片编辑器 -->
  <ClipEditor
    :show="sliceEditorVisible"
    :video-url="sliceVideoUrl"
    :title="sliceVideoTitle"
    :initial-duration="0"
    :ts-mode="sliceTsMode"
    @close="closeSliceEditor"
    @export="handleSliceExport"
    @seek="onSliceEditorSeek"
  />
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import Modal from '@/components/common/Modal.vue'
import ClipEditor from '@/components/business/ClipEditor.vue'
import liveHighlightsApi from '@/api/liveHighlights'
import LyricsDisplay from '@/components/business/LyricsDisplay.vue'
import { useDownloadsStore } from '@/stores/downloads'
import SkeletonLoader from '@/components/common/SkeletonLoader.vue'
import { wsService } from '@/utils/websocket'
import { tasksApi } from '@/api/tasks'
import { authApi } from '@/api/auth'
import { subscriptionsApi } from '@/api/subscriptions'
import VideoListModal from '@/components/business/VideoListModal.vue'

// 自定义指令：点击外部
const vClickOutside = {
  mounted(el, binding) {
    el.clickOutsideEvent = function(event) {
      if (!(el === event.target || el.contains(event.target))) {
        binding.value(event);
      }
    };
    document.body.addEventListener('click', el.clickOutsideEvent);
  },
  unmounted(el) {
    document.body.removeEventListener('click', el.clickOutsideEvent);
  }
}

import { useToast } from '@/composables/useToast'

const router = useRouter()
const route = useRoute()
const isDownloadsRouteActive = computed(() => route.path === '/downloads')
const downloadsStore = useDownloadsStore()
const toast = useToast()
const searchInput = ref('')
const PLACEHOLDER_IMAGE = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'

// 密码验证相关
const showPasswordModal = ref(false)
const passwordInput = ref('')
const passwordError = ref('')
const pendingClearParams = ref(null)

// 确认清空弹窗相关
const showConfirmModal = ref(false)
const confirmTitle = ref('')
const confirmContent = ref('')
const onConfirmAction = ref(null)

// 自定义提示弹窗相关
const showTipModal = ref(false)
const tipTitle = ref('')
const tipMessage = ref('')
const tipType = ref('info') // info, success, warning, error, prompt
const tipInputValue = ref('')
let tipResolve = null

// 图集下载加载状态
const downloadingGalleryId = ref(null)

// 订阅视频列表模态框相关
const showVideosModal = ref(false)
const currentSubscription = ref(null)

// 复制到剪贴板
async function copyToClipboard(text) {
    if (!text) return
    try {
        await navigator.clipboard.writeText(text)
        toast.info('错误详情已复制到剪贴板')
    } catch (err) {
        console.error('Failed to copy text:', err)
        // 兼容策略
        const textArea = document.createElement('textarea')
        textArea.value = text
        document.body.appendChild(textArea)
        textArea.select()
        try {
            document.execCommand('copy')
            toast.info('错误详情已复制到剪贴板')
        } catch (copyErr) {
            toast.error('复制失败')
        }
        document.body.removeChild(textArea)
    }
}


// 博主筛选相关
const showAuthorDropdown = ref(false)
const authorSearch = ref('')
const currentAuthorName = computed(() => {
    if (!downloadsStore.currentAuthorFilter) return ''
    const author = downloadsStore.authorList.find(a => a.subscription_id === downloadsStore.currentAuthorFilter)
    return author ? author.nickname : downloadsStore.currentAuthorFilter
})

const filteredAuthorsGroups = computed(() => {
    const term = authorSearch.value.toLowerCase()
    let authors = downloadsStore.authorList
    
    // 按当前平台筛选（例如选择“小红书”时，只显示小红书博主）
    if (downloadsStore.currentPlatformFilter && downloadsStore.currentPlatformFilter !== 'all') {
        const pf = downloadsStore.currentPlatformFilter
        authors = authors.filter(a => (a.platform || 'unknown') === pf)
    }

    if (term) {
        authors = authors.filter(a => 
            (a.nickname || '').toLowerCase().includes(term) ||
            (a.platform || '').toLowerCase().includes(term)
        )
    }

    // 按平台分组
    const groups = {}
    authors.forEach(author => {
        const platform = author.platform || 'unknown'
        if (!groups[platform]) groups[platform] = []
        groups[platform].push(author)
    })

    const platformOrder = ['douyin', 'xiaohongshu', 'tiktok', 'instagram', 'youtube', 'bilibili', 'netease', 'x', 'others', 'unknown']
    const result = []

    platformOrder.forEach(p => {
        if (groups[p] && groups[p].length > 0) {
            // 组内排序
            groups[p].sort((a, b) => (a.nickname || '').localeCompare(b.nickname || '', 'zh-CN'))
            result.push({
                platform: p,
                platformName: getPlatformDisplayName(p),
                authors: groups[p]
            })
        }
    })

    return result
})

// 分页显示逻辑
const displayedPages = computed(() => {
    const total = downloadsStore.totalPages
    const current = downloadsStore.currentPage
    const pages = []

    if (total <= 7) {
        for (let i = 1; i <= total; i++) pages.push(i)
    } else {
        pages.push(1)
        if (current > 3) pages.push('...')
        
        let start = Math.max(2, current - 1)
        let end = Math.min(total - 1, current + 1)
        
        if (current < 3) end = 3
        if (current > total - 2) start = total - 2
        
        for (let i = start; i <= end; i++) pages.push(i)
        
        if (current < total - 2) pages.push('...')
        pages.push(total)
    }
    return pages
})

// 缩略图缓存
const thumbnailCache = ref({})

// 悬停视频静音自动播放预览相关
const hoveredTaskId = ref(null)
const isPreviewPlaying = ref(false)
let hoverTimeout = null

function isVideoTask(task) {
    if (!task || task.status !== 'COMPLETED' || !task.filename) return false
    
    // 图集任务不是视频
    const isGallery = task.task_type_display && task.task_type_display.includes('图集')
    if (isGallery) return false
    
    // 音频文件后缀
    const isAudioFile = /\.(mp3|flac|m4a|wav|aac|ogg|opus)$/i.test(task.filename)
    if (isAudioFile) return false
    
    // 过滤出支持的视频后缀
    const isVideoFile = /\.(mp4|mkv|webm|avi|mov|flv|wmv|ts)$/i.test(task.filename)
    return isVideoFile
}

function getPlayableUrl(task) {
    if (!task || !task.filename) return ''
    
    // 统一platform处理
    let platform = (task.source || 'others').toLowerCase()
    if (platform === 'unknown' || platform === 'others') {
        platform = 'others'
    }
    
    let filename = task.filename
    let cleanFilename = filename
    
    if (filename.startsWith('subscriptions/')) {
        cleanFilename = filename
    } else {
        if (filename.startsWith(platform + '/')) {
            cleanFilename = filename.substring(platform.length + 1)
        } else if (filename.includes('/')) {
            const parts = filename.split('/')
            if (parts[0] === platform) {
                parts.shift()
                cleanFilename = parts.join('/')
            }
        }
    }
    
    const pathParts = cleanFilename.split('/').filter(part => part)
    const encodedParts = pathParts.map(part => encodeURIComponent(part))
    const encodedFilename = encodedParts.join('/')
    
    if (filename.startsWith('subscriptions/')) {
        return `/downloads/${encodedFilename}`
    } else {
        return `/downloads/${platform}/${encodedFilename}`
    }
}

function handleMouseEnter(task) {
    if (task.status !== 'COMPLETED' || !isVideoTask(task)) return
    
    if (hoverTimeout) clearTimeout(hoverTimeout)
    hoverTimeout = setTimeout(() => {
        hoveredTaskId.value = task.id
        isPreviewPlaying.value = false
    }, 200)
}

function handleMouseLeave() {
    if (hoverTimeout) clearTimeout(hoverTimeout)
    hoveredTaskId.value = null
    isPreviewPlaying.value = false
}

// 处理路由参数
function handleRouteQuery() {
    const { status } = route.query
    if (status) {
        // 确保状态值在允许范围内
        if (['all', 'active', 'completed', 'error', 'cancelled'].includes(status)) {
            downloadsStore.setFilter(status)
            return true
        }
    }
    return false
}

// 监听路由变化
watch(() => route.query, () => {
    handleRouteQuery()
}, { deep: true })

onMounted(async () => {
  // 初始处理路由参数
  const routeTriggeredFetch = handleRouteQuery()

  await downloadsStore.fetchAuthors()
  if (!routeTriggeredFetch) {
    await downloadsStore.fetchTasks(1)
  }
  
  // 连接 WebSocket 获取实时进度
  wsService.connect('downloads')
})

// 启动 WebSocket 监听
const unregister = wsService.onMessage((id, data) => {
  if (id === 'downloads' && data.type === 'progress_update') {
    downloadsStore.handleProgressUpdate(data)
  }
})

onUnmounted(() => {
  if (unregister) unregister()
  wsService.close('downloads')
  if (hoverTimeout) clearTimeout(hoverTimeout)
})

// 监听任务列表变化，更新缩略图
watch(() => downloadsStore.tasks, (newTasks) => {
    newTasks.forEach(task => {
        if (!thumbnailCache.value[task.id]) {
            loadThumbnail(task)
        }
    })
}, { deep: true })

function handleSearch() {
    downloadsStore.setSearchQuery(searchInput.value)
}

function toggleAuthorDropdown() {
    showAuthorDropdown.value = !showAuthorDropdown.value
    if (showAuthorDropdown.value) {
        authorSearch.value = ''
    }
}

function closeAuthorDropdown() {
    showAuthorDropdown.value = false
}

function selectAuthor(author) {
    downloadsStore.setAuthorFilter(author.subscription_id)
    closeAuthorDropdown()
}

function resetAllFilters() {
    searchInput.value = ''
    downloadsStore.resetFilters()
}

// 跳转到批量下载任务页面
function goToBatchDownloadTasks() {
  router.push('/batch-download-tasks')
}

// 跳转到订阅详情并执行定位
async function goToSubscriptionDetail(subscriptionId) {
  if (!subscriptionId) return
  
  try {
    // 获取订阅详情信息以供模态框使用
    const sub = await subscriptionsApi.getDetail(subscriptionId)
    if (sub) {
      currentSubscription.value = sub
      showVideosModal.value = true
    }
  } catch (error) {
    console.error('获取订阅详情失败:', error)
    toast.error('获取订阅详情失败，请重试')
    // 降级方案：跳转到订阅页面
    router.push({
      path: '/subscriptions',
      query: { sub_id: subscriptionId }
    })
  }
}

// 视频列表模态框的回调
function handleQualityUpdated(quality) {
  if (currentSubscription.value) {
    currentSubscription.value.quality = quality
  }
}

function handleBatchDownloadStarted() {
  // 可以在这里处理批量下载开始的消息，或者直接刷下载列表
  downloadsStore.fetchTasks(1)
}

// 处理页码选择
function handlePageSelect(event) {
    const page = parseInt(event.target.value)
    if (page >= 1 && page <= downloadsStore.totalPages) {
        downloadsStore.goToPage(page)
    }
}

// 辅助函数
function getPlatformDisplayName(source) {
    const map = {
        'douyin': '抖音',
        'xiaohongshu': '小红书',
        'tiktok': 'TikTok',
        'instagram': 'Instagram',
        'youtube': '油管',
        'bilibili': 'B站',
        'netease': '网易云音乐',
        'x': 'X',
        'others': '其他'
    }
    return map[(source || '').toLowerCase()] || source || '其他'
}

function getPlatformIcon(source) {
  const map = {
    youtube: 'globe',
    bilibili: 'film',
    douyin: 'play',
    tiktok: 'play',
    instagram: 'image',
    xiaohongshu: 'image',
    netease: 'music',
    x: 'globe'
  }
  return map[(source || '').toLowerCase()] || 'download'
}

// 时间格式化
function formatDateTime(dateStr) {
    if (!dateStr) return ''
    const date = new Date(dateStr)
    const Y = date.getFullYear()
    const M = (date.getMonth() + 1).toString().padStart(2, '0')
    const D = date.getDate().toString().padStart(2, '0')
    const h = date.getHours().toString().padStart(2, '0')
    const m = date.getMinutes().toString().padStart(2, '0')
    return `${Y}-${M}-${D} ${h}:${m}`
}

// 智能缩略图生成
async function loadThumbnail(task) {
    if (task.status !== 'COMPLETED' || !task.filename) return
    
    // 1. 如果已有缓存，跳过
    if (thumbnailCache.value[task.id]) return

    // 2. 统一平台名称处理
    let platform = (task.source || 'others').toLowerCase()
    if (platform.includes('douyin')) platform = 'douyin'
    if (platform.includes('bilibili')) platform = 'bilibili'
    if (platform.includes('youtube')) platform = 'youtube'
    if (platform.includes('tiktok')) platform = 'tiktok'
    if (platform.includes('instagram')) platform = 'instagram'
    if (platform.includes('netease')) platform = 'netease'
    if (platform === 'unknown' || platform === '') platform = 'others'

    // 3. 使用 API 获取本地缩略图
    try {
        // 检测是否为订阅任务
        let isSubscription = !!task.subscription_id || (task.filename && task.filename.includes('subscriptions/'));
        
        // 清理文件路径
        let fullPath = task.filename.replace(/^\/+/, '').replace(/\/+$/, '');
        
        // 如果路径包含视频或音频文件扩展名，则去掉文件名保留目录路径
        let subscriptionPath = fullPath;
        let videoFilename = null;
        
        // 检查是否是视频或音频文件
        if (fullPath.match(/\.(mp4|mkv|avi|mov|flv|webm|mp3|flac|m4a|wav|aac|ogg)$/i)) {
            const pathParts = fullPath.split('/');
            videoFilename = pathParts[pathParts.length - 1]; // 提取文件名
            subscriptionPath = pathParts.slice(0, -1).join('/'); // 移除文件名，保留目录路径
        }
        
        const parts = subscriptionPath.split('/');
        let apiPlatform = platform;
        let folderPath = '';
        
        if (isSubscription) {
            // 订阅路径格式：subscriptions/platform/author/[folder]
            if (parts[0] === 'subscriptions' && parts.length >= 3) {
                apiPlatform = parts[1]; // platform
                const authorName = parts[2]; // author
                const folderName = parts[3]; // folder (可能不存在，合集情况)
                
                if (folderName) {
                    // 有子文件夹：普通订阅
                    folderPath = `${authorName}/${folderName}`;
                } else {
                    // 没有子文件夹：合集
                    folderPath = authorName;
                }
            } else {
                // 兜底：使用整个路径
                folderPath = subscriptionPath;
            }
        } else {
            // 手动下载路径格式：platform/folder
            if (parts.length >= 2 && (parts[0] === apiPlatform || parts[0] === 'others' || parts[0] === 'netease')) {
                // 第一部分是平台名，使用它
                apiPlatform = parts[0];
                // folder_path 是剩余的路径
                folderPath = parts.slice(1).join('/');
            } else {
                // 没有平台前缀，直接使用路径作为folder
                folderPath = subscriptionPath;
            }
        }
        
        // 构建API参数
        const apiParams = {
            platform: apiPlatform,
            folder_path: folderPath || '.',
            subscription: isSubscription
        };
        
        if (videoFilename) {
            apiParams.video_filename = videoFilename;
        }
        
        const data = await tasksApi.getGalleryThumbnail(apiParams);
        
        if (data && data.success && data.thumbnail_path) {
            // 组装缩略图URL - 对路径的每个部分进行编码
            let thumbPath = data.thumbnail_path
            
            // 对路径的每个部分进行 URL 编码（处理中文和特殊字符）
            const encodedThumbPath = thumbPath.split('/').map(encodeURIComponent).join('/')
            
            // 添加 /downloads/ 前缀（如果没有）
            const fullPath = encodedThumbPath.startsWith('downloads/') 
                ? `/${encodedThumbPath}` 
                : `/downloads/${encodedThumbPath}`
            
            const ts = task.updated_at ? new Date(task.updated_at).getTime() : Date.now()
            thumbnailCache.value[task.id] = `${fullPath}?t=${ts}`
        }
    } catch (error) {
        console.error('[Thumbnail] Error loading thumbnail:', error);
        // 出错时，如果是YouTube且已经设置了在线封面，保留它
        // 否则不设置缩略图
    }
}



function extractYoutubeId(url) {
  if (!url) return null
  const regExp = /^.*(youtu\.be\/|v\/|u\/\w\/|embed\/|watch\?v=|\&v=)([^#\&\?]*).*/
  const match = url.match(regExp)
  return (match && match[2].length === 11) ? match[2] : null
}

function handleThumbnailError(task) {
    thumbnailCache.value[task.id] = null
}

function getTaskTitle(task) {
    if (task.title) return task.title
    
    let title = task.filename || task.url || '未知任务'
    if (title.endsWith('.mp4')) title = title.slice(0, -4)
    
    // 如果是目录形式（以 / 结尾），去掉末尾斜杠再取最后一部分
    if (title.endsWith('/')) {
        title = title.substring(0, title.length - 1)
    }
    
    return title.split('/').pop()
}

function getTaskTypeClass(task) {
    const typeDisplay = task.task_type_display || ''
    
    // 优先使用后端返回的 task_type_display
    if (typeDisplay) {
        if (typeDisplay.includes('图集')) return 'badge-gallery'
        if (typeDisplay.includes('合集')) return 'badge-collection'
        if (typeDisplay.includes('订阅')) return 'badge-subscription'
        if (typeDisplay === '手动') return 'badge-manual'
    }
    
    // 兜底逻辑：通过 subscription_id 和 filename 判断
    const isSubscription = task.subscription_id || (task.filename && task.filename.includes('subscriptions/'))
    const isGallery = task.url && task.url.includes('/note/')
    
    if (isSubscription && isGallery) return 'badge-gallery'
    if (isSubscription) return 'badge-subscription'
    if (isGallery) return 'badge-gallery'
    
    return 'badge-manual'
}

function getTaskTypeText(task) {
    // 优先使用后端返回的 task_type_display
    if (task.task_type_display) {
        return task.task_type_display
    }
    
    // 兜底逻辑：根据任务属性推断类型
    const isSubscription = task.subscription_id || (task.filename && task.filename.includes('subscriptions/'))
    const isGallery = task.url && task.url.includes('/note/')
    const authorInfo = task.author_info || {}
    const authorPlatform = (authorInfo.platform || '').toLowerCase()
    const youtubeTabType = (authorInfo.youtube_tab_type || '').toLowerCase()
    
    if (isSubscription) {
        // 订阅任务
        if (isGallery) {
            return '订阅图集'
        }
        
        // 根据平台区分
        if (authorPlatform === 'youtube') {
            if (youtubeTabType === 'shorts') return '订阅油管短视频'
            if (youtubeTabType === 'playlists') return '订阅油管合集'
            return '订阅油管博主'
        }
        if (authorPlatform === 'youtube_playlist') return '订阅油管合集'
        if (authorPlatform === 'bilibili_collection') return '订阅B站合集'
        if (authorPlatform === 'bilibili') {
            // 区分B站博主、合集和收藏
            if (authorInfo.is_collection) return '订阅B站合集'
            if (authorInfo.subscription_type === 'favorite') return '订阅B站收藏'
            return '订阅B站博主'
        }
        if (authorPlatform === 'douyin' || authorPlatform.includes('douyin')) {
            if (authorInfo.is_collection) return '订阅抖音合集'
            return '订阅抖音博主'
        }
        if (authorPlatform === 'xiaohongshu') return '订阅小红书'
        if (authorPlatform === 'tiktok') return '订阅TikTok'
        
        // 检查 is_collection 标记
        if (authorInfo.is_collection) return '订阅合集'
        
        return '订阅博主'
    }
    
    // 手动任务
    if (isGallery) return '手动图集'
    
    return '手动下载'
}

function getProgressClass(status) {
  if (status === 'DOWNLOADING') return 'progress-blue'
  if (status === 'PROCESSING') return 'progress-purple'
  return 'progress-gray'
}

// 操作函数 (保持不变)
// 删除任务的 loading 状态（用于弹窗）
const isDeletingTask = ref(false)
// 取消任务的 loading 状态集合（用于列表按钮）
const cancelingTaskIds = ref(new Set())
const sliceEditorVisible = ref(false)
const sliceVideoUrl = ref('')
const sliceVideoTitle = ref('')
const sliceTask = ref(null)
const sliceTsMode = ref(false)
const sliceManagerVisible = ref(false)
const sliceClips = ref([])
const sliceClipsLoading = ref(false)
const sliceBundling = ref(false)

async function retryTask(id) {
  try { await tasksApi.retryTask(id); downloadsStore.fetchTasks() } catch (err) { console.error(err) }
}
async function cancelTask(id) {
  if (cancelingTaskIds.value.has(id)) return
  cancelingTaskIds.value.add(id)
  try { 
      await tasksApi.deleteTask(id, false, false); 
      // 延迟一点刷新，让用户感觉到状态变化
      setTimeout(() => {
          downloadsStore.fetchTasks() 
          cancelingTaskIds.value.delete(id)
      }, 500)
  } catch (err) { 
      console.error(err)
      cancelingTaskIds.value.delete(id)
  }
}
function deleteTask(id) {
    const targetTask = downloadsStore.tasks.find(t => t.id === id)
    const taskTitle = targetTask ? getTaskTitle(targetTask) : id
    const sourceText = targetTask ? getPlatformDisplayName(targetTask.source) : '未知'
    const taskTypeText = targetTask ? getTaskTypeText(targetTask) : '未知'
    const safeTitle = String(taskTitle || '').replace(/</g, '&lt;').replace(/>/g, '&gt;')

    // 1. 设置弹窗内容
    confirmTitle.value = '确定删除任务？'
    confirmContent.value = `
      <div class="confirm-content">
        <p>确定要删除该任务吗？</p>
        <ul class="scope-list">
          <li class="scope-item">来源：${sourceText}</li>
          <li class="scope-item">类型：${taskTypeText}</li>
          <li class="scope-item">标题：${safeTitle}</li>
        </ul>
        <div class="warning-box">
          <div class="warning-title">删除影响</div>
          <ul>
            <li>将删除任务记录</li>
            <li>将尝试清理该任务关联的成品文件与临时文件</li>
            <li>若为订阅任务，将重置关联视频下载状态</li>
          </ul>
        </div>
      </div>
    `
    
    // 2. 设置回调
    onConfirmAction.value = async () => {
        if (isDeletingTask.value) return
        isDeletingTask.value = true
        try {
            await tasksApi.deleteTask(id)
            downloadsStore.removeTask(id)
            showConfirmModal.value = false
        } catch (err) {
            console.error(err)
            toast.error('删除失败: ' + (err.message || '未知错误'))
        } finally {
            isDeletingTask.value = false
        }
    }
    
    // 3. 显示弹窗
    showConfirmModal.value = true
}
function downloadFile(task) {
    // 判断是否为图集任务
    const isGallery = task.task_type_display && task.task_type_display.includes('图集')
    
    if (isGallery) {
        // 图集任务：调用打包下载 API（需要携带认证 token）
        downloadingGalleryId.value = task.id  // 设置加载状态
        
        const token = localStorage.getItem('token')
        fetch(`/api/tasks/${task.id}/download-gallery`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('下载失败')
            }
            return response.blob()
        })
        .then(blob => {
            const url = window.URL.createObjectURL(blob)
            const link = document.createElement('a')
            link.href = url
            link.download = `${task.title || '图集'}.zip`
            document.body.appendChild(link)
            link.click()
            document.body.removeChild(link)
            window.URL.revokeObjectURL(url)
        })
        .catch(error => {
            console.error('图集下载失败:', error)
            alert('图集打包下载失败，请重试')
        })
        .finally(() => {
            downloadingGalleryId.value = null  // 清除加载状态
        })
        return
    }
    
    // 非图集任务：保持原有下载逻辑
    // 统一platform处理
    let platform = (task.source || 'others').toLowerCase()
    if (platform === 'unknown' || platform === 'others') {
        platform = 'others'
    }
    
    // 处理文件路径
    let filename = task.filename || ''
    let cleanFilename = filename
    
    // 检查是否是订阅路径（已经包含完整路径）
    if (filename.startsWith('subscriptions/')) {
        // 订阅路径已经完整，直接使用
        cleanFilename = filename
    } else {
        // 手动下载路径，需要添加platform前缀
        // 如果路径以platform开头，移除platform部分
        if (filename.startsWith(platform + '/')) {
            cleanFilename = filename.substring(platform.length + 1)
        } else if (filename.includes('/')) {
            // 如果路径包含斜杠但不是以platform开头，检查第一个部分是否是platform
            const parts = filename.split('/')
            if (parts[0] === platform) {
                parts.shift() // 移除第一个部分（platform）
                cleanFilename = parts.join('/')
            }
        }
    }
    
    // 确保路径正确
    const pathParts = cleanFilename.split('/').filter(part => part)
    const encodedParts = pathParts.map(part => encodeURIComponent(part))
    const encodedFilename = encodedParts.join('/')
    
    // 构建下载URL
    let downloadUrl
    if (filename.startsWith('subscriptions/')) {
        // 订阅路径：直接使用，不添加platform前缀
        downloadUrl = `/downloads/${encodedFilename}`
    } else {
        // 手动下载路径：添加platform前缀
        downloadUrl = `/downloads/${platform}/${encodedFilename}`
    }
    
    // 创建一个隐藏的链接并点击
    const link = document.createElement('a')
    link.href = downloadUrl
    link.download = pathParts[pathParts.length - 1] || 'download'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
}

// 视频/音频播放
const showVideoModal = ref(false)
const currentVideoUrl = ref('')
const currentVideoTitle = ref('')
const isAudioPlayback = ref(false)
const currentCoverUrl = ref('')
const audioRef = ref(null)
const currentAudioTime = ref(0)
const currentTaskFilename = ref('') // 保存当前任务的filename

// 图集查看器相关状态
const showGalleryModal = ref(false)
const galleryItems = ref([])
const galleryBgm = ref(null)
const galleryCurrentIndex = ref(0)
const currentGalleryTitle = ref('')
const galleryAudioRef = ref(null)

const currentGalleryItem = computed(() => {
  if (galleryItems.value.length === 0) return null
  return galleryItems.value[galleryCurrentIndex.value]
})

function nextGalleryItem() {
  if (galleryItems.value.length <= 1) return
  galleryCurrentIndex.value = (galleryCurrentIndex.value + 1) % galleryItems.value.length
}

function prevGalleryItem() {
  if (galleryItems.value.length <= 1) return
  galleryCurrentIndex.value = (galleryCurrentIndex.value - 1 + galleryItems.value.length) % galleryItems.value.length
}

async function openGalleryViewer(task) {
    try {
        let platform = (task.source || 'others').toLowerCase()
        let isSubscription = !!task.subscription_id || (task.filename && task.filename.includes('subscriptions/'))
        
        // 解析文件夹路径
        let fullPath = task.filename.replace(/^\/+/, '').replace(/\/+$/, '');
        let folderPath = fullPath;
        
        // 如果路径包含视频或音频文件扩展名，则由上一层级作为图集目录
        if (fullPath.match(/\.(mp4|mkv|avi|mov|flv|webm|mp3|flac|m4a|wav|aac|ogg)$/i)) {
            folderPath = fullPath.split('/').slice(0, -1).join('/');
        }
        
        // 修正 folderPath 提取逻辑（类似 loadThumbnail）
        const parts = folderPath.split('/');
        let apiPlatform = platform;
        let finalFolderPath = '';
        
        if (isSubscription) {
            if (parts[0] === 'subscriptions' && parts.length >= 3) {
                apiPlatform = parts[1];
                finalFolderPath = parts.slice(2).join('/');
            } else {
                finalFolderPath = folderPath;
            }
        } else {
            if (parts.length >= 2 && (parts[0] === apiPlatform || parts[0] === 'others')) {
                apiPlatform = parts[0];
                finalFolderPath = parts.slice(1).join('/');
            } else {
                finalFolderPath = folderPath;
            }
        }

        const res = await tasksApi.getGalleryFiles({
            platform: apiPlatform,
            folder_path: finalFolderPath || '.',
            subscription: isSubscription
        });

        if (res && res.success) {
            galleryItems.value = res.media_items;
            galleryBgm.value = res.bgm;
            galleryCurrentIndex.value = 0;
            currentGalleryTitle.value = getTaskTitle(task);
            showGalleryModal.value = true;
        } else {
            customAlert('获取失败', '无法获取图集内容', 'error');
        }
    } catch (error) {
        console.error('Gallery Viewer Error:', error);
        customAlert('预览失败', error.message || '系统错误', 'error');
    }
}

function closeGalleryModal() {
    showGalleryModal.value = false;
    galleryItems.value = [];
    galleryBgm.value = null;
    galleryCurrentIndex.value = 0;
}

// 音频可视化相关
const audioBarHeights = ref(Array(16).fill(10)) // 16个bar的高度，初始为10%
let audioContext = null
let analyser = null
let sourceNode = null
let animationFrameId = null

// 当前歌词URL
const currentLyricsUrl = computed(() => {
  if (!currentTaskFilename.value || !isAudioPlayback.value) return ''
  
  // 将音频文件扩展名替换为.lyrics.lrc
  const lyricsFilename = currentTaskFilename.value.replace(/\.(mp3|flac|m4a|wav|aac|ogg)$/i, '.lyrics.lrc')
  
  return `/downloads/${encodeURIComponent(lyricsFilename)}`
})

// 音频时间更新
function handleAudioTimeUpdate() {
  if (audioRef.value) {
    currentAudioTime.value = audioRef.value.currentTime
  }
}

// 初始化音频分析器
function initAudioAnalyzer() {
  if (!audioRef.value || !isAudioPlayback.value) return
  
  try {
    // 先停止之前的可视化
    stopAudioVisualization()
    
    // 如果AudioContext已关闭或不存在，创建新的
    if (!audioContext || audioContext.state === 'closed') {
      audioContext = new (window.AudioContext || window.webkitAudioContext)()
    }
    
    // Web Audio API 限制：一个 HTMLMediaElement 只能创建一个 MediaElementSource
    // 我们保持 sourceNode 为单例，避免重复连接报错
    if (!sourceNode) {
      try {
        sourceNode = audioContext.createMediaElementSource(audioRef.value)
      } catch (error) {
        console.warn('MediaElementSource 创建失败:', error)
      }
    }
    
    // 创建 AnalyserNode
    analyser = audioContext.createAnalyser()
    analyser.fftSize = 64 // 32个频率数据点
    analyser.smoothingTimeConstant = 0.8 // 平滑系数
    
    // 重新连接节点：source -> analyser -> destination
    if (sourceNode && analyser) {
      try {
        // 先断开旧连接
        try { sourceNode.disconnect() } catch (e) {}
        try { analyser.disconnect() } catch (e) {}
        
        // 重新建立正确的连接链
        sourceNode.connect(analyser)
        analyser.connect(audioContext.destination)
      } catch (e) {
        console.debug('节点连接错误:', e)
        // 兜底：确保音频能输出
        try { sourceNode.connect(audioContext.destination) } catch (e2) {}
      }
    }
    
    // 确保 AudioContext 处于运行状态
    if (audioContext.state === 'suspended') {
      audioContext.resume().catch(() => {})
    }
    
    // 开始可视化
    startAudioVisualization()
  } catch (error) {
    console.warn('初始化音频分析器失败:', error)
    // 如果初始化失败，重置状态
    stopAudioVisualization()
  }
}

// 开始音频可视化
function startAudioVisualization() {
  if (!analyser) return
  
  const bufferLength = analyser.frequencyBinCount // 通常是 fftSize / 2
  const dataArray = new Uint8Array(bufferLength)
  
  const updateVisualization = () => {
    if (!analyser || !isAudioPlayback.value) {
      animationFrameId = null
      return
    }
    
    // 获取频率数据
    analyser.getByteFrequencyData(dataArray)
    
    // 将32个频率数据点映射到16个bar
    const barCount = 16
    const step = Math.floor(bufferLength / barCount)
    const newHeights = []
    
    for (let i = 0; i < barCount; i++) {
      let sum = 0
      // 取多个数据点的平均值，使可视化更平滑
      for (let j = 0; j < step; j++) {
        sum += dataArray[i * step + j] || 0
      }
      const average = sum / step
      // 将0-255的值转换为10-100%的高度（最小10%保证可见）
      const height = Math.max(10, Math.min(100, (average / 255) * 90 + 10))
      newHeights.push(height)
    }
    
    audioBarHeights.value = newHeights
    animationFrameId = requestAnimationFrame(updateVisualization)
  }
  
  // 停止之前的动画
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId)
  }
  
  updateVisualization()
}

// 停止音频可视化
function stopAudioVisualization() {
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId)
    animationFrameId = null
  }
  
  // 注意：不要断开 sourceNode，也不要将其置为 null
  // 保持单例以规避重复创建 MediaElementSourceNode 的限制
  if (sourceNode && analyser) {
    try {
      sourceNode.disconnect(analyser)
    } catch (e) {}
  }
  
  if (analyser) {
    try {
      analyser.disconnect()
    } catch (e) {}
    analyser = null
  }
  
  // 重置bar高度
  audioBarHeights.value = Array(16).fill(10)
}

function playTask(task) {
    // 统一跳转到 Player.vue 播放器（包括图集任务）
    if (!task.id) {
        customAlert('播放失败', '无法获取任务ID', 'error')
        return
    }
    
    // 判断是否为订阅任务
    const subscriptionId = task.subscription_id || task.author_info?.subscription_id || null
    const isSubscription = !!subscriptionId || (task.filename && task.filename.includes('subscriptions/'))
    
    // 构建查询参数
    const query = { task_id: task.id }
    // 如果是订阅任务，同时传递 subscription_id，这样会加载该博主的所有视频到播放列表
    if (isSubscription && subscriptionId) {
        query.subscription_id = subscriptionId
    }
    
    router.push({ path: '/player', query }).then(() => {
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
function closeVideoModal() {
  // 停止音频可视化
  stopAudioVisualization()
  
  // 完全清理音频资源
  // 因为模态框使用 v-if，关闭时 audio 元素会被销毁
  // 下次打开会创建新的 audio 元素，所以需要重置 sourceNode
  if (sourceNode) {
    try { sourceNode.disconnect() } catch (e) {}
    sourceNode = null
  }
  
  if (audioContext && audioContext.state !== 'closed') {
    audioContext.close().catch(() => {})
    audioContext = null
  }
  
  showVideoModal.value = false
  currentVideoUrl.value = ''
  isAudioPlayback.value = false
  currentCoverUrl.value = ''
  currentTaskFilename.value = ''
  currentAudioTime.value = 0
}
// 获取清空按钮文本
function getClearButtonText() {
    const filter = downloadsStore.currentFilter
    const authorFilter = downloadsStore.currentAuthorFilter
    const platformFilter = downloadsStore.currentPlatformFilter
    const manualOnly = downloadsStore.currentManualOnly
    const orphanOnly = downloadsStore.currentOrphanOnly
    const queryText = (downloadsStore.searchQuery || '').trim()
    
    // 状态映射
    const statusMap = { 
        all: '所有', 
        active: '进行中', 
        completed: '已完成', 
        error: '失败',
        cancelled: '已取消'
    }
    const platformMap = { 
        douyin: '抖音', 
        tiktok: 'TikTok', 
        instagram: 'Instagram',
        youtube: 'YouTube', 
        bilibili: 'B站', 
        xiaohongshu: '小红书', 
        netease: '网易云音乐', 
        unknown: '未知平台',
        others: '其他' 
    }
    
    const parts = []
    
    // 博主
    if (authorFilter) {
        const author = downloadsStore.authorList.find(a => a.subscription_id === authorFilter)
        parts.push(author ? author.nickname : '博主')
    }
    
    // 平台
    if (platformFilter && platformFilter !== 'all') {
        parts.push(platformMap[platformFilter] || platformFilter)
    }
    
    // 仅手动
    if (manualOnly) parts.push('手动')
    
    // 仅孤儿
    if (orphanOnly) parts.push('孤儿')

    // 关键词
    if (queryText) parts.push(`关键词:${queryText}`)
    
    // 状态
    if (filter !== 'all') {
        parts.push(statusMap[filter] || filter)
    }
    
    if (parts.length > 0) {
        return `清空：${parts.join(' · ')}`
    }
    return '清空所有任务'
}

// 智能清空当前筛选的任务
async function clearFilteredTasks() {
    const filter = downloadsStore.currentFilter
    const authorFilter = downloadsStore.currentAuthorFilter
    const platformFilter = downloadsStore.currentPlatformFilter
    const manualOnly = downloadsStore.currentManualOnly
    const orphanOnly = downloadsStore.currentOrphanOnly
    const queryText = (downloadsStore.searchQuery || '').trim()
    
    // 构建确认信息
    const statusMap = { 
        all: '所有', 
        active: '进行中', 
        completed: '已完成', 
        error: '失败',
        cancelled: '已取消'
    }
    const platformMap = { 
        douyin: '抖音', 
        tiktok: 'TikTok', 
        instagram: 'Instagram',
        youtube: 'YouTube', 
        bilibili: 'B站', 
        xiaohongshu: '小红书', 
        netease: '网易云音乐', 
        unknown: '未知平台',
        others: '其他' 
    }
    
    // 检查是否是清空所有任务（无任何筛选条件）
    const isClearAll = !authorFilter && (!platformFilter || platformFilter === 'all') && !manualOnly && !orphanOnly && (!filter || filter === 'all') && !queryText
    
    // 构建清空范围描述
    const scopeLines = []
    if (authorFilter) {
        const author = downloadsStore.authorList.find(a => a.subscription_id === authorFilter)
        scopeLines.push(`• 博主：${author ? author.nickname : '未知博主'}`)
    }
    if (platformFilter && platformFilter !== 'all') {
        scopeLines.push(`• 平台：${platformMap[platformFilter] || platformFilter}`)
    }
    if (manualOnly) scopeLines.push('• 类型：仅手动')
    if (orphanOnly) scopeLines.push('• 类型：仅孤儿（文件缺失）')
    if (queryText) scopeLines.push(`• 关键词：${queryText}`)
    scopeLines.push(`• 状态：${statusMap[filter] || '所有'}`)
    
    const estimatedCount = Number(downloadsStore.totalTasks || 0)
    // 构建提示消息
    const scopeText = isClearAll 
        ? '所有下载任务' 
        : `<strong style="color: var(--color-primary);">${scopeLines.length}</strong> 个筛选条件`

    const scopeDetails = scopeLines.length > 0 ? `<div style="margin-top: 10px; padding: 10px; background: #f5f5f5; border-radius: 4px; font-size: 0.9em;">${scopeLines.join('<br>')}</div>` : ''
    
    const now = new Date()
    const todayPassword = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`

    // 使用和订阅管理一样的验证逻辑
    const password = await customPrompt('开发者工具', `
        <div style="text-align: left;">
            <p style="margin-bottom: 15px;">${isClearAll ? '确定要清空所有下载任务吗？' : '确定要清空以下范围的任务吗？'}</p>
            <p style="margin-bottom: 10px;">预计将删除：<strong style="color:#d9534f;">${estimatedCount}</strong> 条任务记录</p>
            ${scopeDetails}
            <div style="margin-top: 12px; padding: 10px; background: #fff8e1; border-left: 4px solid #f0ad4e; border-radius: 4px; font-size: 0.9em;">
              <div style="font-weight: 600; margin-bottom: 6px;">删除影响</div>
              <div>• 将删除任务记录</div>
              <div>• 将尝试清理关联成品文件与临时文件</div>
              <div>• 关联订阅视频的下载状态会被重置</div>
            </div>
            <p style="color: #856404; font-size: 0.9em; margin-top: 12px; margin-bottom: 12px; padding: 8px 10px; background: #fff3cd; border-radius: 4px;">
              ⏱ 清空操作会逐条删除文件，${estimatedCount} 条任务可能需要一定时间。确认后可在后台执行，无需等待，稍后刷新即可查看结果。
            </p>
            <p style="color: #666; font-size: 0.9em; margin-top: 15px; margin-bottom: 8px;">此为开发者工具，请输入开发者密码：</p>
            <p style="color: #666; font-size: 0.9em; margin-bottom: 15px;">密码为当天日期（YYYYMMDD），例如：<strong>${todayPassword}</strong></p>
            </div>
    `)
    if (!password) return

    // 立即提示用户无需等待
    toast.info(`正在清空 ${estimatedCount} 条任务，稍后刷新即可查看结果`)

    try {
        // 准备参数
    const params = { delete_files: true }
    if (authorFilter) params.subscription_id = authorFilter
        if (filter !== 'all') {
            // 将前端的状态映射转换为后端状态
            const statusMap = {
                'active': 'active',      // 后端会转换为 PENDING + DOWNLOADING + PROCESSING
                'completed': 'COMPLETED',
                'error': 'ERROR',
                'cancelled': 'CANCELLED'
            }
            params.status = statusMap[filter] || filter
        }
    if (platformFilter && platformFilter !== 'all') params.platform = platformFilter
    if (manualOnly) params.manual_only = true
    if (orphanOnly) params.orphan_only = true
    if (queryText) params.query = queryText

        await tasksApi.clearTasks(params, password)

        // 刷新任务列表
        await downloadsStore.fetchTasks(1)

        // 如果清空了博主任务，刷新博主列表
        if (authorFilter) {
            await downloadsStore.fetchAuthors()
        }

        toast.success(`${isClearAll ? '所有任务' : '任务'}已成功清空`)
    } catch (error) {
        console.error('清空操作:', error)
        if (error.response && error.response.status === 403) {
            customAlert('密码错误', '开发者口令错误，无法执行清空操作', 'error')
        } else if (error.code === 'ECONNABORTED' || String(error.message || '').toLowerCase().includes('timeout')) {
            toast.info('请求已超时，但清空操作可能在后台继续执行，请刷新查看实际结果')
        } else {
            toast.error(`清空失败: ${error.message || '未知错误'}`)
        }
    }
}

function handleConfirmClear() {
    if (onConfirmAction.value) {
        onConfirmAction.value()
    }
}

function closePasswordModal() {
    showPasswordModal.value = false
    passwordInput.value = ''
    passwordError.value = ''
    pendingClearParams.value = null
}

// 自定义提示弹窗函数
function customAlert(title, message, type = 'info') {
    tipTitle.value = title
    tipMessage.value = message
    tipType.value = type
    showTipModal.value = true
}

// 模拟输入框（用于密码输入）
function customPrompt(title, message) {
    return new Promise((resolve) => {
        tipTitle.value = title
        tipMessage.value = message
        tipType.value = 'prompt'
        tipInputValue.value = ''
        showTipModal.value = true
        tipResolve = resolve
    })
}

function customConfirm(title, message) {
    return new Promise((resolve) => {
        tipTitle.value = title
        tipMessage.value = message
        tipType.value = 'confirm'
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
        tipResolve = null
    }
}

function handleTipCancel() {
    showTipModal.value = false
    if (tipResolve) {
        // 取消时返回 null（prompt）或 false（confirm）
        const result = tipType.value === 'prompt' ? null : false
        tipResolve(result)
        tipResolve = null
    }
}

async function handleVerifyPassword() {
    if (!passwordInput.value) {
        passwordError.value = '请输入密码'
        return
    }

    try {
        await authApi.verifyPassword(passwordInput.value)
        
        // 密码验证成功，执行清空
        if (pendingClearParams.value) {
            await tasksApi.clearTasks(pendingClearParams.value)
            
            // 刷新任务列表
            await downloadsStore.fetchTasks(1)
            
            // 如果清空了博主任务，刷新博主列表
            if (pendingClearParams.value.subscription_id) {
                await downloadsStore.fetchAuthors()
            }
            
            customAlert('清空成功', '任务已成功清空', 'success')
            closePasswordModal()
        }
    } catch (error) {
        console.error('操作失败:', error)
        if (error.response && error.response.status === 401) {
             passwordError.value = '密码错误'
        } else {
             passwordError.value = '验证失败: ' + (error.message || '未知错误')
        }
    }
}

// ===== 手动切片 =====
function getSliceFilePath(task = sliceTask.value) {
  if (!task?.filename) return ''
  return `/app/downloads/${task.filename.replace(/^\/+/, '')}`
}

function openSliceManager(task) {
  if (!task?.filename) return
  sliceTask.value = task
  const cleanPath = task.filename.replace(/^\/+/, '')
  sliceVideoTitle.value = task.title || cleanPath.split('/').pop() || '手动切片'
  sliceManagerVisible.value = true
  loadDownloadManualClips()
}

function openSliceEditor(task) {
  if (!task.filename) return
  sliceTask.value = task
  const cleanPath = task.filename.replace(/^\/+/, '')
  sliceTsMode.value = /\.ts$/i.test(cleanPath)
  const token = localStorage.getItem('token')
  let url = `/api/video/stream?filename=${encodeURIComponent(cleanPath)}&quality=original`
  if (sliceTsMode.value) url += `&start=0`
  if (token) url += `&token=${encodeURIComponent(token)}`
  sliceVideoUrl.value = url
  sliceVideoTitle.value = task.title || cleanPath.split('/').pop() || '手动切片'
  sliceEditorVisible.value = true
}
function openSliceEditorFromManager() {
  if (!sliceTask.value) return
  sliceManagerVisible.value = false
  openSliceEditor(sliceTask.value)
}
function closeSliceEditor() {
  sliceEditorVisible.value = false
  sliceVideoUrl.value = ''
  if (!sliceManagerVisible.value) {
    sliceVideoTitle.value = ''
    sliceTask.value = null
  }
}
async function handleSliceExport({ startSec, endSec }) {
  const task = sliceTask.value
  if (!task || !task.filename) return
  try {
    const res = await liveHighlightsApi.manualExportByPath({
      file_path: getSliceFilePath(task),
      start_sec: startSec,
      end_sec: endSec,
      overwrite: true,
    })
    if (res?.success && res?.clip_path) {
      closeSliceEditor()
      await loadDownloadManualClips()
      sliceManagerVisible.value = false
      toast.success('切片完成')
    } else {
      throw new Error(res?.clip_error || '导出失败')
    }
  } catch (e) {
    console.error('切片失败:', e)
    const detail = e?.response?.data?.detail || e?.response?.data?.message || e?.message
    toast.error(detail ? `切片失败：${detail}` : '切片失败')
  }
}
function onSliceEditorSeek(sec) {
  const task = sliceTask.value
  if (!task || !task.filename) return
  const cleanPath = task.filename.replace(/^\/+/, '')
  const token = localStorage.getItem('token')
  let url = `/api/video/stream?filename=${encodeURIComponent(cleanPath)}&quality=original&start=${sec}`
  if (token) url += `&token=${encodeURIComponent(token)}`
  sliceVideoUrl.value = url
}

async function loadDownloadManualClips() {
  const filePath = getSliceFilePath()
  if (!filePath) return
  sliceClipsLoading.value = true
  try {
    const res = await liveHighlightsApi.getManualClipsByPath(filePath)
    sliceClips.value = Array.isArray(res?.clips) ? res.clips : []
  } catch (e) {
    console.error('加载手动切片失败:', e)
    sliceClips.value = []
  } finally {
    sliceClipsLoading.value = false
  }
}

function secToClock(sec) {
  const s = Math.max(0, Math.floor(sec || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const x = s % 60
  if (h > 0) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`
  return `${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`
}

function formatBytesLocal(bytes) {
  const size = Number(bytes || 0)
  if (size <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = size
  let idx = 0
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024
    idx += 1
  }
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`
}

function downloadBlob(blob, filename) {
  if (!(blob instanceof Blob)) throw new Error('无效的下载数据')
  const blobUrl = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = blobUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(blobUrl)
}

function playDownloadClip(clip) {
  if (!clip?.path) return
  const relative = String(clip.path || '').replace(/^\/app\/downloads\//, '')
  const token = localStorage.getItem('token')
  let url = `/api/video/stream?filename=${encodeURIComponent(relative)}&quality=original`
  if (token) url += `&token=${encodeURIComponent(token)}`
  window.open(url, '_blank')
}

async function downloadDownloadClip(clip) {
  const filePath = getSliceFilePath()
  if (!filePath || !clip?.name || sliceBundling.value) return
  sliceBundling.value = true
  try {
    const blob = await liveHighlightsApi.downloadManualClipByPath(filePath, clip.name)
    downloadBlob(blob, clip.name)
    toast.success('切片下载开始')
  } catch (e) {
    console.error('下载切片失败:', e)
    toast.error('下载失败')
  } finally {
    sliceBundling.value = false
  }
}

async function downloadDownloadClipsBundle() {
  const filePath = getSliceFilePath()
  if (!filePath || sliceClips.value.length === 0 || sliceBundling.value) return
  sliceBundling.value = true
  try {
    const names = sliceClips.value.map(clip => clip.name).filter(Boolean)
    const blob = await liveHighlightsApi.downloadManualClipsBundleByPath(filePath, names)
    downloadBlob(blob, `manual_clips_${Date.now()}.zip`)
    toast.success('资源包下载开始')
  } catch (e) {
    console.error('批量导出失败:', e)
    toast.error('批量导出失败')
  } finally {
    sliceBundling.value = false
  }
}

async function deleteDownloadClip(clip) {
  const filePath = getSliceFilePath()
  if (!filePath || !clip?.name) return
  const confirmed = await customConfirm('删除手动切片', `确定删除 <strong>${clip.name}</strong> 吗？`)
  if (!confirmed) return
  try {
    await liveHighlightsApi.deleteManualClipByPath(filePath, clip.name)
    await loadDownloadManualClips()
    toast.success('已删除手动切片')
  } catch (e) {
    console.error('删除切片失败:', e)
    toast.error('删除失败')
  }
}

async function cleanupDownloadClips() {
  const filePath = getSliceFilePath()
  if (!filePath || sliceClips.value.length === 0) return
  const confirmed = await customConfirm(
    '清空本视频切片',
    `确定删除当前视频的全部 <strong>${sliceClips.value.length}</strong> 个手动切片吗？<br><br><strong>此操作不可恢复。</strong>`
  )
  if (!confirmed) return
  try {
    const resp = await liveHighlightsApi.cleanupManualClipsByPath(filePath)
    sliceClips.value = []
    toast.success(`已清空 ${resp?.removed_files || 0} 个切片`)
  } catch (e) {
    console.error('清空切片失败:', e)
    toast.error('清空失败')
  }
}
</script>

<style scoped>
.downloads-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-bottom: 40px;
}

/* 顶部工具栏 */
.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 0;
  flex-wrap: nowrap;
}

.filter-tabs {
  display: flex;
  background: var(--color-bg-secondary);
  padding: 4px;
  border-radius: 8px;
  gap: 4px;
  flex-shrink: 0;
}

.filter-tab {
  padding: 6px 16px;
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-secondary);
  border-radius: 6px;
  transition: all 0.2s;
  cursor: pointer;
  border: none;
  background: transparent;
}
.filter-tab:hover { color: var(--color-text-primary); background: rgba(0,0,0,0.05); }
.filter-tab.active { background: var(--color-primary); color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }

/* 桌面端隐藏移动端清空按钮 */
.filter-tab-clear-mobile {
  display: none;
}

/* 订阅系统任务入口容器 */
.batch-tasks-container {
  display: flex;
  align-items: center;
  margin-left: 12px;
  padding-left: 12px;
  border-left: 1px solid var(--color-border);
  flex-shrink: 0;
}

[data-theme="dark"] .batch-tasks-container {
  border-left-color: rgba(255, 255, 255, 0.08);
}

/* 订阅系统任务入口按钮 */
.btn-batch-tasks {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 14px;
  white-space: nowrap;
  height: 40px; /* 与搜索框高度一致 */
}

.btn-batch-tasks:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: rgba(230, 126, 34, 0.05);
}

[data-theme="dark"] .btn-batch-tasks {
  background: #1e1e1e;
  border-color: rgba(255, 255, 255, 0.08);
}

[data-theme="dark"] .btn-batch-tasks:hover {
  background: rgba(230, 126, 34, 0.1);
  border-color: var(--color-primary);
}

.btn-batch-tasks .btn-text {
  display: inline;
}

/* 桌面端隐藏移动端搜索框 */
.search-box-mobile {
  display: none !important;
}

/* 桌面端：只在工具栏右侧显示搜索框 */
@media (min-width: 769px) {
  .advanced-filters .search-box-mobile {
    display: none !important;
  }
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--color-bg-secondary);
  width: 140px;
  height: 40px; /* 统一高度 */
  transition: all 0.2s;
}
.search-box:focus-within {
  border-color: var(--color-primary);
  background: #fff;
}

[data-theme="dark"] .search-box:focus-within {
  background: var(--color-bg-secondary);
}
.search-box input { border: none; background: transparent; width: 100%; outline: none; font-size: 14px; }

/* 高级筛选栏 */
.advanced-filters {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    background: #fff;
    padding: 8px 12px;
    border-radius: 8px;
    border: 1px solid var(--color-border);
}

[data-theme="dark"] .advanced-filters {
    background: #1e1e1e;
    border-color: rgba(255, 255, 255, 0.08);
}

.author-select-container { position: relative; min-width: 260px; }
.author-selector {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px; /* 统一高度 */
    border: 1px solid var(--color-border);
    border-radius: 6px; /* 统一圆角 */
    cursor: pointer;
    background: var(--color-bg-secondary); /* 统一背景 */
    font-size: 14px; /* 统一字体 */
    transition: all 0.2s;
    height: 40px; /* 显式高度以确保对齐 */
    width: 100%;
}
.author-placeholder {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
    margin-right: 8px;
}
.author-selector:hover { border-color: #bbb; }
[data-theme="dark"] .author-selector:hover { border-color: var(--color-border-light); }
.author-selector.active { border-color: var(--color-primary); background: #fff; }
[data-theme="dark"] .author-selector.active { background: var(--color-bg-tertiary); }

.form-select {
    padding: 8px 12px;
    border-radius: 6px;
    border: 1px solid var(--color-border);
    background: var(--color-bg-secondary);
    font-size: 14px;
    height: 40px; /* 显式高度 */
    outline: none;
    cursor: pointer;
}
.form-select:focus { border-color: var(--color-primary); }

.author-dropdown {
    position: absolute;
    top: 100%; left: 0; right: 0;
    margin-top: 4px;
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 6px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    z-index: 100;
    max-height: 300px;
    display: flex;
    flex-direction: column;
}

[data-theme="dark"] .author-dropdown {
    background: var(--color-bg-card);
    border-color: var(--color-border);
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}

.author-search-input { padding: 8px; border-bottom: 1px solid #eee; }
[data-theme="dark"] .author-search-input { border-bottom-color: var(--color-border); }
.author-search-input input { width: 100%; padding: 6px; border: 1px solid #eee; border-radius: 4px; font-size: 12px; }
[data-theme="dark"] .author-search-input input { 
    border-color: var(--color-border); 
    background: var(--color-bg-secondary);
    color: var(--color-text-primary);
}
.author-list { overflow-y: auto; flex: 1; }
.platform-header { 
    padding: 6px 12px; 
    background: #f8f9fa; 
    font-size: 11px; 
    color: #999; 
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
    position: sticky;
    top: 0;
    z-index: 1;
}
[data-theme="dark"] .platform-header { 
    background: var(--color-bg-tertiary); 
    color: var(--color-text-tertiary); 
}
.platform-header .platform-subtitle {
    font-size: 11px;
    font-weight: 400;
    color: #adb5bd;
}
[data-theme="dark"] .platform-header .platform-subtitle {
    color: var(--color-text-tertiary);
}
.author-item { 
    padding: 6px 12px; 
    font-size: 13px; 
    cursor: pointer; 
    border-bottom: 1px solid #f5f5f5; 
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
}
.author-item-name {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
    display: flex;
    align-items: center;
    gap: 4px;
}
.author-item-count {
    color: #999;
    font-size: 11px;
    flex-shrink: 0;
}

[data-theme="dark"] .author-item-count {
    color: var(--color-text-tertiary);
}

.author-platform-tag {
    padding: 1px 4px;
    border-radius: 4px;
    font-size: 10px;
    color: #6c757d;
    background: #f1f3f5;
    flex-shrink: 0;
}
[data-theme="dark"] .author-platform-tag {
    background: var(--color-bg-tertiary);
    color: var(--color-text-tertiary);
}

.author-item:hover { background: #f0f7ff; }
[data-theme="dark"] .author-item:hover { background: var(--color-bg-hover); }
.author-item.selected { background: var(--color-primary-light); color: var(--color-primary); }
[data-theme="dark"] .author-item.selected { 
    background: rgba(230, 126, 34, 0.2); 
    color: var(--color-primary);
}

[data-theme="dark"] .author-item {
    border-bottom-color: var(--color-border);
    color: var(--color-text-primary);
}

/* 复选框组 */
.checkbox-group {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
}

.filter-checkbox { 
    display: flex; 
    align-items: center; 
    gap: 6px; 
    font-size: 14px; 
    cursor: pointer; 
    user-select: none;
    flex: 1;
    min-width: 100px;
}

/* 操作按钮组 */
.action-buttons-group {
    display: flex;
    gap: 10px;
    align-items: stretch;
}

.btn-filter-action {
    flex: 0 0 auto;
    white-space: nowrap;
}

.btn-clear-action {
    flex: 0 0 auto;
    white-space: nowrap;
    color: #ffffff !important; /* 桌面端也确保文字为白色 */
    background: linear-gradient(135deg, #d32f2f 0%, #f44336 100%);
    border: none;
}

.btn-clear-action .icon {
    color: #ffffff !important; /* 确保图标为白色 */
}

.btn-clear-action:hover:not(:disabled) {
    background: linear-gradient(135deg, #c62828 0%, #e53935 100%);
    color: #ffffff !important;
}

/* 分页控件 - 修复样式 */
.pagination-bar {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 8px;
    margin: 10px 0;
}

.footer-pagination {
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid var(--color-border);
}

/* 内联分页（在操作按钮组中） */
.inline-pagination {
    margin: 0;
    padding: 0;
    border: none;
    flex: 1;
    justify-content: flex-start;
    min-width: 0;
}

.inline-pagination .page-info {
    margin-left: 10px;
    white-space: nowrap;
    flex-shrink: 1;
    min-width: 0;
}

.inline-pagination .page-select {
    margin-left: 10px;
}
.page-numbers {
    display: flex; /* 关键修复：水平排列页码 */
    gap: 4px;
    align-items: center;
}
.page-btn, .page-number {
    min-width: 28px;
    height: 32px;
    padding: 0 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--color-border);
    background: var(--color-bg-card) !important;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    color: var(--color-text-primary);
    transition: all 0.2s;
    font-weight: 500;
}
.page-btn:disabled, .page-number:disabled { 
    opacity: 0.5; 
    cursor: not-allowed; 
    background: var(--color-bg-tertiary); 
    border-color: var(--color-border);
    color: var(--color-text-muted);
}
.page-number:hover:not(:disabled) { 
    border-color: var(--color-primary); 
    color: var(--color-primary); 
    background: var(--color-bg-hover) !important;
}
.page-number.active { 
    background: var(--color-primary) !important; 
    color: #fff !important; 
    border-color: var(--color-primary) !important;
    font-weight: 600;
}
.page-number.ellipsis { border: none; background: transparent; cursor: default; }
.page-info { 
    font-size: 13px; 
    color: var(--color-text-secondary); 
    margin-left: 10px; 
    white-space: nowrap;
}

/* 页码选择下拉框 */
.page-select {
    height: 32px;
    padding: 0 8px;
    padding-right: 24px;
    border: 1px solid var(--color-border);
    border-radius: 4px;
    background: var(--color-bg-card);
    font-size: 13px;
    color: var(--color-text-primary);
    cursor: pointer;
    outline: none;
    margin-left: 10px;
    transition: all 0.2s;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23999' d='M6 9L1 4h10z'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 8px center;
    background-size: 12px;
}

.page-select:hover {
    border-color: var(--color-primary);
}

.page-select:focus {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.1);
}

/* 任务列表优化 */
.task-list { display: flex; flex-direction: column; gap: 10px; }

/* 电脑端双列布局 */
@media (min-width: 1200px) {
  .task-list {
    display: grid;
    grid-template-columns: repeat(2, 1fr); /* 默认为双列，或者是4列？原代码是repeat(4, 1fr) */
    gap: 16px;
  }

  /* 同步 Grid 到内容包装器，确保过渡动画不破坏布局 */
  .task-content-wrapper {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
    grid-column: 1 / -1;
  }
  
  /* 确保加载状态在 Grid 布局中占满整行 */
  .loading-state, .skeleton-loader-container {
    grid-column: 1 / -1;
    display: flex;
    flex-direction: column;
    align-items: center; 
    justify-content: center;
    padding: 40px;
  }
}

/* 如果屏幕更宽，可以使用 4 列 */
@media (min-width: 1800px) {
  .task-list, .task-content-wrapper {
    grid-template-columns: repeat(3, 1fr);
  }
}

.task-card {
  display: flex;
  flex-direction: row;
  height: 125px;
  align-items: stretch;
  width: 100%;
  min-width: 0;
  background: var(--color-bg-card);
  border: 1.5px solid rgba(0, 0, 0, 0.12);
  border-radius: 8px;
  overflow: hidden;
  transition: all 0.2s ease;
  position: relative;
  padding: 0 !important;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

[data-theme="dark"] .task-card {
  background: #1e1e1e; /* 稍深一点的灰色，更有质感 */
  border-color: rgba(255, 255, 255, 0.08); /* 降低默认边框亮度 */
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
}

.task-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  border-color: var(--color-primary);
}

[data-theme="dark"] .task-card:hover {
  border-color: rgba(230, 126, 34, 0.5); /* 悬停时才显现品牌色边框 */
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5);
  background: #252525;
}

[data-theme="dark"] .task-card.task-active { 
  border-color: rgba(230, 126, 34, 0.4); 
  box-shadow: 0 0 20px rgba(230, 126, 34, 0.15); /* 替代原本的模糊图层 */
} 

/* 移除了性能开销巨大的 filter: blur 动态光晕，改用更高效的 CSS Box Shadow */

/* 确保内部元素在光晕之上 */
.task-thumbnail,
.task-content {
  position: relative;
  z-index: 1;
}

.task-thumbnail {
  width: 80px;
  height: 100%;
  overflow: hidden;
  position: relative;
  background: var(--color-bg-tertiary);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  margin: 0 !important;
  padding: 0 !important;
  border-radius: 0 !important;
  border-top-left-radius: 7px !important;
  border-bottom-left-radius: 7px !important;
}
.clickable-thumbnail {
  cursor: pointer;
}
.thumbnail-img { 
  width: 100%; 
  height: 100%; 
  object-fit: cover;
  display: block;
  transition: transform 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.task-card:hover .thumbnail-img {
  transform: scale(1.06);
}
.thumbnail-placeholder { 
  width: 100%; 
  height: 100%; 
  display: flex; 
  align-items: center; 
  justify-content: center; 
  color: var(--color-text-muted); 
  transition: transform 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.task-card:hover .thumbnail-placeholder {
  transform: scale(1.06);
}
.play-overlay { position: absolute; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; opacity: 0; cursor: pointer; color: #fff; transition: opacity 0.2s; z-index: 3; }
.task-thumbnail:hover .play-overlay { opacity: 1; }

.thumbnail-video-preview {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  z-index: 2;
  pointer-events: none;
  background: #000;
  opacity: 0;
  transform: scale(1);
  transition: opacity 0.35s ease, transform 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.thumbnail-video-preview.is-playing {
  opacity: 1;
  transform: scale(1.06);
}

.task-content { 
  flex: 1; 
  display: flex; 
  flex-direction: column; 
  gap: 2px; 
  min-width: 0; 
  padding: 8px 12px;
  justify-content: space-between;
}

.task-header { 
  display: flex; 
  align-items: flex-start; 
  justify-content: space-between;
  gap: 8px;
}

.task-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.platform-badge-mini {
  padding: 0 4px;
  height: 16px;
  line-height: 15px;
  font-size: 10px;
  border-radius: 2px;
  background: #555;
  color: #fff;
  flex-shrink: 0;
}
.platform-badge-mini.douyin { background: #000; }
.platform-badge-mini.bilibili { background: #00a1d6; }
.platform-badge-mini.youtube { background: #ff0000; }
.platform-badge-mini.netease { background: #E53E3E; }

.task-title-link {
  text-decoration: none;
  display: block;
  flex: 1;
  min-width: 0;
}

.task-title-link:hover .task-title {
  color: var(--color-primary);
  text-decoration: underline;
}

.task-title { 
  font-size: 14px; 
  font-weight: 600; 
  color: var(--color-text-primary); 
  margin: 0; 
  overflow: hidden; 
  text-overflow: ellipsis; 
  white-space: nowrap; 
  line-height: 1.4; 
  transition: color 0.2s;
}

.task-time-top {
  position: absolute;
  top: 8px;
  right: 12px;
  font-size: 10px;
  color: var(--color-text-muted);
  white-space: nowrap;
  pointer-events: none;
}

.task-badges {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.badge { 
  font-size: 10px; 
  padding: 1px 6px; 
  border-radius: 3px; 
  white-space: nowrap; 
  font-weight: 500;
  display: inline-flex;
  align-items: center;
}

[data-theme="dark"] .author-badge { 
  background: rgba(114, 46, 209, 0.15); 
  color: #a87df0; 
  border-color: rgba(114, 46, 209, 0.3);
}

.status-badge-container { 
  display: flex; 
  align-items: center; 
  gap: 6px; 
  flex-shrink: 0; 
}

.badge { font-size: 11px; padding: 2px 8px; border-radius: 4px; white-space: nowrap; font-weight: 500; }
.platform-badge { background: #555; color: #fff; }
.platform-badge.douyin { background: #000; }
.platform-badge.bilibili { background: #00a1d6; }
.platform-badge.youtube { background: #ff0000; }
.platform-badge.netease { background: #E53E3E; }

.type-badge { border: 1px solid #ddd; color: #666; font-size: 10px; background: #f9f9f9; }
.type-badge.badge-subscription { background: #e6f7ff; color: #1890ff; border-color: #91d5ff; }
.type-badge.badge-collection { background: #fff7e6; color: #fa8c16; border-color: #ffd591; }
.type-badge.badge-gallery { background: #f6ffed; color: #52c41a; border-color: #b7eb8f; }
.type-badge.badge-manual { background: #f0f2f5; color: #64748b; border-color: #d1d5db; }

.author-badge { 
  background: #f9f0ff; 
  color: #722ed1; 
  border: 1px solid #d3adf7;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clickable-author {
  cursor: pointer;
  transition: all 0.2s;
}

.clickable-author:hover {
  background: #722ed1;
  color: #fff;
  border-color: #531dab;
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.badge-link {
  background: #e6f7ff;
  color: #1890ff;
  border: 1px solid #91d5ff;
  text-decoration: none;
  transition: all 0.2s;
}

.badge-link:hover {
  background: #bae7ff;
  border-color: #69c0ff;
}

.slice-manager {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.slice-manager-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.slice-source-name {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  color: var(--text-primary, #333);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.slice-manager-actions,
.slice-clip-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.slice-manager-actions {
  flex-shrink: 0;
  flex-wrap: nowrap;
}

.slice-empty {
  padding: 28px 12px;
  text-align: center;
  color: var(--text-secondary, #888);
  background: var(--bg-secondary, #f8f8f8);
  border-radius: 8px;
}

.slice-clip-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 420px;
  overflow-y: auto;
}

.slice-clip-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border-color, #eee);
  border-radius: 8px;
  background: var(--bg-secondary, #f8f8f8);
}

.slice-clip-main {
  min-width: 0;
  flex: 1;
}

.slice-clip-name {
  font-weight: 600;
  color: var(--text-primary, #333);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.slice-clip-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 3px;
  color: var(--text-secondary, #888);
  font-size: 12px;
  flex-wrap: wrap;
}

/* 深色模式适配：降低标签亮度 */
[data-theme="dark"] .platform-badge { background: #333; color: #bbb; }
[data-theme="dark"] .platform-badge.douyin { background: #000; color: #999; border: 1px solid #222; }
[data-theme="dark"] .platform-badge.bilibili { background: rgba(0, 161, 214, 0.2); color: #00a1d6; border: 1px solid rgba(0, 161, 214, 0.3); }
[data-theme="dark"] .platform-badge.youtube { background: rgba(255, 0, 0, 0.15); color: #ff4d4f; border: 1px solid rgba(255, 0, 0, 0.25); }
[data-theme="dark"] .platform-badge.netease { background: rgba(229, 62, 62, 0.2); color: #fc8181; border: 1px solid rgba(229, 62, 62, 0.3); }

[data-theme="dark"] .type-badge { background: #2d2d2d; color: #888; border-color: #444; }
[data-theme="dark"] .type-badge.badge-subscription { background: rgba(24, 144, 255, 0.1); color: #177ddc; border-color: #1765ad; }
[data-theme="dark"] .type-badge.badge-collection { background: rgba(250, 140, 22, 0.1); color: #d87a16; border-color: #aa6215; }
[data-theme="dark"] .type-badge.badge-gallery { background: rgba(82, 196, 26, 0.1); color: #49aa19; border-color: #3c8618; }
[data-theme="dark"] .type-badge.badge-manual { background: rgba(100, 116, 139, 0.1); color: #64748b; border-color: #475569; }

.task-meta-row { display: flex; gap: 16px; font-size: 12px; color: #666; align-items: center; }
.author-info { display: flex; align-items: center; gap: 4px; min-width: 0; flex: 1; max-width: 200px; }
.author-name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source-link a { text-decoration: none; color: #999; }
.source-link a:hover { color: var(--color-primary); text-decoration: underline; }

.task-progress { margin-top: 8px; }
.progress-bar { height: 8px; background: #eee; border-radius: 4px; overflow: hidden; position: relative; width: 100%; }
.progress-fill { height: 100%; transition: width 0.3s ease; border-radius: 4px; width: 0; }

/* 状态基色 - 使用 background-color 避免被 stripes 的 background-image 覆盖 */
.progress-blue .progress-fill { background-color: #3498db; }
.progress-purple .progress-fill { background-color: #9b59b6; }
.progress-gray .progress-fill { background-color: #bdc3c7; }

.progress-blue .progress-fill,
.progress-purple .progress-fill {
    position: relative;
    overflow: hidden;
}

.progress-blue .progress-fill::after,
.progress-purple .progress-fill::after {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 300%;
    height: 100%;
    background-image: linear-gradient(
        45deg,
        rgba(255, 255, 255, 0.2) 25%,
        transparent 25%,
        transparent 50%,
        rgba(255, 255, 255, 0.2) 50%,
        rgba(255, 255, 255, 0.2) 75%,
        transparent 75%,
        transparent
    );
    background-size: 1rem 1rem;
    /* 使用 transform 替代 background-position，避免触发重排重绘，极大地降低 GPU 压力 */
    animation: progress-bar-stripes-optimized 1.5s linear infinite;
    will-change: transform;
}

@keyframes progress-bar-stripes-optimized {
    from { transform: translateX(0); }
    to { transform: translateX(1rem); }
}

.progress-text { 
  display: flex; 
  justify-content: flex-end; 
  align-items: center;
  gap: 8px;
  font-size: 11px; 
  color: #666; 
  margin-top: 4px; 
}

.error-inline-scroller {
  display: inline-block;
  max-width: 250px;
  overflow: hidden;
  white-space: nowrap;
  background: rgba(255, 77, 79, 0.06);
  border: 1px solid rgba(255, 77, 79, 0.15);
  color: #ff4d4f;
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 11px;
  margin-left: 8px;
  cursor: pointer;
  vertical-align: middle;
  position: relative;
  text-overflow: clip;
}

[data-theme="dark"] .error-inline-scroller {
  background: rgba(255, 77, 79, 0.12);
  border-color: rgba(255, 77, 79, 0.25);
}

.error-scroller-text {
  display: inline-block;
  white-space: nowrap;
  animation: error-inline-ticker 15s linear infinite; /* 统一滚动速度为 15s，视觉阅读更加平稳舒适 */
}

/* 仅在文字非常长需要展示时通过 hover 或是直接持续滚动显示出来 */
@keyframes error-inline-ticker {
  0% { transform: translate3d(0, 0, 0); }
  100% { transform: translate3d(-50%, 0, 0); }
}

.error-message {
  font-size: 12px;
  color: #ff4d4f;
  background: rgba(255, 77, 79, 0.05);
  padding: 6px 10px;
  border-radius: 4px;
  margin-top: 4px;
  /* 文本截断核心样式 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
  cursor: pointer;
  transition: all 0.2s;
  user-select: none;
}

.error-message:hover {
  background: rgba(255, 77, 79, 0.12);
  color: #e53e3e;
}

.error-message:active {
  transform: scale(0.98);
  background: rgba(255, 77, 79, 0.2);
}

[data-theme="dark"] .error-message {
  background: rgba(255, 77, 79, 0.1);
}

[data-theme="dark"] .error-message:hover {
  background: rgba(255, 77, 79, 0.2);
}

.error-inline-tip {
  flex: 1;
  margin-left: 12px;
  margin-right: 12px;
  overflow: hidden;
  white-space: nowrap;
  font-size: 11px;
  color: var(--color-text-secondary);
  background: rgba(230, 126, 34, 0.04);
  border: 1px dashed rgba(230, 126, 34, 0.15);
  padding: 3px 8px;
  border-radius: 4px;
  line-height: 1.4;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  position: relative;
  text-overflow: clip;
  height: 28px;           /* 高度与按钮保持一致 (28px) */
  align-self: flex-start; /* 靠顶部对齐，从而与按钮群组顶部对齐 */
  box-sizing: border-box; /* 保证 padding 不拉伸总高度 */
}

[data-theme="dark"] .error-inline-tip {
  background: rgba(230, 126, 34, 0.06);
  border-color: rgba(230, 126, 34, 0.25);
  color: #a0a0a0;
}

.error-inline-tip-text {
  display: inline-block;
  white-space: nowrap;
  animation: error-inline-tip-ticker 15s linear infinite;
}

@keyframes error-inline-tip-ticker {
  0% { transform: translate3d(0, 0, 0); }
  100% { transform: translate3d(-50%, 0, 0); }
}

.highlight-author {
  color: var(--color-primary);
  cursor: pointer;
  text-decoration: underline;
  font-weight: 600;
  transition: color 0.2s;
}

.highlight-author:hover {
  color: #f39c12;
}

.status-text { font-size: 13px; font-weight: 600; }
.status-text.completed { color: #52c41a; }
.status-text.error { color: #ff4d4f; }

.status-badge.completed { 
  background: #f6ffed; 
  color: #52c41a; 
  border: 1px solid #b7eb8f;
}
[data-theme="dark"] .status-badge.completed { 
  background: rgba(82, 196, 26, 0.15); 
  color: #49aa19; 
  border-color: rgba(82, 196, 26, 0.3);
}

.status-badge.error { 
  background: #fff2f0; 
  color: #ff4d4f; 
  border: 1px solid #ffccc7;
}
[data-theme="dark"] .status-badge.error { 
  background: rgba(255, 77, 79, 0.15); 
  color: #ff4d4f; 
  border-color: rgba(255, 77, 79, 0.3);
}

.task-actions { 
  display: flex; 
  flex-direction: row; 
  align-items: center;
  justify-content: space-between;
  gap: 8px; 
  margin-top: -8px; /* 大幅上移 */
  position: relative;
  z-index: 2;
}

.btns-group-wrapper {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.btns-group {
  display: flex;
  gap: 6px;
  align-items: center;
}

.task-actions .btn {
  padding: 4px 10px;
  height: 28px;
  font-size: 12px;
  white-space: nowrap;
}

[data-theme="dark"] .task-actions .btn-primary {
  background: linear-gradient(135deg, #af3024 0%, #c47d0e 100%) !important;
  border: none !important;
  color: rgba(255, 255, 255, 0.9) !important;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.3) !important;
}

[data-theme="dark"] .task-actions .btn-primary:hover {
  background: linear-gradient(135deg, #bd3427 0%, #d68910 100%) !important;
  box-shadow: 0 6px 14px rgba(0, 0, 0, 0.4) !important;
}

.task-time-inline {
  font-size: 10px;
  color: var(--color-text-muted);
  white-space: nowrap;
  flex-shrink: 0;
  text-align: right;
  margin-top: 4px;
}

.task-time-inline.error-time {
  text-align: left;
  margin-top: 2px;
}

.task-meta-inline {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-top: 8px;
  font-size: 12px;
  color: #666;
  white-space: nowrap;
  flex-shrink: 0;
}

.meta-link {
  color: #1890ff;
  text-decoration: none;
  transition: color 0.2s;
}

.meta-link:hover {
  color: #40a9ff;
  text-decoration: underline;
}

.meta-time {
  color: #999;
}

.modal-overlay { position: fixed; inset: 0; background: transparent; z-index: 1000; display: flex; align-items: center; justify-content: center; }
.video-modal {
  width: 70%;
  max-width: 900px;
  background: var(--color-bg-card);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--shadow-xl);
  border: 1px solid var(--color-border);
}
.modal-header {
  padding: 12px 16px;
  color: #fff;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--gradient-header);
  border-bottom: none;
}
.close-btn {
  background: none;
  border: none;
  color: #fff;
  font-size: 24px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  transition: background 0.2s;
}
.close-btn:hover {
  background: var(--color-bg-hover);
}
.modal-body {
  height: 55vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-primary);
}

/* 音频模式样式 */
.video-modal.audio-mode {
  background: radial-gradient(circle at top, #1f2933 0%, #000 55%, #111827 100%);
}
.audio-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.audio-visualizer {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  width: 100%;
  max-width: 1200px;
  height: 100%;
}
.audio-main-content {
  display: flex;
  align-items: stretch;
  gap: 40px;
  width: 100%;
  height: calc(100% - 80px);
  flex: 1;
}
.audio-left-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  flex-shrink: 0;
}
.audio-cover-wrapper {
  width: 180px;
  height: 180px;
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 10px 25px rgba(0,0,0,0.5);
  flex-shrink: 0;
}
.audio-cover {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.audio-bars {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 4px;
  width: 100%;
  max-width: 280px;
  height: 80px;
}
.audio-bars .bar {
  width: 5px;
  border-radius: 999px;
  background: linear-gradient(180deg, #f97316, #ef4444);
  opacity: 0.75;
  transition: height 0.1s ease-out;
  min-height: 10%;
}
.audio-bars .bar:nth-child(odd) {
  background: linear-gradient(180deg, #60a5fa, #3b82f6);
}
.audio-right-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
}
.lyrics-panel {
  flex: 1;
  width: 100%;
  height: 100%;
  min-height: 340px;
  display: flex;
  flex-direction: column;
}
.audio-visualizer .audio-element {
  width: 100%;
  max-width: 800px;
  margin-top: auto;
}

@keyframes equalizer {
  0%, 100% { height: 10%; }
  25% { height: 70%; }
  50% { height: 30%; }
  75% { height: 90%; }
}

/* 图集查看器样式 (Gallery Viewer) */
.gallery-viewer-overlay {
  background: transparent;
}

.gallery-modal {
  width: 70%;
  height: 65vh;
  max-width: 900px;
  background: var(--color-bg-card);
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  box-shadow: var(--shadow-xl);
  overflow: hidden;
  position: relative;
  border: 1px solid var(--color-border);
}

.gallery-header {
  padding: 15px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--gradient-header);
  border-bottom: none;
  z-index: 10;
}

.gallery-title-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.gallery-badge {
  background: var(--color-primary);
  color: #fff;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}

.gallery-main-title {
  color: #fff;
  font-size: 16px;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 600px;
}

.gallery-controls {
  display: flex;
  align-items: center;
  gap: 20px;
}

.gallery-counter {
  color: rgba(255, 255, 255, 0.8);
  font-family: inherit;
  font-size: 14px;
}

.gallery-body {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  background: var(--color-bg-primary);
}

.gallery-content-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.gallery-item-container {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.gallery-media {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  box-shadow: 0 0 20px rgba(0,0,0,0.4);
}

.gallery-image {
  cursor: zoom-in;
}

.gallery-video {
  background: #000;
}

.gallery-nav-btn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  color: var(--color-text-primary);
  width: 50px;
  height: 50px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  z-index: 5;
  box-shadow: var(--shadow-md);
}

.gallery-nav-btn:hover {
  background: var(--color-bg-hover);
  transform: translateY(-50%) scale(1.1);
}

.gallery-nav-btn.prev { left: 20px; }
.gallery-nav-btn.next { right: 20px; }




.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

/* 空状态样式 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  background: linear-gradient(135deg, #fafbfc 0%, #f0f2f5 100%);
  border-radius: 16px;
  border: 1px dashed #e0e0e0;
  margin: 20px 0;
}

.empty-icon {
  width: 120px;
  height: 120px;
  margin-bottom: 24px;
  animation: float 3s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
  margin: 0 0 8px 0;
}

.empty-desc {
  font-size: 14px;
  color: #888;
  margin: 0 0 20px 0;
}

@keyframes fadeIn {
    from {
        opacity: 0;
    }
    to {
        opacity: 1;
    }
}

/* 密码模态框样式 */
.password-modal {
    width: 90%;
    max-width: 400px;
    background: #fff;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.password-modal .modal-header {
    background: #f8f9fa;
    color: #333;
    border-bottom: 1px solid #eee;
}

.password-modal-body {
    padding: 24px;
}

.password-hint {
    margin-bottom: 16px;
    color: #666;
    font-size: 14px;
}

.password-input {
    width: 100%;
    padding: 10px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 14px;
    outline: none;
    transition: border-color 0.2s;
}

.password-input:focus {
    border-color: var(--color-primary);
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

[data-theme="dark"] .tip-input {
    background: var(--color-bg-secondary);
    border-color: var(--color-border);
    color: var(--color-text-primary);
}

[data-theme="dark"] .tip-input:focus {
    border-color: var(--color-primary);
}

.error-msg {
    color: #ff4d4f;
    font-size: 12px;
    margin-top: 6px;
}

.modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    margin-top: 24px;
}


/* 确认弹窗内容样式 */
:deep(.confirm-content) {
    font-size: 14px;
    color: #333;
}
:deep(.scope-list) {
    margin-bottom: 20px;
    background: #f8f9fa;
    padding: 12px;
    border-radius: 6px;
    border: 1px solid #eee;
}
:deep(.scope-item) {
    margin-bottom: 4px;
    padding-left: 8px;
    border-left: 3px solid var(--color-primary);
}
:deep(.warning-box) {
    background: #fffbe6;
    border: 1px solid #ffe58f;
    padding: 12px;
    border-radius: 6px;
}
:deep(.warning-title) {
    font-weight: 600;
    color: #fa8c16;
    margin-bottom: 8px;
}
:deep(.warning-box ul) {
    margin: 0;
    padding-left: 20px;
    color: #8c8c8c;
}

[data-theme="dark"] :deep(.confirm-content) {
    color: var(--color-text-secondary);
}

[data-theme="dark"] :deep(.confirm-content p) {
    color: var(--color-text-primary);
}

[data-theme="dark"] :deep(.scope-list) {
    background: rgba(30, 41, 59, 0.75);
    border-color: rgba(148, 163, 184, 0.28);
}

[data-theme="dark"] :deep(.scope-item) {
    color: var(--color-text-secondary);
    border-left-color: rgba(251, 146, 60, 0.85);
}

[data-theme="dark"] :deep(.warning-box) {
    background: rgba(120, 53, 15, 0.22);
    border-color: rgba(251, 191, 36, 0.45);
}

[data-theme="dark"] :deep(.warning-title) {
    color: #fbbf24;
}

[data-theme="dark"] :deep(.warning-box ul) {
    color: rgba(226, 232, 240, 0.82);
}

/* Teleport 到 body 的确认框需要全局选择器，scoped + :deep 在此处命中不稳定 */
:global(.download-confirm-modal .modal-body) {
    color: var(--color-text-secondary);
}

:global(.download-confirm-modal .confirm-content) {
    font-size: 14px;
    color: #333;
}

:global(.download-confirm-modal .confirm-content p) {
    margin: 0;
}

:global(.download-confirm-modal .scope-list) {
    margin-bottom: 20px;
    background: #f8f9fa;
    padding: 12px;
    border-radius: 6px;
    border: 1px solid #eee;
}

:global(.download-confirm-modal .scope-item) {
    margin-bottom: 4px;
    padding-left: 8px;
    border-left: 3px solid var(--color-primary);
}

:global(.download-confirm-modal .warning-box) {
    background: #fffbe6;
    border: 1px solid #ffe58f;
    padding: 12px;
    border-radius: 6px;
}

:global(.download-confirm-modal .warning-title) {
    font-weight: 600;
    color: #fa8c16;
    margin-bottom: 8px;
}

:global(.download-confirm-modal .warning-box ul) {
    margin: 0;
    padding-left: 20px;
    color: #8c8c8c;
}

:global([data-theme="dark"] .download-confirm-modal .modal-body) {
    color: var(--color-text-secondary);
}

:global([data-theme="dark"] .download-confirm-modal .confirm-content) {
    color: var(--color-text-secondary);
}

:global([data-theme="dark"] .download-confirm-modal .confirm-content p) {
    color: var(--color-text-primary);
}

:global([data-theme="dark"] .download-confirm-modal .scope-list) {
    background: rgba(30, 41, 59, 0.75);
    border-color: rgba(148, 163, 184, 0.28);
}

:global([data-theme="dark"] .download-confirm-modal .scope-item) {
    color: var(--color-text-secondary);
    border-left-color: rgba(251, 146, 60, 0.85);
}

:global([data-theme="dark"] .download-confirm-modal .warning-box) {
    background: rgba(120, 53, 15, 0.22);
    border-color: rgba(251, 191, 36, 0.45);
}

:global([data-theme="dark"] .download-confirm-modal .warning-title) {
    color: #fbbf24;
}

:global([data-theme="dark"] .download-confirm-modal .warning-box ul) {
    color: rgba(226, 232, 240, 0.82);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .downloads-page {
    padding-bottom: 20px;
  }
  
  /* 顶部工具栏适配 */
  .page-toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  
  .toolbar-left {
    overflow-x: auto;
    padding-bottom: 4px;
    margin: 0 -4px; /* 些许负边距以优化边缘显示 */
    padding: 0 4px;
    /* 隐藏滚动条但保留功能 */
    scrollbar-width: none; 
    -ms-overflow-style: none;
  }
  .toolbar-left::-webkit-scrollbar {
    display: none;
  }
  
  .filter-tabs {
    width: max-content;
    padding: 4px;
  }
  
  .filter-tab {
    padding: 6px 12px;
    font-size: 13px;
    white-space: nowrap;
  }
  
  /* 移动端清空按钮样式 */
  .filter-tab-clear-mobile {
    display: flex !important;
    align-items: center;
    gap: 4px;
    background: linear-gradient(135deg, #d32f2f 0%, #f44336 100%) !important;
    color: #ffffff !important;
    border: none !important;
    margin-left: 4px;
    font-size: 12px;
    padding: 6px 10px !important;
    white-space: nowrap;
    max-width: 120px;
  }
  
  .filter-tab-clear-mobile .icon {
    color: #ffffff !important;
    flex-shrink: 0;
  }
  
  .filter-tab-clear-mobile:active {
    transform: scale(0.98);
    background: linear-gradient(135deg, #c62828 0%, #e53935 100%) !important;
  }
  
  /* 隐藏桌面端清空按钮 */
  .btn-clear-action-desktop {
    display: none !important;
  }
  
  .toolbar-right {
    display: none; /* 移动端隐藏工具栏右侧的搜索框 */
  }
  
  /* 移动端订阅系统任务容器适配 */
  .batch-tasks-container {
    margin-left: 8px;
    padding-left: 8px;
    border-left: 1px solid var(--color-border);
  }
  
  [data-theme="dark"] .batch-tasks-container {
    border-left-color: rgba(255, 255, 255, 0.08);
  }
  
  .btn-batch-tasks {
    padding: 6px 12px;
    font-size: 13px;
    height: 36px;
  }
  
  .btn-batch-tasks .btn-text {
    display: inline; /* 移动端也显示文字 */
  }
  
  /* 移动端搜索框样式 */
  .search-box-mobile {
    display: flex !important;
  }

  /* 高级筛选栏适配 */
  .advanced-filters {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 8px;
    align-items: stretch;
    padding: 12px;
    margin: 0 -4px; /* 与页面边距对齐 */
  }
  
  /* 移动端第一行：搜索、博主、平台在同一行，宽度平分 */
  .search-box-mobile,
  .author-select-container,
  .form-select {
    width: 100% !important;
    min-width: 0 !important;
    height: 40px;
    margin: 0;
  }
  
  /* 其他元素占满整行 */
  .checkbox-group,
  .action-buttons-group {
    grid-column: 1 / -1;
  }
  
  /* 复选框组移动端优化 */
  .checkbox-group {
    width: 100%;
    gap: 8px;
    padding: 8px 0;
    border-top: 1px solid #f0f0f0;
    border-bottom: 1px solid #f0f0f0;
    margin: 4px 0;
    display: flex;
    align-items: center;
    flex-wrap: nowrap;
  }
  
  .filter-checkbox {
    width: auto !important;
    margin: 0 !important;
    padding: 10px 0;
    height: auto;
    font-size: 14px;
    flex: 1;
    min-width: 0;
    justify-content: center;
  }
  
  .filter-checkbox input[type="checkbox"] {
    width: 18px;
    height: 18px;
    margin-right: 6px;
    flex-shrink: 0;
  }
  
  /* 移动端清空按钮在复选框组中 */
  .btn-clear-in-checkbox {
    display: flex !important;
    align-items: center;
    gap: 4px;
    background: linear-gradient(135deg, #d32f2f 0%, #f44336 100%) !important;
    color: #ffffff !important;
    border: none !important;
    font-size: 12px;
    padding: 6px 10px !important;
    white-space: nowrap;
    flex-shrink: 0;
    margin: 0 !important;
    height: auto !important;
    border-radius: 6px;
  }
  
  .btn-clear-in-checkbox:active {
    transform: scale(0.98);
    background: linear-gradient(135deg, #c62828 0%, #e53935 100%) !important;
  }
  
  /* 移动端隐藏顶部工具栏的清空按钮 */
  .filter-tabs .filter-tab-clear-mobile {
    display: none !important;
  }

  /* 操作按钮组移动端优化 */
  .action-buttons-group {
    width: 100%;
    flex-direction: column;
    gap: 10px;
    margin-top: 4px;
  }
  
  /* 移动端内联分页 - 紧凑单行布局 */
  .inline-pagination {
    width: 100%;
    flex-wrap: nowrap;
    justify-content: flex-start;
    gap: 6px;
    overflow-x: auto;
  }
  
  /* 移动端隐藏页码按钮，节省空间 */
  .inline-pagination .page-numbers {
    display: none;
  }
  
  /* 移动端页码信息样式 - 限制宽度 */
  .inline-pagination .page-info {
    flex-shrink: 1;
    margin: 0;
    font-size: 12px;
    color: #666;
    white-space: nowrap;
    min-width: 0;
    max-width: 90px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  /* 移动端下拉框紧凑样式 */
  .inline-pagination .page-select {
    flex-shrink: 0;
    width: 70px;
    margin: 0;
    height: 28px;
    font-size: 12px;
    padding: 0 6px;
    padding-right: 20px;
  }
  
  /* 移动端分页按钮紧凑样式 */
  .inline-pagination .page-btn {
    flex-shrink: 0;
    min-width: 24px;
    height: 28px;
    padding: 0 6px;
  }
  
  .action-buttons-group .btn {
    width: 100% !important;
    margin: 0 !important;
    justify-content: center;
    height: 44px; /* 增大点击区域 */
    font-size: 14px;
    font-weight: 500;
    border-radius: 8px;
  }
  
  .btn-filter-action {
    order: 2; /* 清除筛选按钮放在下面 */
    background: #fff;
    border: 1.5px solid var(--color-error);
    color: var(--color-error);
  }
  
  .btn-filter-action:active {
    background: #fff5f5;
  }
  
  .btn-clear-action {
    order: 1; /* 清空按钮放在上面，更突出 */
    background: linear-gradient(135deg, #d32f2f 0%, #f44336 100%);
    color: #ffffff !important; /* 确保文字为白色 */
    border: none;
    box-shadow: 0 2px 8px rgba(211, 47, 47, 0.4);
  }
  
  .btn-clear-action .icon {
    color: #ffffff !important; /* 确保图标为白色 */
  }
  
  .btn-clear-action:hover:not(:disabled) {
    background: linear-gradient(135deg, #c62828 0%, #e53935 100%);
    color: #ffffff !important;
    box-shadow: 0 3px 12px rgba(211, 47, 47, 0.5);
  }
  
  .btn-clear-action:active {
    transform: scale(0.98);
    background: linear-gradient(135deg, #b71c1c 0%, #d32f2f 100%);
    box-shadow: 0 1px 4px rgba(211, 47, 47, 0.3);
  }
  
  .action-buttons-group .btn .icon {
    margin-right: 6px;
  }
  
  /* 移动端遮罩层 */
  .author-dropdown-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    z-index: 999;
    animation: fade-in 0.2s ease-out;
  }

  /* 筛选下拉框适配 */
  .author-dropdown {
      position: fixed;
      top: auto;
      bottom: 0;
      left: 0;
      right: 0;
      max-height: 60vh;
      border-radius: 12px 12px 0 0;
      z-index: 1000;
      box-shadow: 0 -4px 16px rgba(0,0,0,0.15);
      border: none;
      animation: slide-up 0.3s ease-out;
  }
  
  @keyframes slide-up {
      from { transform: translateY(100%); }
      to { transform: translateY(0); }
  }

  /* 任务列表适配 */
  .task-list {
    gap: 8px;
  }
  
  .task-card {
    flex-direction: row;
    gap: 10px;
    padding: 10px;
    margin: 0 -4px; /* 与页面边距对齐 */
    align-items: flex-start;
  }
  
  .task-thumbnail {
    width: 100px;
    height: 56px;
    min-width: 100px;
    flex-shrink: 0;
    border-radius: 6px;
    aspect-ratio: 16/9;
  }
  
  .task-thumbnail .play-overlay {
    opacity: 0.6;
  }
  
  .task-thumbnail:active .play-overlay {
    opacity: 1;
  }
  
  .thumbnail-placeholder {
    font-size: 16px;
  }
  
  .task-content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  
  .task-header {
    flex-wrap: nowrap;
    gap: 6px;
    align-items: center;
    margin-bottom: 2px;
  }
  
  .task-title-row {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  
  .task-title {
    font-size: 13px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.3;
    flex: 0 1 auto;
    min-width: 0;
    margin: 0;
  }
  
  .platform-badge {
    font-size: 9px;
    padding: 2px 5px;
    flex-shrink: 0;
  }

  .status-badge-container {
    margin-left: 0;
    width: auto;
    justify-content: flex-end;
    flex-wrap: nowrap;
    gap: 4px;
    margin-top: 0;
    flex-shrink: 0;
  }
  
  .type-badge {
    font-size: 9px;
    padding: 1px 4px;
  }
  
  .status-text {
    font-size: 11px;
    white-space: nowrap;
  }
  
  .task-meta-row {
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 6px;
    font-size: 11px;
    background: transparent;
    padding: 0;
    border-radius: 0;
  }
  
  .task-meta-row > div {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  
  .author-info {
    min-width: 0;
    flex: 1;
    max-width: 150px;
  }
  
  .author-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .task-progress {
    margin-top: 6px;
  }
  
  .progress-text {
    font-size: 10px;
    margin-top: 3px;
  }
  
  .error-message {
    font-size: 11px;
    padding: 6px;
    background: #fff5f5;
    border-radius: 4px;
    margin-top: 6px;
  }
  
  .task-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
  }
  
  .task-actions .btn {
    flex: 0 1 auto; /* 取消强制平分空间，按需分配 */
    min-width: 60px;
    justify-content: center;
    padding: 6px 12px;
    height: 32px;
    font-size: 11px;
    white-space: nowrap;
  }
  
  /* 加载状态样式 */
  .btn-loading {
    position: relative;
    pointer-events: none;
    opacity: 0.7;
  }
  
  .btn-loading::before {
    content: '';
    position: absolute;
    left: 8px;
    top: 50%;
    transform: translateY(-50%);
    width: 12px;
    height: 12px;
    border: 2px solid currentColor;
    border-right-color: transparent;
    border-radius: 50%;
    animation: btn-spin 0.6s linear infinite;
  }
  
  @keyframes btn-spin {
    to {
      transform: translateY(-50%) rotate(360deg);
    }
  }
  
  .btn-loading:disabled {
    cursor: not-allowed;
  }

  

  /* 调整弹窗在移动端的显示 */
  .video-modal, .gallery-modal {
    width: 100vw !important;
    height: 100vh !important;
    max-width: 100vw !important;
    max-height: 100vh !important;
    border-radius: 0 !important;
    display: flex;
    flex-direction: column;
    background: #000 !important;
    position: fixed;
    inset: 0;
    z-index: 9999 !important; /* 最高层级 */
  }
  
  .video-modal .modal-header, .gallery-header {
      background: linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.4) 100%) !important;
      backdrop-filter: blur(10px);
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      z-index: 10000 !important;
      border: none !important;
      padding: 15px 16px !important;
      color: #fff !important;
      display: flex !important;
      justify-content: space-between !important;
      align-items: center !important;
      height: 60px !important; /* 固定高度确保不被挤压 */
  }
  
  /* 强制截断标题 */
  .gallery-title-info, .task-title-row {
      flex: 1 !important;
      min-width: 0 !important;
      padding-right: 10px !important;
  }

  .gallery-main-title, .video-modal h3 {
      font-size: 15px !important;
      white-space: nowrap !important;
      overflow: hidden !important;
      text-overflow: ellipsis !important;
      width: 100% !important;
  }

  .gallery-controls, .modal-header .close-container {
      display: flex !important;
      align-items: center !important;
      gap: 12px !important;
      flex-shrink: 0 !important;
  }

  .close-btn {
      font-size: 32px !important; 
      color: #fff !important;
      background: rgba(255,255,255,0.2) !important;
      width: 44px !important; /* 进一步加大点击区域 */
      height: 44px !important;
      display: flex !important;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
      line-height: 1 !important;
      margin: 0 !important;
      padding: 0 !important;
  }
  
  .modal-body, .gallery-body {
    flex: 1;
    height: 100% !important;
    padding: 0 !important;
    background: #000 !important;
  }
  
  .modal-body video, .gallery-media {
      width: 100% !important;
      height: 100% !important;
      max-height: 100% !important;
      object-fit: contain !important;
      box-shadow: none !important;
  }

  /* 移动端图集导航按钮优化 */
  .gallery-nav-btn {
    width: 44px !important;
    height: 44px !important;
    background: rgba(0,0,0,0.3) !important;
    border-radius: 50%;
  }
  
  .gallery-nav-btn.prev { left: 10px !important; }
  .gallery-nav-btn.next { right: 10px !important; }

  /* 移动端音频播放器布局 */
  .audio-body {
    padding: 60px 20px 20px !important; /* 避开悬浮头部 */
    height: 100%;
    justify-content: flex-start !important;
  }

  /* 移动端图集 BGM 样式优化 */
  .gallery-bgm-player {
    bottom: 80px !important;
    right: 15px !important;
    padding: 8px !important;
    border-radius: 50% !important;
    width: 36px !important;
    height: 36px !important;
    justify-content: center !important;
    background: rgba(0,0,0,0.5) !important;
    border-color: rgba(255,255,255,0.2) !important;
    color: #fff !important;
  }

  .bgm-label {
    display: none !important; /* 隐藏文字，只留图标 */
  }

  .music-icon {
    margin: 0 !important;
  }

  .audio-main-content {
    flex-direction: column;
    gap: 20px;
    align-items: center;
    height: auto;
  }

  .audio-left-section {
    width: 100%;
    align-items: center;
  }

  .audio-cover-wrapper {
    width: 140px;
    height: 140px;
  }

  .audio-bars {
    max-width: 100%;
    height: 60px;
  }

  .audio-right-section {
    width: 100%;
    height: 250px;
  }

  .lyrics-panel {
    height: 100%;
  }

  .audio-visualizer .audio-element {
    margin-top: 15px;
  }
  
  .password-modal {
    width: 90%;
    margin: 0 auto;
    max-width: 100%;
  }
  
  .password-modal-body {
    padding: 20px 16px;
  }
  
  .password-input {
    font-size: 16px; /* 防止iOS自动缩放 */
  }
  
  .modal-actions {
    flex-direction: column;
    gap: 10px;
  }
  
  .modal-actions .btn {
    width: 100%;
    height: 44px;
  }

  /* 确认弹窗适配 */
  :deep(.confirm-content) {
    font-size: 13px;
  }
  
  :deep(.scope-list) {
    padding: 10px;
  }
  
  :deep(.scope-item) {
    font-size: 12px;
    margin-bottom: 6px;
  }
  
  :deep(.warning-box) {
    padding: 10px;
    font-size: 12px;
  }

  /* 分页适配 */
  .footer-pagination {
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 10px;
    padding: 16px 10px;
    margin: 0 -4px; /* 与页面边距对齐 */
  }
  
  .page-numbers {
      display: none; 
  }

  .page-info {
      width: 100%;
      text-align: center;
      order: -1;
      font-size: 12px;
      color: var(--color-text-secondary);
      background: var(--color-bg-primary);
      padding: 8px;
      border-radius: 4px;
      margin: 0;
      border: 1px solid var(--color-border);
  }
  
  /* 移动端页码选择下拉框 */
  .page-select {
      width: 100%;
      margin-top: 8px;
      margin-left: 0;
      height: 40px;
      font-size: 14px;
  }
  
  .page-btn {
      flex: 1;
      height: 44px; /* 更大的点击区域 */
      background: #fff;
      border: 1px solid #ddd;
      justify-content: center;
      min-width: 60px;
  }
  .page-btn .icon {
      width: 20px;
      height: 20px;
  }
  
  /* 空状态适配 */
  .empty-state {
    padding: 40px 16px;
    margin: 16px -4px;
    background: #fff;
    border-radius: 12px;
  }
  
  [data-theme="dark"] .empty-state {
    background: #1e1e1e !important;
    border: 1px solid rgba(255, 255, 255, 0.08);
  }
  
  .empty-icon {
    width: 100px;
    height: 100px;
    margin-bottom: 20px;
  }
  
  .empty-title {
    font-size: 16px;
  }
  
  .empty-desc {
    font-size: 13px;
    padding: 0 10px;
  }
  
  .empty-state .btn {
    width: 100%;
    max-width: 200px;
    height: 44px;
  }
}

/* 超小屏幕进一步优化 */
@media (max-width: 480px) {
  .filter-tab {
    padding: 6px 10px;
    font-size: 12px;
  }
  
  .advanced-filters {
    padding: 10px;
    gap: 10px;
  }
  
  .author-select-container,
  .form-select {
    height: 42px;
    font-size: 14px;
  }
  
  .checkbox-group {
    gap: 8px;
    padding: 6px 0;
  }
  
  .filter-checkbox {
    font-size: 13px;
    padding: 8px 0;
  }
  
  .filter-checkbox input[type="checkbox"] {
    width: 16px;
    height: 16px;
  }
  
  .action-buttons-group {
    gap: 8px;
  }
  
  .action-buttons-group .btn {
    height: 42px;
    font-size: 13px;
  }
  
  /* 移动端清除筛选按钮在深色模式下不要显示为白色 */
  [data-theme="dark"] .btn-filter-action {
    background: #252525 !important;
    border-color: rgba(255, 255, 255, 0.1) !important;
    color: var(--color-text-secondary) !important;
  }
  
  .task-list {
    gap: 12px;
  }
  
  .task-card {
    padding: 0;
    gap: 0;
    flex-direction: row !important;
    min-height: 120px !important; /* 使用最小高度，不再强行限死 */
    height: auto !important; 
    background: var(--color-bg-card);
    border: 1.5px solid rgba(0, 0, 0, 0.12) !important;
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 8px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08) !important;
    display: flex !important;
  }
  
  [data-theme="dark"] .task-card {
    background: #1e1e1e !important;
    border-color: rgba(255, 255, 255, 0.08) !important;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4) !important;
  }
  
  .task-thumbnail {
    width: 64px !important;
    min-width: 64px !important;
    height: auto !important;
    align-self: stretch; /* 填充整个左侧高度 */
    border-radius: 0 !important;
    flex-shrink: 0;
    background: var(--color-bg-tertiary);
  }
  
  .task-badges {
    padding: 0 !important;
    background: transparent !important;
    gap: 4px !important;
    border-bottom: none !important;
    overflow-x: visible;
    white-space: normal;
    margin-top: 4px;
  }

  .task-content {
    padding: 10px !important;
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  
  .task-title {
    font-size: 14px !important;
    line-height: 1.4;
    white-space: nowrap;
    margin-bottom: 2px !important;
    color: var(--color-text-primary) !important;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
  }
  
  .badge {
    font-size: 10px !important;
    padding: 2px 6px !important;
  }
  
  .task-actions {
    gap: 6px;
    margin-top: auto !important; /* 核心：始终保持在底部 */
    padding-top: 8px;
    flex-wrap: wrap; /* 移动端允许换行，防止按钮太多挤爆 */
  }
  
  .task-actions .btn {
    font-size: 11px !important;
    height: 32px !important;
    padding: 0 12px !important;
    flex: 0 1 auto !important; /* 强制不拉伸 */
    min-width: 50px !important;
  }

  .error-inline-tip {
    height: 32px !important;   /* 移动端高度对齐按钮 (32px) */
    margin-left: 0 !important;
    margin-right: 0 !important;
  }

  .task-meta-inline {
    margin-left: 0; /* 移动端靠左对齐或按序排列 */
    margin-top: 4px;
    width: 100%;
  }

  .task-meta-inline span {
    font-size: 11px !important;
    color: #999;
  }
}
</style>
