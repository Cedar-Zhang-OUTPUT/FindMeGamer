# FindMeGamer — 官网

## GitHub Pages 发布版 · 2026-10-22

- 站点：`https://cedar-zhang-output.github.io/FindMeGamer/`；中文：`/FindMeGamer/zh/`。
- 源码分支：`website`；自动发布工作流：`.github/workflows/website-pages.yml`。不修改 `main`、`cli` 或后端部署。
- Prompt 现在指向随网站发布的 `install/README.md`，已更新为 CLI 0.8.4，移除旧游戏邮箱绑定，保留 token 与付费调用边界。
- 分享图、canonical、hreflang、sitemap 已配置 GitHub Pages 项目子路径。
- 发布使用白名单构建，只上传网站运行文件、公开安装指南与许可证；不上传本仓库其他文件、`source/`、`tools/` 或本地验证数据。
- 先 `python3 -m pip install -r website/requirements.txt`（推荐隔离环境），再从仓库根目录执行 `python3 website/tools/build-zh.py`、`python3 website/tools/check.py`、`python3 website/tools/build-pages.py --output /absolute/new/output`。
- 下方为导入项目的设计/维护说明；原发布待办的核验状态以 `DEPLOYMENT.md` 为准。

一个纯静态的双语官网，主入口是「复制给 Agent」的安装提示词，而不是下载按钮。

- 英文：`index.html`（默认）
- 中文：`zh/index.html`
- 两页共享 `css/`、`js/`，各自是完整静态页：无 JavaScript 也能读完所有文案，也可以各自被收录。

---

## 1. 先跑起来

静态站需要一个 HTTP 服务（直接双击 `index.html` 时，ES module 会被浏览器的 file:// 策略拦住，3D 不会启动，其余内容正常）。

```bash
cd findmegamer-website
python3 -m http.server 8765
# 打开 http://127.0.0.1:8765/
```

部署时把整个目录（`source/` 和 `tools/` 可以排除）传到任意静态托管：对象存储、CDN、Vercel、Netlify、GitHub Pages 都可以，不需要构建步骤。

---

## 2. 目录

```
index.html                 英文首页
zh/index.html              中文首页（由 tools/build-zh.py 生成，不要手改）
css/site.css               全部样式
js/main.js                 导航、复制入口、滚动进场、按需加载 3D
js/scene.js                首屏 3D 场景（Three.js，代码建模）
js/field.js                深色区块的实时信号场（Three.js）
assets/img/                图片：首屏静帧、正文插画、社交卡片、图标
assets/fonts/              自托管字体（Instrument Serif / Inter / IBM Plex Mono）
vendor/three.module.min.js Three.js r169（本地，无 CDN 依赖）
favicon.svg  robots.txt
tools/                     构建与自检脚本（不参与线上运行）
source/                    原始交付素材（文案库、插画母版、图标）
```

---

## 3. 设计说明

### 视觉

| 用途 | 取值 |
| --- | --- |
| 纸白背景 | `#F7F3EA` |
| 墨色正文 | `#0B1020` / `#333A50` |
| 钴蓝主色 | `#1533E0` |
| 薄荷强调 | `#BCE0C8` |

取色全部来自原始插画（钴蓝玻璃与薄荷节点）。字体三件套：**Instrument Serif** 做大标题（高对比衬线，编辑感），**Inter** 做正文（中性、易读），**IBM Plex Mono** 做编号与技术标签——页眉的 `01–07`、图注、提示词都用它，让页面读起来像一份研究档案，而不是又一个 AI 落地页。

中文页的大标题单独用 **宋体**（`Songti SC / Source Han Serif`）承接英文衬线的气质；正文仍是苹方/思源黑，保证小字号可读。

### 结构

首屏 → 安装提示词控制台 → 产品定位 → 使用方式（深色） → 产品能力 → 任务示例 → 使用边界 → 常见问题 → 页尾行动 → 页脚。

主转化动作是**复制提示词**：整段 prompt 直接可见、可选中，四个位置（导航、首屏、控制台、页尾）都能复制。

### 首屏 3D

