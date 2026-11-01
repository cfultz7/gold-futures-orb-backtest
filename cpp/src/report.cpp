#include "orb/report.hpp"

#include <cmath>
#include <cstdio>
#include <memory>
#include <stdexcept>

#include "orb/dataset.hpp"
#include "orb/stats.hpp"

namespace orb {

namespace {

struct File {
    FILE* f;
    explicit File(const std::string& path) : f(std::fopen(path.c_str(), "w")) {
        if (!f) throw std::runtime_error("cannot write " + path);
    }
    ~File() { std::fclose(f); }
};

std::string jnum(double v) {  // JSON flavour of num(): Python's json module writes Infinity
    if (std::isinf(v)) return v > 0 ? "Infinity" : "-Infinity";
    return num(v);
}

void tradeFields(FILE* f, const Trade& t) {
    std::fprintf(f, "%d,%d,%d,%d,%lld,%d,%lld,%s,%lld,%s\n", t.cfg, t.date, t.side, t.entryMin,
                 static_cast<long long>(t.entry), t.exitMin, static_cast<long long>(t.exit), exitName(t.reason),
                 static_cast<long long>(t.pnlTicks), num(t.pnlUsd).c_str());
}

const char* kTradeHeader = "cfg,date,side,entry_min,entry_tk,exit_min,exit_tk,reason,pnl_tk,pnl_usd";

}  // namespace

std::string num(double v) {
    char buf[40];
    std::snprintf(buf, sizeof buf, "%.17g", v);
    return buf;
}

Summary summarize(const std::vector<Selection>& sel, const std::vector<OosTrade>& trades,
                  const std::vector<OosDay>& daily) {
    Summary s;
    std::vector<double> pnl;
    pnl.reserve(daily.size());
    for (const auto& d : daily) pnl.push_back(d.pnl);
    s.sessions = static_cast<int>(pnl.size());
    s.trades = static_cast<int>(trades.size());
    s.netPnl = total(pnl.data(), pnl.size());
    s.netSharpe = sharpe(pnl.data(), pnl.size());
    s.maxDrawdown = maxDrawdown(pnl.data(), pnl.size());
    int wins = 0;
    for (const auto& t : trades) wins += t.t.pnlUsd > 0.0;
    s.winRate = trades.empty() ? 0.0 : static_cast<double>(wins) / static_cast<double>(trades.size());

    for (const auto& x : sel) {
        FoldSummary f;
        f.fold = x.fold;
        f.cfg = x.cfg;
        f.trainSharpe = x.trainSharpe;
        std::vector<double> fp;
        for (const auto& d : daily)
            if (d.fold == x.fold) fp.push_back(d.pnl);
        for (const auto& t : trades) f.trades += t.fold == x.fold;
        f.sessions = static_cast<int>(fp.size());
        f.pnl = total(fp.data(), fp.size());
        f.sharpe = sharpe(fp.data(), fp.size());
        s.folds.push_back(f);
    }
    return s;
}

void writeSelection(const std::string& path, const std::vector<Selection>& sel, const Config& c) {
    File out(path);
    std::fprintf(out.f, "fold,test_start,test_end,train_start,train_end,cfg,or_min,stop_frac,target_r,"
                        "min_relvol,max_wtov,train_sharpe,train_trades\n");
    for (const auto& s : sel) {
        const Params p = s.cfg >= 0 ? c.grid[s.cfg] : Params{};
        std::fprintf(out.f, "%d,%d,%d,%d,%d,%d,%d,%s,%s,%s,%s,%s,%d\n", s.fold, s.testStart, s.testEnd, s.trainStart,
                     s.trainEnd, s.cfg, p.orMin, num(p.stopFrac).c_str(), num(p.targetR).c_str(),
                     num(p.minRelVol).c_str(), num(p.maxWtoV).c_str(), num(s.trainSharpe).c_str(), s.trainTrades);
    }
}

std::vector<Selection> readSelection(const std::string& path, const Config& c) {
    CsvReader r(path);
    const int cF = r.col("fold"), cTs = r.col("test_start"), cTe = r.col("test_end"), cC = r.col("cfg"),
              cOm = r.col("or_min"), cSf = r.col("stop_frac"), cTr = r.col("target_r"), cRv = r.col("min_relvol"),
              cW = r.col("max_wtov"), cSr = r.col("train_sharpe");
    std::vector<Selection> out;
    while (r.next()) {
        Selection s;
        s.fold = static_cast<int>(r.integer(cF));
        s.testStart = static_cast<int>(r.integer(cTs));
        s.testEnd = static_cast<int>(r.integer(cTe));
        s.cfg = static_cast<int>(r.integer(cC));
        s.trainSharpe = r.num(cSr);
        if (s.cfg >= 0) {
            if (s.cfg >= static_cast<int>(c.grid.size()))
                throw std::runtime_error(path + ": cfg " + std::to_string(s.cfg) + " is outside the grid");
            const Params& p = c.grid[s.cfg];
            if (p.orMin != r.integer(cOm) || p.stopFrac != r.num(cSf) || p.targetR != r.num(cTr) ||
                p.minRelVol != r.num(cRv) || p.maxWtoV != r.num(cW))
                throw std::runtime_error(path + ": params for cfg " + std::to_string(s.cfg) +
                                         " differ from config/orb.cfg; was the selection made with another grid?");
        }
        out.push_back(s);
    }
    return out;
}

void writeGridTrades(const std::string& path, const std::vector<std::vector<Trade>>& perConfig) {
    File out(path);
    std::fprintf(out.f, "%s\n", kTradeHeader);
    for (const auto& v : perConfig)
        for (const auto& t : v) tradeFields(out.f, t);
}

void writeOosTrades(const std::string& path, const std::vector<OosTrade>& trades) {
    File out(path);
    std::fprintf(out.f, "fold,%s\n", kTradeHeader);
    for (const auto& t : trades) {
        std::fprintf(out.f, "%d,", t.fold);
        tradeFields(out.f, t.t);
    }
}

void writeOosDaily(const std::string& path, const std::vector<OosDay>& daily) {
    File out(path);
    std::fprintf(out.f, "date,fold,cfg,pnl_usd\n");
    for (const auto& d : daily) std::fprintf(out.f, "%d,%d,%d,%s\n", d.date, d.fold, d.cfg, num(d.pnl).c_str());
}

void writeSummary(const std::string& path, const Summary& s, const Config& c, int configs, double seconds,
                  const std::string& engine) {
    File out(path);
    FILE* f = out.f;
    std::fprintf(f, "{\n  \"oos_sessions\": %d,\n  \"oos_trades\": %d,\n", s.sessions, s.trades);
    std::fprintf(f, "  \"oos_net_pnl_usd\": %s,\n  \"oos_net_sharpe\": %s,\n", jnum(s.netPnl).c_str(),
                 jnum(s.netSharpe).c_str());
    std::fprintf(f, "  \"oos_max_drawdown_usd\": %s,\n  \"oos_win_rate\": %s,\n  \"folds\": [", jnum(s.maxDrawdown).c_str(),
                 jnum(s.winRate).c_str());
    for (size_t i = 0; i < s.folds.size(); ++i) {
        const FoldSummary& x = s.folds[i];
        std::fprintf(f, "%s\n    {\"fold\": %d, \"cfg\": %d, \"params\": ", i ? "," : "", x.fold, x.cfg);
        if (x.cfg >= 0) {
            const Params& p = c.grid[x.cfg];
            std::fprintf(f, "{\"or_min\": %d, \"stop_frac\": %s, \"target_r\": %s, \"min_relvol\": %s, \"max_wtov\": %s}",
                         p.orMin, jnum(p.stopFrac).c_str(), jnum(p.targetR).c_str(), jnum(p.minRelVol).c_str(),
                         jnum(p.maxWtoV).c_str());
        } else {
            std::fprintf(f, "null");
        }
        std::fprintf(f, ", \"train_sharpe\": %s, \"oos_sessions\": %d, \"oos_trades\": %d, \"oos_pnl_usd\": %s, \"oos_sharpe\": %s}",
                     jnum(x.trainSharpe).c_str(), x.sessions, x.trades, jnum(x.pnl).c_str(), jnum(x.sharpe).c_str());
    }
    std::fprintf(f, "\n  ],\n  \"configs\": %d,\n  \"study_seconds\": %s,\n  \"engine\": \"%s\"\n}\n", configs,
                 jnum(seconds).c_str(), engine.c_str());
}

void printSummary(const Summary& s) {
    for (const auto& f : s.folds)
        std::printf("  fold %d: cfg %3d  train SR %6.2f  OOS trades %3d  OOS P&L %10.0f  OOS SR %6.2f\n", f.fold, f.cfg,
                    f.trainSharpe, f.trades, f.pnl, f.sharpe);
    std::printf("OOS: %d trades, net P&L $%.0f, net Sharpe %.2f, max DD $%.0f\n", s.trades, s.netPnl, s.netSharpe,
                s.maxDrawdown);
}

}  // namespace orb
