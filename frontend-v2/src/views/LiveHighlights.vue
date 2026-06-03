<template>
  <div class="live-highlights-page">
    <div v-if="!licenseValid" class="license-alert">
      <div class="license-icon">🔒</div>
      <h2>{{ checkingLicense ? '正在验证...' : '永久高级版专属' }}</h2>
      <p v-if="!checkingLicense">
        {{
          hasGeneralLicense
            ? '高光切片当前为永久高级版专属测试能力，你的授权已生效，但当前套餐暂不包含该功能'
            : '高光切片当前为永久高级版专属测试能力，采用“规则初筛 + AI语义增强”完成分析'
        }}
      </p>

      <div class="license-features" v-if="!checkingLicense">
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>弹幕热度/密度/关键词规则初筛 + 规则预过滤加速</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>ASR语音转写识别主播说了什么</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>LLM双层增强：语义评分 + 标题/摘要/关键词/剧情生成</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>高光类型偏好：搞笑/高能/争议/教学/情感按选择优先排序</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>分析任务异步执行，进度实时可见，支持失败重试与状态恢复</span>
        </div>
        <div class="feature-item">
          <Icon name="check" :size="16" />
          <span>支持批量导出片段与分析结果，并保留 timeline、score、storyline、SRT 素材</span>
        </div>
      </div>

      <p v-else>正在连接服务器验证授权状态...</p>
      <div class="license-actions" v-if="!checkingLicense">
        <a href="https://c.fakamiao.top/shopDetail/6WNe26" target="_blank" class="btn btn-primary">{{ hasGeneralLicense ? '升级永久版' : '购买永久版' }}</a>
        <button @click="checkLicense(true)" class="btn btn-secondary">刷新状态</button>
      </div>
      <div class="license-actions" v-else>
        <span class="spinner" style="border-color: var(--color-primary); border-top-color: transparent;"></span>
      </div>
    </div>

    <div v-else class="page-content">
      <!-- 模式切换标签 -->
      <div v-if="(!selectedStreamerId && activeTab === 'ai') || (!manualStreamerId && activeTab === 'manual')" class="mode-tabs">
        <button class="mode-tab" :class="{ active: activeTab === 'ai' }" @click="activeTab = 'ai'">
          <Icon name="zap" :size="15" />
          <span>智能切片</span>
        </button>
        <button class="mode-tab" :class="{ active: activeTab === 'manual' }" @click="activeTab = 'manual'">
          <Icon name="edit" :size="15" />
          <span>手动切片</span>
        </button>
      </div>

      <!-- ============ AI 模式 ============ -->
      <div v-if="activeTab === 'ai' && !selectedStreamerId" class="selection-screen card">
        <div class="selection-header">
          <div class="header-left">
            <div class="brand-orb">
              <Icon name="zap" :size="26" />
            </div>
            <div>
              <div class="title-row">
                <h2>高光切片</h2>
                <span class="beta-badge">Beta 测试中</span>
              </div>
              <p class="desc">请选择一个博主，进入该博主有弹幕的录制记录列表</p>
            </div>
          </div>
          <div class="header-right">
            <div class="search-input-wrapper">
              <Icon name="search" :size="16" class="search-icon" />
              <input v-model="searchQuery" type="text" placeholder="搜索博主名称..." class="search-input" />
            </div>
          </div>
        </div>

<div class="platform-filters">
          <button class="filter-tag" :class="{ active: selectedPlatform === 'all' }" @click="selectedPlatform = 'all'">全部</button>
          <button class="filter-tag" :class="{ active: selectedPlatform === 'douyin' }" @click="selectedPlatform = 'douyin'">抖音</button>
          <button class="filter-tag" :class="{ active: selectedPlatform === 'bilibili' }" @click="selectedPlatform = 'bilibili'">B站</button>
          <button class="filter-tag" :class="{ active: selectedPlatform === 'douyu' }" @click="selectedPlatform = 'douyu'">斗鱼</button>
          <button class="filter-tag" :class="{ active: selectedPlatform === 'huya' }" @click="selectedPlatform = 'huya'">虎牙</button>
          <button class="filter-tag" :class="{ active: selectedPlatform === 'cc' }" @click="selectedPlatform = 'cc'">网易CC</button>
          <button class="filter-tag" :class="{ active: selectedPlatform === 'twitch' }" @click="selectedPlatform = 'twitch'">Twitch</button>
        </div>

        <SkeletonLoader 
          v-if="isLoadingStreamers"
          :loading="true"
          text="正在加载博主..."
          type="grid"
          :count="12"
          itemHeight="180px"
          itemMinWidth="160px"
          gap="24px"
        />

        <div v-else-if="filteredStreamers.length > 0" class="streamer-grid">
          <div v-for="s in filteredStreamers" :key="s.id" class="grid-card" @click="selectStreamer(s)">
            <div v-if="s.avatar_url" class="card-blur-bg" :style="{ backgroundImage: `url(${s.avatar_url})` }"></div>
            <div class="card-platform-tag" :class="platformTagClass(s.platform)">{{ platformTagText(s.platform) }}</div>
            <div class="card-record-badge">有弹幕 {{ s.record_count }}</div>
            <div class="card-avatar-wrapper">
              <img v-if="s.avatar_url" :src="s.avatar_url" class="card-avatar" referrerpolicy="no-referrer" />
              <div v-else class="card-avatar-placeholder">{{ (s.anchor_name || '播')[0] }}</div>
            </div>
            <div class="card-info">
              <div class="card-name">{{ s.anchor_name || '未知主播' }}</div>
              <div class="card-meta">最新录制：{{ formatTime(s.latest_start_time) }}</div>
            </div>
          </div>
        </div>
        <div v-else class="empty-state">
          <h3>{{ searchQuery ? '未搜索到相关博主' : '暂无可分析记录' }}</h3>
          <p>仅展示“抖音/B站/斗鱼/虎牙/Twitch/YouTube + 存在弹幕文件(.danmu.jsonl)”的录制记录。</p>
        </div>
      </div>

      <template v-if="activeTab === 'ai' && selectedStreamerId">
      <div class="content-grid workspace-grid">
        <!-- 移动端专属侧边栏抽屉背景遮罩 -->
        <div class="mobile-sidebar-backdrop" :class="{ active: showRecordsSidebarDrawer }" @click="showRecordsSidebarDrawer = false"></div>

        <div class="records-column" :class="{ 'drawer-open': showRecordsSidebarDrawer }">
          <!-- 紧凑切换标签 -->
          <div class="mode-tabs compact-mode-tabs">
            <button class="mode-tab" :class="{ active: activeTab === 'ai' }" @click="activeTab = 'ai'">
              <Icon name="zap" :size="14" />
              <span>智能切片</span>
            </button>
            <button class="mode-tab" :class="{ active: activeTab === 'manual' }" @click="activeTab = 'manual'">
              <Icon name="edit" :size="14" />
              <span>手动切片</span>
            </button>
          </div>

          <!-- 紧凑博主信息头部 -->
          <div class="page-header card compact-page-header">
            <button class="back-btn compact-back-btn" @click="goBackToStreamerList">
              <Icon name="chevron-left" :size="16" />
              <span class="back-btn-text">返回</span>
            </button>
            <div class="header-divider"></div>
            <div class="current-streamer">
              <img v-if="selectedStreamer?.avatar_url" :src="selectedStreamer.avatar_url" class="header-avatar compact-avatar" referrerpolicy="no-referrer" />
              <div v-else class="header-avatar-placeholder compact-avatar">{{ (selectedStreamer?.anchor_name || '播')[0] }}</div>
              <div class="streamer-info">
                <div class="header-name compact-name">
                  <span class="streamer-name-text">{{ selectedStreamer?.anchor_name || '未知主播' }}</span>
                  <span v-if="selectedStreamer?.platform" class="header-platform-tag" :class="platformTagClass(selectedStreamer.platform)">
                    {{ platformTagText(selectedStreamer.platform) }}
                  </span>
                </div>
                <div class="header-sub compact-sub">
                  有弹幕录制
                  <template v-if="recordDateFilterMode === 'all'">
                    {{ selectedStreamerRecords.length }} 条
                  </template>
                  <template v-else>
                    {{ selectedStreamerRecordsFiltered.length }}/{{ selectedStreamerRecords.length }}
                  </template>
                </div>
              </div>
            </div>
          </div>

          <!-- 录制列表面板 -->
          <div class="records-panel card mobile-records-panel flex-1">
          <div class="panel-title">录制记录</div>
          <div v-if="selectedStreamerRecords.length === 0" class="empty">该博主暂无可分析的弹幕录制记录</div>
          <template v-else>
            <div class="records-toolbar">
              <div class="records-filter">
                <select v-model="recordDateFilterMode" class="records-filter-select" @change="onRecordFilterModeUserChange">
                  <option value="all">全部日期</option>
                  <option value="today">今天</option>
                  <option value="last7">近7天</option>
                  <option value="last30">近30天</option>
                  <option value="day">指定日期</option>
                </select>
                <input
                  v-if="recordDateFilterMode === 'day'"
                  v-model="recordDateFilterDay"
                  type="date"
                  class="records-date-input"
                  @change="onRecordFilterDayUserChange"
                />
              </div>
              <div class="records-count">{{ selectedStreamerRecordsFiltered.length }} / {{ selectedStreamerRecords.length }}</div>
            </div>

            <SkeletonLoader 
              :loading="isLoadingRecords"
              text="读取记录..."
              type="list"
              :count="5"
              itemHeight="64px"
              gap="12px"
            />

            <template v-if="!isLoadingRecords">
              <div v-if="selectedStreamerRecordsFiltered.length === 0" class="empty">当前日期筛选下暂无可分析记录</div>
              <div v-else class="record-list">
              <button
                v-for="r in selectedStreamerRecordsFiltered"
                :key="r.id"
                class="record-item"
                :class="{ active: selectedRecordId === r.id }"
                @click="selectRecord(r)"
              >
                <div class="record-line1">
                  <span class="record-time">{{ formatTime(r.start_time) }}</span>
                  <span class="record-mid-tags">
                    <span v-if="recordFormatExt(r.file_path)" class="record-format-tag">{{ recordFormatExt(r.file_path) }}</span>
                    <span class="record-meta-info">
                      <span>{{ recordDurationText(r) }}</span>
                    </span>
                  </span>
                  <span class="record-right-tags">
                    <span
                      v-if="recordHighlightTagText(r)"
                      class="record-highlight-tag"
                      :class="recordHighlightTagClass(r)"
                    >
                      {{ recordHighlightTagText(r) }}
                    </span>
                    <span class="record-status" :class="recordStatusTagClass(r.status)">{{ recordStatusText(r.status) }}</span>
                  </span>
                </div>
              </button>
            </div>
          </template>
        </template>
      </div>
    </div> <!-- records-column ends here -->

        <div class="analysis-panel card mobile-analysis-panel">
          <!-- 移动端主界面头部：展示当前选中的主播与录制，并提供切换按钮 -->
          <div class="mobile-main-header" @click="showRecordsSidebarDrawer = true">
            <div class="header-left-info" v-if="selectedStreamer && selectedRecord">
              <img :src="selectedStreamer.avatar_url" class="active-avatar" referrerpolicy="no-referrer" />
              <div class="active-text">
                <div class="active-name">
                  {{ selectedStreamer.anchor_name }}
                  <span class="active-platform" :class="platformTagClass(selectedStreamer.platform)">
                    {{ platformTagText(selectedStreamer.platform) }}
                  </span>
                </div>
                <div class="active-record">{{ formatTime(selectedRecord.start_time) }}</div>
              </div>
            </div>
            <div class="header-left-info placeholder" v-else>
              <Icon name="zap" :size="16" />
              <span>请选择博主与录制记录</span>
            </div>
            <button class="btn-switch-record">
              <Icon name="refresh" :size="14" />
              <span>切换录制</span>
            </button>
          </div>

          <div class="controls">
            <div class="options-row pc-only">
              <div class="option-cell wide-cell">
                <label>高光类型</label>
                <select v-model="form.highlight_type">
                  <option value="high_energy">高能操作</option>
                  <option value="funny">搞笑整活</option>
                  <option value="controversy">争议对线</option>
                  <option value="teaching">教学讲解</option>
                  <option value="emotion">情绪高潮</option>
                </select>
              </div>

              <div class="option-cell small-cell">
                <label>最大候选</label>
                <input type="number" min="1" max="100" v-model.number="form.max_candidates" />
              </div>

              <div class="option-cell compact-cell seed-cell">
                <label title="-1 表示全随机（每次分析都不同），输入固定数值可精确复现结果。">随机种子</label>
                <div class="seed-input-group">
                  <input
                    v-model.number="form.seed"
                    type="number"
                    placeholder="-1"
                    class="input-seed"
                  />
                  <button class="btn-dice" title="随机生成种子" @click="randomizeSeed">
                    <!-- 手绘一个真正的 5 点骰子图标 -->
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2.5"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    >
                      <rect x="3" y="3" width="18" height="18" rx="3" ry="3"></rect>
                      <circle cx="8.5" cy="8.5" r="1.2" fill="currentColor" stroke="none"></circle>
                      <circle cx="15.5" cy="8.5" r="1.2" fill="currentColor" stroke="none"></circle>
                      <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"></circle>
                      <circle cx="8.5" cy="15.5" r="1.2" fill="currentColor" stroke="none"></circle>
                      <circle cx="15.5" cy="15.5" r="1.2" fill="currentColor" stroke="none"></circle>
                    </svg>
                  </button>
                </div>
              </div>

              <div class="option-cell compact-cell randomness-cell">
                <label title="决定基于种子产生变数的力度。0 为标准热度排序，100 为最大化随机探索。">随机强度 (%)</label>
                <input
                  v-model.number="form.randomness"
                  type="number"
                  min="0"
                  max="100"
                  placeholder="0-100"
                />
              </div>

              <div class="option-cell compact-cell delay-cell">
                <label title="弹幕天然会晚于画面，设置后会将弹幕时间整体前移用于高光定位。">弹幕延迟补偿(秒)</label>
                <input
                  v-model.number="form.danmu_delay_compensation_seconds"
                  type="number"
                  min="0"
                  max="30"
                  placeholder="0-30"
                />
              </div>
            </div>

            <!-- 移动端专属：简易常驻操作条 -->
            <div class="mobile-action-trigger-bar" v-if="selectedRecordId">
              <button
                class="btn btn-primary analyze-trigger-btn"
                :class="{ 'btn-danger': analyzing }"
                :disabled="terminatingAnalyze"
                @click="handleAnalyzeAction"
              >
                {{ analyzeActionText }}
              </button>
              <button class="btn btn-outline more-trigger-btn" @click="showActionsDrawer = true">
                <Icon name="settings" :size="16" />
                <span>设置</span>
              </button>
            </div>

            <!-- 移动端专属操作抽屉遮罩 -->
            <div class="mobile-actions-backdrop" :class="{ active: showActionsDrawer }" @click="showActionsDrawer = false"></div>

            <div class="mobile-action-dock" :class="{ 'drawer-active': showActionsDrawer }">
              <!-- 移动端抽屉控制头部 -->
              <div class="drawer-header-mobile">
                <div class="drawer-handle"></div>
                <div class="drawer-title-row">
                  <h3>切片设置</h3>
                  <button class="drawer-close-btn" @click="showActionsDrawer = false">✕</button>
                </div>
              </div>

              <!-- 移动端专属：参数设置区也在操作抽屉中展示 -->
              <div class="controls mobile-only-drawer">
                <div class="options-row">
                  <div class="option-cell wide-cell">
                    <label>高光类型</label>
                    <select v-model="form.highlight_type">
                      <option value="high_energy">高能操作</option>
                      <option value="funny">搞笑整活</option>
                      <option value="controversy">争议对线</option>
                      <option value="teaching">教学讲解</option>
                      <option value="emotion">情绪高潮</option>
                    </select>
                  </div>

                  <div class="option-cell small-cell">
                    <label>最大候选</label>
                    <input type="number" min="1" max="100" v-model.number="form.max_candidates" />
                  </div>

                  <div class="option-cell compact-cell seed-cell">
                    <label title="-1 表示全随机（每次分析都不同），输入固定数值可精确复现结果。">随机种子</label>
                    <div class="seed-input-group">
                      <input
                        v-model.number="form.seed"
                        type="number"
                        placeholder="-1"
                        class="input-seed"
                      />
                      <button class="btn-dice" title="随机生成种子" @click="randomizeSeed">
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2.5"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        >
                          <rect x="3" y="3" width="18" height="18" rx="3" ry="3"></rect>
                          <circle cx="8.5" cy="8.5" r="1.2" fill="currentColor" stroke="none"></circle>
                          <circle cx="15.5" cy="8.5" r="1.2" fill="currentColor" stroke="none"></circle>
                          <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"></circle>
                          <circle cx="8.5" cy="15.5" r="1.2" fill="currentColor" stroke="none"></circle>
                          <circle cx="15.5" cy="15.5" r="1.2" fill="currentColor" stroke="none"></circle>
                        </svg>
                      </button>
                    </div>
                  </div>

                  <div class="option-cell compact-cell randomness-cell">
                    <label title="决定基于种子产生变数的力度。0 为标准热度排序，100 为最大化随机探索。">随机强度 (%)</label>
                    <input
                      v-model.number="form.randomness"
                      type="number"
                      min="0"
                      max="100"
                      placeholder="0-100"
                    />
                  </div>

                  <div class="option-cell compact-cell delay-cell">
                    <label title="弹幕天然会晚于画面，设置后会将弹幕时间整体前移用于高光定位。">弹幕延迟补偿(秒)</label>
                    <input
                      v-model.number="form.danmu_delay_compensation_seconds"
                      type="number"
                      min="0"
                      max="30"
                      placeholder="0-30"
                    />
                  </div>
                </div>
              </div>

              <!-- 按钮区移动端改造成独立的包裹器 -->
              <div class="actions">
                <button
                  class="btn btn-outline"
                  title="切片参数设置"
                  @click="showSettingsModal = true"
                >
                  <Icon name="settings" :size="16" />
                  <span>切片参数</span>
                </button>
                <button
                  class="btn analyze-action-btn"
                  :class="analyzing ? 'btn-danger' : 'btn-primary'"
                  :disabled="!selectedRecordId || terminatingAnalyze"
                  @mouseenter="analyzeButtonHover = true"
                  @mouseleave="analyzeButtonHover = false"
                  @focus="analyzeButtonHover = true"
                  @blur="analyzeButtonHover = false"
                  @click="handleAnalyzeAction"
                >
                  {{ analyzeActionText }}
                </button>
                <button class="btn btn-outline" :disabled="!selectedRecordId || loadingResult" @click="loadResult">
                  刷新结果
                </button>
                <button class="btn btn-danger" :disabled="!selectedRecordId || analyzing || cleaning || cleaningStreamer" @click="cleanupCurrentRecord">
                  {{ cleaning ? '清理中...' : '清理本场切片' }}
                </button>
                <button class="btn btn-danger" :disabled="!selectedStreamerId || analyzing || cleaning || cleaningStreamer" @click="cleanupCurrentStreamer">
                  {{ cleaningStreamer ? '清理中...' : '清理该博主全部切片' }}
                </button>
                <button class="btn btn-secondary" :disabled="selectedSegmentIds.length === 0 || exporting" @click="exportSelected">
                  {{ exporting ? '切片中...' : `批量切片（含剧情字幕）(${selectedSegmentIds.length})` }}
                </button>
                <button class="btn btn-outline" :disabled="selectedSegmentIds.length === 0 || bundling" @click="downloadBundle">
                  {{ bundling ? '打包中...' : `导出资源包（${selectedSegmentIds.length}）` }}
                </button>
              </div>
            </div>
            <div v-if="analyzing" class="analyze-progress-row">
              <div class="analyze-progress-head">
                <span>任务状态：{{ analyzeStatusText }}</span>
                <span>{{ analyzeProgress }}%</span>
              </div>
              <div class="analyze-progress-track">
                <div class="analyze-progress-fill" :style="{ width: `${analyzeProgress}%` }"></div>
              </div>
              <div class="analyze-progress-msg">{{ analyzeMessage || '后台分析中...' }}</div>
            </div>
          </div>

          <div class="result">
            <div class="result-head">
              <h3>候选高光片段</h3>
              <div class="result-head-right">
                <button
                  v-if="segments.length > 0"
                  class="btn btn-sm btn-outline select-all-btn"
                  @click="toggleSelectAll"
                >
                  {{ isAllSelected ? '取消全选' : '全选' }}
                  <span class="select-count" v-if="selectedSegmentIds.length > 0">({{ selectedSegmentIds.length }})</span>
                </button>
                <span class="meta" v-if="resultMeta">{{ resultMeta }}</span>
              </div>
            </div>
            <div v-if="segments.length === 0" class="empty">暂无候选片段，请先执行分析。</div>
            <div v-else class="segment-list">
              <label class="segment-item" v-for="s in segments" :key="s.id" :class="{ 'has-story': !!s.story_text, 'has-clip': !!s.clip_path }">
                <div class="seg-check">
                  <input type="checkbox" :value="s.id" v-model="selectedSegmentIds" />
                </div>
                <div class="segment-main">
                  <!-- 标题行 -->
                  <div class="seg-title-row">
                    <div class="seg-title">
                      <span class="seg-ai-dot" v-if="s.story_text" title="AI已增强"></span>
                      <strong>{{ s.title }}</strong>
                    </div>
                  </div>
                  <!-- 元信息行 -->
                  <div class="seg-meta-row">
                    <span class="seg-time">
                      <Icon name="film" :size="12" />
                      {{ secToClock(s.start_sec) }} — {{ secToClock(s.end_sec) }}
                    </span>
                    <div class="seg-stats">
                      <span class="seg-pill score-pill" data-tooltip="综合评分：规则热度与 AI 判定融合后的候选排序分（0-1）">
                        {{ formatScore(s.score, 3) }}
                      </span>
                      <span class="seg-pill" data-tooltip="热度指数：基于弹幕密度的综合能量得分">
                        <Icon name="flame" :size="12" class="icon-heat" />
                        {{ s.heat_score.toFixed(1) }}
                      </span>
                      <span class="seg-pill" data-tooltip="爆发率：弹幕突然增长的幅度">
                        <Icon name="activity" :size="12" class="icon-semantic" />
                        {{ s.semantic_score.toFixed(2) }}
                      </span>
                      <span class="seg-pill" data-tooltip="弹幕总数：该片段内的弹幕总量">
                        <Icon name="message-square" :size="12" />
                        {{ s.chat_count }}
                      </span>
                      <span class="seg-pill" data-tooltip="参与人数：该片段内发送弹幕的独立用户数">
                        <Icon name="users" :size="12" />
                        {{ s.unique_users }}
                      </span>
                      <span
                        v-if="hasAiDecision(s)"
                        class="seg-ai-pill"
                        :class="aiDecisionClass(s)"
                        :data-tooltip="aiDecisionTooltip(s)"
                      >
                        {{ aiDecisionText(s) }}
                      </span>
                    </div>
                  </div>
                  <!-- 摘要 -->
                  <div class="seg-summary">{{ s.summary }}</div>
                  <!-- AI 剧情文案 + 主播语音按钮 -->
                  <div class="seg-story" v-if="s.story_text || s.speech_text">
                    <div class="seg-story-top">
                      <span class="seg-story-badge" v-if="s.story_text">AI 剧情</span>
                      <button class="seg-speech-btn" v-if="s.speech_text" @click.stop.prevent="speechModalSegmentId = s.id">
                        <Icon name="music" :size="13" />
                        主播语音
                      </button>
                    </div>
                    <span class="seg-story-text" v-if="s.story_text">{{ s.story_text }}</span>
                  </div>
                  <!-- 关键词 -->
                  <div class="seg-keywords" v-if="s.keywords?.length">
                    <span class="seg-kw" v-for="kw in s.keywords" :key="kw">{{ kw }}</span>
                  </div>
                  <!-- 预览+切片操作 -->
                  <div class="show-on-hover-wrap">
                    <div class="seg-clip">
                      <button class="btn btn-outline btn-sm" @click.stop.prevent="openClipPreview(s)">
                        <Icon name="play" :size="14" />
                        <span>预览调整</span>
                      </button>
                      <button class="btn btn-outline btn-sm" @click.stop.prevent="downloadSegmentBundle(s)" :disabled="bundling" title="导出此片段资源包">
                        <Icon name="download" :size="14" />
                      </button>
                      <span v-if="s.clip_path" class="seg-badge">已切片</span>
                      <span v-else class="seg-tip-text">未切片，可预览后确认导出</span>
                    </div>
                  </div>
                </div>
              </label>
            </div>
          </div>
        </div>
      </div>

      <!-- 主播语音弹窗 -->
      <Modal :show="!!speechModalSegmentId" title="主播语音转写" width="560px" @close="speechModalSegmentId = null">
        <div class="speech-modal-body">
          {{ getSegmentSpeech(speechModalSegmentId) }}
        </div>
      </Modal>

      <!-- 切片参数设置弹窗 -->
      <Modal
        v-model:show="showSettingsModal"
        title="切片参数"
        width="760px"
        @close="showSettingsModal = false"
      >
        <div class="settings-modal-body">
          <!-- 第一行：直播类型（独占一行，输入框较长） -->
          <div class="settings-row full">
            <label class="settings-label">直播类型（可选）</label>
            <input class="settings-input" v-model="form.stream_type" type="text" list="stream-type-options" placeholder="例如：游戏 / 户外 / 钓鱼 / 唱歌 / 聊天" maxlength="32" />
            <datalist id="stream-type-options">
              <option v-for="item in streamTypePresets" :key="item" :value="item"></option>
            </datalist>
          </div>

          <!-- 第二行：两列 -->
          <div class="settings-row cols-2">
            <div class="settings-field">
              <label class="settings-label">分析策略</label>
              <select class="settings-select" v-model="form.analysis_strategy">
                <option value="rule_only">本地规则模式</option>
                <option value="llm_required">大模型分析模式（严格）</option>
              </select>
            </div>
            <div class="settings-field" v-if="form.analysis_strategy !== 'rule_only'">
              <label class="settings-label">主播语音识别</label>
              <label class="settings-check">
                <input v-model="form.asr_enabled" type="checkbox" />
                <span class="check-track"><span class="check-dot"></span></span>
                <span class="check-text">{{ form.asr_enabled ? '开启' : '关闭' }}</span>
              </label>
            </div>
          </div>

          <!-- 第三行：两列 -->
          <div class="settings-row cols-2">
            <div class="settings-field">
              <label class="settings-label">剧情文案增强</label>
              <label class="settings-check">
                <input v-model="form.story_enabled" type="checkbox" />
                <span class="check-track"><span class="check-dot"></span></span>
                <span class="check-text">{{ form.story_enabled ? '开启' : '关闭' }}</span>
              </label>
            </div>
            <div class="settings-field" v-if="form.analysis_strategy !== 'rule_only' && form.asr_enabled">
              <label class="settings-label">ASR 模型</label>
              <select class="settings-select" v-model="form.asr_model">
                <option v-for="item in asrModelOptions" :key="item.value" :value="item.value">{{ asrModelOptionLabel(item) }}</option>
              </select>
            </div>
          </div>

          <!-- L1/L2 模型信息行 -->
          <div class="settings-row cols-2" v-if="form.analysis_strategy !== 'rule_only'">
            <div class="settings-field">
              <label class="settings-label">L1 语义侦察兵 (初筛)</label>
              <div class="settings-value">{{ l1ModelText }}</div>
            </div>
            <div class="settings-field">
              <label class="settings-label">L2 内容剪辑师 (精修)</label>
              <div class="settings-value">{{ l2ModelText }}</div>
            </div>
          </div>

          <!-- 高级参数折叠 -->
          <div class="settings-row full" v-if="form.analysis_strategy !== 'rule_only'">
            <label class="settings-label">高级参数</label>
            <label class="settings-check">
              <input v-model="showAdvancedModelOptions" type="checkbox" />
              <span class="check-track"><span class="check-dot"></span></span>
              <span class="check-text">{{ showAdvancedModelOptions ? '隐藏并发设置' : '显示并发设置' }}</span>
            </label>
          </div>

          <template v-if="form.analysis_strategy !== 'rule_only' && showAdvancedModelOptions">
            <div class="settings-row cols-2">
              <div class="settings-field">
                <label class="settings-label" title="L1 阶段并发请求数，建议 1-4。过高可能触发限流。">L1 并发上限 (1-8)</label>
                <input class="settings-input" v-model.number="form.l1_scout_config.max_concurrency" type="number" min="1" max="8" />
              </div>
              <div class="settings-field">
                <label class="settings-label" title="L2 阶段并发请求数，建议 2-4。过高可能触发限流或超时。">L2 并发上限 (1-8)</label>
                <input class="settings-input" v-model.number="form.l2_editor_config.max_concurrency" type="number" min="1" max="8" />
              </div>
            </div>
          </template>

          <div class="settings-hint" v-if="form.analysis_strategy !== 'rule_only'">
            当前分析架构：{{ modelSourceText }}。
            <a href="/settings?tab=ai-model" class="link-btn" @click.prevent="$router.push({ path: '/settings', query: { tab: 'ai-model' } })">前往全局设置</a>
          </div>
        </div>
        <template #footer>
          <div class="settings-modal-footer">
            <button class="btn btn-outline" @click="resetAnalyzePreferenceToDefault">恢复默认参数</button>
            <button class="btn btn-primary" @click="showSettingsModal = false">完成</button>
          </div>
        </template>
      </Modal>
      </template>

      <!-- 剪辑编辑器（公共组件） -->
      <ClipEditor
        :show="previewVisible"
        :video-url="recordStreamUrl"
        :title="previewTitle"
        :initial-duration="originalDuration"
        :start-sec="editorStartSec"
        :end-sec="editorEndSec"
        :ts-mode="clipEditorTsMode"
        @seek="onClipEditorSeek"
        @close="closePreview"
        @export="handleClipEditorExport"
        @time-change="onClipEditorTimeChange"
      >
        <template #sidebar-extra v-if="previewSegment || manualDanmuRecordId">
          <div class="sidebar-card" v-if="previewSegment?.story_text">
            <div class="sidebar-card-head">
              <Icon name="zap" :size="14" />
              <span>AI 剧情</span>
            </div>
            <p class="sidebar-story">{{ previewSegment.story_text }}</p>
          </div>
          <div class="sidebar-card" v-if="previewSegment">
            <div class="sidebar-card-head">
              <span class="card-icon">#</span>
              <span>关键词</span>
            </div>
            <div class="sidebar-tags" v-if="previewSegment.keywords?.length">
              <span class="kw-tag" v-for="kw in previewSegment.keywords" :key="kw"># {{ kw }}</span>
            </div>
            <div v-else class="sidebar-empty">暂无关键词</div>
          </div>
          <div class="sidebar-card danmu-card">
            <div class="sidebar-card-head">
              <Icon name="message-square" :size="14" />
              <span>弹幕</span>
              <span v-if="previewDanmuMeta.total > 0" class="danmu-count">{{ previewDanmuMeta.included }} / {{ previewDanmuMeta.total }}</span>
            </div>
            <div class="sidebar-danmu-list">
              <div v-if="previewDanmuLoading" class="sidebar-empty">加载中...</div>
              <div v-else-if="previewDanmuItems.length === 0" class="sidebar-empty">暂无弹幕</div>
              <template v-else>
                <div class="danmu-item" v-for="(dm, idx) in previewDanmuItems" :key="`${dm.sec}-${idx}`">
                  <span class="danmu-time">{{ secToClock(dm.offset_sec || 0) }}</span>
                  <span class="danmu-text">{{ dm.text || `[${dm.event_type}]` }}</span>
                </div>
              </template>
            </div>
          </div>
        </template>
      </ClipEditor>
      <!-- ============ 手动切片模式 ============ -->
      <div v-if="activeTab === 'manual'" class="manual-slice-container">

        <!-- ===== 录制视频（两步流：博主选择 → 录制列表） ===== -->
        <template v-if="manualSourceType === 'live'">
          <!-- 第一步：博主选择 -->
          <template v-if="!manualStreamerId">
            <div class="selection-screen card">
              <div class="selection-header">
                <div class="header-left">
                  <div class="brand-orb">
                    <Icon name="edit" :size="26" />
                  </div>
                  <div>
                    <div class="title-row">
                      <h2>手动切片</h2>
                      <span class="beta-badge">Beta 测试中</span>
                    </div>
                    <p class="desc">选择博主查看其录制视频，拖拽时间轴手动切片</p>
                  </div>
                </div>
                <div class="header-right">
                  <div class="search-input-wrapper">
                    <Icon name="search" :size="16" class="search-icon" />
                    <input v-model="manualStreamerSearch" type="text" placeholder="搜索博主名称..." class="search-input" />
                  </div>
                </div>
              </div>
              <div class="platform-filters">
                <button class="filter-tag" :class="{ active: manualStreamerPlatform === 'all' }" @click="manualStreamerPlatform = 'all'">全部</button>
                <button class="filter-tag" :class="{ active: manualStreamerPlatform === 'douyin' }" @click="manualStreamerPlatform = 'douyin'">抖音</button>
                <button class="filter-tag" :class="{ active: manualStreamerPlatform === 'bilibili' }" @click="manualStreamerPlatform = 'bilibili'">B站</button>
                <button class="filter-tag" :class="{ active: manualStreamerPlatform === 'douyu' }" @click="manualStreamerPlatform = 'douyu'">斗鱼</button>
                <button class="filter-tag" :class="{ active: manualStreamerPlatform === 'huya' }" @click="manualStreamerPlatform = 'huya'">虎牙</button>
                <button class="filter-tag" :class="{ active: manualStreamerPlatform === 'cc' }" @click="manualStreamerPlatform = 'cc'">网易CC</button>
                <button class="filter-tag" :class="{ active: manualStreamerPlatform === 'twitch' }" @click="manualStreamerPlatform = 'twitch'">Twitch</button>
              </div>
              <SkeletonLoader 
                v-if="manualStreamersLoading"
                :loading="true"
                text="正在加载博主..."
                type="grid"
                :count="12"
                itemHeight="180px"
                itemMinWidth="160px"
                gap="24px"
              />
              <div v-else-if="filteredManualStreamers.length > 0" class="streamer-grid">
                <div v-for="s in filteredManualStreamers" :key="s.id" class="grid-card" @click="selectManualStreamer(s)">
                  <div v-if="s.avatar_url" class="card-blur-bg" :style="{ backgroundImage: `url(${s.avatar_url})` }"></div>
                  <div class="card-platform-tag" :class="platformTagClass(s.platform)">{{ platformTagText(s.platform) }}</div>
                  <div class="card-record-badge">可切片 {{ s.record_count }}</div>
                  <div class="card-avatar-wrapper">
                    <img v-if="s.avatar_url" :src="s.avatar_url" class="card-avatar" referrerpolicy="no-referrer" />
                    <div v-else class="card-avatar-placeholder">{{ (s.anchor_name || '播')[0] }}</div>
                  </div>
                  <div class="card-info">
                    <div class="card-name">{{ s.anchor_name || '未知主播' }}</div>
                    <div class="card-meta">最新录制：{{ formatTime(s.latest_start_time) }}</div>
                  </div>
                </div>
              </div>
              <div v-else class="empty-state">
                <h3>{{ manualStreamerSearch ? '未搜索到相关博主' : '暂无可切片录制' }}</h3>
                <p>选择博主查看其录制视频，拖拽时间轴手动切片</p>
              </div>
            </div>
          </template>

          <!-- 第二步：录制列表 -->
          <template v-else>
            <div class="content-grid workspace-grid">
              <!-- 移动端专属侧边栏抽屉背景遮罩 -->
              <div class="mobile-sidebar-backdrop" :class="{ active: showRecordsSidebarDrawer }" @click="showRecordsSidebarDrawer = false"></div>

              <div class="records-column" :class="{ 'drawer-open': showRecordsSidebarDrawer }">
                <!-- 紧凑切换标签 -->
                <div class="mode-tabs compact-mode-tabs">
                  <button class="mode-tab" :class="{ active: activeTab === 'ai' }" @click="activeTab = 'ai'">
                    <Icon name="zap" :size="14" />
                    <span>智能切片</span>
                  </button>
                  <button class="mode-tab" :class="{ active: activeTab === 'manual' }" @click="activeTab = 'manual'">
                    <Icon name="edit" :size="14" />
                    <span>手动切片</span>
                  </button>
                </div>

                <!-- 紧凑博主信息头部 -->
                <div class="page-header card compact-page-header">
                  <button class="back-btn compact-back-btn" @click="backManualStreamerList">
                    <Icon name="chevron-left" :size="16" />
                    <span class="back-btn-text">返回</span>
                  </button>
                  <div class="header-divider"></div>
                  <div class="current-streamer">
                    <img v-if="manualStreamerAvatar" :src="manualStreamerAvatar" class="header-avatar compact-avatar" referrerpolicy="no-referrer" />
                    <div v-else class="header-avatar-placeholder compact-avatar">{{ (manualStreamerName || '播')[0] }}</div>
                    <div class="streamer-info">
                      <div class="header-name compact-name">
                        <span class="streamer-name-text">{{ manualStreamerName }}</span>
                        <span v-if="selectedManualStreamer?.platform" class="header-platform-tag" :class="platformTagClass(selectedManualStreamer.platform)">
                          {{ platformTagText(selectedManualStreamer.platform) }}
                        </span>
                      </div>
                      <div class="header-sub compact-sub">{{ filteredManualStreamerRecords.length }}/{{ manualStreamerRecords.length }}条录制</div>
                    </div>
                  </div>
                </div>

                <!-- 录制列表面板 -->
                <div class="records-panel card mobile-records-panel flex-1">
                <div class="panel-title">录制记录</div>
                <div class="records-toolbar">
                  <div class="records-filter">
                    <select v-model="manualDateFilterMode" class="records-filter-select" @change="onManualDateFilterChange">
                      <option value="all">全部日期</option>
                      <option value="today">今天</option>
                      <option value="last7">近7天</option>
                      <option value="last30">近30天</option>
                      <option value="day">指定日期</option>
                    </select>
                    <input v-if="manualDateFilterMode === 'day'" v-model="manualDateFilterDay" type="date" class="records-date-input" @change="onManualDateFilterChange" />
                  </div>
                  <div class="records-count">{{ filteredManualStreamerRecords.length }} / {{ manualStreamerRecords.length }}</div>
                </div>

                <SkeletonLoader 
                  v-if="manualStreamerLoadingRecords"
                  :loading="true"
                  text="加载记录..."
                  type="list"
                  :count="5"
                  itemHeight="64px"
                  gap="12px"
                />

                <template v-else>
                  <div v-if="filteredManualStreamerRecords.length === 0" class="empty">当前筛选条件下暂无可切片记录</div>
                  <div v-else class="record-list">
                    <button
                      v-for="r in filteredManualStreamerRecords"
                      :key="r.id"
                      class="record-item"
                      :class="{ active: manualSelectedRecordId === r.id }"
                      @click="selectManualRecord(r)"
                    >
                      <div class="record-line1">
                        <span class="record-time">{{ formatTime(r.start_time) }}</span>
                        <span class="record-mid-tags">
                          <span v-if="recordFormatExt(r.file_path)" class="record-format-tag">{{ recordFormatExt(r.file_path) }}</span>
                          <span class="record-meta-info">
                            <span>{{ recordDurationText(r) }}</span>
                          </span>
                        </span>
                        <span class="record-right-tags">
                          <span
                            v-if="recordManualClipTagText(r)"
                            class="record-highlight-tag"
                            :class="recordManualClipTagClass(r)"
                          >
                            {{ recordManualClipTagText(r) }}
                          </span>
                           <span class="record-status" :class="recordStatusTagClass(r.status)">{{ recordStatusText(r.status) }}</span>
                        </span>
                      </div>
                    </button>
                  </div>
                </template>
              </div>
            </div> <!-- records-column ends here -->

              <!-- ===== 手动切片结果面板 ===== -->
              <div class="analysis-panel card mobile-analysis-panel">
                <!-- 移动端主界面头部（手动切片模式） -->
                <div class="mobile-main-header" @click="showRecordsSidebarDrawer = true">
                  <div class="header-left-info" v-if="manualStreamerName && manualSelectedVideo">
                    <img v-if="manualStreamerAvatar" :src="manualStreamerAvatar" class="active-avatar" referrerpolicy="no-referrer" />
                    <div class="active-text">
                      <div class="active-name">
                        {{ manualStreamerName }}
                        <span v-if="selectedManualStreamer?.platform" class="active-platform" :class="platformTagClass(selectedManualStreamer.platform)">
                          {{ platformTagText(selectedManualStreamer.platform) }}
                        </span>
                      </div>
                      <div class="active-record">{{ formatTime(manualSelectedVideo.start_time) }}</div>
                    </div>
                  </div>
                  <div class="header-left-info placeholder" v-else>
                    <Icon name="edit" :size="16" />
                    <span>请选择博主与录制记录</span>
                  </div>
                  <button class="btn-switch-record">
                    <Icon name="refresh" :size="14" />
                    <span>切换录制</span>
                  </button>
                </div>

                <div class="panel-title">
                  <span>手动切片结果</span>
                  <div class="panel-actions">
                    <button class="btn btn-outline btn-sm" @click="loadManualClips(manualSelectedRecordId)" :disabled="manualClipsLoading || !manualSelectedRecordId">
                      <Icon name="refresh" :size="12" />
                      <span>刷新</span>
                    </button>
                    <button class="btn btn-outline btn-sm" @click="downloadManualClipsBundle" :disabled="manualClips.length === 0 || !manualSelectedRecordId || manualBundling">
                      <Icon name="download" :size="12" />
                      <span>{{ manualBundling ? '打包中...' : `批量导出(${manualClips.length})` }}</span>
                    </button>
                    <button class="btn btn-outline btn-sm text-danger" @click="confirmCleanupManualRecord" :disabled="manualClips.length === 0 || !manualSelectedRecordId">清理本场</button>
                    <button class="btn btn-outline btn-sm text-danger" @click="confirmCleanupManualStreamer">清理该博主</button>
                  </div>
                </div>

                <div v-if="manualClipsLoading" class="panel-loading">加载中...</div>
                <div v-else-if="!manualSelectedRecordId" class="panel-empty">请从左侧选择录制视频查看切片结果</div>
                <div v-else-if="manualClips.length === 0" class="panel-empty">暂无手动切片结果</div>
                <div v-else class="manual-clips-list">
                  <div v-for="clip in manualClips" :key="clip.name" class="manual-clip-item">
                    <div class="mc-icon"><Icon name="film" :size="16" /></div>
                    <div class="mc-info">
                      <div class="mc-name">{{ clip.name }}</div>
                      <div class="mc-meta">
                        {{ secToClock(clip.start_sec) }} → {{ secToClock(clip.end_sec) }}
                        <span class="mc-sep">·</span>
                        {{ formatBytes(clip.size_bytes) }}
                        <span class="mc-sep">·</span>
                        {{ manualFormatDate(clip.created_at) }}
                      </div>
                    </div>
                    <div class="mc-actions">
                      <button class="btn btn-outline btn-sm" @click="playManualClip(clip)" title="播放">▶</button>
                      <button class="btn btn-outline btn-sm" @click="downloadManualClip(clip)" :disabled="manualBundling" title="下载">
                        <Icon name="download" :size="12" />
                      </button>
                      <button class="btn btn-outline btn-sm text-danger" @click="deleteManualClip(clip)" title="删除">✕</button>
                    </div>
                  </div>
                </div>

                <div class="panel-footer" v-if="manualSelectedRecordId">
                  <button class="btn btn-primary" @click="openManualPreview(manualSelectedVideo || { id: manualSelectedRecordId })">
                    <Icon name="plus" :size="16" />
                    <span>开始新切片</span>
                  </button>
                </div>
              </div>
            </div>
          </template>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, onActivated, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import Modal from '@/components/common/Modal.vue'
