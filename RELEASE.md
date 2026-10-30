# Release plan: a fresh-history public copy

This repository has been private while its text was being finalised. It cannot be made public by
flipping its visibility, because its history holds data that must not be published: the 96 board
recordings and the live probe under `data/kase-board-snapshots/`, tracked since the first commit
(683426b, 2026-08-26). They are observations of KASE's trade-results board, and KASE's Rules for
Exchange Information Dissemination (Article 19) make the inclusion of exchange information in
anyone's information products, or its regular distribution, conditional on an agreement with the
exchange or its written permission. No such permission is on record. Removing the files in a new
commit would leave them in every earlier commit, and the repository's own rule is never to rewrite
history. The route is therefore a copy with a new history: one initial commit holding the finished
tree with the exclusions applied, pushed by the owner to a new public repository, with this private
repository kept as the record. Nothing below has been run; this is the plan.

The analyses that read the recordings (`analysis/board_fields.py`) stop with a message when the
files are absent. Their outputs are committed under `data/derived/` and travel with the public copy;
every number the documents quote from the recordings is in one of those tables. Should the owner
obtain KASE's written permission, the two excluded paths can be added to the public repository in a
later commit, and `data/README.md` says what they are.

## 1. Before the copy

Decisions taken on 2026-10-30:

- The public repository keeps the name `kase-market-data`, which `CITATION.cff` and the README
  citation carry. The private repository is renamed first (for example to
  `kase-market-data-private`) and the local clone's `origin` is re-pointed to the renamed URL,
  before the public one is created under the original name; otherwise a later push from this clone
  would land its full history, recordings included, in the public repository.
- The board recordings and the probe are excluded, as above. The 1-minute bars, the daily
  companion series and the Yahoo series behind five derived tables were never tracked and stay
  out. The rule, shared with the companion KASE repositories: raw vendor feeds (the broker's minute
  bars, Yahoo chart JSON, AIX data) are never published; small derived tables that the published
  results depend on may be committed, with the source named, as `data/README.md` does.
- The `fx_usdkzt` column of the recordings comes from Yahoo Finance, not from KASE; it is
  described as such wherever the files are described, and no committed table carries it.

Steps:

- [ ] Merge `final-writeup` into `main` with a merge commit, or fast-forward; do not squash.
- [ ] Run the clean-clone gate of `docs/reproducibility.md` section 2 on the merged `main`.
      Expect all thirty tables in `data/derived/` byte-identical, except
      `nasdaq_reconciliation_summary.csv` (its `fetched_on` row) and `dividend_dates.csv` (its
      `source` column), which differ in those date fields only, after a run on a later day than
      the one they record, and, in `dividend_dates.csv`, by a row for any dividend Yahoo has
      listed since; and `nasdaq_reconciliation.csv`, `overnight_drops.csv` and
      `overnight_drops_summary.csv`, which differ only if Yahoo has revised a value. Any other
      difference is a defect. Record the run and the commit it ran on in the Status paragraph.
- [ ] Rename the private GitHub repository; run `git remote set-url origin <renamed URL>` in this
      clone; push `main` to it.
- [ ] On the day of the public push, add `date-released` to `CITATION.cff`, commit, and make the
      copy of section 2 from that commit the same day.

## 2. Make the copy

From a clean checkout of the merged `main`, with no untracked files:

```sh
git -C /path/to/kase-market-data status --porcelain      # must print nothing
mkdir /path/to/kase-market-data-public
git -C /path/to/kase-market-data archive --format=tar HEAD | tar -x -C /path/to/kase-market-data-public
cd /path/to/kase-market-data-public
rm -r data/kase-board-snapshots                            # the exclusion that git archive cannot apply
git init -b main
git add -A
git commit -m "KASE market data: minute-bar acquisition and board-feed provenance"
```

`git archive` copies only tracked files at `HEAD`, so the stores, the bytecode and the scratch
directories are excluded by construction. The board recordings are tracked, so they are removed by
the `rm` line; the checklist in section 4 confirms it.

## 3. What the copy excludes

Every path that exists on the author's machine or in this repository's history and is not in the
public tree:

