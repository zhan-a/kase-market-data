"""
Large overnight drops in unadjusted KASE 1-minute prices, marked against the dividend
dates Yahoo Finance publishes for the depositary line of the same company.

Window and instruments: sessions from WINDOW_START to WINDOW_END inclusive (Almaty
calendar days). An instrument is every directory under kase/intraday whose name ends in
".KZ", except on-exchange FX lines (name contains FX_MARKER "_TOM") and the three USD
depositary lines named in DEPOSITARY_LINES (a suffix rule would also drop KMGD.KZ, a
tenge equity), with at least MIN_SESSIONS sessions in the window. Entries that are not directories of .parquet files (a stray symlink, loose files)
and directories whose partitions hold no rows are ignored. Used and skipped are printed.

Session rules: bars of all partitions are concatenated, exact duplicate rows dropped,
sorted by ts_utc. A session is an Almaty calendar day (ts_almaty) with at least one bar.
first_print = open of the session's first bar; close = close of its last bar; prev_close
= close of the last bar of the instrument's previous session, i.e. its most recent earlier
session anywhere in the store, also when that lies before the window or several calendar
days back (weekends, holidays, illiquid lines). The first session ever has no prev_close
and cannot be a drop, but counts as a session. overnight_pct = (first_print / prev_close
- 1) * 100; close_to_close_pct = (close / prev_close - 1) * 100. A drop is a window
session with overnight_pct <= DROP_THRESHOLD_PCT.

Dividend dates are fetched AT RUN TIME with yfinance, Ticker(symbol).dividends, for
DIVIDEND_SYMBOLS (AIRA.IL -> AIRA.KZ, HSBK.IL -> HSBK.KZ, KAP.IL -> KZAP.KZ, KSPI ->
KSPI.KZ). The date is the calendar date of the series index as Yahoo reports it (exchange
local time); the amount is as served (per depositary unit, in that line's currency). The
whole series is written, not only the window. A fetch that fails or returns an empty
series stops the script before anything is written. For a mapped instrument,
on_yahoo_dividend_date is True when the session date equals a dividend date (exact match
only), and days_to_nearest_yahoo_dividend is drop date minus nearest dividend date in
calendar days (-1: the drop fell one day before it; a tie between an earlier and a later
date resolves to the later one, the negative value). Both are empty when unmapped.
Written rounding: percentages and prices to 4 decimals (KASE quotes at most 2 decimals;
the store holds prices with float noise such as 5.8500000000000005); amounts as served.

Files written (DERIVED = data/derived), all with to_csv(index=False):
  dividend_dates.csv: kase_ticker, yahoo_symbol, date, amount, source; sorted by kase_ticker, date.
  overnight_drops.csv: one row per drop, sorted by instrument then date.
  overnight_drops_summary.csv: one row per instrument, sorted by instrument; drops_on_dividend_date
    (exact) and drops_within_3_days_of_dividend_date (|days| <= NEAR_DAYS) are empty when
    unmapped; largest_drop_pct / largest_drop_date is the most negative overnight_pct of any
    window session, also when above the threshold.
Also printed: the mapped instruments' drop rows; KSPI.KZ on EVENT_KASE; the KSPI.US
regular-session close-to-close move on EVENT_NASDAQ against the previous store day, with
regular close = last bar with ts_ny from 09:30 to 16:00 inclusive (the 16:00 bar is the
closing auction), the definition used by nasdaq_reconciliation.py.
"""

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _store import DERIVED, store  # noqa: E402

