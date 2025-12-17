/**
 * Step Executor for AI Control Center
 * 
 * 负责从 Supabase 拉取 pending steps 并执行
 * 使用 lock_task_step / finish_task_step RPC 实现并发安全
 * 
 * @version 1.0.0 - Phase 1 MVP
 */

// ==================== Step Executor 配置 ====================
const STEP_EXECUTOR_CONFIG = {
    // 轮询间隔（毫秒）
    POLL_INTERVAL: 30000,  // 30 秒
    // 锁定标识
    LOCK_OWNER: 'prome-extension-v1.1.0',
    // 支持的 step 类型
    SUPPORTED_STEP_TYPES: ['publish', 'fetch_metrics'],
};

// ==================== Step Executor 状态 ====================
let stepExecutorState = {
    isRunning: false,
    pollTimer: null,
    currentStep: null,
    xhsAccountId: null,  // 当前登录的小红书账号 ID
};

/**
 * 初始化 Step Executor
 * @param {string} xhsAccountId - xhs_accounts 表中的 UUID
 */
async function initStepExecutor(xhsAccountId) {
    log('[StepExecutor] Initializing with account:', xhsAccountId);
    stepExecutorState.xhsAccountId = xhsAccountId;

    if (stepExecutorState.isRunning) {
        log('[StepExecutor] Already running, skipping init');
        return;
    }

    stepExecutorState.isRunning = true;

    // 启动轮询
    startStepPolling();

    log('[StepExecutor] Initialized successfully');
}

/**
 * 停止 Step Executor
 */
function stopStepExecutor() {
    log('[StepExecutor] Stopping...');
    stepExecutorState.isRunning = false;

    if (stepExecutorState.pollTimer) {
        clearInterval(stepExecutorState.pollTimer);
        stepExecutorState.pollTimer = null;
    }

    log('[StepExecutor] Stopped');
}

/**
 * 启动定时轮询
 */
function startStepPolling() {
    if (stepExecutorState.pollTimer) {
        clearInterval(stepExecutorState.pollTimer);
    }

    // 立即执行一次
    pollPendingSteps();

    // 设置定时轮询
    stepExecutorState.pollTimer = setInterval(
        pollPendingSteps,
        STEP_EXECUTOR_CONFIG.POLL_INTERVAL
    );

    log('[StepExecutor] Polling started, interval:', STEP_EXECUTOR_CONFIG.POLL_INTERVAL);
}

/**
 * 拉取待执行的 Steps
 */
async function pollPendingSteps() {
    if (!stepExecutorState.isRunning || !stepExecutorState.xhsAccountId) {
        return;
    }

    if (stepExecutorState.currentStep) {
        log('[StepExecutor] Already executing a step, skipping poll');
        return;
    }

    try {
        const config = await getSupabaseConfigFromStorage();
        if (!config.url || !config.key) {
            log('[StepExecutor] Supabase not configured, skipping poll');
            return;
        }

        // 查询 pending steps（限定当前账号、支持的类型、scheduled_at <= now）
        const now = new Date().toISOString();
        const response = await fetch(
            `${config.url}/rest/v1/xhs_task_steps?` +
            `xhs_account_id=eq.${stepExecutorState.xhsAccountId}&` +
            `status=eq.pending&` +
            `step_type=in.(${STEP_EXECUTOR_CONFIG.SUPPORTED_STEP_TYPES.join(',')})&` +
            `or=(scheduled_at.is.null,scheduled_at.lte.${encodeURIComponent(now)})&` +
            `order=created_at.asc&` +
            `limit=1`,
            {
                headers: {
                    'apikey': config.key,
                    'Authorization': `Bearer ${config.key}`,
                    'Content-Type': 'application/json'
                }
            }
        );

        if (!response.ok) {
            throw new Error(`Failed to fetch pending steps: ${response.status}`);
        }

        const steps = await response.json();

        if (steps.length === 0) {
            log('[StepExecutor] No pending steps for this account');
            return;
        }

        const step = steps[0];
        log('[StepExecutor] Found pending step:', step.id, step.step_type);

        // 尝试锁定
        await executeStep(step, config);

    } catch (error) {
        logError('[StepExecutor] Poll error:', error);
    }
}

