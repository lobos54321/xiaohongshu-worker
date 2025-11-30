// 监听来自 Prome 网页的消息
chrome.runtime.onMessageExternal.addListener(
  async (request, sender, sendResponse) => {
    
    // 如果网页问：你在吗？
    if (request.action === "PING") {
      sendResponse({ status: "INSTALLED" });
      return;
    }

    // 如果网页说：把小红书 Cookie 给我
    if (request.action === "SYNC_XHS") {
      try {
        // 1. 获取 Cookie
        const cookies = await chrome.cookies.getAll({ domain: "xiaohongshu.com" });
        const ua = navigator.userAgent;

        if (cookies.length === 0) {
          sendResponse({ success: false, msg: "未检测到小红书登录状态，请先在浏览器中登录小红书" });
          return;
        }

        // 2. 返回给网页
        sendResponse({ 
          success: true, 
          data: { cookies: cookies, ua: ua } 
        });

      } catch (err) {
        sendResponse({ success: false, msg: err.message });
      }
    }
    
    // 必须返回 true 以支持异步 sendResponse
    return true;
  }
);
