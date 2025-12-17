/**
 * Prome 小红书助手 - 后台服务脚本
 * 负责：WebSocket连接、定时任务调度、消息转发
 */

// ==================== 配置 ====================
const CONFIG = {
  // 后端服务地址（根据实际情况修改）
  BACKEND_URL: 'https://xiaohongshu-worker.zeabur.app',
  WS_URL: 'wss://xiaohongshu-worker.zeabur.app/ws',
  // 前端地址（用于获取 Supabase 配置）
  FRONTEND_URL: 'https://www.prome.live',
  // Supabase 配置 API
  SUPABASE_CONFIG_API: 'https://www.prome.live/api/supabase-config',
  // 重连配置
  RECONNECT_INTERVAL: 5000,
  MAX_RECONNECT_ATTEMPTS: 10,
  // 心跳配置
  HEARTBEAT_INTERVAL: 30000,
  // 定时任务检查间隔（毫秒）
  SCHEDULE_CHECK_INTERVAL: 60000,
  // 默认 Supabase 配置（备用）
  DEFAULT_SUPABASE: {
    url: 'https://lfjslsygnitdgdnfboiy.supabase.co',
    key: '' // 需要从前端获取
  }
};

// Worker Secret for API authentication (should match backend WORKER_SECRET env var)
const WORKER_SECRET = 'prome_xhs_2024';

// ==================== 状态管理 ====================
let state = {
  ws: null,
  apiToken: null,
  userId: null,
  isConnected: false,
  reconnectAttempts: 0,
  heartbeatTimer: null,
  publishQueue: [],
  currentTask: null,
};

// ==================== 工具函数 ====================
function log(message, data = null) {
  const timestamp = new Date().toISOString();
  console.log(`[Prome ${timestamp}] ${message}`, data || '');
}

function logError(message, error = null) {
  const timestamp = new Date().toISOString();
  console.error(`[Prome Error ${timestamp}] ${message}`, error || '');
}

/**
 * 从小红书 Cookie 生成稳定的账号 ID
 * 支持多种 Cookie 作为标识源：web_session, x-user-id, galaxy_creator_session_id, a1
 * @param {Array} cookies - 小红书 Cookie 数组
 * @returns {string} 稳定的账号 ID (xhs_xxxxxxxx)
 */
async function generateXhsAccountId(cookies) {
  // 按优先级尝试不同的 cookie
  const cookiePriority = [
    'web_session',                           // 主站 session
    'x-user-id-creator.xiaohongshu.com',    // 创作者中心用户ID
    'galaxy_creator_session_id',             // 创作者 session
    'a1'                                     // 设备持久ID
  ];

  let selectedCookie = null;
  for (const cookieName of cookiePriority) {
    const cookie = cookies.find(c => c.name === cookieName);
    if (cookie && cookie.value) {
      selectedCookie = cookie;
      log('Using cookie for account ID:', cookieName);
      break;
    }
  }

  if (!selectedCookie) {
    log('No suitable cookie found, using timestamp fallback');
    return 'xhs_temp_' + Date.now();
  }

  try {
    // 使用 SubtleCrypto API 生成 SHA-256 哈希
    const encoder = new TextEncoder();
    const data = encoder.encode(selectedCookie.value);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');

    // 返回 xhs_ 前缀 + 前16位哈希
    const accountId = 'xhs_' + hashHex.substring(0, 16);
    log('Generated stable account ID:', accountId);
    return accountId;
  } catch (error) {
    logError('Failed to generate account hash:', error);
    // 降级方案：使用时间戳
    return 'xhs_temp_' + Date.now();
  }
}

// ==================== 存储操作 ====================
async function saveState(key, value) {
  await chrome.storage.local.set({ [key]: value });
}

async function getState(key) {
  const result = await chrome.storage.local.get([key]);
  return result[key];
}

async function loadAllState() {
  const result = await chrome.storage.local.get([
    'apiToken',
    'userId',
    'publishQueue',
    'userInfo'
  ]);
  state.apiToken = result.apiToken || null;
  state.userId = result.userId || null;
  state.publishQueue = result.publishQueue || [];
  return result;
}

// ==================== Supabase 操作 ====================

/**
 * 从存储获取 Supabase 配置
 * 如果没有配置，会自动尝试从前端获取
 */
async function getSupabaseConfigFromStorage() {
  const result = await chrome.storage.local.get([
    'supabaseUrl',
    'supabaseKey',
    'userId',
    'supabaseConfigFetchedAt'
  ]);

  const config = {
    url: result.supabaseUrl || '',
    key: result.supabaseKey || '',
    userId: result.userId || ''
  };

  // 如果没有配置，或者配置超过24小时，尝试自动获取
  const configAge = Date.now() - (result.supabaseConfigFetchedAt || 0);
  const needRefresh = !config.url || !config.key || configAge > 24 * 60 * 60 * 1000;

  if (needRefresh) {
    log('Supabase config missing or outdated, attempting auto-fetch...');
    const autoConfig = await autoFetchSupabaseConfig();
    if (autoConfig) {
      return autoConfig;
    }
  }

  return config;
}

/**
 * 自动从前端获取 Supabase 配置
 */
async function autoFetchSupabaseConfig() {
  try {
    log('Fetching Supabase config...');

    // 方法0：尝试从后端 API 获取（已移除，确保使用前端同步配置）
    // 此处移除了后端 API 获取逻辑，回归到仅依赖前端 prome.live 注入配置的验证状态
    // 该部分代码被认为是"修改后"的不稳定代码


    log('Fetching Supabase config from frontend...');

    // 方法1：尝试从前端 API 获取
    try {
      const response = await fetch(CONFIG.SUPABASE_CONFIG_API, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json'
        }
      });

      if (response.ok) {
        const data = await response.json();
        if (data.url && data.key) {
          log('Got Supabase config from API');
          await saveSupabaseConfig(data.url, data.key, data.userId || '');
          return { url: data.url, key: data.key, userId: data.userId || '' };
        }
      }
    } catch (apiError) {
      log('API fetch failed, trying alternative method...', apiError.message);
    }

    // 方法2：尝试从打开的 prome.live 标签页获取
    try {
      const tabs = await chrome.tabs.query({ url: '*://*.prome.live/*' });
      for (const tab of tabs) {
        try {
          const result = await chrome.tabs.sendMessage(tab.id, {
            action: 'GET_SUPABASE_CONFIG'
          });
          if (result && result.url && result.key) {
            log('Got Supabase config from tab:', tab.id);
            await saveSupabaseConfig(result.url, result.key, result.userId || '');
            return { url: result.url, key: result.key, userId: result.userId || '' };
          }
        } catch (tabError) {
          // 标签页可能没有注入脚本，忽略
        }
      }
    } catch (tabsError) {
      log('Tab query failed:', tabsError.message);
    }

    // 方法3：使用默认 URL（key 仍需获取）
    if (CONFIG.DEFAULT_SUPABASE.url) {
      log('Using default Supabase URL, key still needed');
      return {
        url: CONFIG.DEFAULT_SUPABASE.url,
        key: CONFIG.DEFAULT_SUPABASE.key,
        userId: ''
      };
    }

    log('Could not auto-fetch Supabase config');
    return null;

  } catch (error) {
    logError('Auto-fetch Supabase config failed:', error);
    return null;
  }
}

/**
 * 保存 Supabase 配置
 */
async function saveSupabaseConfig(url, key, userId) {
  await chrome.storage.local.set({
    supabaseUrl: url,
    supabaseKey: key,
    userId: userId,
    supabaseConfigFetchedAt: Date.now()
  });
  log('Supabase config saved');
}

/**
 * 直接同步数据到 Supabase
 */
