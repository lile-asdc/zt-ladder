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


def fetch_minutes(code: str) -> list[list]:
    """腾讯分时：返回 [[时间轴下标, 价格, 成交量(手)], ...]。"""
    symbol = _symbol(code)
    url = "http://web.ifzq.gtimg.cn/appstock/app/minute/query?code=%s" % symbol
    for attempt in range(2):
        try:
            payload = json.loads(em._get(url, "http://gu.qq.com/", retries=2))
        except (em.SourceError, ValueError):
            time.sleep(0.4)
            continue
        node = ((payload.get("data") or {}).get(symbol) or {}).get("data") or {}
        rows = node.get("data") or []
        points = []
        for row in rows:
            parts = row.split()
            if len(parts) < 3 or len(parts[0]) != 4:
                continue
            hhmm = f"{parts[0][:2]}:{parts[0][2:]}"
            idx = TIME_INDEX.get(hhmm)
            if idx is None:
                continue
            try:
                points.append([idx, round(float(parts[1]), 2), int(float(parts[2]))])
            except (TypeError, ValueError):
                continue
        if points:
            return points
    return []


def _minute_index(times: list[str], hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    return TIME_INDEX.get(hhmm)


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
                "amount": round(amount_yi, 2),
                "net": round(net_yi, 2),
                "turnover": turnover,
                "heat": round(heat, 1),
                "reason": s.get("reason") or "",
                "seats": s.get("seats") or {},
            }
        )
    ranked.sort(key=lambda x: -x["heat"])
    hot = ranked[:top]

    codes = [s["code"] for s in hot]
    with ThreadPoolExecutor(max_workers=6) as pool:
        minute_list = list(pool.map(fetch_minutes, codes))

    times = TIMES

    charts = {}
    for stock, points in zip(hot, minute_list):
        if not points:
            continue
        code = stock["code"]
        events = []
        ev = sealed_events.get(code)
        if ev:
            idx = _minute_index(times, ev["first"])
            if idx is not None:
                events.append({"kind": "first", "i": idx, "label": f"首封 {ev['first']}"})
            idx2 = _minute_index(times, ev["last"])
            if idx2 is not None and ev["last"] != ev["first"]:
                events.append({"kind": "last", "i": idx2, "label": f"最后封板 {ev['last']}"})
            if ev["times"]:
                events.append({"kind": "note", "i": -1, "label": f"开板 {ev['times']} 次"})
        elif code in zb_events:
            z = zb_events[code]
            idx = _minute_index(times, z["time"])
            if idx is not None:
                events.append({"kind": "break", "i": idx, "label": f"首触 {z['time']}"})
            events.append({"kind": "note", "i": -1, "label": f"炸板 {z['times'] or 0} 次"})
        charts[code] = {"points": points, "events": events}

    payload = {
        "date": _norm(date),
        "hot": hot,
        "charts": charts,
        "times": [t.split(" ")[-1] for t in times],
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
    }
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
