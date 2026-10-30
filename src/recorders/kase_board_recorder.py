#!/usr/bin/env python3
"""
KASE board recorder: dense change-log recording via the KASE JSON API.

Designed to run 24/7 in Termux on an Android phone. Polls three endpoints every
POLL_SECONDS during the KASE continuous session (Mon-Fri 11:30-17:35 Almaty)
and appends a row only when an instrument's values actually changed, so file
size tracks information, not polling rate:

  - shares:  https://kase.kz/api/trade-results/shares/   (KZT lines)
  - depts:   https://kase.kz/api/trade-results/depts/    (USD DR lines: KSPId, KZAPd, HSBKd)
  - fx:      https://kase.kz/api/trade-results/currency-spot-current/ (official KASE FX)

The trade-results endpoints publish the previous session and do not change
during the trading day (docs/dataset-and-provenance.md, section 4.1), so a
change-log recorder on them records one row per instrument per day plus the
after-close switch. The output of this recorder is not committed anywhere.

Output (the "v2" series):

  data/kase/v2/YYYY/MM/YYYY-MM-DD.csv   change-log rows
  data/kase/v2/gaps.csv                 explicit gap log (first-class metadata)
  data/kase/v2/heartbeat.json           last poll info, for the watchdog

Every SYNC_SECONDS the accumulated rows are committed and pushed; if nothing
changed, the heartbeat alone is committed so the GitHub-side watchdog can
tell a quiet market from a dead recorder.

Gap accounting: a gap row is written when more than GAP_THRESHOLD_SECONDS of
IN-SESSION time passed without a successful poll, whether from a network
outage, a crash-restart, a reboot, or the phone being off across sessions.
Gap endpoints are clipped to session hours; a row can span a weekend (its
in-session overlap is what was actually lost).

Usage:
    python src/recorders/kase_board_recorder.py           # run the recording loop
    python src/recorders/kase_board_recorder.py --test    # one poll, print parsed rows, write nothing
"""

import argparse
import csv
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# --- Config ----------------------------------------------------------------------
TZ_ALMATY = ZoneInfo("Asia/Almaty")

REPO_DIR = Path(__file__).resolve().parents[2]
V2_DIR = REPO_DIR / "data" / "kase" / "v2"
GAP_LOG = V2_DIR / "gaps.csv"
HEARTBEAT = V2_DIR / "heartbeat.json"

SHARES_URL = "https://kase.kz/api/trade-results/shares/"
DEPTS_URL = "https://kase.kz/api/trade-results/depts/"
FX_URL = "https://kase.kz/api/trade-results/currency-spot-current/"

POLL_SECONDS = 30
SYNC_SECONDS = 600           # git commit/push cadence while in session
GAP_THRESHOLD_SECONDS = 300  # in-session silence longer than this is logged as a gap
GIT_TIMEOUT = 120            # seconds; a hung push must not stall the poll loop

SESSION_START = (11, 30)     # Almaty
SESSION_END = (17, 35)       # a few minutes past close to catch closing prints

HEADERS = {"User-Agent": "Mozilla/5.0 (KASE-recorder/2.0)"}

CSV_COLUMNS = [
    "poll_time",       # local wall-clock of the poll (Almaty, ISO)
    "code",            # instrument code (KSPI, KSPId, USDKZT_TOM#1, ...)
    "board",           # TQBR/TQBD for equities, FX<num_sess> for currency
    "bid",             # current_bid (not a live quote; docs/dataset-and-provenance.md, section 4.2)
    "ask",             # current_offer
    "open",
    "high",
    "low",
    "last",
    "change_pct",
    "vwap",
    "dealcnt",         # cumulative deals for the day
    "volkzt",          # cumulative KZT volume for the day
    "last_deal_date",  # exchange-side timestamp, freshness ground truth
]

GAP_COLUMNS = ["gap_start", "gap_end", "reason"]


# --- Fetching --------------------------------------------------------------------
def fetch_json(url: str) -> list | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            print(f"[WARN] non-list payload from {url}", flush=True)
            return None
        return data
    except Exception as e:
        print(f"[WARN] fetch failed {url}: {e}", flush=True)
        return None


def equity_row(item: dict, poll_time: str) -> dict:
    return {
        "poll_time": poll_time,
        "code": item.get("code"),
        "board": item.get("board"),
        "bid": item.get("current_bid"),
        "ask": item.get("current_offer"),
        "open": item.get("openprice"),
        "high": item.get("max_price"),
        "low": item.get("min_price"),
        "last": item.get("last_deal_price"),
        "change_pct": item.get("trand_percent"),
        "vwap": item.get("avg_price"),
        "dealcnt": item.get("dealcnt"),
        "volkzt": item.get("volkzt"),
        "last_deal_date": item.get("last_deal_date"),
    }


