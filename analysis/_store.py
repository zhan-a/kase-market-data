"""
One place that decides where the data lives.

The analysis scripts read up to three inputs: the 1-minute bar store, the daily
companion series, and the board recordings. The two stores are not in git. Each is
resolved in this order:

1. the environment variable, KASE_STORE or KASE_DAILY;
2. the directory inside this repository, which is where the fetchers write and
   where a symlink can be placed;
3. the sibling checkout `../trading desk/data`, for a working copy laid out beside
   the other repositories.

The board recordings are committed in the private repository and excluded from the
public copy (data/README.md says why), so a script that needs them stops with a
message when they are absent. Every missing input stops the script at the point of
the missing path, naming what was tried, rather than inside a read.
"""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DERIVED = REPO / "data" / "derived"
BOARD = REPO / "data" / "kase-board-snapshots" / "board-recordings"
PROBE = REPO / "data" / "kase-board-snapshots" / "quote_probe_2026-08-25.csv"


def _pick(env_var, candidates, present, what, marker):
    override = os.environ.get(env_var)
    tried = []
    if override:
        p = Path(override)
        if present(p):
            return p
        tried.append(f"{p} (from {env_var})")
    for p in candidates:
        if present(p):
            return p
        tried.append(str(p))
    raise SystemExit(
        f"{what} was not found. Tried:\n  " + "\n  ".join(tried) +
        f"\nSet {env_var} to the directory containing {marker}, or attach the store as "
        "data/README.md describes."
    )


def store() -> Path:
    """Directory holding kase/intraday/<TICKER>/*.parquet and nasdaq/intraday/KSPI.US/."""
    return _pick(
        "KASE_STORE",
        [REPO / "data", REPO.parent / "trading desk" / "data"],
        lambda p: any((p / "kase" / "intraday").glob("*/*.parquet")),
        "The 1-minute bar store",
        "kase/intraday/<TICKER>/<YYYY-MM>.parquet",
    )


def daily() -> Path:
    """Directory holding the daily companion parquets, one per ticker."""
    return _pick(
        "KASE_DAILY",
        [REPO / "data" / "kase" / "daily"],
        lambda p: (p / "KSPI.KZ.parquet").exists(),
        "The daily companion series",
        "KSPI.KZ.parquet",
    )


def board() -> Path:
    """Directory holding the board recordings, YYYY/MM/YYYY-MM-DD.csv."""
    if any(BOARD.glob("*/*/*.csv")):
        return BOARD
    raise SystemExit(
        f"The board recordings are not in this tree ({BOARD.relative_to(REPO)}). They are "
        "KASE exchange information and are not redistributed; data/README.md explains. The "
        "tables this script writes are committed under data/derived/ as the record of its "
        "output."
    )


def probe() -> Path | None:
    """The live probe file, or None when it is not in this tree."""
    return PROBE if PROBE.exists() else None
