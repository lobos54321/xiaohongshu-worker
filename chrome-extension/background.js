// 监听来自 Prome 网页的消息
// 处理具体的业务逻辑
const handleRequest = async (request, sendResponse) => {
  if (request.action === "PING") {
    sendResponse({ status: "INSTALLED" });
    return;
  }

  if (request.action === "SYNC_XHS") {
    try {
      console.log("🔍 [Prome Extension] Starting cookie sync...");
      const ua = navigator.userAgent;

      // 方法1: 尝试通过 chrome.cookies API 获取
      const [domainCookies, creatorCookies, wwwCookies] = await Promise.all([
        chrome.cookies.getAll({ domain: "xiaohongshu.com" }),
        chrome.cookies.getAll({ url: "https://creator.xiaohongshu.com" }),
        chrome.cookies.getAll({ url: "https://www.xiaohongshu.com" })
      ]);

      console.log(`📊 [Prome Extension] Cookie API counts:`, {
        domain: domainCookies.length,
        creator: creatorCookies.length,
        www: wwwCookies.length
      });

      // 合并 API 获取的 cookies
      const allCookies = [...domainCookies, ...creatorCookies, ...wwwCookies];
      const uniqueCookiesMap = new Map();
      allCookies.forEach(c => uniqueCookiesMap.set(c.name + c.domain, c));
      let cookies = Array.from(uniqueCookiesMap.values());

      console.log(`✅ [Prome Extension] Total cookies from API: ${cookies.length}`);

      // 方法2: 如果 API 无法获取，尝试从 xiaohongshu.com 标签页注入脚本获取
      if (cookies.length === 0) {
        console.log("⚠️ [Prome Extension] Cookie API failed, trying tab injection...");

        try {
          // 查找所有小红书相关的标签页
          const xhsTabs = await chrome.tabs.query({
            url: ["*://*.xiaohongshu.com/*"]
          });

          console.log(`📑 [Prome Extension] Found ${xhsTabs.length} XHS tabs`);

          if (xhsTabs.length > 0) {
            // 使用第一个找到的小红书标签页
            const tab = xhsTabs[0];
            console.log(`🎯 [Prome Extension] Using tab: ${tab.url}`);

            // 注入脚本获取 document.cookie
            const results = await chrome.scripting.executeScript({
              target: { tabId: tab.id },
              func: () => document.cookie
            });

            if (results && results[0] && results[0].result) {
              const cookieString = results[0].result;
              console.log(`🍪 [Prome Extension] Got cookie string from page: ${cookieString.substring(0, 100)}...`);

              // 解析 cookie 字符串为对象数组
              const parsedCookies = cookieString.split('; ').map(c => {
                const [name, ...valueParts] = c.split('=');
                return {
                  name: name,
                  value: valueParts.join('='),
                  domain: '.xiaohongshu.com',
                  path: '/',
                  secure: true,
                  httpOnly: false
                };
              }).filter(c => c.name && c.value);

              console.log(`📝 [Prome Extension] Parsed ${parsedCookies.length} cookies from document.cookie`);
              cookies = parsedCookies;
            }
          } else {
            sendResponse({
              success: false,
              msg: "未找到小红书标签页。\n\n请按以下步骤操作：\n1. 在新标签页中打开 https://creator.xiaohongshu.com 并登录\n2. 保持该标签页打开\n3. 切换回本页面\n4. 再次点击\"一键连接小红书\""
            });
            return;
          }
        } catch (injectionError) {
          console.error("❌ [Prome Extension] Tab injection failed:", injectionError);
        }
      }

      console.log(` [Prome Extension] Final cookie count: ${cookies.length}`);
      console.log(`📝 [Prome Extension] Cookie names:`, cookies.map(c => c.name));

      // 最终检查
      if (cookies.length === 0) {
        console.error("❌ [Prome Extension] No cookies found after all attempts!");
        sendResponse({
          success: false,
          msg: "无法获取小红书 Cookie。\n\n请尝试：\n1. 确保已在 https://creator.xiaohongshu.com 登录\n2. 打开该网站的标签页并保持打开\n3. 刷新 Prome 平台页面\n4. 重新点击连接按钮\n\n如仍无法解决，请联系技术支持。"
        });
        return;
      }

      sendResponse({
        success: true,
        data: { cookies: cookies, ua: ua }
      });
    } catch (err) {
      sendResponse({ success: false, msg: err.message });
    }
  }
};

// 监听来自 Content Script 的消息 (chrome.runtime.sendMessage)
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  handleRequest(request, sendResponse);
  return true; // 支持异步
});

// 监听来自网页的直接消息 (如果有的话，保留兼容性)
chrome.runtime.onMessageExternal.addListener((request, sender, sendResponse) => {
  handleRequest(request, sendResponse);
  return true; // 支持异步
});
