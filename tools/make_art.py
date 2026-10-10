"""Draw every picture the bot posts. The results are committed; run this only to change them.

    python tools/make_art.py <folder with Geist-SemiBold.ttf, Geist-Regular.ttf and GeistMono-Regular.ttf>

The Geist fonts are licensed under the SIL Open Font License and are not part of this repository.
Needs Pillow, which is a development dependency only: the bot itself never draws images.

One look for everything: a near-black surface, soft light in the colour of whatever the picture is about,
a faint dot grid, large type. Each project has its own colour and its own sign.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from communitybot.projects import PROJECTS, Project

ASSETS = Path(__file__).resolve().parent.parent / "communitybot" / "assets"
SCALE = 2  # drawn at double size and shrunk, for smooth edges

SURFACE = (18, 17, 19)
TEXT = (244, 242, 245)
MUTED = (158, 154, 164)
ACCENT = (212, 247, 122)

Colour = tuple[int, int, int]
Light = tuple[float, float, float, Colour, float]
"""One soft light: centre x and y and radius as shares of the width, colour, strength from 0 to 1."""


def rgb(value: int) -> Colour:
    return (value >> 16 & 255, value >> 8 & 255, value & 255)


class Canvas:
    def __init__(self, width: int, height: int, font_dir: Path) -> None:
        self.width, self.height, self.font_dir = width, height, font_dir
        self.image = Image.new("RGB", (width * SCALE, height * SCALE), SURFACE)
        self.draw = ImageDraw.Draw(self.image)

    def px(self, value: float) -> int:
        return round(value * SCALE)

    def font(self, name: str, size: float) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.font_dir / name), self.px(size))

    def lights(self, lights: Sequence[Light]) -> None:
        """Soft coloured light on the surface, then a dot grid that only shows where the light falls."""
        glow = Image.new("RGB", self.image.size, (0, 0, 0))
        painter = ImageDraw.Draw(glow)
        for x, y, radius, colour, strength in lights:
            cx, cy, r = self.px(x * self.width), self.px(y * self.width), self.px(radius * self.width)
            shade = tuple(round(part * strength) for part in colour)
            painter.ellipse((cx - r, cy - r, cx + r, cy + r), fill=shade)
        glow = glow.filter(ImageFilter.GaussianBlur(self.px(self.width * 0.085)))
        self.image = ImageChops.screen(self.image, glow)

        dots = Image.new("RGB", self.image.size, (0, 0, 0))
        painter = ImageDraw.Draw(dots)
        step, size = self.px(24), self.px(1.6)
        for gx in range(step // 2, self.image.width, step):
            for gy in range(step // 2, self.image.height, step):
                painter.ellipse((gx, gy, gx + size, gy + size), fill=(255, 255, 255))
        mask = glow.convert("L").point(lambda level: min(255, round(level * 0.55)))
        self.image = Image.composite(ImageChops.screen(self.image, dots), self.image, mask)
        self.draw = ImageDraw.Draw(self.image)

    def text(
        self, x: float, y: float, text: str, font: ImageFont.FreeTypeFont, fill: Colour, anchor: str = "la"
    ) -> None:
        self.draw.text((self.px(x), self.px(y)), text, font=font, fill=fill, anchor=anchor)

    def length(self, text: str, font: ImageFont.FreeTypeFont) -> float:
        return self.draw.textlength(text, font=font) / SCALE

    def tile(self, x: float, y: float, size: float, project: Project) -> None:
        """The project's sign on a tile of its colour."""
        box = (self.px(x), self.px(y), self.px(x + size), self.px(y + size))
        self.draw.rounded_rectangle(box, radius=self.px(size * 0.24), fill=rgb(project.colour))
        SIGNS[project.slug](self.draw, self.px(x), self.px(y), self.px(size))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.resize((self.width, self.height), Image.Resampling.LANCZOS).save(path, optimize=True)
        print(path.relative_to(ASSETS.parent.parent))


# ---------------------------------------------------------------- the five signs
# Each draws in SURFACE on a tile whose top-left corner is (x, y) and whose side is s.


