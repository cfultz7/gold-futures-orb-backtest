// wf_grid: multithreaded port of py/orb_sim.py.
//
//   wf_grid --data export --config config/orb.cfg --out out_cpp [--threads N] [--no-dump]
//
// Each worker takes the next configuration index from an atomic counter and simulates it over
// every session; configurations share nothing but the read-only sessions, so no locking is
// needed and the results land in a vector indexed by configuration. The walk-forward selection
// then runs on one thread, in configuration order, exactly as the Python version does.

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <thread>
#include <vector>

#include "orb/config.hpp"
#include "orb/dataset.hpp"
#include "orb/report.hpp"
#include "orb/walkforward.hpp"

using namespace orb;
using Clock = std::chrono::steady_clock;

static double secondsSince(Clock::time_point t) {
    return std::chrono::duration<double>(Clock::now() - t).count();
}

int main(int argc, char** argv) {
    std::string data = "export", cfgPath = "config/orb.cfg", out = "out_cpp";
    unsigned threads = std::thread::hardware_concurrency();
    bool dump = true;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        auto val = [&]() -> std::string {
            if (i + 1 >= argc) { std::fprintf(stderr, "%s needs a value\n", a.c_str()); std::exit(2); }
            return argv[++i];
        };
        if (a == "--data") data = val();
        else if (a == "--config") cfgPath = val();
        else if (a == "--out") out = val();
        else if (a == "--threads") threads = static_cast<unsigned>(std::stoul(val()));
        else if (a == "--no-dump") dump = false;
        else { std::fprintf(stderr, "usage: wf_grid [--data DIR] [--config FILE] [--out DIR] [--threads N] [--no-dump]\n"); return 2; }
    }
    if (threads == 0) threads = 1;

    try {
        const Config c = loadConfig(cfgPath);
        ::mkdir(out.c_str(), 0755);

        auto t = Clock::now();
        const std::vector<Session> sessions = loadExport(data, c.tick);
        size_t nbars = 0;
        for (const auto& s : sessions) nbars += s.bars.size();
        std::printf("loaded %zu sessions, %zu bars in %.1fs\n", sessions.size(), nbars, secondsSince(t));

        t = Clock::now();
        std::vector<ConfigRun> runs(c.grid.size());
        std::atomic<size_t> next{0};
        auto worker = [&] {
            for (size_t i; (i = next.fetch_add(1)) < c.grid.size();) runs[i] = simulateConfig(sessions, c.grid[i], c);
        };
        std::vector<std::thread> pool;
        for (unsigned k = 0; k < threads; ++k) pool.emplace_back(worker);
        for (auto& th : pool) th.join();
        const double gridSec = secondsSince(t);

        const WalkForward wf = walkForward(sessions, c, runs);
        const double studySec = secondsSince(t);
        std::printf("%zu-config walk-forward study: %.2fs on %u threads (grid %.2fs)\n", c.grid.size(), studySec,
                    threads, gridSec);

        const Summary s = summarize(wf.selection, wf.oosTrades, wf.oosDaily);
        if (dump) {
            std::vector<std::vector<Trade>> perConfig;
            perConfig.reserve(runs.size());
            for (auto& r : runs) perConfig.push_back(r.trades);
            writeGridTrades(out + "/grid_trades.csv", perConfig);
        }
        {
            FILE* f = std::fopen((out + "/grid_fold_stats.csv").c_str(), "w");
            if (!f) throw std::runtime_error("cannot write grid_fold_stats.csv");
            std::fprintf(f, "fold,cfg,train_sessions,train_trades,train_pnl_usd,train_sharpe\n");
            for (const auto& x : wf.foldStats)
                std::fprintf(f, "%d,%d,%d,%d,%s,%s\n", x.fold, x.cfg, x.trainSessions, x.trainTrades,
                             num(x.trainPnl).c_str(), num(x.trainSharpe).c_str());
            std::fclose(f);
        }
        writeSelection(out + "/wf_selection.csv", wf.selection, c);
        writeOosTrades(out + "/wf_trades.csv", wf.oosTrades);
        writeOosDaily(out + "/wf_daily.csv", wf.oosDaily);
        writeSummary(out + "/wf_summary.json", s, c, static_cast<int>(c.grid.size()), studySec, "cpp");
        printSummary(s);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "wf_grid: %s\n", e.what());
        return 1;
    }
    return 0;
}
