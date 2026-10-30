#!/usr/bin/env python3
"""
What do KASE's `current_bid` / `current_offer` actually mean?

They cannot be live top-of-book: bid exceeds ask on every instrument, every
day, which would be a permanently crossed market. Two hypotheses:

  A. live top-of-book, with the fields swapped
  B. session high-water marks of the order book, the highest bid posted and
     the lowest offer posted so far today

A and B make opposite predictions that one live session separates:

  * Under B the values are MONOTONE within a session (bid only ratchets up,
    offer only ratchets down) and RESET at the open. Under A both move freely
    in both directions.
  * Under B, bid >= the day's highest trade and offer <= the day's lowest
    trade at all times. Under A they straddle the last trade.

What the probe found is in docs/dataset-and-provenance.md, section 4: the
board does not move during the session at all, so a live poll separates
nothing; the fields were identified from the recorded archive instead.

Writes quote_probe_<date>.csv beside this script.
"""

import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Almaty")
URL = "https://kase.kz/api/trade-results/shares/"
WATCH = ["KSPI", "HSBK", "KZAP", "AIRA", "KCEL", "KEGC"]
POLL_SECONDS = 30
OUT = Path(__file__).resolve().parent / f"quote_probe_{datetime.now(TZ):%Y-%m-%d}.csv"

STOP_AT = (13, 0)   # run until 13:00 Almaty, 90 minutes past the open


def poll():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main():
    rows = []
    print(f"Polling every {POLL_SECONDS}s until {STOP_AT[0]:02d}:{STOP_AT[1]:02d} Almaty")
    print(f"Writing {OUT}\n")
    header = "time,code,bid,ask,last,high,low,dealcnt,volkzt,last_deal_date"
    OUT.write_text(header + "\n")

    while True:
        now = datetime.now(TZ)
        if (now.hour, now.minute) >= STOP_AT:
            break
        try:
            data = poll()
        except Exception as e:
            print(f"[WARN] {now:%H:%M:%S} poll failed: {e}", flush=True)
            time.sleep(POLL_SECONDS)
            continue

        line_parts = []
        with open(OUT, "a") as f:
            for item in data:
                if item.get("code") not in WATCH:
                    continue
                f.write(",".join(str(x) for x in [
                    now.isoformat(timespec="seconds"), item["code"],
                    item.get("current_bid"), item.get("current_offer"),
                    item.get("last_deal_price"), item.get("max_price"),
                    item.get("min_price"), item.get("dealcnt"),
                    item.get("volkzt"), item.get("last_deal_date"),
                ]) + "\n")
                if item["code"] == "KSPI":
                    line_parts.append(
                        f"KSPI bid={item.get('current_bid')} ask={item.get('current_offer')} "
                        f"last={item.get('last_deal_price')} deals={item.get('dealcnt')}")
        if line_parts:
            print(f"{now:%H:%M:%S}  {line_parts[0]}", flush=True)
        time.sleep(POLL_SECONDS)

    print(f"\nDone. {OUT}")


if __name__ == "__main__":
    main()
