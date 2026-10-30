"""形态胜率：在全市场日 K 上统计几种常见形态的次日 / 5 日表现。

形态（只用价格 + 成交量，公开数据可复现）：
* 放量新高   —— 收盘创 20 日新高，且成交量 > 前 5 日均量 1.5 倍
* 缩量回踩   —— 跌破 5 日线但仍在 20 日线上，量能 < 5 日均量 0.7 倍
* 突破平台   —— 收盘创 20 日新高，且前 20 日振幅 < 15%
* 三连阳     —— 连续 3 根阳线
* 涨停后首阴 —— 昨日涨幅 ≥ 9.5%，今日收阴但未破 5 日线
* 均线多头   —— MA5 > MA10 > MA20，且为首次成立
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import em

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "kline"

PATTERNS = [
    ("放量新高", "创 20 日新高 + 放量 1.5 倍"),
    ("缩量回踩", "回踩 5 日线不破 20 日线 + 缩量"),
    ("突破平台", "20 日窄幅震荡后创新高"),
    ("三连阳", "连续 3 根阳线"),
    ("涨停后首阴", "涨停次日收阴但守住 5 日线"),
    ("均线多头", "MA5>MA10>MA20 首次成立"),
]


def _ma(values: list[float], i: int, n: int) -> float | None:
    if i + 1 < n:
        return None
    window = values[i - n + 1 : i + 1]
    return sum(window) / n


def index_returns() -> dict[str, float]:
    """上证指数日涨跌幅（新浪日线，腾讯作备选），用于算相对大盘的超额胜率。"""
    import json as _json

    closes: list[tuple[str, float]] = []
    try:
        url = (
            "http://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
            "?symbol=sh000001&scale=240&ma=no&datalen=200"
        )
        text = em._get(url, "http://finance.sina.com.cn/", retries=2)
        for row in _json.loads(text):
            closes.append(((row.get("day") or "")[:10], float(row["close"])))
    except Exception:  # noqa: BLE001
        closes = []
    if not closes:
        for row in em._tx_kline(200):
            try:
                closes.append((row[0], float(row[2])))
            except (TypeError, ValueError):
                continue

    out: dict[str, float] = {}
    prev = None
    for date, close in closes:
        if prev:
            out[date] = (close / prev - 1) * 100
        prev = close
    return out


def evaluate(bars: list[list], idx: dict[str, float] | None = None) -> dict[tuple[str, str], dict]:
    """返回 {(pattern, date): {ret1, ret5}} 的原始样本。"""
    if len(bars) < 30:
        return {}
    closes = [b[4] for b in bars]
    opens = [b[1] for b in bars]
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]
    vols = [b[5] if len(b) > 5 else 0 for b in bars]

    hits: dict[tuple[str, str], dict] = {}
    for i in range(20, len(bars) - 1):
        date = bars[i][0]
        ma5 = _ma(closes, i, 5)
        ma10 = _ma(closes, i, 10)
        ma20 = _ma(closes, i, 20)
        if not (ma5 and ma10 and ma20):
            continue
        prev_vol = sum(vols[i - 5 : i]) / 5 if i >= 5 else 0
        hi20 = max(highs[i - 20 : i])
        lo20 = min(lows[i - 20 : i])
        pct_prev = (closes[i - 1] / closes[i - 2] - 1) * 100 if i >= 2 and closes[i - 2] else 0

        matched = set()
        if closes[i] >= max(closes[i - 20 : i]) and prev_vol and vols[i] > prev_vol * 1.5:
            matched.add("放量新高")
        if closes[i] < ma5 and closes[i] > ma20 and prev_vol and vols[i] < prev_vol * 0.7:
            matched.add("缩量回踩")
        if closes[i] >= hi20 and lo20 and (hi20 - lo20) / lo20 < 0.15:
            matched.add("突破平台")
        if closes[i] > opens[i] and closes[i - 1] > opens[i - 1] and closes[i - 2] > opens[i - 2]:
            matched.add("三连阳")
        if pct_prev >= 9.5 and closes[i] < opens[i] and closes[i] > ma5:
            matched.add("涨停后首阴")
        prev_multi = _ma(closes, i - 1, 5), _ma(closes, i - 1, 10), _ma(closes, i - 1, 20)
        if (
            ma5 > ma10 > ma20
            and all(prev_multi)
            and not (prev_multi[0] > prev_multi[1] > prev_multi[2])
        ):
            matched.add("均线多头")

        if not matched:
            continue
        ret1 = (closes[i + 1] / closes[i] - 1) * 100
        ret5 = (closes[i + 5] / closes[i] - 1) * 100 if i + 5 < len(bars) else None
        base = (idx or {}).get(date)
        for name in matched:
            hits[(name, date)] = {
                "ret1": ret1,
                "ret5": ret5,
                "x1": (ret1 - base) if base is not None else None,
            }
    return hits


def build(max_files: int | None = None) -> dict:
    agg: dict[str, dict] = {
        name: {"n": 0, "w1": 0, "s1": 0.0, "n5": 0, "w5": 0, "s5": 0.0, "nx": 0, "wx": 0, "sx": 0.0}
        for name, _ in PATTERNS
    }
    idx = index_returns()
    files = sorted(CACHE.glob("*.json"))
    if max_files:
        files = files[:max_files]
    used = 0
    dates_seen: set[str] = set()
    for path in files:
        try:
            bars = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if len(bars) < 30:
            continue
        used += 1
        dates_seen.update(b[0] for b in bars)
        for (name, _date), res in evaluate(bars, idx).items():
            slot = agg[name]
            slot["n"] += 1
            slot["s1"] += res["ret1"]
            if res["ret1"] > 0:
                slot["w1"] += 1
            if res.get("x1") is not None:
                slot["nx"] += 1
                slot["sx"] += res["x1"]
                if res["x1"] > 0:
                    slot["wx"] += 1
            if res["ret5"] is not None:
                slot["n5"] += 1
                slot["s5"] += res["ret5"]
                if res["ret5"] > 0:
                    slot["w5"] += 1

    rows = []
    for name, desc in PATTERNS:
        slot = agg[name]
        if not slot["n"]:
            continue
        rows.append(
            {
                "name": name,
                "desc": desc,
                "n": slot["n"],
                "win1": round(slot["w1"] / slot["n"] * 100, 1),
                "avg1": round(slot["s1"] / slot["n"], 2),
                "winX": round(slot["wx"] / slot["nx"] * 100, 1) if slot["nx"] else None,
                "avgX": round(slot["sx"] / slot["nx"], 2) if slot["nx"] else None,
                "win5": round(slot["w5"] / slot["n5"] * 100, 1) if slot["n5"] else None,
                "avg5": round(slot["s5"] / slot["n5"], 2) if slot["n5"] else None,
            }
        )
    rows.sort(key=lambda r: -r["win1"])

    return {
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
        "stocks": used,
        "from": min(dates_seen) if dates_seen else None,
        "to": max(dates_seen) if dates_seen else None,
        "rows": rows,
    }


def save(payload: dict, data_dir: Path) -> Path:
    out = data_dir / "patterns.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
