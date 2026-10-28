"""龙虎榜：每日上榜个股 + 买卖席位明细。

数据源：东方财富 datacenter（http 可用）。
落盘结构（体积友好，金额统一「万元」整数）：
{
  "date": "2026-10-28",
  "stocks": [{
      "code","name","pct","close","net","buy","sell","deal","amount","turnover","reason","explain",
      "seats": {"b": [[name, buy, sell, net], ...], "s": [[name, buy, sell, net], ...]}
  }],
  "updatedAt": "..."
}
"""

from __future__ import annotations

import json
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import em

BASE = "http://datacenter-web.eastmoney.com/api/data/v1/get"
REF = "http://data.eastmoney.com/"
LHB_DIR = "lhb"


def _get(params: dict) -> dict:
    url = BASE + "?" + urllib.parse.urlencode(params)
    payload = em._get_json(url, REF, retries=2)
    return payload.get("result") or {}


def _wan(value) -> int | None:
    try:
        return int(round(float(value) / 1e4))
    except (TypeError, ValueError):
        return None


def fetch_list(date: str) -> list[dict]:
    """当日龙虎榜个股（按净买入降序）。"""
    target = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    params = {
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "ALL",
        "filter": f"(TRADE_DATE='{target}')",
        "pageNumber": 1,
        "pageSize": 500,
        "sortColumns": "BILLBOARD_NET_AMT",
        "sortTypes": -1,
        "source": "WEB",
        "client": "WEB",
    }
    rows = _get(params).get("data") or []
    out = []
    seen: dict[str, dict] = {}
    for row in rows:
        code = row.get("SECURITY_CODE")
        if not code:
            continue
        item = (
            {
                "code": code,
                "name": row.get("SECURITY_NAME_ABBR"),
                "pct": round(float(row.get("CHANGE_RATE") or 0), 2),
                "close": row.get("CLOSE_PRICE"),
                "net": _wan(row.get("BILLBOARD_NET_AMT")),
                "buy": _wan(row.get("BILLBOARD_BUY_AMT")),
                "sell": _wan(row.get("BILLBOARD_SELL_AMT")),
                "deal": _wan(row.get("BILLBOARD_DEAL_AMT")),
                "amount": _wan(row.get("ACCUM_AMOUNT")),
                "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
                "reason": (row.get("EXPLANATION") or "").strip(),
                "explain": (row.get("EXPLAIN") or "").strip(),
            }
        )
        if code in seen:
            prev = seen[code]
            if item["reason"] and item["reason"] not in prev["reason"]:
                prev["reason"] = (prev["reason"] + " / " + item["reason"]).strip(" /")
            continue
        seen[code] = item
        out.append(item)
    return out


def fetch_seats(date: str, code: str) -> dict:
    target = f"{date[:4]}-{date[4:6]}-{date[6:]}"

    def side(report: str, sort_col: str = "BUY") -> list[list]:
        params = {
            "reportName": report,
            "columns": "ALL",
            "filter": f"(TRADE_DATE='{target}')(SECURITY_CODE=\"{code}\")",
            "pageNumber": 1,
            "pageSize": 5,
            "sortColumns": sort_col,
            "sortTypes": -1,
            "source": "WEB",
            "client": "WEB",
        }
        try:
            rows = _get(params).get("data") or []
        except em.SourceError:
            return []
        return [
            [
                (r.get("OPERATEDEPT_NAME") or "").strip(),
                _wan(r.get("BUY")),
                _wan(r.get("SELL")),
                _wan(r.get("NET")),
            ]
            for r in rows
        ]

    return {
        "b": side("RPT_BILLBOARD_DAILYDETAILSBUY", "BUY"),
        "s": side("RPT_BILLBOARD_DAILYDETAILSSELL", "SELL"),
    }


def build(date: str) -> dict | None:
    stocks = fetch_list(date)
    if not stocks:
        return None
    codes = [s["code"] for s in stocks]
    with ThreadPoolExecutor(max_workers=6) as pool:
        seats = list(pool.map(lambda c: fetch_seats(date, c), codes))
    for stock, seat in zip(stocks, seats):
        stock["seats"] = seat
    return {
        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        "stocks": stocks,
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
    }


def save(payload: dict, data_dir: Path) -> Path:
    out_dir = data_dir / LHB_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{payload['date']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def load(date: str, data_dir: Path) -> dict | None:
    path = data_dir / LHB_DIR / f"{date}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def build_and_save(date: str, data_dir: Path, retries: int = 2) -> Path | None:
    for attempt in range(retries):
        try:
            payload = build(date)
        except em.SourceError:
            payload = None
        if payload:
            return save(payload, data_dir)
        time.sleep(1.5)
    return None
