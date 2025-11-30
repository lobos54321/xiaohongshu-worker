// 监听来自 Prome 网页的消息
// 处理具体的业务逻辑
const handleRequest = async (request, sendResponse) => {
  if (request.action === "PING") {
    sendResponse({ status: "INSTALLED" });
    return;
  }

  if (request.action === "SYNC_XHS") {
    try {
      const cookies = await chrome.cookies.getAll({ domain: "xiaohongshu.com" });
      const ua = navigator.userAgent;

      if (cookies.length === 0) {
        sendResponse({ success: false, msg: "未检测到小红书登录状态，请先在浏览器中登录小红书" });
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
