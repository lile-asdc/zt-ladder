"""个股日 K 缓存：给「打板赚钱效应」「首板次日溢价」提供次日行情。

数据源：腾讯日 K（http，稳定）；失败时退回新浪日 K。
缓存目录：public/data/kline/{code}.json  ->  [[date, open, high, low, close], ...]
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import em

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(".cache") / "kline"


def _symbol(code: str) -> str:
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("4", "8", "9")):
        return "bj" + code
    return "sz" + code


def _fetch_tencent(code: str, count: int = 90) -> list[list]:
    symbol = _symbol(code)
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{count},qfq"
    try:
        payload = json.loads(em._get(url, "http://gu.qq.com/", retries=2))
    except (em.SourceError, ValueError):
        return []
    node = ((payload.get("data") or {}).get(symbol)) or {}
    rows = node.get("qfqday") or node.get("day") or []
    out = []
    for row in rows:
        if len(row) < 5:
            continue
        try:
            out.append([
                row[0],
                round(float(row[1]), 2),
                round(float(row[3]), 2),
                round(float(row[4]), 2),
                round(float(row[2]), 2),
                round(float(row[5]), 0) if len(row) > 5 else 0,
            ])
        except (TypeError, ValueError):
            continue
    return out


def _fetch_sina(code: str, count: int = 90) -> list[list]:
    symbol = _symbol(code)
    url = (
        "http://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
        f"?symbol={symbol}&scale=240&ma=no&datalen={count}"
    )
    try:
        text = em._get(url, "http://finance.sina.com.cn/", retries=2)
        rows = json.loads(text)
    except (em.SourceError, ValueError):
        return []
    out = []
    for row in rows:
        try:
            out.append(
                [
                    (row.get("day") or "")[:10],
                    round(float(row["open"]), 2),
                    round(float(row["high"]), 2),
                    round(float(row["low"]), 2),
                    round(float(row["close"]), 2),
                    round(float(row["volume"] or 0), 0),
                ]
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def load(code: str, data_dir: Path) -> list[list]:
    path = ROOT / CACHE_DIR / f"{code}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return []
    return []


def ensure(codes: list[str], data_dir: Path, workers: int = 8) -> int:
    """补齐缺失的日 K 缓存，返回新抓取数量。"""
    out_dir = ROOT / CACHE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [c for c in dict.fromkeys(codes) if c and not (out_dir / f"{c}.json").exists()]

    def one(code: str):
        rows = _fetch_tencent(code)
        if not rows:
            rows = _fetch_sina(code)
        if rows:
            (out_dir / f"{code}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return bool(rows)

    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, todo))
    time.sleep(0.2)
    return sum(1 for r in results if r)


def close_on(code: str, data_dir: Path, date: str) -> float | None:
    for row in load(code, data_dir):
        if row[0] == date:
            return row[4]
    return None


def bar_after(code: str, data_dir: Path, date: str) -> list | None:
    """返回 date 之后的下一个交易日 bar。"""
    rows = load(code, data_dir)
    for i, row in enumerate(rows):
        if row[0] == date and i + 1 < len(rows):
            return rows[i + 1]
    return None