async function syncToSupabase(config, userId, publishedNotes, analyticsData) {
  const { url, key } = config;

  let notesCount = 0;
  let analyticsCount = 0;

  // 1. 保存/更新笔记主表
  if (publishedNotes && publishedNotes.length > 0) {
    const notesWithUser = publishedNotes.map(note => ({
      ...note,
      user_id: userId
    }));

    // 使用 upsert（基于 user_id + title_hash 去重）
    const notesResponse = await fetch(
      `${url}/rest/v1/xhs_published_notes?on_conflict=user_id,title_hash`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'apikey': key,
          'Authorization': `Bearer ${key}`,
          'Prefer': 'resolution=merge-duplicates,return=representation'
        },
        body: JSON.stringify(notesWithUser)
      }
    );

    if (!notesResponse.ok) {
      const errorText = await notesResponse.text();
      log('Notes upsert error:', errorText);
      // 如果是约束不存在，尝试普通插入
      if (errorText.includes('constraint')) {
        const insertResponse = await fetch(`${url}/rest/v1/xhs_published_notes`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'apikey': key,
            'Authorization': `Bearer ${key}`,
            'Prefer': 'return=representation'
          },
          body: JSON.stringify(notesWithUser)
        });
        if (insertResponse.ok) {
          const insertedNotes = await insertResponse.json();
          notesCount = insertedNotes.length;
        }
      }
    } else {
      const savedNotes = await notesResponse.json();
      notesCount = savedNotes.length;
    }

    log(`Saved ${notesCount} notes to Supabase`);
  }

  // 2. 保存分析数据（使用 upsert 避免重复）
  if (analyticsData && analyticsData.length > 0) {
    const analyticsWithUser = analyticsData.map(data => ({
      ...data,
      user_id: userId
    }));

    // 使用 upsert（基于 user_id + title_hash 去重）
    const analyticsResponse = await fetch(
      `${url}/rest/v1/xhs_note_analytics?on_conflict=user_id,title_hash`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'apikey': key,
          'Authorization': `Bearer ${key}`,
          'Prefer': 'resolution=merge-duplicates,return=representation'
        },
        body: JSON.stringify(analyticsWithUser)
      }
    );

    if (analyticsResponse.ok) {
      const savedAnalytics = await analyticsResponse.json();
      analyticsCount = savedAnalytics.length;
      log(`Saved ${analyticsCount} analytics records to Supabase`);
    } else {
      const errorText = await analyticsResponse.text();
      logError('Analytics save error:', errorText);
    }
  }

  return { notesCount, analyticsCount };
}

/**
 * 保存同步日志到 Supabase
 */
async function saveSyncLog(config, userId, syncType, notesCount, success, errorMessage = null) {
  const { url, key } = config;

  try {
    await fetch(`${url}/rest/v1/xhs_sync_logs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'apikey': key,
        'Authorization': `Bearer ${key}`
      },
      body: JSON.stringify({
        user_id: userId,
        sync_type: syncType,
        source: 'creator_center',
        notes_synced: notesCount,
        success: success,
        error_message: errorMessage,
        completed_at: new Date().toISOString()
      })
    });
  } catch (error) {
    logError('Failed to save sync log:', error);
  }
}

/**
 * 备选：发送到后端处理
 */
async function syncToBackend(userId, publishedNotes, analyticsData) {
  try {
    const response = await fetch(`${CONFIG.BACKEND_URL}/api/v1/analytics/sync`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        userId,
        publishedNotes,
        analyticsData,
        source: 'extension'
      })
    });

    if (!response.ok) {
      throw new Error(`Backend error: ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    logError('Backend sync failed:', error);
    return { success: false, error: error.message };
  }
}

// ==================== WebSocket 连接管理 ====================
function connectWebSocket() {
  if (!state.apiToken) {
    log('No API token, skipping WebSocket connection');
    return;
  }

  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    log('WebSocket already connected');
    return;
  }

  try {
    const wsUrl = `${CONFIG.WS_URL}?token=${state.apiToken}`;
    log('Connecting to WebSocket...', wsUrl);

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      log('WebSocket connected successfully');
      state.isConnected = true;
      state.reconnectAttempts = 0;

      // 更新连接状态
      saveState('connectionStatus', 'connected');

      // 启动心跳
      startHeartbeat();

      // 同步发布计划
      syncPublishPlan();

      // 通知popup更新状态
      notifyPopup({ type: 'CONNECTION_STATUS', connected: true });
    };

    state.ws.onmessage = async (event) => {
      try {
        const message = JSON.parse(event.data);
        log('Received message:', message);
        await handleServerMessage(message);
      } catch (error) {
        logError('Error parsing message:', error);
      }
    };

    state.ws.onclose = (event) => {
      log('WebSocket closed:', event.code, event.reason);
      state.isConnected = false;
      stopHeartbeat();
      saveState('connectionStatus', 'disconnected');
      notifyPopup({ type: 'CONNECTION_STATUS', connected: false });

      // 尝试重连
      scheduleReconnect();
    };

    state.ws.onerror = (error) => {
      logError('WebSocket error:', error);
      state.isConnected = false;
    };
  } catch (error) {
    logError('Failed to create WebSocket:', error);
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (state.reconnectAttempts >= CONFIG.MAX_RECONNECT_ATTEMPTS) {
    logError('Max reconnect attempts reached');
    notifyPopup({
      type: 'ERROR',
      message: '连接失败，请检查网络后重试'
    });
    return;
  }

  state.reconnectAttempts++;
  const delay = CONFIG.RECONNECT_INTERVAL * state.reconnectAttempts;
  log(`Scheduling reconnect in ${delay}ms (attempt ${state.reconnectAttempts})`);

  setTimeout(connectWebSocket, delay);
}

function disconnectWebSocket() {
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }
  state.isConnected = false;
  stopHeartbeat();
}

// ==================== 心跳机制 ====================
function startHeartbeat() {
  stopHeartbeat();
  state.heartbeatTimer = setInterval(() => {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ type: 'ping' }));
    }
  }, CONFIG.HEARTBEAT_INTERVAL);
}

function stopHeartbeat() {
  if (state.heartbeatTimer) {
    clearInterval(state.heartbeatTimer);
    state.heartbeatTimer = null;
  }
}

// ==================== 消息处理 ====================
async function handleServerMessage(message) {
  switch (message.type) {
    case 'pong':
      // 心跳响应，忽略
      break;

    case 'publish':
      // 收到发布指令
      await handlePublishCommand(message.data);
      break;

    case 'publish_plan':
      // 收到发布计划更新
      await handlePublishPlanUpdate(message.data);
      break;

    case 'cancel_task':
      // 取消任务
      await handleCancelTask(message.data.taskId);
      break;

    case 'check_login':
      // 检查登录状态
      await checkXhsLoginStatus();
      break;

    default:
      log('Unknown message type:', message.type);
  }
}

// ==================== 发布功能 ====================
async function handlePublishCommand(data) {
  log('Handling publish command:', data);

  state.currentTask = data;

  try {
    // 自动检测内容类型
    const hasVideo = (data.videos && data.videos.length > 0) || data.video;
    const contentType = hasVideo ? 'video' : 'image';

    // 根据内容类型选择发布页面
    const publishUrl = contentType === 'video'
      ? 'https://creator.xiaohongshu.com/publish/publish?from=menu&target=video'
      : 'https://creator.xiaohongshu.com/publish/publish?from=menu&target=image';

    log(`Opening ${contentType} publish page:`, publishUrl);

    const tab = await chrome.tabs.create({
      url: publishUrl,
      active: true
    });

    // 等待页面加载完成
    chrome.tabs.onUpdated.addListener(function listener(tabId, info) {
      if (tabId === tab.id && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);

        log('Publish page loaded, sending command to content script...');

        // 发送发布指令给content script
        setTimeout(() => {
          chrome.tabs.sendMessage(tabId, {
            action: 'EXECUTE_PUBLISH',
            data: data
          }).catch(err => {
            logError('Failed to send message to content script:', err);
            // 重试一次
            setTimeout(() => {
              chrome.tabs.sendMessage(tabId, {
                action: 'EXECUTE_PUBLISH',
                data: data
              }).catch(e => {
                logError('Retry also failed:', e);
                sendPublishResult(data.taskId, false, '无法与页面通信，请刷新页面重试');
              });
            }, 2000);
          });
        }, 3000); // 等待3秒确保页面和content script完全加载
      }
    });

  } catch (error) {
    logError('Failed to handle publish command:', error);
    sendPublishResult(data.taskId, false, error.message);
  }
}

