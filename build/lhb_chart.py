"""龙虎榜复盘：热度 Top 20 个股的当日分时 + 封板事件。

只使用公开数据：
* 龙虎榜：日级席位买卖（无时间戳）
* 分时：东财 trends2（每分钟收盘价 / 成交量）
* 事件：涨停池的首封 / 最后封板 / 开板次数，炸板池的首触时间
"""

from __future__ import annotations

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import dragon
import em

CHART_NAME = "{date}-chart.json"


def _symbol(code: str) -> str:
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("4", "8", "9")):
        return "bj" + code
    return "sz" + code


def canonical_times() -> list[str]:
    """A 股一天的分时时间轴：09:30-11:30 + 13:00-15:00。"""
    out = []
    for h, m0, m1 in ((9, 30, 60), (10, 0, 60), (11, 0, 30)):
        for m in range(m0, m1):
            out.append(f"{h:02d}:{m:02d}")
    for h, m0, m1 in ((13, 0, 60), (14, 0, 60), (15, 0, 1)):
        for m in range(m0, m1):
            out.append(f"{h:02d}:{m:02d}")
    return out


TIMES = canonical_times()
TIME_INDEX = {t: i for i, t in enumerate(TIMES)}


def _offset(hhmm: str) -> int | None:
    """把 HH:MM 换成「距 9:30 的分钟数」，午休折叠，范围 0-240。"""
    try:
        h, m = hhmm.split(":")[:2]
        mins = int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None
    if mins < 570 or mins > 900:
        return None
    if mins <= 690:  # 11:30 之前
        return mins - 570
    return 120 + (mins - 780)  # 13:00 之后


def fetch_minutes_symbol(symbol: str) -> list[list]:
    """优先腾讯 1 分钟，失败退回新浪 5 分钟。返回 [[offset, price, vol], ...]。"""
    tencent = _fetch_tencent(symbol)
    if tencent:
        return tencent
    return _fetch_sina(symbol)


def _fetch_tencent(symbol: str) -> list[list]:
    url = "http://web.ifzq.gtimg.cn/appstock/app/minute/query?code=%s" % symbol
    try:
        payload = json.loads(em._get(url, "http://gu.qq.com/", retries=1))
    except (em.SourceError, ValueError):
        return []
    rows = ((((payload.get("data") or {}).get(symbol) or {}).get("data") or {}).get("data")) or []
    points = []
    for row in rows:
        parts = row.split()
        if len(parts) < 3 or len(parts[0]) != 4:
            continue
        off = _offset(f"{parts[0][:2]}:{parts[0][2:]}")
        if off is None:
            continue
        try:
            points.append([off, round(float(parts[1]), 2), int(float(parts[2]))])
        except (TypeError, ValueError):
            continue
    return points


def _fetch_sina(symbol: str) -> list[list]:
    import datetime as _dt

    today = _dt.datetime.now(em.CST).strftime("%Y-%m-%d")
    url = (
        "http://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
        "?symbol=%s&scale=5&ma=no&datalen=120" % symbol
    )
    try:
        raw = em._get(url, "http://finance.sina.com.cn/", retries=2)
        rows = json.loads(raw)
    except (em.SourceError, ValueError):
        return []
    points = []
    for row in rows:
        day = row.get("day") or ""
        if not day.startswith(today):
            continue
        off = _offset(day[11:16])
        if off is None:
            continue
        try:
            points.append([off, round(float(row["close"]), 2), int(float(row.get("volume") or 0))])
        except (KeyError, TypeError, ValueError):
            continue
    return points


def fetch_minutes(code: str) -> list[list]:
    return fetch_minutes_symbol(_symbol(code))


def fetch_index_minutes() -> list[list]:
    return fetch_minutes_symbol("sh000001")


def _minute_index(times: list[str], hhmm: str | None) -> int | None:
    return _offset(hhmm) if hhmm else None


def _norm(date: str) -> str:
    return f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 and date.isdigit() else date


