"""
generate_dashboard.py
---------------------
Renders the RFM dashboard to high-resolution PNGs and a multi-page PDF, so the
analysis can be reviewed without opening Power BI.

Inputs : data/clean/online_retail_clean.csv, data/clean/rfm_segments.csv
Outputs: reports/*.png, reports/rfm_dashboard.pdf

Usage:
    python generate_dashboard.py
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import matplotlib.dates as mdates
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from matplotlib.patches import FancyBboxPatch

# --- design tokens -----------------------------------------------------------
SURFACE = "#fcfcfb"
TILE_BG = "#f2f1ee"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8984"
GRID = "#e3e2de"
SERIES_1 = "#2a78d6"   # blue
SERIES_2 = "#eb6834"   # orange
SERIES_3 = "#1baf7a"   # aqua
NEUTRAL = "#c9c8c3"
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SEQ_CMAP = LinearSegmentedColormap.from_list("seq_blue", BLUE_RAMP)
DPI = 200
CCY = "£"

SEGMENT_ORDER = [
    "Champions", "Loyal Customers", "Potential Loyalist", "New Customers",
    "Promising", "Needs Attention", "About To Sleep", "At Risk",
    "Cannot Lose Them", "Hibernating", "Lost",
]

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans",
    "text.color": INK_PRIMARY,
    "axes.labelcolor": INK_SECONDARY,
    "xtick.color": INK_SECONDARY,
    "ytick.color": INK_SECONDARY,
    "axes.edgecolor": GRID,
    "axes.linewidth": 0.8,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.titlesize": 12,
})


def money(value: float) -> str:
    """Compact currency label."""
    if abs(value) >= 1_000_000:
        return f"{CCY}{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{CCY}{value / 1_000:.0f}K"
    return f"{CCY}{value:,.0f}"


def strip_axes(ax, keep=("left", "bottom")):
    for side in ("top", "right", "left", "bottom"):
        if side not in keep:
            ax.spines[side].set_visible(False)
    ax.tick_params(length=0)


def panel_title(ax, title, subtitle=None):
    ax.set_title(title, loc="left", color=INK_PRIMARY, fontweight="bold", pad=14 if subtitle else 8)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9,
                color=INK_MUTED, va="bottom")


def ink_on(color) -> str:
    """Pick readable text colour for a filled cell."""
    r, g, b = to_rgb(color)
    return INK_PRIMARY if (0.299 * r + 0.587 * g + 0.114 * b) > 0.6 else "#ffffff"


# --- panels ------------------------------------------------------------------
def kpi_row(fig, gs, kpis):
    for idx, (label, value, note) in enumerate(kpis):
        ax = fig.add_subplot(gs[0, idx])
        ax.set_axis_off()
        ax.add_patch(FancyBboxPatch((0.01, 0.06), 0.98, 0.88, transform=ax.transAxes,
                                    boxstyle="round,pad=0.01,rounding_size=0.04",
                                    facecolor=TILE_BG, edgecolor="none", zorder=0))
        ax.text(0.06, 0.70, label.upper(), transform=ax.transAxes, fontsize=9.5,
                color=INK_SECONDARY)
        ax.text(0.06, 0.34, value, transform=ax.transAxes, fontsize=27,
                color=INK_PRIMARY, fontweight="bold")
        ax.text(0.06, 0.16, note, transform=ax.transAxes, fontsize=9, color=INK_MUTED)


def customers_by_segment(ax, seg):
    data = seg.sort_values("customers")
    bars = ax.barh(data.index, data["customers"], height=0.62,
                   color=[SERIES_1 if s == "Champions" else NEUTRAL for s in data.index])
    for bar, value in zip(bars, data["customers"]):
        ax.text(bar.get_width() + max(data["customers"]) * 0.015, bar.get_y() + bar.get_height() / 2,
                f"{value:,}", va="center", fontsize=9, color=INK_SECONDARY)
    ax.set_xlim(0, max(data["customers"]) * 1.18)
    ax.set_xticks([])
    ax.xaxis.set_visible(False)
    strip_axes(ax, keep=())
    panel_title(ax, "Customers by segment", "Champions highlighted")


def revenue_by_segment(ax, seg):
    data = seg.sort_values("revenue")
    vmax = data["revenue"].max()
    shades = [SEQ_CMAP(0.30 + 0.62 * (v / vmax) ** 0.45) for v in data["revenue"]]
    bars = ax.barh(data.index, data["revenue"], height=0.62, color=shades)
    for bar, (name, row) in zip(bars, data.iterrows()):
        ax.text(bar.get_width() + vmax * 0.015, bar.get_y() + bar.get_height() / 2,
                f"{money(row['revenue'])}  \u00b7  {row['pct_revenue']}%",
                va="center", fontsize=9, color=INK_SECONDARY,
                fontweight="bold" if name == "Champions" else "normal")
    ax.set_xlim(0, vmax * 1.26)
    ax.xaxis.set_visible(False)
    strip_axes(ax, keep=())
    panel_title(ax, "Revenue by segment",
                "Darker = more revenue  \u00b7  share of total on each bar")


def monthly_trend(ax, fact):
    series = (fact.set_index("InvoiceDate")["Total_Price"]
                  .resample("MS").sum())
    ax.plot(series.index, series.values, color=SERIES_1, linewidth=2,
            marker="o", markersize=5, markerfacecolor=SURFACE, markeredgewidth=2)
    peak = series.idxmax()
    ax.annotate(f"Peak  {money(series.max())}",
                xy=(peak, series.max()), xytext=(-12, 16), textcoords="offset points",
                fontsize=9.5, color=INK_PRIMARY, fontweight="bold", ha="right")
    ax.set_ylim(0, series.max() * 1.28)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: money(v)))
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    strip_axes(ax, keep=("bottom",))
    panel_title(ax, "Monthly revenue",
                "Dec 2010 - Dec 2011  \u00b7  Dec 2011 is a partial month (data ends 9 Dec)")


def rf_heatmap(ax, rfm):
    pivot = (rfm.pivot_table(index="r_score", columns="f_score",
                             values="monetary", aggfunc="sum")
                .reindex(index=[5, 4, 3, 2, 1], columns=[1, 2, 3, 4, 5]).fillna(0))
    counts = (rfm.pivot_table(index="r_score", columns="f_score",
                              values="customer_id", aggfunc="count")
                 .reindex(index=[5, 4, 3, 2, 1], columns=[1, 2, 3, 4, 5]).fillna(0))
    norm = (pivot / pivot.values.max()) ** 0.45
    ax.imshow(norm, cmap=SEQ_CMAP, vmin=0, vmax=1, aspect="auto")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            shade = SEQ_CMAP(norm.iloc[i, j])
            fg = ink_on(shade)
            ax.text(j, i - 0.13, money(pivot.iloc[i, j]), ha="center", va="center",
                    fontsize=9, color=fg, fontweight="bold")
            ax.text(j, i + 0.17, f"{int(counts.iloc[i, j]):,} cust.", ha="center",
                    va="center", fontsize=7.5, color=fg)
    ax.set_xticks(range(5), [f"F{c}" for c in [1, 2, 3, 4, 5]])
    ax.set_yticks(range(5), [f"R{r}" for r in [5, 4, 3, 2, 1]])
    ax.set_xlabel("Frequency score  (5 = buys most often)")
    ax.set_ylabel("Recency score  (5 = most recent)")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)
    panel_title(ax, "RFM grid: revenue by Recency x Frequency",
                "Darker = more revenue")


def recency_monetary_scatter(ax, rfm):
    highlight = {"Champions": SERIES_1, "At Risk": SERIES_2, "Cannot Lose Them": SERIES_3}
    rest = rfm[~rfm["customer_segment"].isin(highlight)]
    ax.scatter(rest["recency"], rest["monetary"], s=np.clip(rest["frequency"] * 2.2, 8, 90),
               color=NEUTRAL, alpha=0.45, linewidths=0, label="Other segments")
    for name, color in highlight.items():
        sub = rfm[rfm["customer_segment"] == name]
        ax.scatter(sub["recency"], sub["monetary"], s=np.clip(sub["frequency"] * 2.2, 8, 90),
                   color=color, alpha=0.75, linewidths=0.6, edgecolors=SURFACE, label=name)
        ax.text(sub["recency"].median(), sub["monetary"].quantile(0.995) * 2.2, name,
                fontsize=10, fontweight="bold", color=color, ha="center",
                bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.5, alpha=0.85))
    ax.set_yscale("log")
    ax.set_ylim(top=rfm["monetary"].max() * 8)
    ax.set_xlabel("Recency  (days since last purchase)")
    ax.set_ylabel("Monetary  (lifetime spend, log scale)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: money(v)))
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    strip_axes(ax, keep=("bottom", "left"))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=4,
              frameon=False, fontsize=9.5, markerscale=1.5, handletextpad=0.4,
              columnspacing=1.8, labelcolor=INK_SECONDARY)
    panel_title(ax, "Where the value sits", "Marker size = purchase frequency")


def pareto(ax, rfm):
    spend = rfm["monetary"].sort_values(ascending=False).values
    cust_pct = np.arange(1, len(spend) + 1) / len(spend) * 100
    rev_pct = np.cumsum(spend) / spend.sum() * 100
    ax.plot(cust_pct, rev_pct, color=SERIES_1, linewidth=2.2)
    ax.fill_between(cust_pct, rev_pct, color=SERIES_1, alpha=0.10)
    at20 = rev_pct[np.searchsorted(cust_pct, 20)]
    ax.plot([20, 20], [0, at20], color=SERIES_2, linewidth=1.6, linestyle="--")
    ax.plot([0, 20], [at20, at20], color=SERIES_2, linewidth=1.6, linestyle="--")
    ax.scatter([20], [at20], s=46, color=SERIES_2, zorder=5, edgecolors=SURFACE, linewidths=1.5)
    ax.text(22, at20 - 7, f"Top 20% of customers\ndrive {at20:.0f}% of revenue",
            fontsize=10, color=INK_PRIMARY, fontweight="bold")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 102)
    ax.set_xlabel("Customers, ranked by spend (%)")
    ax.set_ylabel("Cumulative revenue (%)")
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    strip_axes(ax, keep=("bottom", "left"))
    panel_title(ax, "Revenue concentration", "Pareto curve")


def top_countries(ax, fact):
    data = (fact.groupby("Country")["Total_Price"].sum()
                .sort_values(ascending=False).head(10).sort_values())
    bars = ax.barh(data.index, data.values, height=0.62,
                   color=[SERIES_1 if c == "United Kingdom" else NEUTRAL for c in data.index])
    for bar, value in zip(bars, data.values):
        ax.text(bar.get_width() + data.max() * 0.015, bar.get_y() + bar.get_height() / 2,
                money(value), va="center", fontsize=9, color=INK_SECONDARY)
    ax.set_xlim(0, data.max() * 1.2)
    ax.xaxis.set_visible(False)
    strip_axes(ax, keep=())
    panel_title(ax, "Revenue by country", "Top 10 markets")


# --- pages -------------------------------------------------------------------
def build_page_one(fact, rfm, seg, kpis):
    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(3, 4, height_ratios=[0.60, 1.45, 1.05],
                          left=0.105, right=0.965, top=0.825, bottom=0.075,
                          hspace=0.62, wspace=0.30)
    fig.text(0.105, 0.945, "E-Commerce Customer Segmentation  ·  RFM Dashboard",
             fontsize=21, fontweight="bold", color=INK_PRIMARY)
    fig.text(0.105, 0.905,
             f"UCI Online Retail  ·  {fact['InvoiceDate'].min():%d %b %Y} - "
             f"{fact['InvoiceDate'].max():%d %b %Y}  ·  "
             f"{len(fact):,} cleaned transaction lines",
             fontsize=10.5, color=INK_SECONDARY)
    fig.text(0.965, 0.915, "Page 1 of 2  ·  Overview", fontsize=9.5,
             color=INK_MUTED, ha="right")

    kpi_row(fig, gs, kpis)
    customers_by_segment(fig.add_subplot(gs[1, :2]), seg)
    revenue_by_segment(fig.add_subplot(gs[1, 2:]), seg)
    monthly_trend(fig.add_subplot(gs[2, :]), fact)
    return fig


def build_page_two(fact, rfm):
    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(2, 2, left=0.105, right=0.965, top=0.815, bottom=0.075,
                          hspace=0.58, wspace=0.26)
    fig.text(0.105, 0.945, "RFM Detail  ·  Scores, Concentration and Markets",
             fontsize=21, fontweight="bold", color=INK_PRIMARY)
    fig.text(0.105, 0.905,
             "Recency / Frequency / Monetary quintiles from NTILE(5)  ·  "
             "5 = best on every axis", fontsize=10.5, color=INK_SECONDARY)
    fig.text(0.965, 0.915, "Page 2 of 2  ·  Detail", fontsize=9.5,
             color=INK_MUTED, ha="right")

    rf_heatmap(fig.add_subplot(gs[0, 0]), rfm)
    recency_monetary_scatter(fig.add_subplot(gs[0, 1]), rfm)
    pareto(fig.add_subplot(gs[1, 0]), rfm)
    top_countries(fig.add_subplot(gs[1, 1]), fact)
    return fig


def save_panel(func, args, path, figsize=(9, 5.6), bottom=0.14):
    fig, ax = plt.subplots(figsize=figsize)
    fig.subplots_adjust(left=0.16, right=0.96, top=0.86, bottom=bottom)
    func(ax, *args)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def main() -> int:
    root = Path(__file__).parent
    reports = root / "reports"
    reports.mkdir(exist_ok=True)

    try:
        fact = pd.read_csv(root / "data/clean/online_retail_clean.csv",
                           parse_dates=["InvoiceDate"])
        rfm = pd.read_csv(root / "data/clean/rfm_segments.csv")
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}\nRun data_cleaning.py and the RFM model first.", file=sys.stderr)
        return 1

    seg = (rfm.groupby("customer_segment")
              .agg(customers=("customer_id", "size"), revenue=("monetary", "sum")))
    seg["pct_customers"] = (100 * seg["customers"] / len(rfm)).round(1)
    seg["pct_revenue"] = (100 * seg["revenue"] / seg["revenue"].sum()).round(1)
    seg = seg.reindex([s for s in SEGMENT_ORDER if s in seg.index])

    revenue = fact["Total_Price"].sum()
    orders = fact["InvoiceNo"].nunique()
    kpis = [
        ("Total revenue", money(revenue), f"{len(fact):,} line items"),
        ("Unique customers", f"{fact['CustomerID'].nunique():,}", "with a valid ID"),
        ("Average order value", f"{CCY}{revenue / orders:,.2f}", f"across {orders:,} orders"),
        ("Champions' revenue share", f"{seg.loc['Champions', 'pct_revenue']:.0f}%",
         f"from {seg.loc['Champions', 'pct_customers']:.0f}% of customers"),
    ]

    page1 = build_page_one(fact, rfm, seg, kpis)
    page2 = build_page_two(fact, rfm)
    page1.savefig(reports / "dashboard_page1_overview.png", dpi=DPI)
    page2.savefig(reports / "dashboard_page2_rfm_detail.png", dpi=DPI)

    with PdfPages(reports / "rfm_dashboard.pdf") as pdf:
        pdf.savefig(page1)
        pdf.savefig(page2)
        meta = pdf.infodict()
        meta["Title"] = "E-Commerce Customer Segmentation - RFM Dashboard"
        meta["Subject"] = "RFM analysis of the UCI Online Retail dataset"
    plt.close(page1)
    plt.close(page2)

    save_panel(customers_by_segment, (seg,), reports / "01_customers_by_segment.png")
    save_panel(revenue_by_segment, (seg,), reports / "02_revenue_by_segment.png")
    save_panel(monthly_trend, (fact,), reports / "03_monthly_revenue.png", figsize=(11, 5))
    save_panel(rf_heatmap, (rfm,), reports / "04_rfm_grid.png")
    save_panel(recency_monetary_scatter, (rfm,), reports / "05_recency_vs_monetary.png",
               bottom=0.24)
    save_panel(pareto, (rfm,), reports / "06_revenue_concentration.png")
    save_panel(top_countries, (fact,), reports / "07_revenue_by_country.png")

    for item in sorted(reports.iterdir()):
        print(f"  {item.relative_to(root)}  ({item.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