def fx_row(item: dict, poll_time: str) -> dict:
    # Currency rows carry a different shape; num_sess disambiguates the
    # multiple sessions a code can have on one day.
    ns = item.get("num_sess")
    ns = 0 if ns is None else ns
    return {
        "poll_time": poll_time,
        "code": f"{item.get('code')}#{ns}",
        "board": f"FX{ns}",
        "high": item.get("high"),
        "low": item.get("low"),
        "last": item.get("last"),
        "last_deal_date": item.get("time_trade"),
    }


def poll(poll_time: str) -> list[dict] | None:
    """One poll of all three endpoints. None means total failure."""
    shares = fetch_json(SHARES_URL)
    depts = fetch_json(DEPTS_URL)
    fx = fetch_json(FX_URL)

    if shares is None and depts is None and fx is None:
        return None

    rows = []
    for item in (shares or []) + (depts or []):
        if isinstance(item, dict) and item.get("code"):
            rows.append(equity_row(item, poll_time))
    for item in fx or []:
        if isinstance(item, dict) and item.get("code") and "KZT" in item["code"]:
            rows.append(fx_row(item, poll_time))
    return rows


# --- Change detection ------------------------------------------------------------
FINGERPRINT_FIELDS = ("bid", "ask", "last", "dealcnt", "volkzt", "high", "low", "last_deal_date")


def fingerprint(row: dict) -> tuple:
    return tuple(row.get(f) for f in FINGERPRINT_FIELDS)


def check_invariants(row: dict, prev_fp: tuple | None):
    """Cheap sanity checks at ingest: warn immediately, never crash."""
    if prev_fp is None:
        return
    prev = dict(zip(FINGERPRINT_FIELDS, prev_fp))
    if row.get("dealcnt") is not None and prev.get("dealcnt") is not None:
        if row["dealcnt"] < prev["dealcnt"]:
            print(f"[ANOMALY] {row['code']}: dealcnt decreased "
                  f"{prev['dealcnt']} -> {row['dealcnt']}", flush=True)
    if row.get("volkzt") is not None and prev.get("volkzt") is not None:
        if row["volkzt"] < prev["volkzt"]:
            print(f"[ANOMALY] {row['code']}: volkzt decreased "
                  f"{prev['volkzt']} -> {row['volkzt']}", flush=True)


# --- Session clock ---------------------------------------------------------------
def session_open(day: datetime) -> datetime:
    return day.replace(hour=SESSION_START[0], minute=SESSION_START[1],
                       second=0, microsecond=0)


def session_close(day: datetime) -> datetime:
    return day.replace(hour=SESSION_END[0], minute=SESSION_END[1],
                       second=0, microsecond=0)


