"""Forms for the Staff & Schedule screens. Formats are checked here; the rules
(unique email, one doctor per session, ...) are checked by accounts/services.py."""

from django import forms

from .models import Session

ROLE_CHOICES = [("", "Select"), ("DOCTOR", "Doctor"), ("NURSE", "Nurse"), ("ADMIN", "Admin")]


class StaffForm(forms.Form):
    full_name = forms.CharField(label="Full name", max_length=100,
                                help_text='Without "Dr." – it is added for doctors.')
    email = forms.EmailField(label="Email", max_length=254, help_text="They log in with this email.")
    role = forms.ChoiceField(label="Role", choices=ROLE_CHOICES)
    phone = forms.CharField(
        label="Phone", max_length=20, help_text="Format: 012-3456789 (dash optional)",
        widget=forms.TextInput(attrs={"placeholder": "012-3456789", "inputmode": "tel"}),
    )
    specialty = forms.CharField(label="Specialty", max_length=100, required=False,
                                widget=forms.TextInput(attrs={"placeholder": "e.g. General practice"}))
    password1 = forms.CharField(
        label="Temporary password", strip=False,
        help_text="Give it to them; they can change it with Forgot password.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.editing = editing
        if editing:  # passwords aren't changed here
            del self.fields["password1"]
            del self.fields["password2"]

    def clean(self):
        cleaned = super().clean()
        if not self.editing:
            p1, p2 = cleaned.get("password1"), cleaned.get("password2")
            if p1 and p2 and p1 != p2:
                self.add_error("password2", "The two passwords do not match.")
        return cleaned


class ShiftForm(forms.Form):
    staff = forms.ChoiceField(label="Staff")
    shift_date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    session = forms.ChoiceField(label="Session", choices=[("", "Select")] + list(Session.choices))

    def __init__(self, *args, staff_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["staff"].choices = [("", "Select")] + list(staff_choices)