WINDOW_START, WINDOW_END = dt.date(2024, 1, 19), dt.date(2026, 8, 24)  # both inclusive
MIN_SESSIONS = 200
DROP_THRESHOLD_PCT = -4.0
NEAR_DAYS = 3
FX_MARKER = "_TOM"
DEPOSITARY_LINES = {"HSBKD.KZ", "KSPID.KZ", "KZAPD.KZ"}
DIVIDEND_SYMBOLS = {"AIRA.KZ": "AIRA.IL", "HSBK.KZ": "HSBK.IL", "KZAP.KZ": "KAP.IL", "KSPI.KZ": "KSPI"}
EVENT_KASE, EVENT_NASDAQ = ("KSPI.KZ", dt.date(2024, 9, 20)), ("KSPI.US", dt.date(2024, 9, 19))
REGULAR_START_MIN, REGULAR_LAST_MIN = 9 * 60 + 30, 16 * 60  # New York 09:30 and 16:00, both inclusive
OUT_DIVIDENDS = DERIVED / "dividend_dates.csv"
OUT_DROPS = DERIVED / "overnight_drops.csv"
OUT_SUMMARY = DERIVED / "overnight_drops_summary.csv"


def read_line(folder):  # all bars of one instrument, deduplicated and sorted; None if none
    frames = [f for f in (pd.read_parquet(p) for p in sorted(folder.glob("*.parquet"))) if len(f)]
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True).drop_duplicates().sort_values("ts_utc", kind="stable")


def sessions(bars, ts_col):  # one row per calendar day of ts_col, indexed by that date
    s = bars.groupby(bars[ts_col].dt.date).agg(first_print=("open", "first"), close=("close", "last"))
    s["prev_close"] = s["close"].shift(1)
    s["overnight_pct"] = (s["first_print"] / s["prev_close"] - 1) * 100
    s["close_to_close_pct"] = (s["close"] / s["prev_close"] - 1) * 100
    return s


def kase_lines(root):  # {instrument: window sessions} for every instrument passing the rules
    out = {}
    for entry in sorted((root / "kase" / "intraday").iterdir()):
        name = entry.name
        if entry.is_symlink() or not entry.is_dir() or not name.endswith(".KZ"):
            continue
        if FX_MARKER in name or name in DEPOSITARY_LINES:
            print(f"  excluded by name: {name}")
            continue
        bars = read_line(entry)
        s = sessions(bars, "ts_almaty") if bars is not None else pd.DataFrame()
        w = s[(s.index >= WINDOW_START) & (s.index <= WINDOW_END)] if len(s) else s
        if len(w) < MIN_SESSIONS:
            print(f"  skipped ({len(w)} sessions in window < {MIN_SESSIONS}): {name}")
            continue
        out[name] = w
    return out


def fetch_dividends(today):
    rows, dates = [], {}
    for kase_ticker, symbol in DIVIDEND_SYMBOLS.items():
        try:
            series = yf.Ticker(symbol).dividends
        except Exception as exc:  # network, rate limit, parsing
            raise SystemExit(f"Yahoo dividends fetch for {symbol} failed: {exc!r}. Nothing written.")
        if series is None or len(series) == 0:
            raise SystemExit(f"Yahoo returned no dividends for {symbol}. Nothing written.")
        days = [ts.date() for ts in series.index]
        dates[kase_ticker] = set(days)
        rows += [(kase_ticker, symbol, d, float(a), f"yfinance dividends, fetched {today}")
                 for d, a in zip(days, series.to_numpy())]
    table = pd.DataFrame(rows, columns=["kase_ticker", "yahoo_symbol", "date", "amount", "source"])
    return table.sort_values(["kase_ticker", "date"]).reset_index(drop=True), dates


def nearest_days(day, dates):  # drop date minus the nearest dividend date; a tie -> the later date
    return min(((day - d).days for d in dates), key=lambda n: (abs(n), n))


