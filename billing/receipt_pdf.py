"""
billing/receipt_pdf.py
Builds the payment receipt as an 80mm-wide thermal-style PDF with reportlab (UI.md §5.8, "Receipt print").
The page is as long as the receipt needs, like a roll of receipt paper.
"""

from io import BytesIO

from django.utils import timezone
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from queueing.models import ClinicSetting

from .services import change_for

WIDTH = 80 * mm
MARGIN = 5 * mm
INK = (0.07, 0.07, 0.07)
MUTED = (0.40, 0.40, 0.40)
RED = (0.75, 0.22, 0.17)
FONT, BOLD = "Times-Roman", "Times-Bold"


def _money(value):
    return f"RM {value:,.2f}"


def _when(value):
    local = timezone.localtime(value)
    return f"{local.day} {local:%b %Y}, {local:%I:%M %p}".replace(", 0", ", ")


def _content(bill):
    """The receipt as a list of drawing steps: (kind, *args). Kinds: text, row, line, gap, brand."""
    clinic = ClinicSetting.load()
    consultation = bill.consultation
    patient = consultation.ticket.patient
    items = list(bill.items.order_by("item_type", "description"))
    total = sum((i.line_total for i in items), 0)
    inner = WIDTH - 2 * MARGIN

    steps = [("brand", clinic.clinic_name)]
    for part in (clinic.address, f"Tel {clinic.phone}" if clinic.phone else ""):
        for text in simpleSplit(part or "", FONT, 8, inner):
            steps.append(("text", text, FONT, 8, MUTED, "center"))
    steps += [("gap", 2), ("line",), ("text", "Receipt", BOLD, 11, INK, "center"), ("gap", 1)]
    steps += [
        ("row", "Bill no.", bill.bill_no, FONT, 8.5),
        ("row", "Paid on", _when(bill.paid_at) if bill.paid_at else "–", FONT, 8.5),
        ("row", "Patient", patient.full_name.title(), FONT, 8.5),
        ("row", "Doctor", f"Dr. {consultation.doctor.full_name}", FONT, 8.5),
        ("line",),
    ]
    for item in items:
        for text in simpleSplit(item.description, FONT, 9, inner):
            steps.append(("text", text, FONT, 9, INK, "left"))
        steps.append(("row", f"  {item.quantity} × {_money(item.unit_price)}", _money(item.line_total), FONT, 8.5))
    steps += [("line",), ("row", "Total", _money(total), BOLD, 11), ("gap", 1)]
    steps.append(("row", f"Paid ({bill.get_payment_method_display() or '–'})", _money(bill.amount_paid or 0), FONT, 9))
    change = change_for(bill, total)
    if change is not None:
        steps.append(("row", "Change", _money(change), FONT, 9))
    steps += [("line",), ("gap", 1), ("text", "Thank you", BOLD, 11, INK, "center"),
              ("text", "Get well soon.", FONT, 8.5, MUTED, "center"), ("gap", 2),
              ("text", f"Computer-generated receipt · {bill.bill_no}", FONT, 7, MUTED, "center")]
    return steps


HEIGHTS = {"brand": 7 * mm, "line": 5 * mm}


def _height(step):
    kind = step[0]
    if kind == "gap":
        return step[1] * mm
    if kind in HEIGHTS:
        return HEIGHTS[kind]
    size = step[3] if kind == "text" else step[4]
    return size * 0.46 * mm + 1.6 * mm  # line height that follows the font size


def build_receipt_pdf(bill):
    """Return the PDF bytes for a paid Bill."""
    steps = _content(bill)
    height = sum(_height(s) for s in steps) + 2 * 8 * mm

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(WIDTH, height))
    pdf.setTitle(f"Receipt {bill.bill_no}")
    left, right, centre = MARGIN, WIDTH - MARGIN, WIDTH / 2
    y = height - 8 * mm

    for step in steps:
        kind = step[0]
        y -= _height(step)
        if kind == "brand":
            name = step[1]
            pdf.setFillColorRGB(*INK)
            pdf.setFont(BOLD, 14)
            name_width = pdf.stringWidth(name, BOLD, 14)
            x = centre - name_width / 2
            pdf.drawString(x, y + 1.5 * mm, name)
            pdf.setFillColorRGB(*RED)
            pdf.circle(x + name_width + 1.6 * mm, y + 1.9 * mm, 0.7 * mm, stroke=0, fill=1)
        elif kind == "text":
            _, text, font, size, colour, align = step
            pdf.setFillColorRGB(*colour)
            pdf.setFont(font, size)
            if align == "center":
                pdf.drawCentredString(centre, y, text)
            else:
                pdf.drawString(left, y, text)
        elif kind == "row":
            _, label, value, font, size = step
            pdf.setFillColorRGB(*INK)
            pdf.setFont(font, size)
            pdf.drawString(left, y, label)
            pdf.drawRightString(right, y, value)
        elif kind == "line":
            pdf.setStrokeColorRGB(*MUTED)
            pdf.setDash(1.5, 1.5)
            pdf.setLineWidth(0.5)
            pdf.line(left, y + 2.2 * mm, right, y + 2.2 * mm)
            pdf.setDash()

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
