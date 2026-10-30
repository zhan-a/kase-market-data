# A minute-resolution dataset for the Kazakhstan Stock Exchange: assembly, correctness, and board-feed identification

## Abstract

This note documents a 1-minute bar store for the Kazakhstan Stock Exchange (KASE):
2,476,602 bars across 24 instruments from 2015-05-25 to 2026-08-24, assembled from
the public chart-data endpoint of a retail broker, together with 119,650 bars of
Kaspi.kz's NASDAQ line from its listing in January 2024. The bars are not scarce;
the endpoint serves them without credentials to the broker's own charting page. The
work reported here is the correctness layer between that endpoint and a usable
panel. Seven defects in the response format, six of which produce a store that
raises no exception, carries plausible row counts and holds prices in the right
range while being wrong. One of them, a fixed UTC offset applied across Almaty's move from
UTC+6 to UTC+5 on 2024-03-01, is invisible to every price-based check and stores
every earlier bar one hour late. The served history carries artefacts of its own,
found by a later re-analysis and measured here by committed scripts: flat bars
outside the session in 2016 to 2019 that repeat the previous close, a collection
hole of 148 trading dates from June 2015 to January 2016, and 63 empty months
that the same endpoint's daily series contradicts.

A second source, KASE's own trade-results board, yields an operational fact and an
identification. The board publishes the completed previous session and does not
move during the trading day; it switches to the same day between 17:30 and 17:35
Almaty, so every test on it joins one session back. Its fields labelled
`current_bid` and `current_offer` are not a two-sided quote: the bid exceeds the
ask on 90.6% of 2,257 instrument-sessions, and the pair collapses onto the
session's high and low in 71.2% of one-deal sessions and 0.5% of sessions with
more than 1,000 deals. The reading most consistent with the tests is that the
fields hold the session's extreme quotes, the highest bid and the lowest offer
posted, with a containment residual the reading does not explain. A third
endpoint, reachable only by POST, publishes a best bid, a best ask and a spread
field; this project observed its schema and not its values, and the trade-based
cost estimates of the companion repository stand in place of it.

## 1. Introduction

Institutional vendors sell KASE market data by the seat. The minute history behind
that pricing is nonetheless reachable from a public endpoint, because a retail
broker has to render candlesticks for its customers. What did not exist was a
packaged, timestamp-correct, validated store with its gaps classified.

The contribution is assembly, validation and documentation. Acquisition took an
afternoon. The rest of this note covers what was needed after that: the defects
of the endpoint (Section 3), the properties of the served history that a user has
to filter for (Section 2), two properties of KASE's board endpoint that determine
what can be asked of it (Section 4), and the checks that were run (Section 5).
Every number here is printed by a committed script or read from a committed
table; `data/README.md` maps each table to its producer, and
`docs/reproducibility.md` records the regeneration.

An independent verification of this repository on 2026-10-12 and a later, stricter
re-analysis of the same market by the author (2026-10-16), both unpublished,
changed this document. The verification found that the board-feed statistics of
Section 4 had no producing script and that the bar counts were stale; the
identification is now computed by `analysis/board_fields.py` and the counts by the
fetcher's own check. The re-analysis found the off-session bars of Section 2.5,
the change in the daily companion of Section 2.7 and the exchange's closing-time
history of Section 2.4; each is now measured by a committed script and stated in
place. Neither document is one a reader can open.

## 2. Data and acquisition

### 2.1 Sources and instruments

The KASE lines come from the chart-data endpoint of Tradernet, Freedom Finance's
retail platform, which returns JSON candle arrays for a requested instrument and
date window. The same endpoint serves the `.US` line for KSPI's NASDAQ listing.
KASE's own public JSON API at `kase.kz/api/trade-results/` supplies the board
snapshots of Section 4; it carries no quote, and a different KASE endpoint does
(Section 4.3).

The 24 instruments are the ones this project needed, listed in the fetcher: 17 KZT
equity lines (AIRA, ASBN, BAST, BSUL, CCBN, HSBK, IFDR, KASE, KCEL, KEGC, KMGD,
KMGZ, KSPI, KZAP, KZTK, KZTO, RAHT), three USD depositary lines (HSBKD, KSPID,
KZAPD) and four on-exchange currency lines (USDKZT_TOM, EURKZT_TOM, RUBKZT_TOM,
CNYKZT_TOM). The manifest also lists four preferred-share lines (AMGZp, CCBNp,
KZTKp, MMGZp) that the endpoint reports as unavailable; their daily files are
empty and `collection_gap_instruments.csv` carries them with zero counts. All 24
are names listed in 2026; no delisted name is in the store, so any cross-section
built on it is survivor-only.

Each row carries `ts_utc` (bar start, tz-aware), the same instant as `ts_almaty`
or `ts_ny`, open, high, low and close in KZT for `.KZ` lines and USD for the
depositary and `.US` lines, and volume in shares. Bars exist only for minutes in
which a trade occurred.

### 2.2 Coverage

The table is `data/derived/store_inventory.csv`, written by
`analysis/store_inventory.py`; the fetcher's `--verify` prints the same partition
and bar counts. A partition is one instrument-month; a zero-row partition is a
month the fetcher checked and found empty (Section 3.4 says why that is not the
same as a month without trading).

