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
    # Nurse
    path("board/", views.board, name="board"),
    path("board/live/", views.board_live, name="board_live"),
    path("board/<int:ticket_id>/check-in/", views.board_check_in, name="board_check_in"),
    path("board/<int:ticket_id>/cancel/", views.board_cancel, name="board_cancel"),
    path("walk-in/", views.walk_in, name="walk_in"),
    path("walk-in/<int:ticket_id>/ticket/", views.walkin_ticket, name="walkin_ticket"),
    # Doctor console
    path("console/", views.console, name="console"),
    path("console/live/", views.console_live, name="console_live"),
    path("console/<str:action>/", views.console_action, name="console_action"),
]
