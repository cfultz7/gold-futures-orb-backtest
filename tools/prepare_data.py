#!/usr/bin/env python3
"""Convert vendor one-minute files into the input q/load.q expects.

    python tools/prepare_data.py --vendor databento --src data/vendor/gc_ohlcv1m.csv --out data/raw
    python tools/prepare_data.py --vendor firstrate --src data/vendor/firstrate_gc  --out data/raw

Output: one CSV per contract, header ts,sym,open,high,low,close,volume, ts = bar START time in
America/New_York ("2020-01-02T08:20:00"), contract codes with two-digit years (GCZ24).

Vendors
  databento  CSV from tools/fetch_databento.py, or a portal download in CSV with symbol mapping on.
             ts_event is the UTC bar start (ISO text or integer nanoseconds); prices decimal text or
             1e-9 fixed point. Spreads (GCZ4-GCG5) are dropped.
  firstrate  FirstRate Data individual-contract files: no header, timestamp,open,high,low,close,volume
             in US Eastern; the contract comes from the file name (GC_Z24_1min.txt -> GCZ24).
  utc-csv    ts,sym,open,high,low,close,volume with UTC timestamps.
  et-csv     ts,sym,open,high,low,close,volume with ET timestamps (filtered and checked only).

--bar-end    the vendor stamps bars with their END time: shift back one minute.
--start/--end limit to trade dates (inclusive).

The report at the end lists the busiest minutes of the day in ET. For GC they should be weekday
mornings ET (around the 08:20 open, 08:30 data releases, 10:00). A peak in the afternoon usually
means the timestamps were read in the wrong timezone.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import sys
from collections import Counter
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
MONTHS = "FGHJKMNQUVXZ"


def contract_code(raw: str, root: str, seen: dt.date):
    """Outright code with a two-digit year, or None for spreads / other roots.

    One-digit years (GCZ4) are resolved against the date the bar was observed: the contract year
    is the first year >= that date's year ending in that digit.
    """
    m = re.fullmatch(re.escape(root) + r"([FGHJKMNQUVXZ])(\d{1,4})", raw.strip())
    if not m:
        return None
    month, y = m.group(1), m.group(2)
    if len(y) == 1:
        year = seen.year + (int(y) - seen.year % 10) % 10
    elif len(y) == 2:
        year = 2000 + int(y)
    else:
        year = int(y)
    return f"{root}{month}{year % 100:02d}"


def parse_price(s: str) -> float:
    s = s.strip()
    if "." in s or "e" in s or "E" in s:
        return float(s)
    v = int(s)
    return v / 1e9 if abs(v) > 10**7 else float(v)  # Databento fixed point is 1e-9 units


def parse_utc(s: str) -> dt.datetime:
    s = s.strip()
    if s.isdigit():  # nanoseconds since the UNIX epoch
        return dt.datetime.fromtimestamp(int(s) // 1_000_000_000, UTC)
    return dt.datetime.fromisoformat(s[:19].replace(" ", "T")).replace(tzinfo=UTC)


def parse_local(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.strip()[:19].replace(" ", "T"))


def rows_databento(path):
    with open(path, newline="") as fh:
        r = csv.DictReader(fh)
        if "symbol" not in (r.fieldnames or []):
            sys.exit(f"{path}: no 'symbol' column; export the CSV with symbol mapping on (map_symbols=True)")
        for x in r:
            ts = parse_utc(x["ts_event"]).astimezone(ET).replace(tzinfo=None)
            yield ts, x["symbol"], x["open"], x["high"], x["low"], x["close"], x["volume"]


def rows_firstrate(path, root):
    name = os.path.basename(path)
    m = re.match(re.escape(root) + r"_([FGHJKMNQUVXZ])(\d{2})", name)
    if not m:
        sys.exit(f"{name}: expected a FirstRate contract file name like {root}_Z24_1min.txt")
    sym = f"{root}{m.group(1)}{m.group(2)}"
    with open(path, newline="") as fh:
        for x in csv.reader(fh):
            if not x or not x[0][:1].isdigit():
                continue
            yield parse_local(x[0]), sym, x[1], x[2], x[3], x[4], x[5]


def rows_plain(path, utc: bool):
    with open(path, newline="") as fh:
        for x in csv.DictReader(fh):
            ts = parse_utc(x["ts"]).astimezone(ET).replace(tzinfo=None) if utc else parse_local(x["ts"])
            yield ts, x["sym"], x["open"], x["high"], x["low"], x["close"], x["volume"]


def main():
    ap = argparse.ArgumentParser(description="vendor files -> q/load.q input")
    ap.add_argument("--vendor", required=True, choices=["databento", "firstrate", "utc-csv", "et-csv"])
    ap.add_argument("--src", required=True, help="a file or a directory of .csv/.txt files")
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--root", default="GC")
    ap.add_argument("--bar-end", action="store_true")
    ap.add_argument("--start", help="first trade date, YYYY-MM-DD")
    ap.add_argument("--end", help="last trade date, YYYY-MM-DD")
    args = ap.parse_args()

    if os.path.isdir(args.src):
        paths = sorted(os.path.join(args.src, f) for f in os.listdir(args.src) if f.endswith((".csv", ".txt")))
    else:
        paths = [args.src]
    if not paths:
        sys.exit(f"no .csv or .txt files in {args.src}")
    if os.path.isdir(args.out) and any(f.endswith(".csv") for f in os.listdir(args.out)):
        sys.exit(f"{args.out} already has CSV files; use an empty directory")
    os.makedirs(args.out, exist_ok=True)

    start = dt.date.fromisoformat(args.start) if args.start else None
    end = dt.date.fromisoformat(args.end) if args.end else None
    shift = dt.timedelta(minutes=1 if args.bar_end else 0)
    six = dt.timedelta(hours=6)

    files, per_sym, by_minute, dropped = {}, Counter(), Counter(), Counter()
    first = last = None
    for path in paths:
        if args.vendor == "databento":
            rows = rows_databento(path)
        elif args.vendor == "firstrate":
            rows = rows_firstrate(path, args.root)
        else:
            rows = rows_plain(path, utc=args.vendor == "utc-csv")
        for ts, raw_sym, o, h, l, c, v in rows:
            ts -= shift
            tdate = (ts + six).date()  # Globex trade date: 18:00 ET starts the next one
            if (start and tdate < start) or (end and tdate > end):
                dropped["outside date range"] += 1
                continue
            sym = contract_code(raw_sym, args.root, ts.date())
            if sym is None:
                dropped["spread or other symbol"] += 1
                continue
            fh = files.get(sym)
            if fh is None:
                fh = files[sym] = open(os.path.join(args.out, f"{sym}.csv"), "w")
                fh.write("ts,sym,open,high,low,close,volume\n")
            vol = int(float(v))
            fh.write(f"{ts:%Y-%m-%dT%H:%M:%S},{sym},{parse_price(o)!r},{parse_price(h)!r},"
                     f"{parse_price(l)!r},{parse_price(c)!r},{vol}\n")
            per_sym[sym] += 1
            if ts.weekday() < 5:
                by_minute[ts.hour * 60 + ts.minute] += vol
            first = ts if first is None or ts < first else first
            last = ts if last is None or ts > last else last
    for fh in files.values():
        fh.close()

    if not per_sym:
        sys.exit("no rows written; check --vendor, --root and the date range")
    print(f"wrote {sum(per_sym.values()):,} bars for {len(per_sym)} contracts to {args.out}")
    print(f"first bar {first:%Y-%m-%d %H:%M} ET, last bar {last:%Y-%m-%d %H:%M} ET")
    for k, n in dropped.items():
        print(f"dropped {n:,} rows: {k}")
    print("contracts with the most bars: " + ", ".join(f"{s} {n:,}" for s, n in per_sym.most_common(6)))
    top5 = [m for m, _ in by_minute.most_common(5)]
    print("busiest minutes of the day (ET, by volume): " + ", ".join(f"{m // 60:02d}:{m % 60:02d}" for m in top5))
    # GC volume spikes at 08:30 and 10:00 ET (data releases) and 13:29 ET (the settlement minute).
    # Bars stamped at their end would put those spikes at 08:31 / 10:01 / 13:30; a timezone error
    # moves them by whole hours.
    markers = {8 * 60 + 30, 10 * 60, 13 * 60 + 29}
    if not markers & set(top5):
        late = {m - 1 for m in top5} & markers
        hint = "bars look stamped at their END: rerun with --bar-end" if late else "check the timezone"
        print(f"WARNING: none of 08:30, 10:00, 13:29 ET is among the busiest minutes; {hint}")


if __name__ == "__main__":
    main()