| instrument | partitions | zero-row | bars | sessions | first bar |
|---|---|---|---|---|---|
| AIRA.KZ | 31 | 0 | 143,848 | 621 | 2024-02-09 |
| ASBN.KZ | 124 | 6 | 270,583 | 1,792 | 2016-05-16 |
| BAST.KZ | 140 | 18 | 29,408 | 1,913 | 2016-01-29 |
| BSUL.KZ | 124 | 21 | 8,811 | 1,330 | 2016-05-23 |
| CCBN.KZ | 138 | 9 | 169,598 | 2,559 | 2015-06-01 |
| CNYKZT_TOM.KZ | 90 | 11 | 8,474 | 1,086 | 2019-03-27 |
| EURKZT_TOM.KZ | 75 | 10 | 9,993 | 984 | 2020-07-01 |
| HSBK.KZ | 138 | 13 | 389,219 | 2,504 | 2015-05-25 |
| HSBKD.KZ | 73 | 2 | 9,012 | 1,064 | 2020-09-01 |
| IFDR.KZ | 35 | 0 | 3,087 | 632 | 2023-10-06 |
| KASE.KZ | 121 | 45 | 7,614 | 872 | 2016-08-23 |
| KCEL.KZ | 138 | 8 | 104,168 | 2,600 | 2015-05-26 |
| KEGC.KZ | 138 | 8 | 218,531 | 2,607 | 2015-05-25 |
| KMGD.KZ | 117 | 39 | 145,694 | 1,243 | 2016-12-14 |
| KMGZ.KZ | 45 | 0 | 116,693 | 910 | 2022-12-08 |
| KSPI.KZ | 98 | 33 | 106,898 | 1,263 | 2018-07-23 |
| KSPID.KZ | 63 | 1 | 12,537 | 1,051 | 2021-06-22 |
| KZAP.KZ | 93 | 0 | 145,192 | 1,860 | 2018-12-11 |
| KZAPD.KZ | 8 | 0 | 1,786 | 156 | 2026-01-05 |
| KZTK.KZ | 138 | 8 | 43,491 | 2,581 | 2015-05-25 |
| KZTO.KZ | 138 | 8 | 229,727 | 2,608 | 2015-05-25 |
| RAHT.KZ | 127 | 26 | 10,332 | 1,145 | 2016-02-02 |
| RUBKZT_TOM.KZ | 140 | 77 | 61,089 | 1,105 | 2019-10-01 |
| USDKZT_TOM.KZ | 140 | 55 | 230,817 | 1,610 | 2019-03-27 |
| KSPI.US (NASDAQ) | 27 | 0 | 119,650 | 551 | 2024-01-19 |

The KASE store holds 2,472 partitions, 398 of them zero-row, and 2,476,602 bars;
every line runs to 2026-08-24. The NASDAQ line runs to 2026-03-31; its partitions
hold 119,676 rows, 26 of them exact repeats at month boundaries (Section 3.6),
which the inventory drops before counting. A first bar is
not the start of usable history: KSPI.KZ has 11 bars in 10 sessions in 2018 and
none in 2019 or 2020, then 1,928 bars in 2021 from July, 8,526 in 2022 and 25,591
in 2024 (`store_bars_by_year.csv`). `USDKZT_TOM` is the traded rate rather than
the National Bank's fixing: 230,817 bars over 1,610 sessions, with a median first
bar at 10:16 and last bar at 16:59 Almaty (`session_bounds.csv`).

### 2.3 What a session looks like

Over the 636 KSPI.KZ sessions from 2024-01-19 to 2026-08-24 the median session
holds 128 bars (`session_summary.csv`, written by `analysis/session_structure.py`).
Bars exist only for minutes with a trade: 45.8% of consecutive bars within a
session are one minute apart, the median gap is 2 minutes and the 90th percentile
6. Forward-filling onto a regular grid manufactures zero returns and biases
volatility and autocorrelation estimates downward. A missing minute inside a
covered session records the absence of a trade; at session level absence is
ambiguous (Section 2.6).

The session has a shape. An opening auction prints at 11:29 on 97.8% of those
sessions, continuous trading runs to 17:14, no bar falls between 17:15 and 17:24
on any session, and a closing auction prints at 17:25 on 71.2% of sessions and is
the session's last bar on 48.3%. No bar in that window falls before 11:29 or after
17:30. Treating the first bar as the price a trader could obtain at the open
conflates an auction clearing price with a continuous quote, which changes
transmission coefficients materially (the companion `kase-price-discovery`
repository).

### 2.4 The exchange's hours over the sample

The session of Section 2.3 is the current one. `session_end_monthly.csv` pools the
last bar of six equities (HSBK, KZTO, KEGC, CCBN, KSPI, KZAP) by month, and
`session_bounds_by_year.csv` gives every instrument by year. Through November 2019 the
pooled median last bar is 16:58 or 16:59 in most months and 16:39 to 16:44 in most
of the others, a 17:00 close; four months fall outside both bands, 2016-01 (15:42,
on four instrument-sessions), 2016-04 (16:21), 2017-11 (17:04) and 2018-10
(16:57). The 90th percentile in 2016 to 2019 often reads 18:00 or later, which is
the after-hours bars of Section 2.5 and not the exchange. From December 2019 the
90th percentile moves to 17:09 and reaches 17:11 to 17:14 in the first quarter of
2020, a 17:15 close that the median shows only as the liquid names reach it; in
2021 it lies between 17:05 and 17:13. From December 2022 the median is 17:25 in
nearly every month and the 90th percentile 17:27 to 17:29, the current regime
with its auction print. Two episodes shortened the day. In April
2020 the median last bar was 12:36, in May 2020 14:39, back to 17:01 in June, down
to 14:38 in July and 14:42 in September, back to 16:45 in October: shortened
schedules during the pandemic. In January 2022 the median last bar was 15:14
against 17:06 in December 2021 and 17:09 in February 2022 (Section 2.6 gives the
days). Anything that depends on wall-clock time, a volume-at-time-of-day profile
or a closing window, has to be computed against the regime in force.

