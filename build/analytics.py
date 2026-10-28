"""在天梯数据之上再算一层「复盘指标」：晋级率、板块热度、主线题材、龙头、昨日对比。

所有计算只读本地 data/*.json，不联网，因此可以随时对历史全量重算。
入口：apply_all()，会按日期顺序重写每个日文件并返回索引。
"""

from __future__ import annotations

import json
import re
from collections import Counter

import kline
from pathlib import Path

DAY_GLOB = "????-??-??.json"
STOP_THEMES = {"", "其他", "无", "—"}


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sealed(day: dict) -> list[dict]:
    return [s for row in day["rows"] for s in row["stocks"] if not s.get("broken")]


def _height_map(day: dict) -> dict[str, int]:
    return {s["code"]: row["height"] for row in day["rows"] for s in row["stocks"] if not s.get("broken")}


def promotion(day: dict, prev: dict | None) -> list[dict]:
    """昨日 N 板 → 今日晋级到 N+1 的比例。"""
    if not prev:
        return []
    today_sealed = _height_map(day)
    buckets: dict[int, list[str]] = {}
    for row in prev["rows"]:
        for s in row["stocks"]:
            if s.get("broken"):
                continue
            buckets.setdefault(row["height"], []).append(s["code"])

    out = []
    for base in sorted(buckets):
        codes = buckets[base]
        if not codes:
            continue
        promoted = [c for c in codes if c in today_sealed and today_sealed[c] == base + 1]
        out.append(
            {
                "base": base,
                "total": len(codes),
                "promoted": len(promoted),
                "rate": round(len(promoted) / len(codes) * 100, 1),
            }
        )
    return out


def yesterday_diff(day: dict, prev: dict | None) -> dict:
    if not prev:
        return {"promoted": [], "dropped": [], "fresh": []}

    today_by_code = {
        s["code"]: {"height": row["height"], "broken": s.get("broken"), "pct": s.get("pct"), "name": s["name"]}
        for row in day["rows"]
        for s in row["stocks"]
    }

    promoted, dropped = [], []
    for row in prev["rows"]:
        for s in row["stocks"]:
            if s.get("broken"):
                continue
            today = today_by_code.get(s["code"])
            item = {
                "code": s["code"],
                "name": s["name"],
                "from": row["height"],
                "sector": s.get("sector"),
            }
            if today and not today["broken"] and today["height"] == row["height"] + 1:
                item["to"] = today["height"]
                promoted.append(item)
            else:
                item["pct"] = (today or {}).get("pct")
                dropped.append(item)

    fresh = [
        {"code": s["code"], "name": s["name"], "sector": s.get("sector")}
        for s in _sealed(day)
        if s["boards"] == 1
    ]
    return {
        "promoted": sorted(promoted, key=lambda x: -x["from"]),
        "dropped": sorted(dropped, key=lambda x: (x["pct"] is None, -(x["pct"] or -99))),
        "fresh": fresh,
    }


def sector_heat(day: dict) -> list[dict]:
    agg: dict[str, dict] = {}
    for row in day["rows"]:
        for s in row["stocks"]:
            name = s.get("sector") or "其他"
            item = agg.setdefault(name, {"name": name, "count": 0, "maxBoard": 0, "sealSum": 0.0})
            item["count"] += 1
            item["maxBoard"] = max(item["maxBoard"], row["height"])
            if not s.get("broken"):
                item["sealSum"] += float(s.get("sealAmount") or 0)

    rows = list(agg.values())
    for item in rows:
        item["sealSum"] = round(item["sealSum"] / 1e8, 2)  # 亿元
        item["heat"] = round(item["count"] * 3 + item["maxBoard"] * 2 + item["sealSum"] * 0.6, 1)
    rows.sort(key=lambda x: (-x["heat"], -x["count"]))
    return rows[:8]


def _tokens(reason: str) -> list[str]:
    if not reason:
        return []
    parts = re.split(r"[+＋、,，/｜|]", reason)
    return [p.strip() for p in parts if len(p.strip()) >= 2 and p.strip() not in STOP_THEMES]


