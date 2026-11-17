from django import forms

from .services import IC_PATTERN, PHONE_PATTERN, normalize_ic, normalize_phone


class PatientForm(forms.Form):
    """Add / edit a patient (nurse, admin). Formats are checked here; IC uniqueness and
    the IC cross-checks (date of birth, gender) are done by the patient services."""

    ic_no = forms.CharField(
        label="IC number", max_length=20,
        help_text="Format: 900101-14-5678 (dashes optional)",
        widget=forms.TextInput(attrs={"placeholder": "900101-14-5678", "inputmode": "numeric"}),
    )
    full_name = forms.CharField(label="Full name", max_length=100, help_text="As shown on the IC.")
    gender = forms.ChoiceField(label="Gender", choices=[("", "Select"), ("M", "Male"), ("F", "Female")])
    date_of_birth = forms.DateField(
        label="Date of birth", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    phone = forms.CharField(
        label="Phone", max_length=20, help_text="Format: 012-3456789 (dash optional)",
        widget=forms.TextInput(attrs={"placeholder": "012-3456789", "inputmode": "tel"}),
    )
    email = forms.EmailField(label="Email", required=False, max_length=254)
    address = forms.CharField(
        label="Address", required=False, max_length=255, widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, linked_account=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.linked_account = linked_account
        if linked_account:
            # The login email: only the patient changes it (My profile, with a code).
            self.fields["email"].disabled = True
            self.fields["email"].help_text = "This is the patient's login email. They change it in My profile."

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


class ProfileForm(forms.Form):
    """My profile (patient): only phone and address here; email has its own verified flow."""

    phone = forms.CharField(
        label="Phone", max_length=20, help_text="Format: 012-3456789 (dash optional)",
        widget=forms.TextInput(attrs={"placeholder": "012-3456789", "inputmode": "tel", "autocomplete": "tel"}),
    )
    address = forms.CharField(
        label="Address", required=False, max_length=255, widget=forms.Textarea(attrs={"rows": 2}),
    )

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if not PHONE_PATTERN.match(phone):
            raise forms.ValidationError("Enter the phone number as 01X-XXXXXXX.")
        return phone


class EmailChangeForm(forms.Form):
    new_email = forms.EmailField(
        label="New email", max_length=254,
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}),
    )
    password = forms.CharField(
        label="Current password", strip=False,
        help_text="To make sure it's really you.",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class EmailCodeForm(forms.Form):
    code = forms.CharField(
        label="Verification code", max_length=6, min_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code",
                                      "placeholder": "6-digit code", "autofocus": True}),
    )
