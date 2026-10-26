"""数据源适配层：东方财富涨停池/炸板池、同花顺涨停原因、市场宽度。

设计要点
--------
* 全部走 http（当前环境 TLS 被拦截，https 只有 python 侧可用，http 更稳）。
* 每个 source 独立重试，失败不影响其它字段（payload 里用 null 表示缺失）。
* 返回结构统一为 plain dict，方便直接落 JSON。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
CST = timezone(timedelta(hours=8))

EM_TOKEN = "7eea3edcaed734bea9cbfc24409ed989"

_POOL_CACHE: dict[tuple[str, str], list[dict]] = {}
_POOL_QDATE: dict[tuple[str, str], str] = {}


class SourceError(RuntimeError):
    pass


def _get(url: str, referer: str, encoding: str = "utf-8", timeout: int = 20, retries: int = 3) -> str:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "*/*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": referer,
                    "Connection": "close",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode(encoding, "replace")
        except Exception as exc:  # noqa: BLE001 - 网络层什么都可能抛
            last = exc
            time.sleep(0.6 * (attempt + 1))
    raise SourceError(f"{url} -> {type(last).__name__}: {last}")


def _get_json(url: str, referer: str, retries: int = 3) -> dict:
    raw = _get(url, referer, retries=retries)
    raw = raw.strip()
    if raw.startswith("(") or raw.startswith("jQuery"):
        raw = raw[raw.index("(") + 1 : raw.rindex(")")]
    return json.loads(raw)


# --------------------------------------------------------------------------- #
# 涨停池 / 炸板池 / 跌停池
# --------------------------------------------------------------------------- #
def _pool(kind: str, date: str) -> list[dict]:
    key = (kind, date)
    if key in _POOL_CACHE:
        return _POOL_CACHE[key]
    url = (
        "http://push2ex.eastmoney.com/getTopic%sPool"
        "?ut=%s&dpt=wz.ztzt&Pageindex=0&pagesize=500&sort=fbt%%3Aasc&date=%s&_=%d"
        % (kind, EM_TOKEN, date, int(time.time() * 1000))
    )
    data = _get_json(url, "http://quote.eastmoney.com/").get("data") or {}
    pool = list(data.get("pool") or [])
    if data.get("qdate"):
        _POOL_QDATE[key] = str(data["qdate"])
    _POOL_CACHE[key] = pool
    return pool


def pool_qdate(kind: str, date: str) -> str:
    """池子数据真正对应的交易日（节假日会指向上一个交易日）。"""
    if (kind, date) not in _POOL_QDATE:
        try:
            _pool(kind, date)
        except SourceError:
            return ""
    return _POOL_QDATE.get((kind, date), "")


def _price(raw, div: float = 1000.0):
    try:
        return round(float(raw) / div, 3)
    except (TypeError, ValueError):
        return None


def _hhmm(sec) -> str | None:
    """92500 -> 09:25 ; 150000 -> 15:00"""
    try:
        n = int(sec)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    s = f"{n:06d}"
    return f"{s[0:2]}:{s[2:4]}"


def _zt_item(row: dict) -> dict:
    fbt = row.get("fbt")
    one_word = int(row.get("zbc") or 0) == 0 and isinstance(fbt, int) and fbt <= 93000
    return {
        "code": row.get("c"),
        "name": row.get("n"),
        "market": row.get("m"),
        "price": _price(row.get("p")),
        "pct": round(float(row.get("zdp") or 0), 2),
        "amount": row.get("amount"),
        "floatCap": row.get("ltsz"),
        "totalCap": row.get("tshare"),
        "turnover": round(float(row.get("hs") or 0), 2),
        "boards": int(row.get("lbc") or 1),
        "firstTime": _hhmm(fbt),
        "lastTime": _hhmm(row.get("lbt")),
        "sealAmount": row.get("fund"),
        "brokenTimes": int(row.get("zbc") or 0),
        "sector": (row.get("hybk") or "其他").strip(),
        "stat": row.get("zttj") or {},
        "oneWord": one_word,
        "broken": False,
    }


def fetch_zt_pool(date: str) -> list[dict]:
    """涨停池（收盘封住的）。"""
    return [_zt_item(row) for row in _pool("ZT", date) if row.get("c")]


def fetch_zb_pool(date: str) -> list[dict]:
    """炸板池：盘中封过、收盘没封住的。height = 今日冲击高度 = ct + 1。"""
    out = []
    for row in _pool("ZB", date):
        stat = row.get("zttj") or {}
        ct = int(stat.get("ct") or 0)
        out.append(
            {
                "code": row.get("c"),
                "name": row.get("n"),
                "market": row.get("m"),
                "price": _price(row.get("p")),
                "pct": round(float(row.get("zdp") or 0), 2),
                "amount": row.get("amount"),
                "floatCap": row.get("ltsz"),
                "totalCap": row.get("tshare"),
                "turnover": round(float(row.get("hs") or 0), 2),
                "boards": ct + 1,
                "firstTime": _hhmm(row.get("fbt")),
                "lastTime": None,
                "sealAmount": None,
                "brokenTimes": int(row.get("zbc") or 0),
                "sector": (row.get("hybk") or "其他").strip(),
                "stat": stat,
                "oneWord": False,
                "broken": True,
            }
        )
    return out


def fetch_dt_count(date: str) -> int | None:
    try:
        return len(_pool("DT", date))
    except SourceError:
        return None


def prev_pool(date: str, max_back: int = 12) -> tuple[str, list[dict]]:
    """上一个交易日的涨停池（用来算「昨日连板数」）。"""
    d = datetime.strptime(date, "%Y%m%d")
    for i in range(1, max_back + 1):
        cand = d - timedelta(days=i)
        key = cand.strftime("%Y%m%d")
        try:
            pool = fetch_zt_pool(key)
        except SourceError:
            continue
        if pool:
            return key, pool
    return "", []


def _quotes_sina(codes: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    symbols = [("sh" if c[0] == "6" else "sz") + c for c in codes]
    for start in range(0, len(symbols), 50):
        chunk = symbols[start : start + 50]
        try:
            text = _get(
                "http://hq.sinajs.cn/list=" + ",".join(chunk),
                "http://finance.sina.com.cn/",
                encoding="gbk",
                retries=2,
            )
        except SourceError:
            continue
        for line in text.split(";"):
            line = line.strip()
            if not line.startswith("var hq_str_"):
                continue
            head, _, body = line.partition("=")
            code = head.replace("var hq_str_", "")[2:]
            parts = body.strip().strip('"').split(",")
            if len(parts) < 10 or not parts[0]:
                continue
            try:
                prev_close = float(parts[2])
                price = float(parts[3])
                amount = float(parts[9])
            except (TypeError, ValueError):
                continue
            pct = (price / prev_close - 1) * 100 if prev_close else None
            out[code] = {
                "price": round(price, 2),
                "pct": round(pct, 2) if pct is not None else None,
                "amount": amount,
                "turnover": None,
                "name": parts[0],
                "totalCap": None,
                "floatCap": None,
            }
    return out


def _quote_prefix(code: str) -> str:
    if code.startswith("6"):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    return "bj"


_KLINE_CACHE: dict[str, list[list[str]]] = {}


def _stock_kline(code: str, count: int = 320) -> list[list[str]]:
    if code in _KLINE_CACHE:
        return _KLINE_CACHE[code]
    symbol = _quote_prefix(code) + code
    url = (
        "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,%d,qfq" % (symbol, count)
    )
    rows: list[list[str]] = []
    try:
        payload = _get_json(url, "http://gu.qq.com/")
        node = ((payload.get("data") or {}).get(symbol)) or {}
        rows = node.get("qfqday") or node.get("day") or []
    except (SourceError, ValueError):
        rows = []
    if rows:
        _KLINE_CACHE[code] = rows
    return rows


def _stock_kline_em(code: str, date: str) -> list[list[str]]:
    """东财日 K 兜底（腾讯取不到时用）。返回 [date, '', close] 结构，与腾讯保持一致。"""
    secid = ("0." if code[0] in "03" else "1.") + code
    d = datetime.strptime(date, "%Y%m%d")
    beg = (d - timedelta(days=20)).strftime("%Y%m%d")
    url = (
        "http://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s"
        "&klt=101&fqt=1&beg=%s&end=%s&fields1=f1,f2,f3&fields2=f51,f53" % (secid, beg, date)
    )
    try:
        data = (_get_json(url, "http://quote.eastmoney.com/", retries=2).get("data")) or {}
    except SourceError:
        return []
    rows: list[list[str]] = []
    for line in data.get("klines") or []:
        parts = line.split(",")
        if len(parts) >= 2:
            rows.append([parts[0], "", parts[1]])
    return rows


def _lookup_pct(rows: list[list[str]], target: str) -> tuple[float, float] | None:
    if not rows:
        return None
    idx = next((i for i, r in enumerate(rows) if r[0] == target), None)
    if idx is None or idx == 0:
        return None
    try:
        close = float(rows[idx][2])
        prev = float(rows[idx - 1][2])
    except (TypeError, ValueError):
        return None
    return close, prev


def fetch_quotes_hist(codes: list[str], date: str) -> dict[str, dict]:
    """历史日期用日 K 补「昨日连板股今天」的收盘涨跌幅（实时接口只给当天）。"""
    target = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    out: dict[str, dict] = {}
    for code in dict.fromkeys(codes):
        found = _lookup_pct(_stock_kline(code), target)
        if found is None:  # 腾讯挂了就用东财兜底
            found = _lookup_pct(_stock_kline_em(code, date), target)
        if found is None:
            continue
        close, prev = found
        out[code] = {
            "price": round(close, 2),
            "pct": round((close / prev - 1) * 100, 2) if prev else None,
            "amount": None,
            "turnover": None,
            "name": None,
            "totalCap": None,
            "floatCap": None,
        }
    return out


def fetch_quotes(codes: list[str]) -> dict[str, dict]:
    """批量取实时/收盘快照，用于「炸板但没进池」的个股涨跌幅。"""
    codes = [c for c in dict.fromkeys(codes) if c]
    if not codes:
        return {}
    out: dict[str, dict] = {}
    for start in range(0, len(codes), 40):
        chunk = codes[start : start + 40]
        secids = ",".join(("0." if c[0] in "03" else "1.") + c for c in chunk)
        url = (
            "http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&secids=%s"
            "&fields=f2,f3,f6,f8,f12,f14,f20,f21" % secids
        )
        try:
            data = (_get_json(url, "http://quote.eastmoney.com/", retries=2).get("data")) or {}
        except SourceError:
            continue
        for row in data.get("diff") or []:
            code = row.get("f12")
            if not code:
                continue
            out[code] = {
                "price": row.get("f2"),
                "pct": row.get("f3"),
                "amount": row.get("f6"),
                "turnover": row.get("f8"),
                "name": row.get("f14"),
                "totalCap": row.get("f20"),
                "floatCap": row.get("f21"),
            }
    missing = [c for c in codes if c not in out]
    if missing:
        out.update(_quotes_sina(missing))
    return out


# --------------------------------------------------------------------------- #
# 同花顺涨停原因（题材）
# --------------------------------------------------------------------------- #
THS_REF = "http://data.10jqka.com.cn/"
THS_FIELDS = "199112,10,9001,330323,330324,330325,9002,330329,9004,9003,9005"


def fetch_ths_reasons(date: str) -> dict[str, dict]:
    """返回 {code: {reason, type, firstTs, lastTs, openNum, highDays}}"""
    out: dict[str, dict] = {}
    for page in range(1, 4):
        url = (
            "http://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
            "?page=%d&limit=200&field=%s&filter=HS,GEM2STAR&order_field=330324&order_type=0&date=%s&_=%d"
            % (page, THS_FIELDS, date, int(time.time() * 1000))
        )
        try:
            payload = _get_json(url, THS_REF)
        except SourceError:
            break
        data = payload.get("data") or {}
        info = data.get("info") or []
        if not info:
            break
        for row in info:
            code = row.get("code")
            if not code:
                continue
            out[code] = {
                "reason": (row.get("reason_type") or "").strip(),
                "type": (row.get("limit_up_type") or "").strip(),
                "openNum": row.get("open_num"),
                "highDays": row.get("high_days"),
                "successRate": row.get("limit_up_suc_rate"),
            }
        total = int((data.get("page") or {}).get("total") or 0)
        if len(out) >= total:
            break
    return out


# --------------------------------------------------------------------------- #
# 指数
# --------------------------------------------------------------------------- #
def _index_tencent() -> dict | None:
    try:
        text = _get("http://qt.gtimg.cn/q=sh000001", "http://gu.qq.com/", encoding="gbk", retries=2)
    except SourceError:
        return None
    body = text.split('="', 1)[-1].rstrip('";\n ')
    parts = body.split("~")
    if len(parts) < 33:
        return None
    try:
        price = float(parts[3])
        prev = float(parts[4])
        pct = float(parts[32]) if parts[32] else (price / prev - 1) * 100
        chg = float(parts[31]) if parts[31] else price - prev
    except (TypeError, ValueError):
        return None
    return {
        "name": parts[1] or "上证指数",
        "value": round(price, 2),
        "pct": round(pct, 2),
        "chg": round(chg, 2),
        "quoteTime": parts[30] or None,
    }


def _index_sina() -> dict | None:
    try:
        text = _get("http://hq.sinajs.cn/list=sh000001", "http://finance.sina.com.cn/", encoding="gbk", retries=2)
    except SourceError:
        return None
    parts = text.split('="', 1)[-1].rstrip('";\n ').split(",")
    try:
        prev = float(parts[2])
        price = float(parts[3])
    except (IndexError, TypeError, ValueError):
        return None
    return {
        "name": parts[0] or "上证指数",
        "value": round(price, 2),
        "pct": round((price / prev - 1) * 100, 2) if prev else 0.0,
        "chg": round(price - prev, 2),
        "quoteTime": f"{parts[30]} {parts[31]}" if len(parts) > 31 else None,
    }


def fetch_index_rt() -> dict | None:
    url = (
        "http://push2.eastmoney.com/api/qt/stock/get?secid=1.000001"
        "&fields=f43,f44,f45,f46,f57,f58,f86,f169,f170"
    )
    data = {}
    try:
        data = (_get_json(url, "http://quote.eastmoney.com/", retries=2).get("data")) or {}
    except SourceError:
        data = {}
    if data.get("f43"):
        ts = data.get("f86")
        when = None
        if ts:
            when = datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "name": data.get("f58") or "上证指数",
            "value": round(float(data["f43"]) / 100, 2),
            "pct": round(float(data.get("f170") or 0) / 100, 2),
            "chg": round(float(data.get("f169") or 0) / 100, 2),
            "quoteTime": when,
        }
    return _index_tencent() or _index_sina()


_TXD_CACHE: list[list[str]] = []


def _tx_kline(count: int = 400) -> list[list[str]]:
    """腾讯日 K（http 稳定）：[[date, open, close, high, low, volume], ...]"""
    global _TXD_CACHE
    if len(_TXD_CACHE) >= count:
        return _TXD_CACHE
    url = (
        "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,,,%d,qfq" % max(count, 400)
    )
    try:
        payload = _get_json(url, "http://gu.qq.com/")
        node = ((payload.get("data") or {}).get("sh000001")) or {}
        rows = node.get("qfqday") or node.get("day") or []
    except (SourceError, ValueError):
        rows = []
    if rows:
        _TXD_CACHE = rows
    return _TXD_CACHE


def trading_days(count: int = 400) -> list[str]:
    return [row[0] for row in _tx_kline(count)]


def is_trading_day(date: str) -> bool:
    target = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    days = trading_days(400)
    if days:
        return target in days
    # 兜底：日历取不到时，用涨停池的 qdate 校验
    try:
        return pool_qdate("ZT", date) == date
    except SourceError:
        return False


def fetch_index_hist(date: str) -> dict | None:
    """历史日期用日 K 线补指数收盘（腾讯）。"""
    target = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    rows = [r for r in _tx_kline(400) if r[0] <= target]
    if not rows or rows[-1][0] != target:
        return None
    close = float(rows[-1][2])
    prev = float(rows[-2][2]) if len(rows) > 1 else close
    return {
        "name": "上证指数",
        "value": round(close, 2),
        "pct": round((close / prev - 1) * 100, 2) if prev else 0.0,
        "chg": round(close - prev, 2),
        "quoteTime": target,
    }


# --------------------------------------------------------------------------- #
# 涨跌家数（市场宽度）
# --------------------------------------------------------------------------- #
EM_FS_HS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"


def _breadth_em() -> dict | None:
    base = (
        "http://push2.eastmoney.com/api/qt/clist/get?pn={pn}&pz=100&po=1&np=1"
        "&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs="
        + EM_FS_HS
        + "&fields=f3,f12"
    )
    try:
        first = _get_json(base.format(pn=1), "http://quote.eastmoney.com/")
        total = int((first.get("data") or {}).get("total") or 0)
        rows = list((first.get("data") or {}).get("diff") or [])
        pages = (total + 99) // 100
        if pages > 1:
            with ThreadPoolExecutor(max_workers=6) as pool:
                for chunk in pool.map(
                    lambda p: (_get_json(base.format(pn=p), "http://quote.eastmoney.com/").get("data") or {}).get("diff") or [],
                    range(2, pages + 1),
                ):
                    rows.extend(chunk)
    except (SourceError, ValueError):
        return None
    up = sum(1 for x in rows if isinstance(x.get("f3"), (int, float)) and x["f3"] > 0)
    down = sum(1 for x in rows if isinstance(x.get("f3"), (int, float)) and x["f3"] < 0)
    flat = sum(1 for x in rows if isinstance(x.get("f3"), (int, float)) and x["f3"] == 0)
    if up + down + flat < 1000:
        return None
    return {"up": up, "down": down, "flat": flat, "source": "eastmoney"}


def _breadth_sina() -> dict | None:
    base = (
        "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeData?page={pn}&num=100&sort=symbol&asc=1&node=hs_a&symbol=&_s_r_a=page"
    )
    try:
        first = json.loads(_get(base.format(pn=1), "http://finance.sina.com.cn/", encoding="gbk"))
    except (SourceError, ValueError):
        return None
    # 新浪单页 100 条；沪深 A 股约 5200 只 => 最多 60 页
    pages = list(range(1, 61))
    rows = list(first or [])
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for chunk in pool.map(
                lambda p: json.loads(_get(base.format(pn=p), "http://finance.sina.com.cn/", encoding="gbk") or "[]"),
                pages[1:],
            ):
                rows.extend(chunk or [])
    except (SourceError, ValueError):
        pass
    up = down = flat = 0
    seen = set()
    for row in rows:
        sym = row.get("symbol") or ""
        if not sym.startswith(("sh", "sz")) or sym in seen:
            continue
        seen.add(sym)
        try:
            pct = float(row.get("changepercent"))
        except (TypeError, ValueError):
            continue
        if pct > 0:
            up += 1
        elif pct < 0:
            down += 1
        else:
            flat += 1
    if up + down + flat < 1000:
        return None
    return {"up": up, "down": down, "flat": flat, "source": "sina"}


def fetch_breadth() -> dict | None:
    return _breadth_em() or _breadth_sina()


# --------------------------------------------------------------------------- #
# 交易日历（用上证指数日 K 判断今天是否开市）
# --------------------------------------------------------------------------- #
