"""概率统计：把「历史同类样本」的胜率算清楚，而不是拍脑袋给预测。

样本来源：
* public/data/*.json          东财日数据（字段全，17 天）
* public/data/extra/*.json    同花顺历史涨停池（字段少，可回溯 ~60 天）
* .cache/kline/*.json         个股日 K（算次日表现）

产物：public/data/prob.json
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import em
import kline

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "public" / "data"
EXTRA = DATA / "extra"

TIME_BUCKETS = [("09:25-10:00", "09:25", "10:00"), ("10:00-11:30", "10:00", "11:30"),
                ("13:00-14:00", "13:00", "14:00"), ("14:00-15:00", "14:00", "15:01")]


def _bucket(time_str: str | None) -> str | None:
    if not time_str or ":" not in time_str:
        return None
    for label, lo, hi in TIME_BUCKETS:
        if lo <= time_str < hi:
            return label
    return None


def load_events() -> dict[str, list[dict]]:
    """{date: [{code,name,height,time,type,reason,oneWord}]}"""
    days: dict[str, list[dict]] = {}
    for path in sorted(DATA.glob("????-??-??.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        rows = []
        for row in payload.get("rows", []):
            for s in row["stocks"]:
                if s.get("broken"):
                    continue
                rows.append(
                    {
                        "code": s["code"],
                        "name": s["name"],
                        "height": row["height"],
                        "time": s.get("firstTime"),
                        "type": "一字板" if s.get("oneWord") else "",
                        "reason": s.get("reason") or "",
                        "oneWord": bool(s.get("oneWord")),
                        "source": "em",
                    }
                )
        days[payload["date"]] = rows

    for path in sorted(EXTRA.glob("*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        date = f"{path.stem[:4]}-{path.stem[4:6]}-{path.stem[6:]}"
        if date in days:
            continue
        days[date] = [
            {
                "code": r["code"],
                "name": r.get("name"),
                "height": r.get("height") or 1,
                "time": r.get("time"),
                "type": r.get("type") or "",
                "reason": r.get("reason") or "",
                "oneWord": (r.get("type") or "") == "一字板",
                "source": "ths",
            }
            for r in rows
        ]
    return days


def next_day(dates: list[str], date: str) -> str | None:
    try:
        i = dates.index(date)
    except ValueError:
        return None
    return dates[i + 1] if i + 1 < len(dates) else None


def build() -> dict:
    days = load_events()
    dates = sorted(days)
    all_codes = [e["code"] for d in dates for e in days[d]]
    kline.ensure(all_codes, DATA, workers=8)

    # ---- 首板分层：次日涨幅 ----
    buckets: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "win": 0, "sum": 0.0})
    # ---- 晋级概率 ----
    promo: dict[int, dict] = defaultdict(lambda: {"n": 0, "next": 0})
    with_next = 0
    day_feat: dict[str, dict] = {
        d: {
            "count": len(days[d]),
            "maxH": max((e["height"] for e in days[d]), default=0),
            "multi": (sum(1 for e in days[d] if e["height"] >= 2) / len(days[d])) if days[d] else 0,
            "nextEffect": None,
        }
        for d in dates
    }

    for date in dates:
        nd = next_day(dates, date)
        if not nd:
            continue
        next_codes = {e["code"]: e["height"] for e in days[nd]}
        today_first_rets: list[float] = []
        heights = [e["height"] for e in days[date]]
        for ev in days[date]:
            code = ev["code"]
            h = ev["height"]
            promo[h]["n"] += 1
            if next_codes.get(code) == h + 1:
                promo[h]["next"] += 1

            if h != 1:
                continue
            bar = kline.bar_after(code, DATA, date)
            base = kline.close_on(code, DATA, date)
            if not bar or not base:
                continue
            pct = (bar[4] / base - 1) * 100
            with_next += 1
            today_first_rets.append(pct)
            key = (_bucket(ev["time"]), bool(ev["oneWord"]))
            slot = buckets[key]
            slot["n"] += 1
            slot["sum"] += pct
            if pct > 0:
                slot["win"] += 1

        if today_first_rets:
            day_feat[date]["nextEffect"] = round(sum(today_first_rets) / len(today_first_rets), 2)

    first_board = []
    for (bucket, oneword), slot in sorted(buckets.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        if not slot["n"]:
            continue
        first_board.append(
            {
                "bucket": bucket or "未知",
                "oneWord": oneword,
                "n": slot["n"],
                "win": round(slot["win"] / slot["n"] * 100, 1),
                "avg": round(slot["sum"] / slot["n"], 2),
            }
        )

    promotion = [
        {"base": h, "n": v["n"], "next": v["next"], "rate": round(v["next"] / v["n"] * 100, 1)}
        for h, v in sorted(promo.items())
        if v["n"] >= 3 and h <= 8
    ]

    # ---- 简单回测：按日等权持有首板股，次日收盘卖出 ----
    strategies = {
        "一字首板": lambda ev: ev["oneWord"],
        "早盘首板": lambda ev: (not ev["oneWord"]) and (ev["time"] or "99:99") <= "10:00",
        "全部首板": lambda ev: True,
    }
    backtest = []
    for name, pick in strategies.items():
        curve = []
        for date in dates:
            nd = next_day(dates, date)
            if not nd:
                continue
            rets = []
            for ev in days[date]:
                if ev["height"] != 1 or not pick(ev):
                    continue
                bar = kline.bar_after(ev["code"], DATA, date)
                base = kline.close_on(ev["code"], DATA, date)
                if not bar or not base:
                    continue
                rets.append((bar[4] / base - 1) * 100)
            if rets:
                curve.append({"date": date, "ret": round(sum(rets) / len(rets), 2), "n": len(rets)})
        if not curve:
            continue
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for point in curve:
            equity += point["ret"]
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        backtest.append(
            {
                "name": name,
                "curve": curve[-60:],
                "total": round(equity, 1),
                "avgDay": round(equity / len(curve), 2),
                "win": round(sum(1 for c in curve if c["ret"] > 0) / len(curve) * 100, 1),
                "maxDD": round(max_dd, 1),
                "days": len(curve),
            }
        )

    # ---- 板块延续（用代码→行业映射，覆盖全部历史日）----
    em_days = [d for d in dates if any(e["source"] == "em" for e in days[d])]
    sector_map: dict[str, str] = {}
    stocks_json = DATA / "stocks.json"
    if stocks_json.exists():
        try:
            for code, meta in json.loads(stocks_json.read_text(encoding="utf-8")).items():
                if meta.get("sector"):
                    sector_map[code] = meta["sector"]
        except ValueError:
            pass
    for d in dates:
        try:
            payload = json.loads((DATA / f"{d}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in payload.get("rows", []):
            for st in row["stocks"]:
                if st.get("sector"):
                    sector_map.setdefault(st["code"], st["sector"])

    daily_sectors: dict[str, set[str]] = {}
    for d in dates:
        counts: dict[str, int] = defaultdict(int)
        for ev in days[d]:
            sector = sector_map.get(ev["code"])
            if sector:
                counts[sector] += 1
        daily_sectors[d] = {k for k, v in counts.items() if v >= 3}

    sector_stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "hit": 0})
    for i, date in enumerate(dates[:-1]):
        nxt = daily_sectors.get(dates[i + 1], set())
        for name in daily_sectors.get(date, set()):
            if name in ("其他", "未知"):
                continue
            slot = sector_stats[name]
            slot["n"] += 1
            if name in nxt:
                slot["hit"] += 1
    sector_cont = [
        {"name": k, "n": v["n"], "hit": v["hit"], "rate": round(v["hit"] / v["n"] * 100, 1)}
        for k, v in sorted(sector_stats.items(), key=lambda kv: -kv[1]["n"])
        if v["n"] >= 5
    ]

    # ---- 情绪分位（用全量 198 天，而非只有东财的 17 天）----
    def pct_rank(values: dict[str, float], v: float) -> float:
        vals = sorted(values.values())
        if not vals:
            return 0.0
        lo = sum(1 for x in vals if x < v)
        return lo / len(vals)

    counts = {d: f["count"] for d, f in day_feat.items()}
    maxhs = {d: f["maxH"] for d, f in day_feat.items()}
    multis = {d: f["multi"] for d, f in day_feat.items()}

    scored = []
    for d, f in day_feat.items():
        if f["nextEffect"] is None:
            continue
        score = 100 * (
            0.45 * pct_rank(counts, f["count"])
            + 0.25 * pct_rank(maxhs, f["maxH"])
            + 0.30 * pct_rank(multis, f["multi"])
        )
        scored.append((score, f["nextEffect"], d))

    tiers = []
    for lo, hi, label in ((0, 25, "0-25 冰点"), (25, 50, "25-50 低迷"), (50, 75, "50-75 修复"), (75, 101, "75-100 亢奋")):
        sel = [x[1] for x in scored if lo <= x[0] < hi]
        if sel:
            tiers.append(
                {
                    "label": label,
                    "n": len(sel),
                    "avg": round(sum(sel) / len(sel), 2),
                    "win": round(sum(1 for x in sel if x > 0) / len(sel) * 100, 1),
                }
            )
    today_score = None
    if dates:
        last = dates[-1]
        f = day_feat.get(last)
        if f:
            today_score = round(
                100
                * (
                    0.45 * pct_rank(counts, f["count"])
                    + 0.25 * pct_rank(maxhs, f["maxH"])
                    + 0.30 * pct_rank(multis, f["multi"])
                ),
                1,
            )

    # ---- 今日观察池 ----
    watchlist = []
    latest = dates[-1]
    latest_payload = None
    try:
        latest_payload = json.loads((DATA / f"{latest}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        latest_payload = None
    if latest_payload:
        heat = {c["name"]: c["count"] for c in latest_payload.get("sectors", [])}
        for row in latest_payload.get("rows", []):
            for s in row["stocks"]:
                if s.get("broken"):
                    continue
                if row["height"] > 3:
                    continue
                base = {
                    "code": s["code"],
                    "name": s["name"],
                    "height": row["height"],
                    "time": s.get("firstTime"),
                    "sector": s.get("sector"),
                    "oneWord": bool(s.get("oneWord")),
                }
                score = 0
                reasons = []
                if base["oneWord"]:
                    score += 25
                    reasons.append("一字板")
                if base["time"] and base["time"] <= "10:00":
                    score += 20
                    reasons.append("早盘封板")
                seal = float(s.get("sealAmount") or 0)
                amount = float(s.get("amount") or 0)
                if amount and seal / amount > 0.15:
                    score += 20
                    reasons.append("封单强")
                if (heat.get(s.get("sector")) or 0) >= 3:
                    score += 15
                    reasons.append("板块成团")
                if row["height"] >= 2:
                    score += 10
                    reasons.append(f"{row['height']}板")
                if score <= 0:
                    continue
                hist_win, hist_n, hist_kind = None, 0, "胜率"
                if row["height"] == 1:
                    bucket_row = next(
                        (b for b in first_board if b["bucket"] == _bucket(base["time"]) and b["oneWord"] == base["oneWord"]),
                        None,
                    )
                    if bucket_row:
                        hist_win, hist_n = bucket_row["win"], bucket_row["n"]
                else:
                    promo_row = next((x for x in promotion if x["base"] == row["height"]), None)
                    if promo_row:
                        hist_win, hist_n, hist_kind = promo_row["rate"], promo_row["n"], "晋级率"
                base.update(
                    {"score": score, "reasons": reasons, "histWin": hist_win, "histN": hist_n, "histKind": hist_kind}
                )
                watchlist.append(base)
        watchlist.sort(key=lambda x: (-x["score"], x["time"] or "99:99"))
        watchlist = watchlist[:10]

    return {
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
        "samples": {
            "days": len(dates),
            "events": sum(len(v) for v in days.values()),
            "withNext": with_next,
        },
        "firstBoard": first_board,
        "promotion": promotion,
        "sectorCont": sector_cont,
        "emotionTier": tiers,
        "emotionToday": today_score,
        "watchlist": watchlist,
        "backtest": backtest,
        "range": {"from": dates[0], "to": dates[-1]},
    }


def save(payload: dict) -> Path:
    out = DATA / "prob.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
