/ export.q -- write the feature set to CSV for the Python and C++ walk-forward simulators

/ usage:  q q/export.q -work work -out export

/ export/feat.csv  date(yyyymmdd), sym, orMin, orHigh, orLow, orVol, nOR, orRv, rv20, relVol,
/                  wToV, cover, nPrior, nRel, ok(0/1)
/ export/bars.csv  date(yyyymmdd), tmin(minutes after midnight ET), sym, open, high, low, close, volume

/ Floats are printed with 17 significant digits so they parse back to the same doubles the
/ IPC stream sends; the CSV route and the kdb+ route therefore feed identical inputs.

.orb.here:{p:"/" vs string .z.f; $[1<count p; "/" sv -1_p; "."]}[];
system "l ",.orb.here,"/config.q";

a:.Q.opt .z.x;
workPath:.cfg.abs .cfg.opt[a;`work;"work"];
outPath:.cfg.abs .cfg.opt[a;`out;"export"];

feat:get hsym `$workPath,"/feat";
fbars:get hsym `$workPath,"/fbars";

system "P 17";
ymd:{(10000*`year$x)+(100*`mm$x)+`dd$x};

fe:select date:ymd date, sym, orMin, orHigh, orLow, orVol, nOR, orRv, rv20, relVol, wToV, cover, nPrior, nRel, ok:`long$ok from feat;
be:select date:ymd date, tmin, sym, open, high, low, close, volume from fbars;

system "mkdir -p ",outPath;
(hsym `$outPath,"/feat.csv") 0: csv 0: fe;
(hsym `$outPath,"/bars.csv") 0: csv 0: be;
-1 "wrote ",(string count fe)," feature rows and ",(string count be)," bars to ",outPath;
exit 0
