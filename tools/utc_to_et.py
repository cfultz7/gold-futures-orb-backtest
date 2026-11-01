#!/usr/bin/env python3
"""Convert vendor 1-minute CSVs from UTC to America/New_York bar-start times for q/load.q.

    python tools/utc_to_et.py --src vendor_utc --out data/raw [--bar-end]

Input columns: ts,sym,open,high,low,close,volume with ts in UTC ("2020-01-02 13:20:00",
"2020-01-02T13:20:00" or with a trailing Z). Pass --bar-end if the vendor stamps bars with
their END time; they are shifted back one minute so every timestamp is a bar start.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bar-end", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    shift = dt.timedelta(minutes=1 if args.bar_end else 0)
    for name in sorted(os.listdir(args.src)):
        if not name.endswith(".csv"):
            continue
        n = 0
        with open(os.path.join(args.src, name), newline="") as fi, open(os.path.join(args.out, name), "w") as fo:
            fo.write("ts,sym,open,high,low,close,volume\n")
            for r in csv.DictReader(fi):
                ts = dt.datetime.fromisoformat(r["ts"].replace(" ", "T").rstrip("Z")).replace(tzinfo=dt.timezone.utc)
                et = (ts - shift).astimezone(ET)
                fo.write(f"{et:%Y-%m-%dT%H:%M:%S},{r['sym']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}\n")
                n += 1
        print(f"{name}: {n} rows")


if __name__ == "__main__":
    main()
