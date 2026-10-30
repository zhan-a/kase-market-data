#!/usr/bin/env python3
"""
KASE Market Data Recorder: snapshots all equities every 5 min during market hours.

Fetches kase.kz/api/trade-results/shares/ for full table data (bid, ask, OHLC,
VWAP, volume, deals) and appends to daily CSV files under data/kase/raw/YYYY/MM/.
The USDKZT column comes from Yahoo Finance (fetch_fx_rate below), not from KASE.

The committed board recordings were written by this recorder, run from a
scheduler every five minutes. Until 2026-08-20 it parsed the board page's HTML
into the same columns; from 2026-08-21 it reads the JSON endpoint above. Both
surfaces carry the previous session during the trading day
(docs/dataset-and-provenance.md, section 4.1).

Usage:
    python src/recorders/kase_snapshot_recorder.py              # Record a snapshot
    python src/recorders/kase_snapshot_recorder.py --test       # Dry-run: print parsed data, don't write
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# --- Config ----------------------------------------------------------------------
TZ_ALMATY = ZoneInfo("Asia/Almaty")

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "kase" / "raw"
STATE_FILE = Path(__file__).resolve().parent / "recorder_state.json"

KASE_API_URL = "https://kase.kz/api/trade-results/shares/"

# Telegram (reuse from premium bot)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID", "")

# Minimum tickers expected, alert if fewer (means scraper is broken)
MIN_TICKERS = 5

# CSV columns
CSV_COLUMNS = [
    "timestamp",        # Canonical 5-min slot (Almaty time, ISO format)
    "scrape_time",      # Actual wall-clock time of scrape (ISO format)
    "delayed",          # True if scrape_time is >15 min from timestamp
    "ticker",
    "mode",
    "bid",
    "ask",
    "open",
    "high",
    "low",
    "last",
    "change_pct",
    "vwap",
    "deals",
    "volume_mln",
    "interval_volume_mln",  # Delta from previous snapshot
    "interval_deals",       # Delta from previous snapshot
    "fx_usdkzt",            # USDKZT exchange rate at time of snapshot
]

# --- FX Rate ---------------------------------------------------------------------
def fetch_fx_rate() -> float | None:
    """Fetch current USDKZT rate from Yahoo Finance."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/USDKZT=X?range=1d&interval=1d"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    data = resp.json()
    return data["chart"]["result"][0]["meta"]["regularMarketPrice"]


# --- Scraping --------------------------------------------------------------------
def scrape_kase() -> list[dict]:
    """Fetch all ticker rows from the KASE trade-results API.

    kase.kz became a client-rendered app in Aug 2026: the served HTML holds
    the previous session's board until after close, so parsing it recorded
    day-stale data. The app's JSON endpoint turned out to be the same board,
    previous session included (docs/dataset-and-provenance.md, section 4.1).
    Output keys and units match the historical CSV schema.
    """
    headers = {"User-Agent": "Mozilla/5.0 (KASE-recorder/1.0)"}

    resp = requests.get(KASE_API_URL, headers=headers, timeout=20)
    resp.raise_for_status()

    rows = []
    for item in resp.json():
        # Skip rows without a deal price (not traded at all)
        if item.get("last_deal_price") is None:
            continue

        volkzt = item.get("volkzt")
        change = item.get("trand_percent")
        rows.append({
            "ticker": item.get("code"),
            "mode": item.get("board"),
            "bid": item.get("current_bid"),
            "ask": item.get("current_offer"),
            "open": item.get("openprice"),
            "high": item.get("max_price"),
            "low": item.get("min_price"),
            "last": item.get("last_deal_price"),
            "change_pct": round(change, 2) if change is not None else None,
            "vwap": item.get("avg_price"),
            "deals": item.get("dealcnt"),
            "volume_mln": round(volkzt / 1e6, 1) if volkzt is not None else None,
        })

    return rows


# --- State management (for interval deltas) --------------------------------------
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# --- CSV writing -----------------------------------------------------------------
def get_csv_path(dt: datetime) -> Path:
    """Return path like data/kase/raw/2026/04/2026-04-14.csv"""
    return DATA_DIR / dt.strftime("%Y") / dt.strftime("%m") / dt.strftime("%Y-%m-%d.csv")


