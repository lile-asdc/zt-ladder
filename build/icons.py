"""生成 PWA 图标：红底 + 奶白色「天梯」图形。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
BLUE_TOP = (47, 129, 247)
BLUE_BOTTOM = (9, 52, 128)
CYAN = (120, 232, 255)


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        grad.putpixel(
            (0, y),
            tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )
    return grad.resize((size, size))


def draw_icon(size: int, *, maskable: bool = False) -> Image.Image:
    canvas = vertical_gradient(size, BLUE_TOP, BLUE_BOTTOM)
    draw = ImageDraw.Draw(canvas)

    # 安全区：maskable 需要把图形缩到内圈
    pad = size * (0.22 if maskable else 0.16)
    w = size - pad * 2

    # 梯子：两根立柱 + 四根横档
    rail_w = w * 0.115
    left = pad + w * 0.16
    right = pad + w * 0.84
    top = pad + w * 0.10
    bottom = pad + w * 0.90

    for x in (left, right):
        draw.rounded_rectangle(
            [x - rail_w / 2, top, x + rail_w / 2, bottom], radius=rail_w / 2, fill=CYAN
        )

    rungs = 4
    for i in range(rungs):
        y = top + (bottom - top) * (i + 1) / (rungs + 1)
        draw.rounded_rectangle(
            [left - rail_w / 2, y - w * 0.045, right + rail_w / 2, y + w * 0.045],
            radius=w * 0.045,
            fill=CYAN,
        )

    if maskable:
        return canvas  # 全出血，交给系统裁切
    canvas.putalpha(rounded_mask(size, int(size * 0.22)))
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw_icon(192).save(OUT / "icon-192.png")
    draw_icon(512).save(OUT / "icon-512.png")
    draw_icon(512, maskable=True).save(OUT / "icon-maskable-512.png")
    print("icons ->", OUT)


if __name__ == "__main__":
    main()
