// orb_bt: event-driven opening-range-breakout backtester.
//
// Walk-forward out-of-sample run (the configuration for each fold comes from wf_grid / orb_sim):
//   orb_bt --source kdb --host localhost --port 5010 --selection out_cpp/wf_selection.csv --out out_bt
//   orb_bt --source csv --data export                --selection out_cpp/wf_selection.csv --out out_bt
//
// One fixed configuration over a date range:
//   orb_bt --source csv --data export --cfg 117 --from 20220101 --to 20241231 --out out_one
//
// Writes bt_trades.csv, bt_daily.csv and bt_summary.json with the same columns as wf_grid's
// wf_trades.csv / wf_daily.csv / wf_summary.json, so the two can be diffed with py/reconcile.py.

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <stdexcept>
#include <string>
#include <sys/stat.h>

#include "orb/config.hpp"
#include "orb/engine.hpp"
#include "orb/report.hpp"
#include "orb/sources.hpp"

using namespace orb;

static void usage() {
    std::fprintf(stderr,
                 "usage: orb_bt --source csv|kdb [--data DIR] [--host H] [--port P] [--config FILE]\n"
                 "              (--selection FILE | --cfg N --from YYYYMMDD --to YYYYMMDD) [--out DIR]\n");
    std::exit(2);
}

int main(int argc, char** argv) {
    std::string source, data = "export", host = "localhost", cfgPath = "config/orb.cfg", selPath, out = "out_bt";
    int port = 5010, fixedCfg = -1, from = 0, to = 0;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        auto val = [&]() -> std::string {
            if (i + 1 >= argc) usage();
            return argv[++i];
        };
        if (a == "--source") source = val();
        else if (a == "--data") data = val();
        else if (a == "--host") host = val();
        else if (a == "--port") port = std::stoi(val());
        else if (a == "--config") cfgPath = val();
        else if (a == "--selection") selPath = val();
        else if (a == "--cfg") fixedCfg = std::stoi(val());
        else if (a == "--from") from = std::stoi(val());
        else if (a == "--to") to = std::stoi(val());
        else if (a == "--out") out = val();
        else usage();
    }
    if (source != "csv" && source != "kdb") usage();
    if (selPath.empty() == (fixedCfg < 0)) usage();

    try {
        const Config c = loadConfig(cfgPath);
        ::mkdir(out.c_str(), 0755);

        // schedule: date -> (configuration, fold)
        std::vector<Selection> sel;
        if (!selPath.empty()) {
            sel = readSelection(selPath, c);
            if (sel.empty()) throw std::runtime_error("empty selection file");
            from = sel.front().testStart;
            to = sel.front().testEnd;
            for (const auto& s : sel) {
                from = std::min(from, s.testStart);
                to = std::max(to, s.testEnd);
            }
        } else {
            if (fixedCfg >= static_cast<int>(c.grid.size())) throw std::runtime_error("--cfg outside the grid");
            if (!from || !to) usage();
            Selection s;
            s.fold = 0;
            s.testStart = from;
            s.testEnd = to;
            s.cfg = fixedCfg;
            sel.push_back(s);
        }
        Schedule schedule = [&](int date) {
            for (const auto& s : sel)
                if (date >= s.testStart && date <= s.testEnd)
                    return Assignment{s.cfg >= 0 ? &c.grid[s.cfg] : nullptr, s.fold};
            return Assignment{};
        };

        std::unique_ptr<EventSource> src;
        if (source == "csv") {
            src = std::make_unique<CsvReplaySource>(data, c.tick, from, to);
        } else {
#ifdef ORB_WITH_KDB
            src = std::make_unique<KdbSource>(host, port, from, to, c.tick);
#else
            (void)host;
            (void)port;
            throw std::runtime_error("built without kdb+ support; reconfigure with -DORB_WITH_KDB=ON -DKDB_C_DIR=...");
#endif
        }

        const auto t0 = std::chrono::steady_clock::now();
        Backtester bt(c, schedule);
        bt.run(*src);
        const double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        std::printf("%s: %zu events, %zu sessions in %.2fs\n", src->describe().c_str(), bt.events(), bt.daily().size(),
                    secs);

        const Summary s = summarize(sel, bt.trades(), bt.daily());
        writeOosTrades(out + "/bt_trades.csv", bt.trades());
        writeOosDaily(out + "/bt_daily.csv", bt.daily());
        writeSummary(out + "/bt_summary.json", s, c, static_cast<int>(c.grid.size()), secs, "orb_bt/" + source);
        printSummary(s);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "orb_bt: %s\n", e.what());
        return 1;
    }
    return 0;
}