/**
 * 执行单个 Step
 * @param {Object} step - Step 对象
 * @param {Object} config - Supabase 配置
 */
async function executeStep(step, config) {
    try {
        // 1. 锁定 Step
        const lockResult = await lockTaskStep(step.id, config);
        if (!lockResult) {
            log('[StepExecutor] Failed to lock step (already taken or not eligible)');
            return;
        }

        stepExecutorState.currentStep = lockResult;
        log('[StepExecutor] Step locked:', lockResult.id);

        // 2. 根据类型执行
        let result;
        switch (step.step_type) {
            case 'publish':
                result = await executePublishStep(lockResult, config);
                break;
            case 'fetch_metrics':
                result = await executeFetchMetricsStep(lockResult, config);
                break;
            default:
                result = { success: false, error: `Unsupported step type: ${step.step_type}` };
        }

        // 3. 完成 Step
        await finishTaskStep(
            lockResult.id,
            result.success ? 'succeeded' : 'failed',
            result.output || {},
            result.usage || {},
            'prome-extension',
            null,
            result.error ? { error: result.error } : null,
            config
        );

        log('[StepExecutor] Step completed:', lockResult.id, result.success ? 'succeeded' : 'failed');

        // 4. 刷新 Task 状态
        await refreshTaskStatus(lockResult.task_id, config);

    } catch (error) {
        logError('[StepExecutor] Execute error:', error);

        // 尝试标记为失败
        if (stepExecutorState.currentStep) {
            try {
                await finishTaskStep(
                    stepExecutorState.currentStep.id,
                    'failed',
                    {},
                    {},
                    'prome-extension',
                    null,
                    { error: error.message },
                    config
                );
            } catch (finishError) {
                logError('[StepExecutor] Failed to mark step as failed:', finishError);
            }
        }
    } finally {
        stepExecutorState.currentStep = null;
    }
}

/**
 * 锁定 Step（调用 RPC）
 * @returns {Object|null} 锁定的 step 或 null
 */
async function lockTaskStep(stepId, config) {
    const response = await fetch(
        `${config.url}/rest/v1/rpc/lock_task_step`,
        {
            method: 'POST',
            headers: {
                'apikey': config.key,
                'Authorization': `Bearer ${config.key}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                p_step_id: stepId,
                p_lock_owner: STEP_EXECUTOR_CONFIG.LOCK_OWNER
            })
        }
    );

    if (!response.ok) {
        const error = await response.text();
        logError('[StepExecutor] Lock RPC failed:', error);
        return null;
    }

    const result = await response.json();

    // RPC 返回数组（SETOF）
    if (Array.isArray(result) && result.length > 0) {
        return result[0];
    }

    return null;
}

/**
 * 完成 Step（调用 RPC）
 */
async function finishTaskStep(stepId, status, outputPayload, usage, provider, providerRunId, error, config) {
    const response = await fetch(
        `${config.url}/rest/v1/rpc/finish_task_step`,
        {
            method: 'POST',
            headers: {
                'apikey': config.key,
                'Authorization': `Bearer ${config.key}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                p_step_id: stepId,
                p_status: status,
                p_output_payload: outputPayload,
                p_usage: usage,
                p_provider: provider,
                p_provider_run_id: providerRunId,
                p_error: error
            })
        }
    );

    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Finish RPC failed: ${errorText}`);
    }

    return await response.json();
}

/**
 * 刷新 Task 状态（调用 RPC）
 */
async function refreshTaskStatus(taskId, config) {
    try {
        const response = await fetch(
            `${config.url}/rest/v1/rpc/refresh_task_status`,
            {
                method: 'POST',
                headers: {
                    'apikey': config.key,
                    'Authorization': `Bearer ${config.key}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    p_task_id: taskId
                })
            }
        );

        if (response.ok) {
            const newStatus = await response.json();
            log('[StepExecutor] Task status refreshed:', newStatus);
        }
    } catch (error) {
        logError('[StepExecutor] Failed to refresh task status:', error);
    }
}

