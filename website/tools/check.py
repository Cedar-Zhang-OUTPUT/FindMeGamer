#!/usr/bin/env python3
"""Pre-launch checks for the FindMeGamer site.

Run from the package root:

    python3 tools/check.py

Verifies the things that break quietly: the copied prompt drifting from the
source of truth, a guide link pointing somewhere else, a missing image, a dead
in-page anchor, an unlabelled link, or unstyled English leaking into the
Chinese page.
"""

import json
import pathlib
import re
import sys
from urllib.parse import urlparse

from lxml import html as lxml_html

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "findmegamer-assets-copy-20261022" / "copy" / "agent-entry.json"
PAGES = {"en": ROOT / "index.html", "zh-CN": ROOT / "zh" / "index.html"}

problems = []
checked = 0


def fail(message):
    problems.append(message)


def check(condition, message):
    global checked
    checked += 1
    if not condition:
        fail(message)


ALLOWED_LATIN = re.compile(
    r"^(?:https?://\S+"
    r"|©\s*\d{4}\s+FindMeGamer"
    r"|(?:FindMeGamer|FMG|Agent|CLI|Skill|Skills|Prompt|Steam|YouTube|Twitch|Codex|macOS|Linux|EN|X)"
    r"(?:[\s·/|,.-]*(?:FindMeGamer|FMG|Agent|CLI|Skill|Skills|Prompt|Steam|YouTube|Twitch|Codex|macOS|Linux|EN|X))*)$"
)


