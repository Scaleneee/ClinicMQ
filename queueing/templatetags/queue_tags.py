"""Template helpers for queue tickets. Load with {% load queue_tags %}."""

import qrcode
import qrcode.image.svg
from django import template
from django.utils import timezone
from django.utils.safestring import mark_safe

register = template.Library()

# Ticket status -> (label shown to people, badge style). Labels follow UI.md §3.
STATUS_BADGES = {
    "WAITING": ("Not arrived", "waiting"),
    "CHECKED_IN": ("Checked in", "checked-in"),
    "SKIPPED": ("Skipped", "skipped"),
    "CALLED": ("Called", "called"),
    "IN_CONSULTATION": ("With doctor", "with-doctor"),
    "COMPLETED": ("Completed", "completed"),
    "MISSED": ("Missed", "missed"),
    "CANCELLED": ("Cancelled", "closed"),
    "EXPIRED": ("Expired", "closed"),
}


@register.inclusion_tag("_status_badge.html")
def status_badge(status):
    """{% status_badge ticket.status %} -> pill with a dot and a text label."""
    label, style = STATUS_BADGES.get(status, (str(status).replace("_", " ").title(), "closed"))
    return {"label": label, "style": style}


@register.filter
def queue_no(value):
    """{{ ticket.queue_no|queue_no }} -> 3 digits, e.g. 12 -> "012"."""
    try:
        return f"{int(value):03d}"
    except (TypeError, ValueError):
        return value


@register.filter
def status_label(status):
    """{{ "WAITING"|status_label }} -> "Not arrived"."""
    return STATUS_BADGES.get(status, (str(status).replace("_", " ").title(), ""))[0]


@register.simple_tag
def wait_range(low, high):
    """{% wait_range s.wait_min s.wait_max %} -> "40–50 min", "Under 10 min" or "–"."""
    if low is None or high is None:
        return "–"
    if low == 0:
        return f"Under {high} min"
    return f"{low}–{high} min"


@register.filter
def age(date_of_birth):
    """{{ patient.date_of_birth|age }} -> 34"""
    if not date_of_birth:
        return ""
    today = timezone.localdate()
    return today.year - date_of_birth.year - (
        (today.month, today.day) < (date_of_birth.month, date_of_birth.day)
    )


@register.filter
def qr_svg(data):
    """{{ url|qr_svg }} -> an inline SVG QR code (scales with its container)."""
    image = qrcode.make(str(data), image_factory=qrcode.image.svg.SvgPathImage, border=2)
    svg = image.to_string(encoding="unicode")
    return mark_safe(svg)