def print_events(lines, root):
    print("\nEvents:")
    name, day = EVENT_KASE
    w = lines.get(name, pd.DataFrame())
    if day not in w.index:
        print(f"{name} {day}: absent from the store or from the instrument list")
    else:
        r = w.loc[day]
        print(f"{name} {day}: overnight_pct {r['overnight_pct']:+.4f}, close_to_close_pct "
              f"{r['close_to_close_pct']:+.4f} (prev_close {r['prev_close']}, first_print "
              f"{r['first_print']}, close {r['close']})")
    us_name, us_day = EVENT_NASDAQ
    bars = read_line(root / "nasdaq" / "intraday" / us_name)
    minute = bars["ts_ny"].dt.hour * 60 + bars["ts_ny"].dt.minute if bars is not None else None
    reg = bars[(minute >= REGULAR_START_MIN) & (minute <= REGULAR_LAST_MIN)] if bars is not None else None
    rc = reg.groupby(reg["ts_ny"].dt.date)["close"].last() if reg is not None else pd.Series(dtype=float)
    if us_day not in rc.index or rc.index.get_loc(us_day) == 0:
        print(f"{us_name} {us_day}: absent from the store (no regular close, or no earlier one)")
        return
    pos = rc.index.get_loc(us_day)
    print(f"{us_name} {us_day}: regular close {rc.loc[us_day]} vs {rc.index[pos - 1]} regular close "
          f"{rc.iloc[pos - 1]}: close_to_close_pct {(rc.loc[us_day] / rc.iloc[pos - 1] - 1) * 100:+.4f}")


def main():
    root = store()
    dividends, div_dates = fetch_dividends(dt.date.today().isoformat())
    print(f"Window {WINDOW_START}..{WINDOW_END}; scanning {root / 'kase' / 'intraday'}")
    lines = kase_lines(root)
    print(f"Instruments used ({len(lines)}): " + ", ".join(lines))

    drop_rows, summary_rows = [], []
    for name, w in lines.items():
        drops = w[w["overnight_pct"] <= DROP_THRESHOLD_PCT]
        mapped, dates = name in div_dates, div_dates.get(name, ())
        near = {day: nearest_days(day, dates) for day in drops.index} if mapped else {}
        for day, r in drops.iterrows():
            drop_rows.append({
                "instrument": name, "date": day, "prev_close": round(r["prev_close"], 4),
                "first_print": round(r["first_print"], 4), "close": round(r["close"], 4),
                "overnight_pct": round(r["overnight_pct"], 4),
                "close_to_close_pct": round(r["close_to_close_pct"], 4),
                "on_yahoo_dividend_date": (day in dates) if mapped else "",
                "days_to_nearest_yahoo_dividend": near.get(day, "")})
        valid = w["overnight_pct"].dropna()
        summary_rows.append({
            "instrument": name, "sessions_in_window": len(w), "drops_below_4pct": len(drops),
            "drops_on_dividend_date": sum(d in dates for d in drops.index) if mapped else "",
            "drops_within_3_days_of_dividend_date":
                sum(abs(n) <= NEAR_DAYS for n in near.values()) if mapped else "",
            "largest_drop_pct": round(valid.min(), 4) if len(valid) else "",
            "largest_drop_date": valid.idxmin() if len(valid) else ""})

    cols = ["instrument", "date", "prev_close", "first_print", "close", "overnight_pct",
            "close_to_close_pct", "on_yahoo_dividend_date", "days_to_nearest_yahoo_dividend"]
    drops_table = pd.DataFrame(drop_rows, columns=cols).sort_values(["instrument", "date"])
    summary = pd.DataFrame(summary_rows).sort_values("instrument").reset_index(drop=True)

    DERIVED.mkdir(parents=True, exist_ok=True)
    for title, table, path in [("Dividend dates", dividends, OUT_DIVIDENDS),
                               (f"Overnight drops <= {DROP_THRESHOLD_PCT}%", drops_table, OUT_DROPS),
                               ("Summary", summary, OUT_SUMMARY)]:
        table.to_csv(path, index=False)
        print(f"\n{title} ({path}, {len(table)} rows):")
        print(table.to_string(index=False))
    mapped_rows = drops_table[drops_table["instrument"].isin(DIVIDEND_SYMBOLS)]
    print(f"\nDrops of the mapped instruments ({len(mapped_rows)} rows):")
    print(mapped_rows.to_string(index=False))
    print_events(lines, root)


if __name__ == "__main__":
    main()
