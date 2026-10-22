# 上线检查清单

> 以下保留原始交接清单，未逐项勾选不代表发布状态。2026-10-22 的实际修复、验证和已知限制见 `DEPLOYMENT.md`。网站已改用随站发布的安装 README，不再依赖旧版业务安装指南。

按顺序过一遍。**第 1 项未完成前，不要对外宣传「复制给 Agent」入口**。

## 1. 阻塞项：安装指南

`source/findmegamer-assets-copy-20261022/copy/agent-entry.json` 里 `readyForPublicLaunch` 仍为 `false`，原因是公开安装指南还停留在 CLI 0.8.1，且含过期业务邮箱说明。

处置步骤（需要发布权限与用户授权）：

- [ ] 确认当前 CLI 专用 release，更新指南里的版本与校验步骤（不要用混有 macOS DMG 的通用 latest 逻辑）
- [ ] 从公共 onboarding 里去掉特定客户/游戏的邮箱选择，业务场景改为安装后读取最新 Skills 与服务目录
- [ ] 写明支持系统（当前 Codex on macOS / Linux）、所需 Agent 工具、token 获取流程、权限范围与成本边界
- [ ] 写明「已安装用户如何更新并保留配置」「Skills 如何重载」
- [ ] 下载走 HTTPS 并校验；不引导关闭 TLS 校验、不写入 token
- [ ] 无 token 的用户可以安装，但页面必须说明「已安装，待授权」，不能暗示可直接使用
- [ ] 匿名环境实测：指南可匿名读取、release 可下载、复制字符串与实际一致
- [ ] 修订完成后，把 `agent-entry.json` 的 `readyForPublicLaunch` 改为 `true`，并在 README 记录核验日期

站点侧对应动作：

- [ ] 若指南地址变化，同步更新两个页面里所有 `[data-guide]` 链接与提示词内的 URL（`tools/check.py` 会拦截不一致）
- [ ] 保持「网站不写死 CLI 版本」的现状，不要镜像完整安装脚本

## 2. 域名与索引

- [ ] 确认正式域名，补 `<link rel="canonical">`
- [ ] 补绝对地址的 `hreflang`（`en` / `zh-CN` / `x-default`）
- [ ] `og:url`、`og:image` 改成绝对地址（当前是相对路径，部分抓取器解析不稳定）
- [ ] 需要的话补 `sitemap.xml` 并在 `robots.txt` 里声明

## 3. 内容

- [ ] 通读中英两版，确认术语一致（CLI / Skill / Agent / FMG token）
- [ ] 确认设计补写的连接文案可以接受：`From first match to follow-through.`、`It starts with one clear brief.`、`Questions, answered plainly.`、图注、按钮旁提示
- [ ] 确认没有出现：价格、客户名、转化率/创作者总量/投递率、评价、免费额度
- [ ] 页脚只保留真实存在的链接（安装指南、站内锚点）；隐私政策 / 条款 / 联系方式待有真实页面后再加
- [ ] 确认平台名（YouTube / Twitch / X / Steam）只作文字提及，未使用其图形标识，也未暗示官方合作

## 4. 交互与降级（人工过一遍）

- [ ] 键盘：Tab 走完全站 → 可见焦点环；跳过链接可用；FAQ 可用回车展开
- [ ] 复制入口：成功时按钮转薄荷绿并提示「已复制，粘贴给你的 Agent」；**在拒绝剪贴板权限的浏览器里**能自动选中文本并提示手动复制
- [ ] 复制结果只声明「已复制」，任何地方都不出现「已安装」
- [ ] 断网 / 禁用 JavaScript：文案、FAQ、提示词仍可读可选中
- [ ] 禁用 WebGL：首屏回落到静帧图，不出现空白或错位
- [ ] 系统开启「减少动态效果」：3D 不加载、滚动动画关闭、页面仍完整
- [ ] 移动端：首屏 CTA 不被遮挡；导航菜单可开合、Esc 可关；375 / 390 / 768 三个宽度各看一次
- [ ] 深色区块里的信号场在低端机上不卡顿（可在 Chrome DevTools 里限制 4× CPU 再看一次）

## 5. 性能与可达性

- [ ] Lighthouse（移动端）：Performance / Accessibility / Best Practices / SEO 四项均 ≥ 90
- [ ] 首屏 3D 是懒加载的：`js/scene.js` 与 `vendor/three.module.min.js` 不阻塞首屏文字
- [ ] 字体只有 5 个 woff2（约 100KB），已 `preload` 显示字体
- [ ] 图片全部是 WebP，正文插画 `loading="lazy"`
- [ ] 对照度复查：正文 `#333A50` on `#F7F3EA` ≈ 8.4:1；钴蓝 `#1533E0` on 纸白 ≈ 7.2:1；薄荷只用于装饰与深色底上的文字

## 6. 发布

- [ ] `python3 tools/check.py` 全绿
- [ ] 上传时排除 `source/` 与 `tools/`（或确认允许公开访问）
- [ ] 上线后复查：中英文互切、四条指南链接、复制后粘贴到真实 Agent 里内容正确
- [ ] 任何一处改动后重跑 `tools/build-zh.py` 与 `tools/check.py`
