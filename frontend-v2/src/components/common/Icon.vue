<template>
  <svg 
    :width="size" 
    :height="size" 
    viewBox="0 0 24 24" 
    fill="none" 
    stroke="currentColor" 
    stroke-width="2" 
    stroke-linecap="round" 
    stroke-linejoin="round"
    class="icon"
  >
    <!-- Dashboard -->
    <template v-if="name === 'dashboard'">
      <rect x="3" y="3" width="7" height="7"></rect>
      <rect x="14" y="3" width="7" height="7"></rect>
      <rect x="14" y="14" width="7" height="7"></rect>
      <rect x="3" y="14" width="7" height="7"></rect>
    </template>

    <!-- Download -->
    <!-- Download -->
    <template v-else-if="name === 'download'">
       <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
       <polyline points="7 10 12 15 17 10"></polyline>
       <line x1="12" y1="15" x2="12" y2="3"></line>
    </template>

    <!-- Upload -->
    <template v-else-if="name === 'upload'">
       <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
       <polyline points="17 8 12 3 7 8"></polyline>
       <line x1="12" y1="3" x2="12" y2="15"></line>
    </template>

    <!-- Subscriptions / Bell / Notifications -->
    <template v-else-if="name === 'subscriptions' || name === 'bell' || name === 'notifications'">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
      <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
    </template>

    <!-- Folder -->
    <template v-else-if="name === 'folder'">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
    </template>

    <!-- Settings / Tool -->
    <template v-else-if="name === 'settings' || name === 'tool'">
      <circle cx="12" cy="12" r="3"></circle>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
    </template>

    <!-- Sliders / Filter -->
    <template v-else-if="name === 'sliders' || name === 'filter'">
      <line x1="4" y1="21" x2="4" y2="14"></line>
      <line x1="4" y1="10" x2="4" y2="3"></line>
      <line x1="12" y1="21" x2="12" y2="12"></line>
      <line x1="12" y1="8" x2="12" y2="3"></line>
      <line x1="20" y1="21" x2="20" y2="16"></line>
      <line x1="20" y1="12" x2="20" y2="3"></line>
      <line x1="1" y1="14" x2="7" y2="14"></line>
      <line x1="9" y1="8" x2="15" y2="8"></line>
      <line x1="17" y1="16" x2="23" y2="16"></line>
    </template>

    <!-- Search -->
    <template v-else-if="name === 'search'">
      <circle cx="11" cy="11" r="8"></circle>
      <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
    </template>

    <!-- User / User Check -->
    <template v-else-if="name === 'user'">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
      <circle cx="12" cy="7" r="4"></circle>
    </template>
    <template v-else-if="name === 'user-check'">
      <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
      <circle cx="8" cy="7" r="4"></circle>
      <polyline points="17 11 19 13 23 9"></polyline>
    </template>

    <!-- Users -->
    <template v-else-if="name === 'users'">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
      <circle cx="9" cy="7" r="4"></circle>
      <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
      <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
    </template>

    <!-- Play -->
    <template v-else-if="name === 'play'">
      <polygon points="5 3 19 12 5 21 5 3"></polygon>
    </template>

    <!-- Pause -->
    <template v-else-if="name === 'pause'">
      <rect x="6" y="4" width="4" height="16"></rect>
      <rect x="14" y="4" width="4" height="16"></rect>
    </template>

    <!-- X / Close -->
    <template v-else-if="name === 'x' || name === 'close'">
      <line x1="18" y1="6" x2="6" y2="18"></line>
      <line x1="6" y1="6" x2="18" y2="18"></line>
    </template>

    <!-- List -->
    <template v-else-if="name === 'list'">
      <line x1="8" y1="6" x2="21" y2="6"></line>
      <line x1="8" y1="12" x2="21" y2="12"></line>
      <line x1="8" y1="18" x2="21" y2="18"></line>
      <line x1="3" y1="6" x2="3.01" y2="6"></line>
      <line x1="3" y1="12" x2="3.01" y2="12"></line>
      <line x1="3" y1="18" x2="3.01" y2="18"></line>
    </template>

    <!-- Slash / Skip / Ban -->
    <template v-else-if="name === 'slash'">
      <circle cx="12" cy="12" r="10"></circle>
      <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line>
    </template>

    <!-- Refresh -->
    <template v-else-if="name === 'refresh' || name === 'refresh-cw'">
      <polyline points="23 4 23 10 17 10"></polyline>
      <polyline points="1 20 1 14 7 14"></polyline>
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
    </template>

    <!-- Edit / Pencil -->
    <template v-else-if="name === 'edit' || name === 'pencil'">
      <path d="M12 20h9"></path>
      <path d="M16.5 3.5a2.12 2.12 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path>
    </template>

    <!-- Infinity -->
    <template v-else-if="name === 'infinity'">
      <path d="M18.2 8.8a3.8 3.8 0 0 0-5.37 0L12 9.64l-.83-.84a3.8 3.8 0 1 0-5.37 5.38l.83.82.84-.82a3.8 3.8 0 0 1 5.36 0l.84.82.83-.82a3.8 3.8 0 1 0 3.7-6.38z"></path>
    </template>

    <!-- Shuffle -->
    <template v-else-if="name === 'shuffle'">
      <polyline points="16 3 21 3 21 8"></polyline>
      <line x1="4" y1="20" x2="21" y2="3"></line>
      <polyline points="21 16 21 21 16 21"></polyline>
      <line x1="15" y1="15" x2="21" y2="21"></line>
      <line x1="4" y1="4" x2="9" y2="9"></line>
    </template>

    <!-- Repeat -->
    <template v-else-if="name === 'repeat'">
      <polyline points="17 1 21 5 17 9"></polyline>
      <path d="M3 11V9a4 4 0 0 1 4-4h14"></path>
      <polyline points="7 23 3 19 7 15"></polyline>
      <path d="M21 13v2a4 4 0 0 1-4 4H3"></path>
    </template>

    <!-- Repeat One -->
    <template v-else-if="name === 'repeat-one'">
      <polyline points="17 1 21 5 17 9"></polyline>
      <path d="M3 11V9a4 4 0 0 1 4-4h14"></path>
      <polyline points="7 23 3 19 7 15"></polyline>
      <path d="M21 13v2a4 4 0 0 1-4 4H3"></path>
      <path d="M11 10.5l2-1.5v5" stroke-width="2.5"></path>
    </template>

    <!-- Check -->
    <template v-else-if="name === 'check'">
      <polyline points="20 6 9 17 4 12"></polyline>
    </template>

    <!-- Plus / Plus Circle / Add -->
    <template v-else-if="name === 'plus' || name === 'plus-circle' || name === 'add'">
      <line x1="12" y1="5" x2="12" y2="19"></line>
      <line x1="5" y1="12" x2="19" y2="12"></line>
    </template>

    <!-- Trash -->
    <template v-else-if="name === 'trash'">
      <polyline points="3 6 5 6 21 6"></polyline>
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
    </template>

    <!-- External Link -->
    <template v-else-if="name === 'external-link'">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
      <polyline points="15 3 21 3 21 9"></polyline>
      <line x1="10" y1="14" x2="21" y2="3"></line>
    </template>

    <!-- Mail -->
    <template v-else-if="name === 'mail'">
      <rect x="2" y="4" width="20" height="16" rx="2"></rect>
      <polyline points="22 6 12 13 2 6"></polyline>
    </template>

    <!-- Chevron Left -->
    <template v-else-if="name === 'chevron-left'">
      <polyline points="15 18 9 12 15 6"></polyline>
    </template>

    <!-- Chevron Right -->
    <template v-else-if="name === 'chevron-right'">
      <polyline points="9 18 15 12 9 6"></polyline>
    </template>

    <!-- Chevron Down -->
    <template v-else-if="name === 'chevron-down'">
      <polyline points="6 9 12 15 18 9"></polyline>
    </template>

    <!-- Chevron Up -->
    <template v-else-if="name === 'chevron-up'">
      <polyline points="18 15 12 9 6 15"></polyline>
    </template>

    <!-- History / Clock -->
    <template v-else-if="name === 'history' || name === 'clock'">
      <path d="M12 8v4l3 3"></path>
      <path d="M3.05 11a9 9 0 1 1 .5 4m-.5 5v-5h5"></path>
    </template>

    <!-- Globe / Sources -->
    <template v-else-if="name === 'globe' || name === 'sources'">
      <circle cx="12" cy="12" r="10"></circle>
      <line x1="2" y1="12" x2="22" y2="12"></line>
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
    </template>

    <!-- Activity / Analytics -->
    <template v-else-if="name === 'activity' || name === 'analytics'">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
    </template>

    <!-- Layers / Copy -->
    <template v-else-if="name === 'layers' || name === 'copy'">
      <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
      <polyline points="2 17 12 22 22 17"></polyline>
      <polyline points="2 12 12 17 22 12"></polyline>
    </template>

    <!-- Save / Disk -->
    <template v-else-if="name === 'save'">
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
      <polyline points="17 21 17 13 7 13 7 21"></polyline>
      <polyline points="7 3 7 8 15 8"></polyline>
    </template>

    <!-- Calendar / Scheduler -->
    <template v-else-if="name === 'calendar' || name === 'scheduler'">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
      <line x1="16" y1="2" x2="16" y2="6"></line>
      <line x1="8" y1="2" x2="8" y2="6"></line>
      <line x1="3" y1="10" x2="21" y2="10"></line>
    </template>

    <!-- Hard Drive / Storage -->
    <template v-else-if="name === 'hard-drive' || name === 'storage'">
      <line x1="22" y1="12" x2="2" y2="12"></line>
      <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>
      <line x1="6" y1="16" x2="6.01" y2="16"></line>
      <line x1="10" y1="16" x2="10.01" y2="16"></line>
    </template>

    <!-- CPU / Processor -->
    <template v-else-if="name === 'cpu'">
      <rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect>
      <rect x="9" y="9" width="6" height="6"></rect>
      <line x1="9" y1="1" x2="9" y2="4"></line>
      <line x1="15" y1="1" x2="15" y2="4"></line>
      <line x1="9" y1="20" x2="9" y2="23"></line>
      <line x1="15" y1="20" x2="15" y2="23"></line>
      <line x1="20" y1="9" x2="23" y2="9"></line>
      <line x1="20" y1="14" x2="23" y2="14"></line>
      <line x1="1" y1="9" x2="4" y2="9"></line>
      <line x1="1" y1="14" x2="4" y2="14"></line>
    </template>

    <!-- Chip DIP (Systems Screenshot) -->
    <template v-else-if="name === 'chip-dip'">
      <rect x="5" y="2" width="14" height="20" rx="1"></rect>
      <line x1="1" y1="5" x2="5" y2="5"></line>
      <line x1="1" y1="8" x2="5" y2="8"></line>
      <line x1="1" y1="11" x2="5" y2="11"></line>
      <line x1="1" y1="14" x2="5" y2="14"></line>
      <line x1="1" y1="17" x2="5" y2="17"></line>
      <line x1="1" y1="20" x2="5" y2="20"></line>
      <line x1="19" y1="5" x2="23" y2="5"></line>
      <line x1="19" y1="8" x2="23" y2="8"></line>
      <line x1="19" y1="11" x2="23" y2="11"></line>
      <line x1="19" y1="14" x2="23" y2="14"></line>
      <line x1="19" y1="17" x2="23" y2="17"></line>
      <line x1="19" y1="20" x2="23" y2="20"></line>
    </template>

    <!-- CPU Socket (Processor Screenshot) -->
    <template v-else-if="name === 'cpu-socket'">
      <rect x="2" y="2" width="20" height="20" rx="2" stroke-dasharray="2 2"></rect>
      <rect x="7" y="7" width="10" height="10" rx="1"></rect>
    </template>

    <!-- WiFi Signal (Refined Screenshot Style) -->
    <template v-else-if="name === 'ethernet-port'">
      <!-- 底部实心圆点 -->
      <circle cx="12" cy="18" r="2.2" fill="currentColor" stroke="none"></circle>
      <!-- 第一层弧线 - 调整间距 -->
      <path d="M7 13.5a7 7 0 0 1 10 0" stroke-width="3.2" stroke-linecap="round"></path>
      <!-- 第二层弧线 -->
      <path d="M3 9a13 13 0 0 1 18 0" stroke-width="3.2" stroke-linecap="round"></path>
    </template>

    <!-- Info -->
    <template v-else-if="name === 'info'">
      <circle cx="12" cy="12" r="10"></circle>
      <line x1="12" y1="8" x2="12" y2="12"></line>
      <line x1="12" y1="16" x2="12.01" y2="16"></line>
    </template>

    <!-- Alert Triangle -->
    <template v-else-if="name === 'alert-triangle'">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
      <line x1="12" y1="9" x2="12" y2="13"></line>
      <line x1="12" y1="17" x2="12.01" y2="17"></line>
    </template>

    <!-- YouTube -->
    <template v-else-if="name === 'youtube'">
      <path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.33z"></path>
      <polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02"></polygon>
    </template>

    <!-- Video Camera / Live -->
    <template v-else-if="name === 'video-camera' || name === 'live'">
      <path d="M23 7l-7 5 7 5V7z"></path>
      <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
    </template>

    <!-- Video / Film / Subscription -->
    <template v-else-if="name === 'video' || name === 'film' || name === 'video-subscription'">
      <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect>
      <line x1="7" y1="2" x2="7" y2="22"></line>
      <line x1="17" y1="2" x2="17" y2="22"></line>
      <line x1="2" y1="12" x2="22" y2="12"></line>
      <line x1="2" y1="7" x2="7" y2="7"></line>
      <line x1="2" y1="17" x2="7" y2="17"></line>
      <line x1="17" y1="17" x2="22" y2="17"></line>
      <line x1="17" y1="7" x2="22" y2="7"></line>
    </template>

    <!-- Smartphone / Mobile -->
    <template v-else-if="name === 'smartphone' || name === 'mobile'">
      <rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect>
      <line x1="12" y1="18" x2="12.01" y2="18"></line>
    </template>

    <!-- Heart -->
    <template v-else-if="name === 'heart'">
      <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>
    </template>

    <!-- Compass -->
    <template v-else-if="name === 'compass'">
      <circle cx="12" cy="12" r="10"></circle>
      <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon>
    </template>

    <template v-else-if="name === 'zap'">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
    </template>

    <!-- Flame / Heat -->
    <template v-else-if="name === 'flame' || name === 'heat'">
      <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"></path>
    </template>

    <!-- Eye / Users -->
    <template v-else-if="name === 'eye' || name === 'views'">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
      <circle cx="12" cy="12" r="3"></circle>
    </template>
    
    <!-- Logs / File Text -->
    <template v-else-if="name === 'logs' || name === 'file-text'">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
      <polyline points="14 2 14 8 20 8"></polyline>
      <line x1="16" y1="13" x2="8" y2="13"></line>
      <line x1="16" y1="17" x2="8" y2="17"></line>
      <polyline points="10 9 9 9 8 9"></polyline>
    </template>

    <!-- Message Square / Feedback -->
    <template v-else-if="name === 'message-square'">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
    </template>

    <!-- Image / Paintbrush -->
    <template v-else-if="name === 'image' || name === 'brush'">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
      <circle cx="8.5" cy="8.5" r="1.5"></circle>
      <polyline points="21 15 16 10 5 21"></polyline>
    </template>

    <!-- Server -->
    <template v-else-if="name === 'server'">
      <rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect>
      <rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect>
      <line x1="6" y1="6" x2="6.01" y2="6"></line>
      <line x1="6" y1="18" x2="6.01" y2="18"></line>
    </template>

    <!-- Sun / Light Mode -->
    <template v-else-if="name === 'sun'">
      <circle cx="12" cy="12" r="5"></circle>
      <line x1="12" y1="1" x2="12" y2="3"></line>
      <line x1="12" y1="21" x2="12" y2="23"></line>
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
      <line x1="1" y1="12" x2="3" y2="12"></line>
      <line x1="21" y1="12" x2="23" y2="12"></line>
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
    </template>

    <!-- Moon / Dark Mode -->
    <template v-else-if="name === 'moon'">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
    </template>

    <!-- Shield / Proxy -->
    <template v-else-if="name === 'shield'">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
    </template>

    <!-- Link / Chain -->
    <template v-else-if="name === 'link'">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
    </template>

    <!-- Key / API Token -->
    <template v-else-if="name === 'key'">
      <!-- 圆形钥匙柄 -->
      <circle cx="8" cy="12" r="3"></circle>
      <!-- 钥匙杆 -->
      <path d="M10.5 12L21 2.5"></path>
      <!-- 齿 -->
      <polyline points="18 5 21 5 21 8"></polyline>
    </template>

    <!-- Lock -->
    <template v-else-if="name === 'lock'">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
      <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
    </template>

    <!-- Log Out -->
    <template v-else-if="name === 'log-out'">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
      <polyline points="16 17 21 12 16 7"></polyline>
      <line x1="21" y1="12" x2="9" y2="12"></line>
    </template>


    <!-- Bilibili -->
    <template v-else-if="name === 'bilibili'">
      <path d="M17.81,4.47L17.73,4.47C17.4,4.45 17.06,4.56 16.8,4.78L14.58,6.73H15.44C15.82,6.73 16.2,6.73 16.59,6.73L18.67,4.89C18.96,4.63 19,4.19 18.74,3.89C18.48,3.59 18.04,3.55 17.74,3.81L17.81,4.47M6.18,4.47L6.26,4.47C6.6,4.45 6.94,4.56 7.2,4.78L9.42,6.73H8.56C8.18,6.73 7.8,6.73 7.41,6.73L5.33,4.89C5.04,4.63 5,4.19 5.26,3.89C5.52,3.59 5.96,3.55 6.26,3.81L6.18,4.47M12,2C17.5,2 22,6.5 22,12s-4.5,10-10,10S2,17.5 2,12S6.5,2 12,2M12,18.5c3.85,0 7-3.15 7-7s-3.15-7-7-7s-7,3.15-7,7S8.15,18.5 12,18.5M12,7c2.48,0 4.5,2.02 4.5,4.5S14.48,16 12,16s-4.5,-2.02 -4.5,-4.5S9.52,7 12,7z"/>
    </template>

    <!-- TikTok -->
    <template v-else-if="name === 'tiktok'">
      <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-.88-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43V7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.43z"/>
    </template>

    <!-- Database (Enlarged Style) -->
    <template v-else-if="name === 'database'">
      <ellipse cx="12" cy="5" rx="10" ry="3.5"></ellipse>
      <path d="M22 12c0 1.93-4.48 3.5-10 3.5S2 13.93 2 12"></path>
      <path d="M2 5v14c0 1.93 4.48 3.5 10 3.5s10-1.57 10-3.5V5"></path>
    </template>

    <!-- Monitor -->
    <template v-else-if="name === 'monitor'">
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
      <line x1="8" y1="21" x2="16" y2="21"></line>
      <line x1="12" y1="17" x2="12" y2="21"></line>
    </template>

    <!-- TV -->
    <template v-else-if="name === 'tv'">
      <rect x="2" y="7" width="20" height="15" rx="2" ry="2"></rect>
      <polyline points="17 2 12 7 7 2"></polyline>
    </template>

    <!-- Music -->
    <template v-else-if="name === 'music'">
      <path d="M9 18V5l12-2v13"></path>
      <circle cx="6" cy="18" r="3"></circle>
      <circle cx="18" cy="16" r="3"></circle>
    </template>

    <!-- Volume X (Mute) -->
    <template v-else-if="name === 'volume-x'">
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
      <line x1="23" y1="9" x2="17" y2="15"></line>
      <line x1="17" y1="9" x2="23" y2="15"></line>
    </template>

    <!-- Volume 2 (Volume Up) -->
    <template v-else-if="name === 'volume-2'">
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
      <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path>
    </template>

    <!-- Maximize (Fullscreen) -->
    <template v-else-if="name === 'maximize'">
      <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path>
    </template>
    
    <!-- Minimize (Exit Fullscreen) - Optional but good to have -->
    <template v-else-if="name === 'minimize'">
        <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"></path>
    </template>

    <!-- PIP (Picture in Picture) -->
    <template v-else-if="name === 'pip'">
       <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
       <rect x="12" y="10" width="8" height="5" rx="1" ry="1" style="fill: currentColor; fill-opacity: 0.3;" />
    </template>

    <!-- Maximize-2 (Enter Theater) -->
    <template v-else-if="name === 'maximize-2'">
      <polyline points="15 3 21 3 21 9"></polyline>
      <polyline points="9 21 3 21 3 15"></polyline>
      <line x1="21" y1="3" x2="14" y2="10"></line>
      <line x1="3" y1="21" x2="10" y2="14"></line>
    </template>

    <!-- Minimize-2 (Exit Theater) -->
    <template v-else-if="name === 'minimize-2'">
      <polyline points="4 14 10 14 10 20"></polyline>
      <polyline points="20 10 14 10 14 4"></polyline>
      <line x1="14" y1="10" x2="21" y2="3"></line>
      <line x1="3" y1="21" x2="10" y2="14"></line>
    </template>

    <!-- Screen Rotation (Intuitive Landscape Toggle) -->
    <template v-else-if="name === 'screen-rotation'">
      <!-- 竖屏形态（虚影） -->
      <rect x="2" y="3" width="7" height="11" rx="1" opacity="0.3"></rect>
      <!-- 旋转箭头 -->
      <path d="M10 6a6 6 0 0 1 6 6"></path>
      <polyline points="14 4 16 6 14 8"></polyline>
      <!-- 横屏形态（实体） -->
      <rect x="11" y="11" width="11" height="7" rx="1"></rect>
    </template>

    <!-- Screen Off (Normal/Portrait) -->
    <template v-else-if="name === 'screen-off'">
      <rect x="7" y="4" width="10" height="16" rx="2"></rect>
      <circle cx="12" cy="17" r="1.5" fill="currentColor" stroke="none"></circle>
    </template>

    <!-- Inbox / Empty -->
    <template v-else-if="name === 'inbox'">
      <polyline points="22 12 16 12 14 15 10 15 8 12 2 12"></polyline>
      <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>
    </template>

    <!-- Default fallback: A subtle circular placeholder -->
    <template v-else>
      <circle cx="12" cy="12" r="9" stroke-dasharray="4 4" opacity="0.5"></circle>
    </template>

  </svg>
</template>

<script setup>
defineProps({
  name: {
    type: String,
    required: true
  },
  size: {
    type: [Number, String],
    default: 20
  }
})
</script>

<style scoped>
.icon {
  flex-shrink: 0;
}
</style>
