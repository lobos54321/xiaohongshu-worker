# 选择器管理指南

## 问题：DOM选择器可能随时变化

小红书可能随时更新页面结构，导致选择器失效。本扩展采用以下策略应对：

## 解决方案

### 1. 多重回退选择器

每个元素配置多个候选选择器，按优先级尝试：

```javascript
const SELECTORS = {
  titleInput: [
    'input.d-text[placeholder*="标题"]',  // 主选择器（当前有效）
    'input[placeholder*="填写标题"]',      // 备选1
    'input[placeholder*="标题"]',          // 备选2（更通用）
    'input[maxlength="20"]',               // 备选3（基于属性）
  ],
};
```

### 2. 优先使用稳定属性

选择器优先级（从稳定到不稳定）：

1. **role 属性** - `[role="textbox"]` - 语义化，很少变
2. **type 属性** - `input[type="file"]` - 标准属性
3. **placeholder** - `input[placeholder*="标题"]` - 用户可见文本
4. **contenteditable** - `[contenteditable="true"]` - 功能属性
5. **class名** - `.publishBtn` - 可能频繁变化

### 3. 远程配置更新

扩展会从后端获取最新选择器配置，无需更新扩展：

```
扩展启动 → 请求 /api/v1/selectors → 获取最新配置 → 覆盖本地配置
```

### 4. 管理员更新流程

当发现选择器失效时：

1. **定位新选择器**
   ```bash
   # 在小红书页面打开控制台，找到新的选择器
   document.querySelector('新选择器')
   ```

2. **更新后端配置**
   ```bash
   curl -X PUT https://your-backend/api/v1/selectors \
     -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "version": "2024.12.02",
       "selectors": {
         "titleInput": ["新选择器1", "新选择器2"]
       }
     }'
   ```

3. **自动广播**
   - 后端会自动将更新广播给所有在线扩展
   - 扩展无需更新，立即生效

## 当前选择器配置（2024年12月）

```javascript
// 图片上传
uploadInput: ['input[type="file"]']

// 标题输入
titleInput: [
  'input.d-text[placeholder*="标题"]',
  'input[placeholder*="标题"]',
  'input[maxlength="20"]'
]

// 内容编辑区（ProseMirror）
contentArea: [
  '.tiptap.ProseMirror[role="textbox"]',
  '.ProseMirror[role="textbox"]',
  '[role="textbox"][contenteditable="true"]'
]

// 发布按钮
publishBtn: [
  'button.publishBtn',
  'button:has-text("发布")'  // 自定义伪类
]
```

## 调试技巧

### 在控制台测试选择器

```javascript
// 测试单个选择器
document.querySelector('input.d-text[placeholder*="标题"]')

// 测试所有候选选择器
const selectors = ['选择器1', '选择器2', '选择器3'];
selectors.forEach(s => {
  console.log(s, '=>', document.querySelector(s));
});
```

### 查看扩展当前使用的选择器

```javascript
// 在小红书页面控制台执行
const marker = document.getElementById('prome-extension-marker');
console.log('扩展版本:', marker?.dataset.version);
```

## 选择器失效的常见表现

1. **发布失败** - "Element not found" 错误
2. **内容没填上** - 标题或正文为空
3. **按钮点不动** - 找不到发布按钮

## 紧急修复流程

如果大量用户反馈发布失败：

1. 访问 creator.xiaohongshu.com/publish
2. 打开开发者工具 → Elements
3. 找到对应元素的新选择器
4. 更新后端 `/api/v1/selectors`
5. 所有在线用户自动修复

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 2024.12.01 | 2024-12-01 | 初始版本，适配ProseMirror编辑器 |

## 添加新选择器的建议

当需要支持新功能时：

1. 先找到稳定的 `role` 或 `type` 属性
2. 添加 placeholder 作为备选
3. class 名作为最后手段
4. 始终配置 3-5 个回退选择器