def _stroke(s: int) -> int:
    return max(2, round(s * 0.085))


def sign_proxy(draw: ImageDraw.ImageDraw, x: int, y: int, s: int) -> None:
    """Two arrows passing each other: traffic going through."""
    w = _stroke(s)
    for row, direction in ((0.38, 1), (0.62, -1)):
        cy = y + s * row
        x0, x1 = x + s * 0.27, x + s * 0.73
        tip, tail = (x1, x0) if direction == 1 else (x0, x1)
        draw.line((tail, cy, tip, cy), fill=SURFACE, width=w)
        head = s * 0.13 * direction
        draw.line(
            (tip - head, cy - abs(head), tip, cy, tip - head, cy + abs(head)),
            fill=SURFACE,
            width=w,
            joint="curve",
        )


def sign_dejabuilt(draw: ImageDraw.ImageDraw, x: int, y: int, s: int) -> None:
    """A magnifying glass: look before you build."""
    w = _stroke(s)
    cx, cy, r = x + s * 0.45, y + s * 0.45, s * 0.19
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=SURFACE, width=w)
    draw.line((cx + r * 0.75, cy + r * 0.75, x + s * 0.74, y + s * 0.74), fill=SURFACE, width=round(w * 1.25))


def sign_spillage(draw: ImageDraw.ImageDraw, x: int, y: int, s: int) -> None:
    """A drop: the thing that must not leak."""
    cx, cy, r = x + s * 0.5, y + s * 0.58, s * 0.19
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=SURFACE)
    draw.polygon(
        ((cx, y + s * 0.2), (cx - r * 0.93, cy - r * 0.36), (cx + r * 0.93, cy - r * 0.36)), fill=SURFACE
    )


def sign_repoatlas(draw: ImageDraw.ImageDraw, x: int, y: int, s: int) -> None:
    """Three connected points: a map of a codebase."""
    w = _stroke(s)
    points = [(x + s * 0.3, y + s * 0.68), (x + s * 0.5, y + s * 0.3), (x + s * 0.72, y + s * 0.62)]
    draw.line((*points[0], *points[1], *points[2], *points[0]), fill=SURFACE, width=round(w * 0.8))
    r = s * 0.085
    for px, py in points:
        draw.ellipse((px - r, py - r, px + r, py + r), fill=SURFACE)


def sign_gha(draw: ImageDraw.ImageDraw, x: int, y: int, s: int) -> None:
    """A play triangle: run it before you push."""
    draw.polygon(
        ((x + s * 0.37, y + s * 0.27), (x + s * 0.37, y + s * 0.73), (x + s * 0.74, y + s * 0.5)),
        fill=SURFACE,
    )


SIGNS: dict[str, Callable[[ImageDraw.ImageDraw, int, int, int], None]] = {
    "proxy-scraper": sign_proxy,
    "dejabuilt": sign_dejabuilt,
    "spillage": sign_spillage,
    "repoatlas": sign_repoatlas,
    "gha-preview": sign_gha,
}


# ---------------------------------------------------------------- the pictures


def hero(font_dir: Path) -> None:
    """The picture on top of #welcome: every project colour at once."""
    canvas = Canvas(1200, 480, font_dir)
    colours = [rgb(project.colour) for project in PROJECTS]
    spots = [(0.86, 0.02), (1.0, 0.24), (0.66, 0.38), (0.08, 0.42), (0.36, -0.06)]
    canvas.lights([(x, y, 0.15, colours[index % len(colours)], 0.62) for index, (x, y) in enumerate(spots)])
    left = 72
    canvas.draw.rounded_rectangle(
        (canvas.px(left), canvas.px(78), canvas.px(left + 16), canvas.px(94)),
        radius=canvas.px(5),
        fill=ACCENT,
    )
    canvas.text(left + 30, 86, "maximilianfeix", canvas.font("GeistMono-Regular.ttf", 22), TEXT, "lm")
    canvas.text(left - 5, 122, "open source", canvas.font("Geist-SemiBold.ttf", 124), TEXT)
    canvas.text(
        left,
        278,
        "Small developer tools that do one job and show their work.",
        canvas.font("Geist-Regular.ttf", 29),
        (214, 211, 219),
    )
    mono = canvas.font("GeistMono-Regular.ttf", 19)
    x, size = float(left), 44.0
    for project in PROJECTS:
        canvas.tile(x, 372, size, project)
        canvas.text(x + size + 12, 372 + size / 2, project.name, mono, TEXT, "lm")
        x += size + 12 + canvas.length(project.name, mono) + 30
    assert x - 30 <= 1200 - left, f"project row is too wide: {x}"
    canvas.save(ASSETS / "banner.png")


