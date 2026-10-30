"""
What the two quote-labelled fields on the exchange's daily results board contain,
and when the board updates.

The board recordings (one CSV per trading day, one row per instrument per
5-minute snapshot) carry the fields the endpoint labels current_bid and
current_offer (columns bid, ask) next to the session's open, high, low, last and
deal count. This script tests, against the 1-minute bar store, which session the
board reports at each hour of the day, then tests what bid and ask hold on the
instrument-session table that results. Steps and rules (constants at the top):

 1. Load every board file; parse timestamp (utc=True, then Asia/Almaty); label a
    snapshot before_open (< 11:30), in_session ([11:30, 17:30)) or after_close
    (>= 17:30) by the slot's minute of day.
 2. Freeze check: (ticker, day) groups with more than one in-session snapshot
    whose (bid, ask, last, high, low, deals) tuple is not identical, compared
    exactly (nunique with NaN counted as a value).
 3. Session identity. A board ticker is matched when the store directory
    <TICKER>.KZ holds at least one bar in the months loaded (one month before
    the first board day through the last board day's month). For a matched row
    with snapshot day D, P is the store's last trading day strictly before D. The
    row's last is compared with the store session close of P and of D. Every price
    equality in this script means equal to the cent: within ABS_TOL, half of the
    PRICE_STEP of 0.01 in which the board and the store quote, which absorbs float
    noise and nothing else. Categories are exclusive: prev (P only), same (D only),
    both, neither. The staleness table has one row per hourly bucket from 09:00
    to 20:00 (rows at or after 21:00 fold into the 20:00 bucket) and carries
    pct_both so the four percentages sum to 100; inclusive shares are printed. A
    snapshot carries the same-day payload when strictly more than half of its
    matched rows are "same"; the per-day first such snapshot is an upper bound on
    the switch time, since snapshots are 1 to 14 per day at irregular slots. Over
    snapshots on store trading days the script also reports the latest snapshot
    whose majority is prev or both, the earliest whose majority is same, and the
    number of snapshots at or after SWITCH_CHECK_MINUTE without a same majority
    (the any-day count also covers holidays and the day after the store ends).
 4. reported_session: P for prev rows, D for same rows; otherwise (both, neither,
    unmatched) the time rule. With TIME_RULE_CALENDAR "store" the trading days
    are every Almaty day on which any matched ticker has a bar in the loaded
    months: in session or before open -> the last trading day strictly before D;
    after close -> D when D is a trading day, else the last trading day before D.
    A weekday after the store's last day counts as a trading day
    (WEEKDAYS_BEYOND_STORE_ARE_TRADING_DAYS), so the board's final day keeps its
    own session; on such a day an after-close row is dated by the time rule even
    when its last happens to equal an earlier store close, because the store
    cannot confirm it. With "weekday" the rule is the previous weekday (numpy
    business days, no holidays) before D, or D after close. Rows collapse to one
    per (ticker, reported_session), keeping the latest snapshot; "store-matched"
    below means the kept row's assignment came from the store match. Variation
    inside a collapsed group is exact inequality of bid, ask or last. Also printed:
    how many instrument-sessions repeat the ticker's previous one exactly and how
    many are keyed to a day the store has no bars for.
 5. Crossing: equal means bid and ask equal to the cent; crossed and normal
    exclude equal. Filter (b) adds deals > 0 (deals is never 0 or null in these
    recordings, so (a) and (b) coincide).
 6. Liquidity signature on instrument-sessions with bid, ask, high, low > 0 and
    deals > 0, binned by deals; collapsed means bid equals high and ask equals low
    to the cent.
 7. Extreme-quote tests. "within payload" uses the row's own high and low on the
    step-6 set; "store aligned" uses the store's session high and low of the
    reported session, on store-matched rows with bid, ask > 0. ge/le tests accept
    equality to the cent; gt/lt tests are strict beyond it; width_ge_range allows
    (bid - ask) to fall short of (high - low) by ABS_TOL. The Spearman row holds
    the coefficient, not a percentage.
 8. Residual placement on the store-aligned set: a violation is bid below the
    session high (ask above the session low) by more than ABS_TOL; high_minute and
    low_minute are the minute of day of the first bar reaching the extreme, and
    are compared with the first and last bar minute of the session.
 9. Widths per ticker on instrument-sessions with bid, ask > 0 and last > 0;
    signed, so a crossed quote has a positive width. The range of
    median_half_width_pct over SIX_TICKERS is printed.
10. Uncrossed snapshots: at least half of the rows with bid, ask > 0 have bid
    strictly below ask. The table carries, per snapshot, the median width
    (ask - bid) as a percentage of last and the share of two-sided rows whose last
    lies between bid and ask. KSPI context rows are printed, not written.
11. Probe summary: times are Almaty HH:MM:SS; distinct counts treat NaN as a
    value; last_deal_date is written only when a code shows a single value.
12. Summary of every headline number as key,value rows, plus the inclusive
    shares, the switch bounds, the snapshot cadence per CADENCE_PERIODS (over the
    days in each period with at least one snapshot; keys carry start_end), the
    SIX_TICKERS median half widths and copies of five extreme-test cells.

Floats are rounded to ROUND decimals in the CSVs; percentages are 0-100.
Files written to data/derived/: board_staleness.csv, board_first_same_day.csv,
board_crossing.csv, board_liquidity_signature.csv, board_extreme_quote_tests.csv,
board_residual_placement.csv, board_widths.csv, board_uncrossed_snapshots.csv,
probe_summary.csv (when the probe file is present), board_summary.csv.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _store import DERIVED, board, probe, store  # noqa: E402

TZ = "Asia/Almaty"
SESSION_OPEN_MINUTE = 11 * 60 + 30    # 11:30, first in-session minute
SESSION_CLOSE_MINUTE = 17 * 60 + 30   # 17:30, first after-close minute
PRICE_STEP = 0.01                     # the board and the store quote to the cent
ABS_TOL = PRICE_STEP / 2              # equal to the cent: absorbs float noise only
BUCKET_FIRST_MINUTE = 9 * 60          # staleness buckets 09:00 ...
BUCKET_LAST_MINUTE = 20 * 60          # ... to 20:00 (later rows folded in)
DEAL_BIN_EDGES = [0, 1, 3, 10, 50, 200, 1000, np.inf]
DEAL_BIN_LABELS = ["1", "2-3", "4-10", "11-50", "51-200", "201-1000", "1000+"]
MAJORITY_SHARE = 0.5                  # same-day payload: more than this share of matched rows
UNCROSSED_SHARE = 0.5                 # uncrossed snapshot: at least this share with bid < ask
FREEZE_COLS = ["bid", "ask", "last", "high", "low", "deals"]
PROBE_FIELDS = ["bid", "ask", "last", "high", "low", "dealcnt", "volkzt", "last_deal_date"]
SWITCH_CHECK_MINUTE = 17 * 60 + 40    # every snapshot at or after 17:40 is expected to be same-day
TIME_RULE_CALENDAR = "store"          # "store": market-wide store trading days; "weekday": previous weekday
WEEKDAYS_BEYOND_STORE_ARE_TRADING_DAYS = True   # a weekday after the store's last day counts as a trading day
CADENCE_PERIODS = [("2026-04-14", "2026-04-24"), ("2026-04-27", "2026-08-06"),
                   ("2026-08-07", "2026-08-14"), ("2026-08-17", "2026-08-25")]
SIX_TICKERS = ["KSPI", "HSBK", "KZAP", "AIRA", "KCEL", "KEGC"]
ROUND = 4


def eq(a, b):
    """Price equality to the cent (within ABS_TOL); NaN compares unequal."""
    return np.isclose(np.asarray(a, float), np.asarray(b, float), rtol=0.0, atol=ABS_TOL)


def pct(mask):
    mask = np.asarray(mask, bool)
    return 100.0 * mask.mean() if mask.size else np.nan


def hhmm(minute):
    if pd.isna(minute):
        return ""
    minute = int(round(minute))
    return f"{minute // 60:02d}:{minute % 60:02d}"


def by_day(dates):
    """{YYYY-MM-DD: count} of a datetime Series or Index, in date order."""
    return {d.date().isoformat(): int(n) for d, n in pd.Series(dates).value_counts().sort_index().items()}


def write(name, table):
    table = table.round(ROUND)
    table.to_csv(DERIVED / name, index=False)
    print(f"\n== {name} ({len(table)} rows)")
    print(table.to_string(index=False))


def load_board():
    files = sorted(board().glob("*/*/*.csv"))
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(TZ)
    df["snapshot_day"] = df["ts"].dt.tz_localize(None).dt.normalize()
    df["minute_of_day"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute
    m = df["minute_of_day"]
    df["phase"] = np.select([m < SESSION_OPEN_MINUTE, m < SESSION_CLOSE_MINUTE],
                            ["before_open", "in_session"], "after_close")
    print(f"board files: {len(files)}")
    return df.sort_values(["ts", "ticker"]).reset_index(drop=True)


def load_sessions(tickers, first_day, last_day):
    """Per matched ticker, one row per Almaty day with bars (index: naive midnight)."""
    root = store() / "kase" / "intraday"
    months = pd.period_range(first_day - pd.DateOffset(months=1), last_day, freq="M")
    out = {}
    for t in tickers:
        d = root / f"{t}.KZ"
        paths = [d / f"{m}.parquet" for m in months if (d / f"{m}.parquet").exists()]
        parts = [p for p in (pd.read_parquet(p) for p in paths) if len(p)]
        if not parts:
            continue
        bars = pd.concat(parts, ignore_index=True).sort_values("ts_almaty").reset_index(drop=True)
        bars["day"] = bars["ts_almaty"].dt.tz_localize(None).dt.normalize()
        bars["minute"] = bars["ts_almaty"].dt.hour * 60 + bars["ts_almaty"].dt.minute
        g = bars.groupby("day")
        out[t] = pd.DataFrame({
            "session_close": g["close"].last(), "session_high": g["high"].max(),
            "session_low": g["low"].min(), "bars": g.size(),
            "first_bar_minute": g["minute"].min(), "last_bar_minute": g["minute"].max(),
            "high_minute": bars.loc[g["high"].idxmax(), "minute"].values,
            "low_minute": bars.loc[g["low"].idxmin(), "minute"].values,
        })
    return out


def classify(df, sessions):
    """Step 3: previous store day P, the two closes, and the exclusive category."""
    df["P"] = pd.NaT
    df["prev_close"] = np.nan
    df["same_close"] = np.nan
    for t, s in sessions.items():
        idx = df.index[df["ticker"] == t]
        days = s.index.values
        D = df.loc[idx, "snapshot_day"].values
        pos = np.searchsorted(days, D, side="left")
        P = np.where(pos > 0, days[np.maximum(pos - 1, 0)], np.datetime64("NaT"))
        df.loc[idx, "P"] = P
        df.loc[idx, "prev_close"] = s["session_close"].reindex(P).values
        df.loc[idx, "same_close"] = s["session_close"].reindex(D).values
    is_prev, is_same = eq(df["last"], df["prev_close"]), eq(df["last"], df["same_close"])
    df["category"] = np.select([is_prev & is_same, is_prev, is_same], ["both", "prev", "same"], "neither")
    df.loc[~df["ticker"].isin(sessions), "category"] = "unmatched"
    return df


def category_shares(sub):
    c = sub["category"]
    return {"n_rows": len(sub), "pct_prev_close": pct(c == "prev"), "pct_same_close": pct(c == "same"),
            "pct_both": pct(c == "both"), "pct_neither": pct(c == "neither")}


def time_rule_sessions(D, after_close, trading):
    """Step 4 time rule: the session a row reports when the store match does not decide it."""
    if TIME_RULE_CALENDAR == "weekday":
        return np.where(after_close, D, np.busday_offset(D, -1, roll="forward"))
    pos = np.searchsorted(trading, D, side="left")      # trading[pos - 1] is the last trading day before D
    if pos.min() == 0:
        raise SystemExit("A board day precedes the store's first trading day; load an earlier month.")
    is_trading_day = np.isin(D, trading)
    if WEEKDAYS_BEYOND_STORE_ARE_TRADING_DAYS:
        is_trading_day |= (D > trading.max()) & np.is_busday(D)
    return np.where(after_close & is_trading_day, D, trading[pos - 1])


def main():
    DERIVED.mkdir(parents=True, exist_ok=True)
    df = load_board()

    # ---- 1. inventory
    snaps = df.drop_duplicates("ts")
    rows_per_snap = df.groupby("ts").size()
    snaps_per_day = snaps.groupby("snapshot_day").size()
    first_day, last_day = df["snapshot_day"].min(), df["snapshot_day"].max()
    print(f"rows {len(df)}, snapshots {len(snaps)}, days {snaps_per_day.size} "
          f"({first_day.date()} to {last_day.date()}), tickers {df['ticker'].nunique()}")
    print(f"rows per snapshot min/median/max: {rows_per_snap.min()}/{rows_per_snap.median():g}/{rows_per_snap.max()}")
    print(f"snapshots per day min/median/max: {snaps_per_day.min()}/{snaps_per_day.median():g}/{snaps_per_day.max()}")
    print("snapshots by phase:", snaps["phase"].value_counts().to_dict())
    nonnull = {c: int(df[c].notna().sum()) for c in ["fx_usdkzt", "bid", "ask", "last"]}
    print("non-null rows:", nonnull)
    print("rows with null open/high/low by snapshot day:", by_day(df.loc[df[["open", "high", "low"]].isna().any(axis=1), "ts"]))

    # ---- 2. freeze check within a day
    ins = df[df["phase"] == "in_session"]
    g = ins.groupby(["ticker", "snapshot_day"])
    multi = g["ts"].nunique() > 1
    freeze_varied = (g[FREEZE_COLS].nunique(dropna=False)[multi] > 1).any(axis=1)
    print(f"\nfreeze check: {int(freeze_varied.sum())} of {int(multi.sum())} (ticker, day) groups with >1 "
          f"in-session snapshot vary in {FREEZE_COLS}")

    # ---- 3. which session does the board report
    tickers = sorted(df["ticker"].unique())
    sessions = load_sessions(tickers, first_day, last_day)
    matched = sorted(sessions)
    print(f"\nstore tickers matched ({len(matched)}): {' '.join(matched)}")
    print(f"not in store ({len(tickers) - len(matched)}): {' '.join(t for t in tickers if t not in sessions)}")
    store_days = pd.DatetimeIndex(sorted(set().union(*(s.index for s in sessions.values()))))
    print(f"store sessions: {sum(len(s) for s in sessions.values())} ticker-days over "
          f"{store_days.min().date()} to {store_days.max().date()}")
    print("board days without any store bar:", [d.date().isoformat() for d in snaps_per_day.index if d not in store_days])
    df = classify(df, sessions)
    m = df[df["category"] != "unmatched"]
    print("matched rows by category:", m["category"].value_counts().to_dict())
    print("neither rows by ticker:", m.loc[m["category"] == "neither", "ticker"].value_counts().to_dict())
    print("in-session neither rows by ticker:",
          m.loc[(m["category"] == "neither") & (m["phase"] == "in_session"), "ticker"].value_counts().to_dict())
    bucket = (m["minute_of_day"] // 60 * 60).clip(BUCKET_FIRST_MINUTE, BUCKET_LAST_MINUTE)
    rows = [{"bucket_start": hhmm(start), "bucket_start_minute": start, **category_shares(m[bucket == start])}
            for start in range(BUCKET_FIRST_MINUTE, BUCKET_LAST_MINUTE + 1, 60)]
    write("board_staleness.csv", pd.DataFrame(rows))
    in_sess = category_shares(m[m["phase"] == "in_session"])
    after = category_shares(m[m["phase"] == "after_close"])
    for label, sh in [("in-session", in_sess), ("after-close", after)]:
        print(f"{label} matched rows:", {k: int(v) if k == "n_rows" else round(float(v), ROUND) for k, v in sh.items()},
              f"| inclusive: prev-or-both {sh['pct_prev_close'] + sh['pct_both']:.{ROUND}f}%, "
              f"same-or-both {sh['pct_same_close'] + sh['pct_both']:.{ROUND}f}%")
    per_snap = m.groupby("ts").agg(n=("category", "size"), same=("category", lambda s: (s == "same").sum()),
                                   prev_or_both=("category", lambda s: s.isin(["prev", "both"]).sum()))
    per_snap["minute"] = per_snap.index.hour * 60 + per_snap.index.minute
    per_snap["on_store_day"] = per_snap.index.tz_localize(None).normalize().isin(store_days)
    per_snap["same_major"] = per_snap["same"] > MAJORITY_SHARE * per_snap["n"]
    per_snap["prev_major"] = per_snap["prev_or_both"] > MAJORITY_SHARE * per_snap["n"]
    same_day = pd.Series(per_snap.index[per_snap["same_major"]])
    first_same = same_day.groupby(same_day.dt.tz_localize(None).dt.normalize()).min()
    days = snaps.groupby("snapshot_day")["ts"].agg(n_snapshots_that_day="size", last="max")
    fsd = pd.DataFrame({
        "snapshot_day": days.index.strftime("%Y-%m-%d"),
        "first_same_day_time": [hhmm(t.hour * 60 + t.minute) if pd.notna(t) else ""
                                for t in first_same.reindex(days.index)],
        "n_snapshots_that_day": days["n_snapshots_that_day"].values,
        "last_snapshot_time": days["last"].dt.strftime("%H:%M").values,
    })
    write("board_first_same_day.csv", fsd)
    first_minutes = first_same.dt.hour * 60 + first_same.dt.minute
    median_first = hhmm(first_minutes.median()) if len(first_minutes) else ""
    print(f"days with a same-day payload: {len(first_same)} of {len(days)}; median first same-day snapshot "
          f"{median_first}; earliest {hhmm(first_minutes.min())}, latest {hhmm(first_minutes.max())}")
    on_td = per_snap[per_snap["on_store_day"]]
    latest_prev = on_td.loc[on_td["prev_major"], "minute"].max()
    earliest_same = on_td.loc[on_td["same_major"], "minute"].min()
    late = per_snap[(per_snap["minute"] >= SWITCH_CHECK_MINUTE) & ~per_snap["same_major"]]
    n_late_td = int(late["on_store_day"].sum())
    print(f"on store trading days: latest snapshot with a prev-or-both majority {hhmm(latest_prev)}, earliest with "
          f"a same majority {hhmm(earliest_same)}; snapshots at or after {hhmm(SWITCH_CHECK_MINUTE)} without a same "
          f"majority: {n_late_td} on store trading days, {len(late)} on any day "
          f"({', '.join(t.strftime('%Y-%m-%d %H:%M') for t in late.index)}); latest prev-or-both majority on any "
          f"day {hhmm(per_snap.loc[per_snap['prev_major'], 'minute'].max())}")

    # ---- 4. reported session and collapse
    D = df["snapshot_day"].values.astype("datetime64[D]")
    trading = store_days.values.astype("datetime64[D]")
    after_close = (df["phase"] == "after_close").values
    time_rule = time_rule_sessions(D, after_close, trading)
    cat = df["category"]
    # after the store ends, an after-close row cannot be confirmed by the store, so
    # a coincidental match with an earlier close must not date it backwards
    use_time = ~cat.isin(["prev", "same"]).values | ((D > trading.max()) & after_close)
    rep = np.where(use_time, time_rule, np.where(cat == "prev", df["P"].values.astype("datetime64[D]"), D))
    df["reported_session"] = pd.to_datetime(rep)
    df["assigned_by"] = np.where(use_time, "time", "store")
    beyond = int(((D > trading.max()) & (df["assigned_by"] == "time").values).sum())
    print(f"\ntime rule calendar: {TIME_RULE_CALENDAR} ({len(trading)} trading days {trading.min()} to "
          f"{trading.max()}); rows assigned by store match: {int((df['assigned_by'] == 'store').sum())}, by time "
          f"rule: {int((df['assigned_by'] == 'time').sum())} (of which on days after the store ends: {beyond})")
    keys = ["ticker", "reported_session"]
    g = df.groupby(keys, sort=True)
    collapse_varied = (g[["bid", "ask", "last"]].nunique(dropna=False) > 1).any(axis=1)
    inst = g.tail(1).sort_values(keys).reset_index(drop=True)
    sess_long = pd.concat([s.rename_axis("reported_session").reset_index().assign(ticker=t)
                           for t, s in sessions.items()], ignore_index=True)
    inst = inst.merge(sess_long, on=keys, how="left")
    print(f"instrument-sessions: {len(inst)} (store-matched {int((inst['assigned_by'] == 'store').sum())}, "
          f"time-rule {int((inst['assigned_by'] == 'time').sum())}); collapsed groups where bid, ask or last "
          f"varied across snapshots: {int(collapse_varied.sum())} of {len(collapse_varied)}")
    print("varied groups by reported_session:",
          by_day(collapse_varied[collapse_varied].index.get_level_values("reported_session")))
    prev_payload = inst.groupby("ticker")[FREEZE_COLS].shift(1)
    repeat = ((inst[FREEZE_COLS] == prev_payload) | (inst[FREEZE_COLS].isna() & prev_payload.isna())).all(axis=1)
    off_day = ~inst["reported_session"].isin(store_days)
    print(f"instrument-sessions repeating the ticker's previous one exactly in {FREEZE_COLS}: {int(repeat.sum())}, "
          f"of which keyed to a day without store bars: {int((repeat & off_day).sum())} "
          f"(instrument-sessions keyed to such a day: {int(off_day.sum())})")

    # ---- 5. crossing
    two = inst[(inst["bid"] > 0) & (inst["ask"] > 0)]
    rows = []
    for label, sub in [("a_two_sided", two), ("b_two_sided_deals_gt_0", two[two["deals"] > 0])]:
        equal = eq(sub["bid"], sub["ask"])
        rows.append({"filter": label, "n": len(sub), "pct_crossed": pct((sub["bid"] > sub["ask"]) & ~equal),
                     "pct_equal": pct(equal), "pct_normal": pct((sub["bid"] < sub["ask"]) & ~equal)})
    crossing = pd.DataFrame(rows)
    write("board_crossing.csv", crossing)
    normal = two[(two["bid"] < two["ask"]) & ~eq(two["bid"], two["ask"])]
    print("normal (bid < ask) instrument-sessions by reported_session:", by_day(normal["reported_session"]))

    # ---- 6. liquidity signature
    liq = two[(two["high"] > 0) & (two["low"] > 0) & (two["deals"] > 0)].copy()
    liq["deal_bin"] = pd.cut(liq["deals"], DEAL_BIN_EDGES, labels=DEAL_BIN_LABELS)
    liq["crossed"] = (liq["bid"] > liq["ask"]) & ~eq(liq["bid"], liq["ask"])
    liq["collapsed"] = eq(liq["bid"], liq["high"]) & eq(liq["ask"], liq["low"])
    gb = liq.groupby("deal_bin", observed=False)
    sig = pd.DataFrame({"deal_bin": DEAL_BIN_LABELS, "n": gb.size().values,
                        "pct_crossed": 100 * gb["crossed"].mean().values,
                        "pct_collapsed": 100 * gb["collapsed"].mean().values})
    write("board_liquidity_signature.csv", sig)
    print(f"total n in the signature: {len(liq)}")

    # ---- 7. extreme-quote tests
    def tests(bid, ask, high, low):
        bid, ask, high, low = (np.asarray(x, float) for x in (bid, ask, high, low))
        bid_ge, ask_le = (bid > high) | eq(bid, high), (ask < low) | eq(ask, low)
        rho = spearmanr(bid - ask, high - low)
        return {
            "bid_ge_high": pct(bid_ge), "bid_eq_high": pct(eq(bid, high)), "bid_gt_high": pct(bid_ge & ~eq(bid, high)),
            "ask_le_low": pct(ask_le), "ask_eq_low": pct(eq(ask, low)), "ask_lt_low": pct(ask_le & ~eq(ask, low)),
            "both_contain": pct(bid_ge & ask_le),
            "width_ge_range": pct((bid - ask) - (high - low) >= -ABS_TOL),
            "bid_lt_high": pct(~bid_ge), "ask_gt_low": pct(~ask_le),
            "spearman_width_range": rho.statistic,
        }, rho.pvalue, ~bid_ge | ~ask_le

    aligned = two[two["assigned_by"] == "store"]
    within, p_within, viol_within = tests(liq["bid"], liq["ask"], liq["high"], liq["low"])
    stored, p_store, _ = tests(aligned["bid"], aligned["ask"], aligned["session_high"], aligned["session_low"])
    ext = pd.DataFrame({"test": list(within), "within_payload_pct": list(within.values()),
                        "within_payload_n": len(liq), "store_aligned_pct": list(stored.values()),
                        "store_aligned_n": len(aligned)})
    write("board_extreme_quote_tests.csv", ext)
    print(f"spearman p-values: within payload {p_within:.3g}, store aligned {p_store:.3g}")
    print("within-payload rows violating bid >= high or ask <= low, by assignment:",
          liq.loc[viol_within, "assigned_by"].value_counts().to_dict())
    coll = eq(aligned["bid"], aligned["session_high"]) & eq(aligned["ask"], aligned["session_low"])
    for label, mask in [("deals == 1", aligned["deals"] == 1), ("deals > 1000", aligned["deals"] > 1000)]:
        print(f"store-aligned collapse (bid = session high and ask = session low) among {label}: "
              f"{pct(coll[mask.values]):.{ROUND}f}% of n={int(mask.sum())}")
    for fld, sfld in [("high", "session_high"), ("low", "session_low")]:
        has = aligned[fld].notna().values
        differ = has & ~eq(aligned[fld], aligned[sfld])
        print(f"store-aligned rows where the board's {fld} differs from the store's {sfld}: {int(differ.sum())} of "
              f"{int(has.sum())} (board above store in {int((differ & (aligned[fld] > aligned[sfld]).values).sum())})")

    # ---- 8. residual placement
    rows = []
    for side, quote, extreme, minute, below in [("bid_vs_high", "bid", "session_high", "high_minute", True),
                                                ("ask_vs_low", "ask", "session_low", "low_minute", False)]:
        q, x = aligned[quote].values, aligned[extreme].values
        viol = ((q < x) if below else (q > x)) & ~eq(q, x)
        at_first = (aligned[minute] == aligned["first_bar_minute"]).values
        at_last = (aligned[minute] == aligned["last_bar_minute"]).values
        rows.append({"side": side, "n_violations": int(viol.sum()),
                     "pct_extreme_in_first_bar_violations": pct(at_first[viol]),
                     "pct_extreme_in_first_bar_all": pct(at_first),
                     "pct_extreme_in_last_bar_violations": pct(at_last[viol]),
                     "pct_extreme_in_last_bar_all": pct(at_last)})
    write("board_residual_placement.csv", pd.DataFrame(rows))
    print(f"store-aligned instrument-sessions in the base rate: {len(aligned)}")

    # ---- 9. widths
    w = two[two["last"] > 0].copy()
    w["width_pct_of_mid"] = (w["bid"] - w["ask"]) / ((w["bid"] + w["ask"]) / 2) * 100
    w["width_bp_of_last"] = (w["bid"] - w["ask"]) / w["last"] * 1e4
    widths = w.groupby("ticker").agg(n=("bid", "size"), median_width_pct_of_mid=("width_pct_of_mid", "median"),
                                     median_width_bp_of_last=("width_bp_of_last", "median")).reset_index()
    widths.insert(3, "median_half_width_pct", widths["median_width_pct_of_mid"] / 2)
    write("board_widths.csv", widths)
    wt = widths.set_index("ticker")
    six = wt.loc[SIX_TICKERS, "median_half_width_pct"]
    print(f"median_half_width_pct over {SIX_TICKERS}: min {six.min():.{ROUND}f} ({six.idxmin()}), "
          f"max {six.max():.{ROUND}f} ({six.idxmax()})")

    # ---- 10. uncrossed snapshots
    raw_two = df[(df["bid"] > 0) & (df["ask"] > 0) & (df["last"] > 0)].copy()
    raw_two["width_pct_of_last"] = (raw_two["ask"] - raw_two["bid"]) / raw_two["last"] * 100
    raw_two["straddles_last"] = (raw_two["bid"] <= raw_two["last"]) & (raw_two["last"] <= raw_two["ask"])
    per = raw_two.groupby("ts").agg(n_two_sided=("bid", "size"),
                                    median_width_pct_of_last=("width_pct_of_last", "median"),
                                    pct_straddling_last=("straddles_last", "mean"))
    per["pct_straddling_last"] *= 100
    per["pct_normal"] = 100 * (raw_two["bid"] < raw_two["ask"]).groupby(raw_two["ts"]).mean()
    unc = per[per["pct_normal"] >= 100 * UNCROSSED_SHARE].reset_index()
    unc["timestamp"] = [t.isoformat() for t in unc["ts"]]
    write("board_uncrossed_snapshots.csv",
          unc[["timestamp", "n_two_sided", "pct_normal", "median_width_pct_of_last", "pct_straddling_last"]])
    order = sorted(df["ts"].unique())
    kspi = df[df["ticker"] == "KSPI"].set_index("ts")
    cols = ["bid", "ask", "open", "high", "low", "last", "deals"]
    for t in unc["ts"]:
        i = order.index(t)
        print(f"KSPI around the uncrossed snapshot {t} (previous, this, next snapshot):")
        ctx = kspi.reindex([order[j] for j in (i - 1, i, i + 1) if 0 <= j < len(order)])[cols]
        print(ctx.rename_axis("timestamp").reset_index().to_string(index=False))

    # ---- 11. probe
    path = probe()
    if path is None:
        print("\nprobe file not present: probe_summary.csv skipped")
    else:
        p = pd.read_csv(path)
        p["t"] = pd.to_datetime(p["time"], utc=True).dt.tz_convert(TZ)
        rows = []
        for code, grp in p.sort_values("t").groupby("code"):
            r = {"code": code, "polls": len(grp), "first_time": grp["t"].iloc[0].strftime("%H:%M:%S"),
                 "last_time": grp["t"].iloc[-1].strftime("%H:%M:%S"),
                 "median_spacing_s": grp["t"].diff().dt.total_seconds().median()}
            r.update({f"distinct_{f}": grp[f].nunique(dropna=False) for f in PROBE_FIELDS})
            r["last_deal_date"] = grp["last_deal_date"].iloc[0] if r["distinct_last_deal_date"] == 1 else ""
            rows.append(r)
        write("probe_summary.csv", pd.DataFrame(rows))
        print(f"probe date: {p['t'].dt.date.min()} (Almaty)")

    # ---- 12. summary
    summary = [
        ("n_rows", len(df)), ("n_snapshots", len(snaps)), ("n_days", snaps_per_day.size),
        ("first_day", first_day.date().isoformat()), ("last_day", last_day.date().isoformat()),
        ("n_tickers", df["ticker"].nunique()), ("n_tickers_matched_to_store", len(matched)),
        ("rows_per_snapshot_median", rows_per_snap.median()), ("snapshots_per_day_median", snaps_per_day.median()),
        ("n_fx_usdkzt_nonnull", nonnull["fx_usdkzt"]),
        ("in_session_matched_rows", in_sess["n_rows"]),
        ("pct_in_session_prev_close", in_sess["pct_prev_close"]), ("pct_in_session_same_close", in_sess["pct_same_close"]),
        ("pct_in_session_both_close", in_sess["pct_both"]),
        ("after_close_matched_rows", after["n_rows"]),
        ("pct_after_close_prev_close", after["pct_prev_close"]), ("pct_after_close_same_close", after["pct_same_close"]),
        ("pct_after_close_both_close", after["pct_both"]),
        ("days_with_same_day_payload", len(first_same)), ("median_first_same_day_payload", median_first),
        ("frozen_groups_total", int(multi.sum())), ("frozen_groups_with_variation", int(freeze_varied.sum())),
        ("instrument_sessions", len(inst)), ("instrument_sessions_store_matched", int((inst["assigned_by"] == "store").sum())),
        ("instrument_sessions_two_sided", int(crossing.loc[0, "n"])),
        ("pct_crossed", crossing.loc[0, "pct_crossed"]), ("pct_equal", crossing.loc[0, "pct_equal"]),
        ("pct_normal", crossing.loc[0, "pct_normal"]),
        ("kspi_median_width_bp_of_last", wt.loc["KSPI", "median_width_bp_of_last"]),
        ("n_uncrossed_snapshots", len(unc)),
        ("pct_in_session_prev_or_both", in_sess["pct_prev_close"] + in_sess["pct_both"]),
        ("pct_in_session_same_or_both", in_sess["pct_same_close"] + in_sess["pct_both"]),
        ("pct_after_close_prev_or_both", after["pct_prev_close"] + after["pct_both"]),
        ("pct_after_close_same_or_both", after["pct_same_close"] + after["pct_both"]),
        ("latest_prev_session_snapshot", hhmm(latest_prev)), ("earliest_same_day_snapshot", hhmm(earliest_same)),
        ("n_snapshots_1740_or_later_not_same", n_late_td),
        ("n_snapshots_1740_or_later_not_same_any_day", len(late)),
    ]
    for start, end in CADENCE_PERIODS:
        sel = snaps_per_day[(snaps_per_day.index >= pd.Timestamp(start)) & (snaps_per_day.index <= pd.Timestamp(end))]
        summary += [(f"days_with_snapshots_{start}_{end}", len(sel)),
                    (f"snapshots_per_day_min_{start}_{end}", sel.min()),
                    (f"snapshots_per_day_median_{start}_{end}", sel.median()),
                    (f"snapshots_per_day_max_{start}_{end}", sel.max())]
    summary += [(f"{t.lower()}_median_half_width_pct", wt.loc[t, "median_half_width_pct"]) for t in SIX_TICKERS]
    cell = ext.set_index("test")
    summary += [("store_aligned_bid_gt_high_pct", cell.loc["bid_gt_high", "store_aligned_pct"]),
                ("store_aligned_bid_lt_high_pct", cell.loc["bid_lt_high", "store_aligned_pct"]),
                ("store_aligned_ask_gt_low_pct", cell.loc["ask_gt_low", "store_aligned_pct"]),
                ("within_payload_bid_lt_high_pct", cell.loc["bid_lt_high", "within_payload_pct"]),
                ("within_payload_ask_gt_low_pct", cell.loc["ask_gt_low", "within_payload_pct"])]
    summary = pd.DataFrame(summary, columns=["key", "value"])
    summary["value"] = [round(v, ROUND) if isinstance(v, float) else v for v in summary["value"]]
    write("board_summary.csv", summary)


if __name__ == "__main__":
    main()
