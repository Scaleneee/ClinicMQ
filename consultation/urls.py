from django.urls import path

from . import views

app_name = "consultation"

urlpatterns = [
    path("", views.consultation_list, name="list"),
    path("<int:pk>/", views.consultation_detail, name="detail"),
    path("new/<int:ticket_id>/", views.consultation_create, name="create"),
    path("<int:pk>/edit/", views.consultation_edit, name="edit"),
    path("<int:pk>/delete/", views.consultation_delete, name="delete"),
]
