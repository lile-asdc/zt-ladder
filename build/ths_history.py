"""补充历史样本：从同花顺拉更早的涨停池（东财只保留约 20 个交易日）。

产物：public/data/extra/{date}.json
[{code, name, height, time, type, reason}]
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import em

OUT = Path(__file__).resolve().parent.parent / "public" / "data" / "extra"


def _height(high_days: str | None) -> int:
    if not high_days:
        return 1
    text = str(high_days)
    if "首板" in text:
        return 1
    m = re.search(r"(\d+)\s*天\s*(\d+)\s*板", text)
    if m:
        return int(m.group(2))
    m = re.search(r"(\d+)\s*板", text)
    if m:
        return int(m.group(1))
    return 1


def _hhmm(ts) -> str | None:
    try:
        n = int(ts)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(n, em.CST).strftime("%H:%M")


def fetch_day(date: str) -> list[dict] | None:
    url = (
        "http://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
        "?page=1&limit=200&field=199112,10,9001,330323,330324,330325,9002,330329,9004,9003,9005"
        "&filter=HS,GEM2STAR&order_field=330324&order_type=0&date=%s&_=%d" % (date, int(time.time() * 1000))
    )
    try:
        payload = em._get_json(url, em.THS_REF)
    except em.SourceError:
        return None
    info = ((payload.get("data") or {}).get("info")) or []
    if not info:
        return None
    rows = []
    for item in info:
        code = item.get("code")
        if not code:
            continue
        rows.append(
            {
                "code": code,
                "name": item.get("name"),
                "height": _height(item.get("high_days")),
                "time": _hhmm(item.get("first_limit_up_time")),
                "type": (item.get("limit_up_type") or "").strip(),
                "reason": (item.get("reason_type") or "").strip(),
            }
        )
    return rows


def main(days: int = 60) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.now(em.CST).date()
    made = skipped = 0
    for i in range(days):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        date = d.strftime("%Y%m%d")
        path = OUT / f"{date}.json"
        if path.exists():
            continue
        rows = fetch_day(date)
        if not rows:
            skipped += 1
            time.sleep(0.4)
            continue
        path.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        made += 1
        print(f"[ok] {date} {len(rows)}")
        time.sleep(0.35)
    print(f"done: +{made}, skipped {skipped}")


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 60))
