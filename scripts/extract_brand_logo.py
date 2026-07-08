#!/usr/bin/env python3
"""Extract MorphoStack stacked-plate logo from docs/public/brand-board.jpg.

Writes docs/public logo variants and apps/web/public favicon assets.
See docs/visual-world-playbook.md for design rationale.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOARD = ROOT / "docs" / "public" / "brand-board.jpg"
DOCS_PUBLIC = ROOT / "docs" / "public"
WEB_PUBLIC = ROOT / "apps" / "web" / "public"
BG = (15, 23, 42)


def extract_stack_icon(board: Image.Image) -> Image.Image:
    w, h = board.size
    panel_box = (int(0.055 * w), int(0.055 * h), int(0.495 * w), int(0.495 * h))
    panel = board.crop(panel_box)
    pw, ph = panel.size
    arr = np.asarray(panel)
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    b = arr[:, :, 2].astype(int)

    cyan = (b > 150) & (g > 130) & (r < 130) & (b > r + 30)
    coral = (r > 170) & (g > 90) & (g < 190) & (b < 130) & (r > g + 20)
    mark = cyan | coral

    m = mark.copy()
    m[: int(0.06 * ph), :] = False
    m[-int(0.06 * ph) :, :] = False
    m[:, : int(0.06 * pw)] = False
    m[:, -int(0.06 * pw) :] = False
    m[: int(0.18 * ph), : int(0.35 * pw)] = False

    ys, xs = np.where(m)
    if len(xs) < 50:
        raise RuntimeError("Could not find brand cyan/coral plates in top-left panel")

    y_min, y_max = int(ys.min()), int(ys.max())
    y_cut = y_min + int(0.52 * (y_max - y_min))
    m2 = m.copy()
    m2[y_cut:, :] = False

    col_counts = m2.sum(axis=0)
    row_counts = m2.sum(axis=1)
    good_cols = np.where(col_counts >= 5)[0]
    good_rows = np.where(row_counts >= 5)[0]
    if len(good_cols) == 0 or len(good_rows) == 0:
        raise RuntimeError("Logo mask empty after wordmark cut")

    x0, x1 = int(good_cols.min()), int(good_cols.max())
    y0, y1 = int(good_rows.min()), int(good_rows.max())
    for x in range(x0, x1 + 1):
        if col_counts[x] > 15:
            x0 = x
            break
    for x in range(x1, x0, -1):
        if col_counts[x] > 15:
            x1 = x
            break

    pad = 8
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(pw, x1 + pad + 1), min(ph, y1 + pad + 1)
    stack = panel.crop((x0, y0, x1, y1))

    sw, sh = stack.size
    side = max(sw, sh) + 24
    canvas = Image.new("RGB", (side, side), BG)
    canvas.paste(stack, ((side - sw) // 2, (side - sh) // 2))

    a = np.asarray(canvas)
    content = ~((a[:, :, 0] < 25) & (a[:, :, 1] < 30) & (a[:, :, 2] < 45))
    frac = float(content.mean())
    if frac < 0.12:
        raise RuntimeError(f"Logo content fraction too low ({frac:.3f}); retune crop")

    return canvas


def extract_lockup(board: Image.Image) -> Image.Image:
    """Best-effort stack + wordmark crop from top-left panel."""
    w, h = board.size
    panel_box = (int(0.055 * w), int(0.055 * h), int(0.495 * w), int(0.495 * h))
    panel = board.crop(panel_box)
    pw, ph = panel.size
    arr = np.asarray(panel)
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    b = arr[:, :, 2].astype(int)
    cyan = (b > 150) & (g > 130) & (r < 130) & (b > r + 30)
    coral = (r > 170) & (g > 90) & (g < 190) & (b < 130) & (r > g + 20)
    white = (r > 200) & (g > 200) & (b > 200)
    m = cyan | coral
    m[: int(0.06 * ph), :] = False
    m[:, : int(0.06 * pw)] = False
    m[: int(0.18 * ph), : int(0.35 * pw)] = False
    ys, xs = np.where(m)
    if len(xs) == 0:
        return extract_stack_icon(board)
    x0, x1 = max(0, int(xs.min()) - 24), min(pw, int(xs.max()) + 24)
    y0 = max(0, int(ys.min()) - 8)
    wm = white.copy()
    wm[: int(ys.min() + 0.45 * (ys.max() - ys.min())), :] = False
    if wm.any():
        y1 = min(ph, int(np.where(wm)[0].max()) + 16)
    else:
        y1 = min(ph, int(ys.max()) + 40)
    return panel.crop((x0, y0, x1, y1))


def save_ladder(canvas: Image.Image, docs: Path, web: Path) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    web.mkdir(parents=True, exist_ok=True)

    canvas.save(docs / "logo-from-board.png")
    canvas.resize((512, 512), Image.Resampling.LANCZOS).save(docs / "logo.png")
    for size, name in ((256, "logo-icon-256.png"), (48, "favicon-48.png"), (32, "favicon-32.png")):
        canvas.resize((size, size), Image.Resampling.LANCZOS).save(docs / name)
    canvas.resize((180, 180), Image.Resampling.LANCZOS).save(docs / "apple-touch-icon.png")

    canvas.resize((512, 512), Image.Resampling.LANCZOS).save(web / "logo.png")
    canvas.resize((32, 32), Image.Resampling.LANCZOS).save(web / "favicon.png")
    canvas.resize((180, 180), Image.Resampling.LANCZOS).save(web / "apple-touch-icon.png")
    icos = [canvas.resize(s, Image.Resampling.LANCZOS) for s in ((16, 16), (32, 32), (48, 48))]
    icos[0].save(web / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    args = parser.parse_args()
    if not args.board.is_file():
        raise SystemExit(f"Brand board not found: {args.board}")

    board = Image.open(args.board).convert("RGB")
    icon = extract_stack_icon(board)
    save_ladder(icon, DOCS_PUBLIC, WEB_PUBLIC)

    lockup = extract_lockup(board)
    lockup.save(DOCS_PUBLIC / "logo-lockup-from-board.png")

    a = np.asarray(icon)
    content = ~((a[:, :, 0] < 25) & (a[:, :, 1] < 30) & (a[:, :, 2] < 45))
    print(f"Wrote logo ladder from {args.board}")
    print(f"  icon size: {icon.size}, content fraction: {float(content.mean()):.3f}")
    print(f"  docs: {DOCS_PUBLIC}")
    print(f"  web:  {WEB_PUBLIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
