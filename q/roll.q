/ roll.q -- look-ahead-safe front-month calendar

/ usage:  q q/roll.q -db db -qa qa

/ Rule: the front contract for trade date d is decided only from sessions that finished
/ before d opened.
/   1. lead(d)  = outright contract with the most volume over the whole trade date d
/   2. conf(d)  = min contract ordinal of lead over the k sessions before d (k = .cfg.rollConfirm),
/                 so a later contract takes over only after leading k sessions in a row
/   3. front(d) = running max of conf, so the calendar never rolls backwards
/ Nothing from session d itself (its volume, prices or expiry behaviour) enters front(d).

/ There is no back-adjusted continuous series: every trade opens and closes inside one session
/ on the contract that was front at the open, so nothing has to be spliced across a roll.

/ Output: qa/roll (q table) and qa/roll.csv with columns date, lead, front, rolled.

.orb.here:{p:"/" vs string .z.f; $[1<count p; "/" sv -1_p; "."]}[];
system "l ",.orb.here,"/config.q";

a:.Q.opt .z.x;
dbPath:.cfg.abs .cfg.opt[a;`db;"db"];
qaPath:.cfg.abs .cfg.opt[a;`qa;"qa"];
system "l ",dbPath;

/ months since year 0 for an outright code like GCZ24; null for spreads or other roots
ordinal:{[s]
  c:string s; n:count .cfg.root;
  if[not .cfg.root~n#c; :0N];
  m:.cfg.mcodes?c n;
  if[m>=count .cfg.mcodes; :0N];
  y:"J"$(n+1)_c;
  y:$[y<10; 2020+y; y<100; 2000+y; y];    / 1-digit years are read as 202x
  (12*y)+m}

dv:0!select vol:sum volume by date, sym from bars;
dv:update sym:`$string sym from dv;
om:s!ordinal each s:distinct dv`sym;
dv:select from dv where not null om sym;

lead:`date xasc 0!select first sym by date from dv where vol=(max;vol) fby date;
lead:update o:om sym from lead;
lead:update conf:.cfg.rollConfirm mmin prev o from lead;
lead:update fo:maxs conf from lead;

om:k!om k:where not null om;             / outrights only, so a null ordinal maps back to a null sym
symOf:(value om)!key om;
roll:select date, lead:sym, front:symOf fo from lead;
roll:update rolled:(differ front) & not null front from roll;

system "mkdir -p ",qaPath;
(hsym `$qaPath,"/roll") set roll;
(hsym `$qaPath,"/roll.csv") 0: csv 0: roll;

-1 "sessions:          ",string count roll;
-1 "no front (warmup): ",string sum null roll`front;
-1 "rolls:             ",string sum roll`rolled;
show select date, lead, front from roll where rolled;
exit 0
