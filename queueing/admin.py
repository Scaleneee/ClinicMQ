from django.contrib import admin

from .models import ClinicSetting, QueueTicket


@admin.register(QueueTicket)
class QueueTicketAdmin(admin.ModelAdmin):
    list_display = ("queue_no", "queue_date", "session", "patient", "status", "source", "doctor")
    list_filter = ("queue_date", "session", "status", "source")
    search_fields = ("patient__full_name", "patient__ic_no")
    readonly_fields = ("public_token", "issued_at")


@admin.register(ClinicSetting)
class ClinicSettingAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not ClinicSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
