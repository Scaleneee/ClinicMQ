"""
pharmacy/views.py
Medicine Inventory screens (UI.md §5.7). Views stay thin: they call pharmacy/services.py.

All staff can view the inventory; only nurses add, edit, restock and dispense; only admins delete.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required

from . import services as ps
from .forms import MedicineForm
from .models import Medicine

VIEW_ROLES = ("NURSE", "DOCTOR", "ADMIN")


def _add_service_errors(form, error):
    """Show a ValidationError from a service under the matching form fields."""
    if hasattr(error, "error_dict"):
        for field, field_messages in error.message_dict.items():
            for message in field_messages:
                form.add_error(field if field in form.fields else None, message)
    else:
        for message in error.messages:
            form.add_error(None, message)


def _active_medicine(pk):
    return get_object_or_404(Medicine, pk=pk, is_active=True)


# ---------------------------------------------------------------------------
# Retrieve: medicine list
# ---------------------------------------------------------------------------
@role_required(*VIEW_ROLES)
def medicine_list(request):
    status = request.GET.get("filter", "all")
    if status not in {key for key, _ in ps.FILTERS}:
        status = "all"
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()

    medicines = list(ps.list_medicines(viewed_by=request.user, query=query, category=category, status=status))
    for m in medicines:
        m.badges = ps.stock_badges(m)
    counts = ps.filter_counts(query=query, category=category)
    pills = [{"key": key, "label": label, "count": counts[key], "active": key == status} for key, label in ps.FILTERS]

    return render(request, "pharmacy/medicine_list.html", {
        "medicines": medicines,
        "pills": pills,
        "status": status,
        "query": query,
        "category": category,
        "categories": ps.categories(),
        "is_nurse": request.user.role == "NURSE",
        "is_admin": request.user.role == "ADMIN",
    })


# ---------------------------------------------------------------------------
# Create / update (nurse)
# ---------------------------------------------------------------------------
def _form_page(request, form, medicine=None):
    return render(request, "pharmacy/medicine_form.html", {
        "form": form,
        "medicine": medicine,
        "categories": ps.categories(),
        "units": ["tablets", "capsules", "bottles", "boxes", "tubes", "sachets", "strips"],
    })


@role_required("NURSE")
def medicine_create(request):
    form = MedicineForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            m = ps.create_medicine(created_by=request.user, **form.cleaned_data)
        except ValidationError as e:
            _add_service_errors(form, e)
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"{m.name} was added.")
            return redirect("pharmacy:medicine_list")
    return _form_page(request, form)


@role_required("NURSE")
def medicine_edit(request, pk):
    medicine = _active_medicine(pk)
    initial = {f: getattr(medicine, f) for f in MedicineForm.base_fields}
    form = MedicineForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            m = ps.update_medicine(updated_by=request.user, medicine_id=medicine.pk, **form.cleaned_data)
        except ValidationError as e:
            _add_service_errors(form, e)
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"{m.name} was updated.")
            return redirect("pharmacy:medicine_list")
    return _form_page(request, form, medicine)
