"""
Where bars fall inside the trading session, over time and across instruments.

Input: the 1-minute bar store resolved by analysis/_store.py, laid out as
kase/intraday/<TICKER>/<YYYY-MM>.parquet. An entry under kase/intraday that is not
a directory holding .parquet files (the stray "intraday" symlink, loose files) is
ignored, and so are zero-row partitions. Only ts_almaty and close are read.

Rules applied throughout
- Times of day are Almaty wall clock from ts_almaty; minute_of_day is
  hour * 60 + minute (11:29 = 689, 17:25 = 1045). The HH:MM columns are the same
  values formatted for a reader.
- A session is one Almaty calendar day of one instrument with at least one bar.
  Its first and last bar are the earliest and latest bars of that day.
- Every median and percentile of minute values uses numpy's "lower" rule, so each
  reported time is an observed bar time; the median of an even count is the lower
  of the two middle values. The same rule gives median_bars_per_session and the
  gap percentiles.
- Percentages are plain numbers on a 0-100 scale rounded to PCT_DECIMALS; a share
  whose denominator is zero is written empty.
- "before HH:MM" and "after HH:MM" are strict; "between A and B" is inclusive.
- A gap is the difference in minutes between consecutive bars of one session.
- The modal first (last) bar is the most frequent first (last) minute over the
  sessions of the window; a tie goes to the earlier minute.
- Constant-offset series of (1): the endpoint's timestamps are Almaty wall clock
  in a fixed UTC+3 frame, and Almaty moved from UTC+6 to UTC+5 on 2024-03-01. A
  conversion that subtracts one constant offset, calibrated after that date, stores
  every earlier bar one hour late, so its implied open equals
  median_first_bar_minute + CONSTANT_OFFSET_SHIFT_MIN (60) for months before
  2024-03 and median_first_bar_minute from 2024-03 on. The committed store converts
  through the time-zone database, so its own series is flat across the change.
- "The last month in the store" is the month of the latest bar of any instrument.
  A month of table (1) with no KSPI session gets sessions = 0 and empty medians.
- The KSPI window of (2) and (3) runs from WINDOW_START to the last KSPI session.
- pct_early_first_bar_at_prev_close: among the sessions whose first bar is before
  11:00 and that have an earlier session of the same instrument, the share whose
  first-bar close equals the previous session's last-bar close within a relative
  tolerance PREV_CLOSE_RTOL; empty when there is no such session.

Files written to data/derived/ (rows sorted as listed, to_csv(index=False))
1. implied_open_monthly.csv, KSPI.KZ, one row per month from 2021-07 to the last
   month in the store: month, sessions, median_first_bar_minute, median_first_bar,
   constant_offset_minute, constant_offset (HH:MM of the previous column).
2. session_bar_density.csv, KSPI.KZ window: one row per minute_of_day from 680
   (11:20) to 1060 (17:40): minute_of_day, hhmm, bars (0 where none).
3. session_summary.csv, KSPI.KZ window: key,value rows (ticker, window_start,
   window_end, n_sessions, bars_total, median_bars_per_session,
   pct_sessions_with_bar_1129, pct_sessions_with_bar_1725,
   pct_sessions_last_bar_1725, bars_1715_to_1724, pct_gaps_1min, median_gap_min,
   p90_gap_min, pct_bars_before_1129, pct_bars_after_1730, first_bar_most_common,
   last_bar_most_common).
4. session_bounds_by_year.csv, every instrument, one row per instrument and year:
   instrument, year, sessions, bars, median_first_bar, p10_first_bar,
   median_last_bar, p90_last_bar, pct_bars_before_1100, pct_bars_after_1735,
   pct_sessions_first_bar_before_1100, pct_early_first_bar_at_prev_close.
5. session_bounds.csv, one row per instrument over all years: instrument,
   sessions, bars, first_bar_date, last_bar_date, median_first_bar,
   median_last_bar, pct_bars_before_1100, pct_bars_after_1735.
6. session_end_monthly.csv, the six equities in POOLED_EQUITIES pooled, one row
   per month with at least one instrument-session: month, sessions
   (instrument-sessions), median_last_bar_minute, median_last_bar, p90_last_bar,
   median_first_bar.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _store import store, DERIVED  # noqa: E402

MAIN_TICKER = "KSPI.KZ"
IMPLIED_OPEN_FIRST_MONTH = "2021-07"
OFFSET_CHANGE_MONTH = "2024-03"          # Almaty went from UTC+6 to UTC+5 on 2024-03-01
CONSTANT_OFFSET_SHIFT_MIN = 60           # added to months before OFFSET_CHANGE_MONTH
IMPLIED_OPEN_PRINT = ("2023-12", "2024-05")
WINDOW_START = "2024-01-19"
DENSITY_RANGE = (680, 1060)              # 11:20 .. 17:40 inclusive
POOLED_EQUITIES = ["HSBK.KZ", "KZTO.KZ", "KEGC.KZ", "CCBN.KZ", "KSPI.KZ", "KZAP.KZ"]
PRINT_BOUNDS_FOR = ["HSBK.KZ", "KZTK.KZ", "CCBN.KZ", "KZTO.KZ", "KEGC.KZ", "KZAP.KZ", "KSPI.KZ"]
LAST_BAR_JUMP_MIN = 10                   # month-to-month change worth printing in (6)
PREV_CLOSE_RTOL = 1e-9
PCT_DECIMALS = 3
M1100, M1129, M1715, M1724, M1725, M1730, M1735 = 660, 689, 1035, 1044, 1045, 1050, 1055


def hhmm(m):
    return "" if pd.isna(m) else f"{int(m) // 60:02d}:{int(m) % 60:02d}"


def q(values, pct):
    """Lower-rule percentile of integer minutes as int; None for an empty input."""
    v = np.asarray(values, dtype=float)
    return int(np.percentile(v, pct, method="lower")) if v.size else None


def share(num, den):
    return round(100.0 * num / den, PCT_DECIMALS) if den else None


def mode_minute(s):
    vc = s.value_counts()
    return int(vc[vc == vc.max()].index.min())


def show(title, df):
    print(f"\n== {title}")
    print(df.to_string(index=False, na_rep=""))


def write(name, df):
    path = DERIVED / name
    df.to_csv(path, index=False)
    print(f"\nwrote {path} ({len(df)} rows)")


def load_bars(root):
    frames = []
    for tdir in sorted((root / "kase" / "intraday").iterdir()):
        if tdir.is_symlink() or not tdir.is_dir():
            continue
        parts = [pd.read_parquet(f, columns=["ts_almaty", "close"]) for f in sorted(tdir.glob("*.parquet"))]
        parts = [p for p in parts if len(p)]
        if not parts:
            continue
        d = pd.concat(parts, ignore_index=True)
        ts = d["ts_almaty"]
        if ts.dt.tz is not None:
            ts = ts.dt.tz_localize(None)          # Almaty wall clock, tz dropped
        frames.append(pd.DataFrame({"instrument": tdir.name, "ts": ts, "close": d["close"].to_numpy()}))
    bars = pd.concat(frames, ignore_index=True).sort_values(["instrument", "ts"], kind="stable")
    bars = bars.reset_index(drop=True)
    bars["date"] = bars["ts"].dt.normalize()
    bars["year"] = bars["ts"].dt.year
    bars["minute"] = bars["ts"].dt.hour * 60 + bars["ts"].dt.minute
    bars["before_1100"] = bars["minute"] < M1100
    bars["after_1735"] = bars["minute"] > M1735
    return bars


def session_table(bars):
    s = bars.groupby(["instrument", "date"], sort=True).agg(
        first_minute=("minute", "min"), last_minute=("minute", "max"), bars=("minute", "size"),
        first_close=("close", "first"), last_close=("close", "last")).reset_index()
    s["prev_last_close"] = s.groupby("instrument")["last_close"].shift(1)
    s["year"] = s["date"].dt.year
    s["month"] = s["date"].dt.strftime("%Y-%m")
    s["early"] = s["first_minute"] < M1100
    s["early_with_prev"] = s["early"] & s["prev_last_close"].notna()
    s["early_at_prev"] = s["early_with_prev"] & np.isclose(
        s["first_close"], s["prev_last_close"].fillna(np.inf), rtol=PREV_CLOSE_RTOL, atol=0.0)
    return s


def implied_open_monthly(sessions, last_month):
    ks = sessions[(sessions["instrument"] == MAIN_TICKER) & (sessions["month"] >= IMPLIED_OPEN_FIRST_MONTH)]
    months = pd.period_range(IMPLIED_OPEN_FIRST_MONTH, last_month, freq="M").strftime("%Y-%m")
    g = ks.groupby("month")["first_minute"].agg(sessions="size", med=lambda v: q(v, 50)).reindex(months)
    out = pd.DataFrame({"month": months, "sessions": g["sessions"].fillna(0).astype(int).to_numpy()})
    med = pd.to_numeric(g["med"], errors="coerce").astype(float).round().astype("Int64")
    out["median_first_bar_minute"] = med.array
    out["median_first_bar"] = out["median_first_bar_minute"].map(hhmm)
    shift = np.where(out["month"] < OFFSET_CHANGE_MONTH, CONSTANT_OFFSET_SHIFT_MIN, 0)
    out["constant_offset_minute"] = out["median_first_bar_minute"] + shift
    out["constant_offset"] = out["constant_offset_minute"].map(hhmm)
    lo, hi = IMPLIED_OPEN_PRINT
    show(f"(1) implied open, {MAIN_TICKER}, {lo} to {hi} (table covers {months[0]} to {months[-1]})",
         out[(out["month"] >= lo) & (out["month"] <= hi)])
    return out


def bar_density(wb):
    lo, hi = DENSITY_RANGE
    counts = wb["minute"].value_counts().reindex(range(lo, hi + 1), fill_value=0)
    out = pd.DataFrame({"minute_of_day": counts.index.to_numpy(), "hhmm": [hhmm(m) for m in counts.index],
                        "bars": counts.to_numpy()})
    outside = wb.loc[(wb["minute"] < lo) | (wb["minute"] > hi), "minute"].value_counts().sort_index()
    print(f"\n== (2) bar density, {MAIN_TICKER} window: {int(out['bars'].sum())} bars at minutes "
          f"{hhmm(lo)}-{hhmm(hi)}, {int(outside.sum())} bars outside that range")
    for m, n in outside.items():
        print(f"   outside: {hhmm(m)} x {n}")
    half = out.groupby(out["minute_of_day"] // 30 * 30)["bars"].sum()
    print("   bars per half hour (bucket start): " + ", ".join(f"{hhmm(m)} {n}" for m, n in half.items()))
    top = out.sort_values(["bars", "minute_of_day"], ascending=[False, True]).head(5)
    print("   busiest minutes: " + ", ".join(f"{r.hhmm} {r.bars}" for r in top.itertuples()))
    return out


def session_summary(ws, wb, start, end):
    gaps = wb.groupby("date")["minute"].diff().dropna()
    n = len(ws)
    rows = [("ticker", MAIN_TICKER), ("window_start", start.strftime("%Y-%m-%d")),
            ("window_end", end.strftime("%Y-%m-%d")), ("n_sessions", n), ("bars_total", len(wb)),
            ("median_bars_per_session", q(ws["bars"], 50)),
            ("pct_sessions_with_bar_1129", share(wb.loc[wb["minute"] == M1129, "date"].nunique(), n)),
            ("pct_sessions_with_bar_1725", share(wb.loc[wb["minute"] == M1725, "date"].nunique(), n)),
            ("pct_sessions_last_bar_1725", share(int((ws["last_minute"] == M1725).sum()), n)),
            ("bars_1715_to_1724", int(wb["minute"].between(M1715, M1724).sum())),
            ("pct_gaps_1min", share(int((gaps == 1).sum()), len(gaps))),
            ("median_gap_min", q(gaps, 50)), ("p90_gap_min", q(gaps, 90)),
            ("pct_bars_before_1129", share(int((wb["minute"] < M1129).sum()), len(wb))),
            ("pct_bars_after_1730", share(int((wb["minute"] > M1730).sum()), len(wb))),
            ("first_bar_most_common", hhmm(mode_minute(ws["first_minute"]))),
            ("last_bar_most_common", hhmm(mode_minute(ws["last_minute"])))]
    out = pd.DataFrame(rows, columns=["key", "value"])
    show(f"(3) session summary, {MAIN_TICKER} window ({len(gaps)} within-session gaps)", out)
    return out


def bounds_by_year(bars, sessions):
    gs = sessions.groupby(["instrument", "year"]).agg(
        sessions=("bars", "size"), median_first=("first_minute", lambda v: q(v, 50)),
        p10_first=("first_minute", lambda v: q(v, 10)), median_last=("last_minute", lambda v: q(v, 50)),
        p90_last=("last_minute", lambda v: q(v, 90)), early=("early", "sum"),
        early_with_prev=("early_with_prev", "sum"), early_at_prev=("early_at_prev", "sum"))
    gb = bars.groupby(["instrument", "year"]).agg(
        bars=("minute", "size"), before=("before_1100", "sum"), after=("after_1735", "sum"))
    t = gs.join(gb).reset_index().sort_values(["instrument", "year"])
    out = pd.DataFrame({
        "instrument": t["instrument"], "year": t["year"], "sessions": t["sessions"], "bars": t["bars"],
        "median_first_bar": t["median_first"].map(hhmm), "p10_first_bar": t["p10_first"].map(hhmm),
        "median_last_bar": t["median_last"].map(hhmm), "p90_last_bar": t["p90_last"].map(hhmm),
        "pct_bars_before_1100": [share(a, b) for a, b in zip(t["before"], t["bars"])],
        "pct_bars_after_1735": [share(a, b) for a, b in zip(t["after"], t["bars"])],
        "pct_sessions_first_bar_before_1100": [share(a, b) for a, b in zip(t["early"], t["sessions"])],
        "pct_early_first_bar_at_prev_close": [share(a, b) for a, b in zip(t["early_at_prev"], t["early_with_prev"])],
    })
    show(f"(4) session bounds by year, {len(out)} instrument-years; rows for {', '.join(PRINT_BOUNDS_FOR)}",
         out[out["instrument"].isin(PRINT_BOUNDS_FOR)])
    return out


def bounds_overall(bars, sessions):
    gs = sessions.groupby("instrument").agg(
        sessions=("bars", "size"), first_bar_date=("date", "min"), last_bar_date=("date", "max"),
        median_first=("first_minute", lambda v: q(v, 50)), median_last=("last_minute", lambda v: q(v, 50)))
    gb = bars.groupby("instrument").agg(bars=("minute", "size"), before=("before_1100", "sum"),
                                        after=("after_1735", "sum"))
    t = gs.join(gb).reset_index().sort_values("instrument")
    out = pd.DataFrame({
        "instrument": t["instrument"], "sessions": t["sessions"], "bars": t["bars"],
        "first_bar_date": t["first_bar_date"].dt.strftime("%Y-%m-%d"),
        "last_bar_date": t["last_bar_date"].dt.strftime("%Y-%m-%d"),
        "median_first_bar": t["median_first"].map(hhmm), "median_last_bar": t["median_last"].map(hhmm),
        "pct_bars_before_1100": [share(a, b) for a, b in zip(t["before"], t["bars"])],
        "pct_bars_after_1735": [share(a, b) for a, b in zip(t["after"], t["bars"])],
    })
    show("(5) session bounds per instrument, all years", out)
    return out


def session_end_monthly(sessions):
    p = sessions[sessions["instrument"].isin(POOLED_EQUITIES)]
    g = p.groupby("month").agg(
        sessions=("bars", "size"), median_last_bar_minute=("last_minute", lambda v: q(v, 50)),
        p90_last=("last_minute", lambda v: q(v, 90)), median_first=("first_minute", lambda v: q(v, 50)))
    g = g.reset_index().sort_values("month")
    out = pd.DataFrame({
        "month": g["month"], "sessions": g["sessions"], "median_last_bar_minute": g["median_last_bar_minute"],
        "median_last_bar": g["median_last_bar_minute"].map(hhmm), "p90_last_bar": g["p90_last"].map(hhmm),
        "median_first_bar": g["median_first"].map(hhmm)})
    print(f"\n== (6) session end by month, {', '.join(POOLED_EQUITIES)} pooled: {len(out)} months, "
          f"{out['month'].iloc[0]} to {out['month'].iloc[-1]}, {int(out['sessions'].sum())} instrument-sessions")
    print(f"   months where median_last_bar_minute moves by more than {LAST_BAR_JUMP_MIN} minutes "
          "from the previous month in the table:")
    delta = out["median_last_bar_minute"].diff()
    for i in np.flatnonzero(delta.abs() > LAST_BAR_JUMP_MIN):
        prev, cur = out.iloc[i - 1], out.iloc[i]
        print(f"   {prev['month']} -> {cur['month']}: median last bar {prev['median_last_bar']} -> "
              f"{cur['median_last_bar']} ({int(delta.iloc[i]):+d} min); p90 {prev['p90_last_bar']} -> "
              f"{cur['p90_last_bar']}; median first bar {prev['median_first_bar']} -> {cur['median_first_bar']}; "
              f"sessions {prev['sessions']} -> {cur['sessions']}")
    return out


def main():
    root = store()
    DERIVED.mkdir(parents=True, exist_ok=True)
    bars = load_bars(root)
    sessions = session_table(bars)
    last_month = bars["ts"].max().strftime("%Y-%m")
    print(f"store: {root}\n{bars['instrument'].nunique()} instruments, {len(bars)} bars, {len(sessions)} sessions, "
          f"{bars['ts'].min():%Y-%m-%d} to {bars['ts'].max():%Y-%m-%d}")

    write("implied_open_monthly.csv", implied_open_monthly(sessions, last_month))

    ks = sessions[sessions["instrument"] == MAIN_TICKER]
    start, end = pd.Timestamp(WINDOW_START), ks["date"].max()
    ws = ks[(ks["date"] >= start) & (ks["date"] <= end)]
    wb = bars[(bars["instrument"] == MAIN_TICKER) & (bars["date"] >= start) & (bars["date"] <= end)]
    write("session_bar_density.csv", bar_density(wb))
    write("session_summary.csv", session_summary(ws, wb, start, end))

    write("session_bounds_by_year.csv", bounds_by_year(bars, sessions))
    write("session_bounds.csv", bounds_overall(bars, sessions))
    write("session_end_monthly.csv", session_end_monthly(sessions))


if __name__ == "__main__":
    main()
