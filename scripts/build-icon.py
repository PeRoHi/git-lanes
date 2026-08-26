"""Build web/icon.png and web/favicon.ico. Requires Pillow (dev only)."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else WEB / "icon-source.jpg"
    if not src.is_file():
        print("source image not found:", src, file=sys.stderr)
        return 1
    im = Image.open(src).convert("RGBA")
    png = im.resize((256, 256), Image.Resampling.LANCZOS)
    png.save(WEB / "icon.png", format="PNG", optimize=True)
    png.save(
        WEB / "favicon.ico",
        format="ICO",
        sizes=[(n, n) for n in SIZES],
    )
    print("wrote", WEB / "icon.png", "and", WEB / "favicon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
