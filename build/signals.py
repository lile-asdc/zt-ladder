"""策略信号：从「买什么」扩展到「什么时候买/卖、避开什么」。

全部基于已有数据（58 天涨停池 + 全市场日 K），输出 public/data/signals.json。
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import em
import kline
import problib

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "public" / "data"


def _limit_pct(code: str) -> float:
    if code.startswith(("30", "68")):
        return 0.20
    if code.startswith(("4", "8", "92")):
        return 0.30
    return 0.10


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    return round((s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2), 2)


def sell_stats(days: dict[str, list[dict]], dates: list[str]) -> dict:
    """首板次日：最高涨幅、收盘涨幅、回撤（冲高回落）分布。"""
    highs, closes, gives = [], [], []
    for date in dates:
        nd = problib.next_day(dates, date)
        if not nd:
            continue
        for ev in days[date]:
            if ev["height"] != 1:
                continue
            bar = kline.bar_after(ev["code"], DATA, date)
            base = kline.close_on(ev["code"], DATA, date)
            if not bar or not base:
                continue
            high_pct = (bar[2] / base - 1) * 100
            close_pct = (bar[4] / base - 1) * 100
            highs.append(high_pct)
            closes.append(close_pct)
            gives.append(high_pct - close_pct)
    if not closes:
        return {}
    buckets = [(-999, 0), (0, 2), (2, 5), (5, 8), (8, 99)]
    dist = []
    for lo, hi in buckets:
        n = sum(1 for g in gives if lo <= g < hi)
        if n:
            label = f"{lo}~{hi}%" if lo > -100 else f"<{hi}%"
            dist.append({"label": label, "n": n, "pct": round(n / len(gives) * 100, 1)})
    return {
        "n": len(closes),
        "highMed": _median(highs),
        "highAvg": round(sum(highs) / len(highs), 2),
        "closeMed": _median(closes),
        "closeAvg": round(sum(closes) / len(closes), 2),
        "giveMed": _median(gives),
        "giveAvg": round(sum(gives) / len(gives), 2),
        "dist": dist,
    }


def auction_stats(days: dict[str, list[dict]], dates: list[str]) -> list[dict]:
    """次日开盘涨幅分档 → 当日收盘胜率。"""
    buckets = {"< -2%": [], "-2~0%": [], "0~2%": [], "2~5%": [], "> 5%": []}

    def label(open_pct: float) -> str:
        if open_pct < -2:
            return "< -2%"
        if open_pct < 0:
            return "-2~0%"
        if open_pct < 2:
            return "0~2%"
        if open_pct < 5:
            return "2~5%"
        return "> 5%"

    for date in dates:
        if not problib.next_day(dates, date):
            continue
        for ev in days[date]:
            if ev["height"] != 1:
                continue
            bar = kline.bar_after(ev["code"], DATA, date)
            base = kline.close_on(ev["code"], DATA, date)
            if not bar or not base:
                continue
            open_pct = (bar[1] / base - 1) * 100
            close_pct = (bar[4] / base - 1) * 100
            buckets[label(open_pct)].append(close_pct)

    out = []
    for name, rows in buckets.items():
        if not rows:
            continue
        out.append(
            {
                "label": name,
                "n": len(rows),
                "win": round(sum(1 for r in rows if r > 0) / len(rows) * 100, 1),
                "avg": round(sum(rows) / len(rows), 2),
            }
        )
    return out


def high_board_stats(days: dict[str, list[dict]], dates: list[str], threshold: int = 4) -> dict:
    """高标（>=threshold 板）断板后的 5 日跌幅 + 次日炸板率。"""
    drops = []
    gap_total = gap_broken = 0
    for date in dates:
        nd = problib.next_day(dates, date)
        if not nd:
            continue
        next_codes = {e["code"] for e in days[nd]}
        for ev in days[date]:
            if ev["height"] < threshold:
                continue
            bar_after = kline.bar_after(ev["code"], DATA, date)
            base = kline.close_on(ev["code"], DATA, date)
            if not bar_after or not base:
                continue
            # 次日炸板率（用最高价是否触及涨停、收盘是否回落判断）
            if ev["height"] >= 5:
                gap_total += 1
                limit_price = base * (1 + _limit_pct(ev["code"]))
                if bar_after[2] >= limit_price * 0.995 and bar_after[4] < limit_price * 0.995:
                    gap_broken += 1
            # 断板（次日没有晋级）后 5 日跌幅
            if ev["code"] not in next_codes:
                rows = kline.load(ev["code"], DATA)
                idx = next((i for i, r in enumerate(rows) if r[0] == date), None)
                if idx is not None and idx + 5 < len(rows):
                    drops.append((rows[idx + 5][4] / rows[idx][4] - 1) * 100)

    return {
        "threshold": threshold,
        "dropN": len(drops),
        "dropMed": _median(drops),
        "dropAvg": round(sum(drops) / len(drops), 2) if drops else None,
        "dropWin": round(sum(1 for d in drops if d > 0) / len(drops) * 100, 1) if drops else None,
        "gapN": gap_total,
        "gapRate": round(gap_broken / gap_total * 100, 1) if gap_total else None,
    }


def late_stats(days: dict[str, list[dict]], dates: list[str], since: str = "14:30") -> dict:
    """历史上「尾盘（14:30 后）首封」的次日表现。"""
    rets = []
    for date in dates:
        if not problib.next_day(dates, date):
            continue
        for ev in days[date]:
            if ev["height"] != 1:
                continue
            if not (ev.get("time") and ev["time"] >= since):
                continue
            bar = kline.bar_after(ev["code"], DATA, date)
            base = kline.close_on(ev["code"], DATA, date)
            if not bar or not base:
                continue
            rets.append((bar[4] / base - 1) * 100)
    if not rets:
        return {}
    return {
        "n": len(rets),
        "win": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
        "avg": round(sum(rets) / len(rets), 2),
        "since": since,
    }


def late_boards(day: dict | None) -> dict:
    """当日 14:30 后首封的个股 + 该时段的历史次日胜率。"""
    if not day:
        return {}
    items = []
    for row in day.get("rows", []):
        for s in row["stocks"]:
            if s.get("broken"):
                continue
            t = s.get("firstTime") or ""
            if t >= "14:30":
                items.append(
                    {
                        "code": s["code"],
                        "name": s["name"],
                        "height": row["height"],
                        "time": t,
                        "sector": s.get("sector"),
                    }
                )
    items.sort(key=lambda x: x["time"])
    return {"items": items[:12], "n": len(items)}


def theme_leaders(day: dict | None) -> list[dict]:
    """按题材聚组，组内按封单强度/封板时间选龙头。"""
    if not day:
        return []
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in day.get("rows", []):
        for s in row["stocks"]:
            if s.get("broken"):
                continue
            reason = s.get("reason") or ""
            for token in [t.strip() for t in reason.replace("＋", "+").split("+") if len(t.strip()) >= 2]:
                groups[token].append(
                    {
                        "code": s["code"],
                        "name": s["name"],
                        "height": row["height"],
                        "time": s.get("firstTime"),
                        "seal": float(s.get("sealAmount") or 0) / 1e8,
                        "amount": float(s.get("amount") or 0) / 1e8,
                        "oneWord": bool(s.get("oneWord")),
                    }
                )
    rows = []
    for theme, stocks in groups.items():
        if len(stocks) < 2:
            continue
        stocks.sort(key=lambda x: (-x["height"], -x["seal"], x["time"] or "99:99"))
        leader = stocks[0]
        rows.append(
            {
                "theme": theme,
                "count": len(stocks),
                "leader": leader,
                "others": [s["name"] for s in stocks[1:4]],
            }
        )
    rows.sort(key=lambda x: (-x["count"], -x["leader"]["height"]))
    seen: set[str] = set()
    unique = []
    for row in rows:
        code = row["leader"]["code"]
        if code in seen:
            continue
        seen.add(code)
        unique.append(row)
        if len(unique) >= 8:
            break
    return unique


def similar_days(em_days: list[dict]) -> list[dict]:
    """用当日特征找最像的历史交易日，输出它们次日的赚钱效应。"""
    if len(em_days) < 6:
        return []
    feats = []
    for d in em_days:
        st = d["stats"]
        promo = next((p for p in d.get("promotion", []) if p["base"] == 1), None)
        feats.append(
            {
                "date": d["date"],
                "v": [
                    st.get("sealed") or 0,
                    st.get("sealRate") or 0,
                    st.get("maxBoard") or 0,
                    (promo or {}).get("rate") or 0,
                ],
                "nextEffect": (d.get("effect") or {}).get("avg"),
            }
        )
    cols = list(zip(*[f["v"] for f in feats]))
    means = [sum(c) / len(c) for c in cols]
    stds = [math.sqrt(sum((x - m) ** 2 for x in c) / len(c)) or 1 for c, m in zip(cols, means)]
    norm = [[(x - m) / s for x, m, s in zip(f["v"], means, stds)] for f in feats]

    last = len(feats) - 1
    target = norm[last]
    scored = []
    for i, vec in enumerate(norm[:-1]):
        if feats[i]["nextEffect"] is None:
            continue
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(target, vec)))
        scored.append({"date": feats[i]["date"], "dist": round(dist, 2), "next": feats[i]["nextEffect"]})
    scored.sort(key=lambda x: x["dist"])
    top = scored[:3]
    if not top:
        return {}
    return {
        "avgNext": round(sum(r["next"] for r in top) / len(top), 2),
        "items": top,
    }


def fund_streak(data_dir: Path, limit: int = 10) -> dict:
    """连续资金净流入（需要至少 3 天资金流快照）。"""
    path = data_dir / "fundflow-history.json"
    if not path.exists():
        return {"ready": False, "need": 3, "have": 0, "items": []}
    try:
        hist = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"ready": False, "need": 3, "have": 0, "items": []}
    days = sorted(hist.keys())[-3:]
    stock_days: dict[str, list[float]] = defaultdict(list)
    for d in days:
        for row in hist[d].get("stocks", []):
            stock_days[row["name"]].append(row.get("net") or 0)
    items = [
        {"name": name, "days": len(vals), "sum": round(sum(vals), 2)}
        for name, vals in stock_days.items()
        if len(vals) == 3 and all(v > 0 for v in vals)
    ]
    items.sort(key=lambda x: -x["sum"])
    return {"ready": len(days) >= 3, "need": 3, "have": len(days), "items": items[:limit]}


def build() -> dict:
    days = problib.load_events()
    dates = sorted(days)
    latest_payload = None
    try:
        latest_payload = json.loads((DATA / f"{dates[-1]}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        latest_payload = None

    em_days = []
    for path in sorted(DATA.glob("????-??-??.json")):
        try:
            em_days.append(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            continue

    return {
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
        "sell": sell_stats(days, dates),
        "auction": auction_stats(days, dates),
        "highBoard": high_board_stats(days, dates),
        "lateBoards": late_boards(latest_payload),
        "lateStats": late_stats(days, dates),
        "themes": theme_leaders(latest_payload),
        "similar": similar_days(em_days),
        "fundStreak": fund_streak(DATA),
    }


def save(payload: dict) -> Path:
    out = DATA / "signals.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
