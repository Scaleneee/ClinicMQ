from django.urls import path

from . import views

app_name = "queueing"

urlpatterns = [
    # Patient
    path("get-number/", views.get_number, name="get_number"),
    path("my-queue/", views.my_queue, name="my_queue"),
    path("my-queue/live/", views.my_queue_live, name="my_queue_live"),
    path("my-queue/cancel/", views.cancel_my_ticket, name="cancel_my_ticket"),
    path("check-in/<str:code>/", views.qr_check_in, name="qr_check_in"),
    # Public status page (QR on a printed walk-in ticket)
    path("t/<uuid:token>/", views.ticket_status, name="ticket_status"),
    path("t/<uuid:token>/live/", views.ticket_status_live, name="ticket_status_live"),
]
