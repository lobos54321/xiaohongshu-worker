/**
 * Prome 小红书助手 - 后台服务脚本
 * 负责：WebSocket连接、定时任务调度、消息转发
 */

// ==================== 配置 ====================
const CONFIG = {
  // 后端服务地址（根据实际情况修改）
  BACKEND_URL: 'https://xiaohongshu-worker.zeabur.app',
  WS_URL: 'wss://xiaohongshu-worker.zeabur.app/ws',
  // 重连配置
  RECONNECT_INTERVAL: 5000,
  MAX_RECONNECT_ATTEMPTS: 10,
  // 心跳配置
  HEARTBEAT_INTERVAL: 30000,
  // 定时任务检查间隔（毫秒）
  SCHEDULE_CHECK_INTERVAL: 60000,
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
    // 打开小红书发布页
    const tab = await chrome.tabs.create({
      url: 'https://creator.xiaohongshu.com/publish/publish',
      active: true
    });
    
    // 等待页面加载完成
    chrome.tabs.onUpdated.addListener(function listener(tabId, info) {
      if (tabId === tab.id && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        
        // 发送发布指令给content script
        setTimeout(() => {
          chrome.tabs.sendMessage(tabId, {
            action: 'EXECUTE_PUBLISH',
            data: data
          });
        }, 2000); // 等待2秒确保页面完全加载
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
    // 获取小红书的cookies
    const cookies = await chrome.cookies.getAll({
      domain: '.xiaohongshu.com'
    });
    
    // 检查关键cookie是否存在
    const hasWebSession = cookies.some(c => c.name === 'web_session');
    const hasA1 = cookies.some(c => c.name === 'a1');
    
    const isLoggedIn = hasWebSession || hasA1;
    
    log('XHS login status:', isLoggedIn ? 'logged in' : 'not logged in');
    
    // 发送状态到后端
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({
        type: 'login_status',
        data: {
          isLoggedIn,
          cookies: cookies.map(c => c.name)
        }
      }));
    }
    
    return isLoggedIn;
  } catch (error) {
    logError('Failed to check login status:', error);
    return false;
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
          const isLoggedIn = await checkXhsLoginStatus();
          sendResponse({ isLoggedIn });
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
