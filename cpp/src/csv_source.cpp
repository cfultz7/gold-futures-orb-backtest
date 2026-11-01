#include <algorithm>

#include "orb/dataset.hpp"
#include "orb/sources.hpp"

namespace orb {

CsvReplaySource::CsvReplaySource(const std::string& dir, double tick, int from, int to) : dir_(dir) {
    auto all = loadExport(dir, tick);
    for (auto& s : all)
        if (s.date >= from && s.date <= to) sessions_.push_back(std::move(s));
}

bool CsvReplaySource::next(Event& ev) {
    while (s_ < sessions_.size()) {
        const Session& s = sessions_[s_];
        switch (phase_) {
            case 0:
                ev.type = EvType::SessionStart;
                ev.date = s.date;
                ev.feats = s.feats;
                phase_ = 1;
                b_ = 0;
                return true;
            case 1:
                if (b_ < s.bars.size()) {
                    ev.type = EvType::Bar;
                    ev.date = s.date;
                    ev.bar = s.bars[b_++];
                    return true;
                }
                phase_ = 2;
                [[fallthrough]];
            default:
                ev.type = EvType::SessionEnd;
                ev.date = s.date;
                phase_ = 0;
                ++s_;
                return true;
        }
    }
    return false;
}

std::string CsvReplaySource::describe() const {
    return "csv replay of " + dir_ + " (" + std::to_string(sessions_.size()) + " sessions)";
}

}  // namespace orb
