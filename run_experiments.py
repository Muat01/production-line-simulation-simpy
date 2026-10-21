"""
Run what-if scenarios on the production line and compare them.

Usage:
    python run_experiments.py              # 30 replications per scenario
    python run_experiments.py --reps 50
"""
from __future__ import annotations

import argparse
import math
import os
from dataclasses import replace
from typing import Callable, Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from simulation import StationConfig, default_line, run_simulation

OUT_RESULTS = "results"
OUT_DOCS = "docs"

# Two-sided 95% t critical values (degrees of freedom -> t)
T_CRIT = {9: 2.262, 19: 2.093, 29: 2.045, 39: 2.023, 49: 2.010}


# ─── Scenarios ──────────────────────────────────────────────────────────────
def edit(line: List[StationConfig], name: str, **changes) -> List[StationConfig]:
    return [replace(s, **changes) if s.name == name else s for s in line]


def baseline() -> List[StationConfig]:
    return default_line()


def bigger_buffers() -> List[StationConfig]:
    return [replace(s, buffer_size=15) for s in default_line()]


def extra_cnc_machine() -> List[StationConfig]:
    return edit(default_line(), "Machining", machines=3)


def predictive_maintenance() -> List[StationConfig]:
    """Assumption: condition monitoring avoids half of the unplanned failures
    (MTBF x2) and planned repairs are 30% shorter (MTTR x0.7)."""
    out = []
    for s in default_line():
        if s.mtbf is not None:
            s = replace(s, mtbf=s.mtbf * 2.0, mttr=s.mttr * 0.7)
        out.append(s)
    return out


def faster_cnc() -> List[StationConfig]:
    """Assumption: process improvement cuts CNC cycle time by 10%."""
    base = default_line()
    cnc = next(s for s in base if s.name == "Machining")
    return edit(base, "Machining", mean_time=cnc.mean_time * 0.9)


def pdm_plus_machine() -> List[StationConfig]:
    line = predictive_maintenance()
    return edit(line, "Machining", machines=3)


SCENARIOS: Dict[str, Callable[[], List[StationConfig]]] = {
    "Baseline": baseline,
    "Bigger buffers": bigger_buffers,
    "CNC cycle -10%": faster_cnc,
    "Predictive maintenance": predictive_maintenance,
    "+1 CNC machine": extra_cnc_machine,
    "PdM + 1 CNC": pdm_plus_machine,
}


# ─── Statistics ─────────────────────────────────────────────────────────────
def ci95(values: np.ndarray) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    t = T_CRIT.get(n - 1, 1.96)
    return t * values.std(ddof=1) / math.sqrt(n)


def run_scenario(name: str, reps: int, sim_time: float, warmup: float) -> dict:
    cfg = SCENARIOS[name]()
    runs = [run_simulation(cfg, sim_time, warmup, seed=1000 + r) for r in range(reps)]
    return {"name": name, "runs": runs}


def summarize(results: List[dict]) -> pd.DataFrame:
    rows = []
    for res in results:
        runs = res["runs"]
        thr = np.array([r["throughput_per_hr"] for r in runs])
        wip = np.array([r["avg_wip"] for r in runs])
        flow = np.array([r["avg_flow_time_min"] for r in runs])
        scrap = np.array([r["scrapped_parts"] for r in runs])
        rows.append({
            "Scenario": res["name"],
            "Throughput (parts/h)": thr.mean(),
            "Throughput ±95% CI": ci95(thr),
            "Avg WIP (parts)": wip.mean(),
            "Avg flow time (min)": flow.mean(),
            "Scrapped parts": scrap.mean(),
        })
    df = pd.DataFrame(rows)
    base = df.loc[df["Scenario"] == "Baseline", "Throughput (parts/h)"].iloc[0]
    df["Δ vs baseline (%)"] = (df["Throughput (parts/h)"] / base - 1.0) * 100.0
    return df


