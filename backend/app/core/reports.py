from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import textwrap

import requests

from app.core.imagery_preview import PreviewError, tiler_render_url_for_payload
from app.models import FindingCard, Investigation
from app.settings import get_settings


SCENE_ROLE_LABELS = {
    "before": "Before",
    "during": "During",
    "after": "After",
}


def _selected_scenes(payload: dict) -> dict[str, dict]:
    scenes = payload.get("selected_scenes")
    if isinstance(scenes, dict) and any(isinstance(v, dict) for v in scenes.values()):
        return {role: scene for role, scene in scenes.items() if role in SCENE_ROLE_LABELS and isinstance(scene, dict)}
    pair = payload.get("selected_pair") or {}
    out: dict[str, dict] = {}
    if isinstance(pair.get("pre"), dict):
        out["before"] = pair["pre"]
    if isinstance(pair.get("post"), dict):
        if pair["post"].get("role") == "during-window":
            out["during"] = pair["post"]
        else:
            out["after"] = pair["post"]
    return out



def generate_markdown_report(inv: Investigation, cards: list[FindingCard]) -> str:
    pinned = [c for c in cards if c.pinned]
    lines = [
        f"# Wildfire Finding Brief: {inv.title}",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"AOI: `{inv.aoi}`",
        f"Year: `{inv.year}`",
        f"Confidence mode: `{inv.confidence_mode.value}`",
        f"Data mode: `synthetic demo`",
        "",
        "> This brief was generated from synthetic demonstration data. It demonstrates the stateful workflow, finding-card model, and report-generation pattern. It is not an operational burned-area estimate.",
        "",
        "## Executive summary",
        "",
    ]
    if not pinned:
        lines.append("No finding cards have been added to the report. Add finding to the report before generating a brief.")
        return "\n".join(lines)

    lines += [
        f"This investigation contains {len(pinned)} report finding item(s). Primary burned-area finding should be interpreted as demo-derived until real CLMS BA processing is enabled. Contextual finding such as AOD, drought, land-cover, and exposure proxies should be labelled as supporting or contextual rather than direct confirmation.",
        "",
        "## Finding used",
        "",
    ]

    api_base = get_settings().api_public_base.rstrip("/")
    for idx, card in enumerate(pinned, 1):
        lines += [
            f"### {idx}. {card.title}",
            "",
            f"**Finding type:** `{card.type.value}`  ",
            f"**Source dataset:** {card.source_dataset}  ",
            "",
            card.summary,
            "",
        ]
        method = card.provenance.get("method")
        if method:
            lines += [f"**Method:** {method}", ""]
        if card.payload.get("monthly"):
            lines.append("**Monthly burned-area values:**")
            lines.append("")
            lines.append("| Month | Burned area (ha) | Burned area (km²) |")
            lines.append("|---:|---:|---:|")
            for point in card.payload["monthly"]:
                lines.append(f"| {point['month']} | {point['burned_area_ha']:,} | {point.get('burned_area_km2', point['burned_area_ha']/100):,.2f} |")
            lines.append("")
        scenes = _selected_scenes(card.payload)
        if scenes:
            lines.append("**Selected optical scenes:**")
            lines.append("")
            lines.append("| Role | Sensor | Date | Cloud cover | AOI coverage | Item |")
            lines.append("|---|---|---:|---:|---:|---|")
            for role in ["before", "during", "after"]:
                item = scenes.get(role)
                if not item:
                    continue
                display_role = SCENE_ROLE_LABELS[role]
                cloud = item.get("cloud_cover")
                cloud_text = f"{cloud}%" if cloud is not None else "n/a"
                coverage = item.get("coverage_percent")
                coverage_text = f"{coverage}%" if coverage is not None else "n/a"
                lines.append(f"| {display_role} | {item.get('sensor', 'n/a')} | {item.get('datetime', 'n/a')} | {cloud_text} | {coverage_text} | `{item.get('item_id', 'n/a')}` |")
            lines.append("")
            if card.payload.get("composite_label"):
                lines.append(f"**Composite:** {card.payload.get('composite_label')} — {card.payload.get('composite_description', '')}")
                lines.append("")
            lines.append("**Selected optical imagery:**")
            lines.append("")
            for role in ["before", "during", "after"]:
                if role not in scenes:
                    continue
                lines.append(f"![{SCENE_ROLE_LABELS[role]} optical image]({api_base}/imagery/{card.id}/preview/{role}.png?width=900)")
                lines.append("")
        if card.caveats:
            lines.append("**Caveats:**")
            for caveat in card.caveats:
                lines.append(f"- {caveat}")
            lines.append("")

    lines += [
        "## Reproducibility block",
        "",
        "This brief was generated only from finding cards explicitly added to the report. Each card stores the source dataset, method, parameters, caveats, and workflow skill provenance. Real operational use should replace the synthetic demo data with validated CLMS BA, Sentinel/Landsat STAC, CAMS, ERA5, WorldCover, and GHSL integrations.",
    ]
    return "\n".join(lines)



def _fetch_tiler_preview_png(payload: dict, role: str, width: int = 900) -> bytes:
    settings = get_settings()
    render_url, _item = tiler_render_url_for_payload(
        payload,
        role=role,
        candidate_index=None,
        tiler_base=settings.tiler_internal_base,
        width=width,
    )
    try:
        response = requests.get(render_url, timeout=90)
        response.raise_for_status()
        return response.content
    except requests.RequestException as exc:
        raise PreviewError(f"Could not fetch rendered imagery from tiler: {exc}") from exc



