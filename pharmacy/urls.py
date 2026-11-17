from django.urls import path

from . import views

app_name = "pharmacy"

urlpatterns = [
    path("", views.medicine_list, name="medicine_list"),
    path("new/", views.medicine_create, name="medicine_create"),
    path("<int:pk>/edit/", views.medicine_edit, name="medicine_edit"),
    path("<int:pk>/restock/", views.medicine_restock, name="medicine_restock"),
    path("<int:pk>/delete/", views.medicine_delete, name="medicine_delete"),
    path("dispense/", views.dispense_list, name="dispense_list"),
    path("dispense/<int:consultation_id>/", views.dispense_detail, name="dispense_detail"),
]
