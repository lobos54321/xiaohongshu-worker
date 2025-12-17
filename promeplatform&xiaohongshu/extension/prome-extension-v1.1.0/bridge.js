/**
 * Prome 助手 - 前端通信脚本
 * 
 * 这个脚本在 prome.live 等前端页面运行
 * 功能：
 * 1. 注入标识元素，让前端知道插件已安装
 * 2. 监听前端的 postMessage，转发给 background script
 * 3. 接收 background script 的响应，返回给前端
 */

// ==================== 配置 ====================
const SELECTOR_VERSION = '2024.12.02';

// ==================== 工具函数 ====================
function log(message, data = null) {
  console.log(`[Prome Bridge] ${message}`, data || '');
}

// ==================== 注入标识元素 ====================
function injectMarker() {
  // 检查是否已存在
  if (document.getElementById('prome-extension-installed')) {
    log('Marker already exists');
    return;
  }

  // 创建标识元素
  const marker = document.createElement('div');
  marker.id = 'prome-extension-installed';
  marker.dataset.version = SELECTOR_VERSION;
  marker.dataset.ready = 'true';
  marker.style.display = 'none';
  document.body.appendChild(marker);

  // 兼容旧版检测
  const markerOld = document.createElement('div');
  markerOld.id = 'prome-extension-marker';
  markerOld.dataset.version = SELECTOR_VERSION;
  markerOld.style.display = 'none';
  document.body.appendChild(markerOld);

  log('✅ Extension markers injected');
}

// ==================== 消息转发 ====================
// 监听来自前端页面的 postMessage
window.addEventListener('message', async (event) => {
  // 只接受来自同一窗口的消息
  if (event.source !== window) return;

  const { type, data } = event.data || {};

  // ===== 发布任务消息 =====
  if (type === 'PROME_PUBLISH_TASK') {
    log('📥 Received publish task from frontend:', data);

    try {
      // 转发给 background script，让它打开小红书发布页面并执行
      const response = await chrome.runtime.sendMessage({
        action: 'OPEN_PUBLISH_PAGE',
        data: data
      });

      log('📤 Background response:', response);

      if (response && response.success) {
        // 通知前端任务已接收
        window.postMessage({
          type: 'PROME_PUBLISH_ACKNOWLEDGED',
          success: true,
          message: '任务已发送，正在打开发布页面...',
          tabId: response.tabId
        }, '*');
      } else {
        window.postMessage({
          type: 'PROME_PUBLISH_RESULT',
          success: false,
          message: response?.error || '发送任务失败',
          taskId: data?.taskId
        }, '*');
      }
    } catch (error) {
      log('❌ Error forwarding to background:', error);
      window.postMessage({
        type: 'PROME_PUBLISH_RESULT',
        success: false,
        message: error.message || '插件通信失败',
        taskId: data?.taskId
      }, '*');
    }
  }

  // ===== Cookie 同步请求 =====
  if (type === 'SYNC_XHS_REQUEST') {
    log('📥 Received cookie sync request');

    try {
      const response = await chrome.runtime.sendMessage({
        action: 'GET_XHS_COOKIES'
      });

      if (response && response.success) {
        window.postMessage({
          type: 'SYNC_XHS_RESPONSE',
          success: true,
          data: {
            cookies: response.cookies,
            ua: navigator.userAgent
          }
        }, '*');
      } else {
        window.postMessage({
          type: 'SYNC_XHS_RESPONSE',
          success: false,
          msg: response?.error || '获取 Cookie 失败'
        }, '*');
      }
    } catch (error) {
      log('❌ Error getting cookies:', error);
      window.postMessage({
        type: 'SYNC_XHS_RESPONSE',
        success: false,
        msg: error.message || '插件通信失败'
      }, '*');
    }
  }

  // ===== 检查插件状态 =====
  if (type === 'PROME_CHECK_STATUS') {
    log('📥 Received status check');

    try {
      const response = await chrome.runtime.sendMessage({
        action: 'GET_STATUS'
      });

      window.postMessage({
        type: 'PROME_STATUS_RESPONSE',
        success: true,
        data: response
      }, '*');
    } catch (error) {
      window.postMessage({
        type: 'PROME_STATUS_RESPONSE',
        success: false,
        error: error.message
      }, '*');
    }
  }

  // ===== Supabase 配置请求 =====
  if (type === 'PROME_GET_SUPABASE_CONFIG') {
    log('📥 Received Supabase config request');

    try {
      const response = await chrome.runtime.sendMessage({
        action: 'GET_SUPABASE_CONFIG'
      });

      window.postMessage({
        type: 'PROME_SUPABASE_CONFIG_RESPONSE',
        success: response?.success,
        config: response?.config
      }, '*');
    } catch (error) {
      window.postMessage({
        type: 'PROME_SUPABASE_CONFIG_RESPONSE',
        success: false,
        error: error.message
      }, '*');
    }
  }

  // ===== Supabase 配置推送（前端主动推送配置给插件）=====
  if (type === 'PROME_SET_SUPABASE_CONFIG') {
    log('📥 Received Supabase config push from frontend:', data);

    try {
      const response = await chrome.runtime.sendMessage({
        action: 'SAVE_SUPABASE_CONFIG',
        data: {
          url: data.supabaseUrl || data.url,
          key: data.supabaseKey || data.key,
          userId: data.userId
        }
      });

      window.postMessage({
        type: 'PROME_SUPABASE_CONFIG_SAVED',
        success: response?.success
      }, '*');
    } catch (error) {
      window.postMessage({
        type: 'PROME_SUPABASE_CONFIG_SAVED',
        success: false,
        error: error.message
      }, '*');
    }
  }

  // ===== 设置 API Token =====
  if (type === 'PROME_SET_TOKEN') {
    log('📥 Received SET_TOKEN request from frontend');
    try {
      const response = await chrome.runtime.sendMessage({
        action: 'SET_TOKEN',
        token: data.token,
        userId: data.userId
      });

      window.postMessage({
        type: 'PROME_SET_TOKEN_RESPONSE',
        success: response?.success
      }, '*');
    } catch (error) {
      window.postMessage({
        type: 'PROME_SET_TOKEN_RESPONSE',
        success: false,
        error: error.message
      }, '*');
    }
  }

  // ===== 🔥 新增：同步 Cookies 到后端 =====
  if (type === 'PROME_SYNC_COOKIES_TO_BACKEND') {
    log('📥 Received cookie sync to backend request:', data);

    try {
      const response = await chrome.runtime.sendMessage({
        action: 'SYNC_COOKIES_TO_BACKEND',
        userId: data.userId
      });

      log('📤 Cookie sync response:', response);

      window.postMessage({
        type: 'PROME_SYNC_COOKIES_RESULT',
        success: response?.success,
        result: response?.result,
        error: response?.error
      }, '*');
    } catch (error) {
      log('❌ Error syncing cookies to backend:', error);
      window.postMessage({
        type: 'PROME_SYNC_COOKIES_RESULT',
        success: false,
        error: error.message
      }, '*');
    }
  }
});

