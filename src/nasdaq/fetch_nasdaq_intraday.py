#!/usr/bin/env python3
"""
Fetch KSPI 1-minute NASDAQ bars *including pre- and post-market* from Tradernet.

The transmission study regresses KASE returns on the prior NASDAQ daily close.
But KASE opens ~10.5h after the 16:00 ET close, and KSPI trades in extended
hours, so the information set at the KASE open is the last extended-hours
print, not the official close. That hypothesis needs extended-hours prices to
test, and Yahoo only serves 1-minute data for ~30 days.

Tradernet's `getHloc` endpoint serves `KSPI.US` back to the 2024
listing, extended hours included. Same quirks as the KASE fetcher
(`src/kase/tradernet_fetch.py`), with one difference that matters:

  * `xSeries` timestamps are unix ints that, read in a UTC+3 frame, give the
    venue's *local wall clock*. For .KZ lines that is Almaty; for .US lines it
    is New York. Localising a US line to Almaty would shift every bar.
  * `hloc` rows are ordered [high, low, open, close], not OHLC.
  * `date_to` is exclusive.
  * windows over ~20k points return an empty payload, not a truncated one.

Writes monthly Parquet partitions to data/nasdaq/intraday/KSPI.US/, or under
the directory named by KASE_STORE when that is set.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent.parent
STORE_ROOT = Path(os.environ["KASE_STORE"]) if os.environ.get("KASE_STORE") else REPO / "data"
OUT = STORE_ROOT / "nasdaq" / "intraday" / "KSPI.US"

API = "https://tradernet.com/api/"
UA = {"User-Agent": "Mozilla/5.0"}
RAW_TO_LOCAL = timedelta(hours=3)
TZ = "America/New_York"
COLUMNS = ["ts_utc", "ts_ny", "open", "high", "low", "close", "volume"]
MAX_RETRIES = 4
PACING = 1.0


class FetchError(RuntimeError):
    pass


def _request(ticker: str, d1: date, d2_exclusive: date) -> dict:
    params = {
        "id": ticker, "count": -1, "timeframe": 1,
        "date_from": d1.strftime("%d.%m.%Y"),
        "date_to": d2_exclusive.strftime("%d.%m.%Y"),
        "intervalMode": "OpenRay",
    }
    q = json.dumps({"cmd": "getHloc", "params": params})
    url = API + "?" + urllib.parse.urlencode({"q": q})
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < MAX_RETRIES:
                time.sleep(PACING * 2 * attempt)
    raise FetchError(f"{ticker} {d1}..{d2_exclusive}: {last}")


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in COLUMNS})


def fetch_bars(ticker: str, d1: date, d2_inclusive: date) -> pd.DataFrame:
    data = _request(ticker, d1, d2_inclusive + timedelta(days=1))
    hloc = (data.get("hloc") or {}).get(ticker)
    xs = (data.get("xSeries") or {}).get(ticker)
    vl = (data.get("vl") or {}).get(ticker)
    if not hloc or not xs:
        return empty_frame()
    if vl is None:
        vl = [None] * len(xs)
    if not (len(hloc) == len(xs) == len(vl)):
        raise FetchError(f"{ticker} {d1}: array length mismatch "
                         f"hloc={len(hloc)} xs={len(xs)} vl={len(vl)}")

    naive = pd.to_datetime([x + int(RAW_TO_LOCAL.total_seconds()) for x in xs], unit="s")
    ny = naive.tz_localize(TZ, ambiguous=True, nonexistent="shift_forward")
    frame = pd.DataFrame({
        "ts_utc": ny.tz_convert("UTC"),
        "ts_ny": ny,
        "open": [b[2] for b in hloc],
        "high": [b[0] for b in hloc],
        "low": [b[1] for b in hloc],
        "close": [b[3] for b in hloc],
        "volume": vl,
    })
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").astype("float64")
    return frame[COLUMNS].sort_values("ts_utc").reset_index(drop=True)


def month_windows(start: date, end: date):
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        first = date(y, m, 1)
        last = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
        yield y, m, max(first, start), min(last, end)
        y, m = y + (m == 12), (m % 12) + 1


def main() -> int:
    start = date(2024, 1, 1)
    end = date.today()
    OUT.mkdir(parents=True, exist_ok=True)
    refetch = "--refetch" in sys.argv

    total = 0
    for y, m, d1, d2 in month_windows(start, end):
        path = OUT / f"{y:04d}-{m:02d}.parquet"
        if path.exists() and not refetch:
            n = len(pd.read_parquet(path))
            total += n
            print(f"  {y}-{m:02d}  cached  {n:>6,} bars", flush=True)
            continue
        # Split the month in half: a full month of 1-min extended-hours bars can
        # approach the ~20k-point cliff, and that cliff returns empty, not short.
        mid = d1 + (d2 - d1) // 2
        parts = []
        for a, b in [(d1, mid), (mid + timedelta(days=1), d2)]:
            if a > b:
                continue
            parts.append(fetch_bars("KSPI.US", a, b))
            time.sleep(PACING)
        frame = pd.concat(parts, ignore_index=True) if parts else empty_frame()
        frame = frame.drop_duplicates(subset=["ts_utc"]).sort_values("ts_utc").reset_index(drop=True)
        frame.to_parquet(path, index=False)
        total += len(frame)
        print(f"  {y}-{m:02d}  fetched {len(frame):>6,} bars", flush=True)

    print(f"\nTotal {total:,} bars -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