import TimelineRange from '@/components/business/TimelineRange.vue'
import ClipEditor from '@/components/business/ClipEditor.vue'
import liveApi from '@/api/live'
import liveHighlightsApi from '@/api/liveHighlights'
import SkeletonLoader from '@/components/common/SkeletonLoader.vue'
import { aiConfigApi } from '@/api/settings'
import { licenseApi } from '@/api/index'
import { tasksApi } from '@/api/tasks'
import { useDialog } from '@/composables/useDialog'
import { useToast } from '@/composables/useToast'
import { buildAuthedWsUrl } from '@/utils/wsAuth'

const { success, error } = useToast()
const dialog = useDialog()
const router = useRouter()
const cachedLicense = localStorage.getItem('license_status')
const cachedLifetime = localStorage.getItem('live_highlights_lifetime_ok')
const hadCachedLicenseOnBoot = cachedLicense !== null
const hasGeneralLicense = ref(cachedLicense === 'true')
const lifetimeEligible = ref(cachedLifetime === 'true')
const licenseValid = ref(hasGeneralLicense.value && lifetimeEligible.value)
const checkingLicense = ref(cachedLicense === null)

const showSettingsModal = ref(false)
const speechModalSegmentId = ref(null)
const streamerListRaw = ref([])
const isLoadingStreamers = ref(true)
const isLoadingRecords = ref(false)
const allRecords = ref([])
const selectedStreamerId = ref('')
const selectedRecordId = ref('')
const searchQuery = ref('')
const selectedPlatform = ref('all')
const recordDateFilterMode = ref('last7')
const recordDateFilterDay = ref('')
const settingsModelSource = ref('cloud')
const loadingResult = ref(false)
const analyzing = ref(false)
const analyzeButtonHover = ref(false)
const terminatingAnalyze = ref(false)
const exporting = ref(false)
const bundling = ref(false)
const cleaning = ref(false)
const cleaningStreamer = ref(false)
const segments = ref([])
const analyzedAt = ref('')
const selectedSegmentIds = ref([])
const previewVisible = ref(false)
const previewSegment = ref(null)
const previewVideoRef = ref(null)
const recordStreamUrl = ref('')
const originalDuration = ref(0)
const adjustedStartSec = ref(0)
const adjustedEndSec = ref(0)
const currentPreviewSec = ref(-1)
const exportingSingle = ref(false)
const previewDanmuLoading = ref(false)
const previewDanmuItems = ref([])
const previewDanmuMeta = ref({
  total: 0,
  included: 0,
  truncated: false
})
const analyzeTaskId = ref('')
const analyzeSocket = ref(null)
const analyzePingTimer = ref(null)
const analyzePollTimer = ref(null)
const recordStatusSocket = ref(null)
const recordStatusPingTimer = ref(null)
const recordStatusReconnectTimer = ref(null)
const recordStatusSocketEnabled = ref(false)
const durationTicker = ref(null)
const nowTickSec = ref(Math.floor(Date.now() / 1000))
const analyzeProgress = ref(0)
const analyzeMessage = ref('')
const analyzeStatus = ref('idle')
const RECORD_STATUS_CHANNEL = 'live_highlights_records'
const PAGE_STATE_KEY = 'live_highlights_page_state_v1'
const RECORD_FILTER_PREF_KEY = 'live_highlights_record_filter_pref_v1'
const ANALYZE_PREF_KEY = 'live_highlights_analyze_pref_v1'
const hasRecordFilterPreference = ref(false)
const analyzeLatest404Count = ref(0)
const showAdvancedModelOptions = ref(false)
const providerDefaultModel = {
  deepseek: 'deepseek-chat',
  compat: '',
  ollama: '',
  cloud: '',
  none: '',
}

// 手动切片模式状态
const activeTab = ref('ai')
const manualSourceType = ref('live') // 'live' | 'download'
const manualVideoList = ref([])
const manualVideosLoading = ref(false)
const manualSearchQuery = ref('')
const manualSelectedVideo = ref(null)
const manualSelectedRecordId = ref('')
const manualClips = ref([])
const manualClipsLoading = ref(false)
const manualBundling = ref(false)
const restoringPageState = ref(false)
const pendingRestoreAiRecordId = ref('')
const pendingRestoreManualRecordId = ref('')

// 移动端整页录制侧边栏展开状态
const showRecordsSidebarDrawer = ref(false)

// 移动端底部操作面板展开状态
const showActionsDrawer = ref(false)

// 录制视频筛选（博主选择 → 录制列表）
const manualDateFilterMode = ref('all')
const manualDateFilterDay = ref('')
const manualStreamerId = ref('')       // 选中博主的 subscription_id
const manualStreamerName = ref('')
const manualStreamerAvatar = ref('')
const manualStreamerSearch = ref('')
const manualStreamerPlatform = ref('all')
const manualStreamersLoading = ref(false)
const manualStreamerLoadingRecords = ref(false)
const manualDanmuRecordId = ref('')

// 下载视频筛选
const manualDownloadFilter = ref('all')
const manualDownloadPlatform = ref('all')
const manualDownloadAuthorId = ref('')
const manualPage = ref(1)
const manualPageSize = ref(20)
const manualTotalItems = ref(0)
const manualTotalPages = ref(0)
const manualThumbnailCache = ref({})  // { taskId: 'url' }
const manualShowAuthorDropdown = ref(false)
const manualAuthorSearch = ref('')
const manualAuthors = ref([])
const MANUAL_PLACEHOLDER = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'

// 下载视频缩略图加载
async function loadManualThumbnail(task) {
  if (!task || task.status !== 'COMPLETED' || !task.filename || manualThumbnailCache.value[task.id]) return
  try {
    const filename = String(task.filename || '')
    const isSubscription = filename.startsWith('subscriptions/')
    let platform = task.source || 'others'
    let folderPath = filename

    if (isSubscription) {
      const parts = filename.split('/')
      platform = parts[1] || platform
      folderPath = parts.slice(2).join('/')
    } else {
      const parts = filename.split('/')
      if (parts.length > 1) {
        platform = parts[0]
        folderPath = parts.slice(1).join('/')
      }
    }

    // 如果是视频文件，剥掉文件名只留目录
    const videoExts = ['.mp4', '.mkv', '.mov', '.webm', '.flv', '.ts', '.avi']
    const ext = folderPath ? '.' + folderPath.split('.').pop()?.toLowerCase() : ''
    let videoFilename = ''
    if (videoExts.includes(ext)) {
      const idx = folderPath.lastIndexOf('/')
      videoFilename = idx >= 0 ? folderPath.slice(idx + 1) : folderPath
      folderPath = idx >= 0 ? folderPath.slice(0, idx) : ''
    }

    const apiParams = {
      platform: platform,
      folder_path: folderPath || '.',
      subscription: isSubscription,
    }
    if (videoFilename) apiParams.video_filename = videoFilename

    const data = await tasksApi.getGalleryThumbnail(apiParams)
    if (data?.success && data?.thumbnail_path) {
      let thumbPath = data.thumbnail_path
      const encoded = thumbPath.split('/').map(encodeURIComponent).join('/')
      const fullPath = encoded.startsWith('downloads/') ? `/${encoded}` : `/downloads/${encoded}`
      const ts = Date.now()
      manualThumbnailCache.value = { ...manualThumbnailCache.value, [task.id]: `${fullPath}?t=${ts}` }
    }
  } catch (e) {
    console.warn('缩略图加载失败', e)
  }
}

