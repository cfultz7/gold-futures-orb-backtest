#pragma once
// Out-of-sample records, summary statistics and the CSV / JSON writers shared by wf_grid and orb_bt.
// Column layouts match py/orb_sim.py so py/reconcile.py can diff the files directly.

#include <string>
#include <vector>

#include "orb/config.hpp"
#include "orb/types.hpp"

namespace orb {

struct Selection {
    int fold = 0, testStart = 0, testEnd = 0, trainStart = 0, trainEnd = 0, cfg = -1;
    double trainSharpe = 0.0;
    int trainTrades = 0;
};

struct OosTrade {
    int fold;
    Trade t;
};

struct OosDay {
    int date, fold, cfg;
    double pnl;
};

struct FoldSummary {
    int fold = 0, cfg = -1, sessions = 0, trades = 0;
    double trainSharpe = 0, pnl = 0, sharpe = 0;
};

struct Summary {
    int sessions = 0, trades = 0;
    double netPnl = 0, netSharpe = 0, maxDrawdown = 0, winRate = 0;
    std::vector<FoldSummary> folds;
};

Summary summarize(const std::vector<Selection>& sel, const std::vector<OosTrade>& trades,
                  const std::vector<OosDay>& daily);

std::string num(double v);  // %.17g, round-trips exactly

void writeSelection(const std::string& path, const std::vector<Selection>& sel, const Config& c);
std::vector<Selection> readSelection(const std::string& path, const Config& c);  // checks params vs grid
void writeGridTrades(const std::string& path, const std::vector<std::vector<Trade>>& perConfig);
void writeOosTrades(const std::string& path, const std::vector<OosTrade>& trades);
void writeOosDaily(const std::string& path, const std::vector<OosDay>& daily);
void writeSummary(const std::string& path, const Summary& s, const Config& c, int configs, double seconds,
                  const std::string& engine);
void printSummary(const Summary& s);

}  // namespace orb
