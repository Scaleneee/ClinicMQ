from django.urls import path

from . import views

app_name = "pharmacy"

urlpatterns = [
    path("", views.medicine_list, name="medicine_list"),
    path("new/", views.medicine_create, name="medicine_create"),
    path("<int:pk>/edit/", views.medicine_edit, name="medicine_edit"),
]