// 平台显示名
function manualPlatformName(source) {
  const map = {
    douyin: '抖音', bilibili: 'B站', youtube: 'YouTube',
    tiktok: 'TikTok', xiaohongshu: '小红书', instagram: 'Instagram',
    netease: '网易云', x: 'X/Twitter', unknown: '未知', others: '其他'
  }
  return map[source?.toLowerCase()] || source || '未知'
}
// 平台图标名
function manualPlatformIcon(source) {
  const map = {
    douyin: 'video', bilibili: 'bilibili', youtube: 'youtube',
    tiktok: 'tiktok', xiaohongshu: 'image', netease: 'music',
    x: 'link', instagram: 'image', others: 'download', unknown: 'download'
  }
  return map[source?.toLowerCase()] || 'download'
}
// 状态文本
function manualStatusText(status) {
  const map = { COMPLETED: '已完成', ERROR: '失败', DOWNLOADING: '下载中', PROCESSING: '处理中', PENDING: '排队中', CANCELLED: '已取消' }
  return map[status] || status || '未知'
}

function manualFormatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return String(dateStr)
  const Y = d.getFullYear()
  const M = (d.getMonth() + 1).toString().padStart(2, '0')
  const D = d.getDate().toString().padStart(2, '0')
  const h = d.getHours().toString().padStart(2, '0')
  const m = d.getMinutes().toString().padStart(2, '0')
  return `${Y}-${M}-${D} ${h}:${m}`
}

// 博主筛选
const manualFilteredAuthorGroups = computed(() => {
  const q = manualAuthorSearch.value.trim().toLowerCase()
  let authors = manualAuthors.value
  if (q) {
    authors = authors.filter(a => (a.nickname || '').toLowerCase().includes(q))
  }
  // 按平台分组
  const groups = {}
  for (const a of authors) {
    const p = a.platform || 'unknown'
    if (!groups[p]) groups[p] = { platform: p, platformName: manualPlatformName(p), authors: [] }
    groups[p].authors.push(a)
  }
  return Object.values(groups).sort((a, b) => a.platformName.localeCompare(b.platformName))
})

const manualCurrentAuthorName = computed(() => {
  const a = manualAuthors.value.find(a => a.subscription_id === manualDownloadAuthorId.value)
  return a ? a.nickname : ''
})

async function loadManualAuthors() {
  try {
    const res = await tasksApi.getAuthors()
    manualAuthors.value = Array.isArray(res?.authors) ? res.authors : []
  } catch (e) {
    manualAuthors.value = []
  }
}

function toggleAuthorDropdown() {
  manualShowAuthorDropdown.value = !manualShowAuthorDropdown.value
  if (manualShowAuthorDropdown.value) {
    manualAuthorSearch.value = ''
  }
}
function closeAuthorDropdown() { manualShowAuthorDropdown.value = false }
function selectManualAuthor(author) {
  manualDownloadAuthorId.value = author.subscription_id
  manualShowAuthorDropdown.value = false
  manualPage.value = 1
  loadDownloadVideos()
}
function clearManualAuthor() {
  manualDownloadAuthorId.value = ''
  loadDownloadVideos()
}

const previewTitle = computed(() => {
  if (previewSegment.value) return previewSegment.value.title
  if (manualSelectedVideo.value) return manualSelectedVideo.value.filename || manualSelectedVideo.value.title || '手动切片'
  return '手动切片'
})

const editorStartSec = computed(() => {
  if (previewSegment.value) return Number(previewSegment.value.start_sec || 0)
  return 0
})
const clipEditorTsMode = computed(() => {
  const fp = selectedRecord.value?.file_path || manualSelectedVideo.value?.file_path || ''
  return /\.ts$/i.test(fp)
})

const editorEndSec = computed(() => {
  if (previewSegment.value) return Number(previewSegment.value.end_sec || 30)
  return 30
})

const streamTypePresets = [
  '游戏',
  '户外',
  '钓鱼',
  '唱歌',
  '聊天',
  '带货',
  '知识讲解',
  '美食',
  '体育赛事',
  '棋牌'
]
const HIGHLIGHTS_SUPPORTED_PLATFORMS = new Set(['douyin', 'bilibili', 'douyu', 'huya', 'twitch'])
const asrModelOptions = [
  { value: 'tiny', label: '快速 tiny' },
  { value: 'base', label: '基础 base' },
  { value: 'small', label: '均衡 small' },
  { value: 'medium', label: '高质量 medium' }
]
const ASR_MODEL_NAMES = new Set(asrModelOptions.map((item) => item.value))
const asrModelsLoading = ref(false)
const asrModelStatusMap = ref({})
const selectedAsrModelInfo = computed(() => asrModelStatusMap.value[String(form.value.asr_model || '')] || null)
const selectedAsrModelInstalled = computed(() => !!selectedAsrModelInfo.value?.installed)
const selectedAsrModelStatusText = computed(() => {
  if (asrModelsLoading.value) return '正在读取模型状态...'
  const info = selectedAsrModelInfo.value
  if (!info) return '模型状态未读取'
  if (info.installed) return '已安装'
  return '未安装，首次使用会自动下载'
})

const form = ref({
  highlight_type: 'high_energy',
  analysis_strategy: 'llm_required',
  max_candidates: 5,
  seed: -1,
  randomness: 10,
  danmu_delay_compensation_seconds: 5,
  stream_type: '',
  window_seconds: 10,
  pre_padding_seconds: 20,
  post_padding_seconds: 15,
  story_enabled: true,
  asr_enabled: true,
  asr_model: 'small',
  asr_device: 'cpu',
  asr_compute_type: 'int8',
  l1_scout_config: {
    provider: 'none',
    model: '',
    temperature: 0.0,
    max_concurrency: 4
  },
  l2_editor_config: {
    provider: 'none',
    model: '',
    temperature: 0.7,
    max_concurrency: 4
  }
})

const eligibleRecords = computed(() =>
  allRecords.value.filter(r =>
    HIGHLIGHTS_SUPPORTED_PLATFORMS.has(String(r.platform || '').toLowerCase())
  )
)

const streamerList = computed(() => {
  return streamerListRaw.value.map(s => ({
    ...s,
    record_count: s.record_count || 0
  }))
})

const filteredStreamers = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  return streamerList.value.filter(s => {
    if (selectedPlatform.value !== 'all' && s.platform !== selectedPlatform.value) return false
    if (!q) return true
    return String(s.anchor_name || '').toLowerCase().includes(q)
  })
})

const selectedStreamer = computed(() => streamerList.value.find(s => s.id === selectedStreamerId.value) || null)
const selectedRecord = computed(() => selectedStreamerRecords.value.find(r => String(r.id) === String(selectedRecordId.value || '')) || null)
const selectedManualStreamer = computed(() => manualStreamerList.value.find(s => s.id === manualStreamerId.value) || null)

function platformTagText(platform) {
  const key = String(platform || '').toLowerCase()
  if (key === 'bilibili') return 'B站'
  if (key === 'douyin') return '抖音'
  if (key === 'douyu') return '斗鱼'
  if (key === 'huya') return '虎牙'
  if (key === 'cc') return '网易CC'
  if (key === 'twitch') return 'Twitch'
  return key || '未知'
}

function recordFormatExt(filePath) {
  const ext = String(filePath || '').split('.').pop()?.toLowerCase()
  if (ext === 'ts') return 'TS'
  if (ext === 'mp4') return 'MP4'
  if (ext === 'flv') return 'FLV'
  if (ext === 'mkv') return 'MKV'
  return ext?.toUpperCase() || ''
}

function platformTagClass(platform) {
  const key = String(platform || '').toLowerCase()
  if (key === 'bilibili') return 'tag-bilibili'
  if (key === 'douyin') return 'tag-douyin'
  if (key === 'douyu') return 'tag-douyu'
  if (key === 'huya') return 'tag-huya'
  if (key === 'cc') return 'tag-cc'
  if (key === 'twitch') return 'tag-twitch'
  return 'tag-unknown'
}

const selectedStreamerRecords = computed(() =>
  eligibleRecords.value
    .filter(r => String(r.subscription_id || '') === selectedStreamerId.value)
    .sort((a, b) => new Date(b.start_time || 0).getTime() - new Date(a.start_time || 0).getTime())
)

