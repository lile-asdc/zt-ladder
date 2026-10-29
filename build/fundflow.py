"""资金流：行业主力净流入 + 个股主力净流入。

东财 push2 的列表接口在部分网络会被直接断连，所以这里做了「抓不到就返回 None」，
前端只在数据存在时渲染对应卡片。CI（境外网络）里通常能通。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import em

CLIST = "http://push2.eastmoney.com/api/qt/clist/get"


def _list(fs: str, fields: str, fid: str, size: int) -> list[dict]:
    url = (
        f"{CLIST}?pn=1&pz={size}&po=1&np=1&fltt=2&invt=2&fid={fid}&fs={fs}&fields={fields}"
    )
    payload = em._get_json(url, "http://quote.eastmoney.com/", retries=2)
    data = payload.get("data") or {}
    return data.get("diff") or []


def fetch_sectors() -> list[dict] | None:
    """行业板块主力净流入（按净额降序）。"""
    try:
        rows = _list("m:90+t:2", "f12,f14,f62,f184", "f62", 40)
    except (em.SourceError, ValueError):
        return None
    out = []
    for row in rows:
        try:
            net = float(row.get("f62") or 0) / 1e8
        except (TypeError, ValueError):
            continue
        out.append({"name": row.get("f14"), "net": round(net, 2)})
    return out or None


def fetch_stocks() -> list[dict] | None:
    """个股主力净流入（沪深，按净额降序取前 20）。"""
    try:
        rows = _list(
            "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "f12,f14,f3,f62,f184",
            "f62",
            20,
        )
    except (em.SourceError, ValueError):
        return None
    out = []
    for row in rows:
        try:
            net = float(row.get("f62") or 0) / 1e8
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "code": row.get("f12"),
                "name": row.get("f14"),
                "pct": row.get("f3"),
                "net": round(net, 2),
            }
        )
    return out or None


def build(data_dir: Path) -> Path | None:
    sectors = fetch_sectors()
    stocks = fetch_stocks()
    if not sectors and not stocks:
        return None
    payload = {
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
        "sectors": sectors or [],
        "stocks": stocks or [],
    }
    out = data_dir / "fundflow.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