| path | why it is excluded |
|---|---|
| `data/kase-board-snapshots/board-recordings/2026/MM/YYYY-MM-DD.csv`, 96 files listed below | KASE exchange information recorded from `kase.kz/api/trade-results/shares/` (HTML-parsed to 2026-08-20); no permission on record under Article 19; tracked from 683426b |
| `data/kase-board-snapshots/quote_probe_2026-08-25.csv` | the same information, 126 polls of six instruments on one morning; tracked from 683426b |
| `data/kase/intraday/**` (`manifest.csv`, `<TICKER>/_coverage.json`, `<TICKER>/<YYYY-MM>.parquet`) | the 1-minute bar store written by `src/kase/tradernet_fetch.py`; never tracked |
| `data/kase/daily/<TICKER>.parquet` | the daily companion series written by `src/kase/fetch_daily.py`; never tracked |
| `data/nasdaq/intraday/KSPI.US/<YYYY-MM>.parquet` | the NASDAQ bars written by `src/nasdaq/fetch_nasdaq_intraday.py`; never tracked |
| `data/historical/**`, `data/kase/raw/**`, `data/kase/v2/**` | output locations of `fetch_kase_history.py` and the two recorders, if ever run from this tree; never tracked |
| `src/recorders/recorder_state.json`, `src/recorders/quote_probe_<date>.csv` | state and output that `kase_snapshot_recorder.py` and `quote_semantics_probe.py` write beside themselves if run from this tree; never tracked |
| `analysis/__pycache__/`, `src/**/__pycache__/` | bytecode; never tracked |
| `scratch/`, `out/` | local scratch; never tracked |
| `.git/` | the private history itself |

The 97 excluded files that are tracked in this repository:

```
data/kase-board-snapshots/board-recordings/2026/04/2026-04-14.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-15.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-16.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-17.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-20.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-21.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-22.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-23.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-24.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-27.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-28.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-29.csv
data/kase-board-snapshots/board-recordings/2026/04/2026-04-30.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-01.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-04.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-05.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-06.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-07.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-08.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-11.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-12.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-13.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-14.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-15.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-18.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-19.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-20.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-21.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-22.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-25.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-26.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-27.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-28.csv
data/kase-board-snapshots/board-recordings/2026/05/2026-05-29.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-01.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-02.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-03.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-04.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-05.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-08.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-09.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-10.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-11.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-12.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-15.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-16.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-17.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-18.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-19.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-22.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-23.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-24.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-25.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-26.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-29.csv
data/kase-board-snapshots/board-recordings/2026/06/2026-06-30.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-01.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-02.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-03.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-06.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-07.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-08.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-09.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-10.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-13.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-14.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-15.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-16.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-17.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-20.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-21.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-22.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-23.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-24.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-27.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-28.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-29.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-30.csv
data/kase-board-snapshots/board-recordings/2026/07/2026-07-31.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-03.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-04.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-05.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-06.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-07.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-10.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-11.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-12.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-13.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-14.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-17.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-18.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-19.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-20.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-21.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-24.csv
data/kase-board-snapshots/board-recordings/2026/08/2026-08-25.csv
data/kase-board-snapshots/quote_probe_2026-08-25.csv
```

Nothing was ever added to this history and later deleted, and no raw bar, Yahoo chart file or
credential has been tracked; the recordings are the only excluded content in the history. The
history also carries earlier versions of `README.md` and `docs/dataset-and-provenance.md`, with the
figures those versions quoted without a producer; the write-up describes the corrections, and the
private repository is where their history can be read.

## 4. After the copy, before the push

- [ ] `git -C /path/to/kase-market-data-public ls-files` lists exactly the files in section 5.
- [ ] `grep -rn "/Users/" .` in the copy prints nothing.
- [ ] `grep -rnP '[^\x00-\x7F]' --include='*.md' --include='*.cff' --include='*.py' --include='*.txt' .`
      prints nothing (ASCII only).
- [ ] `grep -rnP '[\x{200b}-\x{200d}\x{2060}\x{feff}\x{00a0}\x{00ad}]' --include='*.py' --include='*.md' --include='*.cff' .`
      prints nothing (no invisible characters).
