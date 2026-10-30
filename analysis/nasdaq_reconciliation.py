"""
Reconcile the store's KSPI.US 1-minute line against Yahoo Finance daily closes.

What it computes
----------------
For every New York calendar day (ts_ny) that has bars in nasdaq/intraday/KSPI.US:
  store_regular_close   close of the last bar whose ts_ny minute of day is at or
                        after 09:30 and at or before 16:00 (REGULAR_START_MIN <=
                        minute <= REGULAR_LAST_MIN). The bar stamped 16:00 is part of
                        the window: it carries the closing auction.
  store_last_bar_close  close of the last bar of the day, extended hours included.
  regular_bars          number of bars inside the regular window.
  last_regular_bar      HH:MM of the last bar inside the regular window (half
                        sessions close at 13:00 and show up here).
Yahoo Finance is fetched AT RUN TIME: Ticker("KSPI").history(start=first store day,
end=last store day + 1 day, auto_adjust=False); its Close is taken by calendar date.

Rules applied
-------------
* All partitions are concatenated, exact duplicate rows are dropped (the last bar of
  a month is repeated at the head of the next partition), bars are sorted by ts_utc.
* A store day is a New York calendar day with at least one bar. A day without a
  regular bar would keep an empty store_regular_close and count as a mismatch
  (there is no such day in this store).
* Yahoo rows with a missing Close are dropped; a duplicated Yahoo date keeps its last
  row. yahoo_rows in the summary is the raw number of rows Yahoo returned.
* The reconciliation table holds every date present in both sources. n_store_only
  and n_yahoo_only count the dates found in one source only.
* abs_diff = |store_regular_close - yahoo_close|; rel_error_pct = (store_regular_close
  / yahoo_close - 1) * 100, signed. exact: abs_diff < 0.005 (equal to the cent);
  within 0.1 pct: |rel_error_pct| < 0.1. pct_* are percentages of n_sessions_both.
* yahoo_close is rounded to 4 decimals as soon as it is fetched (Yahoo serves float32
  values such as 95.97000122 for 95.97); store closes likewise (they are cents, so this
  only removes float noise). abs_diff and rel_error_pct are rounded to 6 decimals and
  exact / within are decided on those written values, so the table and the summary
  agree. Summary percentages are rounded to 4.
* The summary also lists store_only_dates and yahoo_only_dates (comma-joined ISO
  dates, empty when none) and n_half_cent_yahoo_closes: mismatching sessions whose
  Yahoo close, rounded to 4 decimals, has a non-zero third or fourth decimal, a value
  that no cent-denominated print can equal.
* Printed only: a diagnostic repeating the comparison with the 16:00 bar excluded
  (last bar strictly before 16:00), and the daylight-saving check: per ts_ny calendar
  month, the HH:MM whose bars carry the largest total volume.
* A fetch failure or an empty Yahoo answer stops the script (SystemExit) before any
  file is written.

Files written (DERIVED = data/derived)
  nasdaq_reconciliation.csv          one row per date in both sources, sorted by date
  nasdaq_reconciliation_summary.csv  key,value in the order listed in main()
"""

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _store import DERIVED, store  # noqa: E402

STORE_LINE = "KSPI.US"
YAHOO_SYMBOL = "KSPI"
REGULAR_START_MIN = 9 * 60 + 30  # 09:30 New York, inclusive
REGULAR_LAST_MIN = 16 * 60       # 16:00 New York, inclusive: the 16:00 bar is the closing auction
EXACT_ABS_DIFF = 0.005           # equal to the cent
WITHIN_REL_PCT = 0.1
OUT_TABLE = DERIVED / "nasdaq_reconciliation.csv"
OUT_SUMMARY = DERIVED / "nasdaq_reconciliation_summary.csv"


def load_bars(root):
    folder = root / "nasdaq" / "intraday" / STORE_LINE
    files = sorted(folder.glob("*.parquet"))
    if not files:
        raise SystemExit(f"No partitions under {folder}")
    frames = [f for f in (pd.read_parquet(p) for p in files) if len(f)]
    bars = pd.concat(frames, ignore_index=True)
    n_raw = len(bars)
    bars = bars.drop_duplicates().sort_values("ts_utc", kind="stable").reset_index(drop=True)
    bars["close"] = bars["close"].round(4)  # cents; removes float noise only
    print(f"{STORE_LINE}: {len(files)} partitions, {n_raw} rows, "
          f"{n_raw - len(bars)} exact duplicate rows dropped, {len(bars)} bars kept")
    return bars


def store_daily(bars):
    day = bars["ts_ny"].dt.date
    minute = bars["ts_ny"].dt.hour * 60 + bars["ts_ny"].dt.minute
    regular = (minute >= REGULAR_START_MIN) & (minute <= REGULAR_LAST_MIN)
    reg = bars[regular]
    daily = reg.groupby(day[regular]).agg(
        store_regular_close=("close", "last"),
        regular_bars=("close", "size"),
        last_regular_bar=("ts_ny", lambda s: s.iloc[-1].strftime("%H:%M")),
    )
    last = bars.groupby(day)["close"].last().rename("store_last_bar_close")
    daily = daily.join(last, how="outer").sort_index()
    daily["regular_bars"] = daily["regular_bars"].astype("Int64")
    daily.index.name = "date"
    return daily