function toDateKey(value) {
  const dt = new Date(value || '')
  if (Number.isNaN(dt.getTime())) return ''
  const y = dt.getFullYear()
  const m = String(dt.getMonth() + 1).padStart(2, '0')
  const d = String(dt.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function isWithinRecentDays(value, days) {
  const dt = new Date(value || '')
  if (Number.isNaN(dt.getTime())) return false
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - (days - 1))
  return dt.getTime() >= start.getTime()
}

const selectedStreamerRecordsFiltered = computed(() => {
  const mode = recordDateFilterMode.value
  const list = selectedStreamerRecords.value
  if (mode === 'all') return list
  if (mode === 'today') {
    const today = toDateKey(new Date())
    return list.filter(r => toDateKey(r.start_time) === today)
  }
  if (mode === 'last7') {
    return list.filter(r => isWithinRecentDays(r.start_time, 7))
  }
  if (mode === 'last30') {
    return list.filter(r => isWithinRecentDays(r.start_time, 30))
  }
  if (mode === 'day') {
    if (!recordDateFilterDay.value) return list
    return list.filter(r => toDateKey(r.start_time) === recordDateFilterDay.value)
  }
  return list
})

const resultMeta = computed(() => {
  if (!analyzedAt.value) return ''
  return `分析时间：${formatTime(analyzedAt.value)} · 候选数：${segments.value.length}`
})

const analyzeStatusText = computed(() => {
  if (analyzeStatus.value === 'queued') return '排队中'
  if (analyzeStatus.value === 'running') return '分析中'
  if (analyzeStatus.value === 'success') return '已完成'
  if (analyzeStatus.value === 'cancelled') return '已终止'
  if (analyzeStatus.value === 'failed') return '失败'
  return '未开始'
})

const analyzeActionText = computed(() => {
  if (terminatingAnalyze.value) return '终止中...'
  if (!analyzing.value) return '开始分析'
  if (analyzeButtonHover.value) return '终止分析'
  return `分析中 ${analyzeProgress.value}%`
})

const modelSourceText = computed(() => {
  if (form.value.analysis_strategy === 'rule_only') return '规则模式不依赖模型'
  
  const l1 = form.value.l1_scout_config.provider
  const l2 = form.value.l2_editor_config.provider
  
  if (l1 === 'none' && l2 === 'none') {
    return `系统兜底引擎: ${providerLabel(settingsModelSource.value)}`
  }
  
  const parts = []
  if (l1 !== 'none') parts.push(`L1初筛(${providerLabel(l1)})`)
  if (l2 !== 'none') parts.push(`L2精修(${providerLabel(l2)})`)
  
  return parts.join(' / ')
})

function providerLabel(provider) {
  const key = String(provider || '').toLowerCase()
  if (key === 'minimax') return 'MiniMax'
  if (key === 'cloud') return 'MiniMax'
  if (key === 'deepseek') return 'DeepSeek'
  if (key === 'compat') return '兼容平台'
  if (key === 'ollama') return 'Ollama'
  if (key === 'local') return 'Ollama'
  if (key === 'none') return '关闭'
  return '未配置'
}

function normalizeProviderForDisplay(provider) {
  const key = String(provider || '').trim().toLowerCase()
  if (key === 'cloud') return 'minimax'
  if (key === 'local') return 'ollama'
  return key || 'none'
}

function normalizeProviderForAnalyzeRequest(provider) {
  const key = String(provider || '').trim().toLowerCase()
  if (key === 'minimax') return 'cloud'
  if (key === 'local') return 'ollama'
  return key || 'none'
}

function modelNameFromProviderConfig(cfg, provider, fallback = '') {
  const key = String(provider || '').trim().toLowerCase()
  if (key === 'minimax' || key === 'cloud') {
    return String(cfg?.llm_minimax_model || '').trim() || String(fallback || '').trim() || providerDefaultModel.minimax
  }
  if (key === 'deepseek') {
    return String(cfg?.llm_deepseek_model || '').trim() || String(fallback || '').trim() || providerDefaultModel.deepseek
  }
  if (key === 'compat') {
    return String(cfg?.llm_compat_model || '').trim() || String(fallback || '').trim() || providerDefaultModel.compat
  }
  if (key === 'ollama' || key === 'local') {
    return String(cfg?.llm_ollama_model || '').trim() || String(fallback || '').trim() || providerDefaultModel.ollama
  }
  return String(fallback || '').trim()
}

const l1ModelText = computed(() => {
  if (form.value.analysis_strategy === 'rule_only') return '规则模式下不启用'
  const provider = String(form.value.l1_scout_config?.provider || 'none').toLowerCase()
  const model = String(form.value.l1_scout_config?.model || '').trim()
  if (provider === 'none') return '关闭'
  const maxConcurrency = clampModelConcurrency(form.value.l1_scout_config?.max_concurrency, 4)
  return `${providerLabel(provider)} · ${model || '未配置模型名'} · 并发${maxConcurrency}`
})

const l2ModelText = computed(() => {
  if (form.value.analysis_strategy === 'rule_only') return '规则模式下不启用'
  const provider = String(form.value.l2_editor_config?.provider || 'none').toLowerCase()
  const model = String(form.value.l2_editor_config?.model || '').trim()
  if (provider === 'none') return '关闭'
  const maxConcurrency = clampModelConcurrency(form.value.l2_editor_config?.max_concurrency, 4)
  return `${providerLabel(provider)} · ${model || '未配置模型名'} · 并发${maxConcurrency}`
})

function formatScore(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return n.toFixed(digits)
}

function getSegmentSpeech(segId) {
  if (!segId) return ''
  const seg = segments.value.find(s => s.id === segId)
  return seg?.speech_text || '(无语音转写内容)'
}

function hasAiDecision(segment) {
  return segment?.llm_decision_score != null || segment?.llm_confidence != null || segment?.llm_is_highlight != null
}

function aiDecisionValue(segment) {
  const decision = Number(segment?.llm_decision_score)
  if (Number.isFinite(decision)) return decision
  const confidence = Number(segment?.llm_confidence)
  return Number.isFinite(confidence) ? confidence : 0
}

function aiDecisionText(segment) {
  const value = aiDecisionValue(segment)
  if (segment?.llm_is_highlight === false && value < 0.62) return `${negativeReasonLabel(segment?.llm_negative_reason)} ${formatScore(value, 2)}`
  if (value >= 0.75) return `AI通过 ${formatScore(value, 2)}`
  return `AI复核 ${formatScore(value, 2)}`
}

function aiDecisionClass(segment) {
  const value = aiDecisionValue(segment)
  if (segment?.llm_is_highlight === false && value < 0.62) return 'is-low'
  if (value >= 0.75) return 'is-strong'
  return 'is-medium'
}

function aiDecisionTooltip(segment) {
  const confidence = formatScore(segment?.llm_confidence, 2)
  const decision = formatScore(segment?.llm_decision_score, 2)
  const rank = formatScore(segment?.global_rank_score, 2)
  const scene = String(segment?.llm_scene_type || segment?.highlight_type || '').trim() || '未知'
  const reason = negativeReasonLabel(segment?.llm_negative_reason)
  const shifted = [
    Number(segment?.llm_start_shift_sec || 0),
    Number(segment?.llm_end_shift_sec || 0)
  ].some(v => Number.isFinite(v) && v !== 0)
  return `AI复核：决策分 ${decision}，全局分 ${rank}，置信度 ${confidence}，场景 ${scene}，原因 ${reason}${shifted ? '，已微调时间' : ''}`
}

function negativeReasonLabel(reason) {
  const key = String(reason || 'none').trim().toLowerCase()
  const map = {
    none: 'AI降权',
    tech_issue: '技术噪音',
    shopping_query: '购物咨询',
    greeting: '问候签到',
    spam: '复读刷屏',
    off_topic: '跑题闲聊',
    low_signal: '信息不足'
  }
  return map[key] || 'AI降权'
}

const isAllSelected = computed(() =>
  segments.value.length > 0 &&
  segments.value.every(s => selectedSegmentIds.value.includes(s.id))
)

function toggleSelectAll() {
  if (isAllSelected.value) {
    selectedSegmentIds.value = []
  } else {
    selectedSegmentIds.value = segments.value.map(s => s.id)
  }
}

function formatTime(v) {
  if (!v) return '-'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return String(v)
  return d.toLocaleString()
}

function secToClock(sec) {
  const s = Math.max(0, Math.floor(sec || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const x = s % 60
  if (h > 0) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`
  return `${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`
}

function formatBytes(size) {
  const val = Number(size || 0)
  if (!Number.isFinite(val) || val <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let idx = 0
  let n = val
  while (n >= 1024 && idx < units.length - 1) {
    n /= 1024
    idx += 1
  }
  const digits = n >= 100 ? 0 : n >= 10 ? 1 : 2
  return `${n.toFixed(digits)} ${units[idx]}`
}

function asrModelOptionLabel(item) {
  const name = String(item?.value || '')
  const baseLabel = String(item?.label || name)
  const info = asrModelStatusMap.value[name]
  if (asrModelsLoading.value) return `${baseLabel}（读取中）`
  if (!info) return baseLabel
  return `${baseLabel}（${info.installed ? '已安装' : '未安装'}）`
}

async function loadAsrModelStatus() {
  if (asrModelsLoading.value) return
  asrModelsLoading.value = true
  try {
    const result = await aiConfigApi.listAsrModels()
    const nextMap = {}
    const models = Array.isArray(result?.models) ? result.models : []
    for (const model of models) {
      const name = String(model?.name || '').trim()
      if (!name) continue
      nextMap[name] = model
    }
    asrModelStatusMap.value = nextMap
  } catch (e) {
    console.warn('Failed to load ASR model status:', e)
  } finally {
    asrModelsLoading.value = false
  }
}

function recordDurationText(record) {
  const status = String(record?.status || '').toLowerCase()
  let seconds = Number(record?.duration || 0)

  const startAt = new Date(record?.start_time || '')
  const endAt = new Date(record?.end_time || '')
  const hasStart = !Number.isNaN(startAt.getTime())
  const hasEnd = !Number.isNaN(endAt.getTime())

  if (status === 'recording' && hasStart) {
    const liveSec = Math.max(0, Math.floor(nowTickSec.value - startAt.getTime() / 1000))
    seconds = Math.max(seconds, liveSec)
  } else if (seconds <= 0 && hasStart && hasEnd) {
    seconds = Math.max(0, Math.floor((endAt.getTime() - startAt.getTime()) / 1000))
  }

  if (!Number.isFinite(seconds) || seconds <= 0) return '-'
  return secToClock(seconds)
}

function recordStatusText(status) {
  const s = String(status || '').toLowerCase()
  if (s === 'recording') return '录制中'
  if (s === 'stopped') return '录制中断'
  if (s === 'completed') return '录制完成'
  if (s === 'failed') return '录制失败'
  if (s === 'queued') return '排队中'
  if (s === 'running') return '正在录制'
  return String(status || '-')
}

function getRecordHighlightState(record) {
  const status = String(record?.highlights_status || '').toLowerCase()
  if (record?.has_highlights_analysis || status === 'success') return 'success'
  if (status === 'running' || status === 'queued') return 'running'
  if (status === 'failed') return 'failed'
  return 'none'
}

function recordHighlightTagText(record) {
  const state = getRecordHighlightState(record)
  if (state === 'success') return '已分析'
  if (state === 'running') return '分析中'
  if (state === 'failed') return '分析失败'
  return ''
}

function recordHighlightTagClass(record) {
  const state = getRecordHighlightState(record)
  if (state === 'success') return 'is-success'
  if (state === 'running') return 'is-running'
  if (state === 'failed') return 'is-failed'
  return ''
}

function recordStatusTagClass(status) {
  const s = String(status || '').toLowerCase()
  if (s === 'completed') return 'is-success'
  if (s === 'recording' || s === 'running') return 'is-running'
  if (s === 'failed') return 'is-failed'
  return 'is-neutral'
}

function recordManualClipTagText(record) {
  const count = Number(record?.manual_clip_count || 0)
  if (record?.has_manual_clips || count > 0) return count > 1 ? `已切片 ${count}` : '已切片'
  return ''
}

function recordManualClipTagClass(record) {
  return recordManualClipTagText(record) ? 'is-success' : ''
}

function resetResultPanel() {
  segments.value = []
  analyzedAt.value = ''
  selectedSegmentIds.value = []
}

function saveRecordFilterPreference() {
  const mode = String(recordDateFilterMode.value || 'last7')
  const day = String(recordDateFilterDay.value || '')
  const payload = { mode, day }
  localStorage.setItem(RECORD_FILTER_PREF_KEY, JSON.stringify(payload))
}

function restoreRecordFilterPreference() {
  const raw = localStorage.getItem(RECORD_FILTER_PREF_KEY)
  if (!raw) {
    hasRecordFilterPreference.value = false
    return
  }
  try {
    const parsed = JSON.parse(raw)
    const mode = String(parsed?.mode || '').trim()
    const day = String(parsed?.day || '').trim()
    if (['all', 'today', 'last7', 'last30', 'day'].includes(mode)) {
      recordDateFilterMode.value = mode
      hasRecordFilterPreference.value = true
      if (mode === 'day') {
        recordDateFilterDay.value = day || toDateKey(new Date())
      } else {
        recordDateFilterDay.value = day
      }
      return
    }
  } catch (_) {
    // noop
  }
  hasRecordFilterPreference.value = false
}

function applyDefaultRecordFilterFallback() {
  if (!selectedStreamerId.value) return
  if (hasRecordFilterPreference.value) return
  if (recordDateFilterMode.value !== 'last7') return
  if (selectedStreamerRecords.value.length > 0 && selectedStreamerRecordsFiltered.value.length === 0) {
    recordDateFilterMode.value = 'all'
  }
}

function onRecordFilterModeUserChange() {
  hasRecordFilterPreference.value = true
  if (recordDateFilterMode.value === 'day' && !recordDateFilterDay.value) {
    recordDateFilterDay.value = toDateKey(new Date())
  }
  saveRecordFilterPreference()
}

function onRecordFilterDayUserChange() {
  if (recordDateFilterMode.value !== 'day') return
  hasRecordFilterPreference.value = true
  saveRecordFilterPreference()
}

function savePageState() {
  let previous = {}
  const raw = localStorage.getItem(PAGE_STATE_KEY)
  if (raw) {
    try {
      previous = JSON.parse(raw) || {}
    } catch (_) {
      previous = {}
    }
  }
  const previousAi = previous.ai || {
    selected_streamer_id: previous.selected_streamer_id || '',
    selected_record_id: previous.selected_record_id || '',
  }
  const previousManual = previous.manual_live || {
    streamer_id: previous.manual_streamer_id || '',
    streamer_name: previous.manual_streamer_name || '',
    streamer_avatar: previous.manual_streamer_avatar || '',
    selected_record_id: previous.manual_selected_record_id || '',
    date_filter_mode: previous.manual_date_filter_mode || 'all',
    date_filter_day: previous.manual_date_filter_day || '',
  }
  const aiState = selectedStreamerId.value
    ? {
        selected_streamer_id: selectedStreamerId.value || '',
        selected_record_id: selectedRecordId.value || '',
      }
    : previousAi
  const manualState = manualStreamerId.value
    ? {
        streamer_id: manualStreamerId.value || '',
        streamer_name: manualStreamerName.value || '',
        streamer_avatar: manualStreamerAvatar.value || '',
        selected_record_id: manualSelectedRecordId.value || '',
        date_filter_mode: manualDateFilterMode.value || 'all',
        date_filter_day: manualDateFilterDay.value || '',
      }
    : previousManual
  const payload = {
    version: 2,
    active_tab: activeTab.value,
    ai: aiState,
    manual_live: manualState,
    selected_streamer_id: aiState.selected_streamer_id || '',
    selected_record_id: aiState.selected_record_id || '',
    manual_streamer_id: manualState.streamer_id || '',
    manual_streamer_name: manualState.streamer_name || '',
    manual_streamer_avatar: manualState.streamer_avatar || '',
    manual_selected_record_id: manualState.selected_record_id || '',
    manual_date_filter_mode: manualState.date_filter_mode || 'all',
    manual_date_filter_day: manualState.date_filter_day || '',
  }
  localStorage.setItem(PAGE_STATE_KEY, JSON.stringify(payload))
}

function clampInt(value, min, max, fallback) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  const i = Math.round(n)
  return Math.max(min, Math.min(max, i))
}

function clampModelConcurrency(value, fallback = 4) {
  return clampInt(value, 1, 8, fallback)
}

function saveAnalyzePreference() {
  const payload = {
    highlight_type: String(form.value.highlight_type || 'high_energy'),
    max_candidates: clampInt(form.value.max_candidates, 1, 100, 1),
    seed: Number.isFinite(Number(form.value.seed)) ? Math.trunc(Number(form.value.seed)) : -1,
    randomness: clampInt(form.value.randomness, 0, 100, 10),
    danmu_delay_compensation_seconds: clampInt(form.value.danmu_delay_compensation_seconds, 0, 30, 5),
    stream_type: String(form.value.stream_type || '').slice(0, 64),
    story_enabled: Boolean(form.value.story_enabled),
    asr_enabled: Boolean(form.value.asr_enabled),
    asr_model: ASR_MODEL_NAMES.has(String(form.value.asr_model || '')) ? String(form.value.asr_model) : 'small',
    analysis_strategy: ['rule_only', 'llm_required'].includes(String(form.value.analysis_strategy || ''))
      ? String(form.value.analysis_strategy)
      : 'llm_required',
    l1_max_concurrency: clampModelConcurrency(form.value.l1_scout_config?.max_concurrency, 4),
    l2_max_concurrency: clampModelConcurrency(form.value.l2_editor_config?.max_concurrency, 4),
    show_advanced_model_options: !!showAdvancedModelOptions.value
  }
  localStorage.setItem(ANALYZE_PREF_KEY, JSON.stringify(payload))
}

function restoreAnalyzePreference() {
  const raw = localStorage.getItem(ANALYZE_PREF_KEY)
  if (!raw) return
  try {
    const parsed = JSON.parse(raw)
    const highlightType = String(parsed?.highlight_type || '').trim()
    const strategy = String(parsed?.analysis_strategy || '').trim()

    if (['high_energy', 'funny', 'controversy', 'teaching', 'emotion'].includes(highlightType)) {
      form.value.highlight_type = highlightType
    }
    form.value.max_candidates = clampInt(parsed?.max_candidates, 1, 100, 1)
    form.value.seed = Number.isFinite(Number(parsed?.seed)) ? Math.trunc(Number(parsed.seed)) : -1
    form.value.randomness = clampInt(parsed?.randomness, 0, 100, 10)
    form.value.danmu_delay_compensation_seconds = clampInt(parsed?.danmu_delay_compensation_seconds, 0, 30, 5)
    form.value.stream_type = String(parsed?.stream_type || '').slice(0, 64)
    form.value.story_enabled = parsed?.story_enabled === undefined ? true : !!parsed.story_enabled
    form.value.asr_enabled = parsed?.asr_enabled === undefined ? true : !!parsed.asr_enabled
    form.value.asr_model = ASR_MODEL_NAMES.has(String(parsed?.asr_model || '')) ? String(parsed.asr_model) : 'small'
    form.value.analysis_strategy = ['rule_only', 'llm_required'].includes(strategy) ? strategy : 'llm_required'
    form.value.l1_scout_config.max_concurrency = clampModelConcurrency(parsed?.l1_max_concurrency, 4)
    form.value.l2_editor_config.max_concurrency = clampModelConcurrency(parsed?.l2_max_concurrency, 4)
    showAdvancedModelOptions.value = !!parsed?.show_advanced_model_options
  } catch (_) {
    // noop
  }
}

function resetAnalyzePreferenceToDefault() {
  form.value.highlight_type = 'high_energy'
  form.value.analysis_strategy = 'llm_required'
  form.value.max_candidates = 5
  form.value.seed = -1
  form.value.randomness = 10
  form.value.danmu_delay_compensation_seconds = 5
  form.value.stream_type = ''
  form.value.story_enabled = true
  form.value.asr_enabled = true
  form.value.asr_model = 'small'
  form.value.asr_device = 'cpu'
  form.value.asr_compute_type = 'int8'
  form.value.l1_scout_config.max_concurrency = 4
  form.value.l2_editor_config.max_concurrency = 4
  showAdvancedModelOptions.value = false
  localStorage.removeItem(ANALYZE_PREF_KEY)
  saveAnalyzePreference()
  success('已恢复默认分析参数')
}

function updateStoredPageState(mutator) {
  let payload = {}
  const raw = localStorage.getItem(PAGE_STATE_KEY)
  if (raw) {
    try {
      payload = JSON.parse(raw) || {}
    } catch (_) {
      payload = {}
    }
  }
  payload.version = 2
  mutator(payload)
  localStorage.setItem(PAGE_STATE_KEY, JSON.stringify(payload))
}

function clearPageState(section = 'all') {
  if (section === 'ai') {
    selectedStreamerId.value = ''
    selectedRecordId.value = ''
    updateStoredPageState(payload => {
      payload.active_tab = activeTab.value
      payload.ai = { selected_streamer_id: '', selected_record_id: '' }
      payload.selected_streamer_id = ''
      payload.selected_record_id = ''
    })
    return
  }
  if (section === 'manual') {
    manualStreamerId.value = ''
    manualStreamerName.value = ''
    manualStreamerAvatar.value = ''
    manualSelectedRecordId.value = ''
    manualSelectedVideo.value = null
    manualClips.value = []
    updateStoredPageState(payload => {
      payload.active_tab = activeTab.value
      payload.manual_live = {
        streamer_id: '',
        streamer_name: '',
        streamer_avatar: '',
        selected_record_id: '',
        date_filter_mode: manualDateFilterMode.value || 'all',
        date_filter_day: manualDateFilterDay.value || '',
      }
      payload.manual_streamer_id = ''
      payload.manual_streamer_name = ''
      payload.manual_streamer_avatar = ''
      payload.manual_selected_record_id = ''
    })
    return
  }
  localStorage.removeItem(PAGE_STATE_KEY)
}

async function restorePageState() {
  const raw = localStorage.getItem(PAGE_STATE_KEY)
  if (!raw) return
  restoringPageState.value = true
  try {
    const parsed = JSON.parse(raw)
    const tab = String(parsed?.active_tab || 'ai')
    activeTab.value = tab === 'ai' || tab === 'manual' ? tab : 'ai'

    if (tab === 'manual') {
      const manualState = parsed?.manual_live || {}
      const sid = String(manualState.streamer_id || parsed?.manual_streamer_id || '')
      if (sid) {
        manualStreamerId.value = sid
        manualStreamerName.value = String(manualState.streamer_name || parsed?.manual_streamer_name || '')
        manualStreamerAvatar.value = String(manualState.streamer_avatar || parsed?.manual_streamer_avatar || '')
        manualDateFilterMode.value = String(manualState.date_filter_mode || parsed?.manual_date_filter_mode || 'all')
        manualDateFilterDay.value = String(manualState.date_filter_day || parsed?.manual_date_filter_day || '')
        pendingRestoreManualRecordId.value = String(manualState.selected_record_id || parsed?.manual_selected_record_id || '')
        await loadLiveVideos()
        restoreManualSelectedRecord()
      }
      return
    }

    // AI 模式
    const aiState = parsed?.ai || {}
    const streamerId = String(aiState.selected_streamer_id || parsed?.selected_streamer_id || '')
    const recordId = String(aiState.selected_record_id || parsed?.selected_record_id || '')
    if (!streamerId) return
    const hasStreamer = streamerList.value.some(s => s.id === streamerId)
    if (!hasStreamer) { clearPageState('ai'); return }
    pendingRestoreAiRecordId.value = recordId
    selectedStreamerId.value = streamerId
    await loadRecords(streamerId)
    if (!recordId) return
    const hasRecord = selectedStreamerRecords.value.some(r => String(r.id) === recordId)
    if (hasRecord) selectedRecordId.value = recordId
  } catch (_) {
    clearPageState()
  } finally {
    restoringPageState.value = false
  }
}

async function restoreStoredTabState(tab) {
  const raw = localStorage.getItem(PAGE_STATE_KEY)
  if (!raw) return
  try {
    const parsed = JSON.parse(raw)
    if (tab === 'manual') {
      const manualState = parsed?.manual_live || {}
      const sid = String(manualState.streamer_id || parsed?.manual_streamer_id || '')
      if (!sid || manualStreamerId.value) return
      manualStreamerId.value = sid
      manualStreamerName.value = String(manualState.streamer_name || parsed?.manual_streamer_name || '')
      manualStreamerAvatar.value = String(manualState.streamer_avatar || parsed?.manual_streamer_avatar || '')
      manualDateFilterMode.value = String(manualState.date_filter_mode || parsed?.manual_date_filter_mode || 'all')
      manualDateFilterDay.value = String(manualState.date_filter_day || parsed?.manual_date_filter_day || '')
      pendingRestoreManualRecordId.value = String(manualState.selected_record_id || parsed?.manual_selected_record_id || '')
      await loadLiveVideos()
      restoreManualSelectedRecord()
      return
    }

    const aiState = parsed?.ai || {}
    const streamerId = String(aiState.selected_streamer_id || parsed?.selected_streamer_id || '')
    if (!streamerId || selectedStreamerId.value) return
    const hasStreamer = streamerList.value.some(s => s.id === streamerId)
    if (!hasStreamer) return
    pendingRestoreAiRecordId.value = String(aiState.selected_record_id || parsed?.selected_record_id || '')
    selectedStreamerId.value = streamerId
    await loadRecords(streamerId)
  } catch (_) {
    // noop
  }
}

function stopAnalyzePoll() {
  if (analyzePollTimer.value) {
    clearInterval(analyzePollTimer.value)
    analyzePollTimer.value = null
  }
}

function closeAnalyzeSocket() {
  if (analyzePingTimer.value) {
    clearInterval(analyzePingTimer.value)
    analyzePingTimer.value = null
  }
  const ws = analyzeSocket.value
  analyzeSocket.value = null
  if (ws) {
    try {
      ws.close()
    } catch (_) {
      // noop
    }
  }
}

function stopAnalyzeTracking() {
  stopAnalyzePoll()
  closeAnalyzeSocket()
  analyzeTaskId.value = ''
  analyzing.value = false
  terminatingAnalyze.value = false
  analyzeButtonHover.value = false
  analyzeProgress.value = 0
  analyzeMessage.value = ''
  analyzeStatus.value = 'idle'
}

function applyAnalyzeTaskState(task) {
  if (!task) return
  const taskRecordId = String(task.record_id || selectedRecordId.value || '')
  const status = String(task.status || '')
  analyzeStatus.value = status || 'idle'
  analyzeProgress.value = Math.max(0, Math.min(100, Number(task.progress || 0)))
  analyzeMessage.value = String(task.message || '')
  if (status === 'queued' || status === 'running') {
    patchRecordHighlightState(taskRecordId, { highlights_status: status })
  }
  const incomingStreamType = String(task.stream_type || '').trim()
  if (incomingStreamType && !String(form.value.stream_type || '').trim()) {
    form.value.stream_type = incomingStreamType
  }
  if (status === 'success') {
    patchRecordHighlightState(taskRecordId, {
      highlights_status: 'success',
      has_highlights_analysis: true
    })
    analyzing.value = false
    terminatingAnalyze.value = false
    stopAnalyzePoll()
    closeAnalyzeSocket()
    analyzeTaskId.value = ''
    success(`分析完成，生成 ${Number(task.segment_count || 0)} 个候选片段`)
    loadResult()
    return
  }
  if (status === 'failed') {
    patchRecordHighlightState(taskRecordId, { highlights_status: 'failed' })
    analyzing.value = false
    terminatingAnalyze.value = false
    stopAnalyzePoll()
    closeAnalyzeSocket()
    analyzeTaskId.value = ''
    error(`分析失败: ${task.error || task.message || '未知错误'}`)
    return
  }
  if (status === 'cancelled') {
    patchRecordHighlightState(taskRecordId, {
      highlights_status: '',
      has_highlights_analysis: false
    })
    analyzing.value = false
    terminatingAnalyze.value = false
    stopAnalyzePoll()
    closeAnalyzeSocket()
    analyzeTaskId.value = ''
    analyzeProgress.value = 0
    analyzeMessage.value = ''
    return
  }
}

function handleAnalyzeSocketMessage(payload) {
  if (!payload || typeof payload !== 'object') return
  if (payload.type === 'hello') return
  if (analyzeTaskId.value && payload.task_id && payload.task_id !== analyzeTaskId.value) return
  applyAnalyzeTaskState(payload)
}

function connectAnalyzeSocket(recordId) {
  closeAnalyzeSocket()
  const channel = `live_highlights:${recordId}`
  const wsUrl = buildAuthedWsUrl(`/api/ws/subscribe/${encodeURIComponent(channel)}/progress`)
  const ws = new WebSocket(wsUrl)
  ws.onopen = () => {
    analyzePingTimer.value = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping')
    }, 20000)
  }
  ws.onmessage = event => {
    if (event.data === 'pong') return
    try {
      const payload = JSON.parse(event.data)
      handleAnalyzeSocketMessage(payload)
    } catch (_) {
      // noop
    }
  }
  ws.onclose = () => {
    if (analyzePingTimer.value) {
      clearInterval(analyzePingTimer.value)
      analyzePingTimer.value = null
    }
  }
  analyzeSocket.value = ws
}

async function recoverAnalyzeTask(recordId) {
  if (!recordId) return
  try {
    const latest = await liveHighlightsApi.getAnalyzeLatest(recordId)
    if (!latest || !latest.task_id) return
    analyzeTaskId.value = latest.task_id
    applyAnalyzeTaskState(latest)
    if (String(latest.status || '') === 'queued' || String(latest.status || '') === 'running') {
      analyzing.value = true
      connectAnalyzeSocket(recordId)
      startAnalyzePoll(recordId)
    }
  } catch (_) {
    // noop
  }
}

function startAnalyzePoll(recordId) {
  stopAnalyzePoll()
  analyzeLatest404Count.value = 0
  analyzePollTimer.value = setInterval(async () => {
    if (!recordId || !analyzeTaskId.value) {
      stopAnalyzePoll()
      return
    }
    try {
      const status = await liveHighlightsApi.getAnalyzeLatest(recordId)
      analyzeLatest404Count.value = 0
      applyAnalyzeTaskState(status || {})
    } catch (e) {
      if (e?.response?.status === 404) {
        if (!analyzing.value) {
          stopAnalyzePoll()
          return
        }
        analyzeLatest404Count.value += 1
        if (analyzeLatest404Count.value >= 3) {
          stopAnalyzeTracking()
          patchRecordHighlightState(recordId, { highlights_status: 'failed' })
          error('分析任务状态丢失，请重新发起分析')
        }
      }
      // 轮询兜底，不打扰用户
    }
  }, 2500)
}

function encodeDownloadPath(path) {
  return String(path || '')
    .split('/')
    .map(p => encodeURIComponent(p))
    .join('/')
}

function buildClipPreviewUrl(clipPath) {
  const normalized = String(clipPath || '').replace(/\\/g, '/')
  if (!normalized) return ''

  const marker = '/app/downloads/'
  const markerIdx = normalized.indexOf(marker)
  let relative = markerIdx >= 0 ? normalized.slice(markerIdx + marker.length) : normalized.replace(/^\/+/, '')
  if (relative.startsWith('downloads/')) relative = relative.slice('downloads/'.length)
  if (!relative) return ''

  let url = `/api/video/stream?filename=${encodeDownloadPath(relative)}&quality=original`
  const token = localStorage.getItem('token')
  if (token) url += `&token=${encodeURIComponent(token)}`
  return url
}

function resetPreviewDanmuState() {
  previewDanmuLoading.value = false
  previewDanmuItems.value = []
  previewDanmuMeta.value = {
    total: 0,
    included: 0,
    truncated: false
  }
}

async function loadPreviewDanmu(segment) {
  const rid = selectedRecordId.value
  const sid = String(segment?.id || '')
  if (!rid || !sid) {
    resetPreviewDanmuState()
    return
  }
  previewDanmuLoading.value = true
  previewDanmuItems.value = []
  previewDanmuMeta.value = {
    total: 0,
    included: 0,
    truncated: false
  }
  try {
    const resp = await liveHighlightsApi.getSegmentDanmu(rid, sid)
    previewDanmuItems.value = Array.isArray(resp?.data) ? resp.data : []
    previewDanmuMeta.value = {
      total: Number(resp?.total_events || 0),
      included: Number(resp?.included_events || previewDanmuItems.value.length || 0),
      truncated: !!resp?.truncated
    }
  } catch (e) {
    previewDanmuItems.value = []
    previewDanmuMeta.value = {
      total: 0,
      included: 0,
      truncated: false
    }
    if (e?.response?.status !== 404) {
      error(`片段弹幕加载失败: ${e?.response?.data?.detail || e.message}`)
    }
  } finally {
    previewDanmuLoading.value = false
  }
}

function buildRecordStreamUrl(record, startSec) {
  const filePath = String(record?.converted ? (record?.converted_path || record?.file_path) : (record?.file_path || record?.converted_path)).replace(/\\/g, '/')
  if (!filePath) return ''
  const marker = '/app/downloads/'
  const idx = filePath.indexOf(marker)
  let relative = idx >= 0 ? filePath.slice(idx + marker.length) : filePath.replace(/^\/+/, '')
  if (relative.startsWith('downloads/')) relative = relative.slice('downloads/'.length)
  if (!relative) return ''
  // MP4 支持浏览器原生 range request seek，TS 需后端 ffmpeg 起播
  const isTs = /\.ts$/i.test(relative)
  let url = `/api/video/stream?filename=${encodeDownloadPath(relative)}&quality=original`
  if (isTs) {
    const s = Math.max(0, startSec || 0)
    url += `&start=${s.toFixed(3)}`
  }
  const token = localStorage.getItem('token')
  if (token) url += `&token=${encodeURIComponent(token)}`
  return url
}

function isTsFile() {
  const rec = selectedRecord.value
  const fp = String(rec?.converted ? (rec?.converted_path || rec?.file_path) : (rec?.file_path || rec?.converted_path))
  return /\.ts$/i.test(fp)
}

function openClipPreview(segment) {
  const record = selectedRecord.value
  if (!record) {
    error('预览失败: 未找到录制记录')
    return
  }
  const dur = Number(record.duration || 0)
  if (dur <= 0) {
    error('预览失败: 录制时长无效')
    return
  }
  const start = Number(segment?.start_sec || 0)
  const end = Number(segment?.end_sec || start + 10)
  // 检测 TS 格式，弹框提示转码并跳转
  const resolvedPath = record?.converted ? (record?.converted_path || record?.file_path) : (record?.file_path || record?.converted_path)
  if (/\.ts$/i.test(resolvedPath)) {
    dialog.confirm({
      title: 'TS 格式建议转码',
      message: '当前录制为 TS 格式，直接切片可能出现预览卡顿或画质异常。<br><br>建议先在直播录制页转码为 MP4 后再回来切片。',
      confirmText: '去转码',
      cancelText: '知道了',
    }).then(go => { if (go) router.push(`/live-record`) })
    return
  }
  // MP4 → 不传 start，浏览器原生 seek；TS → 传 start，后端 ffmpeg 起播
  const url = buildRecordStreamUrl(record, start)
  if (!url) {
    error('预览失败: 录制文件路径无效')
    return
  }
  originalDuration.value = dur
  adjustedStartSec.value = start
  adjustedEndSec.value = Math.min(end, dur)
  recordStreamUrl.value = url
  previewVisible.value = true
  previewSegment.value = segment || null
  resetPreviewDanmuState()
  // 初始弹幕基于当前时间加载
  void loadDanmuRange(adjustedStartSec.value, adjustedEndSec.value)
}

function onPreviewLoaded() {
  // 从视频元素获取实际时长（手动模式下可能后端未返回时长）
  if (previewVideoRef.value) {
    const vidDur = previewVideoRef.value.duration
    if (vidDur > 0 && (originalDuration.value <= 0 || Math.abs(vidDur - originalDuration.value) > 1)) {
      originalDuration.value = vidDur
      // 如果当前结束时间超过总时长，修正
      if (adjustedEndSec.value > vidDur) {
        adjustedEndSec.value = vidDur
      }
    }
  }
  // MP4：视频元数据加载后 seek 到片段起点；TS 由后端 start 参数处理，无需前端 seek
  if (!isTsFile() && previewVideoRef.value && adjustedStartSec.value > 0) {
    previewVideoRef.value.currentTime = adjustedStartSec.value
  }
}

function onPreviewTimeUpdate() {
  const vid = previewVideoRef.value
  if (!vid) return
  currentPreviewSec.value = Number(vid.currentTime || 0)
  // 播放到终点时自动暂停
  if (!vid.paused && !vid.ended && adjustedEndSec.value > 0 &&
      Number(vid.currentTime || 0) >= adjustedEndSec.value) {
    vid.pause()
  }
}

let seekUrlRebuildTimer = null
function _seekTo(sec) {
  if (isTsFile()) {
    // TS 无法浏览器端 seek，需重建 URL 让后端 ffmpeg 从新位置起播
    if (seekUrlRebuildTimer) clearTimeout(seekUrlRebuildTimer)
    seekUrlRebuildTimer = setTimeout(() => {
      const newUrl = buildRecordStreamUrl(selectedRecord.value, adjustedStartSec.value)
      if (newUrl && previewVideoRef.value) {
        previewVideoRef.value.src = newUrl
        previewVideoRef.value.load()
      }
      seekUrlRebuildTimer = null
    }, 400)
  } else if (previewVideoRef.value) {
    previewVideoRef.value.currentTime = sec
  }
}

function onStartSecAdjusted(sec) {
  adjustedStartSec.value = sec
  _seekTo(sec)
  debouncedLoadDanmu()
}

function onEndSecAdjusted(sec) {
  adjustedEndSec.value = sec
  debouncedLoadDanmu()
}

function onTimelineSeek(sec) {
  currentPreviewSec.value = sec
  _seekTo(sec)
}

let danmuLoadTimer = null
function debouncedLoadDanmu() {
  if (danmuLoadTimer) clearTimeout(danmuLoadTimer)
  danmuLoadTimer = setTimeout(() => {
    void loadDanmuRange(adjustedStartSec.value, adjustedEndSec.value)
    danmuLoadTimer = null
  }, 400)
}

async function loadDanmuRange(startSec, endSec) {
  const rid = selectedRecordId.value || manualDanmuRecordId.value
  if (!rid || startSec >= endSec) return
  previewDanmuLoading.value = true
  try {
    const resp = await liveHighlightsApi.getDanmuRange(rid, startSec, endSec, 200)
    previewDanmuItems.value = Array.isArray(resp?.data) ? resp.data : []
    previewDanmuMeta.value = {
      total: Number(resp?.total_events || 0),
      included: Number(resp?.included_events || previewDanmuItems.value.length || 0),
      truncated: !!resp?.truncated
    }
  } catch (e) {
    previewDanmuItems.value = []
    previewDanmuMeta.value = { total: 0, included: 0, truncated: false }
    if (e?.response?.status !== 404) {
      error(`弹幕加载失败: ${e?.response?.data?.detail || e.message}`)
    }
  } finally {
    previewDanmuLoading.value = false
  }
}

// ============ 手动切片模式函数 ============

/** 切换录制/下载来源时保留筛选状态 */
function switchManualSource(source) {
  manualSourceType.value = source
  manualSearchQuery.value = ''
  manualSelectedVideo.value = null
  if (source === 'live') {
    manualStreamerId.value = ''
    manualStreamerName.value = ''
    loadLiveVideos()
  } else {
    manualPage.value = 1
    manualDownloadAuthorId.value = ''
    loadDownloadVideos()
    loadManualAuthors()
  }
}

function selectManualStreamer(streamer) {
  manualStreamerId.value = streamer.id
  manualStreamerName.value = streamer.anchor_name || '未知主播'
  manualStreamerAvatar.value = streamer.avatar_url || ''
  manualSelectedRecordId.value = ''
  manualSelectedVideo.value = null
  manualClips.value = []
  manualDateFilterMode.value = 'all'
  manualDateFilterDay.value = ''
  manualSearchQuery.value = ''
  savePageState()
  restoreManualSelectedRecord()
}

function backManualStreamerList() {
  clearPageState('manual')
}

async function loadLiveVideos() {
  manualVideosLoading.value = true
  manualStreamersLoading.value = true
  manualVideoList.value = []
  try {
    const liveRes = await liveApi.getRecordHistory({ page_size: 200 })
    const records = liveRes?.data?.data || liveRes?.data || []
    manualVideoList.value = records
      .filter(r => (r.file_path || r.converted_path) && (r.status === 'completed' || r.status === 'stopped'))
      .map(r => ({
        id: r.id,
        title: `录制 ${r.start_time ? new Date(r.start_time).toLocaleString() : ''}`,
        filename: (r.converted_path || r.file_path)?.split('/').pop(),
        file_path: r.converted ? (r.converted_path || r.file_path) : (r.file_path || r.converted_path),
        duration: r.duration || 0,
        platform: r.platform || 'live',
        source: 'live',
        created_at: r.start_time,
        start_time: r.start_time,
        status: r.status,
        statusRaw: r.status,
        subscription_id: r.subscription_id,
        anchor_name: r.anchor_name,
        avatar_url: r.avatar_url || '',
        file_size: r.file_size,
        has_danmu_file: !!r.has_danmu_file,
        has_manual_clips: !!r.has_manual_clips,
        manual_clip_count: Number(r.manual_clip_count || 0),
      }))
  } catch (e) {
    console.error('加载录制视频失败', e)
    manualVideoList.value = []
  } finally {
    manualVideosLoading.value = false
    manualStreamersLoading.value = false
  }
}

async function loadDownloadVideos() {
  manualVideosLoading.value = true
  manualVideoList.value = []
  try {
    const statusParam = manualDownloadFilter.value === 'all' ? undefined : manualDownloadFilter.value
    const platformParam = manualDownloadPlatform.value === 'all' ? undefined : manualDownloadPlatform.value

    const params = {
      limit: manualPageSize.value,
      offset: (manualPage.value - 1) * manualPageSize.value,
    }
    if (statusParam) params.status = statusParam
    if (platformParam) params.platform = platformParam
    if (manualDownloadAuthorId.value) params.subscription_id = manualDownloadAuthorId.value

    const taskRes = await tasksApi.getTasks(params)
    const tasks = taskRes?.tasks || []
    manualTotalItems.value = taskRes?.total || tasks.length
    manualTotalPages.value = Math.max(1, Math.ceil(manualTotalItems.value / manualPageSize.value))

    manualVideoList.value = tasks
      .filter(t => t.filename)
      .map(t => ({
        id: t.id,
        title: t.title || (t.filename ? t.filename.replace(/\.mp4$/i,'').split('/').pop() : t.url || "未知任务"),
        filename: t.filename,
        file_path: t.filename ? `/app/downloads/${t.filename.replace(/^\/+/, '')}` : '',
        duration: t.status === 'COMPLETED' ? 0 : 0,
        platform: t.source || t.author_info?.platform || 'download',
        source: 'download',
        created_at: t.created_at,
        author: t.author_info?.nickname,
        status: t.status,
        statusRaw: t.status,
      }))
    // 异步加载缩略图
    manualThumbnailCache.value = {}
    for (const t of tasks) {
      if (t.status === 'COMPLETED') loadManualThumbnail(t).catch(() => {})
    }
  } catch (e) {
    console.error('加载下载视频失败', e)
    manualVideoList.value = []
  } finally {
    manualVideosLoading.value = false
  }
}

function onManualDateFilterChange() {
  // 选择「指定日期」时自动填充当天
  if (manualDateFilterMode.value === 'day' && !manualDateFilterDay.value) {
    manualDateFilterDay.value = toDateKey(new Date())
  }
}

// ===== 从 manualVideoList 派生博主列表 =====
const manualStreamerList = computed(() => {
  const map = {}
  for (const r of manualVideoList.value) {
    if (!r.subscription_id) continue
    if (!map[r.subscription_id]) {
      map[r.subscription_id] = {
        id: r.subscription_id,
        anchor_name: r.anchor_name || '未知主播',
        platform: r.platform || 'unknown',
        avatar_url: r.avatar_url || '',
        record_count: 0,
        latest_start_time: null,
      }
    }
    map[r.subscription_id].record_count++
    const st = r.start_time || r.created_at
    if (st && (!map[r.subscription_id].latest_start_time || new Date(st) > new Date(map[r.subscription_id].latest_start_time))) {
      map[r.subscription_id].latest_start_time = st
    }
  }
  return Object.values(map).sort((a, b) => (b.record_count || 0) - (a.record_count || 0))
})

const filteredManualStreamers = computed(() => {
  const q = (manualStreamerSearch.value || '').trim().toLowerCase()
  return manualStreamerList.value.filter(s => {
    if (manualStreamerPlatform.value !== 'all' && s.platform !== manualStreamerPlatform.value) return false
    if (!q) return true
    return (s.anchor_name || '').toLowerCase().includes(q)
  })
})

// ===== 选中博主后的录制列表 =====
const manualStreamerRecords = computed(() => {
  if (!manualStreamerId.value) return []
  return manualVideoList.value.filter(r => r.subscription_id === manualStreamerId.value)
})

const filteredManualStreamerRecords = computed(() => {
  let list = manualStreamerRecords.value.filter(r => r.file_path)
  const mode = manualDateFilterMode.value
  const q = (manualSearchQuery.value || '').trim().toLowerCase()

  // 日期筛选
  if (mode === 'today') {
    const today = toDateKey(new Date())
    list = list.filter(r => r.start_time && toDateKey(r.start_time) === today)
  } else if (mode === 'last7') {
    list = list.filter(r => r.start_time && isWithinRecentDays(r.start_time, 7))
  } else if (mode === 'last30') {
    list = list.filter(r => r.start_time && isWithinRecentDays(r.start_time, 30))
  } else if (mode === 'day' && manualDateFilterDay.value) {
    list = list.filter(r => r.start_time && toDateKey(r.start_time) === manualDateFilterDay.value)
  }

  // 关键词搜索
  if (q) {
    list = list.filter(r =>
      (r.filename || '').toLowerCase().includes(q) ||
      (r.anchor_name || '').toLowerCase().includes(q)
    )
  }

  return list.sort((a, b) => new Date(b.start_time || 0).getTime() - new Date(a.start_time || 0).getTime())
})

// ===== 下载视频搜索（下载来源） =====
const filteredManualVideos = computed(() => {
  if (manualSourceType.value !== 'download') return []
  let list = manualVideoList.value
  const q = (manualSearchQuery.value || '').trim().toLowerCase()
  if (q) {
    list = list.filter(item =>
      (item.title || '').toLowerCase().includes(q) ||
      (item.filename || '').toLowerCase().includes(q) ||
      (item.author || '').toLowerCase().includes(q) ||
      (item.platform || '').toLowerCase().includes(q)
    )
  }
  return list
})

function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '--'
  const s = Math.floor(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

function selectManualRecord(item) {
  manualSelectedRecordId.value = item.id
  manualSelectedVideo.value = item
  showRecordsSidebarDrawer.value = false
  savePageState()
  loadManualClips(item.id)
}

function restoreManualSelectedRecord() {
  if (!manualStreamerId.value) return
  const restoreId = pendingRestoreManualRecordId.value
  const list = filteredManualStreamerRecords.value.length > 0
    ? filteredManualStreamerRecords.value
    : manualStreamerRecords.value
  const record = (restoreId && list.find(r => String(r.id) === restoreId)) || list[0]
  if (!record) return
  pendingRestoreManualRecordId.value = ''
  manualSelectedRecordId.value = record.id
  manualSelectedVideo.value = record
  loadManualClips(record.id)
  savePageState()
}

function openManualPreview(item) {
  if (!item || !item.file_path) {
    error('无法预览：文件路径无效')
    return
  }

  const isTs = /\.ts$/i.test(item.file_path)
  if (isTs) {
    dialog.confirm({
      title: 'TS 格式建议转码',
      message: '当前录制为 TS 格式，直接切片可能出现预览卡顿或画质异常。<br><br>建议先在直播录制页转码为 MP4 后再回来切片。',
      confirmText: '去转码',
      cancelText: '知道了',
    }).then(go => { if (go) router.push(`/live-record`) })
    return
  }
  openManualPreviewInner(item)
}

function openManualPreviewInner(item) {
  manualSelectedVideo.value = item
  manualDanmuRecordId.value = item.has_danmu_file ? (item.id || '') : ''
  if (manualDanmuRecordId.value) {
    resetPreviewDanmuState()
    loadDanmuRange(0, Math.min(30, item.duration || 30))
  }

  // 构建视频流 URL
  const filePath = String(item.file_path || '').replace(/\\/g, '/')
  const marker = '/app/downloads/'
  const idx = filePath.indexOf(marker)
  let relative = idx >= 0 ? filePath.slice(idx + marker.length) : filePath.replace(/^\/+/, '')
  if (relative.startsWith('downloads/')) relative = relative.slice('downloads/'.length)
  if (!relative) {
    error('无法预览：路径解析失败')
    return
  }

  const token = localStorage.getItem('token')
  let url = `/api/video/stream?filename=${encodeDownloadPath(relative)}&quality=original`
  if (token) url += `&token=${encodeURIComponent(token)}`

  // MP4 用浏览器原生 seek；TS 需后端起播
  if (/\.ts$/i.test(item.file_path)) {
    url += `&start=0`
  }

  originalDuration.value = item.duration || 0
  adjustedStartSec.value = 0
  adjustedEndSec.value = Math.min(30, originalDuration.value || 30) || 30
  recordStreamUrl.value = url
  previewVisible.value = true
}

/** 剪辑编辑器时间范围变化（同步本地状态 + 加载弹幕） */
function onClipEditorTimeChange({ startSec, endSec }) {
  adjustedStartSec.value = startSec
  adjustedEndSec.value = endSec
  const hasDanmu = (previewSegment.value && selectedRecordId.value) || manualDanmuRecordId.value
  if (hasDanmu) {
    debouncedLoadDanmu()
  }
}
function onClipEditorSeek(sec) {
  // TS 文件需要重建 URL 让后端 ffmpeg 从新位置起播
  const record = selectedRecord.value
  if (record) {
    const url = buildRecordStreamUrl(record, sec)
    if (url) recordStreamUrl.value = url
  }
}




// ============ 手动切片管理 ============

async function loadManualClips(recordId) {
  if (!recordId) return
  manualClipsLoading.value = true
  try {
    const res = await liveHighlightsApi.getManualClips(recordId)
    manualClips.value = res?.clips || []
    patchManualRecordClipState(recordId, manualClips.value.length)
  } catch (e) {
    manualClips.value = []
    patchManualRecordClipState(recordId, 0)
  } finally {
    manualClipsLoading.value = false
  }
}

async function confirmCleanupManualRecord() {
  if (!manualSelectedRecordId.value || manualClips.value.length === 0) return
  const ok = await dialog.confirm({
    title: '清理本场手动切片',
    message: '确定删除本条录制的全部手动切片吗？',
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!ok) return
  try {
    await liveHighlightsApi.cleanupManualClips(manualSelectedRecordId.value)
    manualClips.value = []
    patchManualRecordClipState(manualSelectedRecordId.value, 0)
    success('已清理本场手动切片')
  } catch (e) {
    error('清理失败: ' + (e?.response?.data?.detail || e.message))
  }
}

async function confirmCleanupManualStreamer() {
  if (!manualStreamerId.value) return
  const subId = manualStreamerId.value
  const ok = await dialog.confirm({
    title: '清理博主全部手动切片',
    message: '确定删除该博主所有录制的手动切片吗？<br><br><strong>此操作不可恢复！</strong>',
    confirmText: '删除全部',
    cancelText: '取消',
  })
  if (!ok) return
  try {
    await liveHighlightsApi.cleanupStreamerManualClips(subId)
    manualClips.value = []
    clearManualStreamerClipState(subId)
    success('已清理该博主全部手动切片')
  } catch (e) {
    error('清理失败: ' + (e?.response?.data?.detail || e.message))
  }
}

function playManualClip(clip) {
  if (!clip?.path) return
  window.open(`/api/video/stream?filename=${encodeURIComponent(clip.path.replace(/^\/app\/downloads\//, ''))}&quality=original&token=${encodeURIComponent(localStorage.getItem('token') || '')}`, '_blank')
}

async function downloadManualClip(clip) {
  if (!manualSelectedRecordId.value || !clip?.name || manualBundling.value) return
  manualBundling.value = true
  try {
    const blob = await liveHighlightsApi.downloadManualClip(manualSelectedRecordId.value, clip.name)
    if (!(blob instanceof Blob)) throw new Error('未获取到有效的切片文件')
    const blobUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = clip.name
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)
    success('切片下载开始')
  } catch (e) {
    error('下载失败: ' + (e?.response?.data?.detail || e.message))
  } finally {
    manualBundling.value = false
  }
}

async function downloadManualClipsBundle() {
  if (!manualSelectedRecordId.value || manualClips.value.length === 0 || manualBundling.value) return
  manualBundling.value = true
  try {
    const blob = await liveHighlightsApi.downloadManualClipsBundle(manualSelectedRecordId.value, {
      clip_names: manualClips.value.map(clip => clip.name).filter(Boolean)
    })
    if (!(blob instanceof Blob)) throw new Error('未获取到有效的资源包')
    const filename = `manual_clips_${manualSelectedRecordId.value}_${Math.floor(Date.now() / 1000)}.zip`
    const blobUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)
    success(`资源包下载开始：${filename}`)
  } catch (e) {
    error('批量导出失败: ' + (e?.response?.data?.detail || e.message))
  } finally {
    manualBundling.value = false
  }
}

async function deleteManualClip(clip) {
  if (!manualSelectedRecordId.value || !clip?.name) return
  const ok = await dialog.confirm({
    title: '删除手动切片',
    message: `确定删除 <strong>${clip.name}</strong> 吗？`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!ok) return
  try {
    await liveHighlightsApi.deleteManualClip(manualSelectedRecordId.value, clip.name)
    await loadManualClips(manualSelectedRecordId.value)
    success('已删除手动切片')
  } catch (e) {
    error('删除失败: ' + (e?.response?.data?.detail || e.message))
  }
}

/** 剪辑编辑器导出回调（从 ClipEditor 组件接收 start/endSec） */
async function handleClipEditorExport({ startSec, endSec }) {
  if (activeTab.value === 'manual' && manualSelectedVideo.value) {
    // 直播录制手动切片
    const video = manualSelectedVideo.value
    if (!video.file_path) { error('切片失败：文件路径无效'); return }
    exportingSingle.value = true
    try {
      const res = await liveHighlightsApi.manualExport({
        file_path: video.file_path, start_sec: startSec, end_sec: endSec, overwrite: true,
      })
      if (res?.success && res?.clip_path) {
        closePreview()
        if (video.source === 'live') {
          await loadManualClips(video.id)
        }
        success('切片完成')
      }
      else { error(res?.clip_error || '切片导出失败') }
    } catch (e) { error(`切片失败: ${e?.response?.data?.detail || e.message}`) }
    finally { exportingSingle.value = false }
  } else if (previewSegment.value && selectedRecordId.value) {
    // AI 模式导出
    exportingSingle.value = true
    try {
      await liveHighlightsApi.export(selectedRecordId.value, {
        segment_ids: [previewSegment.value.id],
        custom_ranges: [{ segment_id: previewSegment.value.id, start_sec: startSec, end_sec: endSec }],
        overwrite: true,
      })
      closePreview()
      await loadResult()
      success('切片完成')
    } catch (e) { error(`切片失败: ${e?.response?.data?.detail || e.message}`) }
    finally { exportingSingle.value = false }
  }
}

// 监听 tab 切换，进入手动模式时自动加载视频列表
watch(activeTab, async (tab) => {
  if (tab === 'manual' && manualVideoList.value.length === 0) {
    if (manualSourceType.value === 'live') {
      loadLiveVideos()
    }
  }
  if (!restoringPageState.value) {
    await restoreStoredTabState(tab)
  }
  savePageState()
})

// 监听来源切换时重置下载分页
watch(manualSourceType, () => {
  manualPage.value = 1
})

function resetAdjustedRange() {
  if (activeTab.value === 'manual' && manualSelectedVideo.value) {
    adjustedStartSec.value = 0
    adjustedEndSec.value = Math.min(30, originalDuration.value || 30)
    _seekTo(0)
    return
  }
  if (!previewSegment.value) return
  adjustedStartSec.value = Number(previewSegment.value.start_sec || 0)
  adjustedEndSec.value = Number(previewSegment.value.end_sec || adjustedStartSec.value + 10)
  _seekTo(adjustedStartSec.value)
  void loadDanmuRange(adjustedStartSec.value, adjustedEndSec.value)
}

async function confirmSlice() {
  const seg = previewSegment.value
  if (!seg || !selectedRecordId.value) return
  exportingSingle.value = true
  try {
    await liveHighlightsApi.export(selectedRecordId.value, {
      segment_ids: [seg.id],
      custom_ranges: [{
        segment_id: seg.id,
        start_sec: adjustedStartSec.value,
        end_sec: adjustedEndSec.value
      }],
      overwrite: true
    })
    // 关闭编辑器（同时让 success toast 可见）
    closePreview()
    // 重新加载分析结果，更新片段列表的 clip_path
    await loadResult()
    success('切片完成')
  } catch (e) {
    error(`切片失败: ${e?.response?.data?.detail || e.message}`)
  } finally {
    exportingSingle.value = false
  }
}

function closePreview() {
  previewVisible.value = false
  recordStreamUrl.value = ''
  previewSegment.value = null
  manualSelectedVideo.value = null
  manualDanmuRecordId.value = ''
  originalDuration.value = 0
}

// 全屏编辑器 Escape 关闭
watch(previewVisible, (visible) => {
  const handler = (e) => {
    if (e.key === 'Escape' && previewVisible.value) closePreview()
  }
  if (visible) {
    document.addEventListener('keydown', handler)
    // 清理上一次的 handler 避免重复注册
    closePreview._keyHandler = handler
  } else if (closePreview._keyHandler) {
    document.removeEventListener('keydown', closePreview._keyHandler)
    closePreview._keyHandler = null
  }
})

function handlePreviewError() {
  error('预览播放失败，请确认录制文件仍存在且可访问')
}

async function checkLicense(force = false) {
  if (!hadCachedLicenseOnBoot) {
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
    const isLicensed = !!res?.is_licensed
    const remainingDays = Number(res?.remaining_days)
    const isLifetime =
      !!res?.is_lifetime ||
      remainingDays === -1 ||
      (Number.isFinite(remainingDays) && remainingDays > 3650)

    hasGeneralLicense.value = isLicensed
    lifetimeEligible.value = isLifetime
    licenseValid.value = isLicensed && isLifetime
    localStorage.setItem('license_status', String(isLicensed))
    localStorage.setItem('live_highlights_lifetime_ok', String(isLifetime))

    if (force && licenseValid.value) {
      success('授权状态已刷新')
    }
  } catch (e) {
    if (!hadCachedLicenseOnBoot) {
      hasGeneralLicense.value = false
      lifetimeEligible.value = false
      licenseValid.value = false
    }
    console.error('License check failed:', e)
  } finally {
    checkingLicense.value = false
    if (licenseValid.value) {
      await loadStreamers()
      await restorePageState()
      connectRecordStatusSocket()
    } else {
      isLoadingStreamers.value = false
      recordStatusSocketEnabled.value = false
      closeRecordStatusSocket()
      stopAnalyzeTracking()
      resetResultPanel()
    }
  }
}

async function loadModelSourceSetting() {
  try {
    const cfg = await aiConfigApi.getConfig()
    
    // 1. 加载旧版兼容配置
    const source = String(cfg?.llm_highlights_model_source || 'cloud').toLowerCase()
    settingsModelSource.value = ['cloud', 'deepseek', 'compat', 'local'].includes(source) ? source : 'cloud'

    // 2. 加载新架构 L1/L2 全局默认配置（切片页只读展示）
    const l1Provider = normalizeProviderForDisplay(cfg?.llm_l1_scout_provider || 'none')
    form.value.l1_scout_config.provider = l1Provider
    form.value.l1_scout_config.model = modelNameFromProviderConfig(
      cfg,
      l1Provider,
      String(cfg?.llm_l1_scout_model || '').trim()
    )
    form.value.l1_scout_config.max_concurrency = clampModelConcurrency(
      cfg?.llm_l1_scout_max_concurrency,
      form.value.l1_scout_config?.max_concurrency || 4
    )

    const l2Provider = normalizeProviderForDisplay(cfg?.llm_l2_editor_provider || 'none')
    form.value.l2_editor_config.provider = l2Provider
    form.value.l2_editor_config.model = modelNameFromProviderConfig(
      cfg,
      l2Provider,
      String(cfg?.llm_l2_editor_model || '').trim()
    )
    form.value.l2_editor_config.max_concurrency = clampModelConcurrency(
      cfg?.llm_l2_editor_max_concurrency,
      form.value.l2_editor_config?.max_concurrency || 4
    )
  } catch (_) {
    settingsModelSource.value = 'cloud'
    form.value.l1_scout_config.provider = 'none'
    form.value.l1_scout_config.model = ''
    form.value.l2_editor_config.provider = 'none'
    form.value.l2_editor_config.model = ''
  }
}

function handleLicenseDenied(err) {
  if (err?.response?.status !== 403) return false
  const detail = String(err?.response?.data?.detail || '')
  if (detail.includes('永久高级版')) {
    hasGeneralLicense.value = true
    lifetimeEligible.value = false
    localStorage.setItem('live_highlights_lifetime_ok', 'false')
  } else {
    hasGeneralLicense.value = false
    lifetimeEligible.value = false
    localStorage.setItem('license_status', 'false')
    localStorage.setItem('live_highlights_lifetime_ok', 'false')
  }
  licenseValid.value = false
  recordStatusSocketEnabled.value = false
  closeRecordStatusSocket()
  stopAnalyzeTracking()
  return true
}

async function loadStreamers() {
  isLoadingStreamers.value = true
  try {
    const resp = await liveHighlightsApi.getEligibleStreamers()
    streamerListRaw.value = resp?.data || []
  } catch (e) {
    if (handleLicenseDenied(e)) return
    error(`加载博主列表失败: ${e?.response?.data?.detail || e.message}`)
  } finally {
    isLoadingStreamers.value = false
  }
}

async function loadRecords(subscriptionId) {
  if (!subscriptionId) return
  isLoadingRecords.value = true
  try {
    const resp = await liveHighlightsApi.getStreamerEligibleRecords(subscriptionId)
    allRecords.value = (resp?.data || []).map(r => ({
      ...r,
      subscription_id: subscriptionId,
      platform: selectedStreamer.value?.platform
    }))
  } catch (e) {
    error(`加载录制记录失败: ${e?.response?.data?.detail || e.message}`)
  } finally {
    isLoadingRecords.value = false
  }
}

function patchRecordHighlightState(recordId, updates = {}) {
  const rid = String(recordId || '')
  if (!rid) return
  const idx = allRecords.value.findIndex(r => String(r?.id || '') === rid)
  if (idx < 0) return
  allRecords.value[idx] = {
    ...allRecords.value[idx],
    ...updates
  }
}

function patchManualRecordClipState(recordId, clipCount) {
  const rid = String(recordId || '')
  if (!rid) return
  const count = Math.max(0, Number(clipCount || 0))
  const updates = {
    has_manual_clips: count > 0,
    manual_clip_count: count
  }

  const idx = manualVideoList.value.findIndex(r => String(r?.id || '') === rid)
  if (idx >= 0) {
    manualVideoList.value[idx] = {
      ...manualVideoList.value[idx],
      ...updates
    }
  }

  if (String(manualSelectedVideo.value?.id || '') === rid) {
    manualSelectedVideo.value = {
      ...manualSelectedVideo.value,
      ...updates
    }
  }
}

function clearManualStreamerClipState(subscriptionId) {
  const sid = String(subscriptionId || '')
  if (!sid) return
  manualVideoList.value = manualVideoList.value.map(record => {
    if (String(record?.subscription_id || '') !== sid) return record
    return {
      ...record,
      has_manual_clips: false,
      manual_clip_count: 0
    }
  })
  if (String(manualSelectedVideo.value?.subscription_id || '') === sid) {
    manualSelectedVideo.value = {
      ...manualSelectedVideo.value,
      has_manual_clips: false,
      manual_clip_count: 0
    }
  }
}

function handleRecordStatusSocketMessage(payload) {
  if (!payload || typeof payload !== 'object') return
  if (payload.type === 'hello') return
  if (payload.type !== 'highlights_record_status_update') return

  const recordId = String(payload.record_id || '')
  if (!recordId) return

  const updates = {}
  if (Object.prototype.hasOwnProperty.call(payload, 'highlights_status')) {
    updates.highlights_status = String(payload.highlights_status || '')
  }
  if (Object.prototype.hasOwnProperty.call(payload, 'has_highlights_analysis')) {
    updates.has_highlights_analysis = !!payload.has_highlights_analysis
  }
  patchRecordHighlightState(recordId, updates)
}

function closeRecordStatusSocket() {
  if (recordStatusReconnectTimer.value) {
    clearTimeout(recordStatusReconnectTimer.value)
    recordStatusReconnectTimer.value = null
  }
  if (recordStatusPingTimer.value) {
    clearInterval(recordStatusPingTimer.value)
    recordStatusPingTimer.value = null
  }
  const ws = recordStatusSocket.value
  recordStatusSocket.value = null
  if (ws) {
    try {
      ws.close()
    } catch (_) {
      // noop
    }
  }
}

function connectRecordStatusSocket() {
  if (!licenseValid.value) return
  recordStatusSocketEnabled.value = true
  if (recordStatusSocket.value) return

  const wsUrl = buildAuthedWsUrl(`/api/ws/subscribe/${encodeURIComponent(RECORD_STATUS_CHANNEL)}/progress`)
  const ws = new WebSocket(wsUrl)
  ws.onopen = () => {
    if (recordStatusReconnectTimer.value) {
      clearTimeout(recordStatusReconnectTimer.value)
      recordStatusReconnectTimer.value = null
    }
    recordStatusPingTimer.value = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping')
    }, 20000)
  }
  ws.onmessage = event => {
    if (event.data === 'pong') return
    try {
      const payload = JSON.parse(event.data)
      handleRecordStatusSocketMessage(payload)
    } catch (_) {
      // noop
    }
  }
  ws.onclose = () => {
    if (recordStatusPingTimer.value) {
      clearInterval(recordStatusPingTimer.value)
      recordStatusPingTimer.value = null
    }
    recordStatusSocket.value = null
    if (!recordStatusSocketEnabled.value || !licenseValid.value) return
    if (recordStatusReconnectTimer.value) {
      clearTimeout(recordStatusReconnectTimer.value)
    }
    recordStatusReconnectTimer.value = setTimeout(() => {
      connectRecordStatusSocket()
    }, 3000)
  }
  recordStatusSocket.value = ws
}

async function selectStreamer(streamer) {
  if (selectedStreamerId.value === streamer.id) return
  selectedStreamerId.value = streamer.id
  allRecords.value = [] // 切换博主时先清空旧记录，触发骨架屏
  await loadRecords(streamer.id)
}

function goBackToStreamerList() {
  stopAnalyzeTracking()
  clearPageState('ai')
  resetResultPanel()
}

function selectRecord(record) {
  selectedRecordId.value = record.id
  showRecordsSidebarDrawer.value = false
  savePageState()
}

watch(selectedStreamerId, async (sid) => {
  if (!sid) return
  savePageState()
  applyDefaultRecordFilterFallback()
  const restoreId = pendingRestoreAiRecordId.value
  const restored = restoreId
    ? selectedStreamerRecordsFiltered.value.find(r => String(r.id) === restoreId)
      || selectedStreamerRecords.value.find(r => String(r.id) === restoreId)
    : null
  const first = selectedStreamerRecordsFiltered.value[0]
  selectedRecordId.value = restored?.id || first?.id || ''
  pendingRestoreAiRecordId.value = ''
  resetResultPanel()
  if (selectedRecordId.value) {
    await loadResult()
  }
})

watch(recordDateFilterMode, mode => {
  if (mode !== 'day') return
  if (!recordDateFilterDay.value) {
    recordDateFilterDay.value = toDateKey(new Date())
  }
})

watch([manualDateFilterMode, manualDateFilterDay], () => {
  savePageState()
  if (manualSelectedRecordId.value) {
    const hasCurrent = filteredManualStreamerRecords.value.some(r => String(r.id) === String(manualSelectedRecordId.value))
    if (!hasCurrent) restoreManualSelectedRecord()
  }
})

watch(selectedStreamerRecordsFiltered, list => {
  applyDefaultRecordFilterFallback()
  if (!selectedStreamerId.value) return
  const hasCurrent = list.some(r => String(r.id) === String(selectedRecordId.value || ''))
  if (hasCurrent) return
  selectedRecordId.value = list[0]?.id || ''
}, { deep: false })

watch(selectedRecordId, async (rid, oldRid) => {
  if (!rid || rid === oldRid) return
  savePageState()
  stopAnalyzeTracking()
  resetResultPanel()
  await loadResult()
  await recoverAnalyzeTask(rid)
})

watch(
  () => [
    form.value.highlight_type,
    form.value.max_candidates,
    form.value.seed,
    form.value.randomness,
    form.value.danmu_delay_compensation_seconds,
    form.value.stream_type,
    form.value.story_enabled,
    form.value.asr_enabled,
    form.value.asr_model,
    form.value.analysis_strategy,
    form.value.l1_scout_config?.max_concurrency,
    form.value.l2_editor_config?.max_concurrency,
    showAdvancedModelOptions.value
  ],
  () => {
    saveAnalyzePreference()
  }
)

async function loadResult() {
  if (!selectedRecordId.value) return
  loadingResult.value = true
  try {
    const resp = await liveHighlightsApi.getResult(selectedRecordId.value)
    const data = resp || {}
    segments.value = data.data || []
    analyzedAt.value = data.analyzed_at || ''
    const incomingStreamType = String(data.stream_type || '').trim()
    if (incomingStreamType && !String(form.value.stream_type || '').trim()) {
      form.value.stream_type = incomingStreamType
    }
    selectedSegmentIds.value = []
  } catch (e) {
    if (handleLicenseDenied(e)) return
    error(`读取分析结果失败: ${e?.response?.data?.detail || e.message}`)
  } finally {
    loadingResult.value = false
  }
}

async function runAnalyze() {
  if (!selectedRecordId.value) return
  const strategy = String(form.value.analysis_strategy || 'llm_required')
  if (strategy === 'llm_required') {
    const validated = await validateRequiredModelReady()
    if (!validated) return
  }
  analyzing.value = true
  try {
    connectAnalyzeSocket(selectedRecordId.value)
    const payload = {
      ...form.value,
      mode: 'offline',
      analysis_strategy: strategy,
      model_source: settingsModelSource.value,
      story_enabled: !!form.value.story_enabled,
      l1_scout_config: {
        ...(form.value.l1_scout_config || {}),
        provider: normalizeProviderForAnalyzeRequest(form.value.l1_scout_config?.provider),
        max_concurrency: clampModelConcurrency(form.value.l1_scout_config?.max_concurrency, 4)
      },
      l2_editor_config: {
        ...(form.value.l2_editor_config || {}),
        provider: normalizeProviderForAnalyzeRequest(form.value.l2_editor_config?.provider),
        max_concurrency: clampModelConcurrency(form.value.l2_editor_config?.max_concurrency, 4)
      }
    }
    const submit = await liveHighlightsApi.analyzeAsync(selectedRecordId.value, {
      ...payload
    })
    analyzeTaskId.value = submit?.task_id || ''
    analyzeStatus.value = String(submit?.status || 'queued')
    analyzeProgress.value = 0
    analyzeMessage.value = '任务已提交，等待执行'
    patchRecordHighlightState(selectedRecordId.value, { highlights_status: 'queued' })
    startAnalyzePoll(selectedRecordId.value)
    success('分析任务已提交，后台处理中（刷新页面会自动恢复进度）')
  } catch (e) {
    if (handleLicenseDenied(e)) return
    stopAnalyzeTracking()
    error(`分析失败: ${e?.response?.data?.detail || e.message}`)
  }
}

async function handleAnalyzeAction() {
  if (analyzing.value) {
    await terminateAnalyze()
    return
  }
  await runAnalyze()
}

async function terminateAnalyze() {
  if (!selectedRecordId.value || terminatingAnalyze.value) return
  const titleTime = selectedRecord.value ? formatTime(selectedRecord.value.start_time) : selectedRecordId.value
  const confirmed = await dialog.confirm({
    title: '终止本场分析',
    type: 'warning',
    confirmText: '终止并清理',
    cancelText: '继续分析',
    message: `将终止当前高光分析任务，并清理本场已生成的分析产物。<br><br><strong>录制时间：</strong>${titleTime}<br><strong>范围：</strong>highlights.v1.json、task_status.v1.json、clips、analysis、subtitles`
  })
  if (!confirmed) return

  terminatingAnalyze.value = true
  try {
    await liveHighlightsApi.cancelAnalyze(selectedRecordId.value)
    patchRecordHighlightState(selectedRecordId.value, {
      highlights_status: '',
      has_highlights_analysis: false
    })
    segments.value = []
    analyzedAt.value = ''
    stopAnalyzeTracking()
    success('已终止分析并清理本场产物')
  } catch (e) {
    if (handleLicenseDenied(e)) return
    error(`终止分析失败: ${e?.response?.data?.detail || e.message}`)
  } finally {
    terminatingAnalyze.value = false
    analyzeButtonHover.value = false
  }
}

async function validateRequiredModelReady() {
  let cfg = null
  try {
    cfg = await aiConfigApi.getConfig()
  } catch (_) {
    cfg = null
  }

  const source = String(settingsModelSource.value || 'cloud').toLowerCase()
  const providerName = source === 'local'
    ? 'Ollama'
    : source === 'compat'
      ? '兼容平台'
      : (source === 'deepseek' ? 'DeepSeek' : 'MiniMax')

  const isEnabled = source === 'local'
    ? !!cfg?.llm_ollama_enabled
    : source === 'compat'
      ? !!cfg?.llm_compat_enabled
      : source === 'deepseek'
        ? !!cfg?.llm_deepseek_enabled
        : !!cfg?.llm_minimax_enabled
  const baseUrl = String(
    source === 'local'
      ? (cfg?.llm_ollama_base_url || '')
      : source === 'compat'
        ? (cfg?.llm_compat_base_url || '')
        : source === 'deepseek'
          ? (cfg?.llm_deepseek_base_url || '')
          : (cfg?.llm_minimax_base_url || '')
  ).trim()
  const model = String(
    source === 'local'
      ? (cfg?.llm_ollama_model || '')
      : source === 'compat'
        ? (cfg?.llm_compat_model || '')
        : source === 'deepseek'
          ? (cfg?.llm_deepseek_model || '')
          : (cfg?.llm_minimax_model || '')
  ).trim()
  const apiKey = String(
    source === 'local'
      ? (cfg?.llm_ollama_api_key || '')
      : source === 'compat'
        ? (cfg?.llm_compat_api_key || '')
        : source === 'deepseek'
          ? (cfg?.llm_deepseek_api_key || '')
          : (cfg?.llm_minimax_api_key || '')
  ).trim()

  let reason = ''
  if (!isEnabled) {
    reason = `${providerName} 尚未启用`
  } else if (!baseUrl) {
    reason = `${providerName} Base URL 为空`
  } else if (!model) {
    reason = `${providerName} 模型名为空`
  } else if (source !== 'local' && !apiKey) {
    reason = `${providerName} API Key 为空`
  }

  if (!reason) return true

  const goSettings = await dialog.confirm({
    title: '模型不可用',
    type: 'warning',
    confirmText: '去设置页',
    cancelText: '取消',
    message: `当前选择的是“大模型分析模式（严格）”，但检测到配置不可用：<br><strong>${reason}</strong><br><br>请先配置并保存可用模型后再发起分析。`
  })
  if (goSettings) {
    router.push('/settings?tab=ai-model')
  }
  return false
}

async function exportSelected() {
  if (!selectedRecordId.value || selectedSegmentIds.value.length === 0) return
  exporting.value = true
  try {
    const resp = await liveHighlightsApi.export(selectedRecordId.value, {
      segment_ids: selectedSegmentIds.value,
      overwrite: false,
      include_story_assets: true
    })
    const count = resp?.exported_count || 0
    const hasStory = !!(resp?.storyline_json_path || resp?.subtitles_srt_path)
    success(`切片完成，共 ${count} 段${hasStory ? '，已生成剧情素材' : ''}`)
    await loadResult()
  } catch (e) {
    if (handleLicenseDenied(e)) return
    error(`切片失败: ${e?.response?.data?.detail || e.message}`)
  } finally {
    exporting.value = false
  }
}

function parseFilenameFromDisposition(contentDisposition) {
  const raw = String(contentDisposition || '')
  if (!raw) return ''
  const utf8Match = raw.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch (_) {
      return utf8Match[1]
    }
  }
  const plainMatch = raw.match(/filename="?([^";]+)"?/i)
  if (plainMatch && plainMatch[1]) return plainMatch[1]
  return ''
}

async function downloadSegmentBundle(segment) {
  if (!selectedRecordId.value || !segment?.id) return
  bundling.value = true
  try {
    const blob = await liveHighlightsApi.downloadBundle(selectedRecordId.value, {
      segment_ids: [segment.id],
      overwrite: true,
      include_story_assets: true
    })
    if (!(blob instanceof Blob)) throw new Error('未获取到有效的二进制数据包')
    const filename = `highlight_${segment.id.slice(0, 8)}_${Math.floor(Date.now() / 1000)}.zip`
    const blobUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)
    success('资源包下载开始')
  } catch (e) {
    error(`下载失败: ${e?.response?.data?.detail || e.message}`)
  } finally {
    bundling.value = false
  }
}

async function downloadBundle() {
  if (!selectedRecordId.value || selectedSegmentIds.value.length === 0) return
  bundling.value = true
  try {
    // 由于 client.js 中的拦截器直接返回了 response.data，
    // 所以这里的 resp 其实直接就是 Blob 对象。
    const blob = await liveHighlightsApi.downloadBundle(selectedRecordId.value, {
      segment_ids: selectedSegmentIds.value,
      overwrite: false,
      include_story_assets: true
    })

    if (!(blob instanceof Blob)) {
      throw new Error('未获取到有效的二进制数据包')
    }

    // 因为拦截器剥离了原始 response 容器，我们拿不到 headers 里的文件名，
    // 因此这里使用本地生成的默认名称。
    const filename = `highlights_bundle_${selectedRecordId.value}_${Math.floor(Date.now() / 1000)}.zip`
    
    const blobUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)

    success(`资源包下载开始：${filename}`)
    
    // 刷新列表以同步服务器上的切片路径状态
    setTimeout(() => {
      loadResult()
    }, 500)
  } catch (e) {
    if (handleLicenseDenied(e)) return
    let detail = e?.message || '未知错误'
    const data = e?.response?.data
    // 如果错误返回也是 Blob，尝试读取其中的错误信息
    if (data instanceof Blob) {
      try {
        const text = await data.text()
        const parsed = JSON.parse(text)
        detail = parsed?.detail || parsed?.message || detail
      } catch (_) {
        // noop
      }
    } else {
      detail = e?.response?.data?.detail || e?.response?.data?.message || detail
    }
    error(`下载失败: ${detail}`)
  } finally {
    bundling.value = false
  }
}

