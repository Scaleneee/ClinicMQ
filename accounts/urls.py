from django.urls import path

from . import staff_views, views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("register/", views.register, name="register"),
    path("dashboard/", views.dashboard, name="dashboard"),
    # Staff & Schedule
    path("staff/", staff_views.staff_list, name="staff_list"),
    path("staff/add/", staff_views.staff_create, name="staff_create"),
    path("staff/<int:pk>/edit/", staff_views.staff_edit, name="staff_edit"),
    path("staff/<int:pk>/deactivate/", staff_views.staff_deactivate, name="staff_deactivate"),
    path("staff/<int:pk>/reactivate/", staff_views.staff_reactivate, name="staff_reactivate"),
    path("roster/", staff_views.roster, name="roster"),
]
