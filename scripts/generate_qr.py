"""Generate branded QR codes for J's domains — v2, segno-based.

Palette straight from the app:  --cyan #00D9FF  on  --midnight #000000

Outputs per domain into /app/docs/media/qr/:
  * <slug>.png         — 1200x1200, cyan-on-black, with centered J emblem
  * <slug>-flat.png    — 1200x1200, cyan-on-black, no emblem (best for tiny prints)
  * <slug>.svg         — infinitely scalable, cyan-on-black, no emblem

Level-H error correction (30%) so the ~18%-wide emblem never breaks the scan.
"""
from __future__ import annotations

import io
from pathlib import Path

import segno
from PIL import Image, ImageDraw, ImageFont


CYAN_HEX = "#00D9FF"
CYAN = (0, 217, 255)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

OUT = Path("/app/docs/media/qr")
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("blue-j-gauntlet", "https://blue-j-gauntlet.com"),
    ("bluejgenesis", "https://bluejgenesis.com"),
]

SIZE = 1200          # final canvas px
BORDER = 4           # quiet-zone modules
EMBLEM_FRAC = 0.18


def _emblem(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size // 12
    # Black cut-out backing so the emblem sits crisply inside the QR
    d.rectangle((0, 0, size, size), fill=BLACK)
    r = (size - 2 * pad) // 6
    d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=r, fill=CYAN)
    font = None
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, size=int(size * 0.62))
            break
    if font is None:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), "J", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - size * 0.03),
        "J", font=font, fill=WHITE,
    )
    return img


def _render_png(url: str, *, with_emblem: bool) -> Image.Image:
    """Render the QR to an in-memory PNG via segno, then convert to PIL."""
    q = segno.make(url, error="h")
    buf = io.BytesIO()
    # scale=25 → ample modules; we'll resize to SIZE below
    q.save(buf, kind="png", scale=25, dark=CYAN_HEX, light="#000000", border=BORDER)
    buf.seek(0)
    img = Image.open(buf).convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
    if with_emblem:
        e = int(SIZE * EMBLEM_FRAC)
        emblem = _emblem(e)
        img.paste(emblem, ((SIZE - e) // 2, (SIZE - e) // 2), emblem)
    return img


def main() -> None:
    print(f"→ {OUT}\n")
    for slug, url in TARGETS:
        _render_png(url, with_emblem=True).save(OUT / f"{slug}.png", "PNG", optimize=True)
        _render_png(url, with_emblem=False).save(OUT / f"{slug}-flat.png", "PNG", optimize=True)
        q = segno.make(url, error="h")
        q.save(str(OUT / f"{slug}.svg"), scale=20, dark=CYAN_HEX, light="#000000", border=BORDER)
        print(f"  {url}")
        print(f"    {slug}.png       (with J emblem)")
        print(f"    {slug}-flat.png  (no emblem)")
        print(f"    {slug}.svg       (scalable)\n")


if __name__ == "__main__":
    main()
