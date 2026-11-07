from django.contrib import admin

from .models import Bill, BillItem


class BillItemInline(admin.TabularInline):
    model = BillItem
    extra = 0


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ("bill_no", "consultation", "status", "payment_method", "created_at", "paid_at")
    list_filter = ("status", "payment_method")
    search_fields = ("bill_no",)
    inlines = [BillItemInline]
