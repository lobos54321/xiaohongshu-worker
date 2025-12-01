# Prome 小红书助手 - Chrome扩展

一个帮助你自动化发布小红书内容的浏览器扩展。

## 功能特性

### 阶段1 - MVP
- ✅ 半自动发布：在扩展中填写内容，一键发布到小红书
- ✅ 图片支持：支持通过URL上传图片
- ✅ 登录状态检测：自动检测小红书登录状态
- ✅ WebSocket实时通信：与后端服务保持长连接

### 阶段2 - 定时发布
- ✅ 定时发布：设置发布时间，到点自动执行
- ✅ 发布计划管理：查看、编辑、删除发布计划
- ✅ 任务状态追踪：实时显示任务执行状态

## 安装方法

### 方法1：开发者模式安装（推荐）

1. 下载本扩展文件夹
2. 打开 Chrome 浏览器，访问 `chrome://extensions/`
3. 开启右上角的"开发者模式"
4. 点击"加载已解压的扩展程序"
5. 选择本扩展文件夹

### 方法2：打包安装

```bash
# 在扩展目录下打包
zip -r prome-extension.zip . -x "*.git*"
```

## 使用方法

### 1. 获取 API Token

1. 访问 [prome.live](https://www.prome.live) 注册/登录
2. 在控制台获取 API Token
3. 复制 Token

### 2. 连接服务

1. 点击浏览器右上角的扩展图标
2. 在输入框中粘贴 API Token
3. 点击"连接服务"
4. 状态显示"已连接"即成功

### 3. 确保小红书已登录

1. 扩展会自动检测小红书登录状态
2. 如果显示"未登录"，点击"打开小红书"进行登录
3. 登录后点击"重新检测"

### 4. 发布内容

#### 立即发布
1. 填写标题（最多20字）
2. 填写正文内容
3. 填写图片URL（每行一个）
4. 点击"立即发布"

#### 定时发布
1. 填写标题和内容
2. 选择发布时间
3. 点击"添加到计划"
4. 任务会在指定时间自动执行

> ⚠️ 注意：定时发布需要保持浏览器运行

## 目录结构

```
prome-extension/
├── manifest.json       # 扩展配置文件
├── background.js       # 后台服务脚本
├── content.js          # 内容脚本（DOM操作）
├── content.css         # 内容脚本样式
├── popup/
│   ├── popup.html      # 弹窗界面
│   ├── popup.css       # 弹窗样式
│   └── popup.js        # 弹窗逻辑
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

## 后端API要求

扩展需要配合后端服务使用，后端需要实现以下接口：

### WebSocket接口
- 地址：`wss://your-backend/ws?token={apiToken}`
- 消息格式：JSON

### HTTP接口
- `GET /api/v1/publish-plan` - 获取发布计划
- `POST /api/v1/publish` - 触发发布（通过WebSocket转发）

## 配置说明

修改 `background.js` 中的配置：

```javascript
const CONFIG = {
  BACKEND_URL: 'https://your-backend.com',  // 后端地址
  WS_URL: 'wss://your-backend.com/ws',      // WebSocket地址
  RECONNECT_INTERVAL: 5000,                  // 重连间隔
  MAX_RECONNECT_ATTEMPTS: 10,                // 最大重连次数
  HEARTBEAT_INTERVAL: 30000,                 // 心跳间隔
  SCHEDULE_CHECK_INTERVAL: 60000,            // 定时检查间隔
};
```

## 常见问题

### Q: 发布失败怎么办？
A: 
1. 检查小红书是否已登录
2. 检查网络连接
3. 确认后端服务正常运行
4. 查看浏览器控制台错误信息

### Q: 定时发布没有执行？
A: 
1. 确保浏览器保持运行
2. 确保扩展保持连接状态
3. 检查发布时间是否正确

### Q: 图片上传失败？
A: 
1. 确保图片URL可以正常访问
2. 检查图片格式（支持jpg、png、webp）
3. 图片大小不要超过20MB

## 开发说明

### 调试方法
1. 打开 `chrome://extensions/`
2. 找到扩展，点击"Service Worker"查看后台日志
3. 打开小红书页面，按F12查看content script日志

### 修改后重新加载
1. 修改代码后，在扩展管理页面点击刷新按钮
2. 或者点击"更新"按钮

## 版本历史

### v1.0.0
- 初始版本
- 支持半自动发布
- 支持定时发布
- 支持发布计划管理

## 许可证

MIT License

## 联系我们

- 官网：[prome.live](https://www.prome.live)
- 问题反馈：请提交 Issue