def station_states(result: dict) -> pd.DataFrame:
    names = list(result["runs"][0]["stations"].keys())
    rows = []
    for n in names:
        row = {"Station": n}
        for k in ("busy_pct", "blocked_pct", "starved_pct", "down_pct", "failures"):
            row[k] = np.mean([r["stations"][n][k] for r in result["runs"]])
        rows.append(row)
    return pd.DataFrame(rows)


# ─── Charts ─────────────────────────────────────────────────────────────────
PALETTE = {"busy": "#00a98a", "blocked": "#ffa502", "starved": "#3d8eff", "down": "#ff4757"}


def plot_throughput(df: pd.DataFrame, path: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.8))
    colors = ["#8b92a8"] + ["#00a98a"] * (len(df) - 1)
    bars = ax.bar(df["Scenario"], df["Throughput (parts/h)"],
                  yerr=df["Throughput ±95% CI"], capsize=4, color=colors)
    for bar, delta in zip(bars, df["Δ vs baseline (%)"]):
        if abs(delta) > 0.05:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.6,
                    f"{delta:+.1f}%", ha="center", fontsize=9, fontweight="bold")
    ax.set_ylabel("Good parts per hour")
    ax.set_title("Throughput by scenario (mean ± 95% CI)")
    ax.set_ylim(0, df["Throughput (parts/h)"].max() * 1.25)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_station_states(df: pd.DataFrame, title: str, path: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.2))
    left = np.zeros(len(df))
    for key, label in (("busy_pct", "Processing"), ("blocked_pct", "Blocked"),
                       ("starved_pct", "Starved"), ("down_pct", "Down (failure)")):
        vals = df[key].to_numpy()
        ax.barh(df["Station"], vals, left=left, label=label,
                color=PALETTE[key.replace("_pct", "")])
        left += vals
    ax.invert_yaxis()
    ax.set_xlabel("% of machine time")
    ax.set_title(title)
    ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.18), frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_wip_vs_throughput(df: pd.DataFrame, path: str) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    ax.scatter(df["Avg WIP (parts)"], df["Throughput (parts/h)"], s=90, color="#3d8eff")
    for _, r in df.iterrows():
        ax.annotate(r["Scenario"], (r["Avg WIP (parts)"], r["Throughput (parts/h)"]),
                    textcoords="offset points", xytext=(6, 6), fontsize=8)
    ax.set_xlabel("Average WIP (parts)")
    ax.set_ylabel("Throughput (parts/h)")
    ax.set_title("Throughput vs work-in-process")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


# ─── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=30, help="replications per scenario")
    parser.add_argument("--sim-time", type=float, default=9600.0, help="minutes per run (20 shifts x 8h)")
    parser.add_argument("--warmup", type=float, default=960.0, help="warm-up minutes discarded")
    args = parser.parse_args()

    os.makedirs(OUT_RESULTS, exist_ok=True)
    os.makedirs(OUT_DOCS, exist_ok=True)

    results = []
    for name in SCENARIOS:
        print(f"Running: {name} ({args.reps} replications)...")
        results.append(run_scenario(name, args.reps, args.sim_time, args.warmup))

    summary = summarize(results)
    summary.round(2).to_csv(os.path.join(OUT_RESULTS, "scenario_summary.csv"), index=False)
    print("\n" + summary.round(2).to_string(index=False))

    plot_throughput(summary, os.path.join(OUT_DOCS, "throughput_by_scenario.png"))
    plot_wip_vs_throughput(summary, os.path.join(OUT_DOCS, "wip_vs_throughput.png"))

    base_states = station_states(results[0])
    base_states.round(2).to_csv(os.path.join(OUT_RESULTS, "baseline_station_states.csv"), index=False)
    plot_station_states(base_states, "Baseline: machine state by station",
                        os.path.join(OUT_DOCS, "baseline_station_states.png"))

    print(f"\nSaved tables to ./{OUT_RESULTS}/ and charts to ./{OUT_DOCS}/")


if __name__ == "__main__":
    main()
