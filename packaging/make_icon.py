"""MorrowFriends icon — bold seal that stays readable in the Windows shell."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "morrowfriends.ico"
PNG = OUT.with_suffix(".png")

ASH = (18, 14, 10, 255)
RING = (212, 163, 92, 255)
RING_DIM = (140, 100, 48, 255)
FILL = (212, 163, 92, 255)
CREAM = (240, 230, 210, 255)


def _make(size: int) -> Image.Image:
    """Draw at higher res then downscale for crisp small sizes."""
    scale = 8 if size <= 48 else 4
    S = size * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = S / 2

    # Opaque rounded-square plate so Explorer doesn't show weird transparency
    pad = int(S * 0.04)
    d.rounded_rectangle(
        [pad, pad, S - pad - 1, S - pad - 1],
        radius=int(S * 0.18),
        fill=ASH,
    )

    # Outer ring
    r_out = S * 0.40
    r_in = S * 0.33
    d.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], outline=RING, width=max(scale, int(S * 0.055)))
    d.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], outline=RING_DIM, width=max(1, scale // 2))

    # Tick marks
    for i in range(12):
        ang = math.radians(i * 30 - 90)
        x0 = cx + (r_in + S * 0.01) * math.cos(ang)
        y0 = cy + (r_in + S * 0.01) * math.sin(ang)
        x1 = cx + (r_out - S * 0.01) * math.cos(ang)
        y1 = cy + (r_out - S * 0.01) * math.sin(ang)
        d.line([(x0, y0), (x1, y1)], fill=RING_DIM, width=max(scale, int(S * 0.02)))

    # Big crescent — drawn as moon minus cutout (reads at 16px)
    mr = S * 0.20
    mx, my = cx - S * 0.03, cy - S * 0.04
    d.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=FILL)
    cut = mr * 0.78
    d.ellipse(
        [mx - cut + mr * 0.55, my - cut - mr * 0.05, mx + cut + mr * 0.55, my + cut - mr * 0.05],
        fill=ASH,
    )

    # Small moon
    sr = S * 0.07
    sx, sy = cx + S * 0.14, cy - S * 0.10
    d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=RING_DIM)
    d.ellipse(
        [sx - sr * 0.7 + sr * 0.45, sy - sr * 0.7, sx + sr * 0.7 + sr * 0.45, sy + sr * 0.7],
        fill=ASH,
    )

    # Twin diamonds (friends) — oversized so shell shows them
    def diamond(x: float, y: float, r: float, fill):
        d.polygon([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], fill=fill)

    dr = S * 0.07
    diamond(cx - S * 0.10, cy + S * 0.18, dr, FILL)
    diamond(cx + S * 0.10, cy + S * 0.18, dr, CREAM)

    # Downscale with LANCZOS for shell sharpness
    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [_make(s) for s in sizes]
    # Save multi-resolution ICO (Windows shell picks 256 / 48 / 32)
    images[-1].save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
    )
    images[-1].save(PNG, format="PNG")
    for s, im in zip(sizes, images):
        im.save(OUT.parent / f"preview-{s}.png")
    print(OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
