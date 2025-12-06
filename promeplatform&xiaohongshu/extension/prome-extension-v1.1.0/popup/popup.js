/**
 * Prome 小红书助手 - Popup脚本
 * 负责：用户界面交互、与background通信
 */

// ==================== DOM元素 ====================
const elements = {
  // 状态指示
  statusIndicator: document.getElementById('statusIndicator'),
  
  // 登录区块
  loginSection: document.getElementById('loginSection'),
  apiTokenInput: document.getElementById('apiToken'),
  connectBtn: document.getElementById('connectBtn'),
  
  // 主面板
  mainSection: document.getElementById('mainSection'),
  
  // 小红书状态
  xhsStatus: document.getElementById('xhsStatus'),
  checkXhsBtn: document.getElementById('checkXhsBtn'),
  
  // 快速发布
  publishTitle: document.getElementById('publishTitle'),
  publishContent: document.getElementById('publishContent'),
  publishImages: document.getElementById('publishImages'),
  publishNowBtn: document.getElementById('publishNowBtn'),
  
  // 定时发布
  scheduleTime: document.getElementById('scheduleTime'),
  scheduleBtn: document.getElementById('scheduleBtn'),
  
  // 任务列表
  taskCount: document.getElementById('taskCount'),
  taskList: document.getElementById('taskList'),
  syncPlanBtn: document.getElementById('syncPlanBtn'),
  
  // 断开连接
  disconnectBtn: document.getElementById('disconnectBtn'),
};

// ==================== 状态 ====================
let state = {
  isConnected: false,
  xhsLoggedIn: false,
  publishQueue: [],
};

// ==================== 工具函数 ====================
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  
  setTimeout(() => {
    toast.remove();
  }, 3000);
}

function formatDateTime(dateString) {
  const date = new Date(dateString);
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${month}-${day} ${hours}:${minutes}`;
}

function generateTaskId() {
  return `task_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

// ==================== UI更新函数 ====================
function updateConnectionStatus(connected) {
  state.isConnected = connected;
  
  if (connected) {
    elements.statusIndicator.classList.add('connected');
    elements.statusIndicator.querySelector('.status-text').textContent = '已连接';
    elements.loginSection.classList.add('hidden');
    elements.mainSection.classList.remove('hidden');
  } else {
    elements.statusIndicator.classList.remove('connected');
    elements.statusIndicator.querySelector('.status-text').textContent = '未连接';
    elements.loginSection.classList.remove('hidden');
    elements.mainSection.classList.add('hidden');
  }
}

function updateXhsStatus(loggedIn, method = '', cookies = []) {
  state.xhsLoggedIn = loggedIn;
  
  const statusEl = elements.xhsStatus;
  statusEl.className = `xhs-status ${loggedIn ? 'logged-in' : 'logged-out'}`;
  
  if (loggedIn) {
    statusEl.innerHTML = `
      <span class="status-icon">✅</span>
      <span class="status-text">小红书已登录</span>
    `;
  } else {
    // 显示更多帮助信息
    const cookieInfo = cookies && cookies.length > 0 
      ? `<br><small style="color:#999;">检测到Cookie: ${cookies.slice(0, 5).join(', ')}${cookies.length > 5 ? '...' : ''}</small>` 
      : '';
    statusEl.innerHTML = `
      <span class="status-icon">❌</span>
      <span class="status-text">小红书未登录，请先登录${cookieInfo}</span>
    `;
  }
  
  console.log('XHS status updated:', { loggedIn, method, cookiesCount: cookies?.length });
}

function updateTaskList(tasks) {
  state.publishQueue = tasks || [];
  
  elements.taskCount.textContent = state.publishQueue.length;
  
  if (state.publishQueue.length === 0) {
    elements.taskList.innerHTML = '<div class="empty-state">暂无发布计划</div>';
    return;
  }
  
  elements.taskList.innerHTML = state.publishQueue.map(task => `
    <div class="task-item" data-id="${task.id}">
      <div class="task-info">
        <div class="task-title">${escapeHtml(task.title)}</div>
        <div class="task-time">${formatDateTime(task.scheduledTime)}</div>
      </div>
      <span class="task-status ${task.status}">${getStatusText(task.status)}</span>
      <button class="task-delete" data-id="${task.id}" title="删除">×</button>
    </div>
  `).join('');
  
  // 绑定删除按钮事件
  elements.taskList.querySelectorAll('.task-delete').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const taskId = e.target.dataset.id;
      deleteTask(taskId);
    });
  });
}

