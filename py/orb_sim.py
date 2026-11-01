#!/usr/bin/env python3
"""Walk-forward opening-range-breakout simulator: the reference Python version.

Reads export/feat.csv and export/bars.csv (from q/export.q), simulates every configuration
in the 432-point grid over every session, then runs the walk-forward: for each fold, pick
the configuration with the best in-sample Sharpe and trade it out of sample.

    python py/orb_sim.py --data export --config config/orb.cfg --out out_py

cpp/src/wf_grid.cpp is a line-for-line port. py/reconcile.py checks that both produce the
same trades, the same P&L and the same selections.

Everything price-like is held in integer ticks, so fills and P&L are exact. Floating-point
sums (Sharpe) are accumulated left to right in plain loops (not sum(), which compensates on
Python 3.12+) so the C++ port can reproduce them bit for bit.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orbcfg import Config, Params, load as load_config  # noqa: E402

TRADING_DAYS = 252.0


# ---------------------------------------------------------------- data

def parse_float(s: str) -> float:
    s = s.strip()
    if s.endswith("f"):  # q prints whole floats as e.g. 1500f
        s = s[:-1]
    return float(s)


def to_ticks(px: float, tick: float) -> int:
    return int(math.floor(px / tick + 0.5))


class Session:
    __slots__ = ("date", "tm", "o", "h", "l", "c", "feat")

    def __init__(self, date: int):
        self.date = date
        self.tm: list[int] = []
        self.o: list[int] = []
        self.h: list[int] = []
        self.l: list[int] = []
        self.c: list[int] = []
        # or_min -> (ok, or_high_ticks, or_low_ticks, rel_vol, w_to_v)
        self.feat: dict[int, tuple[bool, int, int, float, float]] = {}


def load_export(path: str, tick: float) -> list[Session]:
    sessions: dict[int, Session] = {}
    with open(os.path.join(path, "feat.csv"), newline="") as fh:
        for row in csv.DictReader(fh):
            date = int(row["date"])
            s = sessions.get(date)
            if s is None:
                s = sessions[date] = Session(date)
            s.feat[int(row["orMin"])] = (
                int(row["ok"]) == 1,
                to_ticks(parse_float(row["orHigh"]), tick),
                to_ticks(parse_float(row["orLow"]), tick),
                parse_float(row["relVol"]),
                parse_float(row["wToV"]),
            )
    with open(os.path.join(path, "bars.csv"), newline="") as fh:
        for row in csv.DictReader(fh):
            s = sessions.get(int(row["date"]))
            if s is None:
                raise ValueError(f"bar for date {row['date']} has no feature row")
            tmin = int(row["tmin"])
            if s.tm and tmin <= s.tm[-1]:
                raise ValueError(f"bars out of order on {s.date} at minute {tmin}")
            s.tm.append(tmin)
            s.o.append(to_ticks(parse_float(row["open"]), tick))
            s.h.append(to_ticks(parse_float(row["high"]), tick))
            s.l.append(to_ticks(parse_float(row["low"]), tick))
            s.c.append(to_ticks(parse_float(row["close"]), tick))
    return [sessions[d] for d in sorted(sessions)]


# ---------------------------------------------------------------- strategy

def run_session(s: Session, p: Params, c: Config):
    """One session of the breakout. Returns (side, entry_min, entry, exit_min, exit, reason) or None.

    Rules (identical to cpp/include/orb/strategy.hpp):
      * filters: feature row ok, relVol >= min_relvol, wToV <= max_wtov, OR width > 0
      * entry: buy stop one tick above the OR high, sell stop one tick below the OR low,
        from the first bar after the range closes until entry_cutoff; one trade per session.
        Fill = worse of trigger and bar open, plus slippage. A bar that crosses both triggers
        is ambiguous at 1-minute resolution, so the session is skipped.
      * stop = entry -/+ round(stop_frac * width); target = entry +/- round(target_r * stop distance)
      * on the entry bar only the stop is checked (pessimistic); on later bars, in order:
        gap through stop at the open, gap through target at the open, stop, target.
        When a bar touches both, the stop wins.
      * stops and the end-of-session exit pay slippage; the target is a resting limit and does not
      * still open after the last window bar: exit at its close
      * P&L = ticks * tick_value - 2 * fee_per_side
    """
    f = s.feat.get(p.or_min)
    if f is None:
        return None
    ok, hi, lo, relvol, wtov = f
    if not ok or relvol < p.min_relvol or wtov > p.max_wtov:
        return None
    width = hi - lo
    if width <= 0:
        return None

    stop_d = max(1, int(math.floor(p.stop_frac * width + 0.5)))
    tgt_d = max(1, int(math.floor(p.target_r * stop_d + 0.5)))
    trig_l = hi + 1
    trig_s = lo - 1
    slip = c.slip_ticks
    cutoff = c.entry_cutoff

    tm, o, h, l, cl = s.tm, s.o, s.h, s.l, s.c
    n = len(tm)
    i = bisect.bisect_left(tm, c.sess_open + p.or_min)
    side = 0
    entry = stop = tgt = emin = 0

    while i < n:
        if side == 0:
            if tm[i] >= cutoff:
                return None
            up = h[i] >= trig_l
            dn = l[i] <= trig_s
            if up and dn:
                return None
            if up:
                side, emin = 1, tm[i]
                entry = max(o[i], trig_l) + slip
                stop, tgt = entry - stop_d, entry + tgt_d
                if l[i] <= stop:
                    return (side, emin, entry, tm[i], stop - slip, "stop")
            elif dn:
                side, emin = -1, tm[i]
                entry = min(o[i], trig_s) - slip
                stop, tgt = entry + stop_d, entry - tgt_d
                if h[i] >= stop:
                    return (side, emin, entry, tm[i], stop + slip, "stop")
        elif side == 1:
            if o[i] <= stop:
                return (side, emin, entry, tm[i], o[i] - slip, "stop")
            if o[i] >= tgt:
                return (side, emin, entry, tm[i], o[i], "target")
            if l[i] <= stop:
                return (side, emin, entry, tm[i], stop - slip, "stop")
            if h[i] >= tgt:
                return (side, emin, entry, tm[i], tgt, "target")
        else:
            if o[i] >= stop:
                return (side, emin, entry, tm[i], o[i] + slip, "stop")
            if o[i] <= tgt:
                return (side, emin, entry, tm[i], o[i], "target")
            if h[i] >= stop:
                return (side, emin, entry, tm[i], stop + slip, "stop")
            if l[i] <= tgt:
                return (side, emin, entry, tm[i], tgt, "target")
        i += 1

    if side != 0:
        return (side, emin, entry, tm[n - 1], cl[n - 1] - side * slip, "close")
    return None


def simulate_config(sessions: list[Session], p: Params, c: Config):
    """All sessions for one configuration -> (trades, daily P&L, traded flags)."""
    fees = 2.0 * c.fee_per_side
    trades = []
    pnl = [0.0] * len(sessions)
    traded = [0] * len(sessions)
    for k, s in enumerate(sessions):
        t = run_session(s, p, c)
        if t is None:
            continue
        side, emin, entry, xmin, exit_, reason = t
        pnl_tk = (exit_ - entry) * side
        pnl_usd = pnl_tk * c.tick_value - fees
        trades.append((p.idx, s.date, side, emin, entry, xmin, exit_, reason, pnl_tk, pnl_usd))
        pnl[k] = pnl_usd
        traded[k] = 1
    return trades, pnl, traded


# ---------------------------------------------------------------- statistics

def sharpe(x: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    tot = 0.0
    for v in x:
        tot += v
    m = tot / n
    ss = 0.0
    for v in x:
        d = v - m
        ss += d * d
    var = ss / (n - 1)
    if var <= 0.0:
        return 0.0
    return m / math.sqrt(var) * math.sqrt(TRADING_DAYS)


def total(x: list[float]) -> float:
    tot = 0.0
    for v in x:
        tot += v
    return tot


def max_drawdown(x: list[float]) -> float:
    eq = peak = dd = 0.0
    for v in x:
        eq += v
        if eq > peak:
            peak = eq
        if peak - eq > dd:
            dd = peak - eq
    return dd


# ---------------------------------------------------------------- walk-forward

def walk_forward(sessions, c: Config, daily, traded, all_trades):
    dates = [s.date for s in sessions]
    fold_stats, selection, oos_trades, oos_daily = [], [], [], []

    for k, fold in enumerate(c.folds, start=1):
        t0 = bisect.bisect_left(dates, fold.test_start)
        t1 = bisect.bisect_right(dates, fold.test_end)
        a = 0 if c.train_years == 0 else bisect.bisect_left(dates, fold.test_start - 10000 * c.train_years)
        b = t0  # training ends the session before the test window opens

        best, best_sr = -1, 0.0
        for p in c.grid:
            d = daily[p.idx][a:b]
            sr = sharpe(d)
            nt = 0
            for v in traded[p.idx][a:b]:
                nt += v
            fold_stats.append((k, p.idx, b - a, nt, total(d), sr))
            if nt >= c.min_trades and (best < 0 or sr > best_sr):
                best, best_sr = p.idx, sr

        best_nt = 0
        if best >= 0:
            for v in traded[best][a:b]:
                best_nt += v
            for t in all_trades[best]:
                if fold.test_start <= t[1] <= fold.test_end:
                    oos_trades.append((k,) + t)
        selection.append({
            "fold": k, "test_start": fold.test_start, "test_end": fold.test_end,
            "train_start": dates[a] if b > a else 0, "train_end": dates[b - 1] if b > a else 0,
            "cfg": best, "train_sharpe": best_sr if best >= 0 else 0.0, "train_trades": best_nt,
        })
        for i in range(t0, t1):
            oos_daily.append((dates[i], k, best, daily[best][i] if best >= 0 else 0.0))

    return fold_stats, selection, oos_trades, oos_daily


def summarize(c: Config, selection, oos_trades, oos_daily):
    pnl = [r[3] for r in oos_daily]
    wins = sum(1 for t in oos_trades if t[10] > 0.0)
    out = {
        "oos_sessions": len(pnl),
        "oos_trades": len(oos_trades),
        "oos_net_pnl_usd": total(pnl),
        "oos_net_sharpe": sharpe(pnl),
        "oos_max_drawdown_usd": max_drawdown(pnl),
        "oos_win_rate": wins / len(oos_trades) if oos_trades else 0.0,
        "folds": [],
    }
    for sel in selection:
        k = sel["fold"]
        fp = [r[3] for r in oos_daily if r[1] == k]
        ft = [t for t in oos_trades if t[0] == k]
        out["folds"].append({
            "fold": k, "cfg": sel["cfg"], "params": params_dict(c.grid[sel["cfg"]]) if sel["cfg"] >= 0 else None,
            "train_sharpe": sel["train_sharpe"], "oos_sessions": len(fp), "oos_trades": len(ft),
            "oos_pnl_usd": total(fp), "oos_sharpe": sharpe(fp),
        })
    return out


def params_dict(p: Params):
    return {"or_min": p.or_min, "stop_frac": p.stop_frac, "target_r": p.target_r,
            "min_relvol": p.min_relvol, "max_wtov": p.max_wtov}


# ---------------------------------------------------------------- output

TRADE_COLS = ["cfg", "date", "side", "entry_min", "entry_tk", "exit_min", "exit_tk", "reason", "pnl_tk", "pnl_usd"]


def fmt(v):
    return repr(v) if isinstance(v, float) else str(v)


def write_csv(path, header, rows):
    with open(path, "w", newline="") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join(fmt(v) for v in r) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="export", help="directory with feat.csv and bars.csv")
    ap.add_argument("--config", default="config/orb.cfg")
    ap.add_argument("--out", default="out_py")
    ap.add_argument("--no-dump", action="store_true", help="skip grid_trades.csv (every trade of every config)")
    args = ap.parse_args()

    c = load_config(args.config)
    os.makedirs(args.out, exist_ok=True)

    t_load = time.perf_counter()
    sessions = load_export(args.data, c.tick)
    t_load = time.perf_counter() - t_load
    print(f"loaded {len(sessions)} sessions, {sum(len(s.tm) for s in sessions)} bars in {t_load:.1f}s")

    t0 = time.perf_counter()
    daily, traded, all_trades = [], [], []
    for p in c.grid:
        tr, d, f = simulate_config(sessions, p, c)
        all_trades.append(tr)
        daily.append(d)
        traded.append(f)
        if (p.idx + 1) % 48 == 0:
            print(f"  {p.idx + 1}/{len(c.grid)} configs  {time.perf_counter() - t0:.1f}s", flush=True)
    fold_stats, selection, oos_trades, oos_daily = walk_forward(sessions, c, daily, traded, all_trades)
    elapsed = time.perf_counter() - t0

    summary = summarize(c, selection, oos_trades, oos_daily)
    summary["configs"] = len(c.grid)
    summary["study_seconds"] = elapsed
    summary["engine"] = "python"

    if not args.no_dump:
        write_csv(os.path.join(args.out, "grid_trades.csv"), TRADE_COLS, (t for tr in all_trades for t in tr))
    write_csv(os.path.join(args.out, "grid_fold_stats.csv"),
              ["fold", "cfg", "train_sessions", "train_trades", "train_pnl_usd", "train_sharpe"], fold_stats)
    sel_cols = ["fold", "test_start", "test_end", "train_start", "train_end", "cfg",
                "or_min", "stop_frac", "target_r", "min_relvol", "max_wtov", "train_sharpe", "train_trades"]
    sel_rows = []
    for s in selection:
        p = c.grid[s["cfg"]] if s["cfg"] >= 0 else None
        sel_rows.append([s["fold"], s["test_start"], s["test_end"], s["train_start"], s["train_end"], s["cfg"],
                         p.or_min if p else 0, p.stop_frac if p else 0.0, p.target_r if p else 0.0,
                         p.min_relvol if p else 0.0, p.max_wtov if p else 0.0,
                         s["train_sharpe"], s["train_trades"]])
    write_csv(os.path.join(args.out, "wf_selection.csv"), sel_cols, sel_rows)
    write_csv(os.path.join(args.out, "wf_trades.csv"), ["fold"] + TRADE_COLS, oos_trades)
    write_csv(os.path.join(args.out, "wf_daily.csv"), ["date", "fold", "cfg", "pnl_usd"], oos_daily)
    with open(os.path.join(args.out, "wf_summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)

    print(f"{len(c.grid)}-config walk-forward study: {elapsed:.1f}s")
    for f in summary["folds"]:
        print(f"  fold {f['fold']}: cfg {f['cfg']:>3}  train SR {f['train_sharpe']:6.2f}  "
              f"OOS trades {f['oos_trades']:>3}  OOS P&L {f['oos_pnl_usd']:>10.0f}  OOS SR {f['oos_sharpe']:6.2f}")
    print(f"OOS: {summary['oos_trades']} trades, net P&L ${summary['oos_net_pnl_usd']:,.0f}, "
          f"net Sharpe {summary['oos_net_sharpe']:.2f}, max DD ${summary['oos_max_drawdown_usd']:,.0f}")


if __name__ == "__main__":
    main()
