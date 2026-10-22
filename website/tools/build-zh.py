#!/usr/bin/env python3
"""Generate zh/index.html from index.html.

The Chinese page is a real static page, not a client-side swap: it keeps the
same structure and shared CSS/JS, so both languages work without JavaScript and
each can be indexed on its own. This script rewrites text nodes, metadata,
ARIA labels and relative paths, then asserts that no English copy was missed.

    python3 tools/build-zh.py
"""

import pathlib
import re

from lxml import html as lxml_html

ROOT = pathlib.Path(__file__).resolve().parents[1]

GUIDE = "https://cedar-zhang-output.github.io/FindMeGamer/install/README.md"

TEXT = {
    "Skip to content": "跳到主要内容",
    "How it works": "使用方式",
    "Capabilities": "产品能力",
    "For Agents": "Agent 接入",
    "FAQ": "常见问题",
    "Copy setup prompt": "复制给 Agent",
    "Creator discovery, built for agents": "为 Agent 工作流打造的游戏创作者发现工具",
    "Find the creators who": "为你的游戏，找到真正",
    "get": "同频",
    "your game.": "的创作者。",
    "Bring FindMeGamer into your Agent’s workflow. Research relevant gaming creators, understand the fit, and prepare thoughtful outreach—with you in control of what gets sent.": "让 FindMeGamer 加入你的 Agent 工作流。发现相关游戏创作者、理解匹配理由、准备有针对性的邀约；最终联系谁、发送什么，由你决定。",
    "Read the setup guide": "阅读安装指南",
    "Paste it into your Agent. It reads the guide and helps install the CLI and Skills.": "粘贴给你的 Agent，让它阅读指南并协助安装 CLI 和 Skill。",
    "An FMG access token is required. Setup does not start research or send email.": "需要 FMG 访问令牌。安装不会自动开始研究或发信。",
    "Fig. 01 — selective orbit": "图 01 — 选择性轨道",
    "· drag to turn": "· 拖动可旋转",
    "Agent setup prompt": "Agent 安装提示词",
    "Select all": "全选",
    "Works with an Agent that has terminal and file access. An FMG token is required.": "适用于具备终端和文件访问能力的 Agent。需要 FMG 访问令牌。",
    "The current guide targets Codex with terminal and file tools on macOS / Linux. Check compatibility for other Agent hosts.": "当前指南面向 macOS / Linux 上具备终端和文件工具的 Codex；其他 Agent 需核对兼容性。",
    "The problem": "问题",
    "A long list isn’t the same as a good match.": "名单很长，不代表真正合适。",
    "A creator’s audience size tells only part of the story. Start with the games they cover, the way they play, and the context behind the match. Build a shortlist you can explain—not just a spreadsheet you can export.": "粉丝量只是故事的一部分。先看创作者关注哪些游戏、如何呈现内容，以及他为什么可能适合你的作品。建立一份讲得清理由的候选名单，而不只是多一张表格。",
    "The games they cover": "关注哪些游戏",
    "The way they play": "如何呈现内容",
    "The context behind the match": "匹配背后的语境",
    "Illustrative — a match is a connection, not a row.": "示意 — 匹配是一次连接，不是一行记录。",
    "Give your Agent a new capability.": "给你的 Agent，多一项能力。",
    "No dashboard detour required to get started. Copy a short prompt, let your Agent read the setup guide, and install FindMeGamer where you already work.": "无需为了开始使用而切换到新的操作后台。复制一段短 Prompt，让 Agent 读取安装指南，把 FindMeGamer 接入你熟悉的工作流。",
    "Copy the prompt.": "复制 Prompt。",
    "Send it to an Agent with terminal and file access.": "发给具备终端和文件访问能力的 Agent。",
    "Let it handle setup.": "让 Agent 完成安装。",
    "Your Agent follows the guide to install the CLI and Skills, respecting your environment’s permissions.": "按指南安装 CLI 和 Skill，并遵守当前环境的权限要求。",
    "Authorize, then brief it.": "完成授权，再提出任务。",
    "Connect your FMG access token privately. Choose a game, platforms, and a research scope before starting.": "私下配置 FMG 访问令牌；确认游戏、平台和研究范围后再开始。",
    "From first match to follow-through.": "从第一次匹配，到后续跟进。",
    "Start with the game": "从游戏本身出发",
    "Bring a Steam game or a clear game brief. Give the research a direction: genre, mechanics, tone, and the kind of coverage you’re looking for.": "提供 Steam 游戏链接或明确的游戏介绍，用题材、玩法、氛围和期望的内容形式，为研究设定方向。",
    "Find relevant creators": "发现相关创作者",
    "Research gaming creators across YouTube, Twitch, and X. Focus on relevant content and explainable matches, not audience size alone.": "研究 YouTube、Twitch 和 X 上的游戏创作者。关注相关内容和可解释的匹配，而不只看粉丝规模。",
    "Understand the fit": "看懂为什么匹配",
    "Keep matching reasons alongside the evidence available for review. Let your team decide which creators belong on the shortlist.": "把匹配理由与可供核对的证据放在一起。由团队判断，谁值得进入最终名单。",
    "Look for public contact details": "补充公开商务联系方式",
    "Enrich a shortlist with available public business contact details. Keep uncertainty visible when information cannot be found or independently verified.": "为候选名单查找可获得的公开商务邮箱。找不到或无法独立核验时，保留真实的不确定性。",
    "Prepare outreach with intent": "准备有针对性的邀约",
    "Choose the sending mailbox and template, review the message, and approve the recipients before sending. Installation is never permission to contact someone.": "明确发件邮箱和模板，审核正文与收件人，再确认发送。安装工具不等于授权联系任何人。",
    "Keep track of delivery": "跟进发送情况",
    "Inspect task progress, delivery issues, and mailbox monitoring through the workflow. A message accepted by a mail server is not a guarantee of inbox placement or a reply.": "通过工作流查询任务进度、投递异常和邮箱监控情况。邮件服务器接受发送，不代表一定进入收件箱或获得回复。",
    "Example brief": "任务示例",
    "It starts with one clear brief.": "从一段清楚的 brief 开始。",
    "After setup and authorization, research begins with the game and the scope you agree on. A brief can be this short.": "安装并授权之后，研究从游戏和你们确认的范围开始。一段 brief 可以就这么短。",
    "Example prompt": "任务示例",
    "Find 10 YouTube creators for this Steam game: [Steam URL]. Focus on creators who cover narrative indie games. Show the matching reasons and available evidence. Don’t enrich email addresses or send messages yet.": "为这款 Steam 游戏找 10 位适合的 YouTube 创作者：[Steam 链接]。优先寻找关注叙事类独立游戏的频道，列出匹配理由和可用证据。先不要补充邮箱，也不要发信。",
    "Example prompt. Research may use service quota; agree on the scope before running it.": "此为任务示例。实际研究可能消耗服务额度，执行前先确认范围。",
    "Control and boundaries": "使用边界",
    "Your Agent does the legwork. You make the call.": "Agent 做研究，决定权在你。",
    "Review before outreach.": "发信前审核。",
    "Approve recipients and message content before sending.": "收件人和正文确认后，才进入发送流程。",
    "Keep secrets off the page.": "凭证不进网页。",
    "Authenticate privately; never paste access tokens into the website.": "通过私密方式授权，不在官网粘贴访问令牌。",
    "See the limits.": "结果如实呈现。",
    "Missing contact details, uncertain results, and provider errors should stay visible—not become invented successes.": "联系方式缺失、结果未核验、上游服务错误，都不应被包装成「成功」。",
    "Questions, answered plainly.": "把问题讲清楚。",
    "If you are missing a token or permissions, contact your FMG administrator.": "如果你缺少令牌或权限，请联系你的 FMG 管理员。",
    "Is this a download or a web app?": "这是下载安装，还是网页应用？",
    "The primary entry point is a prompt for your Agent. It follows the setup guide to install the FindMeGamer CLI and companion Skills. The website introduces the product; it is not the research workspace.": "主要入口是一段发给 Agent 的 Prompt。Agent 读取指南后安装 FindMeGamer CLI 和配套 Skill。官网负责介绍和分发，不是执行研究任务的工作台。",
    "Can I use it immediately after installation?": "安装完就可以直接使用吗？",
    "You need an FMG access token and the appropriate permissions. If you do not have one, contact your FMG administrator. Installation alone does not grant service access.": "还需要 FMG 访问令牌及相应权限。没有令牌时，请联系你的 FMG 管理员；安装本身不会自动获得服务访问权。",
    "Which platforms can I research?": "支持哪些平台？",
    "The current workflow includes YouTube, Twitch, and X creator research, with Steam for game context. Available operations depend on your service permissions and provider availability. Platform names do not imply endorsement or partnership.": "当前工作流包含 YouTube、Twitch、X 创作者研究，以及 Steam 游戏背景信息。实际可用能力受服务权限和上游可用性影响；提及平台不代表官方合作或背书。",
    "Will it find an email for every creator?": "每位创作者都能找到邮箱吗？",
    "No. Public business contact enrichment is best-effort. No result may be a valid outcome, and a discovered address is not a guarantee of identity, deliverability, or permission to contact its owner.": "不能保证。公开商务联系方式补强是尽力查询，正常找不到也是合理结果。找到地址不代表已经验证身份、保证可投递，或获得联系许可。",
    "Will my Agent send emails automatically?": "Agent 会自动发信吗？",
    "Not as part of setup. Outreach requires a separate, approved workflow with the selected mailbox, recipients, and message content.": "安装过程不会发信。外联需要另行确认发件邮箱、收件人和邮件正文，并授权执行发送流程。",
    "Does a successful send mean the message reached the inbox?": "「发送成功」意味着进入收件箱了吗？",
    "No. Server acceptance, delivery, inbox placement, and a reply are different outcomes. FindMeGamer does not guarantee coverage or replies.": "不意味着。服务器接受、实际投递、进入收件箱、收到回复是不同结果。FindMeGamer 不保证回复或内容报道。",
    "Are all Agent hosts and operating systems supported?": "所有 Agent 和操作系统都能用吗？",
    "The current guide targets Codex with terminal/file tools on macOS or Linux. Compatibility with other hosts must be checked. Do not assume native Windows support or universal Agent integration.": "当前指南面向具备终端和文件工具的 Codex，支持 macOS 和 Linux。其他环境需核对兼容性，不应宣传为全平台即装即用。",
    "Is research free?": "研究任务免费吗？",
    "Installation does not authorize paid work. Research and enrichment may consume service or provider quota. Confirm access and usage terms with your administrator before starting; no public pricing is specified here.": "安装不授权付费调用。研究和邮箱补强可能消耗服务或上游额度，使用前请向管理员确认。当前不在官网文案中承诺价格或免费额度。",
    "Get started": "开始使用",
    "Start with your game. Find your people.": "从你的游戏出发，找到值得交流的人。",
    "Add FindMeGamer to your Agent’s workflow and build your next creator shortlist with a clearer reason for every match.": "把 FindMeGamer 接入 Agent 工作流，让下一份创作者名单，拥有更清楚的匹配理由。",
    "Creator research and thoughtful outreach for game teams.": "为游戏团队提供创作者研究与有针对性的外联工具。",
    "Setup prompt": "安装提示词",
    "Installation guide": "安装指南",
}

