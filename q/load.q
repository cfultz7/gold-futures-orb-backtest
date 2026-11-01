/ load.q -- vendor 1-minute CSVs -> date-partitioned kdb+ database

/ usage:  q q/load.q -raw data/raw -db db

/ Input: every *.csv in -raw, each with the header   ts,sym,open,high,low,close,volume
/   ts     bar START time in America/New_York, ISO format: 2020-01-02T08:20:00
/          (tools/utc_to_et.py converts UTC vendor files)
/   sym    contract code: GCZ24 (GCZ4 / GCZ2024 also accepted)

/ Output: db/<trade date>/bars/ splayed and partitioned by CME trade date, sorted by sym,ts,
/ with the parted attribute on sym. Globex bars from 18:00 ET belong to the next trade date.
/ Files are appended one at a time, so memory use is bounded by the largest single file.

.orb.here:{p:"/" vs string .z.f; $[1<count p; "/" sv -1_p; "."]}[];
system "l ",.orb.here,"/config.q";

a:.Q.opt .z.x;
rawDir:.cfg.abs .cfg.opt[a;`raw;"data/raw"];
dbDir:hsym `$.cfg.abs .cfg.opt[a;`db;"db"];

if[0<count key dbDir; -2 "refusing to append to non-empty ",(1_string dbDir),": delete it and rerun"; exit 1];

files:key hsym `$rawDir;
files:files where files like "*.csv";
if[0=count files; -2 "no csv files in ",rawDir; exit 1];

partPath:{[d] `$(string dbDir),"/",(string d),"/bars/"};

readCsv:{[f]
  t:("PSFFFFJ";enlist ",") 0: f;
  if[not (cols t)~`ts`sym`open`high`low`close`volume; '"bad header in ",string f];
  t}

/ trade date: shifting by 6h maps 18:00 ET (Globex reopen) to 00:00 of the next calendar day
tradeDate:{[ts] `date$ts+0D06:00:00};

writeFile:{[f]
  t:readCsv .Q.dd[hsym `$rawDir;f];
  t:update tdate:tradeDate ts from t;
  {[t;d] (partPath d) upsert .Q.en[dbDir] delete tdate from select from t where tdate=d}[t] each distinct t`tdate;
  -1 "  ",(string f),"  rows=",string count t;
 }

/ sort each partition by sym,ts and set the parted attribute
finalize:{[d]
  p:partPath d;
  `sym`ts xasc p;          / xasc on a splayed path sorts the table on disk
  @[p;`sym;`p#];
 }

-1 "loading ",(string count files)," file(s) from ",rawDir;
writeFile each files;
parts:asc "D"$string k where (k:key dbDir) like "[0-9][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]";
finalize each parts;
-1 "wrote ",(string count parts)," partitions to ",1_string dbDir;
exit 0
