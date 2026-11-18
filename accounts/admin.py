from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Shift, Staff, User


@admin.register(User)
class ClinicUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_active", "date_joined")
    list_filter = ("role", "is_active")
    search_fields = ("username", "email")
    ordering = ("username",)
    # Django's default has a "Personal info" section with first/last name, which this User doesn't have.
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Account", {"fields": ("email", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (("Account", {"fields": ("email", "role")}),)


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    # Role and active status are stored on the linked User.
    list_display = ("full_name", "role", "phone", "specialty", "is_active")
    list_filter = ("user__role", "user__is_active")
    list_select_related = ("user",)
    search_fields = ("full_name", "user__username")

    @admin.display(description="Role", ordering="user__role")
    def role(self, obj):
        return obj.user.get_role_display()

    @admin.display(description="Active", boolean=True, ordering="user__is_active")
    def is_active(self, obj):
        return obj.user.is_active


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("shift_date", "session", "staff")
    list_filter = ("session", "shift_date")