def generate_pdf_report(inv: Investigation, cards: list[FindingCard]) -> bytes:
    """Generate a simple PDF finding brief. Requires reportlab."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PDF export requires the 'reportlab' package. Run `uv sync` after updating dependencies.") from exc

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.7 * cm,
        rightMargin=1.7 * cm,
        topMargin=1.7 * cm,
        bottomMargin=1.7 * cm,
        title=f"Wildfire Finding Brief - {inv.year}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallMuted", parent=styles["BodyText"], fontSize=8, leading=11, textColor=colors.HexColor("#64748b")))
    styles.add(ParagraphStyle(name="CardTitle", parent=styles["Heading3"], fontSize=11, leading=14, spaceAfter=5, textColor=colors.HexColor("#0f172a")))

    story = []
    story.append(Paragraph(f"Wildfire Finding Brief: {inv.title}", styles["Title"]))
    story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).isoformat()} · AOI: {inv.aoi} · Year: {inv.year} · Confidence mode: {inv.confidence_mode.value}", styles["SmallMuted"]))
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph("Demo mode notice", styles["Heading2"]))
    story.append(Paragraph("This PDF was generated from synthetic demonstration data. It is intended to show workflow orchestration, finding cards, provenance, and report export. It must not be used as an operational burned-area estimate.", styles["BodyText"]))
    story.append(Spacer(1, 0.25 * cm))

    pinned = [c for c in cards if c.pinned]
    story.append(Paragraph("Finding used", styles["Heading2"]))
    if not pinned:
        story.append(Paragraph("No finding cards have been added to the report.", styles["BodyText"]))
    for idx, card in enumerate(pinned, 1):
        story.append(Paragraph(f"{idx}. {card.title}", styles["CardTitle"]))
        story.append(Paragraph(f"Finding type: {card.type.value}<br/>Source: {card.source_dataset}", styles["SmallMuted"]))
        story.append(Paragraph(_escape_reportlab(card.summary), styles["BodyText"]))
        method = card.provenance.get("method")
        if method:
            story.append(Paragraph(f"Method: {_escape_reportlab(str(method))}", styles["SmallMuted"]))
        if card.payload.get("monthly"):
            rows = [["Month", "Burned area (ha)", "Burned area (km²)"]]
            for point in card.payload["monthly"]:
                rows.append([str(point["month"]), f"{point['burned_area_ha']:,}", f"{point.get('burned_area_km2', point['burned_area_ha']/100):,.2f}"])
            table = Table(rows, colWidths=[2.2 * cm, 5 * cm, 5 * cm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ]))
            story.append(Spacer(1, 0.12 * cm))
            story.append(table)
        scenes = _selected_scenes(card.payload)
        if scenes:
            story.append(Spacer(1, 0.12 * cm))
            coverage_note = []
            for role in ["before", "during", "after"]:
                item = scenes.get(role)
                if not item:
                    continue
                display_role = SCENE_ROLE_LABELS[role].lower()
                coverage = item.get("coverage_percent")
                cloud = item.get("cloud_cover")
                coverage_note.append(f"{display_role}: cloud {cloud if cloud is not None else 'n/a'}%, AOI coverage {coverage if coverage is not None else 'n/a'}%")
            story.append(Paragraph("Selected optical imagery", styles["SmallMuted"]))
            story.append(Paragraph(_escape_reportlab(" · ".join(coverage_note)), styles["SmallMuted"]))
            image_row = []
            image_roles = [role for role in ["before", "during", "after"] if role in scenes]
            for role in image_roles:
                try:
                    png = _fetch_tiler_preview_png(card.payload, role=role, width=1000)
                    img = RLImage(BytesIO(png))
                    img.drawWidth = 5.3 * cm if len(image_roles) > 2 else 8.0 * cm
                    img.drawHeight = 4.8 * cm
                    image_row.append(img)
                except Exception as exc:
                    image_row.append(Paragraph(f"{role} image unavailable: {_escape_reportlab(str(exc))}", styles["SmallMuted"]))
            col_width = 5.4 * cm if len(image_roles) > 2 else 8.2 * cm
            img_table = Table([image_row], colWidths=[col_width for _ in image_row])
            img_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(img_table)
        if card.caveats:
            caveat_text = "<br/>".join([f"• {_escape_reportlab(c)}" for c in card.caveats])
            story.append(Paragraph(f"Caveats:<br/>{caveat_text}", styles["SmallMuted"]))
        story.append(Spacer(1, 0.35 * cm))

    story.append(Paragraph("Reproducibility block", styles["Heading2"]))
    story.append(Paragraph("The brief is compiled only from finding cards explicitly added to the report. Each card stores the source dataset, method, parameters, caveats, and workflow skill provenance. Real operational use should replace the synthetic demo data with validated CLMS BA, Sentinel/Landsat STAC, CAMS, ERA5, WorldCover, and GHSL integrations.", styles["BodyText"]))

    doc.build(story)
    return buffer.getvalue()



def _escape_reportlab(text: str) -> str:
    return textwrap.shorten(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), width=1200, placeholder="…")
