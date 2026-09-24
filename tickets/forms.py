from django import forms
from .models import Ticket


class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ["category", "title", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}
