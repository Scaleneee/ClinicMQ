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
    path("roster/shifts/add/", staff_views.shift_create, name="shift_create"),
    path("roster/shifts/<int:pk>/edit/", staff_views.shift_edit, name="shift_edit"),
    path("roster/shifts/<int:pk>/remove/", staff_views.shift_delete, name="shift_delete"),
]