### 2.5 Bars outside the session, 2016 to 2019

A later re-analysis of this market by the author found that the served history
before 2021 carries bars outside the session that are not trades, and
`session_bounds_by_year.csv` measures them. In 2016 and 2017 the median first bar
of HSBK, KZTO and KEGC is 09:00, in 2018 09:30 and in 2019 10:30, and 93.5% to
99.2% of their sessions in those four years begin with a bar before 11:00. Among
those early first bars, the share whose close equals the previous session's last
close is 97.3% to 100% in 2016 and 2017, 98.7% in 2018 and 95.2% in 2019: a flat
bar that repeats yesterday's close at a fixed time of the morning. CCBN and KZTK
show the same times and the same repeat rates (94.7% to 100%). Bars after 17:35
appear in the same years, 0.4% to 8.3% of a name's bars, and fall below 0.1% of
these names' bars from 2021.
The fetcher does not filter these bars, so a user of the 2016 to 2019 history
should keep bars from 11:29 to the regime's closing time and treat a session that
consists of one such bar as no session. The 2020 rows are different: the early
bars sit at 10:00, only 3.6% to 21.1% of them repeat the previous close, and they
are real trades under the shortened schedules of Section 2.4.

### 2.6 Absence: closures, a halt, and a collection hole

A missing session has four possible causes, a scheduled closure, a halt, a hole
in the vendor's history and a failure at fetch time, and the acquisition path
separates only some of them. `analysis/store_inventory.py` writes the evidence.

Scheduled closures. Over 2024-01-19 to 2026-08-24, the window the companion
repository studies, 43 of 677 weekdays have no bar in any instrument, with no run
longer than three, and the daily series of Section 2.7 has no row on any of them
either (`market_closures.csv` counts both). Three of them, 2024-12-12, 2025-04-28
and 2025-04-29, match no public holiday and no closure that KASE announced in its
monthly schedule notices; the rest fall on Kazakhstan's national holidays, on the
weekdays to which weekend holidays are moved, and on two days off exchanged for
working weekend days. For the three, `analysis/probe_endpoint.py` asked the
endpoint again on 2026-10-30, one day per request, for KSPI, HSBK and USDKZT_TOM:
neither the minute nor the daily reply carried a point dated on the requested day,
while the daily replies carried the sessions on either side. The NASDAQ line has
no bars on 2025-04-28 either, a day NASDAQ traded (Section 5), and the endpoint
served no minute or daily point for it on that day. The three days are absent at
the vendor, in minute and daily data alike, rather than lost at fetch time, and
their cause is not known. Two weekend days in the window, Saturday 2024-05-04 and
Sunday 2025-01-05, have trading in 20 and 21 instruments: working weekends are
real in this market.

A halt. No instrument trades on 2022-01-03, 01-04, 01-06, 01-07 or 01-10; 13
instruments trade on 01-05 and 9 on 01-11; and from 01-11 to 01-21 the median
last bar lies between 14:59 and 15:13 against 16:19 to 16:59 in the last two
weeks of December and 17:04 on 01-24 (`halt_2022.csv`). That is the January 2022
unrest, read off the tape.

A collection hole. Between 2015-06-24 and 2016-01-28 the store holds zero bars for
every instrument on 148 dates on which the daily series shows trading
(`collection_gaps.csv`). Nine instruments have daily bars inside the hole: KZTO on
all 148 dates, HSBK on 144, BAST 143, KEGC 142, KZTK 129, KCEL 123, CCBN 109, RAHT
6 and KASE 3 (`collection_gap_instruments.csv`), against zero minute bars each.
The window contains the August 2015 tenge float. More broadly, 398 of the 2,472
monthly partitions are zero-row, and 63 of them are contradicted by the daily
series (`zero_row_partitions.csv`): 58 are 2015 months of BAST, CCBN, HSBK, KCEL,
KEGC, KZTK and KZTO, and five are HSBK alone in 2020-08, 2020-10, 2021-02,
2021-03 and 2021-04. The other 335 are months in which the daily series shows no
trading either.

The two groups have different causes, and `analysis/probe_endpoint.py` asks the
endpoint directly; its output is a dated observation, not a table. On 2026-10-30
a one-week minute request inside the hole (2015-07-06 to 2015-07-10) returned 1
point, the leading reference bar of Section 3.6 and nothing inside the window,
while the daily request for the same week returned 5 points and a control week
before the hole returned 38 minute points. The minute history behind the hole,
and behind the 42 contradicted months of July to December 2015 inside it, is
absent at the endpoint rather than lost by the fetcher, which recorded those
months empty correctly; the 16 contradicted months of March to June 2015, before
and around the first minute bar, were not probed. The five HSBK months of 2020
and 2021 are different: on the same day the endpoint
returned 1,220, 1,074, 1,860, 2,107 and 3,348 minute points for them, so they
were a failure at fetch time, which `--backfill --refetch --ticker HSBK.KZ`
repairs. The committed store was left as it was, because the companion
repository's gated results read it; a rebuilt store will differ in those five
months.

