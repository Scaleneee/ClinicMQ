from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("admin/", admin.site.urls),
    # accounts.urls first so its login/register views win over Django's defaults.
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("django.contrib.auth.urls")),  # logout, password reset
    path("patients/", include("patients.urls")),
    path("queue/", include("queueing.urls")),
    path("consultation/", include("consultation.urls")),
    path("pharmacy/", include("pharmacy.urls")),
    path("billing/", include("billing.urls")),
]
