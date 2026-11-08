"""Pharmacy services: e.g. dispense_item() (deduct stock), low_stock_medicines(), expiring_medicines().

Business logic for this app. Views call these functions; keep views thin.
Wrap multi-step writes in transaction.atomic().
"""
