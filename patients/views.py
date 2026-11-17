"""
patients/views.py
Patient module screens (UI.md §5.4). Views stay thin: they call patients/services.py.
"""

from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from accounts.decorators import role_required
from queueing.services import get_todays_ticket

from . import services as ps
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
