"""
PDF report export, mapped to CIS / NIST CSF / SOC 2 / CERT-In per control.

**The evidence rule.** Each finding's evidence is rendered from the `evidence` JSONB
column exactly as it was stored at scan time. This module does NOT re-run any check,
re-derive any value, or paraphrase evidence into prose. It serialises what the
database holds.

That is not fussiness. A report that regenerates its own evidence is not evidence — it
is a second opinion that happens to agree, and it diverges silently the moment the
audited host changes. An auditor reading a finding from three months ago must see what
was actually observed then, not what the host would say today. The Phase 6
verification harness asserts byte-equality between the JSON rendered in the PDF and
the JSONB read straight from PostgreSQL.
"""

from __future__ import annotations

import datetime
import io
import json

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from queries import (
    compliance_trend,
    dashboard_summary,
    findings_for_report,
    open_exceptions,
    per_domain_breakdown,
)

SEVERITY_COLOR = {
    "critical": colors.HexColor("#B00020"),
    "high": colors.HexColor("#D35400"),
    "medium": colors.HexColor("#B7950B"),
    "low": colors.HexColor("#5D6D7E"),
}

OUTCOME_COLOR = {
    "pass": colors.HexColor("#1E8449"),
    "fail": colors.HexColor("#B00020"),
    "error": colors.HexColor("#6C3483"),
    "manual_review": colors.HexColor("#1F618D"),
}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=18, spaceAfter=4),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9,
                              textColor=colors.HexColor("#555555"), spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, spaceBefore=12,
                             spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontSize=10.5,
                             spaceBefore=8, spaceAfter=3),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=8.5, leading=11.5),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontSize=7.5, leading=9.5,
                                textColor=colors.HexColor("#444444")),
        "mono": ParagraphStyle("m", parent=base["Code"], fontSize=7, leading=8.6,
                               alignment=TA_LEFT,
                               textColor=colors.HexColor("#1a1a1a")),
        "caveat": ParagraphStyle("c", parent=base["Normal"], fontSize=8, leading=11,
                                 textColor=colors.HexColor("#8A4B00")),
    }


def _provider(control_id: str) -> str:
    return "AWS" if control_id.startswith("AWS-") else "Linux"


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _table(data, widths, style_extra=None):
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BDC3C7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F4F6F7")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if style_extra:
        style.extend(style_extra)
    t.setStyle(TableStyle(style))
    return t


