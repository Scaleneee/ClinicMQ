"""Forms for the Medicine Inventory screens. Formats are checked here; the rules
(unique name, price > 0, future expiry, ...) are checked by pharmacy/services.py."""

from django import forms


class MedicineForm(forms.Form):
    name = forms.CharField(label="Name", max_length=100,
                           widget=forms.TextInput(attrs={"placeholder": "e.g. Paracetamol 500mg"}),
                           help_text="Include the strength, e.g. 500mg or 100ml.")
    category = forms.CharField(label="Category", max_length=50,
                               widget=forms.TextInput(attrs={"placeholder": "e.g. Analgesic", "list": "category-list"}))
    unit = forms.CharField(label="Unit", max_length=20,
                           widget=forms.TextInput(attrs={"placeholder": "e.g. tablets", "list": "unit-list"}),
                           help_text="How it is counted and sold.")
    unit_price = forms.DecimalField(label="Unit price (RM)", max_digits=8, decimal_places=2,
                                    widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01",
                                                                    "inputmode": "decimal", "placeholder": "0.50"}))
    quantity = forms.IntegerField(label="Quantity in stock", widget=forms.NumberInput(attrs={"min": "0"}))
    reorder_level = forms.IntegerField(label="Reorder level", initial=10,
                                       widget=forms.NumberInput(attrs={"min": "0"}),
                                       help_text="Shows Low stock at or below this number.")
    expiry_date = forms.DateField(label="Expiry date", widget=forms.DateInput(attrs={"type": "date"}))
