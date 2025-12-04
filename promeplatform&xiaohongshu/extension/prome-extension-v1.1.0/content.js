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

  // 发布按钮 - 2024年12月更新
  publishBtn: [
    'button.publishBtn',                           // 主要选择器
    'button.css-1n5avvs',                          // class选择器
    'button.dyn.css-1n5avvs',                      // 动态class
    'button[class*="publishBtn"]',                 // 包含publishBtn的class
    'button[class*="publish"]',                    // 包含publish的class
    '.creator-btn-publish button',                 // 创作者发布按钮容器
    '.btn-publish',                                // 发布按钮class
    'button.primary',                              // 主要按钮
    'button[type="submit"]',                       // 提交按钮
    '.publish-btn button',                         // 发布按钮容器
  ],

  // 发布模式切换标签
  imageTabBtn: [
    'span:has-text("上传图文")',                   // 按文本匹配
    'div[class*="tab"]:has-text("上传图文")',
    '.creator-tab:has-text("上传图文")',
    'a[href*="target=image"]',                     // 链接参数
  ],

  videoTabBtn: [
    'span:has-text("上传视频")',
    'div[class*="tab"]:has-text("上传视频")',
    '.creator-tab:has-text("上传视频")',
    'a[href*="target=video"]',
  ],

  // 视频上传输入框
  videoUploadInput: [
    'input[type="file"][accept*="video"]',
    'input[accept*="mp4"]',
    'input[accept*="mov"]',
  ],

  // 话题按钮（用于添加标签）
  topicBtn: [
    'button#topicBtn',
    'button[id="topicBtn"]',
    '.topic-btn',
  ],

  // 登录检测 - 未登录时页面上会有这些元素
  loginIndicators: [
    '.login-btn',
    'a[href*="login"]',
    '.user-login',
    'button:has-text("登录")',
    '.login-guide',
    '[class*="login-btn"]',
    '[class*="loginBtn"]',
  ],

  // 已登录检测 - 登录后页面上会有这些元素
  loggedInIndicators: [
    '.user-avatar',
    '.avatar',
    '.user-info',
    '.creator-info',
    '.user-name',
    '.nickname',
    '[class*="avatar"]',
    '[class*="user-info"]',
    '.header-user',
    '.dui-avatar',
    'img[src*="avatar"]',
    'img[src*="sns-avatar"]',
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
 * 等待发布结果并捕获帖子数据
 * @param {string} originalUrl - 发布前的URL
 * @param {number} timeout - 超时时间（毫秒）
 * @returns {Promise<Object>} - 发布结果对象
 */
async function waitForPublishResult(originalUrl, timeout = 30000) {
  const startTime = Date.now();

  log('Waiting for publish result, originalUrl:', originalUrl);

  while (Date.now() - startTime < timeout) {
    await sleep(1000);

    // 检查错误提示
    const errorEl = findElement(SELECTORS.errorIndicators);
    if (errorEl) {
      const errorText = errorEl.textContent || '发布失败';
      log('Found error:', errorText);
      return {
        success: false,
        message: errorText
      };
    }

    // 检查成功提示
    const successEl = findElement(SELECTORS.successIndicators);
    if (successEl) {
      log('Found success indicator');

      // 等待一下让页面完成跳转
      await sleep(2000);

      // 尝试提取帖子数据
      const postData = extractPublishedPostData();
      return {
        success: true,
        message: '发布成功',
        ...postData
      };
    }

    // 检查URL变化（发布成功通常会跳转到帖子页面）
    const currentUrl = window.location.href;
    if (currentUrl !== originalUrl) {
      log('URL changed to:', currentUrl);

      // 等待页面加载
      await sleep(2000);

      // 尝试提取帖子数据
      const postData = extractPublishedPostData();

      if (postData.feedId) {
        return {
          success: true,
          message: '发布成功',
          ...postData
        };
      }
    }

    // 检查是否出现"发布成功"的toast或弹窗
    const toasts = document.querySelectorAll('.dyn-toast, .toast, .message, [class*="toast"], [class*="message"], [class*="success"]');
    for (const toast of toasts) {
      const text = toast.textContent || '';
      if (text.includes('发布成功') || text.includes('已发布') || text.includes('发布完成')) {
        log('Found success toast:', text);
        await sleep(2000);
        const postData = extractPublishedPostData();
        return {
          success: true,
          message: '发布成功',
          ...postData
        };
      }
    }
  }

  // 超时但没有明确错误，可能发布已提交
  log('Timeout waiting for publish result');
  const postData = extractPublishedPostData();
  return {
    success: postData.feedId ? true : false,
    message: postData.feedId ? '发布成功' : '发布已提交，请检查结果',
    ...postData
  };
}

/**
 * 从当前页面提取已发布帖子的数据
 * @returns {Object} - { feedId, xsecToken, publishedUrl }
 */
function extractPublishedPostData() {
  const result = {
    feedId: null,
    xsecToken: null,
    publishedUrl: null
  };

  const currentUrl = window.location.href;
  result.publishedUrl = currentUrl;

  // 尝试从URL提取feedId
  // 格式1: https://www.xiaohongshu.com/explore/xxxxxx
  // 格式2: https://www.xiaohongshu.com/discovery/item/xxxxxx
  // 格式3: https://creator.xiaohongshu.com/creator/note/xxxxxx
  // 格式4: URL参数中的 note_id 或 id

  const feedIdPatterns = [
    /explore\/([a-f0-9]{24})/i,
    /discovery\/item\/([a-f0-9]{24})/i,
    /creator\/note\/([a-f0-9]{24})/i,
    /note_id=([a-f0-9]{24})/i,
    /\/note\/([a-f0-9]{24})/i,
    /[?&]id=([a-f0-9]{24})/i
  ];

  for (const pattern of feedIdPatterns) {
    const match = currentUrl.match(pattern);
    if (match) {
      result.feedId = match[1];
      log('Extracted feedId from URL:', result.feedId);
      break;
    }
  }

  // 尝试从页面元素中提取 feedId
  if (!result.feedId) {
    // 从 meta 标签
    const metaEl = document.querySelector('meta[name="note-id"], meta[property="og:note_id"], meta[name="xhs:note_id"]');
    if (metaEl) {
      result.feedId = metaEl.getAttribute('content');
      log('Extracted feedId from meta:', result.feedId);
    }
  }

  // 从 script 标签中的 JSON 数据
  if (!result.feedId) {
    const scripts = document.querySelectorAll('script[type="application/json"], script:not([src])');
    for (const script of scripts) {
      try {
        const content = script.textContent || '';
        // 查找 noteId 或 note_id 或 id
        const noteIdMatch = content.match(/"(?:noteId|note_id|id)":\s*"([a-f0-9]{24})"/i);
        if (noteIdMatch) {
          result.feedId = noteIdMatch[1];
          log('Extracted feedId from script:', result.feedId);
          break;
        }
      } catch (e) {
        // 忽略解析错误
      }
    }
  }

  // 从 window 对象中查找（某些页面会暴露）
  if (!result.feedId && typeof window !== 'undefined') {
    try {
      // @ts-ignore
      if (window.__INITIAL_STATE__?.note?.noteId) {
        // @ts-ignore
        result.feedId = window.__INITIAL_STATE__.note.noteId;
        log('Extracted feedId from __INITIAL_STATE__:', result.feedId);
      }
    } catch (e) {
      // 忽略
    }
  }

  // 尝试从 URL 或页面提取 xsec_token
  const urlParams = new URLSearchParams(window.location.search);
  result.xsecToken = urlParams.get('xsec_token');

  if (!result.xsecToken) {
    // 从 script 标签中查找
    const scripts = document.querySelectorAll('script:not([src])');
    for (const script of scripts) {
      const content = script.textContent || '';
      const tokenMatch = content.match(/xsec_token['":\s]+(['"])([^'"]+)\1/);
      if (tokenMatch) {
        result.xsecToken = tokenMatch[2];
        log('Extracted xsecToken from script:', result.xsecToken);
        break;
      }
    }
  }

  // 从 data 属性中查找
  if (!result.xsecToken) {
    const dataEl = document.querySelector('[data-xsec-token]');
    if (dataEl) {
      result.xsecToken = dataEl.getAttribute('data-xsec-token');
      log('Extracted xsecToken from data attribute:', result.xsecToken);
    }
  }

  log('Extracted post data:', result);
  return result;
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

// ==================== 内容类型检测 ====================
function detectContentType(data) {
  const { images, videos, video } = data;

  // 检查是否有视频
  const hasVideo = (videos && videos.length > 0) || video;
  // 检查是否有图片
  const hasImages = images && images.length > 0;

  if (hasVideo) {
    return 'video';
  } else if (hasImages) {
    return 'image';
  } else {
    // 默认图文模式（纯文字也用图文）
    return 'image';
  }
}

// 检测文件是否是视频
function isVideoFile(url) {
  if (!url) return false;
  const videoExtensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v'];
  const lowerUrl = url.toLowerCase();
  return videoExtensions.some(ext => lowerUrl.includes(ext));
}

// 检测文件是否是图片
function isImageFile(url) {
  if (!url) return false;
  const imageExtensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'];
  const lowerUrl = url.toLowerCase();
  return imageExtensions.some(ext => lowerUrl.includes(ext));
}

// ==================== 切换发布模式 ====================
async function switchToPublishMode(targetMode) {
  log(`Switching to ${targetMode} mode...`);
  showToast(`切换到${targetMode === 'video' ? '视频' : '图文'}模式...`, 'info');

  const currentUrl = window.location.href;

  // 检查当前是否已经在目标模式
  if (targetMode === 'video' && currentUrl.includes('target=video')) {
    log('Already in video mode');
    return false;
  }
  if (targetMode === 'image' && currentUrl.includes('target=image')) {
    log('Already in image mode');
    return false;
  }

  // 目标URL
  const targetUrl = targetMode === 'video'
    ? 'https://creator.xiaohongshu.com/publish/publish?from=menu&target=video'
    : 'https://creator.xiaohongshu.com/publish/publish?from=menu&target=image';

  // 方法1: 尝试点击标签
  let tabElement = null;
  const tabSelectors = targetMode === 'video' ? SELECTORS.videoTabBtn : SELECTORS.imageTabBtn;

  // 通过文本查找标签
  const targetText = targetMode === 'video' ? '上传视频' : '上传图文';
  const allElements = document.querySelectorAll('span, div, a, button');
  for (const el of allElements) {
    const text = el.textContent.trim();
    if (text === targetText) {
      tabElement = el;
      log(`Found tab by text: ${el.tagName}.${el.className}`);
      break;
    }
  }

  // 备用：通过选择器查找
  if (!tabElement) {
    tabElement = findElement(tabSelectors);
  }

  if (tabElement) {
    log('Clicking tab element...');
    simulateClick(tabElement);
    await sleep(1500);

    // 检查是否切换成功
    if (window.location.href.includes(`target=${targetMode}`)) {
      log('Tab click successful');
      await sleep(1000);
      return true;
    }
  }

  // 方法2: 直接导航
  log('Tab click failed or not found, navigating directly...');
  window.location.href = targetUrl;

  // 等待页面加载
  await new Promise(resolve => {
    let checkCount = 0;
    const checkLoaded = setInterval(() => {
      checkCount++;
      if (document.readyState === 'complete' || checkCount > 50) {
        clearInterval(checkLoaded);
        resolve();
      }
    }, 100);
  });

  await sleep(2000);
  return true;
}

// 保留旧函数名兼容
async function switchToImageMode() {
  return switchToPublishMode('image');
}

async function switchToVideoMode() {
  return switchToPublishMode('video');
}

// ==================== 视频上传 ====================
async function uploadVideo(videoUrl) {
  log('Uploading video:', videoUrl);
  showToast('正在上传视频...', 'info');

  try {
    // 找到视频上传input
    let uploadInput = findElement(SELECTORS.videoUploadInput);

    // 如果找不到专门的视频input，尝试通用的file input
    if (!uploadInput) {
      uploadInput = await waitForElement(['input[type="file"]']);
    }

    if (!uploadInput) {
      throw new Error('Video upload input not found');
    }

    // 下载视频
    log('Downloading video...');
    showToast('下载视频中，请稍候...', 'info');

    const response = await fetch(videoUrl, {
      mode: 'cors',
      credentials: 'omit'
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const blob = await response.blob();

    // 确定文件扩展名
    let ext = 'mp4';
    if (videoUrl.toLowerCase().includes('.mov')) ext = 'mov';
    else if (videoUrl.toLowerCase().includes('.avi')) ext = 'avi';
    else if (videoUrl.toLowerCase().includes('.webm')) ext = 'webm';

    const fileName = `video.${ext}`;
    const file = new File([blob], fileName, { type: blob.type || 'video/mp4' });

    log(`Video downloaded: ${file.name}, size: ${(file.size / 1024 / 1024).toFixed(2)}MB`);

    // 创建DataTransfer来模拟文件选择
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);

    // 设置文件并触发change事件
    uploadInput.files = dataTransfer.files;
    uploadInput.dispatchEvent(new Event('change', { bubbles: true }));

    // 视频上传需要更长时间
    showToast('视频上传中，请稍候...', 'info');
    await sleep(5000);

    log('Video upload initiated');
    showToast('视频上传成功', 'success');

    return true;
  } catch (error) {
    logError('Failed to upload video:', error);
    showToast('视频上传失败: ' + error.message, 'error');
    throw error;
  }
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
    await waitForUploadCompletion();

    log(`Successfully uploaded ${files.length} images`);
    showToast(`${files.length} 张图片上传成功`, 'success');

    return true;
  } catch (error) {
    logError('Failed to upload images:', error);
    showToast('图片上传失败: ' + error.message, 'error');
    throw error;
  }
}

/**
 * 等待上传完成
 * 检测页面上是否有"上传中"提示，并等待图片预览出现
 */
async function waitForUploadCompletion(timeout = 60000) {
  log('Waiting for upload completion...');
  const startTime = Date.now();

  // 1. 基础等待，让上传开始
  await sleep(2000);

  while (Date.now() - startTime < timeout) {
    // 检查是否有"上传中"、"处理中"的提示
    const uploadingIndicators = [
      '.uploading',
      '.processing',
      '.loading',
      '[class*="uploading"]',
      '[class*="processing"]'
    ];

    // 检查文本内容
    const allDivs = document.querySelectorAll('div, span, p');
    let isUploading = false;

    for (const el of allDivs) {
      if (el.offsetParent === null) continue; // 跳过隐藏元素
      const text = el.textContent.trim();
      if (text === '上传中' || text === '处理中' || text.includes('正在上传')) {
        isUploading = true;
        log('Found uploading text:', text);
        break;
      }
    }

    if (isUploading) {
      await sleep(1000);
      continue;
    }

    // 检查是否有进度条
    const progressBars = document.querySelectorAll('.progress-bar, [role="progressbar"]');
    if (progressBars.length > 0) {
      log('Found progress bar, waiting...');
      await sleep(1000);
      continue;
    }

    // 检查是否有图片预览（表示上传成功）
    // 小红书发布页面的图片预览通常在 .image-list 或类似容器中
    const previewImages = document.querySelectorAll('.preview-item, .image-item, .uploaded-image, img[src*="sns-web-img"]');
    if (previewImages.length > 0) {
      log(`Found ${previewImages.length} uploaded images`);
      // 额外等待一下，确保状态稳定
      await sleep(2000);
      return true;
    }

    // 如果没有明确的"上传中"标志，且时间已经过了一会儿，假设完成
    if (Date.now() - startTime > 10000) {
      log('No uploading indicators found for 10s, assuming complete');
      return true;
    }

    await sleep(1000);
  }

  log('Timeout waiting for upload completion');
  return false; // 超时
}

// ==================== 发布操作 ====================
async function executePublish(data) {
  log('Executing publish:', data);
  showToast('开始发布...', 'info');

  const { taskId, title, content, images, videos, video, tags } = data;

  try {
    // 1. 等待页面加载
    await sleep(2000);

    // 2. 检查是否在发布页面
    const currentUrl = window.location.href;
    if (!currentUrl.includes('creator.xiaohongshu.com/publish')) {
      throw new Error('Not on publish page');
    }

    // 3. 【重要】自动检测内容类型并切换模式
    const contentType = detectContentType(data);
    log(`Detected content type: ${contentType}`);
    showToast(`检测到${contentType === 'video' ? '视频' : '图文'}内容...`, 'info');

    const switched = await switchToPublishMode(contentType);
    if (switched) {
      // 切换后等待页面刷新
      await sleep(2000);
    }

    // 4. 根据类型上传内容
    if (contentType === 'video') {
      // 视频模式
      const videoUrl = video || (videos && videos[0]);
      if (videoUrl) {
        await uploadVideo(videoUrl);
        await sleep(3000); // 视频处理需要更长时间
      }
    } else {
      // 图文模式
      if (images && images.length > 0) {
        await uploadImages(images);
        await sleep(2000);
      }
    }

    // 5. 填写标题
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

    // 6. 填写正文（包含标签）
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

    // 7. 可选：点击话题按钮添加话题（如果需要更正式的标签）
    // 暂时跳过，因为在内容中添加 #标签 已经足够

    // 8. 等待一下让页面处理
    await sleep(1500);

    // 9. 点击发布按钮
    log('Clicking publish button...');
    showToast('点击发布...', 'info');

    // 再次确认上传状态（双重保险）
    if (contentType === 'image' || contentType === 'video') {
      await waitForUploadCompletion(10000); // 快速检查
    }

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

    // 9. 等待发布结果并捕获帖子数据
    log('Waiting for publish result...');
    showToast('等待发布结果...', 'info');

    // 等待更长时间让发布完成和页面跳转
    const publishResult = await waitForPublishResult(currentUrl, 30000);

    log('Publish result:', publishResult);

    // 发送结果到background（包含feedId和xsecToken用于后续数据追踪）
    chrome.runtime.sendMessage({
      action: 'PUBLISH_RESULT',
      taskId: taskId,
      success: publishResult.success,
      message: publishResult.message,
      // 新增：用于数据追踪的字段
      feedId: publishResult.feedId || null,
      xsecToken: publishResult.xsecToken || null,
      publishedUrl: publishResult.publishedUrl || null,
      publishedAt: new Date().toISOString()
    });

    if (publishResult.success) {
      showToast('发布成功！', 'success');
      if (publishResult.feedId) {
        log('Published feedId:', publishResult.feedId);
      }
    } else {
      showToast(publishResult.message || '发布已提交', 'info');
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
  log('Checking login status on page...');

  // 方法1: 检查URL是否是登录页
  if (window.location.href.includes('login')) {
    log('On login page, not logged in');
    return false;
  }

  // 方法2: 检查页面上是否有登录按钮（未登录标志）
  const loginIndicator = findElement(SELECTORS.loginIndicators);
  if (loginIndicator) {
    log('Found login indicator, not logged in:', loginIndicator);
    return false;
  }

  // 方法3: 检查页面上是否有用户信息（已登录标志）
  const loggedInIndicator = findElement(SELECTORS.loggedInIndicators);
  if (loggedInIndicator) {
    log('Found logged in indicator:', loggedInIndicator);
    return true;
  }

  // 方法4: 检查页面标题或特定元素
  // creator.xiaohongshu.com 登录后通常有创作者相关元素
  const creatorElements = [
    document.querySelector('.creator-center'),
    document.querySelector('.sidebar'),
    document.querySelector('.publish-btn'),
    document.querySelector('[class*="creator"]'),
    document.querySelector('.menu-item'),
  ].filter(Boolean);

  if (creatorElements.length > 0) {
    log('Found creator elements, assuming logged in');
    return true;
  }

  // 方法5: 检查是否能访问发布页面（只有登录才能访问）
  if (window.location.href.includes('creator.xiaohongshu.com/publish')) {
    // 如果在发布页面且没有被重定向到登录页，说明已登录
    log('On publish page, assuming logged in');
    return true;
  }

  // 方法6: 检查document.cookie（虽然不包含HttpOnly，但可以辅助判断）
  const cookies = document.cookie;
  if (cookies.includes('a1=') || cookies.includes('webId=')) {
    log('Found login cookies in document.cookie');
    return true;
  }

  // 默认：如果在creator域名下且没有登录按钮，假设已登录
  if (window.location.hostname.includes('creator.xiaohongshu.com')) {
    log('On creator domain without login button, assuming logged in');
    return true;
  }

  log('Could not determine login status, assuming not logged in');
  return false;
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

// ==================== 前端 postMessage 监听 ====================
// 监听来自前端页面（如 prome.live）的发布任务
// 这是前端中转模式的关键：前端通过 window.postMessage 发送任务给插件
window.addEventListener('message', async (event) => {
  // 安全检查：只接受来自同一窗口的消息
  if (event.source !== window) return;

  const { type, data } = event.data || {};

  // ===== 发布任务消息 =====
  if (type === 'PROME_PUBLISH_TASK') {
    log('📥 Received publish task from frontend via postMessage:', data);
    showToast('收到发布任务，正在处理...', 'info');

    try {
      // 检查是否在小红书发布页面
      const currentUrl = window.location.href;

      if (!currentUrl.includes('creator.xiaohongshu.com/publish')) {
        log('⚠️ Not on publish page, current URL:', currentUrl);
        showToast('请在小红书发布页面中操作', 'error');

        // 通知前端需要手动操作
        window.postMessage({
          type: 'PROME_PUBLISH_RESULT',
          success: false,
          message: '请先打开小红书发布页面 (creator.xiaohongshu.com/publish)',
          taskId: data?.taskId,
          needRedirect: true
        }, '*');

        // 尝试打开发布页面（通过 background script）
        chrome.runtime.sendMessage({
          action: 'OPEN_PUBLISH_PAGE',
          data: data
        }).catch(e => log('Failed to send OPEN_PUBLISH_PAGE:', e));

        return;
      }

      // 检查登录状态
      const loggedIn = checkLoginStatus();
      if (!loggedIn) {
        log('⚠️ User not logged in');
        showToast('请先登录小红书账号', 'error');

        window.postMessage({
          type: 'PROME_PUBLISH_RESULT',
          success: false,
          message: '请先登录小红书账号',
          taskId: data?.taskId,
          needLogin: true
        }, '*');
        return;
      }

      // 验证数据完整性
      if (!data || (!data.title && !data.content)) {
        throw new Error('发布数据不完整：缺少标题或内容');
      }

      log('✅ All checks passed, starting publish...');
      showToast('开始自动发布...', 'info');

      // 执行发布
      await executePublish(data);

      // 发布完成后等待确认
      await sleep(3000);

      // 发布成功，通知前端
      log('✅ Publish completed, notifying frontend');
      window.postMessage({
        type: 'PROME_PUBLISH_RESULT',
        success: true,
        message: '发布成功！',
        taskId: data?.taskId
      }, '*');

      showToast('🎉 发布成功！', 'success');

    } catch (error) {
      logError('❌ Publish task failed:', error);
      showToast('发布失败: ' + error.message, 'error');

      // 发布失败，通知前端
      window.postMessage({
        type: 'PROME_PUBLISH_RESULT',
        success: false,
        message: error.message || '发布失败',
        taskId: data?.taskId
      }, '*');
    }
  }

  // ===== Cookie 同步请求（已有功能）=====
  if (type === 'SYNC_XHS_REQUEST') {
    log('📥 Received cookie sync request from frontend');
    handleCookieSyncRequest();
  }
});

// Cookie 同步处理函数
async function handleCookieSyncRequest() {
  try {
    // 检查是否在小红书域名下
    if (!window.location.hostname.includes('xiaohongshu.com')) {
      window.postMessage({
        type: 'SYNC_XHS_RESPONSE',
        success: false,
        msg: '请在小红书网站中操作'
      }, '*');
      return;
    }

    // 获取 cookies
    const cookies = await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ action: 'GET_XHS_COOKIES' }, (response) => {
        if (chrome.runtime.lastError) {
          reject(chrome.runtime.lastError);
        } else {
          resolve(response?.cookies || []);
        }
      });
    });

    // 获取 UA
    const ua = navigator.userAgent;

    window.postMessage({
      type: 'SYNC_XHS_RESPONSE',
      success: true,
      data: { cookies, ua }
    }, '*');

  } catch (error) {
    logError('Cookie sync failed:', error);
    window.postMessage({
      type: 'SYNC_XHS_RESPONSE',
      success: false,
      msg: error.message || 'Cookie同步失败'
    }, '*');
  }
}

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
// 前端通过检测这个元素来确认插件已安装
const marker = document.createElement('div');
marker.id = 'prome-extension-installed';  // 前端检测用的ID
marker.dataset.version = SELECTOR_VERSION;
marker.dataset.ready = 'true';
marker.style.display = 'none';
document.body.appendChild(marker);

// 同时保留旧ID兼容
const markerOld = document.createElement('div');
markerOld.id = 'prome-extension-marker';
markerOld.dataset.version = SELECTOR_VERSION;
markerOld.style.display = 'none';
document.body.appendChild(markerOld);

log('✅ Extension markers injected, ready to receive tasks');