def build(date: str, data_dir: Path, top: int = 20) -> Path | None:
    date = _norm(date)
    lhb = dragon.load(date, data_dir)
    if not lhb:
        return None
    day_path = data_dir / f"{date}.json" if "-" in date else data_dir / f"{date[:4]}-{date[4:6]}-{date[6:]}.json"
    if not day_path.exists():
        return None
    day = json.loads(day_path.read_text(encoding="utf-8"))

    boards: dict[str, int] = {}
    sealed_events: dict[str, dict] = {}
    for row in day.get("rows", []):
        for s in row["stocks"]:
            if s.get("broken"):
                continue
            boards[s["code"]] = row["height"]
            sealed_events[s["code"]] = {
                "first": s.get("firstTime"),
                "last": s.get("lastTime"),
                "times": s.get("brokenTimes") or 0,
                "oneWord": bool(s.get("oneWord")),
            }
    zb_events = {
        e["code"]: {"time": e.get("time"), "times": e.get("times"), "height": e.get("height")}
        for e in (day.get("zb") or [])
    }

    ranked = []
    for s in lhb["stocks"]:
        height = boards.get(s["code"]) or (zb_events.get(s["code"]) or {}).get("height") or 0
        amount_yi = (s.get("amount") or 0) / 10000  # 万元 -> 亿元
        net_yi = (s.get("net") or 0) / 10000
        turnover = s.get("turnover") or 0
        heat = (
            30 * min(1.0, height / 5)
            + 25 * min(1.0, amount_yi / 30)
            + 25 * min(1.0, max(0.0, net_yi) / 5)
            + 20 * min(1.0, turnover / 30)
        )
        ranked.append(
            {
                "code": s["code"],
                "name": s["name"],
                "pct": s["pct"],
                "board": height,
                "broken": bool(height and s["code"] in zb_events and s["code"] not in boards),
                "amount": round(amount_yi, 2),
                "net": round(net_yi, 2),
                "turnover": turnover,
                "heat": round(heat, 1),
                "reason": s.get("reason") or "",
                "seats": s.get("seats") or {},
            }
        )
    # 机构 / 北向净买 + 席位集中度（按席位名去重，买卖两侧合并）
    for item in ranked:
        seat_map = item.get("seats") or {}
        merged: dict[str, dict] = {}
        for side in ("b", "s"):
            for row in seat_map.get(side) or []:
                name = row[0]
                slot = merged.setdefault(name, {"buy": 0, "sell": 0, "net": 0, "tag": row[5] if len(row) > 5 else "营业部"})
                slot["buy"] += row[1] or 0
                slot["sell"] += row[2] or 0
                slot["net"] += row[3] or 0
        inst = sum(v["net"] for v in merged.values() if v["tag"] == "机构") / 10000
        north = sum(v["net"] for v in merged.values() if v["tag"] == "北向") / 10000
        buy_total = sum(v["buy"] for v in merged.values())
        top1 = max((v["buy"] for v in merged.values()), default=0)
        item["instNet"] = round(inst, 2)
        item["northNet"] = round(north, 2)
        item["concentration"] = round(min(100.0, top1 / buy_total * 100), 1) if buy_total else None

    ranked.sort(key=lambda x: -x["heat"])
    hot = ranked[:top]

    codes = [s["code"] for s in hot]
    with ThreadPoolExecutor(max_workers=6) as pool:
        minute_list = list(pool.map(fetch_minutes, codes))
        index_points = fetch_index_minutes()


    charts = {}
    for stock, points in zip(hot, minute_list):
        if not points:
            continue
        code = stock["code"]
        events = []
        ev = sealed_events.get(code)
        if ev:
            idx = _offset(ev["first"]) if ev.get("first") else None
            if idx is not None:
                events.append({"kind": "first", "i": idx, "label": f"首封 {ev['first']}"})
            idx2 = _offset(ev["last"]) if ev.get("last") else None
            if idx2 is not None and ev["last"] != ev["first"]:
                events.append({"kind": "last", "i": idx2, "label": f"最后封板 {ev['last']}"})
            if ev["times"]:
                events.append({"kind": "note", "i": -1, "label": f"开板 {ev['times']} 次"})
        elif code in zb_events:
            z = zb_events[code]
            idx = _offset(z["time"]) if z.get("time") else None
            if idx is not None:
                events.append({"kind": "break", "i": idx, "label": f"首触 {z['time']}"})
            events.append({"kind": "note", "i": -1, "label": f"炸板 {z['times'] or 0} 次"})
        vols = sorted(p[2] for p in points)
        median = vols[len(vols) // 2] if vols else 0
        spikes = [
            {"i": p[0], "v": p[2]}
            for p in points
            if median and p[2] > median * 3
        ][:6]
        charts[code] = {"points": points, "events": events, "spikes": spikes}

    payload = {
        "date": _norm(date),
        "hot": hot,
        "charts": charts,
        "index": index_points,
        "summary": _summary(lhb, hot),
        "streak": _streak(_norm(date), data_dir),
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
    }
    lhb["hot"] = hot
    (data_dir / dragon.LHB_DIR / f"{_norm(date)}.json").write_text(
        json.dumps(lhb, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    out = data_dir / dragon.LHB_DIR / CHART_NAME.format(date=_norm(date))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out


def load(date: str, data_dir: Path) -> dict | None:
    path = data_dir / dragon.LHB_DIR / CHART_NAME.format(date=_norm(date))
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None

def _summary(lhb: dict, hot: list[dict]) -> dict:
    stocks = lhb.get("stocks") or []
    inst = sum((s.get("instNet") or 0) for s in hot)
    north = sum((s.get("northNet") or 0) for s in hot)
    net_total = sum((s.get("net") or 0) for s in stocks) / 10000

    seat_counter: dict[str, dict] = {}
    for s in stocks:
        for side in ("b", "s"):
            for row in (s.get("seats") or {}).get(side) or []:
                name = row[0]
                tag = row[5] if len(row) > 5 else "营业部"
                slot = seat_counter.setdefault(name, {"name": name, "tag": tag, "n": 0, "net": 0})
                slot["n"] += 1
                slot["net"] += row[3] or 0
    top_seat = max(seat_counter.values(), key=lambda x: x["n"], default=None)

    parts = [f"{lhb['date']} 龙虎榜 {len(stocks)} 家，净买入合计 {net_total:+.2f} 亿"]
    if hot:
        best = max(hot, key=lambda x: x.get("instNet") or -99)
        if best.get("instNet"):
            parts.append(f"机构净买最多 {best['name']} {best['instNet']:+.2f} 亿")
        n_best = max(hot, key=lambda x: x.get("northNet") or -99)
        if n_best.get("northNet"):
            parts.append(f"北向净买最多 {n_best['name']} {n_best['northNet']:+.2f} 亿")
    if top_seat:
        parts.append(f"最活跃席位 {top_seat['name'][:14]}（上榜 {top_seat['n']} 次）")
    text = "；".join(parts) + "。"

    return {
        "text": text,
        "netTotal": round(net_total, 2),
        "instNet": round(inst, 2),
        "northNet": round(north, 2),
        "topSeat": top_seat,
    }


def _streak(date: str, data_dir: Path, limit: int = 10) -> list[dict]:
    """连续上榜天数（含今天）。"""
    days: list[dict] = []
    cursor = date
    for _ in range(30):
        payload = dragon.load(cursor, data_dir)
        if not payload:
            break
        days.append(payload)
        prev = _prev_day(cursor)
        if not prev:
            break
        cursor = prev
    if len(days) < 2:
        return []

    today = {s["code"]: s for s in days[0].get("stocks") or []}
    out = []
    for code, stock in today.items():
        n = 1
        for day in days[1:]:
            if any(s["code"] == code for s in day.get("stocks") or []):
                n += 1
            else:
                break
        if n >= 2:
            out.append({"code": code, "name": stock["name"], "days": n, "net": round((stock.get("net") or 0) / 10000, 2)})
    out.sort(key=lambda x: (-x["days"], -x["net"]))
    return out[:limit]


def _prev_day(date: str) -> str | None:
    from datetime import datetime, timedelta

    cur = datetime.strptime(date, "%Y-%m-%d")
    for i in range(1, 8):
        cand = (cur - timedelta(days=i)).strftime("%Y-%m-%d")
        return cand
    return None