def themes(day: dict, limit: int = 8) -> list[dict]:
    counter: Counter[str] = Counter()
    owners: dict[str, list[str]] = {}
    for s in _sealed(day):
        for token in set(_tokens(s.get("reason") or "")):
            counter[token] += 1
            owners.setdefault(token, []).append(s["name"])
    out = []
    for name, count in counter.most_common(limit):
        if count < 2:
            continue
        out.append({"name": name, "count": count, "stocks": owners[name][:12]})
    return out


def leaders(day: dict) -> dict:
    sealed = _sealed(day)
    by_height = sorted(sealed, key=lambda s: (-s["boards"], -(s.get("sealAmount") or 0)))
    by_seal = sorted(sealed, key=lambda s: -(s.get("sealAmount") or 0))
    one_word = [s for s in sealed if s.get("oneWord")]

    def brief(s, extra=None):
        if not s:
            return None
        item = {"code": s["code"], "name": s["name"], "boards": s["boards"], "sector": s.get("sector")}
        if extra:
            item.update(extra(s))
        return item

    # 天梯顶格（可能是炸板），和图上第一行保持一致
    top_row = day["rows"][0] if day.get("rows") else None
    top_stock = top_row["stocks"][0] if top_row and top_row["stocks"] else None
    top = None
    if top_stock:
        top = brief(top_stock)
        top["boards"] = top_row["height"]
        top["broken"] = bool(top_stock.get("broken"))

    return {
        "maxBoard": top,
        "sealKing": brief(by_seal[0], lambda s: {
            "seal": round(float(s.get("sealAmount") or 0) / 1e8, 2),
            "turnover": s.get("turnover"),
        }) if by_seal else None,
        "oneWord": [brief(s) for s in one_word[:3]],
    }


def summary_text(day: dict, promo: list[dict], heat: list[dict], lead: dict) -> str:
    stats = day["stats"]
    bits = []
    top = lead.get("maxBoard")
    if top:
        bits.append(f"最高 {top['boards']} 板 {top['name']}" + ("（炸板）" if top.get("broken") else ""))
    bits.append(f"涨停 {stats['sealed']} 家（首板 {stats['firstBoard']}）")
    if stats.get("sealRate") is not None:
        bits.append(f"封板率 {stats['sealRate']}%")
    if heat:
        bits.append(f"最热板块 {heat[0]['name']}（{heat[0]['count']} 家）")
    p2 = next((p for p in promo if p["base"] == 1), None)
    if p2 and p2["total"]:
        bits.append(f"首板晋级率 {p2['rate']}%")
    king = lead.get("sealKing")
    if king and king.get("seal"):
        bits.append(f"封单王 {king['name']}（{king['seal']} 亿）")
    return "；".join(bits) + "。"



# --------------------------------------------------------------------------- #
# 赚钱效应 / 首板溢价 / 回封 / 市值结构 / 题材迁移
# --------------------------------------------------------------------------- #
def _pct(a: float, b: float) -> float | None:
    if not b:
        return None
    return round((a / b - 1) * 100, 2)


def money_effect(day: dict, prev: dict | None, data_dir: Path) -> dict:
    """昨日涨停股今天的表现：平均涨幅、红盘率、连板率。"""
    if not prev:
        return {}
    target = day["date"]
    today_sealed = {s["code"] for s in _sealed(day)}
    prev_sealed = _sealed(prev)

    pcts = []
    for stock in prev_sealed:
        rows = kline.load(stock["code"], data_dir)
        closes = {r[0]: r[4] for r in rows}
        if target not in closes:
            continue
        idx = next((i for i, r in enumerate(rows) if r[0] == target), None)
        if not idx:
            continue
        p = _pct(closes[target], rows[idx - 1][4])
        if p is not None:
            pcts.append(p)

    if not pcts:
        return {}
    red = sum(1 for p in pcts if p > 0)
    limit_up = sum(1 for s in prev_sealed if s["code"] in today_sealed)
    return {
        "count": len(pcts),
        "avg": round(sum(pcts) / len(pcts), 2),
        "redRate": round(red / len(pcts) * 100, 1),
        "limitRate": round(limit_up / len(prev_sealed) * 100, 1) if prev_sealed else None,
    }