def write_snapshot(rows: list[dict], timestamp: str, scrape_time: str, delayed: bool,
                   prev_state: dict, fx_usdkzt: float | None = None) -> dict:
    """Write rows to daily CSV, return new state for next run."""
    if not rows:
        return prev_state

    dt = datetime.fromisoformat(timestamp)
    csv_path = get_csv_path(dt)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    file_exists = csv_path.exists()

    new_state = {}

    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()

        for row in rows:
            ticker = row["ticker"]

            # Compute interval deltas
            prev = prev_state.get(ticker, {})
            prev_volume = prev.get("volume_mln")
            prev_deals = prev.get("deals")

            interval_volume = None
            interval_deals = None
            if prev_volume is not None and row["volume_mln"] is not None:
                delta = row["volume_mln"] - prev_volume
                interval_volume = round(delta, 4) if delta >= 0 else None  # Reset on new day
            if prev_deals is not None and row["deals"] is not None:
                delta = row["deals"] - prev_deals
                interval_deals = int(delta) if delta >= 0 else None

            csv_row = {
                "timestamp": timestamp,
                "scrape_time": scrape_time,
                "delayed": delayed,
                "ticker": ticker,
                "mode": row["mode"],
                "bid": row["bid"],
                "ask": row["ask"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "last": row["last"],
                "change_pct": row["change_pct"],
                "vwap": row["vwap"],
                "deals": int(row["deals"]) if row["deals"] is not None else None,
                "volume_mln": row["volume_mln"],
                "interval_volume_mln": interval_volume,
                "interval_deals": interval_deals,
                "fx_usdkzt": fx_usdkzt,
            }
            writer.writerow(csv_row)

            # Save current cumulative values for next run
            new_state[ticker] = {
                "volume_mln": row["volume_mln"],
                "deals": row["deals"],
            }

    return new_state


# --- Telegram alerts -------------------------------------------------------------
def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[SKIP] {message}")
        return
    if TELEGRAM_USER_ID:
        message = f'<a href="tg://user?id={TELEGRAM_USER_ID}">\u200b</a>{message}'
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception:
        pass


# --- Main ------------------------------------------------------------------------
def compute_timestamps() -> tuple[str, str, bool]:
    """Compute canonical timestamp (5-min slot) and actual scrape time.

    Returns (timestamp, scrape_time, delayed).
    """
    now = datetime.now(TZ_ALMATY)
    scrape_time = now.isoformat(timespec="seconds")

    # Round down to nearest 5-min slot
    slot_minute = (now.minute // 5) * 5
    slot = now.replace(minute=slot_minute, second=0, microsecond=0)
    timestamp = slot.isoformat(timespec="seconds")

    # Check delay
    delay_seconds = (now - slot).total_seconds()
    delayed = delay_seconds > 900  # >15 min

    return timestamp, scrape_time, delayed


def record(dry_run: bool = False):
    timestamp, scrape_time, delayed = compute_timestamps()

    print(f"KASE Recorder, {scrape_time}")
    print(f"  Canonical slot: {timestamp}")
    if delayed:
        print(f"  WARNING: delayed >15 min from slot")

    # Scrape
    try:
        rows = scrape_kase()
    except Exception as e:
        print(f"  ERROR: scrape failed: {e}")
        send_telegram(f"<b>KASE Recorder Error</b>\n\nScrape failed: {e}")
        return

    print(f"  Tickers scraped: {len(rows)}")

    # Fetch FX rate
    fx_usdkzt = None
    try:
        fx_usdkzt = fetch_fx_rate()
        print(f"  USDKZT rate: {fx_usdkzt}")
    except Exception as e:
        print(f"  WARNING: FX rate fetch failed: {e}")

    if len(rows) < MIN_TICKERS:
        msg = f"Only {len(rows)} tickers scraped (expected >={MIN_TICKERS}). Scraper may be broken."
        print(f"  WARNING: {msg}")
        send_telegram(f"<b>KASE Recorder Warning</b>\n\n{msg}")
        if len(rows) == 0:
            return

    if dry_run:
        print(f"\n  {'Ticker':<12} {'Last':>12} {'Volume(M)':>12} {'Deals':>8}")
        print(f"  {'-'*12} {'-'*12} {'-'*12} {'-'*8}")
        for row in rows:
            last = f"{row['last']:,.2f}" if row['last'] else "-"
            vol = f"{row['volume_mln']:,.1f}" if row['volume_mln'] else "-"
            deals = f"{row['deals']:.0f}" if row['deals'] else "-"
            print(f"  {row['ticker']:<12} {last:>12} {vol:>12} {deals:>8}")
        print(f"\n  FX USDKZT: {fx_usdkzt if fx_usdkzt else 'N/A'}")
        print(f"\n  Dry run, no data written.")
        return

    # Load previous state for interval deltas
    prev_state = load_state()

    # Write to CSV
    new_state = write_snapshot(rows, timestamp, scrape_time, delayed, prev_state, fx_usdkzt)

    # Save state
    save_state(new_state)

    csv_path = get_csv_path(datetime.fromisoformat(timestamp))
    print(f"  Written to: {csv_path}")
    print(f"  Done.")


def main():
    parser = argparse.ArgumentParser(description="KASE Market Data Recorder")
    parser.add_argument("--test", action="store_true", help="Dry run: scrape and print, don't write")
    args = parser.parse_args()

    record(dry_run=args.test)


if __name__ == "__main__":
    main()
