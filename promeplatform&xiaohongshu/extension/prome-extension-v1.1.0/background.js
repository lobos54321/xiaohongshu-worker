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

    // 方法0：尝试从后端 API 获取（新增，最优先）
    try {
      if (state.apiToken) {
        const backendUrl = `${CONFIG.BACKEND_URL}/api/v1/config/supabase`;
        log('Fetching Supabase config from backend:', backendUrl);

        const response = await fetch(backendUrl, {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${state.apiToken}`,
            'Content-Type': 'application/json'
          }
        });

        if (response.ok) {
          const data = await response.json();
          if (data.success && data.config) {
            log('Got Supabase config from Backend API');
            await saveSupabaseConfig(data.config.url, data.config.key, state.userId || '');
            return { url: data.config.url, key: data.config.key, userId: state.userId || '' };
          }
        } else {
          log('Backend config fetch failed:', response.status);
        }
      }
    } catch (backendError) {
      log('Backend fetch error:', backendError.message);
    }

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

    // 使用 upsert（基于 feed_id 去重）
    const notesResponse = await fetch(
      `${url}/rest/v1/xhs_published_notes?on_conflict=user_id,feed_id`,
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

  // 2. 保存分析数据（每次都是新记录）
  if (analyticsData && analyticsData.length > 0) {
    const analyticsWithUser = analyticsData.map(data => ({
      ...data,
      user_id: userId
    }));

    const analyticsResponse = await fetch(`${url}/rest/v1/xhs_note_analytics`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'apikey': key,
        'Authorization': `Bearer ${key}`,
        'Prefer': 'return=representation'
      },
      body: JSON.stringify(analyticsWithUser)
    });

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