async function cleanupCurrentRecord() {
  if (!selectedRecordId.value || cleaning.value || cleaningStreamer.value) return

  const titleTime = selectedRecord.value ? formatTime(selectedRecord.value.start_time) : selectedRecordId.value
  const confirmed = await dialog.confirm({
    title: '确认清理本场切片',
    type: 'warning',
    confirmText: '确认清理',
    cancelText: '取消',
    message: `将清理当前录制记录的高光分析和导出产物。<br><br><strong>录制时间：</strong>${titleTime}<br><strong>范围：</strong>highlights.v1.json、task_status.v1.json、clips、analysis、subtitles`
  })
  if (!confirmed) return

  cleaning.value = true
  try {
    const resp = await liveHighlightsApi.cleanup(selectedRecordId.value)
    patchRecordHighlightState(selectedRecordId.value, {
      highlights_status: '',
      has_highlights_analysis: false
    })
    stopAnalyzeTracking()
    resetResultPanel()
    await loadResult()
    success(`清理完成：文件 ${resp?.removed_files || 0} 个，目录 ${resp?.removed_dirs || 0} 个，释放 ${formatBytes(resp?.freed_bytes || 0)}`)
  } catch (e) {
    if (handleLicenseDenied(e)) return
    error(`清理失败: ${e?.response?.data?.detail || e.message}`)
  } finally {
    cleaning.value = false
  }
}