def build_report(conn, run_id, as_of: datetime.datetime | None = None) -> bytes:
    """Render the run as a PDF and return the bytes."""
    now = as_of or datetime.datetime.now(datetime.timezone.utc)
    s = _styles()

    summary = dashboard_summary(conn, run_id, now)
    domains = per_domain_breakdown(conn, run_id, now)
    exceptions = open_exceptions(conn, now)
    trend = compliance_trend(conn)
    findings = findings_for_report(conn, run_id, now)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"Audit Report {run_id}",
    )
    story = []

    # ---- header -------------------------------------------------------------
    story.append(Paragraph("IT Systems Compliance Audit Report", s["title"]))
    story.append(Paragraph(
        f"Run <b>{run_id}</b> &nbsp;|&nbsp; generated {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        s["sub"]))

    # ---- summary ------------------------------------------------------------
    story.append(Paragraph("1. Summary", s["h2"]))
    story.append(_table(
        [["Compliance", "Total", "Pass", "Fail", "Error", "Manual review",
          "Open findings", "Accepted risk"],
         [f"{summary['compliance_pct']}%", summary["total"], summary["passed"],
          summary["failed"], summary["errored"], summary["manual_review"],
          summary["open_findings"], summary["accepted_risk"]]],
        [26 * mm] * 8))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "Compliance % counts pass against pass+fail. <b>error</b> and "
        "<b>manual_review</b> are excluded from the denominator: a control awaiting "
        "human judgement has neither passed nor failed, and an unreadable source is a "
        "broken audit rather than a compliance failure. Counting either as a failure "
        "would move this figure for reasons unrelated to security posture.",
        s["small"]))

    if any(_provider(f["control_id"]) == "AWS" for f in findings):
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            "&#9888; <b>AWS findings in this report are mock-derived.</b> The AWS "
            "collector has been verified against the <i>moto</i> mock library, not a "
            "real AWS account, and is not evidenced to the standard of the Linux "
            "findings. See architecture.md &sect;3.6. Findings are labelled by "
            "provider in section 4.", s["caveat"]))

    # ---- per-domain ---------------------------------------------------------
    story.append(Paragraph("2. Compliance by domain", s["h2"]))
    story.append(_table(
        [["Domain", "Total", "Pass", "Fail", "Error", "Open findings", "Compliance"]]
        + [[d["category"], d["total"], d["passed"], d["failed"], d["errored"],
            d["open_findings"],
            f"{d['compliance_pct']}%" if d["compliance_pct"] is not None else "n/a"]
           for d in domains],
        [50 * mm] + [24 * mm] * 6))

    # ---- exceptions ---------------------------------------------------------
    story.append(Paragraph("3. Exceptions (accepted risk)", s["h2"]))
    if exceptions:
        story.append(_table(
            [["Control", "Sev", "Status", "Requested by", "Approved by",
              "Expiry", "Expired?", "Justification"]]
            + [[e["control_id"], e["severity"], e["status"], e["requested_by"],
                e["approved_by"] or "—", str(e["expiry_date"])[:19],
                "YES" if e["expired"] else "no",
                Paragraph(_esc(e["justification"])[:180], s["small"])]
               for e in exceptions],
            [24 * mm, 16 * mm, 24 * mm, 24 * mm, 24 * mm, 32 * mm, 16 * mm, 74 * mm]))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            "An exception suppresses a finding in the dashboard's open-findings view "
            "but never rewrites the stored result, which remains <b>fail</b>. "
            "Exceptions expire automatically; an expired exception stops suppressing "
            "on the next scan. No permanent exceptions exist.", s["small"]))
    else:
        story.append(Paragraph("No approved exceptions.", s["body"]))

    # ---- trend --------------------------------------------------------------
    story.append(Paragraph("4. Compliance trend", s["h2"]))
    story.append(_table(
        [["#", "Run", "Completed", "Pass", "Fail", "Error", "Compliance"]]
        + [[i, str(t["run_id"])[:8], str(t["completed_at"])[:19], t["passed"],
            t["failed"], t["errored"], f"{t['compliance_pct']}%"]
           for i, t in enumerate(trend, 1)],
        [10 * mm, 26 * mm, 40 * mm, 20 * mm, 20 * mm, 20 * mm, 26 * mm]))

    story.append(PageBreak())

    # ---- findings with framework mapping + verbatim evidence ---------------
    story.append(Paragraph("5. Findings — framework mapping and evidence", s["h2"]))
    story.append(Paragraph(
        "Each finding's evidence below is reproduced <b>verbatim from the stored "
        "evidence record</b> captured at scan time. It is not re-run, re-derived or "
        "paraphrased for this report.", s["small"]))
    story.append(Spacer(1, 3 * mm))

    for f in findings:
        fm = f["framework_mappings"] or {}
        cis = fm.get("cis_linux_v8") or fm.get("cis_aws_v3") or "—"
        cis_label = "CIS Linux v8" if fm.get("cis_linux_v8") else "CIS AWS v3"

        header = _table(
            [["Control", "Severity", "Outcome", "Provider", "Resource"],
             [f["control_id"], f["severity"], f["outcome"],
              _provider(f["control_id"]),
              Paragraph(_esc(f["resource_id"]), s["small"])]],
            [26 * mm, 20 * mm, 24 * mm, 20 * mm, 84 * mm],
            style_extra=[
                ("TEXTCOLOR", (1, 1), (1, 1),
                 SEVERITY_COLOR.get(f["severity"], colors.black)),
                ("TEXTCOLOR", (2, 1), (2, 1),
                 OUTCOME_COLOR.get(f["outcome"], colors.black)),
                ("FONTNAME", (1, 1), (2, 1), "Helvetica-Bold"),
            ])

        mapping = _table(
            [[cis_label, "NIST CSF", "SOC 2", "CERT-In"],
             [cis, fm.get("nist_csf", "—"), fm.get("soc2", "—"),
              fm.get("cert_in_marker", "—")]],
            [44 * mm, 44 * mm, 44 * mm, 44 * mm])

        # VERBATIM: json.dumps of the exact JSONB column value. No transformation.
        evidence_json = json.dumps(f["evidence"], indent=2, sort_keys=True, default=str)

        block = [
            Paragraph(f"{f['control_id']} — {_esc(f['title'])}", s["h3"]),
            header,
            Spacer(1, 1.5 * mm),
            mapping,
            Spacer(1, 1.5 * mm),
            Paragraph("<b>Evidence (verbatim from the stored record):</b>", s["small"]),
            Paragraph(
                "<font face='Courier'>"
                + _esc(evidence_json).replace("\n", "<br/>").replace(" ", "&nbsp;")
                + "</font>", s["mono"]),
        ]
        if f["suppressed"]:
            block.append(Paragraph(
                "&#9888; Suppressed by an approved, unexpired exception. The stored "
                "outcome remains <b>fail</b>.", s["caveat"]))
        if f["outcome"] in ("fail", "error"):
            block.append(Spacer(1, 1.5 * mm))
            block.append(Paragraph(
                "<b>Remediation:</b> " + _esc(f["remediation"]), s["small"]))

        block.append(Spacer(1, 5 * mm))
        story.append(KeepTogether(block))

    doc.build(story)
    return buf.getvalue()
