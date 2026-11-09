from django import forms
from .models import SatelliteImage

class SatelliteImageForm(forms.ModelForm):
    class Meta:
        model = SatelliteImage
        fields = ['imagery_type', 'acquisition_date', 'file']
        widgets = {
            'acquisition_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'imagery_type': forms.Select(attrs={'class': 'form-select'}),
            'file': forms.FileInput(attrs={'class': 'form-control', 'accept': '.tif,.tiff'}),
        }