"""
patients/services.py
All the business logic for patients is implemented here. 
This includes creating, updating, and deleting patient records, as well as any other operations related to patient management.
"""

import hashlib
import hmac
import re
import secrets
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from .models import Patient

User = get_user_model()

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
    return (raw or "").strip()

# Phone number
def normalize_phone(raw: str) -> str:
    # Accept "0123456789" / "012 345 6789" / "012-3456789" -> "012-3456789"
    # keep only digits in the raw string
    digits = re.sub(r"\D", "", raw or "")

    # valid phone length
    if digits.startswith("01") and len(digits) in (10, 11):
        return f"{digits[:3]}-{digits[3:]}"

    # invalid phone
    return (raw or "").strip()

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
        errors["ic_no"] = "IC must be in the format ######-##-####."

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
                errors["date_of_birth"] = f"Date of birth does not match IC ({ic_bday:%d/%m/%Y})."

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
# Search patients (nurse, doctor, admin)
# ------------------------------------------------
STAFF_ROLES = {"NURSE", "DOCTOR", "ADMIN"}
def search_patients(*, searched_by, query: str, limit: int = 20):
    """
    Search by IC, name or phone. Returns a QuerySet
    """
    if not searched_by.is_authenticated or searched_by.role not in STAFF_ROLES:
        raise PermissionDenied("Only clinic staff can search patients.")

    query = (query or "").strip()
    if len(query) < 2:
        return Patient.objects.none()

    ic = normalize_ic(query)
    if IC_PATTERN.match(ic):
        # return the patient obj match the ic
        return Patient.objects.filter(ic_no = ic)

    digits = re.sub(r"\D", "", query)
    conditions = Q(full_name__icontains=query) | Q(ic_no__icontains=query)
    if len(digits) >= 3:
        phone_match = Q(phone__icontains=digits[:3])
        if len(digits) > 3:
            phone_match &= Q(phone__icontains=digits[3:])
        conditions |= phone_match
    return Patient.objects.filter(conditions).order_by("full_name")[:limit]

# ------------------------------------------------
# Search patients (nurse, doctor, admin)
# ------------------------------------------------
STAFF_EDITABLE = {"ic_no", "full_name", "gender", "date_of_birth", "phone", "email", "address"}
PATIENT_EDITABLE = {"phone", "email", "address"}

@transaction.atomic
def update_patient(*, updated_by, patient_id: int, **changes) -> Patient:
    """
    Update a patient's details.
    - NURSE / ADMIN can edit every field.
    - The PATIENT can edit only phone, email, and address on their own record.
    """
    patient = Patient.objects.select_for_update().get(pk=patient_id)

    if not updated_by.is_authenticated:
        raise PermissionDenied("Please log in.")
    if updated_by.role in ("NURSE", "ADMIN"):
        allowed = STAFF_EDITABLE
    elif updated_by.role == "PATIENT" and patient.user_id == updated_by.id:
        allowed = PATIENT_EDITABLE
    else:
        raise PermissionDenied("You cannot edit this patient.")

    not_allowed = set(changes) - allowed
    if not_allowed:
        raise PermissionDenied(f"You cannot change: {', '.join(sorted(not_allowed))}.")

    # clean the new values
    cleaners = {"ic_no": normalize_ic, "full_name": normalize_name, "phone": normalize_phone}
    for field, value in changes.items():
        if field in cleaners:
            changes[field] = cleaners[field](value)
        elif field == "gender":
            changes[field] = (value or "").strip().upper()
        elif field == "email":
            changes[field] = (value or "").strip().lower() or None
        elif field == "address":
            changes[field] = (value or "").strip() or None

    # validate the record as it would look after the change
    merged = {f: getattr(patient, f) for f in STAFF_EDITABLE}
    merged.update(changes)
    validate_patient_data(
        ic_no=merged["ic_no"], full_name=merged["full_name"], gender=merged["gender"],
        date_of_birth=merged["date_of_birth"], phone=merged["phone"], email=merged["email"],
        exclude_patient_id=patient.pk,
    )

    for field, value in changes.items():
        setattr(patient, field, value)
    try:
        patient.save(update_fields=list(changes) or None)
    except IntegrityError:
        raise ValidationError({"ic_no": "A patient with this IC is already registered."})
    return patient

