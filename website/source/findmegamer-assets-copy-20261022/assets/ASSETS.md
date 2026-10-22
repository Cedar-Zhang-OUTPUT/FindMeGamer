# 素材目录

## 插画

| 文件 | 格式 / 尺寸 | 用途 | 中文替代文本 | English alt |
| --- | --- | --- | --- | --- |
| illustrations/signal-orbit.png | PNG / 1536 × 1024 / 不透明 | 主视觉、品牌介绍、静态降级 | 钴蓝玻璃轨道与薄荷色节点组成的抽象雕塑 | Abstract cobalt glass orbit with pale mint satellite nodes |
| illustrations/selective-connections.png | PNG / 1536 × 1024 / 不透明 | 匹配能力、工作流辅助视觉 | 蓝色中心节点与部分浅色节点相连的抽象插画 | A blue central tile selectively connected to smaller pale tiles |
| brand/existing-app-icon.png | PNG / 1254 × 1254 / 不透明 | 现有品牌参考，是否使用由接手设计者决定 | FindMeGamer 现有应用图标 | Existing FindMeGamer app icon |

若图片纯装饰且相邻文案已表达完整信息，请使用 `alt=""`，不要机械套用表中描述。请勿把两张图当作真实产品截图或把节点数量作为业务统计。

图像含背景，不能直接当透明贴图；不是无缝纹理、环境 HDR、深度图或 GLB。没有提供 3D 网格。可以用作 Three.js 的视觉参考或静态回退图，真实三维效果另行实现。

两张插画未压缩的 PNG 是母版，交接时保留。实现者可另行导出 WebP/AVIF 和响应式尺寸，不覆盖母版；推荐按实际使用尺寸控制下载体积。这里未生成或验证压缩衍生版。

## 图标

全部 24 × 24 viewBox，stroke-width=1.7，round caps/joins，fill=none，使用 currentColor。通过 inline SVG 或 mask 使用以继承文字色；作为外部 img 时 currentColor 通常不继承页面颜色。

| 文件 | 语义 |
| --- | --- |
| icons/discover.svg | 创作者发现 / 搜索 |
| icons/evidence.svg | 证据与匹配理由 |
| icons/contact.svg | 公开联系方式 |
| icons/outreach.svg | 经审核的外联 |
| icons/agent.svg | CLI / Agent 接入 |
| icons/copy.svg | 复制 Prompt |
| icons/check.svg | 已复制 / 已完成 |
| icons/arrow-up-right.svg | 打开文档 / 外部链接 |

SVG 未嵌字体、脚本、外部 URL 或位图。图标按钮须由实现者提供可访问名称；装饰图标应隐藏于辅助技术，不依赖图标单独解释状态。

## 来源与使用边界

- 两张插画：本次通过内置 imagegen 生成，生成日期 2026-10-22。原始 Prompt 见 `GENERATION-PROMPTS.md`。未使用第三方人物/游戏截图，不代表平台背书。生成内容的商业使用仍需遵守适用服务条款，本包不提供独占版权或商标清查保证。
- SVG：本次用代码原创绘制，没有引入第三方图标库。
- 现有 App 图标：复制自本项目 `macos/Design/FindMeGamer-Logo-Concept.png`，既有资产的授权与品牌归属沿用原项目，本次不重新声明其版权来源。
- 不包含字体文件、第三方平台 Logo、真实创作者头像、实际联系人、访问凭证或客户邮件。