function sendPublishResult(taskId, success, message = '') {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({
      type: 'publish_result',
      data: {
        taskId,
        success,
        message,
        timestamp: new Date().toISOString()
      }
    }));
  }

  state.currentTask = null;
}

// ==================== 定时发布功能 ====================
async function syncPublishPlan() {
  if (!state.apiToken) return;

  try {
    const response = await fetch(
      `${CONFIG.BACKEND_URL}/api/v1/publish-plan`,
      {
        headers: {
          'Authorization': `Bearer ${state.apiToken}`,
          'Content-Type': 'application/json'
        }
      }
    );

    if (response.ok) {
      const plan = await response.json();
      state.publishQueue = plan.tasks || [];
      await saveState('publishQueue', state.publishQueue);

      // 设置定时器
      setupScheduledTasks();

      log('Publish plan synced:', state.publishQueue.length, 'tasks');
    }
  } catch (error) {
    logError('Failed to sync publish plan:', error);
  }
}

async function handlePublishPlanUpdate(data) {
  state.publishQueue = data.tasks || [];
  await saveState('publishQueue', state.publishQueue);
  setupScheduledTasks();
  notifyPopup({ type: 'PLAN_UPDATED', tasks: state.publishQueue });
}

function setupScheduledTasks() {
  // 清除所有现有的定时器
  chrome.alarms.clearAll();

  // 为每个待发布任务设置定时器
  state.publishQueue.forEach(task => {
    if (task.status === 'pending' && task.scheduledTime) {
      const scheduledTime = new Date(task.scheduledTime).getTime();
      const now = Date.now();

      if (scheduledTime > now) {
        // 设置 Chrome Alarm
        chrome.alarms.create(`publish_${task.id}`, {
          when: scheduledTime
        });
        log(`Scheduled task ${task.id} for ${task.scheduledTime}`);
      }
    }
  });
}

// 监听定时器触发
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name.startsWith('publish_')) {
    const taskId = alarm.name.replace('publish_', '');
    const task = state.publishQueue.find(t => t.id === taskId);

    if (task && task.status === 'pending') {
      log('Executing scheduled task:', taskId);
      await handlePublishCommand(task);

      // 更新任务状态
      task.status = 'executing';
      await saveState('publishQueue', state.publishQueue);
    }
  }
});

async function handleCancelTask(taskId) {
  chrome.alarms.clear(`publish_${taskId}`);

  const taskIndex = state.publishQueue.findIndex(t => t.id === taskId);
  if (taskIndex !== -1) {
    state.publishQueue[taskIndex].status = 'cancelled';
    await saveState('publishQueue', state.publishQueue);
  }

  notifyPopup({ type: 'TASK_CANCELLED', taskId });
}

// ==================== 登录状态检查 ====================
async function checkXhsLoginStatus() {
  try {
    log('Checking XHS login status...');

    // 方法1: 检查 Cookie（最可靠）
    let cookieResult = await checkLoginByCookies();
    log('Cookie check result:', cookieResult);

    // 方法2: 如果 Cookie 检测不确定，尝试通过 Content Script 检测页面
    if (!cookieResult.certain) {
      const pageResult = await checkLoginByPage();
      log('Page check result:', pageResult);

      if (pageResult.checked) {
        cookieResult.isLoggedIn = pageResult.isLoggedIn;
        cookieResult.method = 'page';
      }
    }

    const isLoggedIn = cookieResult.isLoggedIn;

    log('Final XHS login status:', isLoggedIn ? 'logged in' : 'not logged in', cookieResult);

    // 发送状态到后端
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({
        type: 'login_status',
        data: {
          isLoggedIn,
          method: cookieResult.method,
          cookies: cookieResult.cookies
        }
      }));
    }

    return isLoggedIn;
  } catch (error) {
    logError('Failed to check login status:', error);
    return false;
  }
}

async function checkLoginByCookies() {
  try {
    // 方法1: 使用 URL 参数获取 cookie（更可靠）
    let allCookies = [];

    const urls = [
      'https://www.xiaohongshu.com',
      'https://creator.xiaohongshu.com',
      'https://xiaohongshu.com'
    ];

    for (const url of urls) {
      try {
        const cookies = await chrome.cookies.getAll({ url });
        log(`Cookies from ${url}:`, cookies.length);
        allCookies = allCookies.concat(cookies);
      } catch (e) {
        log(`Failed to get cookies from ${url}:`, e.message);
      }
    }

    // 方法2: 也尝试 domain 参数
    const domains = ['.xiaohongshu.com', 'xiaohongshu.com'];
    for (const domain of domains) {
      try {
        const cookies = await chrome.cookies.getAll({ domain });
        log(`Cookies from domain ${domain}:`, cookies.length);
        allCookies = allCookies.concat(cookies);
      } catch (e) {
        log(`Failed to get cookies from domain ${domain}:`, e.message);
      }
    }

    // 去重
    const uniqueCookies = [...new Map(allCookies.map(c => [`${c.name}_${c.domain}`, c])).values()];
    const cookieNames = [...new Set(uniqueCookies.map(c => c.name))];

    log('Total unique cookies found:', cookieNames.length);
    log('Cookie names:', cookieNames);

    // 检查关键cookie - 根据你提供的实际cookie列表
    const loginCookies = [
      'a1',                    // 主要登录标识
      'web_session',           // 会话
      'webId',                 // 用户标识
      'gid',                   // 
      'customerClientId',      // 客户端ID
      'access-token-creator',  // 创作者token
      'customer-sso-sid',      // SSO会话
      'x-user-id-creator',     // 用户ID
      'galaxy_creator_session_id',  // 创作者会话
    ];

    const foundLoginCookies = loginCookies.filter(name => cookieNames.includes(name));

    log('Found login cookies:', foundLoginCookies);

    // 判断登录状态 - 根据你的实际cookie情况调整
    const hasA1 = cookieNames.includes('a1');
    const hasWebId = cookieNames.includes('webId');
    const hasGid = cookieNames.includes('gid');
    const hasCreatorToken = cookieNames.includes('access-token-creator') ||
      cookieNames.includes('x-user-id-creator');
    const hasCustomerClient = cookieNames.includes('customerClientId');

    let isLoggedIn = false;
    let certain = false;

    // 你的cookie显示有 a1, webId, gid, customerClientId, access-token-creator 等
    // 这些都是登录后才有的cookie
    if (hasA1) {
      isLoggedIn = true;
      certain = true;
      log('Logged in: found a1 cookie');
    } else if (hasCreatorToken) {
      isLoggedIn = true;
      certain = true;
      log('Logged in: found creator token');
    } else if (hasWebId && hasGid && hasCustomerClient) {
      isLoggedIn = true;
      certain = true;
      log('Logged in: found multiple login indicators');
    } else if (foundLoginCookies.length >= 2) {
      isLoggedIn = true;
      certain = false;
      log('Probably logged in: found some login cookies');
    }

    return {
      isLoggedIn,
      certain,
      method: 'cookie',
      cookies: cookieNames,
      foundLoginCookies,
      totalCookies: uniqueCookies.length
    };
  } catch (error) {
    logError('Cookie check error:', error);
    return {
      isLoggedIn: false,
      certain: false,
      method: 'cookie',
      error: error.message,
      cookies: []
    };
  }
}

async function checkLoginByPage() {
  try {
    // 查找小红书相关的标签页
    const tabs = await chrome.tabs.query({
      url: ['https://creator.xiaohongshu.com/*', 'https://www.xiaohongshu.com/*']
    });

    if (tabs.length === 0) {
      log('No XHS tabs found');
      return { checked: false };
    }

    // 向第一个找到的标签页发送消息
    const tab = tabs[0];
    log('Checking login via tab:', tab.id, tab.url);

    try {
      const response = await chrome.tabs.sendMessage(tab.id, { action: 'CHECK_LOGIN' });
      return {
        checked: true,
        isLoggedIn: response?.isLoggedIn ?? false
      };
    } catch (e) {
      log('Failed to communicate with content script:', e.message);
      return { checked: false };
    }
  } catch (error) {
    logError('Page check error:', error);
    return { checked: false };
  }
}