// ==================== 监听来自 background 的消息 ====================
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  log('Received from background:', message);

  // 将发布结果转发给前端
  if (message.type === 'PUBLISH_RESULT') {
    window.postMessage({
      type: 'PROME_PUBLISH_RESULT',
      success: message.success,
      message: message.message,
      taskId: message.taskId
    }, '*');
  }

  sendResponse({ received: true });
  return true;
});

// ==================== 初始化 ====================
function initialize() {
  log('Initializing on:', window.location.href);

  // 等待 body 加载完成
  if (document.body) {
    injectMarker();
  } else {
    document.addEventListener('DOMContentLoaded', injectMarker);
  }

  // 自动推送 Supabase 配置
  setTimeout(autoSyncSupabaseConfig, 2000);
}

/**
 * 自动同步 Supabase 配置
 * 尝试从页面获取配置并推送给插件
 */
async function autoSyncSupabaseConfig() {
  log('Attempting to auto-sync Supabase config...');

  try {
    // 方法1：从全局变量获取（如果前端暴露了）
    if (window.__PROME_CONFIG__) {
      const config = window.__PROME_CONFIG__;
      if (config.supabaseUrl && config.supabaseKey) {
        await pushSupabaseConfig(config.supabaseUrl, config.supabaseKey, config.userId);
        return;
      }
    }

    // 方法2：从 meta 标签获取
    const urlMeta = document.querySelector('meta[name="supabase-url"]');
    const keyMeta = document.querySelector('meta[name="supabase-key"]');
    if (urlMeta && keyMeta) {
      await pushSupabaseConfig(urlMeta.content, keyMeta.content, '');
      return;
    }

    // 方法3：请求前端提供配置
    window.postMessage({ type: 'PROME_REQUEST_SUPABASE_CONFIG' }, '*');

  } catch (error) {
    log('Auto-sync Supabase config failed:', error.message);
  }
}

/**
 * 推送配置给后台脚本
 */
async function pushSupabaseConfig(url, key, userId) {
  try {
    const response = await chrome.runtime.sendMessage({
      action: 'SAVE_SUPABASE_CONFIG',
      data: { url, key, userId }
    });

    if (response?.success) {
      log('✅ Supabase config auto-synced successfully');
    }
  } catch (error) {
    log('Failed to push Supabase config:', error.message);
  }
}

// 立即执行
initialize();

// 如果是 SPA，监听路由变化重新注入
const observer = new MutationObserver(() => {
  if (!document.getElementById('prome-extension-installed')) {
    injectMarker();
  }
});

observer.observe(document.documentElement, {
  childList: true,
  subtree: true
});

log('✅ Bridge script loaded');
