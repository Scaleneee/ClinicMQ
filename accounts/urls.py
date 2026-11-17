from django.urls import path

from . import staff_views, views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("register/", views.register, name="register"),
    path("dashboard/", views.dashboard, name="dashboard"),
    # Staff & Schedule
    path("staff/", staff_views.staff_list, name="staff_list"),
]
