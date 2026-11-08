"""Patient services: e.g. register_patient(), find_by_ic(), link_patient_to_user().

Business logic for this app. Views call these functions; keep views thin.
Wrap multi-step writes in transaction.atomic().
"""
