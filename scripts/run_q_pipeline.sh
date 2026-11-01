#!/usr/bin/env bash
# Full kdb+ path: raw CSVs -> HDB -> QA -> roll -> features -> CSV export, then the walk-forward
# study in Python and C++, then the event-driven backtest streamed from q over IPC.
#
#   scripts/run_q_pipeline.sh data/raw        (needs q on PATH and cpp/build built with -DORB_WITH_KDB=ON)
set -euo pipefail
cd "$(dirname "$0")/.."

RAW=${1:-data/raw}
PORT=${PORT:-5010}
BUILD=${BUILD:-cpp/build}

rm -rf db qa work export
q q/load.q     -raw "$RAW" -db db
q q/validate.q -db db -qa qa
q q/roll.q     -db db -qa qa
q q/features.q -db db -qa qa -work work
q q/export.q   -work work -out export

python3 py/orb_sim.py --data export --config config/orb.cfg --out out_py
"$BUILD/wf_grid"      --data export --config config/orb.cfg --out out_cpp
python3 py/reconcile.py grid out_py out_cpp

q q/server.q -work work -p "$PORT" < /dev/null > server.log 2>&1 &
QPID=$!
trap 'kill $QPID 2>/dev/null || true' EXIT
sleep 2
"$BUILD/orb_bt" --source kdb --port "$PORT" --config config/orb.cfg --selection out_cpp/wf_selection.csv --out out_bt
python3 py/reconcile.py bt out_cpp out_bt