def fetch_yahoo(first_day, last_day):
    start = first_day.isoformat()
    end = (last_day + dt.timedelta(days=1)).isoformat()
    try:
        hist = yf.Ticker(YAHOO_SYMBOL).history(start=start, end=end, auto_adjust=False)
    except Exception as exc:  # network, rate limit, parsing
        raise SystemExit(f"Yahoo fetch for {YAHOO_SYMBOL} failed: {exc!r}. Nothing written.")
    if hist is None or hist.empty or "Close" not in hist.columns:
        raise SystemExit(f"Yahoo returned no rows for {YAHOO_SYMBOL} {start}..{end}. Nothing written.")
    close = pd.Series(hist["Close"].to_numpy(dtype=float).round(4),
                      index=pd.Index(hist.index.date, name="date"), name="yahoo_close")
    close = close[~close.index.duplicated(keep="last")].dropna().sort_index()
    if close.empty:
        raise SystemExit(f"Yahoo returned only empty closes for {YAHOO_SYMBOL}. Nothing written.")
    print(f"Yahoo {YAHOO_SYMBOL}: {len(hist)} rows {start}..{end}, {len(close)} usable closes")
    return close, len(hist)


def dst_check(bars):
    month = bars["ts_ny"].dt.strftime("%Y-%m").rename("month")
    hhmm = bars["ts_ny"].dt.strftime("%H:%M").rename("peak_minute")
    vol = bars.groupby([month, hhmm])["volume"].sum().reset_index()
    return vol.loc[vol.groupby("month")["volume"].idxmax()].reset_index(drop=True)


def main():
    root = store()
    bars = load_bars(root)
    daily = store_daily(bars)
    yahoo, yahoo_rows = fetch_yahoo(daily.index.min(), daily.index.max())

    both = daily.join(yahoo, how="inner").sort_index()
    both["abs_diff"] = (both["store_regular_close"] - both["yahoo_close"]).abs().round(6)
    both["rel_error_pct"] = ((both["store_regular_close"] / both["yahoo_close"] - 1) * 100).round(6)
    exact = both["abs_diff"] < EXACT_ABS_DIFF           # on written values; NaN is a mismatch
    within = both["rel_error_pct"].abs() < WITHIN_REL_PCT
    cents = (both["yahoo_close"] * 100).round(6)
    half_cent = ((cents - cents.round()).abs() > 1e-6) & ~exact  # x.xx5-type Yahoo closes
    store_only = sorted(set(daily.index) - set(yahoo.index))
    yahoo_only = sorted(set(yahoo.index) - set(daily.index))
    dst = dst_check(bars)  # computed before anything is written

    table = both.reset_index()[["date", "store_regular_close", "store_last_bar_close",
                                "yahoo_close", "abs_diff", "rel_error_pct",
                                "regular_bars", "last_regular_bar"]].sort_values("date")

    n_both = len(both)
    summary = [
        ("n_sessions_both", n_both),
        ("n_store_only", len(store_only)),
        ("n_yahoo_only", len(yahoo_only)),
        ("store_only_dates", ",".join(d.isoformat() for d in store_only)),
        ("yahoo_only_dates", ",".join(d.isoformat() for d in yahoo_only)),
        ("pct_exact", round(100.0 * exact.sum() / n_both, 4)),
        ("median_abs_rel_error_pct", round(both["rel_error_pct"].abs().median(), 4)),
        ("pct_within_0_1pct", round(100.0 * within.sum() / n_both, 4)),
        ("n_mismatch", int((~exact).sum())),
        ("n_half_cent_yahoo_closes", int(half_cent.sum())),
        ("first_date", both.index.min().isoformat()),
        ("last_date", both.index.max().isoformat()),
        ("fetched_on", dt.date.today().isoformat()),
        ("yahoo_rows", yahoo_rows),
    ]
    DERIVED.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT_TABLE, index=False)
    pd.DataFrame(summary, columns=["key", "value"]).to_csv(OUT_SUMMARY, index=False)

    print(f"\nSummary ({OUT_SUMMARY}):")
    for key, value in summary:
        print(f"  {key} = {value}")

    mism = table[~exact.to_numpy()][["date", "store_regular_close", "yahoo_close",
                                      "rel_error_pct", "regular_bars", "last_regular_bar"]]
    print(f"\nMismatching dates (abs_diff >= {EXACT_ABS_DIFF}): {len(mism)} of {n_both}")
    print(mism.to_string(index=False))

    # Diagnostic, not written: the same comparison with the 16:00 bar excluded.
    minute = bars["ts_ny"].dt.hour * 60 + bars["ts_ny"].dt.minute
    excl = bars[(minute >= REGULAR_START_MIN) & (minute < REGULAR_LAST_MIN)]
    excl_close = excl.groupby(excl["ts_ny"].dt.date)["close"].last()
    diag = excl_close.to_frame("c").join(yahoo, how="inner")
    pct_excl = 100.0 * ((diag["c"] - diag["yahoo_close"]).abs().round(6) < EXACT_ABS_DIFF).mean()
    print(f"\nDiagnostic (not written): with the 16:00 bar excluded (last bar strictly before "
          f"16:00), {pct_excl:.4f}% of {len(diag)} sessions match Yahoo to the cent.")

    print("\nDaylight-saving check: minute of day (ts_ny) with the largest total volume")
    print(dst.to_string(index=False))
    print(f"\nWrote {OUT_TABLE} ({len(table)} rows) and {OUT_SUMMARY} ({len(summary)} rows)")


if __name__ == "__main__":
    main()