function getStatusText(status) {
  const statusMap = {
    pending: '待发布',
    executing: '发布中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消'
  };
  return statusMap[status] || status;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ==================== 与Background通信 ====================
async function sendMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        reject(chrome.runtime.lastError);
      } else {
        resolve(response);
      }
    });
  });
}

async function getStatus() {
  try {
    const response = await sendMessage({ action: 'GET_STATUS' });
    return response;
  } catch (error) {
    console.error('Failed to get status:', error);
    return null;
  }
}

async function connect(token) {
  try {
    elements.connectBtn.disabled = true;
    elements.connectBtn.classList.add('loading');
    elements.connectBtn.textContent = '连接中...';
    
    const response = await sendMessage({
      action: 'SET_TOKEN',
      token: token,
      userId: 'user_' + Date.now() // 临时用户ID，实际应从token解析
    });
    
    if (response.success) {
      showToast('连接成功', 'success');
      updateConnectionStatus(true);
      checkXhsLogin();
      syncPlan();
    } else {
      showToast('连接失败: ' + (response.error || '未知错误'), 'error');
    }
  } catch (error) {
    showToast('连接失败: ' + error.message, 'error');
  } finally {
    elements.connectBtn.disabled = false;
    elements.connectBtn.classList.remove('loading');
    elements.connectBtn.textContent = '连接服务';
  }
}

async function disconnect() {
  try {
    await sendMessage({ action: 'DISCONNECT' });
    showToast('已断开连接', 'info');
    updateConnectionStatus(false);
    elements.apiTokenInput.value = '';
  } catch (error) {
    console.error('Disconnect error:', error);
  }
}

async function checkXhsLogin() {
  try {
    elements.xhsStatus.innerHTML = `
      <span class="status-icon">⏳</span>
      <span class="status-text">检测中...</span>
    `;
    elements.xhsStatus.className = 'xhs-status';
    
    console.log('Checking XHS login status...');
    const response = await sendMessage({ action: 'CHECK_XHS_LOGIN' });
    console.log('XHS login check response:', response);
    
    updateXhsStatus(response.isLoggedIn, response.method, response.cookies);
  } catch (error) {
    console.error('Check XHS login error:', error);
    // 显示错误信息
    elements.xhsStatus.innerHTML = `
      <span class="status-icon">⚠️</span>
      <span class="status-text">检测失败: ${error.message}</span>
    `;
    elements.xhsStatus.className = 'xhs-status logged-out';
  }
}

async function publishNow() {
  const title = elements.publishTitle.value.trim();
  const content = elements.publishContent.value.trim();
  const imagesText = elements.publishImages.value.trim();
  
  if (!title) {
    showToast('请输入标题', 'error');
    return;
  }
  
  if (!content) {
    showToast('请输入内容', 'error');
    return;
  }
  
  // 解析图片链接
  const images = imagesText
    .split('\n')
    .map(url => url.trim())
    .filter(url => url.length > 0);
  
  try {
    elements.publishNowBtn.disabled = true;
    elements.publishNowBtn.textContent = '发布中...';
    
    const taskData = {
      id: generateTaskId(),
      title,
      content,
      images,
      scheduledTime: new Date().toISOString(),
      status: 'executing'
    };
    
    await sendMessage({
      action: 'MANUAL_PUBLISH',
      data: taskData
    });
    
    showToast('正在发布，请稍候...', 'info');
    
    // 清空表单
    elements.publishTitle.value = '';
    elements.publishContent.value = '';
    elements.publishImages.value = '';
    
  } catch (error) {
    showToast('发布失败: ' + error.message, 'error');
  } finally {
    elements.publishNowBtn.disabled = false;
    elements.publishNowBtn.textContent = '立即发布';
  }
}

