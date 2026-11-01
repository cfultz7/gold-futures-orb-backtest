#pragma once
// Event sources for the backtester.

#include <deque>
#include <memory>
#include <string>
#include <vector>

#include "orb/engine.hpp"

namespace orb {

// Replays export/feat.csv + export/bars.csv for sessions with from <= date <= to.
class CsvReplaySource : public EventSource {
public:
    CsvReplaySource(const std::string& dir, double tick, int from, int to);
    bool next(Event& ev) override;
    std::string describe() const override;

private:
    std::vector<Session> sessions_;
    std::string dir_;
    size_t s_ = 0;   // session index
    size_t b_ = 0;   // bar index within the session
    int phase_ = 0;  // 0 start, 1 bars, 2 end
};

#ifdef ORB_WITH_KDB
// Subscribes to q/server.q: sends .orb.stream[from;to] asynchronously, then reads the
// (`day; date; features; bars) messages the server pushes until (`done; n).
class KdbSource : public EventSource {
public:
    KdbSource(const std::string& host, int port, int from, int to, double tick);
    ~KdbSource() override;
    bool next(Event& ev) override;
    std::string describe() const override;

private:
    bool pull();  // read one IPC message into queue_
    std::string host_;
    int port_, handle_ = -1;
    double tick_;
    bool done_ = false;
    size_t messages_ = 0;
    std::deque<Event> queue_;
};
#endif

}  // namespace orb