// ==================== Popup 通信 ====================
function notifyPopup(message) {
  chrome.runtime.sendMessage(message).catch(() => {
    // Popup可能没有打开，忽略错误
  });
}

// 监听来自popup和content script的消息
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  log('Received runtime message:', message);

  (async () => {
    try {
      switch (message.action) {
        case 'SET_TOKEN':
          state.apiToken = message.token;
          state.userId = message.userId;
          await saveState('apiToken', message.token);
          await saveState('userId', message.userId);
          connectWebSocket();

          // 立即获取 Supabase 配置
          await autoFetchSupabaseConfig();

          sendResponse({ success: true });
          break;

        case 'DISCONNECT':
          disconnectWebSocket();
          state.apiToken = null;
          await saveState('apiToken', null);
          sendResponse({ success: true });
          break;

        case 'GET_STATUS':
          sendResponse({
            isConnected: state.isConnected,
            apiToken: state.apiToken,
            publishQueue: state.publishQueue,
            currentTask: state.currentTask
          });
          break;

        case 'CHECK_XHS_LOGIN':
          const loginResult = await checkLoginByCookies();

          // 如果 Cookie 检测不确定，尝试页面检测
          if (!loginResult.certain) {
            const pageResult = await checkLoginByPage();
            if (pageResult.checked) {
              loginResult.isLoggedIn = loginResult.isLoggedIn || pageResult.isLoggedIn;
              loginResult.pageCheck = pageResult;
            }
          }

          sendResponse({
            isLoggedIn: loginResult.isLoggedIn,
            method: loginResult.method,
            cookies: loginResult.cookies || [],
            foundLoginCookies: loginResult.foundLoginCookies || [],
            certain: loginResult.certain
          });
          break;

        case 'GET_XHS_ACCOUNT_ID':
          // 获取小红书账号的稳定 ID（从 Cookie 哈希）
          try {
            // 尝试多个可能的域名
            let xhsCookies = await chrome.cookies.getAll({ domain: '.xiaohongshu.com' });
            log('Cookies from .xiaohongshu.com:', xhsCookies.length);

            if (!xhsCookies.length) {
              xhsCookies = await chrome.cookies.getAll({ domain: 'xiaohongshu.com' });
              log('Cookies from xiaohongshu.com:', xhsCookies.length);
            }

            if (!xhsCookies.length) {
              xhsCookies = await chrome.cookies.getAll({ domain: 'creator.xiaohongshu.com' });
              log('Cookies from creator.xiaohongshu.com:', xhsCookies.length);
            }

            // 尝试获取所有 cookie 并过滤
            if (!xhsCookies.length) {
              const allCookies = await chrome.cookies.getAll({});
              xhsCookies = allCookies.filter(c => c.domain.includes('xiaohongshu'));
              log('Filtered xiaohongshu cookies:', xhsCookies.length);
            }

            // 列出所有 cookie 名称便于调试
            const cookieNames = xhsCookies.map(c => c.name);
            log('Available cookie names:', cookieNames);

            const accountId = await generateXhsAccountId(xhsCookies);
            log('Generated account ID:', accountId);
            sendResponse({ success: true, accountId });
          } catch (error) {
            logError('Failed to generate account ID:', error);
            sendResponse({ success: false, accountId: null, error: error.message });
          }
          break;

        case 'MANUAL_PUBLISH':
          await handlePublishCommand(message.data);
          sendResponse({ success: true });
          break;

        case 'ADD_SCHEDULED_TASK':
          state.publishQueue.push(message.task);
          await saveState('publishQueue', state.publishQueue);
          setupScheduledTasks();
          sendResponse({ success: true });
          break;

        case 'REMOVE_SCHEDULED_TASK':
          await handleCancelTask(message.taskId);
          sendResponse({ success: true });
          break;

        case 'PUBLISH_RESULT':
          // 来自content script的发布结果
          sendPublishResult(
            message.taskId,
            message.success,
            message.message
          );

          // 更新本地任务状态
          const task = state.publishQueue.find(t => t.id === message.taskId);
          if (task) {
            task.status = message.success ? 'completed' : 'failed';
            task.completedAt = new Date().toISOString();
            task.error = message.message;
            await saveState('publishQueue', state.publishQueue);
          }

          notifyPopup({
            type: 'PUBLISH_COMPLETE',
            taskId: message.taskId,
            success: message.success,
            message: message.message
          });
          sendResponse({ success: true });
          break;

        case 'SYNC_PLAN':
          await syncPublishPlan();
          sendResponse({ success: true, tasks: state.publishQueue });
          break;

        // ===== 新增：打开发布页面（从前端中转模式调用）=====
        case 'OPEN_PUBLISH_PAGE':
          log('Opening publish page for frontend relay mode');
          try {
            // 检测内容类型
            const hasVideoContent = (message.data?.videos && message.data.videos.length > 0) || message.data?.video;
            const targetType = hasVideoContent ? 'video' : 'image';
            const publishPageUrl = `https://creator.xiaohongshu.com/publish/publish?from=menu&target=${targetType}`;

            log(`Opening ${targetType} publish page:`, publishPageUrl);

            // 创建新标签页
            const newTab = await chrome.tabs.create({
              url: publishPageUrl,
              active: true
            });

            // 如果有待发布数据，存储起来
            if (message.data) {
              await chrome.storage.local.set({
                pendingPublishData: message.data,
                pendingPublishTabId: newTab.id
              });
              log('Stored pending publish data for tab:', newTab.id);
            }

            sendResponse({ success: true, tabId: newTab.id });
          } catch (error) {
            logError('Failed to open publish page:', error);
            sendResponse({ success: false, error: error.message });
          }
          break;

        // ===== 新增：获取小红书 Cookies（用于 Cookie 同步）=====
        case 'GET_XHS_COOKIES':
          log('Getting XHS cookies for sync');
          try {
            const cookieResult = await checkLoginByCookies();

            // 获取完整的 cookie 对象（不只是名称）
            let fullCookies = [];
            const urls = [
              'https://www.xiaohongshu.com',
              'https://creator.xiaohongshu.com'
            ];

            for (const url of urls) {
              try {
                const cookies = await chrome.cookies.getAll({ url });
                fullCookies = fullCookies.concat(cookies);
              } catch (e) {
                log(`Failed to get cookies from ${url}:`, e.message);
              }
            }

            // Method 2: By domain (to capture cookies like web_session on .xiaohongshu.com)
            const cookieDomains = [
              '.xiaohongshu.com',
              'xiaohongshu.com',
              'www.xiaohongshu.com'
            ];

            for (const domain of cookieDomains) {
              try {
                const cookies = await chrome.cookies.getAll({ domain });
                log(`Cookies from domain ${domain}: ${cookies.length}`);
                fullCookies = fullCookies.concat(cookies);
              } catch (e) {
                log(`Failed to get cookies from domain ${domain}:`, e.message);
              }
            }

            // 去重并转换格式
            const uniqueCookies = [...new Map(fullCookies.map(c => [`${c.name}_${c.domain}`, c])).values()];
            const formattedCookies = uniqueCookies.map(c => ({
              name: c.name,
              value: c.value,
              domain: c.domain,
              path: c.path,
              secure: c.secure,
              httpOnly: c.httpOnly,
              sameSite: c.sameSite
            }));

            // 🔥 DEBUG: Check for web_session specifically
            const webSessionCookie = formattedCookies.find(c => c.name === 'web_session');
            if (webSessionCookie) {
              log(`✅ web_session FOUND! Domain: ${webSessionCookie.domain}, Value prefix: ${webSessionCookie.value.substring(0, 20)}...`);
            } else {
              log(`❌ web_session NOT FOUND in ${formattedCookies.length} cookies`);
              log(`Available cookie names: ${formattedCookies.map(c => c.name).join(', ')}`);
            }

            sendResponse({
              success: true,
              cookies: formattedCookies,
              isLoggedIn: cookieResult.isLoggedIn
            });
          } catch (error) {
            logError('Failed to get XHS cookies:', error);
            sendResponse({ success: false, error: error.message, cookies: [] });
          }
          break;

        // ===== 新增：同步分析数据到 Supabase =====
        case 'SYNC_ANALYTICS_TO_SUPABASE':
          log('Syncing analytics data to Supabase');
          try {
            const { userId, publishedNotes, analyticsData, syncType } = message.data;

            // 获取 Supabase 配置
            const supabaseConfig = await getSupabaseConfigFromStorage();

            if (!supabaseConfig.url || !supabaseConfig.key) {
              // 如果没有 Supabase 配置，发送到后端处理
              log('No Supabase config, sending to backend');
              const backendResult = await syncToBackend(userId, publishedNotes, analyticsData);
              sendResponse(backendResult);
              break;
            }

            // 直接保存到 Supabase
            const result = await syncToSupabase(
              supabaseConfig,
              userId,
              publishedNotes,
              analyticsData
            );

            // 记录同步日志
            await saveSyncLog(supabaseConfig, userId, syncType, publishedNotes.length, true);

            sendResponse({
              success: true,
              savedNotes: result.notesCount,
              savedAnalytics: result.analyticsCount
            });
          } catch (error) {
            logError('Failed to sync analytics:', error);
            sendResponse({ success: false, error: error.message });
          }
          break;

        // ===== 新增：获取 Supabase 配置 =====
        case 'GET_SUPABASE_CONFIG':
          try {
            const config = await getSupabaseConfigFromStorage();
            sendResponse({ success: true, config });
          } catch (error) {
            sendResponse({ success: false, error: error.message });
          }
          break;

        // ===== 新增：保存 Supabase 配置 =====
        case 'SAVE_SUPABASE_CONFIG':
          try {
            await chrome.storage.local.set({
              supabaseUrl: message.data.url,
              supabaseKey: message.data.key,
              userId: message.data.userId
            });
            sendResponse({ success: true });
          } catch (error) {
            sendResponse({ success: false, error: error.message });
          }
          break;

        // ===== 🔥 新增：同步 Cookies 到后端 =====
        case 'SYNC_COOKIES_TO_BACKEND':
          log('Syncing cookies to backend...');
          try {
            const targetUserId = message.userId;
            if (!targetUserId) {
              sendResponse({ success: false, error: 'userId is required' });
              break;
            }

            // 1. 获取小红书 Cookies - 使用多种方式确保获取 web_session
            let fullCookies = [];

            // Method 1: By URL
            const cookieUrls = [
              'https://www.xiaohongshu.com',
              'https://creator.xiaohongshu.com',
              'https://edith.xiaohongshu.com'
            ];

            for (const url of cookieUrls) {
              try {
                const cookies = await chrome.cookies.getAll({ url });
                log(`Cookies from URL ${url}: ${cookies.length}`);
                fullCookies = fullCookies.concat(cookies);
              } catch (e) {
                log(`Failed to get cookies from ${url}:`, e.message);
              }
            }

            // Method 2: By domain (to capture cookies like web_session on .xiaohongshu.com)
            const cookieDomains = [
              '.xiaohongshu.com',
              'xiaohongshu.com',
              'www.xiaohongshu.com'
            ];

            for (const domain of cookieDomains) {
              try {
                const cookies = await chrome.cookies.getAll({ domain });
                log(`Cookies from domain ${domain}: ${cookies.length}`);
                fullCookies = fullCookies.concat(cookies);
              } catch (e) {
                log(`Failed to get cookies from domain ${domain}:`, e.message);
              }
            }

            // 去重 (by name + domain)
            const uniqueCookies = [...new Map(fullCookies.map(c => [`${c.name}_${c.domain}`, c])).values()];
            const formattedCookies = uniqueCookies.map(c => ({
              name: c.name,
              value: c.value,
              domain: c.domain,
              path: c.path,
              secure: c.secure,
              httpOnly: c.httpOnly,
              sameSite: c.sameSite
            }));

            // 🔥 Check if we have the critical web_session cookie
            const hasWebSession = formattedCookies.some(c => c.name === 'web_session');
            const foundNames = formattedCookies.map(c => `${c.name} (${c.domain})`);
            log(`Total unique cookies: ${formattedCookies.length}`);
            log(`Cookie names found: ${JSON.stringify(foundNames)}`);
            log(`Has web_session: ${hasWebSession}`);

            if (formattedCookies.length === 0) {
              sendResponse({ success: false, error: 'No cookies found' });
              break;
            }

            log(`Found ${formattedCookies.length} cookies, syncing to backend...`);

            // 2. 发送到后端
            const response = await fetch(`${CONFIG.BACKEND_URL}/api/v1/login/sync`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${WORKER_SECRET || 'default_secret_key'}`
              },
              body: JSON.stringify({
                user_id: targetUserId,
                cookies: formattedCookies,
                ua: navigator.userAgent
              })
            });

            if (!response.ok) {
              const errorText = await response.text();
              log('Backend sync error:', errorText);
              sendResponse({ success: false, error: `Backend error: ${response.status}` });
              break;
            }

            const result = await response.json();
            log('Cookie sync result:', result);
            sendResponse({ success: true, result });
          } catch (error) {
            logError('Failed to sync cookies to backend:', error);
            sendResponse({ success: false, error: error.message });
          }
          break;

        default:
          sendResponse({ error: 'Unknown action' });
      }
    } catch (error) {
      logError('Error handling message:', error);
      sendResponse({ error: error.message });
    }
  })();

  return true; // 保持消息通道开放
});

// ==================== 初始化 ====================
async function initialize() {
  log('Initializing Prome extension...');

  // 加载保存的状态
  await loadAllState();

  // 如果有token，尝试连接
  if (state.apiToken) {
    connectWebSocket();
  }

  // 设置定时同步发布计划
  setInterval(syncPublishPlan, CONFIG.SCHEDULE_CHECK_INTERVAL);

  log('Initialization complete');
}

// 启动
initialize();

// ==================== 标签页更新监听 ====================
// 监听标签页加载完成，执行待发布任务（用于前端中转模式）
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  // 只在页面完全加载后处理
  if (changeInfo.status !== 'complete') return;

  // 检查是否是小红书发布页面
  if (!tab.url || !tab.url.includes('creator.xiaohongshu.com/publish')) return;

  // 检查是否有待发布数据
  const storage = await chrome.storage.local.get(['pendingPublishData', 'pendingPublishTabId']);

  if (storage.pendingPublishData) {
    log('Found pending publish data, checking if this is the target tab...');

    // 可选：检查是否是我们打开的标签页
    // if (storage.pendingPublishTabId && storage.pendingPublishTabId !== tabId) {
    //   log('Tab ID mismatch, skipping');
    //   return;
    // }

    log('Sending pending publish data to tab:', tabId);

    // 等待一段时间确保 content script 已加载
    setTimeout(async () => {
      try {
        await chrome.tabs.sendMessage(tabId, {
          action: 'EXECUTE_PUBLISH',
          data: storage.pendingPublishData
        });

        log('Pending publish data sent successfully');

        // 清除待发布数据
        await chrome.storage.local.remove(['pendingPublishData', 'pendingPublishTabId']);

      } catch (error) {
        logError('Failed to send pending publish data:', error);

        // 重试一次
        setTimeout(async () => {
          try {
            await chrome.tabs.sendMessage(tabId, {
              action: 'EXECUTE_PUBLISH',
              data: storage.pendingPublishData
            });
            await chrome.storage.local.remove(['pendingPublishData', 'pendingPublishTabId']);
          } catch (retryError) {
            logError('Retry also failed:', retryError);
          }
        }, 3000);
      }
    }, 3000); // 等待3秒
  }
});

// 监听扩展安装/更新
chrome.runtime.onInstalled.addListener((details) => {
  log('Extension installed/updated:', details.reason);

  if (details.reason === 'install') {
    // 首次安装，打开设置页面
    chrome.tabs.create({
      url: 'popup/popup.html'
    });
  }
});

// ==================== Step Executor for AI Control Center ====================
// Phase 1 MVP: 从 Supabase 拉取 pending steps 并执行

const STEP_EXECUTOR_CONFIG = {
  POLL_INTERVAL: 30000,  // 30 秒
  LOCK_OWNER: 'prome-extension-v1.1.0',
  SUPPORTED_STEP_TYPES: ['publish', 'fetch_metrics'],
};

let stepExecutorState = {
  isRunning: false,
  pollTimer: null,
  currentStep: null,
  xhsAccountId: null,
};

/**
 * 初始化 Step Executor
 */
async function initStepExecutor(xhsAccountId) {
  log('[StepExecutor] Initializing with account:', xhsAccountId);
  stepExecutorState.xhsAccountId = xhsAccountId;

  if (stepExecutorState.isRunning) {
    log('[StepExecutor] Already running');
    return;
  }

  stepExecutorState.isRunning = true;
  startStepPolling();
  log('[StepExecutor] Initialized');
}

function stopStepExecutor() {
  stepExecutorState.isRunning = false;
  if (stepExecutorState.pollTimer) {
    clearInterval(stepExecutorState.pollTimer);
    stepExecutorState.pollTimer = null;
  }
}

function startStepPolling() {
  if (stepExecutorState.pollTimer) {
    clearInterval(stepExecutorState.pollTimer);
  }
  pollPendingSteps();
  stepExecutorState.pollTimer = setInterval(pollPendingSteps, STEP_EXECUTOR_CONFIG.POLL_INTERVAL);
}

async function pollPendingSteps() {
  if (!stepExecutorState.isRunning || !stepExecutorState.xhsAccountId || stepExecutorState.currentStep) {
    return;
  }

  try {
    const config = await getSupabaseConfigFromStorage();
    if (!config.url || !config.key) return;

    const now = new Date().toISOString();
    const response = await fetch(
      `${config.url}/rest/v1/xhs_task_steps?` +
      `xhs_account_id=eq.${stepExecutorState.xhsAccountId}&` +
      `status=eq.pending&` +
      `step_type=in.(${STEP_EXECUTOR_CONFIG.SUPPORTED_STEP_TYPES.join(',')})&` +
      `or=(scheduled_at.is.null,scheduled_at.lte.${encodeURIComponent(now)})&` +
      `order=created_at.asc&limit=1`,
      {
        headers: {
          'apikey': config.key,
          'Authorization': `Bearer ${config.key}`,
          'Content-Type': 'application/json'
        }
      }
    );

    if (!response.ok) return;
    const steps = await response.json();
    if (steps.length === 0) return;

    const step = steps[0];
    log('[StepExecutor] Found pending step:', step.id, step.step_type);
    await executeStepWithLock(step, config);

  } catch (error) {
    logError('[StepExecutor] Poll error:', error);
  }
}

async function executeStepWithLock(step, config) {
  try {
    // Lock
    const lockResponse = await fetch(`${config.url}/rest/v1/rpc/lock_task_step`, {
      method: 'POST',
      headers: {
        'apikey': config.key,
        'Authorization': `Bearer ${config.key}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ p_step_id: step.id, p_lock_owner: STEP_EXECUTOR_CONFIG.LOCK_OWNER })
    });

    if (!lockResponse.ok) {
      log('[StepExecutor] Failed to lock step');
      return;
    }

    const lockResult = await lockResponse.json();
    const lockedStep = Array.isArray(lockResult) && lockResult.length > 0 ? lockResult[0] : null;
    if (!lockedStep) return;

    stepExecutorState.currentStep = lockedStep;
    log('[StepExecutor] Step locked:', lockedStep.id);

    // Execute
    let result;
    switch (step.step_type) {
      case 'publish':
        result = await executePublishStepHandler(lockedStep, config);
        break;
      case 'fetch_metrics':
        result = await executeFetchMetricsHandler(lockedStep, config);
        break;
      default:
        result = { success: false, error: 'Unsupported step type' };
    }

    // Finish
    await fetch(`${config.url}/rest/v1/rpc/finish_task_step`, {
      method: 'POST',
      headers: {
        'apikey': config.key,
        'Authorization': `Bearer ${config.key}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        p_step_id: lockedStep.id,
        p_status: result.success ? 'succeeded' : 'failed',
        p_output_payload: result.output || {},
        p_usage: result.usage || {},
        p_provider: 'prome-extension',
        p_provider_run_id: null,
        p_error: result.error ? { error: result.error } : null
      })
    });

    log('[StepExecutor] Step completed:', lockedStep.id, result.success ? 'succeeded' : 'failed');

    // Refresh task status
    await fetch(`${config.url}/rest/v1/rpc/refresh_task_status`, {
      method: 'POST',
      headers: {
        'apikey': config.key,
        'Authorization': `Bearer ${config.key}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ p_task_id: lockedStep.task_id })
    });

  } catch (error) {
    logError('[StepExecutor] Execute error:', error);
  } finally {
    stepExecutorState.currentStep = null;
  }
}

