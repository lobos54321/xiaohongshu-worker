// 注入标志，让网页知道插件已安装
console.log("Prome Extension Content Script Loaded");

// 注入一个隐藏的 DOM 元素作为标记，比 window 变量更稳定
const installedMarker = document.createElement('div');
installedMarker.id = 'prome-extension-installed';
installedMarker.style.display = 'none';
document.body.appendChild(installedMarker);

// 也可以设置 window 变量，但需要通过 script 注入才行（content script 与页面 JS 隔离）
// 这里我们使用 postMessage 进行通信，这是最通用的方式

// 监听来自网页的消息
window.addEventListener("message", async (event) => {
    // 只接受来自当前窗口的消息
    if (event.source !== window) return;

    if (event.data.type === "SYNC_XHS_REQUEST") {
        console.log("Content Script received sync request");

        try {
            // 转发给 background.js
            chrome.runtime.sendMessage({ action: "SYNC_XHS" }, (response) => {
                // 收到 background 的回复，转发回网页
                window.postMessage({
                    type: "SYNC_XHS_RESPONSE",
                    success: response && response.success,
                    data: response && response.data,
                    msg: response ? response.msg : "Unknown error"
                }, "*");
            });
        } catch (err) {
            console.error("Error sending message to background:", err);
            window.postMessage({
                type: "SYNC_XHS_RESPONSE",
                success: false,
                msg: "插件通信失败: " + err.message
            }, "*");
        }
    }
});
