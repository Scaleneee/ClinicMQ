"""Queue services: e.g. issue_ticket(), check_in(), call_next(), mark_missed(), rejoin(), expire_old_tickets().

Business logic for this app. Views call these functions; keep views thin.
Wrap multi-step writes in transaction.atomic().
"""

from .models import QueueTicket


def get_todays_ticket(patient):
    """The patient's active ticket for today, or None.

    Active = not finished yet (WAITING, CHECKED_IN, SKIPPED, CALLED, IN_CONSULTATION).
    R3 allows at most one, so this returns the latest just in case.
    """
    if patient is None:
        return None
    return (
        QueueTicket.objects.today()
        .active()
        .filter(patient=patient)
        .select_related("doctor")
        .order_by("-issued_at")
        .first()
    )


def people_ahead(ticket):
    """How many patients will be called before this ticket.

    TODO (queue logic): count today's tickets in the same session that will be
    called first: CHECKED_IN tickets ordered by (position, checked_in_at), R6/R11.
    Returns None until implemented, and the page shows "–".
    """
    return None
