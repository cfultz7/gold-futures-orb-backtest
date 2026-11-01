// kdb+ IPC event source. Built only with -DORB_WITH_KDB=ON (needs k.h and c.o from
// github.com/KxSystems/kdb: c/c/k.h and l64/c.o, or m64/c.o on macOS).
//
// k.h defines short macros (R, O, P, U, Z, xs, xt, nf, ...) and global typedefs (K, S, I, J, F),
// so it is included last and nothing after it uses those names.

#include <cstring>
#include <stdexcept>
#include <string>

#include "orb/sources.hpp"

#define KXVER 3
#include "k.h"

namespace orb {

namespace {

struct Guard {  // releases a K object on scope exit
    K obj;
    ~Guard() { if (obj) r0(obj); }
};

S mut(const char* s) { return const_cast<S>(s); }

K column(K tbl, const char* name) {
    if (tbl->t != XT) throw std::runtime_error("kdb: expected a table");
    K dict = tbl->k;
    K names = kK(dict)[0];
    K cols = kK(dict)[1];
    for (J i = 0; i < names->n; ++i)
        if (std::strcmp(kS(names)[i], name) == 0) return kK(cols)[i];
    throw std::runtime_error(std::string("kdb: table has no column ") + name);
}

double fval(K v, J i) {
    switch (v->t) {
        case KF: return kF(v)[i];
        case KE: return kE(v)[i];
        case KJ: return static_cast<double>(kJ(v)[i]);
        case KI: return kI(v)[i];
        default: throw std::runtime_error("kdb: unexpected numeric column type " + std::to_string(v->t));
    }
}

long long jval(K v, J i) {
    switch (v->t) {
        case KJ: return kJ(v)[i];
        case KI: return kI(v)[i];
        case KH: return kH(v)[i];
        case KB:
        case KG: return kG(v)[i];
        default: throw std::runtime_error("kdb: unexpected integer column type " + std::to_string(v->t));
    }
}

int toKdbDate(int yyyymmdd) { return ymd(yyyymmdd / 10000, yyyymmdd / 100 % 100, yyyymmdd % 100); }

}  // namespace

KdbSource::KdbSource(const std::string& host, int port, int from, int to, double tick)
    : host_(host), port_(port), tick_(tick) {
    handle_ = khpu(mut(host_.c_str()), port_, mut(""));
    if (handle_ <= 0)
        throw std::runtime_error("kdb: cannot connect to " + host_ + ":" + std::to_string(port_) +
                                 (handle_ == 0 ? " (access denied)" : " (is q/server.q running?)"));
    // async request; the server answers with a stream of async messages
    K sent = k(-handle_, mut(".orb.stream"), kd(toKdbDate(from)), kd(toKdbDate(to)), static_cast<K>(nullptr));
    if (!sent) throw std::runtime_error("kdb: failed to send .orb.stream request");
}

KdbSource::~KdbSource() {
    if (handle_ > 0) kclose(handle_);
}

bool KdbSource::pull() {
    K msg = k(handle_, static_cast<S>(nullptr), static_cast<K>(nullptr));  // block for the next message
    if (!msg) throw std::runtime_error("kdb: connection closed before the stream finished");
    Guard g{msg};
    if (msg->t == -128) throw std::runtime_error(std::string("kdb error: ") + msg->s);
    if (msg->t != 0 || msg->n < 2 || kK(msg)[0]->t != -KS) throw std::runtime_error("kdb: unexpected message shape");
    ++messages_;

    const std::string tag = kK(msg)[0]->s;
    if (tag == "done") {
        done_ = true;
        return false;
    }
    if (tag != "day" || msg->n != 4) throw std::runtime_error("kdb: unexpected message tag " + tag);

    const int date = dj(kK(msg)[1]->i);
    K feat = kK(msg)[2];
    K bars = kK(msg)[3];

    Event start;
    start.type = EvType::SessionStart;
    start.date = date;
    {
        K om = column(feat, "orMin"), ok = column(feat, "ok"), hi = column(feat, "orHigh"),
          lo = column(feat, "orLow"), rv = column(feat, "relVol"), wv = column(feat, "wToV");
        for (J i = 0; i < om->n; ++i) {
            Feature f;
            f.orMin = static_cast<int>(jval(om, i));
            f.ok = jval(ok, i) == 1;
            f.hi = toTicks(fval(hi, i), tick_);
            f.lo = toTicks(fval(lo, i), tick_);
            f.relVol = fval(rv, i);
            f.wToV = fval(wv, i);
            start.feats.push_back(f);
        }
    }
    queue_.push_back(std::move(start));
    {
        K tm = column(bars, "tmin"), op = column(bars, "open"), hp = column(bars, "high"),
          lp = column(bars, "low"), cp = column(bars, "close");
        for (J i = 0; i < tm->n; ++i) {
            Event e;
            e.type = EvType::Bar;
            e.date = date;
            e.bar.tmin = static_cast<int>(jval(tm, i));
            e.bar.o = toTicks(fval(op, i), tick_);
            e.bar.h = toTicks(fval(hp, i), tick_);
            e.bar.l = toTicks(fval(lp, i), tick_);
            e.bar.c = toTicks(fval(cp, i), tick_);
            queue_.push_back(std::move(e));
        }
    }
    Event end;
    end.type = EvType::SessionEnd;
    end.date = date;
    queue_.push_back(std::move(end));
    return true;
}

bool KdbSource::next(Event& ev) {
    while (queue_.empty()) {
        if (done_ || !pull()) return false;
    }
    ev = std::move(queue_.front());
    queue_.pop_front();
    return true;
}

std::string KdbSource::describe() const {
    return "kdb+ IPC stream from " + host_ + ":" + std::to_string(port_) + " (" + std::to_string(messages_) +
           " messages)";
}

}  // namespace orb
