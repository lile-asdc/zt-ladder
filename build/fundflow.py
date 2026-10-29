"""资金流：行业主力净额 + 个股主力净额（同花顺 HTML 页面，解析稳定）。

东财 push2 的列表接口在当前网络与 GitHub Actions 上都被断连，故改用同花顺。
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

import em

SECTOR_URL = "http://data.10jqka.com.cn/funds/hyzjl/"
STOCK_URL = "http://data.10jqka.com.cn/funds/ggzjl/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


def _get(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "http://data.10jqka.com.cn/"}
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("gbk", "replace")


def _rows(html: str) -> list[list[str]]:
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if cells and re.fullmatch(r"\d{1,3}", cells[0]):
            out.append(cells)
    return out


def _num(text: str) -> float:
    """'2.19亿' -> 2.19 ; '1234万' -> 0.1234 ; '41.26' -> 41.26"""
    text = (text or "").strip()
    try:
        if text.endswith("亿"):
            return round(float(text[:-1]), 2)
        if text.endswith("万"):
            return round(float(text[:-1]) / 10000, 4)
        return round(float(text), 2)
    except ValueError:
        return 0.0


def fetch_sectors(limit: int = 12) -> list[dict] | None:
    try:
        html = _get(SECTOR_URL)
    except Exception:  # noqa: BLE001
        return None
    out = []
    for cells in _rows(html):
        if len(cells) < 7:
            continue
        out.append({"name": cells[1], "pct": cells[3], "net": _num(cells[6]), "count": cells[7] if len(cells) > 7 else None})
    if not out:
        return None
    out.sort(key=lambda x: -x["net"])
    return out[:limit]


def fetch_stocks(limit: int = 20) -> list[dict] | None:
    try:
        html = _get(STOCK_URL)
    except Exception:  # noqa: BLE001
        return None
    out = []
    for cells in _rows(html):
        if len(cells) < 8:
            continue
        net = round(_num(cells[6]) - _num(cells[7]), 2)
        out.append({"code": cells[1], "name": cells[2], "pct": cells[4], "net": net})
    if not out:
        return None
    out.sort(key=lambda x: -x["net"])
    return out[:limit]


def build(data_dir: Path) -> Path | None:
    sectors = fetch_sectors()
    stocks = fetch_stocks()
    if not sectors and not stocks:
        return None
    payload = {
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
        "source": "10jqka",
        "sectors": sectors or [],
        "stocks": stocks or [],
    }
    out = data_dir / "fundflow.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