async function cleanupCurrentStreamer() {
  if (!selectedStreamerId.value || cleaning.value || cleaningStreamer.value) return

  const streamerName = selectedStreamer.value?.anchor_name || '该博主'
  const total = selectedStreamerRecords.value.length
  const confirmed = await dialog.confirm({
    title: '确认清理该博主全部切片',
    type: 'warning',
    confirmText: '确认清理',
    cancelText: '取消',
    message: `将清理 <strong>${streamerName}</strong> 的全部录制记录高光分析与导出产物。<br><br><strong>涉及记录：</strong>${total} 条`
  })
  if (!confirmed) return

  cleaningStreamer.value = true
  try {
    const resp = await liveHighlightsApi.cleanupByStreamer(selectedStreamerId.value)
    for (const r of allRecords.value) {
      if (String(r.subscription_id || '') !== String(selectedStreamerId.value || '')) continue
      r.highlights_status = ''
      r.has_highlights_analysis = false
    }
    stopAnalyzeTracking()
    resetResultPanel()
    await loadResult()
    success(`批量清理完成：记录 ${resp?.cleaned_records || 0} 条，文件 ${resp?.removed_files || 0} 个，目录 ${resp?.removed_dirs || 0} 个，释放 ${formatBytes(resp?.freed_bytes || 0)}`)
  } catch (e) {
    if (handleLicenseDenied(e)) return
    error(`批量清理失败: ${e?.response?.data?.detail || e.message}`)
  } finally {
    cleaningStreamer.value = false
  }
}

onMounted(async () => {
  durationTicker.value = setInterval(() => {
    nowTickSec.value = Math.floor(Date.now() / 1000)
  }, 1000)
  restoreAnalyzePreference()
  await loadModelSourceSetting()
  await loadAsrModelStatus()
  restoreRecordFilterPreference()
  await checkLicense()
})

onActivated(async () => {
  // 页面被 keep-alive 缓存时，返回本页不会触发 onMounted，需要主动刷新模型来源配置。
  await loadModelSourceSetting()
  await loadAsrModelStatus()
})

onBeforeUnmount(() => {
  if (durationTicker.value) {
    clearInterval(durationTicker.value)
    durationTicker.value = null
  }
  if (seekUrlRebuildTimer) { clearTimeout(seekUrlRebuildTimer); seekUrlRebuildTimer = null }
  if (danmuLoadTimer) { clearTimeout(danmuLoadTimer); danmuLoadTimer = null }
  if (closePreview._keyHandler) {
    document.removeEventListener('keydown', closePreview._keyHandler)
    closePreview._keyHandler = null
  }
  recordStatusSocketEnabled.value = false
  closeRecordStatusSocket()
  stopAnalyzeTracking()
})
function randomizeSeed() {
  form.value.seed = Math.floor(Math.random() * 1000000)
}
</script>

<style scoped>
.live-highlights-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.page-content {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 授权提示 */
.license-alert {
  text-align: center;
  background: var(--color-bg-card);
  border: 2px dashed var(--color-error);
  border-radius: var(--radius-xl);
  padding: 2.5rem 3rem;
  margin: 2rem auto;
  width: min(980px, calc(100% - 32px));
  box-sizing: border-box;
}

.license-alert h2 {
  margin: 0 0 12px 0;
}

.license-alert > p {
  margin: 0 auto;
  max-width: 760px;
  line-height: 1.7;
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
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 28px;
  margin: 32px 0;
  text-align: left;
}

.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  color: var(--color-text-secondary);
  font-size: 15px;
  min-width: 0;
  line-height: 1.7;
}

.feature-item span {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}

.feature-item .icon {
  color: var(--color-success);
}

.card {
  background: var(--color-bg-card);
  border-radius: 12px;
  border: 1px solid var(--color-border-primary);
  padding: 16px;
}

.selection-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-orb {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ef6c24;
  border: 1px solid var(--color-border-primary);
  background: var(--color-bg-secondary);
}

h2 {
  margin: 0;
  font-size: 28px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.beta-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.2px;
  color: #ef6c24;
  border: 1px solid rgba(239, 108, 36, 0.28);
  background: rgba(239, 108, 36, 0.1);
}

.desc {
  margin: 8px 0 0;
  color: var(--color-text-secondary);
}

.header-right {
  width: 380px;
  max-width: 100%;
}

.search-input-wrapper {
  position: relative;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-tertiary);
}

.search-input {
  width: 100%;
  height: 42px;
  border-radius: 10px;
  border: 1px solid var(--color-border-primary);
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  padding: 0 12px 0 36px;
}

.platform-filters {
  margin-top: 16px;
  display: flex;
  gap: 10px;
}

.filter-tag {
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  border-radius: 999px;
  padding: 6px 16px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-tag:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-bg-hover);
}

.filter-tag.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
  box-shadow: 0 4px 10px var(--color-primary-light, rgba(230, 126, 34, 0.2));
}

.streamer-grid {
  margin-top: 20px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 24px;
}

.grid-card {
  background: var(--color-bg-card);
  border-radius: var(--radius-xl);
  padding: 32px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  transition: all 0.4s cubic-bezier(0.23, 1, 0.32, 1);
  border: 1px solid var(--color-border);
  position: relative;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
}

.grid-card:hover {
  transform: translateY(-8px) scale(1.02);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.08);
  border-color: var(--color-primary-light);
}

.card-blur-bg {
  position: absolute;
  top: -20%;
  left: -20%;
  width: 140%;
  height: 140%;
  background-size: cover;
  background-position: center;
  filter: blur(45px) saturate(1.8) opacity(0.12);
  z-index: 0;
  pointer-events: none;
  transition: all 0.5s ease;
}

.grid-card:hover .card-blur-bg {
  filter: blur(35px) saturate(2.2) opacity(0.18);
  transform: scale(1.1);
}

.card-platform-tag {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 5;
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 700;
  color: #ffffff;
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  pointer-events: none;
}

