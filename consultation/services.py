"""Consultation services: e.g. start_consultation(), complete_consultation(), issue_mc().

Business logic for this app. Views call these functions; keep views thin.
Wrap multi-step writes in transaction.atomic().
"""
