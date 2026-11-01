/ config.q -- parameters shared by the q pipeline scripts
/ Session times must match sess_open / sess_close in config/orb.cfg.

\d .cfg
root:"GC";                  / contract root; codes look like GCZ24 (GCZ4 and GCZ2024 are accepted too)
mcodes:"FGHJKMNQUVXZ";      / CME month codes, Jan..Dec
sessOpen:08:20;             / COMEX day-session open, America/New_York, bar-start time
sessClose:13:30;            / window is [08:20,13:30): last bar starts 13:29
expMin:310;                 / minutes in the window
orMins:5 15 30 60;          / opening-range lengths (minutes) to precompute
rollConfirm:2;              / a new contract must lead daily volume this many prior sessions in a row
jumpTh:0.05;                / |1-minute log return| above this is flagged in the QA report (not excluded)
minCover:0.9;               / minimum fraction of the 310 window minutes that must be present
minHist:15;                 / minimum prior valid sessions before rv20 / relative volume are trusted
lookback:20;                / trailing window (sessions) for rv20 and relative volume
\d .

/ absolute path from a possibly relative one (loading a database with \l changes the working directory)
.cfg.abs:{[p] $["/"=first p; p; (raze system "cd"),"/",p]}
/ command-line option with a default
.cfg.opt:{[d;k;dflt] $[k in key d; first d k; dflt]}
/ finite test that is false for nulls and infinities (in q a float null sorts below -0w)
.cfg.fin:{(x>-0w) & x<0w}
