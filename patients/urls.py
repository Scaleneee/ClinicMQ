from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    # Staff
    path("", views.patient_list, name="list"),
    path("<int:pk>/", views.patient_detail, name="detail"),
]
