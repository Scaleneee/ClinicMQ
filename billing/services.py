"""Billing services: e.g. create_bill_for_consultation(), pay_bill(), void_bill().

Business logic for this app. Views call these functions; keep views thin.
Wrap multi-step writes in transaction.atomic().
"""
