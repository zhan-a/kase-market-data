# Reproducibility policy

This file is a commitment made in advance, not a description written afterwards.
It applies to all three repositories in this project: `kase-market-data`,
`kase-price-discovery` and `kase-strategy-audit`.

## 1. Every published number comes from committed code

No number, table or figure enters a writeup unless a script in the repository
produces it. A figure that plots stored constants is an assertion, not a figure,
and does not satisfy this rule.

The rule exists because this project has repeatedly failed it. Numbers computed
in a working session and pasted into a document cannot be audited later, because
the session that produced them is gone. When such a number is wrong there is no
way to find out, and when it is right there is no way to show it.

## 2. Clean-clone regeneration before any release

Before a repository is made public, or a version is tagged, or a writeup is
submitted anywhere:

1. Clone the repository fresh into an empty directory.
2. Install from `requirements.txt` only.
3. Rebuild or attach the data store as `data/README.md` describes.
4. Run every analysis script.
5. Compare every number in every writeup against the output.
6. Run `analysis/check_figure_literals.py`. It greps the plotting code for
   numeric literals and fails on any that is not a styling parameter. Step 5
   cannot see this class of defect, because a constant typed into plotting
   source appears in neither the writeup nor any script's output.
7. Scan for invisible characters: zero-width spaces and joiners, non-breaking
   spaces, byte-order marks and soft hyphens. None of them shows in an editor or
   a diff, all of them survive a copy-paste out of a browser or a PDF, and a soft
   hyphen inside an identifier breaks a search that looks correct on screen. All
   four repositories were clean on 2026-08-27; the check exists to keep them that
   way, so a hit means something was pasted rather than typed.

   ```sh
   grep -rnP '[\x{200b}-\x{200d}\x{2060}\x{feff}\x{00a0}\x{00ad}]' \
     --include='*.py' --include='*.md' --include='*.cff' .
   ```

Any number the committed code does not produce is a defect. Either the script is
written or the number comes out of the writeup. There is no third option.

## 3. Replication is blind, or it is review

When an analysis is re-derived as a check, the person or process doing the
re-derivation is given the specification only: the regression equation, the
sample definition, the variable construction, the data. Not the results section,
not the tables, not the figures, not the target values.

An instruction to "report disagreements rather than tune toward the published
number" cannot be followed by anyone who already knows the published number. The
knowledge does the tuning whether or not the intent is there. Specification in,
number out, compare afterwards.

## 4. Disagreement rule, pre-committed

If an independent re-derivation disagrees with a published number, and the
published number originates from a working session rather than from committed
code, the re-derivation stands and the published number is retracted.

Not reconciled. Not averaged. Not investigated until the difference is explained
away. Retracted, with the re-derived value published in its place and the
disagreement stated.

The reasoning is that an unauditable number has no standing against an auditable
one, whatever their relative provenance feels like at the time. This rule is
written here before any such disagreement has arisen, because the temptation to
reconcile arrives together with the disagreement and not before it. The same
discipline applies as to pinning a hypothesis before seeing the data.

Where both numbers come from committed code, the disagreement is a defect in one
of them and is resolved on the merits.

## 5. Trials are reported

Every backtest is reported with the number of trials behind it, following
Lopez de Prado's third law of backtesting. The counts are in the
`kase-strategy-audit` writeup. A specification chosen after seeing results is
labelled as such at the point of use.

## 6. A recomputation is not evidence against committed code

An uncommitted script that disagrees with committed output is a hypothesis about
a bug. The first candidate for that bug is the uncommitted script.

Before a disagreement is treated as a defect in the committed code, the
challenging script must itself be committed and reviewed to the same standard. An
ad-hoc reconstruction written to check a number is not an independent
measurement: it was written by someone who knew the target, it has been run once,
and nobody has read it.

This is not a counsel of conservatism. It is what the record shows. Two
reconstructions written in a single evening to check committed numbers were both
wrong, and in both cases the committed number was right:

- One mixed raw-tenge prices from the bar store with USD aggregates from the
  session panel and produced a beta of -54.87. That one announced itself.
- One rebuilt the session set from the store rather than using the panel,
  reported a sample of 555 against the correct 591, and produced an opening-gap
  beta of 0.273 against the correct 0.2986. That one did not announce itself. It
  looked like a plausible small disagreement, and it was nearly used to retract a
  correct result.

The second case is the dangerous one, and it is the reason the rule in Section 4
turns on auditability rather than on which script ran most recently.

The procedure when a recomputation disagrees:

1. Run the committed script. Not a reconstruction of it, the script itself.
2. If the committed script reproduces the published number, the recomputation is
   the outlier and carries the burden of proof.
3. If it does not, the published number is stale and is updated to what the
   committed code produces.
4. Only where no committed code produces the number does Section 4 apply.

## 7. Stored constants are not results

A figure or table that plots values typed into the source is an assertion
wearing the costume of a computation, and it is worse than no figure, because it
cannot go stale visibly. It will agree with whatever it was copied from at the
moment of copying and will silently diverge from the data thereafter.

Where a figure disagrees with the analysis it illustrates, the disagreement is
the finding and the correct response is to publish both and explain them, never
to type the expected values into the plotting code.

The operational rule, which makes a stale figure impossible rather than merely
catchable:

> **No figure plots a literal. Every plotted series is read from a committed file
> under `data/derived/`, written by a committed analysis script.**

Plotting code draws; it does not measure. It holds no regression, no aggregation
over the bar store, and no typed values. Layout numbers are named constants at
the top of the file, so that any number appearing inside a plotting call is
either data or a name.

