"""在天梯数据之上再算一层「复盘指标」：晋级率、板块热度、主线题材、龙头、昨日对比。

所有计算只读本地 data/*.json，不联网，因此可以随时对历史全量重算。
入口：apply_all()，会按日期顺序重写每个日文件并返回索引。
"""

from __future__ import annotations

import json
import re
from collections import Counter
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

    return {
        "maxBoard": brief(by_height[0]) if by_height else None,
        "sealKing": brief(by_seal[0], lambda s: {"seal": round(float(s.get("sealAmount") or 0) / 1e8, 2)}) if by_seal else None,
        "oneWord": [brief(s) for s in one_word[:3]],
    }


def summary_text(day: dict, promo: list[dict], heat: list[dict], lead: dict) -> str:
    stats = day["stats"]
    bits = []
    top = lead.get("maxBoard")
    if top:
        bits.append(f"最高 {top['boards']} 板 {top['name']}")
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


def compute(day: dict, prev: dict | None) -> dict:
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
    }


def apply_all(data_dir: Path) -> int:
    """按日期顺序重算所有日文件里的复盘指标，返回处理天数。"""
    files = sorted(data_dir.glob(DAY_GLOB))
    days: list[tuple[Path, dict]] = []
    for path in files:
        data = _load(path)
        if data:
            days.append((path, data))

    # 先算出每天的基础指标（依赖前一天）
    computed: list[dict] = []
    for i, (_, day) in enumerate(days):
        prev = days[i - 1][1] if i > 0 else None
        computed.append(compute(day, prev))

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

    for i, (path, day) in enumerate(days):
        day.update(computed[i])
        path.write_text(json.dumps(day, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(days)
