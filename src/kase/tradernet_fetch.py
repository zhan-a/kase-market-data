#!/usr/bin/env python3
"""
Fetch KASE 1-minute history from Tradernet into partitioned Parquet.

Tradernet (Freedom Finance's platform) serves 1-minute OHLC and volume bars
for KASE instruments through a public chart-data endpoint, with history far
deeper than anything that can be recorded live. This is the primary source for
KASE intraday data in this project.

Layout, under data/ in this repository or under the directory named by the
KASE_STORE environment variable:

    kase/intraday/manifest.csv                  per-ticker market and first date
    kase/intraday/<TICKER>/_coverage.json       what has been fetched, through when
    kase/intraday/<TICKER>/<YYYY-MM>.parquet

A month with no trading is stored as a zero-row partition so it is recorded as
"checked and empty" rather than re-probed on every future run.

API quirks, all learned the hard way. Change these at your peril:

  * Request dates are DD.MM.YYYY, but info.firstDate comes back MM.DD.YYYY.
  * `date_to` is EXCLUSIVE: to get through the 31st you must ask for the 1st
    of the next month.
  * During the 2026-08 backfill, large requests (tens of thousands of points)
    returned an EMPTY payload rather than a truncated one, which is why fetching
    is chunked by month. analysis/probe_endpoint.py re-tests this; the limit is
    not fixed, and a fetcher cannot rely on its absence.
  * A request also returns one leading reference bar from BEFORE the window
    (an artifact of intervalMode=OpenRay), so partitions filter by month.
  * hloc rows are ordered [high, low, open, close], not OHLC.
  * info.firstDate is when the instrument began trading, NOT when minute bars
    begin. KSPI claims 2018 but its minute data starts mid-2021.

Timestamps: xSeries values are Almaty LOCAL wall-clock rendered in a fixed
UTC+3 frame. They are converted as local time, not by a constant UTC offset,
because Kazakhstan moved Almaty from UTC+6 to UTC+5 on 2024-03-01, a constant
offset silently shifts everything before that date by an hour:

    local_naive = raw + 3h   ->   localize to Asia/Almaty   ->   convert to UTC

The same frame holds for the `.US` lines, but there the wall clock is New York's,
so they are fetched by src/nasdaq/fetch_nasdaq_intraday.py with its own
localisation. An earlier version of this note called the `.US` line an internal
book because it was off by a fraction of a percent from NASDAQ closes; that was
this timestamp error, not the data (docs/dataset-and-provenance.md, section 3.1).

Usage:
    python src/kase/tradernet_fetch.py --discover            # probe availability
    python src/kase/tradernet_fetch.py --backfill            # full history (resumable)
    python src/kase/tradernet_fetch.py --backfill --ticker KSPI.KZ
    python src/kase/tradernet_fetch.py --update              # recent days (scheduled job)
    python src/kase/tradernet_fetch.py --verify              # sanity-check stored data
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

try:
    import fcntl
except ImportError:                                    # non-POSIX
    fcntl = None

# --- Config ----------------------------------------------------------------------
API = "https://tradernet.com/api/"
UA = {"User-Agent": "Mozilla/5.0"}

REPO_DIR = Path(__file__).resolve().parents[2]
# KASE_STORE, when set, names the directory that holds kase/intraday; the
# companion repositories read the store through the same variable.
STORE_ROOT = Path(os.environ["KASE_STORE"]) if os.environ.get("KASE_STORE") else REPO_DIR / "data"
OUT_DIR = STORE_ROOT / "kase" / "intraday"
MANIFEST = OUT_DIR / "manifest.csv"

TZ = "Asia/Almaty"
RAW_TO_LOCAL = timedelta(hours=3)   # xSeries -> Almaty wall clock (see module docstring)

PACING_SECONDS = 1.5       # measured safe; hammering stalls the connection
MAX_RETRIES = 3
UPDATE_DAYS = 10           # scheduled job re-fetches this many days and merges

# Minute data begins well after most instruments list, so never probe earlier.
EARLIEST = date(2015, 1, 1)

TICKERS = [
    # KZT equity lines
    "KSPI.KZ", "HSBK.KZ", "KZAP.KZ", "AIRA.KZ", "KCEL.KZ", "KZTK.KZ",
    "KEGC.KZ", "KZTO.KZ", "KMGZ.KZ", "CCBN.KZ", "ASBN.KZ", "BAST.KZ",
    "RAHT.KZ", "KMGD.KZ", "IFDR.KZ", "BSUL.KZ", "KASE.KZ",
    # USD depositary lines (capital D)
    "KSPID.KZ", "HSBKD.KZ", "KZAPD.KZ",
    # On-exchange FX
    "USDKZT_TOM.KZ", "EURKZT_TOM.KZ", "RUBKZT_TOM.KZ", "CNYKZT_TOM.KZ",
]

COLUMNS = ["ts_utc", "ts_almaty", "open", "high", "low", "close", "volume"]
PRICE_COLS = ["open", "high", "low", "close"]

# Equity continuous session, Almaty. FX and depositary lines run wider, so this
# is used for reporting and for the open-time check on .KZ equities only.
SESSION_OPEN_MIN = 11 * 60 + 30
SESSION_CLOSE_MIN = 17 * 60 + 30
EQUITY_TICKERS = {t for t in TICKERS if not t.endswith("_TOM.KZ")}


class FetchError(RuntimeError):
    """A request failed outright, distinct from a window that is legitimately empty."""


# --- API -------------------------------------------------------------------------
def api_hloc(ticker: str, d1: date, d2_exclusive: date, timeframe: int = 1) -> dict:
    """Raw getHloc call. `d2_exclusive` is passed through as-is: the API's
    date_to is exclusive, so callers must pass the day AFTER the last one they
    want."""
    params = {
        "id": ticker,
        "count": -1,
        "timeframe": timeframe,
        "date_from": d1.strftime("%d.%m.%Y"),
        "date_to": d2_exclusive.strftime("%d.%m.%Y"),
        "intervalMode": "OpenRay",
    }
    q = json.dumps({"cmd": "getHloc", "params": params})
    url = API + "?" + urllib.parse.urlencode({"q": q})
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode())


def _request(ticker: str, d1: date, d2_exclusive: date) -> dict:
    """api_hloc with retries. Raises FetchError once retries are exhausted."""
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return api_hloc(ticker, d1, d2_exclusive)
        except Exception as e:
            last = e
            if attempt < MAX_RETRIES:
                time.sleep(PACING_SECONDS * 2 * attempt)
    raise FetchError(f"{ticker} {d1}..{d2_exclusive}: {last}")


def empty_frame() -> pd.DataFrame:
    frame = pd.DataFrame({c: pd.Series(dtype="float64") for c in COLUMNS})
    frame["ts_utc"] = pd.Series(dtype="datetime64[ns, UTC]")
    frame["ts_almaty"] = pd.Series(dtype=f"datetime64[ns, {TZ}]")
    return frame[COLUMNS]


def fetch_bars(ticker: str, d1: date, d2_inclusive: date) -> pd.DataFrame:
    """Fetch [d1, d2_inclusive] as a tidy frame.

    Returns an empty frame when the window genuinely holds no bars; raises
    FetchError when the request failed, so callers can tell the two apart.
    """
    data = _request(ticker, d1, d2_inclusive + timedelta(days=1))

    hloc = (data.get("hloc") or {}).get(ticker)
    xs = (data.get("xSeries") or {}).get(ticker)
    vl = (data.get("vl") or {}).get(ticker)
    if not hloc or not xs:
        return empty_frame()
    if vl is None:
        vl = [None] * len(xs)
    if not (len(hloc) == len(xs) == len(vl)):
        # Arrays should be parallel; misalignment would silently pair the wrong
        # price with the wrong minute, so refuse the window rather than guess.
        raise FetchError(f"{ticker} {d1}: array length mismatch "
                         f"hloc={len(hloc)} xs={len(xs)} vl={len(vl)}")

    local = pd.to_datetime([x + int(RAW_TO_LOCAL.total_seconds()) for x in xs], unit="s")
    alm = local.tz_localize(TZ, ambiguous=True, nonexistent="shift_forward")
    frame = pd.DataFrame({
        "ts_utc": alm.tz_convert("UTC"),
        "ts_almaty": alm,
        "open": [b[2] for b in hloc],
        "high": [b[0] for b in hloc],
        "low": [b[1] for b in hloc],
        "close": [b[3] for b in hloc],
        "volume": vl,
    })
    # Pin dtypes: early years quote whole KZT and arrive as JSON ints, which
    # would otherwise make partitions unreadable as one dataset.
    for col in PRICE_COLS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").astype("float64")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").astype("float64")
    return frame[COLUMNS]


def probe_info(ticker: str) -> dict:
    try:
        data = _request(ticker, date.today() - timedelta(days=5), date.today() + timedelta(days=1))
    except FetchError:
        return {}
    return ((data.get("info") or {}).get(ticker) or {})


def parse_first_date(info: dict) -> date | None:
    raw = info.get("firstDate")
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw, "%m.%d.%Y").date()   # info uses MM.DD.YYYY
    except ValueError:
        return None
    return None if parsed.year <= 1970 else parsed


# --- Storage ---------------------------------------------------------------------
def month_path(ticker: str, year: int, month: int) -> Path:
    return OUT_DIR / ticker / f"{year:04d}-{month:02d}.parquet"


def coverage_path(ticker: str) -> Path:
    return OUT_DIR / ticker / "_coverage.json"


def read_coverage(ticker: str) -> dict:
    try:
        return json.loads(coverage_path(ticker).read_text())
    except Exception:
        return {}


def write_coverage(ticker: str, cov: dict):
    path = coverage_path(ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cov, indent=2, sort_keys=True))
    os.replace(tmp, path)


class _Lock:
    """Advisory per-ticker lock so a manual backfill and the scheduled update
    cannot interleave read-modify-write on the same partition."""

    def __init__(self, ticker: str):
        self.path = OUT_DIR / ticker / ".lock"
        self.handle = None

    def __enter__(self):
        if fcntl is None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "w")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if self.handle is not None:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()


def read_partition(path: Path) -> pd.DataFrame:
    try:
        return pd.read_parquet(path)
    except Exception as e:
        print(f"    [WARN] unreadable partition {path.name} ({e}), rebuilding", flush=True)
        return empty_frame()


def write_month(ticker: str, year: int, month: int, frame: pd.DataFrame) -> tuple[int, int]:
    """Merge into a monthly partition. Returns (rows from this fetch, partition total).

    Writes are atomic (temp file + rename) so an interrupted run cannot leave a
    truncated Parquet behind.
    """
    # Drop the leading reference bar and anything else outside the month.
    if not frame.empty:
        alm = pd.to_datetime(frame["ts_almaty"])
        frame = frame[(alm.dt.year == year) & (alm.dt.month == month)]
    fetched = len(frame)

    path = month_path(ticker, year, month)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = frame
    if path.exists():
        merged = pd.concat([read_partition(path), frame], ignore_index=True)
    if not merged.empty:
        merged = (merged.drop_duplicates(subset="ts_utc", keep="last")
                        .sort_values("ts_utc")
                        .reset_index(drop=True))
    else:
        merged = empty_frame()

    tmp = path.with_suffix(".parquet.tmp")
    merged.to_parquet(tmp, index=False, compression="zstd")
    os.replace(tmp, path)
    return fetched, len(merged)


def months_between(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def month_last_day(year: int, month: int) -> date:
    first_next = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return first_next - timedelta(days=1)


# --- Commands --------------------------------------------------------------------
def cmd_discover():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    previous = load_manifest()
    rows, changes = [], []
    print(f"{'ticker':16} {'market':10} {'firstDate':>12}")
    for t in TICKERS:
        info = probe_info(t)
        time.sleep(PACING_SECONDS)
        mkt = info.get("mkt_name", "")
        fd = parse_first_date(info)
        prior = previous.get(t)
        if not mkt and prior and prior.get("status") == "ok":
            # A transient probe failure must not silently drop a healthy
            # ticker from every future fetch.
            print(f"{t:16} {'(probe failed, keeping previous)':<34}")
            rows.append(prior)
            continue
        status = "ok" if mkt else "unavailable"
        if prior and prior.get("status") != status:
            changes.append(f"{t}: {prior.get('status')} -> {status}")
        print(f"{t:16} {mkt or '-':10} {str(fd) if fd else '-':>12}  {status}")
        rows.append({"ticker": t, "market": mkt,
                     "first_date": fd.isoformat() if fd else "", "status": status})

    with open(MANIFEST, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "market", "first_date", "status"])
        w.writeheader()
        w.writerows(rows)
    if changes:
        print("\nStatus changes: " + "; ".join(changes))
    print(f"\nManifest: {MANIFEST}")


def load_manifest() -> dict[str, dict]:
    if not MANIFEST.exists():
        return {}
    with open(MANIFEST) as f:
        return {r["ticker"]: r for r in csv.DictReader(f)}


def cmd_backfill(only: str | None, refetch: bool) -> int:
    manifest = load_manifest()
    if not manifest:
        print("No manifest. Run --discover first.", file=sys.stderr)
        return 1

    today = date.today()
    tickers = [only] if only else [t for t, r in manifest.items() if r["status"] == "ok"]
    grand, failures = 0, 0

    for ticker in tickers:
        rec = manifest.get(ticker, {})
        fd = rec.get("first_date") or ""
        start = max(date.fromisoformat(fd), EARLIEST) if fd else EARLIEST
        print(f"\n{ticker}  (from {start})", flush=True)
        cov = read_coverage(ticker)
        total = 0

        with _Lock(ticker):
            for year, month in months_between(start, today):
                key = f"{year:04d}-{month:02d}"
                last_day = month_last_day(year, month)
                want_through = min(last_day, today)
                entry = cov.get(key, {})
                got_through = entry.get("fetched_through")
                # Re-fetch unless we already covered the month through its end
                # (or through today, for the month still in progress).
                if (not refetch and got_through
                        and date.fromisoformat(got_through) >= want_through):
                    continue
                try:
                    frame = fetch_bars(ticker, date(year, month, 1), want_through)
                except FetchError as e:
                    print(f"  [FAIL] {key}: {e}", flush=True)
                    failures += 1
                    time.sleep(PACING_SECONDS)
                    continue
                time.sleep(PACING_SECONDS)
                fetched, partition = write_month(ticker, year, month, frame)
                cov[key] = {"fetched_through": want_through.isoformat(), "bars": partition}
                write_coverage(ticker, cov)
                if fetched:
                    total += fetched
                    print(f"  {key}: +{fetched:>5} bars (partition {partition})", flush=True)
        print(f"  -> {total} bars fetched for {ticker}")
        grand += total

    print(f"\nDone. {grand} bars fetched, {failures} failed window(s).")
    return 1 if failures else 0


def cmd_update(days: int) -> int:
    manifest = load_manifest()
    tickers = [t for t, r in manifest.items() if r["status"] == "ok"] or TICKERS
    end = date.today()
    start = end - timedelta(days=days)
    print(f"Updating {len(tickers)} tickers over {start} .. {end}")

    total_bars, failures, with_data = 0, 0, 0
    for ticker in tickers:
        try:
            frame = fetch_bars(ticker, start, end)
        except FetchError as e:
            print(f"  [FAIL] {ticker}: {e}", flush=True)
            failures += 1
            time.sleep(PACING_SECONDS)
            continue
        time.sleep(PACING_SECONDS)
        if frame.empty:
            continue
        with _Lock(ticker):
            cov = read_coverage(ticker)
            alm = pd.to_datetime(frame["ts_almaty"])
            for (year, month), part in frame.groupby([alm.dt.year, alm.dt.month]):
                year, month = int(year), int(month)
                _, partition = write_month(ticker, year, month, part)
                key = f"{year:04d}-{month:02d}"
                through = min(month_last_day(year, month), end)
                prior = cov.get(key, {}).get("fetched_through")
                if not prior or date.fromisoformat(prior) < through:
                    cov[key] = {"fetched_through": through.isoformat(), "bars": partition}
            write_coverage(ticker, cov)
        total_bars += len(frame)
        with_data += 1
        print(f"  {ticker}: {len(frame)} bars", flush=True)

    print(f"Updated {with_data} tickers, {total_bars} bars, {failures} failure(s).")
    if failures:
        print("::warning::some tickers failed to fetch")
        return 1
    # Every ticker silently returning nothing on a weekday means the feed
    # changed or is blocking us. That must not look like a healthy run.
    if with_data == 0 and end.weekday() < 5:
        print("No bars from any ticker on a weekday, treating as failure.", file=sys.stderr)
        return 1
    return 0


def cmd_verify() -> int:
    if not OUT_DIR.exists():
        print("Nothing stored yet.")
        return 0
    problems = 0
    print(f"{'ticker':16} {'files':>6} {'bars':>9} {'range':>25} {'median open':>12}")
    for tdir in sorted(p for p in OUT_DIR.iterdir() if p.is_dir()):
        files = sorted(tdir.glob("*.parquet"))
        if not files:
            continue
        frame = pd.concat([read_partition(p) for p in files], ignore_index=True)
        if frame.empty:
            continue
        ticker = tdir.name
        alm = pd.to_datetime(frame["ts_almaty"])
        opens = alm.groupby(alm.dt.normalize()).min()
        median_open_min = int((opens.dt.hour * 60 + opens.dt.minute).median())
        rng = f"{alm.min():%Y-%m-%d}..{alm.max():%Y-%m-%d}"
        print(f"{ticker:16} {len(files):>6} {len(frame):>9} {rng:>25} "
              f"{median_open_min // 60:02d}:{median_open_min % 60:02d}")

        if frame["ts_utc"].duplicated().any():
            print(f"  [PROBLEM] {ticker}: duplicate timestamps"); problems += 1
        if (frame[PRICE_COLS] <= 0).any().any():
            print(f"  [PROBLEM] {ticker}: non-positive prices"); problems += 1
        if (frame["high"] < frame["low"]).any():
            print(f"  [PROBLEM] {ticker}: bars with high < low"); problems += 1
        bad_volume = frame["volume"].notna() & (frame["volume"] <= 0)
        if bad_volume.any():
            # A zero volume is a bar without a trade; a negative one is a vendor-side
            # overflow. Both are reported, neither is removed.
            print(f"  [PROBLEM] {ticker}: {int(bad_volume.sum())} bars with non-positive volume"); problems += 1
        # A wrong timezone conversion shows up here as a shifted open, which is
        # exactly how the 2024 Almaty UTC+6->UTC+5 change was originally missed.
        # Only meaningful for names liquid enough to trade near the bell: a
        # ticker averaging a few deals a day opens late for real reasons.
        bars_per_day = len(frame) / max(1, opens.size)
        if (ticker in EQUITY_TICKERS and bars_per_day >= 20
                and abs(median_open_min - SESSION_OPEN_MIN) > 10):
            print(f"  [PROBLEM] {ticker}: median open {median_open_min // 60:02d}:"
                  f"{median_open_min % 60:02d} deviates from the 11:30 session open "
                  f"(suspect timestamp handling)"); problems += 1
        if ticker in EQUITY_TICKERS:
            mins = alm.dt.hour * 60 + alm.dt.minute
            in_sess = ((mins >= SESSION_OPEN_MIN - 5) & (mins <= SESSION_CLOSE_MIN + 5)).mean()
            if in_sess < 0.95:
                print(f"  [PROBLEM] {ticker}: only {in_sess * 100:.1f}% of bars "
                      f"inside the continuous session"); problems += 1

    print("\nNo problems found." if not problems else f"\n{problems} problem(s) found.")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--discover", action="store_true", help="Probe ticker availability")
    g.add_argument("--backfill", action="store_true", help="Fetch full history (resumable)")
    g.add_argument("--update", action="store_true", help="Fetch recent days and merge")
    g.add_argument("--verify", action="store_true", help="Sanity-check stored data")
    ap.add_argument("--ticker", help="Restrict --backfill to one ticker")
    ap.add_argument("--refetch", action="store_true",
                    help="With --backfill, re-fetch months already covered")
    ap.add_argument("--days", type=int, default=UPDATE_DAYS,
                    help=f"With --update, days to re-fetch (default {UPDATE_DAYS})")
    args = ap.parse_args()

    if args.discover:
        cmd_discover()
        return 0
    if args.backfill:
        return cmd_backfill(args.ticker, args.refetch)
    if args.update:
        return cmd_update(args.days)
    return cmd_verify()


if __name__ == "__main__":
    sys.exit(main())
