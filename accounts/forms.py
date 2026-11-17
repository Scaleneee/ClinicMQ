from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone

from patients.services import IC_PATTERN, PHONE_PATTERN, normalize_ic, normalize_phone


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

    Checks formats here so the page can show field errors straight away.
    Uniqueness, the IC cross-checks and linking to an existing walk-in record
    are done by patients.services.register_patient_account() in the view.
    """

    ic_no = forms.CharField(
        label="IC number",
        max_length=20,
        help_text="Format: 900101-14-5678 (dashes optional)",
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
        choices=[("", "Select"), ("M", "Male"), ("F", "Female")],
    )
    date_of_birth = forms.DateField(
        label="Date of birth",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    phone = forms.CharField(
        label="Phone",
        max_length=20,
        help_text="Format: 012-3456789 (dash optional)",
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

    def clean_ic_no(self):
        ic_no = normalize_ic(self.cleaned_data["ic_no"])
        if not IC_PATTERN.match(ic_no):
            raise forms.ValidationError("Enter the IC number as ######-##-####.")
        return ic_no

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if not PHONE_PATTERN.match(phone):
            raise forms.ValidationError("Enter the phone number as 01X-XXXXXXX.")
        return phone

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
