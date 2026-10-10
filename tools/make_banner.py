"""Draw the welcome banner. The result is committed; run this only to change it.

    python tools/make_banner.py <folder with Geist-SemiBold.ttf and GeistMono-Regular.ttf>

The Geist fonts are licensed under the SIL Open Font License and are not part of this repository.
Needs Pillow, which is a development dependency only: the bot itself never draws images.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from communitybot.projects import PROJECTS

OUTPUT = Path(__file__).resolve().parent.parent / "communitybot" / "assets" / "banner.png"
WIDTH, HEIGHT, SCALE = 1200, 400, 2  # drawn at double size and shrunk, for smooth edges

SURFACE = "#121113"
ACCENT = "#D4F77A"
TEXT = "#F4F2F5"
MUTED = "#8E8A93"
LINE = "#2A282C"


def main(font_dir: Path) -> None:
    def font(name: str, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(font_dir / name), size * SCALE)

    def px(value: float) -> int:
        return round(value * SCALE)

    image = Image.new("RGB", (px(WIDTH), px(HEIGHT)), SURFACE)
    draw = ImageDraw.Draw(image)
    left = 72

    draw.rounded_rectangle((px(left), px(74), px(left + 14), px(88)), radius=px(4), fill=ACCENT)
    draw.text(
        (px(left + 28), px(81)), "maximilianfeix", font=font("GeistMono-Regular.ttf", 22), fill=MUTED, anchor="lm"
    )
    draw.text((px(left - 3), px(118)), "open source", font=font("Geist-SemiBold.ttf", 92), fill=TEXT)
    draw.text(
        (px(left), px(236)),
        "Small developer tools that do one job and show their work.",
        font=font("Geist-Regular.ttf", 27),
        fill=MUTED,
    )

    draw.line((px(left), px(304), px(WIDTH - left), px(304)), fill=LINE, width=px(1))
    mono = font("GeistMono-Regular.ttf", 20)
    x = float(left)
    for project in PROJECTS:
        draw.ellipse((px(x), px(335), px(x + 9), px(344)), fill=ACCENT)
        draw.text((px(x + 18), px(340)), project.name, font=mono, fill=TEXT, anchor="lm")
        x += 18 + draw.textlength(project.name, font=mono) / SCALE + 34
    assert x - 34 <= WIDTH - left, f"project row is too wide: {x}"

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS).save(OUTPUT, optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