This changed a reported result. The companion repository prices a 20 December to
10 January window on a nine-name basket from this store; its 2015 window lies
entirely inside the hole, so an earlier version of that result covered 2016 to
2025 only and read as positive in all ten windows. Priced from the daily series,
the 2015 window returns -3.92%, the most adverse of the eleven; the eleven-window
mean is +3.148% (t 3.574, 10 of 11 positive) against +3.855% for the ten
(`kase-price-discovery`, `data/derived/yearend_windows.csv` and Section 9 of its
write-up). The cost of a hole that the store cannot distinguish from an absence of
trading is therefore not hypothetical. It changed a result, silently, and in the
favourable direction.

### 2.7 The daily companion

The remedy is a daily series from the same endpoint at daily resolution
(`src/kase/fetch_daily.py`), which answers for windows where the minute request
returns nothing. It resolves whether a minute-level hole is a closure or a
failure, and it is what priced the 2015 window above.

It is not a substitute for the minute store, and from 2026-03-10 it is not a
check on it either (`daily_vs_minute_monthly.csv`). Through 2026-03-06 the daily
close equals the close of the minute store's last bar on 97.2% of 33,419
instrument-sessions, within 0.1% on 98.0%, and the daily volume equals the summed
minute volume at the median. From 2026-03-10 the daily close equals the last bar
on 17.5% of 2,677 instrument-sessions and lies within 0.1% on 35.2%, while it
still equals the close of some bar traded that day on 99.6% of them, and the
daily volume is 0.434 of the summed minute volume at the median. From that date
the daily bar covers only part of the session, with the close of some bar in the
day and about half of the day's volume; the minute store did not change. The
later re-analysis found the same break, and this table is its measurement.

### 2.8 Redistribution

The bars are not redistributed. The endpoint's terms do not clearly address
republication, so the fetchers are published and the bars are left where they
came from. The board recordings of Section 4 are not redistributed either: they
are exchange information under KASE's Rules for Exchange Information
Dissemination (Article 19), which make their inclusion in anyone's information
products conditional on an agreement with the exchange or its written permission.
The derived tables that the statements below rest on are committed;
`data/README.md` describes both decisions and names the one column of the
recordings, `fx_usdkzt`, that is not KASE data but a Yahoo Finance rate the
recorder added (KASE, 2025).

## 3. Correctness defects in the acquisition path

Six of the seven below leave the store looking intact: no exception, no empty
column, plausible counts, plausible prices. Each corrupts an analysis without
announcing itself. One of them, the timestamp frame of Section 3.1, corrupted
this project's own results twice and was caught after the fact rather than at
implementation.

### 3.1 Timestamps are venue-local wall clock in a fixed UTC+3 frame

The endpoint's `xSeries` values are not Unix epochs. They encode the venue's
local wall clock inside a fixed UTC+3 frame, so the conversion has to route
through the timezone database:

```
local_naive = raw + 3h  ->  localize to venue tz  ->  convert to UTC
```

The first implementation used a flat `raw - 2h`, which is correct for Almaty
after 2024-03-01 and wrong before it, because Kazakhstan moved Almaty from UTC+6
to UTC+5 on that date. Every bar before it was stored one hour late and every bar
after it correctly.

Nothing in the data reports this. Prices, volumes and session lengths are all
unaffected, and the error is absent from any statistic that does not reference
clock time. It surfaces in one check: each instrument's implied session open per
month. `implied_open_monthly.csv` carries the committed store's median first bar
for KSPI by month next to what a constant-offset conversion would have produced:

| month | committed store | constant offset |
|---|---|---|
| 2023-12 | 11:29 | 12:29 |
| 2024-01 | 11:29 | 12:29 |
| 2024-02 | 11:29 | 12:29 |
| 2024-03 | 11:29 | 11:29 |
| 2024-04 | 11:29 | 11:29 |
| 2024-05 | 11:29 | 11:29 |

The defective series steps by exactly one hour on exactly the date of the change;
the committed store is flat, because the exchange kept local hours. The fetcher's
`--verify` compares each equity's median session open against the 11:30 official
open for this reason, on the lines with at least 20 bars a day. That check is a
whole-history median, and it passes while the 2016 to 2019 bars of Section 2.5
sit at 09:00 to 10:30; the per-year table is the check that sees them.

The same frame has a second consequence. For `.US` lines, `raw + 3h` yields New
York wall clock, not Almaty, and the offset between the two zones changes twice
a year because they observe daylight saving on different calendars. An earlier
iteration of this project localised the US line to Almaty, found it off from
NASDAQ closes by a fraction of a percent, and concluded that the broker's `.US`
line was an internal book rather than genuine NASDAQ prints. That conclusion
stood in the project notes for months. Under the New York frame the same line
matches Yahoo Finance's NASDAQ close to the cent on 91.8% of 550 sessions
(Section 5), and the minute carrying the largest volume in a month is 16:00 New
York in 24 of 27 months, winter and summer alike.

### 3.2 `date_to` is exclusive

