"""把一天的连板天梯数据渲染成竖版长图（深蓝科技风）。

用法：python build/png.py --date 2026-10-26
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

import payload as pl

W = 1125
SCALE = 2
MARGIN = 26
LABEL_W = 96
COLS = 8
CELL_H = 84          # 首板行（条目多，紧凑）
CELL_H_RUNG = 124    # 连板行（条目少，留白更多）

# ---- 深蓝科技风配色 -------------------------------------------------------
BG_TOP = (12, 23, 41)
BG_BOTTOM = (5, 10, 18)
PANEL = (13, 26, 45)
PANEL_EDGE = (38, 72, 110)
RULE = (36, 68, 106)
RULE_SOFT = (23, 41, 64)
LABEL_TOP = (22, 52, 92)
LABEL_BOTTOM = (13, 30, 55)

CYAN = (56, 214, 255)
BLUE = (47, 129, 247)
BLUE_LIGHT = (121, 180, 255)
INK = (231, 240, 251)
INK_2 = (166, 188, 216)
INK_3 = (109, 134, 166)
INK_4 = (77, 97, 128)
UP = (255, 107, 107)
DOWN = (46, 212, 122)
UP_MUTED = (201, 112, 107)
DOWN_MUTED = (79, 157, 120)
BROKEN = (130, 152, 178)
BROKEN_SECTOR = (100, 120, 145)
BADGE_TOP = (63, 220, 255)
BADGE_BOTTOM = (47, 129, 247)

FONT_DIR = Path("C:/Windows/Fonts")
BOLD = "msyhbd.ttc"
REGULAR = "msyh.ttc"

# 兼容 Linux（GitHub Actions 上跑）：按优先级找一个可用的中文字体
FONT_CANDIDATES = {
    True: [
        FONT_DIR / BOLD,
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ],
    False: [
        FONT_DIR / REGULAR,
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ],
}

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font_path(bold: bool) -> Path:
    env = os.environ.get("ZT_FONT_BOLD" if bold else "ZT_FONT_REGULAR")
    if env and Path(env).exists():
        return Path(env)
    for candidate in FONT_CANDIDATES[bold]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("找不到可用的中文字体，请设置 ZT_FONT_BOLD / ZT_FONT_REGULAR")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = ("b" if bold else "r", size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(_font_path(bold)), size * SCALE)
    return _font_cache[key]


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Canvas:
    def __init__(self, width: int, height: int):
        self.size = (width * SCALE, height * SCALE)
        self.img = Image.new("RGB", self.size, BG_BOTTOM)
        self.d = ImageDraw.Draw(self.img)
        self._paint_background()

    # -- 底层 --------------------------------------------------------------
    def _paint_background(self) -> None:
        w, h = self.size
        grad = Image.new("RGB", (1, h))
        for y in range(h):
            grad.putpixel((0, y), lerp(BG_TOP, BG_BOTTOM, y / max(h - 1, 1)))
        self.img = grad.resize((w, h))
        self.d = ImageDraw.Draw(self.img)

        # 顶部冷色光晕（低分辨率绘制后放大，省时）
        gw, gh = max(2, w // 8), max(2, h // 8)
        glow = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([-gw * 0.3, -gh * 0.5, gw * 1.3, gh * 0.5], fill=(47, 129, 247, 70))
        gd.ellipse([gw * 0.5, -gh * 0.42, gw * 1.4, gh * 0.42], fill=(56, 214, 255, 34))
        glow = glow.filter(ImageFilter.GaussianBlur(16)).resize((w, h), Image.BICUBIC)
        self.img = Image.alpha_composite(self.img.convert("RGBA"), glow).convert("RGB")

        # 细网格
        grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd2 = ImageDraw.Draw(grid)
        step = 48 * SCALE
        for x in range(0, w, step):
            gd2.line([(x, 0), (x, h)], fill=(56, 214, 255, 6), width=1)
        for y in range(0, int(h * 0.55), step):
            gd2.line([(0, y), (w, y)], fill=(56, 214, 255, 6), width=1)
        self.img = Image.alpha_composite(self.img.convert("RGBA"), grid).convert("RGB")
        self.d = ImageDraw.Draw(self.img)

    # -- 基本绘制 ----------------------------------------------------------
    def _s(self, box):
        return [v * SCALE for v in box]

    def rect(self, box, fill=None, outline=None, width=1):
        self.d.rectangle(self._s(box), fill=fill, outline=outline, width=max(1, int(width * SCALE)))

    def rrect(self, box, radius, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(
            self._s(box), radius=radius * SCALE, fill=fill, outline=outline, width=max(1, int(width * SCALE))
        )

    def line(self, xy, fill, width=1):
        self.d.line([(x * SCALE, y * SCALE) for x, y in xy], fill=fill, width=max(1, int(width * SCALE)))

    def text(self, xy, s, f, fill, anchor="la"):
        self.d.text((xy[0] * SCALE, xy[1] * SCALE), s, font=f, fill=fill, anchor=anchor)

    def measure(self, s, f) -> float:
        return self.d.textlength(s, font=f) / SCALE

    # -- 渐变 / 发光 -------------------------------------------------------
    def gradient_rrect(self, box, radius, top, bottom):
        x0, y0, x1, y1 = box
        w, h = int((x1 - x0) * SCALE), int((y1 - y0) * SCALE)
        grad = Image.new("RGB", (1, h))
        for y in range(h):
            grad.putpixel((0, y), lerp(top, bottom, y / max(h - 1, 1)))
        grad = grad.resize((w, h))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius * SCALE, fill=255)
        self.img.paste(grad, (int(x0 * SCALE), int(y0 * SCALE)), mask)
        self.d = ImageDraw.Draw(self.img)

    def glow_text(self, xy, s, f, color, blur=8, alpha=120, anchor="la"):
        """只在小画布上做模糊，再把光晕贴回原图（比整图合成快很多）。"""
        pad = int(blur * SCALE * 2)
        l, t, r, b = [round(v) for v in self.d.textbbox((0, 0), s, font=f, anchor=anchor)]
        w, h = max(r - l, 1) + pad * 2, max(b - t, 1) + pad * 2
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(
            (pad - l, pad - t), s, font=f, fill=color + (alpha,), anchor=anchor
        )
        layer = layer.filter(ImageFilter.GaussianBlur(blur * SCALE / 2))
        self.img.paste(
            layer, (round(xy[0] * SCALE) + l - pad, round(xy[1] * SCALE) + t - pad), layer
        )

    def gradient_text(self, xy, s, f, top, bottom, anchor="la"):
        bbox = self.d.textbbox((0, 0), s, font=f, anchor=anchor)
        l, t, r, b = [round(v) for v in bbox]
        w, h = max(r - l, 1), max(b - t, 1)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).text((-l, -t), s, font=f, fill=255, anchor=anchor)
        grad = Image.new("RGB", (1, h))
        for y in range(h):
            grad.putpixel((0, y), lerp(top, bottom, y / max(h - 1, 1)))
        grad = grad.resize((w, h))
        self.img.paste(grad, (int(xy[0] * SCALE) + l, int(xy[1] * SCALE) + t), mask)
        self.d = ImageDraw.Draw(self.img)


def fit(canvas: Canvas, s: str, f, max_w: float) -> str:
    if canvas.measure(s, f) <= max_w:
        return s
    out = s
    while out and canvas.measure(out + "…", f) > max_w:
        out = out[:-1]
    return out + "…" if out else ""


def cell_height(height: int) -> int:
    return CELL_H if height == 1 else CELL_H_RUNG


def layout(payload: dict) -> dict:
    rows = payload["rows"]
    chips = payload.get("sectors") or []

    per_line, line_w, lines = [], 0.0, 1
    max_w = W - MARGIN * 2
    for chip in chips:
        w = len(chip["name"]) * 17 + 10 + 26
        if line_w + w > max_w and per_line:
            lines += 1
            per_line, line_w = [], 0.0
        per_line.append(chip["name"])
        line_w += w
    chip_h = lines * 32

    top = 240 + chip_h + 12
    table_h = sum(max(1, -(-len(r["stocks"]) // COLS)) * cell_height(r["height"]) for r in rows)
    footer_h = 120
    height = top + table_h + 44 + footer_h
    return {"top": top, "table_h": table_h, "height": height}


def draw_header(c: Canvas, payload: dict) -> None:
    # 周几徽标
    c.gradient_rrect([MARGIN, 22, MARGIN + 96, 82], 12, BADGE_TOP, BADGE_BOTTOM)
    c.rrect([MARGIN, 22, MARGIN + 96, 82], 12, outline=(120, 226, 255), width=1)
    badge_font = font(30, bold=True)
    c.glow_text((MARGIN + 48, 52), payload["weekday"], badge_font, (150, 235, 255), blur=10, alpha=90, anchor="mm")
    c.text((MARGIN + 48, 52), payload["weekday"], badge_font, (240, 250, 255), anchor="mm")

    c.text((MARGIN + 2, 90), payload["date"].replace("-", "."), font(17), INK_3)

    # 指数
    right = W - MARGIN
    idx = payload.get("index") or {}
    if idx.get("value"):
        pct = float(idx.get("pct") or 0)
        color = UP if pct >= 0 else DOWN
        name_f, value_f, chg_f = font(17), font(40, bold=True), font(19, bold=True)

        chg_txt = f"{pct:+.2f}%  {float(idx.get('chg') or 0):+.2f}"
        w_chg = c.measure(chg_txt, chg_f)
        w_val = c.measure(f"{idx['value']:.2f}", value_f)
        w_name = c.measure(idx.get("name") or "上证指数", name_f)

        x = right - w_chg
        c.text((x, 56), chg_txt, chg_f, color, anchor="ls")
        x -= w_val + 12
        c.glow_text((x, 56), f"{idx['value']:.2f}", value_f, CYAN, blur=12, alpha=90, anchor="ls")
        c.text((x, 56), f"{idx['value']:.2f}", value_f, CYAN, anchor="ls")
        x -= w_name + 10
        c.text((x, 56), idx.get("name") or "上证指数", name_f, INK_3, anchor="ls")

    # 涨跌家数 + 比例条
    breadth = payload.get("breadth") or {}
    if breadth.get("up") is not None and breadth.get("down") is not None:
        up, down = int(breadth["up"]), int(breadth["down"])
        up_f, down_f = font(17, bold=True), font(17, bold=True)
        up_txt, down_txt = f"涨 {up}", f"跌 {down}"
        bar_w = 330
        total = up + down or 1
        w_up, w_down = c.measure(up_txt, up_f), c.measure(down_txt, down_f)
        span = w_up + 14 + bar_w + 14 + w_down
        x = right - span
        c.text((x, 112), up_txt, up_f, UP, anchor="ls")
        bx = x + w_up + 14
        c.rrect([bx, 104, bx + bar_w, 115], 6, fill=(14, 143, 87))
        red_w = max(6.0, bar_w * up / total)
        c.rrect([bx, 104, bx + red_w, 115], 6, fill=(217, 59, 59))
        c.rect([bx + red_w - 6, 104, bx + red_w, 115], fill=(217, 59, 59))
        c.text((bx + bar_w + 14, 112), down_txt, down_f, DOWN, anchor="ls")


def draw_title(c: Canvas, payload: dict) -> None:
    t1, t2 = payload["label"], "连板天梯"
    f = font(52, bold=True)
    gap = 26
    w1, w2 = c.measure(t1, f), c.measure(t2, f)
    x = (W - (w1 + w2 + gap)) / 2
    y = 196  # 基线

    c.glow_text((x, y), t1, f, CYAN, blur=14, alpha=70, anchor="ls")
    c.glow_text((x + w1 + gap, y), t2, f, CYAN, blur=14, alpha=70, anchor="ls")
    c.gradient_text((x, y), t1, f, (226, 247, 255), (56, 214, 255), anchor="ls")
    c.gradient_text((x + w1 + gap, y), t2, f, (226, 247, 255), (47, 129, 247), anchor="ls")


def draw_chips(c: Canvas, payload: dict, top: float) -> None:
    chips = payload.get("sectors") or []
    if not chips:
        return
    name_f, count_f = font(17), font(14)
    max_w = W - MARGIN * 2
    lines: list[list[tuple]] = [[]]
    width = 0.0
    for chip in chips:
        w = c.measure(chip["name"], name_f) + c.measure(str(chip["count"]), count_f) + 6
        if width + w > max_w and lines[-1]:
            lines.append([])
            width = 0.0
        lines[-1].append((chip["name"], chip["count"], w))
        width += w + 26

    for li, line in enumerate(lines):
        total = sum(item[2] for item in line) + 26 * (len(line) - 1)
        x = (W - total) / 2
        y = top + li * 32 + 14
        for name, count, w in line:
            c.text((x, y), name, name_f, BLUE_LIGHT, anchor="lm")
            nw = c.measure(name, name_f)
            c.text((x + nw + 3, y + 2), str(count), count_f, (77, 111, 153), anchor="lm")
            x += w + 26


def hud_corners(c: Canvas, box, size: float = 16, color=(56, 190, 235), width: float = 2) -> None:
    x0, y0, x1, y1 = box
    for cx, cy, dx, dy in (
        (x0, y0, 1, 1),
        (x1, y0, -1, 1),
        (x0, y1, 1, -1),
        (x1, y1, -1, -1),
    ):
        c.line([(cx, cy), (cx + dx * size, cy)], color, width)
        c.line([(cx, cy), (cx, cy + dy * size)], color, width)


def draw_table(c: Canvas, payload: dict, top: float) -> None:
    rows = payload["rows"]
    left = MARGIN
    right = W - MARGIN
    col_w = (right - left - LABEL_W) / COLS

    table_h = sum(max(1, -(-len(r["stocks"]) // COLS)) * cell_height(r["height"]) for r in rows)

    c.rrect([left, top, right, top + table_h], 8, fill=PANEL, outline=PANEL_EDGE, width=1)
    hud_corners(c, (left - 3, top - 3, right + 3, top + table_h + 3), 16)
    # 左侧连板数栏
    c.rrect([left, top, left + LABEL_W, top + table_h], 8, fill=(14, 32, 56))
    c.rect([left + 2, top + 2, left + LABEL_W - 2, top + table_h - 2], fill=(14, 32, 56))
    c.line([(left, top + 8), (left, top + table_h - 8)], BLUE, 2)
    c.line([(left + LABEL_W, top + 2), (left + LABEL_W, top + table_h - 2)], (36, 72, 112), 1)

    y = top
    for rung in rows:
        n = len(rung["stocks"])
        cell_h = cell_height(rung["height"])
        lines = max(1, -(-n // COLS))
        height = lines * cell_h

        if y > top:
            c.line([(left + 2, y), (right - 2, y)], RULE, 1)

        label = "首板" if rung["height"] == 1 else f"{rung['height']}板"
        label_font = font(26 if rung["height"] > 1 else 24, bold=True)
        cy = y + height / 2
        c.glow_text((left + LABEL_W / 2, cy - 8), label, label_font, CYAN, blur=10, alpha=70, anchor="mm")
        c.text((left + LABEL_W / 2, cy - 8), label, label_font, CYAN, anchor="mm")
        c.text((left + LABEL_W / 2, cy + 18), f"({n})", font(12), (95, 131, 171), anchor="mm")

        for i, stock in enumerate(rung["stocks"]):
            col, line_no = i % COLS, i // COLS
            x = left + LABEL_W + col * col_w
            cyy = y + line_no * cell_h
            draw_cell(c, stock, x, cyy, col_w, cell_h)

        y += height


def draw_cell(c: Canvas, stock: dict, x: float, y: float, col_w: float, cell_h: int = 84) -> None:
    pad = 12
    inner = col_w - pad * 2
    top_y = y + (14 if cell_h > 90 else 10)

    if stock.get("broken"):
        pct = stock.get("pct")
        color = UP_MUTED if (pct or 0) >= 0 else DOWN_MUTED
        pct_txt = "—" if pct is None else f"{pct:+.2f}%"
        c.text((x + pad, top_y + 7), pct_txt, font(12, bold=True), color, anchor="lm")
    elif stock.get("oneWord"):
        badge_font = font(11, bold=True)
        text = "一字板"
        w = c.measure(text, badge_font) + 12
        c.gradient_rrect([x + pad, top_y - 1, x + pad + w, top_y + 16], 4, BADGE_TOP, BADGE_BOTTOM)
        c.text((x + pad + w / 2, top_y + 7.5), text, badge_font, (4, 18, 31), anchor="mm")
    else:
        t = stock.get("lastTime") or stock.get("firstTime") or ""
        if t:
            c.text((x + pad, top_y + 7), t, font(12), (111, 141, 178), anchor="lm")

    name = stock["name"]
    name_font = font(19, bold=True)
    if stock.get("broken"):
        name = fit(c, name, name_font, inner)
        c.text((x + pad, top_y + 24), name, name_font, BROKEN)
        w = c.measure(name, name_font)
        c.line([(x + pad, top_y + 37), (x + pad + w, top_y + 37)], (67, 86, 109), 1)
    else:
        name = fit(c, name, name_font, inner)
        c.text((x + pad, top_y + 24), name, name_font, INK)

    sector = fit(c, stock.get("sector") or "其他", font(12), inner)
    c.text((x + pad, top_y + 56), sector, font(12), BROKEN_SECTOR if stock.get("broken") else (139, 165, 195))


def draw_footer(c: Canvas, payload: dict, top: float, height: int) -> None:
    c.text((W / 2, top), payload.get("disclaimer") or "内容来自网络整理，不做任何投资建议", font(15), (109, 131, 164), anchor="ma")
    meta = f"数据源 东方财富 · 同花顺    更新 {payload.get('updatedAt', '')[11:16]}"
    c.text((W / 2, top + 30), meta, font(11), (82, 103, 138), anchor="ma")


def render(date: str | None = None) -> Path:
    if not date:
        date = json.loads((pl.DATA_DIR / "index.json").read_text(encoding="utf-8"))["latest"]
    payload = json.loads((pl.DATA_DIR / f"{date}.json").read_text(encoding="utf-8"))

    geo = layout(payload)
    canvas = Canvas(W, int(geo["height"]))
    draw_header(canvas, payload)
    draw_title(canvas, payload)
    draw_chips(canvas, payload, 204)
    draw_table(canvas, payload, geo["top"])
    footer_top = geo["top"] + geo["table_h"] + 44
    draw_footer(canvas, payload, footer_top, int(geo["height"]))

    out_dir = pl.PUBLIC / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{date}.png"
    final = canvas.img.resize((W, int(geo["height"])), Image.LANCZOS)
    final.save(out, "PNG", optimize=True)
    return out


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all:
        for path in sorted(pl.DATA_DIR.glob("????-??-??.json")):
            print(render(path.stem))
    else:
        print(render(args.date))


if __name__ == "__main__":
    main()
