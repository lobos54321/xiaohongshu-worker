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

      // 尝试多种方式获取 Cookie，以防漏掉
      const [domainCookies, creatorCookies, wwwCookies] = await Promise.all([
        chrome.cookies.getAll({ domain: "xiaohongshu.com" }),
        chrome.cookies.getAll({ url: "https://creator.xiaohongshu.com" }),
        chrome.cookies.getAll({ url: "https://www.xiaohongshu.com" })
      ]);

      console.log(`📊 [Prome Extension] Cookie counts:`, {
        domain: domainCookies.length,
        creator: creatorCookies.length,
        www: wwwCookies.length
      });
      console.log(`📋 [Prome Extension] Domain cookies:`, domainCookies.map(c => c.name));
      console.log(`📋 [Prome Extension] Creator cookies:`, creatorCookies.map(c => c.name));
      console.log(`📋 [Prome Extension] WWW cookies:`, wwwCookies.map(c => c.name));

      // 合并并去重
      const allCookies = [...domainCookies, ...creatorCookies, ...wwwCookies];
      const uniqueCookiesMap = new Map();
      allCookies.forEach(c => uniqueCookiesMap.set(c.name + c.domain, c));
      const cookies = Array.from(uniqueCookiesMap.values());

      console.log(`✅ [Prome Extension] Total unique cookies: ${cookies.length}`);
      console.log(`📝 [Prome Extension] Cookie names:`, cookies.map(c => c.name));

      // Relaxed check: Just pass all cookies to backend for verification
      if (cookies.length === 0) {
        console.error("❌ [Prome Extension] No cookies found!");
        sendResponse({ success: false, msg: "未检测到任何小红书 Cookie，请确保您已登录 https://creator.xiaohongshu.com 并刷新此页面后重试" });
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
