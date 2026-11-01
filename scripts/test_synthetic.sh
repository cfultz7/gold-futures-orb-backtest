#!/usr/bin/env bash
# End-to-end test that needs no kdb+ license and no market data:
# synthetic raw bars -> Python mirror of the q pipeline -> Python and C++ walk-forward studies ->
# event-driven backtest from CSV replay and from a mock kdb+ IPC server -> reconciliation.
#
#   scripts/test_synthetic.sh            (builds cpp/build first if needed)
set -euo pipefail
cd "$(dirname "$0")/.."

T=${T:-.synth}
BUILD=${BUILD:-cpp/build}
PORT=${PORT:-5019}

if [[ ! -x "$BUILD/wf_grid" ]]; then
  cmake -S cpp -B "$BUILD" ${KDB_C_DIR:+-DORB_WITH_KDB=ON -DKDB_C_DIR="$KDB_C_DIR"}
  cmake --build "$BUILD" -j
fi

rm -rf "$T" && mkdir -p "$T"
python3 tools/make_synth.py   --out "$T/raw"
python3 tools/ref_pipeline.py --raw "$T/raw" --out "$T/export"

python3 py/orb_sim.py  --data "$T/export" --config config/orb.cfg --out "$T/out_py"
"$BUILD/wf_grid"       --data "$T/export" --config config/orb.cfg --out "$T/out_cpp"
python3 py/reconcile.py grid "$T/out_py" "$T/out_cpp"

"$BUILD/orb_bt" --source csv --data "$T/export" --config config/orb.cfg \
                --selection "$T/out_cpp/wf_selection.csv" --out "$T/out_bt_csv"
python3 py/reconcile.py bt "$T/out_cpp" "$T/out_bt_csv"

probe=$("$BUILD/orb_bt" --source kdb --port 1 --config config/orb.cfg --cfg 0 --from 20220101 --to 20220102 \
          --out "$T/probe" 2>&1 || true)
if [[ $probe == *"built without kdb"* ]]; then
  echo "orb_bt built without kdb+ support; skipping the IPC test"
else
  python3 tools/mock_q_server.py --data "$T/export" --port "$PORT" &
  MOCK=$!
  trap 'kill $MOCK 2>/dev/null || true' EXIT
  sleep 2
  "$BUILD/orb_bt" --source kdb --port "$PORT" --config config/orb.cfg \
                  --selection "$T/out_cpp/wf_selection.csv" --out "$T/out_bt_kdb"
  wait "$MOCK"
  python3 py/reconcile.py bt "$T/out_cpp" "$T/out_bt_kdb"
fi
echo "all reconciliations passed"
