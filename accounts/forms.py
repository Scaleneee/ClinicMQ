from django import forms
from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    """Email + password, with "Remember me". Checked by accounts.backends.EmailBackend."""

    username = forms.CharField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email", "placeholder": "you@example.com"}),
    )
    remember_me = forms.BooleanField(label="Remember me", required=False, initial=True)

    error_messages = {
        "invalid_login": "Incorrect email or password. Please try again.",
        "inactive": "This account has been deactivated. Please contact the clinic.",
    }
