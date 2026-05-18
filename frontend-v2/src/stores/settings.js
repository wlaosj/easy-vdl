import { defineStore } from 'pinia';
import { ref, reactive } from 'vue';
import {
    globalConfigApi,
    aiConfigApi,
    cookieApi,
    notificationsApi,
    backgroundApi
} from '@/api/settings';

const LLM_PROVIDER_DEFAULT_MODELS = {
    minimax: 'MiniMax-Text-01',
    deepseek: 'deepseek-chat',
    compat: 'gpt-4o-mini',
    ollama: 'qwen2.5:7b',
};

function normalizeLlmProvider(provider) {
    const key = String(provider || '').trim().toLowerCase();
    return ['minimax', 'deepseek', 'compat', 'ollama', 'none'].includes(key) ? key : 'none';
}

function getDefaultModelForProvider(provider) {
    const key = normalizeLlmProvider(provider);
    return LLM_PROVIDER_DEFAULT_MODELS[key] || '';
}

export const useSettingsStore = defineStore('settings', () => {
    // 代理设置
    const proxySettings = reactive({
        enabled: false,
        type: 'http',
        host: '',
        port: 8080,
        noProxy: 'localhost,127.0.0.1,*.local'
    });

    // Cookie 状态
    const cookieStatus = reactive({
        youtube: {
            exists: false,
            fileSize: '-',
            lastUpdate: null,
            nextUpdate: null,
            autoUpdate: false,
            autoUpdateInterval: 10
        },
        bilibili: {
            exists: false,
            fileSize: '-',
            lastUpdate: null,
            nextUpdate: null,
            autoUpdate: false,
            autoUpdateInterval: 10
        },
        tiktok: {
            exists: false,
            fileSize: '-',
            lastUpdate: null
        },
        instagram: {
            exists: false,
            username: '',
            lastUpdate: null
        },
        x: {
            exists: false,
            fileSize: '-',
            lastUpdate: null
        },
        netease: {
            exists: false,
            fileSize: '-',
            lastUpdate: null
        },
        xiaohongshu: {
            exists: false,
            fileSize: '-',
            lastUpdate: null
        }
    });

    // 通知设置
    const notificationSettings = reactive({
        // 微信机器人
        wechatBotEnabled: false,
        wechatWebhookUrl: '',
        // Server酱³
        serverChan3Enabled: false,
        serverChan3Uid: '',
        serverChan3Sendkey: '',
        // Bark
        barkEnabled: false,
        barkServerUrl: 'https://api.day.app',
        barkDeviceKey: '',
        barkSound: '',
        barkGroup: '',
        barkIcon: '',
        barkUrl: '',
        barkAutomaticallyCopy: false,
        // 通知类型
        downloadCompleted: true,
        downloadError: true,
        subscriptionCheckFailed: true,
        subscriptionCheckNewVideos: true,
        subscriptionCheckNoNewVideos: false,
        systemStatusEnabled: true,
        // 静音时间
        quietHoursEnabled: false,
        quietHoursStart: '22:00',
        quietHoursEnd: '08:00',
        // 媒体服务器
        mediaServerEnabled: false,
        mediaServerType: 'jellyfin',
        mediaServerUrl: '',
        mediaServerApiKey: '',
        // Telegram Bot
        telegramBotEnabled: false,
        telegramBotToken: '',
        telegramChatId: '',
        telegramProxy: '',
        telegramMediaMaxConcurrent: 5,
        telegramMediaUseDateSubdir: true
    });

    // 背景设置
    const backgroundSettings = reactive({
        exists: false,
        url: '',
        blur: 0,
        modifiedTime: null
    });

    // 下载设置
    const downloadSettings = reactive({
        maxConcurrentDownloads: 10
    });

    // AI 模型设置
    const aiModelSettings = reactive({
        minimaxEnabled: false,
        minimaxBaseUrl: 'https://api.minimaxi.com/v1',
        minimaxModel: 'MiniMax-Text-01',
        minimaxApiKey: '',
        minimaxTimeoutSeconds: 90,
        deepseekEnabled: false,
        deepseekBaseUrl: 'https://api.deepseek.com',
        deepseekModel: 'deepseek-chat',
        deepseekApiKey: '',
        deepseekTimeoutSeconds: 90,
        compatEnabled: false,
        compatProvider: 'OpenAI',
        compatBaseUrl: 'https://api.openai.com/v1',
        compatModel: 'gpt-4o-mini',
        compatApiKey: '',
        compatTimeoutSeconds: 90,
        compatExtraParams: '{}',
        ollamaEnabled: false,
        ollamaBaseUrl: 'http://127.0.0.1:11434',
        ollamaModel: 'qwen2.5:7b',
        ollamaApiKey: '',
        ollamaTimeoutSeconds: 180,
        ollamaMode: 'native',
        ollamaDisableThinking: true,
        ollamaExtraParams: '{}',
        ollamaMetaCapability: 'unknown',
        ollamaMetaCheckedAt: '',
        ollamaMetaDetail: '',
        ollamaMetaCapabilities: [],
        ollamaMetaSupportsVision: null,
        ollamaMetaSupportsAudio: null,
        ollamaMetaSupportsTools: null,
        ollamaMetaSupportsThinking: null,
        ollamaMetaFamily: '',
        ollamaMetaParameterSize: '',
        ollamaMetaQuantizationLevel: '',
        ollamaMetaFormat: '',
        ollamaMetaArchitecture: '',
        ollamaMetaContextLength: null,
        ollamaMetaRequires: '',
        ollamaMetaModifiedAt: '',
        ollamaVisionCapability: 'unknown',
        ollamaVisionCheckedAt: '',
        ollamaVisionDetail: '',
        highlightsModelSource: 'cloud',
        // --- 新架构默认偏好 ---
        l1ScoutProvider: 'none',
        l1ScoutModel: '',
        l2EditorProvider: 'none',
        l2EditorModel: ''
    });

    // 加载状态
    const loading = ref(false);
    const saving = ref(false);

    // 加载所有配置
    async function loadAllSettings() {
        loading.value = true;
        try {
            await Promise.all([
                loadProxySettings(),
                loadCookieStatus(),
                loadNotificationSettings(),
                loadBackgroundSettings(),
                loadDownloadSettings(),
                loadAiModelSettings()
            ]);
        } catch (err) {
            console.error('Failed to load settings:', err);
        } finally {
            loading.value = false;
        }
    }

    // 加载代理设置
    async function loadProxySettings() {
        try {
            const data = await globalConfigApi.getConfig();
            proxySettings.enabled = data.global_proxy_enabled || false;

            if (data.proxy) {
                // 解析代理 URL: http://host:port 或 socks5://host:port
                const match = data.proxy.match(/^(https?|socks5):\/\/([^:]+):(\d+)$/);
                if (match) {
                    proxySettings.type = match[1];
                    proxySettings.host = match[2];
                    proxySettings.port = parseInt(match[3]);
                }
            }

            if (data.no_proxy) {
                proxySettings.noProxy = data.no_proxy;
            }
        } catch (err) {
            console.error('Failed to load proxy settings:', err);
        }
    }

    // 保存代理设置
    async function saveProxySettings() {
        saving.value = true;
        try {
            const config = {
                global_proxy_enabled: proxySettings.enabled
            };

            if (proxySettings.enabled && proxySettings.host) {
                config.proxy = `${proxySettings.type}://${proxySettings.host}:${proxySettings.port}`;
                config.no_proxy = proxySettings.noProxy;
            }

            await globalConfigApi.saveConfig(config);
            return { success: true };
        } catch (err) {
            console.error('Failed to save proxy settings:', err);
            return { success: false, error: err.message };
        } finally {
            saving.value = false;
        }
    }

    // 测试代理连接
    async function testProxyConnection() {
        if (!proxySettings.host) {
            return { success: false, error: '请输入代理服务器地址' };
        }

        const proxyUrl = `${proxySettings.type}://${proxySettings.host}:${proxySettings.port}`;
        try {
            const result = await globalConfigApi.testProxy(proxyUrl);
            return result;
        } catch (err) {
            return { success: false, error: err.message };
        }
    }

    // 清除代理配置
    async function clearProxySettings() {
        try {
            await globalConfigApi.clearConfig(['proxy', 'no_proxy']);
            proxySettings.enabled = false;
            proxySettings.host = '';
            proxySettings.port = 8080;
            proxySettings.noProxy = 'localhost,127.0.0.1,*.local';
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    }

    // 辅助函数：格式化文件大小
    const formatSize = (bytes) => {
        if (!bytes || bytes === 0) return '0 KB';
        return `${(bytes / 1024).toFixed(1)} KB`;
    };

    // 加载 Cookie 状态
    async function loadCookieStatus() {
        try {
            const data = await cookieApi.getStatus();

            if (data.youtube) {
                Object.assign(cookieStatus.youtube, {
                    exists: data.youtube.exists,
                    fileSize: formatSize(data.youtube.size),
                    lastUpdate: data.youtube.last_modified,
                    nextUpdate: data.youtube.next_update,
                    autoUpdate: data.youtube.auto_update_enabled || false,
                    autoUpdateInterval: data.youtube.interval_minutes || 10
                });
            }

            if (data.bilibili) {
                Object.assign(cookieStatus.bilibili, {
                    exists: data.bilibili.exists,
                    fileSize: formatSize(data.bilibili.size),
                    lastUpdate: data.bilibili.last_modified,
                    nextUpdate: data.bilibili.next_update,
                    autoUpdate: data.bilibili.auto_update_enabled || false,
                    autoUpdateInterval: data.bilibili.interval_minutes || 10
                });
            }

            if (data.tiktok) {
                Object.assign(cookieStatus.tiktok, {
                    exists: data.tiktok.exists,
                    fileSize: formatSize(data.tiktok.size),
                    lastUpdate: data.tiktok.last_modified
                });
            }

            if (data.instagram) {
                Object.assign(cookieStatus.instagram, {
                    exists: data.instagram.configured || data.instagram.exists || false,
                    username: data.instagram.username || '',
                    lastUpdate: data.instagram.last_modified
                });
            }

            if (data.x) {
                Object.assign(cookieStatus.x, {
                    exists: data.x.exists,
                    fileSize: formatSize(data.x.size),
                    lastUpdate: data.x.last_modified
                });
            }

            if (data.netease) {
                Object.assign(cookieStatus.netease, {
                    exists: data.netease.exists,
                    fileSize: formatSize(data.netease.size),
                    lastUpdate: data.netease.last_modified
                });
            }

            if (data.xiaohongshu) {
                Object.assign(cookieStatus.xiaohongshu, {
                    exists: data.xiaohongshu.exists,
                    fileSize: formatSize(data.xiaohongshu.size),
                    lastUpdate: data.xiaohongshu.last_modified,
                    nextUpdate: data.xiaohongshu.next_update,
                    autoUpdate: data.xiaohongshu.auto_update_enabled || false,
                    autoUpdateInterval: data.xiaohongshu.interval_minutes || 10
                });
            }
        } catch (err) {
            console.error('Failed to load cookie status:', err);
        }
    }

    // 保存 YouTube Cookie
    async function saveYoutubeCookie(content) {
        saving.value = true;
        try {
            await cookieApi.saveYoutubeCookie(content);
            await loadCookieStatus();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        } finally {
            saving.value = false;
        }
    }

    // 保存 Bilibili Cookie
    async function saveBilibiliCookie(content) {
        saving.value = true;
        try {
            await cookieApi.saveBilibiliCookie(content);
            await loadCookieStatus();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        } finally {
            saving.value = false;
        }
    }

    // 保存 TikTok Cookie
    async function saveTiktokCookie(content) {
        saving.value = true;
        try {
            await cookieApi.saveTiktokCookie(content);
            await loadCookieStatus();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        } finally {
            saving.value = false;
        }
    }

    // 保存 Instagram Cookie
    async function saveInstagramCookie({ username, password }) {
        saving.value = true;
        try {
            await cookieApi.saveInstagramCredentials(username, password);
            await loadCookieStatus();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        } finally {
            saving.value = false;
        }
    }

    // 保存 X Cookie
    async function saveXCookie(content) {
        saving.value = true;
        try {
            await cookieApi.saveXCookie(content);
            await loadCookieStatus();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        } finally {
            saving.value = false;
        }
    }

    // 保存网易云音乐 Cookie
    async function saveNeteaseCookie(content) {
        saving.value = true;
        try {
            await cookieApi.saveNeteaseCookie(content);
            await loadCookieStatus();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        } finally {
            saving.value = false;
        }
    }

    // 保存小红书 Cookie
    async function saveXiaohongshuCookie(content) {
        saving.value = true;
        try {
            await cookieApi.saveXiaohongshuCookie(content);
            await loadCookieStatus();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        } finally {
            saving.value = false;
        }
    }

    // 清除 Cookie
    async function clearCookie(platform) {
        try {
            if (platform === 'youtube') await cookieApi.clearYoutubeCookie();
            if (platform === 'bilibili') await cookieApi.clearBilibiliCookie();
            if (platform === 'tiktok') await cookieApi.clearTiktokCookie();
            if (platform === 'instagram') await cookieApi.clearInstagramCookie();
            if (platform === 'x') await cookieApi.clearXCookie();
            if (platform === 'netease') await cookieApi.clearNeteaseCookie();
            if (platform === 'xiaohongshu') await cookieApi.clearXiaohongshuCookie();
            await loadCookieStatus();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    }

    // 手动立即更新 Cookie
    async function updateCookieNow(platform) {
        try {
            if (platform === 'youtube') await cookieApi.updateYoutubeCookie();
            if (platform === 'bilibili') await cookieApi.updateBilibiliCookie();
            if (platform === 'xiaohongshu') await cookieApi.updateXiaohongshuCookie();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    }

    // 设置自动更新
    async function setAutoUpdate(platform, enabled, interval) {
        try {
            if (platform === 'youtube') await cookieApi.setYoutubeAutoUpdate(enabled, interval);
            if (platform === 'bilibili') await cookieApi.setBilibiliAutoUpdate(enabled, interval);
            if (platform === 'xiaohongshu') await cookieApi.setXiaohongshuAutoUpdate(enabled, interval);
            await loadCookieStatus();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    }

    // 辅助函数：转换布尔值
    const toBool = (val) => String(val) === 'true';
    const toStr = (val) => val ? 'true' : 'false';

    // 加载通知设置
    async function loadNotificationSettings() {
        try {
            const data = await notificationsApi.getSettings();

            Object.assign(notificationSettings, {
                wechatBotEnabled: toBool(data.wechat_bot_enabled),
                wechatWebhookUrl: data.wechat_webhook_url || '',
                serverChan3Enabled: toBool(data.serverchan3_enabled),
                serverChan3Uid: data.serverchan3_uid || '',
                serverChan3Sendkey: data.serverchan3_sendkey || '',
                downloadCompleted: toBool(data.download_completed_enabled),
                downloadError: toBool(data.download_error_enabled),
                subscriptionCheckFailed: toBool(data.subscription_check_failed_enabled),
                subscriptionCheckNewVideos: toBool(data.subscription_check_new_videos_enabled),
                subscriptionCheckNoNewVideos: toBool(data.subscription_check_no_new_videos_enabled),
                systemStatusEnabled: toBool(data.system_status_enabled),
                quietHoursEnabled: toBool(data.quiet_hours_enabled),
                quietHoursStart: data.quiet_hours_start || '22:00',
                quietHoursEnd: data.quiet_hours_end || '08:00',
                mediaServerEnabled: toBool(data.media_server_enabled),
                mediaServerType: data.media_server_type || 'jellyfin',
                mediaServerUrl: data.media_server_url || '',
                mediaServerApiKey: data.media_server_api_key || '',
                // Telegram
                telegramBotEnabled: toBool(data.telegram_bot_enabled),
                telegramBotToken: data.telegram_bot_token || '',
                telegramChatId: data.telegram_chat_id || '',
                telegramProxy: data.telegram_proxy || '',
                telegramMediaMaxConcurrent: Math.max(
                    1,
                    Math.min(
                        10,
                        parseInt(data.telegram_media_max_concurrent ?? 5, 10) || 5
                    )
                ),
                telegramMediaUseDateSubdir: toBool(data.telegram_media_use_date_subdir ?? 'true'),
                // Bark
                barkEnabled: toBool(data.bark_enabled),
                barkServerUrl: data.bark_server_url || 'https://api.day.app',
                barkDeviceKey: data.bark_device_key || '',
                barkSound: data.bark_sound || '',
                barkGroup: data.bark_group || '',
                barkIcon: data.bark_icon || '',
                barkUrl: data.bark_url || '',
                barkAutomaticallyCopy: toBool(data.bark_automatically_copy ?? 'false')
            });
        } catch (err) {
            console.error('Failed to load notification settings:', err);
        }
    }

    // 保存通知设置
    async function saveNotificationSettings() {
        saving.value = true;
        try {
            const telegramEnabled = toStr(notificationSettings.telegramBotEnabled) === 'true'
            const telegramToken = String(notificationSettings.telegramBotToken || '').trim()
            const telegramChatId = String(notificationSettings.telegramChatId || '').trim()

            if (telegramEnabled) {
                if (!telegramToken) {
                    return { success: false, error: '启用 Telegram Bot 失败：请先配置 Bot Token' }
                }
                if (!telegramChatId) {
                    return { success: false, error: '启用 Telegram Bot 失败：请先配置 Chat ID 白名单（可向 Bot 发送 /id 获取）' }
                }
            }
            const barkEnabled = toStr(notificationSettings.barkEnabled) === 'true'
            const barkDeviceKey = String(notificationSettings.barkDeviceKey || '').trim()
            if (barkEnabled && !barkDeviceKey) {
                return { success: false, error: '启用 Bark 失败：请先配置设备 Key' }
            }

            const telegramMediaMaxConcurrent = Math.max(
                1,
                Math.min(
                    10,
                    parseInt(notificationSettings.telegramMediaMaxConcurrent, 10) || 5
                )
            );
            notificationSettings.telegramMediaMaxConcurrent = telegramMediaMaxConcurrent;
            notificationSettings.telegramBotToken = telegramToken;
            notificationSettings.telegramChatId = telegramChatId;
            notificationSettings.barkDeviceKey = barkDeviceKey;

            await notificationsApi.updateSettings({
                wechat_bot_enabled: toStr(notificationSettings.wechatBotEnabled),
                wechat_webhook_url: notificationSettings.wechatWebhookUrl,
                serverchan3_enabled: toStr(notificationSettings.serverChan3Enabled),
                serverchan3_uid: notificationSettings.serverChan3Uid,
                serverchan3_sendkey: notificationSettings.serverChan3Sendkey,
                bark_enabled: toStr(notificationSettings.barkEnabled),
                bark_server_url: notificationSettings.barkServerUrl,
                bark_device_key: barkDeviceKey,
                bark_sound: notificationSettings.barkSound,
                bark_group: notificationSettings.barkGroup,
                bark_icon: notificationSettings.barkIcon,
                bark_url: notificationSettings.barkUrl,
                bark_automatically_copy: toStr(notificationSettings.barkAutomaticallyCopy),
                download_completed_enabled: toStr(notificationSettings.downloadCompleted),
                download_error_enabled: toStr(notificationSettings.downloadError),
                subscription_check_failed_enabled: toStr(notificationSettings.subscriptionCheckFailed),
                subscription_check_new_videos_enabled: toStr(notificationSettings.subscriptionCheckNewVideos),
                subscription_check_no_new_videos_enabled: toStr(notificationSettings.subscriptionCheckNoNewVideos),
                system_status_enabled: toStr(notificationSettings.systemStatusEnabled),
                quiet_hours_enabled: toStr(notificationSettings.quietHoursEnabled),
                quiet_hours_start: notificationSettings.quietHoursStart,
                quiet_hours_end: notificationSettings.quietHoursEnd,
                media_server_enabled: toStr(notificationSettings.mediaServerEnabled),
                media_server_type: notificationSettings.mediaServerType,
                media_server_url: notificationSettings.mediaServerUrl,
                media_server_api_key: notificationSettings.mediaServerApiKey,
                // Telegram
                telegram_bot_enabled: toStr(notificationSettings.telegramBotEnabled),
                telegram_bot_token: telegramToken,
                telegram_chat_id: telegramChatId,
                telegram_proxy: notificationSettings.telegramProxy,
                telegram_media_max_concurrent: telegramMediaMaxConcurrent,
                telegram_media_use_date_subdir: toStr(notificationSettings.telegramMediaUseDateSubdir)
            });
            return { success: true };
        } catch (err) {
            console.error('Failed to save notification settings:', err);
            const backendDetail = err?.response?.data?.detail || err?.response?.data?.message
            return { success: false, error: backendDetail || err.message || '保存失败' };
        } finally {
            saving.value = false;
        }
    }

    // 加载背景设置
    async function loadBackgroundSettings() {
        try {
            const data = await backgroundApi.getStatus();
            backgroundSettings.exists = data.exists || false;
            if (data.exists) {
                backgroundSettings.url = data.path;
                backgroundSettings.modifiedTime = data.modified_time;
            }

            // 从 localStorage 加载模糊度
            const savedBlur = localStorage.getItem('background_blur');
            if (savedBlur) {
                backgroundSettings.blur = parseInt(savedBlur);
            }
        } catch (err) {
            console.error('Failed to load background settings:', err);
        }
    }

    // 设置背景图片
    async function setBackground(url) {
        try {
            const result = await backgroundApi.setBackground(url);
            if (result.success) {
                backgroundSettings.exists = true;
                backgroundSettings.url = result.path;
            }
            return result;
        } catch (err) {
            return { success: false, error: err.message };
        }
    }

    // 清除背景
    async function clearBackground() {
        try {
            await backgroundApi.clearBackground();
            backgroundSettings.exists = false;
            backgroundSettings.url = '';
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    }

    // 设置背景模糊度
    function setBackgroundBlur(blur) {
        backgroundSettings.blur = blur;
        localStorage.setItem('background_blur', blur.toString());
    }

    // 加载下载设置
    async function loadDownloadSettings() {
        try {
            const data = await globalConfigApi.getConfig();
            if (data.max_concurrent_downloads !== undefined) {
                downloadSettings.maxConcurrentDownloads = data.max_concurrent_downloads;
            }
        } catch (err) {
            console.error('Failed to load download settings:', err);
        }
    }

    // 保存下载设置
    async function saveDownloadSettings() {
        saving.value = true;
        try {
            const config = {
                max_concurrent_downloads: downloadSettings.maxConcurrentDownloads
            };
            await globalConfigApi.saveConfig(config);
            return { success: true };
        } catch (err) {
            console.error('Failed to save download settings:', err);
            return { success: false, error: err.message };
        } finally {
            saving.value = false;
        }
    }

    // 加载 AI 模型设置
    async function loadAiModelSettings() {
        try {
            const data = await aiConfigApi.getConfig();
            aiModelSettings.minimaxEnabled = !!data.llm_minimax_enabled;
            aiModelSettings.minimaxBaseUrl = data.llm_minimax_base_url || 'https://api.minimaxi.com/v1';
            aiModelSettings.minimaxModel = data.llm_minimax_model || 'MiniMax-Text-01';
            aiModelSettings.minimaxApiKey = data.llm_minimax_api_key || '';
            aiModelSettings.minimaxTimeoutSeconds = Number(data.llm_minimax_timeout_seconds || 90);
            aiModelSettings.deepseekEnabled = !!data.llm_deepseek_enabled;
            aiModelSettings.deepseekBaseUrl = data.llm_deepseek_base_url || 'https://api.deepseek.com';
            aiModelSettings.deepseekModel = data.llm_deepseek_model || 'deepseek-chat';
            aiModelSettings.deepseekApiKey = data.llm_deepseek_api_key || '';
            aiModelSettings.deepseekTimeoutSeconds = Number(data.llm_deepseek_timeout_seconds || 90);
            aiModelSettings.compatEnabled = !!data.llm_compat_enabled;
            aiModelSettings.compatProvider = data.llm_compat_provider || 'OpenAI';
            aiModelSettings.compatBaseUrl = data.llm_compat_base_url || 'https://api.openai.com/v1';
            aiModelSettings.compatModel = data.llm_compat_model || 'gpt-4o-mini';
            aiModelSettings.compatApiKey = data.llm_compat_api_key || '';
            aiModelSettings.compatTimeoutSeconds = Number(data.llm_compat_timeout_seconds || 90);
            const rawCompatExtra = String(data.llm_compat_extra_params || '').trim();
            if (!rawCompatExtra) {
                aiModelSettings.compatExtraParams = '{}';
            } else {
                try {
                    const parsed = JSON.parse(rawCompatExtra);
                    aiModelSettings.compatExtraParams = (parsed && typeof parsed === 'object' && !Array.isArray(parsed))
                        ? JSON.stringify(parsed, null, 2)
                        : '{}';
                } catch {
                    aiModelSettings.compatExtraParams = '{}';
                }
            }
            aiModelSettings.ollamaEnabled = !!data.llm_ollama_enabled;
            aiModelSettings.ollamaBaseUrl = data.llm_ollama_base_url || 'http://127.0.0.1:11434';
            aiModelSettings.ollamaModel = data.llm_ollama_model || 'qwen2.5:7b';
            aiModelSettings.ollamaApiKey = data.llm_ollama_api_key || '';
            aiModelSettings.ollamaTimeoutSeconds = Number(data.llm_ollama_timeout_seconds || 180);
            const ollamaMode = String(data.llm_ollama_mode || 'native').toLowerCase();
            aiModelSettings.ollamaMode = ['native', 'openai_compat'].includes(ollamaMode) ? ollamaMode : 'native';
            aiModelSettings.ollamaDisableThinking = data.llm_ollama_disable_thinking === undefined
                ? true
                : !!data.llm_ollama_disable_thinking;
            resetOllamaMetaState();
            const rawExtra = String(data.llm_ollama_extra_params || '').trim();
            if (!rawExtra) {
                aiModelSettings.ollamaExtraParams = '{}';
            } else {
                try {
                    const parsed = JSON.parse(rawExtra);
                    aiModelSettings.ollamaExtraParams = (parsed && typeof parsed === 'object' && !Array.isArray(parsed))
                        ? JSON.stringify(parsed, null, 2)
                        : '{}';
                } catch {
                    aiModelSettings.ollamaExtraParams = '{}';
                }
            }
            const capability = String(data.llm_ollama_vision_capability || 'unknown').toLowerCase();
            aiModelSettings.ollamaVisionCapability = ['supported', 'unsupported', 'unknown'].includes(capability)
                ? capability
                : 'unknown';
            aiModelSettings.ollamaVisionCheckedAt = String(data.llm_ollama_vision_checked_at || '').trim();
            aiModelSettings.ollamaVisionDetail = String(data.llm_ollama_vision_detail || '').trim();
            const source = String(data.llm_highlights_model_source || '').toLowerCase();
            if (source === 'auto') {
                aiModelSettings.highlightsModelSource = 'cloud';
            } else {
                aiModelSettings.highlightsModelSource = ['cloud', 'deepseek', 'compat', 'local'].includes(source)
                    ? source
                    : 'cloud';
            }
            
            // 加载 L1/L2 默认配置
            aiModelSettings.l1ScoutProvider = normalizeLlmProvider(data.llm_l1_scout_provider || 'none');
            aiModelSettings.l2EditorProvider = normalizeLlmProvider(data.llm_l2_editor_provider || 'none');
            aiModelSettings.l1ScoutModel = String(data.llm_l1_scout_model || '').trim()
                || getDefaultModelForProvider(aiModelSettings.l1ScoutProvider);
            aiModelSettings.l2EditorModel = String(data.llm_l2_editor_model || '').trim()
                || getDefaultModelForProvider(aiModelSettings.l2EditorProvider);
        } catch (err) {
            console.error('Failed to load AI model settings:', err);
        }
    }

    function normalizeOllamaExtraParams(raw) {
        const text = String(raw ?? '').trim();
        if (!text) {
            return { ok: true, value: '{}' };
        }
        try {
            const parsed = JSON.parse(text);
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
                return { ok: false, error: 'Ollama 额外参数必须是 JSON 对象' };
            }
            return { ok: true, value: JSON.stringify(parsed) };
        } catch (err) {
            return { ok: false, error: `Ollama 额外参数 JSON 无效: ${err.message}` };
        }
    }

    function resetOllamaMetaState() {
        aiModelSettings.ollamaMetaCapability = 'unknown';
        aiModelSettings.ollamaMetaCheckedAt = '';
        aiModelSettings.ollamaMetaDetail = '';
        aiModelSettings.ollamaMetaCapabilities = [];
        aiModelSettings.ollamaMetaSupportsVision = null;
        aiModelSettings.ollamaMetaSupportsAudio = null;
        aiModelSettings.ollamaMetaSupportsTools = null;
        aiModelSettings.ollamaMetaSupportsThinking = null;
        aiModelSettings.ollamaMetaFamily = '';
        aiModelSettings.ollamaMetaParameterSize = '';
        aiModelSettings.ollamaMetaQuantizationLevel = '';
        aiModelSettings.ollamaMetaFormat = '';
        aiModelSettings.ollamaMetaArchitecture = '';
        aiModelSettings.ollamaMetaContextLength = null;
        aiModelSettings.ollamaMetaRequires = '';
        aiModelSettings.ollamaMetaModifiedAt = '';
    }

    // 保存 AI 模型设置
    async function saveAiModelSettings() {
        saving.value = true;
        try {
            const timeout = Math.max(5, Math.min(120, Number(aiModelSettings.minimaxTimeoutSeconds || 90)));
            const deepseekTimeout = Math.max(5, Math.min(120, Number(aiModelSettings.deepseekTimeoutSeconds || 90)));
            const compatTimeout = Math.max(5, Math.min(120, Number(aiModelSettings.compatTimeoutSeconds || 90)));
            const ollamaTimeout = Math.max(10, Math.min(600, Number(aiModelSettings.ollamaTimeoutSeconds || 180)));
            aiModelSettings.minimaxTimeoutSeconds = timeout;
            aiModelSettings.deepseekTimeoutSeconds = deepseekTimeout;
            aiModelSettings.compatTimeoutSeconds = compatTimeout;
            aiModelSettings.ollamaTimeoutSeconds = ollamaTimeout;
            const minimaxReady = !!String(aiModelSettings.minimaxBaseUrl || '').trim()
                && !!String(aiModelSettings.minimaxModel || '').trim()
                && !!String(aiModelSettings.minimaxApiKey || '').trim();
            const deepseekReady = !!String(aiModelSettings.deepseekBaseUrl || '').trim()
                && !!String(aiModelSettings.deepseekModel || '').trim()
                && !!String(aiModelSettings.deepseekApiKey || '').trim();
            const compatReady = !!String(aiModelSettings.compatBaseUrl || '').trim()
                && !!String(aiModelSettings.compatModel || '').trim()
                && !!String(aiModelSettings.compatApiKey || '').trim();
            const ollamaReady = !!String(aiModelSettings.ollamaBaseUrl || '').trim()
                && !!String(aiModelSettings.ollamaModel || '').trim();
            const compatExtraParamsResult = normalizeOllamaExtraParams(aiModelSettings.compatExtraParams);
            if (!compatExtraParamsResult.ok) {
                return { success: false, error: compatExtraParamsResult.error.replace('Ollama', '兼容平台') };
            }
            const extraParamsResult = normalizeOllamaExtraParams(aiModelSettings.ollamaExtraParams);
            if (!extraParamsResult.ok) {
                return { success: false, error: extraParamsResult.error };
            }
            aiModelSettings.compatExtraParams = compatExtraParamsResult.value;
            aiModelSettings.ollamaExtraParams = extraParamsResult.value;
            aiModelSettings.minimaxEnabled = minimaxReady;
            aiModelSettings.deepseekEnabled = deepseekReady;
            aiModelSettings.compatEnabled = compatReady;
            aiModelSettings.ollamaEnabled = ollamaReady;
            await aiConfigApi.saveConfig({
                llm_minimax_enabled: minimaxReady,
                llm_minimax_base_url: aiModelSettings.minimaxBaseUrl || 'https://api.minimaxi.com/v1',
                llm_minimax_model: aiModelSettings.minimaxModel || 'MiniMax-Text-01',
                llm_minimax_api_key: aiModelSettings.minimaxApiKey || '',
                llm_minimax_timeout_seconds: timeout,
                llm_deepseek_enabled: deepseekReady,
                llm_deepseek_base_url: aiModelSettings.deepseekBaseUrl || 'https://api.deepseek.com',
                llm_deepseek_model: aiModelSettings.deepseekModel || 'deepseek-chat',
                llm_deepseek_api_key: aiModelSettings.deepseekApiKey || '',
                llm_deepseek_timeout_seconds: deepseekTimeout,
                llm_compat_enabled: compatReady,
                llm_compat_provider: aiModelSettings.compatProvider || 'OpenAI',
                llm_compat_base_url: aiModelSettings.compatBaseUrl || 'https://api.openai.com/v1',
                llm_compat_model: aiModelSettings.compatModel || 'gpt-4o-mini',
                llm_compat_api_key: aiModelSettings.compatApiKey || '',
                llm_compat_timeout_seconds: compatTimeout,
                llm_compat_extra_params: compatExtraParamsResult.value,
                llm_ollama_enabled: ollamaReady,
                llm_ollama_base_url: aiModelSettings.ollamaBaseUrl || 'http://127.0.0.1:11434',
                llm_ollama_model: aiModelSettings.ollamaModel || 'qwen2.5:7b',
                llm_ollama_api_key: aiModelSettings.ollamaApiKey || '',
                llm_ollama_timeout_seconds: ollamaTimeout,
                llm_ollama_mode: ['native', 'openai_compat'].includes(aiModelSettings.ollamaMode)
                    ? aiModelSettings.ollamaMode
                    : 'native',
                llm_ollama_disable_thinking: !!aiModelSettings.ollamaDisableThinking,
                llm_ollama_extra_params: extraParamsResult.value,
                llm_highlights_model_source: ['cloud', 'deepseek', 'compat', 'local'].includes(aiModelSettings.highlightsModelSource)
                    ? aiModelSettings.highlightsModelSource
                    : 'cloud',
                llm_l1_scout_provider: normalizeLlmProvider(aiModelSettings.l1ScoutProvider || 'none'),
                llm_l1_scout_model: String(aiModelSettings.l1ScoutModel || '').trim()
                    || getDefaultModelForProvider(aiModelSettings.l1ScoutProvider),
                llm_l2_editor_provider: normalizeLlmProvider(aiModelSettings.l2EditorProvider || 'none'),
                llm_l2_editor_model: String(aiModelSettings.l2EditorModel || '').trim()
                    || getDefaultModelForProvider(aiModelSettings.l2EditorProvider),
            });
            resetOllamaMetaState();
            aiModelSettings.ollamaVisionCapability = 'unknown';
            aiModelSettings.ollamaVisionCheckedAt = '';
            aiModelSettings.ollamaVisionDetail = '';
            return { success: true };
        } catch (err) {
            console.error('Failed to save AI model settings:', err);
            return { success: false, error: err.message };
        } finally {
            saving.value = false;
        }
    }

    function getAiClearKeys(scope = 'all') {
        const keyGroups = {
            minimax: [
                'llm_minimax_enabled',
                'llm_minimax_base_url',
                'llm_minimax_model',
                'llm_minimax_api_key',
                'llm_minimax_timeout_seconds',
            ],
            deepseek: [
                'llm_deepseek_enabled',
                'llm_deepseek_base_url',
                'llm_deepseek_model',
                'llm_deepseek_api_key',
                'llm_deepseek_timeout_seconds',
            ],
            compat: [
                'llm_compat_enabled',
                'llm_compat_provider',
                'llm_compat_base_url',
                'llm_compat_model',
                'llm_compat_api_key',
                'llm_compat_timeout_seconds',
                'llm_compat_extra_params',
            ],
            ollama: [
                'llm_ollama_enabled',
                'llm_ollama_base_url',
                'llm_ollama_model',
                'llm_ollama_api_key',
                'llm_ollama_timeout_seconds',
                'llm_ollama_mode',
                'llm_ollama_disable_thinking',
                'llm_ollama_extra_params',
                'llm_ollama_vision_capability',
                'llm_ollama_vision_checked_at',
                'llm_ollama_vision_detail',
            ],
            strategy: [
                'llm_highlights_model_source',
                'llm_l1_scout_provider',
                'llm_l1_scout_model',
                'llm_l2_editor_provider',
                'llm_l2_editor_model',
            ],
        };
        if (scope === 'all') {
            return Object.values(keyGroups).flat();
        }
        return keyGroups[scope] || keyGroups.strategy;
    }

    function resetAiSettingsScope(scope = 'all') {
        if (scope === 'all' || scope === 'minimax') {
            aiModelSettings.minimaxEnabled = false;
            aiModelSettings.minimaxBaseUrl = 'https://api.minimaxi.com/v1';
            aiModelSettings.minimaxModel = 'MiniMax-Text-01';
            aiModelSettings.minimaxApiKey = '';
            aiModelSettings.minimaxTimeoutSeconds = 90;
        }
        if (scope === 'all' || scope === 'deepseek') {
            aiModelSettings.deepseekEnabled = false;
            aiModelSettings.deepseekBaseUrl = 'https://api.deepseek.com';
            aiModelSettings.deepseekModel = 'deepseek-chat';
            aiModelSettings.deepseekApiKey = '';
            aiModelSettings.deepseekTimeoutSeconds = 90;
        }
        if (scope === 'all' || scope === 'compat') {
            aiModelSettings.compatEnabled = false;
            aiModelSettings.compatProvider = 'OpenAI';
            aiModelSettings.compatBaseUrl = 'https://api.openai.com/v1';
            aiModelSettings.compatModel = 'gpt-4o-mini';
            aiModelSettings.compatApiKey = '';
            aiModelSettings.compatTimeoutSeconds = 90;
            aiModelSettings.compatExtraParams = '{}';
        }
        if (scope === 'all' || scope === 'ollama') {
            aiModelSettings.ollamaEnabled = false;
            aiModelSettings.ollamaBaseUrl = 'http://127.0.0.1:11434';
            aiModelSettings.ollamaModel = 'qwen2.5:7b';
            aiModelSettings.ollamaApiKey = '';
            aiModelSettings.ollamaTimeoutSeconds = 180;
            aiModelSettings.ollamaMode = 'native';
            aiModelSettings.ollamaDisableThinking = true;
            aiModelSettings.ollamaExtraParams = '{}';
            resetOllamaMetaState();
            aiModelSettings.ollamaVisionCapability = 'unknown';
            aiModelSettings.ollamaVisionCheckedAt = '';
            aiModelSettings.ollamaVisionDetail = '';
        }
        if (scope === 'all' || scope === 'strategy') {
            aiModelSettings.highlightsModelSource = 'cloud';
            aiModelSettings.l1ScoutProvider = 'none';
            aiModelSettings.l1ScoutModel = '';
            aiModelSettings.l2EditorProvider = 'none';
            aiModelSettings.l2EditorModel = '';
        }
    }

    // 清空 AI 模型设置
    async function clearAiModelSettings(scope = 'all') {
        try {
            await aiConfigApi.clearConfig(getAiClearKeys(scope));
            resetAiSettingsScope(scope);
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    }

    // 测试 AI 模型配置（MiniMax）
    async function testAiModelSettings() {
        try {
            const timeout = Math.max(5, Math.min(120, Number(aiModelSettings.minimaxTimeoutSeconds || 90)));
            const result = await aiConfigApi.testMinimax({
                llm_minimax_base_url: aiModelSettings.minimaxBaseUrl || '',
                llm_minimax_model: aiModelSettings.minimaxModel || '',
                llm_minimax_api_key: aiModelSettings.minimaxApiKey || '',
                llm_minimax_timeout_seconds: timeout,
            });
            return { success: !!result?.success, data: result };
        } catch (err) {
            const msg = err?.response?.data?.detail || err?.response?.data?.message || err.message || '测试失败';
            return { success: false, error: msg, data: err?.response?.data || null };
        }
    }

    // 测试 Ollama 配置
    async function testOllamaSettings() {
        try {
            const timeout = Math.max(10, Math.min(600, Number(aiModelSettings.ollamaTimeoutSeconds || 180)));
            const extraParamsResult = normalizeOllamaExtraParams(aiModelSettings.ollamaExtraParams);
            if (!extraParamsResult.ok) {
                return { success: false, error: extraParamsResult.error };
            }
            const result = await aiConfigApi.testOllama({
                llm_ollama_base_url: aiModelSettings.ollamaBaseUrl || '',
                llm_ollama_model: aiModelSettings.ollamaModel || '',
                llm_ollama_api_key: aiModelSettings.ollamaApiKey || '',
                llm_ollama_timeout_seconds: timeout,
                llm_ollama_mode: ['native', 'openai_compat'].includes(aiModelSettings.ollamaMode)
                    ? aiModelSettings.ollamaMode
                    : 'native',
                llm_ollama_disable_thinking: !!aiModelSettings.ollamaDisableThinking,
                llm_ollama_extra_params: extraParamsResult.value,
            });
            return { success: !!result?.success, data: result };
        } catch (err) {
            const msg = err?.response?.data?.detail || err?.response?.data?.message || err.message || '测试失败';
            return { success: false, error: msg, data: err?.response?.data || null };
        }
    }

    // 测试 OpenAI 兼容平台配置
    async function testCompatSettings() {
        try {
            const timeout = Math.max(5, Math.min(120, Number(aiModelSettings.compatTimeoutSeconds || 90)));
            const extraParamsResult = normalizeOllamaExtraParams(aiModelSettings.compatExtraParams);
            if (!extraParamsResult.ok) {
                return { success: false, error: extraParamsResult.error.replace('Ollama', '兼容平台') };
            }
            const result = await aiConfigApi.testOpenAiCompatible({
                llm_compat_provider: aiModelSettings.compatProvider || 'OpenAI',
                llm_compat_base_url: aiModelSettings.compatBaseUrl || '',
                llm_compat_model: aiModelSettings.compatModel || '',
                llm_compat_api_key: aiModelSettings.compatApiKey || '',
                llm_compat_timeout_seconds: timeout,
                llm_compat_extra_params: extraParamsResult.value,
            });
            return { success: !!result?.success, data: result };
        } catch (err) {
            const msg = err?.response?.data?.detail || err?.response?.data?.message || err.message || '测试失败';
            return { success: false, error: msg, data: err?.response?.data || null };
        }
    }

    async function detectOllamaVision() {
        try {
            const timeout = Math.max(10, Math.min(600, Number(aiModelSettings.ollamaTimeoutSeconds || 180)));
            const extraParamsResult = normalizeOllamaExtraParams(aiModelSettings.ollamaExtraParams);
            if (!extraParamsResult.ok) {
                return { success: false, error: extraParamsResult.error };
            }
            const result = await aiConfigApi.testOllamaVision({
                llm_ollama_base_url: aiModelSettings.ollamaBaseUrl || '',
                llm_ollama_model: aiModelSettings.ollamaModel || '',
                llm_ollama_api_key: aiModelSettings.ollamaApiKey || '',
                llm_ollama_timeout_seconds: timeout,
                llm_ollama_mode: ['native', 'openai_compat'].includes(aiModelSettings.ollamaMode)
                    ? aiModelSettings.ollamaMode
                    : 'native',
                llm_ollama_disable_thinking: !!aiModelSettings.ollamaDisableThinking,
                llm_ollama_extra_params: extraParamsResult.value,
            });
            const capability = String(result?.capability || (result?.vision_supported ? 'supported' : 'unsupported')).toLowerCase();
            aiModelSettings.ollamaVisionCapability = ['supported', 'unsupported', 'unknown'].includes(capability)
                ? capability
                : 'unknown';
            aiModelSettings.ollamaVisionCheckedAt = String(result?.checked_at || '').trim();
            aiModelSettings.ollamaVisionDetail = String(result?.detail || result?.preview || '').trim();
            return { success: true, data: result };
        } catch (err) {
            const msg = err?.response?.data?.detail || err?.response?.data?.message || err.message || '检测失败';
            aiModelSettings.ollamaVisionCapability = 'unknown';
            aiModelSettings.ollamaVisionDetail = String(msg || '').trim();
            return { success: false, error: msg, data: err?.response?.data || null };
        }
    }

    async function fetchOllamaCapabilities() {
        try {
            const timeout = Math.max(5, Math.min(120, Number(aiModelSettings.ollamaTimeoutSeconds || 30)));
            const result = await aiConfigApi.getOllamaCapabilities({
                llm_ollama_base_url: aiModelSettings.ollamaBaseUrl || '',
                llm_ollama_model: aiModelSettings.ollamaModel || '',
                llm_ollama_api_key: aiModelSettings.ollamaApiKey || '',
                llm_ollama_timeout_seconds: timeout,
                llm_ollama_mode: ['native', 'openai_compat'].includes(aiModelSettings.ollamaMode)
                    ? aiModelSettings.ollamaMode
                    : 'native',
            });
            const capability = String(result?.capability || 'unknown').toLowerCase();
            aiModelSettings.ollamaMetaCapability = ['supported', 'unsupported', 'unknown'].includes(capability)
                ? capability
                : 'unknown';
            aiModelSettings.ollamaMetaCheckedAt = String(result?.checked_at || '').trim();
            aiModelSettings.ollamaMetaDetail = String(result?.detail || '').trim();
            aiModelSettings.ollamaMetaCapabilities = Array.isArray(result?.capabilities)
                ? result.capabilities.map((item) => String(item || '').trim()).filter(Boolean)
                : [];
            aiModelSettings.ollamaMetaSupportsVision = result?.supports_vision === undefined ? null : !!result.supports_vision;
            aiModelSettings.ollamaMetaSupportsAudio = result?.supports_audio === undefined ? null : !!result.supports_audio;
            aiModelSettings.ollamaMetaSupportsTools = result?.supports_tools === undefined ? null : !!result.supports_tools;
            aiModelSettings.ollamaMetaSupportsThinking = result?.supports_thinking === undefined ? null : !!result.supports_thinking;
            aiModelSettings.ollamaMetaFamily = String(result?.meta?.family || '').trim();
            aiModelSettings.ollamaMetaParameterSize = String(result?.meta?.parameter_size || '').trim();
            aiModelSettings.ollamaMetaQuantizationLevel = String(result?.meta?.quantization_level || '').trim();
            aiModelSettings.ollamaMetaFormat = String(result?.meta?.format || '').trim();
            aiModelSettings.ollamaMetaArchitecture = String(result?.meta?.architecture || '').trim();
            aiModelSettings.ollamaMetaContextLength = Number.isFinite(Number(result?.meta?.context_length))
                ? Number(result.meta.context_length)
                : null;
            aiModelSettings.ollamaMetaRequires = String(result?.meta?.requires || '').trim();
            aiModelSettings.ollamaMetaModifiedAt = String(result?.meta?.modified_at || '').trim();
            return { success: true, data: result };
        } catch (err) {
            const msg = err?.response?.data?.detail || err?.response?.data?.message || err.message || '读取能力信息失败';
            resetOllamaMetaState();
            aiModelSettings.ollamaMetaDetail = String(msg || '').trim();
            return { success: false, error: msg, data: err?.response?.data || null };
        }
    }

    // 测试 DeepSeek 配置
    async function testDeepseekSettings() {
        try {
            const timeout = Math.max(5, Math.min(120, Number(aiModelSettings.deepseekTimeoutSeconds || 90)));
            const result = await aiConfigApi.testDeepseek({
                llm_deepseek_base_url: aiModelSettings.deepseekBaseUrl || '',
                llm_deepseek_model: aiModelSettings.deepseekModel || '',
                llm_deepseek_api_key: aiModelSettings.deepseekApiKey || '',
                llm_deepseek_timeout_seconds: timeout,
            });
            return { success: !!result?.success, data: result };
        } catch (err) {
            const msg = err?.response?.data?.detail || err?.response?.data?.message || err.message || '测试失败';
            return { success: false, error: msg, data: err?.response?.data || null };
        }
    }

    return {
        // 状态
        proxySettings,
        cookieStatus,
        notificationSettings,
        backgroundSettings,
        downloadSettings,
        aiModelSettings,
        loading,
        saving,

        // 方法
        loadAllSettings,
        loadProxySettings,
        saveProxySettings,
        testProxyConnection,
        clearProxySettings,
        loadCookieStatus,
        loadNotificationSettings,
        saveNotificationSettings,
        loadBackgroundSettings,
        setBackground,
        clearBackground,
        setBackgroundBlur,
        loadDownloadSettings,
        saveDownloadSettings,
        loadAiModelSettings,
        saveAiModelSettings,
        clearAiModelSettings,
        testAiModelSettings,
        testDeepseekSettings,
        testCompatSettings,
        testOllamaSettings,
        detectOllamaVision,
        fetchOllamaCapabilities,

        // Cookie 方法
        saveYoutubeCookie,
        saveBilibiliCookie,
        saveTiktokCookie,
        saveInstagramCookie,
        saveXCookie,
        saveNeteaseCookie,
        saveXiaohongshuCookie,
        clearCookie,
        updateCookieNow,
        setAutoUpdate
    };
});
