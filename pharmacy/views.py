"""
pharmacy/views.py
Medicine Inventory screens (UI.md §5.7). Views stay thin: they call pharmacy/services.py.

All staff can view the inventory; only nurses add, edit, restock and dispense; only admins delete.
"""

from django.shortcuts import render

from accounts.decorators import role_required

from . import services as ps

VIEW_ROLES = ("NURSE", "DOCTOR", "ADMIN")


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
