"""
generate_report.py
------------------
Builds a two-page, resume-ready case study PDF from the RFM outputs.

Usage:
    python generate_report.py --author "Your Name" --github "github.com/you/repo"
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

INK = colors.HexColor("#0b0b0b")
INK_2 = colors.HexColor("#52514e")
INK_MUTED = colors.HexColor("#8a8984")
ACCENT = colors.HexColor("#2a78d6")
ACCENT_DARK = colors.HexColor("#184f95")
WARM = colors.HexColor("#eb6834")
TILE = colors.HexColor("#f2f1ee")
RULE = colors.HexColor("#e3e2de")

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
RAW_ROWS = 541_909  # rows in the UCI source file, before cleaning


def styles():
    base = getSampleStyleSheet()
    s = {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold",
                                fontSize=19, leading=23, alignment=0, textColor=INK,
                                spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10.5,
                                   leading=14, textColor=INK_2),
        "byline": ParagraphStyle("byline", fontName="Helvetica", fontSize=9,
                                 leading=12.5, textColor=INK_MUTED, alignment=2),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=15,
                             textColor=INK, spaceBefore=9, spaceAfter=5),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.6, leading=13.6,
                               textColor=INK_2, alignment=TA_JUSTIFY),
        "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9.6, leading=13.4,
                                 textColor=INK_2, leftIndent=9, bulletIndent=1,
                                 spaceAfter=3.5),
        "kpi_label": ParagraphStyle("kpi_label", fontName="Helvetica", fontSize=7.4,
                                    leading=9, textColor=INK_2),
        "kpi_value": ParagraphStyle("kpi_value", fontName="Helvetica-Bold", fontSize=16,
                                    leading=19, textColor=INK),
        "kpi_note": ParagraphStyle("kpi_note", fontName="Helvetica", fontSize=7.2,
                                   leading=9, textColor=INK_MUTED),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.6, leading=11.4,
                               textColor=INK_2),
        "cell_b": ParagraphStyle("cell_b", fontName="Helvetica-Bold", fontSize=8.6,
                                 leading=11.4, textColor=INK),
        "cap": ParagraphStyle("cap", fontName="Helvetica", fontSize=7.8, leading=10,
                              textColor=INK_MUTED),
    }
    return s


def money(v, decimals=0):
    if abs(v) >= 1_000_000:
        return f"£{v / 1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"£{v / 1_000:.0f}K"
    return f"£{v:,.{decimals}f}"


def kpi_strip(items, st, width):
    cells = []
    for label, value, note in items:
        cells.append(Table([[Paragraph(label.upper(), st["kpi_label"])],
                            [Paragraph(value, st["kpi_value"])],
                            [Paragraph(note, st["kpi_note"])]],
                           colWidths=[width / len(items) - 4],
                           style=TableStyle([
                               ("BACKGROUND", (0, 0), (-1, -1), TILE),
                               ("LEFTPADDING", (0, 0), (-1, -1), 7),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                               ("TOPPADDING", (0, 0), (-1, 0), 7),
                               ("BOTTOMPADDING", (0, 0), (-1, -2), 0),
                               ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
                           ])))
    return Table([cells], colWidths=[width / len(items)] * len(items),
                 style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                   ("TOPPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))


def data_table(rows, st, width, col_ratios, header=True):
    table = Table(rows, colWidths=[width * r for r in col_ratios])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]
    if header:
        style += [("LINEBELOW", (0, 0), (-1, 0), 0.9, INK),
                  ("BOTTOMPADDING", (0, 0), (-1, 0), 6)]
    table.setStyle(TableStyle(style))
    return table


def fitted(path: Path, width):
    """Scale an image to a target width, preserving aspect ratio."""
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(str(path)).getSize()
    return Image(str(path), width=width, height=width * ih / iw)


def build(args) -> int:
    root = Path(__file__).parent
    reports = root / "reports"
    st = styles()

    try:
        fact = pd.read_csv(root / "data/clean/online_retail_clean.csv",
                           usecols=["InvoiceNo", "InvoiceDate", "CustomerID", "Total_Price"],
                           parse_dates=["InvoiceDate"])
        rfm = pd.read_csv(root / "data/clean/rfm_segments.csv")
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}\nRun data_cleaning.py and the RFM model first.", file=sys.stderr)
        return 1
    for name in ("dashboard_page1_overview.png", "04_rfm_grid.png",
                 "06_revenue_concentration.png"):
        if not (reports / name).exists():
            print(f"ERROR: missing {name} - run generate_dashboard.py first.", file=sys.stderr)
            return 1

    revenue = fact["Total_Price"].sum()
    orders = fact["InvoiceNo"].nunique()
    seg = (rfm.groupby("customer_segment")
              .agg(customers=("customer_id", "size"), revenue=("monetary", "sum")))
    seg["pct_rev"] = 100 * seg["revenue"] / seg["revenue"].sum()
    seg["pct_cust"] = 100 * seg["customers"] / len(rfm)
    spend = rfm["monetary"].sort_values(ascending=False).values
    top20 = spend[:int(len(spend) * 0.2)].sum() / spend.sum() * 100
    lapsing = seg.loc[["At Risk", "Cannot Lose Them"]]

    width = PAGE_W - 2 * MARGIN
    story = []

    # ---------------- page 1 -------------------------------------------------
    head = Table([[
        Paragraph("E-Commerce Customer Segmentation", st["title"]),
        Paragraph(f"{args.author}<br/>Data Analytics Portfolio Project<br/>"
                  f"{date.today():%B %Y}", st["byline"]),
    ]], colWidths=[width * 0.72, width * 0.28],
        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                          ("LEFTPADDING", (0, 0), (-1, -1), 0),
                          ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                          ("TOPPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 2)]
    story.append(Paragraph(
        "RFM (Recency, Frequency, Monetary) analysis of 541,909 transactions &nbsp;&middot;&nbsp; "
        "Python &middot; PostgreSQL &middot; Power BI", st["subtitle"]))
    story.append(Spacer(1, 9))

    story.append(Paragraph("Executive summary", st["h2"]))
    story.append(Paragraph(
        f"A UK online retailer held 13 months of transaction history \u2014 {RAW_ROWS:,} raw "
        f"rows \u2014 but no view of which customers actually drove revenue, so marketing spend "
        f"was spread evenly across the base. "
        f"I built a reproducible pipeline that cleans the raw extract, scores every customer on "
        f"Recency, Frequency and Monetary value using SQL window functions, and segments the "
        f"base into eleven actionable groups.<br/><br/>"
        f"The result reframes the budget conversation: <b>{seg.loc['Champions', 'pct_cust']:.0f}% "
        f"of customers generate {seg.loc['Champions', 'pct_rev']:.0f}% of revenue</b>, and a "
        f"further {int(lapsing['customers'].sum())} high-value customers are lapsing with "
        f"{money(lapsing['revenue'].sum())} of historic spend at stake. Both groups are now "
        f"addressable by name.", st["body"]))
    story.append(Spacer(1, 10))

    story.append(kpi_strip([
        ("Revenue analysed", money(revenue), f"{orders:,} orders"),
        ("Customers scored", f"{len(rfm):,}", "11 segments"),
        ("Average order value", f"£{revenue / orders:,.0f}", "across 13 months"),
        ("Champions' share", f"{seg.loc['Champions', 'pct_rev']:.0f}%",
         f"from {seg.loc['Champions', 'pct_cust']:.0f}% of customers"),
    ], st, width))
    story.append(Spacer(1, 12))

    story.append(fitted(reports / "dashboard_page1_overview.png", width))
    story.append(Spacer(1, 3))
    story.append(Paragraph("Dashboard page 1 &mdash; segment sizes, revenue distribution and "
                           "monthly trend. Full two-page dashboard: reports/rfm_dashboard.pdf",
                           st["cap"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("What the analysis found", st["h2"]))
    for text in [
        f"<b>Revenue is highly concentrated.</b> The top 20% of customers by spend account for "
        f"{top20:.0f}% of revenue; the bottom half contributes under 4%.",
        f"<b>{int(seg.loc['Champions', 'customers'])} Champions are the business.</b> They buy "
        f"recently, often, and at the highest value &mdash; {money(seg.loc['Champions', 'revenue'])} "
        f"between them.",
        f"<b>{int(lapsing.loc['Cannot Lose Them', 'customers'])} 'Cannot Lose Them' customers "
        f"have gone quiet.</b> High historic spend, no recent purchase &mdash; the highest-ROI "
        f"win-back target in the base.",
        "<b>Demand is seasonal.</b> Revenue climbs from September and peaks at £1.16M in "
        "November, so retention campaigns should land before the Q4 ramp, not during it.",
    ]:
        story.append(Paragraph(text, st["bullet"], bulletText="•"))

    # ---------------- page 2 -------------------------------------------------
    story.append(PageBreak())
    story.append(Paragraph("How it was built", st["h2"]))
    story.append(data_table([
        [Paragraph("Stage", st["cell_b"]), Paragraph("Artifact", st["cell_b"]),
         Paragraph("What it does", st["cell_b"])],
        [Paragraph("1. Clean", st["cell"]), Paragraph("data_cleaning.py", st["cell_b"]),
         Paragraph("Pandas pipeline: removes duplicates, null customer IDs, cancelled orders "
                   "(<font face='Courier'>C</font>-prefixed invoices) and non-positive "
                   "quantity/price, then derives <font face='Courier'>Total_Price</font>. "
                   "541,909 &rarr; 392,692 rows, with every exclusion logged and counted.",
                   st["cell"])],
        [Paragraph("2. Model", st["cell"]), Paragraph("rfm_model.sql", st["cell_b"]),
         Paragraph("PostgreSQL CTEs and <font face='Courier'>NTILE(5)</font> window functions "
                   "score each customer 1&ndash;5 on Recency, Frequency and Monetary value, "
                   "concatenated into a three-digit RFM code and mapped to a business segment.",
                   st["cell"])],
        [Paragraph("3. Visualise", st["cell"]), Paragraph("power_bi_dax.txt", st["cell_b"]),
         Paragraph("DAX measures (Total Revenue, Unique Customers, Average Order Value) and a "
                   "<font face='Courier'>SWITCH(TRUE())</font> segmentation column, plus a "
                   "matplotlib renderer for the static dashboard.", st["cell"])],
    ], st, width, [0.13, 0.20, 0.67]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Modelling decisions worth noting", st["h2"]))
    for text in [
        "<b>Recency is scored in reverse.</b> <font face='Courier'>NTILE(5) OVER (ORDER BY "
        "recency DESC)</font> puts the longest gap in quintile 1, so 5 always means 'bought most "
        "recently' &mdash; the direction every segment rule depends on.",
        "<b>The snapshot date is the last transaction plus one day</b>, so the most recent buyer "
        "scores a recency of 1 rather than 0 and no customer divides by zero.",
        "<b>Segment logic lives in SQL, not only in DAX</b>, so the label is identical in Power "
        "BI, in the static dashboard, and in any future tool reading the same table.",
    ]:
        story.append(Paragraph(text, st["bullet"], bulletText="•"))
    story.append(Spacer(1, 8))

    charts = Table([[fitted(reports / "04_rfm_grid.png", width * 0.45),
                     fitted(reports / "06_revenue_concentration.png", width * 0.45)]],
                   colWidths=[width * 0.5, width * 0.5],
                   style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                     ("RIGHTPADDING", (0, 0), (0, 0), 8),
                                     ("RIGHTPADDING", (1, 0), (1, 0), 0),
                                     ("TOPPADDING", (0, 0), (-1, -1), 0)]))
    story.append(charts)
    story.append(Paragraph("Left: revenue by Recency &times; Frequency quintile. "
                           "Right: cumulative revenue by customer rank.", st["cap"]))
    story.append(Spacer(1, 6))

    actions = [[Paragraph("Segment", st["cell_b"]), Paragraph("Customers", st["cell_b"]),
                Paragraph("Revenue", st["cell_b"]), Paragraph("Recommended action", st["cell_b"])]]
    for name, action in [
        ("Champions", "Early access, loyalty tier, referral asks. Protect first."),
        ("Loyal Customers", "Cross-sell adjacent categories; raise basket size."),
        ("At Risk", "Targeted win-back with a time-boxed incentive."),
        ("Cannot Lose Them", "Personal outreach before Q4; highest ROI per contact."),
        ("New Customers", "Onboarding sequence to drive a critical second order."),
        ("Lost", "Low-cost automated reactivation only — no paid spend."),
    ]:
        row = seg.loc[name]
        actions.append([Paragraph(name, st["cell_b"]),
                        Paragraph(f"{int(row['customers']):,}", st["cell"]),
                        Paragraph(f"{money(row['revenue'])} ({row['pct_rev']:.1f}%)", st["cell"]),
                        Paragraph(action, st["cell"])])
    story.append(KeepTogether([Paragraph("Recommended actions", st["h2"]),
                               data_table(actions, st, width, [0.19, 0.12, 0.17, 0.52])]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Where I would take it next", st["h2"]))
    for text in [
        "<b>Measure, don't just segment.</b> Hold out a control group per campaign so win-back "
        "lift is attributable rather than assumed.",
        "<b>Score on a schedule.</b> Running the SQL nightly turns a one-off study into tracked "
        "movement between segments.",
        "<b>Add product affinity.</b> RFM says who to contact; basket analysis on the same table "
        "would say what to show them.",
    ]:
        story.append(Paragraph(text, st["bullet"], bulletText="\u2022"))

    # ---------------- frame / chrome ----------------------------------------
    def chrome(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(ACCENT)
        canvas.rect(0, PAGE_H - 4 * mm, PAGE_W, 4 * mm, stroke=0, fill=1)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, MARGIN - 4 * mm, PAGE_W - MARGIN, MARGIN - 4 * mm)
        canvas.setFont("Helvetica", 7.6)
        canvas.setFillColor(INK_MUTED)
        footer = f"{args.author} · RFM Customer Segmentation"
        if args.github:
            footer += f" · {args.github}"
        canvas.drawString(MARGIN, MARGIN - 9 * mm, footer)
        canvas.restoreState()

    class NumberedCanvas(pdfcanvas.Canvas):
        """Second pass over the finished pages, so the footer can say 'of N'."""

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.setFont("Helvetica", 7.6)
                self.setFillColor(INK_MUTED)
                self.drawRightString(PAGE_W - MARGIN, MARGIN - 9 * mm,
                                     f"Page {self._pageNumber} of {total}")
                super().showPage()
            super().save()

    out = reports / "rfm_case_study.pdf"
    doc = BaseDocTemplate(str(out), pagesize=A4,
                          leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=MARGIN, bottomMargin=MARGIN + 2 * mm,
                          title="E-Commerce Customer Segmentation - RFM Case Study",
                          author=args.author,
                          subject="RFM analysis of the UCI Online Retail dataset")
    frame = Frame(MARGIN, MARGIN + 2 * mm, width,
                  PAGE_H - MARGIN - (MARGIN + 2 * mm), id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="std", frames=[frame], onPage=chrome)])
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"  {out.relative_to(root)}  ({out.stat().st_size / 1024:.0f} KB, {doc.page} pages)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the case-study PDF.")
    ap.add_argument("--author", default="Dhruvi", help="Name shown in the byline and footer.")
    ap.add_argument("--github", default="", help="Optional repo URL for the footer.")
    return build(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
