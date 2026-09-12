"""Procedural ash-night backdrop for the MorrowFriends launcher."""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


@lru_cache(maxsize=4)
def make_atmosphere(width: int = 1100, height: int = 900) -> Image.Image:
    """Dark ash field with a low Red Mountain glow — no purple, no neon."""
    width = max(640, min(int(width), 1800))
    height = max(520, min(int(height), 1400))

    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(9 + t * 18)
        g = int(8 + t * 7)
        b = int(11 + (1.0 - t) * 5)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Fine ash grain from a small noise plate (fast, cached).
    nw, nh = max(160, width // 4), max(120, height // 4)
    noise = Image.effect_noise((nw, nh), 22).convert("L")
    noise = noise.resize((width, height), Image.Resampling.BILINEAR)
    grain = ImageEnhance.Contrast(noise).enhance(1.35).convert("RGB")
    img = Image.blend(img, grain, 0.06)

    bloom = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(bloom)
    cx, cy = int(width * 0.86), int(height * 0.82)
    for i, alpha in enumerate((78, 46, 24, 11)):
        radius = int(width * (0.48 - i * 0.055))
        bdraw.ellipse(
            [cx - radius, cy - int(radius * 0.70), cx + radius, cy + int(radius * 0.70)],
            fill=(178, 68, 40, alpha),
        )
    bloom = bloom.filter(ImageFilter.GaussianBlur(radius=52))
    img = Image.alpha_composite(img.convert("RGBA"), bloom)

    cool = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(cool)
    cx2, cy2 = int(width * 0.16), int(height * 0.10)
    for i, alpha in enumerate((40, 20, 9)):
        radius = int(width * (0.36 - i * 0.05))
        cdraw.ellipse(
            [cx2 - radius, cy2 - radius, cx2 + radius, cy2 + radius],
            fill=(52, 56, 68, alpha),
        )
    cool = cool.filter(ImageFilter.GaussianBlur(radius=42))
    img = Image.alpha_composite(img, cool)

    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    for i, alpha in enumerate((60, 32, 14)):
        pad = int(height * (0.018 + i * 0.045))
        vdraw.rectangle([0, 0, width, pad], fill=(5, 4, 7, alpha))
    for i, alpha in enumerate((36, 18, 8)):
        pad = int(width * (0.012 + i * 0.028))
        vdraw.rectangle([0, 0, pad, height], fill=(5, 4, 7, alpha))
        vdraw.rectangle([width - pad, 0, width, height], fill=(5, 4, 7, alpha))
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=28))
    img = Image.alpha_composite(img, vignette)
    return img.convert("RGB")


@lru_cache(maxsize=8)
def make_gear_icon(
    size: int = 20,
    color: tuple[int, int, int] = (176, 168, 150),
    teeth: int = 8,
) -> Image.Image:
    """Flat settings gear on transparency.

    Drawn at 4x and downsampled — a gear this small drawn at 1x has ragged
    teeth. Returned RGBA so it sits on the panel or the backdrop unchanged;
    the launcher tints it by passing the theme colour, never by recolouring
    a baked asset.
    """
    size = max(12, min(int(size), 128))
    teeth = max(5, min(int(teeth), 16))
    ss = 4
    n = size * ss
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx = cy = n / 2.0
    r_out = n * 0.47
    r_in = n * 0.345
    r_hole = n * 0.155
    tau = math.pi * 2.0
    steps = teeth * 2
    seg = tau / steps
    # Pull each tooth's corners inward so the teeth read as trapezoids rather
    # than square pegs, which is what makes it look like a gear and not a star.
    inset = seg * 0.16

    pts: list[tuple[float, float]] = []
    for i in range(steps):
        radius = r_out if i % 2 == 0 else r_in
        bite = inset if i % 2 == 0 else -inset
        a0 = i * seg + bite
        a1 = (i + 1) * seg - bite
        pts.append((cx + radius * math.cos(a0), cy + radius * math.sin(a0)))
        pts.append((cx + radius * math.cos(a1), cy + radius * math.sin(a1)))

    draw.polygon(pts, fill=(color[0], color[1], color[2], 255))
    # fill=(0,0,0,0) REPLACES rather than blends on RGBA, so this punches a
    # real hole instead of painting a black dot.
    draw.ellipse(
        [cx - r_hole, cy - r_hole, cx + r_hole, cy + r_hole], fill=(0, 0, 0, 0)
    )
    return img.resize((size, size), Image.Resampling.LANCZOS)
