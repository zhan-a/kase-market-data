# Data

Three stored inputs feed this repository, plus two Yahoo series fetched at run time, and only the
derived tables are redistributed. The rule, shared with the companion KASE repositories: raw vendor
feeds (the broker's minute bars, Yahoo chart data, AIX data) are never published; small derived
tables that the published results depend on may be committed, with their source named. Exchange
information recorded from KASE's own endpoints is covered by KASE's rules rather than by the vendor
rule, and is not redistributed either; the next section says why.

## Not in the public copy: KASE board recordings

`kase-board-snapshots/board-recordings/YYYY/MM/YYYY-MM-DD.csv` and
`kase-board-snapshots/quote_probe_2026-08-25.csv`

These are observations of KASE's trade-results board, recorded by the scripts in `src/recorders/`.
The 96 daily files hold full snapshots, 22 to 26 instruments per snapshot, taken by
`kase_snapshot_recorder.py` on a five-minute slot grid, one to fourteen a day (median four),
between 2026-04-14 and 2026-08-25; the probe file holds 126 polls of six instruments at 30-second
spacing on the morning of 2026-08-25 by `quote_semantics_probe.py`. Until 2026-08-20 the snapshot
recorder parsed the HTML of the board page at kase.kz; from 2026-08-21 it reads
`kase.kz/api/trade-results/shares/`, the JSON endpoint behind that page. Both surfaces carry the
previous session during the trading day (Section 4.1 of `docs/dataset-and-provenance.md`), so the
switch changed the delivery mechanism and not the content.

Columns of the daily files: `timestamp` (the five-minute slot, Almaty), `scrape_time`, `delayed`,
`ticker`, `mode`, `bid`, `ask`, `open`, `high`, `low`, `last`, `change_pct`, `vwap`, `deals`,
`volume_mln`, `interval_volume_mln`, `interval_deals`, `fx_usdkzt`. `bid` and `ask` are the fields
the endpoint labels `current_bid` and `current_offer`; the write-up identifies what they hold.
`fx_usdkzt` is not KASE data: the recorder fetched it from Yahoo Finance (`USDKZT=X`, the
`regularMarketPrice` field of the chart endpoint) at each scrape. The `interval_*` columns are
differences the recorder computed between consecutive snapshots. No committed table carries the FX
column.

KASE's Rules for Exchange Information Dissemination (Article 19) make the inclusion of exchange
information that KASE distributes free of charge in other parties' information products, or its
regular distribution, conditional on an agreement with the exchange or its written permission. No
such permission is on record, so the recordings are excluded from the public copy (`RELEASE.md`
lists every excluded path) and are kept in the private repository as the record. The analyses that
read them (`analysis/board_fields.py`) stop with a message when the files are absent; their outputs
are committed below, and every number the documents quote from the recordings is in one of those
tables. The archived companion `kase-cross-listing` holds byte-identical copies of the 96 files
and must never acquire a remote.

Read any copy of the recordings with the one-session lag in mind: the board on day D reports
session D-1 until the switch after the close. Snapshot density is uneven: five or six snapshots a
day until 2026-04-24, one to five a day from 2026-04-27 to 2026-08-06 under scheduler throttling,
six or seven a day from 2026-08-07 to 2026-08-14, eleven to fourteen a day from 2026-08-17. Because
the board is frozen within the day, repeat snapshots duplicate one reported session; the analysis
collapses them to instrument-sessions before counting.

## Not committed: the 1-minute bar store and the daily companion

`kase/intraday/<TICKER>/<YYYY-MM>.parquet` (24 KASE instruments, 2,472 monthly partitions,
2,476,602 bars, 2015-05-25 to 2026-08-24), `nasdaq/intraday/KSPI.US/<YYYY-MM>.parquet` (27
partitions, 119,650 bars once 26 duplicate rows at month boundaries are dropped, 2024-01-19 to
2026-03-31) and `kase/daily/<TICKER>.parquet` (one file per manifest ticker). All three come from
the chart-data endpoint of Tradernet, Freedom Finance's retail platform, through the fetchers in
`src/`. Using them for research is one thing; republishing them as a dataset is another, and the
endpoint's terms do not clearly address it. This repository ships the fetchers and leaves the bars
where they came from. That is a judgement, not a legal opinion; anyone intending to redistribute
the bars should ask the operator first.

The paths above are in `.gitignore`. The analysis scripts resolve them through
`analysis/_store.py`, in this order:

1. the environment variables `KASE_STORE` (the directory holding `kase/intraday` and
   `nasdaq/intraday`) and `KASE_DAILY` (the directory holding the daily parquets);
2. `data/` inside this repository, where the fetchers write by default;
3. the sibling checkout `../trading desk/data`, for a working copy laid out beside the other
   repositories; this fallback exists for the minute store only, and the daily series is looked for
   under `KASE_DAILY` and `data/kase/daily` alone.

A script that cannot find a store stops at that point and prints the paths it tried. The fetchers
honour the same two variables, so a store can live outside the tree:

```sh
export KASE_STORE=/path/to/store          # will contain kase/intraday and nasdaq/intraday
export KASE_DAILY=/path/to/kase/daily     # will contain KSPI.KZ.parquet and siblings
python src/kase/tradernet_fetch.py --discover
python src/kase/tradernet_fetch.py --backfill     # several hours
python src/kase/tradernet_fetch.py --verify
python src/kase/fetch_daily.py
python src/nasdaq/fetch_nasdaq_intraday.py
```

Known properties of a rebuilt store, each measured by a script in `analysis/` or by the fetcher's
`--verify` and described in the write-up: a collection gap from 2015-06-24 to 2016-01-28 in which
every instrument has zero minute bars while the daily series shows trading; 398 zero-row monthly
partitions of which 63 are contradicted by the daily series; bars outside the session in 2016 to
2019 that repeat the previous close; seven bars with a non-positive volume; five HSBK months of
2020 and 2021 that the committed store holds empty and the endpoint now serves, so a rebuilt store
fills them; three weekdays, 2024-12-12, 2025-04-28 and 2025-04-29, with no bar in any instrument,
which match no public holiday or announced closure and for which the endpoint serves no minute or
daily point (asked for KSPI, HSBK and USDKZT_TOM), absent at the vendor and of unknown cause; a change on 2026-03-10 after which the
daily companion's close no longer matches the minute store's session close; one phantom NASDAQ
session on a US market holiday and one missing NASDAQ session, 2025-04-28, also absent at the
vendor; unadjusted prices.

## Committed: `derived/`

Thirty CSV files, each written by one of five scripts. Every number in the write-up and the README
traces to one of them, to the standard output of the script named beside it, to the dated output
of `analysis/probe_endpoint.py`, to the output of `src/kase/tradernet_fetch.py --verify`, or to a
named file of the companion `kase-price-discovery` repository.

`analysis/store_inventory.py` reads the minute store and the daily companion:

| file | what it holds |
|---|---|
| `store_inventory.csv` | per instrument: partitions, zero-row partitions, bars, sessions, first and last bar; both markets |
| `store_bars_by_year.csv` | bars and sessions per instrument and year |
| `zero_row_partitions.csv` | every empty monthly partition, with the daily rows in that month and whether they contradict it |
| `collection_gaps.csv`, `collection_gap_instruments.csv` | runs of five or more daily-calendar dates with no minute bar, and per-instrument daily and minute bars inside the longest |
| `market_closures.csv` | instruments trading on every weekday of 2024-01-19 to 2026-08-24 |
| `halt_2022.csv` | instruments trading and median first and last bar around the January 2022 halt |
| `daily_vs_minute.csv`, `daily_vs_minute_monthly.csv` | agreement of the daily close with the minute session close, by instrument and year, and pooled by month around the 2026-03-10 change |

`analysis/session_structure.py` reads the minute store:

| file | what it holds |
|---|---|
| `implied_open_monthly.csv` | KSPI median first bar by month, with the series a constant UTC offset would have produced |
| `session_bar_density.csv`, `session_summary.csv` | KSPI bars by minute of session from 2024-01-19, and the session statistics of that window |
| `session_bounds_by_year.csv`, `session_bounds.csv` | first and last bar, off-session bar shares and the echo-bar test, per instrument and year and overall |
| `session_end_monthly.csv` | pooled median last bar by month for six equities, the record of the exchange's closing-time changes |

`analysis/board_fields.py` reads the board recordings, the probe and the minute store:

| file | what it holds |
|---|---|
| `board_staleness.csv`, `board_first_same_day.csv` | which session the board reports by hour of the day, and the first same-day snapshot per day |
| `board_crossing.csv`, `board_liquidity_signature.csv` | crossing shares, and crossing and collapse rates by deal count |
| `board_extreme_quote_tests.csv`, `board_residual_placement.csv` | the extreme-quote tests against the board's own range and the store's, and where the violating extremes fall |
| `board_widths.csv`, `board_uncrossed_snapshots.csv` | median widths per ticker, and the two snapshots with a normally ordered board |
| `probe_summary.csv`, `board_summary.csv` | the probe's constancy by field, and the headline figures as key and value, with the rest in the other board tables |

`analysis/nasdaq_reconciliation.py` reads the NASDAQ store and fetches KSPI daily closes from Yahoo
Finance at run time:

| file | what it holds |
|---|---|
| `nasdaq_reconciliation.csv`, `nasdaq_reconciliation_summary.csv` | per session the store's regular-session close against Yahoo's close, and the agreement statistics |

`analysis/overnight_drops.py` reads the minute store and fetches dividend dates from Yahoo Finance at
run time for the depositary lines of four KASE names:

| file | what it holds |
|---|---|
| `dividend_dates.csv` | the Yahoo dividend dates of AIRA.IL, HSBK.IL, KAP.IL and KSPI, mapped to the KASE tickers |
| `overnight_drops.csv`, `overnight_drops_summary.csv` | every overnight drop of 4% or more in 2024-01-19 to 2026-08-24 for the 17 equity lines, its distance from the nearest dividend date, and per-instrument counts |

Five tables depend on one of two Yahoo series fetched at run time: KSPI's daily closes
(`nasdaq_reconciliation.csv` and `nasdaq_reconciliation_summary.csv`) and the dividend dates of
the depositary lines (`dividend_dates.csv`, and through it `overnight_drops.csv` and
`overnight_drops_summary.csv`). Two of them record the fetch date,
`nasdaq_reconciliation_summary.csv` in its `fetched_on` row and `dividend_dates.csv` in its
`source` column, and therefore differ after any run on a later day; the other three differ only if
Yahoo has revised a value. Every other table regenerates from the stores alone, and the ten board
tables regenerate only where the recordings are present.

## Running

```sh
pip install -r requirements.txt
python src/kase/tradernet_fetch.py --verify
python analysis/store_inventory.py
python analysis/session_structure.py
python analysis/board_fields.py            # stops with a message where the recordings are absent
python analysis/nasdaq_reconciliation.py   # fetches from Yahoo
python analysis/overnight_drops.py         # fetches from Yahoo
python analysis/probe_endpoint.py          # optional: live probe of the endpoint, writes nothing
python src/make_figures.py
python analysis/check_figure_literals.py
```

The order does not matter among the five analysis scripts that write tables; `make_figures.py` reads what two of them
write. `docs/reproducibility.md` gives the regeneration procedure and records its last run.
`src/kase/tradernet_fetch.py --verify` exits with status 1 on the committed store because it
reports seven bars with non-positive volume; that is the expected result.
