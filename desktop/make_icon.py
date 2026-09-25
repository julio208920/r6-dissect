"""
make_icon.py
============
Draws the app icon: desktop/assets/app.ico (the exe, window, taskbar and
shortcuts) and scripts/icon.png (the page's favicon). The outputs are checked
in; rerun this only to change the design:  python desktop/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BG_TOP, BG_BOTTOM = (31, 39, 51), (13, 17, 23)  # the app's panel and page colors
ACCENT = (255, 92, 26)  # the app's orange
BARS = (240, 243, 246)


def draw(size: int) -> Image.Image:
    """The icon at `size` px: a crosshair around three rising stat bars.
    Drawn 4x larger and scaled down for smooth edges; small sizes get
    thicker strokes and no crosshair ticks, so they stay readable."""
    s = size * 4
    small = size <= 32
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # rounded square with a vertical gradient
    gradient = Image.new("RGBA", (s, s))
    g = ImageDraw.Draw(gradient)
    for y in range(s):
        t = y / (s - 1)
        g.line([(0, y), (s, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.22, fill=255)
    img.paste(gradient, (0, 0), mask)

    d = ImageDraw.Draw(img)
    c = s / 2
    ring = s * (0.34 if small else 0.31)
    width = round(s * (0.085 if small else 0.055))
    d.ellipse([c - ring, c - ring, c + ring, c + ring], outline=ACCENT, width=width)
    if not small:
        gap, tick = s * 0.05, s * 0.13
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            start = (c + dx * (ring - tick), c + dy * (ring - tick))
            end = (c + dx * (ring + gap + tick * 0.35), c + dy * (ring + gap + tick * 0.35))
            d.line([start, end], fill=ACCENT, width=width)

    # three rising bars inside the ring
    bar_w = s * (0.1 if small else 0.075)
    space = s * (0.045 if small else 0.035)
    base = c + ring * 0.45
    heights = (0.24, 0.38, 0.52) if small else (0.2, 0.33, 0.47)
    left = c - (3 * bar_w + 2 * space) / 2
    for i, h in enumerate(heights):
        x = left + i * (bar_w + space)
        d.rounded_rectangle([x, base - s * h * 0.7, x + bar_w, base], radius=bar_w * 0.25,
                            fill=ACCENT if i == 2 else BARS)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [draw(n) for n in sizes]
    ico = ROOT / "desktop" / "assets" / "app.ico"
    ico.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(ico, format="ICO", sizes=[(n, n) for n in sizes], append_images=frames[:-1])
    draw(128).save(ROOT / "scripts" / "icon.png")
    print(f"Wrote {ico.relative_to(ROOT)} and scripts/icon.png")


if __name__ == "__main__":
    main()
