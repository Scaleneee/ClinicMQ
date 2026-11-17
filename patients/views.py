"""
patients/views.py
Patient module screens (UI.md §5.4). Views stay thin: they call patients/services.py.
"""

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from queueing.services import get_todays_ticket

from . import services as ps
from .forms import EmailChangeForm, EmailCodeForm, PatientForm, ProfileForm
from .models import Patient

STAFF_ROLES = ("NURSE", "DOCTOR", "ADMIN")
DESK_ROLES = ("NURSE", "ADMIN")  # add, edit, issue numbers
PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# Retrieve: list / search, detail (nurse, doctor, admin)
# ---------------------------------------------------------------------------
@role_required(*STAFF_ROLES)
def patient_list(request):
    query = request.GET.get("q", "").strip()
    page_obj = None
    if query:
        patients = list(ps.search_patients(searched_by=request.user, query=query, limit=50))
    else:
        page_obj = Paginator(ps.list_patients(viewed_by=request.user), PAGE_SIZE).get_page(request.GET.get("page"))
        patients = list(page_obj)

    last = ps.last_visit_dates(p.pk for p in patients)
    for p in patients:
        p.last_visit = last.get(p.pk)

    return render(request, "patients/patient_list.html", {
        "patients": patients,
        "page_obj": page_obj,
        "query": query,
        "can_add": request.user.role in DESK_ROLES,
    })


@role_required(*STAFF_ROLES)
def patient_detail(request, pk):
    patient = get_object_or_404(Patient.objects.select_related("user"), pk=pk)
    return render(request, "patients/patient_detail.html", {
        "patient": patient,
        "ticket": get_todays_ticket(patient),
        "visits": ps.patient_visits(patient),
        "can_edit": request.user.role in DESK_ROLES,
        "can_delete": request.user.role == "ADMIN",
        "deletable": ps.can_delete_patient(patient),
    })


def _add_service_errors(form, error):
    """Show a ValidationError from a service under the matching form fields."""
    if hasattr(error, "error_dict"):
        for field, field_messages in error.message_dict.items():
            target = field if field in form.fields else None
            for message in field_messages:
                form.add_error(target, message)
    else:
        for message in error.messages:
            form.add_error(None, message)


# ---------------------------------------------------------------------------
# Create / update (nurse, admin), delete (admin)
# ---------------------------------------------------------------------------
@role_required(*DESK_ROLES)
def patient_create(request):
    back_to_walk_in = (request.GET.get("next") or request.POST.get("next")) == "walk_in"
    form = PatientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            patient = ps.register_patient(registered_by=request.user, **form.cleaned_data)
        except ValidationError as e:
            _add_service_errors(form, e)
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"{patient.full_name.title()} was registered.")
            if back_to_walk_in:
                return redirect(f"{reverse('queueing:walk_in')}?patient={patient.pk}")
            return redirect("patients:detail", pk=patient.pk)

    return render(request, "patients/patient_form.html", {
        "form": form, "patient": None, "back_to_walk_in": back_to_walk_in,
    })


@role_required(*DESK_ROLES)
def patient_edit(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    linked = patient.user_id is not None
    initial = {f: getattr(patient, f) for f in ("ic_no", "full_name", "gender", "date_of_birth",
                                                "phone", "email", "address")}
    initial["full_name"] = patient.full_name.title()
    form = PatientForm(request.POST or None, initial=initial, linked_account=linked)

    if request.method == "POST" and form.is_valid():
        changes = {f: v for f, v in form.cleaned_data.items() if not (f == "email" and linked)}
        try:
            ps.update_patient(updated_by=request.user, patient_id=patient.pk, **changes)
        except ValidationError as e:
            _add_service_errors(form, e)
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Patient details saved.")
            return redirect("patients:detail", pk=patient.pk)

    return render(request, "patients/patient_form.html", {"form": form, "patient": patient})


@role_required("ADMIN")
def patient_delete(request, pk):
    patient = get_object_or_404(Patient.objects.select_related("user"), pk=pk)
    if request.method == "POST":
        name = patient.full_name.title()
        try:
            ps.delete_patient(deleted_by=request.user, patient_id=patient.pk)
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, " ".join(getattr(e, "messages", [str(e)])))
            return redirect("patients:delete", pk=patient.pk)
        messages.success(request, f"{name} was deleted.")
        return redirect("patients:list")

    return render(request, "patients/patient_confirm_delete.html", {
        "patient": patient,
        "deletable": ps.can_delete_patient(patient),
    })


# ---------------------------------------------------------------------------
# Patient: My profile (phone, address) and a verified email change
# ---------------------------------------------------------------------------
EMAIL_CHANGE_KEY = "pending_email_change"


def _own_patient(request):
    try:
        return request.user.patient
    except ObjectDoesNotExist:
        return None


@role_required("PATIENT")
def my_profile(request):
    patient = _own_patient(request)
    form = ProfileForm(request.POST or None, initial={"phone": patient.phone, "address": patient.address}
                       if patient else None)
    if patient and request.method == "POST" and form.is_valid():
        try:
            ps.update_patient(updated_by=request.user, patient_id=patient.pk, **form.cleaned_data)
        except ValidationError as e:
            _add_service_errors(form, e)
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Your details were saved.")
            return redirect("patients:my_profile")

    return render(request, "patients/my_profile.html", {
        "patient": patient,
        "form": form,
        "pending": request.session.get(EMAIL_CHANGE_KEY),
    })


@role_required("PATIENT")
def change_email(request):
    """Step 1: new email + current password -> a code is emailed to the new address."""
    form = EmailChangeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            pending = ps.start_email_change(user=request.user, **form.cleaned_data)
        except ValidationError as e:
            _add_service_errors(form, e)
        else:
            request.session[EMAIL_CHANGE_KEY] = pending
            messages.info(request, f"We sent a 6-digit code to {pending['email']}.")
            return redirect("patients:verify_email")
    return render(request, "patients/change_email.html", {"form": form})


@role_required("PATIENT")
def verify_email(request):
    """Step 2: enter the code -> login email and patient email both change."""
    pending = request.session.get(EMAIL_CHANGE_KEY)
    if not pending:
        return redirect("patients:change_email")

    form = EmailCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            new_email = ps.confirm_email_change(user=request.user, pending=pending, code=form.cleaned_data["code"])
        except ValidationError as e:
            for message in e.messages:
                form.add_error("code", message)
            request.session[EMAIL_CHANGE_KEY] = pending  # keeps the tries count
        else:
            request.session.pop(EMAIL_CHANGE_KEY, None)
            messages.success(request, f"Your email is now {new_email}. Use it to log in next time.")
            return redirect("patients:my_profile")

    return render(request, "patients/verify_email.html", {"form": form, "email": pending["email"]})


@require_POST
@role_required("PATIENT")
def cancel_email_change(request):
    request.session.pop(EMAIL_CHANGE_KEY, None)
    messages.info(request, "Email change cancelled.")
    return redirect("patients:my_profile")
