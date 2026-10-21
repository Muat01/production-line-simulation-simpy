"""
Interactive production line simulator (digital-twin style what-if tool).

Run:  streamlit run app.py
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from run_experiments import SCENARIOS, ci95
from simulation import StationConfig, default_line, run_simulation

st.set_page_config(page_title="Production Line Simulator", page_icon="🏭", layout="wide")

STATE_COLORS = {"Processing": "#00d4aa", "Blocked": "#ffa502", "Starved": "#3d8eff", "Down (failure)": "#ff4757"}
STATE_KEYS = {"Processing": "busy_pct", "Blocked": "blocked_pct", "Starved": "starved_pct", "Down (failure)": "down_pct"}

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.8rem; }
.small-note { font-size: 12px; color: #8b92a8; }
</style>
""", unsafe_allow_html=True)


# ─── Session-state helpers (presets fill the widgets) ───────────────────────
def station_fields(cfg: StationConfig) -> dict:
    return dict(machines=cfg.machines, mean_time=cfg.mean_time, cv=cfg.cv,
                mtbf=float(cfg.mtbf or 0.0), mttr=float(cfg.mttr),
                buffer_size=cfg.buffer_size, scrap=cfg.scrap_rate * 100.0)


def apply_preset(name: str) -> None:
    for cfg in SCENARIOS[name]():
        for key, value in station_fields(cfg).items():
            st.session_state[f"{cfg.name}_{key}"] = value


def on_preset_change() -> None:
    apply_preset(st.session_state["preset"])


if "initialized" not in st.session_state:
    apply_preset("Baseline")
    st.session_state["initialized"] = True

# ─── Sidebar ────────────────────────────────────────────────────────────────
station_names = [c.name for c in default_line()]

with st.sidebar:
    st.markdown("### 🏭 Line settings")
    st.selectbox("Start from a preset scenario", list(SCENARIOS.keys()),
                 key="preset", on_change=on_preset_change)
    st.caption("Presets fill the controls below. Then adjust anything you like.")

    configs: list[StationConfig] = []
    for name in station_names:
        with st.expander(name, expanded=(name == "Machining")):
            k = lambda f: f"{name}_{f}"
            machines = st.number_input("Machines", 1, 6, key=k("machines"), step=1)
            mean_time = st.number_input("Mean processing time (min)", 0.5, 20.0, key=k("mean_time"), step=0.1)
            cv = st.slider("Time variability (CV)", 0.05, 1.0, key=k("cv"), step=0.05)
            mtbf = st.number_input("MTBF, operating min (0 = no failures)", 0.0, 2000.0, key=k("mtbf"), step=10.0)
            mttr = st.number_input("MTTR, repair min", 0.0, 200.0, key=k("mttr"), step=1.0)
            buffer_size = st.number_input("Input buffer size", 1, 50, key=k("buffer_size"), step=1)
            scrap = st.slider("Scrap rate (%)", 0.0, 15.0, key=k("scrap"), step=0.5)
            configs.append(StationConfig(
                name=name, machines=int(machines), mean_time=float(mean_time), cv=float(cv),
                mtbf=float(mtbf) if mtbf > 0 else None, mttr=float(mttr),
                buffer_size=int(buffer_size), scrap_rate=float(scrap) / 100.0))

    st.markdown("### ⚙️ Simulation")
    reps = st.slider("Replications", 5, 50, 15, step=5)
    shifts = st.slider("Run length (8-hour shifts)", 5, 40, 20, step=5)
    seed = st.number_input("Random seed", 0, 99999, 1000, step=1)

# ─── Simulation (cached) ────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def simulate(cfgs: tuple, reps: int, shifts: int, seed: int) -> dict:
    sim_time = shifts * 480.0
    warmup = min(960.0, sim_time * 0.1)
    runs = [run_simulation(list(cfgs), sim_time, warmup, seed=seed + r) for r in range(reps)]
    thr = np.array([r["throughput_per_hr"] for r in runs])
    states = {}
    for n in runs[0]["stations"]:
        states[n] = {k: float(np.mean([r["stations"][n][k] for r in runs]))
                     for k in ("busy_pct", "blocked_pct", "starved_pct", "down_pct", "failures")}
    return {
        "thr": float(thr.mean()), "thr_ci": float(ci95(thr)),
        "wip": float(np.mean([r["avg_wip"] for r in runs])),
        "flow": float(np.nanmean([r["avg_flow_time_min"] for r in runs])),
        "scrap": float(np.mean([r["scrapped_parts"] for r in runs])),
        "good": float(np.mean([r["good_parts"] for r in runs])),
        "states": states,
    }


