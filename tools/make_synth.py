#!/usr/bin/env python3
"""Synthetic GC 1-minute bars in the vendor format q/load.q expects. For testing only.

    python tools/make_synth.py --out data/synth_raw --start 2020-01-02 --end 2024-12-31

Writes one CSV per contract (ts,sym,open,high,low,close,volume; ts = bar start, ET). The front
contract trades 18:00-19:59 the evening before plus 06:00-15:59; the next contract prints a bar
every 5 minutes. Volume leadership switches around the 26th of the month before delivery, so the
roll logic has something to find. A few defects are injected on purpose (a broken OHLC bar, a
duplicated timestamp, a thin session) so the validation and exclusion paths get exercised.

Prices are a random walk with occasional trend days. Results on this data mean nothing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import random

ACTIVE = [2, 4, 6, 8, 10, 12]
CODES = "FGHJKMNQUVXZ"


def contract_for(day: dt.date, offset: int) -> tuple[int, int]:
    """(year, month) of the front contract (offset 0) or the one after it (offset 1)."""
    m = day.year * 12 + day.month - 1 + (1 if day.day >= 26 else 0)
    found = []
    k = m + 1
    while len(found) <= offset:
        if (k % 12) + 1 in ACTIVE:
            found.append((k // 12, k % 12 + 1))
        k += 1
    return found[offset]


def code(ym: tuple[int, int]) -> str:
    return f"GC{CODES[ym[1] - 1]}{ym[0] % 100:02d}"


def trading_days(a: dt.date, b: dt.date):
    d = a
    while d <= b:
        if d.weekday() < 5 and not (d.month == 1 and d.day == 1) and not (d.month == 12 and d.day == 25):
            yield d
        d += dt.timedelta(days=1)


def minutes_for(day: dt.date, step: int):
    """Bar start datetimes for trade date `day` (evening session belongs to the next trade date)."""
    prev = day - dt.timedelta(days=1)  # Monday's evening session opens Sunday 18:00
    for m in range(18 * 60, 20 * 60, step):
        yield dt.datetime.combine(prev, dt.time(m // 60, m % 60))
    for m in range(6 * 60, 16 * 60, step):
        yield dt.datetime.combine(day, dt.time(m // 60, m % 60))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/synth_raw")
    ap.add_argument("--start", default="2020-01-02")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    os.makedirs(args.out, exist_ok=True)
    files: dict[str, object] = {}

    def writer(sym):
        if sym not in files:
            fh = open(os.path.join(args.out, f"{sym}.csv"), "w")
            fh.write("ts,sym,open,high,low,close,volume\n")
            files[sym] = fh
        return files[sym]

    days = list(trading_days(dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)))
    defects = {d: kind for d, kind in zip(rng.sample(days, 6), ["ohlc", "ohlc", "dup", "dup", "thin", "thin"])}
    spot = 15200  # ticks ($1520.0)

    for day in days:
        day_vol = math.exp(rng.gauss(0.0, 0.35))
        trend = rng.gauss(0.0, 0.03) if rng.random() < 0.3 else 0.0
        front, nxt = code(contract_for(day, 0)), code(contract_for(day, 1))
        carry = {front: 15, nxt: 45}
        path = {}
        for ts in minutes_for(day, 1):
            m = ts.hour * 60 + ts.minute
            in_day = ts.date() == day
            sigma = 2.2 * day_vol * (2.0 if in_day and 500 <= m < 560 else 1.0)
            drift = trend * 4 if in_day and m >= 530 else 0.0
            o = spot
            spot = spot + int(round(rng.gauss(drift, sigma)))
            c = spot
            h = max(o, c) + int(abs(rng.gauss(0, sigma * 0.6)))
            l = min(o, c) - int(abs(rng.gauss(0, sigma * 0.6)))
            u = 3.0 if in_day and 500 <= m < 560 else (1.6 if in_day and m < 810 else 0.6)
            v = max(1, int(rng.lognormvariate(math.log(120 * u * day_vol), 0.5)))
            path[ts] = (o, h, l, c, v)

        thin = defects.get(day) == "thin"
        rows = []
        for ts, (o, h, l, c, v) in path.items():
            if thin and ts.date() == day and rng.random() < 0.4:
                continue
            rows.append((ts, front, o, h, l, c, v))
        if defects.get(day) == "ohlc":
            i = next(k for k, r in enumerate(rows) if r[0].date() == day and r[0].hour == 9)
            ts, s, o, h, l, c, v = rows[i]
            rows[i] = (ts, s, o, min(o, c) - 3, l, c, v)  # high below the body
        if defects.get(day) == "dup":
            i = next(k for k, r in enumerate(rows) if r[0].date() == day and r[0].hour == 10)
            rows.insert(i + 1, rows[i])
        for ts in minutes_for(day, 5):
            o, h, l, c, v = path[ts]
            rows.append((ts, nxt, o, h, l, c, max(1, v // 12)))

        for ts, sym, o, h, l, c, v in rows:
            off = carry[sym]
            writer(sym).write(f"{ts:%Y-%m-%dT%H:%M:%S},{sym},{(o + off) / 10:.1f},{(h + off) / 10:.1f},"
                              f"{(l + off) / 10:.1f},{(c + off) / 10:.1f},{v}\n")

    for fh in files.values():
        fh.close()
    print(f"wrote {len(files)} contract files for {len(days)} sessions to {args.out}; defects on "
          + ", ".join(f"{d} ({k})" for d, k in sorted(defects.items())))


if __name__ == "__main__":
    main()
