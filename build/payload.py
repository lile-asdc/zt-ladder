"""把各数据源拼成一份可直接给前端/长图用的「连板天梯」日数据。"""

from __future__ import annotations

import json
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

import em

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
DATA_DIR = PUBLIC / "data"

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DISCLAIMER = "内容来自网络整理，不做任何投资建议"
MAX_SECTOR_CHIPS = 7


def weekday_cn(date: str) -> str:
    d = datetime.strptime(date, "%Y%m%d")
    return WEEKDAYS[d.weekday()]


def label_cn(date: str) -> str:
    d = datetime.strptime(date, "%Y%m%d")
    return f"{d.month}月{d.day}日"


def _sort_key_sealed(stock: dict):
    return (stock.get("lastTime") or "99:99", stock.get("code") or "")


def _sort_key_broken(stock: dict):
    return (stock.get("firstTime") or "99:99", stock.get("code") or "")


def build_day(date: str, *, with_breadth: bool = True) -> dict:
    sealed = em.fetch_zt_pool(date)
    broken_raw = em.fetch_zb_pool(date)
    reasons = em.fetch_ths_reasons(date)
    prev_date, prev_pool = em.prev_pool(date)

    zb_time = {s["code"]: s["firstTime"] for s in broken_raw}

    # 「昨日连板数 >= 2」的个股，今天没封住 → 进天梯但不带涨停标记（灰色划线）
    prev_by_code = {s["code"]: s for s in prev_pool}
    sealed_codes = {s["code"] for s in sealed}
    gray_codes = [
        code
        for code, stock in prev_by_code.items()
        if stock["boards"] >= 2 and code not in sealed_codes
    ]
    quotes = {}
    if gray_codes:
        if date == datetime.now(em.CST).strftime("%Y%m%d"):
            quotes = em.fetch_quotes(gray_codes)
        else:
            quotes = em.fetch_quotes_hist(gray_codes, date)
    broken: list[dict] = []
    for code in gray_codes:
        prev = prev_by_code[code]
        quote = quotes.get(code) or {}
        pct = quote.get("pct")
        broken.append(
            {
                "code": code,
                "name": prev["name"],
                "market": prev["market"],
                "price": quote.get("price"),
                "pct": round(float(pct), 2) if isinstance(pct, (int, float)) else None,
                "amount": quote.get("amount"),
                "floatCap": quote.get("floatCap"),
                "totalCap": quote.get("totalCap"),
                "turnover": quote.get("turnover"),
                "boards": prev["boards"] + 1,
                "firstTime": zb_time.get(code),
                "lastTime": None,
                "sealAmount": None,
                "brokenTimes": 0,
                "sector": prev["sector"],
                "stat": {"days": prev["boards"] + 1, "ct": prev["boards"]},
                "oneWord": False,
                "broken": True,
                "reason": "",
                "prevBoards": prev["boards"],
            }
        )

    for stock in sealed:
        info = reasons.get(stock["code"]) or {}
        stock["reason"] = info.get("reason") or ""
        if info.get("type") == "一字板":
            stock["oneWord"] = True
        elif info.get("type") == "T字板":
            stock["oneWord"] = False

    today = datetime.now(em.CST).strftime("%Y%m%d")
    if date == today:
        index = em.fetch_index_rt()
        breadth = em.fetch_breadth() if with_breadth else None
    else:
        index = em.fetch_index_hist(date)
        breadth = None
    if index and not index.get("name"):
        index["name"] = "上证指数"

    # 按高度分组
    buckets: dict[int, list[dict]] = {}
    for stock in sealed:
        buckets.setdefault(stock["boards"], []).append(stock)
    for stock in broken:
        buckets.setdefault(stock["boards"], []).append(stock)

    rows = []
    for height in sorted(buckets, reverse=True):
        group = buckets[height]
        up = sorted([s for s in group if not s["broken"]], key=_sort_key_sealed)
        down = sorted([s for s in group if s["broken"]], key=_sort_key_broken)
        rows.append({"height": height, "stocks": up + down})

    # 板块分布（含炸板，与参考图口径一致）
    order = []
    for row in rows:
        for stock in row["stocks"]:
            name = stock["sector"] or "其他"
            if name not in order:
                order.append(name)
    counts = Counter((s["sector"] or "其他") for r in rows for s in r["stocks"])
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], order.index(kv[0])))
    chips = [{"name": n, "count": c} for n, c in ranked[:MAX_SECTOR_CHIPS]]
    other = sum(c for _, c in ranked[MAX_SECTOR_CHIPS:])
    if other:
        chips.append({"name": "其他", "count": other})

    total = sum(len(r["stocks"]) for r in rows)
    first_board = sum(1 for r in rows if r["height"] == 1 for _ in r["stocks"])
    max_board = max((r["height"] for r in rows), default=0)

    return {
        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        "dateParam": date,
        "label": label_cn(date),
        "weekday": weekday_cn(date),
        "index": index,
        "breadth": breadth,
        "stats": {
            "sealed": len(sealed),
            "broken": len(broken),
            "total": total,
            "firstBoard": first_board,
            "maxBoard": max_board,
            "sealRate": round(len(sealed) / (len(sealed) + len(broken_raw)) * 100, 1)
            if sealed or broken_raw
            else None,
        },
        "sectors": chips,
        "rows": rows,
        "prevDate": f"{prev_date[:4]}-{prev_date[4:6]}-{prev_date[6:]}" if prev_date else None,
        "disclaimer": DISCLAIMER,
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
    }


def save_day(payload: dict) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{payload['date']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def _day_meta(payload: dict) -> dict:
    return {
        "date": payload["date"],
        "label": payload["label"],
        "weekday": payload["weekday"],
        "maxBoard": payload["stats"]["maxBoard"],
        "sealed": payload["stats"]["sealed"],
        "broken": payload["stats"]["broken"],
        "total": payload["stats"]["total"],
        "sectors": [c["name"] for c in payload["sectors"][:3]],
    }


def rebuild_index() -> Path:
    days = []
    for path in sorted(DATA_DIR.glob("????-??-??.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        days.append(_day_meta(payload))
    days.sort(key=lambda d: d["date"], reverse=True)
    index = {
        "generatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
        "latest": days[0]["date"] if days else None,
        "days": days,
    }
    out = DATA_DIR / "index.json"
    out.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
