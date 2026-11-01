#!/usr/bin/env python3
"""Stand-in for q/server.q that speaks the kdb+ IPC wire protocol. Test fixture only.

    python tools/mock_q_server.py --data export --port 5010

Serves export/feat.csv + export/bars.csv with the same messages q/server.q sends
((`day; date; features; bars) per session, then (`done; n)), so the C++ IPC client in
cpp/src/kdb_source.cpp can be tested without a kdb+ license. It handles one client and exits.
It does not exercise q/server.q itself; run the real server for that.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import socket
import struct

EPOCH = dt.date(2000, 1, 1)


def kdate(yyyymmdd: int) -> int:
    return (dt.date(yyyymmdd // 10000, yyyymmdd // 100 % 100, yyyymmdd % 100) - EPOCH).days


def ymd(kd: int) -> int:
    d = EPOCH + dt.timedelta(days=kd)
    return d.year * 10000 + d.month * 100 + d.day


# ---- serialization (little endian)
def sym_atom(s):
    return b"\xf5" + s.encode() + b"\0"


def date_atom(v):
    return struct.pack("<bi", -14, v)


def long_atom(v):
    return struct.pack("<bq", -7, v)


def vec(t, fmt, xs):
    return struct.pack("<bbi", t, 0, len(xs)) + struct.pack(f"<{len(xs)}{fmt}", *xs)


def sym_vec(xs):
    return struct.pack("<bbi", 11, 0, len(xs)) + b"".join(s.encode() + b"\0" for s in xs)


def glist(items):
    return struct.pack("<bbi", 0, 0, len(items)) + b"".join(items)


def table(cols):  # cols: list of (name, encoded vector)
    return b"\x62\x00\x63" + sym_vec([c for c, _ in cols]) + glist([v for _, v in cols])


def message(payload, kind=0):
    return struct.pack("<bbbbi", 1, kind, 0, 0, 8 + len(payload)) + payload


def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("client closed")
        buf += chunk
    return buf


def load(path):
    feat, bars = {}, {}
    num = lambda s: float(s[:-1] if s.endswith("f") else s)  # noqa: E731
    with open(os.path.join(path, "feat.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            feat.setdefault(int(r["date"]), []).append(r)
    with open(os.path.join(path, "bars.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            bars.setdefault(int(r["date"]), []).append(r)
    return feat, bars, num


def day_message(d, frows, brows, num):
    kd = kdate(d)
    ft = table([
        ("date", vec(14, "i", [kd] * len(frows))),
        ("sym", sym_vec([r["sym"] for r in frows])),
        ("orMin", vec(7, "q", [int(r["orMin"]) for r in frows])),
        ("orHigh", vec(9, "d", [num(r["orHigh"]) for r in frows])),
        ("orLow", vec(9, "d", [num(r["orLow"]) for r in frows])),
        ("relVol", vec(9, "d", [num(r["relVol"]) for r in frows])),
        ("wToV", vec(9, "d", [num(r["wToV"]) for r in frows])),
        ("ok", vec(1, "B", [int(r["ok"]) for r in frows])),
    ])
    bt = table([
        ("date", vec(14, "i", [kd] * len(brows))),
        ("sym", sym_vec([r["sym"] for r in brows])),
        ("tmin", vec(7, "q", [int(r["tmin"]) for r in brows])),
        ("open", vec(9, "d", [num(r["open"]) for r in brows])),
        ("high", vec(9, "d", [num(r["high"]) for r in brows])),
        ("low", vec(9, "d", [num(r["low"]) for r in brows])),
        ("close", vec(9, "d", [num(r["close"]) for r in brows])),
        ("volume", vec(7, "q", [int(r["volume"]) for r in brows])),
    ])
    return message(glist([sym_atom("day"), date_atom(kd), ft, bt]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="export")
    ap.add_argument("--port", type=int, default=5010)
    ap.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for the client")
    args = ap.parse_args()
    feat, bars, num = load(args.data)

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", args.port))
    srv.listen(1)
    srv.settimeout(args.timeout)
    print(f"mock q server: {len(feat)} sessions on port {args.port}", flush=True)
    try:
        conn, _ = srv.accept()
    except socket.timeout:
        raise SystemExit(f"mock q server: no client within {args.timeout}s")
    conn.settimeout(args.timeout)
    with conn:
        hello = b""
        while not hello.endswith(b"\0"):  # "user:pass" + capability byte + NUL
            hello += recv_exact(conn, 1)
        conn.sendall(bytes([min(hello[-2], 3)]))

        head = recv_exact(conn, 8)
        body = recv_exact(conn, struct.unpack("<i", head[4:8])[0] - 8)
        # (".orb.stream"; d0; d1): general list -> char vector, date atom, date atom
        n_fn = struct.unpack("<i", body[8:12])[0]
        fn = body[12:12 + n_fn].decode()
        p = 12 + n_fn
        d0 = struct.unpack("<i", body[p + 1:p + 5])[0]
        d1 = struct.unpack("<i", body[p + 6:p + 10])[0]
        lo, hi = ymd(d0), ymd(d1)
        print(f"request {fn}[{lo};{hi}] (async={head[1] == 0})", flush=True)

        days = [d for d in sorted(feat) if lo <= d <= hi]
        for d in days:
            conn.sendall(day_message(d, feat[d], bars.get(d, []), num))
        conn.sendall(message(glist([sym_atom("done"), long_atom(len(days))])))
        print(f"streamed {len(days)} sessions", flush=True)
        try:
            conn.recv(1)  # wait for the client to hang up
        except OSError:
            pass


if __name__ == "__main__":
    main()
