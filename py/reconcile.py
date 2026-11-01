#!/usr/bin/env python3
"""Reconcile simulator outputs.

    python py/reconcile.py grid out_py out_cpp       # Python simulator vs C++ wf_grid: every trade of
                                                     # every config, fold stats, selections, OOS P&L
    python py/reconcile.py bt out_cpp out_bt         # wf_grid's OOS trades vs orb_bt's event-driven run
    python py/reconcile.py exports export export_ref [--tol 1e-9]
                                                     # q export vs tools/ref_pipeline.py export

grid and bt require exact equality: prices and P&L are integer ticks, and the floating-point
statistics are accumulated in the same order in both languages. exports allows a relative
tolerance on floats (q computes mavg from running sums, so the last bits can differ).
Exit status is 0 only if everything matches.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys

SKIP_JSON = {"study_seconds", "engine"}


def as_num(s: str):
    t = s.strip()
    if t.endswith("f"):
        t = t[:-1]
    try:
        return float(t)
    except ValueError:
        return None


def same(a: str, b: str, tol: float) -> bool:
    if a == b:
        return True
    x, y = as_num(a), as_num(b)
    if x is None or y is None:
        return False
    if x == y or (math.isnan(x) and math.isnan(y)):
        return True
    return tol > 0 and abs(x - y) <= tol * max(1.0, abs(x), abs(y))


def compare_csv(label, pa, pb, tol=0.0, show=5) -> bool:
    if not (os.path.exists(pa) and os.path.exists(pb)):
        missing = [p for p in (pa, pb) if not os.path.exists(p)]
        print(f"  {label:<22} SKIP (missing {', '.join(missing)})")
        return True
    with open(pa, newline="") as fa, open(pb, newline="") as fb:
        ra, rb = list(csv.reader(fa)), list(csv.reader(fb))
    if ra[0] != rb[0]:
        print(f"  {label:<22} FAIL header differs: {ra[0]} vs {rb[0]}")
        return False
    bad, shown = 0, 0
    for i, (x, y) in enumerate(zip(ra[1:], rb[1:]), start=2):
        diffs = [(ra[0][j], x[j], y[j]) for j in range(len(x)) if not same(x[j], y[j], tol)]
        if diffs:
            bad += 1
            if shown < show:
                print(f"      line {i}: " + "; ".join(f"{c}: {u} != {v}" for c, u, v in diffs))
                shown += 1
    n = len(ra) - 1
    if len(ra) != len(rb):
        print(f"  {label:<22} FAIL row count {len(ra) - 1} vs {len(rb) - 1} ({bad} differing rows in the overlap)")
        return False
    print(f"  {label:<22} {'OK  ' if not bad else 'FAIL'} {n} rows" + (f", {bad} differ" if bad else ""))
    return bad == 0


def compare_json(label, pa, pb) -> bool:
    with open(pa) as fa, open(pb) as fb:
        a, b = json.load(fa), json.load(fb)
    diffs = []

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                if k in SKIP_JSON:
                    continue
                walk(x.get(k), y.get(k), f"{path}.{k}")
        elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            for i, (u, v) in enumerate(zip(x, y)):
                walk(u, v, f"{path}[{i}]")
        elif x != y:
            diffs.append(f"{path}: {x!r} != {y!r}")

    walk(a, b, "")
    print(f"  {label:<22} {'OK' if not diffs else 'FAIL'}")
    for d in diffs[:10]:
        print("      " + d)
    return not diffs


def main():
    ap = argparse.ArgumentParser(description="Reconcile simulator outputs")
    ap.add_argument("mode", choices=["grid", "bt", "exports"])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--tol", type=float, default=1e-9, help="relative float tolerance for 'exports'")
    args = ap.parse_args()
    A, B = args.a, args.b
    j = os.path.join
    ok = True
    print(f"reconcile {args.mode}: {A} vs {B}")
    if args.mode == "grid":
        ok &= compare_csv("grid_trades.csv", j(A, "grid_trades.csv"), j(B, "grid_trades.csv"))
        ok &= compare_csv("grid_fold_stats.csv", j(A, "grid_fold_stats.csv"), j(B, "grid_fold_stats.csv"))
        ok &= compare_csv("wf_selection.csv", j(A, "wf_selection.csv"), j(B, "wf_selection.csv"))
        ok &= compare_csv("wf_trades.csv", j(A, "wf_trades.csv"), j(B, "wf_trades.csv"))
        ok &= compare_csv("wf_daily.csv", j(A, "wf_daily.csv"), j(B, "wf_daily.csv"))
        ok &= compare_json("wf_summary.json", j(A, "wf_summary.json"), j(B, "wf_summary.json"))
    elif args.mode == "bt":
        ok &= compare_csv("trades", j(A, "wf_trades.csv"), j(B, "bt_trades.csv"))
        ok &= compare_csv("daily P&L", j(A, "wf_daily.csv"), j(B, "bt_daily.csv"))
        ok &= compare_json("summary", j(A, "wf_summary.json"), j(B, "bt_summary.json"))
    else:
        ok &= compare_csv("feat.csv", j(A, "feat.csv"), j(B, "feat.csv"), tol=args.tol)
        ok &= compare_csv("bars.csv", j(A, "bars.csv"), j(B, "bars.csv"), tol=args.tol)
    print("MATCH" if ok else "MISMATCH")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
