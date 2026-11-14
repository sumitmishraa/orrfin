"""Build PDFs from Orrfin records: payment advice, purchase order, RFQ, audit pack (BUILD_PLAN change 49).

Every PDF is built from data passed in, never from user-supplied markup, so nothing in a record
(a vendor name, a line description) can inject layout or scripts. Text is drawn as plain strings.
Each document carries "Simulated" or "Draft" where that is the truth, and the hash of its inputs
in the footer, so a printed copy can be traced back to the record it came from.
"""

import hashlib
import io
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

NAVY = colors.HexColor("#0B1F3A")


def _para(text: str, style) -> Paragraph:
    # Paragraph understands a little markup; escaping makes every record value plain text.
    return Paragraph(escape(str(text)), style)


def build(title: str, subtitle: str, facts: Sequence[tuple[str, str]], columns: Sequence[str],
          rows: Sequence[Sequence[Any]], *, notice: str, source: dict[str, Any]) -> bytes:
    """One simple, consistent layout for every Orrfin PDF."""
    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(15 * mm, 10 * mm, f"Orrfin · generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC · "
                                            f"record hash {fingerprint[:16]} · page {document.page}")
        canvas.restoreState()

    story: list[Any] = [_para(title, styles["Title"]), _para(subtitle, styles["Normal"]), Spacer(1, 4 * mm),
                        _para(notice, styles["Italic"]), Spacer(1, 4 * mm)]
    if facts:
        table = Table([[_para(k, styles["Normal"]), _para(v, styles["Normal"])] for k, v in facts], colWidths=[50 * mm, 120 * mm])
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
        story += [table, Spacer(1, 5 * mm)]
    if columns:
        data = [[_para(c, styles["Normal"]) for c in columns]] + [[_para(v, styles["Normal"]) for v in row] for row in rows]
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                   ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
        story.append(table)
    SimpleDocTemplate(buffer, pagesize=A4, title=title, leftMargin=15 * mm, rightMargin=15 * mm,
                      topMargin=15 * mm, bottomMargin=18 * mm).build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


SIMULATED = "Simulated payment: no money moved. Produced by the Orrfin mock bank for demonstration."