A fetcher looping over months and requesting `01.03.2024` to `31.03.2024` omits
31 March, every month. The store loses the last trading day of each month in a
pattern indistinguishable from ordinary non-trading days. Backfills must request
`date_to = last_day + 1`.

### 3.3 `hloc` rows are ordered `[high, low, open, close]`

Read positionally as OHLC, `open` receives the high and `high` receives the low,
so every bar satisfies `high < open`, and every estimator built on the daily
range, Corwin and Schultz (2012) among them, inverts. This defect is detectable
after the fact: assert `low <= min(open, close)` and `high >= max(open, close)`
at ingest rather than in a notebook.

### 3.4 Oversized requests return an empty payload, not a truncated one

During the backfill of August 2026, requests spanning tens of thousands of points
returned an empty payload rather than a truncated one, which is why the fetcher
chunks by month. The limit is not fixed: on 2026-10-30 the probe of Section 2.6
returned 80,051 points for a twelve-month window of HSBK without truncation, so a
fetcher cannot rely on its absence either. A fetcher that reads empty as "no
trading in this window" writes a zero-row partition and marks the month complete,
producing holes exactly where the instrument was most active. Empty has to be
treated as ambiguous: split the window and retry, and record "checked and
genuinely empty" separately from "not yet fetched" in the coverage metadata.
Section 2.6 shows that most of this store's empty months are absent at the
endpoint rather than lost this way, and that five are not.

### 3.5 Mixed date formats

Request dates are `DD.MM.YYYY`; the metadata's `firstDate` is `MM.DD.YYYY`. Both
parse without complaint until the 13th of the month.

### 3.6 A leading reference bar

Responses include one bar from before the requested window. Concatenating windows
without dropping it duplicates boundary bars and fabricates a zero return at each
seam. The KASE fetcher filters each partition to its month; the NASDAQ fetcher
does not, and the committed NASDAQ line carries 26 exact duplicate rows at month
boundaries, 119,676 rows for 119,650 bars, which the analysis scripts drop before
counting.

### 3.7 `firstDate` is the listing date, not the start of minute data

KSPI's metadata reports 2018; its minute history effectively begins in July 2021
(Section 2.2). A backfill driven by `firstDate` spends hours requesting windows
that will never return anything and, given 3.4, records their emptiness as fact.

### 3.8 Artefacts of the served history

Three further properties are not defects of the acquisition code but of what the
endpoint serves, and a user has to know them: the flat off-session bars of 2016
to 2019 (Section 2.5), together with seven bars of non-positive volume that the
fetcher's check now reports (Section 5); the daily series covering only part of
the session from 2026-03-10 (Section 2.7); and, on the NASDAQ line, one phantom session on
2025-01-09, a day the US markets were closed, whose bars the reconciliation of
Section 5 finds in the store and Yahoo correctly lacks, together with one missing
session on 2025-04-28, which the endpoint does not serve either (Section 2.6).

## 4. The KASE board endpoint: cadence, quote fields, and a second feed

The evidence is the recording described in `data/README.md`: 10,217 rows in 416
snapshots over 96 recording days from 2026-04-14 to 2026-08-25, five of them
exchange closures on which the board kept the previous session, one row per
instrument per snapshot (22 to 26 instruments), 29 tickers, and a live probe of
six names on the morning of 2026-08-25. The recordings' `fx_usdkzt` column is a
Yahoo Finance rate the recorder added, not KASE data, and nothing below uses it.
`analysis/board_fields.py` computes everything in this section from the
recordings and the minute store; its tables are under `data/derived/`, prefixed
`board_`, and `board_summary.csv` holds the headline figures, with the rest in
the other board tables and in the script's output. Every price equality below
means equal to the cent, the price step both sources quote in.

### 4.1 Methods note: the board publishes the previous session

This subsection is a property of one endpoint and a join rule that follows from
it, not a statement about the exchange's public interfaces in general; Section
4.3 documents a different KASE endpoint that publishes intraday quotes.

`kase.kz/api/trade-results/shares/` does not update during the trading day. Of
the 2,061 instrument-days with more than one in-session snapshot, none shows any
change in bid, ask, last, high, low or deal count across the day's snapshots. The
probe of 2026-08-25, 126 polls at 30-second spacing from 10:50 to 11:54 Almaty,
returned one value of every field for each of its six instruments, with
`last_deal_date` on 2026-08-24 for all of them (`probe_summary.csv`).

Which session the frozen board reports is settled against the store. For the 17
board tickers that the store carries, the board's `last` is compared with the
store's session close of the previous trading day and of the snapshot day. Of
5,039 in-session rows, 97.8% equal the previous session's close (88.1% that close
only, 9.7% both closes because the name did not move), none equals the same-day
close only, and 2.2% match neither close. The share for the previous close only lies
between 87% and 90% in every hourly bucket from 09:00 to 16:00
(`board_staleness.csv`). At or after 17:30, 89.0% of 1,099 rows equal the same-day
close. The switch is tight: on the days the store covers, the latest snapshot
whose majority of rows still carried the previous session was taken at 17:30, the
earliest whose majority carried the same day at 17:35, and no snapshot at or after
17:40 carried the previous session; each bound rests on the few snapshots the
archive holds at those minutes. The median first same-day snapshot of 18:15 that
the archive shows is an artefact of its polling times, not of the board.

