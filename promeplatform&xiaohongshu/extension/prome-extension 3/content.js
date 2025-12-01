/**
 * Prome 小红书助手 - 内容脚本
 * 负责：在小红书页面执行发布操作
 * 
 * 设计原则：
 * 1. 使用多重选择器回退机制，应对DOM变化
 * 2. 优先使用稳定的属性选择器（role, type, placeholder）
 * 3. 支持远程更新选择器配置
 */

// ==================== 选择器配置 ====================
// 使用数组存储多个候选选择器，按优先级排序
// 如果小红书更新了DOM，只需更新这个配置
const SELECTORS = {
  // 图片上传 - 最稳定，type="file" 不太会变
  uploadInput: [
    'input[type="file"]',
    'input[accept*="image"]',
    '.upload-input input',
  ],
  
  // 标题输入框 - 2024年12月实测选择器
  titleInput: [
    'input.d-text[placeholder*="标题"]',           // 当前主要选择器
    'input[placeholder*="填写标题"]',              // 备选
    'input[placeholder*="标题"]',                  // 通用
    '.title-input input',                          // 类名选择
    'input[maxlength="20"]',                       // 小红书标题限制20字
  ],
  
  // 内容编辑区 - ProseMirror 富文本编辑器
  contentArea: [
    '.tiptap.ProseMirror[role="textbox"]',         // 当前主要选择器
    '.ProseMirror[role="textbox"]',                // 简化版
    '[role="textbox"][contenteditable="true"]',   // 通用富文本
    '.tiptap[contenteditable="true"]',            // tiptap编辑器
    '.ql-editor',                                  // Quill编辑器（备选）
    '[contenteditable="true"]',                   // 最通用
  ],
  
  // 发布按钮
  publishBtn: [
    'button.publishBtn',                           // 当前主要选择器
    'button.css-1n5avvs',                          // class选择器（可能变）
    'button:has-text("发布")',                     // 按文本匹配
    '.publish-btn button',
    'button[type="submit"]',
  ],
  
  // 话题按钮（用于添加标签）
  topicBtn: [
    'button#topicBtn',
    'button[id="topicBtn"]',
    '.topic-btn',
  ],
  
  // 登录检测
  loginIndicators: [
    '.login-btn',
    'a[href*="login"]',
    '.user-login',
  ],
  
  // 已登录检测
  loggedInIndicators: [
    '.user-avatar',
    '.avatar',
    '.user-info',
    '.creator-info',
  ],
  
  // 发布成功检测
  successIndicators: [
    '.success-modal',
    '.publish-success',
    '[class*="success"]',
    '.toast-success',
  ],
  
  // 发布失败检测
  errorIndicators: [
    '.error-modal',
    '.publish-error',
    '[class*="error"]',
    '.toast-error',
  ],
};

// 选择器版本，用于远程更新
const SELECTOR_VERSION = '2024.12.01';

const TIMEOUTS = {
  elementWait: 10000,
  uploadWait: 30000,
  publishWait: 30000,
};

// ==================== 工具函数 ====================
function log(message, data = null) {
  console.log(`[Prome Content] ${message}`, data || '');
}

