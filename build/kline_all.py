"""抓全市场个股日 K 到本地缓存（一次性，约 20-30 分钟）。

代码表来源：新浪行情列表（分页），再与已有缓存合并。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import kline

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "public" / "data"
SINA = (
    "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node=hs_a&symbol=&_s_r_a=page"
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


def all_codes() -> list[str]:
    codes: list[str] = []
    for page in range(1, 70):
        url = SINA.format(page=page)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "http://finance.sina.com.cn/"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                rows = json.loads(resp.read().decode("gbk", "replace") or "[]")
        except Exception:  # noqa: BLE001
            break
        if not rows:
            break
        for row in rows:
            code = (row.get("code") or "").strip()
            if len(code) == 6 and code.isdigit():
                if code.startswith(("60", "68", "00", "30", "43", "83", "87", "92")):
                    codes.append(code)
    return list(dict.fromkeys(codes))


FORCE = "--force" in sys.argv


def main() -> None:
    t0 = time.time()
    codes = all_codes()
    print(f"代码 {len(codes)} 只")
    cached = len(list((ROOT / ".cache" / "kline").glob("*.json")))
    print(f"已有缓存 {cached} 只")

    batch = 400
    for i in range(0, len(codes), batch):
        chunk = codes[i : i + batch]
        added = kline.ensure(chunk, DATA, workers=8, force=FORCE)
        total = len(list((ROOT / ".cache" / "kline").glob("*.json")))
        print(f"  {i + len(chunk)}/{len(codes)}  新增 {added}  累计 {total}  ({time.time() - t0:.0f}s)", flush=True)
    print("done")


if __name__ == "__main__":
    sys.exit(main())
