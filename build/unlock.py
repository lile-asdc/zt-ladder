"""限售解禁日历：未来 30 个自然日的大额解禁。"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import em

BASE = "http://datacenter-web.eastmoney.com/api/data/v1/get"


def fetch(days: int = 30, limit: int = 40) -> list[dict]:
    today = datetime.now(em.CST).date()
    end = today + timedelta(days=days)
    params = {
        "reportName": "RPT_LIFT_STAGE",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,FREE_DATE,LIFT_MARKET_CAP,FREE_SHARES_TYPE,CURRENT_FREE_SHARES",
        "filter": f"(FREE_DATE>='{today}')(FREE_DATE<='{end}')",
        "pageNumber": 1,
        "pageSize": 500,
        "sortColumns": "LIFT_MARKET_CAP",
        "sortTypes": -1,
        "source": "WEB",
        "client": "WEB",
    }
    payload = em._get_json(BASE + "?" + urllib.parse.urlencode(params), "http://data.eastmoney.com/", retries=2)
    rows = ((payload.get("result") or {}).get("data")) or []
    out = []
    seen = {}
    for row in rows:
        code = row.get("SECURITY_CODE")
        if not code:
            continue
        cap = round((row.get("LIFT_MARKET_CAP") or 0) / 1e8, 2)
        date = (row.get("FREE_DATE") or "")[:10]
        item = {
            "date": date,
            "code": code,
            "name": row.get("SECURITY_NAME_ABBR") or code,
            "cap": cap,
            "type": (row.get("FREE_SHARES_TYPE") or "").strip(),
        }
        # 同一只票同一天可能多条，取市值最大的那条
        key = f"{code}-{date}"
        if key not in seen or seen[key]["cap"] < cap:
            seen[key] = item
    out = sorted(seen.values(), key=lambda x: -x["cap"])[:limit]
    return out


def build(data_dir: Path, days: int = 30, limit: int = 40) -> Path | None:
    try:
        items = fetch(days, limit)
    except em.SourceError:
        return None
    payload = {
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
        "days": days,
        "items": items,
    }
    out = data_dir / "unlock.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
