"""限售解禁日历（新浪财经，解禁市值直接给「亿元」，比东财那个字段靠谱）。"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import em

BASE = "http://vip.stock.finance.sina.com.cn/q/go.php/vInvestConsult/kind/xsjj/index.phtml?p={page}"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


def _fetch_page(page: int) -> list[dict]:
    req = urllib.request.Request(
        BASE.format(page=page),
        headers={"User-Agent": UA, "Referer": "http://finance.sina.com.cn/"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("gbk", "replace")

    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) < 5 or not re.fullmatch(r"\d{6}", cells[0]):
            continue
        code, name, date, shares, cap = cells[0], cells[1], cells[2], cells[3], cells[4]
        try:
            cap_yi = float(cap.replace(",", ""))
        except ValueError:
            cap_yi = 0.0
        try:
            shares_wan = float(shares.replace(",", ""))
        except ValueError:
            shares_wan = 0.0
        rows.append({"date": date, "code": code, "name": name, "shares": shares_wan, "cap": round(cap_yi, 2)})
    return rows


def fetch(days: int = 45, limit: int = 40) -> list[dict]:
    today = datetime.now(em.CST).date()
    end = today + timedelta(days=days)

    seen: dict[str, dict] = {}
    for page in range(1, 8):
        try:
            rows = _fetch_page(page)
        except Exception:  # noqa: BLE001 - 单页失败就停
            break
        if not rows:
            break
        oldest = None
        for row in rows:
            try:
                d = datetime.strptime(row["date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            oldest = d if oldest is None else min(oldest, d)
            if today <= d <= end:
                key = f"{row['code']}-{row['date']}"
                if key not in seen or seen[key]["cap"] < row["cap"]:
                    seen[key] = row
        if oldest and oldest > end:
            break

    items = sorted(seen.values(), key=lambda x: (-x["cap"], x["date"]))
    return items[:limit]


def build(data_dir: Path, days: int = 45, limit: int = 40) -> Path | None:
    try:
        items = fetch(days, limit)
    except Exception:  # noqa: BLE001
        return None
    if not items:
        return None
    payload = {
        "updatedAt": datetime.now(em.CST).isoformat(timespec="seconds"),
        "days": days,
        "items": items,
    }
    out = data_dir / "unlock.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