# ---------------------------------------------------------------------------
# Link an existing walk-in record to a login account
# ---------------------------------------------------------------------------
@transaction.atomic
def link_patient_to_user(*, user, ic_no: str, date_of_birth) -> Patient:
    """
    Connect a walk-in Patient (user = NULL) to a PATIENT account.
    The date of birth must match, so nobody can claim a record with only an IC.
    """
    if user.role != "PATIENT":
        raise PermissionDenied("Only patient accounts can be linked to a patient record.")
    if Patient.objects.filter(user=user).exists():
        raise ValidationError("This account is already linked to a patient record.")

    ic_no = normalize_ic(ic_no)
    patient = Patient.objects.select_for_update().filter(ic_no=ic_no).first()
    if patient is None or patient.date_of_birth != date_of_birth:
        # same message for both cases: don't reveal whether an IC exists
        raise ValidationError({"ic_no": "No matching patient record found. Check IC and date of birth."})
    if patient.user_id is not None:
        raise ValidationError({"ic_no": "This patient record already has an online account."})

    patient.user = user
    patient.save(update_fields=["user"])
    return patient

# ---------------------------------------------------------------------------
# Patient signs up online (User + Patient in one transaction)
# ---------------------------------------------------------------------------
@transaction.atomic
def register_patient_account(*, username, email, password, ic_no, full_name,
                             gender, date_of_birth, phone, address=None):
    """
    Create a PATIENT login account and its Patient record.

    - New IC            -> create User + new Patient
    - IC of a walk-in   -> create User + link the existing Patient (DOB must match)
    - IC already linked -> error

    Returns (user, patient). If anything fails, nothing is saved.
    """
    username = (username or "").strip()
    email = (email or "").strip().lower()
    ic_no = normalize_ic(ic_no)
    errors = {}

    # Account checks
    if not username:
        errors["username"] = "Username is required."
    elif User.objects.filter(username__iexact=username).exists():
        errors["username"] = "This username is taken."
    if not email:
        errors["email"] = "Email is required."
    elif User.objects.filter(email__iexact=email).exists():
        errors["email"] = "An account with this email already exists."
    try:
        validate_password(password)
    except ValidationError as e:
        errors["password"] = e.messages

    existing = Patient.objects.select_for_update().filter(ic_no=ic_no).first()
    if existing and existing.user_id is not None:
        errors["ic_no"] = "This IC already has an online account. Please log in instead."

    if errors:
        raise ValidationError(errors)

    # New patient: validate all patient fields BEFORE creating the user
    if existing is None:
        validate_patient_data(
            ic_no=ic_no, full_name=normalize_name(full_name),
            gender=(gender or "").strip().upper(), date_of_birth=date_of_birth,
            phone=normalize_phone(phone), email=email,
        )

    user = User.objects.create_user(
        username=username, email=email, password=password, role="PATIENT",
    )

    if existing is not None:
        # Returning walk-in patient: link instead of creating a duplicate
        patient = link_patient_to_user(user=user, ic_no=ic_no, date_of_birth=date_of_birth)
    else:
        try:
            patient = Patient.objects.create(
                ic_no=ic_no,
                full_name=normalize_name(full_name),
                gender=(gender or "").strip().upper(),
                date_of_birth=date_of_birth,
                phone=normalize_phone(phone),
                email=email,
                address=(address or "").strip() or None,
                user=user,
            )
        except IntegrityError:
            raise ValidationError({"ic_no": "A patient with this IC is already registered."})

    return user, patient

# ---------------------------------------------------------------------------
# List and visits (nurse, doctor, admin)
# ---------------------------------------------------------------------------
def list_patients(*, viewed_by):
    """All patients by name (the page paginates). Staff only."""
    if not viewed_by.is_authenticated or viewed_by.role not in STAFF_ROLES:
        raise PermissionDenied("Only clinic staff can view patients.")
    return Patient.objects.order_by("full_name")


def last_visit_dates(patient_ids):
    """{patient_id: date of the latest completed visit} for a page of patients."""
    from queueing.models import QueueTicket

    rows = (
        QueueTicket.objects.filter(patient_id__in=list(patient_ids), status="COMPLETED")
        .values("patient_id")
        .annotate(last=Max("queue_date"))
    )
    return {r["patient_id"]: r["last"] for r in rows}


def patient_visits(patient):
    """The patient's consultations, newest first, with doctor, medicines and MC."""
    from consultation.models import Consultation

    return (
        Consultation.objects.filter(ticket__patient=patient)
        .select_related("doctor", "ticket")
        .prefetch_related("prescription_items__medicine", "medical_certificate")
        .order_by("-created_at")
    )