def main() -> int:
    entry = json.loads(SOURCE.read_text())
    guide = entry["guideUrl"]

    for locale, path in PAGES.items():
        label = path.relative_to(ROOT).as_posix()
        check(path.exists(), f"{label}: page is missing")
        if not path.exists():
            continue

        document = lxml_html.document_fromstring(path.read_text())
        root = document.getroottree().getroot()
        check(
            root.get("lang") == locale,
            f"{label}: html lang is {root.get('lang')!r}, expected {locale!r}",
        )

        # ---- the setup prompt must be character-identical to the source ---
        prompt = document.get_element_by_id("setup-prompt")
        check(prompt is not None, f"{label}: #setup-prompt missing")
        if prompt is not None:
            rendered = "".join(prompt.itertext())
            expected = entry["locales"][locale]["prompt"]
            check(
                rendered == expected,
                f"{label}: prompt text differs from agent-entry.json\n"
                f"      rendered: {rendered!r}\n"
                f"      expected: {expected!r}",
            )
            check(
                "```" not in rendered and "$ " not in rendered,
                f"{label}: prompt looks like it contains markdown or a shell command",
            )

        # ---- every guide link points at the same, secure destination ------
        for index, link in enumerate(document.xpath("//a[@data-guide]")):
            check(
                link.get("href") == guide,
                f"{label}: guide link #{index + 1} points at {link.get('href')!r}",
            )
            check(
                link.get("rel") == "noopener noreferrer",
                f"{label}: guide link #{index + 1} needs rel=noopener noreferrer",
            )
        check(
            len(document.xpath("//a[@data-guide]")) >= 3,
            f"{label}: expected at least 3 guide links",
        )

        # ---- the page must offer the copy entry in several places ---------
        buttons = document.xpath("//button[@data-copy-prompt]")
        check(len(buttons) >= 3, f"{label}: only {len(buttons)} copy buttons")
        for index, button in enumerate(buttons):
            check(
                (button.get("type") or "") == "button",
                f"{label}: copy button #{index + 1} needs type=button",
            )
            check(
                bool(button.xpath(".//*[@data-copy-label]")),
                f"{label}: copy button #{index + 1} has no label hook",
            )

        # ---- external links are safe --------------------------------------
        for link in document.xpath("//a[@target='_blank']"):
            rel = link.get("rel") or ""
            check("noopener" in rel, f"{label}: {link.get('href')} missing noopener")
            check(
                (link.get("href") or "").startswith("https://"),
                f"{label}: {link.get('href')} is not https",
            )
        insecure = [
            anchor.get("href")
            for anchor in document.xpath("//a[starts-with(@href, 'http://')]")
        ]
        check(not insecure, f"{label}: insecure links {insecure}")

        # ---- no placeholder or fabricated proof ---------------------------
        text = " ".join(document.xpath("//body//text()")).lower()
        for word in ("lorem", "ipsum", "example.com", "placeholder", "coming soon"):
            check(word not in text, f"{label}: placeholder text found: {word!r}")
        for claim in ("1,000", "10,000", "customers", "trusted by"):
            check(claim not in text, f"{label}: unverified claim found: {claim!r}")

        # ---- in-page anchors resolve --------------------------------------
        ids = set(document.xpath("//@id"))
        for anchor in document.xpath("//a[starts-with(@href, '#')]"):
            target = (anchor.get("href") or "")[1:]
            if target:
                check(target in ids, f"{label}: anchor #{target} has no target")

        # ---- local files referenced by the page exist ---------------------
        for element in document.xpath("//img"):
            check(
                element.get("alt") is not None,
                f"{label}: <img> without alt: {element.get('src')}",
            )
            sources = [element.get("src") or ""]
            for candidate in (element.get("srcset") or "").split(","):
                candidate = candidate.strip().split(" ")[0]
                if candidate:
                    sources.append(candidate)
            for source in sources:
                if source.startswith(("http://", "https://", "data:")):
                    continue
                check(
                    (path.parent / source).exists(),
                    f"{label}: missing image file {source}",
                )

        for link in document.xpath("//link[@href]"):
            href = link.get("href")
            if not href or href.startswith(("http", "data:")):
                continue
            check(
                (path.parent / href).exists(),
                f"{label}: missing linked file {href}",
            )

        base = "https://cedar-zhang-output.github.io/FindMeGamer/"
        expected_url = base + ("zh/" if locale == "zh-CN" else "")
        check(document.xpath('//link[@rel="canonical"]/@href') == [expected_url], f"{label}: incorrect canonical")
        check(document.xpath('//meta[@property="og:url"]/@content') == [expected_url], f"{label}: incorrect og:url")
        for tag in ("og:image", "twitter:image"):
            values = document.xpath(f'//meta[@property="{tag}" or @name="{tag}"]/@content')
            check(values == [base + "assets/img/og-image.png"], f"{label}: invalid social image URL")
        alternates = {e.get("hreflang"): e.get("href") for e in document.xpath('//link[@rel="alternate"]')}
        check(alternates == {"en": base, "zh-CN": base + "zh/", "x-default": base}, f"{label}: incomplete language alternates")
        for script in document.xpath('//script[@src]'):
            check((path.parent / script.get("src")).is_file(), f"{label}: missing script")
        for element in document.xpath('//*[@src or @href]'):
            for name in ("src", "href"):
                ref = element.get(name, "")
                check(not ref.startswith("/"), f"{label}: root-absolute resource breaks project subpath: {ref}")

        # ---- accessibility basics -----------------------------------------
        check(
            len(document.xpath("//h1")) == 1,
            f"{label}: expected exactly one h1, found {len(document.xpath('//h1'))}",
        )
        check(
            bool(document.xpath("//a[@href='#main'][contains(@class, 'skip-link')]")),
            f"{label}: skip link missing",
        )
        for button in document.xpath("//button[not(normalize-space(.))]"):
            check(
                bool(button.get("aria-label")),
                f"{label}: icon-only button without aria-label: {button.get('class')}",
            )
        for details in document.xpath("//details"):
            check(
                bool(details.xpath("./summary")),
                f"{label}: <details> without <summary>",
            )

        # ---- language hygiene ---------------------------------------------
        if locale == "zh-CN":
            in_prompt = set(document.get_element_by_id("setup-prompt").iter())
            for element in document.xpath("//body//*[not(self::script) and not(self::style)]"):
                if element in in_prompt:
                    continue
                text = (element.text or "").strip()
                if not text or len(text) < 12:
                    continue
                if re.search(r"[\u4e00-\u9fff]", text):
                    continue
                if ALLOWED_LATIN.match(text):
                    continue
                check(False, f"{label}: untranslated English block: {text[:60]!r}")

    # ---- the required technical files are present -------------------------
    for relative in (
        "install/README.md",
        "licenses/three-MIT.txt",
        "licenses/inter-OFL.txt",
        "licenses/instrument-serif-OFL.txt",
        "licenses/ibm-plex-mono-OFL.txt",
        "sitemap.xml",
        "404.html",
        "robots.txt",
        "favicon.svg",
        "assets/img/og-image.png",
        "assets/img/apple-touch-icon.png",
        "vendor/three.module.min.js",
        "js/main.js",
        "js/field.js",
        "css/site.css",
    ):
        check((ROOT / relative).exists(), f"missing required file: {relative}")

    check(entry["guideUrl"] == "https://cedar-zhang-output.github.io/FindMeGamer/install/README.md", "guide is outside the deployed site")
    guide_text = (ROOT / "install/README.md").read_text()
    check("fmg-v0.8.4" in guide_text and "fmg-v0.8.1" not in guide_text, "guide release outdated")
    check("hotmail" not in guide_text.lower() and "thieves-outreach" not in guide_text, "guide embeds a business mailbox/template")
    for locale in PAGES:
        text = (SOURCE.parent / f"prompt.{locale}.txt").read_text().strip()
        check(text == entry["locales"][locale]["prompt"], f"{locale}: standalone prompt drift")

    # ---- report -----------------------------------------------------------
    if problems:
        print(f"FAIL · {len(problems)} problem(s) of {checked} checks\n")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"OK · {checked} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