全部由代码生成，没有外部模型或贴图：

- 一个钴蓝釉面圆环 + 环内的奶油色球体（「合适的那一个」），薄荷与钴蓝卫星点沿细轨道环绕。
- 光照用代码搭出的「影棚」：环境贴图由一个带柔光板的 PMREM 场景烘焙而来，再加一盏主光负责投影。
- 交互：拖动可旋转（带惯性）、指针轻微视差、三个光点沿线流动。
- 降级：`prefers-reduced-motion`、省流量模式、无 WebGL 或模块加载失败时，直接用同一场景渲染出的**静帧图**（`assets/img/hero-still-*.webp`），观感一致，不会出现两种风格的跳变。

深色「使用方式」区块另有一层 Three.js 信号场（74 个柔光节点 + 7 条细连接 + 流动光点），专门表达「名单里只有少数会被连上」。

### 关于「生成素材」

首屏静帧、社交卡片、应用图标都是用本项目自己的渲染代码/页面截取生成的，不是外部图片；插画母版仍来自原始素材包（`source/`）。

---

## 4. 改内容

### 改文案

英文改 `index.html`，中文改**生成脚本里的对照表** `tools/build-zh.py` 的 `TEXT` 字典，然后：

```bash
python3 tools/build-zh.py
```

> 直接手改 `zh/index.html` 会在下次生成时被覆盖。

### 改提示词（重点）

提示词是主转化物，必须和中英各自的实际内容严格一致。它只出现一次：`index.html` 里 `#setup-prompt` 的纯文本内容；复制按钮读的就是这段 DOM 文本，所以**显示与复制永远一致**。

- 中文提示词在 `tools/build-zh.py` 的 `PROMPT_ZH`。
- 改完跑 `python3 tools/check.py`，它会逐字符比对 `source/.../copy/agent-entry.json` 里的 `prompt`，不一致会直接报错。

### 改图片

插画母版在 `source/findmegamer-assets-copy-20261022/assets/illustrations/`，改完执行：

```bash
python3 tools/build-images.py
```

首屏静帧是从同一个 3D 场景重新截取的（改了 `js/scene.js` 之后要同步更新，否则降级观感会和实时版本不一致）：

```bash
node tools/shot.mjs --url http://127.0.0.1:8765/tools/hero-still.html \
     --out shots/hero-render.png --width 1400 --height 1050 --wait 3500 --motion
# 再把 PNG 转成 1400 / 700 / 420 三个宽度的 WebP，覆盖 assets/img/hero-still-*.webp
```

`tools/hero-still.html` 只用于出图，不参与线上运行。同理，社交卡片由 `tools/og-card.html` 截取，应用图标由 `tools/icon.html` 截取。

---

## 5. 自检

```bash
python3 tools/check.py
```

覆盖 172 项：提示词与源文件逐字符一致、所有指南链接同源、无 `http://`、外链都带 `rel="noopener"`、图片与锚点无死链、`img` 都有 `alt`、每页只有一个 `h1`、图标按钮有可访问名称、FAQ 结构完整、中文页没有漏译的英文段落、必备文件齐全。

无障碍与降级的手动检查项见 `LAUNCH-CHECKLIST.md`。

---

## 6. 已知的、需要产品方决定的事

1. **安装指南**：网站版本维护 `install/README.md`；升级 CLI 后需再次核验文档及下载。旧 cli 分支的 AGENT-INSTALL.md 本次未改。
2. **域名、canonical、hreflang**：已配置 GitHub Pages 地址。以后迁移域名需同步修改元数据、sitemap、复制 Prompt 与指南链接。
3. **没有的东西都没有编**：无价格、无客户、无转化率、无评价、无隐私政策/条款/联系地址、无「申请试用」入口。这些位置在有真实渠道前保持空缺。
4. **App 图标未使用**：现有图标是紫色 3D 人物，与暖纸+钴蓝的体系冲突，品牌改用自绘轨道标记 + 字标。
5. **平台名只作文本提及**：YouTube / Twitch / X / Steam 未使用商标图形，页脚也未声称官方合作。