def first_board_premium(day: dict, data_dir: Path) -> dict:
    """今日首板 → 次日开盘/最高/收盘相对今日收盘的溢价。"""
    boards = [s for s in _sealed(day) if s["boards"] == 1]
    opens, highs, closes = [], [], []
    for stock in boards:
        bar = kline.bar_after(stock["code"], data_dir, day["date"])
        if not bar:
            continue
        _, o, h, _, c = bar
        base = kline.close_on(stock["code"], data_dir, day["date"])
        if not base:
            continue
        for bucket, value in ((opens, o), (highs, h), (closes, c)):
            v = _pct(value, base)
            if v is not None:
                bucket.append(v)
    if not closes:
        return {}
    return {
        "count": len(closes),
        "open": round(sum(opens) / len(opens), 2) if opens else None,
        "high": round(sum(highs) / len(highs), 2) if highs else None,
        "close": round(sum(closes) / len(closes), 2),
        "winRate": round(sum(1 for c in closes if c > 0) / len(closes) * 100, 1),
    }


def reseal(day: dict) -> dict:
    """炸板回封率 = 收盘回封的（有过开板但最终封住）/ 当日所有触板股。"""
    zt_broken = [s for s in _sealed(day) if (s.get("brokenTimes") or 0) > 0]
    zb = day.get("zb") or []
    total = len(zt_broken) + len(zb)
    if not total:
        return {}
    return {
        "total": total,
        "resealed": len(zt_broken),
        "rate": round(len(zt_broken) / total * 100, 1),
    }


def cap_dist(day: dict) -> list[dict]:
    buckets = [("<50亿", 0), ("50-100亿", 0), ("100-300亿", 0), (">300亿", 0), ("未知", 0)]
    for s in _sealed(day):
        cap = (s.get("floatCap") or 0) / 1e8
        if not cap:
            buckets[4] = (buckets[4][0], buckets[4][1] + 1)
        elif cap < 50:
            buckets[0] = (buckets[0][0], buckets[0][1] + 1)
        elif cap < 100:
            buckets[1] = (buckets[1][0], buckets[1][1] + 1)
        elif cap < 300:
            buckets[2] = (buckets[2][0], buckets[2][1] + 1)
        else:
            buckets[3] = (buckets[3][0], buckets[3][1] + 1)
    return [{"label": k, "count": v} for k, v in buckets if v]


def word_shift(day: dict, prev: dict | None) -> list[dict]:
    def freq(d):
        counter: Counter[str] = Counter()
        for s in _sealed(d):
            for token in set(_tokens(s.get("reason") or "")):
                counter[token] += 1
        return counter

    today = freq(day)
    before = freq(prev) if prev else Counter()
    names = set(list(today)[:12] + [k for k, _ in before.most_common(6)])
    rows = [
        {"name": n, "today": today.get(n, 0), "prev": before.get(n, 0)}
        for n in names
        if today.get(n, 0) or before.get(n, 0)
    ]
    rows.sort(key=lambda x: (-x["today"], -x["prev"]))
    return rows[:10]


def compute(day: dict, prev: dict | None, data_dir: Path) -> dict:
    promo = promotion(day, prev)
    heat = sector_heat(day)
    diff = yesterday_diff(day, prev)
    lead = leaders(day)
    return {
        "promotion": promo,
        "sectorHeat": heat,
        "themes": themes(day),
        "leaders": lead,
        "yesterdayDiff": diff,
        "summary": summary_text(day, promo, heat, lead),
        "emotion": emotion(day, promo),
        "heightDist": height_dist(day, prev),
        "brokenReview": broken_review(day),
        "strongFirst": strong_first(day),
        "reseal": reseal(day),
        "capDist": cap_dist(day),
        "wordShift": word_shift(day, prev),
        "effect": money_effect(day, prev, data_dir),
        "premium": first_board_premium(day, data_dir),
    }



