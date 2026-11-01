#include "orb/dataset.hpp"

#include <cstdlib>
#include <fstream>
#include <map>
#include <stdexcept>

namespace orb {

static void split(const std::string& s, std::vector<std::string>& out) {
    out.clear();
    size_t a = 0;
    for (;;) {
        const size_t b = s.find(',', a);
        out.emplace_back(s, a, b == std::string::npos ? std::string::npos : b - a);
        if (b == std::string::npos) break;
        a = b + 1;
    }
    if (!out.empty() && !out.back().empty() && out.back().back() == '\r') out.back().pop_back();
}

CsvReader::CsvReader(const std::string& path) : path_(path), in_(new std::ifstream(path)) {
    auto& in = *static_cast<std::ifstream*>(in_);
    if (!in) throw std::runtime_error("cannot open " + path);
    if (!std::getline(in, line_)) throw std::runtime_error("empty file " + path);
    split(line_, header_);
}

CsvReader::~CsvReader() { delete static_cast<std::ifstream*>(in_); }

bool CsvReader::next() {
    auto& in = *static_cast<std::ifstream*>(in_);
    while (std::getline(in, line_)) {
        if (line_.empty() || line_ == "\r") continue;
        split(line_, row_);
        if (row_.size() != header_.size())
            throw std::runtime_error(path_ + ": wrong field count in line: " + line_);
        return true;
    }
    return false;
}

int CsvReader::col(const std::string& name) const {
    for (size_t i = 0; i < header_.size(); ++i)
        if (header_[i] == name) return static_cast<int>(i);
    throw std::runtime_error(path_ + ": missing column " + name);
}

double CsvReader::num(int i) const {
    const char* s = row_[i].c_str();
    char* end = nullptr;
    const double v = std::strtod(s, &end);  // stops at a trailing 'f'
    if (end == s) throw std::runtime_error(path_ + ": bad number '" + row_[i] + "'");
    return v;
}

long long CsvReader::integer(int i) const {
    const char* s = row_[i].c_str();
    char* end = nullptr;
    const long long v = std::strtoll(s, &end, 10);
    if (end == s) throw std::runtime_error(path_ + ": bad integer '" + row_[i] + "'");
    return v;
}

std::vector<Session> loadExport(const std::string& dir, double tick) {
    std::map<int, Session> byDate;
    {
        CsvReader r(dir + "/feat.csv");
        const int cDate = r.col("date"), cOr = r.col("orMin"), cOk = r.col("ok"), cHi = r.col("orHigh"),
                  cLo = r.col("orLow"), cRv = r.col("relVol"), cW = r.col("wToV");
        while (r.next()) {
            const int date = static_cast<int>(r.integer(cDate));
            Session& s = byDate[date];
            s.date = date;
            Feature f;
            f.orMin = static_cast<int>(r.integer(cOr));
            f.ok = r.integer(cOk) == 1;
            f.hi = toTicks(r.num(cHi), tick);
            f.lo = toTicks(r.num(cLo), tick);
            f.relVol = r.num(cRv);
            f.wToV = r.num(cW);
            bool replaced = false;
            for (auto& g : s.feats)
                if (g.orMin == f.orMin) { g = f; replaced = true; }
            if (!replaced) s.feats.push_back(f);
        }
    }
    {
        CsvReader r(dir + "/bars.csv");
        const int cDate = r.col("date"), cT = r.col("tmin"), cO = r.col("open"), cH = r.col("high"),
                  cL = r.col("low"), cC = r.col("close");
        while (r.next()) {
            const int date = static_cast<int>(r.integer(cDate));
            auto it = byDate.find(date);
            if (it == byDate.end()) throw std::runtime_error("bar for date " + std::to_string(date) + " has no feature row");
            Bar b;
            b.tmin = static_cast<int>(r.integer(cT));
            b.o = toTicks(r.num(cO), tick);
            b.h = toTicks(r.num(cH), tick);
            b.l = toTicks(r.num(cL), tick);
            b.c = toTicks(r.num(cC), tick);
            auto& bars = it->second.bars;
            if (!bars.empty() && b.tmin <= bars.back().tmin)
                throw std::runtime_error("bars out of order on " + std::to_string(date));
            bars.push_back(b);
        }
    }
    std::vector<Session> out;
    out.reserve(byDate.size());
    for (auto& kv : byDate) out.push_back(std::move(kv.second));
    return out;
}

}  // namespace orb
