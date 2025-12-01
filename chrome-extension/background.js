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

      // 首先检查当前是否在小红书页面
      const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const isOnXhsSite = activeTab?.url && (
        activeTab.url.includes('xiaohongshu.com') ||
        activeTab.url.includes('xhscdn.com')
      );

      console.log(`📍 [Prome Extension] Current tab:`, activeTab?.url);
      console.log(`✅ [Prome Extension] On XHS site:`, isOnXhsSite);

      // 尝试多种方式获取 Cookie
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

      // 如果没有找到Cookie，给出详细指导
      if (cookies.length === 0) {
        console.error("❌ [Prome Extension] No cookies found!");

        const errorMsg = isOnXhsSite
          ? "未检测到小红书 Cookie。请确保您已登录小红书创作平台，然后刷新此页面重试。"
          : `未检测到小红书 Cookie。\n\n请按以下步骤操作：\n1. 在新标签页中打开并登录 https://creator.xiaohongshu.com\n2. 登录成功后，切换回本页面\n3. 再次点击"一键连接小红书"按钮\n\n或者：\n请确保您已经在 Chrome 中登录小红书创作平台，然后重新加载此插件（chrome://extensions 中点击重新加载）`;

        sendResponse({ success: false, msg: errorMsg });
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
