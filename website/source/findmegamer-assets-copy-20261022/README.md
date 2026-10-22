# FindMeGamer · 官网素材与文案交付包

日期：2026-10-22。范围：**素材 + 文案 + Agent 安装入口内容**。不含网站原型、页面设计、生产代码或部署。

## 交给实现 Agent

先读 `HANDOFF.md`，再读 `copy/home.zh-CN.md` 和 `copy/home.en.md`。网站排版、交互和 Three.js 效果由你设计实现。

核心分发入口不是下载按钮，而是 **「复制给 Agent / Copy setup prompt」**。复制内容见 `copy/agent-entry.json`；用户把这段短 Prompt 发给自己的 Agent，Agent 读取公开安装 README 后安装 CLI 和 Skills。

## 文件

- `copy/home.en.md`：英文官网模块文案，适合作为默认语言。
- `copy/home.zh-CN.md`：中文对应文案。
- `copy/agent-entry.json`：可直接接入的中英入口文案与复制字符串。
- `copy/prompt.zh-CN.txt` / `copy/prompt.en.txt`：独立纯文本安装 Prompt。
- `assets/illustrations/signal-orbit.png`：原创轨道主视觉，1536 × 1024。
- `assets/illustrations/selective-connections.png`：原创选择性连接辅助插画，1536 × 1024。
- `assets/icons/*.svg`：8 个原创、24 × 24、可换色线性图标。
- `assets/brand/existing-app-icon.png`：从当前项目复制的现有品牌参考图，不是新 Logo 提案。
- `assets/ASSETS.md`：用途、替代文本、来源、使用边界。
- `assets/GENERATION-PROMPTS.md`：图像生成原始 Prompt。
- `QA.md`：交付检查和上线待办。

## 特别注意

1. 当前产品属于需服务授权的 CLI / Agent 工作流，不能写成匿名免费 SaaS 或即时自助注册。
2. 不加入虚构客户、转化率、创作者总量、投递率、评价或收费价格。
3. 本包内图片是装饰性图像，不是实时数据、真实产品截图或 3D 模型。
4. 官网可以发布素材与介绍；**复制安装入口启用前必须先修订并核对公开安装指南**。本次直接读取的在线指南仍写 0.8.1，且有旧邮箱绑定信息。不要把这份过时指南原样作为正式 onboarding 承诺。
5. 这里只交付内容；没有更改后端、发布新版本、恢复发信或实际执行安装 Prompt。
