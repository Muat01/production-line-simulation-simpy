"""Unit tests for the SimPy production-line model.

The model is stochastic, so the tests assert the properties a discrete-event
model must hold (conservation, determinism under a seed, Little's law) rather
than exact output values, and use long runs where a mean is compared.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation import StationConfig, default_line, run_simulation  # noqa: E402

STATES = ["busy_pct", "blocked_pct", "starved_pct", "down_pct"]


def line(**overrides):
    """A short deterministic line: no failures, no scrap, fixed times."""
    base = dict(machines=1, cv=0.0, mtbf=None, mttr=0.0, buffer_size=5, scrap_rate=0.0)
    return [
        StationConfig("A", mean_time=2.0, **{**base, **overrides.get("A", {})}),
        StationConfig("B", mean_time=4.0, **{**base, **overrides.get("B", {})}),
        StationConfig("C", mean_time=2.0, **{**base, **overrides.get("C", {})}),
    ]


@pytest.fixture(scope="module")
def baseline():
    return run_simulation(default_line(), sim_time=9600.0, warmup=960.0, seed=1)


# ─── Reproducibility ─────────────────────────────────────────────────────────

def test_the_same_seed_gives_the_same_run():
    a = run_simulation(default_line(), sim_time=2400, warmup=240, seed=7)
    b = run_simulation(default_line(), sim_time=2400, warmup=240, seed=7)
    assert a["throughput_per_hr"] == b["throughput_per_hr"]
    assert a["good_parts"] == b["good_parts"]
    assert a["avg_wip"] == b["avg_wip"]


def test_different_seeds_give_different_runs():
    a = run_simulation(default_line(), sim_time=2400, warmup=240, seed=1)
    b = run_simulation(default_line(), sim_time=2400, warmup=240, seed=2)
    assert a["good_parts"] != b["good_parts"], "a stochastic model should not repeat across seeds"


# ─── Bookkeeping ─────────────────────────────────────────────────────────────

def test_every_station_accounts_for_all_of_its_time(baseline):
    for name, stats in baseline["stations"].items():
        assert sum(stats[s] for s in STATES) == pytest.approx(100.0, abs=0.01), name


def test_results_are_finite_and_non_negative(baseline):
    assert baseline["good_parts"] > 0
    assert baseline["avg_wip"] > 0
    assert baseline["avg_flow_time_min"] > 0
    assert baseline["scrapped_parts"] >= 0


def test_a_part_cannot_leave_a_station_it_never_entered(baseline):
    counts = [s["processed"] for s in baseline["stations"].values()]
    for upstream, downstream in zip(counts, counts[1:]):
        assert downstream <= upstream


# ─── Physical limits ─────────────────────────────────────────────────────────

def test_throughput_never_beats_the_bottleneck_rate():
    # B is the slowest station: one machine, 4 minutes per part = 15 parts/hour.
    res = run_simulation(line(), sim_time=4800, warmup=480, seed=3)
    assert res["throughput_per_hr"] <= 15.0 + 1e-6
    assert res["throughput_per_hr"] > 14.0, "a deterministic line should reach its bottleneck rate"


def test_the_bottleneck_is_the_busiest_station():
    res = run_simulation(line(), sim_time=4800, warmup=480, seed=3)
    busiest = max(res["stations"], key=lambda n: res["stations"][n]["busy_pct"])
    assert busiest == "B"
    assert res["stations"]["B"]["busy_pct"] > 99.0


def test_the_station_before_the_bottleneck_is_blocked_and_the_one_after_is_starved():
    res = run_simulation(line(), sim_time=4800, warmup=480, seed=3)
    assert res["stations"]["A"]["blocked_pct"] > 10.0
    assert res["stations"]["C"]["starved_pct"] > 10.0


def test_littles_law_holds(baseline):
    # WIP = throughput x flow time, with throughput per hour and flow time in minutes.
    expected = baseline["throughput_per_hr"] / 60.0 * baseline["avg_flow_time_min"]
    assert baseline["avg_wip"] == pytest.approx(expected, rel=0.15)


# ─── Levers behave the way the model claims ──────────────────────────────────

def test_a_second_machine_on_the_bottleneck_raises_throughput():
    before = run_simulation(line(), sim_time=4800, warmup=480, seed=5)
    after = run_simulation(line(B={"machines": 2}), sim_time=4800, warmup=480, seed=5)
    assert after["throughput_per_hr"] > before["throughput_per_hr"] * 1.2


def test_bigger_buffers_raise_work_in_process():
    small = run_simulation(default_line(), sim_time=4800, warmup=480, seed=11)
    big = [StationConfig(**{**c.__dict__, "buffer_size": 20}) for c in default_line()]
    large = run_simulation(big, sim_time=4800, warmup=480, seed=11)
    assert large["avg_wip"] > small["avg_wip"]


def test_removing_breakdowns_raises_throughput():
    perfect = [StationConfig(**{**c.__dict__, "mtbf": None, "mttr": 0.0}) for c in default_line()]
    assert (run_simulation(perfect, sim_time=4800, warmup=480, seed=9)["throughput_per_hr"]
            > run_simulation(default_line(), sim_time=4800, warmup=480, seed=9)["throughput_per_hr"])


# ─── Failures and scrap ──────────────────────────────────────────────────────

def test_a_station_without_an_mtbf_never_fails_and_is_never_down(baseline):
    inspection = baseline["stations"]["Inspection"]
    assert inspection["failures"] == 0
    assert inspection["down_pct"] == 0.0


def test_a_station_with_an_mtbf_does_fail(baseline):
    assert baseline["stations"]["Machining"]["failures"] > 0
    assert baseline["stations"]["Machining"]["down_pct"] > 0.0


def test_no_scrap_when_the_scrap_rate_is_zero():
    assert run_simulation(line(), sim_time=2400, warmup=240, seed=4)["scrapped_parts"] == 0


def test_scrap_appears_and_costs_throughput():
    clean = run_simulation(line(), sim_time=4800, warmup=480, seed=6)
    lossy = run_simulation(line(C={"scrap_rate": 0.30}), sim_time=4800, warmup=480, seed=6)
    assert lossy["scrapped_parts"] > 0
    assert lossy["throughput_per_hr"] < clean["throughput_per_hr"]


# ─── Warm-up ─────────────────────────────────────────────────────────────────

def test_the_warmup_period_is_excluded_from_the_statistics():
    full = run_simulation(line(), sim_time=4800, warmup=0.0, seed=8)
    warmed = run_simulation(line(), sim_time=4800, warmup=480.0, seed=8)
    # The line starts empty, so counting the fill-up drags the average down.
    assert warmed["throughput_per_hr"] > full["throughput_per_hr"]
