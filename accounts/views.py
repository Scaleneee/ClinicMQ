from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone

from patients.services import register_patient_account
from queueing.services import get_todays_ticket, people_ahead

from .forms import LoginForm, RegisterForm

# Service error keys -> RegisterForm field names.
# The email is also stored as the username, so username errors belong on the email field.
SERVICE_FIELD_MAP = {"username": "email", "password": "password1"}


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        if not form.cleaned_data.get("remember_me"):
            # Log out when the browser closes.
            self.request.session.set_expiry(0)
        return super().form_valid(form)


def _add_service_errors(form, error):
    """Show a ValidationError from the service under the matching form fields."""
    if not hasattr(error, "error_dict"):
        for message in error.messages:
            form.add_error(None, message)
        return

    shown = set()
    for key, field_messages in error.message_dict.items():
        field = SERVICE_FIELD_MAP.get(key, key)
        if field not in form.fields:
            field = None
        for message in field_messages:
            if (field, message) in shown:
                continue
            # "username taken" and "email exists" mean the same thing here; show one.
            if key == "username" and "email" in error.message_dict:
                continue
            shown.add((field, message))
            form.add_error(field, message)


def register(request):
    """Patient self-registration: creates the login account and its Patient record."""
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            user, patient = register_patient_account(
                username=data["email"],  # email is also stored as the username
                email=data["email"],
                password=data["password1"],
                ic_no=data["ic_no"],
                full_name=data["full_name"],
                gender=data["gender"],
                date_of_birth=data["date_of_birth"],
                phone=data["phone"],
            )
        except ValidationError as e:
            _add_service_errors(form, e)
        else:
            login(request, user)
            messages.success(request, f"Welcome, {patient.full_name}. Your account is ready.")
            return redirect("dashboard")

    return render(request, "registration/register.html", {"form": form})


def _greeting():
    hour = timezone.localtime().hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _patient_home(request):
    """Patient home (UI.md §5.2): greeting, today's ticket or an empty state, quick links."""
    try:
        patient = request.user.patient
    except ObjectDoesNotExist:
        patient = None  # PATIENT account without a Patient record

    ticket = get_todays_ticket(patient)
    return render(request, "accounts/patient_home.html", {
        "greeting": _greeting(),
        # Names are stored in capitals (as on the IC); show them in title case.
        "name": patient.full_name.title() if patient else request.user.get_full_name(),
        "patient": patient,
        "ticket": ticket,
        "ahead": people_ahead(ticket) if ticket else None,
    })


@login_required
def dashboard(request):
    """Home after login. Each role gets its own page (UI.md §5.2)."""
    from . import dashboards

    role = request.user.role
    if role == request.user.Role.PATIENT:
        return _patient_home(request)
    if role == request.user.Role.NURSE:
        return dashboards.nurse_dashboard(request)
    # Doctor and admin dashboards: generic page for now.
    return render(request, "accounts/dashboard.html")
