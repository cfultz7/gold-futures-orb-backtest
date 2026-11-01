#pragma once
// Market data and trade records. Prices are integer ticks everywhere past the loaders.

#include <cmath>
#include <cstdint>
#include <vector>

namespace orb {

struct Bar {
    int tmin = 0;  // bar start, minutes after midnight ET
    int64_t o = 0, h = 0, l = 0, c = 0;
};

// One opening-range feature row (one per OR length per session), from q/features.q.
struct Feature {
    int orMin = 0;
    bool ok = false;
    int64_t hi = 0, lo = 0;  // OR high / low in ticks
    double relVol = 0;
    double wToV = 0;
};

struct Session {
    int date = 0;  // yyyymmdd
    std::vector<Bar> bars;
    std::vector<Feature> feats;

    const Feature* find(int orMin) const {
        for (const auto& f : feats)
            if (f.orMin == orMin) return &f;
        return nullptr;
    }
};

enum class Exit : uint8_t { Stop, Target, Close };

inline const char* exitName(Exit e) {
    switch (e) {
        case Exit::Stop: return "stop";
        case Exit::Target: return "target";
        case Exit::Close: return "close";
    }
    return "?";
}

struct Trade {
    int cfg = -1;
    int date = 0;
    int side = 0;  // +1 long, -1 short
    int entryMin = 0;
    int64_t entry = 0;
    int exitMin = 0;
    int64_t exit = 0;
    Exit reason = Exit::Close;
    int64_t pnlTicks = 0;
    double pnlUsd = 0;
};

// Same rounding as py/orb_sim.py: floor(px / tick + 0.5).
inline int64_t toTicks(double px, double tick) {
    return static_cast<int64_t>(std::floor(px / tick + 0.5));
}

}  // namespace orb
