from django import forms

MC_DAY_CHOICES = [(n, f"{n} day{'s' if n > 1 else ''}") for n in range(1, 8)]


class ConsultationForm(forms.Form):
    """Section 1 (notes and fee) and section 3 (MC). Prescription rows are read
    separately (medicine[], dosage[], quantity[]) so the page can add and remove rows."""

    symptoms = forms.CharField(label="Symptoms", widget=forms.Textarea(attrs={"rows": 3}))
    diagnosis = forms.CharField(label="Diagnosis", max_length=255)
    notes = forms.CharField(label="Notes", required=False, widget=forms.Textarea(attrs={"rows": 3}),
                            help_text="Advice, follow-up, anything else.")
    consult_fee = forms.DecimalField(
        label="Consult fee (RM)", max_digits=8, decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "placeholder": "30.00", "inputmode": "decimal"}),
    )

    issue_mc = forms.BooleanField(label="Issue medical certificate (MC)", required=False)
    mc_start_date = forms.DateField(label="Start date", required=False,
                                    widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    mc_days = forms.TypedChoiceField(label="Days", choices=MC_DAY_CHOICES, coerce=int, required=False)
    mc_reason = forms.CharField(label="Reason", max_length=255, required=False,
                                widget=forms.TextInput(attrs={"placeholder": "e.g. Viral fever"}))

    def mc(self):
        """The MC as the service expects it, or None if 'Issue MC' isn't ticked."""
        if not self.cleaned_data.get("issue_mc"):
            return None
        return {"start_date": self.cleaned_data.get("mc_start_date"),
                "days": self.cleaned_data.get("mc_days"),
                "reason": self.cleaned_data.get("mc_reason")}

    def fields_for_service(self):
        d = self.cleaned_data
        return {"symptoms": d["symptoms"], "diagnosis": d["diagnosis"], "notes": d.get("notes"),
                "consult_fee": d["consult_fee"]}


def rows_from_post(post):
    """Prescription rows from the form: [{"medicine": "3", "dosage": "...", "quantity": "20"}, ...].
    Completely empty rows are ignored."""
    rows = []
    for med, dosage, qty in zip(post.getlist("medicine"), post.getlist("dosage"), post.getlist("quantity")):
        if med or dosage.strip() or qty.strip():
            rows.append({"medicine": med, "dosage": dosage, "quantity": qty})
    return rows
