"""
Discrete-event simulation of a serial production line (SimPy).

Model summary
-------------
* Parts flow through stations in series: Cutting -> CNC Machining -> Assembly -> Inspection.
* Each station has one or more identical machines and a finite input buffer.
  When the next buffer is full, the machine is BLOCKED; when its own buffer is
  empty it is STARVED.
* Processing times are stochastic (gamma distribution with a given mean and CV).
* Machines fail after an exponentially distributed amount of *operating* time
  (MTBF) and are repaired in an exponentially distributed time (MTTR).
* A fraction of parts is scrapped at each station (quality loss).
* Raw material is unlimited, so the line is always loaded and its throughput is
  limited by the bottleneck, breakdowns and blocking/starving effects.

Time unit: minutes.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional

import simpy


# ─── Configuration ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class StationConfig:
    name: str
    machines: int            # number of parallel identical machines
    mean_time: float         # mean processing time per part (min)
    cv: float = 0.25         # coefficient of variation of processing time
    mtbf: Optional[float] = None   # mean operating time between failures (min)
    mttr: float = 0.0        # mean time to repair (min)
    buffer_size: int = 5     # capacity of the INPUT buffer of this station
    scrap_rate: float = 0.0  # probability a processed part is scrapped


def default_line() -> List[StationConfig]:
    """Baseline line. CNC machining is the designed bottleneck."""
    return [
        StationConfig("Cutting",   machines=1, mean_time=2.0, mtbf=400, mttr=10, buffer_size=5, scrap_rate=0.005),
        StationConfig("Machining", machines=2, mean_time=6.0, mtbf=180, mttr=25, buffer_size=5, scrap_rate=0.02),
        StationConfig("Assembly",  machines=1, mean_time=2.6, mtbf=300, mttr=12, buffer_size=5, scrap_rate=0.01),
        StationConfig("Inspection", machines=1, mean_time=2.2, mtbf=None, mttr=0.0, buffer_size=5, scrap_rate=0.03),
    ]


# ─── Model ──────────────────────────────────────────────────────────────────
class Part:
    __slots__ = ("pid", "t_start")

    def __init__(self, pid: int):
        self.pid = pid
        self.t_start: Optional[float] = None  # when the first operation starts


class Station:
    STATES = ("busy", "blocked", "starved", "down")

    def __init__(self, env: simpy.Environment, cfg: StationConfig, index: int,
                 line: "ProductionLine"):
        self.env, self.cfg, self.index, self.line = env, cfg, index, line
        self.inbuf = simpy.Store(env, capacity=cfg.buffer_size)
        self.outbuf: Optional[simpy.Store] = None  # set by the line (None for last station)
        self.time: Dict[str, float] = {s: 0.0 for s in self.STATES}
        self.failures = 0
        self.processed = 0
        for _ in range(cfg.machines):
            env.process(self._machine())

    # -- helpers -------------------------------------------------------------
    def _acc(self, state: str, t0: float, t1: float) -> None:
        """Accumulate time in a state, ignoring the warm-up period."""
        t0 = max(t0, self.line.warmup)
        if t1 > t0:
            self.time[state] += t1 - t0

    def _processing_time(self) -> float:
        cv = self.cfg.cv
        shape = 1.0 / (cv * cv)
        return self.line.rng.gammavariate(shape, self.cfg.mean_time / shape)

    def _time_to_failure(self) -> Optional[float]:
        if self.cfg.mtbf is None:
            return None
        return self.line.rng.expovariate(1.0 / self.cfg.mtbf)

    # -- machine process -----------------------------------------------------
    def _machine(self):
        env, rng, cfg = self.env, self.line.rng, self.cfg
        ttf = self._time_to_failure()
        while True:
            # wait for a part (starved)
            t0 = env.now
            part = yield self.inbuf.get()
            self._acc("starved", t0, env.now)

            if self.index == 0:
                part.t_start = env.now
                self.line.wip += 1

            # process the part, with possible breakdowns
            remaining = self._processing_time()
            while remaining > 0:
                if ttf is not None and ttf <= remaining:
                    t0 = env.now
                    yield env.timeout(ttf)
                    self._acc("busy", t0, env.now)
                    remaining -= ttf
                    repair = rng.expovariate(1.0 / cfg.mttr) if cfg.mttr > 0 else 0.0
                    t0 = env.now
                    yield env.timeout(repair)
                    self._acc("down", t0, env.now)
                    if env.now >= self.line.warmup:
                        self.failures += 1
                    ttf = self._time_to_failure()
                else:
                    t0 = env.now
                    yield env.timeout(remaining)
                    self._acc("busy", t0, env.now)
                    if ttf is not None:
                        ttf -= remaining
                    remaining = 0

            if env.now >= self.line.warmup:
                self.processed += 1

            # quality loss
            if rng.random() < cfg.scrap_rate:
                self.line.wip -= 1
                if env.now >= self.line.warmup:
                    self.line.scrapped += 1
                continue

            # pass the part on (blocked if the next buffer is full)
            if self.outbuf is None:
                self.line.record_exit(part)
            else:
                t0 = env.now
                yield self.outbuf.put(part)
                self._acc("blocked", t0, env.now)


class ProductionLine:
    def __init__(self, env: simpy.Environment, configs: List[StationConfig],
                 warmup: float, seed: int):
        self.env = env
        self.warmup = warmup
        self.rng = random.Random(seed)
        self.wip = 0
        self.good = 0
        self.scrapped = 0
        self.flow_times: List[float] = []
        self.wip_samples: List[float] = []

        self.stations = [Station(env, c, i, self) for i, c in enumerate(configs)]
        for a, b in zip(self.stations, self.stations[1:]):
            a.outbuf = b.inbuf

        env.process(self._source())
        env.process(self._wip_monitor())

    def _source(self):
        pid = 0
        first = self.stations[0].inbuf
        while True:                      # unlimited raw material
            yield first.put(Part(pid))
            pid += 1

    def _wip_monitor(self):
        while True:
            yield self.env.timeout(1.0)
            if self.env.now >= self.warmup:
                self.wip_samples.append(self.wip)

    def record_exit(self, part: Part) -> None:
        self.wip -= 1
        if self.env.now >= self.warmup:
            self.good += 1
            self.flow_times.append(self.env.now - part.t_start)


# ─── Public API ─────────────────────────────────────────────────────────────
def run_simulation(configs: List[StationConfig], sim_time: float = 9600.0,
                   warmup: float = 960.0, seed: int = 1) -> dict:
    """Run one replication and return KPIs (time in minutes)."""
    env = simpy.Environment()
    line = ProductionLine(env, configs, warmup, seed)
    env.run(until=sim_time)

    window = sim_time - warmup
    result = {
        "throughput_per_hr": line.good / window * 60.0,
        "good_parts": line.good,
        "scrapped_parts": line.scrapped,
        "avg_wip": sum(line.wip_samples) / len(line.wip_samples) if line.wip_samples else 0.0,
        "avg_flow_time_min": sum(line.flow_times) / len(line.flow_times) if line.flow_times else float("nan"),
        "stations": {},
    }
    for st in line.stations:
        total = sum(st.time.values()) or 1.0
        result["stations"][st.cfg.name] = {
            **{f"{k}_pct": 100.0 * v / total for k, v in st.time.items()},
            "failures": st.failures,
            "processed": st.processed,
        }
    return result


if __name__ == "__main__":
    res = run_simulation(default_line())
    print(f"Throughput : {res['throughput_per_hr']:.2f} good parts/hour")
    print(f"Avg WIP    : {res['avg_wip']:.1f} parts")
    print(f"Flow time  : {res['avg_flow_time_min']:.1f} min")
    print(f"Scrapped   : {res['scrapped_parts']} parts")
    print("\nStation states (% of machine time):")
    for name, s in res["stations"].items():
        print(f"  {name:<11} busy {s['busy_pct']:5.1f} | blocked {s['blocked_pct']:5.1f} | "
              f"starved {s['starved_pct']:5.1f} | down {s['down_pct']:5.1f} | failures {s['failures']}")
