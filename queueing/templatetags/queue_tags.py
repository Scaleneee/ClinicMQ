"""Template helpers for queue tickets. Load with {% load queue_tags %}."""

from django import template

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