// ==================== Step Handlers ====================

/**
 * 执行 publish step
 * 
 * 🔥 Phase 1: 读取 input_snapshot，获取 task 的 title/content，触发发布
 */
async function executePublishStep(step, config) {
    log('[StepExecutor] Executing publish step...');

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
            throw new Error('Failed to fetch task');
        }

        const tasks = await taskResponse.json();
        if (tasks.length === 0) {
            throw new Error('Task not found');
        }

        const task = tasks[0];

        // 2. 检查 review_mode（从 task.metadata 读取）
        const reviewMode = task.metadata?.review_mode || 'manual_confirm';

        if (reviewMode === 'manual_confirm') {
            // 需要用户手动确认
            log('[StepExecutor] Publish requires manual confirmation');

            // 发送通知给用户（通过 popup 或 notification）
            await chrome.notifications.create(`publish_confirm_${step.id}`, {
                type: 'basic',
                iconUrl: 'icons/icon128.png',
                title: '发布确认',
                message: `待发布内容: ${task.title || '(无标题)'}\n点击确认发布`,
                buttons: [
                    { title: '立即发布' },
                    { title: '稍后发布' }
                ],
                priority: 2,
                requireInteraction: true
            });

            // 返回等待状态（不算失败，step 会保持 running 状态等待用户确认）
            // 🔥 这里需要重新设计：Phase 1 先跳过，返回 mock 成功
            return {
                success: true,
                output: {
                    note_id: 'mock_note_id_' + Date.now(),
                    note_url: 'https://xiaohongshu.com/mock',
                    published_at: new Date().toISOString(),
                    mock: true,
                    review_mode: reviewMode
                }
            };
        }

        // 3. auto_publish 模式：直接发布
        // 🔥 Phase 1: Mock 发布逻辑
        log('[StepExecutor] Auto-publishing...');

        // 实际发布逻辑将在 Phase 2 实现
        // 这里返回 mock 结果
        return {
            success: true,
            output: {
                note_id: 'mock_note_id_' + Date.now(),
                note_url: 'https://xiaohongshu.com/mock',
                published_at: new Date().toISOString(),
                mock: true
            }
        };

    } catch (error) {
        logError('[StepExecutor] Publish step failed:', error);
        return {
            success: false,
            error: error.message
        };
    }
}

/**
 * 执行 fetch_metrics step
 * 
 * 🔥 Phase 2: 主动抓取实现
 */
