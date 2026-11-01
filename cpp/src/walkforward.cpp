#include "orb/walkforward.hpp"

#include <algorithm>

#include "orb/stats.hpp"
#include "orb/strategy.hpp"

namespace orb {

ConfigRun simulateConfig(const std::vector<Session>& sessions, const Params& p, const Config& c) {
    ConfigRun run;
    run.pnl.assign(sessions.size(), 0.0);
    run.traded.assign(sessions.size(), 0);
    OrbSession s;
    for (size_t k = 0; k < sessions.size(); ++k) {
        const Session& ss = sessions[k];
        s.begin(ss.date, ss.find(p.orMin), &p, c);
        for (const Bar& b : ss.bars) s.onBar(b);
        Trade t;
        if (s.finish(t)) {
            t.cfg = p.idx;
            run.trades.push_back(t);
            run.pnl[k] = t.pnlUsd;
            run.traded[k] = 1;
        }
    }
    return run;
}

WalkForward walkForward(const std::vector<Session>& sessions, const Config& c, const std::vector<ConfigRun>& runs) {
    std::vector<int> dates;
    dates.reserve(sessions.size());
    for (const auto& s : sessions) dates.push_back(s.date);

    WalkForward wf;
    int k = 0;
    for (const Fold& fold : c.folds) {
        ++k;
        const size_t t0 = std::lower_bound(dates.begin(), dates.end(), fold.testStart) - dates.begin();
        const size_t t1 = std::upper_bound(dates.begin(), dates.end(), fold.testEnd) - dates.begin();
        const size_t a = c.trainYears == 0
            ? 0
            : std::lower_bound(dates.begin(), dates.end(), fold.testStart - 10000 * c.trainYears) - dates.begin();
        const size_t b = t0;  // training ends the session before the test window opens
        const size_t n = b > a ? b - a : 0;

        int best = -1;
        double bestSr = 0.0;
        for (const Params& p : c.grid) {
            const ConfigRun& r = runs[p.idx];
            const double sr = sharpe(r.pnl.data() + a, n);
            int nt = 0;
            for (size_t i = a; i < a + n; ++i) nt += r.traded[i];
            wf.foldStats.push_back(FoldStat{k, p.idx, static_cast<int>(n), nt, total(r.pnl.data() + a, n), sr});
            if (nt >= c.minTrades && (best < 0 || sr > bestSr)) {
                best = p.idx;
                bestSr = sr;
            }
        }

        Selection sel;
        sel.fold = k;
        sel.testStart = fold.testStart;
        sel.testEnd = fold.testEnd;
        sel.trainStart = n ? dates[a] : 0;
        sel.trainEnd = n ? dates[b - 1] : 0;
        sel.cfg = best;
        sel.trainSharpe = best >= 0 ? bestSr : 0.0;
        if (best >= 0) {
            for (size_t i = a; i < a + n; ++i) sel.trainTrades += runs[best].traded[i];
            for (const Trade& t : runs[best].trades)
                if (t.date >= fold.testStart && t.date <= fold.testEnd) wf.oosTrades.push_back(OosTrade{k, t});
        }
        wf.selection.push_back(sel);
        for (size_t i = t0; i < t1; ++i)
            wf.oosDaily.push_back(OosDay{dates[i], k, best, best >= 0 ? runs[best].pnl[i] : 0.0});
    }
    return wf;
}

}  // namespace orb
