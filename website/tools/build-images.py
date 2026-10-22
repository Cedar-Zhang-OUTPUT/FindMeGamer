#!/usr/bin/env python3
"""Derive web-ready images from the handed-off master PNGs.

Masters stay untouched in the source pack. Run from the site/ directory:

    python3 tools/build-images.py

Requires Pillow. Outputs WebP (primary) + PNG (fallback) at the widths the
layout actually requests, so no page downloads the 1536 x 1024 master.
"""

from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parents[2] / "assets/findmegamer-assets-copy-20261022/assets/illustrations"
OUT = Path(__file__).resolve().parents[1] / "assets/img"

JOBS = [
    # name, source file, widths
    ("signal-orbit", "signal-orbit.png", [1600, 1000, 640]),
    ("selective-connections", "selective-connections.png", [1400, 800, 560]),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, filename, widths in JOBS:
        master = Image.open(SRC / filename).convert("RGB")
        for width in widths:
            height = round(width * master.height / master.width)
            frame = master.resize((width, height), Image.LANCZOS)
            suffix = "" if width == widths[0] else f"-{width}"
            webp = OUT / f"{name}{suffix}.webp"
            frame.save(webp, "WEBP", quality=82, method=6)
            print(f"{webp.name:38s} {webp.stat().st_size / 1024:7.1f} KB  {width}x{height}")


if __name__ == "__main__":
    main()
