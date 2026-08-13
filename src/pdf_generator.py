from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .markets import MARKETS


def _page(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5B6470"))
    canvas.drawCentredString(landscape(A4)[0] / 2, 8 * mm, f"Página {doc.page}")
    canvas.restoreState()


def _paragraph(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape("" if text is None else str(text)).replace("\n", "<br/>"), style)


def _market_rows(market: dict[str, Any], body: ParagraphStyle, compact: ParagraphStyle) -> list[list[Any]]:
    status = market.get("status", "ERROR DE EXTRACCIÓN")
    rows: list[list[Any]] = [[
        _paragraph("Línea", compact),
        _paragraph("Selección", compact),
        _paragraph("Cuota", compact),
        _paragraph("Consulta", compact),
    ]]
    if status != "VERIFICADO":
        message = market.get("message") or market.get("error") or status
        rows.append([_paragraph(message, body), "", "", _paragraph(market.get("queried_at", ""), compact)])
        return rows
    data = market.get("data", [])
    for item in data:
        rows.append(
            [
                _paragraph(item.get("line", ""), compact),
                _paragraph(item.get("selection", ""), body),
                _paragraph(item.get("odd", ""), compact),
                _paragraph(market.get("queried_at", ""), compact),
            ]
        )
    if len(rows) == 1:
        rows.append([_paragraph("ERROR DE EXTRACCIÓN - Sin filas persistidas", body), "", "", ""])
    return rows


def build_pdf(data: dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    page_size = landscape(A4)
    doc = BaseDocTemplate(
        str(destination),
        pagesize=page_size,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=13 * mm,
        bottomMargin=15 * mm,
        title=f"Cuotas Ecuabet {data['target_date']}",
        author="EcuabetExtractor",
        subject="Cuotas prematch observadas en Ecuabet",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=_page)])

    base = getSampleStyleSheet()
    title = ParagraphStyle("TitleEC", parent=base["Title"], fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=colors.HexColor("#14213D"), spaceAfter=5 * mm)
    league_style = ParagraphStyle("League", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.HexColor("#0B6E4F"), spaceBefore=2 * mm, spaceAfter=2 * mm)
    match_style = ParagraphStyle("Match", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#14213D"), spaceAfter=1.5 * mm)
    market_style = ParagraphStyle("Market", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=colors.HexColor("#8A3B12"), spaceBefore=2 * mm, spaceAfter=1 * mm)
    body = ParagraphStyle("BodyEC", parent=base["BodyText"], fontName="Helvetica", fontSize=8.2, leading=10.2)
    compact = ParagraphStyle("Compact", parent=body, fontSize=7.2, leading=8.7)
    centered = ParagraphStyle("Centered", parent=body, alignment=TA_CENTER)

    story: list[Any] = [
        _paragraph(f"Cuotas Ecuabet — {data['target_date']}", title),
        _paragraph(
            f"Zona horaria: {data.get('timezone', 'America/Guayaquil')} · "
            f"Inicio: {data.get('started_at', '')} · Última actualización: {data.get('last_updated', '')}",
            body,
        ),
        Spacer(1, 3 * mm),
    ]
    matches = data.get("matches", [])
    if not matches:
        story.append(
            _paragraph(
                "No se encontraron partidos publicados en Ecuabet para las cinco ligas autorizadas en la fecha objetivo.",
                centered,
            )
        )
        doc.build(story)
        return

    current_league = None
    for match_index, match in enumerate(matches):
        if match_index:
            story.append(PageBreak())
        if match.get("league") != current_league:
            current_league = match.get("league")
            story.append(_paragraph(current_league, league_style))
        referee = match.get("referee", {})
        metadata = [
            _paragraph(f"{match['home']} vs {match['away']}", match_style),
            _paragraph(f"Fecha y hora: {match['date']} {match['time']} (America/Guayaquil)", body),
            _paragraph(f"Árbitro principal: {referee.get('name', '')}", body),
            _paragraph(f"Fuente arbitral: {referee.get('source_url') or 'Sin URL oficial verificable'}", compact),
            _paragraph(f"URL directa Ecuabet: {match.get('url', '')}", compact),
            _paragraph(f"Consulta del partido: {match.get('queried_at') or match.get('last_updated', '')}", compact),
        ]
        story.append(KeepTogether(metadata))
        by_id = {int(market["id"]): market for market in match.get("markets", [])}
        for spec in MARKETS:
            market = by_id.get(spec["id"], {"id": spec["id"], "name": spec["name"], "status": "ERROR DE EXTRACCIÓN", "error": "Estado ausente en JSON"})
            slider = market.get("slider")
            extra = ""
            if slider:
                extra = f" — deslizador {slider.get('min')}..{slider.get('max')}, {len(slider.get('visited_positions', []))} posiciones"
            elif market.get("coverage"):
                extra = f" — {market['coverage']}"
            story.append(CondPageBreak(18 * mm))
            story.append(_paragraph(f"{spec['id']}. {spec['name']} — {market.get('status')}{extra}", market_style))
            rows = _market_rows(market, body, compact)
            table = Table(rows, colWidths=[32 * mm, 91 * mm, 24 * mm, 76 * mm], repeatRows=1, splitByRow=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE7F0")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#14213D")),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#AAB4BE")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 3),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                        ("SPAN", (0, 1), (2, 1)) if market.get("status") != "VERIFICADO" else ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#52606D")),
                    ]
                )
            )
            story.append(table)
            if spec["id"] != MARKETS[-1]["id"]:
                story.append(Spacer(1, 1.5 * mm))
    doc.build(story)