# ---------------------------------------------------------------------------
# Delete (admin) - blocked once the patient has any queue ticket
# ---------------------------------------------------------------------------
def can_delete_patient(patient) -> bool:
    return not patient.queue_tickets.exists()


@transaction.atomic
def delete_patient(*, deleted_by, patient_id) -> None:
    """Delete a patient registered by mistake.

    Blocked if the patient has any queue ticket (visits lead to consultations,
    prescriptions and bills). A linked PATIENT login is deleted too, since it is
    useless without the record; the person can simply register again.
    """
    if not deleted_by.is_authenticated or deleted_by.role != "ADMIN":
        raise PermissionDenied("Only admins can delete patients.")
    try:
        patient = Patient.objects.select_for_update().get(pk=patient_id)
    except Patient.DoesNotExist:
        raise ValidationError("Patient not found.")
    if not can_delete_patient(patient):
        raise ValidationError("This patient has visits and cannot be deleted.")

    user = patient.user
    patient.delete()
    if user is not None and user.role == "PATIENT":
        user.delete()


# ---------------------------------------------------------------------------
# Patient changes their email (login email + patient record), verified by
# their password and a 6-digit code sent to the new address
# ---------------------------------------------------------------------------
EMAIL_CODE_MINUTES = 10
EMAIL_CODE_MAX_TRIES = 5


def _hash_code(code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"email-code:{code}".encode(), hashlib.sha256).hexdigest()


def start_email_change(*, user, new_email, password) -> dict:
    """Check the request and email a 6-digit code to the NEW address.

    Returns the pending change to keep in the session (the code itself is only
    stored as a hash). Raises ValidationError with field errors.
    """
    from django.core.validators import validate_email

    new_email = (new_email or "").strip().lower()
    errors = {}
    try:
        validate_email(new_email)
    except ValidationError:
        errors["new_email"] = "Enter a valid email address."
    else:
        if new_email == (user.email or "").lower():
            errors["new_email"] = "This is already your email."
        elif User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
            errors["new_email"] = "An account with this email already exists."
    if not user.check_password(password or ""):
        errors["password"] = "Incorrect password."
    if errors:
        raise ValidationError(errors)

    code = f"{secrets.randbelow(10**6):06d}"
    send_mail(
        subject="Your ClinicMQ verification code",
        message=(
            f"Your verification code is {code}\n\n"
            f"Enter it in ClinicMQ to change your email to {new_email}. "
            f"It expires in {EMAIL_CODE_MINUTES} minutes.\n\n"
            "If you didn't ask for this, you can ignore this email.\n\n"
            "ClinicMQ · Clinic Management System with Online Queue"
        ),
        from_email=None,
        recipient_list=[new_email],
    )
    expires = timezone.now() + timedelta(minutes=EMAIL_CODE_MINUTES)
    return {"email": new_email, "code_hash": _hash_code(code), "expires": expires.timestamp(), "tries": 0}


@transaction.atomic
def confirm_email_change(*, user, pending, code) -> str:
    """Apply the change if the code is right. Returns the new email.

    `pending` is the dict from start_email_change(); a wrong code increases
    pending["tries"] in place, so the caller must save it back to the session.
    """
    if not pending:
        raise ValidationError("There is no email change waiting. Please start again.")
    if timezone.now().timestamp() > pending["expires"]:
        raise ValidationError("This code has expired. Please request a new one.")
    if pending["tries"] >= EMAIL_CODE_MAX_TRIES:
        raise ValidationError("Too many wrong codes. Please request a new one.")
    if not hmac.compare_digest(_hash_code((code or "").strip()), pending["code_hash"]):
        pending["tries"] += 1
        left = EMAIL_CODE_MAX_TRIES - pending["tries"]
        raise ValidationError(f"Incorrect code. {left} {'try' if left == 1 else 'tries'} left." if left
                              else "Too many wrong codes. Please request a new one.")

    new_email = pending["email"]
    if User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
        raise ValidationError("An account with this email already exists.")

    user.email = new_email
    user.username = new_email  # patients log in with their email, stored as username too
    try:
        user.save(update_fields=["email", "username"])
    except IntegrityError:
        raise ValidationError("An account with this email already exists.")
    Patient.objects.filter(user=user).update(email=new_email)
    return new_email
