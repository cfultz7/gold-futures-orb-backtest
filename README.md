# GC opening-range breakout: kdb+/q pipeline, C++ backtester, walk-forward study

Reference implementation of three pieces:

1. **q pipeline** — a date-partitioned kdb+ database of GC one-minute bars, data validation,
   session features (opening range, realized volatility, relative volume) and a look-ahead-safe
   contract roll.
2. **Event-driven C++ backtester** — features and bars streamed from q over kdb+ IPC, opening-range
   breakout strategy, fees and slippage, six walk-forward folds with 2022–2024 out of sample.
3. **432-configuration walk-forward study** in Python and a multithreaded C++ port, reconciled to
   identical trades and P&L.

## Layout

```
config/orb.cfg            strategy, costs, grid and folds; parsed by both Python and C++
q/config.q                pipeline parameters (session times must match orb.cfg)
q/load.q                  vendor CSVs -> db/<trade date>/bars/ (parted on sym)
q/validate.q              QA report + excluded (date, contract) sessions
q/roll.q                  front-month calendar
q/features.q              per-session features and window bars
q/export.q                features and bars -> CSV for the simulators
q/server.q                IPC server that streams sessions to orb_bt
py/orb_sim.py             walk-forward study, reference Python version
py/reconcile.py           exact diff of Python vs C++ and wf_grid vs orb_bt outputs
cpp/include/orb/          config, types, strategy state machine, stats, engine, sources
cpp/src/wf_grid.cpp       multithreaded port of orb_sim.py
cpp/src/orb_bt.cpp        event-driven backtester (CSV replay or kdb+ IPC source)
cpp/src/kdb_source.cpp    kdb+ IPC client (C API: k.h + c.o)
tools/make_synth.py       synthetic raw bars for testing
tools/ref_pipeline.py     Python mirror of the q pipeline (runs without kdb+, cross-checks q)
tools/mock_q_server.py    kdb+ wire-protocol stand-in for server.q (tests the C++ IPC client)
tools/fetch_databento.py  downloads every GC contract's 1-minute bars from Databento (quote first)
tools/prepare_data.py     Databento / FirstRate / generic vendor files -> load.q input, with checks
tools/utc_to_et.py        converts UTC vendor files to the ET bar-start format load.q expects
scripts/test_synthetic.sh end-to-end test with no kdb+ and no market data
scripts/run_q_pipeline.sh end-to-end run on real data with kdb+
```

## Requirements

