from django.urls import path

from . import views

app_name = "consultation"

urlpatterns = [
    path("", views.consultation_list, name="list"),
    path("<int:pk>/", views.consultation_detail, name="detail"),
]