Three consequences follow. First, the board on day D reports session D-1 until
the switch, and every test on it must join on that basis; a naive join shifts the
comparison by one session and produces a picture in which no hypothesis fits.
Second, the archive carries no intraday information: 10,217 rows collapse to
2,263 instrument-sessions, one per ticker and reported session, and no same-day
timing analysis can be built on the feed. Third, an earlier finding of zero
intraday variation in `current_bid` and `current_offer`, which had been read as
evidence for a fixed daily band, was a statement about the endpoint's cadence:
every field is frozen intraday, `dealcnt` and `volume` included.

The cadence was also missed in the opposite direction. When kase.kz became a
client-rendered application in August 2026 and its HTML began serving the
previous session's board, the recorder was switched on 2026-08-21 from parsing
the HTML to reading this JSON endpoint as the fix. The JSON endpoint has the same
cadence, and the HTML had carried the previous session from the first recording.

### 4.2 `current_bid` and `current_offer` are not quotes in the ordinary sense

The pair depends on how much the instrument traded. On the 2,257 two-sided
instrument-sessions, binned by the session's deal count (`board_liquidity_signature.csv`):

| deals in the session | instrument-sessions | bid exceeds ask | bid equals high and ask equals low |
|---|---|---|---|
| 1 | 52 | 21.2% | 71.2% |
| 2-3 | 101 | 43.6% | 79.2% |
| 4-10 | 272 | 68.8% | 74.3% |
| 11-50 | 662 | 97.3% | 47.3% |
| 51-200 | 264 | 99.2% | 25.0% |
| 201-1000 | 704 | 99.0% | 9.9% |
| 1000+ | 202 | 98.5% | 0.5% |

No rule-based price limit, corridor or circuit breaker can be a monotone function
of session deal count, because none of those parameters is set from realised
activity. A quantity aggregated over the session can be: in a thin name the
single best bid posted is usually the one that got hit, so it lands on the
session high, and in an active name quotes accumulate beyond where trades
occurred.

The crossedness points the same way in one step. Over the 2,257 instrument-sessions
the field labelled bid exceeds the field labelled ask in 90.6% of cases, is equal
in 8.1%, and is ordered normally in 1.3% (`board_crossing.csv`); most of the
normally ordered cases come from one payload discussed below. Crossed markets do
occur in live books but resolve within seconds (Shkilko, Van Ness and Van Ness,
2008), which is why standard liquidity pipelines discard them rather than treat
them as states of the book (Holden and Jacobsen, 2014), and why a persistent
cross identifies the fields as something other than a live quote. The class of
error is familiar in vendor data, where a column's label and its contents diverge
and the divergence is detectable only by testing the field against its supposed
meaning (Ince and Porter, 2006). CRSP's daily file carries a parallel in its
`BIDLO` and `ASKHI` columns, named "bid or low price" and "ask or high price": one
label for two kinds of content (CRSP, 2021).

An earlier stage of this project read the pair as a live quote and computed a
quoted spread for KSPI from it, a figure that propagated into the cost model of
every downstream stage. It is withdrawn: the archive gives a median `bid - ask` of
283.7 basis points of the last price for KSPI (`board_widths.csv`), and neither
that nor the earlier figure is a trading cost. The companion repository's
trade-based estimators, which return the full bid-ask width, give 0.24% under Roll
(1984) over 748 KSPI sessions and 0.47% under Corwin and Schultz (2012) as the
median of positive two-day estimates, 0.31% under the paper's own treatment of
negative estimates; with commission of 0.085% per side a round trip costs 0.41% or
0.64% (`kase-price-discovery`, `data/derived/spread_estimates.csv`). Those
estimates stand in place of a quote feed rather than in the absence of one: KASE
publishes a best bid, a best ask and a spread on the endpoint of Section 4.3,
which this project did not sample.

Two other readings fail. An earlier stage of this project compared the pair with
the daily price corridor that the clearing centre publishes per instrument and
found no match; that comparison and its data are not in this repository, so it is
stated without figures, and the deal-count signature above refutes a corridor on
its own. The reading that the fields are trade high-water marks is refuted
directly: against the store's session high, the bid lies strictly above it on
54.1% of the 1,341 store-aligned sessions.

KASE's own page labels the two columns, in Russian, as the best buy quote and the
best sell quote, under a heading reading "results of trading" for a given date.
The bonds endpoint carries `dirty_best_bid` and `dirty_best_offer` as the
dirty-price twins. No corridor column exists in either schema. The field names also
separate the two feeds: the watcher endpoint of Section 4.3 names its top-of-book
fields `bestbuyprc` and `bestslprc` and carries `spread` and `spreadprc` beside
them, so the board's `current_bid` and `current_offer` are not the exchange's own
names for a best bid and a best ask.

The reading consistent with the discriminating tests is that these are the
session's extreme quotes: the highest bid and the lowest offer posted during the
completed session. `board_extreme_quote_tests.csv` tests the reading twice, against
the board's own high and low on the 2,257 instrument-sessions and against the
minute store's session high and low on the 1,341 sessions whose payload the store
dates:

| prediction | against the board's range (n 2,257) | against the store's range (n 1,341) |
|---|---|---|
| bid at or above the session high | 89.4% | 93.6% |
| bid equal to the high | 51.2% | 39.5% |
| ask at or below the session low | 87.5% | 95.4% |
| ask equal to the low | 51.9% | 40.3% |
| both hold | 79.7% | 90.3% |
| width at or above the realised range | 84.1% | 92.7% |
| Spearman of width against range | 0.908 | 0.907 |

