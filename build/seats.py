"""席位分类：机构 / 北向 / 知名游资 / 普通营业部。

别名表放在 data/seats-alias.json，可随时增删，格式：
{"华鑫证券股份有限公司上海分公司": {"tag": "游资", "alias": "章盟主"}}
没命中别名表的，按名称关键词归类。
"""

from __future__ import annotations

import json
from pathlib import Path

ALIAS_FILE = "seats-alias.json"

# 名称里出现这些关键词就判为机构/北向
INSTITUTION_KEYS = ("机构专用", "机构席位")
NORTH_KEYS = ("沪股通", "深股通", "港股通")

# 内置的少量参考别名（知名游资常用席位，仅供阅读方便，可能随时间变化）
BUILTIN = {
    "华鑫证券有限责任公司上海分公司": ("游资", "章盟主"),
    "国泰君安证券股份有限公司上海江苏路证券营业部": ("游资", "章盟主"),
    "中国银河证券股份有限公司绍兴证券营业部": ("游资", "赵老哥"),
    "华泰证券股份有限公司深圳益田路荣超商务中心证券营业部": ("游资", "作手新一"),
    "光大证券股份有限公司佛山绿景路证券营业部": ("游资", "佛山无影脚"),
    "国信证券股份有限公司深圳泰然九路证券营业部": ("游资", "深圳帮"),
    "东方财富证券股份有限公司拉萨团结路第二证券营业部": ("游资", "拉萨天团"),
    "东方财富证券股份有限公司拉萨东环路第二证券营业部": ("游资", "拉萨天团"),
    "财通证券股份有限公司杭州上塘路证券营业部": ("游资", "上塘路"),
    "中国中金财富证券有限公司北京宋庄路证券营业部": ("游资", "宋庄路"),
}

_cache: dict[str, dict] | None = None


def _load_alias(data_dir: Path) -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache
    table: dict[str, dict] = {}
    for name, (tag, alias) in BUILTIN.items():
        table[name] = {"tag": tag, "alias": alias}
    path = data_dir / ALIAS_FILE
    if path.exists():
        try:
            extra = json.loads(path.read_text(encoding="utf-8"))
            for name, meta in extra.items():
                if isinstance(meta, dict) and meta.get("tag"):
                    table[name] = {"tag": meta["tag"], "alias": meta.get("alias") or ""}
        except ValueError:
            pass
    _cache = table
    return table


def classify(name: str, data_dir: Path) -> dict:
    """返回 {tag, alias}，tag ∈ 机构 / 北向 / 游资 / 营业部。"""
    clean = (name or "").strip()
    table = _load_alias(data_dir)
    if clean in table:
        return table[clean]
    if any(k in clean for k in INSTITUTION_KEYS):
        return {"tag": "机构", "alias": ""}
    if any(k in clean for k in NORTH_KEYS):
        return {"tag": "北向", "alias": ""}
    return {"tag": "营业部", "alias": ""}


def tag_seats(seats: dict, data_dir: Path) -> dict:
    """给 b/s 两组席位补上 label 与 3 日胜率。"""
    out = {}
    for side, rows in (seats or {}).items():
        tagged = []
        for row in rows or []:
            name, buy, sell, net = row[0], row[1], row[2], row[3]
            prob = row[4] if len(row) > 4 else None
            meta = classify(name, data_dir)
            tagged.append([name, buy, sell, net, prob, meta["tag"], meta["alias"]])
        out[side] = tagged
    return out
