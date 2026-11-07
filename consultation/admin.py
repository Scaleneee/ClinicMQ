from django.contrib import admin

from .models import Consultation, MedicalCertificate


@admin.register(Consultation)
class ConsultationAdmin(admin.ModelAdmin):
    list_display = ("consultation_id", "ticket", "doctor", "diagnosis", "consult_fee", "created_at")
    search_fields = ("diagnosis", "ticket__patient__full_name")


@admin.register(MedicalCertificate)
class MedicalCertificateAdmin(admin.ModelAdmin):
    list_display = ("mc_no", "consultation", "start_date", "days")
    search_fields = ("mc_no",)
