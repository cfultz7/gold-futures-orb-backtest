#!/usr/bin/env python3
"""Download GC one-minute bars for every listed contract from Databento (CME Globex, GLBX.MDP3).

    pip install databento
    export DATABENTO_API_KEY=db-xxxxxxxx

    python tools/fetch_databento.py                 # prints Databento's price quote, downloads nothing
    python tools/fetch_databento.py --yes           # downloads and writes data/vendor/gc_ohlcv1m.csv

Then convert for q/load.q:
    python tools/prepare_data.py --vendor databento --src data/vendor/gc_ohlcv1m.csv --out data/raw

The request uses parent symbology (GC.FUT), so it returns each contract separately (GCG0, GCJ0, ...)
rather than a spliced continuous series; the roll logic in q/roll.q needs the individual contracts.
The default start (2019-12-01) gives the features their 20-session warm-up before 2020.
"""
from __future__ import annotations

import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-12-01", help="inclusive, UTC")
    ap.add_argument("--end", default="2025-01-01", help="exclusive, UTC")
    ap.add_argument("--out", default="data/vendor/gc_ohlcv1m.csv")
    ap.add_argument("--yes", action="store_true", help="actually download (this is billed to your account)")
    args = ap.parse_args()

    try:
        import databento as db
    except ImportError:
        sys.exit("pip install databento")
    if not os.environ.get("DATABENTO_API_KEY"):
        sys.exit("set DATABENTO_API_KEY (from the API keys page of your Databento portal)")

    client = db.Historical()
    params = dict(dataset="GLBX.MDP3", schema="ohlcv-1m", symbols=["GC.FUT"], stype_in="parent",
                  start=args.start, end=args.end)
    cost = client.metadata.get_cost(**params)
    size = client.metadata.get_billable_size(**params)
    records = client.metadata.get_record_count(**params)
    print(f"GLBX.MDP3 ohlcv-1m GC.FUT {args.start} -> {args.end}: {records:,} bars, "
          f"{size / 1e9:.3f} GB billable, quoted ${cost:,.2f}")
    print("(new accounts get a one-time data credit; the quote above is before credits)")
    if not args.yes:
        print("nothing downloaded; rerun with --yes to download")
        return

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    dbn_path = os.path.splitext(args.out)[0] + ".dbn.zst"
    store = client.timeseries.get_range(**params, path=dbn_path)
    store.to_csv(args.out, pretty_px=True, pretty_ts=True, map_symbols=True)
    print(f"wrote {dbn_path} (raw) and {args.out}")


if __name__ == "__main__":
    main()
