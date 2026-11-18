"""Data migration: before Staff.role and Staff.is_active are dropped (next migration),
copy them onto the linked User wherever they differ, so nothing is lost."""

from django.db import migrations


def copy_to_user(apps, schema_editor):
    Staff = apps.get_model("accounts", "Staff")
    for staff in Staff.objects.select_related("user"):
        user = staff.user
        changed = []
        if user.role != staff.role:
            user.role = staff.role
            changed.append("role")
        if user.is_active != staff.is_active:
            user.is_active = staff.is_active
            changed.append("is_active")
        if changed:
            user.save(update_fields=changed)


def copy_back(apps, schema_editor):
    """Undo: the restored Staff columns take their values from the User again."""
    Staff = apps.get_model("accounts", "Staff")
    for staff in Staff.objects.select_related("user"):
        staff.role = staff.user.role
        staff.is_active = staff.user.is_active
        staff.save(update_fields=["role", "is_active"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_remove_user_first_name_remove_user_last_name"),
    ]

    operations = [
        migrations.RunPython(copy_to_user, copy_back),
    ]
