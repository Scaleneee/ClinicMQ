from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.validators import RegexValidator
from django.utils import timezone

from patients.models import IC_REGEX, PHONE_REGEX


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


class RegisterForm(forms.Form):
    """Patient self-registration (UI.md §5.1).

    Checks formats only, so the page can show field errors. Uniqueness and
    linking to an existing walk-in record are done by
    patients.services.register_patient_account() when the logic is wired up.
    """

    ic_no = forms.CharField(
        label="IC number",
        max_length=14,
        validators=[RegexValidator(IC_REGEX, "Enter the IC number as ######-##-####.")],
        help_text="Format: 900101-14-5678",
        widget=forms.TextInput(attrs={"placeholder": "900101-14-5678", "inputmode": "numeric", "autofocus": True}),
    )
    full_name = forms.CharField(
        label="Full name",
        max_length=100,
        help_text="As shown on your IC.",
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    gender = forms.ChoiceField(
        label="Gender",
        choices=[("M", "Male"), ("F", "Female")],
        widget=forms.RadioSelect,
    )
    date_of_birth = forms.DateField(
        label="Date of birth",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    phone = forms.CharField(
        label="Phone",
        max_length=15,
        validators=[RegexValidator(PHONE_REGEX, "Enter the phone number as 01X-XXXXXXX.")],
        help_text="Format: 012-3456789",
        widget=forms.TextInput(attrs={"placeholder": "012-3456789", "inputmode": "tel", "autocomplete": "tel"}),
    )
    email = forms.EmailField(
        label="Email",
        max_length=254,
        help_text="You will log in with this email.",
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}),
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        help_text="At least 8 characters, not only numbers.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_date_of_birth(self):
        dob = self.cleaned_data["date_of_birth"]
        if dob > timezone.localdate():
            raise forms.ValidationError("Date of birth cannot be in the future.")
        return dob

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        return cleaned
