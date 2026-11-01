#pragma once
// Event-driven backtest engine.
//
// An EventSource yields, for each session in date order:
//     SessionStart(date, feature rows)  ->  Bar ... Bar  ->  SessionEnd(date)
// The Backtester dispatches each event to the strategy for whichever configuration the
// schedule assigns to that date (the walk-forward selection), and books trades and daily P&L.
// Sources: KdbSource (kdb+ IPC stream from q/server.q) and CsvReplaySource (export CSVs).

#include <functional>
#include <string>
#include <vector>

#include "orb/config.hpp"
#include "orb/report.hpp"
#include "orb/strategy.hpp"
#include "orb/types.hpp"

namespace orb {

enum class EvType { SessionStart, Bar, SessionEnd };

struct Event {
    EvType type = EvType::Bar;
    int date = 0;                 // yyyymmdd
    std::vector<Feature> feats;   // SessionStart only
    Bar bar;                      // Bar only
};

class EventSource {
public:
    virtual ~EventSource() = default;
    virtual bool next(Event& ev) = 0;  // false at end of stream
    virtual std::string describe() const = 0;
};

// What to trade on a given date: the configuration and the fold it belongs to.
struct Assignment {
    const Params* params = nullptr;  // nullptr = stay flat
    int fold = 0;
};
using Schedule = std::function<Assignment(int date)>;

class Backtester {
public:
    Backtester(const Config& c, Schedule schedule) : c_(c), schedule_(std::move(schedule)) {}

    void onEvent(const Event& ev) {
        ++events_;
        switch (ev.type) {
            case EvType::SessionStart: {
                cur_ = schedule_(ev.date);
                const Feature* f = nullptr;
                if (cur_.params)
                    for (const auto& x : ev.feats)
                        if (x.orMin == cur_.params->orMin) f = &x;
                strat_.begin(ev.date, f, cur_.params, c_);
                date_ = ev.date;
                inSession_ = true;
                break;
            }
            case EvType::Bar:
                if (inSession_) strat_.onBar(ev.bar);
                break;
            case EvType::SessionEnd: {
                Trade t;
                double pnl = 0.0;
                if (strat_.finish(t)) {
                    t.cfg = cur_.params->idx;
                    trades_.push_back(OosTrade{cur_.fold, t});
                    pnl = t.pnlUsd;
                }
                daily_.push_back(OosDay{date_, cur_.fold, cur_.params ? cur_.params->idx : -1, pnl});
                inSession_ = false;
                break;
            }
        }
    }

    void run(EventSource& src) {
        Event ev;
        while (src.next(ev)) onEvent(ev);
    }

    const std::vector<OosTrade>& trades() const { return trades_; }
    const std::vector<OosDay>& daily() const { return daily_; }
    size_t events() const { return events_; }

private:
    const Config& c_;
    Schedule schedule_;
    OrbSession strat_;
    Assignment cur_;
    int date_ = 0;
    bool inSession_ = false;
    size_t events_ = 0;
    std::vector<OosTrade> trades_;
    std::vector<OosDay> daily_;
};

}  // namespace orb