The board's own high and low differ from the store's in a minority of sessions,
269 of 1,341 for the high and 406 for the low, and the board's value lies outside
the store's range in 261 of the 269 and in all 406. The board's range therefore
includes prints that the minute bars do not carry, and the quote extremes agree
better with the bars than with the board's own range.

Two snapshots in the archive, both on 2026-06-04, are board-wide uncrossed
(`board_uncrossed_snapshots.csv`). Their 23 two-sided pairs are normally ordered,
narrow (median width 0.53% of the last price) and in 78.3% of cases enclose the
completed 3 June close, while the open, high, low and deal-count fields report
that session: for KSPI, bid 43,667.18 and ask 43,890.00 against a close of
43,668.00 and 288 deals. The snapshot before them, taken after the close on 3 June,
carried bid 44,299.00 and ask 42,258.00 for the same session, and the snapshot
after them, taken after the close on 4 June, carried bid 43,668.00 and ask
41,900.00 for the 4 June session with its high of 43,300.00 and low of 42,000.00.
The pair is therefore not fixed by the session it reports, and the fields can carry
a real top-of-book, which places the usual published value as an aggregate over the
session.

The reading is the best supported and it is not established. It makes a
non-probabilistic prediction, that a trade at price P requires a bid at or above P
and an offer at or below P to have existed, and that prediction fails on a
measurable minority: against the store's range the bid sits below the session high
on 6.4% of sessions and the ask above the session low on 4.6%, and against the
board's own range on 10.6% and 12.5%. The violating extremes are not concentrated at
the auctions (`board_residual_placement.csv`): among the 86 sessions where the bid
falls short of the high, the high was set in the session's first bar in 19.8% of
cases against 18.3% of all aligned sessions, and in the last bar in 5.8% against
3.3%; among the 62 ask violations, 25.8% against 21.1% and 6.5% against 3.4%. The
account left standing is that the published values are extremes over a
periodically sampled book rather than over the continuous one, which this data
cannot distinguish from the continuous version.

Recording timestamped top-of-book for one liquid KASE name over one full session
and testing whether `max(bid_t)` and `min(offer_t)` over the session reproduce the
next morning's published values would separate the two remaining accounts, most
informatively on a high-activity day, where the exact-match rate is near zero.
Section 4.3 identifies the feed that would supply that recording.

### 4.3 A separate endpoint publishes best bid, best ask and a spread

`kase.kz/api/trades/watcher/` requires POST. A GET returns 405 Method Not Allowed,
which is why earlier stages of this project treated the board endpoint of Section
4.1 as the exchange's only public price interface. The response schema carries,
among its fields, `bestbuyprc` (best bid price), `bestslprc` (best ask price),
`spread` (best ask minus best bid), `spreadprc` (the same in per cent),
`buyquantity` and `sellquantity` (quantity at each side), `volbid_kzt` and
`volask_kzt` (tenge volume at each side), and `tradestatus` (session status).

What the feed does during a session is not established here. Queried at 18:16
Almaty on 2026-08-26, after the close, the response carried `is_realtime: false`
and an empty `data` array under every request shape tried, so this project has
observed the schema and not the values. Whether the fields populate while the
session is open, and whether they are live or delayed, remains open.

Sampling it through a full session is the next step for two questions already
stated above: it would replace the Roll and Corwin-Schultz estimates with a
measured spread, and it would supply the `bid_t` and `offer_t` series that the
extreme-quote reading needs to be tested against.

## 5. Validation

Four checks, all runnable from the tree.

1. Session bounds. `tradernet_fetch.py --verify` reports a median session open of
   11:29 for every equity line with at least 20 bars a day and finds no duplicate timestamp, no
   non-positive price and no bar with high below low; `implied_open_monthly.csv`
   shows the open flat across the 2024-03-01 boundary (Section 3.1). The same
   check flags seven bars with non-positive volume, one in KZTK, an off-session
   bar of Section 2.5 with zero volume, and six in RUBKZT_TOM with negative
   volumes that no trade can produce; they are reported, not removed.
2. Cross-venue reconciliation of the NASDAQ line
   (`analysis/nasdaq_reconciliation.py`). The store's regular-session close, the
   last bar from 09:30 to 16:00 New York with the 16:00 closing-auction bar
   included, equals Yahoo Finance's close to the cent on 91.8% of 550 common
   sessions from 2024-01-19 to 2026-03-31, and lies within 0.1% on 97.3%. Of the
   45 mismatches, 20 are Yahoo closes carrying a half-cent third decimal, which
   no cent-denominated print can equal, three are half-session days on which the
   window catches a print after the 13:00 close, and the rest differ by a cent or
   carry a later print in the 16:00 bar than the one Yahoo reports, apart from
   2026-03-19, which differs by 11 cents. The store holds one session Yahoo lacks, 2025-01-09, a day the US
   markets were closed, and lacks one that Yahoo has, 2025-04-28, for which the
   endpoint serves no minute or daily point (`nasdaq_reconciliation_summary.csv`;
   Section 2.6). Without the 16:00 bar the cent-exact
   share is 18.4%, which is how sensitive such a check is to one minute.
