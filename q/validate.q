/ validate.q -- data-quality checks on the partitioned database

/ usage:  q q/validate.q -db db -qa qa

/ Writes qa/report.csv (one row per trade date x contract with a count per check) and qa/excl
/ (the date x contract pairs that fail a hard check). Excluded sessions are never traded and
/ are left out of the rv20 / relative-volume history in features.q.

/ Hard checks (exclude the session):
/   badOHLC   high below max(open,close), low above min(open,close), or low above high
/   nonPos    a non-positive price
/   negVol    negative volume
/   dup       repeated timestamp for the same contract
/   offMin    timestamp not on a whole minute
/   wrongDay  bar stored under the wrong trade date
/ Soft check (reported only):
/   jump      |1-minute log return| above .cfg.jumpTh

.orb.here:{p:"/" vs string .z.f; $[1<count p; "/" sv -1_p; "."]}[];
system "l ",.orb.here,"/config.q";

a:.Q.opt .z.x;
dbPath:.cfg.abs .cfg.opt[a;`db;"db"];
qaPath:.cfg.abs .cfg.opt[a;`qa;"qa"];
system "l ",dbPath;

chkDay:{[d]
  t:select sym, ts, open, high, low, close, volume from bars where date=d;
  t:update r:log close % prev close by sym from t;
  c:0!select n:count i,
      badOHLC:sum (high<open|close) or (low>open&close) or low>high,
      nonPos:sum (open<=0) or (high<=0) or (low<=0) or close<=0,
      negVol:sum volume<0,
      dup:(count ts)-count distinct ts,
      offMin:sum 0<(`long$ts) mod 60000000000,
      wrongDay:sum d<>`date$ts+0D06:00:00,
      jump:sum .cfg.jumpTh<abs r
    by sym from t;
  update date:d from c}

rep:raze chkDay each date;
rep:`date`sym xcols update sym:`$string sym from rep;
excl:select date, sym from rep where (badOHLC>0) or (nonPos>0) or (negVol>0) or (dup>0) or (offMin>0) or wrongDay>0;

system "mkdir -p ",qaPath;
(hsym `$qaPath,"/report.csv") 0: csv 0: rep;
(hsym `$qaPath,"/excl") set excl;

-1 "partitions checked:   ",string count date;
-1 "date x contract rows: ",string count rep;
-1 "hard-fail sessions:   ",string count excl;
-1 "flagged jumps (kept): ",string sum rep`jump;
if[count excl; -1 "excluded:"; show excl];
exit 0
