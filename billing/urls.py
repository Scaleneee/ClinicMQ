from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.bill_list, name="bill_list"),
    path("<int:pk>/", views.bill_detail, name="bill_detail"),
    path("new/<int:consultation_id>/", views.bill_create, name="bill_create"),
    path("<int:pk>/pay/", views.bill_pay, name="bill_pay"),
    path("<int:pk>/void/", views.bill_void, name="bill_void"),
    path("<int:pk>/receipt.pdf", views.receipt_pdf, name="receipt_pdf"),
]
