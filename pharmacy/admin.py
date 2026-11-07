from django.contrib import admin

from .models import Medicine

# PrescriptionItem uses a composite primary key, which the Django admin
# does not support, so it is managed through the app's own views instead.


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "unit", "unit_price", "quantity", "reorder_level", "expiry_date", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name",)
