import csv
import io
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Max, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render

from .models import WeatherRecord

REQUIRED = ['station_name', 'date_recorded', 'rainfall_mm']
OPTIONAL = ['temperature_c', 'humidity_percent']


def _parse_date(s):
    s = s.strip()
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%d-%b-%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f'Invalid date "{s}" (gamitin ang YYYY-MM-DD)')


def _float_or_none(v):
    v = (v or '').strip()
    return float(v) if v != '' else None


@login_required
def weather_records_view(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        f = request.FILES['csv_file']
        try:
            text = f.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(text))
            headers = [h.strip() for h in (reader.fieldnames or [])]
            missing = [c for c in REQUIRED if c not in headers]
            if missing:
                raise ValueError('Kulang na columns: ' + ', '.join(missing))
            created = updated = 0
            errors = []
            for i, row in enumerate(reader, start=2):
                try:
                    row = {k.strip(): v for k, v in row.items() if k}
                    obj, was_created = WeatherRecord.objects.update_or_create(
                        station_name=row['station_name'].strip(),
                        date_recorded=_parse_date(row['date_recorded']),
                        defaults={
                            'rainfall_mm': float(row['rainfall_mm']),
                            'temperature_c': _float_or_none(row.get('temperature_c')),
                            'humidity_percent': _float_or_none(row.get('humidity_percent')),
                        })
                    created += was_created
                    updated += (not was_created)
                except Exception as exc:
                    errors.append(f'Row {i}: {exc}')
            messages.success(request, f'Weather CSV imported: {created} bago, {updated} na-update.')
            if errors:
                messages.warning(request, f'{len(errors)} row(s) ang nilaktawan. ' + ' | '.join(errors[:5]))
        except Exception as exc:
            messages.error(request, f'Hindi ma-import ang CSV: {exc}')
        return redirect('weather_records')

    records = WeatherRecord.objects.order_by('-date_recorded', 'station_name')[:200]
    agg = WeatherRecord.objects.aggregate(total=Sum('rainfall_mm'), peak=Max('rainfall_mm'), avg=Avg('rainfall_mm'))
    return render(request, 'weather/records.html', {
        'records': records, 'total_count': WeatherRecord.objects.count(), 'agg': agg,
    })


@login_required
def weather_template_csv(request):
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="pagasa_weather_template.csv"'
    w = csv.writer(resp)
    w.writerow(REQUIRED + OPTIONAL)
    w.writerow(['PAGASA Science Garden', '2024-07-24', '152.4', '25.8', '95'])
    w.writerow(['PAGASA Science Garden', '2024-07-25', '88.0', '26.4', '93'])
    return resp
