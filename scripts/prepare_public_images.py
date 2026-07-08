#!/usr/bin/env python3
"""Compress docs/public JPGs, build Open Graph card, prepare UI screenshot.

Usage:
  python scripts/prepare_public_images.py
  python scripts/prepare_public_images.py --ui path/to/screenshot.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOCS_PUBLIC = ROOT / "docs" / "public"
BG = (15, 23, 42)
CYAN = (34, 211, 238)
CORAL = (251, 113, 133)
WHITE = (248, 250, 252)
MUTED = (148, 163, 184)

JPG_TARGETS = (
    "hero-banner.jpg",
    "pipeline-concept.jpg",
    "mesh-3d.jpg",
    "vesicle-glow.jpg",
    "rbc-photoreal.jpg",
    "crowded-seed-concept.jpg",
    "active-surfaces-sketch.jpg",
    "brand-board.jpg",
    "logo-mark.jpg",
    "ui-app.jpg",
    "og-card.jpg",
)


def compress_jpgs(folder: Path, *, max_edge: int = 1920, quality: int = 85) -> list[str]:
    done: list[str] = []
    for name in JPG_TARGETS:
        path = folder / name
        if not path.is_file():
            continue
        im = Image.open(path).convert("RGB")
        w, h = im.size
        scale = min(1.0, max_edge / max(w, h))
        if scale < 1.0:
            im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        im.save(path, "JPEG", quality=quality, optimize=True, progressive=True)
        done.append(f"{name} -> {im.size[0]}x{im.size[1]}")
    return done


def load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def build_og_card(logo_path: Path, out_path: Path) -> None:
    w, h = 1200, 630
    card = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(card)

    # subtle grid
    for x in range(0, w, 48):
        draw.line([(x, 0), (x, h)], fill=(30, 41, 59), width=1)
    for y in range(0, h, 48):
        draw.line([(0, y), (w, y)], fill=(30, 41, 59), width=1)

    # accent bar
    draw.rectangle([0, 0, 8, h], fill=CYAN)
    draw.rectangle([0, h - 8, w, h], fill=(30, 41, 59))
    draw.rectangle([0, h - 8, 280, h], fill=CORAL)

    logo = Image.open(logo_path).convert("RGBA")
    logo = logo.resize((168, 168), Image.Resampling.LANCZOS)
    # dark plate behind logo
    plate = Image.new("RGB", (200, 200), (11, 18, 32))
    card.paste(plate, (72, 180))
    card.paste(logo, (88, 196), logo)

    title = load_font(72)
    sub = load_font(32)
    tiny = load_font(22)
    draw.text((320, 200), "MorphoStack", font=title, fill=WHITE)
    draw.text(
        (320, 300),
        "Local morphometry for microscopy Z-stacks",
        font=sub,
        fill=MUTED,
    )
    draw.text(
        (320, 360),
        "Vesicles · RBCs · seeded crowded fields · mesh export",
        font=tiny,
        fill=(100, 116, 139),
    )
    draw.text((320, 470), "morphostack  ·  mst  ·  v0.1.0", font=tiny, fill=CYAN)

    card.save(out_path, "JPEG", quality=88, optimize=True, progressive=True)


def prepare_ui_screenshot(source: Path, out_jpg: Path, out_png: Path) -> None:
    im = Image.open(source).convert("RGB")
    # Soft-anonymize bottom-right / path-like bright fields by slight blur on lower band if huge
    w, h = im.size
    # Crop browser chrome noise if present at very top thin strip only when huge
    if h > 900:
        im = im.crop((0, 0, w, h))

    # Cover sample path region with a neutral chip (left panel stack path area roughly)
    # Safer approach: lightly blur entire left-middle path text zone using relative box
    cover = im.copy()
    # Approximate path input row — user screenshot had path under stack file
    # Use a soft rectangle scrub near mid-left
    x0, y0, x1, y1 = int(0.05 * w), int(0.28 * h), int(0.42 * w), int(0.36 * h)
    if x1 > x0 and y1 > y0:
        region = cover.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(radius=8))
        # paint a clean field instead of blurry secrets
        draw = ImageDraw.Draw(cover)
        draw.rectangle([x0, y0, x1, y1], fill=(248, 250, 252), outline=(226, 232, 240))
        font = load_font(max(14, h // 70))
        draw.text((x0 + 12, y0 + (y1 - y0) // 3), "stack.tif  (local path redacted)", font=font, fill=(100, 116, 139))

    # Cap width for README
    max_w = 1600
    if cover.size[0] > max_w:
        nh = int(cover.size[1] * (max_w / cover.size[0]))
        cover = cover.resize((max_w, nh), Image.Resampling.LANCZOS)

    cover.save(out_png, "PNG", optimize=True)
    cover.convert("RGB").save(out_jpg, "JPEG", quality=86, optimize=True, progressive=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui", type=Path, default=None, help="Source UI screenshot to sanitize")
    parser.add_argument("--skip-compress", action="store_true")
    args = parser.parse_args()

    DOCS_PUBLIC.mkdir(parents=True, exist_ok=True)
    logo = DOCS_PUBLIC / "logo.png"
    if not logo.is_file():
        raise SystemExit("docs/public/logo.png missing — run scripts/extract_brand_logo.py first")

    og = DOCS_PUBLIC / "og-card.jpg"
    build_og_card(logo, og)
    print(f"Wrote {og}")

    if args.ui and args.ui.is_file():
        prepare_ui_screenshot(args.ui, DOCS_PUBLIC / "ui-app.jpg", DOCS_PUBLIC / "ui-app.png")
        print(f"Wrote ui-app.png / ui-app.jpg from {args.ui}")
    elif (DOCS_PUBLIC / "ui-app.png").is_file() or (DOCS_PUBLIC / "ui-app.jpg").is_file():
        print("UI asset already present; pass --ui to refresh from a new screenshot")
    else:
        print("No --ui source; skip UI asset")

    if not args.skip_compress:
        done = compress_jpgs(DOCS_PUBLIC)
        print("Compressed:")
        for line in done:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
