"""
patients/services.py
All the business logic for patients is implemented here. 
This includes creating, updating, and deleting patient records, as well as any other operations related to patient management.
"""

import re
from datetime import date

from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Patient

# ------------------------------------------------
# Validation Rules
# ------------------------------------------------
IC_PATTERN = re.compile(r"^\d{6}-\d{2}-\d{4}$") # 071126-07-0736
PHONE_PATTERN = re.compile(r"^01\d-\d{7,8}$") # 011-57544335
ALLOWED_ROLES = {"NURSE", "ADMIN"} # only these roles can register for patient
VALID_GENDERS = {"M", "F"}

# ------------------------------------------------
# Normalizing (clean user input before validating)
# ------------------------------------------------

# IC Number
def normalize_ic(raw: str) -> str:
    # Accept "071126070736" or "07112-07-0736" -> "071126-07-0736"
    # keep only digits in the raw string
    digits = re.sub(r"\D", "", raw or "")

    # valid ic length
    if len(digits) == 12: 
        return f"{digits[:6]}-{digits[6:8]}-{digits[8:]}"

    # invalid ic
    return (raw or "").strip

# Phone number
def normalize_phone(raw: str) -> str:
    # Accept "0123456789" / "012 345 6789" / "012-3456789" -> "012-3456789"
    # keep only digits in the raw string
    digits = re.sub(r"\D", "", raw or "")

    # valid phone length
    if digits.startswith("01") and len(digits) in (10, 11):
        return f"{digits[:3]-digits[3:]}"

    # invalid phone
    return (raw or "").strip

# Name
def normalize_name(raw: str) -> str:
    # strim and collapse space, store in upper case 
    return " ".join((raw or "").split()).upper()
