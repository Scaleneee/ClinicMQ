"""Template helpers for bills. Load with {% load bill_tags %}."""

from django import template

register = template.Library()

# Bill status -> (label, badge style), UI.md §3.
BILL_BADGES = {
    "UNPAID": ("Unpaid", "waiting"),
    "PAID": ("Paid", "checked-in"),
    "VOID": ("Void", "completed"),
}


@register.inclusion_tag("_status_badge.html")
def bill_badge(status):
    """{% bill_badge bill.status %} -> pill with a dot and a text label."""
    label, style = BILL_BADGES.get(status, (str(status).title(), "closed"))
    return {"label": label, "style": style}


@register.filter
def rm(value):
    """{{ 12.5|rm }} -> "RM 12.50"."""
    try:
        return f"RM {value:,.2f}"
    except (TypeError, ValueError):
        return value
