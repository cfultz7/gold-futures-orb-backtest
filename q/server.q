/ server.q -- streams session features and bars to the C++ backtester over kdb+ IPC

/ usage:  q q/server.q -work work -p 5010

/ Protocol (the client drives it):
/   client -> server, async:  .orb.stream[d0;d1]         d0,d1 dates, inclusive
/   server -> client, async:  (`day; d; featRows; bars)   one message per session, in date order
/                             (`done; nSessions)          end of stream
/ featRows has one row per opening-range length; bars are the front contract's window bars.
/ Sessions with no bars still send a `day message, so the client sees every trading day
/ (days without a trade count as zero P&L in the Sharpe ratio).

/ Sync helpers for interactive checks:  .orb.dates[]   .orb.day[d]

.orb.here:{p:"/" vs string .z.f; $[1<count p; "/" sv -1_p; "."]}[];
system "l ",.orb.here,"/config.q";

a:.Q.opt .z.x;
workPath:.cfg.abs .cfg.opt[a;`work;"work"];
if[0=system "p"; system "p 5010"];

feat:update `s#date from `date`orMin xasc get hsym `$workPath,"/feat";
fbars:update `s#date from `date`tmin xasc get hsym `$workPath,"/fbars";

.orb.dates:{[] asc distinct exec date from feat};
.orb.day:{[d] (select from feat where date=d; select from fbars where date=d)};

.orb.stream:{[d0;d1]
  h:neg .z.w;
  ds:.orb.dates[];
  ds:ds where ds within (d0;d1);
  {[h;d] h (`day; d; select from feat where date=d; select from fbars where date=d); h[]}[h] each ds;
  h (`done; count ds);
  h[];
 }

.z.po:{-1 (string .z.p)," client connected, handle ",string x};
.z.pc:{-1 (string .z.p)," client closed, handle ",string x};

-1 "serving ",(string count .orb.dates[])," sessions on port ",string system "p";
