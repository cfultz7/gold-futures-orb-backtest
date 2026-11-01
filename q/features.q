/ features.q -- session features for the front contract

/ usage:  q q/features.q -db db -qa qa -work work

/ For each trade date with a front contract (qa/roll), takes the front contract's bars in the
/ day-session window [08:20,13:30) ET and computes, for each opening-range length k in .cfg.orMins:

/   orHigh, orLow  high / low of the first k minutes
/   orVol, nOR     volume and bar count of the first k minutes
/   orRv           realized vol of 1-minute log returns inside the opening range
/   rv20           mean daily realized vol (window returns) over the previous 20 sessions
/   relVol         orVol / mean orVol (same k) over the previous 20 sessions
/   wToV           (orHigh-orLow) / (rv20 * OR midpoint): OR width relative to typical session vol
/   cover          fraction of the 310 window minutes present
/   ok             session is tradable for this k (see below)

/ Look-ahead: everything in a row is known when the opening range closes. rv20 and relVol use
/ prev (prior sessions only). Sessions excluded by validate.q, or with low coverage, are left
/ out of the trailing history rather than averaged in.

/ Output: work/feat (date, sym, orMin, features...), work/fbars (window bars of the front
/ contract: date, sym, tmin, open, high, low, close, volume), work/dayt (per-session stats).
/ Non-finite values are written as 0 with ok=0, so every consumer sees finite numbers.

.orb.here:{p:"/" vs string .z.f; $[1<count p; "/" sv -1_p; "."]}[];
system "l ",.orb.here,"/config.q";

a:.Q.opt .z.x;
dbPath:.cfg.abs .cfg.opt[a;`db;"db"];
qaPath:.cfg.abs .cfg.opt[a;`qa;"qa"];
workPath:.cfg.abs .cfg.opt[a;`work;"work"];
system "l ",dbPath;

roll:get hsym `$qaPath,"/roll";
excl:get hsym `$qaPath,"/excl";
w0:.cfg.sessOpen;
w1:.cfg.sessClose-1;
L:.cfg.lookback;
H:.cfg.minHist;

/ opening-range stats for window bars b (with minute column m) and range length k
orStats:{[b;k]
  o:select from b where m<w0+k;
  r:log o[`close] % prev o`close;
  `orHigh`orLow`orVol`nOR`orRv!(max o`high; min o`low; sum o`volume; count o; sqrt sum r*r)}

/ one session: (day stats; feature rows; window bars)
mkDay:{[d;f]
  b:select ts, open, high, low, close, volume from bars where date=d, sym=f;
  b:select from (update m:`minute$ts from b) where m within (w0;w1);
  b:`ts xasc b;
  n:count b;
  r:log b[`close] % prev b`close;
  ex:0<count select from excl where date=d, sym=f;
  day:`date`sym`nWin`rvDay`excluded!(d; f; n; $[n; sqrt sum r*r; 0n]; ex);
  k:count .cfg.orMins;
  ft:([] date:k#d; sym:k#f; orMin:.cfg.orMins) ,' orStats[b] each .cfg.orMins;
  wb:([] date:n#d; sym:n#f; tmin:`long$b`m; open:b`open; high:b`high; low:b`low; close:b`close; volume:b`volume);
  if[ex; wb:0#wb];   / excluded sessions never trade; their bars may hold duplicates, so ship none
  (day; ft; wb)}

days:select date, front from roll where not null front;
-1 "building features for ",(string count days)," sessions";
res:mkDay'[days`date; days`front];
dayt:raze {enlist x 0} each res;
feat:raze res[;1];
fbars:`date`tmin xasc raze res[;2];

/ trailing realized vol: excluded or thin sessions drop out of the history
dayt:update rvUse:?[excluded or nWin<.cfg.minCover*.cfg.expMin; 0n; rvDay] from dayt;
dayt:update rv20:prev L mavg rvUse, nPrior:prev L mcount rvUse from dayt;

feat:feat lj `date xkey select date, nWin, excluded, rv20, nPrior from dayt;
feat:update ovv:?[(nOR=orMin) & not excluded; `float$orVol; 0n] from feat;
feat:update relVol:orVol % prev L mavg ovv, nRel:prev L mcount ovv by orMin from feat;
feat:update cover:nWin % .cfg.expMin, wToV:(orHigh-orLow) % rv20*0.5*orHigh+orLow from feat;
feat:update ok:(not excluded) & (nOR=orMin) & (cover>=.cfg.minCover) & (H<=0^nPrior) & (H<=0^nRel) & (rv20>0) & (.cfg.fin relVol) & (.cfg.fin wToV) & orHigh>orLow from feat;

fix:{?[.cfg.fin x; x; 0f]};
feat:update orHigh:fix orHigh, orLow:fix orLow, orRv:fix orRv, rv20:fix rv20, relVol:fix relVol, wToV:fix wToV, nPrior:0^nPrior, nRel:0^nRel from feat;
feat:`date`orMin xasc select date, sym, orMin, orHigh, orLow, orVol, nOR, orRv, rv20, relVol, wToV, cover, nPrior, nRel, ok from feat;

system "mkdir -p ",workPath;
(hsym `$workPath,"/feat") set feat;
(hsym `$workPath,"/fbars") set fbars;
(hsym `$workPath,"/dayt") set dayt;

-1 "sessions:       ",string count dayt;
-1 "window bars:    ",string count fbars;
-1 "feature rows:   ",string count feat;
show select sessions:count i, tradable:sum ok by orMin from feat;
exit 0
