"""
Coverage facts about the 1-minute bar store, written as small derived CSV tables.

Inputs, resolved by analysis/_store.py:
  store()/kase/intraday/<TICKER>/<YYYY-MM>.parquet    KASE minute bars
  store()/nasdaq/intraday/KSPI.US/<YYYY-MM>.parquet   NASDAQ minute bars
  daily()/<TICKER>.parquet                            daily companion series

Rules applied:
  * An instrument is a directory under <market>/intraday that holds at least one
    .parquet file; every other entry (loose files, the stray "intraday" symlink) is
    skipped. Only its *.parquet files are read (.lock and _coverage.json are ignored)
    and a partition's month is its file stem.
  * A KASE bar belongs to the Almaty calendar day of ts_almaty; a KSPI.US bar to the
    New York day of ts_ny (the UTC day if that column is absent). Sessions are the
    distinct such days with at least one bar; first_bar and last_bar are those dates.
    Rows that repeat an earlier row of the same instrument exactly (the leading
    reference bar of a month repeated from the previous partition, which the NASDAQ
    fetcher does not filter) are dropped before counting; the number dropped per
    market is printed, and bars counts what remains. A market directory that is
    absent is skipped with a note.
  * store_bars_by_year lists every year covered by at least one monthly partition of
    the instrument, so a year the store checked and found empty appears with 0 bars.
  * zero_row_partitions.daily_bars counts the daily companion rows dated inside that
    month. It is empty when the instrument has no daily file, and contradicted is
    then False (there is no evidence either way).
  * The market-wide daily calendar is the union of the dates in every daily file,
    restricted to the span from the first to the last KASE minute bar, so dates before
    collection began or after it stopped do not count as gaps (the excluded counts
    are printed). A no-trading run is consecutive within that calendar; runs of at
    least MIN_GAP_DATES dates are written, and the per-instrument table covers the
    longest run (the earliest if tied) for every instrument that has a daily file.
  * market_closures and halt_2022 cover Monday-to-Friday dates only. Weekend trading
    days (working Saturdays or Sundays) inside the windows are printed but not
    listed. A run of no-trading weekdays is consecutive in the weekday sequence, so a
    Friday and the following Monday are consecutive. market_closures also counts, per
    weekday, the instruments with a row in the daily companion that day.
  * median_first_bar and median_last_bar take each instrument's first and last bar of
    the day in Almaty wall time, in minutes after midnight; the median across the
    instruments is rounded half up to the whole minute and written HH:MM.
  * daily_vs_minute matches (instrument, date) between the daily file and the close of
    the last minute bar of the Almaty day. pct_exact uses |m/d - 1| < EXACT_TOL and
    pct_within_0_1pct uses |m/d - 1| <= NEAR_TOL. Percentages run 0-100 and are
    rounded to two decimals. The year column is text; "all" sorts after the years.
  * daily_vs_minute_monthly pools those matched sessions over all instruments: one row
    per calendar month from MONTHLY_START to the last matched month (a month without
    sessions would still appear, with 0), then a row "to <BREAK_BEFORE>" over every
    matched session up to that date, from the first session of the store, and a row
    "from <BREAK_AFTER>" over every matched session from that date on; the rows are
    written in that order. pct_daily_close_equals_some_bar is the share of sessions
    whose daily close is within EXACT_TOL (relative) of the close of at least one
    minute bar of the day. median_volume_ratio is the median over sessions of daily
    volume divided by the day's summed minute volume, rounded to three decimals; a
    session whose minute volume sums to zero or whose volume is missing is left out of
    the median, and the cell is empty when no session remains.

Files written under data/derived/:
  store_inventory.csv            one row per instrument directory, both markets
  store_bars_by_year.csv         instrument, year, bars, sessions (KASE)
  zero_row_partitions.csv        every empty monthly partition, checked against daily
  collection_gaps.csv            runs of >= MIN_GAP_DATES daily dates with no bars
  collection_gap_instruments.csv daily and minute bars per instrument in the longest run
  market_closures.csv            instruments trading on every weekday of the window
  halt_2022.csv                  weekday coverage around the January 2022 halt
  daily_vs_minute.csv            agreement of daily close with the minute session close
  daily_vs_minute_monthly.csv    the same agreement pooled by month, and before/after the break
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _store import store, daily, DERIVED  # noqa: E402

MIN_GAP_DATES = 5                       # shortest no-trading run written as a gap
CLOSURE_START, CLOSURE_END = "2024-01-19", "2026-08-24"
HALT_START, HALT_END = "2021-12-20", "2022-02-04"
EXACT_TOL = 1e-6                        # |minute_close / daily_close - 1| below this: exact
NEAR_TOL = 1e-3                         # ... at or below this: within 0.1 percent
MONTHLY_START = "2025-09"               # first month of the pooled monthly table
BREAK_BEFORE, BREAK_AFTER = "2026-03-06", "2026-03-10"   # last and first session around the break
MARKETS = {"kase": "kase/intraday", "nasdaq": "nasdaq/intraday"}
MATCH_SPEC = dict(sessions_both=("day", "size"), pct_exact=("exact", "mean"), pct_within_0_1pct=("near", "mean"))
MONTHLY_SPEC = dict(MATCH_SPEC, pct_daily_close_equals_some_bar=("any_bar", "mean"),
                    median_volume_ratio=("vol_ratio", "median"))

pd.set_option("display.width", 200, "display.max_rows", 5000)


def show(df):
    print(df.to_string(index=False) if len(df) else "(no rows)")


def write(name, df):
    df.to_csv(DERIVED / name, index=False)
    print(f"\n=== {name} ({len(df)} rows) ===")


def hhmm(minutes):
    m = None if pd.isna(minutes) else int(minutes + 0.5)
    return "" if m is None else f"{m // 60:02d}:{m % 60:02d}"


def true_runs(mask):
    """Runs of consecutive True in a boolean Series indexed by date: start, end, length."""
    run = (mask != mask.shift()).cumsum()
    frame = pd.DataFrame({"date": mask.index, "run": run.values})[mask.values]
    return frame.groupby("run")["date"].agg(start="min", end="max", length="size").reset_index(drop=True)


BAR_COLUMNS = ["market", "instrument", "ts_utc", "day", "tod", "close", "volume"]


def read_market(root, market):
    """One row per partition and one row per distinct bar for every instrument of a market."""
    parts, bars = [], []
    if not root.is_dir():
        print(f"note: {root} is absent, market {market} skipped")
    for inst_dir in (sorted(root.iterdir()) if root.is_dir() else []):
        for f in (sorted(inst_dir.glob("*.parquet")) if inst_dir.is_dir() else []):
            df = pd.read_parquet(f)
            parts.append((market, inst_dir.name, f.stem, len(df)))
            if len(df) == 0:
                continue
            col = "ts_almaty" if market == "kase" else ("ts_ny" if "ts_ny" in df.columns else "ts_utc")
            local = df[col].dt.tz_localize(None)
            bars.append(pd.DataFrame({
                "market": market, "instrument": inst_dir.name, "ts_utc": df["ts_utc"],
                "day": local.dt.normalize(), "tod": local.dt.hour * 60 + local.dt.minute,
                "close": df["close"], "volume": df["volume"]}))
    parts = pd.DataFrame(parts, columns=["market", "instrument", "month", "rows"])
    if not bars:
        return parts, pd.DataFrame(columns=BAR_COLUMNS)
    bars = pd.concat(bars, ignore_index=True)
    before = len(bars)
    bars = bars.drop_duplicates(subset=["instrument", "ts_utc", "close", "volume"]).reset_index(drop=True)
    print(f"{market}: {before} partition rows, {before - len(bars)} exact duplicate rows dropped, {len(bars)} bars")
    return parts, bars[BAR_COLUMNS]


def read_daily(root):
    """The instrument names that have a daily file, and their rows (instrument, date, close, volume)."""
    names, frames = [], []
    for f in sorted(root.glob("*.parquet")):
        df = pd.read_parquet(f, columns=["date", "close", "volume"])
        names.append(f.stem)
        if len(df):
            frames.append(df.assign(instrument=f.stem)[["instrument", "date", "close", "volume"]])
    return names, pd.concat(frames, ignore_index=True)


def inventory(parts, bars):
    p = parts.assign(zero=parts["rows"] == 0).groupby(["market", "instrument"]).agg(
        partitions=("rows", "size"), zero_row_partitions=("zero", "sum"))
    b = bars.groupby(["market", "instrument"]).agg(
        bars=("day", "size"), sessions=("day", "nunique"), first_bar=("day", "min"), last_bar=("day", "max"))
    inv = p.join(b).reset_index()
    inv["bars"] = inv["bars"].fillna(0).astype(int)
    inv["sessions"] = inv["sessions"].fillna(0).astype(int)
    for c in ("first_bar", "last_bar"):
        inv[c] = inv[c].dt.strftime("%Y-%m-%d")
    inv = inv.sort_values(["market", "instrument"]).reset_index(drop=True)
    return inv[["instrument", "market", "partitions", "zero_row_partitions", "bars",
                "sessions", "first_bar", "last_bar"]]


def bars_by_year(parts, bars):
    k = bars[bars["market"] == "kase"]
    by = k.assign(year=k["day"].dt.year).groupby(["instrument", "year"]).agg(
        bars=("day", "size"), sessions=("day", "nunique")).reset_index()
    kp = parts[parts["market"] == "kase"]
    covered = kp.assign(year=kp["month"].str[:4].astype(int))[["instrument", "year"]].drop_duplicates()
    out = covered.merge(by, how="outer", on=["instrument", "year"]).fillna({"bars": 0, "sessions": 0})
    out[["bars", "sessions"]] = out[["bars", "sessions"]].astype(int)
    return out.sort_values(["instrument", "year"]).reset_index(drop=True)


def zero_partitions(parts, dailydf, daily_names):
    z = parts[(parts["market"] == "kase") & (parts["rows"] == 0)][["instrument", "month"]]
    z = z.sort_values(["instrument", "month"]).reset_index(drop=True)
    per_month = dailydf.assign(month=dailydf["date"].dt.strftime("%Y-%m")).groupby(["instrument", "month"]).size()
    z["daily_bars"] = pd.array(
        [per_month.get((i, m), 0) if i in daily_names else None for i, m in zip(z["instrument"], z["month"])],
        dtype="Int64")
    z["contradicted"] = (z["daily_bars"].fillna(0) > 0).astype(bool)
    return z


def collection_gaps(bars, dailydf, daily_names):
    k = bars[bars["market"] == "kase"]
    cal = pd.DatetimeIndex(sorted(dailydf["date"].unique()))
    first, last = k["day"].min(), k["day"].max()
    before, after = int((cal < first).sum()), int((cal > last).sum())
    cal = cal[(cal >= first) & (cal <= last)]
    trading = k.groupby("day")["instrument"].nunique().reindex(cal, fill_value=0)
    runs = true_runs(trading.eq(0))
    print(f"daily calendar: {len(cal) + before + after} dates, {before} before the first minute bar "
          f"({first.date()}) and {after} after the last ({last.date()}) are excluded; "
          f"{int(trading.eq(0).sum())} of the remaining {len(cal)} dates have no minute bar in any instrument")
    runs = runs[runs["length"] >= MIN_GAP_DATES].reset_index(drop=True)
    gaps = pd.DataFrame({
        "start": runs["start"].dt.strftime("%Y-%m-%d"), "end": runs["end"].dt.strftime("%Y-%m-%d"),
        "trading_dates": runs["length"],
        "instruments_with_daily_bars": [
            dailydf.loc[dailydf["date"].between(s, e), "instrument"].nunique()
            for s, e in zip(runs["start"], runs["end"])]})
    gi = pd.DataFrame({"instrument": sorted(daily_names)})
    if len(runs):
        top = runs.sort_values(["length", "start"], ascending=[False, True]).iloc[0]
        d_in = dailydf[dailydf["date"].between(top["start"], top["end"])].groupby("instrument").size()
        m_in = k[k["day"].between(top["start"], top["end"])].groupby("instrument").size()
        gi["daily_bars_in_gap"] = gi["instrument"].map(d_in).fillna(0).astype(int)
        gi["minute_bars_in_gap"] = gi["instrument"].map(m_in).fillna(0).astype(int)
        print(f"longest run: {top['start'].date()} to {top['end'].date()}, {top['length']} daily dates")
    else:
        gi["daily_bars_in_gap"], gi["minute_bars_in_gap"] = 0, 0
        print(f"no run of {MIN_GAP_DATES} or more no-trading dates")
    return gaps, gi


def market_closures(bars, dailydf):
    k = bars[bars["market"] == "kase"]
    days = pd.bdate_range(CLOSURE_START, CLOSURE_END)
    per_day = k.groupby("day")["instrument"].nunique()
    n = per_day.reindex(days, fill_value=0)
    d = dailydf.groupby("date")["instrument"].nunique().reindex(days, fill_value=0)
    out = pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "weekday": days.day_name(),
                        "instruments_trading": n.values, "daily_instruments": d.values})
    idle = out.loc[n.eq(0).values, "date"].tolist()
    runs = true_runs(n.eq(0))
    longest = int(runs["length"].max()) if len(runs) else 0
    weekend = per_day[(per_day.index >= days[0]) & (per_day.index <= days[-1]) & (per_day.index.dayofweek >= 5)]
    print(f"window {CLOSURE_START} to {CLOSURE_END}: {len(days)} weekdays, {len(idle)} with no instrument "
          f"trading, longest run of consecutive no-trading weekdays: {longest}; daily companion rows on "
          f"those weekdays: {int(d[n.eq(0)].sum())}")
    print("no-trading weekdays: " + (", ".join(idle) if idle else "none"))
    print("weekend days with trading inside the window (not listed in the table): " + (
        ", ".join(f"{d.date()} ({c} instruments)" for d, c in weekend.items()) if len(weekend) else "none"))
    return out


def halt_table(bars):
    k = bars[bars["market"] == "kase"]
    days = pd.bdate_range(HALT_START, HALT_END)
    sub = k[k["day"].between(days[0], days[-1])]
    per = sub.groupby(["day", "instrument"])["tod"].agg(first="min", last="max").reset_index()
    med = per.groupby("day").agg(instruments_trading=("instrument", "size"),
                                 median_first_bar=("first", "median"),
                                 median_last_bar=("last", "median")).reindex(days)
    weekend = sorted(d.date() for d in sub["day"].unique() if d.dayofweek >= 5)
    print(f"window {HALT_START} to {HALT_END}: {len(days)} weekdays, "
          f"{int(med['instruments_trading'].isna().sum())} with no instrument trading; "
          f"weekend days with trading: {', '.join(map(str, weekend)) if weekend else 'none'}")
    return pd.DataFrame({"date": days.strftime("%Y-%m-%d"),
                         "instruments_trading": med["instruments_trading"].fillna(0).astype(int).values,
                         "median_last_bar": med["median_last_bar"].map(hhmm).values,
                         "median_first_bar": med["median_first_bar"].map(hhmm).values})


def session_matches(bars, dailydf):
    """One row per (instrument, Almaty day) present in both series, with the comparisons."""
    k = bars[bars["market"] == "kase"].sort_values(["instrument", "ts_utc"], kind="stable")
    sess = k.drop_duplicates(["instrument", "day"], keep="last")[["instrument", "day", "close"]]
    sess = sess.rename(columns={"close": "minute_close"}).merge(
        k.groupby(["instrument", "day"])["volume"].sum().rename("minute_volume").reset_index())
    both = sess.merge(dailydf.rename(columns={"date": "day", "close": "daily_close", "volume": "daily_volume"}))
    dev = (both["minute_close"] / both["daily_close"] - 1).abs()
    hits = k.merge(both[["instrument", "day", "daily_close"]])
    hits = hits.loc[(hits["close"] / hits["daily_close"] - 1).abs() < EXACT_TOL, ["instrument", "day"]]
    both = both.merge(hits.drop_duplicates(), how="left", indicator="hit")
    return both.assign(
        exact=dev < EXACT_TOL, near=dev <= NEAR_TOL, any_bar=both["hit"].eq("both"),
        vol_ratio=both["daily_volume"] / both["minute_volume"].where(both["minute_volume"] > 0),
        year=both["day"].dt.year.astype(str), month=both["day"].dt.strftime("%Y-%m"))


def summarize(both, by, spec):
    out = both.groupby(by).agg(**spec).reset_index()
    pct = [c for c in out.columns if c.startswith("pct_")]
    out[pct] = (out[pct] * 100).round(2)
    return out


def daily_vs_minute(both):
    by_year = summarize(both, ["instrument", "year"], MATCH_SPEC)
    overall = summarize(both, ["instrument"], MATCH_SPEC).assign(year="all")
    out = pd.concat([by_year, overall], ignore_index=True).sort_values(["instrument", "year"]).reset_index(drop=True)
    return out[["instrument", "year", "sessions_both", "pct_exact", "pct_within_0_1pct"]]


def daily_vs_minute_monthly(both):
    months = pd.period_range(MONTHLY_START, both["month"].max(), freq="M").strftime("%Y-%m")
    by_month = summarize(both[both["month"] >= MONTHLY_START], ["month"], MONTHLY_SPEC)
    by_month = by_month.set_index("month").reindex(months).rename_axis("month").reset_index()
    by_month["sessions_both"] = by_month["sessions_both"].fillna(0).astype(int)
    before = both[both["day"] <= pd.Timestamp(BREAK_BEFORE)].assign(month=f"to {BREAK_BEFORE}")
    after = both[both["day"] >= pd.Timestamp(BREAK_AFTER)].assign(month=f"from {BREAK_AFTER}")
    spans = [summarize(part, ["month"], MONTHLY_SPEC) for part in (before, after) if len(part)]
    out = pd.concat([by_month] + spans, ignore_index=True)
    out["median_volume_ratio"] = out["median_volume_ratio"].round(3)
    return out[["month", "sessions_both", "pct_exact", "pct_within_0_1pct",
                "pct_daily_close_equals_some_bar", "median_volume_ratio"]]


def main():
    root, daily_root = store(), daily()
    DERIVED.mkdir(parents=True, exist_ok=True)
    print(f"minute store: {root}\ndaily series: {daily_root}\noutput: {DERIVED}")
    parts, bars = zip(*(read_market(root / sub, market) for market, sub in MARKETS.items()))
    parts, bars = pd.concat(parts, ignore_index=True), pd.concat(bars, ignore_index=True)
    daily_names, dailydf = read_daily(daily_root)
    print(f"read {len(parts)} partitions, {len(bars)} bars; {len(daily_names)} daily files, {len(dailydf)} rows")

    inv = inventory(parts, bars)
    write("store_inventory.csv", inv)
    show(inv)
    totals = inv.groupby("market").agg(instruments=("instrument", "size"), partitions=("partitions", "sum"),
                                       zero_row_partitions=("zero_row_partitions", "sum"), bars=("bars", "sum"))
    print("\ntotals by market:\n" + totals.to_string())

    by = bars_by_year(parts, bars)
    write("store_bars_by_year.csv", by)
    print("KSPI.KZ rows:")
    show(by[by["instrument"] == "KSPI.KZ"])

    z = zero_partitions(parts, dailydf, daily_names)
    write("zero_row_partitions.csv", z)
    print(f"{len(z)} zero-row partitions in the KASE store, {int(z['contradicted'].sum())} contradicted by the "
          f"daily series (daily rows exist in a month the minute store recorded as empty)")
    c = z[z["contradicted"]]
    for (inst, year), g in c.assign(year=c["month"].str[:4]).groupby(["instrument", "year"]):
        print(f"  {inst} {year}: months {' '.join(g['month'].str[5:])} ({len(g)} partitions, "
              f"{int(g['daily_bars'].sum())} daily rows)")

    gaps, gi = collection_gaps(bars, dailydf, daily_names)
    write("collection_gaps.csv", gaps)
    show(gaps)
    write("collection_gap_instruments.csv", gi)
    show(gi)

    closures = market_closures(bars, dailydf)
    write("market_closures.csv", closures)
    print(f"{len(closures)} weekday rows written; {int(closures['instruments_trading'].eq(0).sum())} with zero "
          f"instruments trading; median instruments trading on the other days: "
          f"{closures.loc[closures['instruments_trading'] > 0, 'instruments_trading'].median():.0f}")

    halt = halt_table(bars)
    write("halt_2022.csv", halt)
    show(halt)

    both = session_matches(bars, dailydf)
    dvm = daily_vs_minute(both)
    write("daily_vs_minute.csv", dvm)
    print("all-years rows:")
    show(dvm[dvm["year"] == "all"])
    for inst in ("KSPI.KZ", "HSBK.KZ"):
        print(f"\n{inst} by year:")
        show(dvm[(dvm["instrument"] == inst) & (dvm["year"] != "all")])

    monthly = daily_vs_minute_monthly(both)
    write("daily_vs_minute_monthly.csv", monthly)
    show(monthly)


if __name__ == "__main__":
    main()
