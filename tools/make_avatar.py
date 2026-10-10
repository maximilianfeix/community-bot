"""Draw the bot's avatar, which also serves as the server icon. The result is committed.

    python tools/make_avatar.py <folder with Geist-SemiBold.ttf>

Discord shows avatars and server icons in a circle or a rounded square, so everything that matters sits
inside the middle 70 percent.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT = Path(__file__).resolve().parent.parent / "communitybot" / "assets" / "avatar.png"
SIZE, SCALE = 512, 2  # drawn at double size and shrunk, for smooth edges

SURFACE = "#121113"
ACCENT = "#D4F77A"


def main(font_dir: Path) -> None:
    full = SIZE * SCALE
    image = Image.new("RGB", (full, full), SURFACE)
    draw = ImageDraw.Draw(image)

    tile = round(full * 0.60)
    left = (full - tile) // 2
    draw.rounded_rectangle((left, left, left + tile, left + tile), radius=round(tile * 0.24), fill=ACCENT)

    font = ImageFont.truetype(str(font_dir / "Geist-SemiBold.ttf"), round(tile * 0.50))
    # Centre the letters by their real outline, not by the font's line box.
    box = draw.textbbox((0, 0), "mf", font=font)
    x = (full - (box[2] - box[0])) / 2 - box[0]
    y = (full - (box[3] - box[1])) / 2 - box[1]
    draw.text((x, y), "mf", font=font, fill=SURFACE)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.resize((SIZE, SIZE), Image.Resampling.LANCZOS).save(OUTPUT, optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
