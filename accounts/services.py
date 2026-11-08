"""Accounts services: e.g. create_staff(), assign_shift(), staff_on_duty(date, session).

Business logic for this app. Views call these functions; keep views thin.
Wrap multi-step writes in transaction.atomic().
"""