// Real publish handler - fetches task data and triggers existing publish flow
async function executePublishStepHandler(step, config) {
  log('[StepExecutor] Executing publish step (real)...');

  try {
    // 1. 获取关联的 Task 信息
    const taskResponse = await fetch(
      `${config.url}/rest/v1/xhs_daily_tasks?id=eq.${step.task_id}&select=*`,
      {
        headers: {
          'apikey': config.key,
          'Authorization': `Bearer ${config.key}`,
          'Content-Type': 'application/json'
        }
      }
    );

    if (!taskResponse.ok) {
      throw new Error('Failed to fetch task: ' + taskResponse.status);
    }

    const tasks = await taskResponse.json();
    if (tasks.length === 0) {
      throw new Error('Task not found');
    }

    const task = tasks[0];
    log('[StepExecutor] Task data:', task.title);

    // 2. 检查 review_mode
    const reviewMode = task.metadata?.review_mode || 'auto_publish';

    if (reviewMode === 'manual_confirm' || reviewMode === 'human_review') {
      // 需要用户手动确认 - 创建通知
      log('[StepExecutor] Publish requires manual confirmation, showing notification');

      chrome.notifications.create(`publish_confirm_${step.id}`, {
        type: 'basic',
        iconUrl: 'icons/icon128.png',
        title: '📝 发布确认',
        message: `待发布: ${task.title || '(无标题)'}\n点击确认后发布`,
        priority: 2,
        requireInteraction: true
      });

      // 保存待发布数据供用户点击通知时使用
      await chrome.storage.local.set({
        [`pendingPublish_${step.id}`]: {
          stepId: step.id,
          taskId: task.id,
          title: task.title || '',
          content: task.content || '',
          images: task.image_urls || [],
          video: null,
          reviewMode: reviewMode
        }
      });

      // 🔥 返回等待状态 - 不执行自动发布
      // 用户点击通知后会触发 REVIEW_CONFIRM_RESPONSE 处理
      return {
        success: true,
        output: {
          status: 'pending_review',
          message: '等待用户确认发布',
          notification_id: `publish_confirm_${step.id}`,
          review_mode: reviewMode
        }
      };
    }

    // 3. auto_publish 模式：直接发布
    log('[StepExecutor] Auto-publish mode, proceeding...');

    // 构建发布数据
    const publishData = {
      taskId: step.id,  // 使用 step_id 作为 taskId
      title: task.title || '',
      content: task.content || '',
      images: task.image_urls || [],
      video: null,
      videos: [],
      stepExecutor: true,  // 标记来自 step executor
      orchestratorTaskId: task.id
    };

    log('[StepExecutor] Publishing with data:', publishData.title);

    // 4. 打开发布页面并执行
    return await executePublishFlow(publishData, step, config);

  } catch (error) {
    logError('[StepExecutor] Publish step failed:', error);
    return {
      success: false,
      error: error.message
    };
  }
}

