#!/usr/bin/env python3
"""
Draw the four figures into figures/. Computes nothing.

Every plotted series is read from data/derived/, written by the analysis
scripts named below; the only numbers in this file are styling and layout.
analysis/check_figure_literals.py enforces that.

  implied_open_monthly.csv        analysis/session_structure.py
  session_bar_density.csv         analysis/session_structure.py
  session_summary.csv             analysis/session_structure.py
  board_staleness.csv             analysis/board_fields.py
  board_liquidity_signature.csv   analysis/board_fields.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
FIGS = ROOT / "figures"

IMPLIED_OPEN = DERIVED / "implied_open_monthly.csv"
DENSITY = DERIVED / "session_bar_density.csv"
SESSION_SUMMARY = DERIVED / "session_summary.csv"
STALENESS = DERIVED / "board_staleness.csv"
SIGNATURE = DERIVED / "board_liquidity_signature.csv"

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 130, "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
})
INK, ACCENT, MUTE = "#222222", "#B03A2E", "#888888"

# layout numbers, so that a number in a plot call is data or a name
MINUTES_PER_HOUR = 60
TZ_CHANGE = pd.Timestamp("2024-03-01")        # Almaty moved from UTC+6 to UTC+5
TICK_1129 = 11 * MINUTES_PER_HOUR + 29        # y ticks of the implied-open figure
TICK_1229 = 12 * MINUTES_PER_HOUR + 29
OPEN_YLIM = (11 * MINUTES_PER_HOUR + 10, 12 * MINUTES_PER_HOUR + 50)
TZ_LABEL_Y = 12 * MINUTES_PER_HOUR + 10
SESSION_OPEN = 11 * MINUTES_PER_HOUR + 30     # KASE continuous session, Almaty
SESSION_CLOSE = 17 * MINUTES_PER_HOUR + 30
OPEN_AUCTION = 11 * MINUTES_PER_HOUR + 29     # labelled minutes of the density figure
CLOSE_AUCTION = 17 * MINUTES_PER_HOUR + 25
QUIET_START = 17 * MINUTES_PER_HOUR + 15
QUIET_END = 17 * MINUTES_PER_HOUR + 24
QUIET_LABEL_Y = 0.55                          # fraction of the tallest bar
DENSITY_TICKS = [11 * MINUTES_PER_HOUR + 30, 13 * MINUTES_PER_HOUR,
                 14 * MINUTES_PER_HOUR + 30, 16 * MINUTES_PER_HOUR,
                 17 * MINUTES_PER_HOUR + 30]
STALENESS_TICKS = range(9 * MINUTES_PER_HOUR, 21 * MINUTES_PER_HOUR, 2 * MINUTES_PER_HOUR)
STALENESS_LABEL_X = 14 * MINUTES_PER_HOUR + 30
PCT_MID = 50
PCT_YLIM = (-5, 105)
BAR_OFFSET = 0.2                              # grouped bars, half the gap


def hhmm(m) -> str:
    return f"{int(m) // MINUTES_PER_HOUR:02d}:{int(m) % MINUTES_PER_HOUR:02d}"


def need(path, script):
    """Read a derived input, or name the script that writes it."""
    if not path.exists():
        print(f"   {path.relative_to(ROOT)} not found; run {script} first")
        return None
    return pd.read_csv(path)


def fig_timezone() -> bool:
    """The defect a price-based check cannot see, and the test that catches it.

    The committed store is correct, so its implied session open is flat at 11:29
    across the boundary. Plotted against it is what a constant-offset conversion
    would have produced: Almaty ran UTC+6 before 2024-03-01, so every earlier bar
    is stored one hour late and the series steps down on exactly that date.
    """
    d = need(IMPLIED_OPEN, "analysis/session_structure.py")
    if d is None:
        return False
    month = pd.to_datetime(d["month"])

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(month, d["constant_offset_minute"], marker="o", ms=2.5, lw=1.0, color=ACCENT,
            label="constant UTC offset (the defect)")
    ax.plot(month, d["median_first_bar_minute"], marker="o", ms=2.5, lw=1.0, color=INK,
            label="timezone database (committed store)")
    ax.axvline(TZ_CHANGE, color=MUTE, lw=1.0, ls="--")
    ax.annotate("Almaty UTC+6 to UTC+5\n2024-03-01", xy=(TZ_CHANGE, TZ_LABEL_Y),
                xytext=(8, 0), textcoords="offset points", color="#666666", fontsize=8)
    ax.set_yticks([TICK_1129, TICK_1229])
    ax.set_yticklabels([hhmm(TICK_1129), hhmm(TICK_1229)])
    ax.set_ylim(*OPEN_YLIM)
    ax.set_ylabel("median first bar (Almaty)")
    ax.legend(frameon=False, fontsize=8, loc="center left")
    ax.set_title("Implied session open, KSPI: the check that detects a wrong time frame",
                 loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGS / "timezone-detection.png")
    plt.close(fig)
    return True


def fig_session() -> bool:
    """Where bars fall inside a session."""
    d = need(DENSITY, "analysis/session_structure.py")
    s = need(SESSION_SUMMARY, "analysis/session_structure.py")
    if d is None or s is None:
        return False
    counts = d.set_index("minute_of_day")["bars"]
    summary = s.set_index("key")["value"]
    n_sessions = int(summary["n_sessions"])
    start = summary["window_start"]

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.bar(counts.index, counts.values, width=1.0, color=INK, linewidth=0)
    for m, lbl in [(OPEN_AUCTION, "opening auction"), (CLOSE_AUCTION, "closing auction")]:
        ax.annotate(lbl, xy=(m, counts.get(m, 0)), xytext=(0, 6), textcoords="offset points",
                    ha="center", fontsize=8, color=ACCENT)
    ax.axvspan(QUIET_START, QUIET_END, color=ACCENT, alpha=0.12)
    ax.annotate("no bar falls here", xy=(QUIET_END, counts.max() * QUIET_LABEL_Y),
                ha="right", fontsize=8, color=ACCENT)
    ax.set_xticks(DENSITY_TICKS)
    ax.set_xticklabels([hhmm(t) for t in DENSITY_TICKS])
    ax.set_ylabel("bars")
    ax.set_xlabel("minute of session (Almaty)")
    ax.set_title(f"Bar density within a session, KSPI, {n_sessions} sessions from {start}",
                 loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGS / "session-structure.png")
    plt.close(fig)
    return True


def fig_staleness() -> bool:
    """Which session the board reports, by time of day."""
    g = need(STALENESS, "analysis/board_fields.py")
    if g is None:
        return False
    g = g.sort_values("bucket_start_minute")
    x = g["bucket_start_minute"]

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(x, g["pct_prev_close"], marker="o", ms=3, lw=1.2, color=INK,
            label="previous session's close only")
    ax.plot(x, g["pct_same_close"], marker="s", ms=3, lw=1.2, color=ACCENT,
            label="same-day close only")
    ax.plot(x, g["pct_both"], marker="^", ms=3, lw=1.0, color=MUTE, ls=":",
            label="both (close unchanged)")
    ax.axvspan(SESSION_OPEN, SESSION_CLOSE, color=MUTE, alpha=0.10)
    ax.annotate("KASE session", xy=(STALENESS_LABEL_X, PCT_MID), ha="center", fontsize=8,
                color="#666666")
    ax.set_xticks(list(STALENESS_TICKS))
    ax.set_xticklabels([hhmm(t) for t in STALENESS_TICKS])
    ax.set_ylabel("% of snapshots")
    ax.set_xlabel("time of poll (Almaty)")
    ax.set_ylim(*PCT_YLIM)
    ax.legend(frameon=False, fontsize=8, loc="center left")
    ax.set_title("Which session the board API reports", loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGS / "board-staleness.png")
    plt.close(fig)
    return True


def fig_liquidity() -> bool:
    """The signature no rule-based price limit can produce."""
    g = need(SIGNATURE, "analysis/board_fields.py")
    if g is None:
        return False
    n_total = int(g["n"].sum())
    x = np.arange(len(g))

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.bar(x - BAR_OFFSET, g["pct_crossed"], width=2 * BAR_OFFSET, color=INK,
           label="bid exceeds ask")
    ax.bar(x + BAR_OFFSET, g["pct_collapsed"], width=2 * BAR_OFFSET, color=ACCENT,
           label="bid = high and ask = low")
    ax.set_xticks(x)
    ax.set_xticklabels(g["deal_bin"].tolist(), fontsize=8)
    ax.set_xlabel("deals in the session")
    ax.set_ylabel("% of instrument-sessions")
    ax.legend(frameon=False, fontsize=8)
    ax.set_title(f"Board quote fields against trading activity, {n_total:,} instrument-sessions",
                 loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGS / "quote-liquidity-signature.png")
    plt.close(fig)
    return True


def main() -> None:
    FIGS.mkdir(exist_ok=True)
    figures = [("timezone-detection", fig_timezone),
               ("session-structure", fig_session),
               ("board-staleness", fig_staleness),
               ("quote-liquidity-signature", fig_liquidity)]
    drawn = 0
    for name, fn in figures:
        if fn():
            drawn += 1
            print(f"wrote figures/{name}.png")
    print(f"{drawn} of {len(figures)} figures drawn")


if __name__ == "__main__":
    main()
