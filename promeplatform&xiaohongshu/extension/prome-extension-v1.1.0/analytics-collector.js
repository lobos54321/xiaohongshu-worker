/**
 * analytics-collector.js
 * 小红书创作者中心数据采集脚本
 * 
 * v1.1.0 更新：
 * - 添加自动定时同步
 * - 优化标题匹配关联
 * - 支持从"详情数据"链接提取 feedId
 * 
 * 在 creator.xiaohongshu.com/statistics/* 页面运行
 * 采集笔记数据并保存到 Supabase
 */

(function () {
  'use strict';

  const COLLECTOR_VERSION = '1.1.0';

  // ==================== 配置 ====================
  const CONFIG = {
    // 自动采集配置
    autoCollectEnabled: true,
    autoCollectInterval: 6 * 60 * 60 * 1000,  // 6小时
    autoCollectOnLoad: true,  // 页面加载时自动采集

    // 页面检测
    analyticsPagePattern: /creator\.xiaohongshu\.com\/statistics/,
    dataAnalysisPath: '/statistics/data-analysis',

    // DOM 选择器（需要根据实际页面调整）
    selectors: {
      // 数据表格
      dataTable: '.data-table, table, [class*="table"]',
      tableRows: 'tbody tr, .table-row, [class*="row"]',

      // 表格列（按顺序）
      noteInfo: '.note-info, td:nth-child(1), [class*="note"]',
      noteTitle: '.note-title, .title, a',
      noteDate: '.note-date, .date, .time',
      noteCover: 'img',

      // 数据列
      impressions: 'td:nth-child(2), [class*="impression"], [class*="曝光"]',
      views: 'td:nth-child(3), [class*="view"], [class*="观看"]',
      clickRate: 'td:nth-child(4), [class*="click-rate"], [class*="点击率"]',
      likes: 'td:nth-child(5), [class*="like"], [class*="点赞"]',
      comments: 'td:nth-child(6), [class*="comment"], [class*="评论"]',
      collects: 'td:nth-child(7), [class*="collect"], [class*="收藏"]',

      // 详情数据链接（用于提取 feedId）
      detailLink: 'a:has-text("详情数据"), .detail-link, [class*="detail"]',

      // 导出按钮
      exportBtn: 'button:has-text("导出"), .export-btn, [class*="export"]',

      // 分页
      pagination: '.pagination, .pager, [class*="page"]',
      nextPageBtn: '.next, .next-page, [class*="next"]',

      // 筛选器
      dateFilter: '.date-filter, .date-picker, [class*="date"]',
      typeFilter: '.type-filter, select, [class*="filter"]'
    }
  };

  // ==================== 工具函数 ====================

  function log(...args) {
    console.log('[Prome Analytics]', ...args);
  }

  function logError(...args) {
    console.error('[Prome Analytics Error]', ...args);
  }

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * 解析数字（处理 "1.2万" "999+" 等格式）
   */
  function parseNumber(text) {
    if (!text) return 0;

    text = text.toString().trim();

    // 处理 "-" 或空
    if (text === '-' || text === '' || text === '--') return 0;

    // 处理 "999+" 格式
    text = text.replace('+', '');

    // 处理 "1.2万" 格式
    if (text.includes('万')) {
      return Math.round(parseFloat(text.replace('万', '')) * 10000);
    }

    // 处理 "1.2k" 格式
    if (text.toLowerCase().includes('k')) {
      return Math.round(parseFloat(text.replace(/k/i, '')) * 1000);
    }

    // 处理百分比
    if (text.includes('%')) {
      return parseFloat(text.replace('%', ''));
    }

    return parseInt(text.replace(/,/g, ''), 10) || 0;
  }

  /**
   * 从元素获取文本
   */
  function getText(element, selector) {
    if (!element) return '';

    if (selector) {
      const el = element.querySelector(selector);
      return el ? el.textContent.trim() : '';
    }

    return element.textContent.trim();
  }

  /**
   * 查找元素（支持多选择器）
   */
  function findElement(selectors, context = document) {
    const selectorList = Array.isArray(selectors) ? selectors : selectors.split(', ');

    for (const selector of selectorList) {
      try {
        // 处理 :has-text() 伪选择器
        if (selector.includes(':has-text(')) {
          const match = selector.match(/^(.+):has-text\("(.+)"\)$/);
          if (match) {
            const [, baseSelector, text] = match;
            const elements = context.querySelectorAll(baseSelector || '*');
            for (const el of elements) {
              if (el.textContent.includes(text)) {
                return el;
              }
            }
          }
          continue;
        }

        const element = context.querySelector(selector);
        if (element) return element;
      } catch (e) {
        // 选择器语法错误，跳过
      }
    }

    return null;
  }

  /**
   * 查找所有元素
   */
  function findAllElements(selectors, context = document) {
    const selectorList = Array.isArray(selectors) ? selectors : selectors.split(', ');
    const results = [];

    for (const selector of selectorList) {
      try {
        if (!selector.includes(':has-text(')) {
          const elements = context.querySelectorAll(selector);
          results.push(...elements);
        }
      } catch (e) {
        // 忽略错误
      }
    }

    return [...new Set(results)];
  }

  // ==================== Supabase 操作 ====================

  /**
   * 获取 Supabase 配置
   */
  async function getSupabaseConfig() {
    return new Promise((resolve) => {
      chrome.storage.local.get(['supabaseUrl', 'supabaseKey', 'userId'], (result) => {
        resolve({
          url: result.supabaseUrl,
          key: result.supabaseKey,
          userId: result.userId
        });
      });
    });
  }

  /**
   * 获取小红书账号的稳定 ID
   * 通过 background.js 从 Cookie 生成哈希
   */
  async function getXhsAccountId() {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ action: 'GET_XHS_ACCOUNT_ID' }, (response) => {
        if (chrome.runtime.lastError) {
          log('Failed to get XHS account ID:', chrome.runtime.lastError);
          resolve(null);
          return;
        }
        resolve(response?.accountId || null);
      });
    });
  }

  /**
   * 保存数据到 Supabase
   */
  async function saveToSupabase(tableName, data) {
    const config = await getSupabaseConfig();

    if (!config.url || !config.key) {
      log('Supabase not configured, sending to background for backend save');
      // 发送给 background.js 处理
      return new Promise((resolve) => {
        chrome.runtime.sendMessage({
          action: 'SAVE_ANALYTICS_DATA',
          data: {
            tableName,
            records: data
          }
        }, resolve);
      });
    }

    try {
      const response = await fetch(`${config.url}/rest/v1/${tableName}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'apikey': config.key,
          'Authorization': `Bearer ${config.key}`,
          'Prefer': 'return=representation'
        },
        body: JSON.stringify(data)
      });

      if (!response.ok) {
        throw new Error(`Supabase error: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      logError('Failed to save to Supabase:', error);
      throw error;
    }
  }

  /**
   * 更新或插入数据 (upsert)
   */
  async function upsertToSupabase(tableName, data, conflictColumn = 'feed_id') {
    const config = await getSupabaseConfig();

    if (!config.url || !config.key) {
      return new Promise((resolve) => {
        chrome.runtime.sendMessage({
          action: 'UPSERT_ANALYTICS_DATA',
          data: { tableName, records: data, conflictColumn }
        }, resolve);
      });
    }

    try {
      const response = await fetch(
        `${config.url}/rest/v1/${tableName}?on_conflict=${conflictColumn}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'apikey': config.key,
            'Authorization': `Bearer ${config.key}`,
            'Prefer': 'resolution=merge-duplicates,return=representation'
          },
          body: JSON.stringify(data)
        }
      );

      if (!response.ok) {
        throw new Error(`Supabase error: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      logError('Failed to upsert to Supabase:', error);
      throw error;
    }
  }

  // ==================== 数据采集 ====================

  /**
   * 从表格行提取笔记数据
   */
  function extractNoteFromRow(row, index) {
    try {
      // 获取所有单元格
      const cells = row.querySelectorAll('td');
      if (cells.length < 5) {
        log(`Row ${index}: Not enough cells (${cells.length})`);
        return null;
      }

      // 第一列：笔记信息
      const noteCell = cells[0];
      const titleEl = noteCell.querySelector('a, .title, [class*="title"]');
      const dateEl = noteCell.querySelector('.date, .time, [class*="date"], [class*="time"], span:last-child');
      const coverEl = noteCell.querySelector('img');

      // 提取标题和链接
      let title = '';
      let noteUrl = '';
      let feedId = '';

      if (titleEl) {
        title = titleEl.textContent.trim();
        noteUrl = titleEl.href || '';

        // 方法1：从标题链接提取 feed_id
        log(`[Feed ID Extract] Title URL: ${noteUrl}`);
        feedId = extractFeedIdFromUrl(noteUrl);
        if (feedId) {
          log(`[Feed ID Extract] ✅ Extracted from title URL: ${feedId}`);
        }
      }

      // 方法2：从"详情数据"链接提取 feedId
      if (!feedId) {
        const lastCell = cells[cells.length - 1];
        const detailLink = lastCell.querySelector('a');
        if (detailLink && detailLink.href) {
          log(`[Feed ID Extract] Detail URL: ${detailLink.href}`);
          feedId = extractFeedIdFromUrl(detailLink.href);
          if (feedId) {
            log(`[Feed ID Extract] ✅ Extracted from detail link: ${feedId}`);
          }
        }
      }

      // 方法3：从行的 data 属性提取
      if (!feedId) {
        feedId = row.dataset.noteId || row.dataset.feedId || row.dataset.id || '';
        if (feedId) {
          log(`[Feed ID Extract] ✅ Extracted from data attributes: ${feedId}`);
        }
      }

      // 方法4：从封面图 URL 提取
      if (!feedId && coverEl && coverEl.src) {
        log(`[Feed ID Extract] Cover URL: ${coverEl.src}`);
        const coverMatch = coverEl.src.match(/\/([a-f0-9]{24})\//i);
        if (coverMatch) {
          feedId = coverMatch[1];
          log(`[Feed ID Extract] ✅ Extracted from cover URL: ${feedId}`);
        }
      }

      // Final check
      if (!feedId) {
        log(`[Feed ID Extract] ⚠️ Could not extract feed_id for: ${title}`);
      }

      // 提取发布日期
      let publishedAt = '';
      if (dateEl) {
        const dateText = dateEl.textContent.trim();
        // 格式: "发布于2025-12-02 21:42" 或 "2025-12-02 21:42"
        const dateMatch = dateText.match(/(\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2})/);
        if (dateMatch) {
          publishedAt = dateMatch[1].replace(/\s+/, 'T') + ':00';
        }
      }

      // 提取封面图
      const coverUrl = coverEl ? coverEl.src : '';

      // 提取数据列
      // 根据截图顺序：曝光、观看、封面点击率、点赞、评论、收藏
      const impressions = parseNumber(getText(cells[1]));
      const views = parseNumber(getText(cells[2]));
      const clickRate = parseNumber(getText(cells[3]));
      const likes = parseNumber(getText(cells[4]));
      const comments = parseNumber(getText(cells[5]));
      const collects = parseNumber(getText(cells[6]));

      // 计算互动率
      const engagementRate = views > 0
        ? ((likes + comments + collects) / views * 100).toFixed(2)
        : 0;

      // 生成唯一标识（用于没有 feedId 时的匹配）
      const titleHash = generateTitleHash(title, publishedAt);

      const noteData = {
        title,
        feedId,
        titleHash,  // 新增：用于标题匹配
        noteUrl,
        coverUrl,
        publishedAt,
        impressions,
        views,
        clickRate,
        likes,
        comments,
        collects,
        engagementRate: parseFloat(engagementRate),
        collectedAt: new Date().toISOString()
      };

      log(`Extracted note ${index}:`, title, { feedId: feedId || '(none)', likes, collects, views });

      return noteData;
    } catch (error) {
      logError(`Error extracting row ${index}:`, error);
      return null;
    }
  }

  /**
   * 从 URL 提取 feedId
   */
  function extractFeedIdFromUrl(url) {
    if (!url) return '';

    const patterns = [
      /\/explore\/([a-f0-9]{24})/i,
      /\/discovery\/item\/([a-f0-9]{24})/i,
      /\/note\/([a-f0-9]{24})/i,
      /\/creator\/note\/([a-f0-9]{24})/i,
      /note_id=([a-f0-9]{24})/i,
      /noteId=([a-f0-9]{24})/i,
      /[?&]id=([a-f0-9]{24})/i,
      /\/([a-f0-9]{24})(?:\?|$)/i  // URL 末尾的 24 位十六进制
    ];

    for (const pattern of patterns) {
      const match = url.match(pattern);
      if (match) {
        return match[1];
      }
    }

    return '';
  }

  /**
   * 生成标题哈希（用于没有 feedId 时的匹配）
   */
  function generateTitleHash(title, publishedAt) {
    // 简单哈希：标题前20字符 + 发布日期
    const normalizedTitle = (title || '').substring(0, 20).toLowerCase().replace(/\s/g, '');
    const dateStr = publishedAt ? publishedAt.split('T')[0] : '';
    return `${normalizedTitle}_${dateStr}`;
  }

  /**
   * 采集当前页面的所有笔记数据
   */
  async function collectCurrentPageData() {
    log('Starting data collection...');

    // 等待页面加载
    await sleep(1000);

    // 查找数据表格
    const table = findElement(CONFIG.selectors.dataTable);
    if (!table) {
      logError('Data table not found');
      return [];
    }

    // 查找所有数据行
    const rows = table.querySelectorAll('tbody tr');
    log(`Found ${rows.length} rows`);

    const notes = [];

    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];

      // 跳过空行或标题行
      if (row.querySelector('th') || !row.querySelector('td')) {
        continue;
      }

      const noteData = extractNoteFromRow(row, i);
      if (noteData && noteData.title) {
        notes.push(noteData);
      }
    }

    log(`Collected ${notes.length} notes`);
    return notes;
  }

  /**
   * 采集所有页面数据（处理分页）
   */
  async function collectAllPagesData() {
    const allNotes = [];
    let pageNum = 1;
    const maxPages = 10; // 最多采集10页

    while (pageNum <= maxPages) {
      log(`Collecting page ${pageNum}...`);

      const notes = await collectCurrentPageData();
      allNotes.push(...notes);

      // 查找下一页按钮
      const nextBtn = findElement(CONFIG.selectors.nextPageBtn);
      if (!nextBtn || nextBtn.disabled || nextBtn.classList.contains('disabled')) {
        log('No more pages');
        break;
      }

      // 点击下一页
      nextBtn.click();
      await sleep(2000); // 等待页面加载

      pageNum++;
    }

    log(`Total collected: ${allNotes.length} notes from ${pageNum} pages`);
    return allNotes;
  }

  // ==================== 保存数据 ====================

  /**
   * 保存采集的数据到 Supabase
   */
  async function saveCollectedData(notes, userId) {
    if (!notes || notes.length === 0) {
      log('No data to save');
      return;
    }

    log(`Saving ${notes.length} notes for user ${userId}...`);

    try {
      // 准备笔记主表数据
      const publishedNotes = notes.map(note => ({
        user_id: userId,
        feed_id: note.feedId || null,
        title_hash: note.titleHash || null,  // 添加 title_hash
        title: note.title,
        cover_url: note.coverUrl,
        published_url: note.noteUrl,
        published_at: note.publishedAt || null,
        status: 'published'
      }));

      // 准备分析数据
      const analyticsData = notes.map(note => ({
        user_id: userId,
        feed_id: note.feedId || null,
        title_hash: note.titleHash || null,  // 添加 title_hash
        impressions: note.impressions,
        views: note.views,
        click_rate: note.clickRate,
        likes: note.likes,
        comments: note.comments,
        collects: note.collects,
        engagement_rate: note.engagementRate,
        collected_at: note.collectedAt,
        source: 'creator_center'
      }));


      // 发送给 background.js 处理保存
      chrome.runtime.sendMessage({
        action: 'SYNC_ANALYTICS_TO_SUPABASE',
        data: {
          userId,
          publishedNotes,
          analyticsData,
          syncType: 'manual',
          collectedAt: new Date().toISOString()
        }
      }, (response) => {
        if (response && response.success) {
          log('Data saved successfully:', response);
          showNotification('数据同步成功', `已同步 ${notes.length} 条笔记数据`);
        } else {
          const errorMsg = response?.error || JSON.stringify(response);
          logError('Failed to save data:', errorMsg);
          showNotification('数据同步失败', errorMsg, 'error');
        }
      });

    } catch (error) {
      logError('Error saving data:', error);
      showNotification('数据同步失败', error.message, 'error');
    }
  }

  // ==================== UI ====================

  /**
   * 显示通知
   */
  function showNotification(title, message, type = 'success') {
    // 创建通知元素
    const notification = document.createElement('div');
    notification.className = 'prome-notification';
    notification.innerHTML = `
      <div class="prome-notification-content ${type}">
        <div class="prome-notification-icon">${type === 'success' ? '✅' : '❌'}</div>
        <div class="prome-notification-text">
          <div class="prome-notification-title">${title}</div>
          <div class="prome-notification-message">${message}</div>
        </div>
        <button class="prome-notification-close">×</button>
      </div>
    `;

    // 添加样式
    const style = document.createElement('style');
    style.textContent = `
      .prome-notification {
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 999999;
        animation: slideIn 0.3s ease;
      }
      @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
      }
      .prome-notification-content {
        display: flex;
        align-items: center;
        padding: 12px 16px;
        background: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        min-width: 280px;
      }
      .prome-notification-content.success {
        border-left: 4px solid #52c41a;
      }
      .prome-notification-content.error {
        border-left: 4px solid #ff4d4f;
      }
      .prome-notification-icon {
        font-size: 20px;
        margin-right: 12px;
      }
      .prome-notification-title {
        font-weight: 600;
        color: #333;
        margin-bottom: 4px;
      }
      .prome-notification-message {
        font-size: 13px;
        color: #666;
      }
      .prome-notification-close {
        margin-left: auto;
        background: none;
        border: none;
        font-size: 18px;
        cursor: pointer;
        color: #999;
        padding: 0 4px;
      }
      .prome-notification-close:hover {
        color: #333;
      }
    `;

    document.head.appendChild(style);
    document.body.appendChild(notification);

    // 点击关闭
    notification.querySelector('.prome-notification-close').onclick = () => {
      notification.remove();
    };

    // 自动关闭
    setTimeout(() => {
      notification.remove();
    }, 5000);
  }

  /**
   * 添加采集按钮到页面
   */
  function addCollectButton() {
    // 检查是否已添加
    if (document.getElementById('prome-collect-btn')) {
      return;
    }

    // 查找导出按钮位置
    const exportBtn = findElement('button:has-text("导出"), .export-btn, [class*="export"]');

    // 创建采集按钮
    const collectBtn = document.createElement('button');
    collectBtn.id = 'prome-collect-btn';
    collectBtn.innerHTML = '📊 同步到 Prome';
    collectBtn.style.cssText = `
      margin-left: 12px;
      padding: 8px 16px;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      border: none;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
    `;

    collectBtn.onmouseover = () => {
      collectBtn.style.transform = 'translateY(-1px)';
      collectBtn.style.boxShadow = '0 4px 12px rgba(102, 126, 234, 0.4)';
    };

    collectBtn.onmouseout = () => {
      collectBtn.style.transform = 'translateY(0)';
      collectBtn.style.boxShadow = 'none';
    };

    collectBtn.onclick = async () => {
      collectBtn.disabled = true;
      collectBtn.innerHTML = '⏳ 采集中...';

      try {
        // 优先使用小红书账号的稳定 ID（从 Cookie 哈希生成）
        // 这样即使用户没有在 Prome 登录，也能正确关联数据
        let userId = await getXhsAccountId();

        // 如果无法获取稳定 ID，降级使用配置中的 userId
        if (!userId) {
          const config = await getSupabaseConfig();
          userId = config.userId || 'unknown';
          log('Fallback to config userId:', userId);
        } else {
          log('Using stable XHS account ID:', userId);
        }

        // 采集数据
        const notes = await collectCurrentPageData();

        if (notes.length === 0) {
          showNotification('采集完成', '未找到笔记数据', 'error');
          return;
        }

        // 保存数据
        await saveCollectedData(notes, userId);

      } catch (error) {
        logError('Collection failed:', error);
        showNotification('采集失败', error.message, 'error');
      } finally {
        collectBtn.disabled = false;
        collectBtn.innerHTML = '📊 同步到 Prome';
      }
    };

    // 插入按钮
    if (exportBtn && exportBtn.parentElement) {
      exportBtn.parentElement.appendChild(collectBtn);
    } else {
      // 备选：添加到页面右上角
      collectBtn.style.position = 'fixed';
      collectBtn.style.top = '80px';
      collectBtn.style.right = '20px';
      collectBtn.style.zIndex = '9999';
      document.body.appendChild(collectBtn);
    }

    log('Collect button added');
  }

  // ==================== 初始化 ====================

  /**
   * 检查是否在数据分析页面
   */
  function isAnalyticsPage() {
    return window.location.href.includes('/statistics');
  }

  /**
   * 检查是否需要自动同步
   */
  async function shouldAutoSync() {
    return new Promise((resolve) => {
      chrome.storage.local.get(['lastAutoSync', 'autoSyncEnabled'], (result) => {
        // 默认启用自动同步
        const enabled = result.autoSyncEnabled !== false;
        if (!enabled) {
          resolve(false);
          return;
        }

        const lastSync = result.lastAutoSync || 0;
        const now = Date.now();
        const timeSinceLastSync = now - lastSync;

        // 如果距离上次同步超过6小时，则需要同步
        resolve(timeSinceLastSync > CONFIG.autoCollectInterval);
      });
    });
  }

  /**
   * 执行自动同步
   */
  async function performAutoSync() {
    log('Performing auto sync...');

    try {
      // 优先使用小红书账号的稳定 ID
      let userId = await getXhsAccountId();

      if (!userId) {
        const config = await getSupabaseConfig();
        userId = config.userId || 'unknown';
      }

      if (!userId || userId === 'unknown') {
        log('No user ID available, skipping auto sync');
        return;
      }

      log('Auto sync with user ID:', userId);

      // 等待页面完全加载
      await sleep(3000);

      // 采集数据
      const notes = await collectCurrentPageData();

      if (notes.length === 0) {
        log('No notes found for auto sync');
        return;
      }

      // 保存数据
      await saveCollectedData(notes, userId);

      // 记录同步时间
      await chrome.storage.local.set({ lastAutoSync: Date.now() });

      log(`Auto sync completed: ${notes.length} notes`);
      showNotification('自动同步完成', `已同步 ${notes.length} 条笔记数据`);

    } catch (error) {
      logError('Auto sync failed:', error);
    }
  }

  /**
   * 初始化采集器
   */
  async function init() {
    log(`Analytics Collector v${COLLECTOR_VERSION} initializing...`);

    if (!isAnalyticsPage()) {
      log('Not on analytics page, skipping');
      return;
    }

    // 等待页面加载完成
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        setTimeout(onPageReady, 1000);
      });
    } else {
      setTimeout(onPageReady, 1000);
    }

    // 监听 URL 变化（SPA）
    let lastUrl = location.href;
    new MutationObserver(() => {
      if (location.href !== lastUrl) {
        lastUrl = location.href;
        if (isAnalyticsPage()) {
          setTimeout(onPageReady, 1000);
        }
      }
    }).observe(document.body, { childList: true, subtree: true });

    log('Analytics Collector initialized');
  }

  /**
   * 页面准备就绪时的处理
   */
  async function onPageReady() {
    // 添加手动采集按钮
    addCollectButton();

    // 检查是否需要自动同步
    if (CONFIG.autoCollectOnLoad) {
      const needSync = await shouldAutoSync();
      if (needSync) {
        log('Auto sync needed, starting...');
        // 延迟执行，让页面完全加载
        setTimeout(performAutoSync, 5000);
      } else {
        log('Auto sync not needed yet');
      }
    }
  }

  // 启动
  init();

  // 暴露给外部调用
  window.PromeAnalyticsCollector = {
    collect: collectCurrentPageData,
    collectAll: collectAllPagesData,
    save: saveCollectedData,
    autoSync: performAutoSync,
    version: COLLECTOR_VERSION
  };

})();