* kdb+ 4.x (`q` on PATH) for the pipeline and server. The free personal edition works.
* C++17 compiler, CMake ≥ 3.16. For the IPC source: `k.h` and `c.o` from
  [KxSystems/kdb](https://github.com/KxSystems/kdb) (`c/c/k.h`, `l64/c.o` or `m64/c.o`).
* Python 3.9+ (standard library only).

```bash
cmake -S cpp -B cpp/build -DORB_WITH_KDB=ON -DKDB_C_DIR=/path/to/kx   # omit the flags for CSV-only
cmake --build cpp/build -j
```

## Getting the data

The pipeline needs one-minute bars for **each individual GC contract** (GCG20, GCJ20, …), not a
spliced continuous series, because `roll.q` picks the front contract itself. Start a month before
2020 so the 20-session trailing features are warmed up by January 2020.

**Databento** (CME Globex feed, billed per GB, with a quote before you pay):

```bash
pip install databento
export DATABENTO_API_KEY=db-...                 # from the API keys page of the Databento portal
python3 tools/fetch_databento.py                # prints bars, GB and price; downloads nothing
python3 tools/fetch_databento.py --yes          # downloads data/vendor/gc_ohlcv1m.csv
python3 tools/prepare_data.py --vendor databento --src data/vendor/gc_ohlcv1m.csv --out data/raw
```

**FirstRate Data** (individual-contract files, US Eastern timestamps):

```bash
python3 tools/prepare_data.py --vendor firstrate --src path/to/unzipped_gc_files --out data/raw
```

**Anything else**: get it into `ts,sym,open,high,low,close,volume` and use `--vendor utc-csv` or
`--vendor et-csv`. Add `--bar-end` if the vendor stamps bars with their end time.

`prepare_data.py` drops spreads, turns one-digit years (GCZ4) into two-digit ones using the bar's
date, converts to ET bar-start times and prints the busiest minutes of the day. For GC those
include 08:30 and 10:00 ET (economic releases) and 13:29 ET (the settlement minute); it warns if
none of them show up, which usually means the timezone or the bar-start/bar-end convention is off.

## Installing kdb+

* Get q from KX (the free KDB-X Community Edition is at developer.kx.com) and put `q` on PATH.
* For the C++ IPC client, fetch the C API files and build with them:

```bash
mkdir -p third_party/kx
curl -L -o third_party/kx/k.h https://raw.githubusercontent.com/KxSystems/kdb/master/c/c/k.h
curl -L -o third_party/kx/c.o https://raw.githubusercontent.com/KxSystems/kdb/master/l64/c.o
#   macOS (Intel or Apple Silicon): use m64/c.o instead of l64/c.o.  Windows: build inside WSL.
cmake -S cpp -B cpp/build -DORB_WITH_KDB=ON -DKDB_C_DIR=$PWD/third_party/kx
cmake --build cpp/build -j
```

## Running

No kdb+ and no data needed:

```bash
scripts/test_synthetic.sh
```

With real data (one CSV per contract, `ts,sym,open,high,low,close,volume`, `ts` = bar start in
America/New_York as `2020-01-02T08:20:00`):

```bash
scripts/run_q_pipeline.sh data/raw
```

Or step by step:

```bash
q q/load.q -raw data/raw -db db
q q/validate.q -db db -qa qa
q q/roll.q -db db -qa qa
q q/features.q -db db -qa qa -work work
q q/export.q -work work -out export

python3 py/orb_sim.py --data export --out out_py              # Python study
cpp/build/wf_grid    --data export --out out_cpp             # C++ study (all cores)
python3 py/reconcile.py grid out_py out_cpp                  # must print MATCH

q q/server.q -work work -p 5010 &                             # stream over IPC
cpp/build/orb_bt --source kdb --port 5010 --selection out_cpp/wf_selection.csv --out out_bt
python3 py/reconcile.py bt out_cpp out_bt                    # must print MATCH
```

Each study writes `wf_summary.json` (out-of-sample net Sharpe, trades, P&L, drawdown, per-fold
breakdown and runtime), `wf_selection.csv`, `wf_trades.csv`, `wf_daily.csv`, `grid_fold_stats.csv`
and `grid_trades.csv` (every trade of every configuration).

## Design

### Data conventions
* Timestamps are bar **start** times in America/New_York. `tools/utc_to_et.py` converts UTC
  files and shifts bar-end stamps.
* Trade date = calendar date of `ts + 6h`, so the 18:00 Globex reopen belongs to the next trade
  date (CME convention). Partitions are trade dates.
* Prices become integer ticks (`floor(px/0.1 + 0.5)`) as soon as the simulators read them.

### Validation (`validate.q`)
Hard checks exclude a (trade date, contract) session: broken OHLC ordering, non-positive prices,
negative volume, duplicate timestamps, off-minute stamps, wrong partition. One-minute log returns
above 5% are flagged but kept. Excluded sessions never trade and drop out of trailing averages.

### Roll (`roll.q`) — why it is look-ahead safe
`front(d)` is decided only from sessions that finished before `d` opened:
1. `lead(d)` = contract with the most volume on trade date `d`.
2. `conf(d)` = min contract ordinal of `lead` over the 2 sessions **before** `d`
   (a new contract takes over only after leading 2 completed sessions in a row).
3. `front(d)` = running max of `conf` (never rolls backwards).

No back-adjusted series is built: every trade opens and closes within one session on the
contract that was front at the open, so there is nothing to splice.

### Features (`features.q`)
Window = 08:20–13:30 ET (COMEX day session). For each opening-range length in {5, 15, 30, 60}:
OR high/low/volume, realized vol inside the range, `rv20` (mean daily realized vol over the 20
prior sessions), `relVol` (OR volume ÷ mean OR volume over the 20 prior sessions), `wToV`
(OR width ÷ rv20 × price), coverage, and an `ok` flag (complete range, ≥ 90% coverage, ≥ 15
sessions of history, finite values, not excluded). Every input to a row is known when the opening
range closes; trailing statistics use `prev`, so today never enters its own baseline.

### Strategy and fills (`cpp/include/orb/strategy.hpp`, `run_session` in `py/orb_sim.py`)
* Filters: `ok`, `relVol ≥ min_relvol`, `wToV ≤ max_wtov`.
* Entry: stop one tick beyond the OR high (long) or low (short), first breakout only, until 13:00.
  Fill = worse of trigger and bar open, plus 1 tick slippage. A bar that crosses both sides is
  ambiguous at one-minute resolution, so that session is skipped.
* Stop = `round(stop_frac × OR width)` from entry; target = `round(target_r × stop)`.
* Intrabar order: on the entry bar only the stop is checked. Later bars: gap through stop at the
  open, gap through target at the open, then stop, then target, so a bar that touches both is a
  loss. Stops and the end-of-session exit pay slippage; the target is a resting limit.
* Flat at the close of the last window bar. Costs: $2.50 per side per contract, $10 per tick.

### Walk-forward
Grid (4 × 3 × 3 × 4 × 3 = 432): OR length, stop fraction, target multiple, min relative volume,
max width-to-vol. Each configuration is simulated once over all sessions; each session's result
depends only on that session's bars and its lagged features, so for a fold the in-sample Sharpe
is computed over sessions before the fold opens (anchored at the first date; `train_years` gives a
rolling window). The configuration with the highest in-sample Sharpe and at least 30 in-sample
trades is traded out of sample for that half-year. Sharpe = mean / sd of daily P&L × √252, with
no-trade days counted as zero.

### Why Python and C++ agree exactly
* All prices and P&L are integer ticks or exact multiples of $5.
* Sums are plain left-to-right loops in both languages (Python's `sum()` is avoided: on 3.12+ it
  uses compensated summation).
* C++ builds with `-ffp-contract=off` so no fused multiply-adds slip in.
* Both read the grid from `config/orb.cfg` in the same nesting order; `orb_bt` refuses a
  selection file whose parameters don't match its grid.
* `wf_grid` workers only write to their own configuration's slot; selection runs single-threaded
  in configuration order, so thread count cannot change the output.

## Test status

`scripts/test_synthetic.sh` passes: on synthetic data, Python and C++ agree on every one of
~155k trades across all 432 configurations, fold statistics, selections and out-of-sample P&L;
`orb_bt` reproduces the out-of-sample trades exactly from CSV replay and over the kdb+ wire
protocol (against `tools/mock_q_server.py`); results are identical at 1 and N threads.

The full kdb+ path (`scripts/run_q_pipeline.sh`) has run end to end on KDB-X 5.0 Community
Edition under WSL with Databento GC data, Dec 2019 – Dec 2024: Python and C++ matched on all
175,248 grid trades, and `orb_bt` streaming from `q/server.q` matched the walk-forward trades
exactly. `tools/ref_pipeline.py` mirrors the q scripts step by step; to cross-check a q run,
compare the two exports:

```bash
python3 tools/ref_pipeline.py --raw data/raw --out export_ref
python3 py/reconcile.py exports export export_ref
```

Small float differences in `rv20` / `relVol` are expected (q's `mavg` uses running sums); any
difference in `ok`, prices or counts is a bug.

## About the numbers

Results depend entirely on the data. Synthetic-data results are meaningless. Runtime depends on
the machine and data: with this design (each configuration simulated once, then sliced by fold) the
pure-Python study takes seconds rather than minutes on five years of one-minute GC data.
