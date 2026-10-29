"""命令行入口：抓取 / 回填 / 生成图片 / 每日任务。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analytics
import dragon
import em
import fundflow
import lhb_chart
import unlock
import payload as pl


def cmd_day(date: str, *, quiet: bool = False) -> bool:
    if not em.is_trading_day(date):
        # 日历偶尔滞后（比如当天收盘前后），用涨停池兜底：必须确认池子确实属于这一天
        today = datetime.now(em.CST).strftime("%Y%m%d")
        has_pool = False
        if date == today:
            try:
                has_pool = bool(em.fetch_zt_pool(date)) and em.pool_qdate("ZT", date) == date
            except em.SourceError:
                has_pool = False
        if not has_pool:
            if not quiet:
                print(f"[skip] {date} 非交易日")
            return False
    data = pl.build_day(date)
    if not data["rows"]:
        if not quiet:
            print(f"[skip] {date} 无涨停数据")
        return False
    path = pl.save_day(data)
    analytics.apply_all(pl.DATA_DIR)
    pl.rebuild_index()
    if not quiet:
        stats = data["stats"]
        print(
            f"[ok] {date} {data['weekday']} 封板{stats['sealed']} 炸板{stats['broken']} "
            f"最高{stats['maxBoard']}板 首板{stats['firstBoard']} -> {path.name}"
        )
        for row in data["rows"]:
            names = " ".join(s["name"] for s in row["stocks"][:12])
            print(f"     {row['height']}板({len(row['stocks'])}): {names}")
        print("     板块:", " ".join(f"{c['name']}({c['count']})" for c in data["sectors"]))
        print("     指数:", data.get("index"), "涨跌:", data.get("breadth"))
    return True


def cmd_backfill(days: int) -> None:
    today = datetime.now(em.CST).date()
    made = 0
    for i in range(days):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        date = d.strftime("%Y%m%d")
        try:
            if cmd_day(date, quiet=True):
                made += 1
                print(f"[ok] {date}")
        except Exception:  # noqa: BLE001
            print(f"[fail] {date}")
            traceback.print_exc(limit=2)
        time.sleep(0.4)
    pl.rebuild_index()
    print(f"done: {made} 个交易日")


def cmd_daily() -> None:
    today = datetime.now(em.CST).strftime("%Y%m%d")
    ok = cmd_day(today)
    if ok:
        import png

        png.render(f"{today[:4]}-{today[4:6]}-{today[6:]}")
        try:
            dragon.build_and_save(today, pl.DATA_DIR)
            lhb_chart.build(today, pl.DATA_DIR)
            lhb_chart.build_history(pl.DATA_DIR)
            unlock_path = unlock.build(pl.DATA_DIR)
            print(f"[{'ok' if unlock_path else 'warn'}] 解禁日历")
            flow_path = fundflow.build(pl.DATA_DIR)
            print(f"[{'ok' if flow_path else 'warn'}] 资金流（接口不可达时为空）")
        except Exception as exc:  # noqa: BLE001 - 龙虎榜失败不影响主流程
            print(f"[warn] 龙虎榜抓取失败：{exc}")
    pl.rebuild_index()


class _Tee:
    """把 stdout/stderr 同时写进日志文件（计划任务里没有控制台，靠它留痕）。"""

    def __init__(self, path: Path):
        self.file = open(path, "a", encoding="utf-8")
        self.console = sys.__stdout__

    def write(self, text: str) -> int:
        try:
            self.console.write(text)
        except Exception:  # noqa: BLE001 - 没有控制台就忽略
            pass
        self.file.write(text)
        self.file.flush()
        return len(text)

    def flush(self) -> None:
        self.file.flush()


def _attach_log() -> None:
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    tee = _Tee(log_dir / f"daily-{datetime.now(em.CST).strftime('%Y-%m-%d')}.log")
    sys.stdout = tee
    sys.stderr = tee


def main(argv=None) -> int:
    if os.environ.get("ZT_LOG"):
        _attach_log()
    ap = argparse.ArgumentParser(prog="ztladder")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_day = sub.add_parser("day", help="抓取某一天")
    p_day.add_argument("--date", default=datetime.now(em.CST).strftime("%Y%m%d"))

    p_bf = sub.add_parser("backfill", help="回填最近 N 天")
    p_bf.add_argument("--days", type=int, default=30)

    sub.add_parser("daily", help="每日任务：抓当天 + 生成长图 + 刷新索引")
    sub.add_parser("index", help="仅重建索引")
    sub.add_parser("analytics", help="重算全部历史日的复盘指标（不联网）")

    p_lhb = sub.add_parser("lhb", help="抓取某天/最近几天的龙虎榜")
    p_lhb.add_argument("--date", default=None)
    p_lhb.add_argument("--days", type=int, default=1)

    p_png = sub.add_parser("png", help="生成某天长图")
    p_png.add_argument("--date", default=None)
    p_png.add_argument("--all", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "day":
        return 0 if cmd_day(args.date) else 1
    if args.cmd == "backfill":
        cmd_backfill(args.days)
        return 0
    if args.cmd == "daily":
        cmd_daily()
        return 0
    if args.cmd == "index":
        print(pl.rebuild_index())
        return 0
    if args.cmd == "lhb":
        from datetime import timedelta as _td

        base = datetime.now(em.CST)
        dates = [args.date] if args.date else [
            (base - _td(days=i)).strftime("%Y%m%d") for i in range(args.days)
        ]
        for d in dates:
            path = dragon.build_and_save(d, pl.DATA_DIR)
            chart = lhb_chart.build(d, pl.DATA_DIR) if path else None
            print(f"[{'ok' if path else 'skip'}] {d} 龙虎榜 {'+ 分时' if chart else ''}")
        lhb_chart.build_history(pl.DATA_DIR)
        return 0
    if args.cmd == "analytics":
        count = analytics.apply_all(pl.DATA_DIR)
        pl.rebuild_index()
        print(f"已重算 {count} 个交易日")
        return 0
    if args.cmd == "png":
        import png

        if args.all:
            for path in sorted(pl.DATA_DIR.glob("????-??-??.json")):
                png.render(path.stem)
        else:
            png.render(args.date or json.loads((pl.DATA_DIR / "index.json").read_text(encoding="utf-8"))["latest"])
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