ATTRS = {
    "FindMeGamer, home": "FindMeGamer，返回首页",
    "FindMeGamer, back to top": "FindMeGamer，返回顶部",
    "Primary": "主导航",
    "Language": "语言",
    "Footer": "页脚",
    "Open menu": "打开菜单",
    "Close menu": "关闭菜单",
    "Agent setup prompt": "Agent 安装提示词",
}

PROMPT_ZH = (
    "请阅读 ",
    GUIDE,
    " ，按指南安装 FindMeGamer CLI 和配套 Skills；缺少授权时问我，不要执行付费检索或发送邮件。",
)

UI = {
    "data-ui-copy": "复制给 Agent",
    "data-ui-copied": "已复制",
    "data-ui-copied-long": "已复制，粘贴给你的 Agent。",
    "data-ui-copy-error": "未能自动复制，请选中上方 Prompt 手动复制。",
    "data-ui-selected": "已选中 Prompt，请按 Command + C 或 Ctrl + C 复制。",
    "data-ui-copy-error-short": "复制失败",
    "data-ui-status-default": "适用于具备终端和文件访问能力的 Agent。需要 FMG 访问令牌。",
}

META = {
    "title": "FindMeGamer｜为游戏团队找到同频创作者",
    "description": "让 Agent 帮你研究游戏创作者、理解匹配理由、查找公开商务联系方式，并准备由你审核确认的外联邮件。",
    "og_title": "为你的游戏，找到真正同频的创作者。",
    "og_description": "把创作者研究，接入你的 Agent 工作流。",
}


