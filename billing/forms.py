"""Forms for the Billing screens. Formats are checked here; the rules
(cash >= total, method required, reason required, ...) are checked by billing/services.py."""

from django import forms

from .models import Bill


class PaymentForm(forms.Form):
    method = forms.ChoiceField(label="Payment method", choices=Bill.PaymentMethod.choices,
                               widget=forms.RadioSelect,
                               error_messages={"required": "Choose how the patient paid."})
    amount_received = forms.CharField(label="Amount received (RM)", required=False,
                                      widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0.00",
                                                                    "autocomplete": "off"}))


class VoidForm(forms.Form):
    reason = forms.CharField(label="Reason", max_length=255,
                             widget=forms.Textarea(attrs={"rows": 3, "placeholder": "e.g. Billed to the wrong patient"}),
                             error_messages={"required": "Enter the reason for voiding this bill."})
