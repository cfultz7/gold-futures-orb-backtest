#pragma once
// Grid simulation and walk-forward selection: the C++ port of py/orb_sim.py.

#include <cstdint>
#include <vector>

#include "orb/config.hpp"
#include "orb/report.hpp"
#include "orb/types.hpp"

namespace orb {

// One configuration over every session.
struct ConfigRun {
    std::vector<Trade> trades;
    std::vector<double> pnl;      // per session, USD (0 when no trade)
    std::vector<uint8_t> traded;  // per session, 1 when a trade completed
};

ConfigRun simulateConfig(const std::vector<Session>& sessions, const Params& p, const Config& c);

struct FoldStat {
    int fold, cfg, trainSessions, trainTrades;
    double trainPnl, trainSharpe;
};

struct WalkForward {
    std::vector<FoldStat> foldStats;  // every config, every fold
    std::vector<Selection> selection; // chosen config per fold
    std::vector<OosTrade> oosTrades;
    std::vector<OosDay> oosDaily;
};

WalkForward walkForward(const std::vector<Session>& sessions, const Config& c, const std::vector<ConfigRun>& runs);

}  // namespace orb
