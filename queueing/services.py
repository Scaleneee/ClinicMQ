"""Queue services: e.g. issue_ticket(), check_in(), call_next(), mark_missed(), rejoin(), expire_old_tickets().

Business logic for this app. Views call these functions; keep views thin.
Wrap multi-step writes in transaction.atomic().
"""
