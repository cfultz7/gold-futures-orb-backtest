#pragma once
// Settings shared with py/orbcfg.py: both parse config/orb.cfg with the same rules.

#include <string>
#include <vector>

namespace orb {

struct Params {
    int idx = -1;
    int orMin = 0;         // opening-range length, minutes
    double stopFrac = 0;   // stop distance as a fraction of OR width
    double targetR = 0;    // target distance as a multiple of the stop distance
    double minRelVol = 0;  // minimum opening-range relative volume
    double maxWtoV = 0;    // maximum OR width relative to rv20 * price (inf = off)
};

struct Fold {
    int testStart = 0;  // yyyymmdd, inclusive
    int testEnd = 0;    // yyyymmdd, inclusive
};

struct Config {
    double tick = 0.1;
    double tickValue = 10.0;
    double feePerSide = 0;
    int slipTicks = 0;
    int sessOpen = 0;     // minutes after midnight ET
    int sessClose = 0;
    int entryCutoff = 0;
    std::vector<Params> grid;  // or_min outermost, max_wtov innermost (same order as Python)
    std::vector<Fold> folds;
    int trainYears = 0;   // 0 = expanding window
    int minTrades = 0;
};

Config loadConfig(const std::string& path);

}  // namespace orb