# --------------------------------------------------------------------------- #
# 情绪 / 结构 / 炸板 / 强首板 / 板块轮动
# --------------------------------------------------------------------------- #
EMOTION_LEVELS = [(30, "冰点"), (45, "低迷"), (60, "修复"), (75, "活跃"), (101, "亢奋")]


def emotion(day: dict, promo: list[dict]) -> dict:
    stats = day["stats"]
    sealed = stats.get("sealed") or 0
    seal = stats.get("sealRate") or 0
    p2 = next((p for p in promo if p["base"] == 1), None)
    promote = p2["rate"] if p2 else 0
    maxb = stats.get("maxBoard") or 1

    c = min(1.0, max(0.0, (sealed - 20) / 80))
    s = min(1.0, seal / 100)
    p = min(1.0, promote / 60)
    h = min(1.0, max(0.0, (maxb - 2) / 6))
    score = round(100 * (0.34 * c + 0.26 * s + 0.25 * p + 0.15 * h))
    label = next(name for limit, name in EMOTION_LEVELS if score < limit)
    return {
        "score": score,
        "label": label,
        "parts": {
            "涨停家数": round(c * 100),
            "封板率": round(s * 100),
            "首板晋级": round(p * 100),
            "高度": round(h * 100),
        },
    }


def height_dist(day: dict, prev: dict | None) -> list[dict]:
    today: dict[int, dict] = {}
    for row in day["rows"]:
        item = today.setdefault(row["height"], {"height": row["height"], "sealed": 0, "broken": 0, "prev": 0})
        for s in row["stocks"]:
            if s.get("broken"):
                item["broken"] += 1
            else:
                item["sealed"] += 1
    if prev:
        for row in prev["rows"]:
            item = today.get(row["height"])
            if item:
                item["prev"] = sum(1 for s in row["stocks"] if not s.get("broken"))
    return [today[h] for h in sorted(today, reverse=True)]


def broken_review(day: dict) -> dict:
    rows = []
    buckets = {"09:30-10:00": 0, "10:00-11:00": 0, "11:00-13:30": 0, "13:30-14:30": 0, "14:30-15:00": 0, "未知": 0}
    entries = day.get("zb") or []
    resealed = 0
    for e in entries:
        if e.get("resealed"):
            resealed += 1
        t = e.get("time") or ""
        rows.append(
            {
                "code": e["code"],
                "name": e["name"],
                "height": e.get("height"),
                "pct": e.get("pct"),
                "time": t,
                "times": e.get("times"),
                "sector": e.get("sector"),
                "resealed": bool(e.get("resealed")),
            }
        )
        if not t:
            buckets["未知"] += 1
        elif t < "10:00":
            buckets["09:30-10:00"] += 1
        elif t < "11:00":
            buckets["10:00-11:00"] += 1
        elif t < "13:30":
            buckets["11:00-13:30"] += 1
        elif t < "14:30":
            buckets["13:30-14:30"] += 1
        else:
            buckets["14:30-15:00"] += 1
    rows.sort(key=lambda x: (x["time"] or "99:99"))
    total = len(rows)
    return {
        "list": rows,
        "buckets": [{"label": k, "count": v} for k, v in buckets.items() if v],
        "sealed": day["stats"]["sealed"],
        "broken": total,
        "resealed": resealed,
        "rate": round(total / (total + day["stats"]["sealed"]) * 100, 1) if (total + day["stats"]["sealed"]) else None,
    }


def _minutes(t: str | None) -> int | None:
    if not t or ":" not in t:
        return None
    h, m = t.split(":")[:2]
    return int(h) * 60 + int(m)