// 执行实际发布流程
async function executePublishFlow(data, step, config) {
  return new Promise((resolve) => {
    // 设置超时
    const timeout = setTimeout(() => {
      resolve({
        success: false,
        error: 'Publish timeout after 5 minutes'
      });
    }, 5 * 60 * 1000);

    // 监听发布结果
    const resultListener = (message, sender, sendResponse) => {
      if (message.action === 'PUBLISH_RESULT' && message.taskId === data.taskId) {
        clearTimeout(timeout);
        chrome.runtime.onMessage.removeListener(resultListener);

        log('[StepExecutor] Received publish result:', message);

        if (message.success) {
          resolve({
            success: true,
            output: {
              note_id: message.feedId || message.noteId || 'unknown',
              note_url: message.noteUrl || null,
              published_at: new Date().toISOString()
            }
          });
        } else {
          resolve({
            success: false,
            error: message.message || 'Publish failed'
          });
        }
      }
    };

    chrome.runtime.onMessage.addListener(resultListener);

    // 触发发布流程
    handlePublishCommand(data);
  });
}

// Real fetch_metrics handler - Phase 2: 主动抓取数据
async function executeFetchMetricsHandler(step, config) {
  log('[StepExecutor] Executing fetch_metrics step...');

  const noteId = step.input_snapshot?.note_id;
  const feedId = step.input_snapshot?.feed_id;
  const titleHash = step.input_snapshot?.title_hash;
  const metricsWindow = step.input_snapshot?.metrics_window || '24h';

  // 如果没有有效的标识符，返回空数据
  if (!feedId && !titleHash && (!noteId || noteId === 'unknown' || noteId.startsWith('mock_'))) {
    log('[StepExecutor] No valid identifier for fetch_metrics, returning empty data');
    return {
      success: true,
      output: {
        note_id: noteId || 'unknown',
        metrics_window: metricsWindow,
        fetched_at: new Date().toISOString(),
        likes: 0,
        collects: 0,
        comments: 0,
        views: 0,
        impressions: 0,
        mock: true,
        reason: 'no_valid_identifier'
      }
    };
  }

  try {
    log('[StepExecutor] Starting active metrics fetch...');
    log('[StepExecutor] Target:', { feedId, titleHash, noteId });

    // 1. 打开小红书创作者中心统计页面
    const statisticsUrl = 'https://creator.xiaohongshu.com/statistics/data-analysis';

    log('[StepExecutor] Opening statistics page:', statisticsUrl);

    const tab = await chrome.tabs.create({
      url: statisticsUrl,
      active: false  // 后台打开，不干扰用户
    });

    log('[StepExecutor] Tab created:', tab.id);

    // 2. 等待页面加载完成
    await new Promise((resolve) => {
      const checkLoaded = () => {
        chrome.tabs.get(tab.id, (tabInfo) => {
          if (chrome.runtime.lastError) {
            resolve(); // Tab 可能已关闭
            return;
          }
          if (tabInfo.status === 'complete') {
            resolve();
          } else {
            setTimeout(checkLoaded, 500);
          }
        });
      };
      setTimeout(checkLoaded, 1000);
    });

    log('[StepExecutor] Page loaded, waiting for data table...');

    // 3. 等待额外时间让数据表格渲染
    await new Promise(resolve => setTimeout(resolve, 3000));

    // 4. 注入脚本抓取数据
    log('[StepExecutor] Injecting scraper script...');

    const scrapeResult = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (targetFeedId, targetTitleHash) => {
        // 这个函数在页面上下文中执行
        console.log('[Prome Scraper] Starting scrape for:', { targetFeedId, targetTitleHash });

        try {
          // 查找数据表格
          const table = document.querySelector('table');
          if (!table) {
            return { success: false, error: 'Table not found' };
          }

          const rows = table.querySelectorAll('tbody tr');
          console.log('[Prome Scraper] Found rows:', rows.length);

          const allNotes = [];

          for (let i = 0; i < rows.length; i++) {
            const row = rows[i];
            const cells = row.querySelectorAll('td');
            if (cells.length < 5) continue;

            // 提取标题
            const noteCell = cells[0];
            const titleEl = noteCell.querySelector('a, .title, [class*="title"]');
            const title = titleEl ? titleEl.textContent.trim() : '';
            const noteUrl = titleEl ? titleEl.href : '';

            // 提取 feedId
            let feedId = '';
            const patterns = [
              /\/explore\/([a-f0-9]{24})/i,
              /\/note\/([a-f0-9]{24})/i,
              /note_id=([a-f0-9]{24})/i,
              /[?&]id=([a-f0-9]{24})/i
            ];

            for (const pattern of patterns) {
              const match = noteUrl.match(pattern);
              if (match) {
                feedId = match[1];
                break;
              }
            }

            // 尝试从详情链接提取
            if (!feedId) {
              const lastCell = cells[cells.length - 1];
              const detailLink = lastCell.querySelector('a');
              if (detailLink && detailLink.href) {
                for (const pattern of patterns) {
                  const match = detailLink.href.match(pattern);
                  if (match) {
                    feedId = match[1];
                    break;
                  }
                }
              }
            }

            // 生成 title hash
            const normalizedTitle = (title || '').substring(0, 20).toLowerCase().replace(/\s/g, '');
            const titleHash = `${normalizedTitle}_`;

            // 解析数字
            const parseNum = (text) => {
              if (!text) return 0;
              text = text.toString().trim();
              if (text === '-' || text === '' || text === '--') return 0;
              text = text.replace('+', '');
              if (text.includes('万')) return Math.round(parseFloat(text.replace('万', '')) * 10000);
              if (text.toLowerCase().includes('k')) return Math.round(parseFloat(text.replace(/k/i, '')) * 1000);
              if (text.includes('%')) return parseFloat(text.replace('%', ''));
              return parseInt(text.replace(/,/g, ''), 10) || 0;
            };

            // 提取数据
            const noteData = {
              title,
              feedId,
              titleHash,
              impressions: parseNum(cells[1]?.textContent),
              views: parseNum(cells[2]?.textContent),
              clickRate: parseNum(cells[3]?.textContent),
              likes: parseNum(cells[4]?.textContent),
              comments: parseNum(cells[5]?.textContent),
              collects: parseNum(cells[6]?.textContent)
            };

            allNotes.push(noteData);
          }

          console.log('[Prome Scraper] Extracted notes:', allNotes.length);

          // 查找目标笔记
          let targetNote = null;

          if (targetFeedId) {
            targetNote = allNotes.find(n => n.feedId === targetFeedId);
          }

          if (!targetNote && targetTitleHash) {
            targetNote = allNotes.find(n => n.titleHash.startsWith(targetTitleHash.substring(0, 10)));
          }

          if (targetNote) {
            console.log('[Prome Scraper] Found target note:', targetNote);
            return { success: true, data: targetNote, allNotes };
          } else {
            console.log('[Prome Scraper] Target not found, returning all notes');
            return { success: true, data: null, allNotes, message: 'Target not found' };
          }

        } catch (error) {
          console.error('[Prome Scraper] Error:', error);
          return { success: false, error: error.message };
        }
      },
      args: [feedId || '', titleHash || '']
    });

    // 5. 关闭标签页
    try {
      await chrome.tabs.remove(tab.id);
      log('[StepExecutor] Tab closed');
    } catch (e) {
      // 忽略关闭错误
    }

    // 6. 处理结果
    const result = scrapeResult[0]?.result;
    log('[StepExecutor] Scrape result:', result);

    if (!result || !result.success) {
      return {
        success: false,
        error: result?.error || 'Scrape failed'
      };
    }

    // 如果找到目标笔记
    if (result.data) {
      return {
        success: true,
        output: {
          note_id: noteId,
          feed_id: result.data.feedId,
          metrics_window: metricsWindow,
          fetched_at: new Date().toISOString(),
          impressions: result.data.impressions || 0,
          views: result.data.views || 0,
          click_rate: result.data.clickRate || 0,
          likes: result.data.likes || 0,
          comments: result.data.comments || 0,
          collects: result.data.collects || 0,
          title: result.data.title,
          source: 'active_fetch'
        }
      };
    }

    // 如果没找到目标但有数据，返回汇总
    if (result.allNotes && result.allNotes.length > 0) {
      // 返回最新的笔记数据
      const latest = result.allNotes[0];
      return {
        success: true,
        output: {
          note_id: noteId,
          metrics_window: metricsWindow,
          fetched_at: new Date().toISOString(),
          impressions: latest.impressions || 0,
          views: latest.views || 0,
          click_rate: latest.clickRate || 0,
          likes: latest.likes || 0,
          comments: latest.comments || 0,
          collects: latest.collects || 0,
          title: latest.title,
          source: 'active_fetch_fallback',
          total_notes_found: result.allNotes.length
        }
      };
    }

    // 没有数据
    return {
      success: true,
      output: {
        note_id: noteId,
        metrics_window: metricsWindow,
        fetched_at: new Date().toISOString(),
        impressions: 0,
        views: 0,
        likes: 0,
        comments: 0,
        collects: 0,
        source: 'active_fetch_empty',
        reason: 'No notes found on statistics page'
      }
    };

  } catch (error) {
    logError('[StepExecutor] Fetch metrics failed:', error);
    return {
      success: false,
      error: error.message
    };
  }
}

