from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .forms import LoginForm


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        if not form.cleaned_data.get("remember_me"):
            # Log out when the browser closes.
            self.request.session.set_expiry(0)
        return super().form_valid(form)


@login_required
def dashboard(request):
    return render(request, "accounts/dashboard.html")