def strong_first(day: dict, limit: int = 10) -> list[dict]:
    out = []
    for s in _sealed(day):
        if s["boards"] != 1:
            continue
        amount = float(s.get("amount") or 0)
        seal = float(s.get("sealAmount") or 0)
        ratio = seal / amount if amount else 0
        minute = _minutes(s.get("firstTime")) or 400
        earliness = max(0.0, 1 - (minute - 570) / 330)  # 9:30 满分，15:00 0 分
        score = (
            48 * min(1.0, ratio / 0.35)
            + 30 * earliness
            + (12 if s.get("oneWord") else 0)
            - 4 * min(3, int(s.get("brokenTimes") or 0))
        )
        out.append(
            {
                "code": s["code"],
                "name": s["name"],
                "sector": s.get("sector"),
                "time": s.get("lastTime") or s.get("firstTime"),
                "sealRatio": round(ratio * 100, 1),
                "seal": round(seal / 1e8, 2),
                "amount": round(amount / 1e8, 2),
                "score": round(max(0, min(100, score))),
            }
        )
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def rotation(days: list[dict], i: int, window: int = 5, top: int = 6) -> list[dict]:
    start = max(0, i - window + 1)
    chunk = days[start : i + 1]
    today_counts: Counter[str] = Counter()
    series: dict[str, list[int]] = {}
    for d in chunk:
        counts = Counter()
        for row in d["rows"]:
            for s in row["stocks"]:
                counts[(s.get("sector") or "其他")] += 1
        for name, n in counts.items():
            series.setdefault(name, []).append(n)
        if d is days[i]:
            today_counts = counts

    rows = []
    for name, values in series.items():
        padded = [0] * (len(chunk) - len(values)) + values
        rows.append({"name": name, "counts": padded[-window:], "total": sum(values), "today": today_counts.get(name, 0)})
    rows.sort(key=lambda x: (-x["today"], -x["total"]))
    return rows[:top]


def apply_all(data_dir: Path) -> int:
    """按日期顺序重算所有日文件里的复盘指标，返回处理天数。"""
    files = sorted(data_dir.glob(DAY_GLOB))
    days: list[tuple[Path, dict]] = []
    for path in files:
        data = _load(path)
        if data:
            days.append((path, data))

    all_codes = [st["code"] for _, d in days for st in _sealed(d)]
    kline.ensure(all_codes, data_dir)

    # 先算出每天的基础指标（依赖前一天）
    computed: list[dict] = []
    for i, (_, day) in enumerate(days):
        prev = days[i - 1][1] if i > 0 else None
        computed.append(compute(day, prev, data_dir))

    # 再补「近 10 日趋势」
    for i, (_, day) in enumerate(days):
        trend = []
        for j in range(max(0, i - 9), i + 1):
            d = days[j][1]
            promo2 = next((p for p in computed[j]["promotion"] if p["base"] == 1), None)
            trend.append(
                {
                    "date": d["date"],
                    "sealRate": d["stats"].get("sealRate"),
                    "promote2": promo2["rate"] if promo2 else None,
                }
            )
        computed[i]["trend"] = trend
        computed[i]["rotation"] = rotation([d for _, d in days], i)
        computed[i]["resealTrend"] = [
            {"date": days[j][1]["date"], "rate": computed[j].get("reseal", {}).get("rate")}
            for j in range(max(0, i - 19), i + 1)
            if computed[j].get("reseal")
        ]
        computed[i]["effectTrend"] = [
            {"date": days[j][1]["date"], "avg": computed[j].get("effect", {}).get("avg")}
            for j in range(max(0, i - 19), i + 1)
            if computed[j].get("effect")
        ]
        computed[i]["emotionTrend"] = [
            {"date": days[j][1]["date"], "score": computed[j]["emotion"]["score"]}
            for j in range(max(0, i - 59), i + 1)
        ]

    for i, (path, day) in enumerate(days):
        day.update(computed[i])
        path.write_text(json.dumps(day, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    _write_stock_index(data_dir, days)
    return len(days)


def _write_stock_index(data_dir: Path, days: list[tuple[Path, dict]]) -> Path:
    """把所有日期的个股记录压成一份索引，供「个股档案」按需读取。"""
    index: dict[str, dict] = {}
    for _, day in days:
        for row in day["rows"]:
            for s in row["stocks"]:
                item = index.setdefault(
                    s["code"], {"name": s["name"], "sector": s.get("sector"), "hits": []}
                )
                item["name"] = s["name"]
                item["sector"] = s.get("sector") or item.get("sector")
                item["hits"].append(
                    [day["date"], row["height"], s.get("pct"), 1 if s.get("broken") else 0]
                )
    out = data_dir / "stocks.json"
    out.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