// ==================== Multi-Account Support ====================
// 矩阵账号支持：动态检测当前登录的小红书账号，查询 xhs_accounts.id

/**
 * 检测当前登录的小红书账号
 * 从 Cookie 中提取 x-user-id-creator 或 a1
 * @returns {Object} { xhsUserId, xhsSessionHash }
 */
async function detectCurrentXhsAccount() {
  try {
    // 获取小红书相关 cookies
    const cookies = await chrome.cookies.getAll({ domain: '.xiaohongshu.com' });

    // 提取 x-user-id-creator（用户真实ID）
    const userIdCookie = cookies.find(c => c.name === 'x-user-id-creator.xiaohongshu.com');
    const xhsUserId = userIdCookie?.value || null;

    // 生成 session hash（用于备用匹配）
    const xhsSessionHash = await generateXhsAccountId(cookies);

    log('[MultiAccount] Detected account:', { xhsUserId, xhsSessionHash });

    return { xhsUserId, xhsSessionHash };
  } catch (error) {
    logError('[MultiAccount] Failed to detect account:', error);
    return { xhsUserId: null, xhsSessionHash: null };
  }
}

/**
 * 查询 Supabase 获取 xhs_accounts.id
 * 通过 xhs_user_id 或 xhs_session_hash 匹配
 * @returns {string|null} xhs_accounts.id UUID 或 null
 */