function logError(message, error = null) {
  console.error(`[Prome Content Error] ${message}`, error || '');
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * 智能元素查找 - 核心函数
 * 尝试多个选择器，返回第一个找到的元素
 * @param {string|string[]} selectors - 单个选择器或选择器数组
 * @param {Element} context - 搜索上下文，默认document
 * @returns {Element|null}
 */
function findElement(selectors, context = document) {
  const selectorList = Array.isArray(selectors) ? selectors : [selectors];
  
  for (const selector of selectorList) {
    try {
      // 处理特殊选择器
      if (selector.startsWith('//')) {
        // XPath选择器
        const result = document.evaluate(
          selector, 
          context, 
          null, 
          XPathResult.FIRST_ORDERED_NODE_TYPE, 
          null
        );
        if (result.singleNodeValue) {
          log(`Found element via XPath: ${selector}`);
          return result.singleNodeValue;
        }
      } else if (selector.includes(':has-text(')) {
        // 文本匹配选择器（自定义实现）
        const match = selector.match(/^(.+):has-text\("(.+)"\)$/);
        if (match) {
          const [, baseSelector, text] = match;
          const elements = context.querySelectorAll(baseSelector);
          for (const el of elements) {
            if (el.textContent.includes(text)) {
              log(`Found element via text match: ${selector}`);
              return el;
            }
          }
        }
      } else {
        // 标准CSS选择器
        const element = context.querySelector(selector);
        if (element) {
          log(`Found element via CSS: ${selector}`);
          return element;
        }
      }
    } catch (e) {
      // 选择器语法错误，跳过
      log(`Selector error: ${selector}`, e.message);
    }
  }
  
  return null;
}

/**
 * 查找所有匹配元素
 */
function findAllElements(selectors, context = document) {
  const selectorList = Array.isArray(selectors) ? selectors : [selectors];
  const results = [];
  
  for (const selector of selectorList) {
    try {
      if (!selector.startsWith('//') && !selector.includes(':has-text(')) {
        const elements = context.querySelectorAll(selector);
        results.push(...elements);
      }
    } catch (e) {
      // 忽略错误
    }
  }
  
  return [...new Set(results)]; // 去重
}

/**
 * 等待元素出现 - 支持多选择器
 */
function waitForElement(selectors, timeout = TIMEOUTS.elementWait) {
  return new Promise((resolve, reject) => {
    // 首先检查元素是否已存在
    const element = findElement(selectors);
    if (element) {
      return resolve(element);
    }
    
    // 设置观察器
    const observer = new MutationObserver((mutations, obs) => {
      const element = findElement(selectors);
      if (element) {
        obs.disconnect();
        resolve(element);
      }
    });
    
    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
    
    // 超时处理
    setTimeout(() => {
      observer.disconnect();
      const selectorStr = Array.isArray(selectors) ? selectors.join(', ') : selectors;
      reject(new Error(`Element not found: ${selectorStr}`));
    }, timeout);
  });
}

/**
 * 模拟用户输入 - 针对不同类型的输入框
 */
function simulateInput(element, value) {
  // 聚焦元素
  element.focus();
  
  // 判断元素类型
  const isContentEditable = element.getAttribute('contenteditable') === 'true';
  const isProseMirror = element.classList.contains('ProseMirror') || 
                        element.classList.contains('tiptap');
  
  if (isProseMirror || isContentEditable) {
    // ProseMirror/富文本编辑器
    // 清空内容
    element.innerHTML = '';
    
    // 处理换行和标签
    const processedContent = processContent(value);
    element.innerHTML = processedContent;
    
    // 触发输入事件
    element.dispatchEvent(new InputEvent('input', { 
      bubbles: true, 
      cancelable: true,
      inputType: 'insertText'
    }));
    
  } else if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
    // 普通输入框
    element.value = '';
    
    // 逐字符输入（更真实）
    for (const char of value) {
      element.value += char;
      element.dispatchEvent(new InputEvent('input', { 
        bubbles: true,
        data: char,
        inputType: 'insertText'
      }));
    }
  }
  
  // 触发change事件
  element.dispatchEvent(new Event('change', { bubbles: true }));
  element.dispatchEvent(new Event('blur', { bubbles: true }));
}

/**
 * 处理内容 - 转换标签为话题格式
 */
function processContent(content) {
  // 将换行转为<p>标签（ProseMirror格式）
  let processed = content
    .split('\n')
    .map(line => `<p>${line || '<br>'}</p>`)
    .join('');
  
  return processed;
}

/**
 * 在内容末尾添加标签
 */
