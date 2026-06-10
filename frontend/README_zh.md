# AI Dzeck × Claw 前端

[English](README.md) | 中文

AI Dzeck × Claw 的前端，使用 Vue 3 + TypeScript + Vite + Tailwind CSS 构建。

## 特性

- 聊天界面与任务会话
- 工具面板（搜索、文件、终端、浏览器）
- VNC 查看器，实时可视化沙盒桌面
- 计划面板，显示 Agent 逐步执行过程
- **Claw 页面** —— 集成 [OpenClaw](https://github.com/anthropics/openclaw) 聊天体验，支持 WebSocket 实时通信、自动过期倒计时、文件上传与下载

## 在 Replit 上运行

前端通过 **Start application** 工作流运行。Vite 开发服务器在端口 5000 启动，并将所有 `/api` 请求代理到 `http://localhost:8000` 的后端。

无需 `.env` 文件 —— 后端 URL 由 Vite 代理配置自动处理。

```bash
# 安装依赖（如有需要）
cd frontend && pnpm install

# 启动开发服务器（端口 5000）
pnpm dev

# 构建生产版本
pnpm build

# 类型检查
pnpm type-check
```

## 项目结构

```
src/
├── assets/          # 静态资源和 CSS 文件
├── components/      # 可复用组件
│   ├── ChatBox.vue          # 聊天输入框（支持文件附件）
│   ├── ChatMessage.vue      # 聊天消息渲染
│   ├── LeftPanel.vue        # 会话列表侧边栏
│   ├── ToolPanel.vue        # 工具调用可视化面板
│   ├── PlanPanel.vue        # Agent 计划步骤面板
│   ├── VNCViewer.vue        # noVNC 沙盒桌面查看器
│   ├── FilePanel.vue        # 文件浏览器面板
│   ├── UserMenu.vue         # 用户账户菜单
│   ├── SessionItem.vue      # 会话列表项
│   ├── filePreviews/        # 文件预览组件（代码、图片、PDF 等）
│   ├── toolViews/           # 工具专用视图组件
│   ├── settings/            # 设置组件
│   └── ui/                  # 基础 UI 组件（基于 reka-ui）
├── pages/           # 页面组件
│   ├── ChatPage.vue         # 主聊天界面
│   ├── HomePage.vue         # 会话列表 / 首页
│   ├── ClawPage.vue         # OpenClaw 助手页面
│   ├── LoginPage.vue        # 登录 / 注册
│   ├── LandingPage.vue      # 公开落地页
│   └── SharePage.vue        # 分享会话视图
├── composables/     # Vue 组合式函数（可复用逻辑）
├── api/             # API 客户端函数
├── types/           # TypeScript 类型定义
├── constants/       # 应用常量
├── locales/         # 国际化翻译（英文 + 中文）
├── lib/             # 工具库
├── utils/           # 辅助工具
├── App.vue          # 根组件
└── main.ts          # 入口文件
```
