#pragma once
// Loader for export/feat.csv and export/bars.csv (written by q/export.q).

#include <string>
#include <vector>

#include "orb/types.hpp"

namespace orb {

// Sessions in date order, one per feature date; bars sorted by minute.
std::vector<Session> loadExport(const std::string& dir, double tick);

// Minimal comma-separated reader with a header row (no quoting; the exports never need it).
class CsvReader {
public:
    explicit CsvReader(const std::string& path);
    ~CsvReader();
    bool next();                                  // advance to the next data row
    int col(const std::string& name) const;       // column index, throws if missing
    const std::string& str(int i) const { return row_[i]; }
    double num(int i) const;                      // tolerates q's trailing 'f' on whole floats
    long long integer(int i) const;
    const std::string& path() const { return path_; }

private:
    std::string path_;
    void* in_;  // std::ifstream, kept out of the header
    std::vector<std::string> header_, row_;
    std::string line_;
};

}  // namespace orb
