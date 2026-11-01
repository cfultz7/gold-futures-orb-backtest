#pragma once
// Opening-range breakout for one session, as an event-driven state machine:
//   begin() at the session open, onBar() for each window bar, finish() after the last bar.
// Shared by the event-driven backtester (orb_bt) and the walk-forward grid (wf_grid), and a
// port of run_session() in py/orb_sim.py. The fill rules are documented there.

#include <algorithm>
#include <cmath>

#include "orb/config.hpp"
#include "orb/types.hpp"

namespace orb {

class OrbSession {
public:
    // p == nullptr or a filtered-out feature row leaves the session flat.
    void begin(int date, const Feature* f, const Params* p, const Config& c) {
        st_ = St::Off;
        have_ = false;
        date_ = date;
        c_ = &c;
        if (p == nullptr || f == nullptr || !f->ok) return;
        if (f->relVol < p->minRelVol || f->wToV > p->maxWtoV) return;
        const int64_t width = f->hi - f->lo;
        if (width <= 0) return;

        stopD_ = std::max<int64_t>(1, static_cast<int64_t>(std::floor(p->stopFrac * static_cast<double>(width) + 0.5)));
        tgtD_ = std::max<int64_t>(1, static_cast<int64_t>(std::floor(p->targetR * static_cast<double>(stopD_) + 0.5)));
        trigL_ = f->hi + 1;
        trigS_ = f->lo - 1;
        start_ = c.sessOpen + p->orMin;
        st_ = St::Waiting;
    }

    void onBar(const Bar& b) {
        const int64_t slip = c_ ? c_->slipTicks : 0;
        switch (st_) {
            case St::Off:
            case St::Done:
                return;

            case St::Waiting: {
                if (b.tmin < start_) return;  // still inside the opening range
                if (b.tmin >= c_->entryCutoff) { st_ = St::Done; return; }
                const bool up = b.h >= trigL_;
                const bool dn = b.l <= trigS_;
                if (up && dn) { st_ = St::Done; return; }  // both triggers in one bar: skip
                if (up) {
                    open(+1, b, std::max(b.o, trigL_) + slip);
                    if (b.l <= stop_) close(b.tmin, stop_ - slip, Exit::Stop);
                } else if (dn) {
                    open(-1, b, std::min(b.o, trigS_) - slip);
                    if (b.h >= stop_) close(b.tmin, stop_ + slip, Exit::Stop);
                }
                return;
            }

            case St::Long:
                lastMin_ = b.tmin;
                lastClose_ = b.c;
                if (b.o <= stop_)      close(b.tmin, b.o - slip, Exit::Stop);
                else if (b.o >= tgt_)  close(b.tmin, b.o, Exit::Target);
                else if (b.l <= stop_) close(b.tmin, stop_ - slip, Exit::Stop);
                else if (b.h >= tgt_)  close(b.tmin, tgt_, Exit::Target);
                return;

            case St::Short:
                lastMin_ = b.tmin;
                lastClose_ = b.c;
                if (b.o >= stop_)      close(b.tmin, b.o + slip, Exit::Stop);
                else if (b.o <= tgt_)  close(b.tmin, b.o, Exit::Target);
                else if (b.h >= stop_) close(b.tmin, stop_ + slip, Exit::Stop);
                else if (b.l <= tgt_)  close(b.tmin, tgt_, Exit::Target);
                return;
        }
    }

    // End of session: flatten at the last bar's close. Returns true if a trade completed today.
    bool finish(Trade& out) {
        if (st_ == St::Long || st_ == St::Short)
            close(lastMin_, lastClose_ - side_ * c_->slipTicks, Exit::Close);
        st_ = St::Off;
        if (!have_) return false;
        out = trade_;
        return true;
    }

private:
    enum class St { Off, Waiting, Long, Short, Done };

    void open(int side, const Bar& b, int64_t fill) {
        side_ = side;
        entryMin_ = b.tmin;
        entry_ = fill;
        stop_ = fill - side * stopD_;
        tgt_ = fill + side * tgtD_;
        lastMin_ = b.tmin;
        lastClose_ = b.c;
        st_ = side > 0 ? St::Long : St::Short;
    }

    void close(int tmin, int64_t fill, Exit why) {
        trade_.date = date_;
        trade_.side = side_;
        trade_.entryMin = entryMin_;
        trade_.entry = entry_;
        trade_.exitMin = tmin;
        trade_.exit = fill;
        trade_.reason = why;
        trade_.pnlTicks = (fill - entry_) * side_;
        trade_.pnlUsd = static_cast<double>(trade_.pnlTicks) * c_->tickValue - 2.0 * c_->feePerSide;
        have_ = true;
        st_ = St::Done;
    }

    St st_ = St::Off;
    const Config* c_ = nullptr;
    int date_ = 0, start_ = 0, side_ = 0, entryMin_ = 0, lastMin_ = 0;
    int64_t trigL_ = 0, trigS_ = 0, stopD_ = 0, tgtD_ = 0;
    int64_t entry_ = 0, stop_ = 0, tgt_ = 0, lastClose_ = 0;
    bool have_ = false;
    Trade trade_;
};

}  // namespace orb
