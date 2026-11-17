from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.bill_list, name="bill_list"),
    path("<int:pk>/", views.bill_detail, name="bill_detail"),
]
