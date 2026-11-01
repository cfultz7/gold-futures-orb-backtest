#include "orb/config.hpp"

#include <cstdlib>
#include <fstream>
#include <map>
#include <sstream>
#include <stdexcept>

namespace orb {

static std::string trim(const std::string& s) {
    const char* ws = " \t\r\n";
    const size_t a = s.find_first_not_of(ws);
    if (a == std::string::npos) return "";
    return s.substr(a, s.find_last_not_of(ws) - a + 1);
}

static std::vector<std::string> splitList(const std::string& s) {
    std::vector<std::string> out;
    std::stringstream ss(s);
    std::string item;
    while (std::getline(ss, item, ',')) out.push_back(trim(item));
    return out;
}

static double toDouble(const std::string& s) {
    char* end = nullptr;
    const double v = std::strtod(s.c_str(), &end);  // accepts "inf"
    if (end == s.c_str()) throw std::runtime_error("config: bad number '" + s + "'");
    return v;
}

static int toInt(const std::string& s) { return static_cast<int>(toDouble(s)); }

static int hhmm(const std::string& s) {
    const size_t c = s.find(':');
    if (c == std::string::npos) throw std::runtime_error("config: bad time '" + s + "'");
    return std::stoi(s.substr(0, c)) * 60 + std::stoi(s.substr(c + 1));
}

Config loadConfig(const std::string& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open config " + path);
    std::map<std::string, std::string> kv;
    std::string line;
    while (std::getline(in, line)) {
        const size_t h = line.find('#');
        if (h != std::string::npos) line.erase(h);
        line = trim(line);
        if (line.empty()) continue;
        const size_t eq = line.find('=');
        if (eq == std::string::npos) throw std::runtime_error("config: no '=' in line: " + line);
        kv[trim(line.substr(0, eq))] = trim(line.substr(eq + 1));
    }
    auto get = [&](const std::string& k) -> const std::string& {
        auto it = kv.find(k);
        if (it == kv.end()) throw std::runtime_error("config: missing key " + k);
        return it->second;
    };
    auto dlist = [&](const std::string& k) {
        std::vector<double> v;
        for (auto& s : splitList(get(k))) v.push_back(toDouble(s));
        return v;
    };

    Config c;
    c.tick = toDouble(get("tick"));
    c.tickValue = toDouble(get("tick_value"));
    c.feePerSide = toDouble(get("fee_per_side"));
    c.slipTicks = toInt(get("slip_ticks"));
    c.sessOpen = hhmm(get("sess_open"));
    c.sessClose = hhmm(get("sess_close"));
    c.entryCutoff = hhmm(get("entry_cutoff"));
    c.trainYears = toInt(get("train_years"));
    c.minTrades = toInt(get("min_trades"));

    std::vector<int> orMins;
    for (auto& s : splitList(get("grid.or_min"))) orMins.push_back(toInt(s));
    const auto sf = dlist("grid.stop_frac"), tr = dlist("grid.target_r"), rv = dlist("grid.min_relvol"),
               wv = dlist("grid.max_wtov");
    int idx = 0;
    for (int om : orMins)
        for (double a : sf)
            for (double b : tr)
                for (double r : rv)
                    for (double w : wv) c.grid.push_back(Params{idx++, om, a, b, r, w});

    for (auto& item : splitList(get("folds"))) {
        const size_t colon = item.find(':');
        if (colon == std::string::npos) throw std::runtime_error("config: bad fold '" + item + "'");
        c.folds.push_back(Fold{std::stoi(item.substr(0, colon)), std::stoi(item.substr(colon + 1))});
    }
    return c;
}

}  // namespace orb