.tag-douyin {
  background: linear-gradient(135deg, #25f4ee 0%, #fe2c55 100%);
}

.tag-douyu {
  background: linear-gradient(135deg, #ff6a00 0%, #ff8c00 100%);
}

.tag-bilibili {
  background: linear-gradient(135deg, #00a1d6 0%, #35c7ff 100%);
}

.tag-huya {
  background: linear-gradient(135deg, #ff8c00 0%, #ffb347 100%);
}

.tag-cc {
  background: linear-gradient(135deg, #0d91e9 0%, #00b0ff 100%);
}

.tag-twitch {
  background: linear-gradient(135deg, #9146ff 0%, #6441a5 100%);
}

.tag-unknown {
  background: linear-gradient(135deg, #64748b 0%, #94a3b8 100%);
}

.card-record-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 5;
  background: var(--color-success);
  color: white;
  font-size: 10px;
  padding: 2px 10px;
  border-radius: 10px;
  font-weight: 700;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  white-space: nowrap;
  transition: all 0.3s ease;
  transform: translateY(0);
  pointer-events: none;
}

.grid-card:hover .card-record-badge {
  transform: translateY(-2px);
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.12);
}

.card-avatar-wrapper {
  position: relative;
  margin-bottom: 16px;
}

.card-avatar,
.card-avatar-placeholder {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  object-fit: cover;
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.12);
  position: relative;
  z-index: 1;
  border: 2px solid white;
}

.card-avatar-placeholder {
  background: var(--color-bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
}

.card-info {
  text-align: center;
  width: 100%;
}

.card-name {
  font-size: 16px;
  font-weight: 700;
  margin-top: 4px;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-meta {
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.empty-state {
  margin-top: 18px;
  text-align: center;
  color: var(--color-text-secondary);
  padding: 24px;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);
}

.back-btn:hover {
  background: white;
  border-color: var(--color-primary);
  color: var(--color-primary);
  transform: translateX(-4px);
  box-shadow: 0 6px 16px rgba(230, 126, 34, 0.15);
}

.back-btn:active {
  transform: translateX(-4px) scale(0.95);
  box-shadow: 0 2px 4px rgba(230, 126, 34, 0.1);
}

.header-divider {
  width: 1px;
  height: 26px;
  background: var(--color-border-primary);
}

.current-streamer {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-avatar,
.header-avatar-placeholder {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid var(--color-border-primary);
}

.header-avatar-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.header-name {
  font-weight: 700;
  display: flex;
  align-items: center;
}

.header-platform-tag {
  display: inline-flex;
  align-items: center;
  font-size: 10px;
  line-height: 1.4;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 700;
  color: #ffffff;
  margin-left: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  flex-shrink: 0;
}

.header-sub {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.content-grid {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 10px;
  /* 展开到剧余视口高度，配合内部独立滚动 */
  height: calc(100vh - 160px);
  min-height: 500px;
  align-items: stretch;
}

.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  font-weight: 700;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

/* 左侧面板：flex 列，标题锁定，列表滚动 */
.records-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 右侧面板：flex 列，控制栏锁定，片段列表滚动 */
.analysis-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 顶部控制栏锁定不滚动 */
.controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex-shrink: 0;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--color-border-primary);
  margin-bottom: 2px;
}

.record-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  /* 左侧面板整体就是可滚动区域 */
  overflow-y: auto;
  overflow-x: hidden;
  flex: 1;
}

.record-item {
  display: block;
  width: 100%;
  border: 1px solid var(--color-border-primary);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--color-bg-secondary);
  text-align: left;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
  cursor: pointer;
  flex-shrink: 0;
}

.record-item:hover:not(.active) {
  border-color: var(--color-primary-light);
  background: var(--color-bg-hover);
  transform: translateX(4px);
}

.record-item.active {
  border-color: #ef6c24;
  background: rgba(239, 108, 36, 0.06);
  box-shadow: inset 3px 0 0 #ef6c24;
}

.record-line1 {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.record-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.6;
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  flex-shrink: 0;
}

.record-filename {
  font-weight: 600;
  font-size: 13px;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.record-time {
  font-weight: 700;
}

.record-mid-tags {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
  margin-left: auto;
}

.record-right-tags {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
  margin-left: 12px;
}

.record-meta-info {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  white-space: nowrap;
}

.record-format-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  flex-shrink: 0;
  letter-spacing: 0.5px;
}

.record-highlight-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1;
  border: 1px solid transparent;
  white-space: nowrap;
}

.record-highlight-tag.is-success {
  color: var(--color-primary, #e67e22);
  background: var(--color-primary-light, rgba(230, 126, 34, 0.1));
  border-color: rgba(230, 126, 34, 0.25);
}

.record-highlight-tag.is-running {
  color: #9a6700;
  background: rgba(245, 158, 11, 0.18);
  border-color: rgba(245, 158, 11, 0.35);
}

.record-highlight-tag.is-failed {
  color: #b42318;
  background: rgba(248, 113, 113, 0.18);
  border-color: rgba(248, 113, 113, 0.35);
}

.record-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1;
  border: 1px solid transparent;
  white-space: nowrap;
}

.record-status.is-success {
  color: #0b7a44;
  background: rgba(16, 185, 129, 0.14);
  border-color: rgba(16, 185, 129, 0.3);
}

.record-status.is-running {
  color: #9a6700;
  background: rgba(245, 158, 11, 0.18);
  border-color: rgba(245, 158, 11, 0.35);
}

.record-status.is-failed {
  color: #b42318;
  background: rgba(248, 113, 113, 0.18);
  border-color: rgba(248, 113, 113, 0.35);
}

.record-status.is-neutral {
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
  border-color: var(--color-border);
}

.record-sep {
  margin: 0 6px;
  color: var(--color-text-tertiary);
}

.records-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.records-filter {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.records-filter-select {
  min-width: 100px;
  max-width: 180px;
}

.records-date-input {
  min-width: 110px;
  width: 110px;
}

.records-count {
  flex-shrink: 0;
  color: var(--color-text-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.options-row {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  column-gap: 12px;
  row-gap: 12px;
  align-items: start;
  width: 100%;
}

.option-cell {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  margin-bottom: 2px;
}

.option-cell.compact-cell {
  grid-column: span 1;
}

.option-cell.wide-cell {
  grid-column: span 2;
}

.option-cell label {
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 600;
  color: var(--color-text-secondary);
  letter-spacing: 0.2px;
  margin-left: 2px;
}

.option-cell.small-cell {
  grid-column: span 1;
}

.option-cell.medium-cell {
  grid-column: span 2;
}

.ai-config-cell {
  grid-column: span 3;
}

.option-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  padding: 0 10px;
  border: 1px solid var(--color-border-primary);
  border-radius: 8px;
  background: var(--color-bg-primary);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-primary);
  text-transform: none;
  letter-spacing: 0;
  margin-left: 0;
}

.option-check-input {
  width: 16px;
  height: 16px;
  margin: 0;
  padding: 0;
  accent-color: var(--color-primary);
}

.asr-model-status {
  min-height: 22px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.45);
  background: rgba(148, 163, 184, 0.1);
  color: var(--color-text-secondary);
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.2;
  white-space: nowrap;
}

.asr-model-status.installed {
  border-color: rgba(22, 163, 74, 0.45);
  background: rgba(22, 163, 74, 0.1);
  color: #166534;
}

.asr-model-status.missing {
  border-color: rgba(245, 158, 11, 0.45);
  background: rgba(245, 158, 11, 0.1);
  color: #92400e;
}

.asr-status-refresh {
  border: 0;
  border-left: 1px solid currentColor;
  padding: 0 0 0 6px;
  margin-left: 2px;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.asr-status-refresh:disabled {
  opacity: 0.55;
  cursor: wait;
}

.randomness-cell,
.delay-cell,
.seed-cell {
  grid-column: span 2;
}

.stream-type-row {
  grid-column: span 3;
}

.strategy-cell {
  grid-column: span 2;
}

select,
input {
  width: 100%;
  height: 40px;
  border-radius: 8px;
  border: 1px solid var(--color-border-primary);
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  padding: 0 10px;
}

input[type="number"] {
  padding: 0 8px;
}

.model-source-link {
  height: 40px;
  border-radius: 8px;
  border: 1px solid var(--color-border-primary);
  background: var(--color-bg-primary);
  color: var(--color-primary);
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  text-decoration: none;
  font-size: 13.5px;
  cursor: pointer;
  transition: all 0.2s ease;
  font-weight: 500;
}

.model-source-link:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
  box-shadow: var(--shadow-sm);
}

.model-source-link span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-source-link.disabled {
  opacity: 0.6;
  pointer-events: none;
  color: var(--color-text-secondary);
}

.actions {
  margin-top: 2px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

@media (max-width: 1550px) {
  .options-row {
    grid-template-columns: repeat(6, minmax(0, 1fr));
  }
  .option-cell.wide-cell {
    grid-column: span 2;
  }
  .option-cell.small-cell,
  .option-cell.compact-cell {
    grid-column: span 1;
  }
  .randomness-cell,
  .delay-cell,
  .seed-cell {
    grid-column: span 2;
  }
}

@media (max-width: 1200px) {
  .options-row {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .option-cell.wide-cell,
  .randomness-cell,
  .delay-cell,
  .seed-cell {
    grid-column: span 2;
  }
  .option-cell.small-cell {
    grid-column: span 2;
  }
}

.analyze-action-btn {
  min-width: 112px;
}

@media (min-width: 769px) {
  [data-theme="dark"] .live-highlights-page .actions .btn-primary {
    background: linear-gradient(135deg, #ff9a57 0%, #f7b267 100%);
    color: #2c1600;
    box-shadow: 0 4px 12px rgba(247, 178, 103, 0.28);
  }

  [data-theme="dark"] .live-highlights-page .actions .btn-primary:hover:not(:disabled) {
    background: linear-gradient(135deg, #ffab72 0%, #f9bf83 100%);
    color: #2a1400;
  }

  [data-theme="dark"] .live-highlights-page .actions .btn-outline {
    background: rgba(255, 255, 255, 0.05);
    border-color: rgba(255, 190, 120, 0.65);
    color: #ffc690;
  }

  [data-theme="dark"] .live-highlights-page .actions .btn-outline:hover:not(:disabled) {
    background: rgba(255, 190, 120, 0.16);
    border-color: rgba(255, 201, 145, 0.9);
    color: #ffd8b2;
  }

  [data-theme="dark"] .live-highlights-page .actions .btn-danger {
    background: rgba(255, 134, 127, 0.16);
    border-color: rgba(255, 152, 146, 0.56);
    color: #ffb7af;
  }

  [data-theme="dark"] .live-highlights-page .actions .btn-danger:hover:not(:disabled) {
    background: rgba(255, 152, 146, 0.22);
    border-color: rgba(255, 174, 170, 0.75);
    color: #ffd2cc;
  }
}

.result {
  margin-top: 14px;
  /* 占满剩余空间，独立滚动 */
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.result-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.result-head-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.select-all-btn {
  font-size: 12px;
  padding: 3px 10px;
  height: auto;
  white-space: nowrap;
}

.select-count {
  margin-left: 2px;
  font-weight: 700;
  color: #ef6c24;
}

.meta {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.empty {
  color: var(--color-text-secondary);
  padding: 16px 0;
}

.seed-input-group {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.input-seed {
  flex: 1;
  min-width: 0;
  /* 隐藏 number 输入框自带的微调按钮，保持整洁 */
  -moz-appearance: textfield;
}

.input-seed::-webkit-outer-spin-button,
.input-seed::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.btn-dice {
  width: 38px;
  height: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: 1px solid var(--color-border-primary);
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.btn-dice:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-primary);
  border-color: var(--color-primary);
  transform: rotate(45deg);
}

.btn-dice:active {
  transform: scale(0.9) rotate(90deg);
}

.segment-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.segment-item {
  display: flex;
  gap: 10px;
  border: 1px solid var(--color-border-primary);
  border-radius: 12px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  background: var(--color-bg-card);
}

.segment-item:hover {
  background: var(--color-bg-secondary);
  border-color: var(--color-primary);
  transform: translateY(-2px);
  box-shadow: 0 6px 12px rgba(0, 0, 0, 0.06);
}

.segment-item.has-clip {
  border-left: 4px solid var(--color-success);
}

.segment-item.has-story.has-clip {
  border-left: 4px solid #ef6c24;
}

.segment-item.has-story:not(.has-clip) {
    border-left: 4px solid rgba(239, 108, 36, 0.4);
}

.seg-check {
  padding-top: 2px;
  flex-shrink: 0;
}

.segment-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* 标题行 */
.seg-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.seg-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.seg-ai-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ef6c24, #f5a623);
  flex-shrink: 0;
  margin-top: 1px;
}

.seg-title strong {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-primary);
}

.seg-badge {
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  background: var(--color-primary);
  padding: 2px 8px;
  border-radius: 999px;
  flex-shrink: 0;
  letter-spacing: 0.3px;
  line-height: 1.4;
}

.seg-score {
  font-size: 12px;
  font-weight: 700;
  color: #ef6c24;
  flex-shrink: 0;
  background: rgba(239, 108, 36, 0.1);
  padding: 1px 8px;
  border-radius: 6px;
  white-space: nowrap;
}

/* 元信息行 */
.seg-meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.seg-time {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-primary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--color-bg-secondary);
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid var(--color-border-primary);
}

.seg-time-label {
  display: none;
}

.seg-stats {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}

.seg-pill {
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 10px;
  border-radius: 20px;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border-primary);
  color: var(--color-text-secondary);
  white-space: nowrap;
  transition: all 0.2s ease;
}

.seg-pill.score-pill {
  background: var(--color-primary);
  color: #fff;
  font-weight: 700;
  padding: 2px 7px;
  border: none;
}

.seg-pill:hover {
  border-color: var(--color-primary-light);
  background: var(--color-bg-hover);
}

.seg-ai-pill {
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 20px;
  white-space: nowrap;
  font-weight: 700;
  border: 1px solid transparent;
}

.seg-ai-pill.is-strong {
  color: #0f8a4b;
  background: rgba(22, 163, 74, 0.1);
  border-color: rgba(22, 163, 74, 0.24);
}

.seg-ai-pill.is-medium {
  color: #8a5a0f;
  background: rgba(245, 166, 35, 0.12);
  border-color: rgba(245, 166, 35, 0.26);
}

.seg-ai-pill.is-low {
  color: #b42318;
  background: rgba(244, 63, 94, 0.1);
  border-color: rgba(244, 63, 94, 0.24);
}

.icon-heat { color: #f5222d; }
.icon-semantic { color: #1890ff; }

/* 摘要 */
.seg-summary {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.45;
  margin-top: 0;
}

.seg-summary:empty {
  display: none;
}

.seg-speech {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(24, 144, 255, 0.06);
  border: 1px solid rgba(24, 144, 255, 0.16);
  cursor: pointer;
  margin-top: 4px;
}

.seg-speech:hover {
  border-color: rgba(24, 144, 255, 0.35);
}

.seg-speech-header {
  display: flex;
  align-items: center;
  gap: 4px;
  pointer-events: none;
}

.seg-collapse-icon {
  font-size: 8px;
  color: rgba(24, 144, 255, 0.5);
  transition: transform 0.15s;
}

.seg-speech-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 800;
  background: rgba(24, 144, 255, 0.14);
  color: #1677ff;
}

.seg-speech-text {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.55;
}

.seg-story-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.seg-speech-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 700;
  color: #1677ff;
  background: rgba(24, 144, 255, 0.1);
  border: 1px solid rgba(24, 144, 255, 0.2);
  border-radius: 6px;
  padding: 2px 8px;
  cursor: pointer;
  transition: all 0.12s;
  line-height: 1.5;
}

.seg-speech-btn:hover {
  background: rgba(24, 144, 255, 0.18);
  border-color: rgba(24, 144, 255, 0.35);
}

.speech-modal-body {
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-text-primary);
  max-height: 55vh;
  overflow-y: auto;
  padding: 4px 0;
}

/* AI 剧情文案 */
.seg-story {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border-radius: 8px;
  background: linear-gradient(145deg, rgba(239, 108, 36, 0.05) 0%, rgba(245, 166, 35, 0.08) 100%);
  border: 1px solid rgba(239, 108, 36, 0.15);
  margin-top: 4px;
  box-shadow: inset 0 1px 2px rgba(239, 108, 36, 0.05);
}

.seg-story-badge {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 800;
  background: linear-gradient(135deg, #ef6c24, #f5a623);
  color: #fff;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  box-shadow: 0 2px 4px rgba(239, 108, 36, 0.2);
}

.seg-story-text {
  font-size: 12.5px;
  color: var(--color-text-primary);
  line-height: 1.5;
  font-weight: 500;
}

/* 关键词 */
.seg-keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.seg-kw {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 20px;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border-primary);
  color: var(--color-text-secondary);
}

/* 导出路径 */
.seg-clip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}

.seg-clip .btn-sm {
  height: 32px;
  padding: 0 12px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}


.seg-clip-path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  font-family: monospace;
  color: var(--color-text-secondary);
}

.seg-quick-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-quick-export {
  box-shadow: 0 4px 12px rgba(239, 108, 36, 0.2);
  padding-left: 12px;
  padding-right: 16px;
}

.seg-tip-text {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

.settings-modal-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 65vh;
  overflow-y: auto;
  padding: 4px 0;
}

.settings-row {
  display: flex;
  gap: 16px;
}

.settings-row.full {
  flex-direction: column;
  gap: 6px;
}

.settings-row.cols-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.settings-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.settings-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.settings-input {
  padding: 7px 10px;
  border-radius: 6px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s;
}

.settings-input:focus {
  border-color: var(--color-primary);
}

.settings-select {
  padding: 7px 10px;
  border-radius: 6px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  font-size: 13px;
  outline: none;
  cursor: pointer;
}

.settings-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  padding: 7px 0;
}

/* Toggle switch */
.settings-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.settings-check input {
  display: none;
}

.check-track {
  width: 36px;
  height: 22px;
  border-radius: 999px;
  background: var(--color-bg-tertiary);
  border: 1px solid var(--color-border);
  position: relative;
  transition: background 0.2s;
  flex-shrink: 0;
}

.check-dot {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  transition: transform 0.2s;
}

.settings-check input:checked + .check-track {
  background: var(--color-primary);
  border-color: var(--color-primary);
}

.settings-check input:checked + .check-track .check-dot {
  transform: translateX(14px);
}

.check-text {
  font-size: 13px;
  color: var(--color-text-primary);
}

.settings-hint {
  font-size: 12px;
  color: var(--color-text-tertiary);
  padding-top: 4px;
}

.settings-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 4px;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.spin {
  animation: spin 1s linear infinite;
}

.analyze-progress-row {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--color-border-primary);
  border-radius: 8px;
  background: var(--color-bg-secondary);
}

.analyze-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.analyze-progress-track {
  margin-top: 6px;
  width: 100%;
  height: 7px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.25);
  overflow: hidden;
}

.analyze-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #ef6c24, #f59e0b);
  transition: width 0.25s ease;
  position: relative;
  overflow: hidden;
}

.analyze-progress-fill::after {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0) 0%,
    rgba(255, 255, 255, 0.3) 50%,
    rgba(255, 255, 255, 0) 100%
  );
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.analyze-progress-msg {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.clip {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.clip-path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.clip-preview-btn {
  flex-shrink: 0;
}

/* ===== 全屏切片编辑器 ===== */
.clip-editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: editorFadeIn 0.2s ease;
}

@keyframes editorFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.clip-editor {
  width: 95vw;
  height: 92vh;
  background: var(--color-bg-card);
  border-radius: 14px;
  box-shadow: 0 12px 60px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: editorSlideIn 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes editorSlideIn {
  from { transform: translateY(20px) scale(0.97); opacity: 0; }
  to { transform: translateY(0) scale(1); opacity: 1; }
}

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.editor-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.editor-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text-primary);
  margin: 0;
  white-space: nowrap;
}

.editor-segment-label {
  font-size: 13px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.editor-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.editor-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 8px;
  border: none;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  background: var(--color-primary);
  color: #fff;
  transition: all 0.15s ease;
}

.editor-btn:hover { opacity: 0.9; transform: translateY(-1px); }
.editor-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

.editor-btn.secondary {
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
}

.editor-btn.secondary:hover {
  background: var(--color-bg-hover);
}

.editor-btn.close-btn {
  background: transparent;
  color: var(--color-text-secondary);
  padding: 6px;
}

.editor-btn.close-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
  transform: none;
}

.editor-body {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 0;
  min-height: 0;
  overflow: hidden;
}

.editor-main {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #000;
}

.editor-player-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
  background: #000;
  position: relative;
}

.editor-video {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: contain;
}

.editor-empty {
  color: var(--color-text-tertiary);
  font-size: 14px;
}

.editor-actions-row {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  gap: 8px;
  padding: 8px 20px;
  background: var(--color-bg-card);
  border-top: 1px solid var(--color-border);
}

.editor-timeline-wrap {
  flex-shrink: 0;
  padding: 8px 20px 12px;
  background: var(--color-bg-card);
  border-top: 1px solid var(--color-border);
}

.editor-sidebar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  overflow-y: auto;
  background: var(--color-bg-secondary);
  border-left: 1px solid var(--color-border);
}

.sidebar-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 12px;
  flex-shrink: 0;
}

.sidebar-card.danmu-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.sidebar-card-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
}

.card-icon {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-tertiary);
  line-height: 1;
}

.danmu-count {
  margin-left: auto;
  font-weight: 400;
  color: var(--color-text-tertiary);
}

.sidebar-story {
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text-primary);
  margin: 0;
}

.sidebar-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.kw-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(230, 126, 34, 0.1);
  color: var(--color-primary);
}

.sidebar-empty {
  font-size: 12px;
  color: var(--color-text-tertiary);
  padding: 4px 0;
}

.sidebar-time-display {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.time-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 0;
}

.time-label {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

.time-value {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.time-value.primary {
  color: var(--color-primary);
}

.sidebar-danmu-list {
  flex: 1;
  overflow-y: auto;
  margin: 0 -12px -12px;
  padding: 0 12px 12px;
}

.danmu-item {
  display: flex;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--color-border-primary);
}

.danmu-item:last-child { border-bottom: none; }

.danmu-time {
  flex-shrink: 0;
  width: 48px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-text-tertiary);
}

.danmu-text {
  flex: 1;
  font-size: 12px;
  color: var(--color-text-primary);
  word-break: break-all;
}

.keywords,
.clip {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

@media (max-width: 1100px) {
  .content-grid {
    grid-template-columns: 1fr;
    height: auto;
    min-height: 0;
  }

  .records-panel,
  .analysis-panel {
    overflow: visible;
  }

  .record-list {
    max-height: 400px;
    overflow-y: auto;
    padding-right: 4px;
  }

  .result {
    overflow: visible;
  }

  .options-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }

  .option-cell.compact-cell,
  .option-cell.wide-cell,
  .option-cell.medium-cell,
  .option-cell.small-cell,
  .stream-type-row,
  .ai-config-cell,
  .randomness-cell,
  .delay-cell,
  .seed-cell {
    grid-column: span 1;
  }
}

.mobile-main-header,
.mobile-sidebar-backdrop,
.mobile-action-trigger-bar,
.mobile-actions-backdrop,
.mobile-only-drawer,
.drawer-header-mobile {
  display: none;
}