def project_banner(project: Project, font_dir: Path) -> None:
    """The picture on top of a project's card and of its release posts."""
    canvas = Canvas(1200, 300, font_dir)
    colour = rgb(project.colour)
    canvas.lights(
        [(0.9, 0.02, 0.2, colour, 0.75), (0.62, 0.3, 0.12, colour, 0.4), (0.0, 0.26, 0.1, colour, 0.3)]
    )
    left, size = 64, 124
    top = (300 - size) / 2
    canvas.tile(left, top, size, project)
    x = left + size + 40
    canvas.text(x, 150 - 54, project.language.lower(), canvas.font("GeistMono-Regular.ttf", 20), colour, "ls")
    canvas.text(x - 3, 150 + 26, project.name, canvas.font("Geist-SemiBold.ttf", 84), TEXT, "ls")
    canvas.text(x, 150 + 72, project.short, canvas.font("Geist-Regular.ttf", 27), (214, 211, 219), "ls")
    assert x + canvas.length(project.short, canvas.font("Geist-Regular.ttf", 27)) <= 1150, project.slug
    canvas.save(ASSETS / "projects" / f"{project.slug}.png")


def heading(name: str, kicker: str, title: str, colour: Colour, font_dir: Path) -> None:
    """A strip on top of a card: a small label and one large word."""
    canvas = Canvas(1200, 210, font_dir)
    canvas.lights([(0.92, 0.0, 0.17, colour, 0.75), (0.7, 0.2, 0.09, colour, 0.35)])
    left = 64
    canvas.draw.rounded_rectangle(
        (canvas.px(left), canvas.px(52), canvas.px(left + 14), canvas.px(66)),
        radius=canvas.px(4),
        fill=colour,
    )
    canvas.text(left + 26, 59, kicker, canvas.font("GeistMono-Regular.ttf", 20), MUTED, "lm")
    canvas.text(left - 4, 166, title, canvas.font("Geist-SemiBold.ttf", 86), TEXT, "ls")
    canvas.save(ASSETS / "headings" / f"{name}.png")


def emoji(project: Project, font_dir: Path) -> None:
    """The project's sign as a custom emoji."""
    canvas = Canvas(128, 128, font_dir)
    canvas.image = Image.new("RGBA", canvas.image.size, (0, 0, 0, 0))
    canvas.draw = ImageDraw.Draw(canvas.image)
    canvas.tile(4, 4, 120, project)
    canvas.save(ASSETS / "emoji" / f"{project.slug}.png")


def profile(font_dir: Path) -> None:
    """The banner on the bot's own profile."""
    canvas = Canvas(680, 240, font_dir)
    colours = [rgb(project.colour) for project in PROJECTS]
    canvas.lights(
        [
            (0.1 + 0.2 * index, 0.05 + 0.12 * (index % 2), 0.16, colour, 0.7)
            for index, colour in enumerate(colours)
        ]
    )
    canvas.save(ASSETS / "profile.png")


HEADINGS = (
    ("rules", "keep it kind", "Rules", (247, 146, 122)),
    ("notify", "never miss a release", "Notifications", (122, 215, 247)),
    ("help", "ask well, get answers", "Help", (247, 210, 122)),
    ("hello", "come on in", "Say hello", (180, 154, 247)),
)


def main(font_dir: Path) -> None:
    hero(font_dir)
    profile(font_dir)
    for name, kicker, title, colour in HEADINGS:
        heading(name, kicker, title, colour, font_dir)
    for project in PROJECTS:
        project_banner(project, font_dir)
        emoji(project, font_dir)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
