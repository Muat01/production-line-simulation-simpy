"""
MH Emerald & Gold — shared visual identity for the dashboards in this portfolio.

One palette, one type scale and one Plotly layout across every project, so the
apps read as one body of work. Dark is the default surface; gold marks value,
cost and anything the reader must treat as illustrative.
"""

# ─── Tokens ──────────────────────────────────────────────────────────────────
GROUND = "#0E1311"
SURFACE = "#171E1B"
SURFACE_2 = "#1F2824"
LINE = "#2A3530"
GRID = "#232D29"

INK = "#EEF2EF"
INK_SOFT = "#B7C2BC"
INK_MUTED = "#7E8C85"

EMERALD = "#22C98A"   # brand, "better", in control
GOLD = "#E6B94A"      # value, cost, simulated-data marker
STEEL = "#6FA8FF"     # supporting series
ROSE = "#D05A74"
LILAC = "#9479E6"
CRITICAL = "#F0616D"  # always paired with a label, never colour alone

# Fixed categorical order, checked for colour-vision deficiency separation.
CATEGORICAL = [EMERALD, STEEL, GOLD, ROSE, LILAC]

FONT_SANS = "Inter, -apple-system, Segoe UI, sans-serif"
FONT_MONO = "JetBrains Mono, Consolas, monospace"

# Severity scale, dark to light risk.
RISK_COLORS = {
    "CRITICAL": CRITICAL,
    "HIGH": GOLD,
    "MEDIUM": STEEL,
    "LOW": EMERALD,
}

# ─── Plotly ──────────────────────────────────────────────────────────────────
PLOT_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family=FONT_SANS, color=INK_MUTED, size=11),
    margin=dict(l=10, r=10, t=30, b=10),
    showlegend=True,
    legend=dict(font=dict(size=10), bgcolor="rgba(0,0,0,0)"),
    xaxis=dict(gridcolor=GRID, linecolor=LINE, tickfont=dict(size=10)),
    yaxis=dict(gridcolor=GRID, linecolor=LINE, tickfont=dict(size=10)),
)


def layout(**overrides):
    """PLOT_LAYOUT with overrides applied.

    Nested axis and legend dicts are merged rather than replaced, so a caller
    can set one axis property without losing the theme, and no keyword is ever
    passed twice to update_layout.
    """
    merged = dict(PLOT_LAYOUT)
    for key, value in overrides.items():
        if key in ("xaxis", "yaxis", "legend") and isinstance(value, dict):
            merged[key] = {**PLOT_LAYOUT[key], **value}
        else:
            merged[key] = value
    return merged


# ─── Streamlit CSS ───────────────────────────────────────────────────────────
CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap');

html, body, [class*="css"] {{ font-family: {FONT_SANS}; }}
.stApp {{ background: {GROUND}; color: {INK}; }}
section[data-testid="stSidebar"] {{ background: {SURFACE}; border-right: 1px solid {LINE}; }}

h1, h2, h3 {{ color: {INK}; letter-spacing: -0.02em; }}

.mh-title {{ font-size: 1.6rem; font-weight: 800; color: {INK}; letter-spacing: -0.02em; margin-bottom: 2px; }}
.mh-sub {{ font-size: 0.85rem; color: {INK_MUTED}; margin-bottom: 18px; }}
.sec-header {{ font-size: 1.05rem; font-weight: 700; color: {INK}; margin: 6px 0 2px; }}
.sec-sub {{ font-size: 0.8rem; color: {INK_MUTED}; margin-bottom: 14px; }}
.mh-label {{ font-family: {FONT_MONO}; font-size: 0.68rem; letter-spacing: 0.16em; text-transform: uppercase; color: {INK_MUTED}; }}

div[data-testid="stMetric"] {{
    background: {SURFACE}; border: 1px solid {LINE}; border-radius: 14px; padding: 14px 16px;
}}
div[data-testid="stMetricValue"] {{ font-family: {FONT_MONO}; font-weight: 700; color: {INK}; }}
div[data-testid="stMetricLabel"] {{ color: {INK_MUTED}; }}

.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {LINE}; }}
.stTabs [data-baseweb="tab"] {{ background: transparent; color: {INK_MUTED}; border-radius: 10px 10px 0 0; padding: 8px 14px; }}
.stTabs [aria-selected="true"] {{ background: {SURFACE}; color: {INK}; }}

.stButton > button {{
    background: {SURFACE}; color: {INK_SOFT}; border: 1px solid {LINE}; border-radius: 10px; font-weight: 500;
}}
.stButton > button:hover {{ border-color: {EMERALD}; color: {INK}; }}

.mh-note {{
    display: block; padding: 10px 14px; border-radius: 12px; font-size: 0.8rem; line-height: 1.5;
    background: rgba(230,185,74,0.10); border: 1px dashed rgba(230,185,74,0.45); color: {INK_SOFT};
}}
.mh-card {{
    background: {SURFACE}; border: 1px solid {LINE}; border-radius: 16px; padding: 16px 18px; margin-bottom: 12px;
}}
#MainMenu, footer {{ visibility: hidden; }}
</style>
"""

# Streamlit config.toml equivalent of the tokens above, for reference:
#   primaryColor = "#22C98A"
#   backgroundColor = "#0E1311"
#   secondaryBackgroundColor = "#171E1B"
#   textColor = "#EEF2EF"