# ─── Header ─────────────────────────────────────────────────────────────────
st.title("🏭 Production Line Simulator")
st.markdown(
    "Discrete-event simulation (SimPy) of a four-station line with breakdowns, finite buffers "
    "and scrap. Change the settings on the left and compare your line with the baseline."
)

run_clicked = st.button("▶ Run simulation", type="primary")
if run_clicked:
    st.session_state["last_cfgs"] = tuple(configs)
    st.session_state["last_params"] = (reps, shifts, int(seed))

if "last_cfgs" not in st.session_state:
    st.info("Press **Run simulation** to simulate the current settings.")
    st.stop()

cfgs = st.session_state["last_cfgs"]
p_reps, p_shifts, p_seed = st.session_state["last_params"]

with st.spinner("Simulating..."):
    res = simulate(cfgs, p_reps, p_shifts, p_seed)
    base = simulate(tuple(default_line()), p_reps, p_shifts, p_seed)

if tuple(configs) != cfgs or (reps, shifts, int(seed)) != st.session_state["last_params"]:
    st.warning("Settings changed since the last run. Press **Run simulation** to update the results.")

# ─── KPIs ───────────────────────────────────────────────────────────────────
d_thr = (res["thr"] / base["thr"] - 1) * 100 if base["thr"] else 0.0
c1, c2, c3, c4 = st.columns(4)
c1.metric("Throughput (good parts/h)", f"{res['thr']:.2f}", f"{d_thr:+.1f}% vs baseline")
c2.metric("Average WIP (parts)", f"{res['wip']:.1f}", f"{res['wip'] - base['wip']:+.1f} vs baseline", delta_color="inverse")
c3.metric("Flow time (min)", f"{res['flow']:.1f}", f"{res['flow'] - base['flow']:+.1f} vs baseline", delta_color="inverse")
c4.metric("Scrapped parts / run", f"{res['scrap']:.0f}", f"{res['scrap'] - base['scrap']:+.0f} vs baseline", delta_color="inverse")
st.caption(f"Throughput 95% CI: ±{res['thr_ci']:.2f} parts/h · {p_reps} replications × {p_shifts} shifts")

# ─── Station states + bottleneck ────────────────────────────────────────────
left, right = st.columns([3, 2])

with left:
    st.subheader("Machine state by station")
    fig = go.Figure()
    names = list(res["states"].keys())
    for label, key in STATE_KEYS.items():
        fig.add_trace(go.Bar(y=names, x=[res["states"][n][key] for n in names], name=label,
                             orientation="h", marker_color=STATE_COLORS[label],
                             hovertemplate="%{y}: %{x:.1f}%<extra>" + label + "</extra>"))
    fig.update_layout(barmode="stack", height=320, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_title="% of machine time", yaxis=dict(autorange="reversed"),
                      legend=dict(orientation="h", y=-0.25), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("Bottleneck")
    load = {n: s["busy_pct"] + s["down_pct"] for n, s in res["states"].items()}
    bottleneck = max(load, key=load.get)
    st.success(f"**{bottleneck}** is the bottleneck ({load[bottleneck]:.0f}% of its time busy or down).")
    st.markdown(
        "<div class='small-note'>The bottleneck is the station that is almost never idle. "
        "Stations before it get <b>blocked</b>, stations after it get <b>starved</b>. "
        "Improving any other station barely changes throughput.</div>", unsafe_allow_html=True)

    cap_rows = []
    for c in cfgs:
        availability = 1.0 if not c.mtbf else c.mtbf / (c.mtbf + c.mttr)
        nominal = c.machines * 60.0 / c.mean_time
        cap_rows.append({"Station": c.name,
                         "Nominal (parts/h)": round(nominal, 1),
                         "With failures (parts/h)": round(nominal * availability, 1)})
    st.markdown("**Capacity check**")
    st.dataframe(pd.DataFrame(cap_rows), hide_index=True, width="stretch")

# ─── Comparison table ───────────────────────────────────────────────────────
st.subheader("Your line vs baseline")
cmp_df = pd.DataFrame({
    "KPI": ["Throughput (parts/h)", "Average WIP", "Flow time (min)", "Scrapped parts / run"],
    "Baseline": [base["thr"], base["wip"], base["flow"], base["scrap"]],
    "Your line": [res["thr"], res["wip"], res["flow"], res["scrap"]],
})
cmp_df["Change (%)"] = (cmp_df["Your line"] / cmp_df["Baseline"] - 1) * 100
st.dataframe(cmp_df.style.format({"Baseline": "{:.2f}", "Your line": "{:.2f}", "Change (%)": "{:+.1f}%"}),
             hide_index=True, width="stretch")

st.caption(
    "Parameters are illustrative assumptions, not measurements from a real factory. "
    "Academic project · Muatasem Hadi · Telkom University · "
    "[Source code](https://github.com/Muat01/production-line-simulation-simpy)"
)
