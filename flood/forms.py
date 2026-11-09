# flood/forms.py — English labels
import json

from django import forms
from .models import DrainageOutlet, FloodEvent


def normalize_geojson(data):
    if not isinstance(data, dict):
        raise forms.ValidationError('Not a valid GeoJSON object.')
    t = data.get('type')
    if t == 'FeatureCollection':
        feats = data.get('features') or []
    elif t == 'Feature':
        feats = [data]
    elif t in ('Polygon', 'MultiPolygon'):
        feats = [{'type': 'Feature', 'properties': {}, 'geometry': data}]
    else:
        raise forms.ValidationError('GeoJSON must be FeatureCollection, Feature, Polygon or MultiPolygon.')
    kept = []
    for f in feats:
        g = (f or {}).get('geometry') or {}
        if g.get('type') in ('Polygon', 'MultiPolygon') and g.get('coordinates'):
            kept.append({'type': 'Feature', 'properties': f.get('properties') or {}, 'geometry': g})
    if not kept:
        raise forms.ValidationError('No Polygon/MultiPolygon found in the GeoJSON file.')
    return {'type': 'FeatureCollection', 'features': kept}


class FloodEventForm(forms.ModelForm):
    reference_geojson = forms.FileField(
        required=False, label='Reference flood extent (GeoJSON, lon/lat)',
        help_text='Optional. Ground-truth polygon(s) used for IoU / Precision / Recall / F1.')
    clear_reference = forms.BooleanField(required=False, label='Remove current reference map')

    class Meta:
        model = FloodEvent
        fields = ['event_name', 'date_occurred', 'description', 'actual_flood_time', 'actual_magnitude_pixels']
        labels = {
            'event_name': 'Event name',
            'date_occurred': 'Date occurred',
            'description': 'Description',
            'actual_flood_time': 'Actual flood time (on-site / records)',
            'actual_magnitude_pixels': 'Actual flood magnitude (pixels)',
        }
        widgets = {
            'date_occurred': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'description': forms.Textarea(attrs={'rows': 2}),
            'actual_flood_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['actual_flood_time'].input_formats = [
            '%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S']
        for name, f in self.fields.items():
            css = 'form-check-input' if isinstance(f.widget, forms.CheckboxInput) else 'form-control'
            f.widget.attrs['class'] = css
        self.fields['reference_geojson'].widget.attrs['accept'] = '.geojson,.json'

    def clean_reference_geojson(self):
        f = self.cleaned_data.get('reference_geojson')
        if not f:
            return None
        try:
            data = json.loads(f.read().decode('utf-8-sig'))
        except (ValueError, UnicodeDecodeError):
            raise forms.ValidationError('Could not read the file as JSON.')
        return normalize_geojson(data)

    def save(self, commit=True):
        inst = super().save(commit=False)
        ref = self.cleaned_data.get('reference_geojson')
        if ref is not None:
            inst.actual_extent_geojson = ref
        elif self.cleaned_data.get('clear_reference'):
            inst.actual_extent_geojson = None
        if commit:
            inst.save()
        return inst


class OutletForm(forms.ModelForm):
    class Meta:
        model = DrainageOutlet
        fields = ['name', 'latitude', 'longitude', 'elevation']
        labels = {'elevation': 'Elevation (m)'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs['class'] = 'form-control'
        self.fields['latitude'].widget.attrs['step'] = 'any'
        self.fields['longitude'].widget.attrs['step'] = 'any'
        self.fields['elevation'].widget.attrs['step'] = 'any'

    def clean_latitude(self):
        v = self.cleaned_data['latitude']
        if not -90 <= v <= 90:
            raise forms.ValidationError('Latitude must be between -90 and 90.')
        return v

    def clean_longitude(self):
        v = self.cleaned_data['longitude']
        if not -180 <= v <= 180:
            raise forms.ValidationError('Longitude must be between -180 and 180.')
        return v