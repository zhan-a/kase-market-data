#!/usr/bin/env python3
"""
Fetch historical daily OHLCV data for KASE stocks.

Sources (tried in order):
1. yfinance with various ticker formats (.ME, .KZ, .IL)
2. Existing local data in data/historical/kase/ and data/historical/
3. KASE recorder raw snapshots (data/kase/raw/)

Output: data/historical/kase/{TICKER}_daily.csv
Schema: date,open,high,low,close,volume,source

Does NOT overwrite existing files in data/historical/.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

# Project root
ROOT = Path(__file__).resolve().parents[2]
HIST_DIR = ROOT / "data" / "historical"
KASE_DIR = HIST_DIR / "kase"
RAW_DIR = ROOT / "data" / "kase" / "raw"
OUT_DIR = KASE_DIR  # output goes alongside existing kase data

# All KASE tickers we want to fetch, with metadata
KASE_TICKERS = {
    "AIRA": {"name": "Air Astana JSC", "sector": "transport"},
    "HSBK": {"name": "Halyk Bank", "sector": "finance"},
    "KSPI": {"name": "Kaspi.kz JSC", "sector": "finance"},
    "KZAP": {"name": "NAC Kazatomprom", "sector": "energy"},
    "FRHC_KZ": {"name": "Freedom Holding Corp", "sector": "finance"},
    "CCBN": {"name": "Bank CenterCredit", "sector": "finance"},
    "KCEL": {"name": "Kcell JSC", "sector": "telecom"},
    "KEGC": {"name": "KEGOC JSC", "sector": "energy"},
    "KMGZ": {"name": "KazMunayGaz", "sector": "energy"},
    "KZTO": {"name": "KazTransOil", "sector": "energy"},
    "KZTK": {"name": "Kazakhtelecom", "sector": "telecom"},
    "KZTKp": {"name": "Kazakhtelecom (pref)", "sector": "telecom"},
    "KASE": {"name": "Kazakhstan Stock Exchange", "sector": "finance"},
    "RAHT": {"name": "LOTTE Rakhat", "sector": "consumer"},
    "BSUL": {"name": "Bayan Sulu", "sector": "consumer"},
    "BAST": {"name": "BAST JSC", "sector": "industrial"},
    "AMGZp": {"name": "CNPC-AMG (pref)", "sector": "energy"},
    "MMGZp": {"name": "Mangistaumunaigas (pref)", "sector": "energy"},
    "KMGD": {"name": "KM GOLD", "sector": "mining"},
    "GB_ALTN": {"name": "AltynGold plc", "sector": "mining"},
    "ASBN": {"name": "ForteBank", "sector": "finance"},
    "IFDR": {"name": "Teniz Capital", "sector": "finance"},
}

# yfinance ticker mappings to try for each KASE ticker
YF_TICKER_MAP = {
    "AIRA": ["AIRA.ME", "AIRA.KZ", "AIR.IL"],
    "HSBK": ["HSBK.IL", "HSBK.ME", "HSBK.KZ"],
    "KSPI": ["KSPI.ME", "KSPI.KZ", "KSPI"],
    "KZAP": ["KAP.IL", "KZAP.ME", "KZAP.KZ"],
    "FRHC_KZ": ["FRHC"],  # NASDAQ-listed
    "CCBN": ["CCBN.ME", "CCBN.KZ"],
    "KCEL": ["KCEL.ME", "KCEL.KZ", "KCELL.IL"],
    "KEGC": ["KEGC.ME", "KEGC.KZ"],
    "KMGZ": ["KMGZ.ME", "KMGZ.KZ", "KMG.IL"],
    "KZTO": ["KZTO.ME", "KZTO.KZ"],
    "KZTK": ["KZTK.ME", "KZTK.KZ"],
    "KZTKp": ["KZTKp.ME"],
    "KASE": ["KASE.ME", "KASE.KZ"],
    "RAHT": ["RAHT.ME", "RAHT.KZ"],
    "BSUL": ["BSUL.ME", "BSUL.KZ"],
    "BAST": ["BAST.ME", "BAST.KZ"],
    "AMGZp": ["AMGZp.ME"],
    "MMGZp": ["MMGZp.ME"],
    "KMGD": ["KMGD.ME", "KMGD.KZ"],
    "GB_ALTN": ["GB_ALTN.ME", "ALTN.L"],
    "ASBN": ["ASBN.ME", "ASBN.KZ"],
    "IFDR": ["IFDR.ME", "IFDR.KZ"],
}

# Mapping from KASE ticker to existing local CSV files
LOCAL_FILE_MAP = {
    "AIRA": KASE_DIR / "AIRA.csv",
    "HSBK": KASE_DIR / "HSBK.csv",
    "KSPI": KASE_DIR / "KSPI.csv",
    "KZAP": KASE_DIR / "KZAP.csv",
    "FRHC_KZ": KASE_DIR / "FRHC_KZ.csv",
}


def try_yfinance(ticker: str, yf_symbols: list[str]) -> pd.DataFrame | None:
    """Try fetching from yfinance with multiple ticker formats."""
    try:
        import yfinance as yf
    except ImportError:
        print("  [WARN] yfinance not installed, skipping yfinance source")
        return None

    for sym in yf_symbols:
        try:
            print(f"  Trying yfinance: {sym} ...", end=" ")
            data = yf.download(sym, period="max", progress=False, auto_adjust=True)
            if data is not None and len(data) >= 10:
                print(f"OK ({len(data)} rows)")
                df = data.reset_index()
                # Handle both single and multi-level column names
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] if c[1] == '' else c[0] for c in df.columns]
                df = df.rename(columns={
                    "Date": "date",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                })
                df["source"] = f"yfinance:{sym}"
                df = df[["date", "open", "high", "low", "close", "volume", "source"]]
                df["date"] = pd.to_datetime(df["date"]).dt.date
                return df
            else:
                print("no data")
        except Exception as e:
            print(f"error: {e}")
    return None


def try_local(ticker: str) -> pd.DataFrame | None:
    """Try loading from existing local CSV files."""
    local_path = LOCAL_FILE_MAP.get(ticker)
    if local_path is None or not local_path.exists():
        return None

    print(f"  Loading local: {local_path.name} ...", end=" ")
    try:
        df = pd.read_csv(local_path)
        # Already in normalized format (date,open,high,low,close,volume)
        if "date" in df.columns:
            df["source"] = f"local:{local_path.name}"
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df[["date", "open", "high", "low", "close", "volume", "source"]]
            print(f"OK ({len(df)} rows)")
            return df
        # Legacy format (DATE,HIGH,LOW,OPEN,CLOSE,VOLUME) with DD/MM/YYYY
        elif "DATE" in df.columns:
            df = df.rename(columns={
                "DATE": "date",
                "OPEN": "open",
                "HIGH": "high",
                "LOW": "low",
                "CLOSE": "close",
                "VOLUME": "volume",
            })
            df["date"] = pd.to_datetime(df["date"], format="%d/%m/%Y").dt.date
            df["source"] = f"local:{local_path.name}"
            df = df[["date", "open", "high", "low", "close", "volume", "source"]]
            df = df.sort_values("date").reset_index(drop=True)
            print(f"OK ({len(df)} rows)")
            return df
    except Exception as e:
        print(f"error: {e}")
    return None


def try_raw_snapshots(ticker: str) -> pd.DataFrame | None:
    """Try building daily OHLCV from KASE recorder 5-min snapshots."""
    # Walk raw directory structure: raw/YYYY/MM/DD/
    if not RAW_DIR.exists():
        return None

    rows = []
    for year_dir in sorted(RAW_DIR.iterdir()):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            for day_dir in sorted(month_dir.iterdir()):
                if not day_dir.is_dir():
                    continue
                # Look for snapshot files containing this ticker
                for f in sorted(day_dir.glob("*.json")):
                    try:
                        import json
                        with open(f) as fh:
                            snap = json.load(fh)
                        # Find our ticker in snapshot
                        if isinstance(snap, list):
                            for item in snap:
                                if item.get("code") == ticker:
                                    rows.append({
                                        "timestamp": f.stem,
                                        "price": item.get("price"),
                                        "volume": item.get("volkzt"),
                                    })
                        elif isinstance(snap, dict) and snap.get("code") == ticker:
                            rows.append({
                                "timestamp": f.stem,
                                "price": snap.get("price"),
                                "volume": snap.get("volkzt"),
                            })
                    except Exception:
                        continue

    if not rows:
        return None

    print(f"  Building from {len(rows)} raw snapshots ...", end=" ")
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date

    daily = df.groupby("date").agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("volume", "last"),  # cumulative, take last
    ).reset_index()
    daily["source"] = "kase_recorder"
    print(f"OK ({len(daily)} days)")
    return daily


def fetch_all():
    """Fetch data for all KASE tickers."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results = {}
    for ticker, meta in KASE_TICKERS.items():
        out_path = OUT_DIR / f"{ticker}_daily.csv"
        print(f"\n{'='*60}")
        print(f"Ticker: {ticker} ({meta['name']})")

        if out_path.exists():
            existing = pd.read_csv(out_path)
            print(f"  Already exists: {len(existing)} rows, skipping")
            results[ticker] = {"rows": len(existing), "source": "existing", "status": "skipped"}
            continue

        # Try sources in order
        df = None

        # 1. Try yfinance
        yf_syms = YF_TICKER_MAP.get(ticker, [])
        if yf_syms:
            df = try_yfinance(ticker, yf_syms)

        # 2. Try local existing data
        if df is None:
            df = try_local(ticker)

        # 3. Try raw snapshots
        if df is None:
            df = try_raw_snapshots(ticker)

        if df is not None and len(df) > 0:
            # Clean up
            df = df.dropna(subset=["open", "high", "low", "close"])
            df = df.sort_values("date").reset_index(drop=True)
            df.to_csv(out_path, index=False)
            source = df["source"].iloc[0] if len(df) > 0 else "unknown"
            print(f"  -> Saved {len(df)} rows to {out_path.name} (source: {source})")
            results[ticker] = {"rows": len(df), "source": source, "status": "saved"}
        else:
            print(f"  -> NO DATA AVAILABLE from any source")
            results[ticker] = {"rows": 0, "source": "none", "status": "no_data"}

    # Print summary
    print(f"\n{'='*60}")
    print("FETCH SUMMARY")
    print(f"{'='*60}")
    total_saved = 0
    total_nodata = 0
    for ticker, res in sorted(results.items()):
        status_icon = {
            "saved": "+",
            "skipped": "~",
            "no_data": "X",
        }.get(res["status"], "?")
        print(f"  [{status_icon}] {ticker:10s} {res['rows']:>6d} rows  ({res['source']})")
        if res["status"] == "saved":
            total_saved += 1
        elif res["status"] == "no_data":
            total_nodata += 1

    print(f"\nSaved: {total_saved}  |  No data: {total_nodata}  |  Skipped (existing): {len(results) - total_saved - total_nodata}")


if __name__ == "__main__":
    fetch_all()
