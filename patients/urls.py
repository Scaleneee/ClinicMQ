from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    # Staff
    path("", views.patient_list, name="list"),
    path("<int:pk>/", views.patient_detail, name="detail"),
    path("add/", views.patient_create, name="create"),
    path("<int:pk>/edit/", views.patient_edit, name="edit"),
    path("<int:pk>/delete/", views.patient_delete, name="delete"),
    # Patient
    path("me/", views.my_profile, name="my_profile"),
    path("me/email/", views.change_email, name="change_email"),
    path("me/email/verify/", views.verify_email, name="verify_email"),
    path("me/email/cancel/", views.cancel_email_change, name="cancel_email_change"),
]