async function executeFetchMetricsStep(step, config) {
    log('[StepExecutor] Executing fetch_metrics step...');

    try {
        const noteId = step.input_snapshot?.note_id;
        const feedId = step.input_snapshot?.feed_id;
        const titleHash = step.input_snapshot?.title_hash;
        const metricsWindow = step.input_snapshot?.metrics_window || '24h';

        // 如果没有有效的标识符，返回空数据
        if (!feedId && !titleHash && (!noteId || noteId === 'unknown' || noteId.startsWith('mock_'))) {
            log('[StepExecutor] No valid identifier for fetch_metrics');
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

        log('[StepExecutor] Starting active metrics fetch...');
        log('[StepExecutor] Target:', { feedId, titleHash, noteId });

        // 1. 打开小红书创作者中心统计页面
        const statisticsUrl = 'https://creator.xiaohongshu.com/statistics/data-analysis';

        log('[StepExecutor] Opening statistics page:', statisticsUrl);

        const tab = await chrome.tabs.create({
            url: statisticsUrl,
            active: false  // 后台打开
        });

        log('[StepExecutor] Tab created:', tab.id);

        // 2. 等待页面加载
        await new Promise((resolve) => {
            const checkLoaded = () => {
                chrome.tabs.get(tab.id, (tabInfo) => {
                    if (chrome.runtime.lastError) {
                        resolve();
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

        // 3. 等待数据表格渲染
        await new Promise(resolve => setTimeout(resolve, 3000));

        // 4. 注入脚本抓取数据
        log('[StepExecutor] Injecting scraper script...');

        const scrapeResult = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: (targetFeedId, targetTitleHash) => {
                try {
                    const table = document.querySelector('table');
                    if (!table) {
                        return { success: false, error: 'Table not found' };
                    }

                    const rows = table.querySelectorAll('tbody tr');
                    const allNotes = [];

                    for (let i = 0; i < rows.length; i++) {
                        const row = rows[i];
                        const cells = row.querySelectorAll('td');
                        if (cells.length < 5) continue;

                        const noteCell = cells[0];
                        const titleEl = noteCell.querySelector('a, .title');
                        const title = titleEl ? titleEl.textContent.trim() : '';
                        const noteUrl = titleEl ? titleEl.href : '';

                        let feedId = '';
                        const patterns = [/\/explore\/([a-f0-9]{24})/i, /\/note\/([a-f0-9]{24})/i];

                        for (const pattern of patterns) {
                            const match = noteUrl.match(pattern);
                            if (match) { feedId = match[1]; break; }
                        }

                        // 从详情链接提取
                        if (!feedId) {
                            const lastCell = cells[cells.length - 1];
                            const detailLink = lastCell.querySelector('a');
                            if (detailLink && detailLink.href) {
                                for (const pattern of patterns) {
                                    const match = detailLink.href.match(pattern);
                                    if (match) { feedId = match[1]; break; }
                                }
                            }
                        }

                        const normalizedTitle = (title || '').substring(0, 20).toLowerCase().replace(/\s/g, '');
                        const titleHash = `${normalizedTitle}_`;

                        const parseNum = (text) => {
                            if (!text) return 0;
                            text = text.toString().trim();
                            if (text === '-' || text === '' || text === '--') return 0;
                            text = text.replace('+', '');
                            if (text.includes('万')) return Math.round(parseFloat(text.replace('万', '')) * 10000);
                            if (text.toLowerCase().includes('k')) return Math.round(parseFloat(text.replace(/k/i, '')) * 1000);
                            return parseInt(text.replace(/,/g, ''), 10) || 0;
                        };

                        allNotes.push({
                            title, feedId, titleHash,
                            impressions: parseNum(cells[1]?.textContent),
                            views: parseNum(cells[2]?.textContent),
                            clickRate: parseNum(cells[3]?.textContent),
                            likes: parseNum(cells[4]?.textContent),
                            comments: parseNum(cells[5]?.textContent),
                            collects: parseNum(cells[6]?.textContent)
                        });
                    }

                    let targetNote = null;
                    if (targetFeedId) {
                        targetNote = allNotes.find(n => n.feedId === targetFeedId);
                    }
                    if (!targetNote && targetTitleHash) {
                        targetNote = allNotes.find(n => n.titleHash.startsWith(targetTitleHash.substring(0, 10)));
                    }

                    return { success: true, data: targetNote, allNotes };
                } catch (error) {
                    return { success: false, error: error.message };
                }
            },
            args: [feedId || '', titleHash || '']
        });

        // 5. 关闭标签页
        try { await chrome.tabs.remove(tab.id); } catch (e) { }

        // 6. 处理结果
        const result = scrapeResult[0]?.result;
        log('[StepExecutor] Scrape result:', result);

        if (!result || !result.success) {
            return { success: false, error: result?.error || 'Scrape failed' };
        }

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

        // 如果没找到目标但有数据
        if (result.allNotes && result.allNotes.length > 0) {
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

        return {
            success: true,
            output: {
                note_id: noteId,
                metrics_window: metricsWindow,
                fetched_at: new Date().toISOString(),
                impressions: 0, views: 0, likes: 0, comments: 0, collects: 0,
                source: 'active_fetch_empty',
                reason: 'No notes found'
            }
        };

    } catch (error) {
        logError('[StepExecutor] Fetch metrics step failed:', error);
        return { success: false, error: error.message };
    }
}

// ==================== 导出给 background.js 使用 ====================

// 注意：这些函数将被注入到 background.js 中使用
// 需要在 background.js 中调用 initStepExecutor(xhsAccountId)