- [ ] The two `grep -P` checks need GNU grep or ugrep; with the stock macOS grep use
      `LC_ALL=C grep -rn '[^ -~]' --include='*.md' --include='*.cff' --include='*.py' --include='*.txt' .`
      for the ASCII check and
      `perl -CSD -ne 'print "$ARGV:$.: $_" if /[\x{200b}-\x{200d}\x{2060}\x{feff}\x{00a0}\x{00ad}]/' $(git ls-files '*.py' '*.md' '*.cff')`
      for the invisible characters.
- [ ] Run the regeneration steps of `docs/reproducibility.md` on the copy with `KASE_STORE` and
      `KASE_DAILY` exported: `tradernet_fetch.py --verify`, then the five analysis scripts in the
      README's order (and `analysis/probe_endpoint.py` if the endpoint is to be re-probed; it
      writes nothing), then `src/make_figures.py` and `analysis/check_figure_literals.py`.
      `board_fields.py` is expected to stop with its message, because the recordings are absent;
      its ten tables stay as committed. `git status data/derived` then prints nothing apart from
      `nasdaq_reconciliation_summary.csv` and `dividend_dates.csv`, which record the fetch date and
      therefore differ after any run on a later day, and apart from `nasdaq_reconciliation.csv`,
      `overnight_drops.csv` and `overnight_drops_summary.csv` if Yahoo has revised a value.
      `tradernet_fetch.py --verify` exits 1 because it reports seven bars with non-positive volume;
      that is the expected result.
- [ ] Create the public repository empty, with no README, licence or gitignore of its own, add it
      as `origin` of the copy and push `main`.

## 5. The public tree

```
.gitignore
CITATION.cff
LICENSE
README.md
RELEASE.md
analysis/_store.py
analysis/board_fields.py
analysis/check_figure_literals.py
analysis/nasdaq_reconciliation.py
analysis/overnight_drops.py
analysis/probe_endpoint.py
analysis/session_structure.py
analysis/store_inventory.py
data/README.md
data/derived/board_crossing.csv
data/derived/board_extreme_quote_tests.csv
data/derived/board_first_same_day.csv
data/derived/board_liquidity_signature.csv
data/derived/board_residual_placement.csv
data/derived/board_staleness.csv
data/derived/board_summary.csv
data/derived/board_uncrossed_snapshots.csv
data/derived/board_widths.csv
data/derived/collection_gap_instruments.csv
data/derived/collection_gaps.csv
data/derived/daily_vs_minute.csv
data/derived/daily_vs_minute_monthly.csv
data/derived/dividend_dates.csv
data/derived/halt_2022.csv
data/derived/implied_open_monthly.csv
data/derived/market_closures.csv
data/derived/nasdaq_reconciliation.csv
data/derived/nasdaq_reconciliation_summary.csv
data/derived/overnight_drops.csv
data/derived/overnight_drops_summary.csv
data/derived/probe_summary.csv
data/derived/session_bar_density.csv
data/derived/session_bounds.csv
data/derived/session_bounds_by_year.csv
data/derived/session_end_monthly.csv
data/derived/session_summary.csv
data/derived/store_bars_by_year.csv
data/derived/store_inventory.csv
data/derived/zero_row_partitions.csv
docs/dataset-and-provenance.md
docs/reproducibility.md
figures/board-staleness.png
figures/quote-liquidity-signature.png
figures/session-structure.png
figures/timezone-detection.png
requirements.txt
src/kase/fetch_daily.py
src/kase/fetch_kase_history.py
src/kase/tradernet_fetch.py
src/make_figures.py
src/nasdaq/fetch_nasdaq_intraday.py
src/recorders/kase_board_recorder.py
src/recorders/kase_snapshot_recorder.py
src/recorders/quote_semantics_probe.py
```

## 6. After the push

- [ ] Keep this repository private and unchanged as the record; add a line to its README pointing
      at the public copy, or leave it as it is.
- [ ] The companion repository `kase-price-discovery` reads the stores this repository's fetchers
      build and quotes nothing from the recordings; `kase-strategy-audit` quotes neither. The
      archived `kase-cross-listing` holds byte-identical copies of the 96 recordings and must never
      acquire a remote.
- [ ] If KASE's written permission to redistribute the recordings is obtained, add the two excluded
      paths in a new commit to the public repository, record the permission in `data/README.md`,
      and re-run `analysis/board_fields.py` to confirm the committed tables regenerate.