function appendTags(content, tags) {
  if (!tags || tags.length === 0) return content;
  
  // 小红书的标签格式是 #标签名#（双井号）或 #标签名
  const tagStr = tags.map(tag => {
    // 移除可能存在的#号
    const cleanTag = tag.replace(/^#/, '').replace(/#$/, '');
    return `#${cleanTag}`;
  }).join(' ');
  
  return content + '\n\n' + tagStr;
}

// 模拟点击
function simulateClick(element) {
  // 确保元素可见
  element.scrollIntoView({ behavior: 'smooth', block: 'center' });
  
  // 多种点击方式确保成功
  element.click();
  element.dispatchEvent(new MouseEvent('click', {
    bubbles: true,
    cancelable: true,
    view: window
  }));
  element.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
  element.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
}

/**
 * 显示操作提示
 */
function showToast(message, type = 'info') {
  // 移除旧提示
  const oldToast = document.querySelector('.prome-toast');
  if (oldToast) oldToast.remove();
  
  const toast = document.createElement('div');
  toast.className = `prome-toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  
  setTimeout(() => toast.remove(), 3000);
}

// ==================== 图片上传 ====================
async function uploadImages(imageUrls) {
  log('Uploading images:', imageUrls);
  showToast('正在上传图片...', 'info');
  
  try {
    // 找到文件上传input
    const uploadInput = await waitForElement(SELECTORS.uploadInput);
    
    // 下载图片并转换为File对象
    const files = [];
    for (let i = 0; i < imageUrls.length; i++) {
      const url = imageUrls[i];
      log(`Downloading image ${i + 1}/${imageUrls.length}: ${url}`);
      showToast(`下载图片 ${i + 1}/${imageUrls.length}`, 'info');
      
      try {
        const response = await fetch(url, {
          mode: 'cors',
          credentials: 'omit'
        });
        
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        
        const blob = await response.blob();
        
        // 确定文件扩展名
        let ext = 'jpg';
        if (blob.type.includes('png')) ext = 'png';
        else if (blob.type.includes('webp')) ext = 'webp';
        else if (blob.type.includes('gif')) ext = 'gif';
        
        const fileName = `image_${i + 1}.${ext}`;
        const file = new File([blob], fileName, { type: blob.type || 'image/jpeg' });
        files.push(file);
        
      } catch (error) {
        logError(`Failed to download image: ${url}`, error);
        showToast(`图片 ${i + 1} 下载失败`, 'error');
        // 继续处理其他图片
      }
    }
    
    if (files.length === 0) {
      throw new Error('No images could be downloaded');
    }
    
    // 创建DataTransfer来模拟文件选择
    const dataTransfer = new DataTransfer();
    files.forEach(file => dataTransfer.items.add(file));
    
    // 设置文件并触发change事件
    uploadInput.files = dataTransfer.files;
    uploadInput.dispatchEvent(new Event('change', { bubbles: true }));
    
    // 等待上传完成
    showToast('图片上传中，请稍候...', 'info');
    await sleep(3000);
    
    log(`Successfully uploaded ${files.length} images`);
    showToast(`${files.length} 张图片上传成功`, 'success');
    
    return true;
  } catch (error) {
    logError('Failed to upload images:', error);
    showToast('图片上传失败: ' + error.message, 'error');
    throw error;
  }
}

// ==================== 发布操作 ====================
async function executePublish(data) {
  log('Executing publish:', data);
  showToast('开始发布...', 'info');
  
  const { taskId, title, content, images, tags } = data;
  
  try {
    // 1. 等待页面加载
    await sleep(2000);
    
    // 2. 检查是否在发布页面
    const currentUrl = window.location.href;
    if (!currentUrl.includes('creator.xiaohongshu.com/publish')) {
      throw new Error('Not on publish page');
    }
    
    // 3. 上传图片（如果有）
    if (images && images.length > 0) {
      await uploadImages(images);
      await sleep(2000); // 等待图片处理完成
    }
    
    // 4. 填写标题
    log('Filling title...');
    showToast('填写标题...', 'info');
    
    const titleInput = findElement(SELECTORS.titleInput);
    if (titleInput) {
      simulateInput(titleInput, title);
      await sleep(500);
    } else {
      logError('Title input not found');
      // 不中断，继续尝试
    }
    
    // 5. 填写正文（包含标签）
    log('Filling content...');
    showToast('填写内容...', 'info');
    
    const contentArea = findElement(SELECTORS.contentArea);
    if (contentArea) {
      // 将标签附加到内容末尾
      const fullContent = appendTags(content, tags);
      simulateInput(contentArea, fullContent);
      await sleep(500);
    } else {
      logError('Content area not found');
    }
    
    // 6. 可选：点击话题按钮添加话题（如果需要更正式的标签）
    // 暂时跳过，因为在内容中添加 #标签 已经足够
    
    // 7. 等待一下让页面处理
    await sleep(1500);
    
    // 8. 点击发布按钮
    log('Clicking publish button...');
    showToast('点击发布...', 'info');
    
    let publishBtn = findElement(SELECTORS.publishBtn);
    
    // 如果没找到，尝试通过文本查找
    if (!publishBtn) {
      const buttons = document.querySelectorAll('button');
      for (const btn of buttons) {
        const text = btn.textContent.trim();
        if (text === '发布' || text === '发布笔记') {
          if (!btn.disabled) {
            publishBtn = btn;
            break;
          }
        }
      }
    }
    
    if (publishBtn) {
      // 检查按钮是否可用
      if (publishBtn.disabled) {
        throw new Error('发布按钮不可用，请检查内容是否完整');
      }
      
      simulateClick(publishBtn);
      log('Publish button clicked');
      showToast('已点击发布按钮', 'info');
    } else {
      throw new Error('Publish button not found');
    }
    
    // 9. 等待发布结果
    await sleep(3000);
    
    // 检测成功或失败
    let isSuccess = false;
    let errorMessage = '';
    
    // 检查成功提示
    const successEl = findElement(SELECTORS.successIndicators);
    if (successEl) {
      isSuccess = true;
    }
    
    // 检查错误提示
    const errorEl = findElement(SELECTORS.errorIndicators);
    if (errorEl) {
      errorMessage = errorEl.textContent || '发布失败';
    }
    
    // 检查URL变化（发布成功通常会跳转）
    if (window.location.href !== currentUrl) {
      isSuccess = true;
    }
    
    // 发送结果到background
    chrome.runtime.sendMessage({
      action: 'PUBLISH_RESULT',
      taskId: taskId,
      success: !errorMessage && (isSuccess || !errorEl),
      message: isSuccess ? '发布成功' : (errorMessage || '发布已提交，请检查结果')
    });
    
    if (isSuccess) {
      showToast('发布成功！', 'success');
    } else {
      showToast(errorMessage || '发布已提交', 'info');
    }
    
    log('Publish completed');
    
  } catch (error) {
    logError('Publish failed:', error);
    showToast('发布失败: ' + error.message, 'error');
    
    // 发送失败结果
    chrome.runtime.sendMessage({
      action: 'PUBLISH_RESULT',
      taskId: taskId,
      success: false,
      message: error.message
    });
  }
}

// ==================== 登录状态检测 ====================
function checkLoginStatus() {
  // 检测未登录指示
  const loginIndicator = findElement(SELECTORS.loginIndicators);
  if (loginIndicator) {
    return false;
  }
  
  // 检测已登录指示
  const loggedInIndicator = findElement(SELECTORS.loggedInIndicators);
  if (loggedInIndicator) {
    return true;
  }
  
  // 检查URL是否包含登录页
  if (window.location.href.includes('login')) {
    return false;
  }
  
  return true; // 默认假设已登录
}

// ==================== 页面状态采集 ====================
function getPageInfo() {
  return {
    url: window.location.href,
    title: document.title,
    isLoginPage: window.location.href.includes('login'),
    isPublishPage: window.location.href.includes('publish'),
    isCreatorPage: window.location.href.includes('creator.xiaohongshu.com'),
    selectorVersion: SELECTOR_VERSION,
  };
}

// ==================== 远程选择器更新 ====================
async function updateSelectorsFromRemote() {
  try {
    // 从后端获取最新的选择器配置
    const response = await fetch('https://xiaohongshu-worker.zeabur.app/api/v1/selectors');
    if (response.ok) {
      const remoteSelectors = await response.json();
      if (remoteSelectors.version > SELECTOR_VERSION) {
        // 更新选择器
        Object.assign(SELECTORS, remoteSelectors.selectors);
        log('Selectors updated from remote:', remoteSelectors.version);
      }
    }
  } catch (error) {
    // 静默失败，使用本地选择器
    log('Failed to fetch remote selectors, using local');
  }
}

// ==================== 消息监听 ====================
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  log('Received message:', message);
  
  switch (message.action) {
    case 'EXECUTE_PUBLISH':
      executePublish(message.data);
      sendResponse({ received: true });
      break;
      
    case 'CHECK_LOGIN':
      const isLoggedIn = checkLoginStatus();
      sendResponse({ isLoggedIn });
      break;
      
    case 'GET_PAGE_INFO':
      const pageInfo = getPageInfo();
      sendResponse(pageInfo);
      break;
      
    case 'UPDATE_SELECTORS':
      // 手动更新选择器
      if (message.selectors) {
        Object.assign(SELECTORS, message.selectors);
        log('Selectors updated manually');
      }
      sendResponse({ success: true });
      break;
      
    case 'PING':
      sendResponse({ pong: true });
      break;
      
    default:
      sendResponse({ error: 'Unknown action' });
  }
  
  return true;
});

// ==================== 初始化 ====================
async function initialize() {
  log('Content script initialized on:', window.location.href);
  log('Selector version:', SELECTOR_VERSION);
  
  // 尝试从远程更新选择器
  await updateSelectorsFromRemote();
  
  // 通知background脚本页面已加载
  chrome.runtime.sendMessage({
    action: 'PAGE_LOADED',
    pageInfo: getPageInfo()
  }).catch(() => {
    // 忽略错误
  });
}

// 页面加载完成后初始化
if (document.readyState === 'complete') {
  initialize();
} else {
  window.addEventListener('load', initialize);
}

// ==================== 注入样式标识 ====================
// 添加一个隐藏的标识元素，表示扩展已加载
const marker = document.createElement('div');
marker.id = 'prome-extension-marker';
marker.dataset.version = SELECTOR_VERSION;
marker.style.display = 'none';
document.body.appendChild(marker);
