"""Parser for config/orb.cfg, the settings file shared with the C++ programs.

Format: `key = value` lines, `#` comments, comma-separated lists. The C++ side
(cpp/src/config.cpp) parses the same file with the same rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


@dataclass(frozen=True)
class Params:
    idx: int
    or_min: int
    stop_frac: float
    target_r: float
    min_relvol: float
    max_wtov: float


@dataclass(frozen=True)
class Fold:
    test_start: int  # yyyymmdd, inclusive
    test_end: int    # yyyymmdd, inclusive


@dataclass
class Config:
    tick: float
    tick_value: float
    fee_per_side: float
    slip_ticks: int
    sess_open: int      # minutes after midnight ET
    sess_close: int
    entry_cutoff: int
    grid: list[Params]
    folds: list[Fold]
    train_years: int
    min_trades: int


def load(path: str) -> Config:
    kv: dict[str, str] = {}
    with open(path) as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()

    def flist(key: str) -> list[float]:
        return [float(x) for x in kv[key].split(",")]

    or_mins = [int(x) for x in kv["grid.or_min"].split(",")]
    # Grid order is fixed: or_min outermost, max_wtov innermost. The C++ side builds the
    # same nesting, so config index i means the same parameters in both programs.
    grid = [
        Params(i, om, sf, tr, rv, wv)
        for i, (om, sf, tr, rv, wv) in enumerate(
            product(or_mins, flist("grid.stop_frac"), flist("grid.target_r"),
                    flist("grid.min_relvol"), flist("grid.max_wtov"))
        )
    ]
    folds = []
    for item in kv["folds"].split(","):
        a, b = item.strip().split(":")
        folds.append(Fold(int(a), int(b)))

    return Config(
        tick=float(kv["tick"]),
        tick_value=float(kv["tick_value"]),
        fee_per_side=float(kv["fee_per_side"]),
        slip_ticks=int(kv["slip_ticks"]),
        sess_open=_hhmm(kv["sess_open"]),
        sess_close=_hhmm(kv["sess_close"]),
        entry_cutoff=_hhmm(kv["entry_cutoff"]),
        grid=grid,
        folds=folds,
        train_years=int(kv["train_years"]),
        min_trades=int(kv["min_trades"]),
    )