async function addScheduledTask() {
  const title = elements.publishTitle.value.trim();
  const content = elements.publishContent.value.trim();
  const imagesText = elements.publishImages.value.trim();
  const scheduleTime = elements.scheduleTime.value;
  
  if (!title) {
    showToast('请输入标题', 'error');
    return;
  }
  
  if (!content) {
    showToast('请输入内容', 'error');
    return;
  }
  
  if (!scheduleTime) {
    showToast('请选择发布时间', 'error');
    return;
  }
  
  const scheduledDate = new Date(scheduleTime);
  if (scheduledDate <= new Date()) {
    showToast('发布时间必须晚于当前时间', 'error');
    return;
  }
  
  const images = imagesText
    .split('\n')
    .map(url => url.trim())
    .filter(url => url.length > 0);
  
  try {
    const task = {
      id: generateTaskId(),
      title,
      content,
      images,
      scheduledTime: scheduledDate.toISOString(),
      status: 'pending',
      createdAt: new Date().toISOString()
    };
    
    await sendMessage({
      action: 'ADD_SCHEDULED_TASK',
      task
    });
    
    showToast('已添加到发布计划', 'success');
    
    // 刷新任务列表
    await syncPlan();
    
    // 清空时间选择
    elements.scheduleTime.value = '';
    
  } catch (error) {
    showToast('添加失败: ' + error.message, 'error');
  }
}

async function deleteTask(taskId) {
  try {
    await sendMessage({
      action: 'REMOVE_SCHEDULED_TASK',
      taskId
    });
    
    showToast('任务已删除', 'success');
    await syncPlan();
  } catch (error) {
    showToast('删除失败: ' + error.message, 'error');
  }
}

async function syncPlan() {
  try {
    const response = await sendMessage({ action: 'SYNC_PLAN' });
    if (response.tasks) {
      updateTaskList(response.tasks);
    }
  } catch (error) {
    console.error('Sync plan error:', error);
  }
}

// ==================== 事件监听 ====================
function bindEvents() {
  // 连接按钮
  elements.connectBtn.addEventListener('click', () => {
    const token = elements.apiTokenInput.value.trim();
    if (!token) {
      showToast('请输入 API Token', 'error');
      return;
    }
    connect(token);
  });
  
  // 回车连接
  elements.apiTokenInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      elements.connectBtn.click();
    }
  });
  
  // 断开连接
  elements.disconnectBtn.addEventListener('click', disconnect);
  
  // 检查小红书登录
  elements.checkXhsBtn.addEventListener('click', checkXhsLogin);
  
  // 立即发布
  elements.publishNowBtn.addEventListener('click', publishNow);
  
  // 添加定时任务
  elements.scheduleBtn.addEventListener('click', addScheduledTask);
  
  // 同步计划
  elements.syncPlanBtn.addEventListener('click', syncPlan);
}

// 监听background消息
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log('Popup received message:', message);
  
  switch (message.type) {
    case 'CONNECTION_STATUS':
      updateConnectionStatus(message.connected);
      break;
      
    case 'PLAN_UPDATED':
      updateTaskList(message.tasks);
      break;
      
    case 'PUBLISH_COMPLETE':
      if (message.success) {
        showToast('发布成功！', 'success');
      } else {
        showToast('发布失败: ' + message.message, 'error');
      }
      syncPlan();
      break;
      
    case 'TASK_CANCELLED':
      showToast('任务已取消', 'info');
      syncPlan();
      break;
      
    case 'ERROR':
      showToast(message.message, 'error');
      break;
  }
});

// ==================== 初始化 ====================
async function initialize() {
  console.log('Initializing popup...');
  
  // 绑定事件
  bindEvents();
  
  // 设置默认时间（当前时间+1小时）
  const defaultTime = new Date(Date.now() + 60 * 60 * 1000);
  elements.scheduleTime.value = defaultTime.toISOString().slice(0, 16);
  
  // 获取当前状态
  const status = await getStatus();
  
  if (status) {
    if (status.apiToken) {
      updateConnectionStatus(status.isConnected);
      updateTaskList(status.publishQueue);
      
      if (status.isConnected) {
        checkXhsLogin();
      }
    } else {
      updateConnectionStatus(false);
    }
  }
  
  console.log('Popup initialized');
}

// 启动
document.addEventListener('DOMContentLoaded', initialize);
