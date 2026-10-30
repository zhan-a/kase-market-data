"""
Live probe of the chart-data endpoint, behind three statements in the write-up.

Sections 2.6, 3.4 and 5 of docs/dataset-and-provenance.md say what the endpoint
returns for windows the store holds as empty, and whether a request size limit
exists. Those are properties of a third-party service on the day they are
tested, so this script prints dated observations and writes no table; a reader
can re-run it and compare. It does not read or write the store.

It uses the fetcher's own request function (src/kase/tradernet_fetch.py) and
prints:

1. for HSBK.KZ, the number of points returned at timeframe 1 (minute) and 1440
   (daily) for one week inside the collection hole (HOLE_WEEK) and for a control
   week just before it (CONTROL_WEEK);
2. for HSBK.KZ, the number of minute points returned for each month the
   committed store holds as a zero-row partition although the daily series
   shows trading (CONTRADICTED_MONTHS);
3. for HSBK.KZ, the number of minute points returned for windows of growing
   length in 2024 (LIMIT_WINDOWS), to show whether a point limit truncates or
   empties a reply;
4. for each weekday on which no KASE instrument has a minute bar and which no
   holiday or announced closure explains (NO_BAR_DATES), and each instrument in
   NO_BAR_TICKERS, the minute and daily points returned for a request of that
   day alone, and the same for the NASDAQ session the store lacks
   (NASDAQ_LINE on NASDAQ_DATE).

The endpoint returns one leading reference bar from before the window
(Section 3.6), so a reply of one point means no bar inside the window. Item 4
also counts the points dated on the requested day itself, in the venue's wall
clock: xSeries values are wall clock in a fixed UTC+3 frame (Section 3.1), so a
point's venue-local date is the UTC date of the value plus three hours. Network
access is required; the script paces requests like the fetcher.
"""

import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "kase"))
from tradernet_fetch import PACING_SECONDS, api_hloc  # noqa: E402

TICKER = "HSBK.KZ"
HOLE_WEEK = (date(2015, 7, 6), date(2015, 7, 10))
CONTROL_WEEK = (date(2015, 6, 15), date(2015, 6, 19))
CONTRADICTED_MONTHS = [(2020, 8), (2020, 10), (2021, 2), (2021, 3), (2021, 4)]
LIMIT_WINDOWS = [(date(2024, 1, 1), date(2024, 1, 31)), (date(2024, 1, 1), date(2024, 3, 31)),
                 (date(2024, 1, 1), date(2024, 6, 30)), (date(2024, 1, 1), date(2024, 12, 31))]
NO_BAR_DATES = [date(2024, 12, 12), date(2025, 4, 28), date(2025, 4, 29)]
NO_BAR_TICKERS = ["KSPI.KZ", "HSBK.KZ", "USDKZT_TOM.KZ"]
NASDAQ_LINE, NASDAQ_DATE = "KSPI.US", date(2025, 4, 28)
RAW_TO_LOCAL_SECONDS = 3 * 3600   # xSeries frame, as in the fetchers


def reply(ticker, d1, d2, timeframe):
    """xSeries values of the reply for [d1, d2]; date_to is exclusive at the endpoint."""
    data = api_hloc(ticker, d1, d2 + timedelta(days=1), timeframe=timeframe)
    time.sleep(PACING_SECONDS)
    return (data.get("xSeries") or {}).get(ticker) or []


def points(ticker, d1, d2, timeframe):
    """Number of points in the reply for [d1, d2], the leading reference bar included."""
    return len(reply(ticker, d1, d2, timeframe))


def points_on_day(ticker, day, timeframe):
    """For `day` alone: points in the reply, points dated on `day` in venue wall clock,
    and the other venue-local dates the reply carries."""
    xs = reply(ticker, day, day, timeframe)
    local = [datetime.fromtimestamp(x + RAW_TO_LOCAL_SECONDS, tz=timezone.utc).date() for x in xs]
    others = ", ".join(d.isoformat() for d in sorted(set(local) - {day})) or "none"
    return len(xs), sum(d == day for d in local), others


def print_day(ticker, day):
    m_all, m_day, m_other = points_on_day(ticker, day, 1)
    d_all, d_day, d_other = points_on_day(ticker, day, 1440)
    print(f"  no-bar weekday {day} {ticker:14} minute: {m_all} points, {m_day} on the day "
          f"(other dates: {m_other}); daily: {d_all} points, {d_day} on the day (other dates: {d_other})")


def main():
    print(f"probe of {date.today().isoformat()}, {TICKER}")
    for label, (d1, d2) in [("hole week", HOLE_WEEK), ("control week", CONTROL_WEEK)]:
        minute, daily = points(TICKER, d1, d2, 1), points(TICKER, d1, d2, 1440)
        print(f"  {label} {d1}..{d2}: {minute} minute points, {daily} daily points")
    for year, month in CONTRADICTED_MONTHS:
        d1 = date(year, month, 1)
        d2 = date(year + (month == 12), month % 12 + 1, 1).fromordinal(
            date(year + (month == 12), month % 12 + 1, 1).toordinal() - 1)
        print(f"  zero-row month {year}-{month:02d}: {points(TICKER, d1, d2, 1)} minute points")
    for d1, d2 in LIMIT_WINDOWS:
        print(f"  window {d1}..{d2}: {points(TICKER, d1, d2, 1)} minute points")
    for day in NO_BAR_DATES:
        for ticker in NO_BAR_TICKERS:
            print_day(ticker, day)
    print_day(NASDAQ_LINE, NASDAQ_DATE)


if __name__ == "__main__":
    main()
