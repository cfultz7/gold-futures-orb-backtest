#!/usr/bin/env python3
"""Pure-Python mirror of the q pipeline (load -> validate -> roll -> features -> export).

    python tools/ref_pipeline.py --raw data/synth_raw --out export_ref

Two uses:
  * run the simulators without kdb+ (export_ref has the same layout as q/export.q's output)
  * cross-check the q pipeline: py/reconcile.py exports export export_ref

It follows the q scripts step by step, including how q's mavg is computed (difference of
running sums), so on the same raw data the two exports agree to within float rounding.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import os
from collections import defaultdict

# --- mirror of q/config.q
ROOT = "GC"
MCODES = "FGHJKMNQUVXZ"
SESS_OPEN = 8 * 60 + 20
SESS_LAST = 13 * 60 + 29
EXP_MIN = 310
OR_MINS = [5, 15, 30, 60]
ROLL_CONFIRM = 2
MIN_COVER = 0.9
MIN_HIST = 15
LOOKBACK = 20


def ordinal(sym: str):
    n = len(ROOT)
    if not sym.startswith(ROOT) or len(sym) <= n:
        return None
    m = MCODES.find(sym[n])
    if m < 0:
        return None
    try:
        y = int(sym[n + 1:])
    except ValueError:
        return None
    y = 2020 + y if y < 10 else (2000 + y if y < 100 else y)
    return 12 * y + m


def fin(x):
    return x is not None and not math.isinf(x) and not math.isnan(x)


def prev_mavg(xs, L):
    """q: prev L mavg x, and prev L mcount x (nulls = None)."""
    n = len(xs)
    s = [0.0] * n
    c = [0] * n
    run_s, run_c = 0.0, 0
    for i, v in enumerate(xs):
        if v is not None:
            run_s += v
            run_c += 1
        s[i], c[i] = run_s, run_c
    avg, cnt = [None] * n, [0] * n
    for i in range(1, n):
        j = i - 1
        ws = s[j] - (s[j - L] if j >= L else 0.0)
        wc = c[j] - (c[j - L] if j >= L else 0)
        cnt[i] = wc
        avg[i] = ws / wc if wc else None
    return avg, cnt


def realized(closes):
    tot = 0.0
    for a, b in zip(closes, closes[1:]):
        r = math.log(b / a)
        tot += r * r
    return math.sqrt(tot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/synth_raw")
    ap.add_argument("--out", default="export_ref")
    args = ap.parse_args()

    # ---- load: group by (trade date, contract); trade date = date(ts + 6h)
    sessions = defaultdict(list)
    for name in sorted(os.listdir(args.raw)):
        if not name.endswith(".csv"):
            continue
        with open(os.path.join(args.raw, name), newline="") as fh:
            for r in csv.DictReader(fh):
                ts = dt.datetime.fromisoformat(r["ts"])
                td = (ts + dt.timedelta(hours=6)).date()
                sessions[(td, r["sym"])].append(
                    (ts, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), int(r["volume"])))
    for v in sessions.values():
        v.sort(key=lambda b: b[0])

    # ---- validate: hard failures exclude the (date, contract) session
    excl = set()
    for key, bars in sessions.items():
        stamps = [b[0] for b in bars]
        bad = any(h < max(o, c) or l > min(o, c) or l > h for _, o, h, l, c, _ in bars)
        bad |= any(min(o, h, l, c) <= 0 for _, o, h, l, c, _ in bars)
        bad |= any(v < 0 for *_, v in bars)
        bad |= len(set(stamps)) != len(stamps)
        bad |= any(t.second or t.microsecond for t in stamps)
        if bad:
            excl.add(key)

    # ---- roll: lead by daily volume, confirm over prior sessions, never roll back
    dates = sorted({d for d, _ in sessions})
    vol = defaultdict(dict)
    for (d, s), bars in sessions.items():
        if ordinal(s) is not None:
            vol[d][s] = sum(b[5] for b in bars)
    lead = []
    for d in dates:
        if vol[d]:
            mx = max(vol[d].values())
            lead.append(min(s for s, v in vol[d].items() if v == mx))
        else:
            lead.append(None)
    o = [ordinal(s) if s else None for s in lead]
    conf = [None] * len(dates)
    for i in range(len(dates)):
        w = o[i - ROLL_CONFIRM:i] if i >= ROLL_CONFIRM else None
        conf[i] = None if (w is None or any(x is None for x in w)) else min(w)
    inv = {ordinal(s): s for d in dates for s in vol[d]}
    front, best = [], None
    for c in conf:
        if c is not None and (best is None or c > best):
            best = c
        front.append(inv[best] if best is not None else None)

    # ---- features
    day_rows, feat_rows, bar_rows = [], [], []
    for d, f in zip(dates, front):
        if f is None:
            continue
        b = [x for x in sessions.get((d, f), []) if SESS_OPEN <= x[0].hour * 60 + x[0].minute <= SESS_LAST]
        ex = (d, f) in excl
        n = len(b)
        day_rows.append({"date": d, "nWin": n, "excluded": ex, "rvDay": realized([x[4] for x in b]) if n else None})
        for k in OR_MINS:
            ob = [x for x in b if x[0].hour * 60 + x[0].minute < SESS_OPEN + k]
            feat_rows.append({
                "date": d, "sym": f, "orMin": k,
                "orHigh": max((x[2] for x in ob), default=-math.inf),
                "orLow": min((x[3] for x in ob), default=math.inf),
                "orVol": sum(x[5] for x in ob), "nOR": len(ob),
                "orRv": realized([x[4] for x in ob]) if ob else 0.0,
                "excluded": ex, "nWin": n,
            })
        if not ex:
            for x in b:
                bar_rows.append((d, x[0].hour * 60 + x[0].minute, f, x[1], x[2], x[3], x[4], x[5]))

    rv_use = [None if (r["excluded"] or r["nWin"] < MIN_COVER * EXP_MIN) else r["rvDay"] for r in day_rows]
    rv20, n_prior = prev_mavg(rv_use, LOOKBACK)
    by_date = {r["date"]: (rv20[i], n_prior[i]) for i, r in enumerate(day_rows)}

    for k in OR_MINS:
        rows = [r for r in feat_rows if r["orMin"] == k]
        ovv = [float(r["orVol"]) if (r["nOR"] == k and not r["excluded"]) else None for r in rows]
        avg, cnt = prev_mavg(ovv, LOOKBACK)
        for r, a, c in zip(rows, avg, cnt):
            r["rv20"], r["nPrior"] = by_date[r["date"]]
            if a is None:
                r["relVol"] = None
            elif a == 0.0:
                r["relVol"] = math.inf if r["orVol"] else None
            else:
                r["relVol"] = r["orVol"] / a
            r["nRel"] = c

    for r in feat_rows:
        r["cover"] = r["nWin"] / EXP_MIN
        rv = r["rv20"]
        mid = 0.5 * (r["orHigh"] + r["orLow"])
        try:
            r["wToV"] = (r["orHigh"] - r["orLow"]) / (rv * mid) if rv is not None else None
        except ZeroDivisionError:
            r["wToV"] = None
        r["ok"] = (not r["excluded"] and r["nOR"] == r["orMin"] and r["cover"] >= MIN_COVER
                   and r["nPrior"] >= MIN_HIST and r["nRel"] >= MIN_HIST and rv is not None and rv > 0
                   and fin(r["relVol"]) and fin(r["wToV"]) and r["orHigh"] > r["orLow"])
        for col in ("orHigh", "orLow", "orRv", "rv20", "relVol", "wToV"):
            if not fin(r[col]):
                r[col] = 0.0

    def ymd(d):
        return d.year * 10000 + d.month * 100 + d.day

    os.makedirs(args.out, exist_ok=True)
    cols = ["date", "sym", "orMin", "orHigh", "orLow", "orVol", "nOR", "orRv", "rv20", "relVol", "wToV",
            "cover", "nPrior", "nRel", "ok"]
    feat_rows.sort(key=lambda r: (r["date"], r["orMin"]))
    with open(os.path.join(args.out, "feat.csv"), "w") as fh:
        fh.write(",".join(cols) + "\n")
        for r in feat_rows:
            vals = dict(r, date=ymd(r["date"]), ok=int(r["ok"]))
            fh.write(",".join(repr(vals[c]) if isinstance(vals[c], float) else str(vals[c]) for c in cols) + "\n")
    with open(os.path.join(args.out, "bars.csv"), "w") as fh:
        fh.write("date,tmin,sym,open,high,low,close,volume\n")
        for d, t, s, o, h, l, c, v in bar_rows:
            fh.write(f"{ymd(d)},{t},{s},{o!r},{h!r},{l!r},{c!r},{v}\n")

    rolls = sum(1 for a, b in zip(front, front[1:]) if a != b and b is not None)
    print(f"sessions {len(dates)}, with front {len(day_rows)}, rolls {rolls}, excluded {len(excl)}, "
          f"tradable (or=15) {sum(1 for r in feat_rows if r['orMin'] == 15 and r['ok'])}")
    print(f"wrote {len(feat_rows)} feature rows and {len(bar_rows)} bars to {args.out}")


if __name__ == "__main__":
    main()