async function lookupXhsAccountId(xhsUserId, xhsSessionHash) {
  try {
    const config = await getSupabaseConfigFromStorage();
    if (!config.url || !config.key) {
      log('[MultiAccount] Supabase not configured');
      return null;
    }

    // 优先使用 xhs_user_id 查询
    if (xhsUserId) {
      const response = await fetch(
        `${config.url}/rest/v1/xhs_accounts?xhs_user_id=eq.${encodeURIComponent(xhsUserId)}&select=id`,
        {
          headers: {
            'apikey': config.key,
            'Authorization': `Bearer ${config.key}`,
            'Content-Type': 'application/json'
          }
        }
      );

      if (response.ok) {
        const accounts = await response.json();
        if (accounts.length > 0) {
          log('[MultiAccount] Found account by xhs_user_id:', accounts[0].id);
          return accounts[0].id;
        }
      }
    }

    // 如果没有 xhs_user_id 或未找到，返回 null
    // 用户需要先在前端绑定账号
    log('[MultiAccount] Account not found in xhs_accounts');
    return null;

  } catch (error) {
    logError('[MultiAccount] Lookup failed:', error);
    return null;
  }
}

/**
 * 初始化 Step Executor（带动态账号检测）
 */
async function initStepExecutorWithAccountDetection() {
  try {
    // 1. 检测当前登录账号
    const { xhsUserId, xhsSessionHash } = await detectCurrentXhsAccount();

    if (!xhsUserId && !xhsSessionHash) {
      log('[StepExecutor] No XHS account detected, executor disabled');
      return;
    }

    // 2. 查询 xhs_accounts.id
    const accountId = await lookupXhsAccountId(xhsUserId, xhsSessionHash);

    if (!accountId) {
      log('[StepExecutor] Account not bound in Supabase, executor disabled');
      log('[StepExecutor] User needs to bind account in prome.live first');
      return;
    }

    // 3. 保存并初始化
    await chrome.storage.local.set({
      xhsAccountUuid: accountId,
      xhsUserId: xhsUserId,
      xhsSessionHash: xhsSessionHash
    });

    initStepExecutor(accountId);

  } catch (error) {
    logError('[StepExecutor] Init with account detection failed:', error);
  }
}

/**
 * 监听账号变化（Cookie 变化 = 账号切换）
 */
chrome.cookies.onChanged.addListener(async (changeInfo) => {
  // 只关注小红书相关的关键 cookie
  const criticalCookies = ['web_session', 'a1', 'x-user-id-creator.xiaohongshu.com'];

  if (changeInfo.cookie.domain.includes('xiaohongshu') &&
    criticalCookies.includes(changeInfo.cookie.name)) {
    log('[MultiAccount] XHS cookie changed:', changeInfo.cookie.name, changeInfo.cause);

    // 账号可能已切换，重新检测
    if (changeInfo.cause === 'explicit' || changeInfo.cause === 'overwrite') {
      // 延迟一点让所有 cookie 都更新完
      setTimeout(() => {
        initStepExecutorWithAccountDetection();
      }, 2000);
    }
  }
});

// 启动时自动检测并初始化
initStepExecutorWithAccountDetection();

log('[StepExecutor] Multi-account support enabled');

// ==================== Review Mode Confirmation ====================

/**
 * 监听通知点击事件
 * 当用户点击发布确认通知时，打开确认弹窗
 */
chrome.notifications.onClicked.addListener(async (notificationId) => {
  log('[ReviewConfirm] Notification clicked:', notificationId);

  // 检查是否是发布确认通知
  if (notificationId.startsWith('publish_confirm_')) {
    const stepId = notificationId.replace('publish_confirm_', '');

    // 打开确认页面
    chrome.windows.create({
      url: `popup/review-confirm.html?stepId=${stepId}`,
      type: 'popup',
      width: 650,
      height: 600,
      focused: true
    });

    // 关闭通知
    chrome.notifications.clear(notificationId);
  }
});

/**
 * 处理确认/跳过响应
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'REVIEW_CONFIRM_RESPONSE') {
    log('[ReviewConfirm] Received response:', message);

    const { stepId, confirmed, data } = message;

    if (confirmed && data) {
      // 用户确认发布 - 触发发布流程
      log('[ReviewConfirm] User confirmed publish, triggering flow...');

      const publishData = {
        taskId: stepId,
        title: data.title || '',
        content: data.content || '',
        images: data.images || [],
        video: null,
        videos: [],
        stepExecutor: true,
        reviewConfirmed: true
      };

      // 触发现有的发布流程
      handlePublishCommand(publishData);

      sendResponse({ success: true, action: 'publishing' });
    } else {
      // 用户跳过 - 标记 step 为 skipped
      log('[ReviewConfirm] User skipped publish');

      // 异步更新 step 状态
      (async () => {
        try {
          const config = await getSupabaseConfigFromStorage();
          if (config.url && config.key) {
            await fetch(`${config.url}/rest/v1/rpc/finish_task_step`, {
              method: 'POST',
              headers: {
                'apikey': config.key,
                'Authorization': `Bearer ${config.key}`,
                'Content-Type': 'application/json'
              },
              body: JSON.stringify({
                p_step_id: stepId,
                p_status: 'failed',
                p_output_payload: { skipped: true, reason: 'user_skipped' },
                p_usage: {},
                p_provider: 'prome-extension',
                p_provider_run_id: null,
                p_error: { error: 'User skipped manual review' }
              })
            });
            log('[ReviewConfirm] Step marked as skipped');
          }
        } catch (error) {
          logError('[ReviewConfirm] Failed to update step:', error);
        }
      })();

      sendResponse({ success: true, action: 'skipped' });
    }

    return true;  // async response
  }
});

log('[ReviewConfirm] Review mode confirmation handlers registered');