3. Cross-source reconciliation of the KASE closes. The board's `last` equals the
   store's previous-session close to the cent on 97.8% of 5,039 in-session rows
   (Section 4.1); the two sources are independent, one recorded from the exchange
   and one fetched from the broker.
4. The daily companion against the minute store: exact on 97.2% of
   instrument-sessions through 2026-03-06 and no longer a check after that date
   (Section 2.7).

## 6. Limitations

The store contains no order-book data, so the bid-ask spread is bounded by
trade-based estimators rather than measured, and the two estimators the companion
repository uses differ by a factor of two (0.24% against 0.47% for the full
width). That is a sampling decision rather than a property of the venue: the
endpoint in Section 4.3 publishes a best bid, a best ask and a spread field, and
was found after the store was built.

Prices are raw traded prices, with no corporate-actions file and no adjustment for
distributions, so an ex-dividend date enters the series as a mechanical overnight
drop. `analysis/overnight_drops.py` lists every drop of 4% or more from the
previous session's last close to the session's first print over 2024-01-19 to
2026-08-24, for the 17 equity lines with at least 200 sessions in the window, and
marks it against the dividend dates Yahoo Finance publishes for the depositary
line of the same company (`overnight_drops.csv`, `dividend_dates.csv`). Among the
mapped names, AIRA's one drop, -7.45% on 2025-06-20, falls on the London line's
dividend date; five of HSBK's six drops fall one to three days before an HSBK.IL
dividend date; KSPI's four drops include 2024-09-20, -6.67% at the first print and
-2.17% close to close, the session after the NASDAQ line fell 16.02% on
2024-09-19 on an information event, and three fall within three days of a KSPI
dividend date without falling on it; KZAP's two drops are unrelated to any KAP.IL
date, and KZAP shows no drop of 4% or more on its dividend dates. Most of the 111
drops belong to five names: 38 to BAST, 18 to KASE, 14 to RAHT and six to BSUL,
all thin names, the six BSUL drops at -30% or worse with a close back at or near
the previous level, and 13 to KMGD, an active line. In nearly all of them the
session closes above the first print (`overnight_drops.csv`), a property of
opening prints rather than of distributions. Ex-dividend dates for the KZT-only names
could not be verified from the sources available here, so contamination of a
calendar window, including the 20 December to 10 January window the companion
repository uses, is possible and unquantified.

The 24 names are those listed in 2026. No delisted name is in the store, so
anything cross-sectional built on it carries survivorship bias.

Bars are present only for traded minutes. Any procedure requiring a regular grid
has to state how it handles the gaps, whose median is 2 minutes and whose 90th
percentile is 6 in the KSPI window. The 2016 to 2019 history carries the
off-session bars of Section 2.5, the 2020 history the shortened schedules of
Section 2.4, and the daily companion changes its session definition on
2026-03-10.

The identification of `current_bid` and `current_offer` in Section 4.2 is a
best-supported reading, not an established one, and the containment failures of
6.4% and 4.6% against the store's range remain unexplained. Any cost or liquidity
measure built on those fields inherits that uncertainty.

The board archive supports daily analysis only, at most 92 instrument-sessions
per ticker between April and August 2026, and its density is uneven: five or six
snapshots a day until 2026-04-24, one to five a day (median three) between
2026-04-27 and 2026-08-06 under scheduler throttling, six or seven a day from
2026-08-07 to 2026-08-14, and eleven to fourteen a day from 2026-08-17. Because
the board is frozen within the day, the count matters less than it would for a
live feed.

The 1-minute bars are not redistributed, so reproduction requires a multi-hour
backfill against a third-party endpoint whose availability is outside this
project's control; the board recordings are not redistributed either, so the
board tables of Section 4 can be read but not regenerated from the public copy.

## References

Corwin, S. A., and P. Schultz (2012). A simple way to estimate bid-ask spreads
from daily high and low prices. *Journal of Finance* 67(2), 719-760.

CRSP (2021). *CRSP US Stock and Indexes Databases for SAS, ASCII and R Files*,
flat-file table layouts, daily items BIDLO and ASKHI. Center for Research in
Security Prices, LLC, modified 2021-02-24.
https://www.crsp.org/wp-content/uploads/2023/10/crsp_us_stock.pdf

Holden, C. W., and S. Jacobsen (2014). Liquidity measurement problems in fast,
competitive markets: Expensive and cheap solutions. *Journal of Finance* 69(4),
1747-1785.

Ince, O. S., and R. B. Porter (2006). Individual equity return data from Thomson
Datastream: Handle with care! *Journal of Financial Research* 29(4), 463-479.

KASE (2025). Amendments to the Rules for Exchange Information Dissemination will
come into effect on February 1. Kazakhstan Stock Exchange, news item of
2025-01-22, summarising Article 19 of the Rules.
https://kase.kz/en/news/show/1535885

Roll, R. (1984). A simple implicit measure of the effective bid-ask spread in an
efficient market. *Journal of Finance* 39(4), 1127-1139.

Shkilko, A. V., B. F. Van Ness, and R. A. Van Ness (2008). Locked and crossed
markets on NASDAQ and the NYSE. *Journal of Financial Markets* 11(3), 308-337.

The independent verification of 2026-10-12 and the author's later re-analysis of
the same market (2026-10-16), referred to in the text, are unpublished working
documents. Where the text draws on them it states the finding in place and names
the committed script that now measures it; those statements cannot be checked by a
reader against a published source.