@media (max-width: 760px) {
  /* 解决移动端网格高度和列宽限制，使其高度自适应流体排版 */
  .workspace-grid {
    height: auto !important;
    margin-top: 0 !important;
  }

  /* 移动端主界面头部（切换按钮与当前选中显示卡） */
  .mobile-main-header {
    display: flex !important;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px;
    background: rgba(255, 255, 255, 0.9) !important;
    border: 1px solid var(--color-border-primary);
    border-radius: 12px;
    cursor: pointer;
    margin-bottom: 12px;
    transition: all 0.2s ease;
    box-sizing: border-box;
    width: 100%;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08) !important;
    position: sticky !important;
    top: 10px !important; /* 悬浮留有 10px 间隙显得极其灵动 */
    z-index: 80 !important; /* 确保盖在滚动列表上方 */
    backdrop-filter: blur(12px) !important;
    -webkit-backdrop-filter: blur(12px) !important;
  }

  [data-theme="dark"] .mobile-main-header {
    background: rgba(24, 24, 24, 0.9) !important;
    border-color: var(--color-border) !important;
  }

  .mobile-main-header:active {
    transform: scale(0.98);
    background: var(--color-bg-hover);
  }

  .header-left-info {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }

  .active-avatar {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 2px solid var(--color-primary);
    object-fit: cover;
    flex-shrink: 0;
  }

  .active-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    text-align: left;
    min-width: 0;
  }

  .active-name {
    font-size: 13.5px;
    font-weight: 700;
    color: var(--color-text-primary);
    display: flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .active-platform {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 4px;
    font-weight: 600;
  }

  .active-record {
    font-size: 11px;
    color: var(--color-text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .placeholder {
    color: var(--color-text-secondary);
    font-size: 13px;
    font-weight: 600;
  }

  .btn-switch-record {
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--color-bg-card);
    border: 1px solid var(--color-border-primary);
    color: var(--color-primary);
    padding: 6px 10px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    flex-shrink: 0;
  }

  .btn-switch-record:active {
    background: var(--color-bg-hover);
  }

  /* 移动端专属遮罩背景 */
  .mobile-sidebar-backdrop {
    display: block !important;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    z-index: 998;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .mobile-sidebar-backdrop.active {
    opacity: 1;
    pointer-events: auto;
  }

  /* 将整个 records-column (截图页面) 在移动端转换为左侧拉出抽屉 */
  .records-column {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    bottom: 0 !important;
    width: 300px !important;
    max-width: 85vw !important;
    height: 100vh !important;
    background: var(--color-bg-card) !important;
    z-index: 999 !important;
    box-shadow: 10px 0 35px rgba(0, 0, 0, 0.15) !important;
    transform: translateX(-100%) !important; /* 默认隐藏在左侧屏幕外 */
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    display: flex !important;
    flex-direction: column !important;
    padding: 16px 14px env(safe-area-inset-bottom) 14px !important;
    margin: 0 !important;
    box-sizing: border-box !important;
    overflow-y: auto !important;
  }

  .records-column.drawer-open {
    transform: translateX(0) !important; /* 划入屏幕 */
  }

  /* 移动端常驻底部快捷简易操作栏 */
  .mobile-action-trigger-bar {
    display: flex !important;
    position: fixed !important;
    left: 12px !important;
    right: 12px !important;
    bottom: calc(10px + env(safe-area-inset-bottom)) !important;
    z-index: 90 !important;
    gap: 8px !important;
    padding: 8px 12px !important;
    border-radius: 14px !important;
    background: rgba(255, 255, 255, 0.94) !important;
    border: 1px solid var(--color-border-primary) !important;
    backdrop-filter: blur(16px) !important;
    -webkit-backdrop-filter: blur(16px) !important;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08) !important;
    box-sizing: border-box !important;
    align-items: center !important;
  }

  [data-theme="dark"] .mobile-action-trigger-bar {
    background: rgba(24, 24, 24, 0.94) !important;
    border-color: var(--color-border) !important;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35) !important;
  }

  .analyze-trigger-btn {
    flex: 1 1 auto !important;
    height: 40px !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    border-radius: 10px !important;
    justify-content: center !important;
  }

  .more-trigger-btn {
    flex: 0 0 110px !important;
    height: 40px !important;
    font-size: 13px !important;
    border-radius: 10px !important;
    justify-content: center !important;
    gap: 4px !important;
  }



  .live-highlights-page {
    padding-bottom: calc(92px + env(safe-area-inset-bottom));
    width: 100%;
    max-width: 100%;
    overflow-x: clip;
  }

  .live-highlights-page,
  .page-content {
    gap: 10px;
    width: 100%;
    max-width: 100%;
    overflow-x: clip;
  }

  .selection-screen,
  .content-grid,
  .card,
  .records-panel,
  .analysis-panel,
  .mobile-records-panel,
  .mobile-analysis-panel {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    box-sizing: border-box;
  }

  .card {
    padding: 12px;
    border-radius: 10px;
  }

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

  .selection-header {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .header-left {
    gap: 10px;
  }

  .brand-orb {
    width: 46px;
    height: 46px;
    border-radius: 12px;
  }

  h2 {
    font-size: 22px;
  }

  .title-row {
    gap: 8px;
    flex-wrap: wrap;
  }

  .beta-badge {
    font-size: 11px;
    padding: 2px 8px;
  }

  .desc {
    margin-top: 4px;
    font-size: 13px;
    line-height: 1.45;
  }

  .header-right {
    width: 100%;
  }

  .search-input {
    height: 40px;
    border-radius: 9px;
  }

  .platform-filters {
    margin-top: 10px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 2px;
  }

  .filter-tag {
    white-space: nowrap;
    flex-shrink: 0;
  }

  .streamer-grid {
    grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
    gap: 15px;
  }

  .grid-card {
    padding: 16px 10px;
  }

  .card-avatar,
  .card-avatar-placeholder {
    width: 60px;
    height: 60px;
  }

  .card-name {
    font-size: 14px;
  }

  .card-meta {
    font-size: 10px;
  }

  .page-header {
    flex-wrap: nowrap;
    align-items: center;
    gap: 8px;
    overflow: hidden;
  }

  .mobile-sticky-header {
    position: sticky;
    top: 0;
    z-index: 40;
    border-radius: 0 0 12px 12px;
    border-left: 0;
    border-right: 0;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }

  .header-divider {
    display: none;
  }

  .back-btn {
    padding: 6px 8px;
    flex-shrink: 0;
  }

  .back-btn-text {
    display: none;
  }

  .current-streamer {
    width: auto;
    min-width: 0;
    flex: 1;
  }

  .header-name,
  .header-sub {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .header-avatar,
  .header-avatar-placeholder {
    width: 34px;
    height: 34px;
  }

  .content-grid {
    gap: 10px;
  }

  .records-panel,
  .analysis-panel {
    overflow: visible;
  }

  .mobile-records-panel {
    padding: 10px;
    overflow-x: clip;
  }

  .mobile-records-panel .panel-title,
  .mobile-analysis-panel .panel-title {
    margin-bottom: 10px;
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }

  .panel-actions {
    display: flex;
    flex-wrap: nowrap;
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    gap: 8px;
    width: 100%;
    scrollbar-width: none;
    padding-bottom: 2px;
  }

  .panel-actions::-webkit-scrollbar {
    display: none;
  }

  .panel-actions .btn {
    flex-shrink: 0;
    white-space: nowrap;
  }

  .record-list {
    display: flex !important;
    flex-direction: column !important;
    gap: 10px !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    width: 100% !important;
    max-height: none !important;
    box-sizing: border-box !important;
    padding-bottom: 24px !important;
  }

  .records-toolbar {
    flex-direction: column;
    align-items: stretch;
    margin-bottom: 8px;
  }

  .records-filter {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
    width: 100%;
  }

  .records-filter-select,
  .records-date-input {
    width: 100%;
    max-width: 100%;
  }

  .records-count {
    align-self: flex-end;
    font-size: 11px;
  }

  .record-item {
    border-radius: 12px !important;
    min-height: auto !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: stretch !important;
    gap: 6px !important;
    padding: 12px 14px !important;
    width: 100% !important;
    box-sizing: border-box !important;
    border: 1px solid var(--color-border-primary) !important;
    background: var(--color-bg-secondary) !important;
    transition: all 0.2s ease !important;
    scroll-snap-align: none !important;
  }

  .record-item.active {
    border-color: #ef6c24 !important;
    background: rgba(239, 108, 36, 0.05) !important;
    box-shadow: inset 3px 0 0 #ef6c24 !important;
  }

  .record-line1 {
    display: flex !important;
    flex-wrap: wrap !important;
    justify-content: space-between !important;
    align-items: center !important;
    width: 100% !important;
    gap: 4px 8px !important;
  }

  .record-badge {
    display: inline-block;
  }

  .record-time {
    font-size: 13.5px !important;
    font-weight: 700 !important;
    color: var(--color-text-primary) !important;
    flex: 1 1 100% !important; /* 独占第一整行 */
    text-align: left !important;
    margin-bottom: 2px !important;
  }

  .record-mid-tags {
    display: flex !important;
    flex-direction: row !important;
    align-items: center !important;
    gap: 6px !important;
    flex: 0 0 auto !important; /* 不独占，与状态栏共享第二行 */
    justify-content: flex-start !important;
    margin-left: 0 !important;
    padding: 0 !important;
    border: none !important;
    margin-top: 0 !important;
  }

  .record-format-tag {
    height: 18px;
    font-size: 10px;
    padding: 0 6px;
    border-radius: 4px;
    background: var(--color-bg-card);
    border: 1px solid var(--color-border-primary);
    display: inline-flex;
    align-items: center;
  }

  .record-meta-info {
    height: 18px;
    font-size: 10px;
    padding: 0 6px;
    border-radius: 4px;
    background: var(--color-bg-card);
    border: 1px solid var(--color-border-primary);
    display: inline-flex;
    align-items: center;
  }

  .record-right-tags {
    display: flex !important;
    flex-direction: row !important;
    align-items: center !important;
    gap: 4px !important;
    width: auto !important;
    justify-content: flex-end !important;
    margin: 0 0 0 auto !important; /* 强制靠右，共享第二行右侧 */
    padding: 0 !important;
    border: none !important;
    flex-shrink: 0 !important;
  }

  .record-highlight-tag {
    height: 18px;
    font-size: 10px;
    padding: 0 6px;
    white-space: nowrap;
    flex-shrink: 0;
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
  }

  .record-status {
    height: 18px;
    font-size: 10px;
    padding: 0 6px;
    white-space: nowrap;
    flex-shrink: 0;
    margin-right: 0;
    opacity: 1;
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
  }

  .record-sep {
    margin: 0 2px;
  }

  .options-row {
    display: flex;
    flex-wrap: nowrap;
    align-items: stretch;
    gap: 9px;
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    scroll-snap-type: x proximity;
    padding-bottom: 6px;
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }

  .option-cell {
    scroll-snap-align: start;
    flex: 0 0 min(120px, 40vw);
    min-width: 0;
    padding: 8px;
    border: 1px solid var(--color-border-primary);
    border-radius: 12px;
    background: var(--color-bg-secondary);
    box-sizing: border-box;
  }

  .option-cell.wide-cell {
    flex: 0 0 min(150px, 48vw);
  }

  .option-cell.medium-cell {
    flex: 0 0 min(160px, 50vw);
  }

  .option-cell.small-cell,
  .option-cell.compact-cell {
    flex: 0 0 min(95px, 30vw);
  }

  .option-cell.seed-cell {
    flex: 0 0 min(140px, 45vw);
  }

  .ai-config-cell {
    flex: 0 0 min(220px, 70vw);
    min-width: 0;
  }

  .option-cell.compact-cell,
  .option-cell.wide-cell,
  .option-cell.medium-cell,
  .stream-type-row {
    grid-column: auto;
  }

  .option-cell label {
    font-size: 12.5px;
    color: var(--color-text-secondary);
  }

  .option-check {
    height: 44px;
    border-radius: 12px;
  }

  .mobile-analysis-panel {
    padding: 12px 10px 14px;
  }

  select,
  input {
    height: 44px;
    border-radius: 12px;
    font-size: 15px;
  }

  .stream-type-row {
    flex: 0 0 min(280px, 85vw);
    grid-column: auto;
  }

  .pc-only {
    display: none !important;
  }

  .mobile-only-drawer {
    display: flex !important;
    flex-direction: column !important;
    width: 100% !important;
    border-bottom: 1px solid var(--color-border-primary) !important;
    padding-bottom: 14px !important;
    margin-bottom: 8px !important;
    flex-shrink: 0 !important;
  }

  .mobile-only-drawer .options-row {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 8px !important;
    width: 100% !important;
    padding-bottom: 0 !important;
    overflow: visible !important;
  }

  .mobile-only-drawer .option-cell {
    flex: 1 1 calc(50% - 4px) !important;
    box-sizing: border-box !important;
    background: var(--color-bg-secondary) !important;
    border: 1px solid var(--color-border-primary) !important;
    border-radius: 10px !important;
    padding: 6px 8px !important;
  }

  .mobile-only-drawer .option-cell.seed-cell {
    flex: 1 1 100% !important; /* 随机种子独占一行 */
  }



  .actions {
    display: flex;
    flex-wrap: wrap !important;
    gap: 6px !important;
    width: 100% !important;
    box-sizing: border-box !important;
    padding-bottom: 0 !important;
  }

  .actions .btn {
    width: auto !important;
    flex: 1 1 calc(50% - 4px) !important;
    min-width: 0 !important;
    justify-content: center !important;
    height: 38px !important;
    border-radius: 10px !important;
    font-size: 13px !important;
    padding: 0 8px !important;
    white-space: nowrap !important;
    font-weight: 600 !important;
    outline: none !important;
    box-shadow: none !important;
    transition: all 0.2s ease;
  }

  .actions .analyze-action-btn {
    flex: 1 1 100% !important; /* 核心的“开始分析”主按钮独占一整行 */
    height: 42px !important;
    font-size: 14px !important;
    font-weight: 700 !important;
  }

  /* 强力定制移动端按钮风格，彻底杜绝双边框或胶囊形不协调问题 */
  .actions .btn-outline {
    border: 1px solid var(--color-primary) !important;
    background: transparent !important;
    color: var(--color-primary) !important;
  }

  .actions .btn-primary {
    background: linear-gradient(135deg, #e96a2e 0%, #f39c12 100%) !important;
    color: #ffffff !important;
    border: none !important;
    box-shadow: 0 2px 8px rgba(233, 106, 46, 0.18) !important;
  }

  .actions .btn-danger {
    background: transparent !important;
    border: 1px solid var(--color-error) !important;
    color: var(--color-error) !important;
  }

  .actions .btn-secondary {
    background: transparent !important;
    border: 1px solid var(--color-text-secondary) !important;
    color: var(--color-text-secondary) !important;
  }

  [data-theme="dark"] .actions .btn-outline {
    background: rgba(255, 255, 255, 0.04) !important;
    border-color: var(--color-border) !important;
    color: var(--color-text-primary) !important;
  }

  [data-theme="dark"] .actions .btn-danger {
    background: rgba(231, 76, 60, 0.06) !important;
    border-color: rgba(231, 76, 60, 0.3) !important;
    color: #ff8f88 !important;
  }

  .result {
    margin-top: 10px;
    overflow: visible;
    padding-right: 0;
  }

  .segment-list,
  .manual-clips-list {
    padding-bottom: calc(76px + env(safe-area-inset-bottom)) !important; /* 给底部悬浮条留出绝对宽裕的占位高度 */
  }

  .result-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }

  .result-head-right {
    width: 100%;
    justify-content: space-between;
  }

  .meta {
    font-size: 12px;
  }

  .segment-item {
    padding: 11px 10px 10px;
    gap: 8px;
    border-radius: 14px;
  }

  .seg-title strong {
    white-space: normal;
    font-size: 13px;
    line-height: 1.35;
  }

  .seg-score {
    font-size: 11px;
    padding: 1px 6px;
  }

  .seg-clip {
    flex-direction: row;
    align-items: center;
    flex-wrap: nowrap;
    gap: 8px;
  }

  .seg-pill {
    font-size: 10px;
    padding: 1px 6px;
  }

  .seg-summary,
  .seg-story-text {
    font-size: 12px;
    line-height: 1.5;
  }

}
@keyframes btn-pulse {
  0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 108, 36, 0.6); }
  50% { transform: scale(1.05); box-shadow: 0 0 0 12px rgba(239, 108, 36, 0); }
  100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 108, 36, 0); }
}

@keyframes bg-flow {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

.btn-primary:disabled {
  background: linear-gradient(-45deg, #ef6c24, #ff8c00, #f59e0b, #ff8c00) !important;
  background-size: 400% 400% !important;
  border: none !important;
  color: #fff !important;
  opacity: 1 !important;
  animation: bg-flow 2s ease infinite, btn-pulse 1.5s infinite !important;
  cursor: wait;
}
.ai-config-cell {
  min-width: 300px;
}

.model-readonly-value {
  margin-top: 0;
  min-height: 40px;
  width: 100%;
  max-width: 320px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  border-radius: 8px;
  background: var(--color-bg-secondary, #f8f9fa);
  border: 1px solid var(--color-border-primary, #d1d5db);
  color: var(--color-text-primary);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  box-sizing: border-box;
}
  .model-settings-hint {
    margin-top: 10px;
    color: var(--color-text-secondary);
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .link-btn {
    border: none;
    background: transparent;
    color: var(--color-primary);
    cursor: pointer;
    padding: 0;
    font-size: 12px;
    text-decoration: underline;
  }
  .link-btn:hover {
    opacity: 0.9;
  }
  .hint-divider {
    color: var(--color-border);
    margin: 0 2px;
  }
  .reset-btn {
    color: var(--color-text-secondary);
  }
  .reset-btn:hover {
    color: var(--color-primary);
  }

.live-type-input {
  width: 80px !important;
  flex: none !important;
}

/* 即时显示的自定义 Tooltip */
[data-tooltip] {
  position: relative;
  cursor: help;
}

[data-tooltip]::after {
  content: attr(data-tooltip);
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%) scale(0.95);
  padding: 6px 10px;
  background: rgba(30, 41, 59, 0.98);
  color: #fff;
  font-size: 12px;
  line-height: 1.4;
  border-radius: 6px;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.05s ease-out, transform 0.05s ease-out;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  z-index: 2000;
  font-weight: normal;
}

[data-tooltip]:hover::after {
  opacity: 1;
  transform: translateX(-50%) scale(1);
}

[data-tooltip]::before {
  content: '';
  position: absolute;
  bottom: calc(100% + 2px);
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-top-color: rgba(30, 41, 59, 0.98);
  opacity: 0;
  transition: opacity 0.05s ease-out;
  pointer-events: none;
  z-index: 2000;
}

[data-tooltip]:hover::before {
  opacity: 1;
}

/* 适配移动端：移动端通常通过长按显示，这里简单兼容 */
@media (max-width: 768px) {
  [data-tooltip]::after, [data-tooltip]::before {
    display: none !important;
  }
}

/* ============ 模式切换标签 ============ */
.mode-tabs {
  display: inline-flex;
  gap: 6px;
  margin-bottom: 20px;
  background: var(--color-bg-card);
  border-radius: 12px;
  padding: 6px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.06);
  border: 1px solid var(--color-border);
}
.mode-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary, #666);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
}
.mode-tab:hover:not(.active) {
  background: var(--color-bg-hover, #f5f5f5);
  color: var(--color-primary);
}
.mode-tab.active {
  background: var(--color-primary, #e67e22);
  color: #fff;
  box-shadow: 0 4px 12px var(--color-primary-light, rgba(230, 126, 34, 0.25));
}
.mode-tab.active:hover {
  background: var(--color-primary-hover, #d35400);
}

/* ============ 手动切片容器 ============ */
.manual-slice-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.manual-source-tabs {
  display: flex;
  gap: 4px;
  background: var(--color-bg-card);
  border-radius: 8px;
  padding: 3px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.06);
}
.manual-source-tabs .mode-tab {
  flex: 0 1 auto;
  padding: 8px 16px;
  font-size: 13px;
}
.manual-search-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.manual-search-row .search-input-wrapper {
  flex: 1;
}
.manual-count {
  font-size: 13px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.manual-video-list {
  background: var(--color-bg-card);
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  min-height: 200px;
  max-height: 520px;
  overflow-y: auto;
}
.manual-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 48px 20px;
  color: var(--color-text-secondary);
}
.manual-video-items {
  display: flex;
  flex-direction: column;
}
.manual-video-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  cursor: pointer;
  transition: background 0.15s;
  border-bottom: 1px solid var(--border-color, #f0f0f0);
}
.manual-video-item:last-child {
  border-bottom: none;
}
.manual-video-item:hover {
  background: var(--bg-hover, rgba(0,0,0,0.03));
}
.manual-video-item.selected {
  background: rgba(99,102,241,0.06);
}
.mvi-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: rgba(99,102,241,0.1);
  color: var(--color-primary, #6366f1);
  flex-shrink: 0;
}
.mvi-info {
  flex: 1;
  min-width: 0;
}
.mvi-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary, #333);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mvi-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 2px;
}
.mvi-tag {
  background: var(--bg-tag, rgba(0,0,0,0.05));
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
}
.mvi-sep {
  color: var(--border-color, #ddd);
}
.mvi-arrow {
  color: var(--text-tertiary, #bbb);
  flex-shrink: 0;
}

/* ============ 下载视频卡片 ============ */
.download-card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.download-card {
  display: flex;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--color-bg-card);
  border: 1px solid var(--border-color, #f0f0f0);
  cursor: pointer;
  transition: all 0.15s;
  align-items: center;
}
.download-card:hover {
  border-color: var(--color-primary, #6366f1);
  box-shadow: 0 2px 8px rgba(99,102,241,0.12);
}
.download-card.selected {
  border-color: var(--color-primary, #6366f1);
  background: rgba(99,102,241,0.04);
}
.dc-thumb {
  position: relative;
  width: 100px;
  height: 56px;
  border-radius: 6px;
  overflow: hidden;
  background: var(--bg-secondary, #f5f5f5);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.dc-thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.dc-thumb-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  color: var(--text-tertiary, #bbb);
}
.dc-thumb-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0,0,0,0.2);
  color: #fff;
  opacity: 0;
  transition: opacity 0.15s;
}
.download-card:hover .dc-thumb-overlay {
  opacity: 1;
}
.dc-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dc-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dc-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary, #333);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dc-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
  flex-wrap: wrap;
}
.dc-author {
  white-space: nowrap;
}
.dc-status {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.6;
}
.dc-status.completed {
  background: #f6ffed;
  color: #52c41a;
  border: 1px solid #b7eb8f;
}
.dc-status.error {
  background: #fff2f0;
  color: #ff4d4f;
  border: 1px solid #ffccc7;
}
.dc-status.downloading,
.dc-status.processing,
.dc-status.pending {
  background: #e6f7ff;
  color: #1890ff;
  border: 1px solid #91d5ff;
}
.dc-status.cancelled {
  background: #f5f5f5;
  color: #999;
  border: 1px solid #d9d9d9;
}
.dc-date {
  white-space: nowrap;
  margin-left: auto;
}

/* 平台徽标（复刻下载中心样式） */
.badge.platform-badge-mini,
.platform-badge-mini {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  line-height: 1.7;
  white-space: nowrap;
  background: #f0f2f5;
  color: #64748b;
  border: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.badge.platform-badge-mini.douyin,
.platform-badge-mini.badge-douyin { background: #fff0f0; color: #e84393; border-color: #f5c6d6; }
.badge.platform-badge-mini.bilibili,
.platform-badge-mini.badge-bilibili { background: #e6f7ff; color: #00a1d6; border-color: #91d5ff; }
.badge.platform-badge-mini.youtube,
.platform-badge-mini.badge-youtube { background: #fff0f0; color: #ff0000; border-color: #ffcdd2; }
.badge.platform-badge-mini.tiktok,
.platform-badge-mini.badge-tiktok { background: #f0f0ff; color: #333; border-color: #ccc; }
.badge.platform-badge-mini.xiaohongshu,
.platform-badge-mini.badge-xiaohongshu { background: #fff0f0; color: #ff2442; border-color: #ffcdd2; }
.badge.platform-badge-mini.instagram,
.platform-badge-mini.badge-instagram { background: linear-gradient(135deg,#f0e6ff,#fff0f0); color: #e1306c; border-color: #f5c6d6; }
.badge.platform-badge-mini.netease,
.platform-badge-mini.badge-netease { background: #fff7e6; color: #d43c33; border-color: #ffd591; }

.manual-hint {
  text-align: center;
  padding: 24px;
  color: var(--color-text-secondary);
  font-size: 13px;
  background: var(--color-bg-card);
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.manual-clips-panel {
  border: 1px solid var(--border-color, #eee);
  border-radius: 10px;
  padding: 14px;
  background: var(--color-bg-card);
}
.manual-clips-panel .panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 10px;
}
.manual-clips-panel .panel-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.manual-clips-panel .panel-actions .btn-sm {
  font-size: 11px;
  padding: 3px 8px;
}
.manual-clips-panel .panel-loading,
.manual-clips-panel .panel-empty {
  text-align: center;
  padding: 24px;
  color: var(--color-text-secondary);
  font-size: 13px;
}
.manual-clips-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.manual-clip-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--bg-secondary, #f8f8f8);
  transition: background 0.15s;
}
.manual-clip-item:hover {
  background: var(--bg-hover, #f0f0f0);
}
.mc-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 6px;
  background: rgba(99,102,241,0.1);
  color: var(--color-primary, #6366f1);
  flex-shrink: 0;
}
.mc-info {
  flex: 1;
  min-width: 0;
}
.mc-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #333);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mc-meta {
  font-size: 11px;
  color: var(--color-text-secondary);
  margin-top: 2px;
}
.mc-sep {
  color: var(--border-color, #ddd);
  margin: 0 3px;
}
.mc-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.mc-actions .btn-sm {
  font-size: 11px;
  padding: 2px 8px;
  min-width: 28px;
}
.manual-clips-panel .panel-footer {
  margin-top: 10px;
  text-align: center;
}

@keyframes manual-spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

/* ============ 下载作者下拉 ============ */
.manual-author-selector-wrap {
  position: relative;
  z-index: 50;
}
.manual-author-selector {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 6px;
  background: var(--color-bg-card);
  cursor: pointer;
  font-size: 13px;
  line-height: 1.4;
  height: 32px;
  color: var(--text-primary, #333);
  min-width: 100px;
  max-width: 180px;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s;
}
.manual-author-selector:hover {
  border-color: #bbb;
}
.manual-author-selector.active {
  border-color: var(--color-primary, #6366f1);
}
.manual-author-placeholder {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.manual-author-placeholder.has-value {
  color: var(--text-primary, #333);
}
.manual-author-selector .dropdown-arrow {
  flex-shrink: 0;
  color: var(--text-tertiary, #bbb);
  transition: transform 0.2s;
}
.manual-author-selector.active .dropdown-arrow {
  transform: rotate(180deg);
}
.manual-author-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  width: 280px;
  max-height: 360px;
  background: var(--color-bg-card);
  border: 1px solid var(--border-color, #e0e0e0);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
  display: flex;
  flex-direction: column;
  z-index: 100;
}
.manual-author-search-input {
  padding: 8px;
  border-bottom: 1px solid var(--border-color, #f0f0f0);
}
.manual-author-search-input input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
}
.manual-author-search-input input:focus {
  border-color: var(--color-primary, #6366f1);
}
.manual-author-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}
.manual-author-list .no-authors {
  padding: 24px 16px;
  text-align: center;
  color: var(--color-text-secondary);
  font-size: 13px;
}
.manual-author-list .platform-group {
  padding: 4px 0;
}
.manual-author-list .platform-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px 4px;
  font-size: 11px;
}
.manual-author-list .platform-subtitle {
  color: var(--text-tertiary, #aaa);
}
.manual-author-list .author-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px 8px 16px;
  cursor: pointer;
  transition: background 0.1s;
}
.manual-author-list .author-item:hover {
  background: var(--bg-hover, rgba(0,0,0,0.03));
}
.manual-author-list .author-item.selected {
  color: var(--color-primary, #6366f1);
  font-weight: 500;
}
.manual-author-list .author-item-name {
  font-size: 13px;
  color: var(--text-primary, #333);
}
.manual-author-list .author-item-count {
  font-size: 11px;
  color: var(--text-tertiary, #aaa);
}
.manual-author-clear {
  padding: 8px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--color-primary, #6366f1);
  cursor: pointer;
  border-top: 1px solid var(--border-color, #f0f0f0);
}
.manual-author-clear:hover {
  background: var(--bg-hover, rgba(0,0,0,0.03));
}

/* ============ 手动切片筛选栏 ============ */
.manual-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.manual-filter-bar.download-filters {
  gap: 10px;
  flex-wrap: nowrap;
  padding-bottom: 2px;
}
.manual-filter-bar.download-filters > .manual-status-tabs {
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  flex-shrink: 0;
  scrollbar-width: thin;
}
.manual-filter-bar.download-filters > .manual-status-tabs::-webkit-scrollbar {
  height: 3px;
}
.manual-filter-bar.download-filters > .manual-status-tabs::-webkit-scrollbar-thumb {
  background: var(--border-color, #ddd);
  border-radius: 2px;
}
.manual-filter-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.manual-select {
  padding: 4px 10px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 6px;
  background: var(--color-bg-card);
  color: var(--text-primary, #333);
  font-size: 13px;
  line-height: 1.4;
  height: 32px;
  cursor: pointer;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s;
}
.manual-select:focus {
  border-color: var(--color-primary, #6366f1);
}
.manual-select-narrow {
  width: 120px;
}
.manual-date-input {
  padding: 5px 10px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 6px;
  background: var(--color-bg-card);
  color: var(--text-primary, #333);
  font-size: 13px;
  outline: none;
}
.manual-date-input:focus {
  border-color: var(--color-primary, #6366f1);
}
.manual-platform-tabs,
.manual-status-tabs {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.manual-platform-tabs .filter-tag,
.manual-status-tabs .filter-tag {
  padding: 4px 12px;
  border: 1px solid var(--border-color, #e0e0e0);
  border-radius: 14px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.manual-platform-tabs .filter-tag:hover,
.manual-status-tabs .filter-tag:hover {
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
}
.manual-platform-tabs .filter-tag.active,
.manual-status-tabs .filter-tag.active {
  background: var(--color-primary, #6366f1);
  border-color: var(--color-primary, #6366f1);
  color: #fff;
}
.manual-pagination-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 8px 0;
}
.pagination-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}
.inline-pagination {
  flex-shrink: 0;
}
.page-btn {
  min-width: 28px;
  height: 28px;
  padding: 0 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 4px;
  background: var(--color-bg-card);
  color: var(--text-primary, #333);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.page-btn:hover:not(:disabled) {
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
}
.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.page-info {
  font-size: 12px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.page-select {
  margin-left: 2px;
  padding: 3px 6px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 4px;
  background: var(--color-bg-card);
  color: var(--text-primary, #333);
  font-size: 12px;
  outline: none;
  cursor: pointer;
  height: 28px;
}

/* ============ 紧凑工作区网格布局 ============ */
.workspace-grid {
  height: calc(100vh - 76px) !important; /* 无顶部遮挡，让网格直达顶部，充分利用视口高度 */
  margin-top: 0 !important;
}

.records-column {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  overflow: hidden;
  width: 320px;
  flex-shrink: 0;
}

.records-column .flex-1 {
  flex: 1;
  min-height: 0; /* 防止 Flex 子元素溢出 */
}

/* ============ 紧凑模式标签 ============ */
.compact-mode-tabs {
  width: 100% !important;
  display: flex !important;
  margin-bottom: 0 !important;
  box-sizing: border-box;
}

.compact-mode-tabs .mode-tab {
  flex: 1;
  justify-content: center;
  padding: 8px 12px !important;
  font-size: 13px !important;
  border-radius: 8px !important;
}

/* ============ 紧凑博主信息头部 ============ */
.compact-page-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px !important;
  background: var(--color-bg-card);
  border-radius: 12px;
  border: 1px solid var(--color-border-primary);
  flex-shrink: 0;
}

.compact-page-header .current-streamer {
  flex: 1;
  min-width: 0;
}

.compact-back-btn {
  padding: 6px 10px !important;
  border-radius: 8px !important;
  font-size: 12px !important;
  white-space: nowrap;
}

.compact-back-btn .back-btn-text {
  font-size: 12px !important;
}

.compact-avatar {
  width: 34px !important;
  height: 34px !important;
  border-radius: 50%;
}

.streamer-info {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0; /* 允许截断 */
}

.compact-name {
  font-size: 14px !important;
  font-weight: 700;
  display: flex;
  align-items: center;
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

.streamer-name-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 0 1 auto;
  min-width: 0;
}

.compact-sub {
  font-size: 11px !important;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
</style>
