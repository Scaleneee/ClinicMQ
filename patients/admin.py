from django.contrib import admin

from .models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("full_name", "ic_no", "gender", "phone", "created_at")
    list_filter = ("gender",)
    search_fields = ("full_name", "ic_no", "phone")