def in_session(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return SESSION_START <= t < SESSION_END


def next_session_start(now: datetime) -> datetime:
    candidate = session_open(now)
    while candidate <= now or candidate.weekday() >= 5:
        candidate = session_open(candidate + timedelta(days=1))
    return candidate


def session_seconds_between(start: datetime, end: datetime) -> float:
    """Total in-session seconds inside [start, end]."""
    total = 0.0
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        if day.weekday() < 5:
            lo = max(start, session_open(day))
            hi = min(end, session_close(day))
            if hi > lo:
                total += (hi - lo).total_seconds()
        day += timedelta(days=1)
    return total


def previous_session_end(now: datetime) -> datetime:
    candidate = session_close(now)
    while candidate > now or candidate.weekday() >= 5:
        candidate = session_close(candidate - timedelta(days=1))
    return candidate


# --- Writing ---------------------------------------------------------------------
def append_rows(path: Path, columns: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, restval="", extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def day_csv_path(now: datetime) -> Path:
    return V2_DIR / now.strftime("%Y") / now.strftime("%m") / now.strftime("%Y-%m-%d.csv")


def log_gap(start: datetime, end: datetime, reason: str):
    """Record lost in-session time. Endpoints are clipped to session hours;
    called only after session_seconds_between() exceeded the threshold."""
    if not in_session(start):
        start = next_session_start(start)
    if not in_session(end):
        end = previous_session_end(end)
    if start >= end:
        return
    append_rows(GAP_LOG, GAP_COLUMNS, [{
        "gap_start": start.isoformat(timespec="seconds"),
        "gap_end": end.isoformat(timespec="seconds"),
        "reason": reason,
    }])
    print(f"[GAP] {start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} ({reason})", flush=True)


def write_heartbeat(now: datetime, polls: int, rows_written: int):
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEARTBEAT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({
        "last_poll": now.isoformat(timespec="seconds"),
        "polls_today": polls,
        "rows_written_today": rows_written,
    }, indent=2))
    os.replace(tmp, HEARTBEAT)


def read_heartbeat() -> datetime | None:
    try:
        data = json.loads(HEARTBEAT.read_text())
        return datetime.fromisoformat(data["last_poll"])
    except Exception:
        return None


# --- Git sync --------------------------------------------------------------------
def git(*args) -> bool:
    try:
        result = subprocess.run(["git", *args], cwd=REPO_DIR, timeout=GIT_TIMEOUT,
                                capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        print(f"[WARN] git {' '.join(args)}: timeout after {GIT_TIMEOUT}s", flush=True)
        return False
    if result.returncode != 0:
        print(f"[WARN] git {' '.join(args)}: {result.stderr.strip()[:200]}", flush=True)
    return result.returncode == 0


def git_sync(now: datetime):
    """Commit and push accumulated v2 data. Failures are non-fatal, data
    stays local and the next sync retries."""
    if not V2_DIR.exists():
        return  # nothing recorded yet, git add would fatal on the pathspec

    # Recover from a rebase a previous sync (or crash) left behind.
    for state_dir in (".git/rebase-merge", ".git/rebase-apply"):
        if (REPO_DIR / state_dir).exists():
            print("[WARN] leftover rebase state, aborting it", flush=True)
            git("rebase", "--abort")
            break

    git("add", "data/kase/v2")
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_DIR)
    if staged.returncode == 0:
        return  # nothing new
    if not git("commit", "-m", f"data: v2 {now.strftime('%Y-%m-%d %H:%M')}"):
        return
    if git("pull", "--rebase"):
        git("push")
    else:
        # Conflicted or interrupted rebase would wedge every later sync.
        git("rebase", "--abort")


# --- Main loop -------------------------------------------------------------------
def run_loop():
    print(f"KASE phone recorder starting, repo {REPO_DIR}", flush=True)

    # Last known-good poll, surviving restarts via the heartbeat file. Gap
    # rows are written on the first successful poll after any dark period,
    # never at startup, so a crash-restart loop can't spam duplicates.
    last_success = read_heartbeat()
    last_fp: dict[tuple, tuple] = {}
    last_sync = time.monotonic()
    now = datetime.now(TZ_ALMATY)
    current_day = now.strftime("%Y-%m-%d")
    polls_today = 0
    rows_today = 0

    while True:
        now = datetime.now(TZ_ALMATY)

        if not in_session(now):
            git_sync(now)  # flush whatever the session left behind
            nxt = next_session_start(now)
            print(f"Session closed. Sleeping until {nxt:%Y-%m-%d %H:%M} Almaty.", flush=True)
            while datetime.now(TZ_ALMATY) < nxt:
                time.sleep(min(300, max(1, (nxt - datetime.now(TZ_ALMATY)).total_seconds())))
            last_fp.clear()  # last_success is kept: it anchors cross-session gap detection
            continue

        if now.strftime("%Y-%m-%d") != current_day:
            current_day = now.strftime("%Y-%m-%d")
            last_fp.clear()
            polls_today = 0
            rows_today = 0

        poll_time = now.isoformat(timespec="seconds")
        rows = poll(poll_time)

        if rows is None:
            # Total fetch failure (no network / API down). The gap is logged
            # when connectivity returns.
            print(f"[WARN] poll failed entirely at {poll_time}", flush=True)
        else:
            if last_success is not None:
                lost = session_seconds_between(last_success, now)
                if lost > GAP_THRESHOLD_SECONDS:
                    log_gap(last_success, now, "recorder offline or no network")
            last_success = now
            polls_today += 1

            changed = []
            for row in rows:
                key = (row["code"], row["board"])
                fp = fingerprint(row)
                if last_fp.get(key) != fp:
                    check_invariants(row, last_fp.get(key))
                    last_fp[key] = fp
                    changed.append(row)
            if changed:
                append_rows(day_csv_path(now), CSV_COLUMNS, changed)
                rows_today += len(changed)
            write_heartbeat(now, polls_today, rows_today)

        if time.monotonic() - last_sync >= SYNC_SECONDS:
            git_sync(now)
            last_sync = time.monotonic()

        time.sleep(POLL_SECONDS)


def run_test():
    now = datetime.now(TZ_ALMATY)
    print(f"Test poll at {now:%Y-%m-%d %H:%M:%S} Almaty (in_session={in_session(now)})")
    rows = poll(now.isoformat(timespec="seconds"))
    if rows is None:
        print("FAIL: all three endpoints unreachable")
        raise SystemExit(1)
    equities = [r for r in rows if not str(r["board"]).startswith("FX")]
    fx = [r for r in rows if str(r["board"]).startswith("FX")]
    print(f"OK: {len(equities)} equity rows, {len(fx)} FX rows. Nothing written.")
    for r in rows[:3] + fx[:2]:
        print(" ", r)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true",
                        help="One poll, print parsed rows, write nothing")
    args = parser.parse_args()
    if args.test:
        run_test()
    else:
        run_loop()
