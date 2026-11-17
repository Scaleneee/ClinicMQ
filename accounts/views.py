from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import LoginForm, RegisterForm


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        if not form.cleaned_data.get("remember_me"):
            # Log out when the browser closes.
            self.request.session.set_expiry(0)
        return super().form_valid(form)


def register(request):
    """Patient self-registration page (UI only for now)."""
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # TODO (logic): create the account, e.g.
        #   from patients.services import register_patient_account
        #   data = form.cleaned_data
        #   user, patient = register_patient_account(
        #       username=data["email"],  # email is also stored as the username
        #       email=data["email"], password=data["password1"],
        #       ic_no=data["ic_no"], full_name=data["full_name"], gender=data["gender"],
        #       date_of_birth=data["date_of_birth"], phone=data["phone"],
        #   )
        #   On ValidationError: copy e.message_dict onto the form with form.add_error().
        #   On success: login(request, user) and redirect("dashboard").
        messages.info(request, "Your details look good. Account creation isn't switched on yet.")

    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    return render(request, "accounts/dashboard.html")
