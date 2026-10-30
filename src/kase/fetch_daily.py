#!/usr/bin/env python3
"""
Fetch KASE daily bars as a companion to the 1-minute store.

The minute feed has holes the endpoint reports as empty payloads, which the
fetcher records as "checked and empty" and which are indistinguishable from
genuine non-trading. The same endpoint queried at timeframe=1440 answers for
windows where timeframe=1 returns nothing: for 2015-07 to 2015-12, HSBK returns
1 minute bar against 125 daily bars, KZTO 1 against 127, KEGC 1 against 122.

This pulls the daily series for every instrument in the manifest so that
(a) minute-store holes can be classified as collection failures rather than
closures, and (b) analyses that need only daily resolution are not silently
truncated by them.

Writes one Parquet per ticker to data/kase/daily/<TICKER>.parquet with the same
timestamp convention as the minute store. KASE_STORE, when set, names the
directory holding kase/intraday (for the manifest), and KASE_DAILY the output
directory; the companion repositories read both through the same variables.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STORE_ROOT = Path(os.environ["KASE_STORE"]) if os.environ.get("KASE_STORE") else ROOT / "data"
MANIFEST = STORE_ROOT / "kase" / "intraday" / "manifest.csv"
OUT = Path(os.environ["KASE_DAILY"]) if os.environ.get("KASE_DAILY") else ROOT / "data" / "kase" / "daily"

API = "https://tradernet.com/api/"
UA = {"User-Agent": "Mozilla/5.0"}
RAW_TO_LOCAL = timedelta(hours=3)
TZ = "Asia/Almaty"
COLUMNS = ["ts_almaty", "date", "open", "high", "low", "close", "volume"]
MAX_RETRIES, PACING = 4, 1.0


def request(ticker: str, d1: date, d2_exclusive: date) -> dict:
    params = {
        "id": ticker, "count": -1, "timeframe": 1440,
        "date_from": d1.strftime("%d.%m.%Y"),
        "date_to": d2_exclusive.strftime("%d.%m.%Y"),
        "intervalMode": "OpenRay",
    }
    url = API + "?" + urllib.parse.urlencode({"q": json.dumps({"cmd": "getHloc", "params": params})})
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < MAX_RETRIES:
                time.sleep(PACING * 2 * attempt)
    raise RuntimeError(f"{ticker} {d1}..{d2_exclusive}: {last}")


def fetch(ticker: str, d1: date, d2: date) -> pd.DataFrame:
    """Daily bars, inclusive of d2. `date_to` is exclusive at the endpoint."""
    data = request(ticker, d1, d2 + timedelta(days=1))
    hloc = (data.get("hloc") or {}).get(ticker)
    xs = (data.get("xSeries") or {}).get(ticker)
    vl = (data.get("vl") or {}).get(ticker)
    if not hloc or not xs:
        return pd.DataFrame(columns=COLUMNS)
    if vl is None:
        vl = [None] * len(xs)
    if not (len(hloc) == len(xs) == len(vl)):
        raise RuntimeError(f"{ticker}: array length mismatch {len(hloc)}/{len(xs)}/{len(vl)}")

    naive = pd.to_datetime([x + int(RAW_TO_LOCAL.total_seconds()) for x in xs], unit="s")
    local = naive.tz_localize(TZ, ambiguous=True, nonexistent="shift_forward")
    frame = pd.DataFrame({
        "ts_almaty": local,
        "date": local.tz_localize(None).normalize(),
        # hloc rows are [high, low, open, close], not OHLC
        "open": [b[2] for b in hloc], "high": [b[0] for b in hloc],
        "low": [b[1] for b in hloc], "close": [b[3] for b in hloc],
        "volume": vl,
    })
    for c in ["open", "high", "low", "close", "volume"]:
        frame[c] = pd.to_numeric(frame[c], errors="coerce").astype("float64")
    return frame[COLUMNS].drop_duplicates("date").sort_values("date").reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--ticker", action="append", help="repeatable; default is the whole manifest")
    args = ap.parse_args()

    d1, d2 = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if args.ticker:
        tickers = args.ticker
    elif MANIFEST.exists():
        tickers = pd.read_csv(MANIFEST)["ticker"].tolist()
    else:
        sys.exit(
            f"No ticker list. {MANIFEST} is written by tradernet_fetch.py --discover "
            "and is not committed. Either run --discover first, or pass --ticker "
            "explicitly (repeatable)."
        )
    OUT.mkdir(parents=True, exist_ok=True)

    total = 0
    for t in tickers:
        try:
            # Split into year windows: a decade of daily bars is well inside the
            # point cap, but a single window that trips it returns empty, not short.
            parts = []
            y1, y2 = d1.year, d2.year
            for y in range(y1, y2 + 1):
                a = max(d1, date(y, 1, 1))
                b = min(d2, date(y, 12, 31))
                if a > b:
                    continue
                parts.append(fetch(t, a, b))
                time.sleep(PACING)
            frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)
            frame = frame.drop_duplicates("date").sort_values("date").reset_index(drop=True)
            frame.to_parquet(OUT / f"{t}.parquet", index=False)
            total += len(frame)
            span = f"{frame['date'].min():%Y-%m-%d}..{frame['date'].max():%Y-%m-%d}" if len(frame) else "empty"
            print(f"  {t:16s} {len(frame):>6,} daily bars  {span}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {t:16s} FAILED: {e}", flush=True)

    print(f"\nTotal {total:,} daily bars -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
