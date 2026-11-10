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

# ------------------------------------------------
# IC Helper Functions
# ------------------------------------------------
# return the birthday encoded in ic number
def bday_from_ic(ic_no: str) -> date | None:
    # get the year, month, day from ic_no, store as int
    yy, mm, dd = int(ic_no[:2]), int(ic_no[2:4]), int(ic_no[4:6])
    current_yy = timezone.localdate().year % 100 # 2026 -> 26

    century = 2000 if current_yy >= yy else 1900
    try:
        return date(century + yy, mm, dd)
    except ValueError:
        return None

# return the gender 
def gender_from_ic(ic_no: str) -> str: 
    # last digit of ic, odd = male; even = female
    last_digit = int(ic_no[-1])
    return "M" if last_digit % 2 == 1 else "F"

# ------------------------------------------------
# Validation Check
# ------------------------------------------------
def validate_patient_data(*, ic_no, full_name, gender, date_of_birth,
                           phone, email=None, exclude_patient_id=None) -> None:
    # Raise ValidationError with field-specific messages if anything is wrong.
    errors = {}

    # IC format + uniqueness
    if not IC_PATTERN.match(ic_no):
        # invalid format
        errors["ic_no"] = "IC muse be in the format ######-##-####."

    else:
        dup = Patient.objects.filter(ic_no=ic_no)
        if(exclude_patient_id):
            dup = dup.exclude(pk=exclude_patient_id)
        if dup.exists():
            errors["ic_no"] = "A patient with this IC is already registered."

    # Name
    if not full_name:
        errors["full_name"] = "Full name is required."
    elif len(full_name) > 100:
        errors["full_name"] = "Full name must be at most 100 characters."

    # Gender
    if gender not in VALID_GENDERS:
        errors["gender"] = "Gender must be M or F."

    # Date of Birth
    today = timezone.localdate()
    if not date_of_birth:
        errors["date_of_birth"] = "Date of birth is required."
    elif date_of_birth > today:
        errors["date_of_birth"] = "Date of birth cannot be in the future."


    # Cross-check bday and gender against the IC
    if "ic_no" not in errors or errors["ic_no"].startswith("A patient"):
        # if the ic_no is valid
        ic_bday = bday_from_ic(ic_no)

        if ic_bday is None:
            errors["ic_no"] = "IC contains an invalid date of birth."
        else:
            if date_of_birth and "date_of_birth" not in errors and date_of_birth != ic_bday:
                # different bday from input and ic
                errors["date_of_birth"] = f"Date of birth does not match IC ({ic_bday: %d/%m/%Y})."

            # cross check gender
            if gender in VALID_GENDERS and gender and gender != gender_from_ic(ic_no):
                errors["gender"] = "Gender does not match IC."

    # Phone
    if not PHONE_PATTERN.match(phone):
        errors["phone"] = "Phone must be in the format 01X-XXXXXXX."

    # Email (optional)
    if email:
        from django.core.validators import validate_email
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "Enter a valid email address."

    if errors:
        raise ValidationError(errors)

# ------------------------------------------------
# Main use case: nurse registers a walk-in patient
# ------------------------------------------------
# registerd_by: User
@transaction.atomic
def register_patient(*, registered_by, ic_no, full_name, gender, date_of_birth, 
                     phone, email=None, address=None) -> Patient:
    """
    Register a new walk-in patient without login account

    Raises:
        PermissionDenied - caller is not a NURSE or ADMIN
        ValidationError - any field is invalid or the IC already exists
    """
    # check Permission
    if not registered_by.is_authenticated or registered_by.role not in ALLOWED_ROLES:
        raise PermissionDenied("Only nurses or admins can register patients.")

    # clean input
    ic_no = normalize_ic(ic_no)
    full_name = normalize_name(full_name)
    gender = (gender or "").strip().upper()
    phone = normalize_phone(phone)
    email = (email or "").strip().lower() or None
    address = (address or "").strip() or None

    # Validate
    validate_patient_data(ic_no=ic_no, full_name=full_name, gender=gender, 
                          date_of_birth=date_of_birth, phone=phone, email=email)

    # Save 
    # IntegrityError covers two nurses saving the same IC at the same moment
    try:
        return Patient.objects.create(
            ic_no=ic_no,
            full_name=full_name,
            gender=gender,
            date_of_birth=date_of_birth,
            phone=phone,
            email=email,
            address=address,
            user=None,
        )
    except IntegrityError:
        raise ValidationError({"ic_no": "A patient with this IC is already registered."})

# ------------------------------------------------
# Helpers the nurse screen will need
# ------------------------------------------------
def find_patient_by_id(ic_no: str) -> Patient | None:
    """
    Check before registering
    """ 
    return Patient.objects.filter(ic_no=normalize_ic(ic_no)).first()

def prefill_from_ic(ic_no: str) -> dict:
    """
    Auto-fill date_of_birth and gender once the nurse type the IC
    """
    ic_no = normalize_ic(ic_no)
    if not IC_PATTERN.match(ic_no): 
        return {}
    return {"date_of_birth": bday_from_ic(ic_no), "gender": gender_from_ic(ic_no)}