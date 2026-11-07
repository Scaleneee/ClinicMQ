from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Shift, Staff, User


@admin.register(User)
class ClinicUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_active", "date_joined")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (("Clinic", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Clinic", {"fields": ("email", "role")}),)


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ("full_name", "role", "phone", "specialty", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("full_name", "user__username")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("shift_date", "session", "staff")
    list_filter = ("session", "shift_date")
