#pragma once
// Statistics, accumulated left to right exactly as in py/orb_sim.py so results match bit for bit.
// Build with -ffp-contract=off (CMakeLists.txt does) so the compiler cannot fuse a*b+c into an FMA.

#include <cmath>
#include <cstddef>

namespace orb {

constexpr double kTradingDays = 252.0;

inline double total(const double* x, size_t n) {
    double t = 0.0;
    for (size_t i = 0; i < n; ++i) t += x[i];
    return t;
}

// Annualized Sharpe of a daily P&L series (days without a trade count as zero).
inline double sharpe(const double* x, size_t n) {
    if (n < 2) return 0.0;
    const double m = total(x, n) / static_cast<double>(n);
    double ss = 0.0;
    for (size_t i = 0; i < n; ++i) {
        const double d = x[i] - m;
        ss += d * d;
    }
    const double var = ss / static_cast<double>(n - 1);
    if (var <= 0.0) return 0.0;
    return m / std::sqrt(var) * std::sqrt(kTradingDays);
}

inline double maxDrawdown(const double* x, size_t n) {
    double eq = 0.0, peak = 0.0, dd = 0.0;
    for (size_t i = 0; i < n; ++i) {
        eq += x[i];
        if (eq > peak) peak = eq;
        if (peak - eq > dd) dd = peak - eq;
    }
    return dd;
}

}  // namespace orb