def normalise(value):
    return re.sub(r"\s+", " ", value).strip()


def main() -> None:
    source = (ROOT / "index.html").read_text()
    document = lxml_html.document_fromstring(source)

    document.set("lang", "zh-CN")

    # ---- text nodes -------------------------------------------------------
    replaced = set()
    for element in document.iter():
        if element.tag in ("script", "style"):
            continue
        if element.text and element.text.strip():
            key = normalise(element.text)
            if key in TEXT:
                leading = element.text[: len(element.text) - len(element.text.lstrip())]
                trailing = element.text[len(element.text.rstrip()) :]
                element.text = leading + TEXT[key] + trailing
                replaced.add(key)
        if element.tail and element.tail.strip():
            key = normalise(element.tail)
            if key in TEXT:
                leading = element.tail[: len(element.tail) - len(element.tail.lstrip())]
                trailing = element.tail[len(element.tail.rstrip()) :]
                element.tail = leading + TEXT[key] + trailing
                replaced.add(key)

    missing = set(TEXT) - replaced
    if missing:
        raise SystemExit("Untranslated strings:\n  " + "\n  ".join(sorted(missing)))

    # ---- hero headline: keep "真正同频" from splitting across lines ------
    title = document.xpath("//h1[contains(@class, 'hero__title')]")[0]
    for child in list(title):
        title.remove(child)
    title.text = "为你的游戏，找到"
    wrapper = lxml_html.fragment_fromstring('<span class="nb">真正<em>同频</em></span>')
    wrapper.tail = None
    title.append(wrapper)
    tail = lxml_html.fragment_fromstring("<span>的创作者。</span>")
    title.append(tail)

    # ---- the setup prompt, kept character-exact --------------------------
    prompt = document.get_element_by_id("setup-prompt")
    spans = list(prompt)
    if len(spans) != 3:
        raise SystemExit(f"Unexpected prompt markup: {len(spans)} spans")
    spans[0].text = PROMPT_ZH[0]
    spans[1].text = PROMPT_ZH[1]
    spans[2].text = PROMPT_ZH[2]

    # ---- attributes -------------------------------------------------------
    for element in document.iter():
        for name in ("aria-label", "alt", "title", "content"):
            value = element.get(name)
            if value and normalise(value) in ATTRS:
                element.set(name, ATTRS[normalise(value)])

    # ---- document metadata ------------------------------------------------
    head = document.xpath("//head")[0]
    for preload in head.xpath('./link[@rel="preload"][@as="font"]'):
        head.remove(preload)  # Chinese headings use the system Songti stack.
    for element in head:
        if element.tag == "link" and element.get("rel") == "canonical":
            element.set("href", "https://cedar-zhang-output.github.io/FindMeGamer/zh/")
        if element.tag == "meta" and element.get("property") == "og:url":
            element.set("content", "https://cedar-zhang-output.github.io/FindMeGamer/zh/")
        if element.tag == "title":
            element.text = META["title"]
        if element.tag == "meta" and element.get("name") == "description":
            element.set("content", META["description"])
        if element.tag == "meta" and element.get("property") == "og:title":
            element.set("content", META["og_title"])
        if element.tag == "meta" and element.get("property") == "og:description":
            element.set("content", META["og_description"])
        if element.tag == "meta" and element.get("name") == "twitter:title":
            element.set("content", META["og_title"])
        if element.tag == "meta" and element.get("name") == "twitter:description":
            element.set("content", META["og_description"])

    body = document.xpath("//body")[0]
    for attribute, value in UI.items():
        body.set(attribute, value)

    # ---- relative paths ---------------------------------------------------
    serialised = lxml_html.tostring(document, encoding="unicode", method="html")
    # lxml lowercases SVG attribute names; viewBox is case-sensitive.
    serialised = serialised.replace("viewbox=", "viewBox=")
    serialised = serialised.replace('href="css/', 'href="../css/')
    serialised = serialised.replace('src="js/', 'src="../js/')
    serialised = serialised.replace('href="js/', 'href="../js/')
    serialised = serialised.replace('"assets/img/', '"../assets/img/')
    serialised = serialised.replace(', assets/img/', ', ../assets/img/')
    serialised = serialised.replace('"assets/fonts/', '"../assets/fonts/')
    serialised = serialised.replace('href="favicon.svg"', 'href="../favicon.svg"')
    serialised = serialised.replace('href="./" hreflang="en"', 'href="../" hreflang="en"')
    serialised = serialised.replace('href="zh/" hreflang="zh-CN"', 'href="./" hreflang="zh-CN"')
    serialised = serialised.replace(
        '<a href="../" hreflang="en" aria-current="true">EN</a>',
        '<a href="../" hreflang="en">EN</a>',
    )
    serialised = serialised.replace(
        '<a href="./" hreflang="zh-CN" lang="zh-CN">中文</a>',
        '<a href="./" hreflang="zh-CN" lang="zh-CN" aria-current="true">中文</a>',
    )

    output = "<!doctype html>\n" + serialised
    target = ROOT / "zh" / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output)
    print(f"wrote {target.relative_to(ROOT)} ({len(output)} bytes)")


if __name__ == "__main__":
    main()