The rule is stated this way because the weaker version, "do not hardcode figure
values", was already the intent and was broken twice in this repository. The
overlap figure plotted three arrays of betas typed into `make_figures.py` and
went stale against the section it illustrated. The measurement-point curve was
computed inside `make_figures.py`, which meant the table in the writeup was
quoting the stdout of the plotting script, and the figure and the table were one
implementation with no independent check on either. Both survived a clean-clone
gate, because that gate compares document numbers against script output and a
constant in plotting source is in neither set.

Enforcement is `analysis/check_figure_literals.py`, run as step 6 of Section 2.
It fails on a numeric literal outside a styling context, on an import or call
that performs analysis, and on a data read from outside `data/derived/`. It is
tested against both of the historical defects above. The check is implemented in
`kase-price-discovery`; it must be ported to any other repository in this project
before that repository is gated, and `kase-strategy-audit` has plotting code that
has not yet been checked.

## Status

`kase-market-data` has been through the Section 2 procedure twice, both on 2026-10-30: at commit
`a83ed3e` on the `final-writeup` branch, and on the merged `main` at commit `34de24b`.

Before the first run the repository carried this policy and nothing more. Its write-up quoted
board-feed statistics that no committed script produced and bar counts that were stale against
the store, which an unpublished independent verification of 2026-10-12 found; every number now
comes from the five scripts under `analysis/` that write tables, from the endpoint probe
`analysis/probe_endpoint.py`, from the fetcher's `--verify`, or from a named table of the
companion repository, and the figures draw only from `data/derived/`. A later
re-analysis of the same market by the author, also unpublished, found properties of the served
history that no check here had looked for: flat bars outside the session before 2021, the
exchange's closing-time history, and a change in the daily companion on 2026-03-10. Each is now
measured by a committed script and stated in the write-up where it bears on a result.

The first gate, at `a83ed3e`: cloned fresh into an empty directory, a new virtual environment installed from
`requirements.txt` only (pandas 3.1.0, numpy 2.5.4, scipy 1.18.1, pyarrow 26.0.0, matplotlib
3.11.2, requests 2.34.2, yfinance 1.7.0, each newer than the build that wrote the committed
files), the two stores attached through `KASE_STORE` and `KASE_DAILY` and the board recordings
present in the clone; `tradernet_fetch.py --verify` run (it exits 1 by design, reporting seven
bars with non-positive volume in two lines), then the five analysis scripts, then
`src/make_figures.py` and `analysis/check_figure_literals.py`; then `git status data/derived`
empty: all thirty committed tables reproduced byte for byte, including the five that depend on a
Yahoo fetch at run time, two of which record the fetch date and reproduce only on the day they were
written. The printed outputs differed from the author's environment only in deprecation warnings
from pandas and numpy; no numeric line differed. Step 6 passed. Step 7 found nothing, and a scan for
any non-ASCII byte in the scripts and documents found nothing. Figure PNGs are byte-identical within
one matplotlib build and not across builds (3.10.0 against 3.11.2, same dimensions), and no claim
is made that they are. `analysis/probe_endpoint.py`, which writes no table, reproduced the dated
observations the write-up quotes from it.

Step 5 was run as three independent passes, each extracting every number from the documents by
script and matching it against the outputs and the committed tables: the write-up in two halves,
and `README.md`, `data/README.md`, `RELEASE.md` and `CITATION.cff` together. Every value matched
its producer at the printed precision except one upper bound re-quoted as 91% where the table's
maximum rounds to 90%; the other findings were numbers read under the wrong sample or scope,
counts without a producer, and wording, and all were corrected in `a1e4d84` and `8deb98f`. An
earlier review of the first version of this text, on the same day, found three defects in the
producers themselves, since fixed and regenerated: an equality tolerance of five parts in a
hundred thousand, wide enough to absorb real price differences (now equality to the cent), a
dating rule that filed two rows of the recording's final day under the previous session, and a
suffix rule that dropped KMGD as if it were a depositary line. Between the two runs the commits
changed documents, docstrings, `.gitignore` and the endpoint probe, which writes no table; no
table changed.

The second gate, on the merged `main` at `34de24b`: the same procedure in a new clone and a new
virtual environment from `requirements.txt` only (Python 3.13.5, pandas 3.1.0, numpy 2.5.4, scipy
1.18.1, pyarrow 26.0.0, matplotlib 3.11.2, requests 2.34.2, yfinance 1.7.0), the same two stores
and the board recordings present in the clone. `--verify` exited 1 with the same seven bars, every
other script exited 0, Step 6 passed and Step 7 found nothing. `git status data/derived` was empty:
all thirty tables byte-identical. Two of them record the fetch date, `nasdaq_reconciliation_summary.csv`
in its `fetched_on` row and `dividend_dates.csv` in its `source` column; they reproduced because
the run fell on the day they record, 2026-10-30, and a run on a later day changes those date
fields and nothing else in them unless Yahoo has revised a value or, in `dividend_dates.csv`,
listed a new dividend. The four figures, redrawn by matplotlib 3.11.2 against the committed
3.10.0, differed as at the first gate. `analysis/probe_endpoint.py`,
extended at this commit for the three no-bar weekdays and the missing NASDAQ session, returned the
observations the write-up quotes. Step 5 at this run covered the text written since the earlier
passes; its findings, numbers read under the wrong sample and statements of scope, were corrected
in the commit that follows `34de24b`, and the changed paragraphs were checked again. The
commits after `34de24b` change documents and `CITATION.cff` only; no table or figure changed after
the gate.

The companion `kase-price-discovery` has been gated at commit `05684ca` on its own branch;
`kase-strategy-audit` has not been gated and carries an open blocker. Any number that a later run
cannot reproduce is a defect under Section 1 whether or not it is later explained.
